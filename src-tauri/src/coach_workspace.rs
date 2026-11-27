//! Memory-only transcript and fixes for the Speech Coach Live Workspace.
//! Nothing here is written to disk, logged or sent anywhere; closing clears it all.

use serde::Serialize;

pub const MAX_WORDS: usize = 2_000;
pub const MAX_FIXES: usize = 64;
const MIN_SENTENCE_WORDS: usize = 3;
const MAX_SENTENCE_BYTES: usize = 2_000;

pub struct NewFix {
    pub quote: String,
    pub suggestion: String,
    pub hint: String,
    pub pattern_id: String,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Fix {
    pub id: u32,
    pub quote: String,
    pub suggestion: String,
    pub hint: String,
    pub category: &'static str,
    pub pattern_id: String,
    /// The rule behind the fix in plain words, when one is written for it.
    pub rule: Option<&'static crate::coach_rules::Rule>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Part {
    pub text: String,
    pub fix_id: Option<u32>,
    pub suggestion: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub open: bool,
    pub state: &'static str,
    pub checks_available: bool,
    pub word_count: usize,
    pub parts: Vec<Part>,
    pub fixes: Vec<Fix>,
    pub pace_wpm: Option<u32>,
    pub apple_status: &'static str,
}

#[derive(Default)]
pub struct Workspace {
    open: bool,
    transcript: String,
    checked_upto: usize,
    fixes: Vec<Fix>,
    next_id: u32,
    checking: bool,
    checks_unavailable: bool,
    pace: Option<u32>,
    /// Earlier dictations, the dictation (overlay generation) now adding to the end, and what Clear already took.
    base: String,
    session: u64,
    last_session_len: usize,
    cut: usize,
    apple: u8,
}

impl Workspace {
    pub fn open(&mut self) {
        *self = Self {
            open: true,
            ..Self::default()
        };
    }

    /// Adds one dictation to the end of what is already here; the engine's text for the same dictation only grows.
    pub fn record_session(&mut self, generation: u64, text: &str) {
        if !self.open {
            return;
        }
        if generation != self.session {
            self.session = generation;
            self.base = self.transcript.clone();
            self.cut = 0;
        }
        let text = text.trim();
        self.last_session_len = text.len();
        let text = text.get(self.cut..).unwrap_or("").trim();
        if text.is_empty() {
            return;
        }
        let full = if self.base.is_empty() {
            text.to_string()
        } else {
            format!("{} {}", self.base, text)
        };
        self.replace_transcript(&full);
    }

    /// Empties the pad and the fixes on purpose; words already spoken in a running dictation do not come back.
    pub fn clear(&mut self) {
        if !self.open {
            return;
        }
        self.transcript.clear();
        self.base.clear();
        self.fixes.clear();
        self.checked_upto = 0;
        self.checking = false;
        self.pace = None;
        self.cut = self.last_session_len;
    }

    /// 0 available, 1 Apple Intelligence off, 2 still preparing, anything else unsupported.
    pub fn set_apple_status(&mut self, code: i32) {
        self.apple = u8::try_from(code).unwrap_or(3);
    }

    pub fn close(&mut self) {
        *self = Self::default();
    }

    pub fn is_open(&self) -> bool {
        self.open
    }

    pub fn append(&mut self, text: &str) {
        let text = text.trim();
        if !self.open || text.is_empty() {
            return;
        }
        if !self.transcript.is_empty() {
            self.transcript.push(' ');
        }
        self.transcript.push_str(text);
        self.trim_to_word_limit();
    }

    /// Replaces the transcript with the running text of a dictation, keeping what was already checked.
    pub fn replace_transcript(&mut self, text: &str) {
        let text = text.trim();
        if !self.open || text.is_empty() || text == self.transcript {
            return;
        }
        self.transcript = text.to_string();
        let mut checked = self.checked_upto.min(self.transcript.len());
        while !self.transcript.is_char_boundary(checked) {
            checked -= 1;
        }
        self.checked_upto = checked;
        self.trim_to_word_limit();
        let transcript = &self.transcript;
        self.fixes.retain(|fix| transcript.contains(&fix.quote));
    }

    fn trim_to_word_limit(&mut self) {
        let starts = word_starts(&self.transcript);
        if starts.len() <= MAX_WORDS {
            return;
        }
        let cut = starts[starts.len() - MAX_WORDS];
        self.transcript.drain(..cut);
        self.base.drain(..cut.min(self.base.len()));
        self.checked_upto = self.checked_upto.saturating_sub(cut);
        let transcript = &self.transcript;
        self.fixes.retain(|fix| transcript.contains(&fix.quote));
    }

    /// The next completed sentence not yet handed out, or None while it is still being spoken.
    pub fn next_sentence(&mut self) -> Option<String> {
        loop {
            let rest = self.transcript.get(self.checked_upto..)?;
            let end = rest.find(['.', '?', '!'])? + 1;
            let sentence = rest[..end].trim().to_string();
            self.checked_upto += end;
            if sentence.split_whitespace().count() >= MIN_SENTENCE_WORDS
                && sentence.len() <= MAX_SENTENCE_BYTES
            {
                return Some(sentence);
            }
        }
    }

    pub fn add_fix(&mut self, new: NewFix) -> bool {
        if !self.open
            || new.quote.is_empty()
            || self.fixes.len() >= MAX_FIXES
            || !self.transcript.contains(&new.quote)
            || self.fixes.iter().any(|fix| fix.quote == new.quote)
        {
            return false;
        }
        self.next_id += 1;
        let category = if new.pattern_id.starts_with("vocabulary.") {
            "Word choice"
        } else {
            "Grammar"
        };
        let rule =
            crate::coach_rules::rule_for(&new.pattern_id, &new.hint, &new.quote, &new.suggestion);
        self.fixes.push(Fix {
            id: self.next_id,
            quote: new.quote,
            suggestion: new.suggestion,
            hint: new.hint,
            category,
            pattern_id: new.pattern_id,
            rule,
        });
        true
    }

    /// Removes a fix the speaker says is not a mistake and returns its pattern id.
    pub fn dismiss(&mut self, id: u32) -> Option<String> {
        let index = self.fixes.iter().position(|fix| fix.id == id)?;
        Some(self.fixes.remove(index).pattern_id)
    }

    pub fn set_checking(&mut self, checking: bool) {
        self.checking = checking;
    }

    pub fn set_checks_available(&mut self, available: bool) {
        self.checks_unavailable = !available;
    }

    pub fn set_pace(&mut self, pace: Option<u32>) {
        self.pace = pace;
    }

    /// Non-overlapping marked ranges: each fix claims the first free occurrence of its quote.
    fn spans(&self) -> Vec<(usize, usize, &Fix)> {
        let mut spans: Vec<(usize, usize, &Fix)> = Vec::new();
        for fix in &self.fixes {
            let free = self
                .transcript
                .match_indices(&fix.quote)
                .find(|(start, _)| {
                    let end = start + fix.quote.len();
                    spans.iter().all(|(s, e, _)| end <= *s || *start >= *e)
                });
            if let Some((start, _)) = free {
                spans.push((start, start + fix.quote.len(), fix));
            }
        }
        spans.sort_by_key(|(start, _, _)| *start);
        spans
    }

    pub fn corrected_text(&self) -> String {
        let mut out = String::new();
        let mut at = 0;
        for (start, end, fix) in self.spans() {
            out.push_str(&self.transcript[at..start]);
            out.push_str(&fix.suggestion);
            at = end;
        }
        out.push_str(&self.transcript[at..]);
        out
    }

    pub fn snapshot(&self) -> Snapshot {
        let mut parts = Vec::new();
        let mut at = 0;
        for (start, end, fix) in self.spans() {
            if start > at {
                parts.push(plain(&self.transcript[at..start]));
            }
            parts.push(Part {
                text: self.transcript[start..end].to_string(),
                fix_id: Some(fix.id),
                suggestion: Some(fix.suggestion.clone()),
            });
            at = end;
        }
        if at < self.transcript.len() {
            parts.push(plain(&self.transcript[at..]));
        }
        Snapshot {
            open: self.open,
            state: if self.checks_unavailable {
                "unavailable"
            } else if self.checking {
                "checking"
            } else {
                "listening"
            },
            checks_available: !self.checks_unavailable,
            word_count: self.transcript.split_whitespace().count(),
            parts,
            fixes: self.fixes.clone(),
            pace_wpm: self.pace,
            apple_status: match self.apple {
                0 => "available",
                1 => "off",
                2 => "preparing",
                _ => "unsupported",
            },
        }
    }
}

pub const WINDOW_LABEL: &str = "coach-workspace";

#[derive(Default)]
pub struct CoachWorkspaceRuntime(pub std::sync::Mutex<Workspace>);

impl CoachWorkspaceRuntime {
    fn with<T>(&self, apply: impl FnOnce(&mut Workspace) -> T) -> Option<T> {
        self.0
            .lock()
            .ok()
            .map(|mut workspace| apply(&mut workspace))
    }

    pub fn is_open(&self) -> bool {
        self.with(|workspace| workspace.is_open()).unwrap_or(false)
    }

    /// Records the running text of a dictation and the current pace; true when the workspace wants it.
    pub fn record_transcript(&self, generation: u64, text: &str, pace_wpm: Option<u16>) -> bool {
        self.with(|workspace| {
            if !workspace.is_open() {
                return false;
            }
            workspace.record_session(generation, text);
            if let Some(pace) = pace_wpm {
                workspace.set_pace(Some(u32::from(pace)));
            }
            true
        })
        .unwrap_or(false)
    }

    /// Records a recognised segment and the current pace; true when the workspace wants it.
    pub fn record_segment(&self, text: &str, pace_wpm: Option<u16>) -> bool {
        self.with(|workspace| {
            if !workspace.is_open() {
                return false;
            }
            workspace.append(text);
            if let Some(pace) = pace_wpm {
                workspace.set_pace(Some(u32::from(pace)));
            }
            true
        })
        .unwrap_or(false)
    }

    pub fn next_sentence(&self) -> Option<String> {
        self.with(|workspace| workspace.next_sentence()).flatten()
    }

    pub fn set_checking(&self, checking: bool) {
        self.with(|workspace| workspace.set_checking(checking));
    }

    pub fn set_checks_available(&self, available: bool) {
        self.with(|workspace| workspace.set_checks_available(available));
    }

    pub fn set_apple_status(&self, code: i32) {
        self.with(|workspace| workspace.set_apple_status(code));
    }

    pub fn add_fix(&self, new: NewFix) -> bool {
        self.with(|workspace| workspace.add_fix(new))
            .unwrap_or(false)
    }
}

const POSITION_FILE: &str = "coach-workspace-position.json";
/// The dictation (overlay generation) in which the person pressed Done; the panel stays closed for the rest of it.
static DISMISSED_GENERATION: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Where the person last left the panel, in physical pixels. Only a screen position, never text.
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SavedPosition {
    pub x: i32,
    pub y: i32,
}

/// A remembered spot is used only while its top-left area is still on a connected display (a second screen may be unplugged).
pub fn position_on_screen(position: SavedPosition, screens: &[(i32, i32, u32, u32)]) -> bool {
    screens.iter().any(|&(left, top, width, height)| {
        position.x >= left
            && position.y >= top
            && i64::from(position.x) < i64::from(left) + i64::from(width) - 80
            && i64::from(position.y) < i64::from(top) + i64::from(height) - 60
    })
}

fn position_path(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    use tauri::Manager;
    app.path()
        .app_data_dir()
        .ok()
        .map(|dir| dir.join(POSITION_FILE))
}

/// Remembers where the panel was dragged so it opens there next time.
pub fn remember_position(app: &tauri::AppHandle, x: i32, y: i32) {
    let Some(path) = position_path(app) else {
        return;
    };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(json) = serde_json::to_vec(&SavedPosition { x, y }) {
        let _ = std::fs::write(path, json);
    }
}

fn saved_position(app: &tauri::AppHandle) -> Option<SavedPosition> {
    let bytes = std::fs::read(position_path(app)?).ok()?;
    serde_json::from_slice(&bytes).ok()
}

/// Opens the panel next to the HUD without taking focus from the app being used. It is hidden from screen sharing and recordings.
pub fn open_window(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri::Manager;
    let runtime = app
        .try_state::<CoachWorkspaceRuntime>()
        .ok_or("Live Workspace is unavailable")?;
    runtime.with(|workspace| workspace.open());
    if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        return window
            .show()
            .map_err(|_| "Cannot show the Live Workspace".into());
    }
    let window = tauri::WebviewWindowBuilder::new(
        app,
        WINDOW_LABEL,
        tauri::WebviewUrl::App("assets/coach-workspace.html".into()),
    )
    .title("Speech Coach Live Workspace")
    .inner_size(420.0, 640.0)
    .resizable(false)
    .decorations(false)
    .transparent(true)
    .shadow(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .content_protected(true)
    .focused(false)
    .build()
    .map_err(|_| "Cannot open the Live Workspace".to_string())?;
    if let Some(saved) = saved_position(app) {
        let screens: Vec<(i32, i32, u32, u32)> = app
            .available_monitors()
            .unwrap_or_default()
            .iter()
            .map(|monitor| {
                let origin = monitor.position();
                let size = monitor.size();
                (origin.x, origin.y, size.width, size.height)
            })
            .collect();
        if position_on_screen(saved, &screens) {
            let _ = window.set_position(tauri::PhysicalPosition::new(saved.x, saved.y));
        }
    }
    Ok(())
}

/// Opens the panel when Speech Coach starts coaching a dictation, unless it is already open or was closed with Done during this dictation.
pub fn open_for_dictation(app: &tauri::AppHandle, generation: u64) {
    use std::sync::atomic::Ordering;
    use tauri::Manager;
    let Some(runtime) = app.try_state::<CoachWorkspaceRuntime>() else {
        return;
    };
    if runtime.is_open() || DISMISSED_GENERATION.load(Ordering::Acquire) == generation {
        return;
    }
    let _ = open_window(app);
}

/// Records that Done was pressed during this dictation, so the next transcript does not reopen the panel.
pub fn dismiss_for_dictation(generation: u64) {
    DISMISSED_GENERATION.store(generation, std::sync::atomic::Ordering::Release);
}

/// Clears the transcript and fixes, then removes the panel.
pub fn close_window(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(runtime) = app.try_state::<CoachWorkspaceRuntime>() {
        runtime.with(|workspace| workspace.close());
    }
    if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        *CLOSED_AT.lock().unwrap_or_else(|e| e.into_inner()) = Some(std::time::Instant::now());
        let _ = window.destroy();
    }
}

static CLOSED_AT: std::sync::Mutex<Option<std::time::Instant>> = std::sync::Mutex::new(None);

/// macOS reports an app "reopen" when the last visible window closes; that must not raise the main window.
pub fn closed_recently() -> bool {
    CLOSED_AT
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .is_some_and(|at| at.elapsed() < std::time::Duration::from_secs(2))
}

#[cfg(target_os = "macos")]
extern "C" {
    fn officekit_dictation_polish_status() -> i32;
}

/// Whether Apple's on-device model can run: 0 yes, 1 turned off, 2 still preparing, 3 not on this Mac.
fn apple_intelligence_status() -> i32 {
    #[cfg(target_os = "macos")]
    return unsafe { officekit_dictation_polish_status() };
    #[cfg(not(target_os = "macos"))]
    3
}

#[tauri::command]
pub fn coach_workspace_snapshot(
    runtime: tauri::State<'_, CoachWorkspaceRuntime>,
) -> Result<Snapshot, String> {
    // Re-asked on every poll so turning Apple Intelligence on in System Settings shows up without a restart.
    let status = apple_intelligence_status();
    runtime
        .with(|workspace| {
            workspace.set_apple_status(status);
            workspace.snapshot()
        })
        .ok_or_else(|| "Live Workspace is unavailable".into())
}

/// Clear: empties the pad and the fixes but keeps the panel open.
#[tauri::command]
pub fn coach_workspace_clear(
    runtime: tauri::State<'_, CoachWorkspaceRuntime>,
) -> Result<Snapshot, String> {
    runtime
        .with(|workspace| {
            workspace.clear();
            workspace.snapshot()
        })
        .ok_or_else(|| "Live Workspace is unavailable".into())
}

/// Opens the Apple Intelligence pane of System Settings.
#[tauri::command]
pub fn coach_workspace_open_apple_intelligence() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("/usr/bin/open")
            .arg("x-apple.systempreferences:com.apple.Siri-Settings.extension")
            .spawn()
            .map(|_| ())
            .map_err(|_| "System Settings could not be opened".to_string())
    }
    #[cfg(not(target_os = "macos"))]
    Err("System Settings is not available on this system".into())
}

#[tauri::command]
pub fn coach_workspace_corrected_text(
    runtime: tauri::State<'_, CoachWorkspaceRuntime>,
) -> Result<String, String> {
    runtime
        .with(|workspace| workspace.corrected_text())
        .ok_or_else(|| "Live Workspace is unavailable".into())
}

/// "Not a mistake": drops the fix and tells the coach to show that pattern less.
#[tauri::command]
pub fn coach_workspace_dismiss(
    runtime: tauri::State<'_, CoachWorkspaceRuntime>,
    coach: tauri::State<'_, crate::speech_coach::CoachRuntime>,
    fix_id: u32,
) -> Result<Snapshot, String> {
    let pattern = runtime
        .with(|workspace| workspace.dismiss(fix_id))
        .ok_or("Live Workspace is unavailable")?;
    if let Some(pattern_id) = pattern {
        crate::speech_coach::speech_coach_set_pattern_dismissed(coach, pattern_id, true)?;
    }
    coach_workspace_snapshot(runtime)
}

/// Done: clears the workspace and stops Listen In so the microphone is not left open unseen.
#[tauri::command]
pub fn coach_workspace_done(
    app: tauri::AppHandle,
    coach: tauri::State<'_, crate::speech_coach::CoachRuntime>,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    dismiss_for_dictation(unsafe { crate::officekit_dictation_overlay_generation() });
    close_window(&app);
    crate::speech_coach::speech_coach_set_listen_in(&coach, false).map(|_| ())
}

fn plain(text: &str) -> Part {
    Part {
        text: text.to_string(),
        fix_id: None,
        suggestion: None,
    }
}

fn word_starts(text: &str) -> Vec<usize> {
    let mut starts = Vec::new();
    let mut in_word = false;
    for (index, character) in text.char_indices() {
        if character.is_whitespace() {
            in_word = false;
        } else if !in_word {
            in_word = true;
            starts.push(index);
        }
    }
    starts
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fix(quote: &str, suggestion: &str) -> NewFix {
        NewFix {
            quote: quote.into(),
            suggestion: suggestion.into(),
            hint: "Irregular past tense".into(),
            pattern_id: "grammar.tense".into(),
        }
    }

    fn open_with(text: &str) -> Workspace {
        let mut workspace = Workspace::default();
        workspace.open();
        workspace.append(text);
        workspace
    }

    #[test]
    fn appending_while_closed_keeps_nothing() {
        let mut workspace = Workspace::default();
        workspace.append("We went to the market early.");
        assert_eq!(workspace.snapshot().word_count, 0);
    }

    #[test]
    fn segments_join_with_single_spaces() {
        let mut workspace = open_with("  Hello there  ");
        workspace.append("how are you");
        let snapshot = workspace.snapshot();
        assert_eq!(snapshot.word_count, 5);
        assert_eq!(snapshot.parts.len(), 1);
        assert_eq!(snapshot.parts[0].text, "Hello there how are you");
    }

    #[test]
    fn blank_segments_are_ignored() {
        let mut workspace = open_with("Hello there");
        workspace.append("   ");
        assert_eq!(workspace.snapshot().word_count, 2);
    }

    #[test]
    fn next_sentence_returns_each_complete_sentence_once_in_order() {
        let mut workspace = open_with(
            "Yesterday I was two friends at the market. We buyed some fruit today. The prices",
        );
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("Yesterday I was two friends at the market.")
        );
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("We buyed some fruit today.")
        );
        assert_eq!(workspace.next_sentence(), None);
        workspace.append("is very low today.");
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("The prices is very low today.")
        );
    }

    #[test]
    fn short_sentences_are_skipped_not_checked() {
        let mut workspace = open_with("Okay then. Right. We went to the market early.");
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("We went to the market early.")
        );
    }

    #[test]
    fn a_fix_must_quote_words_present_in_the_transcript() {
        let mut workspace = open_with("We buyed some fruit today.");
        assert!(!workspace.add_fix(fix("bought it", "bought")));
        assert!(workspace.add_fix(fix("buyed", "bought")));
        assert!(
            !workspace.add_fix(fix("buyed", "bought")),
            "same words are not listed twice"
        );
        assert_eq!(workspace.snapshot().fixes.len(), 1);
    }

    #[test]
    fn a_fix_carries_the_rule_behind_it() {
        let mut workspace = open_with("We buyed some fruit and the prices is low. Also teh end.");
        let with = |quote: &str, suggestion: &str, hint: &str, pattern_id: &str| NewFix {
            quote: quote.into(),
            suggestion: suggestion.into(),
            hint: hint.into(),
            pattern_id: pattern_id.into(),
        };
        assert!(workspace.add_fix(with(
            "prices is",
            "prices are",
            "Subject–verb agreement",
            "grammar.subject_verb"
        )));
        assert!(workspace.add_fix(with(
            "buyed",
            "bought",
            "Irregular past tense",
            "grammar.harper"
        )));
        assert!(workspace.add_fix(with("teh", "the", "A wording slip", "grammar.harper")));
        let fixes = workspace.snapshot().fixes;
        let rule = fixes[0].rule.expect("subject-verb rule");
        assert!(rule.rule.contains("plural subject takes a plural verb"));
        assert_eq!(fixes[1].rule.map(|r| r.title), Some("Irregular forms"));
        assert!(
            fixes[2].rule.is_none(),
            "no written rule: the fix still shows its hint"
        );
        let json = serde_json::to_value(&fixes[0]).unwrap();
        assert_eq!(json["rule"]["title"], "Subject–verb agreement");
        assert_eq!(json["rule"]["wrong"], "The prices is low.");
    }

    #[test]
    fn fixes_are_capped() {
        let words: Vec<String> = (0..80).map(|n| format!("word{n}")).collect();
        let mut workspace = open_with(&words.join(" "));
        let added = (0..80)
            .filter(|n| workspace.add_fix(fix(&format!("word{n}"), "fixed")))
            .count();
        assert_eq!(added, MAX_FIXES);
    }

    #[test]
    fn parts_mark_the_quoted_words_with_the_fix() {
        let mut workspace = open_with("Yesterday we buyed some fruit and the prices is low.");
        workspace.add_fix(fix("buyed", "bought"));
        workspace.add_fix(fix("prices is", "prices are"));
        let parts = workspace.snapshot().parts;
        let texts: Vec<&str> = parts.iter().map(|part| part.text.as_str()).collect();
        assert_eq!(
            texts,
            [
                "Yesterday we ",
                "buyed",
                " some fruit and the ",
                "prices is",
                " low."
            ]
        );
        assert_eq!(parts[1].suggestion.as_deref(), Some("bought"));
        assert_eq!(parts[1].fix_id, Some(1));
        assert_eq!(parts[3].fix_id, Some(2));
        assert_eq!(parts[0].fix_id, None);
    }

    #[test]
    fn overlapping_quotes_mark_only_the_first_fix() {
        let mut workspace = open_with("I was two friends there.");
        workspace.add_fix(fix("was two friends", "met two friends"));
        workspace.add_fix(fix("two friends", "both friends"));
        let marked: Vec<_> = workspace
            .snapshot()
            .parts
            .into_iter()
            .filter(|part| part.fix_id.is_some())
            .collect();
        assert_eq!(marked.len(), 1);
        assert_eq!(marked[0].text, "was two friends");
    }

    #[test]
    fn corrected_text_applies_every_listed_fix() {
        let mut workspace = open_with("We buyed some fruit and the prices is low.");
        workspace.add_fix(fix("buyed", "bought"));
        workspace.add_fix(fix("prices is", "prices are"));
        assert_eq!(
            workspace.corrected_text(),
            "We bought some fruit and the prices are low."
        );
    }

    #[test]
    fn dismissing_removes_the_fix_and_returns_its_pattern() {
        let mut workspace = open_with("We buyed some fruit today.");
        workspace.add_fix(fix("buyed", "bought"));
        assert_eq!(workspace.dismiss(1).as_deref(), Some("grammar.tense"));
        assert_eq!(workspace.dismiss(1), None);
        let snapshot = workspace.snapshot();
        assert!(snapshot.fixes.is_empty());
        assert_eq!(snapshot.parts.len(), 1);
        assert_eq!(workspace.corrected_text(), "We buyed some fruit today.");
    }

    #[test]
    fn closing_clears_everything() {
        let mut workspace = open_with("We buyed some fruit today.");
        workspace.add_fix(fix("buyed", "bought"));
        workspace.close();
        let snapshot = workspace.snapshot();
        assert!(!snapshot.open);
        assert_eq!(snapshot.word_count, 0);
        assert!(snapshot.fixes.is_empty());
        assert_eq!(workspace.corrected_text(), "");
        workspace.open();
        assert_eq!(workspace.snapshot().word_count, 0);
        assert_eq!(workspace.next_sentence(), None);
    }

    #[test]
    fn only_the_last_two_thousand_words_are_kept() {
        let mut workspace = Workspace::default();
        workspace.open();
        workspace.append("first words stay only briefly here.");
        workspace.add_fix(fix("briefly", "shortly"));
        let filler = vec!["word"; MAX_WORDS].join(" ");
        workspace.append(&filler);
        let snapshot = workspace.snapshot();
        assert_eq!(snapshot.word_count, MAX_WORDS);
        assert!(
            snapshot.fixes.is_empty(),
            "a fix whose words scrolled off is dropped"
        );
    }

    #[test]
    fn trimming_keeps_the_sentence_cursor_pointing_at_unchecked_text() {
        let mut workspace = Workspace::default();
        workspace.open();
        workspace.append("Old sentence number one is here.");
        assert!(workspace.next_sentence().is_some());
        workspace.append(&vec!["Another filler sentence goes here."; MAX_WORDS / 5].join(" "));
        let sentence = workspace
            .next_sentence()
            .expect("unchecked text remains after trimming");
        assert!(sentence.ends_with("here."), "{sentence}");
        assert!(!sentence.contains("Old sentence"));
    }

    #[test]
    fn state_reports_unavailable_before_checking_before_listening() {
        let mut workspace = open_with("Hello there everyone.");
        assert_eq!(workspace.snapshot().state, "listening");
        workspace.set_checking(true);
        assert_eq!(workspace.snapshot().state, "checking");
        workspace.set_checks_available(false);
        assert_eq!(workspace.snapshot().state, "unavailable");
        assert!(!workspace.snapshot().checks_available);
    }

    #[test]
    fn categories_come_from_the_pattern_prefix() {
        let mut workspace = open_with("We buyed some fruit today.");
        workspace.add_fix(fix("buyed", "bought"));
        let mut word_choice = fix("fruit", "produce");
        word_choice.pattern_id = "vocabulary.word_choice".into();
        workspace.add_fix(word_choice);
        let categories: Vec<_> = workspace
            .snapshot()
            .fixes
            .iter()
            .map(|f| f.category)
            .collect();
        assert_eq!(categories, ["Grammar", "Word choice"]);
    }

    #[test]
    fn pace_is_reported_only_when_known() {
        let mut workspace = open_with("Hello there everyone.");
        assert_eq!(workspace.snapshot().pace_wpm, None);
        workspace.set_pace(Some(142));
        assert_eq!(workspace.snapshot().pace_wpm, Some(142));
    }

    #[test]
    fn the_running_text_of_a_dictation_replaces_the_transcript_without_rechecking_sentences() {
        let mut workspace = Workspace::default();
        workspace.open();
        workspace.replace_transcript("We was hoping to ship on Friday.");
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("We was hoping to ship on Friday.")
        );
        workspace
            .replace_transcript("We was hoping to ship on Friday. The team don't have numbers.");
        assert_eq!(
            workspace.next_sentence().as_deref(),
            Some("The team don't have numbers.")
        );
        assert_eq!(workspace.next_sentence(), None);
        workspace.replace_transcript("   ");
        assert_eq!(workspace.snapshot().word_count, 12);
    }

    #[test]
    fn a_closed_workspace_ignores_the_running_text() {
        let mut workspace = Workspace::default();
        workspace.replace_transcript("We went to the market early.");
        assert_eq!(workspace.snapshot().word_count, 0);
    }

    #[test]
    fn a_shorter_replacement_keeps_the_checked_point_on_a_character_boundary() {
        let mut workspace = Workspace::default();
        workspace.open();
        workspace.replace_transcript("Café owners were hoping for sales today.");
        let _ = workspace.next_sentence();
        workspace.replace_transcript("Café");
        assert_eq!(workspace.snapshot().word_count, 1);
    }

    #[test]
    fn a_remembered_position_is_used_only_while_it_is_on_a_connected_display() {
        let screens = [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)];
        assert!(position_on_screen(
            SavedPosition { x: 100, y: 100 },
            &screens
        ));
        assert!(position_on_screen(
            SavedPosition { x: 3000, y: 50 },
            &screens
        ));
        assert!(!position_on_screen(
            SavedPosition { x: 3000, y: 50 },
            &screens[..1]
        ));
        assert!(!position_on_screen(
            SavedPosition { x: 2520, y: 100 },
            &screens[..1]
        ));
        assert!(!position_on_screen(
            SavedPosition { x: -400, y: 100 },
            &screens
        ));
        assert!(!position_on_screen(SavedPosition { x: 100, y: 100 }, &[]));
    }

    #[test]
    fn done_keeps_the_panel_closed_for_the_rest_of_that_dictation_only() {
        dismiss_for_dictation(41);
        assert_eq!(
            DISMISSED_GENERATION.load(std::sync::atomic::Ordering::Acquire),
            41
        );
        assert_ne!(
            DISMISSED_GENERATION.load(std::sync::atomic::Ordering::Acquire),
            42
        );
    }

    #[test]
    fn each_dictation_is_added_after_the_earlier_ones() {
        let mut workspace = open_with("");
        workspace.record_session(1, "We went to the market.");
        workspace.record_session(1, "We went to the market. It was busy.");
        workspace.record_session(2, "The prices were low.");
        assert_eq!(
            workspace.snapshot().parts[0].text,
            "We went to the market. It was busy. The prices were low."
        );
        workspace.record_session(2, "The prices were low. I bought fruit.");
        assert_eq!(
            workspace.corrected_text(),
            "We went to the market. It was busy. The prices were low. I bought fruit."
        );
    }

    #[test]
    fn clear_empties_the_pad_but_not_words_already_spoken_in_the_running_dictation() {
        let mut workspace = open_with("");
        workspace.record_session(1, "We buyed fruit today.");
        assert!(workspace.add_fix(NewFix {
            quote: "buyed".into(),
            suggestion: "bought".into(),
            hint: "Irregular".into(),
            pattern_id: "grammar.tense".into(),
        }));
        workspace.clear();
        let snapshot = workspace.snapshot();
        assert!(snapshot.parts.is_empty() && snapshot.fixes.is_empty() && snapshot.open);
        workspace.record_session(1, "We buyed fruit today.");
        assert!(workspace.snapshot().parts.is_empty());
        workspace.record_session(1, "We buyed fruit today. Prices are low.");
        assert_eq!(workspace.corrected_text(), "Prices are low.");
        workspace.record_session(2, "A new dictation.");
        assert_eq!(
            workspace.corrected_text(),
            "Prices are low. A new dictation."
        );
    }

    #[test]
    fn the_snapshot_says_why_apple_intelligence_is_not_helping() {
        let mut workspace = open_with("");
        for (code, label) in [
            (0, "available"),
            (1, "off"),
            (2, "preparing"),
            (3, "unsupported"),
            (9, "unsupported"),
        ] {
            workspace.set_apple_status(code);
            assert_eq!(workspace.snapshot().apple_status, label);
        }
    }
}
