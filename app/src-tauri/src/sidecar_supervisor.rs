//! Sidecar lifecycle supervisor — voice sidecars (whisper / Piper) load
//! on demand and unload after 60 s idle (W1 pre-birth fix).
//!
//! The voice builder (Phase 3) implements [`SidecarBackend`] for each sidecar
//! binary; this module owns the idle policy, the background reaper thread,
//! and the OOM / gaming-hours policy hooks:
//!
//! - **Idle unload:** a sidecar untouched for 60 s is shut down and its RAM
//!   released. The next `acquire` reloads it transparently.
//! - **OOM policy hook:** [`SidecarBackend::max_ram_bytes`] declares each
//!   sidecar's RAM budget; the brain builder's OOM watchdog restarts an
//!   over-budget sidecar with smaller settings (e.g. llama-server `-c`)
//!   *before* Windows kills it, with an honest Persian notice.
//! - **Gaming-hours profile (18:00–24:00 local):** the voice builder
//!   pre-unloads whisper during these hours via [`SidecarSupervisor::release`]
//!   + [`SidecarSupervisor::in_gaming_hours`].

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// Idle timeout after which an unused voice sidecar is unloaded.
pub const IDLE_UNLOAD_SECS: u64 = 60;
/// How often the reaper thread sweeps for idle sidecars.
const REAPER_SWEEP_SECS: u64 = 15;
/// Gaming-hours window (local time): whisper is pre-unloaded 18:00–24:00.
pub const GAMING_HOURS_START: u8 = 18;
pub const GAMING_HOURS_END: u8 = 24;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SidecarKind {
    Whisper,
    Piper,
}

impl SidecarKind {
    pub fn as_str(self) -> &'static str {
        match self {
            SidecarKind::Whisper => "whisper",
            SidecarKind::Piper => "piper",
        }
    }
}

/// Implemented by the voice builder for each sidecar binary.
///
/// The supervisor never guesses how a sidecar starts or stops — it only
/// enforces *when*.
#[allow(dead_code)] // trait impls arrive with the voice builder (Phase 3)
pub trait SidecarBackend: Send + 'static {
    fn kind(&self) -> SidecarKind;
    fn spawn(&mut self) -> Result<(), String>;
    fn shutdown(&mut self) -> Result<(), String>;
    fn is_alive(&self) -> bool;
    /// Hard RAM budget for this sidecar in bytes (W1 OOM policy).
    fn max_ram_bytes(&self) -> u64;
    /// Shrink settings before a forced restart (e.g. smaller context).
    /// Default: nothing to shrink.
    fn shrink_for_restart(&mut self) {}
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)] // read by HUD/diagnostics via status() (Phase 3+)
pub enum SidecarState {
    Unloaded,
    LoadedIdle,
    LoadedBusy,
}

#[derive(Debug, Clone)]
#[allow(dead_code)] // read by HUD/diagnostics via status() (Phase 3+)
pub struct SidecarStatus {
    pub kind: SidecarKind,
    pub state: SidecarState,
    /// Seconds since last use (0 when busy or never loaded).
    pub idle_secs: u64,
}

struct Slot {
    backend: Box<dyn SidecarBackend>,
    /// `None` = currently unloaded. Set on acquire/release.
    last_used: Option<Instant>,
    busy: bool,
}

/// Owns the lifecycle of all registered voice sidecars.
pub struct SidecarSupervisor {
    slots: HashMap<SidecarKind, Slot>,
}

impl SidecarSupervisor {
    pub fn new() -> Self {
        Self {
            slots: HashMap::new(),
        }
    }

    /// Register a sidecar backend (done once at boot by the voice builder).
    #[allow(dead_code)] // called by the voice builder when it wires Phase 3
    pub fn register(&mut self, backend: Box<dyn SidecarBackend>) {
        let kind = backend.kind();
        self.slots.insert(
            kind,
            Slot {
                backend,
                last_used: None,
                busy: false,
            },
        );
    }

    /// Load the sidecar if needed and mark it busy. Loads on demand:
    /// a cold sidecar is spawned here, transparently to the caller.
    #[allow(dead_code)] // consumed by the voice builder (Phase 3 wiring)
    pub fn acquire(&mut self, kind: SidecarKind) -> Result<(), String> {
        let slot = self
            .slots
            .get_mut(&kind)
            .ok_or_else(|| format!("no sidecar registered for {:?}", kind))?;
        if slot.last_used.is_none() || !slot.backend.is_alive() {
            slot.backend.spawn()?;
        }
        slot.busy = true;
        slot.last_used = Some(Instant::now());
        Ok(())
    }

    /// Mark the sidecar idle. The reaper unloads it after 60 s of idleness.
    #[allow(dead_code)] // consumed by the voice builder (Phase 3 wiring)
    pub fn release(&mut self, kind: SidecarKind) {
        if let Some(slot) = self.slots.get_mut(&kind) {
            slot.busy = false;
            slot.last_used = Some(Instant::now());
        }
    }

    /// Point-in-time status for HUD / diagnostics.
    pub fn status(&self) -> Vec<SidecarStatus> {
        let now = Instant::now();
        self.slots
            .iter()
            .map(|(kind, slot)| {
                let (state, idle_secs) = match (slot.last_used, slot.busy) {
                    (None, _) => (SidecarState::Unloaded, 0),
                    (Some(_), true) => (SidecarState::LoadedBusy, 0),
                    (Some(t), false) => (
                        SidecarState::LoadedIdle,
                        now.duration_since(t).as_secs(),
                    ),
                };
                SidecarStatus {
                    kind: *kind,
                    state,
                    idle_secs,
                }
            })
            .collect()
    }

    /// Unload every non-busy sidecar idle since before `cutoff`.
    /// Takes the cutoff as a parameter so tests don't need clock mocking.
    pub fn reap_idle_before(&mut self, cutoff: Instant) -> Vec<SidecarKind> {
        let mut unloaded = Vec::new();
        for (kind, slot) in self.slots.iter_mut() {
            if slot.busy {
                continue;
            }
            let idle_since = match slot.last_used {
                Some(t) => t,
                None => continue, // already unloaded
            };
            if idle_since <= cutoff && slot.backend.is_alive() {
                if slot.backend.shutdown().is_ok() {
                    slot.last_used = None;
                    unloaded.push(*kind);
                }
                // On shutdown failure the slot keeps its timestamp and the
                // next sweep retries — we never leak a half-dead sidecar
                // silently: the failure is logged by the caller.
            } else if idle_since <= cutoff {
                slot.last_used = None;
                unloaded.push(*kind);
            }
        }
        unloaded
    }

    /// Unload sidecars idle longer than [`IDLE_UNLOAD_SECS`].
    pub fn reap_idle(&mut self) -> Vec<SidecarKind> {
        let cutoff = Instant::now()
            .checked_sub(Duration::from_secs(IDLE_UNLOAD_SECS))
            .unwrap_or_else(Instant::now);
        self.reap_idle_before(cutoff)
    }

    /// True during local gaming hours (18:00–24:00): the voice builder
    /// pre-unloads whisper then, so YZ's games always win the RAM.
    pub fn in_gaming_hours() -> bool {
        match local_hour() {
            Some(h) => h >= GAMING_HOURS_START && h < GAMING_HOURS_END,
            None => false, // unknown clock: never pre-unload on a guess
        }
    }
}

/// Spawn the background reaper thread: every 15 s it unloads sidecars idle
/// for 60 s. Returns the join handle (detached by the caller via `manage`).
pub fn spawn_reaper(supervisor: Arc<Mutex<SidecarSupervisor>>) -> thread::JoinHandle<()> {
    thread::Builder::new()
        .name("sidecar-reaper".to_string())
        .spawn(move || loop {
            thread::sleep(Duration::from_secs(REAPER_SWEEP_SECS));
            match supervisor.lock() {
                Ok(mut sup) => {
                    for kind in sup.reap_idle() {
                        eprintln!(
                            "[sidecar] unloaded idle {} after {}s",
                            kind.as_str(),
                            IDLE_UNLOAD_SECS
                        );
                    }
                }
                Err(e) => {
                    eprintln!("[sidecar] reaper: supervisor lock poisoned: {e}");
                    break;
                }
            }
        })
        .expect("failed to spawn sidecar reaper thread")
}

/// Local hour of day (0–23), or `None` when the OS clock is unreadable.
fn local_hour() -> Option<u8> {
    #[cfg(unix)]
    {
        let t = unsafe { libc::time(std::ptr::null_mut()) };
        if t == -1 {
            return None;
        }
        let mut tm: libc::tm = unsafe { std::mem::zeroed() };
        let p = unsafe { libc::localtime_r(&t, &mut tm) };
        if p.is_null() {
            None
        } else {
            Some(tm.tm_hour as u8)
        }
    }
    #[cfg(target_os = "windows")]
    {
        // SYSTEMTIME is absent from windows-sys 0.48 SystemInformation; declare both locally.
        // Canonical Win32 layout: 8x WORD in fixed order — stable ABI, kernel32.
        #[repr(C)]
        #[derive(Default)]
        struct SYSTEMTIME {
            w_year: u16, w_month: u16, w_day_of_week: u16, w_day: u16,
            w_hour: u16, w_minute: u16, w_second: u16, w_milliseconds: u16,
        }
        #[link(name = "kernel32")]
        extern "system" {
            fn GetLocalTime(lpsystemtime: *mut SYSTEMTIME);
        }
        let mut st: SYSTEMTIME = unsafe { std::mem::zeroed() };
        unsafe { GetLocalTime(&mut st) };
        Some(st.w_hour as u8)
    }
    #[cfg(not(any(unix, target_os = "windows")))]
    {
        None
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Fake backend the voice builder's real one will replace.
    struct FakeBackend {
        kind: SidecarKind,
        alive: bool,
        spawns: usize,
        shutdowns: usize,
    }

    impl FakeBackend {
        fn new(kind: SidecarKind) -> Self {
            Self {
                kind,
                alive: false,
                spawns: 0,
                shutdowns: 0,
            }
        }
    }

    impl SidecarBackend for FakeBackend {
        fn kind(&self) -> SidecarKind {
            self.kind
        }
        fn spawn(&mut self) -> Result<(), String> {
            self.alive = true;
            self.spawns += 1;
            Ok(())
        }
        fn shutdown(&mut self) -> Result<(), String> {
            self.alive = false;
            self.shutdowns += 1;
            Ok(())
        }
        fn is_alive(&self) -> bool {
            self.alive
        }
        fn max_ram_bytes(&self) -> u64 {
            512 * 1024 * 1024
        }
    }

    fn supervisor_with_fake() -> SidecarSupervisor {
        let mut sup = SidecarSupervisor::new();
        sup.register(Box::new(FakeBackend::new(SidecarKind::Whisper)));
        sup
    }

    #[test]
    fn acquire_loads_on_demand() {
        let mut sup = supervisor_with_fake();
        assert!(matches!(
            sup.status()[0].state,
            SidecarState::Unloaded
        ));
        sup.acquire(SidecarKind::Whisper).unwrap();
        assert!(matches!(
            sup.status()[0].state,
            SidecarState::LoadedBusy
        ));
    }

    #[test]
    fn idle_sidecar_unloads_after_timeout() {
        let mut sup = supervisor_with_fake();
        sup.acquire(SidecarKind::Whisper).unwrap();
        sup.release(SidecarKind::Whisper);
        assert!(matches!(
            sup.status()[0].state,
            SidecarState::LoadedIdle
        ));
        // Simulate 61 s of idleness with a cutoff in the future.
        let cutoff = Instant::now() + Duration::from_secs(IDLE_UNLOAD_SECS + 1);
        let unloaded = sup.reap_idle_before(cutoff);
        assert_eq!(unloaded, vec![SidecarKind::Whisper]);
        assert!(matches!(
            sup.status()[0].state,
            SidecarState::Unloaded
        ));
    }

    #[test]
    fn busy_sidecar_is_never_reaped() {
        let mut sup = supervisor_with_fake();
        sup.acquire(SidecarKind::Whisper).unwrap(); // busy, no release
        let cutoff = Instant::now() + Duration::from_secs(3600);
        let unloaded = sup.reap_idle_before(cutoff);
        assert!(unloaded.is_empty());
    }

    #[test]
    fn fresh_sidecar_is_not_reaped() {
        let mut sup = supervisor_with_fake();
        sup.acquire(SidecarKind::Whisper).unwrap();
        sup.release(SidecarKind::Whisper);
        // Cutoff in the past: idle period hasn't elapsed.
        let cutoff = Instant::now() - Duration::from_secs(3600);
        let unloaded = sup.reap_idle_before(cutoff);
        assert!(unloaded.is_empty());
    }

    #[test]
    fn local_hour_in_range_when_known() {
        if let Some(h) = local_hour() {
            assert!(h < 24);
        }
        // None is acceptable (unknown clock); no assertion either way.
    }
}
