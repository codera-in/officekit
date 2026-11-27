//! Pure, engine-agnostic helpers that raise dictation quality: silence trimming,
//! Whisper prompt building, stable-prefix commit and focus-context validation.
//!
//! Nothing here logs or returns audio, transcript or field text in an error.

#![cfg_attr(not(target_os = "macos"), allow(dead_code))]

use std::collections::BTreeMap;
use std::ops::Range;

use crate::dictation::DICTATION_SAMPLE_RATE;

const FRAME_SAMPLES: usize = (DICTATION_SAMPLE_RATE as usize) / 50; // 20 ms
const PADDING_FRAMES: usize = 10; // 200 ms kept on both sides of speech
const MIN_SPEECH_RUN_FRAMES: usize = 3; // 60 ms of consecutive energy counts as speech
const NOISE_FLOOR_PERCENTILE: usize = 20;
const NOISE_FLOOR_MULTIPLIER: f32 = 3.0;
const ABSOLUTE_SPEECH_RMS: f32 = 0.004;
const CLEAR_SPEECH_RMS: f32 = 0.02;
const MIN_DYNAMIC_RANGE: f32 = 2.0;
const MAX_THRESHOLD_PEAK_FRACTION: f32 = 0.25;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrimResult {
    pub range: Range<usize>,
    pub had_speech: bool,
}

fn frame_rms(frame: &[f32]) -> f32 {
    if frame.is_empty() {
        return 0.0;
    }
    let energy: f32 = frame
        .iter()
        .map(|sample| {
            if sample.is_finite() {
                sample * sample
            } else {
                0.0
            }
        })
        .sum();
    (energy / frame.len() as f32).sqrt()
}

/// What the microphone step of the history shows. Numbers only, never audio.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct CaptureStats {
    pub recorded_seconds: f64,
    pub speech_seconds: f64,
    pub had_speech: bool,
    /// Loudest 20 ms frame in dB relative to full scale; absent for pure digital silence.
    pub level_db: Option<f32>,
}

pub fn capture_stats(samples: &[f32]) -> CaptureStats {
    let rate = DICTATION_SAMPLE_RATE as f64;
    let trimmed = trim_silence(samples);
    let peak = samples
        .chunks(FRAME_SAMPLES)
        .map(frame_rms)
        .fold(0.0_f32, f32::max);
    let round = |seconds: f64| (seconds * 10.0).round() / 10.0;
    CaptureStats {
        recorded_seconds: round(samples.len() as f64 / rate),
        speech_seconds: round(trimmed.range.len() as f64 / rate),
        had_speech: trimmed.had_speech,
        level_db: (peak > 0.0).then(|| (20.0 * peak.log10()).round()),
    }
}

/// Locate the speech inside a 16 kHz mono clip and return the range to decode.
///
/// The range keeps padding around speech, never exceeds the input and keeps any
/// silence between two speech runs. When no sustained speech is found the range
/// is empty and `had_speech` is false, so callers skip decoding instead of
/// letting an engine invent text for silence.
pub fn trim_silence(samples: &[f32]) -> TrimResult {
    let mask = speech_mask(samples);
    let (Some(first), Some(last)) = (
        mask.iter().position(|speech| *speech),
        mask.iter().rposition(|speech| *speech),
    ) else {
        return TrimResult {
            range: 0..0,
            had_speech: false,
        };
    };
    let start = first.saturating_sub(PADDING_FRAMES) * FRAME_SAMPLES;
    let end = ((last + 1 + PADDING_FRAMES) * FRAME_SAMPLES).min(samples.len());
    TrimResult {
        range: start..end,
        had_speech: true,
    }
}

/// Per-frame (20 ms) speech flags. A frame is speech only inside a run of at
/// least `MIN_SPEECH_RUN_FRAMES` consecutive energetic frames, so clicks and
/// isolated noise never count. Clips with no quiet/loud contrast are judged by
/// absolute level: steady noise is silence, speech filling the clip is speech.
fn speech_mask(samples: &[f32]) -> Vec<bool> {
    let frame_rms_values: Vec<f32> = samples.chunks(FRAME_SAMPLES).map(frame_rms).collect();
    let frames = frame_rms_values.len();
    if frames < MIN_SPEECH_RUN_FRAMES {
        let peak = frame_rms_values.iter().cloned().fold(0.0_f32, f32::max);
        return vec![peak > ABSOLUTE_SPEECH_RMS; frames];
    }

    let mut sorted = frame_rms_values.clone();
    sorted.sort_by(|left, right| left.total_cmp(right));
    let floor = sorted[frames * NOISE_FLOOR_PERCENTILE / 100];
    let peak = sorted[frames - 1];
    if peak < floor * MIN_DYNAMIC_RANGE {
        return vec![peak > CLEAR_SPEECH_RMS; frames];
    }
    let threshold = (floor * NOISE_FLOOR_MULTIPLIER)
        .min(peak * MAX_THRESHOLD_PEAK_FRACTION)
        .max(ABSOLUTE_SPEECH_RMS);

    let mut mask = vec![false; frames];
    let mut run_start = 0;
    let mut run_length = 0;
    for (index, rms) in frame_rms_values.iter().enumerate() {
        if *rms > threshold {
            if run_length == 0 {
                run_start = index;
            }
            run_length += 1;
            if run_length == MIN_SPEECH_RUN_FRAMES {
                mask[run_start..=index].fill(true);
            } else if run_length > MIN_SPEECH_RUN_FRAMES {
                mask[index] = true;
            }
        } else {
            run_length = 0;
        }
    }
    mask
}

/// 700 ms of silence ends a segment; shorter gaps are normal speech rhythm.
const COMMIT_PAUSE_FRAMES: usize = 35;
/// A segment needs at least one second of speech before it is worth committing.
const COMMIT_MIN_SPEECH_FRAMES: usize = 50;
/// Do not scan or decode until this much audio is waiting (3 s).
pub const COMMIT_MIN_PENDING_SAMPLES: usize = (DICTATION_SAMPLE_RATE as usize) * 3;

/// Find where already-spoken audio can be decoded for good while the user keeps
/// talking. Returns the sample offset (relative to `pending`) in the middle of the
/// last pause that follows enough speech, or `None` when there is no safe cut.
///
/// Cuts land inside silence, so no word is ever split. The audio after the cut
/// stays pending and is decoded when the key is released.
pub fn find_commit_boundary(pending: &[f32]) -> Option<usize> {
    if pending.len() < COMMIT_MIN_PENDING_SAMPLES {
        return None;
    }
    let mask = speech_mask(pending);
    let mut speech_frames = 0;
    let mut boundary: Option<usize> = None;
    let mut index = 0;
    while index < mask.len() {
        if mask[index] {
            speech_frames += 1;
            index += 1;
            continue;
        }
        let run_start = index;
        while index < mask.len() && !mask[index] {
            index += 1;
        }
        let run_length = index - run_start;
        if run_length >= COMMIT_PAUSE_FRAMES && speech_frames >= COMMIT_MIN_SPEECH_FRAMES {
            boundary = Some((run_start + run_length / 2) * FRAME_SAMPLES);
        }
    }
    boundary.filter(|offset| *offset > 0 && *offset < pending.len())
}

/// Fewest words per second of speech a real decode produces. Ordinary speech runs
/// 2 to 3; a decode below this lost words (the decoder stopped early or returned nothing).
pub const MIN_WORDS_PER_SPEECH_SECOND: f32 = 0.6;

/// Whether `text` could be everything said in `samples`. A false answer means the
/// decoder dropped words, so the audio must be decoded again, not trusted.
pub fn decode_is_plausible(samples: &[f32], text: &str) -> bool {
    let speech_frames = speech_mask(samples)
        .iter()
        .filter(|speech| **speech)
        .count();
    let speech_seconds = speech_frames as f32 * FRAME_SAMPLES as f32 / DICTATION_SAMPLE_RATE as f32;
    if speech_seconds < 1.0 {
        return true;
    }
    let expected = ((speech_seconds * MIN_WORDS_PER_SPEECH_SECOND) as usize).max(1);
    text.split_whitespace().count() >= expected
}

/// Text decoded ahead of the key release, plus how much audio it covers.
/// Deliberately not `Debug`: it holds transcript text.
#[derive(Default)]
pub struct CommitState {
    generation: u64,
    committed_end: usize,
    next_try_at: usize,
    texts: Vec<String>,
}

impl CommitState {
    /// Start over for a new capture.
    pub fn reset(&mut self, generation: u64) {
        self.generation = generation;
        self.committed_end = 0;
        self.next_try_at = 0;
        self.texts.clear();
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn committed_end(&self) -> usize {
        self.committed_end
    }

    /// Record a decoded segment. Accepts only the next contiguous segment of the
    /// current capture; anything stale or out of order is dropped.
    pub fn commit(&mut self, generation: u64, start: usize, end: usize, text: &str) -> bool {
        if generation != self.generation || start != self.committed_end || end <= start {
            return false;
        }
        self.committed_end = end;
        let text = text.trim();
        if !text.is_empty() {
            self.texts.push(text.to_string());
        }
        true
    }

    /// Do not try another segment until this many samples exist.
    pub fn next_try_at(&self) -> usize {
        self.next_try_at
    }

    /// A segment decoded to too few words: keep the marker where it is, so the audio is
    /// decoded again with more around it, and wait for 3 s more before trying again.
    pub fn reject(&mut self, generation: u64, available: usize) {
        if generation == self.generation {
            self.next_try_at = available + COMMIT_MIN_PENDING_SAMPLES;
        }
    }

    pub fn committed_text(&self) -> String {
        self.texts.join(" ")
    }

    /// The segments decoded while speaking, in order, for the history steps view.
    pub fn pieces(&self) -> Vec<String> {
        self.texts.clone()
    }
}

/// Join text committed while speaking with the text decoded after the last cut.
pub fn join_committed(committed: &str, tail: &str) -> String {
    match (committed.trim(), tail.trim()) {
        ("", tail) => tail.to_string(),
        (committed, "") => committed.to_string(),
        (committed, tail) => format!("{committed} {tail}"),
    }
}

pub const MAX_CONTEXT_LABEL_CHARACTERS: usize = 128;
pub const MAX_FIELD_TEXT_CHARACTERS: usize = 1_000;
pub const FOCUS_CONTEXT_BUFFER_BYTES: usize = 16 * 1024;

/// What the user allows dictation to learn about the place they are typing.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ContextOptions {
    pub app_context: bool,
    pub field_text: bool,
}

impl Default for ContextOptions {
    fn default() -> Self {
        Self {
            app_context: true,
            field_text: false,
        }
    }
}

impl ContextOptions {
    pub fn wants_context(self) -> bool {
        self.app_context || self.field_text
    }
}

#[derive(Clone, Default, PartialEq, Eq, serde::Deserialize)]
pub struct FocusContext {
    #[serde(default)]
    pub app_name: Option<String>,
    #[serde(default)]
    pub bundle_id: Option<String>,
    #[serde(default)]
    pub field_role: Option<String>,
    #[serde(default)]
    pub field_text: Option<String>,
}

// Field text is sensitive, so Debug never prints it.
impl std::fmt::Debug for FocusContext {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("FocusContext")
            .field("app_name", &self.app_name)
            .field("bundle_id", &self.bundle_id)
            .field("field_role", &self.field_role)
            .field(
                "field_text",
                &self.field_text.as_ref().map(|_| "<redacted>"),
            )
            .finish()
    }
}

fn sanitized_field_text(value: &str) -> String {
    let cleaned: String = value
        .chars()
        .map(|character| {
            if character == '\n' || !character.is_control() {
                character
            } else {
                ' '
            }
        })
        .collect();
    cleaned
        .trim()
        .chars()
        .take(MAX_FIELD_TEXT_CHARACTERS)
        .collect()
}

impl FocusContext {
    /// Keep only what the user's options allow. Returns `None` when nothing remains.
    pub fn filtered(self, options: ContextOptions) -> Option<Self> {
        let filtered = Self {
            app_name: options.app_context.then_some(self.app_name).flatten(),
            bundle_id: options.app_context.then_some(self.bundle_id).flatten(),
            field_role: options.app_context.then_some(self.field_role).flatten(),
            field_text: options.field_text.then_some(self.field_text).flatten(),
        };
        (filtered != Self::default()).then_some(filtered)
    }
}

/// Parse and bound the JSON the native layer returns. Anything malformed or empty
/// is "no context"; context is best effort and never an error.
pub fn parse_focus_context(bytes: &[u8]) -> Option<FocusContext> {
    let raw: FocusContext = serde_json::from_slice(bytes).ok()?;
    let label = |value: Option<String>| {
        value
            .map(|text| sanitized_text(&text, MAX_CONTEXT_LABEL_CHARACTERS))
            .filter(|text| !text.is_empty())
    };
    let context = FocusContext {
        app_name: label(raw.app_name),
        bundle_id: label(raw.bundle_id),
        field_role: label(raw.field_role),
        field_text: raw
            .field_text
            .map(|text| sanitized_field_text(&text))
            .filter(|text| !text.is_empty()),
    };
    (context != FocusContext::default()).then_some(context)
}

/// Options for the loopback cleanup request. The default is today's request.
#[derive(Default)]
pub struct CleanupOptions<'a> {
    pub smart: bool,
    pub language: Option<&'a str>,
    pub context: Option<&'a FocusContext>,
}

/// Accept a short alphabetic language tag such as `en` or `pt-br`; anything else is dropped.
pub fn validate_language_hint(language: &str) -> Option<String> {
    let trimmed = language.trim();
    let valid = (2..=8).contains(&trimmed.len())
        && trimmed
            .chars()
            .all(|character| character.is_ascii_alphabetic() || character == '-')
        && trimmed
            .chars()
            .next()
            .is_some_and(|character| character.is_ascii_alphabetic());
    valid.then(|| trimmed.to_ascii_lowercase())
}

/// Most apps that can carry their own cleanup settings.
pub const MAX_APP_MODES: usize = 64;

/// One app's cleanup choices; `None` follows the global switch.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppMode {
    #[serde(default)]
    pub smart: Option<bool>,
    #[serde(default)]
    pub fix_grammar: Option<bool>,
}

/// A bundle identifier: letters, digits, dots, dashes and underscores, at most 128 characters.
fn is_app_bundle_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
}

/// Rejects too many apps or a malformed bundle identifier.
pub fn validate_app_modes(modes: &BTreeMap<String, AppMode>) -> Result<(), ()> {
    if modes.len() > MAX_APP_MODES || modes.keys().any(|key| !is_app_bundle_id(key)) {
        return Err(());
    }
    Ok(())
}

/// The focused app's display name and bundle id for the per-app list, or `None` without a valid
/// bundle id. The name falls back to the bundle id.
pub fn focused_app_label(context: Option<&FocusContext>) -> Option<(String, String)> {
    let context = context?;
    let bundle_id = context
        .bundle_id
        .as_deref()
        .filter(|id| is_app_bundle_id(id))?;
    let name = context
        .app_name
        .as_deref()
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .unwrap_or(bundle_id);
    Some((name.to_string(), bundle_id.to_string()))
}

/// The cleanup settings for the focused app: its own choice where it has one, the global value
/// otherwise. Bundle identifiers match without regard to case. Without a focused app (the
/// "Use the app you are typing in" switch is off, or nothing was captured) the globals stand.
pub fn resolve_app_mode(
    modes: &BTreeMap<String, AppMode>,
    context: Option<&FocusContext>,
    smart: bool,
    fix_grammar: bool,
) -> (bool, bool) {
    let Some(bundle_id) = context.and_then(|context| context.bundle_id.as_deref()) else {
        return (smart, fix_grammar);
    };
    let chosen = modes
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(bundle_id))
        .map(|(_, mode)| *mode)
        .unwrap_or_default();
    (
        chosen.smart.unwrap_or(smart),
        chosen.fix_grammar.unwrap_or(fix_grammar),
    )
}

/// Build the JSON body for `POST /api/dictate/cleanup`. Without smart mode the body
/// is exactly the original `{transcript, dictionary}`. Smart cleanup adds only the
/// app name, bundle id and field role; optional field text stays in the native layer.
pub fn cleanup_request_body(
    transcript: &str,
    dictionary: &std::collections::BTreeMap<String, String>,
    options: &CleanupOptions<'_>,
) -> serde_json::Value {
    let mut body = serde_json::json!({
        "transcript": transcript,
        "dictionary": dictionary,
    });
    if !options.smart {
        return body;
    }
    body["mode"] = "smart".into();
    if let Some(language) = options.language {
        body["language"] = language.into();
    }
    if let Some(context) = options.context {
        let mut object = serde_json::Map::new();
        for (key, value) in [
            ("app_name", &context.app_name),
            ("bundle_id", &context.bundle_id),
            ("field_role", &context.field_role),
        ] {
            if let Some(value) = value {
                object.insert(key.to_string(), value.clone().into());
            }
        }
        if !object.is_empty() {
            body["context"] = serde_json::Value::Object(object);
        }
    }
    body
}

pub const MAX_VOCABULARY_TERMS: usize = 256;
pub const MAX_VOCABULARY_TERM_CHARACTERS: usize = 64;
pub const MAX_PROMPT_CHARACTERS: usize = 600;
const MAX_APP_NAME_CHARACTERS: usize = 64;

fn sanitized_text(value: &str, limit: usize) -> String {
    let collapsed = value
        .chars()
        .map(|character| {
            if character.is_control() {
                ' '
            } else {
                character
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    collapsed.chars().take(limit).collect()
}

/// Validate the vocabulary a client sends for Whisper biasing. Terms must be
/// non-empty after trimming and within the same bounds as the dictionary.
pub fn validate_vocabulary_terms(terms: &[String]) -> Result<Vec<String>, String> {
    if terms.len() > MAX_VOCABULARY_TERMS {
        return Err("Vocabulary must contain at most 256 terms".into());
    }
    let mut accepted: Vec<String> = Vec::with_capacity(terms.len());
    for term in terms {
        if term.chars().count() > MAX_VOCABULARY_TERM_CHARACTERS {
            return Err("Vocabulary terms cannot exceed 64 characters".into());
        }
        let cleaned = sanitized_text(term, MAX_VOCABULARY_TERM_CHARACTERS);
        if cleaned.is_empty() {
            continue;
        }
        if !accepted
            .iter()
            .any(|existing| existing.to_lowercase() == cleaned.to_lowercase())
        {
            accepted.push(cleaned);
        }
    }
    Ok(accepted)
}

/// Build the Whisper `initial_prompt` from vocabulary terms and, when known,
/// the focused app's name. Returns `None` without terms, because an app name
/// alone gives the decoder nothing useful to bias toward.
pub fn build_initial_prompt(terms: &[String], app_name: Option<&str>) -> Option<String> {
    let mut prompt = String::new();
    if let Some(app) = app_name.map(|name| sanitized_text(name, MAX_APP_NAME_CHARACTERS)) {
        if !app.is_empty() && !terms.is_empty() {
            prompt.push_str(&app);
            prompt.push_str(". ");
        }
    }
    let prefix_length = prompt.chars().count();
    let mut listed: Vec<String> = Vec::new();
    for term in terms {
        let cleaned = sanitized_text(term, MAX_VOCABULARY_TERM_CHARACTERS);
        if cleaned.is_empty()
            || listed
                .iter()
                .any(|existing| existing.to_lowercase() == cleaned.to_lowercase())
        {
            continue;
        }
        let candidate_length = prefix_length
            + "Glossary: ".len()
            + listed
                .iter()
                .map(|item| item.chars().count() + 2)
                .sum::<usize>()
            + cleaned.chars().count()
            + 1;
        if candidate_length > MAX_PROMPT_CHARACTERS {
            break;
        }
        listed.push(cleaned);
    }
    if listed.is_empty() {
        return None;
    }
    prompt.push_str("Glossary: ");
    prompt.push_str(&listed.join(", "));
    prompt.push('.');
    Some(prompt)
}

const LLM_MIN_LENGTH_RATIO: f64 = 0.4;
const LLM_MAX_LENGTH_RATIO: f64 = 1.25;
const LLM_MIN_SHARED_PREFIX: usize = 4;

fn guard_words(text: &str) -> Vec<String> {
    text.split_whitespace()
        .map(|word| {
            word.chars()
                .filter(|character| character.is_alphanumeric())
                .flat_map(char::to_lowercase)
                .collect::<String>()
        })
        .filter(|word| !word.is_empty())
        .collect()
}

fn word_is_grounded(word: &str, source_words: &[String]) -> bool {
    source_words.iter().any(|source| {
        if source == word {
            return true;
        }
        let shared = source
            .chars()
            .zip(word.chars())
            .take_while(|(left, right)| left == right)
            .count();
        shared >= LLM_MIN_SHARED_PREFIX
    })
}

/// Accepts a model rewrite only when it provably adds nothing: it keeps a sane
/// length, uses no word the input lacks (casing, punctuation and inflection
/// aside) and never introduces or changes a digit sequence. Any rejection means
/// the caller keeps the deterministic rules result.
pub fn accept_llm_output(input: &str, output: &str) -> Result<String, &'static str> {
    let cleaned = output
        .trim()
        .trim_matches(|character| matches!(character, '"' | '\u{201C}' | '\u{201D}'))
        .trim();
    if cleaned.is_empty() {
        return Err("empty-output");
    }
    let input_length = input.trim().chars().count() as f64;
    let ratio = cleaned.chars().count() as f64 / input_length.max(1.0);
    if !(LLM_MIN_LENGTH_RATIO..=LLM_MAX_LENGTH_RATIO).contains(&ratio) {
        return Err("length-out-of-bounds");
    }
    let digit_runs = |text: &str| -> Vec<String> {
        text.split(|character: char| !character.is_ascii_digit())
            .filter(|run| !run.is_empty())
            .map(str::to_string)
            .collect()
    };
    let source_digits = digit_runs(input);
    if digit_runs(cleaned)
        .iter()
        .any(|run| !source_digits.contains(run))
    {
        return Err("changed-numbers");
    }
    let source_words = guard_words(input);
    if guard_words(cleaned)
        .iter()
        .any(|word| !word_is_grounded(word, &source_words))
    {
        return Err("added-words");
    }
    Ok(cleaned.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn focused(bundle_id: Option<&str>) -> FocusContext {
        FocusContext {
            bundle_id: bundle_id.map(str::to_string),
            ..FocusContext::default()
        }
    }

    fn modes(entries: &[(&str, Option<bool>, Option<bool>)]) -> BTreeMap<String, AppMode> {
        entries
            .iter()
            .map(|(id, smart, grammar)| {
                (
                    id.to_string(),
                    AppMode {
                        smart: *smart,
                        fix_grammar: *grammar,
                    },
                )
            })
            .collect()
    }

    #[test]
    fn an_app_choice_wins_and_default_follows_the_global_switches() {
        let table = modes(&[
            ("com.apple.mail", Some(true), Some(true)),
            ("com.apple.Terminal", Some(false), None),
        ]);
        let mail = focused(Some("com.apple.mail"));
        let terminal = focused(Some("com.apple.Terminal"));
        let slack = focused(Some("com.tinyspeck.slackmacgap"));
        assert_eq!(
            resolve_app_mode(&table, Some(&mail), false, false),
            (true, true)
        );
        assert_eq!(
            resolve_app_mode(&table, Some(&terminal), true, true),
            (false, true)
        );
        assert_eq!(
            resolve_app_mode(&table, Some(&slack), true, false),
            (true, false)
        );
    }

    #[test]
    fn the_focused_app_label_needs_a_valid_bundle_id_and_falls_back_to_it_for_the_name() {
        let named = FocusContext {
            app_name: Some(" Mail ".into()),
            bundle_id: Some("com.apple.mail".into()),
            ..FocusContext::default()
        };
        assert_eq!(
            focused_app_label(Some(&named)),
            Some(("Mail".into(), "com.apple.mail".into()))
        );
        let unnamed = focused(Some("com.apple.Terminal"));
        assert_eq!(
            focused_app_label(Some(&unnamed)),
            Some(("com.apple.Terminal".into(), "com.apple.Terminal".into()))
        );
        assert_eq!(focused_app_label(Some(&focused(Some("bad id")))), None);
        assert_eq!(focused_app_label(Some(&focused(None))), None);
        assert_eq!(focused_app_label(None), None);
    }

    #[test]
    fn bundle_ids_match_without_regard_to_case() {
        let table = modes(&[("COM.APPLE.MAIL", Some(false), None)]);
        let mail = focused(Some("com.apple.Mail"));
        assert_eq!(
            resolve_app_mode(&table, Some(&mail), true, true),
            (false, true)
        );
    }

    #[test]
    fn no_focused_app_or_no_bundle_id_keeps_the_global_switches() {
        let table = modes(&[("com.apple.mail", Some(false), Some(false))]);
        assert_eq!(resolve_app_mode(&table, None, true, true), (true, true));
        assert_eq!(
            resolve_app_mode(&table, Some(&focused(None)), true, false),
            (true, false)
        );
        assert_eq!(
            resolve_app_mode(&BTreeMap::new(), Some(&focused(Some("a.b"))), false, true),
            (false, true)
        );
    }

    #[test]
    fn app_modes_are_bounded_and_need_valid_bundle_ids() {
        assert!(validate_app_modes(&modes(&[("com.apple.mail", None, None)])).is_ok());
        assert!(validate_app_modes(&BTreeMap::new()).is_ok());
        for bad in ["", "has space", "bad/slash", "emoji😀", &"a".repeat(129)] {
            assert!(
                validate_app_modes(&modes(&[(bad, None, None)])).is_err(),
                "{bad:?}"
            );
        }
        let many: BTreeMap<String, AppMode> = (0..=MAX_APP_MODES)
            .map(|index| (format!("app.n{index}"), AppMode::default()))
            .collect();
        assert!(validate_app_modes(&many).is_err());
        let exactly: BTreeMap<String, AppMode> = (0..MAX_APP_MODES)
            .map(|index| (format!("app.n{index}"), AppMode::default()))
            .collect();
        assert!(validate_app_modes(&exactly).is_ok());
    }

    #[test]
    fn app_modes_deserialize_from_the_page_json_with_missing_fields() {
        let parsed: BTreeMap<String, AppMode> = serde_json::from_str(
            r#"{"com.apple.mail":{"smart":true,"fixGrammar":false},"x.y":{}}"#,
        )
        .unwrap();
        assert_eq!(
            parsed["com.apple.mail"],
            AppMode {
                smart: Some(true),
                fix_grammar: Some(false)
            }
        );
        assert_eq!(parsed["x.y"], AppMode::default());
    }

    fn terms(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| value.to_string()).collect()
    }

    #[test]
    fn prompt_needs_vocabulary_and_lists_terms_once_without_case_duplicates() {
        assert_eq!(build_initial_prompt(&[], Some("Slack")), None);
        assert_eq!(build_initial_prompt(&terms(&["  ", ""]), None), None);
        assert_eq!(
            build_initial_prompt(&terms(&["OfficeKit", "officekit", "Sedhu"]), None),
            Some("Glossary: OfficeKit, Sedhu.".to_string())
        );
    }

    #[test]
    fn prompt_prefixes_a_sanitized_app_name_and_ignores_blank_names() {
        assert_eq!(
            build_initial_prompt(&terms(&["JSON"]), Some("  Slack\n")),
            Some("Slack. Glossary: JSON.".to_string())
        );
        assert_eq!(
            build_initial_prompt(&terms(&["JSON"]), Some(" \t ")),
            Some("Glossary: JSON.".to_string())
        );
        let long_name = "A".repeat(200);
        let prompt = build_initial_prompt(&terms(&["JSON"]), Some(&long_name)).unwrap();
        assert!(prompt.starts_with(&format!("{}. ", "A".repeat(MAX_APP_NAME_CHARACTERS))));
    }

    #[test]
    fn prompt_strips_control_characters_and_collapses_whitespace() {
        let prompt = build_initial_prompt(&terms(&["Open\u{0}Kit\n  Pro"]), None).unwrap();
        assert_eq!(prompt, "Glossary: Open Kit Pro.");
        assert!(!prompt.chars().any(char::is_control));
    }

    #[test]
    fn prompt_stays_inside_the_budget_and_cuts_at_a_whole_term() {
        let many: Vec<String> = (0..200)
            .map(|index| format!("term{index:03}-{}", "x".repeat(20)))
            .collect();
        let prompt = build_initial_prompt(&many, Some("Mail")).unwrap();
        assert!(prompt.chars().count() <= MAX_PROMPT_CHARACTERS);
        assert!(prompt.ends_with('.'));
        let listed = prompt
            .trim_start_matches("Mail. Glossary: ")
            .trim_end_matches('.');
        assert!(listed
            .split(", ")
            .all(|item| item.len() == "term000-".len() + 20));
        assert!(listed.starts_with("term000-"));
    }

    #[test]
    fn vocabulary_validation_bounds_count_and_length_and_drops_blanks_and_duplicates() {
        assert_eq!(
            validate_vocabulary_terms(&terms(&["Sedhu", " sedhu ", "", "OfficeKit"])).unwrap(),
            terms(&["Sedhu", "OfficeKit"])
        );
        assert!(
            validate_vocabulary_terms(&vec!["a".to_string(); MAX_VOCABULARY_TERMS + 1]).is_err()
        );
        assert!(validate_vocabulary_terms(&terms(&[
            &"y".repeat(MAX_VOCABULARY_TERM_CHARACTERS + 1)
        ]))
        .is_err());
        assert!(validate_vocabulary_terms(&vec!["a".to_string(); MAX_VOCABULARY_TERMS]).is_ok());
    }

    #[test]
    fn focus_context_defaults_allow_the_app_but_never_field_text() {
        let options = ContextOptions::default();
        assert!(options.app_context && !options.field_text && options.wants_context());
        assert!(!ContextOptions {
            app_context: false,
            field_text: false
        }
        .wants_context());
    }

    #[test]
    fn focus_context_parsing_bounds_and_cleans_every_field() {
        let long = "N".repeat(500);
        let payload = format!(
            r#"{{"app_name":"Mail\u0000 App","bundle_id":"{long}","field_role":"AXTextArea","field_text":"line one\nline\ttwo {}"}}"#,
            "z".repeat(2_000)
        );
        let context = parse_focus_context(payload.as_bytes()).unwrap();
        assert_eq!(context.app_name.as_deref(), Some("Mail App"));
        assert_eq!(
            context.bundle_id.as_ref().unwrap().chars().count(),
            MAX_CONTEXT_LABEL_CHARACTERS
        );
        assert_eq!(context.field_role.as_deref(), Some("AXTextArea"));
        let text = context.field_text.unwrap();
        assert!(text.starts_with("line one\nline two"));
        assert_eq!(text.chars().count(), MAX_FIELD_TEXT_CHARACTERS);
    }

    #[test]
    fn focus_context_parsing_treats_malformed_or_empty_payloads_as_no_context() {
        for payload in [
            "",
            "not json",
            "[]",
            "{}",
            r#"{"app_name":"  "}"#,
            r#"{"app_name":5}"#,
        ] {
            assert_eq!(parse_focus_context(payload.as_bytes()), None, "{payload}");
        }
        assert_eq!(parse_focus_context(&[0xff, 0xfe]), None);
    }

    #[test]
    fn focus_context_filtering_honours_each_option() {
        let full = FocusContext {
            app_name: Some("Slack".into()),
            bundle_id: Some("com.slack".into()),
            field_role: Some("AXTextArea".into()),
            field_text: Some("draft".into()),
        };
        let app_only = full
            .clone()
            .filtered(ContextOptions {
                app_context: true,
                field_text: false,
            })
            .unwrap();
        assert_eq!(app_only.app_name.as_deref(), Some("Slack"));
        assert_eq!(app_only.field_text, None);
        let text_only = full
            .clone()
            .filtered(ContextOptions {
                app_context: false,
                field_text: true,
            })
            .unwrap();
        assert_eq!(text_only.app_name, None);
        assert_eq!(text_only.field_text.as_deref(), Some("draft"));
        assert_eq!(
            full.filtered(ContextOptions {
                app_context: false,
                field_text: false
            }),
            None
        );
    }

    #[test]
    fn focus_context_debug_output_never_prints_field_text() {
        let context = FocusContext {
            app_name: Some("Notes".into()),
            field_text: Some("my private sentence".into()),
            ..FocusContext::default()
        };
        let printed = format!("{context:?}");
        assert!(printed.contains("Notes") && printed.contains("<redacted>"));
        assert!(!printed.contains("private"));
    }

    #[test]
    fn language_hints_accept_short_alphabetic_tags_only() {
        assert_eq!(validate_language_hint("en"), Some("en".into()));
        assert_eq!(validate_language_hint(" PT-br "), Some("pt-br".into()));
        for invalid in ["", "e", "english-us", "e1", "-en", "en_US", "en us", "ée"] {
            assert_eq!(validate_language_hint(invalid), None, "{invalid}");
        }
    }

    #[test]
    fn committed_pieces_keep_order_and_skip_empty_segments() {
        let mut state = CommitState::default();
        state.reset(3);
        assert!(state.commit(3, 0, 100, " so I think "));
        assert!(state.commit(3, 100, 200, "   "));
        assert!(state.commit(3, 200, 300, "we ship"));
        assert!(!state.commit(3, 50, 400, "out of order"));
        assert_eq!(state.pieces(), vec!["so I think", "we ship"]);
        assert_eq!(state.committed_text(), "so I think we ship");
    }

    #[test]
    fn a_decode_with_far_fewer_words_than_the_speech_holds_is_not_plausible() {
        // 37.5 s of speech decoded to 13 words, the reported case.
        let long = speech(1875);
        assert!(!decode_is_plausible(&long, &"word ".repeat(13)));
        assert!(decode_is_plausible(&long, &"word ".repeat(90)));
        // A segment with over a second of speech that decoded to nothing lost it all.
        let segment = speech(75);
        assert!(!decode_is_plausible(&segment, ""));
        assert!(!decode_is_plausible(&segment, "   "));
        assert!(decode_is_plausible(&segment, "so I think we ship"));
    }

    #[test]
    fn plausibility_counts_speech_not_silence() {
        let padded = concat(&[silence(500), speech(100), silence(500)]);
        assert!(decode_is_plausible(&padded, "five whole words were spoken"));
        assert!(
            decode_is_plausible(&silence(500), ""),
            "silence needs no words"
        );
        assert!(decode_is_plausible(&[], ""));
    }

    #[test]
    fn a_rejected_segment_waits_for_more_audio_before_the_next_try() {
        let mut state = CommitState::default();
        state.reset(5);
        assert_eq!(state.next_try_at(), 0);
        state.reject(5, 48_000);
        assert_eq!(state.committed_end(), 0, "the marker does not move");
        assert!(state.next_try_at() > 48_000, "no retry on the same audio");
        state.reject(4, 90_000);
        assert!(
            state.next_try_at() <= 48_000 + COMMIT_MIN_PENDING_SAMPLES,
            "stale generation ignored"
        );
        state.reset(6);
        assert_eq!(state.next_try_at(), 0);
    }

    #[test]
    fn capture_stats_tell_silence_from_speech_without_keeping_audio() {
        let rate = DICTATION_SAMPLE_RATE as usize;
        let silence = vec![0.0_f32; rate];
        let quiet = capture_stats(&silence);
        assert_eq!(quiet.recorded_seconds, 1.0);
        assert!(!quiet.had_speech);
        assert_eq!(quiet.speech_seconds, 0.0);
        assert_eq!(quiet.level_db, None);

        let mut clip = vec![0.0_f32; rate * 2];
        for (index, sample) in clip[rate / 2..rate].iter_mut().enumerate() {
            *sample = if index % 2 == 0 { 0.3 } else { -0.3 };
        }
        let loud = capture_stats(&clip);
        assert_eq!(loud.recorded_seconds, 2.0);
        assert!(loud.had_speech);
        assert!(loud.speech_seconds >= 0.5 && loud.speech_seconds < 1.5);
        assert_eq!(loud.level_db, Some(-10.0));
        assert_eq!(capture_stats(&[]).recorded_seconds, 0.0);
    }

    #[test]
    fn rules_cleanup_body_is_exactly_the_original_request() {
        let dictionary = std::collections::BTreeMap::from([("a".to_string(), "B".to_string())]);
        let context = FocusContext {
            app_name: Some("Slack".into()),
            field_text: Some("secret draft".into()),
            ..FocusContext::default()
        };
        let body = cleanup_request_body(
            "hello",
            &dictionary,
            &CleanupOptions {
                smart: false,
                language: Some("en"),
                context: Some(&context),
            },
        );
        let keys: Vec<&String> = body.as_object().unwrap().keys().collect();
        assert_eq!(keys, ["dictionary", "transcript"]);
        assert!(!body.to_string().contains("secret"));
    }

    #[test]
    fn field_text_never_goes_into_the_loopback_cleanup_request() {
        let context = FocusContext {
            app_name: Some("Mail".into()),
            field_text: Some("private draft text".into()),
            ..FocusContext::default()
        };
        let body = cleanup_request_body(
            "hello",
            &std::collections::BTreeMap::new(),
            &CleanupOptions {
                smart: true,
                language: None,
                context: Some(&context),
            },
        );
        let serialized = body.to_string();
        assert!(!serialized.contains("private draft text"));
        assert!(!serialized.contains("field_text"));
    }

    #[test]
    fn smart_cleanup_body_carries_mode_language_and_only_present_context() {
        let dictionary = std::collections::BTreeMap::new();
        let context = FocusContext {
            app_name: Some("Slack".into()),
            field_role: Some("AXTextArea".into()),
            ..FocusContext::default()
        };
        let body = cleanup_request_body(
            "hello",
            &dictionary,
            &CleanupOptions {
                smart: true,
                language: Some("en"),
                context: Some(&context),
            },
        );
        assert_eq!(body["mode"], "smart");
        assert_eq!(body["language"], "en");
        assert_eq!(
            body["context"],
            serde_json::json!({"app_name": "Slack", "field_role": "AXTextArea"})
        );
        let bare = cleanup_request_body(
            "hello",
            &dictionary,
            &CleanupOptions {
                smart: true,
                ..CleanupOptions::default()
            },
        );
        assert_eq!(bare["mode"], "smart");
        assert!(bare.get("language").is_none() && bare.get("context").is_none());
        let empty = FocusContext::default();
        let without = cleanup_request_body(
            "hello",
            &dictionary,
            &CleanupOptions {
                smart: true,
                language: None,
                context: Some(&empty),
            },
        );
        assert!(without.get("context").is_none());
    }

    #[test]
    fn vocabulary_errors_never_echo_the_submitted_terms() {
        let secret = "x".repeat(MAX_VOCABULARY_TERM_CHARACTERS + 1);
        let error = validate_vocabulary_terms(&terms(&[&secret])).unwrap_err();
        assert!(!error.contains(&secret));
    }

    fn silence(frames: usize) -> Vec<f32> {
        vec![0.0; frames * FRAME_SAMPLES]
    }

    fn noise(frames: usize, amplitude: f32) -> Vec<f32> {
        let mut state = 0x2545_f491_u32;
        (0..frames * FRAME_SAMPLES)
            .map(|_| {
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                ((state >> 8) as f32 / (1 << 24) as f32 - 0.5) * 2.0 * amplitude
            })
            .collect()
    }

    fn speech(frames: usize) -> Vec<f32> {
        (0..frames * FRAME_SAMPLES)
            .map(|index| 0.2 * (index as f32 * 0.07).sin())
            .collect()
    }

    fn concat(parts: &[Vec<f32>]) -> Vec<f32> {
        parts.iter().flatten().copied().collect()
    }

    #[test]
    fn empty_and_all_silence_have_no_speech() {
        assert_eq!(
            trim_silence(&[]),
            TrimResult {
                range: 0..0,
                had_speech: false
            }
        );
        let clip = silence(100);
        assert_eq!(
            trim_silence(&clip),
            TrimResult {
                range: 0..0,
                had_speech: false
            }
        );
    }

    #[test]
    fn steady_background_noise_is_not_speech() {
        let clip = noise(150, 0.01);
        assert!(!trim_silence(&clip).had_speech);
    }

    #[test]
    fn a_single_click_shorter_than_the_minimum_run_is_not_speech() {
        let clip = concat(&[silence(40), speech(2), silence(40)]);
        assert!(!trim_silence(&clip).had_speech);
    }

    #[test]
    fn leading_and_trailing_silence_is_trimmed_with_padding() {
        let clip = concat(&[silence(100), speech(50), silence(100)]);
        let result = trim_silence(&clip);
        assert!(result.had_speech);
        assert_eq!(result.range.start, (100 - PADDING_FRAMES) * FRAME_SAMPLES);
        assert_eq!(result.range.end, (150 + PADDING_FRAMES) * FRAME_SAMPLES);
        assert!(result.range.len() < clip.len());
    }

    #[test]
    fn speech_at_the_clip_edges_is_not_clipped() {
        let clip = speech(30);
        let result = trim_silence(&clip);
        assert!(result.had_speech);
        assert_eq!(result.range, 0..clip.len());
    }

    #[test]
    fn mostly_speech_with_short_pauses_is_still_detected() {
        let clip = concat(&[speech(80), silence(4), speech(80), silence(4), speech(80)]);
        let result = trim_silence(&clip);
        assert!(result.had_speech);
        assert_eq!(result.range, 0..clip.len());
    }

    #[test]
    fn silence_between_two_speech_runs_is_kept() {
        let clip = concat(&[
            silence(60),
            speech(20),
            silence(80),
            speech(20),
            silence(60),
        ]);
        let result = trim_silence(&clip);
        assert!(result.had_speech);
        assert_eq!(result.range.start, (60 - PADDING_FRAMES) * FRAME_SAMPLES);
        assert_eq!(result.range.end, (180 + PADDING_FRAMES) * FRAME_SAMPLES);
    }

    #[test]
    fn speech_over_a_noise_floor_is_found() {
        let mut clip = noise(150, 0.01);
        let talk = speech(40);
        for (offset, sample) in talk.iter().enumerate() {
            clip[60 * FRAME_SAMPLES + offset] += sample;
        }
        let result = trim_silence(&clip);
        assert!(result.had_speech);
        assert!(result.range.start <= 60 * FRAME_SAMPLES);
        assert!(result.range.end >= 100 * FRAME_SAMPLES);
        assert!(result.range.len() < clip.len());
    }

    #[test]
    fn commit_boundary_needs_enough_audio_a_real_pause_and_enough_speech() {
        assert_eq!(
            find_commit_boundary(&concat(&[speech(40), silence(40)])),
            None,
            "under 3 s waits"
        );
        assert_eq!(
            find_commit_boundary(&speech(200)),
            None,
            "continuous speech has no pause"
        );
        let short_gaps = concat(&[speech(60), silence(15), speech(60), silence(15), speech(60)]);
        assert_eq!(
            find_commit_boundary(&short_gaps),
            None,
            "300 ms gaps are speech rhythm"
        );
        let tiny_speech = concat(&[speech(30), silence(150)]);
        assert_eq!(
            find_commit_boundary(&tiny_speech),
            None,
            "under one second of speech is not committed"
        );
    }

    #[test]
    fn commit_boundary_cuts_inside_the_last_pause_never_through_speech() {
        let clip = concat(&[speech(80), silence(50), speech(60), silence(70)]);
        let boundary = find_commit_boundary(&clip).expect("pause after enough speech");
        let last_pause_start = (80 + 50 + 60) * FRAME_SAMPLES;
        assert!(boundary > last_pause_start && boundary < clip.len());
        assert_eq!(boundary, (190 + 35) * FRAME_SAMPLES);
        assert!(clip[boundary - FRAME_SAMPLES..boundary + FRAME_SAMPLES]
            .iter()
            .all(|sample| *sample == 0.0));

        let one_pause = concat(&[speech(80), silence(50), speech(60)]);
        let boundary = find_commit_boundary(&one_pause).expect("pause between two phrases");
        assert_eq!(boundary, (80 + 25) * FRAME_SAMPLES);
        assert!(
            one_pause[boundary..]
                .iter()
                .any(|sample| sample.abs() > 0.1),
            "the later phrase stays pending"
        );
    }

    #[test]
    fn commit_state_accepts_only_the_next_contiguous_segment_of_its_capture() {
        let mut state = CommitState::default();
        state.reset(7);
        assert!(!state.commit(6, 0, 100, "stale capture"));
        assert!(!state.commit(7, 50, 100, "gap before the segment"));
        assert!(!state.commit(7, 0, 0, "empty range"));
        assert!(state.commit(7, 0, 100, " First segment. "));
        assert!(!state.commit(7, 0, 200, "overlaps committed audio"));
        assert!(state.commit(7, 100, 250, "   "));
        assert!(state.commit(7, 250, 400, "Second segment."));
        assert_eq!(state.committed_end(), 400);
        assert_eq!(state.committed_text(), "First segment. Second segment.");
        assert_eq!(state.generation(), 7);
        state.reset(8);
        assert_eq!(
            (state.committed_end(), state.committed_text().as_str()),
            (0, "")
        );
        assert!(!state.commit(7, 0, 10, "old capture"));
    }

    #[test]
    fn committed_and_tail_text_join_without_blank_or_doubled_spaces() {
        assert_eq!(join_committed("", "tail only"), "tail only");
        assert_eq!(join_committed("done early", " "), "done early");
        assert_eq!(join_committed(" head ", " tail "), "head tail");
        assert_eq!(join_committed("", ""), "");
    }

    #[test]
    fn llm_output_that_only_removes_and_reformats_is_accepted() {
        assert_eq!(
            accept_llm_output(
                "send the report to maria by tomorrow",
                "Send the report to Maria by tomorrow."
            ),
            Ok("Send the report to Maria by tomorrow.".into())
        );
        assert_eq!(
            accept_llm_output(
                "lets talk about the budget",
                "\u{201C}Let\u{2019}s talk about the budget.\u{201D}"
            ),
            Ok("Let\u{2019}s talk about the budget.".into())
        );
        assert_eq!(
            accept_llm_output(
                "the meeting is at 4 pm in the main office",
                "The meeting is at 4 PM in the main office."
            ),
            Ok("The meeting is at 4 PM in the main office.".into())
        );
    }

    #[test]
    fn llm_output_with_new_words_numbers_or_bad_length_is_rejected() {
        let input = "ship it on friday at 4 pm";
        assert_eq!(accept_llm_output(input, ""), Err("empty-output"));
        assert_eq!(accept_llm_output(input, "  \"\"  "), Err("empty-output"));
        assert_eq!(
            accept_llm_output(input, "Ship."),
            Err("length-out-of-bounds")
        );
        assert_eq!(
            accept_llm_output(input, "Ship it on Friday at 4 pm and notify everyone."),
            Err("length-out-of-bounds")
        );
        assert_eq!(
            accept_llm_output(input, "Ship it on Friday at 4 pm now."),
            Err("added-words")
        );
        assert_eq!(
            accept_llm_output(input, "Sorry, cannot help it."),
            Err("added-words")
        );
        assert_eq!(
            accept_llm_output(input, "Ship it on Friday at 5 pm."),
            Err("changed-numbers")
        );
    }

    #[test]
    fn frame_energy_ignores_non_finite_samples() {
        let rms = frame_rms(&[f32::NAN, 0.5, f32::INFINITY, f32::NEG_INFINITY]);
        assert!(rms.is_finite());
        assert!((rms - (0.25_f32 / 4.0).sqrt()).abs() < 1e-6);
        assert_eq!(frame_rms(&[]), 0.0);
    }

    #[test]
    fn non_finite_samples_alone_never_count_as_speech() {
        let clip = vec![f32::NAN; FRAME_SAMPLES * 10];
        assert!(!trim_silence(&clip).had_speech);
        let clip = vec![f32::INFINITY; FRAME_SAMPLES * 10];
        assert!(!trim_silence(&clip).had_speech);
    }

    #[test]
    fn clips_without_contrast_are_judged_at_the_absolute_levels() {
        let steady = |level: f32| vec![level; FRAME_SAMPLES * 10];
        assert!(trim_silence(&steady(CLEAR_SPEECH_RMS * 1.01)).had_speech);
        assert!(!trim_silence(&steady(CLEAR_SPEECH_RMS * 0.99)).had_speech);
        let short = |level: f32| vec![level; FRAME_SAMPLES * 2];
        assert!(trim_silence(&short(ABSOLUTE_SPEECH_RMS * 1.01)).had_speech);
        assert!(!trim_silence(&short(ABSOLUTE_SPEECH_RMS * 0.99)).had_speech);
    }

    #[test]
    fn steady_loud_noise_is_kept_whole_so_the_engine_decides() {
        // A fan louder than CLEAR_SPEECH_RMS cannot be told from speech by energy alone.
        // The safe outcome is to decode everything, exactly as before trimming existed.
        let noise = vec![0.05_f32; FRAME_SAMPLES * 50];
        let result = trim_silence(&noise);
        assert!(result.had_speech);
        assert_eq!(result.range, 0..noise.len());
    }

    #[test]
    fn llm_length_ratio_boundaries_are_inclusive() {
        // Ten characters in: 0.4 allows 4 and 1.25 allows 12.
        let input = "aaaaaaaaaa";
        assert!(accept_llm_output(input, "aaaa").is_ok());
        assert_eq!(accept_llm_output(input, "aaa"), Err("length-out-of-bounds"));
        assert!(accept_llm_output(input, "aaaaaaaaaaaa").is_ok());
        assert_eq!(
            accept_llm_output(input, "aaaaaaaaaaaaa"),
            Err("length-out-of-bounds")
        );
    }

    #[test]
    fn llm_words_must_match_or_share_a_four_letter_stem() {
        let input = "we are meeting tomorrow";
        assert!(accept_llm_output(input, "We are meeting tomorrows").is_ok());
        assert!(accept_llm_output(input, "We are meeting tomorr").is_ok());
        // Only three letters in common is a different word.
        assert_eq!(
            accept_llm_output(input, "We are meeting tomato"),
            Err("added-words")
        );
        assert_eq!(
            accept_llm_output("ship it at 4 pm", "Ship it at 40 pm."),
            Err("changed-numbers")
        );
        assert_eq!(
            accept_llm_output("ship it at 4 pm", "Ship it at 4 pm."),
            Ok("Ship it at 4 pm.".into())
        );
    }

    #[test]
    fn very_short_clips_are_judged_by_peak_energy() {
        let loud: Vec<f32> = vec![0.2; FRAME_SAMPLES];
        let result = trim_silence(&loud);
        assert!(result.had_speech);
        assert_eq!(result.range, 0..loud.len());
        let quiet: Vec<f32> = vec![0.0; FRAME_SAMPLES];
        assert!(!trim_silence(&quiet).had_speech);
    }

    #[test]
    fn range_is_always_inside_the_input_and_non_finite_samples_are_ignored() {
        let mut clip = concat(&[silence(20), speech(20), silence(20)]);
        clip[3] = f32::NAN;
        clip[4] = f32::INFINITY;
        let result = trim_silence(&clip);
        assert!(result.range.start <= result.range.end);
        assert!(result.range.end <= clip.len());
        assert!(result.had_speech);
    }
}
