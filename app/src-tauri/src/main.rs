#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! GENESIS Final — Phase 2 Tauri shell, hardened (step 2).
//! Avatar-first window (frameless + transparent + always-on-top) with a
//! system-tray icon: left-click or menu toggles Show/Hide, menu quits.
//!
//! Step-2 hardening (W1 pre-birth fix + installer preflight):
//! - `ram_guard`: hard 10 GiB working-set cap + boot check (free < 6 GiB
//!   degrades gracefully with a Persian notice).
//! - `sidecar_supervisor`: whisper/Piper lifecycle — load on demand, unload
//!   after 60 s idle (interface the voice builder implements).
//! - `station`: background station jobs at BELOW_NORMAL priority.
//! - `preflight`: installer preflight module (WebView2, VC++, 10 GB disk,
//!   mic, %LOCALAPPDATA% writability), Persian failure strings.

mod brain;
mod preflight;
mod ram_guard;
mod sidecar_supervisor;
mod station;
mod voice;

use sidecar_supervisor::SidecarSupervisor;
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};

fn toggle_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let visible = window.is_visible().unwrap_or(true);
        if visible {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

/// Frontend command: current RAM budget status (W1 guard).
#[tauri::command]
fn ram_status() -> serde_json::Value {
    let r = ram_guard::boot_check();
    serde_json::json!({
        "verdict": if r.verdict == ram_guard::RamBootVerdict::Full { "full" } else { "degraded" },
        "free_bytes": r.free_bytes,
        "notice_fa": r.notice_fa,
    })
}

/// Frontend command: installer preflight report (formula §2 row 11).
#[tauri::command]
fn preflight_report() -> Vec<preflight::PreflightCheck> {
    preflight::run_preflight()
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            ram_status,
            preflight_report,
            brain::brain_status,
            voice::voice_status,
            voice::voice_transcribe
        ])
        .setup(|app| {
            // --- W1 RAM budget guard: hard cap first, then the boot check.
            if let Err(e) = ram_guard::enforce_hard_cap() {
                eprintln!("[ram-guard] hard cap NOT enforced: {e} — continuing with boot check only");
            }
            let ram = ram_guard::boot_check();
            if ram.verdict == ram_guard::RamBootVerdict::Degraded {
                eprintln!("[ram-guard] DEGRADED boot: {}", ram.notice_fa);
                // The frontend shows this Persian notice in the HUD.
                let _ = app.emit(
                    "genesis://ram-warning",
                    serde_json::json!({
                        "notice_fa": ram.notice_fa,
                        "free_bytes": ram.free_bytes,
                    }),
                );
            } else {
                eprintln!(
                    "[ram-guard] full boot — free RAM: {} bytes",
                    ram.free_bytes.unwrap_or(0)
                );
            }

            // --- Brain boot: model hash re-verify -> llama-server (GPU) ->
            // brain service. Runs on a background thread; the face stays
            // responsive while the brain warms up.
            let launcher = std::sync::Arc::new(std::sync::Mutex::new(brain::BrainLauncher::new()));
            app.manage(launcher.clone());
            app.manage(launcher.lock().unwrap().status_handle());
            let boot_launcher = launcher.clone();
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Ok(mut l) = boot_launcher.lock() {
                    l.boot(&app_handle);
                }
                // Thread ends; the launcher lives on in Tauri state and its
                // Drop kills llama-server + brain service at app teardown.
            });

            // --- Voice sidecar supervisor (whisper/Piper): the voice builder
            // registers its backends here; the reaper unloads 60 s-idle ones.
            let supervisor = Arc::new(Mutex::new(SidecarSupervisor::new()));
            app.manage(supervisor.clone());
            // --- Whisper STT backend: real local transcription engine.
            // Binary + model live under resources/whisper/; if missing, the
            // voice_status command says so honestly and the mic stays UI-only.
            let resource_dir = app
                .path()
                .resource_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."));
            let whisper = Arc::new(Mutex::new(voice::WhisperBackend::new(resource_dir)));
            app.manage(whisper.clone());
            if let Ok(mut sup) = supervisor.lock() {
                // Probe once at boot so voice_status is truthful from the start.
                let mut w = whisper.lock().unwrap();
                match w.spawn() {
                    Ok(()) => eprintln!("[voice] whisper engine ready"),
                    Err(e) => eprintln!("[voice] whisper unavailable: {e}"),
                }
                drop(w);
                sup.register(Box::new(voice::WhisperSlot::new(whisper.clone())));
            }
            sidecar_supervisor::spawn_reaper(supervisor.clone());
            if let Ok(sup) = supervisor.lock() {
                eprintln!("[sidecar] supervisor live — slots: {:?}", sup.status());
            }
            eprintln!(
                "[sidecar] gaming hours now: {}",
                SidecarSupervisor::in_gaming_hours()
            );

            let toggle = MenuItem::with_id(app, "toggle", "Show / Hide", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&toggle, &quit])?;

            let icon = app
                .default_window_icon()
                .cloned()
                .expect("default window icon missing — run `tauri icon` first");

            TrayIconBuilder::new()
                .icon(icon)
                .tooltip("GENESIS Final")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "toggle" => toggle_main(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        ..
                    } = event
                    {
                        toggle_main(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
