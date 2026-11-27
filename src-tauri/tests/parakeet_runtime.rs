//! Opt-in native inference check; never downloads models during the normal suite.
//! Supply a synthetic 16 kHz mono float WAV and its expected sentence.

#![cfg(all(target_os = "macos", target_arch = "aarch64"))]

use fluidaudio_rs::FluidAudio;
use std::fs;
use std::time::Instant;

fn words(text: &str) -> String {
    text.split(|character: char| !character.is_ascii_alphabetic())
        .filter(|word| !word.is_empty())
        .map(str::to_ascii_lowercase)
        .collect::<Vec<_>>()
        .join(" ")
}

fn fixture_samples(wav: &[u8]) -> Vec<f32> {
    assert_eq!(&wav[..4], b"RIFF", "fixture must be a WAV");
    assert_eq!(&wav[8..12], b"WAVE", "fixture must be a WAV");
    let mut offset = 12;
    let mut format_checked = false;
    while offset + 8 <= wav.len() {
        let chunk = &wav[offset..offset + 4];
        let length = u32::from_le_bytes(wav[offset + 4..offset + 8].try_into().unwrap()) as usize;
        let start = offset + 8;
        let end = start.checked_add(length).expect("fixture chunk overflow");
        assert!(end <= wav.len(), "truncated fixture chunk");
        if chunk == b"fmt " {
            assert!(length >= 16);
            assert_eq!(
                u16::from_le_bytes(wav[start..start + 2].try_into().unwrap()),
                3
            );
            assert_eq!(
                u16::from_le_bytes(wav[start + 2..start + 4].try_into().unwrap()),
                1
            );
            assert_eq!(
                u32::from_le_bytes(wav[start + 4..start + 8].try_into().unwrap()),
                16000
            );
            assert_eq!(
                u16::from_le_bytes(wav[start + 14..start + 16].try_into().unwrap()),
                32
            );
            format_checked = true;
        } else if chunk == b"data" {
            assert!(format_checked, "expected 16 kHz mono IEEE float WAV");
            assert!(length > 0 && length % 4 == 0);
            let samples: Vec<f32> = wav[start..end]
                .chunks_exact(4)
                .map(|bytes| f32::from_le_bytes(bytes.try_into().unwrap()))
                .collect();
            assert!(samples
                .iter()
                .all(|value| value.is_finite() && value.abs() <= 1.0));
            return samples;
        }
        offset = end + length % 2;
    }
    panic!("fixture lacks audio samples");
}

#[test]
#[ignore = "Opt-in: downloads Parakeet and runs actual CoreML inference on Apple silicon"]
fn local_parakeet_transcribes_file_and_repeated_sample_buffers() {
    let fixture = std::env::var("OFFICEKIT_PARAKEET_FIXTURE").expect("set synthetic WAV fixture");
    let expected =
        words(&std::env::var("OFFICEKIT_PARAKEET_EXPECTED").expect("set expected phrase"));
    assert!(!expected.is_empty());
    let samples = fixture_samples(&fs::read(&fixture).expect("read synthetic fixture"));
    let model_version = std::env::var("OFFICEKIT_PARAKEET_VERSION")
        .unwrap_or_else(|_| "3".to_string())
        .parse::<i32>()
        .expect("OFFICEKIT_PARAKEET_VERSION must be 2 or 3");
    assert!(matches!(model_version, 2 | 3));
    let engine = FluidAudio::new().expect("create native engine");
    let start = Instant::now();
    eprintln!("Preparing actual Parakeet model...");
    engine
        .init_asr_version(model_version)
        .expect("download and load model with vocabulary");
    assert!(engine.is_asr_available());
    eprintln!("Model ready after {:.1}s", start.elapsed().as_secs_f64());

    let file = engine
        .transcribe_file(&fixture)
        .expect("transcribe WAV file");
    assert!(
        words(&file.text).contains(&expected),
        "file transcript: {:?}",
        file.text
    );
    for attempt in 1..=2 {
        let result = engine
            .transcribe_samples(&samples)
            .expect("transcribe capture-shaped samples");
        assert!(
            words(&result.text).contains(&expected),
            "sample attempt {attempt}: {:?}",
            result.text
        );
        assert!(result.duration.is_finite() && result.duration > 0.0);
        eprintln!("File/sample inference attempt {attempt} passed");
    }
}
