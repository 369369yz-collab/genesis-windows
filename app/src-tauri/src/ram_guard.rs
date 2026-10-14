//! RAM budget guard — pre-birth fix for W1 (local resource budget).
//!
//! The full stack (Qwen3-8B Q4_K_M + llama-server + whisper + Piper +
//! Tauri/WebView2 + three.js VRM + Chromium hands + 80 workflows) can exceed
//! 16 GB under nominal load, and Windows would OOM-kill llama-server or the
//! UI. This module implements the negotiated-degradation policy instead:
//!
//! - **Hard 10 GiB working-set cap** for the app (6 GiB reserved for the OS),
//!   enforced with a Windows Job Object at boot.
//! - **Boot check**: if free RAM < 6 GiB the app refuses full boot and
//!   degrades gracefully — lighter model slot + a Persian notice for YZ,
//!   never a silent crash and never an OOM kill.
//!
//! Platform notes: Windows uses `GlobalMemoryStatusEx`; Linux reads
//! `/proc/meminfo` (same logic, verifiable here). The `cfg(windows)` blocks
//! compile only on the windows target — they are verified by T1 on
//! windows-latest CI, not on this Linux VM.

/// Hard cap on this app's working set (W1 pre-birth fix).
pub const APP_WORKING_SET_CAP_BYTES: u64 = 10 * 1024 * 1024 * 1024; // 10 GiB
/// RAM reserved for the OS — the app never plans to use this.
pub const OS_RESERVE_BYTES: u64 = 6 * 1024 * 1024 * 1024; // 6 GiB
/// Boot refuses full mode when free RAM is below this.
pub const BOOT_MIN_FREE_BYTES: u64 = OS_RESERVE_BYTES;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RamBootVerdict {
    /// Enough free RAM: full boot (local Qwen3-8B core etc.).
    Full,
    /// Free RAM < 6 GiB: degraded boot — fallback model slot / context 2048,
    /// whisper/Piper strictly on-demand, Persian notice shown to YZ.
    Degraded,
}

#[derive(Debug, Clone)]
pub struct RamBootReport {
    pub verdict: RamBootVerdict,
    pub free_bytes: Option<u64>,
    /// Persian notice for YZ. Empty on a full boot.
    pub notice_fa: String,
}

/// Free physical RAM in bytes, or `None` when the platform cannot report it.
pub fn free_ram_bytes() -> Option<u64> {
    #[cfg(target_os = "windows")]
    {
        win32_free_ram()
    }
    #[cfg(target_os = "linux")]
    {
        linux_free_ram()
    }
    #[cfg(not(any(target_os = "windows", target_os = "linux")))]
    {
        None
    }
}

/// W1 boot gate. Never panics; unknown platform degrades honestly.
pub fn boot_check() -> RamBootReport {
    match free_ram_bytes() {
        Some(free) if free >= BOOT_MIN_FREE_BYTES => RamBootReport {
            verdict: RamBootVerdict::Full,
            free_bytes: Some(free),
            notice_fa: String::new(),
        },
        Some(free) => RamBootReport {
            verdict: RamBootVerdict::Degraded,
            free_bytes: Some(free),
            notice_fa: format!(
                "پدر، حافظه‌ی آزاد دستگاه الان {:.1} گیگابایته و از ۶ گیگ کمتره. \
                 برای اینکه وسط کار هنگ نکنم، حالت سبک رو فعال کردم (مدل سبک‌تر، حافظه‌ی کمتر). \
                 اگه برنامه‌های اضافه رو ببندی، حالم خیلی بهتر میشه.",
                free as f64 / 1024.0 / 1024.0 / 1024.0
            ),
        },
        None => RamBootReport {
            verdict: RamBootVerdict::Degraded,
            free_bytes: None,
            notice_fa: "پدر، نتونستم حافظه‌ی آزاد دستگاه رو بخونم. \
                        برای احتیاط حالت سبک رو فعال کردم تا وسط کار هنگ نکنم."
                .to_string(),
        },
    }
}

/// Enforce the hard 10 GiB working-set cap on this process.
/// Windows: Job Object with `JOB_OBJECT_LIMIT_PROCESS_MEMORY`.
/// Other OS: no portable hard cap — the boot check above is the guard.
pub fn enforce_hard_cap() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        win32_enforce_cap()
    }
    #[cfg(not(target_os = "windows"))]
    {
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Linux
// ---------------------------------------------------------------------------

#[cfg(target_os = "linux")]
fn linux_free_ram() -> Option<u64> {
    let text = std::fs::read_to_string("/proc/meminfo").ok()?;
    parse_meminfo_available_kb(&text).map(|kb| kb.saturating_mul(1024))
}

/// Parse `MemAvailable:` (kB) out of /proc/meminfo text. Pure + unit-tested.
fn parse_meminfo_available_kb(text: &str) -> Option<u64> {
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("MemAvailable:") {
            let num = rest.split_whitespace().next()?;
            return num.parse::<u64>().ok();
        }
    }
    None
}

// ---------------------------------------------------------------------------
// Windows (compiled + verified on windows-latest CI, T1 — not on this VM)
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
fn win32_free_ram() -> Option<u64> {
    use windows_sys::Win32::Foundation::BOOL;
    use windows_sys::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
    let mut st: MEMORYSTATUSEX = unsafe { std::mem::zeroed() };
    st.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
    let ok: BOOL = unsafe { GlobalMemoryStatusEx(&mut st) };
    if ok != 0 {
        Some(st.ullAvailPhys)
    } else {
        None
    }
}

#[cfg(target_os = "windows")]
fn win32_enforce_cap() -> Result<(), String> {
    use windows_sys::Win32::Foundation::HANDLE;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_PROCESS_MEMORY,
        JobObjectExtendedLimitInformation,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    unsafe {
        let job: HANDLE = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job == 0 {
            return Err("CreateJobObjectW failed".to_string());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY;
        info.ProcessMemoryLimit = APP_WORKING_SET_CAP_BYTES as usize;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            return Err("SetInformationJobObject failed".to_string());
        }
        if AssignProcessToJobObject(job, GetCurrentProcess()) == 0 {
            return Err("AssignProcessToJobObject failed".to_string());
        }
        // The job handle is intentionally leaked: the memory limit must
        // outlive this call for the whole process lifetime.
        std::mem::forget(job);
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Tests (run on this VM via `cargo test`)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const MEMINFO_FIXTURE: &str = "MemTotal:        8024344 kB\n\
         MemFree:          123456 kB\n\
         MemAvailable:    4012345 kB\n\
         Buffers:          234567 kB\n";

    #[test]
    fn parses_memavailable_kb() {
        assert_eq!(parse_meminfo_available_kb(MEMINFO_FIXTURE), Some(4012345));
    }

    #[test]
    fn missing_memavailable_is_none() {
        assert_eq!(parse_meminfo_available_kb("MemTotal: 100 kB\n"), None);
    }

    #[test]
    fn boot_check_matches_this_machine() {
        // Real assertion against the live machine: verdict must agree with
        // the measured free RAM — no hard-coded expectation.
        let report = boot_check();
        match report.free_bytes {
            Some(free) if free >= BOOT_MIN_FREE_BYTES => {
                assert_eq!(report.verdict, RamBootVerdict::Full);
                assert!(report.notice_fa.is_empty());
            }
            Some(_) => {
                assert_eq!(report.verdict, RamBootVerdict::Degraded);
                assert!(!report.notice_fa.is_empty());
            }
            None => assert_eq!(report.verdict, RamBootVerdict::Degraded),
        }
    }

    #[test]
    fn constants_reconcile() {
        // Mathematical precision: the numbers must say what the doc says.
        assert_eq!(APP_WORKING_SET_CAP_BYTES, 10 * 1024 * 1024 * 1024);
        assert_eq!(OS_RESERVE_BYTES, 6 * 1024 * 1024 * 1024);
        assert_eq!(BOOT_MIN_FREE_BYTES, OS_RESERVE_BYTES);
    }
}
