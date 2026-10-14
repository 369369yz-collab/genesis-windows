//! Background station jobs — W1 pre-birth fix.
//!
//! Every background station job (workflow runs, schedulers, watchers) is
//! spawned at **BELOW_NORMAL** OS priority, so YZ's foreground — his games,
//! his work, and GENESIS's own UI/voice — always wins the CPU.
//!
//! Windows: the child is created with `BELOW_NORMAL_PRIORITY_CLASS`.
//! Unix:    the child is `nice`d +10 in a `pre_exec` hook (best effort —
//!          a failed `nice` never fails the spawn).

use std::process::{Child, Command};

/// Spawn a background station job at below-normal priority.
/// `program` + `args` are exactly what [`Command::new`] takes.
#[allow(dead_code)] // consumed by the station/module builders, not the shell
pub fn spawn_background(program: &str, args: &[&str]) -> std::io::Result<Child> {
    let mut cmd = Command::new(program);
    cmd.args(args);
    lower_priority(&mut cmd);
    cmd.spawn()
}

#[cfg(target_os = "windows")]
fn lower_priority(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x0000_4000;
    cmd.creation_flags(BELOW_NORMAL_PRIORITY_CLASS);
}

#[cfg(unix)]
fn lower_priority(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    // SAFETY: `pre_exec` runs after fork, before exec, in the child only.
    // `setpriority` is async-signal-safe; we ignore its return — a failed
    // nice must never kill the spawn.
    unsafe {
        cmd.pre_exec(|| {
            libc::setpriority(libc::PRIO_PROCESS, 0, 10);
            Ok(())
        });
    }
}

#[cfg(not(any(target_os = "windows", unix)))]
fn lower_priority(_cmd: &mut Command) {
    // No portable priority API here; the job still spawns.
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spawn_background_runs_true() {
        // Real spawn through the priority-lowering path (`true` exits 0).
        #[cfg(unix)]
        {
            let mut child = spawn_background("true", &[]).expect("spawn failed");
            let status = child.wait().expect("wait failed");
            assert!(status.success());
        }
    }
}
