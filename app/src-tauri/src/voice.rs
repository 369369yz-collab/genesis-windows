//! Voice STT backend — whisper sidecar implementing [`SidecarBackend`].
//!
//! Local-only speech-to-text. The whisper binary + model ship in the app
//! resources dir (`resources/whisper/`). Everything is honest:
//! - engine or model missing → commands return `installed: false` with the
//!   exact missing paths; the frontend shows a Persian notice, never fake text.
//! - whisper-cli is a one-shot transcriber, so `spawn` = runnable probe and
//!   `shutdown` = no-op; the supervisor's idle policy simply forgets the probe.
//!
//! Audio path: the frontend captures 16 kHz mono PCM via Web Audio, encodes
//! WAV in JS, and sends the bytes here. No network, no cloud.

use crate::sidecar_supervisor::{SidecarBackend, SidecarKind};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};

/// Relative to the Tauri resource dir.
const WHISPER_BIN: &str = "whisper/whisper-cli";
const WHISPER_MODEL: &str = "whisper/ggml-small.bin";
/// Hard RAM budget for one whisper-cli run (W1 OOM policy).
const WHISPER_MAX_RAM: u64 = 1_500_000_000;

pub struct WhisperBackend {
    resource_dir: PathBuf,
    /// Last successful probe time; `None` = never probed or probe failed.
    probed_ok: bool,
}

impl WhisperBackend {
    pub fn new(resource_dir: PathBuf) -> Self {
        Self { resource_dir, probed_ok: false }
    }

    pub fn bin_path(&self) -> PathBuf {
        let mut p = self.resource_dir.join(WHISPER_BIN);
        if cfg!(windows) {
            p.set_extension("exe");
        }
        p
    }

    pub fn model_path(&self) -> PathBuf {
        self.resource_dir.join(WHISPER_MODEL)
    }

    /// Exact list of missing engine files (empty = installed).
    pub fn missing_files(&self) -> Vec<String> {
        let mut v = Vec::new();
        if !self.bin_path().exists() {
            v.push(self.bin_path().to_string_lossy().into_owned());
        }
        if !self.model_path().exists() {
            v.push(self.model_path().to_string_lossy().into_owned());
        }
        v
    }

    pub fn installed(&self) -> bool {
        self.missing_files().is_empty()
    }

    /// Run whisper-cli on a 16 kHz mono WAV file; returns the transcript.
    pub fn transcribe_wav(&self, wav: &Path) -> Result<String, String> {
        let missing = self.missing_files();
        if !missing.is_empty() {
            return Err(format!("موتور ویس نصب نیست: {}", missing.join(", ")));
        }
        let out = Command::new(self.bin_path())
            .arg("--model")
            .arg(self.model_path())
            .arg("--language")
            .arg("fa")
            .arg("--no-prints")
            .arg("--output-txt")
            .arg("-f")
            .arg(wav)
            .output()
            .map_err(|e| format!("whisper spawn failed: {e}"))?;
        if !out.status.success() {
            return Err(format!(
                "whisper failed: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            ));
        }
        let txt_path = wav.with_extension("txt");
        let text = std::fs::read_to_string(&txt_path)
            .map_err(|e| format!("whisper output unreadable: {e}"))?;
        let _ = std::fs::remove_file(&txt_path);
        Ok(text.trim().to_string())
    }
}

impl SidecarBackend for WhisperBackend {
    fn kind(&self) -> SidecarKind {
        SidecarKind::Whisper
    }

    fn spawn(&mut self) -> Result<(), String> {
        let missing = self.missing_files();
        if !missing.is_empty() {
            self.probed_ok = false;
            return Err(format!("whisper not installed, missing: {}", missing.join(", ")));
        }
        // Runnable probe: --version must exit 0.
        let ok = Command::new(self.bin_path())
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        self.probed_ok = ok;
        if ok {
            Ok(())
        } else {
            Err("whisper binary present but not runnable".to_string())
        }
    }

    fn shutdown(&mut self) -> Result<(), String> {
        // One-shot binary: nothing persistent to stop.
        self.probed_ok = false;
        Ok(())
    }

    fn is_alive(&self) -> bool {
        self.probed_ok && self.installed()
    }

    fn max_ram_bytes(&self) -> u64 {
        WHISPER_MAX_RAM
    }
}

/// [`SidecarBackend`] adapter sharing the managed [`WhisperBackend`].
/// Lets the supervisor enforce idle/OOM policy on the same engine instance
/// the Tauri commands use — one engine, one truth.
pub struct WhisperSlot {
    inner: Arc<Mutex<WhisperBackend>>,
}

impl WhisperSlot {
    pub fn new(inner: Arc<Mutex<WhisperBackend>>) -> Self {
        Self { inner }
    }
}

impl SidecarBackend for WhisperSlot {
    fn kind(&self) -> SidecarKind {
        SidecarKind::Whisper
    }
    fn spawn(&mut self) -> Result<(), String> {
        self.inner.lock().unwrap().spawn()
    }
    fn shutdown(&mut self) -> Result<(), String> {
        self.inner.lock().unwrap().shutdown()
    }
    fn is_alive(&self) -> bool {
        self.inner.lock().unwrap().is_alive()
    }
    fn max_ram_bytes(&self) -> u64 {
        WHISPER_MAX_RAM
    }
}

/// Frontend command: honest voice-engine status.
#[tauri::command]
pub fn voice_status(
    backend: tauri::State<Arc<Mutex<WhisperBackend>>>,
) -> serde_json::Value {
    let b = backend.lock().unwrap();
    serde_json::json!({
        "installed": b.installed(),
        "missing": b.missing_files(),
        "alive": b.is_alive(),
    })
}

/// Frontend command: transcribe 16 kHz mono WAV bytes (local only).
#[tauri::command]
pub fn voice_transcribe(
    app: AppHandle,
    backend: tauri::State<Arc<Mutex<WhisperBackend>>>,
    wav_bytes: Vec<u8>,
) -> Result<String, String> {
    if wav_bytes.len() < 44 || wav_bytes.len() > 25_000_000 {
        return Err("bad wav payload".to_string());
    }
    let tmp = std::env::temp_dir().join(format!("genesis-voice-{}.wav", std::process::id()));
    std::fs::write(&tmp, &wav_bytes).map_err(|e| format!("temp write failed: {e}"))?;
    let text = backend.lock().unwrap().transcribe_wav(&tmp);
    let _ = std::fs::remove_file(&tmp);
    let _ = app;
    text
}
