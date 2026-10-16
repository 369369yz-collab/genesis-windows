//! Brain launcher — starts the local model server + brain service at boot.
//!
//! GENESIS Full ships these inside the installer (Tauri resources):
//!   resources/llama-server-vulkan.exe   (llama.cpp Vulkan build, pinned)
//!   resources/llama-server-cpu.exe      (llama.cpp CPU build, pinned)
//!   resources/python/python.exe         (portable CPython, no system Python)
//!   resources/brain/genesis_onecode/    (the brain; incl. model_manifest.json)
//!   resources/chromium/chrome.exe       (portable Chromium for the governor)
//!
//! The 5GB model is NOT in the installer (makensis is 32-bit and cannot
//! build it). On first boot the launcher downloads the pinned release
//! parts into the app-local data dir, verifies every part's SHA-256,
//! assembles, and re-verifies the full pinned SHA-256 (W14). After that
//! the model is local and the app is fully standalone.
//!
//! Boot order: payloads present -> model ensure (download/verify) ->
//! llama-server (GPU offload) -> wait /health -> brain service (17369).
//! Children are killed on app exit. All localhost-only.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};

const LLAMA_PORT: u16 = 8080;
const BRAIN_PORT: u16 = 17369;
/// Pinned SHA-256 of the model (genesis_onecode/brain/pins.json).
const MODEL_SHA256: &str =
    "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785";
/// Full GPU offload: 8B Q4_K_M (~4.9 GiB) fits the RTX 5070 12 GB comfortably.
/// This is the DEFAULT for --n-gpu-layers; the GENESIS_N_GPU_LAYERS env var
/// overrides it at runtime (0 = CPU-only, for GPU-less machines/CI runners).
const N_GPU_LAYERS: &str = "99";
/// llama-server spawn attempts before the boot thread gives up (fail-closed).
/// HUMANFLOW-RED 2026-10-15 (run 38759814918): on a shared 2-vCPU GitHub
/// runner, CPU-loading a 4.68GB Qwen3-8B model needs longer than any single
/// short health window — one stalled attempt must not doom the whole boot.
const LLAMA_SPAWN_ATTEMPTS: u32 = 2;
/// Per-attempt budget for llama-server /health to return 200. The old 180s
/// window killed a healthy-but-slow CPU load on CI runners (same RED).
const LLAMA_HEALTH_BUDGET: Duration = Duration::from_secs(600);

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct BrainStatus {
    pub llama_running: bool,
    pub brain_running: bool,
    pub model_path: String,
    pub model_verified: bool,
    /// "idle" | "downloading" | "assembling" | "verifying" | "ready" | "error"
    pub model_state: String,
    pub model_downloaded_bytes: u64,
    pub model_total_bytes: u64,
    pub chromium_path: String,
    pub chromium_present: bool,
    pub last_error: String,
}

pub struct BrainLauncher {
    status: Arc<Mutex<BrainStatus>>,
    llama_child: Option<Child>,
    brain_child: Option<Child>,
    /// <app_local_data_dir>/boot.log — every boot stage is appended here so
    /// a silent brain failure is diagnosable on any machine (the GUI gives
    /// no hint; windows_subsystem hides stderr). Written from the boot
    /// thread only.
    boot_log: PathBuf,
}

impl BrainLauncher {
    pub fn new() -> Self {
        let mut s = BrainStatus::default();
        s.model_state = "idle".to_string();
        Self {
            status: Arc::new(Mutex::new(s)),
            llama_child: None,
            brain_child: None,
            boot_log: PathBuf::new(),
        }
    }

    pub fn status_handle(&self) -> Arc<Mutex<BrainStatus>> {
        self.status.clone()
    }

    /// Append one timestamped line to boot.log (best-effort; never fails boot).
    fn blog(&self, msg: &str) {
        if self.boot_log.as_os_str().is_empty() {
            return;
        }
        use std::io::Write;
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.boot_log)
        {
            let _ = writeln!(f, "[{ts}] {msg}");
        }
        eprintln!("[brain] {msg}");
    }

    fn set_error(&self, e: &str) {
        if let Ok(mut s) = self.status.lock() {
            s.last_error = e.to_string();
            s.model_state = "error".to_string();
        }
        self.blog(&format!("ERROR: {e}"));
    }

    fn set_model_state(&self, state: &str, downloaded: u64, total: u64) {
        if let Ok(mut s) = self.status.lock() {
            s.model_state = state.to_string();
            s.model_downloaded_bytes = downloaded;
            s.model_total_bytes = total;
        }
    }

    /// Chunked SHA-256 of a file.
    fn sha256_file(path: &Path) -> Result<String, String> {
        let mut file =
            std::fs::File::open(path).map_err(|e| format!("cannot open {}: {e}", path.display()))?;
        let mut hasher = Sha256::new();
        // HEAP buffer, not stack: this runs on a spawned thread with a 2 MiB
        // stack; an 8 MiB stack array = instant 0xC00000FD (2026-10-15).
        let mut buf = vec![0u8; 8 * 1024 * 1024];
        loop {
            let n = file
                .read(&mut buf)
                .map_err(|e| format!("read error {}: {e}", path.display()))?;
            if n == 0 {
                break;
            }
            hasher.update(&buf[..n]);
        }
        Ok(hex::encode(hasher.finalize()))
    }

    /// W14: the assembled model hash must match the pin, every boot.
    fn verify_model(path: &Path) -> Result<(), String> {
        let hex = Self::sha256_file(path)?;
        if hex != MODEL_SHA256 {
            return Err(format!(
                "model SHA-256 MISMATCH — refusing to load (expected {MODEL_SHA256}, got {hex})"
            ));
        }
        Ok(())
    }

    /// Download one release part (streamed to disk), verifying its hash.
    fn download_part(&self, url: &str, dest: &Path, expected_sha: &str, expected_size: u64) -> Result<(), String> {
        if dest.exists() {
            let size = dest.metadata().map(|m| m.len()).unwrap_or(0);
            if size == expected_size {
                if let Ok(h) = Self::sha256_file(dest) {
                    if h == expected_sha {
                        eprintln!("[brain] part cached + verified: {}", dest.display());
                        return Ok(());
                    }
                }
            }
            let _ = std::fs::remove_file(dest);
        }
        eprintln!("[brain] downloading {url}");
        self.blog(&format!("downloading part -> {}", dest.display()));
        let resp = ureq::get(url)
            .timeout(Duration::from_secs(3600))
            .call()
            .map_err(|e| format!("download failed for {url}: {e}"))?;
        if resp.status() != 200 {
            return Err(format!("download {url}: HTTP {}", resp.status()));
        }
        let mut reader = resp.into_reader();
        let mut out = std::fs::File::create(dest)
            .map_err(|e| format!("cannot write {}: {e}", dest.display()))?;
        std::io::copy(&mut reader, &mut out)
            .map_err(|e| format!("write failed {}: {e}", dest.display()))?;
        drop(out);
        let actual = Self::sha256_file(dest)?;
        if actual != expected_sha {
            let _ = std::fs::remove_file(dest);
            return Err(format!("part hash mismatch for {url} — deleted, will retry next boot"));
        }
        Ok(())
    }

    /// Ensure the local model: download parts on first boot, assemble,
    /// verify. Returns the model path.
    fn ensure_model(
        &self,
        manifest_path: &Path,
        models_dir: &Path,
    ) -> Result<PathBuf, String> {
        let raw = std::fs::read_to_string(manifest_path)
            .map_err(|e| format!("cannot read model manifest {}: {e}", manifest_path.display()))?;
        let m: serde_json::Value = serde_json::from_str(&raw)
            .map_err(|e| format!("bad model manifest: {e}"))?;
        let name = m["assembled_name"].as_str().ok_or("manifest: no assembled_name")?;
        let total = m["assembled_size"].as_u64().unwrap_or(0);
        let dest = models_dir.join(name);

        if dest.exists() {
            self.set_model_state("verifying", 0, total);
            Self::verify_model(&dest)?;
            self.set_model_state("ready", total, total);
            self.status.lock().unwrap().model_verified = true;
            eprintln!("[brain] local model verified: {}", dest.display());
            return Ok(dest);
        }

        // First boot: download the parts.
        let parts = m["parts"].as_array().ok_or("manifest: no parts")?;
        if parts.is_empty() {
            return Err("model manifest has no parts — cannot download".to_string());
        }
        self.blog(&format!("manifest ok: {} parts, {} total bytes", parts.len(), total));
        std::fs::create_dir_all(models_dir)
            .map_err(|e| format!("cannot create {}: {e}", models_dir.display()))?;
        let mut downloaded: u64 = 0;
        self.set_model_state("downloading", 0, total);
        let n_parts = parts.len();
        for (i, p) in parts.iter().enumerate() {
            let pname = p["name"].as_str().ok_or("manifest part: no name")?;
            let purl = p["url"].as_str().ok_or("manifest part: no url")?;
            let psha = p["sha256"].as_str().ok_or("manifest part: no sha256")?;
            let psize = p["size"].as_u64().unwrap_or(0);
            let part_path = models_dir.join(pname);
            self.blog(&format!("part {}/{} start: {pname} ({} bytes)", i + 1, n_parts, psize));
            if let Err(e) = self.download_part(purl, &part_path, psha, psize) {
                self.blog(&format!("part {}/{} FAILED: {pname}: {e}", i + 1, n_parts));
                return Err(format!("{pname}: {e}"));
            }
            downloaded += psize;
            self.blog(&format!("part {}/{} done: {pname}", i + 1, n_parts));
            self.set_model_state("downloading", downloaded, total);
        }

        // Assemble in manifest order.
        self.set_model_state("assembling", downloaded, total);
        eprintln!("[brain] assembling model from {} parts...", parts.len());
        let tmp = models_dir.join(format!("{name}.assembling"));
        let mut out = std::fs::File::create(&tmp)
            .map_err(|e| format!("cannot create assembly file: {e}"))?;
        for p in parts {
            let pname = p["name"].as_str().unwrap();
            let part_path = models_dir.join(pname);
            let mut f = std::fs::File::open(&part_path)
                .map_err(|e| format!("cannot open {}: {e}", part_path.display()))?;
            std::io::copy(&mut f, &mut out)
                .map_err(|e| format!("assemble copy failed: {e}"))?;
        }
        drop(out);
        self.set_model_state("verifying", downloaded, total);
        let hex = Self::sha256_file(&tmp)?;
        if hex != MODEL_SHA256 {
            let _ = std::fs::remove_file(&tmp);
            return Err(format!(
                "assembled model SHA-256 MISMATCH (expected {MODEL_SHA256}, got {hex}) — deleted"
            ));
        }
        std::fs::rename(&tmp, &dest).map_err(|e| format!("cannot finalize model: {e}"))?;
        // Parts no longer needed; reclaim ~5GB.
        for p in parts {
            let _ = std::fs::remove_file(models_dir.join(p["name"].as_str().unwrap()));
        }
        self.set_model_state("ready", total, total);
        self.status.lock().unwrap().model_verified = true;
        eprintln!("[brain] model ready: {}", dest.display());
        Ok(dest)
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

    /// Append the last ~30 lines of the llama-server stderr log to boot.log
    /// so a dead spawn attempt always leaves its cause in the CI-captured
    /// forensics (HUMANFLOW-RED 2026-10-15: run 38759814918 died with no
    /// boot.log evidence at all).
    fn dump_llama_stderr_tail(err_log: &Path, boot: &BrainLauncher) {
        let tail: Vec<String> = std::fs::read_to_string(err_log)
            .map(|s| {
                let lines: Vec<&str> = s.lines().collect();
                let n = lines.len().min(30);
                lines[lines.len().saturating_sub(n)..]
                    .iter()
                    .map(|l| l.to_string())
                    .collect()
            })
            .unwrap_or_default();
        if tail.is_empty() {
            boot.blog("llama stderr tail: <empty or unreadable>");
        } else {
            boot.blog("== llama-server.err.log tail ==");
            for l in tail {
                boot.blog(&format!("  {l}"));
            }
            boot.blog("== end tail ==");
        }
    }

    /// Resolve a bundled resource. Tauri v2 keeps the `resources/` prefix
    /// from tauri.conf in the installed layout (`<res>/resources/...`),
    /// while the original code assumed `<res>/...` directly. Try both and
    /// take whichever exists — the payload check below then verifies.
    /// (Found by the windows self-test 2026-10-14: the brain silently never
    /// booted because every payload lookup missed.)
    fn resource(res_dir: &Path, rel: &str) -> PathBuf {
        let direct = res_dir.join(rel);
        if direct.exists() {
            return direct;
        }
        res_dir.join("resources").join(rel)
    }

    /// True when the Vulkan loader exists on this Windows machine.
    /// The Vulkan-linked llama-server cannot run without it (HUMANFLOW-RED
    /// 2026-10-15, run 38769194892: on GPU-less GitHub runners the Vulkan
    /// build hung 600s twice with empty stderr and /health never 200).
    fn vulkan_present() -> bool {
        Path::new(r"C:\Windows\System32\vulkan-1.dll").exists()
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
        let data_dir: PathBuf = match app.path().app_local_data_dir() {
            Ok(d) => d,
            Err(e) => {
                self.set_error(&format!("app_local_data_dir() failed: {e}"));
                return;
            }
        };
        if let Err(e) = std::fs::create_dir_all(&data_dir) {
            self.set_error(&format!("cannot create data dir {}: {e}", data_dir.display()));
            return;
        }
        self.boot_log = data_dir.join("boot.log");
        self.blog(&format!("boot start; res_dir={} data_dir={}",
                           res_dir.display(), data_dir.display()));
        let llama_vulkan_exe = Self::resource(&res_dir, "llama-server-vulkan.exe");
        let llama_cpu_exe = Self::resource(&res_dir, "llama-server-cpu.exe");
        let python_exe = Self::resource(&res_dir, "python/python.exe");
        let brain_dir = Self::resource(&res_dir, "brain/genesis_onecode");
        let service_py = brain_dir.join("service.py");
        // stage_brain.py copies repo genesis_onecode/ -> resources/brain/genesis_onecode/,
        // so the committed manifest (genesis_onecode/brain/model_manifest.json)
        // lands at brain/genesis_onecode/brain/model_manifest.json.
        let manifest = {
            let direct = brain_dir.join("model_manifest.json");
            if direct.exists() {
                direct
            } else {
                brain_dir.join("brain").join("model_manifest.json")
            }
        };
        let chrome_exe = Self::resource(&res_dir, "chromium/chrome.exe");
        let models_dir = data_dir.join("models");

        {
            let mut s = self.status.lock().unwrap();
            s.chromium_path = chrome_exe.to_string_lossy().to_string();
            s.chromium_present = chrome_exe.exists();
        }

        for (label, p) in [
            ("llama-server-vulkan.exe", &llama_vulkan_exe),
            ("llama-server-cpu.exe", &llama_cpu_exe),
            ("python.exe", &python_exe),
            ("service.py", &service_py),
            ("model_manifest.json", &manifest),
        ] {
            if !p.exists() {
                self.set_error(&format!("missing payload: {label} at {}", p.display()));
                return;
            }
            self.blog(&format!("payload ok: {label} at {}", p.display()));
        }

        // 1. Local model: download on first boot, verify every boot (W14).
        let model = match self.ensure_model(&manifest, &models_dir) {
            Ok(m) => m,
            Err(e) => {
                self.set_error(&e);
                return;
            }
        };
        self.status.lock().unwrap().model_path = model.to_string_lossy().to_string();

        // 2. llama-server — dual sidecar. GPU offload layers are configurable
        // via the GENESIS_N_GPU_LAYERS env var (default 99 = full offload).
        // The Vulkan build is preferred where the Vulkan loader exists
        // (GPU machines); the CPU build is preferred elsewhere (CI runners,
        // VMs). HUMANFLOW-RED 2026-10-15 (run 38769194892): the Vulkan
        // build hung 600s twice with empty stderr on a GPU-less runner and
        // /health never 200 — it cannot run without vulkan-1.dll. If the
        // first-choice build fails all its attempts, the other build is
        // tried before boot gives up (fail-closed preserved).
        let gpu_layers = std::env::var("GENESIS_N_GPU_LAYERS")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .unwrap_or_else(|| N_GPU_LAYERS.to_string());
        let vulkan_first = Self::vulkan_present();
        self.blog(&format!("vulkan runtime present: {vulkan_first}"));
        // (flavor label, binary, --n-gpu-layers). The CPU build always gets
        // 0 — it has no GPU backends compiled in.
        let candidates: Vec<(String, PathBuf, String)> = if vulkan_first {
            vec![
                ("vulkan".to_string(), llama_vulkan_exe.clone(), gpu_layers.clone()),
                ("cpu".to_string(), llama_cpu_exe.clone(), "0".to_string()),
            ]
        } else {
            vec![
                ("cpu".to_string(), llama_cpu_exe.clone(), "0".to_string()),
                ("vulkan".to_string(), llama_vulkan_exe.clone(), gpu_layers.clone()),
            ]
        };
        let llama_err_log = data_dir.join("llama-server.err.log");
        let health_url = format!("http://127.0.0.1:{LLAMA_PORT}/health");
        // Retry loop: a slow CPU model load on a shared runner must not doom
        // the whole boot because of one short health window (HUMANFLOW-RED
        // 2026-10-15, run 38759814918: the old single 180s window killed a
        // healthy-but-slow llama-server and /health stayed dark for the
        // entire 30-min driver wait).
        let mut last_err = String::new();
        let mut llama_child: Option<Child> = None;
        for (flavor, llama_exe, n_gpu_layers) in &candidates {
            if llama_child.is_some() {
                break;
            }
            self.blog(&format!(
                "llama-server ({flavor}) spawn plan: {} -m <model> --n-gpu-layers {} (attempts={LLAMA_SPAWN_ATTEMPTS}, health budget={}s)",
                llama_exe.display(),
                n_gpu_layers,
                LLAMA_HEALTH_BUDGET.as_secs(),
            ));
            let mut attempt: u32 = 0;
            while attempt < LLAMA_SPAWN_ATTEMPTS && llama_child.is_none() {
                attempt += 1;
                let llama_err: Stdio = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&llama_err_log)
                    .map(Stdio::from)
                    .unwrap_or_else(|e| {
                        self.blog(&format!(
                            "warn: cannot open {}: {e} — llama stderr discarded",
                            llama_err_log.display()
                        ));
                        Stdio::null()
                    });
                self.blog(&format!("spawning llama-server ({flavor}) (attempt {attempt}/{LLAMA_SPAWN_ATTEMPTS})"));
                let mut llama = match Command::new(llama_exe)
                    .args([
                        "-m",
                        &model.to_string_lossy(),
                        "--port",
                        &LLAMA_PORT.to_string(),
                        "--n-gpu-layers",
                        n_gpu_layers,
                        "--host",
                        "127.0.0.1",
                    ])
                    .stdout(Stdio::null())
                    .stderr(llama_err)
                    .spawn()
                {
                    Ok(c) => c,
                    Err(e) => {
                        last_err = format!("llama-server ({flavor}) spawn failed: {e}");
                        self.blog(&format!("attempt {attempt}: {last_err}"));
                        continue;
                    }
                };
                std::thread::sleep(Duration::from_secs(3));
                if let Ok(Some(code)) = llama.try_wait() {
                    last_err = format!("llama-server ({flavor}) exited immediately (code {code})");
                    self.blog(&format!("attempt {attempt}: {last_err}"));
                    Self::dump_llama_stderr_tail(&llama_err_log, self);
                    continue;
                }
                if Self::wait_for_health(&health_url, LLAMA_HEALTH_BUDGET) {
                    self.status.lock().unwrap().llama_running = true;
                    self.blog(&format!("llama-server ({flavor}) healthy (attempt {attempt})"));
                    eprintln!("[brain] llama-server healthy on 127.0.0.1:{LLAMA_PORT}");
                    llama_child = Some(llama);
                } else {
                    last_err = format!(
                        "llama-server ({flavor}) never became healthy within {}s",
                        LLAMA_HEALTH_BUDGET.as_secs()
                    );
                    self.blog(&format!(
                        "attempt {attempt}: {last_err} — killing and retrying"
                    ));
                    Self::dump_llama_stderr_tail(&llama_err_log, self);
                    let _ = llama.kill();
                    // Give the OS a moment to release port 8080 before the next
                    // spawn, so attempt N+1 cannot die on a bind race with the
                    // dying child.
                    std::thread::sleep(Duration::from_secs(5));
                }
            }
            if llama_child.is_none() {
                self.blog(&format!("{flavor} build failed all attempts — trying next build"));
            }
        }
        let llama = match llama_child {
            Some(c) => c,
            None => {
                self.set_error(&format!(
                    "llama-server failed on all builds ({LLAMA_SPAWN_ATTEMPTS} attempts each): {last_err}"
                ));
                return;
            }
        };
        self.llama_child = Some(llama);

        // 3. Brain service on the bundled portable Python.
        self.blog(&format!("spawning brain service: {} {}", python_exe.display(), service_py.display()));
        let brain = Command::new(&python_exe)
            .arg(&service_py)
            .env("GENESIS_BRAIN_PORT", BRAIN_PORT.to_string())
            .env(
                "GENESIS_LLAMA_URL",
                format!("http://127.0.0.1:{LLAMA_PORT}"),
            )
            .env("GENESIS_CHROMIUM_EXE", chrome_exe.to_string_lossy().to_string())
            .env("GENESIS_DATA_DIR", data_dir.to_string_lossy().to_string())
            .env("PYTHONUTF8", "1")
            // NEVER-AGAIN (exhaust E16 RED 2026-10-16): the bundled CPython
            // bytecode-compiled stdlib imports (http.server) into __pycache__
            // inside the INSTALL dir at runtime; the NSIS uninstaller cannot
            // remove files it never installed, so silent uninstall left one
            // .pyc behind. Zero-tolerance: the app must never write into its
            // own install dir — no .pyc files, ever.
            .env("PYTHONDONTWRITEBYTECODE", "1")
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
                    self.blog("brain service healthy — boot complete");
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
