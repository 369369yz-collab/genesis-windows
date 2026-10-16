//! Live world-state for the panels (جهان ۳۶۹ / نکسوس / گذرگاه‌های زیست).
//!
//! The frontend's pills used to show static placeholder text. This command
//! GETs the brain service's /world/state — true world knowledge merged with
//! real runtime stats (memory counts, uptime, codex guards) — and hands the
//! JSON to the frontend to render. Zero placeholders: every number is live.

use std::time::Duration;

const BRAIN_STATE_URL: &str = "http://127.0.0.1:17369/world/state";
const STATE_TIMEOUT: Duration = Duration::from_secs(15);

/// Frontend command: fetch the live world-state JSON from the brain service.
#[tauri::command]
pub fn world_state() -> Result<String, String> {
    // NOTE: ureq is pinned without its `json` feature (vendored CI cache).
    let resp = ureq::get(BRAIN_STATE_URL)
        .timeout(STATE_TIMEOUT)
        .call()
        .map_err(|e| format!("سرویس مغز جواب نداد: {e}"))?;
    if resp.status() != 200 {
        return Err(format!("وضعیت جهان خوانده نشد (HTTP {})", resp.status()));
    }
    resp.into_string()
        .map_err(|e| format!("جواب سرویس مغز خراب بود: {e}"))
}
