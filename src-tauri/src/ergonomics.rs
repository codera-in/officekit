//! Opt-in reminders. The pure clock-driven core never calls the window or motion bridges.
use crate::call_detect;
use crate::headphone_motion::{self, MotionSnapshot};
use crate::meeting_calendar::{self, CalendarCore, CalendarSnapshot, MeetingSettings};
use chrono::Timelike;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, OnceLock,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter, Manager, Runtime as TauriRuntime};
const KINDS: [&str; 3] = ["break", "eyes", "water"];
const READY_SECONDS: u64 = 60;
const ACTIVE_INPUT_WINDOW_SECONDS: f64 = 300.0;
// A wellness reminder fades in over the last two minutes before it is due, a meeting over the
// 25 minutes from 30 to 5 minutes out. The bubble is not shown below 5% so it never blocks a click.
const TEASER_SECONDS: u64 = 120;
const TEASER_VISIBLE_SECONDS: u64 = TEASER_SECONDS * 95 / 100;
const MEETING_FULL_SECONDS: u64 = 5 * 60;
const MEETING_VISIBLE_SECONDS: u64 =
    MEETING_FULL_SECONDS + (meeting_calendar::LEAD_SECONDS - MEETING_FULL_SECONDS) * 95 / 100;
const HEAD_ANGLE_DEGREES: f64 = 15.0;
const HEAD_RECOVERY_DEGREES: f64 = 5.0;
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReminderSettings {
    pub enabled: bool,
    pub interval_minutes: u32,
    pub duration_seconds: u32,
    pub snooze_minutes: u32,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PostureSettings {
    pub enabled: bool,
    pub dwell_seconds: u32,
    pub cooldown_minutes: u32,
    pub snooze_minutes: u32,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuietHours {
    pub enabled: bool,
    pub start_minutes: u16,
    pub end_minutes: u16,
}
impl QuietHours {
    fn contains(&self, m: u16) -> bool {
        self.enabled
            && if self.start_minutes < self.end_minutes {
                m >= self.start_minutes && m < self.end_minutes
            } else {
                m >= self.start_minutes || m < self.end_minutes
            }
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Settings {
    pub version: u8,
    pub corner: String,
    pub reduced_motion: bool,
    pub quiet_hours: QuietHours,
    pub breaks: ReminderSettings,
    pub eyes: ReminderSettings,
    pub water: ReminderSettings,
    pub posture: PostureSettings,
    #[serde(default)]
    pub meetings: MeetingSettings,
    #[serde(default)]
    pub quick_controls_paused: bool,
}
impl Default for Settings {
    fn default() -> Self {
        let r = |interval_minutes, duration_seconds| ReminderSettings {
            enabled: false,
            interval_minutes,
            duration_seconds,
            snooze_minutes: 5,
        };
        Self {
            version: 1,
            corner: "bottom-right".into(),
            reduced_motion: false,
            quiet_hours: QuietHours {
                enabled: true,
                start_minutes: 1320,
                end_minutes: 480,
            },
            breaks: r(50, 120),
            eyes: r(20, 20),
            water: r(60, 0),
            posture: PostureSettings {
                enabled: false,
                dwell_seconds: 20,
                cooldown_minutes: 5,
                snooze_minutes: 5,
            },
            meetings: MeetingSettings::default(),
            quick_controls_paused: false,
        }
    }
}
impl Settings {
    fn validate(&self) -> Result<(), String> {
        self.meetings.validate()?;
        if self.version != 1
            || !["top-left", "top-right", "bottom-left", "bottom-right"]
                .contains(&self.corner.as_str())
        {
            return Err("Unsupported reminder settings version or corner".into());
        }
        if self.quiet_hours.start_minutes > 1439
            || self.quiet_hours.end_minutes > 1439
            || self.quiet_hours.start_minutes == self.quiet_hours.end_minutes
        {
            return Err("Quiet hours need distinct start/end times within the day".into());
        }
        for (r, max, dmin, dmax) in [
            (&self.breaks, 180, 20, 900),
            (&self.eyes, 120, 10, 120),
            (&self.water, 240, 0, 0),
        ] {
            if !(5..=max).contains(&r.interval_minutes)
                || !(dmin..=dmax).contains(&r.duration_seconds)
                || !(1..=60).contains(&r.snooze_minutes)
            {
                return Err("Reminder interval, duration, or snooze is out of range".into());
            }
        }
        if !(5..=120).contains(&self.posture.dwell_seconds)
            || !(1..=60).contains(&self.posture.cooldown_minutes)
            || !(1..=60).contains(&self.posture.snooze_minutes)
        {
            return Err("Posture timing is out of range".into());
        }
        Ok(())
    }
    fn reminders(&self) -> [&ReminderSettings; 3] {
        [&self.breaks, &self.eyes, &self.water]
    }
}
fn safe_restart_settings(mut settings: Settings) -> Settings {
    // Headphone sensing is a separate permissioned opt-in for every app session.
    settings.posture.enabled = false;
    settings
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Prompt {
    pub id: String,
    pub kind: String,
    pub phase: String,
    pub remaining_seconds: Option<u64>,
    pub preview: bool,
    /// A meeting or call is under way and the person can press Record to start a local transcript.
    pub record_offer: bool,
    /// For kind "call": the call app's name, or None when only a browser holds the microphone.
    pub call_app: Option<String>,
    #[serde(skip)]
    deadline: u64,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NextDue {
    kind: String,
    seconds: Option<u64>,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    settings: Settings,
    activity_supported: bool,
    paused_remaining_seconds: Option<u64>,
    next_due: Vec<NextDue>,
    prompt: Option<Prompt>,
    motion: MotionSnapshot,
    error: Option<String>,
    calendar: Option<CalendarSnapshot>,
}
struct Core {
    settings: Settings,
    due: [Option<u64>; 3],
    prompt: Option<Prompt>,
    paused_until: Option<u64>,
    last_tick: u64,
    last_wall: Option<u64>,
    quiet: bool,
    dwell_since: Option<u64>,
    posture_after: u64,
    active_input: bool,
    error: Option<String>,
}
impl Core {
    fn new(settings: Settings, now: u64) -> Self {
        let mut s = Self {
            settings,
            due: [None; 3],
            prompt: None,
            paused_until: None,
            last_tick: now,
            last_wall: None,
            quiet: false,
            dwell_since: None,
            posture_after: now,
            active_input: true,
            error: None,
        };
        s.rearm(now);
        s
    }
    fn rearm(&mut self, now: u64) {
        for (i, r) in self.settings.reminders().iter().enumerate() {
            self.due[i] = (!self.settings.quick_controls_paused && r.enabled)
                .then_some(now + u64::from(r.interval_minutes) * 60);
        }
        self.dwell_since = None;
        self.posture_after = now + u64::from(self.settings.posture.cooldown_minutes) * 60;
    }
    fn set_settings(&mut self, s: Settings, now: u64) {
        for (i, (old, new)) in self
            .settings
            .reminders()
            .iter()
            .zip(s.reminders())
            .enumerate()
        {
            if *old != new {
                self.due[i] = new
                    .enabled
                    .then_some(now + u64::from(new.interval_minutes) * 60);
            }
        }
        if self.settings.posture != s.posture {
            self.dwell_since = None;
            self.posture_after = now;
        }
        if self.settings.quiet_hours != s.quiet_hours {
            self.prompt = None;
        }
        let quick_pause_changed = self.settings.quick_controls_paused != s.quick_controls_paused;
        self.settings = s;
        if quick_pause_changed {
            self.prompt = None;
            self.rearm(now);
        }
        if let Some(p) = &self.prompt {
            let disabled = KINDS
                .iter()
                .position(|k| *k == p.kind)
                .map(|i| !self.settings.reminders()[i].enabled)
                .unwrap_or(!self.settings.posture.enabled);
            if disabled && !p.preview {
                self.prompt = None;
            }
        }
    }
    fn open(&mut self, kind: &str, now: u64, preview: bool) {
        self.prompt = Some(Prompt {
            id: uuid::Uuid::new_v4().to_string(),
            kind: kind.into(),
            phase: "ready".into(),
            remaining_seconds: None,
            preview,
            record_offer: false,
            call_app: None,
            deadline: now + READY_SECONDS,
        });
    }
    fn observe_wall(&mut self, wall: u64, now: u64) {
        // On macOS Instant excludes sleep. Wall time is solely a wake/clock-change
        // detector; every actual reminder deadline stays on the monotonic clock.
        if self
            .last_wall
            .is_some_and(|last| wall < last || wall.saturating_sub(last) > 60)
        {
            self.rearm(now);
            if !self.prompt.as_ref().is_some_and(|p| p.preview) {
                self.prompt = None;
            }
        }
        self.last_wall = Some(wall);
    }
    #[cfg(test)]
    fn tick(&mut self, now: u64, minute: u16, motion: Option<&MotionSnapshot>) {
        self.tick_with_activity(now, minute, motion, true);
    }
    fn tick_with_activity(
        &mut self,
        now: u64,
        minute: u16,
        motion: Option<&MotionSnapshot>,
        active_input: bool,
    ) {
        self.active_input = active_input;
        let elapsed = now.saturating_sub(self.last_tick);
        let gap = elapsed > 60 || now < self.last_tick;
        self.last_tick = now;
        if self.settings.quick_controls_paused {
            self.prompt = None;
            self.dwell_since = None;
            return;
        }
        let quiet = self.settings.quiet_hours.contains(minute);
        let pause = self.paused_until.is_some_and(|p| p > now);
        let resumed = self.paused_until.is_some() && !pause;
        if resumed {
            self.paused_until = None;
        }
        if gap || quiet != self.quiet || resumed {
            self.rearm(now);
            if !self
                .prompt
                .as_ref()
                .is_some_and(|p| p.preview || (!active_input && !resumed && !quiet))
            {
                self.prompt = None;
            }
        }
        self.quiet = quiet;
        // Automatic prompts and their exercise timers pause while the user is away.
        // Extend the deadline by elapsed wall time so returning activity resumes the
        // same prompt instead of expiring it invisibly. Manual previews keep running.
        if !active_input && !quiet && !pause && !resumed {
            if let Some(p) = self.prompt.as_mut().filter(|p| !p.preview) {
                p.deadline = p.deadline.saturating_add(elapsed);
                if p.phase == "active" {
                    p.remaining_seconds = Some(p.deadline.saturating_sub(now));
                }
            }
        }
        if let Some(p) = &mut self.prompt {
            if p.phase == "active" && (active_input || p.preview) {
                p.remaining_seconds = Some(p.deadline.saturating_sub(now));
                if now >= p.deadline {
                    p.phase = "complete".into();
                    p.deadline = now + READY_SECONDS;
                    p.remaining_seconds = None;
                }
            } else if now >= p.deadline && (active_input || p.preview) {
                let kind = p.kind.clone();
                let preview = p.preview;
                self.prompt = None;
                if !preview {
                    self.rearm_kind(&kind, now, false);
                }
            }
        }
        if quiet || pause || gap || resumed {
            return;
        }
        if active_input && self.prompt.is_none() {
            if let Some(i) = self.due.iter().position(|d| d.is_some_and(|d| now >= d)) {
                self.coalesce_overdue(now);
                self.open(KINDS[i], now, false);
            }
        }
        let eligible = active_input
            .then_some(motion)
            .flatten()
            .filter(|m| {
                self.settings.posture.enabled && m.status == "ready" && m.calibrated && m.stable
            })
            .and_then(|m| {
                Some(
                    m.relative_pitch_degrees?
                        .abs()
                        .max(m.relative_roll_degrees?.abs()),
                )
            })
            .filter(|a| a.is_finite());
        match eligible {
            Some(angle) if angle >= HEAD_ANGLE_DEGREES => {
                let since = *self.dwell_since.get_or_insert(now);
                if now >= self.posture_after
                    && now.saturating_sub(since) >= u64::from(self.settings.posture.dwell_seconds)
                    && self.prompt.is_none()
                {
                    self.coalesce_overdue(now);
                    self.open("posture", now, false);
                    self.posture_after =
                        now + u64::from(self.settings.posture.cooldown_minutes) * 60;
                    self.dwell_since = None;
                }
            }
            Some(angle) if angle > HEAD_RECOVERY_DEGREES => {}
            _ => self.dwell_since = None,
        }
    }
    fn coalesce_overdue(&mut self, now: u64) {
        for i in 0..self.due.len() {
            if self.due[i].is_some_and(|deadline| now >= deadline) {
                self.rearm_kind(KINDS[i], now, false);
            }
        }
        if self.settings.posture.enabled && now >= self.posture_after {
            self.posture_after = now + u64::from(self.settings.posture.cooldown_minutes) * 60;
        }
    }
    fn rearm_kind(&mut self, kind: &str, now: u64, snooze: bool) {
        if let Some(i) = KINDS.iter().position(|k| *k == kind) {
            let r = self.settings.reminders()[i];
            self.due[i] = r.enabled.then_some(
                now + u64::from(if snooze {
                    r.snooze_minutes
                } else {
                    r.interval_minutes
                }) * 60,
            );
        } else {
            self.posture_after = now
                + u64::from(if snooze {
                    self.settings.posture.snooze_minutes
                } else {
                    self.settings.posture.cooldown_minutes
                }) * 60;
            self.dwell_since = None;
        }
    }
    fn action(&mut self, id: &str, action: &str, now: u64) -> Result<(), String> {
        if ["pause", "resume", "close-preview"].contains(&action) && id.is_empty() {
            match action {
                "pause" => {
                    self.paused_until = Some(now + 3600);
                    self.prompt = None;
                    self.rearm(now);
                }
                "resume" => {
                    self.paused_until = None;
                    self.rearm(now);
                }
                _ => {
                    if self.prompt.as_ref().is_some_and(|p| p.preview) {
                        self.prompt = None;
                    }
                }
            }
            return Ok(());
        }
        // A reminder that is still fading in is not stored; closing it moves that kind to its normal interval.
        if action == "dismiss" && self.prompt.is_none() {
            if let Some(kind) = id.strip_prefix("teaser-") {
                if self.teaser(now).is_some_and(|t| t.id == id) {
                    self.rearm_kind(kind, now, false);
                    return Ok(());
                }
            }
        }
        let p = self
            .prompt
            .as_ref()
            .filter(|p| p.id == id)
            .ok_or("This reminder has expired; use the current reminder")?
            .clone();
        match action {
            "start" if p.phase == "ready" => {
                let duration = KINDS
                    .iter()
                    .position(|k| *k == p.kind)
                    .map(|i| self.settings.reminders()[i].duration_seconds)
                    .unwrap_or(0);
                let q = self.prompt.as_mut().unwrap();
                q.phase = if duration == 0 { "complete" } else { "active" }.into();
                q.deadline = now
                    + if duration == 0 {
                        READY_SECONDS
                    } else {
                        u64::from(duration)
                    };
                q.remaining_seconds = (duration > 0).then_some(u64::from(duration));
            }
            "done" | "snooze" | "dismiss" => {
                if action == "done" && p.phase == "active" {
                    return Err("Finish the countdown before marking this break done".into());
                }
                self.prompt = None;
                if !p.preview {
                    self.rearm_kind(&p.kind, now, action == "snooze");
                }
            }
            _ => return Err("Unsupported reminder action or phase".into()),
        }
        Ok(())
    }
    /// The soonest reminder that is due within the teaser window, shown fading in before it opens.
    /// It is computed per snapshot, never stored, so it cannot be acted on or outlive its due time.
    fn teaser(&self, now: u64) -> Option<Prompt> {
        if self.prompt.is_some() || !self.active_input || self.quiet || self.paused_until.is_some()
        {
            return None;
        }
        let (index, left) = self
            .due
            .iter()
            .enumerate()
            .filter_map(|(i, d)| Some((i, (*d)?.checked_sub(now)?)))
            .filter(|(_, left)| (1..=TEASER_VISIBLE_SECONDS).contains(left))
            .min_by_key(|(_, left)| *left)?;
        Some(Prompt {
            id: format!("teaser-{}", KINDS[index]),
            kind: KINDS[index].into(),
            phase: "teaser".into(),
            remaining_seconds: Some(left),
            preview: false,
            record_offer: false,
            call_app: None,
            deadline: 0,
        })
    }
    fn snapshot(&self, now: u64, motion: MotionSnapshot) -> Snapshot {
        Snapshot {
            settings: self.settings.clone(),
            activity_supported: cfg!(target_os = "macos"),
            paused_remaining_seconds: self.paused_until.map(|t| t.saturating_sub(now)),
            next_due: KINDS
                .iter()
                .enumerate()
                .map(|(i, k)| NextDue {
                    kind: (*k).into(),
                    seconds: if self.quiet || self.paused_until.is_some() {
                        None
                    } else {
                        self.due[i].map(|d| d.saturating_sub(now))
                    },
                })
                .chain(std::iter::once(NextDue {
                    kind: "posture".into(),
                    seconds: if self.quiet
                        || self.paused_until.is_some()
                        || !self.settings.posture.enabled
                    {
                        None
                    } else {
                        Some(self.posture_after.saturating_sub(now))
                    },
                }))
                .collect(),
            prompt: self
                .prompt
                .as_ref()
                .filter(|p| p.preview || self.active_input)
                .cloned()
                .or_else(|| self.teaser(now)),
            motion,
            error: self.error.clone(),
            calendar: None,
        }
    }
}
fn now() -> u64 {
    static ORIGIN: OnceLock<Instant> = OnceLock::new();
    ORIGIN.get_or_init(Instant::now).elapsed().as_secs()
}
fn wall_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn minute() -> u16 {
    let t = chrono::Local::now();
    (t.hour() * 60 + t.minute()) as u16
}
fn load(path: &Path) -> (Settings, Option<String>) {
    if let Ok(meta) = fs::symlink_metadata(path) {
        if !meta.is_file() || meta.len() > 16384 {
            return (Settings::default(), Some("Reminder settings must be a regular file under 16 KiB. Review the app-data file and save settings to repair it.".into()));
        }
    }
    interpret_settings_read(fs::read(path))
}
fn interpret_settings_read(read: std::io::Result<Vec<u8>>) -> (Settings, Option<String>) {
    match read {
        Ok(bytes) => {
            if bytes.len() > 16384 {
                return (
                    Settings::default(),
                    Some(
                        "Reminder settings are too large. Save settings to repair the file.".into(),
                    ),
                );
            }
            match serde_json::from_slice::<Settings>(&bytes)
                .and_then(|s| s.validate().map(|_| s).map_err(serde::de::Error::custom))
            {
                Ok(s) => (s, None),
                Err(_) => (
                    Settings::default(),
                    Some(
                        "Reminder settings are invalid. Review and save settings to repair them."
                            .into(),
                    ),
                ),
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (Settings::default(), None),
        Err(_) => (
            Settings::default(),
            Some("Cannot read reminder settings. Check OfficeKit app-data permissions.".into()),
        ),
    }
}
fn save(path: &Path, s: &Settings) -> Result<(), String> {
    s.validate()?;
    let bytes = serde_json::to_vec(s).map_err(|_| "Cannot encode reminder settings")?;
    if bytes.len() > 16384 {
        return Err("Reminder settings exceed 16 KiB; select fewer calendars".into());
    }
    let parent = path.parent().ok_or("Missing settings directory")?;
    fs::create_dir_all(parent)
        .map_err(|_| "Cannot create reminder settings directory; check permissions")?;
    let tmp = parent.join(format!(".ergonomics-{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&tmp)
            .map_err(|_| "Cannot write reminder settings; check app-data permissions")?;
        file.write_all(&bytes)
            .map_err(|_| "Cannot write reminder settings")?;
        file.sync_all()
            .map_err(|_| "Cannot flush reminder settings")?;
        fs::rename(&tmp, path)
            .map_err(|_| "Cannot replace reminder settings; check app-data permissions")?;
        Ok(())
    })();
    let _ = fs::remove_file(&tmp);
    result
}
pub struct Runtime {
    core: Arc<Mutex<Core>>,
    delivery: Arc<Mutex<()>>,
    path: Option<PathBuf>,
    stop: Arc<AtomicBool>,
    motion_enabled: AtomicBool,
    calendar: Arc<Mutex<CalendarCore>>,
}
fn authorize<R: TauriRuntime>(window: &tauri::WebviewWindow<R>) -> Result<(), String> {
    if !crate::ergonomics_access::profile_enabled(env!("OFFICEKIT_RELEASE_PROFILE"))
        || !["main", "ergonomics"].contains(&window.label())
    {
        return Err("Ergonomics is not available in this build".into());
    }
    Ok(())
}
fn authorize_main<R: TauriRuntime>(window: &tauri::WebviewWindow<R>) -> Result<(), String> {
    authorize(window)?;
    if window.label() != "main" {
        return Err("Open reminder settings in the main OfficeKit window".into());
    }
    Ok(())
}
fn authorize_quick_controls<R: TauriRuntime>(
    window: &tauri::WebviewWindow<R>,
) -> Result<(), String> {
    if window.label() == "quick-controls" {
        Ok(())
    } else {
        Err("This action is only available from OfficeKit Quick Controls".into())
    }
}
fn corner_position(
    corner: &str,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    scale: f64,
) -> (i32, i32) {
    let window_width = (300.0 * scale).round() as i64;
    let window_height = (460.0 * scale).round() as i64;
    let inset = (16.0 * scale).round() as i64;
    let dx = if corner.ends_with("right") {
        (i64::from(width) - window_width - inset).max(0)
    } else {
        inset
    };
    let dy = if corner.starts_with("bottom") {
        (i64::from(height) - window_height - inset).max(0)
    } else {
        inset
    };
    (
        (i64::from(x) + dx).clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32,
        (i64::from(y) + dy).clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32,
    )
}
const COMPANION_HIDE_REOPEN_GRACE: Duration = Duration::from_secs(15);
/// A press can be answered by a reopen much later than the hide (for example when the countdown
/// ends a break), so presses are remembered for longer than hides.
const COMPANION_PRESS_REOPEN_GRACE: Duration = Duration::from_secs(30);
static LAST_COMPANION_HIDE: Mutex<Option<Instant>> = Mutex::new(None);
static LAST_COMPANION_PRESS: Mutex<Option<Instant>> = Mutex::new(None);
/// Any press on the mascot (close, Done, Start, End early) activates OfficeKit, and macOS may
/// report the resulting reopen after the mascot has hidden, so the press itself starts the grace period.
pub fn note_companion_press() {
    for last in [&LAST_COMPANION_HIDE, &LAST_COMPANION_PRESS] {
        if let Ok(mut pressed) = last.lock() {
            *pressed = Some(Instant::now());
        }
    }
}
fn within(last: &Mutex<Option<Instant>>, grace: Duration) -> bool {
    last.lock()
        .ok()
        .and_then(|at| *at)
        .is_some_and(|at| at.elapsed() < grace)
}
/// Hiding the mascot can make macOS report an app reopen with no visible windows;
/// that must not pop the main window open.
/// A click on the mascot activates the app, and macOS reports that as a reopen before the
/// mascot has hidden. While the mascot is on screen a reopen is therefore never a request
/// for the main window.
pub fn companion_visible<R: TauriRuntime>(app: &AppHandle<R>) -> bool {
    app.get_webview_window("ergonomics")
        .is_some_and(|window| window.is_visible().unwrap_or(false))
}
pub fn companion_hid_recently() -> bool {
    within(&LAST_COMPANION_HIDE, COMPANION_HIDE_REOPEN_GRACE)
        || within(&LAST_COMPANION_PRESS, COMPANION_PRESS_REOPEN_GRACE)
}
fn view<R: TauriRuntime>(app: &AppHandle<R>, s: &Snapshot) -> Result<(), String> {
    if s.prompt.is_none() {
        if let Some(w) = app.get_webview_window("ergonomics") {
            if let Ok(mut hidden) = LAST_COMPANION_HIDE.lock() {
                *hidden = Some(Instant::now());
            }
            // Closed like the speech coach panel: the window is destroyed, not kept hidden, so macOS has no
            // leftover window to activate or reopen the app around. The next reminder builds a fresh one.
            w.destroy().map_err(|_| "Cannot close reminder companion")?;
        }
        return Ok(());
    }
    let w = match app.get_webview_window("ergonomics") {
        Some(w) => w,
        None => tauri::WebviewWindowBuilder::new(
            app,
            "ergonomics",
            tauri::WebviewUrl::App("assets/ergonomics-companion.html".into()),
        )
        .title("OfficeKit companion")
        .inner_size(300.0, 460.0)
        .transparent(true)
        .shadow(false)
        .decorations(false)
        .resizable(false)
        .always_on_top(true)
        // Reminders, including the Record and Coach me offer on a call, stay out of screen shares.
        .content_protected(true)
        .skip_taskbar(true)
        .visible(false)
        .focused(false)
        .focusable(true)
        // The bubble is shown without activating OfficeKit, so the first click must reach its buttons
        // instead of only activating the app.
        .accept_first_mouse(true)
        .build()
        .map_err(|_| "Cannot create reminder companion")?,
    };
    let monitor = w
        .current_monitor()
        .map_err(|_| "Cannot locate companion display")?
        .or(w
            .primary_monitor()
            .map_err(|_| "Cannot locate primary display")?);
    if let Some(m) = monitor {
        let a = m.work_area();
        let (x, y) = corner_position(
            &s.settings.corner,
            a.position.x,
            a.position.y,
            a.size.width,
            a.size.height,
            m.scale_factor(),
        );
        w.set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|_| "Cannot position reminder companion")?;
    }
    if !w
        .is_visible()
        .map_err(|_| "Cannot read companion window state")?
    {
        show_without_activation(app, &w)?;
    }
    Ok(())
}
#[cfg(all(target_os = "macos", not(test)))]
fn show_without_activation<R: TauriRuntime>(
    app: &AppHandle<R>,
    window: &tauri::WebviewWindow<R>,
) -> Result<(), String> {
    // Tauri show() maps to makeKeyAndOrderFront on macOS. orderFrontRegardless
    // displays the reminder without changing the user's active application.
    let window = window.clone();
    app.run_on_main_thread(move || {
        if let Ok(pointer) = window.ns_window() {
            unsafe {
                (&*(pointer as *const objc2_app_kit::NSWindow)).orderFrontRegardless();
            }
        }
    })
    .map_err(|_| "Cannot display reminder companion".into())
}
#[cfg(any(not(target_os = "macos"), test))]
fn show_without_activation<R: TauriRuntime>(
    _app: &AppHandle<R>,
    window: &tauri::WebviewWindow<R>,
) -> Result<(), String> {
    window
        .show()
        .map_err(|_| "Cannot display reminder companion".into())
}
fn publish<R: TauriRuntime>(app: &AppHandle<R>, s: &Snapshot) {
    let _ = app.emit_to("main", "ergonomics:state", s);
}
fn current(r: &Runtime) -> Result<Snapshot, String> {
    let m = headphone_motion::snapshot();
    let c = r
        .core
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    let calendar = r
        .calendar
        .lock()
        .map_err(|_| "Calendar reminders unavailable")?;
    Ok(with_calendar(
        c.snapshot(now(), m),
        &calendar,
        wall_now(),
        minute(),
    ))
}
fn with_calendar(
    mut snapshot: Snapshot,
    calendar: &CalendarCore,
    wall: u64,
    minute: u16,
) -> Snapshot {
    let state = calendar.snapshot(&snapshot.settings.meetings, wall);
    let reminders_on = snapshot.paused_remaining_seconds.is_none()
        && !snapshot.settings.quiet_hours.contains(minute);
    if reminders_on || state.preview {
        if let Some(event) = state.selected_event.as_ref().filter(|event| {
            let left = event.start.saturating_sub(wall);
            // The meeting fades in from 30 to 5 minutes out. It is hidden while too faint to see,
            // and it waits while a wellness reminder is on screen, until the last 5 minutes.
            state.preview
                || left <= MEETING_VISIBLE_SECONDS
                    && (left <= MEETING_FULL_SECONDS
                        || snapshot.prompt.as_ref().is_none_or(|p| p.phase == "teaser"))
        }) {
            snapshot.prompt = Some(Prompt {
                id: event.id.clone(),
                kind: "meeting".into(),
                phase: if event.start <= wall {
                    "starting"
                } else {
                    "ready"
                }
                .into(),
                remaining_seconds: Some(event.start.saturating_sub(wall)),
                preview: state.preview,
                record_offer: !state.preview
                    && event.start <= wall
                    && snapshot.settings.meetings.offer_recording
                    && !calendar.recording(),
                call_app: None,
                deadline: 0,
            });
        }
    }
    // A call with no invite: a call app holds the microphone. It waits for a wellness reminder
    // that is on screen, and never replaces a meeting reminder.
    if reminders_on
        && snapshot.settings.meetings.offer_recording
        && !calendar.recording()
        && snapshot
            .prompt
            .as_ref()
            .is_none_or(|p| p.phase == "teaser" && p.kind != "meeting")
    {
        if let Some(offer) = calendar.call_offer(wall) {
            snapshot.prompt = Some(Prompt {
                id: offer.id,
                kind: "call".into(),
                phase: "ready".into(),
                remaining_seconds: None,
                preview: false,
                record_offer: true,
                call_app: offer.app,
                deadline: 0,
            });
        }
    }
    snapshot.calendar = Some(state);
    snapshot
}
#[cfg(target_os = "macos")]
fn native_activity_active() -> bool {
    let (keyboard_idle, mic_idle) = unsafe {
        (
            officekit_user_activity_idle_seconds(),
            officekit_dictation_voice_activity_age_seconds(),
        )
    };
    activity_active(keyboard_idle, mic_idle)
}
fn activity_active(keyboard_idle: f64, mic_idle: f64) -> bool {
    input_age_is_recent(keyboard_idle) || input_age_is_recent(mic_idle)
}
fn input_age_is_recent(seconds: f64) -> bool {
    seconds.is_finite() && (0.0..=ACTIVE_INPUT_WINDOW_SECONDS).contains(&seconds)
}
#[cfg(not(target_os = "macos"))]
fn native_activity_active() -> bool {
    false
}
#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_user_activity_idle_seconds() -> f64;
    fn officekit_dictation_voice_activity_age_seconds() -> f64;
}
pub fn start<R: TauriRuntime>(app: &AppHandle<R>) {
    let path = app
        .path()
        .app_data_dir()
        .ok()
        .map(|p| p.join("ergonomics-v1.json"));
    start_with_profile_and_path(app, env!("OFFICEKIT_RELEASE_PROFILE"), path);
}
fn start_with_profile_and_path<R: TauriRuntime>(
    app: &AppHandle<R>,
    profile: &str,
    path: Option<PathBuf>,
) {
    if !crate::ergonomics_access::profile_enabled(profile) {
        return;
    }
    let (settings, mut error) = match &path {
        Some(path) => load(path),
        None => (Settings::default(),Some("Cannot locate OfficeKit app-data directory. Check app-data permissions and restart OfficeKit.".into())),
    };
    let needs_motion_reset = settings.posture.enabled;
    let settings = safe_restart_settings(settings);
    if needs_motion_reset {
        if let Some(path) = &path {
            if let Err(message) = save(path, &settings) {
                error = Some(message);
            }
        }
    }
    let mut c = Core::new(settings, now());
    c.error = error;
    let core = Arc::new(Mutex::new(c));
    let delivery = Arc::new(Mutex::new(()));
    let stop = Arc::new(AtomicBool::new(false));
    let calendar = Arc::new(Mutex::new(CalendarCore::default()));
    app.manage(Runtime {
        core: core.clone(),
        delivery: delivery.clone(),
        path,
        stop: stop.clone(),
        motion_enabled: AtomicBool::new(false),
        calendar: calendar.clone(),
    });
    // EventKit work never runs under the scheduler/delivery mutex or on the UI thread.
    let calendar_core = core.clone();
    let calendar_stop = stop.clone();
    let calendar_cache = calendar.clone();
    std::thread::spawn(move || {
        while !calendar_stop.load(Ordering::Relaxed) {
            let enabled = calendar_core
                .lock()
                .map(|c| c.settings.meetings.enabled)
                .unwrap_or(false);
            if enabled {
                let feed = meeting_calendar::read(true);
                // A disable while EventKit is running must discard the result.
                if let Ok(c) = calendar_core.lock() {
                    if let Ok(mut cache) = calendar_cache.lock() {
                        if c.settings.meetings.enabled {
                            cache.replace(feed, wall_now());
                        } else {
                            cache.clear();
                        }
                    }
                }
            }
            for _ in 0..10 {
                if calendar_stop.load(Ordering::Relaxed) {
                    return;
                }
                std::thread::sleep(Duration::from_secs(1));
            }
        }
    });
    let app = app.clone();
    std::thread::spawn(move || {
        while !stop.load(Ordering::Relaxed) {
            if let Ok(_delivery) = delivery.lock() {
                let m = headphone_motion::snapshot();
                // Which app holds the microphone is read only while the offer is on, and outside
                // every lock.
                let offer_calls = core
                    .lock()
                    .map(|c| c.settings.meetings.offer_recording)
                    .unwrap_or(false);
                let call = if offer_calls {
                    call_detect::current_call()
                } else {
                    None
                };
                let recording = offer_calls && recording_active(&app);
                // Coach me ends with the call whether or not the record offer is on, so it reads the
                // call itself rather than the offer-gated value above.
                coach_call_tick(&app);
                let s = if let Ok(mut c) = core.lock() {
                    let monotonic = now();
                    c.observe_wall(wall_now(), monotonic);
                    c.tick_with_activity(monotonic, minute(), Some(&m), native_activity_active());
                    calendar.lock().ok().map(|mut calendar| {
                        calendar.observe_call(call, recording, wall_now());
                        with_calendar(c.snapshot(monotonic, m), &calendar, wall_now(), minute())
                    })
                } else {
                    None
                };
                if let Some(s) = s {
                    if view(&app, &s).is_err() {
                        if let Ok(mut c) = core.lock() {
                            c.error = Some("Cannot show reminder companion. Restart OfficeKit and try Preview again.".into());
                        }
                    }
                    publish(&app, &s);
                }
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    });
}
pub fn shutdown<R: TauriRuntime>(app: &AppHandle<R>) {
    if let Some(r) = app.try_state::<Runtime>() {
        r.stop.store(true, Ordering::Relaxed);
    }
    headphone_motion::shutdown();
}
#[tauri::command]
pub async fn ergonomics_get_state<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    state: tauri::State<'_, Runtime>,
) -> Result<Snapshot, String> {
    authorize(&window)?;
    current(&state)
}
#[tauri::command]
pub async fn ergonomics_update_settings<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    settings: Settings,
) -> Result<Snapshot, String> {
    authorize_main(&window)?;
    let _delivery = state
        .delivery
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    settings.validate()?;
    if settings.posture.enabled && !state.motion_enabled.load(Ordering::Relaxed) {
        return Err("Use Enable & calibrate to explicitly start AirPods sensing".into());
    }
    let stop_motion = !settings.posture.enabled && state.motion_enabled.load(Ordering::Relaxed);
    {
        let mut c = state
            .core
            .lock()
            .map_err(|_| "Reminder scheduler unavailable")?;
        save(
            state.path.as_deref().ok_or(
                "Cannot locate OfficeKit app-data directory; check permissions and restart",
            )?,
            &settings,
        )?;
        c.set_settings(settings, now());
        if !c.settings.meetings.enabled {
            state
                .calendar
                .lock()
                .map_err(|_| "Calendar reminders unavailable")?
                .clear();
        }
        c.error = None;
    }
    if stop_motion {
        state.motion_enabled.store(false, Ordering::Relaxed);
        headphone_motion::action("disable")?;
    }
    let s = current(&state)?;
    view(&app, &s)?;
    publish(&app, &s);
    Ok(s)
}

pub fn quick_controls_enabled(state: &Runtime) -> Result<bool, String> {
    state
        .core
        .lock()
        .map(|core| !core.settings.quick_controls_paused)
        .map_err(|_| "Reminder scheduler unavailable".into())
}

/// Quick controls only has something to do when the requested state differs from the saved one.
fn quick_controls_change_needed(paused: bool, enabled: bool) -> bool {
    paused == enabled
}

#[tauri::command]
pub async fn ergonomics_quick_controls_status<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    state: tauri::State<'_, Runtime>,
) -> Result<Snapshot, String> {
    authorize_quick_controls(&window)?;
    current(&state)
}

#[tauri::command]
pub async fn ergonomics_quick_controls_set_enabled<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    enabled: bool,
) -> Result<Snapshot, String> {
    authorize_quick_controls(&window)?;
    let _delivery = state
        .delivery
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    let (mut settings, changed) = {
        let core = state
            .core
            .lock()
            .map_err(|_| "Reminder scheduler unavailable")?;
        (
            core.settings.clone(),
            quick_controls_change_needed(core.settings.quick_controls_paused, enabled),
        )
    };
    if !changed {
        return current(&state);
    }
    settings.quick_controls_paused = !enabled;
    settings.validate()?;
    save(
        state
            .path
            .as_deref()
            .ok_or("Cannot locate OfficeKit app-data directory; check permissions and restart")?,
        &settings,
    )?;
    {
        let mut core = state
            .core
            .lock()
            .map_err(|_| "Reminder scheduler unavailable")?;
        core.set_settings(settings, now());
    }
    if !enabled && state.motion_enabled.load(Ordering::Relaxed) {
        headphone_motion::action("disable")?;
        state.motion_enabled.store(false, Ordering::Relaxed);
    }
    let snapshot = current(&state)?;
    view(&app, &snapshot)?;
    publish(&app, &snapshot);
    Ok(snapshot)
}
#[tauri::command]
pub async fn ergonomics_reminder_action<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    reminder_id: String,
    action: String,
) -> Result<Snapshot, String> {
    authorize(&window)?;
    note_companion_press();
    let _delivery = state
        .delivery
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    // Record and Open Calendar do their one job here, then the reminder is finished like Done.
    let action = match action.as_str() {
        "coach" => {
            let selected = current(&state)?;
            if !coach_is_offered(selected.prompt.as_ref(), &reminder_id) {
                return Err("This reminder has changed; use the current one".into());
            }
            start_coach(&app)?;
            // Like Record, the reminder is finished once Coach me has done its one job.
            "done".to_string()
        }
        "record" | "open-calendar" => {
            let selected = current(&state)?;
            let allowed = selected.prompt.as_ref().is_some_and(|p| {
                p.id == reminder_id
                    && !p.preview
                    && if action == "record" {
                        p.record_offer
                    } else {
                        p.kind == "meeting"
                    }
            });
            if !allowed {
                return Err("This reminder has changed; use the current one".into());
            }
            if action == "record" {
                start_recording(&app)?;
            } else {
                open_calendar()?;
            }
            "done".to_string()
        }
        _ => action,
    };
    apply_reminder_action(&state, &reminder_id, &action)?;
    let s = current(&state)?;
    view(&app, &s)?;
    publish(&app, &s);
    Ok(s)
}
/// Coach me is only for the current call, or for a started meeting that is offering a recording;
/// never for an older reminder or a preview.
fn coach_is_offered(prompt: Option<&Prompt>, reminder_id: &str) -> bool {
    prompt
        .is_some_and(|p| p.id == reminder_id && !p.preview && (p.kind == "call" || p.record_offer))
}
/// Opens the Calendar app. OfficeKit's own window is not involved.
fn open_calendar() -> Result<(), String> {
    #[cfg(all(target_os = "macos", not(test)))]
    {
        return std::process::Command::new("/usr/bin/open")
            .args(["-b", "com.apple.iCal"])
            .spawn()
            .map(|_| ())
            .map_err(|_| "Cannot open the Calendar app".into());
    }
    #[allow(unreachable_code)]
    Ok(())
}
fn start_recording<R: TauriRuntime>(app: &AppHandle<R>) -> Result<(), String> {
    // The recorder is built for the real window runtime; a test runtime has none.
    (app as &dyn std::any::Any)
        .downcast_ref::<AppHandle>()
        .ok_or_else(|| "Recording is not available here".to_string())
        .and_then(crate::start_meeting_recording_from_reminder)
}
fn coach_call_tick<R: TauriRuntime>(app: &AppHandle<R>) {
    if let Some(app) = (app as &dyn std::any::Any).downcast_ref::<AppHandle>() {
        crate::coach_me_call_tick(app);
    }
}
fn start_coach<R: TauriRuntime>(app: &AppHandle<R>) -> Result<(), String> {
    (app as &dyn std::any::Any)
        .downcast_ref::<AppHandle>()
        .ok_or_else(|| "Coaching is not available here".to_string())
        .and_then(crate::start_coach_from_reminder)
}
fn recording_active<R: TauriRuntime>(app: &AppHandle<R>) -> bool {
    (app as &dyn std::any::Any)
        .downcast_ref::<AppHandle>()
        .is_some_and(crate::meeting_recording_active)
}
fn apply_reminder_action(state: &Runtime, reminder_id: &str, action: &str) -> Result<(), String> {
    let selected = current(state)?;
    if selected.prompt.as_ref().is_some_and(|p| p.kind == "call") {
        if !["done", "dismiss"].contains(&action) {
            return Err("Unsupported call reminder action".into());
        }
        state
            .calendar
            .lock()
            .map_err(|_| "Calendar reminders unavailable")?
            .decline_call();
        return Ok(());
    }
    if selected
        .prompt
        .as_ref()
        .is_some_and(|p| p.kind == "meeting")
        && !["pause", "resume"].contains(&action)
    {
        let mut calendar = state
            .calendar
            .lock()
            .map_err(|_| "Calendar reminders unavailable")?;
        if action == "close-preview"
            && reminder_id.is_empty()
            && selected.calendar.as_ref().is_some_and(|c| c.preview)
        {
            calendar.close_preview();
        } else if action == "done" {
            calendar.hide(reminder_id, &selected.settings.meetings, wall_now())?;
            // The call for this meeting has been answered; do not offer it again as a separate call.
            calendar.decline_call();
        } else {
            return Err("Unsupported meeting reminder action".into());
        }
    } else {
        state
            .core
            .lock()
            .map_err(|_| "Reminder scheduler unavailable")?
            .action(reminder_id, action, now())?;
    }
    Ok(())
}
#[tauri::command]
pub async fn ergonomics_preview<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    kind: String,
) -> Result<Snapshot, String> {
    authorize_main(&window)?;
    let _delivery = state
        .delivery
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    if !["break", "eyes", "water", "posture", "meeting"].contains(&kind.as_str()) {
        return Err("Unknown preview kind".into());
    }
    if kind == "meeting" {
        state
            .calendar
            .lock()
            .map_err(|_| "Calendar reminders unavailable")?
            .preview(wall_now());
    } else {
        let mut c = state
            .core
            .lock()
            .map_err(|_| "Reminder scheduler unavailable")?;
        if c.prompt.is_some() {
            return Err("Dismiss the current reminder before previewing".into());
        }
        c.open(&kind, now(), true);
    }
    let s = current(&state)?;
    view(&app, &s)?;
    publish(&app, &s);
    Ok(s)
}
#[tauri::command]
pub async fn ergonomics_calendar_action<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    action: String,
) -> Result<Snapshot, String> {
    authorize_main(&window)?;
    match action.as_str() {
        "permission" => {
            if !cfg!(target_os = "macos") {
                return Err("Local calendar reminders are available on macOS".into());
            }
            meeting_calendar::request_permission();
        }
        "open" => {
            #[cfg(target_os = "macos")]
            std::process::Command::new("/usr/bin/open")
                .args(["-a", "Calendar"])
                .spawn()
                .map_err(|_| "Cannot open Calendar")?;
            #[cfg(not(target_os = "macos"))]
            return Err("Calendar is available on macOS".into());
        }
        "privacy" => {
            #[cfg(target_os = "macos")]
            std::process::Command::new("/usr/bin/open")
                .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")
                .spawn()
                .map_err(|_| "Cannot open calendar privacy settings")?;
            #[cfg(not(target_os = "macos"))]
            return Err("Calendar privacy settings are available on macOS".into());
        }
        _ => return Err("Unsupported calendar action".into()),
    }
    let s = current(&state)?;
    publish(&app, &s);
    Ok(s)
}
#[tauri::command]
pub async fn ergonomics_motion_action<R: TauriRuntime>(
    window: tauri::WebviewWindow<R>,
    app: AppHandle<R>,
    state: tauri::State<'_, Runtime>,
    action: String,
) -> Result<Snapshot, String> {
    authorize_main(&window)?;
    let _delivery = state
        .delivery
        .lock()
        .map_err(|_| "Reminder scheduler unavailable")?;
    if !["enable", "disable", "calibrate"].contains(&action.as_str()) {
        return Err("Unsupported AirPods action".into());
    }
    if action == "calibrate" && !state.motion_enabled.load(Ordering::Relaxed) {
        return Err("Enable AirPods sensing before recalibrating".into());
    }
    headphone_motion::action(&action)?;
    if action == "enable" || action == "disable" {
        let enabled = action == "enable";
        let result = (|| {
            let mut c = state
                .core
                .lock()
                .map_err(|_| "Reminder scheduler unavailable".to_string())?;
            let mut settings = c.settings.clone();
            settings.posture.enabled = enabled;
            save(
                state.path.as_deref().ok_or(
                    "Cannot locate OfficeKit app-data directory; check permissions and restart",
                )?,
                &settings,
            )?;
            c.set_settings(settings, now());
            c.error = None;
            Ok::<(), String>(())
        })();
        if let Err(error) = result {
            let _ = headphone_motion::action("disable");
            state.motion_enabled.store(false, Ordering::Relaxed);
            if let Ok(mut c) = state.core.lock() {
                c.settings.posture.enabled = false;
                c.dwell_since = None;
                if c.prompt
                    .as_ref()
                    .is_some_and(|p| p.kind == "posture" && !p.preview)
                {
                    c.prompt = None;
                }
                c.error = Some(error.clone());
            }
            return Err(error);
        }
        state.motion_enabled.store(enabled, Ordering::Relaxed);
    }
    let s = current(&state)?;
    publish(&app, &s);
    Ok(s)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn meeting_cache(wall: u64) -> CalendarCore {
        let mut cache = CalendarCore::default();
        cache.replace(
            meeting_calendar::Feed {
                status: "allowed".into(),
                calendars: vec![],
                events: vec![meeting_calendar::Event {
                    id: "occurrence".into(),
                    calendar_id: "work".into(),
                    title: "PRIVATE MEETING".into(),
                    calendar_title: "Work".into(),
                    start: wall + 100,
                }],
            },
            wall,
        );
        cache
    }
    fn meeting_in(wall: u64, seconds: u64) -> CalendarCore {
        let mut cache = CalendarCore::default();
        cache.replace(
            meeting_calendar::Feed {
                status: "allowed".into(),
                calendars: vec![],
                events: vec![meeting_calendar::Event {
                    id: "later".into(),
                    calendar_id: "work".into(),
                    title: "Later".into(),
                    calendar_title: "Work".into(),
                    start: wall + seconds,
                }],
            },
            wall,
        );
        cache
    }
    fn fading_core() -> Core {
        let mut settings = Settings::default();
        settings.quiet_hours.enabled = false;
        settings.meetings.enabled = true;
        settings.water.enabled = true;
        settings.water.interval_minutes = 5;
        Core::new(settings, 0)
    }
    #[test]
    fn closing_a_fading_in_reminder_moves_it_to_its_normal_interval() {
        let mut core = fading_core();
        let motion = headphone_motion::snapshot;
        assert_eq!(
            core.snapshot(190, motion()).prompt.unwrap().id,
            "teaser-water"
        );
        // Only the reminder on screen can be closed, and only with dismiss.
        assert!(core.action("teaser-eyes", "dismiss", 190).is_err());
        assert!(core.action("teaser-water", "done", 190).is_err());
        core.action("teaser-water", "dismiss", 190).unwrap();
        assert!(core.snapshot(191, motion()).prompt.is_none());
        let due = core.snapshot(191, motion()).next_due;
        let water = due.iter().find(|d| d.kind == "water").unwrap();
        assert_eq!(water.seconds, Some(5 * 60 - 1));
    }
    #[test]
    fn a_wellness_reminder_teases_only_in_its_last_two_minutes() {
        let mut core = fading_core();
        let motion = headphone_motion::snapshot;
        let at = |core: &Core, now: u64| core.snapshot(now, motion()).prompt;
        // Due at 300 s: nothing before 186 s, a faint teaser from 186 s, none once it is due.
        assert!(at(&core, 100).is_none());
        assert!(at(&core, 185).is_none());
        let teaser = at(&core, 190).unwrap();
        assert_eq!(
            (teaser.kind.as_str(), teaser.phase.as_str()),
            ("water", "teaser")
        );
        assert_eq!(teaser.remaining_seconds, Some(110));
        assert_eq!(teaser.id, "teaser-water");
        assert_eq!(at(&core, 299).unwrap().remaining_seconds, Some(1));
        assert!(
            at(&core, 300).is_none(),
            "due now: the real prompt takes over"
        );
        // Never while paused, quiet, away from the keyboard or with a prompt already open.
        core.active_input = false;
        assert!(at(&core, 250).is_none());
        core.active_input = true;
        core.paused_until = Some(9999);
        assert!(at(&core, 250).is_none());
        core.paused_until = None;
        core.quiet = true;
        assert!(at(&core, 250).is_none());
        core.quiet = false;
        core.open("eyes", 250, false);
        assert_eq!(at(&core, 250).unwrap().kind, "eyes");
        assert_eq!(at(&core, 250).unwrap().phase, "ready");
    }
    #[test]
    fn a_meeting_fades_in_from_thirty_minutes_and_yields_to_wellness_until_five() {
        let mut core = fading_core();
        let motion = headphone_motion::snapshot;
        let meeting_at = |core: &Core, left: u64| {
            with_calendar(
                core.snapshot(0, motion()),
                &meeting_in(1000, left),
                1000,
                600,
            )
            .prompt
        };
        assert!(meeting_at(&core, 1790).is_none(), "too faint to show");
        let faint = meeting_at(&core, 1700).unwrap();
        assert_eq!(
            (faint.kind.as_str(), faint.phase.as_str()),
            ("meeting", "ready")
        );
        assert_eq!(faint.remaining_seconds, Some(1700));
        // A wellness reminder on screen is not pushed aside before the last five minutes.
        core.open("water", 0, false);
        assert_eq!(meeting_at(&core, 1000).unwrap().kind, "water");
        assert_eq!(meeting_at(&core, 301).unwrap().kind, "water");
        assert_eq!(meeting_at(&core, 300).unwrap().kind, "meeting");
        assert_eq!(meeting_at(&core, 100).unwrap().kind, "meeting");
        // A wellness teaser always yields to a visible meeting.
        let core = fading_core();
        assert_eq!(core.snapshot(190, motion()).prompt.unwrap().phase, "teaser");
        let composed = with_calendar(
            core.snapshot(190, motion()),
            &meeting_in(1000, 900),
            1000,
            600,
        );
        assert_eq!(composed.prompt.unwrap().kind, "meeting");
    }
    fn offering_core(offer: bool) -> Core {
        let mut settings = Settings::default();
        settings.quiet_hours.enabled = false;
        settings.meetings.enabled = true;
        settings.meetings.offer_recording = offer;
        Core::new(settings, 0)
    }
    fn compose(core: &Core, cache: &CalendarCore, wall: u64) -> Snapshot {
        with_calendar(
            core.snapshot(0, headphone_motion::snapshot()),
            cache,
            wall,
            600,
        )
    }
    #[test]
    fn a_started_meeting_offers_record_only_when_the_setting_is_on() {
        let cache = meeting_in(1000, 0);
        let off = compose(&offering_core(false), &cache, 1000).prompt.unwrap();
        assert!(!off.record_offer);
        let on = compose(&offering_core(true), &cache, 1000).prompt.unwrap();
        assert_eq!(
            (on.kind.as_str(), on.phase.as_str()),
            ("meeting", "starting")
        );
        assert!(on.record_offer);
        let early = meeting_in(1000, 120);
        assert!(
            !compose(&offering_core(true), &early, 1000)
                .prompt
                .unwrap()
                .record_offer
        );
    }
    #[test]
    fn an_ad_hoc_call_is_offered_without_an_invite_and_never_over_a_meeting() {
        let mut cache = CalendarCore::default();
        cache.observe_call(Some(Some("Zoom")), false, 100);
        let prompt = compose(&offering_core(true), &cache, 110).prompt.unwrap();
        assert_eq!(prompt.kind, "call");
        assert_eq!(prompt.call_app.as_deref(), Some("Zoom"));
        assert!(prompt.record_offer);
        assert!(compose(&offering_core(false), &cache, 110).prompt.is_none());
        cache.observe_call(Some(Some("Zoom")), true, 111);
        assert!(
            compose(&offering_core(true), &cache, 112).prompt.is_none(),
            "already recording"
        );
        let mut with_meeting = meeting_in(110, 0);
        with_meeting.observe_call(Some(Some("Zoom")), false, 100);
        assert_eq!(
            compose(&offering_core(true), &with_meeting, 110)
                .prompt
                .unwrap()
                .kind,
            "meeting"
        );
    }
    #[test]
    fn call_reminders_only_accept_done_or_dismiss_and_decline_the_call() {
        let mut settings = Settings::default();
        settings.quiet_hours.enabled = false;
        settings.meetings.offer_recording = true;
        // The default quiet hours (22:00 to 08:00) hide the call reminder, so the clock must not matter.
        settings.quiet_hours.enabled = false;
        let state = Runtime {
            core: Arc::new(Mutex::new(Core::new(settings, 0))),
            delivery: Arc::new(Mutex::new(())),
            path: None,
            stop: Arc::new(AtomicBool::new(false)),
            motion_enabled: AtomicBool::new(false),
            calendar: Arc::new(Mutex::new({
                let mut cache = CalendarCore::default();
                cache.observe_call(Some(Some("Slack")), false, wall_now().saturating_sub(60));
                cache
            })),
        };
        assert!(current(&state)
            .unwrap()
            .prompt
            .is_some_and(|p| p.kind == "call"));
        assert!(apply_reminder_action(&state, "call-1", "snooze").is_err());
        apply_reminder_action(&state, "call-1", "dismiss").unwrap();
        assert!(current(&state)
            .unwrap()
            .prompt
            .is_none_or(|p| p.kind != "call"));
    }
    #[test]
    fn meeting_priority_pause_quiet_preview_and_wellness_restoration() {
        let mut settings = Settings::default();
        settings.quiet_hours.enabled = false;
        settings.meetings.enabled = true;
        let mut core = Core::new(settings, 0);
        core.open("water", 0, false);
        core.active_input = false;
        let cache = meeting_cache(1000);
        let snapshot = with_calendar(
            core.snapshot(0, headphone_motion::snapshot()),
            &cache,
            1000,
            600,
        );
        assert_eq!(
            snapshot.prompt.unwrap().kind,
            "meeting",
            "calendar bypasses activity gate"
        );
        assert_eq!(
            core.prompt.as_ref().unwrap().kind,
            "water",
            "composition must not replace wellness state"
        );
        core.active_input = true;
        core.paused_until = Some(3600);
        assert_eq!(
            with_calendar(
                core.snapshot(0, headphone_motion::snapshot()),
                &cache,
                1000,
                600
            )
            .prompt
            .unwrap()
            .kind,
            "water"
        );
        core.paused_until = None;
        core.settings.quiet_hours.enabled = true;
        assert_eq!(
            with_calendar(
                core.snapshot(0, headphone_motion::snapshot()),
                &cache,
                1000,
                1380
            )
            .prompt
            .unwrap()
            .kind,
            "water"
        );
        let mut preview = CalendarCore::default();
        preview.preview(1000);
        assert_eq!(
            with_calendar(
                core.snapshot(0, headphone_motion::snapshot()),
                &preview,
                1000,
                1380
            )
            .prompt
            .unwrap()
            .kind,
            "meeting"
        );
        assert_eq!(
            with_calendar(
                core.snapshot(0, headphone_motion::snapshot()),
                &cache,
                1046,
                600
            )
            .prompt
            .unwrap()
            .kind,
            "water",
            "stale feed restores wellness"
        );
    }
    #[test]
    fn meeting_action_ids_preview_and_global_pause_are_isolated() {
        let wall = wall_now();
        let mut settings = Settings::default();
        settings.quiet_hours.enabled = false;
        settings.meetings.enabled = true;
        let runtime = Runtime {
            core: Arc::new(Mutex::new(Core::new(settings, now()))),
            delivery: Arc::new(Mutex::new(())),
            path: None,
            stop: Arc::new(AtomicBool::new(false)),
            motion_enabled: AtomicBool::new(false),
            calendar: Arc::new(Mutex::new(meeting_cache(wall))),
        };
        assert!(apply_reminder_action(&runtime, "wrong", "done").is_err());
        assert!(apply_reminder_action(&runtime, "occurrence", "snooze").is_err());
        apply_reminder_action(&runtime, "occurrence", "done").unwrap();
        assert!(current(&runtime).unwrap().prompt.is_none());
        runtime.calendar.lock().unwrap().preview(wall);
        apply_reminder_action(&runtime, "", "close-preview").unwrap();
        assert!(!current(&runtime).unwrap().calendar.unwrap().preview);
        apply_reminder_action(&runtime, "", "pause").unwrap();
        assert!(current(&runtime)
            .unwrap()
            .paused_remaining_seconds
            .is_some());
        apply_reminder_action(&runtime, "", "resume").unwrap();
        assert!(current(&runtime)
            .unwrap()
            .paused_remaining_seconds
            .is_none());
    }
    #[test]
    fn meeting_preferences_migrate_roundtrip_and_reject_oversized_writes_atomically() {
        let path =
            std::env::temp_dir().join(format!("officekit-meeting-{}.json", uuid::Uuid::new_v4()));
        let mut settings = Settings::default();
        settings.meetings.enabled = true;
        settings.meetings.calendar_ids = vec!["work".into()];
        save(&path, &settings).unwrap();
        assert_eq!(load(&path).0, settings);
        let bytes = fs::read(&path).unwrap();
        assert!(!String::from_utf8_lossy(&bytes).contains("PRIVATE MEETING"));
        let mut old = serde_json::to_value(&settings).unwrap();
        old.as_object_mut().unwrap().remove("meetings");
        assert_eq!(
            serde_json::from_value::<Settings>(old).unwrap().meetings,
            MeetingSettings::default()
        );
        settings.meetings.calendar_ids =
            (0..9).map(|i| format!("{i}{}", "x".repeat(2047))).collect();
        assert!(settings.validate().is_ok());
        assert!(save(&path, &settings).is_err());
        assert_eq!(fs::read(&path).unwrap(), bytes);
        fs::remove_file(path).unwrap();
    }
    fn enabled() -> Settings {
        let mut s = Settings::default();
        s.quiet_hours.enabled = false;
        s.breaks.enabled = true;
        s.eyes.enabled = true;
        s.water.enabled = true;
        s
    }
    #[test]
    fn defaults_are_opt_in() {
        let s = Settings::default();
        assert!(!s.breaks.enabled && !s.eyes.enabled && !s.water.enabled && !s.posture.enabled);
        assert!(s.validate().is_ok());
    }

    #[test]
    fn quick_controls_switch_acts_in_both_directions_and_skips_a_repeat() {
        assert!(
            quick_controls_change_needed(false, false),
            "switching an enabled tool off must act"
        );
        assert!(
            quick_controls_change_needed(true, true),
            "switching a paused tool on must act"
        );
        assert!(!quick_controls_change_needed(false, true), "already on");
        assert!(!quick_controls_change_needed(true, false), "already off");
    }

    #[test]
    fn quick_controls_pause_is_persistent_and_rearms_saved_reminders_on_resume() {
        let mut core = Core::new(enabled(), 0);
        assert_eq!(core.due[0], Some(3000));
        let mut paused = core.settings.clone();
        paused.quick_controls_paused = true;
        core.set_settings(paused, 100);
        assert!(core.due.iter().all(Option::is_none));
        core.tick(100_000, 600, None);
        assert!(core.prompt.is_none());

        let mut resumed = core.settings.clone();
        resumed.quick_controls_paused = false;
        core.set_settings(resumed, 100_000);
        assert_eq!(core.due[0], Some(103_000));
        assert!(core.settings.breaks.enabled);
    }

    #[test]
    fn recent_keyboard_pointer_or_voice_input_enables_delivery_but_silent_mic_does_not() {
        assert!(!activity_active(f64::INFINITY, f64::INFINITY));
        assert!(activity_active(0.0, f64::INFINITY));
        assert!(activity_active(300.0, f64::INFINITY));
        assert!(!activity_active(300.01, f64::INFINITY));
        assert!(activity_active(f64::INFINITY, 10.0));
        assert!(!activity_active(f64::INFINITY, f64::INFINITY));
        assert!(!activity_active(f64::NAN, -1.0));
    }

    #[test]
    fn mocked_tauri_windows_cover_authorization_visibility_and_state_delivery() {
        let app = tauri::test::mock_app();
        let main = tauri::WebviewWindowBuilder::new(
            &app,
            "main",
            tauri::WebviewUrl::App("index.html".into()),
        )
        .build()
        .unwrap();
        assert!(authorize(&main).is_ok());
        assert!(authorize_main(&main).is_ok());

        let mut core = Core::new(Settings::default(), 0);
        let hidden = core.snapshot(0, headphone_motion::snapshot());
        assert!(view(app.handle(), &hidden).is_ok());
        core.open("water", 1, true);
        let visible = core.snapshot(1, headphone_motion::snapshot());
        assert!(view(app.handle(), &visible).is_ok());
        let companion = app.get_webview_window("ergonomics").unwrap();
        assert!(authorize(&companion).is_ok());
        assert!(authorize_main(&companion).is_err());
        assert!(show_without_activation(app.handle(), &companion).is_ok());
        publish(app.handle(), &visible);
        core.action("", "close-preview", 2).unwrap();
        let hidden = core.snapshot(2, headphone_motion::snapshot());
        assert!(view(app.handle(), &hidden).is_ok());
        // Closing destroys the mascot window like the speech coach panel; a repeat close finds nothing to do.
        assert!(view(app.handle(), &hidden).is_ok());
    }

    #[test]
    fn native_scheduler_starts_with_session_only_motion_and_shuts_down() {
        let root = std::env::temp_dir().join(format!(
            "officekit-ergonomics-runtime-{}",
            uuid::Uuid::new_v4()
        ));
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context.config_mut().identifier = "com.officekit.test".into();
        context.config_mut().app.app_directories_override = Some(
            tauri::utils::config::AppDirectoriesOverride::Root(root.clone().into()),
        );
        let app = tauri::test::mock_builder().build(context).unwrap();
        let data = app.path().app_data_dir().unwrap();
        fs::create_dir_all(&data).unwrap();
        let path = data.join("ergonomics-v1.json");
        let mut stored = Settings::default();
        stored.posture.enabled = true;
        save(&path, &stored).unwrap();

        start(app.handle());
        let runtime = app.state::<Runtime>();
        let snapshot = current(&runtime).unwrap();
        assert!(!snapshot.settings.posture.enabled);
        assert_eq!(snapshot.error, None);
        assert!(!runtime.motion_enabled.load(Ordering::Relaxed));
        assert!(!load(&path).0.posture.enabled);

        std::thread::sleep(Duration::from_millis(1100));
        shutdown(app.handle());
        assert!(runtime.stop.load(Ordering::Relaxed));
        std::thread::sleep(Duration::from_millis(50));
        drop(runtime);
        drop(app);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn scheduler_profile_gate_and_missing_app_data_fail_safely() {
        let disabled_app = tauri::test::mock_app();
        start_with_profile_and_path(disabled_app.handle(), "unknown", None);
        assert!(disabled_app.try_state::<Runtime>().is_none());
        shutdown(disabled_app.handle());

        let missing_path_app = tauri::test::mock_app();
        start_with_profile_and_path(missing_path_app.handle(), "development", None);
        let runtime = missing_path_app.state::<Runtime>();
        let state = current(&runtime).unwrap();
        assert!(state.error.unwrap().contains("app-data directory"));
        assert!(runtime.path.is_none());
        std::thread::sleep(Duration::from_millis(1100));
        shutdown(missing_path_app.handle());
        std::thread::sleep(Duration::from_millis(50));
    }

    #[test]
    fn coach_me_is_only_offered_for_the_current_call_or_a_meeting_with_a_record_offer() {
        let prompt = |kind: &str, preview: bool, record_offer: bool| Prompt {
            id: "current".into(),
            kind: kind.into(),
            phase: "ready".into(),
            remaining_seconds: None,
            preview,
            record_offer,
            call_app: None,
            deadline: 0,
        };
        assert!(!coach_is_offered(None, "current"), "no reminder is showing");
        assert!(
            !coach_is_offered(Some(&prompt("call", false, false)), "older"),
            "an older reminder is refused"
        );
        assert!(
            !coach_is_offered(Some(&prompt("call", true, false)), "current"),
            "a preview is refused"
        );
        assert!(
            !coach_is_offered(Some(&prompt("meeting", false, false)), "current"),
            "a meeting that offers no recording is refused"
        );
        assert!(
            !coach_is_offered(Some(&prompt("water", false, false)), "current"),
            "a break is refused"
        );
        assert!(coach_is_offered(
            Some(&prompt("call", false, false)),
            "current"
        ));
        assert!(coach_is_offered(
            Some(&prompt("meeting", false, true)),
            "current"
        ));
    }

    #[test]
    fn mocked_ipc_commands_validate_persist_and_sequence_reminder_actions() {
        let root = std::env::temp_dir().join(format!(
            "officekit-ergonomics-commands-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&root).unwrap();
        let app = tauri::test::mock_app();
        let main = tauri::WebviewWindowBuilder::new(
            &app,
            "main",
            tauri::WebviewUrl::App("index.html".into()),
        )
        .build()
        .unwrap();
        app.manage(Runtime {
            core: Arc::new(Mutex::new(Core::new(Settings::default(), now()))),
            delivery: Arc::new(Mutex::new(())),
            path: Some(root.join("ergonomics-v1.json")),
            stop: Arc::new(AtomicBool::new(false)),
            motion_enabled: AtomicBool::new(false),
            calendar: Arc::new(Mutex::new(CalendarCore::default())),
        });

        let initial = tauri::async_runtime::block_on(ergonomics_get_state(
            main.clone(),
            app.state::<Runtime>(),
        ))
        .unwrap();
        assert!(!initial.settings.breaks.enabled);

        let mut invalid = Settings::default();
        invalid.water.interval_minutes = 4;
        assert!(tauri::async_runtime::block_on(ergonomics_update_settings(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            invalid,
        ))
        .is_err());

        let mut settings = Settings::default();
        settings.breaks.enabled = true;
        settings.breaks.interval_minutes = 65;
        let saved = tauri::async_runtime::block_on(ergonomics_update_settings(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            settings,
        ))
        .unwrap();
        assert_eq!(saved.settings.breaks.interval_minutes, 65);
        assert!(root.join("ergonomics-v1.json").is_file());

        assert!(tauri::async_runtime::block_on(ergonomics_preview(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            "unknown".into(),
        ))
        .is_err());
        let preview = tauri::async_runtime::block_on(ergonomics_preview(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            "water".into(),
        ))
        .unwrap();
        let preview_id = preview.prompt.unwrap().id;
        assert!(tauri::async_runtime::block_on(ergonomics_reminder_action(
            app.get_webview_window("ergonomics").unwrap(),
            app.handle().clone(),
            app.state::<Runtime>(),
            preview_id,
            "start".into(),
        ))
        .is_ok());
        assert!(tauri::async_runtime::block_on(ergonomics_reminder_action(
            app.get_webview_window("ergonomics").unwrap(),
            app.handle().clone(),
            app.state::<Runtime>(),
            String::new(),
            "close-preview".into(),
        ))
        .is_ok());

        // Coach me for a reminder that is not showing is refused, whatever its id.
        assert_eq!(
            tauri::async_runtime::block_on(ergonomics_reminder_action(
                main.clone(),
                app.handle().clone(),
                app.state::<Runtime>(),
                "stale-reminder".into(),
                "coach".into(),
            ))
            .err()
            .as_deref(),
            Some("This reminder has changed; use the current one")
        );
        assert!(tauri::async_runtime::block_on(ergonomics_reminder_action(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            String::new(),
            "pause".into(),
        ))
        .is_ok());
        assert!(tauri::async_runtime::block_on(ergonomics_reminder_action(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            String::new(),
            "resume".into(),
        ))
        .is_ok());

        assert!(tauri::async_runtime::block_on(ergonomics_motion_action(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            "calibrate".into(),
        ))
        .is_err());
        let enabled = tauri::async_runtime::block_on(ergonomics_motion_action(
            main.clone(),
            app.handle().clone(),
            app.state::<Runtime>(),
            "enable".into(),
        ))
        .unwrap();
        assert!(enabled.settings.posture.enabled);
        let mut updated = enabled.settings;
        updated.posture.enabled = false;
        let disabled = tauri::async_runtime::block_on(ergonomics_update_settings(
            main,
            app.handle().clone(),
            app.state::<Runtime>(),
            updated,
        ))
        .unwrap();
        assert!(!disabled.settings.posture.enabled);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn headphone_sensing_never_restores_automatically_after_restart() {
        let mut settings = Settings::default();
        settings.posture.enabled = true;
        assert!(!safe_restart_settings(settings).posture.enabled);
    }
    #[test]
    fn corners_use_monitor_work_area_and_physical_scale() {
        assert_eq!(
            corner_position("top-left", -1920, 40, 1920, 1080, 2.0),
            (-1888, 72)
        );
        assert_eq!(
            corner_position("top-right", -1920, 40, 1920, 1080, 2.0),
            (-632, 72)
        );
        assert_eq!(
            corner_position("bottom-left", -1920, 40, 1920, 1080, 2.0),
            (-1888, 168)
        );
        assert_eq!(
            corner_position("bottom-right", -1920, 40, 1920, 1080, 2.0),
            (-632, 168)
        );
        assert_eq!(corner_position("bottom-right", 0, 0, 100, 100, 1.0), (0, 0));
    }
    #[test]
    fn independent_deadlines_and_stale_ids() {
        let mut c = Core::new(enabled(), 0);
        c.tick(1200, 720, None);
        assert!(c.prompt.is_none());
        c.tick(1201, 720, None);
        assert!(c.prompt.is_none());
        c.tick(2401, 720, None);
        assert!(c.prompt.is_none());
        c.tick(3601, 720, None);
        assert!(c.prompt.is_none());
        c.rearm(3601);
        for n in 3602..=4801 {
            c.tick(n, 720, None);
        }
        assert_eq!(c.prompt.as_ref().unwrap().kind, "eyes");
        assert!(c.action("stale", "start", 4801).is_err());
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "start", 4801).unwrap();
        c.tick(4821, 720, None);
        assert_eq!(c.prompt.as_ref().unwrap().phase, "complete");
    }
    #[test]
    fn overdue_reminders_wait_until_input_returns() {
        let mut settings = Settings::default();
        settings.water.enabled = true;
        settings.eyes.enabled = true;
        settings.breaks.enabled = true;
        let mut c = Core::new(settings, 0);
        for now in (60..=3600).step_by(60) {
            c.tick_with_activity(now, 720, None, false);
        }
        assert!(c.prompt.is_none());
        c.tick_with_activity(3601, 720, None, true);
        assert!(c.prompt.is_some());
        assert!(c.due.iter().flatten().all(|deadline| *deadline > 3601));
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "dismiss", 3602).unwrap();
        c.tick_with_activity(3603, 720, None, true);
        assert!(
            c.prompt.is_none(),
            "old reminders must not cascade after dismissal"
        );
    }
    #[test]
    fn automatic_prompt_hides_when_activity_expires_but_preview_does_not() {
        let mut c = Core::new(Settings::default(), 0);
        c.open("water", 1, false);
        assert!(c.snapshot(1, headphone_motion::snapshot()).prompt.is_some());
        c.tick_with_activity(2, 720, None, false);
        assert!(c.prompt.is_some());
        assert!(c.snapshot(2, headphone_motion::snapshot()).prompt.is_none());
        c.tick_with_activity(3, 720, None, true);
        assert!(c.snapshot(3, headphone_motion::snapshot()).prompt.is_some());
        c.open("water", 4, true);
        c.tick_with_activity(5, 720, None, false);
        assert!(c.snapshot(5, headphone_motion::snapshot()).prompt.is_some());
    }
    #[test]
    fn automatic_prompt_and_exercise_timer_pause_while_inactive() {
        let mut c = Core::new(Settings::default(), 0);
        c.open("water", 1, false);
        c.tick_with_activity(700, 720, None, false);
        assert!(c
            .snapshot(700, headphone_motion::snapshot())
            .prompt
            .is_none());
        c.tick_with_activity(701, 720, None, true);
        assert_eq!(c.prompt.as_ref().map(|p| p.phase.as_str()), Some("ready"));

        c.open("break", 702, false);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "start", 702).unwrap();
        let remaining = c.prompt.as_ref().unwrap().remaining_seconds;
        c.tick_with_activity(1402, 720, None, false);
        assert!(c
            .snapshot(1402, headphone_motion::snapshot())
            .prompt
            .is_none());
        c.tick_with_activity(1403, 720, None, true);
        assert_eq!(c.prompt.as_ref().unwrap().phase, "active");
        assert_eq!(c.prompt.as_ref().unwrap().remaining_seconds, remaining);
    }
    #[test]
    fn bounds_and_unknown_fields() {
        let mut s = enabled();
        s.water.duration_seconds = 1;
        assert!(s.validate().is_err());
        let mut value = serde_json::to_value(Settings::default()).unwrap();
        value["unknown"] = true.into();
        assert!(serde_json::from_value::<Settings>(value).is_err());
    }
    #[test]
    fn quiet_wrap_and_pause() {
        let mut c = Core::new(enabled(), 0);
        c.settings.quiet_hours.enabled = true;
        assert!(c.settings.quiet_hours.contains(23 * 60));
        assert!(c.settings.quiet_hours.contains(7 * 60));
        assert!(!c.settings.quiet_hours.contains(12 * 60));
        c.action("", "pause", 0).unwrap();
        assert_eq!(c.paused_until, Some(3600));
        c.action("", "resume", 1).unwrap();
        assert_eq!(c.due[1], Some(1201));
    }

    #[test]
    fn non_wrapping_quiet_hours_and_settings_edits_clear_stale_state() {
        let mut hours = QuietHours {
            enabled: true,
            start_minutes: 600,
            end_minutes: 900,
        };
        assert!(hours.contains(600));
        assert!(hours.contains(899));
        assert!(!hours.contains(900));
        hours.enabled = false;
        assert!(!hours.contains(700));

        let mut c = Core::new(enabled(), 10);
        c.dwell_since = Some(11);
        c.open("posture", 12, false);
        let mut changed = c.settings.clone();
        changed.posture.dwell_seconds += 1;
        changed.quiet_hours.start_minutes += 1;
        c.set_settings(changed, 13);
        assert_eq!(c.dwell_since, None);
        assert_eq!(c.posture_after, 13);
        assert!(c.prompt.is_none());
    }

    #[test]
    fn the_companion_counts_as_visible_only_once_its_window_exists_and_is_shown() {
        let app = tauri::test::mock_app();
        assert!(!companion_visible(app.handle()), "no companion window yet");
        let mut core = Core::new(Settings::default(), 0);
        core.open("water", 1, true);
        let shown = core.snapshot(1, headphone_motion::snapshot());
        view(app.handle(), &shown).unwrap();
        // The mock window does not track hide(); the real show and hide are covered by the installed check.
        assert!(companion_visible(app.handle()));
    }

    #[test]
    fn posture_preview_can_close_and_posture_snooze_uses_its_own_delay() {
        let mut s = Settings::default();
        s.quiet_hours.enabled = false;
        s.posture.enabled = true;
        let mut c = Core::new(s, 0);
        c.open("posture", 1, true);
        assert!(c.action("", "close-preview", 2).is_ok());
        assert!(c.prompt.is_none());
        c.open("posture", 3, false);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "snooze", 4).unwrap();
        assert_eq!(c.posture_after, 304);
        assert_eq!(c.dwell_since, None);
        assert!(c.action("", "close-preview", 5).is_ok());
        assert!(c.action("missing", "unsupported", 5).is_err());
        c.open("posture", 6, true);
        let id = c.prompt.as_ref().unwrap().id.clone();
        assert!(c.action(&id, "unsupported", 6).is_err());
    }

    #[test]
    fn native_clock_helpers_return_bounded_monotonic_values() {
        let before = now();
        let wall = wall_now();
        let local_minute = minute();
        assert!(now() >= before);
        assert!(wall > 1_700_000_000);
        assert!(local_minute < 1440);
    }

    #[test]
    fn snapshots_report_countdown_pause_and_quiet_deadlines() {
        let mut c = Core::new(enabled(), 0);
        c.settings.posture.enabled = true;
        let initial = c.snapshot(10, headphone_motion::snapshot());
        assert_eq!(initial.activity_supported, cfg!(target_os = "macos"));
        assert_eq!(initial.next_due[0].seconds, Some(2990));
        assert_eq!(initial.next_due[3].kind, "posture");
        assert_eq!(initial.next_due[3].seconds, Some(290));
        let serialized = serde_json::to_value(&initial).unwrap();
        assert_eq!(
            serialized["activitySupported"].as_bool(),
            Some(cfg!(target_os = "macos"))
        );
        assert_eq!(serialized["nextDue"][3]["kind"], "posture");
        assert_eq!(serialized["nextDue"][3]["seconds"], 290);
        c.open("break", 11, false);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "start", 11).unwrap();
        c.tick(60, 720, None);
        assert_eq!(c.prompt.as_ref().unwrap().remaining_seconds, Some(71));
        c.tick(120, 720, None);
        c.tick(131, 720, None);
        assert_eq!(c.prompt.as_ref().unwrap().phase, "complete");
        assert_eq!(c.prompt.as_ref().unwrap().remaining_seconds, None);
        c.action("", "pause", 132).unwrap();
        let paused = c.snapshot(150, headphone_motion::snapshot());
        assert_eq!(paused.paused_remaining_seconds, Some(3582));
        assert!(paused.next_due.iter().all(|due| due.seconds.is_none()));
        c.settings.quiet_hours.enabled = true;
        c.tick(151, 1320, None);
        let quiet = c.snapshot(152, headphone_motion::snapshot());
        assert!(quiet.next_due.iter().all(|due| due.seconds.is_none()));
    }
    #[test]
    fn ready_expires_and_rearms_only_its_kind() {
        let mut c = Core::new(enabled(), 0);
        c.open("eyes", 1, false);
        c.tick(60, 720, None);
        assert!(c.prompt.is_some());
        c.tick(61, 720, None);
        assert!(c.prompt.is_none());
        assert_eq!(c.due, [Some(3000), Some(1261), Some(3600)]);
    }
    #[test]
    fn snooze_and_preview_do_not_disturb_other_deadlines() {
        let mut c = Core::new(enabled(), 0);
        let due = c.due;
        c.open("water", 1, true);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "snooze", 2).unwrap();
        assert_eq!(c.due, due);
        c.open("water", 3, false);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "snooze", 4).unwrap();
        assert_eq!(c.due, [Some(3000), Some(1200), Some(304)]);
        assert!(c.action(&id, "done", 5).is_err());
    }
    #[test]
    fn settings_rearm_only_changed_reminder() {
        let mut c = Core::new(enabled(), 0);
        let mut s = c.settings.clone();
        s.water.interval_minutes = 90;
        c.set_settings(s, 100);
        assert_eq!(c.due, [Some(3000), Some(1200), Some(5500)]);
        let mut s = c.settings.clone();
        s.eyes.enabled = false;
        c.open("eyes", 100, false);
        c.set_settings(s, 101);
        assert!(c.prompt.is_none());
        assert_eq!(c.due[1], None);
    }
    #[test]
    fn quiet_exit_and_wake_have_no_backlog() {
        let mut c = Core::new(enabled(), 0);
        c.settings.quiet_hours.enabled = true;
        c.tick(1, 1320, None);
        assert!(c.quiet);
        c.tick(2, 480, None);
        assert_eq!(c.due[1], Some(1202));
        c.tick(10000, 720, None);
        assert!(c.prompt.is_none());
        assert_eq!(c.due[1], Some(11200));
        c.tick(2, 720, None);
        assert_eq!(c.due[1], Some(1202));
    }
    #[test]
    fn monotonic_deadlines_ignore_small_wall_adjustments_but_reset_after_sleep_or_regression() {
        let mut c = Core::new(enabled(), 0);
        c.observe_wall(1000, 0);
        c.observe_wall(1030, 1);
        assert_eq!(c.due[1], Some(1200));
        c.open("eyes", 1, false);
        c.observe_wall(5000, 2);
        assert_eq!(c.due[1], Some(1202));
        assert!(c.prompt.is_none());
        c.observe_wall(4999, 3);
        assert_eq!(c.due[1], Some(1203));
        c.settings.quiet_hours.enabled = true;
        c.tick(4, 1320, None);
        let due = c.due;
        c.tick(5, 1321, None);
        assert_eq!(c.due, due);
    }
    #[test]
    fn manual_wall_clock_corrections_rearm_monotonic_reminder_deadlines() {
        let mut spring = Core::new(enabled(), 0);
        spring.observe_wall(10_000, 0);
        spring.open("eyes", 1, false);
        spring.observe_wall(13_600, 2); // local wall clock advanced by one DST hour
        assert!(spring.prompt.is_none());
        assert_eq!(spring.due[1], Some(1202));

        let mut autumn = Core::new(enabled(), 0);
        autumn.observe_wall(13_600, 0);
        autumn.open("eyes", 1, false);
        autumn.observe_wall(10_000, 2); // local wall clock moved back by one DST hour
        assert!(autumn.prompt.is_none());
        assert_eq!(autumn.due[1], Some(1202));
    }
    #[test]
    fn quiet_hours_follow_local_minutes_across_daylight_saving_skips_and_repeats() {
        let mut spring = Core::new(enabled(), 0);
        spring.settings.quiet_hours.enabled = true;
        spring.settings.quiet_hours.start_minutes = 90; // 01:30
        spring.settings.quiet_hours.end_minutes = 210; // 03:30
        spring.tick(0, 119, None); // 01:59, immediately before the spring-forward gap
        assert!(spring.quiet);
        spring.tick(1, 180, None); // 03:00, after 02:00–02:59 was skipped
        assert!(spring.quiet);
        spring.tick(2, 210, None);
        assert!(!spring.quiet);

        let mut autumn = Core::new(enabled(), 0);
        autumn.settings.quiet_hours.enabled = true;
        autumn.settings.quiet_hours.start_minutes = 30; // 00:30
        autumn.settings.quiet_hours.end_minutes = 150; // 02:30
        autumn.tick(0, 119, None); // first 01:59 before clocks repeat
        assert!(autumn.quiet);
        autumn.tick(1, 60, None); // repeated 01:00 after the fall-back transition
        assert!(autumn.quiet);
        autumn.tick(2, 150, None);
        assert!(!autumn.quiet);
    }
    #[test]
    fn countdown_requires_completion_and_water_completes_immediately() {
        let mut c = Core::new(enabled(), 0);
        c.open("break", 1, false);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "start", 1).unwrap();
        assert!(c.action(&id, "done", 2).is_err());
        c.action(&id, "dismiss", 2).unwrap();
        c.open("water", 3, true);
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "start", 3).unwrap();
        assert_eq!(c.prompt.as_ref().unwrap().phase, "complete");
        c.action(&id, "done", 4).unwrap();
        assert!(c.prompt.is_none());
    }
    #[test]
    fn posture_requires_stable_calibrated_fresh_dwell_and_cooldown() {
        let mut s = Settings::default();
        s.quiet_hours.enabled = false;
        s.posture.enabled = true;
        s.posture.dwell_seconds = 5;
        let mut c = Core::new(s, 0);
        c.posture_after = 0;
        let mut m = MotionSnapshot {
            status: "ready".into(),
            calibrated: true,
            stable: true,
            relative_pitch_degrees: Some(16.0),
            relative_roll_degrees: Some(0.0),
        };
        for n in 1..5 {
            c.tick(n, 720, Some(&m));
        }
        assert!(c.prompt.is_none());
        m.status = "stale".into();
        c.tick(5, 720, Some(&m));
        m.status = "ready".into();
        for n in 6..=11 {
            c.tick(n, 720, Some(&m));
        }
        assert_eq!(c.prompt.as_ref().unwrap().kind, "posture");
        let id = c.prompt.as_ref().unwrap().id.clone();
        c.action(&id, "done", 11).unwrap();
        for n in 12..=20 {
            c.tick(n, 720, Some(&m));
        }
        assert!(c.prompt.is_none());
        m.relative_pitch_degrees = Some(f64::NAN);
        c.tick(21, 720, Some(&m));
        assert_eq!(c.dwell_since, None);
    }
    #[test]
    fn all_bounds_and_nested_unknown_fields_are_rejected() {
        for field in ["breaks", "eyes", "water"] {
            for (key, bad) in [
                ("intervalMinutes", 0),
                ("durationSeconds", 1000),
                ("snoozeMinutes", 0),
            ] {
                let mut value = serde_json::to_value(Settings::default()).unwrap();
                value[field][key] = bad.into();
                let s: Settings = serde_json::from_value(value).unwrap();
                assert!(s.validate().is_err());
            }
        }
        for (key, bad) in [
            ("dwellSeconds", 0),
            ("cooldownMinutes", 61),
            ("snoozeMinutes", 0),
        ] {
            let mut value = serde_json::to_value(Settings::default()).unwrap();
            value["posture"][key] = bad.into();
            assert!(serde_json::from_value::<Settings>(value)
                .unwrap()
                .validate()
                .is_err());
        }
        let mut s = Settings::default();
        s.version = 2;
        assert!(s.validate().is_err());
        s.version = 1;
        s.corner = "center".into();
        assert!(s.validate().is_err());
        s.corner = "top-left".into();
        s.quiet_hours.end_minutes = s.quiet_hours.start_minutes;
        assert!(s.validate().is_err());
        s.quiet_hours.end_minutes = 1440;
        assert!(s.validate().is_err());
        let mut value = serde_json::to_value(Settings::default()).unwrap();
        value["eyes"]["unknown"] = true.into();
        assert!(serde_json::from_value::<Settings>(value).is_err());
    }
    #[test]
    fn persistence_is_atomic_opt_in_and_reports_corruption() {
        let dir = std::env::temp_dir().join(format!(
            "officekit-ergonomics-test-{}",
            uuid::Uuid::new_v4()
        ));
        let path = dir.join("ergonomics-v1.json");
        assert!(load(&path).1.is_none());
        let mut s = enabled();
        s.posture.enabled = true;
        save(&path, &s).unwrap();
        let (loaded, error) = load(&path);
        assert!(error.is_none());
        assert!(loaded.posture.enabled);
        assert!(loaded.water.enabled);
        let before = fs::read(&path).unwrap();
        s.water.duration_seconds = 1;
        assert!(save(&path, &s).is_err());
        assert_eq!(fs::read(&path).unwrap(), before);
        fs::write(&path, b"invalid").unwrap();
        let (loaded, error) = load(&path);
        assert!(error.is_some());
        assert!(!loaded.water.enabled);
        assert_eq!(fs::read(&path).unwrap(), b"invalid");
        fs::write(&path, vec![0; 16385]).unwrap();
        assert!(load(&path).1.is_some());
        let directory = dir.join("directory-settings");
        fs::create_dir(&directory).unwrap();
        assert!(load(&directory).1.unwrap().contains("regular file"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let link = dir.join("settings-link");
            symlink(&path, &link).unwrap();
            assert!(load(&link).1.unwrap().contains("regular file"));
        }
        let not_dir = dir.join("not-directory");
        fs::write(&not_dir, b"file").unwrap();
        assert!(save(&not_dir.join("settings.json"), &Settings::default()).is_err());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_mascot_press_outlasts_the_hide_grace_for_reopen_events() {
        let long_ago = Instant::now() - COMPANION_HIDE_REOPEN_GRACE - Duration::from_secs(1);
        *LAST_COMPANION_HIDE.lock().unwrap() = Some(long_ago);
        *LAST_COMPANION_PRESS.lock().unwrap() = None;
        assert!(!companion_hid_recently());
        // End early, Done, Start and close all go through the same press note.
        note_companion_press();
        *LAST_COMPANION_HIDE.lock().unwrap() = Some(long_ago);
        assert!(companion_hid_recently());
        *LAST_COMPANION_PRESS.lock().unwrap() =
            Some(Instant::now() - COMPANION_PRESS_REOPEN_GRACE - Duration::from_secs(1));
        assert!(!companion_hid_recently());
    }
}
