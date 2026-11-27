use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-env-changed=OFFICEKIT_RELEASE_PROFILE");
    println!("cargo:rerun-if-env-changed=OFFICEKIT_LICENSE_API_BASE_URL");
    println!("cargo:rerun-if-env-changed=OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON");
    let profile = env::var("OFFICEKIT_RELEASE_PROFILE").unwrap_or_else(|_| "development".into());
    assert!(
        matches!(profile.as_str(), "development" | "private-beta"),
        "Unknown OfficeKit release profile"
    );
    println!("cargo:rustc-env=OFFICEKIT_RELEASE_PROFILE={profile}");
    let api_base_url = env::var("OFFICEKIT_LICENSE_API_BASE_URL")
        .unwrap_or_else(|_| "https://api.officekit.app".into());
    let public_keys =
        env::var("OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON").unwrap_or_else(|_| "{}".into());
    println!("cargo:rustc-env=OFFICEKIT_LICENSE_API_BASE_URL={api_base_url}");
    println!("cargo:rustc-env=OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON={public_keys}");
    println!("cargo:rerun-if-changed=macos-dictation.swift");
    println!("cargo:rerun-if-changed=macos-dictation-context.swift");
    println!("cargo:rerun-if-changed=macos-dictation-polish.swift");
    println!("cargo:rerun-if-changed=macos-global.swift");
    println!("cargo:rerun-if-changed=macos-global-logic.swift");
    println!("cargo:rerun-if-changed=macos-window.swift");
    println!("cargo:rerun-if-changed=macos-drawers.swift");
    println!("cargo:rerun-if-changed=macos-sensors.swift");
    println!("cargo:rerun-if-changed=macos-hardware.swift");
    println!("cargo:rerun-if-changed=macos-headphone-motion.swift");
    println!("cargo:rerun-if-changed=macos-user-activity.swift");
    println!("cargo:rerun-if-changed=macos-calendar.swift");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        compile_macos_dictation_bridge();
        // FluidAudio links Swift Concurrency dynamically. Resolve it from the
        // macOS Swift runtime instead of requiring a developer Xcode path.
        println!("cargo:rustc-link-arg=-Wl,-rpath,/usr/lib/swift");
    }
    ensure_sidecar_stubs();
    tauri_build::build()
}

fn ensure_sidecar_stubs() {
    let target = env::var("TARGET").unwrap_or_default();
    let binaries_dir = PathBuf::from("binaries");
    let resources_dir = PathBuf::from("resources").join("officekit-backend");
    let _ = std::fs::create_dir_all(&binaries_dir);
    let _ = std::fs::create_dir_all(&resources_dir);
    let extension = if target.contains("windows") {
        ".exe"
    } else {
        ""
    };
    let binary_name = format!("officekit-backend-{target}{extension}");
    let binary_path = binaries_dir.join(binary_name);
    if !binary_path.exists() {
        let _ = std::fs::write(&binary_path, b"");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&binary_path, std::fs::Permissions::from_mode(0o755));
        }
    }
    let stub_resource = resources_dir.join(".stub");
    if !stub_resource.exists() {
        let _ = std::fs::write(&stub_resource, b"");
    }
}

fn compile_macos_dictation_bridge() {
    println!("cargo:rerun-if-changed=macos-audio-tap.h");
    println!("cargo:rerun-if-changed=macos-audio-tap.m");
    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo provides OUT_DIR"));
    let object = out_dir.join("macos-dictation.o");
    let rust_target = env::var("TARGET").expect("Cargo provides TARGET");
    let swift_arch = match rust_target.split('-').next().unwrap_or_default() {
        "aarch64" => "arm64",
        "x86_64" => "x86_64",
        _ => panic!("Unsupported macOS architecture for dictation bridge: {rust_target}"),
    };
    let swift_target = format!("{swift_arch}-apple-macosx14.0");
    let audio_tap_object = out_dir.join("macos-audio-tap.o");
    let tap_status = Command::new("clang")
        .args([
            "-fobjc-arc",
            "-target",
            &swift_target,
            "-c",
            "macos-audio-tap.m",
            "-o",
        ])
        .arg(&audio_tap_object)
        .status()
        .expect("Clang is required for the macOS audio exception boundary");
    assert!(
        tap_status.success(),
        "Failed to compile the macOS audio exception boundary"
    );
    println!("cargo:rustc-link-arg={}", audio_tap_object.display());
    // The on-device model exists only in the macOS 26+ SDK. Older toolchains build without
    // it (the Swift side is behind `canImport`); newer ones link it weakly so the app still
    // launches on macOS 14 and 15.
    let has_foundation_models = Command::new("xcrun")
        .args(["--sdk", "macosx", "--show-sdk-path"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| {
            std::path::PathBuf::from(String::from_utf8_lossy(&output.stdout).trim())
                .join("System/Library/Frameworks/FoundationModels.framework")
                .exists()
        })
        .unwrap_or(false);
    let mut swift = Command::new("swiftc");
    swift.args([
        "-parse-as-library",
        "-O",
        "-wmo",
        "-module-name",
        "officekit_native",
        "-target",
        &swift_target,
        "-c",
    ]);
    if has_foundation_models {
        swift.args([
            "-Xfrontend",
            "-disable-autolink-framework",
            "-Xfrontend",
            "FoundationModels",
        ]);
    }
    let status = swift
        .args([
            "-import-objc-header",
            "macos-audio-tap.h",
            "macos-dictation.swift",
            "macos-dictation-context.swift",
            "macos-dictation-polish.swift",
            "macos-global.swift",
            "macos-global-logic.swift",
            "macos-window.swift",
            "macos-drawers.swift",
            "macos-sensors.swift",
            "macos-hardware.swift",
            "macos-headphone-motion.swift",
            "macos-user-activity.swift",
            "macos-calendar.swift",
            "-o",
        ])
        .arg(&object)
        .status()
        .expect("Swift compiler is required for the macOS dictation bridge");
    assert!(
        status.success(),
        "Failed to compile the macOS dictation bridge"
    );
    println!("cargo:rustc-link-arg={}", object.display());
    if has_foundation_models {
        println!("cargo:rustc-link-arg=-Wl,-weak_framework,FoundationModels");
    }
    println!("cargo:rustc-link-lib=framework=Carbon");
    println!("cargo:rustc-link-lib=framework=ServiceManagement");
    println!("cargo:rustc-link-lib=framework=AVFoundation");
    println!("cargo:rustc-link-lib=framework=AVFAudio");
    println!("cargo:rustc-link-lib=framework=ScreenCaptureKit");
    println!("cargo:rustc-link-lib=framework=CoreMedia");
    println!("cargo:rustc-link-lib=framework=CoreAudio");
    println!("cargo:rustc-link-lib=framework=CoreMotion");
    println!("cargo:rustc-link-lib=framework=EventKit");
}
