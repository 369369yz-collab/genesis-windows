//! Real chat inference — GENESIS talks through her own brain.
//!
//! The frontend stub ("حتماً پدر — دارم روش کار می‌کنم.") is gone.
//! This command POSTs the user's message to the bundled brain service
//! (genesis_onecode/service.py, 127.0.0.1:17369), which is the ONE path
//! to the local model. The brain service owns:
//!   - living memory (SQLite): the last exchanges are loaded as context,
//!     and every exchange (user + her reply) is logged — GENESIS remembers;
//!   - the 369 identity prompt (single source of truth lives there);
//!   - inference params (temperature, max tokens).
//! Localhost only — nothing ever leaves the machine.
//!
//! Fail-closed honesty: if the brain isn't ready, the caller gets a
//! Persian error, never a fabricated reply. See
//! `reverse_eng/LLAMACPP_CHAT_DISSECTION.md`.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::Manager;

use crate::brain::BrainStatus;

/// Append one line to chat.log in the app data dir. The human-flow run
/// cannot show us the DOM after the fact; this file is the decisive
/// witness for what chat_send actually did (HUMANFLOW-RED 2026-10-15,
/// run 38777224261: reply never arrived, zero requests hit llama-server,
/// no way to tell error-bubble from hang from CI).
fn clog(app: &tauri::AppHandle, line: &str) {
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    if let Ok(dir) = app.path().app_local_data_dir() {
        let p = dir.join("chat.log");
        let entry = format!("[{ts}] {line}\n");
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&p)
        {
            let _ = f.write_all(entry.as_bytes());
        }
    }
}

/// Brain service chat endpoint — the single gateway to the local model.
/// Memory (history + logging) happens inside the brain service.
const BRAIN_CHAT_URL: &str = "http://127.0.0.1:17369/chat";
/// CPU runners infer slowly; the brain service itself allows 280s for the
/// model call, so the outer timeout stays above it.
const BRAIN_TIMEOUT: Duration = Duration::from_secs(300);

/// NEVER-AGAIN gate target (RED 2026-10-16, run 38805846150): the frontend's
/// IPC-liveness gate calls this at startup. If this line never lands in
/// chat.log on a real run, Tauri IPC is dead and chat cannot reach the brain —
/// the absence of the witness IS the alarm. Fail-closed: returns Ok only when
/// the witness line was appended.
#[tauri::command]
pub fn ipc_ping(app: tauri::AppHandle) -> Result<String, String> {
    clog(&app, "ipc_ping ok — frontend IPC liveness proven");
    Ok("pong".to_string())
}

/// Frontend command: send one chat message to GENESIS's brain.
/// Returns her real reply text, or a Persian error string.
#[tauri::command]
pub async fn chat_send(
    app: tauri::AppHandle,
    prompt: String,
    state: tauri::State<'_, Arc<Mutex<BrainStatus>>>,
) -> Result<String, String> {
    clog(&app, "chat_send invoked");
    let (llama_running, brain_running, model_verified) = state
        .lock()
        .map(|s| (s.llama_running, s.brain_running, s.model_verified))
        .unwrap_or((false, false, false));
    clog(
        &app,
        &format!(
            "ready check: llama_running={llama_running} brain_running={brain_running} model_verified={model_verified}"
        ),
    );
    if !(llama_running && brain_running && model_verified) {
        clog(&app, "ready check FAILED -> not-ready error");
        return Err("مغزم هنوز آماده نیست — مدل داره دانلود یا گرم می‌شه. یه کم دیگه صبر کن، پدر.".to_string());
    }
    let prompt = prompt.trim().to_string();
    if prompt.is_empty() {
        return Err("پیامت خالیه، پدر.".to_string());
    }

    let t0 = Instant::now();
    clog(&app, &format!("POST {BRAIN_CHAT_URL} start (memory-wired)"));
    let out = tauri::async_runtime::spawn_blocking(move || ask_brain(prompt)).await;
    let dt = t0.elapsed().as_secs();
    match &out {
        Ok(Ok(_)) => clog(&app, &format!("POST done: reply ok, elapsed={dt}s")),
        Ok(Err(e)) => clog(&app, &format!("POST done: brain error after {dt}s: {e}")),
        Err(e) => clog(&app, &format!("POST done: join error after {dt}s: {e}")),
    }
    out.map_err(|e| format!("خطای داخلی چت: {e}"))?
}

/// POST {"message"} to the brain service; the brain loads living memory,
/// calls the local model, logs the exchange, and returns {"reply"}.
fn ask_brain(prompt: String) -> Result<String, String> {
    // NOTE: ureq is pinned without its `json` feature (vendored CI cache),
    // so JSON goes over the wire as a plain string.
    let body_str = serde_json::to_string(&serde_json::json!({ "message": prompt }))
        .map_err(|e| format!("خطای ساخت درخواست: {e}"))?;
    let resp = ureq::post(BRAIN_CHAT_URL)
        .timeout(BRAIN_TIMEOUT)
        .set("Content-Type", "application/json")
        .send_string(&body_str)
        .map_err(|e| format!("مغز جواب نداد (سرویس مغز محلی): {e}"))?;
    let status = resp.status();
    let text = resp
        .into_string()
        .map_err(|e| format!("جواب مغز خوانده نشد: {e}"))?;
    let v: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("جواب مغز خراب بود: {e}"))?;
    if status != 200 || v.get("ok").and_then(|o| o.as_bool()) != Some(true) {
        let detail = v
            .get("error")
            .and_then(|e| e.as_str())
            .unwrap_or("unknown brain error");
        return Err(format!("مغز خطا داد ({status}): {detail}"));
    }
    v.get("reply")
        .and_then(|r| r.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .ok_or_else(|| "مغز جواب خالی داد. یه بار دیگه بفرست، پدر.".to_string())
}
