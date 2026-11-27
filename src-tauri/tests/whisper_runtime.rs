//! Opt-in local Whisper inference. The regular suite never downloads large models.
#![cfg(all(target_os = "macos", target_arch = "aarch64"))]

use std::fs;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

fn samples_from_float_wav(bytes: &[u8]) -> Vec<f32> {
    assert!(bytes.len() >= 44, "fixture must be a WAV file");
    assert_eq!(&bytes[..4], b"RIFF");
    assert_eq!(&bytes[8..12], b"WAVE");
    let mut offset = 12;
    let mut valid_format = false;
    while offset + 8 <= bytes.len() {
        let chunk = &bytes[offset..offset + 4];
        let length = u32::from_le_bytes(bytes[offset + 4..offset + 8].try_into().unwrap()) as usize;
        let start = offset + 8;
        let end = start.checked_add(length).expect("WAV chunk size overflow");
        assert!(end <= bytes.len(), "truncated WAV chunk");
        if chunk == b"fmt " {
            assert!(length >= 16);
            assert_eq!(
                u16::from_le_bytes(bytes[start..start + 2].try_into().unwrap()),
                3
            );
            assert_eq!(
                u16::from_le_bytes(bytes[start + 2..start + 4].try_into().unwrap()),
                1
            );
            assert_eq!(
                u32::from_le_bytes(bytes[start + 4..start + 8].try_into().unwrap()),
                16_000
            );
            assert_eq!(
                u16::from_le_bytes(bytes[start + 14..start + 16].try_into().unwrap()),
                32
            );
            valid_format = true;
        } else if chunk == b"data" {
            assert!(valid_format, "expected 16 kHz mono IEEE-float WAV");
            assert!(length > 0 && length % 4 == 0);
            return bytes[start..end]
                .chunks_exact(4)
                .map(|sample| f32::from_le_bytes(sample.try_into().unwrap()))
                .collect();
        }
        offset = end + length % 2;
    }
    panic!("WAV fixture contains no audio samples");
}

#[test]
#[ignore = "Opt-in: requires a verified local GGML model and a synthetic 16 kHz WAV"]
fn whisper_runs_local_multilingual_inference() {
    // Match the app's macOS startup workaround so this opt-in test also
    // exercises safe process teardown after real Metal inference.
    std::env::set_var("GGML_METAL_NO_RESIDENCY", "1");
    let model = std::env::var("OFFICEKIT_WHISPER_MODEL").expect("set local GGML model path");
    let fixture = std::env::var("OFFICEKIT_WHISPER_FIXTURE").expect("set 16 kHz float WAV path");
    let expected = std::env::var("OFFICEKIT_WHISPER_EXPECTED").expect("set expected words");
    let language = std::env::var("OFFICEKIT_WHISPER_LANGUAGE").ok();
    let repetitions = std::env::var("OFFICEKIT_WHISPER_REPETITIONS")
        .ok()
        .map(|value| {
            value
                .parse::<usize>()
                .expect("repetitions must be an integer")
        })
        .unwrap_or(1);
    assert!(
        (1..=100).contains(&repetitions),
        "repetitions must be 1..=100"
    );
    let load_started = std::time::Instant::now();
    let context = WhisperContext::new_with_params(model, WhisperContextParameters::default())
        .expect("load local Whisper model");
    let load_elapsed = load_started.elapsed();
    let mut state = context
        .create_state()
        .expect("create Whisper inference state");
    let samples = samples_from_float_wav(&fs::read(fixture).expect("read WAV fixture"));
    let mut inference_times = Vec::with_capacity(repetitions);
    for _ in 0..repetitions {
        let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
        params.set_language(language.as_deref());
        params.set_no_context(true);
        params.set_no_timestamps(true);
        params.set_print_progress(false);
        params.set_print_realtime(false);
        params.set_print_timestamps(false);
        let inference_started = std::time::Instant::now();
        state
            .full(params, &samples)
            .expect("run local Whisper inference");
        inference_times.push(inference_started.elapsed());
        let transcript = state
            .as_iter()
            .map(|segment| segment.to_string())
            .collect::<String>();
        let normalized = transcript.to_lowercase();
        assert!(
            normalized.contains(&expected.to_lowercase()),
            "transcript did not contain expected words: {transcript:?}"
        );
    }
    inference_times.sort_unstable();
    let median = inference_times[inference_times.len() / 2];
    let total: std::time::Duration = inference_times.iter().sum();
    eprintln!(
        "Whisper benchmark: model_load={load_elapsed:?}, repetitions={repetitions}, inference_total={total:?}, inference_median={median:?}, inference_max={:?}",
        inference_times.last().expect("at least one repetition")
    );
}
