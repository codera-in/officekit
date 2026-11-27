// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // GGML's Metal residency-set keepalive can retain resources past model
    // teardown and assert while its process-global device is freed on Quit.
    // Disable only residency sets; Whisper still uses the Metal backend.
    #[cfg(target_os = "macos")]
    if std::env::var_os("GGML_METAL_NO_RESIDENCY").is_none() {
        std::env::set_var("GGML_METAL_NO_RESIDENCY", "1");
    }

    officekit_lib::run();
}
