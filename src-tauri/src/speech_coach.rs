//! Local, bounded speech-coaching metrics and session history.
//! Audio samples never enter this module or its persisted records.

use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::{Duration, Instant},
};
use tauri::State;

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_dictation_microphone_permission_status() -> i32;
    fn officekit_dictation_has_audio_input() -> i32;
    fn officekit_dictation_coach_start() -> i32;
    fn officekit_dictation_coach_stop() -> i32;
    fn officekit_dictation_coach_overlay_configure(placement: i32, visible: i32);
    fn officekit_dictation_polish_available() -> i32;
}

const STORE_FILE: &str = "speech-coach.json";
const MAX_STORE_BYTES: u64 = 256 * 1024;
const MAX_SESSIONS: usize = 120;
const MAX_SESSION_SECONDS: u32 = 4 * 60 * 60;
const MIN_PACE_WORDS: u32 = 20;
const MIN_PACE_SPEECH_SECONDS: u32 = 10;
const SETTINGS_FILE: &str = "speech-coach-settings.json";
const MAX_SETTINGS_BYTES: u64 = 16 * 1024;
const MAX_TRANSCRIPT_BYTES: usize = 256 * 1024;
const MAX_PITCH_WINDOWS: usize = 1_000;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoachContext {
    #[default]
    Casual,
    Practice,
    Presentation,
    Interview,
    Dictation,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoachFocus {
    #[default]
    Pace,
    Fillers,
    Pauses,
    Grammar,
    Vocabulary,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoachPlacement {
    #[default]
    TopCenter,
    TopLeft,
    TopRight,
    BottomCenter,
    BottomLeft,
    BottomRight,
}

impl CoachPlacement {
    fn code(self) -> i32 {
        match self {
            Self::TopCenter => 0,
            Self::TopLeft => 1,
            Self::TopRight => 2,
            Self::BottomCenter => 3,
            Self::BottomLeft => 4,
            Self::BottomRight => 5,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoachSettings {
    pub version: u8,
    pub enabled: bool,
    pub paused: bool,
    pub overlay_visible: bool,
    pub context: CoachContext,
    pub focus: CoachFocus,
    pub placement: CoachPlacement,
    pub target_pace_min: u16,
    pub target_pace_max: u16,
    pub history_days: u16,
    pub retain_examples: bool,
}

impl Default for CoachSettings {
    fn default() -> Self {
        Self {
            version: 1,
            enabled: false,
            paused: false,
            overlay_visible: true,
            context: CoachContext::Casual,
            focus: CoachFocus::Pace,
            placement: CoachPlacement::TopCenter,
            target_pace_min: 110,
            target_pace_max: 160,
            history_days: 90,
            retain_examples: false,
        }
    }
}

impl CoachSettings {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.version != 1
            || !(60..=240).contains(&self.target_pace_min)
            || !(60..=240).contains(&self.target_pace_max)
            || self.target_pace_min >= self.target_pace_max
            || !(1..=365).contains(&self.history_days)
        {
            return Err("Speech Coach settings are outside supported limits");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoachSession {
    pub id: String,
    pub started_at: String,
    pub context: CoachContext,
    pub focus: CoachFocus,
    pub practice_goal: String,
    pub duration_seconds: u32,
    pub speech_seconds: u32,
    pub recognized_words: u32,
    pub filler_words: u32,
    pub pace_wpm: Option<u16>,
    pub time_in_pace_range_percent: Option<u8>,
    #[serde(default)]
    pub pitch_median_hz: Option<u16>,
    #[serde(default)]
    pub pitch_range_hz: Option<u16>,
    #[serde(default)]
    pub grammar_suggestions: u16,
    #[serde(default)]
    pub vocabulary_suggestions: u16,
    #[serde(default)]
    pub language_patterns: Vec<String>,
    pub dismissed_patterns: Vec<String>,
    pub useful_patterns: Vec<String>,
    #[serde(default)]
    pub examples: Vec<String>,
}

impl CoachSession {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.is_empty()
            || self.id.len() > 64
            || self.started_at.len() > 40
            || self.practice_goal.len() > 160
            || self.duration_seconds > MAX_SESSION_SECONDS
            || self.speech_seconds > self.duration_seconds
            || self.filler_words > self.recognized_words
            || self.time_in_pace_range_percent.is_some_and(|v| v > 100)
            || self
                .pitch_median_hz
                .is_some_and(|v| !(50..=400).contains(&v))
            || self.pitch_range_hz.is_some_and(|v| v > 350)
            || self.dismissed_patterns.len() > 64
            || self.useful_patterns.len() > 64
            || self.language_patterns.len() > 64
            || self
                .dismissed_patterns
                .iter()
                .any(|v| v.is_empty() || v.len() > 64)
            || self
                .useful_patterns
                .iter()
                .any(|v| v.is_empty() || v.len() > 64)
            || self.examples.len() > 20
            || self.examples.iter().any(|v| v.len() > 512)
            || self
                .language_patterns
                .iter()
                .any(|value| value.len() > 64 || !is_supported_language_pattern(value))
        {
            return Err("Speech Coach session is outside supported limits");
        }
        Ok(())
    }
}

impl CoachSessionInput {
    fn validate(&self) -> Result<(), &'static str> {
        if self.text.len() > MAX_TRANSCRIPT_BYTES
            || self.duration_seconds > MAX_SESSION_SECONDS
            || self.speech_seconds > self.duration_seconds
            || self
                .pitch_median_hz
                .is_some_and(|value| !(50..=400).contains(&value))
            || self.pitch_range_hz.is_some_and(|value| value > 350)
        {
            return Err("Speech Coach session is outside supported limits");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoachStore {
    pub version: u8,
    pub sessions: Vec<CoachSession>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CoachStatus {
    pub settings: CoachSettings,
    pub session_count: usize,
    pub state: &'static str,
    pub language_model_available: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoachSessionInput {
    pub text: String,
    pub duration_seconds: u32,
    pub speech_seconds: u32,
    #[serde(default)]
    pub capture_generation: Option<u64>,
    #[serde(default)]
    pub pitch_median_hz: Option<u16>,
    #[serde(default)]
    pub pitch_range_hz: Option<u16>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PitchStats {
    pub median_hz: u16,
    pub range_hz: u16,
}

pub struct CoachRuntime(Mutex<CoachRuntimeState>);

struct CoachRuntimeState {
    settings: CoachSettings,
    store: CoachStore,
    directory: PathBuf,
    capture_available: bool,
    /// A solo Listen In session is running. Runtime only: never saved, never restored.
    listen_in: bool,
    /// A meeting recording is being coached, from the microphone only. Runtime only, like Listen In.
    meeting_coach: bool,
    /// The Listen In session was started by Coach me on a call reminder, so it ends with the call.
    /// It belongs to the session: every route that ends Listen In clears it. Runtime only.
    coach_me: Option<CoachMe>,
    analysis_ready: bool,
    capture_epoch: u64,
    last_live_cue_at: Option<Instant>,
    last_language_cue_at: Option<Instant>,
    active_session: Option<CoachActiveSession>,
    recent_language_sentences: VecDeque<String>,
    language_suggestions_by_capture: BTreeMap<u64, Vec<String>>,
}

struct CoachActiveSession {
    id: String,
    started_at: String,
    started: Instant,
    context: CoachContext,
    focus: CoachFocus,
    practice_goal: String,
    speech_seconds: f64,
    recognized_words: u32,
    filler_words: u32,
    pitch_windows: Vec<PitchStats>,
    grammar_suggestions: u16,
    vocabulary_suggestions: u16,
    language_patterns: Vec<String>,
}

impl CoachRuntime {
    pub fn load(directory: PathBuf) -> Self {
        let settings_path = directory.join(SETTINGS_FILE);
        let settings = fs::metadata(&settings_path)
            .ok()
            .filter(|metadata| metadata.is_file() && metadata.len() <= MAX_SETTINGS_BYTES)
            .and_then(|_| fs::read(settings_path).ok())
            .and_then(|bytes| serde_json::from_slice::<CoachSettings>(&bytes).ok())
            .filter(|settings| settings.validate().is_ok())
            .unwrap_or_default();
        Self(Mutex::new(CoachRuntimeState {
            settings,
            store: load_store(&directory),
            directory,
            capture_available: false,
            listen_in: false,
            meeting_coach: false,
            coach_me: None,
            analysis_ready: false,
            capture_epoch: 0,
            last_live_cue_at: None,
            last_language_cue_at: None,
            active_session: None,
            recent_language_sentences: VecDeque::new(),
            language_suggestions_by_capture: BTreeMap::new(),
        }))
    }
}

pub fn record_standalone_segment(
    runtime: &CoachRuntime,
    text: &str,
    speech_seconds: f64,
    pitch: Option<PitchStats>,
    origin_epoch: u64,
) -> bool {
    if !speech_seconds.is_finite() || speech_seconds <= 0.0 || text.len() > MAX_TRANSCRIPT_BYTES {
        return false;
    }
    let Ok(mut state) = runtime.0.lock() else {
        return false;
    };
    if !standalone_capture_epoch_is_current(&state, origin_epoch) {
        return false;
    }
    let metrics = metrics_for_finalized_text(text, speech_seconds.min(u32::MAX as f64) as u32);
    if metrics.recognized_words == 0 {
        return false;
    }
    if state.active_session.is_none() {
        state.active_session = Some(CoachActiveSession {
            id: uuid::Uuid::new_v4().to_string(),
            started_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
            started: Instant::now(),
            context: state.settings.context,
            focus: state.settings.focus,
            practice_goal: practice_goal(&state.settings),
            speech_seconds: 0.0,
            recognized_words: 0,
            filler_words: 0,
            pitch_windows: Vec::new(),
            grammar_suggestions: 0,
            vocabulary_suggestions: 0,
            language_patterns: Vec::new(),
        });
    }
    if let Some(session) = state.active_session.as_mut() {
        session.speech_seconds =
            (session.speech_seconds + speech_seconds).min(MAX_SESSION_SECONDS as f64);
        session.recognized_words = session
            .recognized_words
            .saturating_add(metrics.recognized_words);
        session.filler_words = session.filler_words.saturating_add(metrics.filler_words);
        if session.pitch_windows.len() < MAX_PITCH_WINDOWS {
            if let Some(pitch) = pitch {
                session.pitch_windows.push(pitch);
            }
        }
    }
    true
}

fn standalone_capture_epoch_is_current(state: &CoachRuntimeState, origin_epoch: u64) -> bool {
    state.capture_epoch == origin_epoch
        && state.settings.enabled
        && !state.settings.paused
        && state.capture_available
        && (state.listen_in || state.meeting_coach)
        && state.analysis_ready
}

/// A call app must be gone this many seconds before Coach me ends, so a brief drop is ignored.
pub const COACH_ME_CALL_GONE_SECONDS: u32 = 20;

/// Coach me on a call: it ends once a call has been seen and then gone for a while. A session
/// started before any call app held the microphone (an in-person or not yet joined meeting) never
/// ends by itself; the person ends it from the HUD or Quick Controls.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct CoachMe {
    call_seen: bool,
    absent_seconds: u32,
}

impl CoachMe {
    /// One second passed. Returns true when the call has been gone long enough to end the session.
    fn tick(&mut self, call_present: bool) -> bool {
        if call_present {
            self.call_seen = true;
            self.absent_seconds = 0;
            return false;
        }
        if !self.call_seen {
            return false;
        }
        self.absent_seconds += 1;
        self.absent_seconds >= COACH_ME_CALL_GONE_SECONDS
    }
}

/// Why Coach me cannot start now, or None. A meeting recording is coached by itself while Speech
/// Coach is on, and a Listen In session already owns the microphone window.
pub fn coach_me_blocker(
    meeting_recording: bool,
    listen_in: bool,
    meeting_coach: bool,
) -> Option<&'static str> {
    if meeting_recording {
        return Some("A meeting recording is running. Speech Coach coaches it while it is on.");
    }
    if listen_in || meeting_coach {
        return Some("Speech Coach is already listening.");
    }
    None
}

pub fn coach_me_blocker_for_runtime(
    runtime: &CoachRuntime,
    meeting_recording: bool,
) -> Option<&'static str> {
    let state = runtime.0.lock().ok()?;
    coach_me_blocker(meeting_recording, state.listen_in, state.meeting_coach)
}

/// Marks the running Listen In session as started by Coach me, so it ends with the call.
pub fn mark_coach_me(runtime: &CoachRuntime) {
    if let Ok(mut state) = runtime.0.lock() {
        if state.listen_in {
            state.coach_me = Some(CoachMe::default());
        }
    }
}

/// Called every second with whether a call app holds the microphone. Ends a Coach me session,
/// saving its note, once the call has gone. Returns true when it ended the session.
pub fn coach_me_tick(runtime: &CoachRuntime, call_present: bool) -> bool {
    let Ok(mut state) = runtime.0.lock() else {
        return false;
    };
    let Some(mut coach_me) = state.coach_me else {
        return false;
    };
    if !state.listen_in {
        state.coach_me = None;
        return false;
    }
    if !coach_me.tick(call_present) {
        state.coach_me = Some(coach_me);
        return false;
    }
    let _ = end_listen_in(&mut state);
    advance_capture_epoch(&mut state);
    true
}

pub fn coach_me_active(runtime: &CoachRuntime) -> bool {
    runtime
        .0
        .lock()
        .is_ok_and(|state| state.coach_me.is_some() && state.listen_in)
}

/// The analyzer leaves the microphone window alone for a dictation, and for a meeting recording
/// that nobody is coaching. A coached meeting is analysed: the window holds only the microphone.
pub fn analyzer_steps_aside(
    capture_active: bool,
    meeting_recording: bool,
    meeting_coached: bool,
) -> bool {
    let dictating = capture_active && !meeting_recording;
    dictating || (meeting_recording && !meeting_coached)
}

/// Whether a drained window belongs to standalone coaching (Listen In or a meeting), as opposed to a
/// dictation that has since started.
pub fn analyzer_window_is_standalone(capture_active: bool, meeting_recording: bool) -> bool {
    !capture_active || meeting_recording
}

/// What happened when the coach tried to join a meeting recording.
#[derive(Debug, PartialEq, Eq)]
pub enum MeetingAttach {
    /// Speech Coach is off, paused or unavailable: the meeting records exactly as before.
    Skipped,
    /// The capture did not let the coach join (someone else owns it).
    NotJoined,
    /// Joined, but the coach cannot analyse, so it left again.
    Released,
    Coaching,
}

/// Joins the coach to a meeting recording that has just started. The collaborators are passed in
/// so the four outcomes can be tested without a microphone.
pub fn attach_to_meeting(
    attach_enabled: bool,
    join_capture: impl FnOnce() -> bool,
    start_coaching: impl FnOnce() -> bool,
    open_workspace: impl FnOnce(),
    release_capture: impl FnOnce(),
) -> MeetingAttach {
    if !attach_enabled {
        return MeetingAttach::Skipped;
    }
    if !join_capture() {
        return MeetingAttach::NotJoined;
    }
    if !start_coaching() {
        release_capture();
        return MeetingAttach::Released;
    }
    open_workspace();
    MeetingAttach::Coaching
}

/// Starts or ends coaching of a meeting recording. Returns whether the coach is now coaching it,
/// which is only when Speech Coach is on and not paused and no Listen In session is running.
/// Ending saves one note for the meeting; the recording has already released the capture.
pub fn set_meeting_coach(runtime: &CoachRuntime, active: bool) -> bool {
    let Ok(mut state) = runtime.0.lock() else {
        return false;
    };
    if active {
        if !state.settings.enabled
            || state.settings.paused
            || !state.capture_available
            || state.listen_in
        {
            return false;
        }
        if !state.meeting_coach {
            state.meeting_coach = true;
            advance_capture_epoch(&mut state);
        }
        return true;
    }
    // A history write failure must not keep the coach attached to a meeting that ended.
    let _ = end_meeting_coach(&mut state, false);
    false
}

/// Ends meeting coaching: saves the one note, clears the flag and, when the recording is still
/// running (the person turned Speech Coach off or paused it), leaves the capture so the HUD goes.
fn end_meeting_coach(state: &mut CoachRuntimeState, release_capture: bool) -> Result<(), String> {
    if !state.meeting_coach {
        return Ok(());
    }
    let saved = finish_standalone_session(state);
    state.meeting_coach = false;
    advance_capture_epoch(state);
    let released = if release_capture {
        stop_coach_capture()
    } else {
        Ok(())
    };
    saved.and(released)
}

/// Ends every kind of coached session. Used when Speech Coach is turned off or paused.
fn end_coached_sessions(state: &mut CoachRuntimeState) -> Result<(), String> {
    let meeting = end_meeting_coach(state, true);
    let listen_in = end_listen_in(state);
    meeting.and(listen_in)
}

/// Leaves a capture the coach joined but cannot analyse.
pub fn release_attached_coach() {
    let _ = stop_coach_capture();
}

pub fn meeting_coach_active(runtime: &CoachRuntime) -> bool {
    runtime.0.lock().is_ok_and(|state| state.meeting_coach)
}

pub fn standalone_analysis_epoch(runtime: &CoachRuntime) -> Option<u64> {
    let state = runtime.0.lock().ok()?;
    standalone_capture_epoch_is_current(&state, state.capture_epoch).then_some(state.capture_epoch)
}

pub fn standalone_analysis_is_current(runtime: &CoachRuntime, origin_epoch: u64) -> bool {
    runtime
        .0
        .lock()
        .is_ok_and(|state| standalone_capture_epoch_is_current(&state, origin_epoch))
}

pub(crate) fn standalone_window_matches_capture(
    origin_mode_epoch: u64,
    current_mode_epoch: u64,
    origin_overlay_generation: u64,
    current_overlay_generation: u64,
    standalone_mode: bool,
) -> bool {
    standalone_mode
        && origin_mode_epoch == current_mode_epoch
        && origin_overlay_generation == current_overlay_generation
}

fn advance_capture_epoch(state: &mut CoachRuntimeState) {
    state.capture_epoch = state.capture_epoch.wrapping_add(1);
}

fn finish_standalone_session(state: &mut CoachRuntimeState) -> Result<(), String> {
    // The session leaves the runtime whether or not it can be saved: a failed save loses that one
    // note, but must never leave it open for the next meeting or Listen In run to append to.
    let Some(active) = state.active_session.take() else {
        return Ok(());
    };
    if active.recognized_words == 0 {
        return Ok(());
    }
    let speech_seconds = active
        .speech_seconds
        .round()
        .clamp(0.0, MAX_SESSION_SECONDS as f64) as u32;
    let pace_wpm = (active.recognized_words >= MIN_PACE_WORDS
        && active.speech_seconds >= MIN_PACE_SPEECH_SECONDS as f64)
        .then(|| {
            ((active.recognized_words as f64 * 60.0 / active.speech_seconds).round() as u16)
                .min(400)
        });
    let pitch_median_hz = median_u16(active.pitch_windows.iter().map(|window| window.median_hz));
    let pitch_range_hz = median_u16(active.pitch_windows.iter().map(|window| window.range_hz));
    let session = CoachSession {
        id: active.id.clone(),
        started_at: active.started_at.clone(),
        context: active.context,
        focus: active.focus,
        practice_goal: active.practice_goal.clone(),
        duration_seconds: (active.started.elapsed().as_secs() as u32)
            .max(speech_seconds)
            .min(MAX_SESSION_SECONDS),
        speech_seconds,
        recognized_words: active.recognized_words,
        filler_words: active.filler_words.min(active.recognized_words),
        pace_wpm,
        time_in_pace_range_percent: None,
        pitch_median_hz,
        pitch_range_hz,
        grammar_suggestions: active.grammar_suggestions,
        vocabulary_suggestions: active.vocabulary_suggestions,
        language_patterns: active.language_patterns.clone(),
        dismissed_patterns: Vec::new(),
        useful_patterns: Vec::new(),
        examples: Vec::new(),
    };
    let mut updated = state.store.clone();
    updated.insert(session).map_err(str::to_string)?;
    save_store(&state.directory, &updated)?;
    state.store = updated;
    Ok(())
}

fn median_u16(values: impl Iterator<Item = u16>) -> Option<u16> {
    let mut values = values.collect::<Vec<_>>();
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    Some(values[values.len() / 2])
}

pub fn finish_standalone_session_for_runtime(runtime: &CoachRuntime) -> Result<(), String> {
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach history is unavailable".to_string())?;
    finish_standalone_session(&mut state)
}

pub fn set_analysis_ready(runtime: &CoachRuntime, ready: bool) {
    if let Ok(mut state) = runtime.0.lock() {
        if state.analysis_ready != ready {
            advance_capture_epoch(&mut state);
        }
        state.analysis_ready = ready;
    }
}

/// A failed first model load must not leave Listen In capturing unusable windows.
pub fn stop_for_model_failure(runtime: &CoachRuntime) {
    if let Ok(mut state) = runtime.0.lock() {
        // A history write failure must not prevent microphone shutdown. A coached meeting leaves
        // its capture too, so the HUD does not stay up for the rest of the recording.
        let _ = end_meeting_coach(&mut state, true);
        if state.listen_in {
            let _ = finish_standalone_session(&mut state);
            let _ = stop_coach_capture();
            state.listen_in = false;
        }
        state.coach_me = None;
        state.analysis_ready = false;
        advance_capture_epoch(&mut state);
    }
}

pub fn live_cue(
    runtime: &CoachRuntime,
    finalized_text: &str,
    speech_seconds: f64,
) -> Option<String> {
    if !speech_seconds.is_finite() || speech_seconds < MIN_PACE_SPEECH_SECONDS as f64 {
        return None;
    }
    let Ok(mut state) = runtime.0.lock() else {
        return None;
    };
    if !state.settings.enabled || state.settings.paused || !state.capture_available {
        return None;
    }
    live_cue_for_state(&mut state, finalized_text, speech_seconds)
}

fn live_cue_for_state(
    state: &mut CoachRuntimeState,
    finalized_text: &str,
    speech_seconds: f64,
) -> Option<String> {
    let pace = estimated_pace_wpm(finalized_text, speech_seconds)?;
    let cue = if pace > state.settings.target_pace_max {
        format!(
            "Estimated pace is above your {}–{} WPM zone. Ease into your next sentence.",
            state.settings.target_pace_min, state.settings.target_pace_max
        )
    } else if pace < state.settings.target_pace_min {
        format!(
            "Estimated pace is below your {}–{} WPM zone. Bring your next point forward.",
            state.settings.target_pace_min, state.settings.target_pace_max
        )
    } else {
        "Estimated pace is in your zone. Pause briefly before your next point.".to_string()
    };
    let now = Instant::now();
    if state
        .last_live_cue_at
        .is_some_and(|last| now.duration_since(last) < Duration::from_secs(20))
    {
        return None;
    }
    state.last_live_cue_at = Some(now);
    Some(cue)
}

pub fn publish_standalone_feedback(
    runtime: &CoachRuntime,
    origin_epoch: u64,
    text: &str,
    speech_seconds: f64,
    pitch: Option<PitchStats>,
    publish: impl FnOnce(Option<(u16, u16, u16)>, Option<PitchStats>, Option<String>),
) -> bool {
    let Ok(mut state) = runtime.0.lock() else {
        return false;
    };
    if !standalone_capture_epoch_is_current(&state, origin_epoch) {
        return false;
    }
    let pace = estimated_pace_wpm(text, speech_seconds).map(|pace| {
        (
            pace,
            state.settings.target_pace_min,
            state.settings.target_pace_max,
        )
    });
    let cue = live_cue_for_state(&mut state, text, speech_seconds);
    publish(pace, pitch, cue);
    true
}

pub(crate) fn language_cue_capture_is_current(
    origin_generation: u64,
    current_generation: u64,
    origin_active: bool,
) -> bool {
    origin_active && origin_generation == current_generation
}

pub fn estimated_pace_wpm(finalized_text: &str, speech_seconds: f64) -> Option<u16> {
    if !speech_seconds.is_finite() || speech_seconds < MIN_PACE_SPEECH_SECONDS as f64 {
        return None;
    }
    let recognized_words = finalized_text.split_whitespace().count();
    if recognized_words < MIN_PACE_WORDS as usize {
        return None;
    }
    Some(((recognized_words as f64 * 60.0 / speech_seconds).round() as u16).min(400))
}

pub fn pace_reading(
    runtime: &CoachRuntime,
    text: &str,
    speech_seconds: f64,
) -> Option<(u16, u16, u16)> {
    let pace = estimated_pace_wpm(text, speech_seconds)?;
    let state = runtime.0.lock().ok()?;
    if !state.settings.enabled || state.settings.paused || !state.capture_available {
        return None;
    }
    Some((
        pace,
        state.settings.target_pace_min,
        state.settings.target_pace_max,
    ))
}

pub fn reserve_language_suggestion(
    runtime: &CoachRuntime,
    transcript: &str,
) -> Option<(CoachFocus, String)> {
    let sentence = latest_complete_sentence(transcript)?;
    let mut state = runtime.0.lock().ok()?;
    if !state.settings.enabled || state.settings.paused || !state.analysis_ready {
        return None;
    }
    let focus = state.settings.focus;
    if !matches!(focus, CoachFocus::Grammar | CoachFocus::Vocabulary)
        || state
            .recent_language_sentences
            .iter()
            .any(|recent| recent == &sentence)
    {
        return None;
    }
    state.recent_language_sentences.push_back(sentence.clone());
    while state.recent_language_sentences.len() > 16 {
        state.recent_language_sentences.pop_front();
    }
    Some((focus, sentence))
}

pub fn publish_language_suggestion(
    runtime: &CoachRuntime,
    focus: CoachFocus,
    pattern_id: &str,
    capture_generation: u64,
    standalone_epoch: Option<u64>,
    publish: impl FnOnce(),
) -> bool {
    let Ok(mut state) = runtime.0.lock() else {
        return false;
    };
    if !state.settings.enabled || state.settings.paused || !state.capture_available {
        return false;
    }
    if standalone_epoch.is_some_and(|epoch| !standalone_capture_epoch_is_current(&state, epoch)) {
        return false;
    }
    if !is_supported_language_pattern(pattern_id) {
        return false;
    }
    let expected_prefix = match focus {
        CoachFocus::Grammar => "grammar.",
        CoachFocus::Vocabulary => "vocabulary.",
        _ => return false,
    };
    if !pattern_id.starts_with(expected_prefix) {
        return false;
    }
    let now = Instant::now();
    if state
        .last_language_cue_at
        .is_some_and(|last| now.duration_since(last) < Duration::from_secs(20))
    {
        return false;
    }
    if let Some(session) = state.active_session.as_mut() {
        if session.language_patterns.len() >= 64 {
            return false;
        }
        match focus {
            CoachFocus::Grammar => {
                session.grammar_suggestions = session.grammar_suggestions.saturating_add(1)
            }
            CoachFocus::Vocabulary => {
                session.vocabulary_suggestions = session.vocabulary_suggestions.saturating_add(1)
            }
            _ => {}
        }
        session.language_patterns.push(pattern_id.to_string());
    } else {
        let counts = state
            .language_suggestions_by_capture
            .entry(capture_generation)
            .or_default();
        if counts.len() >= 64 {
            return false;
        }
        counts.push(pattern_id.to_string());
        while state.language_suggestions_by_capture.len() > 4 {
            if let Some(oldest) = state.language_suggestions_by_capture.keys().next().copied() {
                state.language_suggestions_by_capture.remove(&oldest);
            }
        }
    }
    state.last_language_cue_at = Some(now);
    publish();
    true
}

pub fn latest_complete_sentence(transcript: &str) -> Option<String> {
    let trimmed = transcript.trim();
    let (end_start, end_char) = trimmed
        .char_indices()
        .rev()
        .find(|(_, character)| matches!(character, '.' | '?' | '!'))?;
    let end = end_start + end_char.len_utf8();
    let start = trimmed[..end_start]
        .char_indices()
        .rev()
        .find(|(_, character)| matches!(character, '.' | '?' | '!'))
        .map(|(index, character)| index + character.len_utf8())
        .unwrap_or(0);
    let sentence = trimmed[start..end].trim();
    (sentence.split_whitespace().count() >= 5 && sentence.len() <= 2_000)
        .then(|| sentence.to_string())
}

pub fn validate_language_suggestion(
    focus: CoachFocus,
    source: &str,
    response: &str,
) -> Option<ValidatedLanguageSuggestion> {
    validate_language_suggestion_with_limit(focus, source, response, 160)
}

/// Workspace coaching can replace a whole sentence; HUD cues remain short.
pub fn validate_workspace_suggestion(
    source: &str,
    response: &str,
) -> Option<ValidatedLanguageSuggestion> {
    validate_language_suggestion_with_limit(CoachFocus::Grammar, source, response, 2_000)
}

fn validate_language_suggestion_with_limit(
    focus: CoachFocus,
    source: &str,
    response: &str,
    max_phrase_bytes: usize,
) -> Option<ValidatedLanguageSuggestion> {
    if !matches!(focus, CoachFocus::Grammar | CoachFocus::Vocabulary) {
        return None;
    }
    let response = response.trim();
    if response.eq_ignore_ascii_case("none") {
        return None;
    }
    let mut lines = response.lines();
    let pattern = lines.next()?.strip_prefix("PATTERN: ")?.trim();
    let pattern_id = format!(
        "{}.{}",
        if focus == CoachFocus::Grammar {
            "grammar"
        } else {
            "vocabulary"
        },
        pattern
    );
    let quote = lines.next()?.strip_prefix("QUOTE: ")?.trim();
    let suggestion = lines.next()?.strip_prefix("SUGGESTION: ")?.trim();
    let hint = lines.next()?.strip_prefix("HINT: ")?.trim();
    if lines.next().is_some()
        || quote.is_empty()
        || quote.len() > max_phrase_bytes
        || suggestion.is_empty()
        || suggestion.len() > max_phrase_bytes
        || hint.is_empty()
        || hint.len() > 120
        || !is_supported_language_pattern(&pattern_id)
        || quote == suggestion
        || !source.contains(quote)
        || [quote, suggestion, hint]
            .iter()
            .any(|value| value.chars().any(char::is_control) || value.contains('|'))
    {
        return None;
    }
    let digit_runs = |text: &str| {
        text.split(|character: char| !character.is_ascii_digit())
            .filter(|run| !run.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };
    if digit_runs(quote) != digit_runs(suggestion) {
        return None;
    }
    let category = if focus == CoachFocus::Grammar {
        "grammar"
    } else {
        "vocabulary"
    };
    Some(ValidatedLanguageSuggestion {
        message: format!(
            "Possible {category} suggestion: “{quote}” → “{suggestion}”. {hint} Check the transcript against what you meant."
        ),
        pattern_id,
        quote: quote.to_string(),
        suggestion: suggestion.to_string(),
        hint: hint.to_string(),
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedLanguageSuggestion {
    pub message: String,
    pub pattern_id: String,
    pub quote: String,
    pub suggestion: String,
    pub hint: String,
}

pub(crate) fn is_supported_language_pattern(pattern_id: &str) -> bool {
    matches!(
        pattern_id,
        "grammar.subject_verb"
            | "grammar.tense"
            | "grammar.articles"
            | "grammar.prepositions"
            | "grammar.sentence_clarity"
            | "vocabulary.vague_word"
            | "vocabulary.repetition"
            | "vocabulary.precision"
            | "vocabulary.word_choice"
    )
}

pub fn restore_saved_capture(runtime: &CoachRuntime) {
    let Ok(mut state) = runtime.0.lock() else {
        return;
    };
    // Only the ability to coach a dictation comes back; the microphone stays closed until then.
    if coach_attaches_to_dictation(&state.settings) {
        state.capture_available = coach_capture_possible().is_ok();
    }
    sync_dictation_attach(&state.settings);
    apply_overlay_settings(&state.settings);
}

fn apply_overlay_settings(settings: &CoachSettings) {
    #[cfg(target_os = "macos")]
    unsafe {
        officekit_dictation_coach_overlay_configure(
            settings.placement.code(),
            i32::from(settings.overlay_visible),
        );
    }
    #[cfg(not(target_os = "macos"))]
    let _ = settings;
}

fn persist_settings(directory: &Path, settings: &CoachSettings) -> Result<(), String> {
    settings.validate().map_err(str::to_string)?;
    let bytes = serde_json::to_vec(settings)
        .map_err(|_| "Speech Coach settings could not be saved".to_string())?;
    if bytes.len() as u64 > MAX_SETTINGS_BYTES {
        return Err("Speech Coach settings exceed their storage limit".into());
    }
    fs::create_dir_all(directory)
        .map_err(|_| "Speech Coach settings could not be saved".to_string())?;
    let temporary = directory.join(format!("{SETTINGS_FILE}.tmp"));
    let mut file = fs::File::create(&temporary)
        .map_err(|_| "Speech Coach settings could not be saved".to_string())?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "Speech Coach settings could not be saved".to_string())?;
    fs::rename(temporary, directory.join(SETTINGS_FILE))
        .map_err(|_| "Speech Coach settings could not be saved".to_string())
}

fn runtime_status(state: &CoachRuntimeState) -> CoachStatus {
    CoachStatus {
        settings: state.settings.clone(),
        session_count: state.store.sessions.len(),
        language_model_available: language_model_available(),
        state: if !state.settings.enabled {
            "disabled"
        } else if state.settings.paused {
            "paused"
        } else if !state.capture_available {
            "unavailable"
        } else if !state.analysis_ready {
            "waiting_for_model"
        } else {
            "enabled"
        },
    }
}

#[cfg(target_os = "macos")]
fn language_model_available() -> bool {
    unsafe { officekit_dictation_polish_available() != 0 }
}

#[cfg(not(target_os = "macos"))]
fn language_model_available() -> bool {
    false
}

#[tauri::command]
pub fn speech_coach_status(runtime: State<'_, CoachRuntime>) -> Result<CoachStatus, String> {
    current_status(&runtime)
}

pub fn current_status(runtime: &CoachRuntime) -> Result<CoachStatus, String> {
    runtime
        .0
        .lock()
        .map(|state| runtime_status(&state))
        .map_err(|_| "Speech Coach is unavailable".into())
}

#[tauri::command]
pub fn speech_coach_configure(
    runtime: State<'_, CoachRuntime>,
    settings: CoachSettings,
) -> Result<CoachStatus, String> {
    settings.validate().map_err(str::to_string)?;
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach is unavailable".to_string())?;
    if settings.enabled != state.settings.enabled || settings.paused != state.settings.paused {
        return Err(
            "Use the Speech Coach enable or pause control to change its capture state".into(),
        );
    }
    let settings_changed = settings != state.settings;
    persist_settings(&state.directory, &settings)?;
    state.settings = settings;
    if settings_changed {
        advance_capture_epoch(&mut state);
    }
    apply_overlay_settings(&state.settings);
    Ok(runtime_status(&state))
}

#[tauri::command]
pub fn speech_coach_set_enabled(
    app: tauri::AppHandle,
    runtime: State<'_, CoachRuntime>,
    enabled: bool,
) -> Result<CoachStatus, String> {
    set_enabled_with_prepare(&runtime, enabled, || {
        coach_capture_possible()?;
        #[cfg(target_os = "macos")]
        crate::register_speech_model(&app)?;
        Ok(())
    })
}

fn set_enabled_with_prepare(
    runtime: &CoachRuntime,
    enabled: bool,
    prepare: impl FnOnce() -> Result<(), String>,
) -> Result<CoachStatus, String> {
    // The analyzer takes DictationRuntime before CoachRuntime; never reverse that order.
    if enabled {
        prepare()?;
    }
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach is unavailable".to_string())?;
    if !enabled {
        end_coached_sessions(&mut state)?;
    }
    let mut settings = state.settings.clone();
    settings.enabled = enabled;
    settings.paused = false;
    persist_settings(&state.directory, &settings)?;
    state.settings = settings;
    advance_capture_epoch(&mut state);
    // Enabling only lets the coach join a dictation; the microphone stays closed until then.
    state.capture_available = enabled;
    sync_dictation_attach(&state.settings);
    Ok(runtime_status(&state))
}

#[tauri::command]
pub fn speech_coach_set_paused(
    runtime: State<'_, CoachRuntime>,
    paused: bool,
) -> Result<CoachStatus, String> {
    set_paused(&runtime, paused)
}

fn set_paused(runtime: &CoachRuntime, paused: bool) -> Result<CoachStatus, String> {
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach is unavailable".to_string())?;
    if !state.settings.enabled {
        return Err("Enable Speech Coach before pausing it".into());
    }
    if paused {
        end_coached_sessions(&mut state)?;
    }
    let mut settings = state.settings.clone();
    settings.paused = paused;
    persist_settings(&state.directory, &settings)?;
    state.settings = settings;
    advance_capture_epoch(&mut state);
    state.capture_available = !paused;
    sync_dictation_attach(&state.settings);
    Ok(runtime_status(&state))
}

/// Starts or stops a solo Listen In session. It is never saved, so it is always off after a restart.
pub fn speech_coach_set_listen_in(
    runtime: &CoachRuntime,
    active: bool,
) -> Result<CoachStatus, String> {
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach is unavailable".to_string())?;
    if active == state.listen_in {
        return Ok(runtime_status(&state));
    }
    if active {
        if !state.settings.enabled || state.settings.paused {
            return Err("Turn on Speech Coach before starting Listen In".into());
        }
        if state.meeting_coach {
            // The meeting recording already owns the coach's microphone window.
            return Err("Speech Coach is already listening to your meeting recording".into());
        }
        start_coach_capture()?;
        state.listen_in = true;
        state.capture_available = true;
    } else {
        end_listen_in(&mut state)?;
    }
    advance_capture_epoch(&mut state);
    Ok(runtime_status(&state))
}

pub fn listen_in_active(runtime: &CoachRuntime) -> bool {
    runtime.0.lock().is_ok_and(|state| state.listen_in)
}

fn end_listen_in(state: &mut CoachRuntimeState) -> Result<(), String> {
    if !state.listen_in {
        return Ok(());
    }
    // The microphone is released and Listen In ends even when the note cannot be saved.
    let saved = finish_standalone_session(state);
    stop_coach_capture()?;
    state.listen_in = false;
    state.coach_me = None;
    saved
}

static ATTACH_ON_DICTATION: AtomicBool = AtomicBool::new(false);

/// Speech Coach coaches a dictation while it is on and not paused.
pub fn coach_attaches_to_dictation(settings: &CoachSettings) -> bool {
    settings.enabled && !settings.paused
}

fn sync_dictation_attach(settings: &CoachSettings) {
    ATTACH_ON_DICTATION.store(coach_attaches_to_dictation(settings), Ordering::Release);
}

pub fn attach_on_dictation() -> bool {
    ATTACH_ON_DICTATION.load(Ordering::Acquire)
}

#[cfg(target_os = "macos")]
fn coach_capture_possible() -> Result<(), String> {
    let permission = unsafe { officekit_dictation_microphone_permission_status() };
    if permission != 0 {
        return Err("Allow microphone access for Speech Coach in System Settings".into());
    }
    if unsafe { officekit_dictation_has_audio_input() } != 1 {
        return Err("Connect a microphone before enabling Speech Coach".into());
    }
    Ok(())
}

#[cfg(not(target_os = "macos"))]
fn coach_capture_possible() -> Result<(), String> {
    Err("Speech Coach microphone monitoring is available in the macOS app".into())
}

#[cfg(target_os = "macos")]
fn start_coach_capture() -> Result<(), String> {
    let permission = unsafe { officekit_dictation_microphone_permission_status() };
    if permission != 0 {
        return Err("Allow microphone access for Speech Coach in System Settings".into());
    }
    if unsafe { officekit_dictation_has_audio_input() } != 1 {
        return Err("Connect a microphone before enabling Speech Coach".into());
    }
    match unsafe { officekit_dictation_coach_start() } {
        0 => Ok(()),
        1 => Err("The microphone is already owned by an incompatible recording".into()),
        _ => Err("Speech Coach could not start microphone monitoring".into()),
    }
}

#[cfg(not(target_os = "macos"))]
fn start_coach_capture() -> Result<(), String> {
    Err("Speech Coach microphone monitoring is available in the macOS app".into())
}

#[cfg(target_os = "macos")]
fn stop_coach_capture() -> Result<(), String> {
    match unsafe { officekit_dictation_coach_stop() } {
        0 | 1 => Ok(()),
        _ => Err("Speech Coach could not release microphone monitoring".into()),
    }
}

#[cfg(not(target_os = "macos"))]
fn stop_coach_capture() -> Result<(), String> {
    Ok(())
}

#[tauri::command]
pub fn speech_coach_notes(runtime: State<'_, CoachRuntime>) -> Result<Vec<CoachSession>, String> {
    runtime
        .0
        .lock()
        .map(|state| state.store.sessions.clone())
        .map_err(|_| "Speech Coach notes are unavailable".into())
}

#[tauri::command]
pub fn speech_coach_record_session(
    runtime: State<'_, CoachRuntime>,
    input: CoachSessionInput,
) -> Result<CoachStatus, String> {
    input.validate().map_err(str::to_string)?;
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach history is unavailable".to_string())?;
    if !state.settings.enabled || state.settings.paused {
        return Ok(runtime_status(&state));
    }
    let text = input.text.trim();
    let metrics = metrics_for_finalized_text(text, input.speech_seconds);
    let language_patterns = input
        .capture_generation
        .and_then(|generation| {
            state
                .language_suggestions_by_capture
                .get(&generation)
                .cloned()
        })
        .unwrap_or_default();
    let grammar_suggestions = language_patterns
        .iter()
        .filter(|pattern| pattern.starts_with("grammar."))
        .count()
        .min(u16::MAX as usize) as u16;
    let vocabulary_suggestions = language_patterns
        .iter()
        .filter(|pattern| pattern.starts_with("vocabulary."))
        .count()
        .min(u16::MAX as usize) as u16;
    let session = CoachSession {
        id: uuid::Uuid::new_v4().to_string(),
        started_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        context: state.settings.context,
        focus: state.settings.focus,
        practice_goal: practice_goal(&state.settings),
        duration_seconds: input.duration_seconds,
        speech_seconds: metrics.speech_seconds,
        recognized_words: metrics.recognized_words,
        filler_words: metrics.filler_words,
        pace_wpm: metrics.pace_wpm,
        time_in_pace_range_percent: metrics.time_in_range_percent,
        pitch_median_hz: input.pitch_median_hz,
        pitch_range_hz: input.pitch_range_hz,
        grammar_suggestions,
        vocabulary_suggestions,
        language_patterns,
        dismissed_patterns: Vec::new(),
        useful_patterns: Vec::new(),
        examples: Vec::new(),
    };
    if session.validate().is_err() {
        return Err("Speech Coach session is outside supported limits".into());
    }
    let mut updated = state.store.clone();
    updated.insert(session).map_err(str::to_string)?;
    save_store(&state.directory, &updated)?;
    state.store = updated;
    if let Some(generation) = input.capture_generation {
        state.language_suggestions_by_capture.remove(&generation);
    }
    Ok(runtime_status(&state))
}

fn practice_goal(settings: &CoachSettings) -> String {
    match settings.focus {
        CoachFocus::Pace => format!(
            "Keep your pace near {}–{} words per minute, with a short pause between key points.",
            settings.target_pace_min, settings.target_pace_max
        ),
        CoachFocus::Fillers => {
            "Replace a filler word with a brief pause when you notice one.".into()
        }
        CoachFocus::Pauses => "Leave a brief pause between main points.".into(),
        CoachFocus::Grammar => "Try one clear, complete sentence at a time.".into(),
        CoachFocus::Vocabulary => "Choose a precise word when it helps your meaning.".into(),
    }
}

#[tauri::command]
pub fn speech_coach_clear_notes(runtime: State<'_, CoachRuntime>) -> Result<(), String> {
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach notes are unavailable".to_string())?;
    let empty = CoachStore {
        version: 1,
        sessions: Vec::new(),
    };
    save_store(&state.directory, &empty)?;
    state.store = empty;
    Ok(())
}

#[tauri::command]
pub fn speech_coach_dismiss_pattern(
    runtime: State<'_, CoachRuntime>,
    pattern_id: String,
) -> Result<(), String> {
    if pattern_id.is_empty() || pattern_id.len() > 64 {
        return Err("Speech Coach pattern identifier is invalid".into());
    }
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach notes are unavailable".to_string())?;
    let mut updated = state.store.clone();
    for session in &mut updated.sessions {
        if !session.dismissed_patterns.contains(&pattern_id) {
            session.dismissed_patterns.push(pattern_id.clone());
        }
    }
    save_store(&state.directory, &updated)?;
    state.store = updated;
    Ok(())
}

#[tauri::command]
pub fn speech_coach_set_pattern_dismissed(
    runtime: State<'_, CoachRuntime>,
    pattern_id: String,
    dismissed: bool,
) -> Result<(), String> {
    update_pattern_feedback(runtime, pattern_id, dismissed, false)
}

#[tauri::command]
pub fn speech_coach_set_pattern_useful(
    runtime: State<'_, CoachRuntime>,
    pattern_id: String,
    useful: bool,
) -> Result<(), String> {
    update_pattern_feedback(runtime, pattern_id, useful, true)
}

fn update_pattern_feedback(
    runtime: State<'_, CoachRuntime>,
    pattern_id: String,
    enabled: bool,
    useful: bool,
) -> Result<(), String> {
    if pattern_id.is_empty() || pattern_id.len() > 64 {
        return Err("Speech Coach pattern identifier is invalid".into());
    }
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Speech Coach notes are unavailable".to_string())?;
    let mut updated = state.store.clone();
    for session in &mut updated.sessions {
        let values = if useful {
            &mut session.useful_patterns
        } else {
            &mut session.dismissed_patterns
        };
        values.retain(|value| value != &pattern_id);
        if enabled {
            values.push(pattern_id.clone());
        }
    }
    save_store(&state.directory, &updated)?;
    state.store = updated;
    Ok(())
}

impl CoachStore {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.version != 1 || self.sessions.len() > MAX_SESSIONS {
            return Err("Speech Coach history is outside supported limits");
        }
        let mut ids = BTreeSet::new();
        for session in &self.sessions {
            session.validate()?;
            if !ids.insert(session.id.as_str()) {
                return Err("Speech Coach session identifiers must be unique");
            }
        }
        Ok(())
    }

    pub fn insert(&mut self, session: CoachSession) -> Result<(), &'static str> {
        session.validate()?;
        if self
            .sessions
            .iter()
            .any(|existing| existing.id == session.id)
        {
            return Err("Speech Coach session already exists");
        }
        self.sessions.push(session);
        if self.sessions.len() > MAX_SESSIONS {
            self.sessions.remove(0);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SessionMetrics {
    pub recognized_words: u32,
    pub speech_seconds: u32,
    pub pace_wpm: Option<u16>,
    pub filler_words: u32,
    pub time_in_range_percent: Option<u8>,
}

/// Pace uses deduplicated finalized text and eligible voiced time, excluding pauses/revisions.
pub fn metrics_for_finalized_text(text: &str, speech_seconds: u32) -> SessionMetrics {
    let words: Vec<&str> = text.split_whitespace().collect();
    let word_count = words.len().min(u32::MAX as usize) as u32;
    let fillers = words
        .iter()
        .filter(|word| {
            let normalized = word
                .trim_matches(|c: char| !c.is_alphanumeric())
                .to_lowercase();
            matches!(normalized.as_str(), "um" | "uh" | "erm")
        })
        .count()
        .min(u32::MAX as usize) as u32;
    let pace = (word_count >= MIN_PACE_WORDS && speech_seconds >= MIN_PACE_SPEECH_SECONDS)
        .then(|| ((word_count as f64 * 60.0 / speech_seconds as f64).round() as u16).min(400));
    SessionMetrics {
        recognized_words: word_count,
        speech_seconds,
        pace_wpm: pace,
        filler_words: fillers,
        // A whole-session average is not a valid estimate of the share of time within range.
        time_in_range_percent: None,
    }
}

/// Estimate descriptive fundamental-frequency statistics from bounded 16 kHz mono samples.
/// The result is not a speaking-quality score and has no universal target range.
pub fn estimate_pitch_stats(samples: &[f32], sample_rate: u32) -> Option<PitchStats> {
    if samples.is_empty() || !(8_000..=48_000).contains(&sample_rate) {
        return None;
    }
    let rate = (sample_rate / 2) as usize;
    let decimated = samples.iter().step_by(2).copied().collect::<Vec<_>>();
    let frame_len = rate * 3 / 100;
    let min_lag = (rate / 400).max(2);
    let max_lag = (rate / 50).min(frame_len.saturating_sub(2));
    if frame_len == 0 || max_lag <= min_lag {
        return None;
    }

    let mut frequencies = Vec::new();
    for frame in decimated.chunks_exact(frame_len) {
        if frame.iter().any(|sample| !sample.is_finite()) {
            continue;
        }
        let mean = frame.iter().map(|sample| *sample as f64).sum::<f64>() / frame.len() as f64;
        let centered = frame
            .iter()
            .map(|sample| *sample as f64 - mean)
            .collect::<Vec<_>>();
        let energy =
            centered.iter().map(|sample| sample * sample).sum::<f64>() / frame.len() as f64;
        if energy.sqrt() < 0.015 {
            continue;
        }

        let mut differences = vec![0.0_f64; max_lag + 1];
        for lag in 1..=max_lag {
            let length = frame.len() - lag;
            let mut difference = 0.0;
            for index in 0..length {
                let delta = centered[index] - centered[index + lag];
                difference += delta * delta;
            }
            differences[lag] = difference;
        }

        let mut cumulative_difference = 0.0;
        let mut normalized = vec![1.0_f64; max_lag + 1];
        for lag in 1..=max_lag {
            cumulative_difference += differences[lag];
            if cumulative_difference > 0.0 {
                normalized[lag] = differences[lag] * lag as f64 / cumulative_difference;
            }
        }
        let candidate = (min_lag..=max_lag).find(|lag| {
            normalized[*lag] <= 0.18
                && (*lag == max_lag || normalized[*lag] <= normalized[*lag + 1])
        });
        let Some(lag) = candidate else { continue };
        let previous = normalized[lag.saturating_sub(1)];
        let trough = normalized[lag];
        let next = normalized[(lag + 1).min(max_lag)];
        let denominator = previous - 2.0 * trough + next;
        let correction = if denominator.abs() > f64::EPSILON {
            (0.5 * (previous - next) / denominator).clamp(-0.5, 0.5)
        } else {
            0.0
        };
        let hz = (rate as f64 / (lag as f64 + correction)).round();
        if (50.0..=400.0).contains(&hz) {
            frequencies.push(hz as u16);
        }
    }

    if frequencies.len() < 3 {
        return None;
    }
    frequencies.sort_unstable();
    let median = frequencies[frequencies.len() / 2];
    let low = frequencies[(frequencies.len() - 1) * 10 / 100];
    let high = frequencies[(frequencies.len() - 1) * 90 / 100];
    Some(PitchStats {
        median_hz: median,
        range_hz: high.saturating_sub(low),
    })
}

/// Samples up to four evenly spaced three-second windows to bound STT-session analysis.
pub fn estimate_recording_pitch_stats(samples: &[f32], sample_rate: u32) -> Option<PitchStats> {
    if !(8_000..=48_000).contains(&sample_rate) {
        return None;
    }
    let window_len = (sample_rate as usize).saturating_mul(3);
    if samples.len() < window_len / 10 {
        return None;
    }
    let window_count = samples.len().div_ceil(window_len).clamp(1, 4);
    let mut windows = Vec::with_capacity(window_count);
    for index in 0..window_count {
        let max_start = samples.len().saturating_sub(window_len);
        let start = if window_count == 1 {
            0
        } else {
            max_start.saturating_mul(index) / (window_count - 1)
        };
        let end = start.saturating_add(window_len).min(samples.len());
        if let Some(stats) = estimate_pitch_stats(&samples[start..end], sample_rate) {
            windows.push(stats);
        }
    }
    if windows.is_empty() {
        return None;
    }
    Some(PitchStats {
        median_hz: median_u16(windows.iter().map(|window| window.median_hz))?,
        range_hz: median_u16(windows.iter().map(|window| window.range_hz))?,
    })
}

pub fn load_store(directory: &Path) -> CoachStore {
    let path = directory.join(STORE_FILE);
    let Ok(metadata) = fs::metadata(&path) else {
        return CoachStore {
            version: 1,
            sessions: Vec::new(),
        };
    };
    if !metadata.is_file() || metadata.len() > MAX_STORE_BYTES {
        return CoachStore {
            version: 1,
            sessions: Vec::new(),
        };
    }
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<CoachStore>(&bytes).ok())
        .filter(|store| store.validate().is_ok())
        .unwrap_or(CoachStore {
            version: 1,
            sessions: Vec::new(),
        })
}

pub fn save_store(directory: &Path, store: &CoachStore) -> Result<(), String> {
    store.validate().map_err(str::to_string)?;
    let bytes = serde_json::to_vec(store)
        .map_err(|_| "Speech Coach history could not be saved".to_string())?;
    if bytes.len() as u64 > MAX_STORE_BYTES {
        return Err("Speech Coach history exceeds its storage limit".into());
    }
    fs::create_dir_all(directory)
        .map_err(|_| "Speech Coach history could not be saved".to_string())?;
    let path = directory.join(STORE_FILE);
    let temporary = directory.join(format!("{STORE_FILE}.tmp"));
    let mut file = fs::File::create(&temporary)
        .map_err(|_| "Speech Coach history could not be saved".to_string())?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "Speech Coach history could not be saved".to_string())?;
    fs::rename(&temporary, &path).map_err(|_| "Speech Coach history could not be saved".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn session(id: &str) -> CoachSession {
        CoachSession {
            id: id.into(),
            started_at: "2026-10-22T10:00:00Z".into(),
            context: CoachContext::Casual,
            focus: CoachFocus::Pace,
            practice_goal: "Pause between key points.".into(),
            duration_seconds: 60,
            speech_seconds: 30,
            recognized_words: 60,
            filler_words: 2,
            pace_wpm: Some(120),
            time_in_pace_range_percent: None,
            pitch_median_hz: None,
            pitch_range_hz: None,
            grammar_suggestions: 0,
            vocabulary_suggestions: 0,
            language_patterns: vec![],
            dismissed_patterns: vec![],
            useful_patterns: vec![],
            examples: vec![],
        }
    }

    fn runtime_for_cues(settings: CoachSettings, capture_available: bool) -> CoachRuntime {
        let directory =
            std::env::temp_dir().join(format!("speech-coach-test-{}", uuid::Uuid::new_v4()));
        CoachRuntime(Mutex::new(CoachRuntimeState {
            settings,
            store: CoachStore {
                version: 1,
                sessions: Vec::new(),
            },
            directory,
            capture_available,
            listen_in: true,
            meeting_coach: false,
            coach_me: None,
            analysis_ready: true,
            capture_epoch: 0,
            last_live_cue_at: None,
            last_language_cue_at: None,
            active_session: None,
            recent_language_sentences: VecDeque::new(),
            language_suggestions_by_capture: BTreeMap::new(),
        }))
    }

    #[test]
    fn first_model_failure_stops_listen_in_and_marks_analysis_unavailable() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..Default::default()
            },
            true,
        );
        let epoch = runtime.0.lock().unwrap().capture_epoch;
        stop_for_model_failure(&runtime);
        let state = runtime.0.lock().unwrap();
        assert!(!state.listen_in);
        assert!(!state.analysis_ready);
        assert!(state.capture_epoch > epoch);
        assert!(
            state.settings.enabled,
            "failure does not overwrite the saved Coach preference"
        );
    }

    #[test]
    fn enabling_registers_speech_before_taking_the_coach_lock() {
        let runtime = runtime_for_cues(CoachSettings::default(), false);
        let directory = runtime.0.lock().unwrap().directory.clone();
        let status = set_enabled_with_prepare(&runtime, true, || {
            assert!(
                runtime.0.try_lock().is_ok(),
                "speech registration must not hold CoachRuntime while acquiring DictationRuntime"
            );
            Ok(())
        })
        .unwrap();
        assert!(status.settings.enabled);
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn failed_speech_registration_leaves_the_coach_disabled() {
        let runtime = runtime_for_cues(CoachSettings::default(), false);
        assert!(
            set_enabled_with_prepare(&runtime, true, || Err("Model unavailable".into())).is_err()
        );
        assert!(!runtime.0.lock().unwrap().settings.enabled);
    }

    #[test]
    fn standalone_analysis_runs_only_while_listen_in_is_on() {
        let settings = CoachSettings {
            enabled: true,
            ..CoachSettings::default()
        };
        let runtime = runtime_for_cues(settings, true);
        assert!(standalone_analysis_epoch(&runtime).is_some());
        runtime.0.lock().unwrap().listen_in = false;
        assert!(
            standalone_analysis_epoch(&runtime).is_none(),
            "an enabled coach with no Listen In session never analyses on its own"
        );
        assert!(!listen_in_active(&runtime));
    }

    #[test]
    fn a_coached_meeting_analyses_and_saves_one_note_when_it_ends() {
        let settings = CoachSettings {
            enabled: true,
            ..CoachSettings::default()
        };
        let runtime = runtime_for_cues(settings, true);
        runtime.0.lock().unwrap().listen_in = false;
        assert!(standalone_analysis_epoch(&runtime).is_none());
        assert!(set_meeting_coach(&runtime, true));
        assert!(meeting_coach_active(&runtime));
        let epoch = standalone_analysis_epoch(&runtime).expect("a coached meeting is analysed");
        assert!(record_standalone_segment(
            &runtime,
            "We went through the plan and agreed the next steps for the launch today",
            12.0,
            None,
            epoch
        ));
        assert!(!set_meeting_coach(&runtime, false));
        assert!(!meeting_coach_active(&runtime));
        assert!(standalone_analysis_epoch(&runtime).is_none());
        let state = runtime.0.lock().unwrap();
        assert_eq!(state.store.sessions.len(), 1, "one note for the meeting");
        assert!(state.active_session.is_none());
    }

    #[test]
    fn a_meeting_is_not_coached_when_the_coach_is_off_or_paused() {
        let off = runtime_for_cues(CoachSettings::default(), true);
        assert!(!set_meeting_coach(&off, true));
        assert!(!meeting_coach_active(&off));
        let paused = runtime_for_cues(
            CoachSettings {
                enabled: true,
                paused: true,
                ..CoachSettings::default()
            },
            true,
        );
        assert!(!set_meeting_coach(&paused, true));
        let unavailable = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            false,
        );
        assert!(!set_meeting_coach(&unavailable, true));
        assert!(
            !set_meeting_coach(&unavailable, false),
            "ending is harmless"
        );
    }

    #[test]
    fn a_model_failure_ends_meeting_coaching() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        stop_for_model_failure(&runtime);
        assert!(!meeting_coach_active(&runtime));
        assert!(standalone_analysis_epoch(&runtime).is_none());
    }

    #[test]
    fn the_analyzer_steps_aside_for_dictation_and_for_uncoached_meetings_only() {
        // (capture_active, meeting_recording, meeting_coached) -> steps aside
        let table = [
            (false, false, false, false), // idle: Listen In is analysed
            (false, false, true, false),
            (true, false, false, true), // a dictation owns the window
            (true, false, true, true),  // dictation beats a stale meeting flag
            (false, true, false, true), // meeting nobody coaches
            (false, true, true, false), // coached meeting is analysed
            (true, true, false, true),  // a meeting recording reports capture_active too
            (true, true, true, false),
        ];
        for (capture, meeting, coached, expected) in table {
            assert_eq!(
                analyzer_steps_aside(capture, meeting, coached),
                expected,
                "capture={capture} meeting={meeting} coached={coached}"
            );
        }
        assert!(analyzer_window_is_standalone(false, false));
        assert!(analyzer_window_is_standalone(true, true), "a meeting");
        assert!(
            !analyzer_window_is_standalone(true, false),
            "a dictation started since the window was drained"
        );
    }

    #[test]
    fn coach_me_ends_twenty_seconds_after_a_call_that_was_there_has_gone() {
        let mut coach_me = CoachMe::default();
        assert!(!coach_me.tick(true), "a call is present");
        for second in 1..COACH_ME_CALL_GONE_SECONDS {
            assert!(!coach_me.tick(false), "second {second} is not enough");
        }
        assert!(
            coach_me.tick(false),
            "the {COACH_ME_CALL_GONE_SECONDS}th second ends it"
        );
    }

    #[test]
    fn a_call_that_comes_back_restarts_the_coach_me_countdown() {
        let mut coach_me = CoachMe::default();
        coach_me.tick(true);
        for _ in 0..(COACH_ME_CALL_GONE_SECONDS - 1) {
            assert!(!coach_me.tick(false));
        }
        assert!(!coach_me.tick(true), "the call returned at the last second");
        for _ in 0..(COACH_ME_CALL_GONE_SECONDS - 1) {
            assert!(!coach_me.tick(false));
        }
        assert!(coach_me.tick(false));
    }

    #[test]
    fn coach_me_never_ends_before_a_call_has_been_seen() {
        let mut coach_me = CoachMe::default();
        for _ in 0..(COACH_ME_CALL_GONE_SECONDS * 10) {
            assert!(
                !coach_me.tick(false),
                "an in-person or not yet joined meeting keeps coaching"
            );
        }
    }

    fn coach_me_runtime() -> CoachRuntime {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        mark_coach_me(&runtime);
        runtime
    }

    #[test]
    fn the_coach_me_tick_ends_listen_in_once_and_saves_one_note() {
        let runtime = coach_me_runtime();
        let epoch = standalone_analysis_epoch(&runtime).expect("coaching");
        assert!(record_standalone_segment(
            &runtime,
            "We went through the plan and agreed the next steps for the launch today",
            12.0,
            None,
            epoch
        ));
        assert!(coach_me_active(&runtime));
        assert!(!coach_me_tick(&runtime, true));
        for _ in 1..COACH_ME_CALL_GONE_SECONDS {
            assert!(!coach_me_tick(&runtime, false));
        }
        assert!(coach_me_tick(&runtime, false), "the call is gone");
        assert!(!listen_in_active(&runtime));
        assert!(!coach_me_active(&runtime));
        assert!(
            !coach_me_tick(&runtime, false),
            "it does not fire again once ended"
        );
        let state = runtime.0.lock().unwrap();
        assert_eq!(state.store.sessions.len(), 1, "one note for the call");
    }

    #[test]
    fn ending_listen_in_by_hand_leaves_a_later_listen_in_alone() {
        let runtime = coach_me_runtime();
        assert!(coach_me_active(&runtime));
        assert!(!coach_me_tick(&runtime, true), "the call is seen");
        speech_coach_set_listen_in(&runtime, false).expect("ended by hand");
        assert!(!coach_me_active(&runtime), "the Coach me mark went with it");
        // The person starts Listen In again from Quick Controls, with no call running.
        runtime.0.lock().unwrap().listen_in = true;
        for _ in 0..(COACH_ME_CALL_GONE_SECONDS * 2) {
            assert!(!coach_me_tick(&runtime, false));
        }
        assert!(listen_in_active(&runtime), "the manual session keeps going");
    }

    #[test]
    fn coach_me_is_refused_while_the_coach_already_has_the_microphone() {
        assert!(coach_me_blocker(false, false, false).is_none());
        assert!(coach_me_blocker(true, false, false)
            .is_some_and(|reason| reason.contains("meeting recording")));
        assert!(coach_me_blocker(false, true, false)
            .is_some_and(|reason| reason.contains("already listening")));
        assert!(coach_me_blocker(false, false, true)
            .is_some_and(|reason| reason.contains("already listening")));
        let runtime = coach_me_runtime();
        assert!(
            coach_me_blocker_for_runtime(&runtime, false).is_some(),
            "Listen In is running"
        );
    }

    #[test]
    fn joining_a_meeting_has_four_outcomes() {
        use std::cell::Cell;
        let opened = Cell::new(0);
        let released = Cell::new(0);
        let run = |enabled: bool, joined: bool, coaching: bool| {
            opened.set(0);
            released.set(0);
            attach_to_meeting(
                enabled,
                || joined,
                || coaching,
                || opened.set(opened.get() + 1),
                || released.set(released.get() + 1),
            )
        };
        assert_eq!(run(false, true, true), MeetingAttach::Skipped);
        assert_eq!((opened.get(), released.get()), (0, 0), "off: untouched");
        assert_eq!(run(true, false, true), MeetingAttach::NotJoined);
        assert_eq!(
            (opened.get(), released.get()),
            (0, 0),
            "not joined: nothing to leave"
        );
        assert_eq!(run(true, true, false), MeetingAttach::Released);
        assert_eq!(
            (opened.get(), released.get()),
            (0, 1),
            "joined, cannot coach: leaves"
        );
        assert_eq!(run(true, true, true), MeetingAttach::Coaching);
        assert_eq!((opened.get(), released.get()), (1, 0));
    }

    #[test]
    fn starting_meeting_coaching_twice_does_not_advance_the_epoch_again() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        let epoch = runtime.0.lock().unwrap().capture_epoch;
        assert!(set_meeting_coach(&runtime, true));
        assert_eq!(runtime.0.lock().unwrap().capture_epoch, epoch);
        assert!(
            !set_meeting_coach(&runtime, false),
            "ending is not coaching"
        );
        assert!(
            !set_meeting_coach(&runtime, false),
            "ending twice is harmless"
        );
    }

    #[test]
    fn a_meeting_is_not_coached_while_listen_in_has_the_window() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        assert!(runtime.0.lock().unwrap().listen_in);
        assert!(!set_meeting_coach(&runtime, true));
        assert!(!meeting_coach_active(&runtime));
    }

    #[test]
    fn the_meeting_note_holds_what_was_said_in_the_meeting() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime,
            "We went through the plan and agreed the next steps for the launch today",
            12.0,
            None,
            epoch
        ));
        set_meeting_coach(&runtime, false);
        let state = runtime.0.lock().unwrap();
        let note = &state.store.sessions[0];
        assert_eq!(note.recognized_words, 14);
        assert!(note.speech_seconds > 0);
    }

    fn unwritable_directory() -> std::path::PathBuf {
        // A directory below a regular file can never be created, so every save fails.
        let file = std::env::temp_dir().join(format!("speech-coach-file-{}", uuid::Uuid::new_v4()));
        std::fs::write(&file, b"x").unwrap();
        file.join("history")
    }

    const SENTENCE: &str =
        "We went through the plan and agreed the next steps for the launch today";

    #[test]
    fn a_failed_save_loses_that_note_but_never_leaks_into_the_next_meeting() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        {
            let mut state = runtime.0.lock().unwrap();
            state.listen_in = false;
            state.directory = unwritable_directory();
        }
        assert!(set_meeting_coach(&runtime, true));
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, SENTENCE, 12.0, None, epoch
        ));
        set_meeting_coach(&runtime, false);
        {
            let state = runtime.0.lock().unwrap();
            assert!(!state.meeting_coach, "the coach left the meeting");
            assert!(state.active_session.is_none(), "no half-open note is left");
            assert!(
                state.store.sessions.is_empty(),
                "the note could not be saved"
            );
        }
        assert!(set_meeting_coach(&runtime, true));
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, SENTENCE, 12.0, None, epoch
        ));
        let words = runtime
            .0
            .lock()
            .unwrap()
            .active_session
            .as_ref()
            .map(|session| session.recognized_words);
        assert_eq!(words, Some(14), "the next meeting starts clean");
    }

    #[test]
    fn a_failed_save_still_ends_listen_in_and_releases_the_microphone() {
        let runtime = coach_me_runtime();
        runtime.0.lock().unwrap().directory = unwritable_directory();
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, SENTENCE, 12.0, None, epoch
        ));
        assert!(
            speech_coach_set_listen_in(&runtime, false).is_err(),
            "the save error is reported"
        );
        assert!(!listen_in_active(&runtime), "but Listen In has ended");
        assert!(!coach_me_active(&runtime));
        assert!(runtime.0.lock().unwrap().active_session.is_none());
    }

    #[test]
    fn turning_speech_coach_off_mid_meeting_ends_the_meeting_coaching() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, SENTENCE, 12.0, None, epoch
        ));
        set_enabled_with_prepare(&runtime, false, || Ok(())).expect("turned off");
        assert!(!meeting_coach_active(&runtime));
        assert!(standalone_analysis_epoch(&runtime).is_none());
        assert_eq!(
            runtime.0.lock().unwrap().store.sessions.len(),
            1,
            "the note so far is kept"
        );
    }

    #[test]
    fn pausing_speech_coach_mid_meeting_ends_the_meeting_coaching() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, SENTENCE, 12.0, None, epoch
        ));
        set_paused(&runtime, true).expect("paused");
        assert!(!meeting_coach_active(&runtime));
        assert!(standalone_analysis_epoch(&runtime).is_none());
        assert_eq!(
            runtime.0.lock().unwrap().store.sessions.len(),
            1,
            "the note so far is kept"
        );
    }

    #[test]
    fn listen_in_is_refused_while_a_meeting_recording_is_being_coached() {
        let runtime = runtime_for_cues(
            CoachSettings {
                enabled: true,
                ..CoachSettings::default()
            },
            true,
        );
        runtime.0.lock().unwrap().listen_in = false;
        assert!(set_meeting_coach(&runtime, true));
        let error = speech_coach_set_listen_in(&runtime, true).expect_err("refused");
        assert!(error.contains("meeting recording"), "{error}");
        assert!(!listen_in_active(&runtime));
        assert!(meeting_coach_active(&runtime), "the meeting keeps coaching");
    }

    #[test]
    fn ending_listen_in_keeps_speech_coach_on() {
        let settings = CoachSettings {
            enabled: true,
            ..CoachSettings::default()
        };
        let runtime = runtime_for_cues(settings, true);
        assert!(listen_in_active(&runtime));
        let status = speech_coach_set_listen_in(&runtime, false).unwrap();
        assert!(!listen_in_active(&runtime));
        assert!(
            status.settings.enabled,
            "the close button never disables Speech Coach"
        );
        assert!(
            speech_coach_set_listen_in(&runtime, false).is_ok(),
            "closing twice is harmless"
        );
    }

    #[test]
    fn coach_joins_dictation_only_while_enabled_and_not_paused() {
        let mut settings = CoachSettings::default();
        assert!(!coach_attaches_to_dictation(&settings));
        settings.enabled = true;
        assert!(coach_attaches_to_dictation(&settings));
        settings.paused = true;
        assert!(!coach_attaches_to_dictation(&settings));
    }

    #[test]
    fn listen_in_is_never_restored_from_saved_settings() {
        let directory =
            std::env::temp_dir().join(format!("speech-coach-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&directory).unwrap();
        let saved = CoachSettings {
            enabled: true,
            context: CoachContext::Practice,
            ..CoachSettings::default()
        };
        fs::write(
            directory.join(SETTINGS_FILE),
            serde_json::to_vec(&saved).unwrap(),
        )
        .unwrap();
        let runtime = CoachRuntime::load(directory.clone());
        assert!(runtime.0.lock().unwrap().settings.enabled);
        assert!(!listen_in_active(&runtime));
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn pace_waits_for_minimum_words_and_speech_time_and_counts_fillers() {
        assert_eq!(
            metrics_for_finalized_text("one two three", 20).pace_wpm,
            None
        );
        assert_eq!(
            metrics_for_finalized_text(&vec!["word"; 20].join(" "), 5).pace_wpm,
            None
        );
        let words = [
            "um",
            "we",
            "uh",
            "erm",
            "should",
            "speak",
            "clearly",
            "and",
            "leave",
            "a",
            "short",
            "pause",
            "before",
            "we",
            "start",
            "the",
            "next",
            "important",
            "point",
            "today",
        ]
        .join(" ");
        let metrics = metrics_for_finalized_text(&words, 20);
        assert_eq!(metrics.pace_wpm, Some(60));
        assert_eq!(metrics.filler_words, 3);
        assert_eq!(metrics.time_in_range_percent, None);
    }

    #[test]
    fn whole_session_average_does_not_claim_time_in_range() {
        let metrics = metrics_for_finalized_text(&vec!["word"; 30].join(" "), 15);
        assert_eq!(metrics.pace_wpm, Some(120));
        assert_eq!(metrics.time_in_range_percent, None);
    }

    #[test]
    fn live_pace_cues_wait_for_evidence_and_are_deduplicated() {
        let mut settings = CoachSettings::default();
        settings.enabled = true;
        let runtime = runtime_for_cues(settings, true);
        assert_eq!(live_cue(&runtime, "a few words", 20.0), None);
        let words = vec!["word"; 20].join(" ");
        assert_eq!(estimated_pace_wpm(&words, 10.0), Some(120));
        assert_eq!(pace_reading(&runtime, &words, 10.0), Some((120, 110, 160)));
        assert_eq!(pace_reading(&runtime, &words, 9.9), None);
        let cue = live_cue(&runtime, &words, 10.0).unwrap();
        assert!(cue.contains("in your zone"));
        assert_eq!(live_cue(&runtime, &words, 10.0), None);
        {
            let mut state = runtime.0.lock().unwrap();
            state.last_live_cue_at = Some(Instant::now() - Duration::from_secs(21));
        }
        assert!(live_cue(&runtime, &words, 10.0).is_some());

        let mut unavailable = CoachSettings::default();
        unavailable.enabled = true;
        let unavailable = runtime_for_cues(unavailable, false);
        assert_eq!(live_cue(&unavailable, &words, 10.0), None);
    }

    #[test]
    fn language_coaching_waits_for_complete_unique_sentences_and_tracks_capture() {
        let transcript = "My first sentence is already complete. I has a clear point.";
        assert_eq!(
            latest_complete_sentence(transcript).as_deref(),
            Some("I has a clear point.")
        );
        assert_eq!(
            latest_complete_sentence("This sentence is still open"),
            None
        );
        let mut settings = CoachSettings::default();
        settings.enabled = true;
        settings.focus = CoachFocus::Grammar;
        let runtime = runtime_for_cues(settings, true);
        let (focus, sentence) = reserve_language_suggestion(&runtime, transcript).unwrap();
        assert_eq!(focus, CoachFocus::Grammar);
        assert_eq!(sentence, "I has a clear point.");
        assert_eq!(reserve_language_suggestion(&runtime, transcript), None);
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        let mut published = false;
        assert!(publish_language_suggestion(
            &runtime,
            focus,
            "grammar.subject_verb",
            42,
            Some(epoch),
            || published = true,
        ));
        assert!(published);
        assert!(!publish_language_suggestion(
            &runtime,
            focus,
            "grammar.subject_verb",
            42,
            Some(epoch),
            || panic!("cooldown must suppress a second language cue"),
        ));
        let state = runtime.0.lock().unwrap();
        assert_eq!(
            state.language_suggestions_by_capture.get(&42),
            Some(&vec!["grammar.subject_verb".to_string()])
        );
    }

    #[test]
    fn language_cues_require_the_originating_capture_to_remain_active_and_current() {
        assert!(language_cue_capture_is_current(7, 7, true));
        assert!(!language_cue_capture_is_current(7, 8, true));
        assert!(!language_cue_capture_is_current(7, 7, false));
    }

    #[test]
    fn validated_language_suggestion_exposes_quote_fix_and_hint_separately() {
        let source = "I has a clear point.";
        let response = "PATTERN: subject_verb\nQUOTE: I has\nSUGGESTION: I have\nHINT: Match the verb to the subject.";
        let suggestion =
            validate_language_suggestion(CoachFocus::Grammar, source, response).unwrap();
        assert_eq!(suggestion.quote, "I has");
        assert_eq!(suggestion.suggestion, "I have");
        assert_eq!(suggestion.hint, "Match the verb to the subject.");
        assert_eq!(suggestion.pattern_id, "grammar.subject_verb");
    }

    #[test]
    fn challenge_brainstorm_sentence_coaching_reaches_workspace_and_copy() {
        let cases: Vec<serde_json::Value> = serde_json::from_str(include_str!(
            "../../tests/fixtures/speech-coach/clarity.json"
        ))
        .unwrap();
        let transcript = cases
            .iter()
            .map(|case| case["source"].as_str().unwrap())
            .collect::<Vec<_>>()
            .join(" ");
        let expected = cases
            .iter()
            .map(|case| case["suggestion"].as_str().unwrap())
            .collect::<Vec<_>>()
            .join(" ");
        let mut workspace = crate::coach_workspace::Workspace::default();
        workspace.open();
        workspace.record_session(1, &transcript);
        for case in cases {
            let sentence = workspace.next_sentence().unwrap();
            assert_eq!(sentence, case["source"].as_str().unwrap());
            let response = format!(
                "PATTERN: sentence_clarity\nQUOTE: {}\nSUGGESTION: {}\nHINT: {}",
                sentence,
                case["suggestion"].as_str().unwrap(),
                case["hint"].as_str().unwrap()
            );
            let fixes = crate::coach_grammar::check_workspace_sentence(&sentence, Some(&response));
            assert_eq!(fixes.len(), 1);
            for fix in fixes {
                assert_eq!(fix.quote, sentence);
                assert!(workspace.add_fix(fix));
            }
        }
        assert_eq!(workspace.next_sentence(), None);
        assert_eq!(workspace.snapshot().fixes.len(), 4);
        assert_eq!(workspace.corrected_text(), expected);
        assert_eq!(
            workspace
                .snapshot()
                .parts
                .iter()
                .map(|part| part.text.as_str())
                .collect::<String>(),
            transcript
        );
    }

    #[test]
    fn workspace_rewrites_are_bounded_grounded_and_preserve_numbers() {
        let response = |quote: &str, suggestion: &str| {
            format!(
            "PATTERN: sentence_clarity\nQUOTE: {quote}\nSUGGESTION: {suggestion}\nHINT: Clearer phrasing.")
        };
        let source = "x".repeat(2_000);
        let replacement = "y".repeat(2_000);
        let valid = response(&source, &replacement);
        assert!(validate_workspace_suggestion(&source, &valid).is_some());
        assert!(validate_language_suggestion(CoachFocus::Grammar, &source, &valid).is_none());
        assert!(
            validate_workspace_suggestion(&source, &response(&source, &"y".repeat(2_001)))
                .is_none()
        );
        let too_long = "x".repeat(2_001);
        assert!(
            validate_workspace_suggestion(&too_long, &response(&too_long, "Shorter.")).is_none()
        );
        assert!(validate_workspace_suggestion(
            "We need 2 winners.",
            &response("We need 2 winners.", "We need 3 winners.")
        )
        .is_none());
        assert!(validate_workspace_suggestion(
            "We need 2 winners.",
            &response("We need 2 winners.", "We should choose 2 winners.")
        )
        .is_some());
        assert!(validate_workspace_suggestion("A different sentence.", &valid).is_none());
        assert!(validate_workspace_suggestion(&source, "NONE").is_none());
        assert!(validate_workspace_suggestion(&source, "not a response").is_none());
    }

    #[test]
    fn sentence_coaching_parser_rejects_malformed_fields_and_preserves_hud_vocabulary() {
        let valid = "PATTERN: sentence_clarity\nQUOTE: We buyed fruit.\nSUGGESTION: We bought fruit.\nHINT: Use the past tense.";
        for malformed in [
            String::new(),
            "PATTERN: sentence_clarity".to_string(),
            valid.replace("QUOTE: ", "SOURCE: "),
            valid.lines().take(2).collect::<Vec<_>>().join("\n"),
            valid.replace("SUGGESTION: ", "FIX: "),
            valid.lines().take(3).collect::<Vec<_>>().join("\n"),
            valid.replace("HINT: ", "WHY: "),
            format!("{valid}\nextra"),
            valid.replace("We buyed fruit.", ""),
            valid.replace("We bought fruit.", ""),
            valid.replace("Use the past tense.", ""),
            valid.replace("Use the past tense.", &"x".repeat(121)),
            valid.replace("sentence_clarity", "unsupported"),
            valid.replace("We bought fruit.", "We buyed fruit."),
            valid.replace("We bought fruit.", "We\tbought fruit."),
            valid.replace("Use the past tense.", "Use|the past tense."),
        ] {
            assert!(
                validate_workspace_suggestion("We buyed fruit.", &malformed).is_none(),
                "{malformed}"
            );
        }
        let vocabulary = "PATTERN: precision\nQUOTE: very good\nSUGGESTION: excellent\nHINT: A more precise word.";
        let fix =
            validate_language_suggestion(CoachFocus::Vocabulary, "It was very good.", vocabulary)
                .unwrap();
        assert_eq!(fix.pattern_id, "vocabulary.precision");
        assert!(fix.message.starts_with("Possible vocabulary suggestion:"));
    }

    #[test]
    fn language_suggestion_parser_requires_grounded_bounded_output() {
        let source = "I has a clear point.";
        let response = "PATTERN: subject_verb\nQUOTE: I has\nSUGGESTION: I have\nHINT: Match the verb to the subject.";
        assert_eq!(
            validate_language_suggestion(CoachFocus::Grammar, source, response)
                .map(|suggestion| suggestion.message),
            Some("Possible grammar suggestion: “I has” → “I have”. Match the verb to the subject. Check the transcript against what you meant.".to_string())
        );
        assert_eq!(
            validate_language_suggestion(CoachFocus::Grammar, source, "NONE"),
            None
        );
        assert_eq!(
            validate_language_suggestion(
                CoachFocus::Grammar,
                source,
                "PATTERN: subject_verb\nQUOTE: I had\nSUGGESTION: I have\nHINT: Match the verb."
            ),
            None
        );
        assert_eq!(
            validate_language_suggestion(
                CoachFocus::Grammar,
                "I have 2 points.",
                "PATTERN: word_choice\nQUOTE: 2 points\nSUGGESTION: 3 points\nHINT: Use the intended number."
            ),
            None
        );
        assert_eq!(
            validate_language_suggestion(CoachFocus::Pace, source, response),
            None
        );
    }

    #[test]
    fn older_session_records_without_pitch_or_language_counts_still_load() {
        let mut record = serde_json::to_value(session("legacy")).unwrap();
        let object = record.as_object_mut().unwrap();
        object.remove("pitchMedianHz");
        object.remove("pitchRangeHz");
        object.remove("grammarSuggestions");
        object.remove("vocabularySuggestions");
        object.remove("languagePatterns");
        let restored: CoachSession = serde_json::from_value(record).unwrap();
        assert_eq!(restored.pitch_median_hz, None);
        assert_eq!(restored.grammar_suggestions, 0);
        assert_eq!(restored.vocabulary_suggestions, 0);
    }

    #[test]
    fn standalone_recaps_aggregate_metrics_without_persisting_recognized_words() {
        let runtime = runtime_for_cues(
            {
                let mut settings = CoachSettings::default();
                settings.enabled = true;
                settings.focus = CoachFocus::Fillers;
                settings
            },
            true,
        );
        let words = [
            "um", "we", "will", "share", "the", "main", "idea", "then", "pause", "before", "we",
            "move", "to", "the", "next", "point", "and", "keep", "it", "clear",
        ]
        .join(" ");
        let pitch = Some(PitchStats {
            median_hz: 132,
            range_hz: 20,
        });
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert!(record_standalone_segment(
            &runtime, &words, 10.5, pitch, epoch
        ));
        assert!(record_standalone_segment(
            &runtime, &words, 10.5, pitch, epoch
        ));
        finish_standalone_session_for_runtime(&runtime).unwrap();

        let state = runtime.0.lock().unwrap();
        assert_eq!(state.store.sessions.len(), 1);
        let session = &state.store.sessions[0];
        assert_eq!(session.focus, CoachFocus::Fillers);
        assert_eq!(session.recognized_words, 40);
        assert_eq!(session.filler_words, 2);
        assert_eq!(session.pace_wpm, Some(114));
        assert_eq!(session.pitch_median_hz, Some(132));
        assert_eq!(session.pitch_range_hz, Some(20));
        assert!(session.examples.is_empty());
        assert!(state.active_session.is_none());
    }

    #[test]
    fn standalone_analysis_rejects_results_from_an_ended_capture_epoch() {
        let mut settings = CoachSettings::default();
        settings.enabled = true;
        let runtime = runtime_for_cues(settings, true);
        let old_epoch = standalone_analysis_epoch(&runtime).unwrap();
        let words = vec!["word"; 20].join(" ");
        {
            let mut state = runtime.0.lock().unwrap();
            state.settings.paused = true;
            advance_capture_epoch(&mut state);
            state.settings.paused = false;
            advance_capture_epoch(&mut state);
        }

        assert!(!standalone_analysis_is_current(&runtime, old_epoch));
        assert!(!record_standalone_segment(
            &runtime, &words, 10.0, None, old_epoch
        ));
        assert!(runtime.0.lock().unwrap().active_session.is_none());
        let mut stale_language_cue_published = false;
        assert!(!publish_language_suggestion(
            &runtime,
            CoachFocus::Grammar,
            "grammar.subject_verb",
            9,
            Some(old_epoch),
            || stale_language_cue_published = true,
        ));
        assert!(!stale_language_cue_published);
        let new_epoch = standalone_analysis_epoch(&runtime).unwrap();
        assert_ne!(old_epoch, new_epoch);
        assert!(record_standalone_segment(
            &runtime, &words, 10.0, None, new_epoch
        ));
    }

    #[test]
    fn standalone_feedback_publishes_metrics_only_while_originating_capture_is_current() {
        let mut settings = CoachSettings::default();
        settings.enabled = true;
        let runtime = runtime_for_cues(settings, true);
        let epoch = standalone_analysis_epoch(&runtime).unwrap();
        let words = vec!["word"; 20].join(" ");
        let pitch = Some(PitchStats {
            median_hz: 132,
            range_hz: 20,
        });
        let mut published = None;
        assert!(publish_standalone_feedback(
            &runtime,
            epoch,
            &words,
            10.0,
            pitch,
            |pace, published_pitch, cue| published = Some((pace, published_pitch, cue)),
        ));
        let (pace, published_pitch, cue) = published.unwrap();
        assert_eq!(pace, Some((120, 110, 160)));
        assert_eq!(published_pitch, pitch);
        assert!(cue.unwrap().contains("in your zone"));

        let stale_epoch = epoch;
        {
            let mut state = runtime.0.lock().unwrap();
            advance_capture_epoch(&mut state);
        }
        let mut stale_published = false;
        assert!(!publish_standalone_feedback(
            &runtime,
            stale_epoch,
            &words,
            10.0,
            pitch,
            |_, _, _| stale_published = true,
        ));
        assert!(!stale_published);
    }

    #[test]
    fn standalone_windows_require_the_same_idle_dictation_and_overlay_generation() {
        assert!(standalone_window_matches_capture(7, 7, 11, 11, true));
        assert!(!standalone_window_matches_capture(7, 8, 11, 11, true));
        assert!(!standalone_window_matches_capture(7, 7, 11, 12, true));
        assert!(!standalone_window_matches_capture(7, 7, 11, 11, false));
    }

    #[test]
    fn pitch_statistics_follow_synthetic_voicing_and_reject_silence_or_noise() {
        let sample_rate = 16_000_u32;
        let samples = (0..sample_rate)
            .map(|index| {
                let time = index as f32 / sample_rate as f32;
                0.45 * (std::f32::consts::TAU * 120.0 * time).sin()
                    + 0.12 * (std::f32::consts::TAU * 240.0 * time).sin()
            })
            .collect::<Vec<_>>();
        let pitch = estimate_pitch_stats(&samples, sample_rate).unwrap();
        assert!((117..=123).contains(&pitch.median_hz));
        assert!(pitch.range_hz <= 5);
        let recording_pitch = estimate_recording_pitch_stats(&samples, sample_rate).unwrap();
        assert!((117..=123).contains(&recording_pitch.median_hz));
        assert_eq!(estimate_pitch_stats(&vec![0.0; 16_000], sample_rate), None);
        let noise = (0..16_000)
            .map(|index| ((index * 1_103 + 79) % 2_003) as f32 / 2_003.0 - 0.5)
            .collect::<Vec<_>>();
        assert_eq!(estimate_pitch_stats(&noise, sample_rate), None);
        assert_eq!(estimate_pitch_stats(&samples, 0), None);
    }

    #[test]
    fn status_identifies_missing_local_model_for_live_analysis() {
        let mut settings = CoachSettings::default();
        settings.enabled = true;
        let runtime = runtime_for_cues(settings, true);
        set_analysis_ready(&runtime, false);
        assert_eq!(current_status(&runtime).unwrap().state, "waiting_for_model");
    }

    #[test]
    fn settings_and_session_bounds_are_enforced() {
        assert!(CoachSettings::default().validate().is_ok());
        let mut invalid = CoachSettings::default();
        invalid.target_pace_min = 200;
        assert!(invalid.validate().is_err());
        let mut too_long = session("one");
        too_long.speech_seconds = too_long.duration_seconds + 1;
        assert!(too_long.validate().is_err());
    }

    #[test]
    fn store_insert_is_unique_bounded_and_round_trips() {
        let mut store = CoachStore {
            version: 1,
            sessions: vec![],
        };
        store.insert(session("one")).unwrap();
        assert!(store.insert(session("one")).is_err());
        let root = std::env::temp_dir().join(format!("speech-coach-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        save_store(&root, &store).unwrap();
        assert_eq!(load_store(&root), store);
        fs::remove_dir_all(root).unwrap();
    }
}
