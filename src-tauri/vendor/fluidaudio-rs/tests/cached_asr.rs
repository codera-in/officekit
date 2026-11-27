use fluidaudio_rs::FluidAudio;
use std::path::Path;

#[test]
fn cached_loaders_reject_invalid_arguments_and_missing_models() {
    let audio = FluidAudio::new().expect("bridge creation");
    assert!(audio.init_asr_version_cached(99, Path::new("/")).is_err());
    assert!(audio.init_asr_version_cached(3, Path::new("bad\0path")).is_err());
    assert!(audio.init_qwen3_asr_cached(Path::new("bad\0path")).is_err());
    let missing = std::env::temp_dir().join(format!("officekit-missing-model-{}", std::process::id()));
    assert!(!missing.exists());
    assert!(audio.init_asr_version_cached(2, &missing).is_err());
    assert!(audio.init_asr_version_cached(3, &missing).is_err());
    assert!(audio.init_qwen3_asr_cached(&missing).is_err());
}
