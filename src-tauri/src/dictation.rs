use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

const PARAKEET_MODEL_DIRECTORIES: [&str; 4] = [
    "Preprocessor.mlmodelc",
    "Encoder.mlmodelc",
    "Decoder.mlmodelc",
    "JointDecisionv3.mlmodelc",
];
const PARAKEET_VOCABULARY_FILE: &str = "parakeet_vocab.json";
const PARAKEET_V2_JOINT_MODEL: &str = "JointDecision.mlmodelc";
const PARAKEET_V3_JOINT_MODEL: &str = "JointDecisionv3.mlmodelc";
const QWEN3_MODEL_DIRECTORIES: [&str; 2] = [
    "qwen3_asr_audio_encoder_v2.mlmodelc",
    "qwen3_asr_decoder_stateful.mlmodelc",
];
const QWEN3_MODEL_FILES: [&str; 2] = ["qwen3_asr_embeddings.bin", "vocab.json"];
pub const DICTATION_SAMPLE_RATE: u64 = 16_000;
pub const MIN_DICTATION_SAMPLES: u64 = DICTATION_SAMPLE_RATE / 10;
pub const MAX_DICTATION_SAMPLES: u64 = DICTATION_SAMPLE_RATE * 60 * 5;
pub const DICTATION_PREVIEW_INTERVAL_SAMPLES: u64 = DICTATION_SAMPLE_RATE * 3 / 2;
pub const DICTATION_PREVIEW_OVERLAP_SAMPLES: u64 = DICTATION_SAMPLE_RATE / 3;
pub const QWEN3_MAX_AUDIO_SECONDS: u64 = 30;
const QWEN3_CHUNK_SECONDS: u64 = 25;
const QWEN3_CHUNK_OVERLAP_SECONDS: u64 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AudioInputError {
    Empty,
    TooShort,
    TooLong,
    IncompleteCopy,
    InvalidSample,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CaptureStartError {
    ModelNotReady,
    AlreadyActive,
    PermissionDenied,
    NoInputDevice,
    Unavailable,
}

pub fn capture_start_allowed(
    model_state: ModelState,
    engine_registered: bool,
    microphone_permission: MicrophonePermission,
    capture_active: bool,
) -> Result<(), CaptureStartError> {
    if !matches!(model_state, ModelState::Ready | ModelState::Installed) || !engine_registered {
        return Err(CaptureStartError::ModelNotReady);
    }
    if microphone_permission != MicrophonePermission::Granted {
        return Err(CaptureStartError::PermissionDenied);
    }
    if capture_active {
        return Err(CaptureStartError::AlreadyActive);
    }
    Ok(())
}

pub fn capture_start_error_from_code(code: i32) -> Option<CaptureStartError> {
    match code {
        0 => None,
        1 => Some(CaptureStartError::AlreadyActive),
        2 => Some(CaptureStartError::PermissionDenied),
        4 => Some(CaptureStartError::NoInputDevice),
        _ => Some(CaptureStartError::Unavailable),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CaptureStopError {
    NotActive,
    DeviceFailure,
    TooLong,
    NoSamples,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TranscriptValidationError {
    Empty,
    TooLong,
    InvalidDuration,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PasteTextError {
    Empty,
    TooLong,
    ContainsNull,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PasteNativeError {
    PermissionRequired,
    Unavailable,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DictionaryError {
    TooManyEntries,
    InvalidEntry,
    DuplicateSource,
}

pub fn validate_dictionary(dictionary: &BTreeMap<String, String>) -> Result<(), DictionaryError> {
    if dictionary.len() > 256 {
        return Err(DictionaryError::TooManyEntries);
    }
    let mut normalized_sources = std::collections::HashSet::with_capacity(dictionary.len());
    for (source, replacement) in dictionary {
        if source.trim().is_empty()
            || replacement.trim().is_empty()
            || source.chars().count() > 64
            || replacement.chars().count() > 64
            || source.chars().any(char::is_control)
            || replacement.chars().any(char::is_control)
        {
            return Err(DictionaryError::InvalidEntry);
        }
        if !normalized_sources.insert(source.to_lowercase()) {
            return Err(DictionaryError::DuplicateSource);
        }
    }
    Ok(())
}

pub fn validate_paste_text(text: &str) -> Result<(), PasteTextError> {
    if text.trim().is_empty() {
        return Err(PasteTextError::Empty);
    }
    if text.len() > 262_144 {
        return Err(PasteTextError::TooLong);
    }
    if text.contains('\0') {
        return Err(PasteTextError::ContainsNull);
    }
    Ok(())
}

pub fn paste_native_error_from_code(code: i32) -> Option<PasteNativeError> {
    match code {
        0 => None,
        1 => Some(PasteNativeError::PermissionRequired),
        _ => Some(PasteNativeError::Unavailable),
    }
}

pub fn validate_transcript(
    text: &str,
    duration_seconds: f64,
) -> Result<(), TranscriptValidationError> {
    if text.trim().is_empty() {
        return Err(TranscriptValidationError::Empty);
    }
    if text.len() > 262_144 {
        return Err(TranscriptValidationError::TooLong);
    }
    if !duration_seconds.is_finite() || duration_seconds <= 0.0 || duration_seconds > 300.0 {
        return Err(TranscriptValidationError::InvalidDuration);
    }
    Ok(())
}

pub fn capture_stop_error_from_code(code: i32) -> Option<CaptureStopError> {
    match code {
        0 => None,
        1 => Some(CaptureStopError::NotActive),
        4 => Some(CaptureStopError::TooLong),
        5 => Some(CaptureStopError::NoSamples),
        _ => Some(CaptureStopError::DeviceFailure),
    }
}

pub fn collect_audio_samples(
    sample_count: u64,
    mut copy_samples: impl FnMut(&mut [f32]) -> u64,
) -> Result<Vec<f32>, AudioInputError> {
    if sample_count == 0 {
        return Err(AudioInputError::Empty);
    }
    if sample_count > MAX_DICTATION_SAMPLES {
        return Err(AudioInputError::TooLong);
    }
    if sample_count < MIN_DICTATION_SAMPLES {
        return Err(AudioInputError::TooShort);
    }

    let sample_length = usize::try_from(sample_count).map_err(|_| AudioInputError::TooLong)?;
    let mut samples = vec![0.0; sample_length];
    if copy_samples(&mut samples) != sample_count {
        return Err(AudioInputError::IncompleteCopy);
    }
    if samples
        .iter()
        .any(|sample| !sample.is_finite() || !(-1.0..=1.0).contains(sample))
    {
        return Err(AudioInputError::InvalidSample);
    }
    Ok(samples)
}

pub fn qwen3_chunk_ranges(sample_count: u64) -> Vec<std::ops::Range<usize>> {
    let Ok(sample_count) = usize::try_from(sample_count) else {
        return Vec::new();
    };
    if sample_count == 0 {
        return Vec::new();
    }

    let maximum_samples = (QWEN3_MAX_AUDIO_SECONDS * DICTATION_SAMPLE_RATE) as usize;
    if sample_count <= maximum_samples {
        return vec![0..sample_count];
    }

    let chunk_samples = (QWEN3_CHUNK_SECONDS * DICTATION_SAMPLE_RATE) as usize;
    let overlap_samples = (QWEN3_CHUNK_OVERLAP_SECONDS * DICTATION_SAMPLE_RATE) as usize;
    let stride = chunk_samples - overlap_samples;
    let mut ranges = Vec::new();
    let mut start = 0_usize;
    loop {
        let end = start.saturating_add(chunk_samples).min(sample_count);
        ranges.push(start..end);
        if end == sample_count {
            return ranges;
        }
        start = start.saturating_add(stride);
    }
}

pub fn merge_qwen3_transcript_chunks(chunks: &[String]) -> String {
    let mut merged: Vec<String> = Vec::new();
    for chunk in chunks {
        let words: Vec<&str> = chunk.split_whitespace().collect();
        if words.is_empty() {
            continue;
        }
        let maximum_overlap = merged.len().min(words.len()).min(16);
        let overlap = (1..=maximum_overlap)
            .rev()
            .find(|length| {
                merged[merged.len() - length..]
                    .iter()
                    .zip(&words[..*length])
                    .all(|(left, right)| {
                        normalized_transcript_word(left) == normalized_transcript_word(right)
                    })
            })
            .unwrap_or(0);
        for index in 0..overlap {
            let merged_index = merged.len() - overlap + index;
            merged[merged_index] = words[index].to_string();
        }
        merged.extend(words.into_iter().skip(overlap).map(str::to_string));
    }
    merged.join(" ")
}

pub fn dictation_preview_range(
    processed_samples: u64,
    available_samples: u64,
) -> Option<std::ops::Range<usize>> {
    if available_samples.saturating_sub(processed_samples) < DICTATION_PREVIEW_INTERVAL_SAMPLES {
        return None;
    }
    let start = processed_samples.saturating_sub(DICTATION_PREVIEW_OVERLAP_SAMPLES);
    Some(start as usize..available_samples as usize)
}

pub fn transcribe_qwen3_chunks(
    samples: &[f32],
    mut transcribe: impl FnMut(&[f32]) -> Result<String, String>,
) -> Result<String, String> {
    let ranges = qwen3_chunk_ranges(samples.len() as u64);
    if ranges.is_empty() {
        return Err("Qwen3 received no audio samples".to_string());
    }
    let mut transcripts = Vec::with_capacity(ranges.len());
    for range in ranges {
        transcripts.push(transcribe(&samples[range])?);
    }
    Ok(merge_qwen3_transcript_chunks(&transcripts))
}

fn normalized_transcript_word(word: &str) -> String {
    word.chars()
        .filter(|character| character.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelState {
    Unsupported,
    NotInstalled,
    Installed,
    Preparing,
    Ready,
    Failed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DictationModel {
    ParakeetV2,
    ParakeetV3,
    Qwen3Asr,
    WhisperTiny,
    WhisperBase,
    WhisperSmall,
    WhisperMedium,
    WhisperLargeV3,
    WhisperLargeV3Turbo,
    WhisperLargeV3TurboQ5,
}

impl DictationModel {
    pub fn from_id(model_id: &str) -> Option<Self> {
        match model_id {
            "parakeet_v2" => Some(Self::ParakeetV2),
            "parakeet_v3" => Some(Self::ParakeetV3),
            "qwen3_asr" => Some(Self::Qwen3Asr),
            "whisper_tiny" => Some(Self::WhisperTiny),
            "whisper_base" => Some(Self::WhisperBase),
            "whisper_small" => Some(Self::WhisperSmall),
            "whisper_medium" => Some(Self::WhisperMedium),
            "whisper_large_v3" => Some(Self::WhisperLargeV3),
            "whisper_large_v3_turbo" => Some(Self::WhisperLargeV3Turbo),
            "whisper_large_v3_turbo_q5" => Some(Self::WhisperLargeV3TurboQ5),
            _ => None,
        }
    }

    pub const fn id(self) -> &'static str {
        match self {
            Self::ParakeetV2 => "parakeet_v2",
            Self::ParakeetV3 => "parakeet_v3",
            Self::Qwen3Asr => "qwen3_asr",
            Self::WhisperTiny => "whisper_tiny",
            Self::WhisperBase => "whisper_base",
            Self::WhisperSmall => "whisper_small",
            Self::WhisperMedium => "whisper_medium",
            Self::WhisperLargeV3 => "whisper_large_v3",
            Self::WhisperLargeV3Turbo => "whisper_large_v3_turbo",
            Self::WhisperLargeV3TurboQ5 => "whisper_large_v3_turbo_q5",
        }
    }

    pub const fn display_name(self) -> &'static str {
        match self {
            Self::ParakeetV2 => "Parakeet v2 · English",
            Self::ParakeetV3 => "Parakeet v3 · Multilingual",
            Self::Qwen3Asr => "Qwen3 ASR 0.6B · Multilingual",
            Self::WhisperTiny => "Whisper Tiny · Multilingual",
            Self::WhisperBase => "Whisper Base · Multilingual",
            Self::WhisperSmall => "Whisper Small · Multilingual",
            Self::WhisperMedium => "Whisper Medium · Multilingual",
            Self::WhisperLargeV3 => "Whisper Large v3 · Multilingual",
            Self::WhisperLargeV3Turbo => "Whisper Large v3 Turbo · Multilingual",
            Self::WhisperLargeV3TurboQ5 => "Whisper Large v3 Turbo Quantized · Multilingual",
        }
    }

    pub const fn supported_languages(self) -> &'static str {
        match self {
            Self::ParakeetV2 => "English speech",
            Self::ParakeetV3 => "25 European languages",
            Self::Qwen3Asr => "30 languages + 22 Chinese dialects · macOS 15+",
            Self::WhisperTiny
            | Self::WhisperBase
            | Self::WhisperSmall
            | Self::WhisperMedium
            | Self::WhisperLargeV3
            | Self::WhisperLargeV3Turbo
            | Self::WhisperLargeV3TurboQ5 => "99+ languages · Tamil included · Apple Silicon",
        }
    }

    pub const fn cache_slug(self) -> &'static str {
        match self {
            Self::ParakeetV2 => "parakeet-tdt-0.6b-v2",
            Self::ParakeetV3 => "parakeet-tdt-0.6b-v3",
            Self::Qwen3Asr => "qwen3-asr-0.6b/f32",
            Self::WhisperTiny => "whisper.cpp/tiny",
            Self::WhisperBase => "whisper.cpp/base",
            Self::WhisperSmall => "whisper.cpp/small",
            Self::WhisperMedium => "whisper.cpp/medium",
            Self::WhisperLargeV3 => "whisper.cpp/large-v3",
            Self::WhisperLargeV3Turbo => "whisper.cpp/large-v3-turbo",
            Self::WhisperLargeV3TurboQ5 => "whisper.cpp/large-v3-turbo-q5_0",
        }
    }

    pub fn cache_directory(self, home: &Path) -> PathBuf {
        let root = if self.whisper_variant().is_some() {
            home.join("Library")
                .join("Application Support")
                .join("OfficeKit")
                .join("Models")
        } else {
            home.join("Library")
                .join("Application Support")
                .join("FluidAudio")
                .join("Models")
        };
        root.join(self.cache_slug())
    }

    pub const fn joint_model(self) -> &'static str {
        match self {
            Self::ParakeetV2 => PARAKEET_V2_JOINT_MODEL,
            Self::ParakeetV3 => PARAKEET_V3_JOINT_MODEL,
            Self::Qwen3Asr => "",
            Self::WhisperTiny
            | Self::WhisperBase
            | Self::WhisperSmall
            | Self::WhisperMedium
            | Self::WhisperLargeV3
            | Self::WhisperLargeV3Turbo
            | Self::WhisperLargeV3TurboQ5 => "",
        }
    }

    pub const fn whisper_variant(self) -> Option<&'static str> {
        match self {
            Self::WhisperTiny => Some("tiny"),
            Self::WhisperBase => Some("base"),
            Self::WhisperSmall => Some("small"),
            Self::WhisperMedium => Some("medium"),
            Self::WhisperLargeV3 => Some("large-v3"),
            Self::WhisperLargeV3Turbo => Some("large-v3-turbo"),
            Self::WhisperLargeV3TurboQ5 => Some("large-v3-turbo-q5_0"),
            Self::ParakeetV2 | Self::ParakeetV3 | Self::Qwen3Asr => None,
        }
    }

    pub const fn whisper_filename(self) -> Option<&'static str> {
        match self {
            Self::WhisperTiny => Some("ggml-tiny.bin"),
            Self::WhisperBase => Some("ggml-base.bin"),
            Self::WhisperSmall => Some("ggml-small.bin"),
            Self::WhisperMedium => Some("ggml-medium.bin"),
            Self::WhisperLargeV3 => Some("ggml-large-v3.bin"),
            Self::WhisperLargeV3Turbo => Some("ggml-large-v3-turbo.bin"),
            Self::WhisperLargeV3TurboQ5 => Some("ggml-large-v3-turbo-q5_0.bin"),
            Self::ParakeetV2 | Self::ParakeetV3 | Self::Qwen3Asr => None,
        }
    }

    pub const fn whisper_file_size(self) -> Option<u64> {
        match self {
            Self::WhisperTiny => Some(77_691_713),
            Self::WhisperBase => Some(147_951_465),
            Self::WhisperSmall => Some(487_601_967),
            Self::WhisperMedium => Some(1_533_763_059),
            Self::WhisperLargeV3 => Some(3_095_033_483),
            Self::WhisperLargeV3Turbo => Some(1_624_555_275),
            Self::WhisperLargeV3TurboQ5 => Some(574_041_195),
            Self::ParakeetV2 | Self::ParakeetV3 | Self::Qwen3Asr => None,
        }
    }

    pub const fn whisper_sha256(self) -> Option<&'static str> {
        match self {
            Self::WhisperTiny => {
                Some("be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21")
            }
            Self::WhisperLargeV3TurboQ5 => {
                Some("394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2")
            }
            Self::WhisperBase => {
                Some("60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe")
            }
            Self::WhisperSmall => {
                Some("1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b")
            }
            Self::WhisperMedium => {
                Some("6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208")
            }
            Self::WhisperLargeV3 => {
                Some("64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2")
            }
            Self::WhisperLargeV3Turbo => {
                Some("1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69")
            }
            Self::ParakeetV2 | Self::ParakeetV3 | Self::Qwen3Asr => None,
        }
    }

    pub const fn whisper_supports_english_translation(self) -> bool {
        matches!(self, Self::WhisperMedium | Self::WhisperLargeV3)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PrepareDecision {
    Start,
    AlreadyPreparing,
    AlreadyReady,
    Unsupported,
}

pub fn model_switch_allowed(
    state: ModelState,
    capture_active: bool,
    shortcut_enabled: bool,
) -> bool {
    !capture_active && !shortcut_enabled && state != ModelState::Preparing
}

pub fn model_delete_allowed(
    is_selected: bool,
    state: ModelState,
    capture_active: bool,
    shortcut_enabled: bool,
    meeting_recording: bool,
) -> bool {
    !is_selected
        || (model_switch_allowed(state, capture_active, shortcut_enabled) && !meeting_recording)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MicrophonePermission {
    Granted,
    Undetermined,
    Denied,
    Unavailable,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AccessibilityPermission {
    Granted,
    Denied,
    Unavailable,
}

pub fn accessibility_permission_from_code(code: i32) -> AccessibilityPermission {
    match code {
        0 => AccessibilityPermission::Granted,
        1 => AccessibilityPermission::Denied,
        _ => AccessibilityPermission::Unavailable,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HotkeyMonitorStartError {
    AlreadyActive,
    PermissionRequired,
    Unavailable,
}

pub fn hotkey_monitor_start_error_from_code(code: i32) -> Option<HotkeyMonitorStartError> {
    match code {
        0 => None,
        1 => Some(HotkeyMonitorStartError::AlreadyActive),
        2 => Some(HotkeyMonitorStartError::PermissionRequired),
        _ => Some(HotkeyMonitorStartError::Unavailable),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HotkeyState {
    Disabled,
    Ready,
    Recording,
    Processing,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DictationHotkeyKey {
    Fn,
    LeftOption,
    RightOption,
    LeftControl,
    RightControl,
    LeftCommand,
    RightCommand,
    LeftShift,
    RightShift,
    Custom,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DictationCustomHotkey {
    pub key_code: u16,
    pub modifier_mask: u8,
    pub label: String,
}

const SUPPORTED_CUSTOM_HOTKEY_KEY_CODES: &[u16] = &[
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
    27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
    51, 53, 64, 79, 80, 90, 96, 97, 98, 99, 100, 101, 103, 105, 106, 107, 109, 111, 113, 115, 116,
    117, 118, 119, 120, 121, 122, 123, 124, 125, 126,
];

pub fn validate_custom_hotkey(
    key_code: u16,
    modifier_mask: u8,
    label: String,
) -> Result<DictationCustomHotkey, &'static str> {
    const SAFE_STANDALONE_FUNCTION_KEYS: [u16; 8] = [105, 107, 113, 106, 64, 79, 80, 90];
    if !SUPPORTED_CUSTOM_HOTKEY_KEY_CODES.contains(&key_code) || modifier_mask & !0b1111 != 0 {
        return Err("Choose a supported Mac key and modifier combination.");
    }
    if label.is_empty() || label.chars().count() > 48 || label.chars().any(char::is_control) {
        return Err("Shortcut label is invalid.");
    }
    if modifier_mask == 0 && !SAFE_STANDALONE_FUNCTION_KEYS.contains(&key_code) {
        return Err("Use a modifier with this key, or choose F13 through F20 by itself.");
    }
    let command = modifier_mask & 0b1000 != 0;
    let option = modifier_mask & 0b0010 != 0;
    let control = modifier_mask & 0b0001 != 0;
    if (command && [12, 13, 48, 49].contains(&key_code))
        || (command && option && key_code == 53)
        || (control && [123, 124, 125, 126].contains(&key_code))
    {
        return Err("That key combination is reserved by macOS.");
    }
    Ok(DictationCustomHotkey {
        key_code,
        modifier_mask,
        label,
    })
}

/// Validates a global shortcut that may use Control with the arrow keys together with other
/// modifiers (Mission Control owns Control plus an arrow on its own).
pub fn validate_global_shortcut(key_code: u16, modifier_mask: u8) -> Result<(), &'static str> {
    const SAFE_STANDALONE_FUNCTION_KEYS: [u16; 8] = [105, 107, 113, 106, 64, 79, 80, 90];
    if !SUPPORTED_CUSTOM_HOTKEY_KEY_CODES.contains(&key_code) || modifier_mask & !0b1111 != 0 {
        return Err("Choose a supported Mac key and modifier combination.");
    }
    if modifier_mask == 0 && !SAFE_STANDALONE_FUNCTION_KEYS.contains(&key_code) {
        return Err("Use a modifier with this key, or choose F13 through F20 by itself.");
    }
    let command = modifier_mask & 0b1000 != 0;
    let option = modifier_mask & 0b0010 != 0;
    let arrow = [123, 124, 125, 126].contains(&key_code);
    if (command && [12, 13, 48, 49].contains(&key_code))
        || (command && option && key_code == 53)
        || (modifier_mask == 0b0001 && arrow)
    {
        return Err("That key combination is reserved by macOS.");
    }
    Ok(())
}

impl Default for DictationHotkeyKey {
    fn default() -> Self {
        Self::LeftOption
    }
}

impl DictationHotkeyKey {
    pub fn native_id(self) -> i32 {
        match self {
            Self::Fn => 0,
            Self::LeftOption => 1,
            Self::RightOption => 2,
            Self::LeftControl => 3,
            Self::RightControl => 4,
            Self::LeftCommand => 5,
            Self::RightCommand => 6,
            Self::LeftShift => 7,
            Self::RightShift => 8,
            Self::Custom => 9,
        }
    }

    pub fn display_name(self) -> &'static str {
        match self {
            Self::Fn => "Fn",
            Self::LeftOption => "Left Option",
            Self::RightOption => "Right Option",
            Self::LeftControl => "Left Control",
            Self::RightControl => "Right Control",
            Self::LeftCommand => "Left Command",
            Self::RightCommand => "Right Command",
            Self::LeftShift => "Left Shift",
            Self::RightShift => "Right Shift",
            Self::Custom => "Custom shortcut",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HotkeyEvent {
    Enable,
    Disable,
    KeyDown,
    KeyUp,
    CaptureFailed,
    TranscriptionFinished,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HotkeyAction {
    None,
    StartCapture,
    StopAndTranscribe,
    StopCaptureAndMonitor,
    StopMonitor,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HotkeyTransition {
    pub state: HotkeyState,
    pub action: HotkeyAction,
}

pub fn transition_hotkey(state: HotkeyState, event: HotkeyEvent) -> HotkeyTransition {
    use HotkeyAction::{None, StartCapture, StopAndTranscribe, StopCaptureAndMonitor, StopMonitor};
    use HotkeyEvent::{CaptureFailed, Disable, Enable, KeyDown, KeyUp, TranscriptionFinished};
    use HotkeyState::{Disabled, Processing, Ready, Recording};

    let (next_state, action) = match (state, event) {
        (Disabled, Enable) => (Ready, None),
        (Ready, Disable) | (Processing, Disable) => (Disabled, StopMonitor),
        (Recording, Disable) => (Disabled, StopCaptureAndMonitor),
        (Ready, KeyDown) => (Recording, StartCapture),
        (Recording, KeyUp) => (Processing, StopAndTranscribe),
        (Recording, CaptureFailed) => (Ready, None),
        (Processing, TranscriptionFinished) => (Ready, None),
        (current, _) => (current, None),
    };
    HotkeyTransition {
        state: next_state,
        action,
    }
}

pub fn microphone_permission_from_code(code: i32) -> MicrophonePermission {
    match code {
        0 => MicrophonePermission::Granted,
        1 => MicrophonePermission::Undetermined,
        2 => MicrophonePermission::Denied,
        _ => MicrophonePermission::Unavailable,
    }
}

pub fn model_cache_directory(home: &Path, model: DictationModel) -> PathBuf {
    model.cache_directory(home)
}

pub fn request_prepare(state: ModelState) -> PrepareDecision {
    match state {
        ModelState::Unsupported => PrepareDecision::Unsupported,
        ModelState::Preparing => PrepareDecision::AlreadyPreparing,
        ModelState::Ready => PrepareDecision::AlreadyReady,
        ModelState::NotInstalled | ModelState::Installed | ModelState::Failed => {
            PrepareDecision::Start
        }
    }
}

pub fn model_files_present_for(model_directory: &Path, model: DictationModel) -> bool {
    let Ok(root_metadata) = fs::symlink_metadata(model_directory) else {
        return false;
    };
    if root_metadata.file_type().is_symlink() || !root_metadata.is_dir() {
        return false;
    }

    if model.whisper_variant().is_some() {
        let Some(filename) = model.whisper_filename() else {
            return false;
        };
        let Ok(metadata) = fs::symlink_metadata(model_directory.join(filename)) else {
            return false;
        };
        return !metadata.file_type().is_symlink()
            && metadata.is_file()
            && model
                .whisper_file_size()
                .is_some_and(|expected| metadata.len() == expected);
    }

    if model == DictationModel::Qwen3Asr {
        for name in QWEN3_MODEL_DIRECTORIES {
            let Ok(metadata) = fs::symlink_metadata(model_directory.join(name)) else {
                return false;
            };
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return false;
            }
        }
        for name in QWEN3_MODEL_FILES {
            let Ok(metadata) = fs::symlink_metadata(model_directory.join(name)) else {
                return false;
            };
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return false;
            }
        }
        return true;
    }

    for name in [
        PARAKEET_MODEL_DIRECTORIES[0],
        PARAKEET_MODEL_DIRECTORIES[1],
        PARAKEET_MODEL_DIRECTORIES[2],
        model.joint_model(),
    ] {
        let Ok(metadata) = fs::symlink_metadata(model_directory.join(name)) else {
            return false;
        };
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return false;
        }
    }

    let Ok(vocabulary) = fs::symlink_metadata(model_directory.join(PARAKEET_VOCABULARY_FILE))
    else {
        return false;
    };
    !vocabulary.file_type().is_symlink() && vocabulary.is_file()
}

#[cfg(test)]
mod tests {
    use std::fs;
    #[cfg(unix)]
    use std::os::unix::fs::symlink;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::{
        accessibility_permission_from_code, capture_start_allowed, capture_start_error_from_code,
        capture_stop_error_from_code, collect_audio_samples, hotkey_monitor_start_error_from_code,
        microphone_permission_from_code, paste_native_error_from_code, transition_hotkey,
        validate_custom_hotkey, validate_dictionary, validate_paste_text, validate_transcript,
        AccessibilityPermission, AudioInputError, CaptureStartError, CaptureStopError,
        DictationHotkeyKey, DictionaryError, HotkeyAction, HotkeyEvent, HotkeyMonitorStartError,
        HotkeyState, MicrophonePermission, ModelState, PasteNativeError, PasteTextError,
        TranscriptValidationError, DICTATION_PREVIEW_INTERVAL_SAMPLES,
        SUPPORTED_CUSTOM_HOTKEY_KEY_CODES,
    };
    use super::{
        dictation_preview_range, merge_qwen3_transcript_chunks, model_cache_directory,
        model_delete_allowed, model_files_present_for, model_switch_allowed, qwen3_chunk_ranges,
        request_prepare, transcribe_qwen3_chunks, DictationModel, PrepareDecision,
        DICTATION_SAMPLE_RATE, QWEN3_MODEL_DIRECTORIES, QWEN3_MODEL_FILES,
    };

    struct Fixture(PathBuf);

    static FIXTURE_ID: AtomicU64 = AtomicU64::new(0);

    impl Fixture {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock after unix epoch")
                .as_nanos();
            let sequence = FIXTURE_ID.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "officekit-dictation-{}-{nonce}-{sequence}",
                std::process::id()
            ));
            fs::create_dir(&path).expect("create fixture root");
            Self(path)
        }

        fn complete_model(&self) {
            self.complete_model_for(DictationModel::ParakeetV3);
        }

        fn complete_model_for(&self, model: DictationModel) {
            if model == DictationModel::Qwen3Asr {
                for name in QWEN3_MODEL_DIRECTORIES {
                    fs::create_dir_all(self.0.join(name)).expect("create Qwen model directory");
                }
                for name in QWEN3_MODEL_FILES {
                    fs::write(self.0.join(name), b"{}").expect("write Qwen model metadata");
                }
                return;
            }
            for name in [
                "Preprocessor.mlmodelc",
                "Encoder.mlmodelc",
                "Decoder.mlmodelc",
                model.joint_model(),
            ] {
                fs::create_dir_all(self.0.join(name)).expect("create model directory");
            }
            fs::write(self.0.join("parakeet_vocab.json"), b"{}").expect("write model vocabulary");
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn model_is_present_only_when_every_required_artifact_exists() {
        let fixture = Fixture::new();
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));

        fixture.complete_model();

        assert!(model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));
        fs::remove_file(fixture.0.join("parakeet_vocab.json")).expect("remove vocabulary");
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));
    }

    #[test]
    fn qwen3_readiness_requires_all_coreml_and_vocabulary_artifacts() {
        let fixture = Fixture::new();
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::Qwen3Asr
        ));
        fixture.complete_model_for(DictationModel::Qwen3Asr);
        assert!(model_files_present_for(
            &fixture.0,
            DictationModel::Qwen3Asr
        ));
        fs::remove_file(fixture.0.join("qwen3_asr_embeddings.bin")).expect("remove embeddings");
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::Qwen3Asr
        ));
    }

    #[test]
    fn qwen3_chunks_long_audio_under_the_model_limit_with_a_one_second_overlap() {
        let one_chunk = qwen3_chunk_ranges(30 * DICTATION_SAMPLE_RATE);
        assert_eq!(one_chunk, vec![0..(30 * DICTATION_SAMPLE_RATE) as usize]);

        let two_chunks = qwen3_chunk_ranges(31 * DICTATION_SAMPLE_RATE);
        assert_eq!(two_chunks.len(), 2);
        assert_eq!(two_chunks[0], 0..(25 * DICTATION_SAMPLE_RATE) as usize);
        assert_eq!(
            two_chunks[1],
            (24 * DICTATION_SAMPLE_RATE) as usize..(31 * DICTATION_SAMPLE_RATE) as usize
        );

        let five_minutes = qwen3_chunk_ranges(300 * DICTATION_SAMPLE_RATE);
        assert!(five_minutes
            .iter()
            .all(|range| range.len() <= (25 * DICTATION_SAMPLE_RATE) as usize));
        assert_eq!(
            five_minutes.last().unwrap().end,
            (300 * DICTATION_SAMPLE_RATE) as usize
        );
    }

    #[test]
    fn qwen3_chunk_merge_removes_only_matching_overlap_words_and_skips_empty_chunks() {
        let chunks = vec![
            "We need the model to work.".to_string(),
            " the model to work, and stay local. ".to_string(),
            String::new(),
        ];
        assert_eq!(
            merge_qwen3_transcript_chunks(&chunks),
            "We need the model to work, and stay local."
        );
        assert_eq!(merge_qwen3_transcript_chunks(&[]), "");
    }

    #[test]
    fn dictation_preview_uses_short_overlapping_audio_windows_and_waits_for_enough_audio() {
        assert_eq!(
            dictation_preview_range(0, DICTATION_PREVIEW_INTERVAL_SAMPLES - 1),
            None
        );
        assert_eq!(
            dictation_preview_range(0, DICTATION_PREVIEW_INTERVAL_SAMPLES),
            Some(0..24_000)
        );
        assert_eq!(
            dictation_preview_range(24_000, 48_000),
            Some(18_667..48_000)
        );
        assert_eq!(dictation_preview_range(48_000, 48_100), None);
    }

    #[test]
    fn qwen3_transcription_calls_every_bounded_chunk_and_propagates_failures() {
        let samples = vec![0.0; (31 * DICTATION_SAMPLE_RATE) as usize];
        let mut observed_lengths = Vec::new();
        let result = transcribe_qwen3_chunks(&samples, |chunk| {
            observed_lengths.push(chunk.len());
            Ok(if observed_lengths.len() == 1 {
                "Local dictation is working".to_string()
            } else {
                "dictation is working today".to_string()
            })
        })
        .expect("transcribe both chunks");
        assert_eq!(observed_lengths.len(), 2);
        assert!(observed_lengths
            .iter()
            .all(|length| *length <= (25 * DICTATION_SAMPLE_RATE) as usize));
        assert_eq!(result, "Local dictation is working today");

        let mut attempts = 0;
        let failure = transcribe_qwen3_chunks(&samples, |_| {
            attempts += 1;
            Err("inference failed".to_string())
        });
        assert_eq!(attempts, 1);
        assert_eq!(failure, Err("inference failed".to_string()));
    }

    #[test]
    fn model_picker_only_accepts_supported_models_and_maps_language_labels() {
        assert_eq!(
            DictationModel::from_id("parakeet_v2"),
            Some(DictationModel::ParakeetV2)
        );
        assert_eq!(
            DictationModel::from_id("parakeet_v3"),
            Some(DictationModel::ParakeetV3)
        );
        assert_eq!(
            DictationModel::from_id("qwen3_asr"),
            Some(DictationModel::Qwen3Asr)
        );
        assert_eq!(
            DictationModel::Qwen3Asr.supported_languages(),
            "30 languages + 22 Chinese dialects · macOS 15+"
        );
        assert_eq!(DictationModel::from_id("whisper_large"), None);
        assert_eq!(
            DictationModel::from_id("whisper_medium"),
            Some(DictationModel::WhisperMedium)
        );
        assert_eq!(
            DictationModel::WhisperMedium.whisper_variant(),
            Some("medium")
        );
        assert!(DictationModel::WhisperMedium.whisper_supports_english_translation());
        assert!(!DictationModel::WhisperLargeV3Turbo.whisper_supports_english_translation());
        assert_eq!(
            DictationModel::ParakeetV2.supported_languages(),
            "English speech"
        );
        assert_eq!(
            DictationModel::ParakeetV3.supported_languages(),
            "25 European languages"
        );
    }

    #[test]
    fn model_switching_is_blocked_during_capture_shortcut_or_model_setup() {
        assert!(!model_switch_allowed(ModelState::Ready, true, false));
        assert!(!model_switch_allowed(ModelState::Ready, false, true));
        assert!(!model_switch_allowed(ModelState::Preparing, false, false));
        assert!(model_switch_allowed(ModelState::Ready, false, false));
        assert!(model_switch_allowed(ModelState::Failed, false, false));
    }

    #[test]
    fn deleting_an_unselected_model_does_not_require_disabling_dictation() {
        assert!(model_delete_allowed(
            false,
            ModelState::Ready,
            false,
            true,
            false
        ));
        assert!(model_delete_allowed(
            false,
            ModelState::Ready,
            true,
            true,
            true
        ));
        assert!(!model_delete_allowed(
            true,
            ModelState::Ready,
            false,
            true,
            false
        ));
    }

    #[test]
    fn v2_and_v3_readiness_require_their_own_joint_model() {
        let fixture = Fixture::new();
        fixture.complete_model_for(DictationModel::ParakeetV2);
        assert!(model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV2
        ));
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));
        fs::remove_dir(fixture.0.join(DictationModel::ParakeetV2.joint_model()))
            .expect("remove v2 joint model");
        fixture.complete_model_for(DictationModel::ParakeetV3);
        assert!(model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));
    }

    #[test]
    fn model_readiness_rejects_wrong_artifact_types() {
        let fixture = Fixture::new();
        fixture.complete_model();
        fs::remove_dir(fixture.0.join("Encoder.mlmodelc")).expect("remove encoder directory");
        fs::write(fixture.0.join("Encoder.mlmodelc"), b"not a model directory")
            .expect("replace encoder with a file");

        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));
    }

    #[test]
    fn installed_deferred_model_can_capture_before_weights_are_loaded() {
        assert_eq!(
            capture_start_allowed(
                ModelState::Installed,
                true,
                MicrophonePermission::Granted,
                false
            ),
            Ok(())
        );
        assert_eq!(
            capture_start_allowed(
                ModelState::Installed,
                false,
                MicrophonePermission::Granted,
                false
            ),
            Err(CaptureStartError::ModelNotReady)
        );
        assert_eq!(
            capture_start_allowed(
                ModelState::Installed,
                true,
                MicrophonePermission::Denied,
                false
            ),
            Err(CaptureStartError::PermissionDenied)
        );
    }

    #[test]
    fn every_whisper_model_has_a_checked_download() {
        let all = [
            DictationModel::WhisperTiny,
            DictationModel::WhisperBase,
            DictationModel::WhisperSmall,
            DictationModel::WhisperMedium,
            DictationModel::WhisperLargeV3,
            DictationModel::WhisperLargeV3Turbo,
            DictationModel::WhisperLargeV3TurboQ5,
        ];
        let mut ids = std::collections::HashSet::new();
        let mut files = std::collections::HashSet::new();
        for model in all {
            assert_eq!(DictationModel::from_id(model.id()), Some(model));
            assert!(ids.insert(model.id()), "duplicate id {}", model.id());
            let filename = model.whisper_filename().expect("a file name");
            assert!(filename.starts_with("ggml-") && filename.ends_with(".bin"));
            assert!(files.insert(filename), "duplicate file {filename}");
            let sha = model.whisper_sha256().expect("a pinned hash");
            assert_eq!(sha.len(), 64, "{filename}");
            assert!(
                sha.bytes().all(|byte| byte.is_ascii_hexdigit()),
                "{filename}"
            );
            assert!(model.whisper_file_size().expect("a size") > 50_000_000);
            assert!(model.cache_slug().starts_with("whisper.cpp/"));
        }
        assert_eq!(
            DictationModel::WhisperTiny.whisper_file_size(),
            Some(77_691_713)
        );
        assert_eq!(
            DictationModel::WhisperLargeV3TurboQ5.whisper_filename(),
            Some("ggml-large-v3-turbo-q5_0.bin")
        );
        assert!(!DictationModel::WhisperTiny.whisper_supports_english_translation());
        assert!(!DictationModel::WhisperLargeV3TurboQ5.whisper_supports_english_translation());
    }

    #[test]
    fn whisper_model_readiness_requires_a_complete_model_file() {
        let fixture = Fixture::new();
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::WhisperMedium
        ));
        let model_file = fixture.0.join("ggml-medium.bin");
        let file = fs::File::create(&model_file).expect("create model fixture");
        file.set_len(1_533_763_059).expect("size model fixture");
        assert!(model_files_present_for(
            &fixture.0,
            DictationModel::WhisperMedium
        ));
        fs::remove_file(&model_file).expect("remove model fixture");
        fs::write(&model_file, b"partial").expect("write partial model fixture");
        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::WhisperMedium
        ));
    }

    #[test]
    #[cfg(unix)]
    fn model_readiness_rejects_symlinked_artifacts_and_root() {
        let fixture = Fixture::new();
        fixture.complete_model();
        let encoder = fixture.0.join("Encoder.mlmodelc");
        fs::remove_dir(&encoder).expect("remove encoder directory");
        let target = fixture.0.join("encoder-target");
        fs::create_dir(&target).expect("create encoder target");
        symlink(&target, &encoder).expect("symlink encoder directory");

        assert!(!model_files_present_for(
            &fixture.0,
            DictationModel::ParakeetV3
        ));

        let alias = fixture.0.with_extension("alias");
        symlink(&fixture.0, &alias).expect("symlink model root");
        assert!(!model_files_present_for(&alias, DictationModel::ParakeetV3));
        fs::remove_file(alias).expect("remove root symlink");
    }

    #[test]
    fn model_prepare_is_idempotent_while_running_and_ready() {
        assert_eq!(
            request_prepare(ModelState::Preparing),
            PrepareDecision::AlreadyPreparing
        );
        assert_eq!(
            request_prepare(ModelState::Ready),
            PrepareDecision::AlreadyReady
        );
    }

    #[test]
    fn model_prepare_can_start_from_missing_installed_or_failed_states() {
        for state in [
            ModelState::NotInstalled,
            ModelState::Installed,
            ModelState::Failed,
        ] {
            assert_eq!(request_prepare(state), PrepareDecision::Start);
        }
    }

    #[test]
    fn unsupported_architecture_never_starts_a_model_download() {
        assert_eq!(
            request_prepare(ModelState::Unsupported),
            PrepareDecision::Unsupported
        );
    }

    #[test]
    fn model_cache_uses_the_fluid_audio_v3_application_support_location() {
        let home = PathBuf::from("/Users/test-user");

        assert_eq!(
            model_cache_directory(&home, DictationModel::ParakeetV3),
            PathBuf::from(
                "/Users/test-user/Library/Application Support/FluidAudio/Models/parakeet-tdt-0.6b-v3"
            )
        );
        assert_eq!(
            model_cache_directory(&home, DictationModel::ParakeetV2),
            PathBuf::from(
                "/Users/test-user/Library/Application Support/FluidAudio/Models/parakeet-tdt-0.6b-v2"
            )
        );
        assert_eq!(
            model_cache_directory(&home, DictationModel::Qwen3Asr),
            PathBuf::from(
                "/Users/test-user/Library/Application Support/FluidAudio/Models/qwen3-asr-0.6b/f32"
            )
        );
        assert_eq!(
            model_cache_directory(&home, DictationModel::WhisperMedium),
            PathBuf::from(
                "/Users/test-user/Library/Application Support/OfficeKit/Models/whisper.cpp/medium"
            )
        );
    }

    #[test]
    fn native_microphone_permission_codes_are_mapped_without_assuming_access() {
        assert_eq!(
            microphone_permission_from_code(0),
            MicrophonePermission::Granted
        );
        assert_eq!(
            microphone_permission_from_code(1),
            MicrophonePermission::Undetermined
        );
        assert_eq!(
            microphone_permission_from_code(2),
            MicrophonePermission::Denied
        );
        assert_eq!(
            microphone_permission_from_code(-1),
            MicrophonePermission::Unavailable
        );
        assert_eq!(
            microphone_permission_from_code(99),
            MicrophonePermission::Unavailable
        );
    }

    #[test]
    fn audio_samples_require_minimum_duration_and_are_copied_exactly() {
        assert_eq!(
            collect_audio_samples(1599, |_| panic!("short input must not be copied")),
            Err(AudioInputError::TooShort)
        );
        let samples = collect_audio_samples(1600, |output| {
            output.fill(0.25);
            output.len() as u64
        })
        .expect("minimum duration is accepted");
        assert_eq!(samples.len(), 1600);
        assert!(samples.iter().all(|sample| *sample == 0.25));
    }

    #[test]
    fn audio_samples_reject_empty_oversized_and_partial_native_copies() {
        assert_eq!(
            collect_audio_samples(0, |_| panic!("empty input must not be copied")),
            Err(AudioInputError::Empty)
        );
        assert_eq!(
            collect_audio_samples(4_800_001, |_| panic!("oversized input must not be copied")),
            Err(AudioInputError::TooLong)
        );
        assert_eq!(
            collect_audio_samples(1600, |_| 1599),
            Err(AudioInputError::IncompleteCopy)
        );
    }

    #[test]
    fn audio_samples_reject_non_finite_and_out_of_range_values() {
        for invalid in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY, -1.01, 1.01] {
            assert_eq!(
                collect_audio_samples(1600, |output| {
                    output.fill(0.0);
                    output[1599] = invalid;
                    output.len() as u64
                }),
                Err(AudioInputError::InvalidSample)
            );
        }
    }

    #[test]
    fn native_capture_start_codes_have_safe_typed_errors() {
        assert_eq!(capture_start_error_from_code(0), None);
        assert_eq!(
            capture_start_error_from_code(4),
            Some(CaptureStartError::NoInputDevice)
        );
        assert_eq!(
            capture_start_error_from_code(1),
            Some(CaptureStartError::AlreadyActive)
        );
        assert_eq!(
            capture_start_error_from_code(2),
            Some(CaptureStartError::PermissionDenied)
        );
        assert_eq!(
            capture_start_error_from_code(3),
            Some(CaptureStartError::Unavailable)
        );
        assert_eq!(
            capture_start_error_from_code(99),
            Some(CaptureStartError::Unavailable)
        );
    }

    #[test]
    fn native_capture_stop_codes_cover_empty_short_long_and_device_failures() {
        assert_eq!(capture_stop_error_from_code(0), None);
        assert_eq!(
            capture_stop_error_from_code(1),
            Some(CaptureStopError::NotActive)
        );
        assert_eq!(
            capture_stop_error_from_code(3),
            Some(CaptureStopError::DeviceFailure)
        );
        assert_eq!(
            capture_stop_error_from_code(4),
            Some(CaptureStopError::TooLong)
        );
        assert_eq!(
            capture_stop_error_from_code(5),
            Some(CaptureStopError::NoSamples)
        );
        assert_eq!(
            capture_stop_error_from_code(99),
            Some(CaptureStopError::DeviceFailure)
        );
    }

    #[test]
    fn capture_preflight_requires_ready_model_microphone_and_idle_capture() {
        assert_eq!(
            capture_start_allowed(
                ModelState::Installed,
                false,
                MicrophonePermission::Granted,
                false
            ),
            Err(CaptureStartError::ModelNotReady)
        );
        assert_eq!(
            capture_start_allowed(
                ModelState::Ready,
                false,
                MicrophonePermission::Granted,
                false
            ),
            Err(CaptureStartError::ModelNotReady)
        );
        assert_eq!(
            capture_start_allowed(ModelState::Ready, true, MicrophonePermission::Denied, false),
            Err(CaptureStartError::PermissionDenied)
        );
        assert_eq!(
            capture_start_allowed(ModelState::Ready, true, MicrophonePermission::Granted, true),
            Err(CaptureStartError::AlreadyActive)
        );
        assert_eq!(
            capture_start_allowed(
                ModelState::Ready,
                true,
                MicrophonePermission::Granted,
                false
            ),
            Ok(())
        );
    }

    #[test]
    fn transcript_validation_rejects_empty_oversized_and_invalid_durations() {
        assert_eq!(
            validate_transcript(" \n", 1.0),
            Err(TranscriptValidationError::Empty)
        );
        assert_eq!(
            validate_transcript("hello", 0.0),
            Err(TranscriptValidationError::InvalidDuration)
        );
        assert_eq!(
            validate_transcript("hello", f64::NAN),
            Err(TranscriptValidationError::InvalidDuration)
        );
        assert_eq!(
            validate_transcript("hello", 301.0),
            Err(TranscriptValidationError::InvalidDuration)
        );
        assert_eq!(
            validate_transcript(&"a".repeat(262_145), 1.0),
            Err(TranscriptValidationError::TooLong)
        );
        assert_eq!(validate_transcript(&"a".repeat(262_144), 300.0), Ok(()));
    }

    #[test]
    fn paste_text_rejects_empty_oversized_and_nul_inputs() {
        assert_eq!(validate_paste_text(" \n"), Err(PasteTextError::Empty));
        assert_eq!(
            validate_paste_text("hello\0world"),
            Err(PasteTextError::ContainsNull)
        );
        assert_eq!(
            validate_paste_text(&"a".repeat(262_145)),
            Err(PasteTextError::TooLong)
        );
        assert_eq!(validate_paste_text(&"é".repeat(131_072)), Ok(()));
        assert_eq!(validate_paste_text(&"a".repeat(262_144)), Ok(()));
    }

    #[test]
    fn paste_native_codes_fail_closed_without_accessibility_or_event_support() {
        assert_eq!(paste_native_error_from_code(0), None);
        assert_eq!(
            paste_native_error_from_code(1),
            Some(PasteNativeError::PermissionRequired)
        );
        assert_eq!(
            paste_native_error_from_code(2),
            Some(PasteNativeError::Unavailable)
        );
        assert_eq!(
            paste_native_error_from_code(99),
            Some(PasteNativeError::Unavailable)
        );
    }

    #[test]
    fn personal_dictionary_validation_is_bounded_and_case_insensitive() {
        let mut dictionary = std::collections::BTreeMap::from([
            ("OfficeKit".to_string(), "OfficeKit".to_string()),
            ("pike pdf".to_string(), "PyPDF".to_string()),
        ]);
        assert_eq!(validate_dictionary(&dictionary), Ok(()));

        dictionary.insert("officekit".to_string(), "Office Kit".to_string());
        assert_eq!(
            validate_dictionary(&dictionary),
            Err(DictionaryError::DuplicateSource)
        );
        dictionary.remove("officekit");
        dictionary.insert("".to_string(), "invalid".to_string());
        assert_eq!(
            validate_dictionary(&dictionary),
            Err(DictionaryError::InvalidEntry)
        );

        let too_many: std::collections::BTreeMap<_, _> = (0..=256)
            .map(|index| (format!("source{index}"), format!("target{index}")))
            .collect();
        assert_eq!(
            validate_dictionary(&too_many),
            Err(DictionaryError::TooManyEntries)
        );

        let too_long = std::collections::BTreeMap::from([("a".repeat(65), "ok".to_string())]);
        assert_eq!(
            validate_dictionary(&too_long),
            Err(DictionaryError::InvalidEntry)
        );
        let controls =
            std::collections::BTreeMap::from([("term".to_string(), "bad\nvalue".to_string())]);
        assert_eq!(
            validate_dictionary(&controls),
            Err(DictionaryError::InvalidEntry)
        );
    }

    #[test]
    fn accessibility_permission_codes_are_mapped_safely() {
        assert_eq!(
            accessibility_permission_from_code(0),
            AccessibilityPermission::Granted
        );
        assert_eq!(
            accessibility_permission_from_code(1),
            AccessibilityPermission::Denied
        );
        assert_eq!(
            accessibility_permission_from_code(-1),
            AccessibilityPermission::Unavailable
        );
        assert_eq!(
            accessibility_permission_from_code(9),
            AccessibilityPermission::Unavailable
        );
    }

    #[test]
    fn hotkey_monitor_start_codes_distinguish_duplicate_permission_and_failures() {
        assert_eq!(hotkey_monitor_start_error_from_code(0), None);
        assert_eq!(
            hotkey_monitor_start_error_from_code(1),
            Some(HotkeyMonitorStartError::AlreadyActive)
        );
        assert_eq!(
            hotkey_monitor_start_error_from_code(2),
            Some(HotkeyMonitorStartError::PermissionRequired)
        );
        assert_eq!(
            hotkey_monitor_start_error_from_code(3),
            Some(HotkeyMonitorStartError::Unavailable)
        );
        assert_eq!(
            hotkey_monitor_start_error_from_code(4),
            Some(HotkeyMonitorStartError::Unavailable)
        );
        assert_eq!(
            hotkey_monitor_start_error_from_code(99),
            Some(HotkeyMonitorStartError::Unavailable)
        );
    }

    #[test]
    fn fn_hold_transitions_start_once_stop_and_return_to_ready() {
        let down = transition_hotkey(HotkeyState::Ready, HotkeyEvent::KeyDown);
        assert_eq!(down.state, HotkeyState::Recording);
        assert_eq!(down.action, HotkeyAction::StartCapture);
        let repeated = transition_hotkey(down.state, HotkeyEvent::KeyDown);
        assert_eq!(repeated.state, HotkeyState::Recording);
        assert_eq!(repeated.action, HotkeyAction::None);

        let up = transition_hotkey(down.state, HotkeyEvent::KeyUp);
        assert_eq!(up.state, HotkeyState::Processing);
        assert_eq!(up.action, HotkeyAction::StopAndTranscribe);
        let complete = transition_hotkey(up.state, HotkeyEvent::TranscriptionFinished);
        assert_eq!(complete.state, HotkeyState::Ready);
        assert_eq!(complete.action, HotkeyAction::None);
    }

    #[test]
    fn disabling_selected_key_monitor_stops_active_audio_without_transcribing() {
        let disabled = transition_hotkey(HotkeyState::Recording, HotkeyEvent::Disable);
        assert_eq!(disabled.state, HotkeyState::Disabled);
        assert_eq!(disabled.action, HotkeyAction::StopCaptureAndMonitor);
    }

    #[test]
    fn hotkey_capture_failure_recovers_and_invalid_events_are_ignored() {
        let failed = transition_hotkey(HotkeyState::Recording, HotkeyEvent::CaptureFailed);
        assert_eq!(failed.state, HotkeyState::Ready);
        assert_eq!(failed.action, HotkeyAction::None);
        assert_eq!(
            transition_hotkey(HotkeyState::Disabled, HotkeyEvent::KeyUp),
            super::HotkeyTransition {
                state: HotkeyState::Disabled,
                action: HotkeyAction::None,
            }
        );
    }

    #[test]
    fn dictation_hotkey_ids_are_stable_and_left_option_is_the_default() {
        let keys = [
            DictationHotkeyKey::Fn,
            DictationHotkeyKey::LeftOption,
            DictationHotkeyKey::RightOption,
            DictationHotkeyKey::LeftControl,
            DictationHotkeyKey::RightControl,
            DictationHotkeyKey::LeftCommand,
            DictationHotkeyKey::RightCommand,
            DictationHotkeyKey::LeftShift,
            DictationHotkeyKey::RightShift,
            DictationHotkeyKey::Custom,
        ];
        assert_eq!(
            keys.map(DictationHotkeyKey::native_id),
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        );
        assert_eq!(
            DictationHotkeyKey::default(),
            DictationHotkeyKey::LeftOption
        );
        assert_eq!(DictationHotkeyKey::LeftOption.display_name(), "Left Option");
        assert_eq!(
            serde_json::to_string(&DictationHotkeyKey::RightShift).unwrap(),
            "\"right_shift\""
        );
    }

    #[test]
    fn custom_hotkey_validation_accepts_chords_and_safe_standalone_function_keys() {
        let chord = validate_custom_hotkey(2, 0b1010, "⌥ + ⌘ + D".into()).unwrap();
        assert_eq!(chord.key_code, 2);
        assert_eq!(chord.modifier_mask, 0b1010);
        assert_eq!(chord.label, "⌥ + ⌘ + D");
        assert_eq!(
            validate_custom_hotkey(105, 0, "F13".into())
                .unwrap()
                .key_code,
            105
        );
    }

    #[test]
    fn custom_hotkey_validation_accepts_every_key_offered_by_the_capture_ui() {
        for key_code in SUPPORTED_CUSTOM_HOTKEY_KEY_CODES {
            assert!(
                validate_custom_hotkey(*key_code, 0b0010, format!("Option + key {key_code}"))
                    .is_ok(),
                "capturable key code {key_code} should pass native validation"
            );
        }
    }

    #[test]
    fn custom_hotkey_validation_rejects_unsafe_unmodified_keys_and_malformed_values() {
        for (key_code, modifier_mask, label) in [
            (0, 0, "A"),
            (128, 0b0001, "Ctrl + A"),
            (2, 0b1_0000, "Invalid mask"),
            (12, 0b1000, "Command + Q"),
            (123, 0b0001, "Control + Left"),
            (2, 1, ""),
            (2, 1, "Bad\nlabel"),
        ] {
            assert!(validate_custom_hotkey(key_code, modifier_mask, label.into()).is_err());
        }
    }

    #[test]
    fn custom_hotkey_validation_rejects_modifier_and_unrecordable_keys() {
        for key_code in [
            10, 52, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 102, 104, 108, 110, 112, 114, 127,
        ] {
            assert!(
                validate_custom_hotkey(key_code, 0b0010, format!("Option + key {key_code}"))
                    .is_err(),
                "key code {key_code} cannot be recorded or is itself a modifier"
            );
        }
    }
}
