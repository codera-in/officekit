//! Opens OfficeKit again after it crashes, when the user turns "Restart after a crash" on.
//!
//! launchd only restarts jobs it started itself, and OfficeKit is usually opened from the Dock, so a
//! `KeepAlive` on the app would not help. Instead a small per-user LaunchAgent runs a watcher script.
//! The app writes its pid to a lock file at launch and removes it on a normal exit. The watcher
//! restarts the app only when the lock is left behind by a dead process and macOS wrote a crash
//! report for it, so Quit and Force Quit never restart it. A crash loop stops after three restarts
//! in ten minutes. Nothing here reads or writes user data.

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

const LABEL: &str = "app.officekit.desktop.crash-restart";
const STATE_DIR: &str = "Library/Application Support/app.officekit.desktop/crash-watch";
const AGENTS_DIR: &str = "Library/LaunchAgents";
const REPORTS_DIR: &str = "Library/Logs/DiagnosticReports";
const APP_NAME: &str = "OfficeKit";

/// Paths under one home folder. Tests pass a temporary folder instead of the real one.
#[derive(Debug, Clone)]
pub struct Paths {
    pub lock: PathBuf,
    /// A copy of the lock the watcher leaves when it confirms a crash, before it clears the lock.
    pub crashed: PathBuf,
    pub script: PathBuf,
    pub plist: PathBuf,
    pub reports: PathBuf,
}

impl Paths {
    pub fn under(home: &Path) -> Self {
        let state = home.join(STATE_DIR);
        Self {
            lock: state.join("running.pid"),
            crashed: state.join("running.pid.crashed"),
            script: state.join("watch.sh"),
            plist: home.join(AGENTS_DIR).join(format!("{LABEL}.plist")),
            reports: home.join(REPORTS_DIR),
        }
    }

    fn from_env() -> Result<Self, String> {
        let home = std::env::var_os("HOME").ok_or("The home folder is unavailable")?;
        Ok(Self::under(Path::new(&home)))
    }
}

/// The watcher. Arguments: lock file, crash report folder, app name, opener command.
/// The environment variables shorten the waits so tests do not sit for twenty seconds.
pub fn watch_script() -> String {
    r#"#!/bin/sh
LOCK="$1"; REPORTS="$2"; APP="$3"; OPENER="${4:-open}"
STEPS="${OFFICEKIT_WATCH_STEPS:-10}"; STEP="${OFFICEKIT_WATCH_STEP:-2}"; IDLE="${OFFICEKIT_WATCH_IDLE:-5}"
RESTARTS="$LOCK.restarts"
while :; do
  if [ -f "$LOCK" ]; then
    pid=$(head -n 1 "$LOCK" 2>/dev/null)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      crashed=0; i=0
      while [ "$i" -lt "$STEPS" ]; do
        if [ -n "$(find "$REPORTS" -maxdepth 1 -name 'officekit*' -newer "$LOCK" 2>/dev/null | head -n 1)" ]; then crashed=1; break; fi
        sleep "$STEP"; i=$((i+1))
      done
      now=$(date +%s)
      recent=$(awk -v now="$now" 'now - $1 < 600' "$RESTARTS" 2>/dev/null)
      count=0; [ -n "$recent" ] && count=$(printf '%s\n' "$recent" | wc -l | tr -d ' ')
      [ "$crashed" = 1 ] && cp -p "$LOCK" "$LOCK.crashed" 2>/dev/null
      rm -f "$LOCK"
      if [ "$crashed" = 1 ] && [ "$count" -lt 3 ]; then
        { [ -n "$recent" ] && printf '%s\n' "$recent"; printf '%s\n' "$now"; } > "$RESTARTS"
        "$OPENER" -a "$APP"
      fi
    fi
  fi
  [ -n "$OFFICEKIT_WATCH_ONCE" ] && exit 0
  sleep "$IDLE"
done
"#
    .to_string()
}

pub fn plist(paths: &Paths) -> String {
    let arg = |value: &str| format!("    <string>{}</string>\n", xml_escape(value));
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n\
<plist version=\"1.0\">\n<dict>\n  <key>Label</key>\n  <string>{LABEL}</string>\n  <key>ProgramArguments</key>\n  <array>\n{}{}{}{}{}  </array>\n  <key>RunAtLoad</key>\n  <true/>\n  <key>KeepAlive</key>\n  <true/>\n  <key>ProcessType</key>\n  <string>Background</string>\n  <key>LimitLoadToSessionType</key>\n  <string>Aqua</string>\n</dict>\n</plist>\n",
        arg("/bin/sh"),
        arg(&paths.script.to_string_lossy()),
        arg(&paths.lock.to_string_lossy()),
        arg(&paths.reports.to_string_lossy()),
        arg(APP_NAME),
    )
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

pub fn is_enabled(paths: &Paths) -> bool {
    paths.plist.is_file()
}

/// Writes the watcher and its agent files. Does not talk to launchd.
pub fn write_files(paths: &Paths) -> Result<(), String> {
    let fail = |_| "The restart agent could not be written".to_string();
    for file in [&paths.script, &paths.plist] {
        if let Some(parent) = file.parent() {
            std::fs::create_dir_all(parent).map_err(|_| {
                format!(
                    "Could not turn this on: {} is not writable.",
                    parent.display()
                )
            })?;
        }
    }
    std::fs::write(&paths.script, watch_script()).map_err(fail)?;
    std::fs::write(&paths.plist, plist(paths)).map_err(fail)
}

pub fn remove_files(paths: &Paths) {
    let _ = std::fs::remove_file(&paths.plist);
    let _ = std::fs::remove_file(&paths.script);
    let _ = std::fs::remove_file(paths.lock.with_extension("pid.restarts"));
}

/// Records that the app is running. Called at launch.
pub fn mark_running(paths: &Paths) {
    if let Some(parent) = paths.lock.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    // Line 1 is the pid the watcher checks; line 2 names the version, so a later launch can say
    // which one closed.
    let _ = std::fs::write(
        &paths.lock,
        format!("{}\n{}", std::process::id(), env!("CARGO_PKG_VERSION")),
    );
}

/// A run that ended without a normal quit, as found at the next launch.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CrashNotice {
    /// The OfficeKit version that was running, when the lock says.
    pub version: Option<String>,
    /// When it was last seen running, in milliseconds since 1970. The heartbeat keeps this within
    /// a minute of the crash.
    pub closed_at_ms: Option<u64>,
}

fn read_notice(path: &Path) -> Option<(Option<u32>, CrashNotice)> {
    let text = std::fs::read_to_string(path).ok()?;
    let mut lines = text.lines();
    let pid = lines.next().and_then(|line| line.trim().parse().ok());
    let version = lines
        .next()
        .map(|line| crate::support_ticket::sanitize_field(line, "", 20, ".-"))
        .filter(|line| !line.is_empty());
    let closed_at_ms = std::fs::metadata(path)
        .and_then(|meta| meta.modified())
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|age| age.as_millis() as u64);
    Some((
        pid,
        CrashNotice {
            version,
            closed_at_ms,
        },
    ))
}

/// Finds out whether the previous run crashed, and clears the evidence so it is told once.
/// Two signs: the watcher's confirmed-crash copy of the lock, or a lock still on disk whose
/// process is gone (the watcher is off, or has not looked yet). A force quit also leaves the
/// second sign, which is why the notice only offers a report and never sends one.
pub fn take_previous_crash(
    paths: &Paths,
    own_pid: u32,
    is_alive: impl Fn(u32) -> bool,
) -> Option<CrashNotice> {
    let confirmed = read_notice(&paths.crashed);
    let _ = std::fs::remove_file(&paths.crashed);
    if let Some((_, notice)) = confirmed {
        return Some(notice);
    }
    let (pid, notice) = read_notice(&paths.lock)?;
    match pid {
        Some(pid) if pid != own_pid && !is_alive(pid) => Some(notice),
        _ => None,
    }
}

#[cfg(unix)]
fn process_is_alive(pid: u32) -> bool {
    std::process::Command::new("/bin/kill")
        .args(["-0", &pid.to_string()])
        .output()
        .map(|out| out.status.success())
        .unwrap_or(true)
}

#[cfg(not(unix))]
fn process_is_alive(_pid: u32) -> bool {
    true
}

/// Touches the lock so its modified time tracks the last moment the app was running. Returns
/// false once the lock is gone or belongs to another process, which ends the heartbeat.
pub fn heartbeat(paths: &Paths) -> bool {
    let ours = std::fs::read_to_string(&paths.lock).ok().and_then(|text| {
        text.lines()
            .next()
            .and_then(|line| line.trim().parse().ok())
    }) == Some(std::process::id());
    ours && std::fs::OpenOptions::new()
        .write(true)
        .open(&paths.lock)
        .and_then(|file| file.set_modified(std::time::SystemTime::now()))
        .is_ok()
}

const HEARTBEAT_SECONDS: u64 = 60;

static PENDING: Mutex<Option<CrashNotice>> = Mutex::new(None);

fn pending() -> std::sync::MutexGuard<'static, Option<CrashNotice>> {
    PENDING
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Records a normal exit, so the watcher does not treat it as a crash.
pub fn mark_clean_exit(paths: &Paths) {
    let _ = std::fs::remove_file(&paths.lock);
}

pub fn startup() {
    if let Ok(paths) = Paths::from_env() {
        // Look before mark_running overwrites the evidence.
        *pending() = take_previous_crash(&paths, std::process::id(), process_is_alive);
        mark_running(&paths);
        std::thread::spawn(move || {
            while {
                std::thread::sleep(std::time::Duration::from_secs(HEARTBEAT_SECONDS));
                heartbeat(&paths)
            } {}
        });
    }
}

/// What the "OfficeKit closed unexpectedly" dialog shows. No file names or contents.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CrashNoticeView {
    #[serde(flatten)]
    pub notice: CrashNotice,
    pub macos: Option<String>,
    /// Whether "Restart after a crash" is already on, so the dialog can leave out the checkbox.
    pub restart_enabled: bool,
}

#[tauri::command]
pub fn crash_notice_pending() -> Option<CrashNoticeView> {
    let notice = pending().clone()?;
    let macos = std::process::Command::new("/usr/bin/sw_vers")
        .arg("-productVersion")
        .output()
        .ok()
        .map(|out| String::from_utf8_lossy(&out.stdout).to_string())
        .map(|text| crate::support_ticket::sanitize_field(&text, "", 20, "."))
        .filter(|text| !text.is_empty());
    let restart_enabled = Paths::from_env()
        .map(|paths| is_enabled(&paths))
        .unwrap_or(false);
    Some(CrashNoticeView {
        notice,
        macos,
        restart_enabled,
    })
}

/// The person pressed Not now or the report went out: do not show the notice again.
#[tauri::command]
pub fn crash_notice_dismiss() {
    *pending() = None;
}

pub fn shutdown() {
    if let Ok(paths) = Paths::from_env() {
        mark_clean_exit(&paths);
    }
}

#[cfg(target_os = "macos")]
fn launchctl(args: &[&str]) -> bool {
    std::process::Command::new("/bin/launchctl")
        .args(args)
        .output()
        .map(|out| out.status.success())
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn user_domain() -> Result<String, String> {
    let out = std::process::Command::new("/usr/bin/id")
        .arg("-u")
        .output()
        .map_err(|_| "The user id is unavailable".to_string())?;
    let uid = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if uid.is_empty() || !uid.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("The user id is unavailable".to_string());
    }
    Ok(format!("gui/{uid}"))
}

#[tauri::command]
pub fn crash_restart_status() -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    return Ok(is_enabled(&Paths::from_env()?));
    #[cfg(not(target_os = "macos"))]
    Err("Restart after a crash is supported on macOS in this build".to_string())
}

#[tauri::command]
pub fn crash_restart_set(enabled: bool) -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    {
        let paths = Paths::from_env()?;
        let domain = user_domain()?;
        let plist_path = paths.plist.to_string_lossy().to_string();
        // Always unload first: loading an already loaded label fails.
        launchctl(&["bootout", &format!("{domain}/{LABEL}")]);
        if enabled {
            write_files(&paths)?;
            if !launchctl(&["bootstrap", &domain, &plist_path]) {
                remove_files(&paths);
                return Err(
                    "macOS would not load the restart agent. Nothing was changed.".to_string(),
                );
            }
        } else {
            remove_files(&paths);
        }
        Ok(enabled)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = enabled;
        Err("Restart after a crash is supported on macOS in this build".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    fn temp_home(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("officekit-crash-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn plist_runs_the_watcher_with_the_lock_and_report_folders() {
        let paths = Paths::under(Path::new("/Users/a&b"));
        let text = plist(&paths);
        assert!(text.contains(&format!("<string>{LABEL}</string>")));
        assert!(text.contains("<string>/bin/sh</string>"));
        assert!(text.contains("running.pid</string>"));
        assert!(text.contains("Library/Logs/DiagnosticReports</string>"));
        assert!(text.contains("/Users/a&amp;b/"), "paths are XML escaped");
        assert!(!text.contains("a&b"));
    }

    #[test]
    fn write_and_remove_files_toggle_the_enabled_state() {
        let home = temp_home("toggle");
        let paths = Paths::under(&home);
        assert!(!is_enabled(&paths));
        write_files(&paths).unwrap();
        assert!(is_enabled(&paths));
        assert!(std::fs::read_to_string(&paths.script)
            .unwrap()
            .starts_with("#!/bin/sh"));
        remove_files(&paths);
        assert!(!is_enabled(&paths));
        assert!(!paths.script.exists());
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn write_files_reports_an_unwritable_folder_and_changes_nothing() {
        let home = temp_home("blocked");
        std::fs::write(home.join("Library"), "a file where a folder should be").unwrap();
        let paths = Paths::under(&home);
        let message = write_files(&paths).unwrap_err();
        assert!(message.starts_with("Could not turn this on:"), "{message}");
        assert!(!is_enabled(&paths));
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn running_and_clean_exit_manage_the_lock() {
        let home = temp_home("lock");
        let paths = Paths::under(&home);
        mark_running(&paths);
        assert_eq!(
            std::fs::read_to_string(&paths.lock).unwrap(),
            format!("{}\n{}", std::process::id(), env!("CARGO_PKG_VERSION"))
        );
        mark_clean_exit(&paths);
        assert!(!paths.lock.exists());
        mark_clean_exit(&paths);
        std::fs::remove_dir_all(&home).unwrap();
    }

    /// Runs one pass of the real watcher script with a stub opener that records each call.
    fn run_watcher(home: &Path, pid: &str, report: bool, prior_restarts: &str) -> usize {
        let paths = Paths::under(home);
        std::fs::create_dir_all(&paths.reports).unwrap();
        mark_running(&paths);
        std::fs::write(&paths.lock, pid).unwrap();
        if !prior_restarts.is_empty() {
            std::fs::write(format!("{}.restarts", paths.lock.display()), prior_restarts).unwrap();
        }
        if report {
            std::thread::sleep(std::time::Duration::from_millis(1100));
            std::fs::write(paths.reports.join("officekit-2026-11-04.ips"), "x").unwrap();
        }
        let log = home.join("opens.log");
        let opener = home.join("opener.sh");
        std::fs::write(
            &opener,
            format!("#!/bin/sh\necho \"$@\" >> '{}'\n", log.display()),
        )
        .unwrap();
        Command::new("chmod")
            .arg("+x")
            .arg(&opener)
            .status()
            .unwrap();
        std::fs::write(&paths.script, watch_script()).unwrap();
        let status = Command::new("/bin/sh")
            .arg(&paths.script)
            .arg(&paths.lock)
            .arg(&paths.reports)
            .arg(APP_NAME)
            .arg(&opener)
            .env("OFFICEKIT_WATCH_ONCE", "1")
            .env("OFFICEKIT_WATCH_STEPS", "2")
            .env("OFFICEKIT_WATCH_STEP", "0.1")
            .status()
            .unwrap();
        assert!(status.success());
        assert!(!paths.lock.exists(), "the stale lock is always cleared");
        std::fs::read_to_string(&log)
            .map(|text| text.lines().count())
            .unwrap_or(0)
    }

    fn dead_pid() -> String {
        // A pid that no process holds: spawn a child, let it exit, reuse its number.
        let mut child = Command::new("/usr/bin/true").spawn().unwrap();
        let pid = child.id();
        child.wait().unwrap();
        pid.to_string()
    }

    fn write_lock(paths: &Paths, body: &str) {
        std::fs::create_dir_all(paths.lock.parent().unwrap()).unwrap();
        std::fs::write(&paths.lock, body).unwrap();
    }

    #[test]
    fn a_dead_pid_in_the_lock_is_reported_with_its_version_and_time() {
        let home = temp_home("notice-lock");
        let paths = Paths::under(&home);
        write_lock(&paths, "4242\n1.0.112\n");
        let notice = take_previous_crash(&paths, 1, |_| false).unwrap();
        assert_eq!(notice.version.as_deref(), Some("1.0.112"));
        assert!(notice.closed_at_ms.unwrap() > 1_700_000_000_000);
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn no_notice_for_a_clean_exit_a_live_process_or_our_own_pid() {
        let home = temp_home("notice-none");
        let paths = Paths::under(&home);
        assert_eq!(take_previous_crash(&paths, 1, |_| false), None, "no lock");
        write_lock(&paths, "4242\n1.0.112");
        assert_eq!(
            take_previous_crash(&paths, 1, |_| true),
            None,
            "still running"
        );
        assert_eq!(
            take_previous_crash(&paths, 4242, |_| false),
            None,
            "our own pid"
        );
        write_lock(&paths, "not a pid");
        assert_eq!(
            take_previous_crash(&paths, 1, |_| false),
            None,
            "unreadable pid"
        );
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn the_watchers_confirmed_copy_wins_is_told_once_and_survives_a_missing_version() {
        let home = temp_home("notice-marker");
        let paths = Paths::under(&home);
        write_lock(&paths, "4242\n1.0.112");
        std::fs::write(&paths.crashed, "4242\nweird version!!\n").unwrap();
        let notice = take_previous_crash(&paths, 1, |_| true).unwrap();
        assert_eq!(notice.version.as_deref(), Some("weirdversion"));
        assert!(!paths.crashed.exists(), "told once");
        std::fs::write(&paths.crashed, "4242").unwrap();
        assert_eq!(
            take_previous_crash(&paths, 1, |_| true).unwrap().version,
            None
        );
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn the_heartbeat_moves_the_lock_time_and_stops_when_the_lock_goes() {
        let home = temp_home("heartbeat");
        let paths = Paths::under(&home);
        assert!(!heartbeat(&paths), "no lock");
        mark_running(&paths);
        let old = std::time::SystemTime::now() - std::time::Duration::from_secs(3600);
        std::fs::File::options()
            .write(true)
            .open(&paths.lock)
            .unwrap()
            .set_modified(old)
            .unwrap();
        assert!(heartbeat(&paths));
        let after = std::fs::metadata(&paths.lock).unwrap().modified().unwrap();
        assert!(after > old + std::time::Duration::from_secs(3000));
        write_lock(&paths, "1\n1.0.1");
        assert!(!heartbeat(&paths), "another process owns the lock");
        mark_clean_exit(&paths);
        assert!(!heartbeat(&paths));
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn the_notice_serializes_in_camel_case_for_the_page() {
        let view = CrashNoticeView {
            notice: CrashNotice {
                version: Some("1.0.112".into()),
                closed_at_ms: Some(5),
            },
            macos: Some("27.2.1".into()),
            restart_enabled: true,
        };
        assert_eq!(
            serde_json::to_string(&view).unwrap(),
            r#"{"version":"1.0.112","closedAtMs":5,"macos":"27.2.1","restartEnabled":true}"#
        );
    }

    #[test]
    fn watcher_leaves_a_confirmed_crash_for_the_next_launch_but_not_a_kill() {
        let crashed = temp_home("watch-marker");
        run_watcher(&crashed, &dead_pid(), true, "");
        assert!(Paths::under(&crashed).crashed.exists());
        let killed = temp_home("watch-nomarker");
        run_watcher(&killed, &dead_pid(), false, "");
        assert!(!Paths::under(&killed).crashed.exists());
        std::fs::remove_dir_all(&crashed).unwrap();
        std::fs::remove_dir_all(&killed).unwrap();
    }

    #[test]
    fn watcher_restarts_after_a_crash_report_but_not_after_a_kill() {
        let crashed = temp_home("watch-crash");
        assert_eq!(run_watcher(&crashed, &dead_pid(), true, ""), 1);
        let killed = temp_home("watch-kill");
        assert_eq!(run_watcher(&killed, &dead_pid(), false, ""), 0);
        std::fs::remove_dir_all(&crashed).unwrap();
        std::fs::remove_dir_all(&killed).unwrap();
    }

    #[test]
    fn watcher_leaves_a_running_app_alone_and_stops_a_crash_loop() {
        let running = temp_home("watch-running");
        let me = std::process::id().to_string();
        let paths = Paths::under(&running);
        std::fs::create_dir_all(&paths.reports).unwrap();
        mark_running(&paths);
        std::fs::write(&paths.script, watch_script()).unwrap();
        let status = Command::new("/bin/sh")
            .arg(&paths.script)
            .arg(&paths.lock)
            .arg(&paths.reports)
            .arg(APP_NAME)
            .env("OFFICEKIT_WATCH_ONCE", "1")
            .status()
            .unwrap();
        assert!(status.success());
        assert_eq!(
            std::fs::read_to_string(&paths.lock)
                .unwrap()
                .lines()
                .next()
                .unwrap(),
            me,
            "a live pid keeps its lock"
        );
        std::fs::remove_dir_all(&running).unwrap();

        let looping = temp_home("watch-loop");
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let recent = format!("{}\n{}\n{}\n", now - 30, now - 20, now - 10);
        assert_eq!(run_watcher(&looping, &dead_pid(), true, &recent), 0);
        std::fs::remove_dir_all(&looping).unwrap();
    }
}
