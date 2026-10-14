//! Brain launcher — starts the local model server + brain service at boot.
//!
//! GENESIS Full ships everything inside the installer (Tauri resources):
//!   resources/llama-server.exe          (llama.cpp Vulkan build, pinned)
//!   resources/models/Qwen3-8B-Q4_K_M.gguf (pinned SHA-256, re-verified here)
//!   resources/python/python.exe         (portable CPython, no system Python)
//!   resources/brain/genesis_onecode/service.py (the brain HTTP service)
//!   resources/chromium/chrome.exe       (portable Chromium for the governor)
//!
//! Boot order: verify model hash (chunked) -> llama-server (GPU offload) ->
//! wait for /health -> brain service (port 17369). Children are killed on
//! app exit. All localhost-only.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};

const LLAMA_PORT: u16 = 8080;
const BRAIN_PORT: u16 = 17369;
const MODEL_NAME: &str = "Qwen3-8B-Q4_K_M.gguf";
/// Pinned SHA-256 of the model (genesis_onecode/brain/pins.json, single source of truth).
const MODEL_SHA256: &str =
    "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785";
/// Full GPU offload: 8B Q4_K_M (~4.9 GiB) fits the RTX 5070 12 GB comfortably.
const N_GPU_LAYERS: &str = "99";

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct BrainStatus {
    pub llama_running: bool,
    pub brain_running: bool,
    pub model_path: String,
    pub model_verified: bool,
    pub chromium_path: String,
    pub chromium_present: bool,
    pub last_error: String,
}

pub struct BrainLauncher {
    status: Arc<Mutex<BrainStatus>>,
    llama_child: Option<Child>,
    brain_child: Option<Child>,
}

impl BrainLauncher {
    pub fn new() -> Self {
        Self {
            status: Arc::new(Mutex::new(BrainStatus::default())),
            llama_child: None,
            brain_child: None,
        }
    }

    pub fn status_handle(&self) -> Arc<Mutex<BrainStatus>> {
        self.status.clone()
    }

    fn set_error(&self, e: &str) {
        if let Ok(mut s) = self.status.lock() {
            s.last_error = e.to_string();
        }
        eprintln!("[brain] {e}");
    }

    /// Reassemble the model from its NSIS-safe 512MB parts (shipped as
    /// `Qwen3-8B-Q4_K_M.gguf.partNN` resources — makensis cannot mmap a
    /// single 5GB file). Reassembly happens once, into the installed
    /// resources dir; the pinned SHA-256 check afterwards proves the
    /// model is byte-identical.
    fn reassemble_model(model: &Path) -> Result<(), String> {
        let dir = model.parent().ok_or("model has no parent dir")?;
        let stem = model.file_name().ok_or("model has no file name")?
            .to_string_lossy().to_string();
        let mut parts: Vec<PathBuf> = std::fs::read_dir(dir)
            .map_err(|e| format!("cannot list models dir: {e}"))?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy().starts_with(&format!("{stem}.part")))
                    .unwrap_or(false)
            })
            .collect();
        if parts.is_empty() {
            return Err(format!(
                "model missing and no .part files found in {}", dir.display()));
        }
        parts.sort();
        eprintln!("[brain] reassembling model from {} parts...", parts.len());
        let tmp = dir.join(format!("{stem}.assembling"));
        let mut out = std::fs::File::create(&tmp)
            .map_err(|e| format!("cannot create assembly file: {e}"))?;
        for part in &parts {
            let mut f = std::fs::File::open(part)
                .map_err(|e| format!("cannot open {}: {e}", part.display()))?;
            std::io::copy(&mut f, &mut out)
                .map_err(|e| format!("copy failed for {}: {e}", part.display()))?;
        }
        drop(out);
        std::fs::rename(&tmp, model)
            .map_err(|e| format!("cannot finalize assembled model: {e}"))?;
        eprintln!("[brain] model reassembled");
        Ok(())
    }

    /// Chunked SHA-256 re-verification at every boot (W14 boot rule).
    fn verify_model(path: &Path) -> Result<(), String> {
        let mut file = std::fs::File::open(path)
            .map_err(|e| format!("cannot open model: {e}"))?;
        let mut hasher = Sha256::new();
        let mut buf = [0u8; 8 * 1024 * 1024];
        loop {
            let n = file
                .read(&mut buf)
                .map_err(|e| format!("model read error: {e}"))?;
            if n == 0 {
                break;
            }
            hasher.update(&buf[..n]);
        }
        let hex = hex::encode(hasher.finalize());
        if hex != MODEL_SHA256 {
            return Err(format!(
                "model SHA-256 MISMATCH — refusing to load (expected {MODEL_SHA256}, got {hex})"
            ));
        }
        Ok(())
    }

    fn wait_for_health(url: &str, timeout: Duration) -> bool {
        let start = Instant::now();
        while start.elapsed() < timeout {
            if let Ok(resp) = ureq::get(url).timeout(Duration::from_secs(3)).call() {
                if resp.status() == 200 {
                    return true;
                }
            }
            std::thread::sleep(Duration::from_secs(2));
        }
        false
    }

    /// Boot the whole brain. Called once from setup() on a background thread.
    pub fn boot(&mut self, app: &AppHandle) {
        let res_dir: PathBuf = match app.path().resource_dir() {
            Ok(d) => d,
            Err(e) => {
                self.set_error(&format!("resource_dir() failed: {e}"));
                return;
            }
        };
        let llama_exe = res_dir.join("llama-server.exe");
        let model = res_dir.join("models").join(MODEL_NAME);
        let python_exe = res_dir.join("python").join("python.exe");
        let service_py = res_dir
            .join("brain")
            .join("genesis_onecode")
            .join("service.py");
        let chrome_exe = res_dir.join("chromium").join("chrome.exe");

        {
            let mut s = self.status.lock().unwrap();
            s.model_path = model.to_string_lossy().to_string();
            s.chromium_path = chrome_exe.to_string_lossy().to_string();
            s.chromium_present = chrome_exe.exists();
        }

        for (label, p) in [
            ("llama-server.exe", &llama_exe),
            ("python.exe", &python_exe),
            ("service.py", &service_py),
        ] {
            if !p.exists() {
                self.set_error(&format!("missing payload: {label} at {}", p.display()));
                return;
            }
        }
        // The model ships as .partNN files (NSIS-safe); reassemble on first boot.
        if !model.exists() {
            if let Err(e) = Self::reassemble_model(&model) {
                self.set_error(&e);
                return;
            }
        }

        // 1. Re-verify the model hash at boot (W14).
        match Self::verify_model(&model) {
            Ok(()) => {
                self.status.lock().unwrap().model_verified = true;
                eprintln!("[brain] model SHA-256 verified");
            }
            Err(e) => {
                self.set_error(&e);
                return;
            }
        }

        // 2. llama-server with full GPU offload.
        let mut llama = match Command::new(&llama_exe)
            .args([
                "-m", &model.to_string_lossy(),
                "--port", &LLAMA_PORT.to_string(),
                "--n-gpu-layers", N_GPU_LAYERS,
                "--host", "127.0.0.1",
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                self.set_error(&format!("llama-server spawn failed: {e}"));
                return;
            }
        };
        // If it dies instantly, surface the failure instead of hanging.
        std::thread::sleep(Duration::from_secs(3));
        if let Ok(Some(code)) = llama.try_wait() {
            self.set_error(&format!("llama-server exited immediately (code {code})"));
            return;
        }
        if !Self::wait_for_health(
            &format!("http://127.0.0.1:{LLAMA_PORT}/health"),
            Duration::from_secs(120),
        ) {
            self.set_error("llama-server never became healthy");
            let _ = llama.kill();
            return;
        }
        self.status.lock().unwrap().llama_running = true;
        eprintln!("[brain] llama-server healthy on 127.0.0.1:{LLAMA_PORT}");
        self.llama_child = Some(llama);

        // 3. Brain service on the bundled portable Python.
        let brain = Command::new(&python_exe)
            .arg(&service_py)
            .env("GENESIS_BRAIN_PORT", BRAIN_PORT.to_string())
            .env(
                "GENESIS_LLAMA_URL",
                format!("http://127.0.0.1:{LLAMA_PORT}"),
            )
            .env("GENESIS_CHROMIUM_EXE", chrome_exe.to_string_lossy().to_string())
            .env("PYTHONUTF8", "1")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        match brain {
            Ok(mut c) => {
                std::thread::sleep(Duration::from_secs(2));
                if let Ok(Some(code)) = c.try_wait() {
                    self.set_error(&format!("brain service exited immediately (code {code})"));
                    return;
                }
                if Self::wait_for_health(
                    &format!("http://127.0.0.1:{BRAIN_PORT}/health"),
                    Duration::from_secs(60),
                ) {
                    self.status.lock().unwrap().brain_running = true;
                    eprintln!("[brain] brain service healthy on 127.0.0.1:{BRAIN_PORT}");
                    self.brain_child = Some(c);
                } else {
                    self.set_error("brain service never became healthy");
                    let _ = c.kill();
                }
            }
            Err(e) => self.set_error(&format!("brain service spawn failed: {e}")),
        }
    }
}

impl Drop for BrainLauncher {
    fn drop(&mut self) {
        if let Some(c) = self.brain_child.as_mut() {
            let _ = c.kill();
        }
        if let Some(c) = self.llama_child.as_mut() {
            let _ = c.kill();
        }
    }
}

/// Frontend command: brain boot status (formula §2 row 11 diagnostics).
#[tauri::command]
pub fn brain_status(state: tauri::State<Arc<Mutex<BrainStatus>>>) -> BrainStatus {
    state.lock().map(|s| s.clone()).unwrap_or_default()
}
