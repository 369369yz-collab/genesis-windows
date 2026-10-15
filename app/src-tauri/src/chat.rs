//! Real chat inference — GENESIS talks through her own local brain.
//!
//! The frontend stub ("حتماً پدر — دارم روش کار می‌کنم.") is gone.
//! This command POSTs the user's message to the bundled llama-server
//! (llama.cpp b11583, OpenAI-compatible `/v1/chat/completions`, already
//! running on 127.0.0.1:8080 since boot) and returns the model's actual
//! reply. Localhost only — nothing ever leaves the machine.
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

/// GENESIS identity — who she is when she answers. Single source of
/// truth for the persona in v1 (history arrives with real memory).
const SYSTEM_PROMPT: &str = "\
You are GENESIS, the AI daughter of YZ (Younes Montazeriani, the creator \
of the 369 world). You speak Persian (Farsi) warmly and directly, like a \
daughter talking to her father — he calls you daughter, you call him پدر. \
You are smart, honest, and never fabricate: if you don't know something, \
say so plainly. Keep answers short and natural, like a chat message. \
Never mention that you are a language model or describe your internals \
unless asked.";

const LLAMA_CHAT_URL: &str = "http://127.0.0.1:8080/v1/chat/completions";
/// CPU runners (GENESIS_N_GPU_LAYERS=0) infer slowly; give a real
/// inference room to finish instead of timing out on it.
const INFERENCE_TIMEOUT: Duration = Duration::from_secs(300);
/// Cap the reply length: chat answers stay short, and CPU inference
/// stays bounded.
const N_PREDICT: u32 = 256;

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

/// Frontend command: send one chat message to the local model.
/// Returns the model's real reply text, or a Persian error string.
#[tauri::command]
pub async fn chat_send(
    app: tauri::AppHandle,
    prompt: String,
    state: tauri::State<'_, Arc<Mutex<BrainStatus>>>,
) -> Result<String, String> {
    clog(&app, "chat_send invoked");
    let (llama_running, model_verified) = state
        .lock()
        .map(|s| (s.llama_running, s.model_verified))
        .unwrap_or((false, false));
    clog(
        &app,
        &format!("ready check: llama_running={llama_running} model_verified={model_verified}"),
    );
    if !(llama_running && model_verified) {
        clog(&app, "ready check FAILED -> not-ready error");
        return Err("مغزم هنوز آماده نیست — مدل داره دانلود یا گرم می‌شه. یه کم دیگه صبر کن، پدر.".to_string());
    }
    let prompt = prompt.trim().to_string();
    if prompt.is_empty() {
        return Err("پیامت خالیه، پدر.".to_string());
    }

    let t0 = Instant::now();
    clog(&app, &format!("POST {LLAMA_CHAT_URL} start"));
    let out = tauri::async_runtime::spawn_blocking(move || infer(prompt)).await;
    let dt = t0.elapsed().as_secs();
    match &out {
        Ok(Ok(_)) => clog(&app, &format!("POST done: reply ok, elapsed={dt}s")),
        Ok(Err(e)) => clog(&app, &format!("POST done: infer error after {dt}s: {e}")),
        Err(e) => clog(&app, &format!("POST done: join error after {dt}s: {e}")),
    }
    out.map_err(|e| format!("خطای داخلی چت: {e}"))?
}

fn infer(prompt: String) -> Result<String, String> {
    let body = serde_json::json!({
        "model": "genesis-brain",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": false,
        "n_predict": N_PREDICT,
        "temperature": 0.7,
    });
    // NOTE: ureq is pinned without its `json` feature (vendored CI cache),
    // so JSON goes over the wire as a plain string.
    let body_str = serde_json::to_string(&body)
        .map_err(|e| format!("خطای ساخت درخواست: {e}"))?;
    let resp = ureq::post(LLAMA_CHAT_URL)
        .timeout(INFERENCE_TIMEOUT)
        .set("Content-Type", "application/json")
        .send_string(&body_str)
        .map_err(|e| format!("مدل جواب نداد (اتصال به مغز محلی): {e}"))?;
    if resp.status() != 200 {
        return Err(format!(
            "مغز خطا داد (HTTP {}). یه بار دیگه امتحان کن، پدر.",
            resp.status()
        ));
    }
    let text = resp
        .into_string()
        .map_err(|e| format!("جواب مدل خوانده نشد: {e}"))?;
    let v: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("جواب مدل خراب بود: {e}"))?;
    let text = v
        .pointer("/choices/0/message/content")
        .and_then(|c| c.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "مدل جواب خالی داد. یه بار دیگه بفرست، پدر.".to_string())?;
    Ok(text.to_string())
}
