//! Installer preflight — the module the installer builder (Phase 5) calls.
//!
//! Formula §2 row 11 `[Code]` preflight: WebView2 present, VC++ redist,
//! 10 GB disk, mic available, `%LOCALAPPDATA%` writable.
//!
//! Every check returns a [`PreflightCheck`]: pass/fail/skip + an English
//! detail line for the log + a **Persian explanation and offered fix** for
//! every failure. The installer writes the full report to
//! `logs/preflight.log` (see [`default_log_path`]) and offers each fix.
//!
//! The checks are Windows-targeted; on other OSes the Windows-only checks
//! report `Skipped` honestly instead of guessing. The disk-space check runs
//! for real on every platform (`statvfs` on Unix). All Win32 access goes
//! through `windows-sys` 0.48 only (no extra registry crate — the tiny
//! reader below is ours). `cfg(windows)` blocks compile on the windows
//! target — verified by T1 on windows-latest CI, not on this Linux VM.

use std::path::PathBuf;

/// Minimum free disk space required (formula §2 row 11: 10 GB).
pub const REQUIRED_DISK_FREE_BYTES: u64 = 10 * 1024 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CheckStatus {
    Pass,
    Fail,
    Skipped,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct PreflightCheck {
    pub id: &'static str,
    pub name_en: &'static str,
    pub status: CheckStatus,
    pub detail_en: String,
    /// Persian explanation of the failure (empty unless failed).
    pub explanation_fa: String,
    /// Persian offered fix (empty unless failed).
    pub fix_fa: String,
}

impl PreflightCheck {
    fn pass(id: &'static str, name_en: &'static str, detail_en: String) -> Self {
        Self {
            id,
            name_en,
            status: CheckStatus::Pass,
            detail_en,
            explanation_fa: String::new(),
            fix_fa: String::new(),
        }
    }

    fn fail(
        id: &'static str,
        name_en: &'static str,
        detail_en: String,
        explanation_fa: &str,
        fix_fa: &str,
    ) -> Self {
        Self {
            id,
            name_en,
            status: CheckStatus::Fail,
            detail_en,
            explanation_fa: explanation_fa.to_string(),
            fix_fa: fix_fa.to_string(),
        }
    }

    fn skipped(id: &'static str, name_en: &'static str, reason_en: &str) -> Self {
        Self {
            id,
            name_en,
            status: CheckStatus::Skipped,
            detail_en: reason_en.to_string(),
            explanation_fa: String::new(),
            fix_fa: String::new(),
        }
    }
}

/// Run all five preflight checks, in formula order.
pub fn run_preflight() -> Vec<PreflightCheck> {
    vec![
        check_webview2(),
        check_vcredist(),
        check_disk_space(),
        check_microphone(),
        check_localappdata_writable(),
    ]
}

/// True when every non-skipped check passed.
#[allow(dead_code)] // consumed by the installer builder (Phase 5)
pub fn all_pass(checks: &[PreflightCheck]) -> bool {
    checks
        .iter()
        .all(|c| c.status != CheckStatus::Fail)
}

/// Human-readable report for `logs/preflight.log`.
pub fn format_report(checks: &[PreflightCheck]) -> String {
    let mut out = String::from("GENESIS installer preflight\n");
    for c in checks {
        let tag = match c.status {
            CheckStatus::Pass => "PASS",
            CheckStatus::Fail => "FAIL",
            CheckStatus::Skipped => "SKIP",
        };
        out.push_str(&format!("[{}] {} — {}\n", tag, c.id, c.detail_en));
        if c.status == CheckStatus::Fail {
            out.push_str(&format!(
                "  FA: {}\n  FIX FA: {}\n",
                c.explanation_fa, c.fix_fa
            ));
        }
    }
    out
}

/// Default preflight log path: `%LOCALAPPDATA%/GENESIS Final/logs/` on
/// Windows, `./logs/` elsewhere (installer overrides as needed).
pub fn default_log_path() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            return PathBuf::from(local)
                .join("GENESIS Final")
                .join("logs")
                .join("preflight.log");
        }
    }
    PathBuf::from("logs").join("preflight.log")
}

/// Write the report to [`default_log_path`], creating parent dirs.
#[allow(dead_code)] // consumed by the installer builder (Phase 5)
pub fn write_report(checks: &[PreflightCheck]) -> std::io::Result<PathBuf> {
    let path = default_log_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, format_report(checks))?;
    Ok(path)
}

// ---------------------------------------------------------------------------
// 1. WebView2 — the Tauri v2 WebView runtime (Windows 10+)
// ---------------------------------------------------------------------------

fn check_webview2() -> PreflightCheck {
    const ID: &str = "webview2";
    const NAME: &str = "WebView2 runtime";
    #[cfg(target_os = "windows")]
    {
        match win32::webview2_version() {
            Some(v) => PreflightCheck::pass(ID, NAME, format!("WebView2 present (version {v})")),
            None => PreflightCheck::fail(
                ID,
                NAME,
                "WebView2 runtime not found in EdgeUpdate ClientState registry".to_string(),
                "موتور نمایش من (WebView2) روی ویندوزت نصب نیست. بدون اون من نمی‌تونم باز بشم.",
                "گزینه‌ی «نصب خودکار» رو بزن تا نصب‌کننده خودش دانلود و نصبش کنه؛ فقط چند دقیقه طول می‌کشه.",
            ),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        PreflightCheck::skipped(ID, NAME, "Windows-only check")
    }
}

// ---------------------------------------------------------------------------
// 2. VC++ redistributable (bundled with the installer per formula)
// ---------------------------------------------------------------------------

fn check_vcredist() -> PreflightCheck {
    const ID: &str = "vcredist";
    const NAME: &str = "VC++ redistributable";
    #[cfg(target_os = "windows")]
    {
        match win32::vcredist_version() {
            Some(v) => PreflightCheck::pass(
                ID,
                NAME,
                format!("VC++ 2015+ x64 runtime installed (version {v})"),
            ),
            None => PreflightCheck::fail(
                ID,
                NAME,
                "VC++ 2015+ x64 runtime not found in registry".to_string(),
                "کتابخانه‌ی سیستمی ویژوال‌سی (VC++ Redistributable) پیدا نشد. خیلی از برنامه‌ها — از جمله من — بهش نیاز دارن.",
                "نصب‌کننده نسخه‌ی موردنیاز رو همراه خودش داره؛ گزینه‌ی «نصب» رو بزن تا خودش نصبش کنه.",
            ),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        PreflightCheck::skipped(ID, NAME, "Windows-only check")
    }
}

// ---------------------------------------------------------------------------
// 3. Disk space — 10 GB free on the install/data volume
// ---------------------------------------------------------------------------

fn check_disk_space() -> PreflightCheck {
    const ID: &str = "disk";
    const NAME: &str = "Disk space (10 GB)";
    let dir = install_volume_dir();
    match free_bytes_on(&dir) {
        Some(free) if free >= REQUIRED_DISK_FREE_BYTES => PreflightCheck::pass(
            ID,
            NAME,
            format!(
                "{:.1} GB free on {}",
                gb(free),
                dir.display()
            ),
        ),
        Some(free) => PreflightCheck::fail(
            ID,
            NAME,
            format!(
                "only {:.1} GB free on {} (need 10 GB)",
                gb(free),
                dir.display()
            ),
            "برای نصب و کار کردن من حداقل ۱۰ گیگ فضای خالی لازمه، ولی الان کمتر از این داری.",
            "یه کم فضا خالی کن (فایل‌ها و برنامه‌های اضافه رو پاک کن) بعد دوباره امتحان کن.",
        ),
        None => PreflightCheck::fail(
            ID,
            NAME,
            format!("could not measure free space on {}", dir.display()),
            "نتونستم فضای خالی دیسک رو اندازه بگیرم.",
            "مطمئن شو دیسک سالمه و حداقل ۱۰ گیگ فضای خالی داره، بعد دوباره امتحان کن.",
        ),
    }
}

fn gb(bytes: u64) -> f64 {
    bytes as f64 / 1024.0 / 1024.0 / 1024.0
}

/// Directory whose volume we measure: %LOCALAPPDATA% on Windows (where the
/// app + models live), current dir elsewhere.
fn install_volume_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            let p = PathBuf::from(local);
            if p.is_dir() {
                return p;
            }
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn free_bytes_on(dir: &std::path::Path) -> Option<u64> {
    #[cfg(target_os = "windows")]
    {
        win32::free_bytes(dir)
    }
    #[cfg(unix)]
    {
        unix_free_bytes(dir)
    }
    #[cfg(not(any(target_os = "windows", unix)))]
    {
        let _ = dir;
        None
    }
}

#[cfg(unix)]
fn unix_free_bytes(dir: &std::path::Path) -> Option<u64> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let c = CString::new(dir.as_os_str().as_bytes()).ok()?;
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: `c` is a valid NUL-terminated path; `st` is a valid out-param.
    if unsafe { libc::statvfs(c.as_ptr(), &mut st) } != 0 {
        return None;
    }
    Some((st.f_bavail as u64).saturating_mul(st.f_frsize as u64))
}

// ---------------------------------------------------------------------------
// 4. Microphone — a capture endpoint must exist
// ---------------------------------------------------------------------------

fn check_microphone() -> PreflightCheck {
    const ID: &str = "mic";
    const NAME: &str = "Microphone";
    #[cfg(target_os = "windows")]
    {
        match win32::capture_endpoint_count() {
            Some(n) if n > 0 => PreflightCheck::pass(
                ID,
                NAME,
                format!("{n} audio capture endpoint(s) registered"),
            ),
            _ => PreflightCheck::fail(
                ID,
                NAME,
                "no audio capture endpoint registered under MMDevices".to_string(),
                "میکروفونی روی دستگاه پیدا نکردم. بدون میکروفون نمی‌تونم صدات رو بشنوم.",
                "میکروفون رو وصل کن و مطمئن شو ویندوز اون رو شناخته (تنظیمات صدا)، بعد دوباره امتحان کن.",
            ),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        PreflightCheck::skipped(ID, NAME, "Windows-only check")
    }
}

// ---------------------------------------------------------------------------
// 5. %LOCALAPPDATA% writable
// ---------------------------------------------------------------------------

fn check_localappdata_writable() -> PreflightCheck {
    const ID: &str = "localappdata";
    const NAME: &str = "%LOCALAPPDATA% writable";
    #[cfg(target_os = "windows")]
    {
        match std::env::var("LOCALAPPDATA") {
            Ok(local) => {
                let probe = PathBuf::from(&local).join(".genesis_write_test");
                match std::fs::write(&probe, b"genesis-preflight") {
                    Ok(()) => {
                        let _ = std::fs::remove_file(&probe);
                        PreflightCheck::pass(ID, NAME, format!("%LOCALAPPDATA% writable ({local})"))
                    }
                    Err(e) => PreflightCheck::fail(
                        ID,
                        NAME,
                        format!("%LOCALAPPDATA% not writable: {e}"),
                        "نمی‌تونم توی پوشه‌ی خودم فایل بنویسم. شاید دسترسی‌م محدوده.",
                        "نصب‌کننده رو با «اجرا به‌عنوان مدیر» (Run as administrator) باز کن و دوباره امتحان کن.",
                    ),
                }
            }
            Err(_) => PreflightCheck::fail(
                ID,
                NAME,
                "%LOCALAPPDATA% environment variable missing".to_string(),
                "پوشه‌ی سیستمی برنامه‌ها (%LOCALAPPDATA%) پیدا نشد.",
                "ویندوز رو ری‌استارت کن و دوباره امتحان کن؛ اگه درست نشد بهم بگو.",
            ),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        PreflightCheck::skipped(ID, NAME, "Windows-only check")
    }
}

// ---------------------------------------------------------------------------
// Windows helpers (compiled on the windows target; T1 CI verifies)
// ---------------------------------------------------------------------------

/// Minimal Win32 surface for the preflight: registry reads + free-space.
/// One small module, plain DWORD/HKEY/PCWSTR shapes only.
#[cfg(target_os = "windows")]
mod win32 {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::core::PCWSTR;
    use windows_sys::Win32::Foundation::{BOOL, HKEY};
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceW;
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryInfoKeyW, RegQueryValueExW, HKEY_CURRENT_USER,
        HKEY_LOCAL_MACHINE, KEY_READ, KEY_WOW64_32KEY, KEY_WOW64_64KEY, REG_DWORD, REG_EXPAND_SZ,
        REG_SZ,
    };

    fn wide(s: &str) -> Vec<u16> {
        OsStr::new(s).encode_wide().chain([0]).collect()
    }

    fn open(hive: HKEY, path: &str) -> Option<HKEY> {
        let wpath = wide(path);
        for view in [KEY_WOW64_64KEY, KEY_WOW64_32KEY] {
            let mut key: HKEY = 0;
            let rc = unsafe {
                RegOpenKeyExW(
                    hive,
                    PCWSTR(wpath.as_ptr()),
                    0,
                    KEY_READ | view,
                    &mut key,
                )
            };
            if rc == 0 && key != 0 {
                return Some(key);
            }
        }
        None
    }

    fn close(key: HKEY) {
        unsafe {
            RegCloseKey(key);
        }
    }

    fn get_string(key: HKEY, value: &str) -> Option<String> {
        let wvalue = wide(value);
        let mut ty: u32 = 0;
        let mut len: u32 = 0;
        // Size query first.
        let rc = unsafe {
            RegQueryValueExW(
                key,
                PCWSTR(wvalue.as_ptr()),
                std::ptr::null_mut(),
                &mut ty,
                std::ptr::null_mut(),
                &mut len,
            )
        };
        if rc != 0 || (ty != REG_SZ && ty != REG_EXPAND_SZ) || len == 0 || len % 2 != 0 {
            return None;
        }
        let mut buf = vec![0u16; (len / 2) as usize];
        let rc = unsafe {
            RegQueryValueExW(
                key,
                PCWSTR(wvalue.as_ptr()),
                std::ptr::null_mut(),
                &mut ty,
                buf.as_mut_ptr() as *mut u8,
                &mut len,
            )
        };
        if rc != 0 {
            return None;
        }
        let s = String::from_utf16_lossy(&buf);
        let s = s.trim_end_matches('\0').trim().to_string();
        if s.is_empty() {
            None
        } else {
            Some(s)
        }
    }

    fn get_dword(key: HKEY, value: &str) -> Option<u32> {
        let wvalue = wide(value);
        let mut ty: u32 = 0;
        let mut data: u32 = 0;
        let mut len: u32 = 4;
        let rc = unsafe {
            RegQueryValueExW(
                key,
                PCWSTR(wvalue.as_ptr()),
                std::ptr::null_mut(),
                &mut ty,
                &mut data as *mut u32 as *mut u8,
                &mut len,
            )
        };
        if rc == 0 && ty == REG_DWORD {
            Some(data)
        } else {
            None
        }
    }

    /// WebView2 registers its version under the EdgeUpdate ClientState key.
    pub fn webview2_version() -> Option<String> {
        const CLIENT_STATE: &str =
            r"SOFTWARE\Microsoft\EdgeUpdate\ClientState\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
        for hive in [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER] {
            if let Some(key) = open(hive, CLIENT_STATE) {
                let v = get_string(key, "pv");
                close(key);
                if v.is_some() {
                    return v;
                }
            }
        }
        None
    }

    pub fn vcredist_version() -> Option<String> {
        const KEY: &str = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64";
        let key = open(HKEY_LOCAL_MACHINE, KEY)?;
        let installed = get_dword(key, "Installed").unwrap_or(0);
        let version = get_string(key, "Version");
        close(key);
        if installed == 1 {
            Some(version.unwrap_or_else(|| "unknown".to_string()))
        } else {
            None
        }
    }

    /// Number of audio capture endpoints registered in MMDevices.
    /// Registry-level proxy: proves a mic was present; the first-run wizard
    /// performs the live WASAPI probe (formula W9: first-run mic wizard).
    pub fn capture_endpoint_count() -> Option<usize> {
        const KEY: &str = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture";
        let key = open(HKEY_LOCAL_MACHINE, KEY)?;
        let mut subkeys: u32 = 0;
        let rc = unsafe {
            RegQueryInfoKeyW(
                key,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut subkeys,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        };
        close(key);
        if rc == 0 {
            Some(subkeys as usize)
        } else {
            None
        }
    }

    /// Free bytes on the volume hosting `dir`, via GetDiskFreeSpaceW
    /// (DWORD-only shapes — no unions).
    pub fn free_bytes(dir: &std::path::Path) -> Option<u64> {
        // Walk up to the volume root (e.g. `C:\`).
        let root = dir
            .ancestors()
            .find(|a| {
                a.parent()
                    .map(|p| p.as_os_str().is_empty())
                    .unwrap_or(false)
            })
            .unwrap_or(dir);
        let wroot = wide(&root.to_string_lossy());
        let mut sectors_per_cluster: u32 = 0;
        let mut bytes_per_sector: u32 = 0;
        let mut free_clusters: u32 = 0;
        let mut _total_clusters: u32 = 0;
        let ok: BOOL = unsafe {
            GetDiskFreeSpaceW(
                PCWSTR(wroot.as_ptr()),
                &mut sectors_per_cluster,
                &mut bytes_per_sector,
                &mut free_clusters,
                &mut _total_clusters,
            )
        };
        if ok != 0 {
            Some(
                (sectors_per_cluster as u64)
                    .saturating_mul(bytes_per_sector as u64)
                    .saturating_mul(free_clusters as u64),
            )
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Tests (run on this VM via `cargo test`)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn five_checks_in_formula_order() {
        let checks = run_preflight();
        let ids: Vec<&str> = checks.iter().map(|c| c.id).collect();
        assert_eq!(
            ids,
            vec!["webview2", "vcredist", "disk", "mic", "localappdata"]
        );
    }

    #[test]
    fn disk_check_runs_for_real_on_this_machine() {
        let checks = run_preflight();
        let disk = checks.iter().find(|c| c.id == "disk").unwrap();
        // On this Linux VM the statvfs path must execute (Pass or Fail —
        // never Skipped, never a guess).
        assert_ne!(disk.status, CheckStatus::Skipped);
        assert!(!disk.detail_en.is_empty());
    }

    #[test]
    fn failures_carry_persian_strings() {
        // Every failing check must explain itself in Persian + offer a fix.
        for c in run_preflight() {
            if c.status == CheckStatus::Fail {
                assert!(
                    !c.explanation_fa.is_empty(),
                    "check {} failed without Persian explanation",
                    c.id
                );
                assert!(
                    !c.fix_fa.is_empty(),
                    "check {} failed without Persian fix",
                    c.id
                );
            }
        }
    }

    #[test]
    fn report_formats_and_writes() {
        let checks = run_preflight();
        let report = format_report(&checks);
        assert!(report.contains("GENESIS installer preflight"));
        assert!(report.contains("disk"));
        let path = write_report(&checks).expect("write_report failed");
        let back = std::fs::read_to_string(&path).expect("read back failed");
        assert_eq!(back, report);
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(path.parent().unwrap());
    }

    #[test]
    fn required_disk_constant_is_10gb() {
        assert_eq!(REQUIRED_DISK_FREE_BYTES, 10 * 1024 * 1024 * 1024);
    }

    #[test]
    fn all_pass_logic() {
        let checks = run_preflight();
        let expect = !checks.iter().any(|c| c.status == CheckStatus::Fail);
        assert_eq!(all_pass(&checks), expect);
    }
}
