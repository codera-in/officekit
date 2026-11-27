use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
#[cfg(target_os = "macos")]
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Emitter, Manager, RunEvent, State};
#[cfg(target_os = "macos")]
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_global_shortcut::{Builder as GlobalShortcutBuilder, ShortcutState};
#[cfg(test)]
use tauri_plugin_shell::process::TerminatedPayload;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use uuid::Uuid;

#[tauri::command]
fn open_network_settings(app: tauri::AppHandle) -> Result<(), String> {
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        let target = if cfg!(target_os = "macos") {
            "x-apple.systempreferences:com.apple.Network-Settings.extension"
        } else {
            "ms-settings:network"
        };
        return app
            .shell()
            .open(target, None)
            .map_err(|error| error.to_string());
    }
    #[cfg(target_os = "linux")]
    {
        for (program, argument) in [
            ("/usr/bin/gnome-control-center", Some("network")),
            ("/usr/bin/nm-connection-editor", None),
        ] {
            if std::path::Path::new(program).is_file() {
                let mut command = std::process::Command::new(program);
                if let Some(argument) = argument {
                    command.arg(argument);
                }
                command.spawn().map_err(|error| error.to_string())?;
                return Ok(());
            }
        }
        return Err("Network settings are not available on this desktop environment.".into());
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    Err("Network settings are not supported on this platform.".into())
}

#[tauri::command]
fn open_cloudflare_speed_test(app: tauri::AppHandle) -> Result<(), String> {
    app.shell()
        .open("https://speed.cloudflare.com/", None)
        .map_err(|error| error.to_string())
}
#[cfg(target_os = "macos")]
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

use crate::dictation::{
    accessibility_permission_from_code, microphone_permission_from_code, model_cache_directory,
    model_delete_allowed, model_files_present_for, model_switch_allowed,
    paste_native_error_from_code, request_prepare, validate_custom_hotkey, validate_dictionary,
    validate_paste_text, AccessibilityPermission, DictationCustomHotkey, DictationHotkeyKey,
    DictationModel, HotkeyState, MicrophonePermission, ModelState, PasteNativeError,
    PrepareDecision,
};
#[cfg(target_os = "macos")]
use crate::dictation::{
    capture_start_allowed, capture_start_error_from_code, capture_stop_error_from_code,
    collect_audio_samples, dictation_preview_range, hotkey_monitor_start_error_from_code,
    merge_qwen3_transcript_chunks, transition_hotkey, validate_transcript, CaptureStartError,
    CaptureStopError, HotkeyAction, HotkeyEvent, HotkeyMonitorStartError, DICTATION_SAMPLE_RATE,
};
use crate::license_client::{
    activate_license, configured_license_api_base_url, current_license_status, deactivate_license,
    parse_pinned_keyring, ActiveLicenseStatus, HttpActivationApi, LicenseClientError,
    MacKeychainLicenseStore,
};
use crate::license_gate::{LicenseGate, LockState};

#[cfg(target_os = "macos")]
use fluidaudio_rs::FluidAudio;

#[cfg(target_os = "macos")]
enum DictationEngine {
    Fluid(FluidAudio),
    Whisper(WhisperContext),
}

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_dictation_microphone_permission_status() -> i32;
    fn officekit_dictation_has_audio_input() -> i32;
    fn officekit_dictation_request_microphone_permission() -> i32;
    fn officekit_dictation_start_capture() -> i32;
    fn officekit_dictation_start_meeting_capture(capture_system_audio: i32) -> i32;
    fn officekit_dictation_stop_capture() -> i32;
    fn officekit_dictation_sample_count() -> u64;
    fn officekit_dictation_copy_samples(destination: *mut f32, capacity: u64) -> u64;
    fn officekit_dictation_copy_samples_range(
        destination: *mut f32,
        offset: u64,
        capacity: u64,
    ) -> u64;
    fn officekit_dictation_drain_samples(destination: *mut f32, capacity: u64) -> u64;
    fn officekit_dictation_clear_samples();
    fn officekit_dictation_accessibility_status() -> i32;
    fn officekit_dictation_request_accessibility_permission() -> i32;
    fn officekit_dictation_screen_recording_permission_status() -> i32;
    fn officekit_dictation_request_screen_recording_permission() -> i32;
    fn officekit_dictation_start_hotkey_monitor(
        key_id: i32,
        key_code: i32,
        modifier_mask: i32,
    ) -> i32;
    fn officekit_dictation_stop_hotkey_monitor();
    fn officekit_dictation_hotkey_key_pressed() -> i32;
    fn officekit_dictation_paste_text(text: *const u8, length: u64) -> i32;
    fn officekit_dictation_paste_session(text: *const u8, length: u64, generation: u64) -> i32;
    fn officekit_dictation_focus_context(
        include_field_text: i32,
        output: *mut u8,
        capacity: u64,
    ) -> i64;
    fn officekit_dictation_polish_available() -> i32;
    fn officekit_dictation_polish_status() -> i32;
    fn officekit_dictation_language_suggestion(
        input: *const u8,
        length: u64,
        focus: i32,
        output: *mut u8,
        capacity: u64,
        timeout_milliseconds: u64,
    ) -> i64;
    fn officekit_dictation_polish(
        input: *const u8,
        length: u64,
        output: *mut u8,
        capacity: u64,
        timeout_milliseconds: u64,
    ) -> i64;
    fn officekit_dictation_overlay_begin() -> u64;
    fn officekit_dictation_overlay_generation() -> u64;
    fn officekit_dictation_overlay_valid(generation: u64) -> i32;
    fn officekit_dictation_overlay_processing(generation: u64);
    fn officekit_dictation_overlay_transcript(text: *const u8, length: u64, generation: u64);
    fn officekit_dictation_overlay_finish(generation: u64);
    fn officekit_dictation_overlay_fail(text: *const u8, length: u64, generation: u64);
    fn officekit_dictation_coach_speech_seconds() -> f64;
    fn officekit_dictation_coach_is_active() -> i32;
    fn officekit_dictation_coach_start_for_dictation() -> i32;
    fn officekit_dictation_coach_start_for_meeting() -> i32;
    fn officekit_dictation_coach_set_close_callback(callback: extern "C" fn());
    fn officekit_dictation_coach_drain_window(
        destination: *mut f32,
        capacity: u64,
        speech_seconds: *mut f64,
    ) -> u64;
    fn officekit_dictation_coach_window_sample_count() -> u64;
    fn officekit_dictation_coach_cue(text: *const u8, length: u64, generation: u64);
    fn officekit_dictation_coach_pace(
        pace_wpm: u16,
        target_min: u16,
        target_max: u16,
        generation: u64,
    );
    fn officekit_dictation_coach_pitch_stats(median_hz: u16, range_hz: u16, generation: u64);
    fn officekit_screenshot_shortcut_configure(choice: i32, callback: extern "C" fn()) -> i32;
}

#[cfg(target_os = "macos")]
static SPEECH_COACH_LANGUAGE_SUGGESTION_PENDING: AtomicBool = AtomicBool::new(false);

const BACKEND_ADDRESS: &str = "127.0.0.1:8000";
/// The first launch of a freshly installed sidecar takes about 30 s on macOS while the system
/// scans the new binary, so this must stay well above that or the app aborts at launch.
const BACKEND_START_TIMEOUT: Duration = Duration::from_secs(120);
const BACKEND_CONNECT_TIMEOUT: Duration = Duration::from_millis(150);
const MAX_HEALTH_RESPONSE_BYTES: usize = 16 * 1024;
const BACKEND_VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_DICTATION_CLEANUP_RESPONSE_BYTES: usize = 1_200_000;

#[cfg(target_os = "macos")]
fn should_keep_background_after_main_window_close(window_label: &str) -> bool {
    window_label == "main"
}

#[cfg(target_os = "macos")]
fn should_show_main_window_after_reopen(
    has_visible_windows: bool,
    companion_hid_recently: bool,
) -> bool {
    !has_visible_windows && !companion_hid_recently
}

mod agent_settings;
mod app_settings;
mod call_detect;
mod coach_grammar;
mod coach_rules;
mod coach_workspace;
mod crash_restart;
mod dictation;
mod dictation_quality;
mod ergonomics;
mod ergonomics_access;
#[cfg(test)]
#[path = "../../tests/ergonomics-access.rs"]
mod ergonomics_access_tests;
mod global_clipboard;
mod global_desktop;
mod headphone_motion;
mod invoice_native;
mod launcher_apps;
mod license_client;
mod license_gate;
#[cfg(test)]
mod license_guard_tests;
mod licensing;
#[cfg(test)]
mod test_keys;
mod meeting_calendar;
mod menu_stats;
mod panic_log;
mod raw_audio;
mod speech_coach;
mod speech_model;
mod support_ticket;
mod system_hardware;
mod system_sensors;
mod window_manager;
mod window_runtime;
mod workspace_native;
pub use dictation::transcribe_qwen3_chunks;

struct BackendProcess(Mutex<Option<CommandChild>>);
struct BackendApiToken(String);
struct BackendApiAddress(SocketAddr);

const WINDOW_MIN_WIDTH: f64 = 1100.0;
const WINDOW_MIN_HEIGHT: f64 = 760.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WindowBounds {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

fn snap_target_bounds(action: &str, area: WindowBounds) -> Option<WindowBounds> {
    let left_width = area.width / 2;
    let right_width = area.width - left_width;
    let top_height = area.height / 2;
    let bottom_height = area.height - top_height;
    let right = area
        .x
        .saturating_add(left_width.min(i32::MAX as u32) as i32);
    let bottom = area
        .y
        .saturating_add(top_height.min(i32::MAX as u32) as i32);
    let bounds = match action {
        "left-half" => WindowBounds {
            x: area.x,
            y: area.y,
            width: left_width,
            height: area.height,
        },
        "right-half" => WindowBounds {
            x: right,
            y: area.y,
            width: right_width,
            height: area.height,
        },
        "top-half" => WindowBounds {
            x: area.x,
            y: area.y,
            width: area.width,
            height: top_height,
        },
        "bottom-half" => WindowBounds {
            x: area.x,
            y: bottom,
            width: area.width,
            height: bottom_height,
        },
        "top-left" => WindowBounds {
            x: area.x,
            y: area.y,
            width: left_width,
            height: top_height,
        },
        "top-right" => WindowBounds {
            x: right,
            y: area.y,
            width: right_width,
            height: top_height,
        },
        "bottom-left" => WindowBounds {
            x: area.x,
            y: bottom,
            width: left_width,
            height: bottom_height,
        },
        "bottom-right" => WindowBounds {
            x: right,
            y: bottom,
            width: right_width,
            height: bottom_height,
        },
        "center" => {
            let width = area.width.saturating_mul(3) / 5;
            let height = area.height.saturating_mul(4) / 5;
            WindowBounds {
                x: area
                    .x
                    .saturating_add(((area.width - width) / 2).min(i32::MAX as u32) as i32),
                y: area
                    .y
                    .saturating_add(((area.height - height) / 2).min(i32::MAX as u32) as i32),
                width,
                height,
            }
        }
        "maximize" => area,
        _ => return None,
    };
    Some(bounds)
}

fn move_to_monitor_bounds(current: WindowBounds, area: WindowBounds) -> WindowBounds {
    let width = current.width.min(area.width);
    let height = current.height.min(area.height);
    WindowBounds {
        x: area
            .x
            .saturating_add(((area.width - width) / 2).min(i32::MAX as u32) as i32),
        y: area
            .y
            .saturating_add(((area.height - height) / 2).min(i32::MAX as u32) as i32),
        width,
        height,
    }
}

fn edge_snap_action(
    window: WindowBounds,
    area: WindowBounds,
    threshold: u32,
) -> Option<&'static str> {
    let right_delta =
        i64::from(window.x) + i64::from(window.width) - i64::from(area.x) - i64::from(area.width);
    let bottom_delta =
        i64::from(window.y) + i64::from(window.height) - i64::from(area.y) - i64::from(area.height);
    let near_left = (i64::from(window.x) - i64::from(area.x)).abs() <= i64::from(threshold);
    let near_right = right_delta.abs() <= i64::from(threshold);
    let near_top = (i64::from(window.y) - i64::from(area.y)).abs() <= i64::from(threshold);
    let near_bottom = bottom_delta.abs() <= i64::from(threshold);
    match (near_left || near_right, near_top || near_bottom) {
        (true, true) => match (near_left, near_top) {
            (true, true) => Some("top-left"),
            (false, true) => Some("top-right"),
            (true, false) => Some("bottom-left"),
            (false, false) => Some("bottom-right"),
        },
        (true, false) => Some(if near_left { "left-half" } else { "right-half" }),
        (false, true) => Some(if near_top { "top-half" } else { "bottom-half" }),
        (false, false) => None,
    }
}

fn edge_snap_should_apply(
    enabled: bool,
    generation: u64,
    current_generation: u64,
    preview_action: Option<&str>,
    action: &str,
) -> bool {
    enabled && generation == current_generation && preview_action == Some(action)
}

#[derive(Default)]
struct WindowSnapState {
    previous_bounds: Mutex<BTreeMap<String, WindowBounds>>,
    edge_enabled: AtomicBool,
    move_generation: AtomicU64,
    auto_snap_suppression_until: Mutex<Option<Instant>>,
    preview_action: Mutex<Option<String>>,
}

fn leave_window_modes(
    fullscreen: bool,
    maximized: bool,
    exit_fullscreen: impl FnOnce() -> Result<(), String>,
    unmaximize: impl FnOnce() -> Result<(), String>,
) -> Result<(), String> {
    if fullscreen {
        exit_fullscreen()?;
    }
    if maximized {
        unmaximize()?;
    }
    Ok(())
}

#[tauri::command]
fn window_snap(
    window: tauri::WebviewWindow,
    state: State<'_, WindowSnapState>,
    action: String,
) -> Result<(), String> {
    window_snap_action(&window, &state, &action)
}

#[tauri::command]
fn window_snap_set_edge_enabled(state: State<'_, WindowSnapState>, enabled: bool) {
    state.edge_enabled.store(enabled, Ordering::Relaxed);
}

fn window_snap_action(
    window: &tauri::WebviewWindow,
    state: &WindowSnapState,
    action: &str,
) -> Result<(), String> {
    let label = window.label().to_string();
    if action == "toggle-fullscreen" {
        let fullscreen = window.is_fullscreen().unwrap_or(false);
        if !fullscreen {
            save_window_bounds(window, state)?;
        }
        return window
            .set_fullscreen(!fullscreen)
            .map_err(|_| "Could not change fullscreen mode".to_string());
    }

    let monitor_move = match action {
        "move-next-monitor" => Some(1isize),
        "move-previous-monitor" => Some(-1isize),
        _ => None,
    };
    let supported_layout = matches!(
        action,
        "left-half"
            | "right-half"
            | "top-half"
            | "bottom-half"
            | "top-left"
            | "top-right"
            | "bottom-left"
            | "bottom-right"
            | "center"
            | "maximize"
            | "restore"
    );
    if monitor_move.is_none() && !supported_layout {
        return Err("Choose a supported window layout".to_string());
    }

    let current_position = window
        .outer_position()
        .map_err(|_| "Could not read this window's position".to_string())?;
    let current_outer_size = window
        .outer_size()
        .map_err(|_| "Could not read this window's size".to_string())?;
    let current_bounds = WindowBounds {
        x: current_position.x,
        y: current_position.y,
        width: current_outer_size.width,
        height: current_outer_size.height,
    };

    if action == "restore" {
        leave_window_modes(
            window.is_fullscreen().unwrap_or(false),
            window.is_maximized().unwrap_or(false),
            || {
                window
                    .set_fullscreen(false)
                    .map_err(|_| "Could not exit fullscreen mode".to_string())
            },
            || {
                window
                    .unmaximize()
                    .map_err(|_| "Could not prepare the window for restore".to_string())
            },
        )?;
        let bounds = state
            .previous_bounds
            .lock()
            .map_err(|_| "Window snapping state is unavailable".to_string())?
            .get(&label)
            .copied()
            .ok_or_else(|| "There is no earlier window size to restore".to_string())?;
        apply_window_bounds(window, bounds, true)?;
        state
            .previous_bounds
            .lock()
            .map_err(|_| "Window snapping state is unavailable".to_string())?
            .remove(&label);
        return Ok(());
    }

    save_window_bounds(window, state)?;
    leave_window_modes(
        window.is_fullscreen().unwrap_or(false),
        window.is_maximized().unwrap_or(false),
        || {
            window
                .set_fullscreen(false)
                .map_err(|_| "Could not exit fullscreen mode".to_string())
        },
        || {
            window
                .unmaximize()
                .map_err(|_| "Could not prepare the window for snapping".to_string())
        },
    )?;

    let target = if let Some(direction) = monitor_move {
        let monitors = window
            .available_monitors()
            .map_err(|_| "Could not identify the available screens".to_string())?;
        if monitors.len() < 2 {
            return Err("Connect another screen to move OfficeKit between screens".to_string());
        }
        let current_monitor = window
            .current_monitor()
            .map_err(|_| "Could not identify this screen".to_string())?
            .or(window
                .primary_monitor()
                .map_err(|_| "Could not identify this screen".to_string())?)
            .ok_or_else(|| "No screen is available".to_string())?;
        let current_index = monitors
            .iter()
            .position(|monitor| {
                monitor.position() == current_monitor.position()
                    && monitor.size() == current_monitor.size()
            })
            .unwrap_or(0);
        let destination_index =
            (current_index as isize + direction).rem_euclid(monitors.len() as isize) as usize;
        let area = *monitors[destination_index].work_area();
        move_to_monitor_bounds(
            current_bounds,
            WindowBounds {
                x: area.position.x,
                y: area.position.y,
                width: area.size.width,
                height: area.size.height,
            },
        )
    } else {
        let monitor = window
            .current_monitor()
            .map_err(|_| "Could not identify this screen".to_string())?
            .or(window
                .primary_monitor()
                .map_err(|_| "Could not identify this screen".to_string())?)
            .ok_or_else(|| "No screen is available for window snapping".to_string())?;
        let area = *monitor.work_area();
        snap_target_bounds(
            action,
            WindowBounds {
                x: area.position.x,
                y: area.position.y,
                width: area.size.width,
                height: area.size.height,
            },
        )
        .ok_or_else(|| "Choose a supported window layout".to_string())?
    };
    if let Ok(mut suppress) = state.auto_snap_suppression_until.lock() {
        *suppress = Some(Instant::now() + Duration::from_millis(900));
    }
    apply_window_bounds(window, target, false)
}

/// Only the main window snaps to screen edges; panels such as Quick controls are placed against
/// the top of the screen by the app and must keep their own size.
fn window_snaps_to_edges(label: &str) -> bool {
    label == "main"
}

fn handle_window_moved(window: &tauri::WebviewWindow) {
    if !window_snaps_to_edges(window.label()) {
        return;
    }
    let app = window.app_handle().clone();
    let state = app.state::<WindowSnapState>();
    if !state.edge_enabled.load(Ordering::Relaxed) || window.is_fullscreen().unwrap_or(false) {
        return;
    }
    if state
        .auto_snap_suppression_until
        .lock()
        .ok()
        .and_then(|guard| *guard)
        .is_some_and(|until| until > Instant::now())
    {
        return;
    }
    let monitor = window
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else {
        return;
    };
    let Ok(position) = window.outer_position() else {
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };
    let area = *monitor.work_area();
    let bounds = WindowBounds {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    };
    let action = edge_snap_action(
        bounds,
        WindowBounds {
            x: area.position.x,
            y: area.position.y,
            width: area.size.width,
            height: area.size.height,
        },
        20,
    )
    .map(str::to_string);
    let changed = state
        .preview_action
        .lock()
        .ok()
        .is_some_and(|mut previous| {
            if *previous == action {
                false
            } else {
                *previous = action.clone();
                true
            }
        });
    if changed {
        let _ = window.emit(
            "window-snap-preview",
            serde_json::json!({ "action": action }),
        );
    }
    let Some(action) = action else {
        return;
    };
    let generation = state.move_generation.fetch_add(1, Ordering::Relaxed) + 1;
    let label = window.label().to_string();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(240));
        let state = app.state::<WindowSnapState>();
        let preview_action = state
            .preview_action
            .lock()
            .ok()
            .and_then(|action| action.clone());
        if !edge_snap_should_apply(
            state.edge_enabled.load(Ordering::Relaxed),
            generation,
            state.move_generation.load(Ordering::Relaxed),
            preview_action.as_deref(),
            &action,
        ) {
            return;
        }
        if let Some(window) = app.get_webview_window(&label) {
            if let Ok(mut suppress) = state.auto_snap_suppression_until.lock() {
                *suppress = Some(Instant::now() + Duration::from_millis(900));
            }
            let _ = window_snap_action(&window, &state, &action);
            if let Ok(mut preview) = state.preview_action.lock() {
                *preview = None;
            }
            let _ = window.emit("window-snap-preview", serde_json::json!({ "action": null }));
        }
    });
}

fn save_window_bounds(
    window: &tauri::WebviewWindow,
    state: &WindowSnapState,
) -> Result<(), String> {
    let position = window
        .outer_position()
        .map_err(|_| "Could not read this window's position".to_string())?;
    let size = window
        .outer_size()
        .map_err(|_| "Could not read this window's size".to_string())?;
    state
        .previous_bounds
        .lock()
        .map_err(|_| "Window snapping state is unavailable".to_string())?
        .entry(window.label().to_string())
        .or_insert(WindowBounds {
            x: position.x,
            y: position.y,
            width: size.width,
            height: size.height,
        });
    Ok(())
}

fn apply_window_bounds(
    window: &tauri::WebviewWindow,
    bounds: WindowBounds,
    restore_minimum: bool,
) -> Result<(), String> {
    let outer = window
        .outer_size()
        .map_err(|_| "Could not read this window's size".to_string())?;
    let inner = window
        .inner_size()
        .map_err(|_| "Could not read this window's content size".to_string())?;
    let frame_width = outer.width.saturating_sub(inner.width);
    let frame_height = outer.height.saturating_sub(inner.height);
    if restore_minimum {
        window
            .set_min_size(Some(tauri::LogicalSize::new(
                WINDOW_MIN_WIDTH,
                WINDOW_MIN_HEIGHT,
            )))
            .map_err(|_| "Could not restore the window's minimum size".to_string())?;
    } else {
        window
            .set_min_size(None::<tauri::LogicalSize<f64>>)
            .map_err(|_| "Could not prepare the window for snapping".to_string())?;
    }
    window
        .set_size(tauri::PhysicalSize::new(
            bounds.width.saturating_sub(frame_width).max(1),
            bounds.height.saturating_sub(frame_height).max(1),
        ))
        .map_err(|_| "The window could not fit that layout on this screen".to_string())?;
    window
        .set_position(tauri::PhysicalPosition::new(bounds.x, bounds.y))
        .map_err(|_| "The window could not move to that layout".to_string())
}

fn select_backend_address_from(preferred: SocketAddr) -> std::io::Result<SocketAddr> {
    if TcpStream::connect_timeout(&preferred, BACKEND_CONNECT_TIMEOUT).is_err() {
        if let Ok(listener) = TcpListener::bind(preferred) {
            return listener.local_addr();
        }
    }
    TcpListener::bind("127.0.0.1:0")?.local_addr()
}

fn select_backend_address() -> std::io::Result<SocketAddr> {
    let preferred = BACKEND_ADDRESS
        .parse::<SocketAddr>()
        .expect("valid loopback address");
    select_backend_address_from(preferred)
}

fn license_public_keys() -> Result<BTreeMap<String, String>, LicenseClientError> {
    parse_pinned_keyring(option_env!("OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON").unwrap_or("{}"))
}

fn license_platform() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

#[tauri::command]
fn license_status() -> Result<Option<ActiveLicenseStatus>, String> {
    let keys = license_public_keys().map_err(|error| error.public_message().to_string())?;
    current_license_status(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "System time is unavailable".to_string())?
            .as_secs(),
        &keys,
        &MacKeychainLicenseStore::new(),
        &MacKeychainLicenseStore::new(),
    )
    .map_err(|error| error.public_message().to_string())
}

/// Lock state for the locked-app UI: one lowercase word, no email, key, ids or dates.
#[tauri::command]
fn license_state(gate: State<'_, LicenseGate>) -> LockState {
    gate.state(unix_now())
}

/// Seconds since the epoch, or `None` when the system clock is unreadable. The gate treats
/// `None` as "cannot check expiry" and denies paid work (fail closed).
fn unix_now() -> Option<u64> {
    license_gate::epoch_seconds(std::time::SystemTime::now())
}

/// Verify the Keychain receipt and push the result to the sidecar (startup, after activation,
/// and every 15 minutes). Never panics; returns false when the push failed so the caller can
/// retry on a short backoff.
fn license_push_tick(gate: &LicenseGate, client: &license_gate::LoopbackEntitlementClient) -> bool {
    let keys = license_public_keys().unwrap_or_default();
    let store = MacKeychainLicenseStore::new();
    license_gate::tick_from_store(gate, client, unix_now(), &keys, &store, &store)
}

/// Read the Keychain receipt into the native gate before any webview exists, so a licensed
/// user is never `Checking` when the webview's startup calls arrive.
fn license_startup_check(gate: &LicenseGate) {
    let keys = license_public_keys().unwrap_or_default();
    let store = MacKeychainLicenseStore::new();
    license_gate::check_from_store(gate, unix_now(), &keys, &store, &store);
}

struct LicensePushClient(Arc<license_gate::LoopbackEntitlementClient>);

#[tauri::command]
async fn license_activate(
    gate: State<'_, LicenseGate>,
    push: State<'_, LicensePushClient>,
    email: String,
    license_key: String,
) -> Result<ActiveLicenseStatus, String> {
    let keys = license_public_keys().map_err(|error| error.public_message().to_string())?;
    let api_base_url = configured_license_api_base_url()
        .map_err(|error| error.public_message().to_string())?
        .to_string();
    let gate = gate.inner().clone();
    let push_client = push.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let now_epoch = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "System time is unavailable".to_string())?
            .as_secs();
        let device_key = MacKeychainLicenseStore::new();
        let mut receipt_store = MacKeychainLicenseStore::new();
        let mut api = HttpActivationApi::new(&api_base_url)
            .map_err(|error| error.public_message().to_string())?;
        let status = activate_license(
            &email,
            &license_key,
            license_platform(),
            env!("CARGO_PKG_VERSION"),
            now_epoch,
            &keys,
            &mut api,
            &device_key,
            &mut receipt_store,
        )
        .map_err(|error| error.public_message().to_string())?;
        // Unlock the native gate and the sidecar before the UI proceeds. A failed push does not
        // fail the activation; it is retried on a short bounded backoff, then by the scheduler.
        if !license_push_tick(&gate, &push_client) {
            thread::spawn(move || {
                license_gate::retry_failed_push(thread::sleep, || {
                    license_push_tick(&gate, &push_client)
                });
            });
        }
        Ok(status)
    })
    .await
    .map_err(|_| "License activation could not be completed".to_string())?
}

/// Frees this Mac's seat, then locks. The email and licence key are typed again because the app
/// never stores them. The receipt is removed only after the server answered, so a failure leaves
/// the Mac activated.
#[tauri::command]
async fn license_deactivate(
    gate: State<'_, LicenseGate>,
    push: State<'_, LicensePushClient>,
    email: String,
    license_key: String,
) -> Result<(), String> {
    let keys = license_public_keys().map_err(|error| error.public_message().to_string())?;
    let api_base_url = configured_license_api_base_url()
        .map_err(|error| error.public_message().to_string())?
        .to_string();
    let gate = gate.inner().clone();
    let push_client = push.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let now_epoch = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "System time is unavailable".to_string())?
            .as_secs();
        let device_key = MacKeychainLicenseStore::new();
        let mut receipt_store = MacKeychainLicenseStore::new();
        let mut api = HttpActivationApi::new(&api_base_url)
            .map_err(|error| error.public_message().to_string())?;
        deactivate_license(
            &email,
            &license_key,
            now_epoch,
            &keys,
            &mut api,
            &device_key,
            &mut receipt_store,
        )
        .map_err(|error| error.public_message().to_string())?;
        // Lock the native gate and clear the sidecar even when there was no receipt to remove.
        gate.clear(license_gate::LockState::Locked, &*push_client)
            .map_err(|_| "OfficeKit could not lock after deactivating. Restart it.".to_string())
    })
    .await
    .map_err(|_| "License deactivation could not be completed".to_string())?
}

fn command_output_field(program: &str, args: &[&str]) -> String {
    std::process::Command::new(program)
        .args(args)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .unwrap_or_default()
}

fn support_device_info(data_dir: &std::path::Path) -> support_ticket::DeviceInfo {
    let os = command_output_field("/usr/bin/sw_vers", &["-productVersion"]);
    let model = command_output_field("/usr/sbin/sysctl", &["-n", "hw.model"]);
    let license_hash = license_public_keys().ok().and_then(|keys| {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_secs();
        current_license_status(
            now,
            &keys,
            &MacKeychainLicenseStore::new(),
            &MacKeychainLicenseStore::new(),
        )
        .ok()
        .flatten()
        .map(|status| {
            support_ticket::sha256_hex(&format!("officekit-license:{}", status.activation_id))
        })
    });
    support_ticket::DeviceInfo {
        app_version: env!("CARGO_PKG_VERSION").to_string(),
        os_version: format!(
            "macOS {}",
            support_ticket::sanitize_field(&os, "unknown", 20, ".")
        ),
        model: support_ticket::sanitize_field(&model, "Mac", 40, ",._-"),
        device_hash: support_ticket::install_hash(data_dir),
        license_hash,
    }
}

/// Sends a report to OfficeKit support and returns its reference. Exempt from the licence gate so
/// a locked or expired Mac can still ask for help.
#[tauri::command]
async fn support_ticket_submit(
    app: tauri::AppHandle,
    draft: support_ticket::TicketDraft,
) -> Result<String, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|_| "OfficeKit could not find its data folder".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let info = support_device_info(&data_dir);
        let mut api = support_ticket::HttpSupportApi::new()
            .map_err(|error| error.public_message().to_string())?;
        support_ticket::submit_ticket(&draft, &info, &mut api, &data_dir)
            .map_err(|error| error.public_message().to_string())
    })
    .await
    .map_err(|_| {
        support_ticket::SupportError::Unavailable
            .public_message()
            .to_string()
    })?
}

/// Reports tickets that were fixed in a release since the last check, each once.
#[tauri::command]
async fn support_ticket_updates(
    app: tauri::AppHandle,
) -> Result<Vec<support_ticket::FixedNotice>, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|_| "OfficeKit could not find its data folder".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let mut api = support_ticket::HttpSupportApi::new()
            .map_err(|error| error.public_message().to_string())?;
        Ok(support_ticket::collect_updates(&mut api, &data_dir))
    })
    .await
    .map_err(|_| {
        support_ticket::SupportError::Unavailable
            .public_message()
            .to_string()
    })?
}

struct DictationRuntime(Mutex<DictationRuntimeState>);

impl DictationRuntimeState {
    #[cfg(target_os = "macos")]
    fn set_capture_active(&mut self, active: bool) {
        if self.capture_active != active {
            self.capture_active = active;
            self.capture_mode_epoch = self.capture_mode_epoch.wrapping_add(1);
        }
    }

    fn clear_focus_context(&self) {
        if let Ok(mut stored) = self.focus_context.lock() {
            *stored = None;
        }
    }

    fn focus_app_name(&self) -> Option<String> {
        self.focus_context
            .lock()
            .ok()
            .and_then(|stored| stored.as_ref().and_then(|context| context.app_name.clone()))
    }

    /// Context is consumed by exactly one cleanup.
    fn take_focus_context(&self) -> Option<dictation_quality::FocusContext> {
        self.focus_context
            .lock()
            .ok()
            .and_then(|mut stored| stored.take())
    }

    /// Drops everything captured for the dictation that just ended.
    fn clear_session_text(&self) {
        self.clear_focus_context();
        if let Ok(mut commit) = self.commit_state.lock() {
            *commit = dictation_quality::CommitState::default();
        }
    }
}

struct DictationRuntimeState {
    model: DictationModel,
    model_state: ModelState,
    model_progress: Option<DictationModelProgress>,
    translate_to_english: bool,
    spoken_language: Option<String>,
    vocabulary_terms: Vec<String>,
    context_options: dictation_quality::ContextOptions,
    /// Leaf lock, filled by a short-lived reader thread so the Accessibility read
    /// (which hops to the main queue) never runs under the runtime lock.
    focus_context: Arc<Mutex<Option<dictation_quality::FocusContext>>>,
    streaming_commit: bool,
    /// Where each dictation's raw audio is kept for troubleshooting; `None` is the default (off).
    raw_audio_directory: Option<std::path::PathBuf>,
    llm_polish: bool,
    /// Numbers about the last capture that failed after audio was collected; taken once
    /// when the failure is reported, so the history can say what the microphone heard.
    last_failure_capture: Option<dictation_quality::CaptureStats>,
    /// Leaf lock: never held while taking another lock, so the stop path and the
    /// background commit cannot deadlock.
    commit_state: Arc<Mutex<dictation_quality::CommitState>>,
    #[cfg(target_os = "macos")]
    capture_active: bool,
    #[cfg(target_os = "macos")]
    capture_mode_epoch: u64,
    #[cfg(target_os = "macos")]
    tray_capture_generation: Option<u64>,
    #[cfg(target_os = "macos")]
    hotkey_state: HotkeyState,
    hotkey_key: DictationHotkeyKey,
    custom_hotkey: Option<DictationCustomHotkey>,
    #[cfg(target_os = "macos")]
    engine: Option<Arc<Mutex<speech_model::SpeechModel<DictationEngine>>>>,
    #[cfg(target_os = "macos")]
    meeting_recording: bool,
    #[cfg(target_os = "macos")]
    meeting_stop_tx: Option<std::sync::mpsc::Sender<()>>,
}

#[derive(Clone, serde::Serialize)]
struct DictationMeetingStatus {
    is_recording: bool,
    source: String,
    duration_seconds: f64,
}

#[derive(Clone, serde::Serialize)]
struct DictationMeetingChunk {
    text: String,
    translated_text: Option<String>,
    is_final: bool,
}

#[derive(Clone, serde::Serialize)]
struct DictationMeetingProgress {
    duration_seconds: f64,
}

#[derive(Clone, serde::Serialize)]
struct DictationScreenRecordingStatus {
    permission: &'static str,
    message: &'static str,
}

#[derive(serde::Serialize)]
struct DictationModelStatus {
    model_id: &'static str,
    model: &'static str,
    language_support: &'static str,
    state: ModelState,
    message: String,
    progress: Option<DictationModelProgress>,
}

#[derive(Clone, serde::Serialize)]
struct DictationModelProgress {
    phase: &'static str,
    fraction: Option<f64>,
    bytes_downloaded: Option<u64>,
    bytes_total: Option<u64>,
    completed_files: Option<u32>,
    total_files: Option<u32>,
}

#[derive(serde::Serialize)]
struct DictationModelInventoryEntry {
    model_id: &'static str,
    model: &'static str,
    state: ModelState,
    size_bytes: u64,
}

#[derive(serde::Serialize)]
struct DictationMicrophoneStatus {
    permission: MicrophonePermission,
    message: &'static str,
    input_available: bool,
}

#[derive(serde::Serialize)]
struct DictationAccessibilityStatus {
    permission: AccessibilityPermission,
    message: &'static str,
}

#[derive(serde::Serialize)]
struct DictationCaptureStatus {
    state: &'static str,
}

#[derive(Clone, Debug, serde::Serialize)]
struct DictationTranscript {
    text: String,
    translated_text: Option<String>,
    audio_duration_seconds: f64,
    capture_generation: Option<u64>,
    delivery_status: Option<&'static str>,
    /// Numbers about the recording for the history steps view; set once at capture.
    #[serde(skip_serializing_if = "Option::is_none")]
    capture: Option<dictation_quality::CaptureStats>,
    /// Descriptive pitch metrics from bounded microphone windows when Speech Coach is on.
    #[serde(skip_serializing_if = "Option::is_none")]
    speech_coach_metrics: Option<DictationSpeechCoachMetrics>,
    /// What each cleanup stage did; set when the transcript is cleaned and pasted.
    #[serde(skip_serializing_if = "Option::is_none")]
    steps: Option<DictationSteps>,
    /// Display name of the speech model that produced the text.
    #[serde(skip_serializing_if = "Option::is_none")]
    model: Option<&'static str>,
    /// When the opt-in raw audio copy of this dictation is deleted (unix seconds).
    #[serde(skip_serializing_if = "Option::is_none")]
    raw_audio_expires_at: Option<u64>,
    /// Segments decoded while speaking ("Faster results"); only set when there were several.
    #[serde(skip_serializing_if = "Option::is_none")]
    pieces: Option<Vec<String>>,
    /// The app the text was pasted into; only set when "Use the app you are typing in" is on.
    #[serde(skip_serializing_if = "Option::is_none")]
    app: Option<DictationFocusedApp>,
}

#[derive(Clone, Debug, serde::Serialize)]
struct DictationFocusedApp {
    name: String,
    bundle_id: String,
}

#[derive(Clone, Debug, serde::Serialize)]
#[serde(rename_all = "snake_case")]
struct DictationSpeechCoachMetrics {
    pitch_median_hz: u16,
    pitch_range_hz: u16,
}

/// What the dictation overlay says when the shortcut could not start recording. It has room for
/// two short lines, so the long Sound-settings advice is trimmed; other messages are already short.
fn overlay_failure_text(error: &str) -> String {
    if error.starts_with("No microphone is connected") {
        "No microphone detected · connect one or choose an input in Sound settings".to_string()
    } else {
        error.chars().take(100).collect()
    }
}

/// Why a dictation attempt produced no text, for the history. Message wording decides the
/// kind because the capture and decode errors are plain strings.
fn attempt_failure_kind(message: &str) -> &'static str {
    if message.starts_with("No speech was recognized") {
        "no-speech"
    } else if message.starts_with("Audio capture")
        || message.starts_with("No audio was captured")
        || message.starts_with("Dictation exceeded")
        || message.starts_with("Dictation is not recording")
    {
        "capture-error"
    } else {
        "model-error"
    }
}

/// Event payload for a failed attempt. Takes the stored capture numbers so they are reported
/// once. Numbers and the message only, never audio or text.
#[cfg(target_os = "macos")]
fn attempt_failure_payload(
    current: &mut DictationRuntimeState,
    message: &str,
) -> serde_json::Value {
    serde_json::json!({
        "kind": attempt_failure_kind(message),
        "message": message,
        "capture": current.last_failure_capture.take(),
        "model": current.model.display_name(),
    })
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
struct DictionaryChange {
    from: String,
    to: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
struct DictationSteps {
    /// Text after smart cleanup removals; absent when smart cleanup was off.
    after_smart: Option<String>,
    dictionary_changes: Vec<DictionaryChange>,
    /// Text after dictionary, punctuation and capitalisation, before any polish.
    rules_text: String,
    /// Text after Harper's clear grammar fixes; absent when Fix grammar was off.
    grammar_text: Option<String>,
    grammar_fixes: Vec<coach_grammar::AppliedFix>,
    polished: bool,
}

#[derive(Clone, Debug, Default)]
struct CleanupOutcome {
    text: String,
    after_smart: Option<String>,
    dictionary_changes: Vec<DictionaryChange>,
}

/// A "no speech" error says how much was recorded and how loud, so a quiet microphone is
/// visible without opening any debug tool. Numbers only.
fn with_capture_numbers(message: String, capture: &dictation_quality::CaptureStats) -> String {
    if !message.starts_with("No speech was recognized") {
        return message;
    }
    let level = capture
        .level_db
        .map_or_else(|| "silent".to_string(), |db| format!("{db} dB"));
    format!(
        "{message} Recorded {:.1} s, speech found {:.1} s, loudest level {level}.",
        capture.recorded_seconds, capture.speech_seconds
    )
}

fn captured_transcript(text: String, sample_count: u64) -> Result<DictationTranscript, String> {
    if !(crate::dictation::MIN_DICTATION_SAMPLES..=crate::dictation::MAX_DICTATION_SAMPLES)
        .contains(&sample_count)
    {
        return Err(
            "Captured audio duration is outside the supported limits. Try recording again.".into(),
        );
    }
    // Capture samples are authoritative for both models; inference metadata is not
    // a duration/validity authority and may be unavailable on empty-speech results.
    let duration = sample_count as f64 / crate::dictation::DICTATION_SAMPLE_RATE as f64;
    crate::dictation::validate_transcript(&text, duration).map_err(|error| {
        match error {
            crate::dictation::TranscriptValidationError::Empty => {
                "No speech was recognized. Check the microphone and try speaking again."
            }
            crate::dictation::TranscriptValidationError::TooLong => {
                "The transcript exceeds the 256 KiB text limit. Record a shorter passage."
            }
            crate::dictation::TranscriptValidationError::InvalidDuration => {
                "Captured audio duration is outside the supported limits. Try recording again."
            }
        }
        .to_string()
    })?;
    Ok(DictationTranscript {
        text,
        translated_text: None,
        audio_duration_seconds: duration,
        capture_generation: None,
        delivery_status: None,
        capture: None,
        speech_coach_metrics: None,
        steps: None,
        model: None,
        raw_audio_expires_at: None,
        pieces: None,
        app: None,
    })
}

#[cfg(target_os = "macos")]
#[derive(Clone, serde::Serialize)]
struct DictationPreview {
    text: String,
}

#[cfg(target_os = "macos")]
static SCREENSHOT_APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

#[cfg(target_os = "macos")]
extern "C" fn screenshot_shortcut_pressed() {
    if let Some(app) = SCREENSHOT_APP.get() {
        let _ = app.emit("screenshot-requested", ());
    }
}

#[tauri::command]
fn screenshot_shortcut_configure(choice: i32, app: tauri::AppHandle) -> Result<(), String> {
    if !(0..=2).contains(&choice) {
        return Err("Choose a supported screenshot shortcut".into());
    }
    #[cfg(target_os = "macos")]
    {
        let _ = SCREENSHOT_APP.set(app);
        match unsafe {
            officekit_screenshot_shortcut_configure(choice, screenshot_shortcut_pressed)
        } {
            0 => Ok(()),
            1 => Err("Allow Accessibility access to use the screenshot shortcut".into()),
            _ => Err("The screenshot shortcut could not be enabled".into()),
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Screenshot capture shortcuts are available on macOS".into())
    }
}

#[tauri::command]
async fn screenshot_capture(app: tauri::AppHandle) -> Result<Option<String>, String> {
    #[cfg(target_os = "macos")]
    {
        use base64::Engine;
        static CAPTURING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
        if CAPTURING.swap(true, std::sync::atomic::Ordering::SeqCst) {
            return Err("Screenshot capture is already open".into());
        }
        let result = tauri::async_runtime::spawn_blocking(|| {
            let path = std::env::temp_dir().join(format!("officekit-capture-{}.png", Uuid::new_v4()));
            let result: Result<Option<String>, String> = (|| {
                let status = std::process::Command::new("/usr/sbin/screencapture")
                    .args(["-i", "-s", "-x", "-t", "png"])
                    .arg(&path).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null())
                    .status().map_err(|_| "Screenshot capture could not start".to_string())?;
                if !path.exists() {
                    if !status.success() && unsafe { officekit_dictation_screen_recording_permission_status() } != 0 {
                        return Err("Allow Screen Recording access for OfficeKit before capturing a screenshot".into());
                    }
                    return Ok(None);
                }
                let file = std::fs::File::open(&path).map_err(|_| "Screenshot could not be read".to_string())?;
                let mut bytes = Vec::new();
                file.take(64 * 1024 * 1024 + 1).read_to_end(&mut bytes).map_err(|_| "Screenshot could not be read".to_string())?;
                if bytes.is_empty() || bytes.len() > 64 * 1024 * 1024 { return Err("Screenshot exceeds the 64 MiB limit".into()); }
                Ok(Some(base64::engine::general_purpose::STANDARD.encode(bytes)))
            })();
            let _ = std::fs::remove_file(path);
            result
        }).await.map_err(|_| "Screenshot capture is unavailable".to_string());
        CAPTURING.store(false, std::sync::atomic::Ordering::SeqCst);
        let result = result??;
        if result.is_some() {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        Ok(result)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Screenshot capture is available on macOS".into())
    }
}

#[derive(Clone, serde::Serialize)]
struct DictationHotkeyStatus {
    state: HotkeyState,
    key: DictationHotkeyKey,
    custom_binding: Option<DictationCustomHotkey>,
}

fn dictation_microphone_status_for(
    permission: MicrophonePermission,
    input_available: bool,
) -> DictationMicrophoneStatus {
    let message = if permission == MicrophonePermission::Granted && !input_available {
        "No microphone detected. Connect one or choose an input in macOS Sound settings."
    } else {
        match permission {
            MicrophonePermission::Granted => "Microphone access is enabled.",
            MicrophonePermission::Undetermined => "Allow microphone access to dictate.",
            MicrophonePermission::Denied => "Allow microphone access in System Settings.",
            MicrophonePermission::Unavailable => "Microphone access is unavailable on this Mac.",
        }
    };
    DictationMicrophoneStatus {
        permission,
        message,
        input_available,
    }
}

fn dictation_accessibility_status_for(
    permission: AccessibilityPermission,
) -> DictationAccessibilityStatus {
    let message = match permission {
        AccessibilityPermission::Granted => "Accessibility access is enabled.",
        AccessibilityPermission::Denied => {
            "Allow Accessibility access to use the dictation shortcut."
        }
        AccessibilityPermission::Unavailable => "Accessibility access is unavailable on this Mac.",
    };
    DictationAccessibilityStatus {
        permission,
        message,
    }
}

fn dictation_permission_settings_url(kind: &str) -> Option<&'static str> {
    match kind {
        "microphone" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
        }
        "accessibility" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        }
        "screen" | "screen-recording" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
        }
        "calendar" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")
        }
        "storage" | "all-files" | "files" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")
        }
        "removable" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_RemovableVolume")
        }
        _ => None,
    }
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_open_permission_settings(kind: String) -> Result<(), String> {
    let url = dictation_permission_settings_url(&kind)
        .ok_or_else(|| "Unsupported permission settings page".to_string())?;
    std::process::Command::new("open")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open System Settings: {error}"))
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_open_permission_settings(_kind: String) -> Result<(), String> {
    Err("System Settings permission links are available on macOS only".to_string())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_microphone_permission() -> DictationMicrophoneStatus {
    let code = unsafe { officekit_dictation_microphone_permission_status() };
    let input_available = unsafe { officekit_dictation_has_audio_input() != 0 };
    dictation_microphone_status_for(microphone_permission_from_code(code), input_available)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_microphone_permission() -> DictationMicrophoneStatus {
    dictation_microphone_status_for(MicrophonePermission::Unavailable, false)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_request_microphone_permission() -> DictationMicrophoneStatus {
    let code = unsafe { officekit_dictation_request_microphone_permission() };
    let input_available = unsafe { officekit_dictation_has_audio_input() != 0 };
    dictation_microphone_status_for(microphone_permission_from_code(code), input_available)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_request_microphone_permission() -> DictationMicrophoneStatus {
    dictation_microphone_status_for(MicrophonePermission::Unavailable, false)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_accessibility_permission() -> DictationAccessibilityStatus {
    let code = unsafe { officekit_dictation_accessibility_status() };
    dictation_accessibility_status_for(accessibility_permission_from_code(code))
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_accessibility_permission() -> DictationAccessibilityStatus {
    dictation_accessibility_status_for(AccessibilityPermission::Unavailable)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_request_accessibility_permission() -> DictationAccessibilityStatus {
    let code = unsafe { officekit_dictation_request_accessibility_permission() };
    dictation_accessibility_status_for(accessibility_permission_from_code(code))
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_request_accessibility_permission() -> DictationAccessibilityStatus {
    dictation_accessibility_status_for(AccessibilityPermission::Unavailable)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_capture_start(
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationCaptureStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation capture is unavailable".to_string())?;
    if current.hotkey_state != HotkeyState::Disabled {
        return Err("Disable the push-to-talk shortcut before starting an in-app recording".into());
    }
    start_capture_locked(&mut current)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_capture_start() -> Result<DictationCaptureStatus, String> {
    Err("Local dictation capture is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
struct ClearNativeDictationSamples;

#[cfg(target_os = "macos")]
impl Drop for ClearNativeDictationSamples {
    fn drop(&mut self) {
        unsafe { officekit_dictation_clear_samples() };
    }
}

#[cfg(target_os = "macos")]
fn speech_model_available(current: &DictationRuntimeState) -> bool {
    matches!(
        current.model_state,
        ModelState::Installed | ModelState::Ready
    ) && current.engine.is_some()
}

#[cfg(target_os = "macos")]
fn mark_speech_model_failed(
    current: &mut DictationRuntimeState,
    failed: &Arc<Mutex<speech_model::SpeechModel<DictationEngine>>>,
) -> Option<bool> {
    if !speech_model_available(current)
        || !current
            .engine
            .as_ref()
            .is_some_and(|engine| Arc::ptr_eq(engine, failed))
    {
        return None;
    }
    current.model_state = ModelState::Failed;
    let meeting = current.meeting_recording;
    if meeting {
        current.meeting_recording = false;
        current.set_capture_active(false);
        current.meeting_stop_tx = None;
    }
    Some(meeting)
}

#[cfg(target_os = "macos")]
fn report_speech_model_failure(
    app: &tauri::AppHandle,
    failed: &Arc<Mutex<speech_model::SpeechModel<DictationEngine>>>,
    message: &str,
    duration_seconds: f64,
) {
    let runtime = app.state::<DictationRuntime>();
    let meeting = {
        let Ok(mut current) = runtime.0.lock() else {
            return;
        };
        let Some(meeting) = mark_speech_model_failed(&mut current, failed) else {
            return;
        };
        if meeting {
            unsafe {
                officekit_dictation_stop_capture();
                officekit_dictation_clear_samples();
            }
        }
        meeting
    };
    // Release DictationRuntime before taking CoachRuntime or notifying the UI.
    if let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() {
        speech_coach::stop_for_model_failure(&coach);
    }
    if meeting {
        let _ = app.emit(
            "dictation-meeting-stopped",
            DictationMeetingProgress { duration_seconds },
        );
    }
    let _ = app.emit(
        "dictation-error",
        serde_json::json!({"speech_model":true,"meeting":meeting,"message":message}),
    );
}

#[cfg(target_os = "macos")]
fn register_deferred_speech_model(current: &mut DictationRuntimeState) -> Result<(), String> {
    if current.model_state != ModelState::Installed || current.engine.is_some() {
        return Ok(());
    }
    let model = current.model;
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "The local model folder is unavailable".to_string())?;
    let path = model_cache_directory(&home, model);
    register_deferred_speech_model_from_cache(current, path)
}

#[cfg(target_os = "macos")]
fn register_deferred_speech_model_from_cache(
    current: &mut DictationRuntimeState,
    path: std::path::PathBuf,
) -> Result<(), String> {
    let model = current.model;
    if !model_files_present_for(&path, model) {
        current.model_state = ModelState::NotInstalled;
        return Err("Prepare the selected local speech model before recording".into());
    }
    // Captures only the model ID/path, never AppHandle (which would retain its own runtime).
    current.engine = Some(Arc::new(Mutex::new(speech_model::SpeechModel::deferred(
        move || load_cached_speech_model(model, &path),
    ))));
    Ok(())
}

#[cfg(target_os = "macos")]
pub(crate) fn register_speech_model(app: &tauri::AppHandle) -> Result<(), String> {
    let runtime = app.state::<DictationRuntime>();
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation model is unavailable".to_string())?;
    register_deferred_speech_model(&mut current)
}

#[cfg(target_os = "macos")]
fn load_cached_speech_model(
    model: DictationModel,
    path: &std::path::Path,
) -> Result<DictationEngine, String> {
    if !model_files_present_for(path, model) {
        return Err(
            "The cached speech model is incomplete. Prepare it again before recording".into(),
        );
    }
    if let Some(filename) = model.whisper_filename() {
        let home = std::env::var_os("HOME")
            .map(std::path::PathBuf::from)
            .ok_or_else(|| "The local model folder is unavailable".to_string())?;
        let model_path = verified_cached_whisper_file(
            &home.join("Library/Application Support/OfficeKit/Models"),
            path,
            filename,
            model
                .whisper_file_size()
                .ok_or_else(|| "The selected model has no expected size".to_string())?,
            model
                .whisper_sha256()
                .ok_or_else(|| "The selected model has no integrity checksum".to_string())?,
        )?;
        return WhisperContext::new_with_params(
            model_path.to_string_lossy().as_ref(),
            WhisperContextParameters::default(),
        )
        .map(DictationEngine::Whisper)
        .map_err(|_| "Could not load this Whisper model on this Mac".to_string());
    }
    let engine = FluidAudio::new().map_err(|_| "Could not initialize local speech".to_string())?;
    match model {
        DictationModel::ParakeetV2 => engine.init_asr_version_cached(2, path),
        DictationModel::ParakeetV3 => engine.init_asr_version_cached(3, path),
        DictationModel::Qwen3Asr => engine.init_qwen3_asr_cached(path),
        _ => return Err("The selected speech engine is unavailable".into()),
    }
    .map_err(|_| "Could not load the cached local speech model. Prepare it again".to_string())?;
    Ok(DictationEngine::Fluid(engine))
}

#[cfg(target_os = "macos")]
fn verified_cached_whisper_file(
    root: &std::path::Path,
    directory: &std::path::Path,
    filename: &str,
    expected_bytes: u64,
    expected_sha256: &str,
) -> Result<std::path::PathBuf, String> {
    if !path_is_safe_model_child(root, directory) {
        return Err("The local model folder is not safe to use".into());
    }
    let path = directory.join(filename);
    let metadata = std::fs::symlink_metadata(&path)
        .map_err(|_| "Could not verify the local model file".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() != expected_bytes
    {
        return Err("The cached Whisper model is incomplete or unsafe".into());
    }
    if sha256_file(&path).as_deref() != Ok(expected_sha256) {
        return Err(
            "The cached Whisper model failed integrity verification. Prepare it again".into(),
        );
    }
    Ok(path)
}

#[cfg(target_os = "macos")]
fn start_capture_locked(
    current: &mut DictationRuntimeState,
) -> Result<DictationCaptureStatus, String> {
    register_deferred_speech_model(current)?;
    let permission = microphone_permission_from_code(unsafe {
        officekit_dictation_microphone_permission_status()
    });
    if let Err(error) = capture_start_allowed(
        current.model_state,
        current.engine.is_some(),
        permission,
        current.capture_active,
    ) {
        return Err(match error {
            CaptureStartError::ModelNotReady => "Prepare the local speech model before recording",
            CaptureStartError::PermissionDenied => "Allow microphone access before recording",
            CaptureStartError::AlreadyActive => "Dictation is already recording",
            CaptureStartError::Unavailable => "The microphone is unavailable",
            CaptureStartError::NoInputDevice => "No microphone is connected. Connect a microphone and select it in macOS Sound settings.",
        }
        .into());
    }
    let code = unsafe { officekit_dictation_start_capture() };
    if let Some(error) = capture_start_error_from_code(code) {
        return Err(match error {
            CaptureStartError::ModelNotReady => "Prepare the local speech model before recording",
            CaptureStartError::AlreadyActive => "Dictation is already recording",
            CaptureStartError::PermissionDenied => "Allow microphone access before recording",
            CaptureStartError::Unavailable => "The microphone could not start recording",
            CaptureStartError::NoInputDevice => "No microphone is connected. Connect a microphone and select it in macOS Sound settings.",
        }
        .into());
    }
    current.set_capture_active(true);
    // Speech Coach coaches this dictation; it leaves again when the dictation stops.
    if speech_coach::attach_on_dictation() {
        let _ = unsafe { officekit_dictation_coach_start_for_dictation() };
    }
    let generation = unsafe { officekit_dictation_overlay_generation() };
    current.clear_focus_context();
    if let Ok(mut commit) = current.commit_state.lock() {
        commit.reset(generation);
    }
    // Field text is only useful to the optional on-device rewrite, so it is not read
    // unless that is on as well.
    let options = dictation_quality::ContextOptions {
        field_text: current.context_options.field_text && current.llm_polish,
        ..current.context_options
    };
    if options.wants_context() {
        let slot = Arc::clone(&current.focus_context);
        thread::spawn(move || {
            let context = read_focus_context(options);
            // A newer capture may have started or this one been cancelled meanwhile.
            if unsafe { officekit_dictation_overlay_generation() } == generation {
                if let Ok(mut stored) = slot.lock() {
                    *stored = context;
                }
            }
        });
    }
    Ok(DictationCaptureStatus { state: "recording" })
}

/// While the user is still speaking, decode any finished phrase that ends in a
/// pause so key release only has the last phrase left to decode. Every failure
/// leaves the audio uncommitted, and the final pass decodes it as before.
#[cfg(target_os = "macos")]
fn commit_ready_segment(app: &tauri::AppHandle, generation: u64) {
    let Some(runtime) = app.try_state::<DictationRuntime>() else {
        return;
    };
    let (model, language, prompt, engine, commit_state) = {
        let Ok(current) = runtime.0.lock() else {
            return;
        };
        if !current.capture_active || !current.streaming_commit || current.translate_to_english {
            return;
        }
        let Some(engine) = current.engine.clone() else {
            return;
        };
        (
            current.model,
            current.spoken_language.clone(),
            dictation_quality::build_initial_prompt(
                &current.vocabulary_terms,
                current.focus_app_name().as_deref(),
            ),
            engine,
            Arc::clone(&current.commit_state),
        )
    };
    let (committed_end, next_try_at) = {
        let Ok(state) = commit_state.lock() else {
            return;
        };
        if state.generation() != generation {
            return;
        }
        (state.committed_end(), state.next_try_at())
    };
    let available = unsafe { officekit_dictation_sample_count() } as usize;
    if available < (committed_end + dictation_quality::COMMIT_MIN_PENDING_SAMPLES).max(next_try_at)
    {
        return;
    }
    let mut pending = vec![0.0_f32; available - committed_end];
    let copied = unsafe {
        officekit_dictation_copy_samples_range(
            pending.as_mut_ptr(),
            committed_end as u64,
            pending.len() as u64,
        )
    };
    if copied != pending.len() as u64 {
        pending.fill(0.0);
        return;
    }
    let Some(cut) = dictation_quality::find_commit_boundary(&pending) else {
        pending.fill(0.0);
        return;
    };
    let result = engine.lock().ok().map(|mut engine| {
        transcribe_samples_buffer(
            &mut engine,
            model,
            &pending[..cut],
            false,
            language.as_deref(),
            prompt.as_deref(),
        )
    });
    // A decode with far fewer words than the speech holds lost some. Leave the audio
    // uncommitted so the release decode (or a later segment) covers it, never drop it.
    let trusted = matches!(&result, Some(Ok(text))
        if dictation_quality::decode_is_plausible(&pending[..cut], text));
    if let (true, Some(Ok(text))) = (trusted, &result) {
        if let Ok(mut state) = commit_state.lock() {
            state.commit(generation, committed_end, committed_end + cut, text);
        }
    } else if let Ok(mut state) = commit_state.lock() {
        state.reject(generation, available);
    }
    pending.fill(0.0);
}

/// Best-effort read of the focused app and field. Any failure means no context.
#[cfg(target_os = "macos")]
fn read_focus_context(
    options: dictation_quality::ContextOptions,
) -> Option<dictation_quality::FocusContext> {
    if !options.wants_context() {
        return None;
    }
    let mut buffer = vec![0_u8; dictation_quality::FOCUS_CONTEXT_BUFFER_BYTES];
    let written = unsafe {
        officekit_dictation_focus_context(
            i32::from(options.field_text),
            buffer.as_mut_ptr(),
            buffer.len() as u64,
        )
    };
    let context = usize::try_from(written)
        .ok()
        .filter(|length| *length > 0 && *length <= buffer.len())
        .and_then(|length| dictation_quality::parse_focus_context(&buffer[..length]))
        .and_then(|context| context.filtered(options));
    buffer.fill(0);
    context
}

#[cfg(target_os = "macos")]
fn stop_capture_locked(current: &mut DictationRuntimeState) -> Result<DictationTranscript, String> {
    current.last_failure_capture = None;
    if !current.capture_active {
        return Err("Dictation is not recording".into());
    }
    let stop_code = unsafe { officekit_dictation_stop_capture() };
    current.set_capture_active(false);
    let _clear_samples = ClearNativeDictationSamples;
    if let Some(error) = capture_stop_error_from_code(stop_code) {
        return Err(match error {
            CaptureStopError::NotActive => "Dictation is not recording",
            CaptureStopError::DeviceFailure => "Audio capture failed; please try again",
            CaptureStopError::TooLong => "Dictation exceeded the five-minute limit",
            CaptureStopError::NoSamples => "No audio was captured; please try again",
        }
        .into());
    }

    let sample_count = unsafe { officekit_dictation_sample_count() };
    let mut samples = collect_audio_samples(sample_count, |output| unsafe {
        officekit_dictation_copy_samples(output.as_mut_ptr(), output.len() as u64)
    })
    .map_err(|_| "Audio capture was empty, incomplete, or outside supported limits".to_string())?;

    let prompt = dictation_quality::build_initial_prompt(
        &current.vocabulary_terms,
        current.focus_app_name().as_deref(),
    );
    let mut decoded_pieces: Vec<String> = Vec::new();
    let (result, translated_text): (Result<String, String>, Option<String>) =
        match current.engine.as_ref() {
            Some(engine) => match engine.lock() {
                Ok(mut engine) => {
                    // Read what was committed while speaking only after taking the
                    // engine: an in-flight background decode finishes first.
                    let (committed_text, committed_samples, committed_pieces) =
                        if current.streaming_commit && !current.translate_to_english {
                            current
                                .commit_state
                                .lock()
                                .map(|state| {
                                    (
                                        state.committed_text(),
                                        state.committed_end(),
                                        state.pieces(),
                                    )
                                })
                                .unwrap_or_default()
                        } else {
                            (String::new(), 0, Vec::new())
                        };
                    let committed_samples = committed_samples.min(samples.len());
                    decoded_pieces = committed_pieces;
                    let mut source = transcribe_samples_buffer(
                        &mut engine,
                        current.model,
                        &samples[committed_samples..],
                        false,
                        current.spoken_language.as_deref(),
                        prompt.as_deref(),
                    )
                    .map(|tail| {
                        if !tail.trim().is_empty() {
                            decoded_pieces.push(tail.trim().to_string());
                        }
                        dictation_quality::join_committed(&committed_text, &tail)
                    });
                    let lost_words = source
                        .as_ref()
                        .is_ok_and(|text| !dictation_quality::decode_is_plausible(&samples, text));
                    if (source.is_err() || lost_words) && committed_samples > 0 {
                        decoded_pieces.clear();
                        // The shortcut failed or lost words; decode the whole recording as before.
                        source = transcribe_samples_buffer(
                            &mut engine,
                            current.model,
                            &samples,
                            false,
                            current.spoken_language.as_deref(),
                            prompt.as_deref(),
                        );
                    }
                    match source {
                        Ok(source) if current.translate_to_english => {
                            let translated = transcribe_samples_buffer(
                                &mut engine,
                                current.model,
                                &samples,
                                true,
                                current.spoken_language.as_deref(),
                                prompt.as_deref(),
                            )
                            .ok();
                            (
                                Ok(source),
                                translated.filter(|text| !text.trim().is_empty()),
                            )
                        }
                        result => (result, None),
                    }
                }
                Err(_) => (
                    Err("Local transcription is busy; please try again".to_string()),
                    None,
                ),
            },
            None => (Err("The local speech model is not ready".to_string()), None),
        };
    let capture = dictation_quality::capture_stats(&samples);
    // Opt-in troubleshooting copy. A failed write never fails the dictation.
    let raw_audio_expires_at = current
        .raw_audio_directory
        .as_deref()
        .zip(unix_now())
        .and_then(|(directory, now)| raw_audio::save(directory, &samples, now).ok());
    // The coach that joined this dictation has already left, so ask whether it was coaching.
    let speech_coach_metrics = (speech_coach::attach_on_dictation()
        || unsafe { officekit_dictation_coach_is_active() } == 1)
        .then(|| speech_coach::estimate_recording_pitch_stats(&samples, 16_000))
        .flatten()
        .map(|pitch| DictationSpeechCoachMetrics {
            pitch_median_hz: pitch.median_hz,
            pitch_range_hz: pitch.range_hz,
        });
    samples.fill(0.0);
    // The committed transcript has been joined into `result`; do not keep a copy.
    if let Ok(mut commit) = current.commit_state.lock() {
        *commit = dictation_quality::CommitState::default();
    }
    let outcome = result.and_then(|text| {
        captured_transcript(text, sample_count)
            .map_err(|message| with_capture_numbers(message, &capture))
    });
    match outcome {
        Ok(mut transcript) => {
            transcript.translated_text = translated_text;
            transcript.capture = Some(capture);
            transcript.speech_coach_metrics = speech_coach_metrics;
            transcript.model = Some(current.model.display_name());
            transcript.raw_audio_expires_at = raw_audio_expires_at;
            transcript.pieces = (decoded_pieces.len() > 1).then_some(decoded_pieces);
            Ok(transcript)
        }
        Err(message) => {
            current.last_failure_capture = Some(capture);
            Err(message)
        }
    }
}

#[cfg(target_os = "macos")]
fn decode_audio_file_to_samples(path: &std::path::Path) -> Result<Vec<f32>, String> {
    use std::os::unix::fs::PermissionsExt;

    const MAX_INPUT_BYTES: u64 = 64 * 1024 * 1024;
    const MAX_PCM_BYTES: u64 = DICTATION_SAMPLE_RATE * 60 * 5 * 4 + 4096;
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| "Could not read the selected audio file".to_string())?;
    let extension = path
        .extension()
        .and_then(std::ffi::OsStr::to_str)
        .unwrap_or("")
        .to_ascii_lowercase();
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_INPUT_BYTES
        || !matches!(extension.as_str(), "wav" | "mp3" | "m4a")
    {
        return Err("Choose a non-empty WAV, MP3, or M4A audio file no larger than 64 MiB".into());
    }

    let work_dir = std::env::temp_dir().join(format!("officekit-audio-{}", Uuid::new_v4()));
    std::fs::create_dir(&work_dir)
        .map_err(|_| "Could not prepare temporary audio processing".to_string())?;
    std::fs::set_permissions(&work_dir, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| "Could not secure temporary audio processing".to_string())?;
    let wav_path = work_dir.join("decoded.wav");
    let result = (|| {
        let mut child = Command::new("/usr/bin/afconvert")
            .arg(path)
            .arg(&wav_path)
            .args(["-f", "WAVE", "-d", "LEF32@16000", "-c", "1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "macOS could not open this audio format".to_string())?;
        let started = Instant::now();
        loop {
            if let Some(status) = child
                .try_wait()
                .map_err(|_| "Audio decoding failed".to_string())?
            {
                if !status.success() {
                    return Err(
                        "This audio file could not be decoded. Try a WAV, MP3, or M4A file.".into(),
                    );
                }
                break;
            }
            if started.elapsed() > Duration::from_secs(120)
                || std::fs::metadata(&wav_path)
                    .map(|entry| entry.len() > MAX_PCM_BYTES)
                    .unwrap_or(false)
            {
                let _ = child.kill();
                let _ = child.wait();
                return Err("This audio file exceeds the five-minute processing limit".into());
            }
            thread::sleep(Duration::from_millis(100));
        }
        let metadata = std::fs::metadata(&wav_path)
            .map_err(|_| "Audio decoding did not produce audio samples".to_string())?;
        if metadata.len() > MAX_PCM_BYTES {
            return Err("This audio file exceeds the five-minute processing limit".into());
        }
        let bytes =
            std::fs::read(&wav_path).map_err(|_| "Could not read the decoded audio".to_string())?;
        parse_mono_f32_wav(&bytes)
    })();
    let _ = std::fs::remove_dir_all(&work_dir);
    result
}

#[cfg(target_os = "macos")]
fn parse_mono_f32_wav(bytes: &[u8]) -> Result<Vec<f32>, String> {
    if bytes.len() < 44 || &bytes[..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return Err("The selected audio could not be decoded to supported PCM".into());
    }
    let mut offset = 12usize;
    let mut format_ok = false;
    let mut data_range = None;
    while offset + 8 <= bytes.len() {
        let id = &bytes[offset..offset + 4];
        let size = u32::from_le_bytes(bytes[offset + 4..offset + 8].try_into().unwrap()) as usize;
        let start = offset + 8;
        let end = start
            .checked_add(size)
            .filter(|end| *end <= bytes.len())
            .ok_or_else(|| "The decoded audio file is truncated".to_string())?;
        if id == b"fmt " && size >= 16 {
            let chunk = &bytes[start..end];
            format_ok = u16::from_le_bytes(chunk[0..2].try_into().unwrap()) == 3
                && u16::from_le_bytes(chunk[2..4].try_into().unwrap()) == 1
                && u32::from_le_bytes(chunk[4..8].try_into().unwrap())
                    == DICTATION_SAMPLE_RATE as u32
                && u16::from_le_bytes(chunk[14..16].try_into().unwrap()) == 32;
        } else if id == b"data" {
            data_range = Some(start..end);
        }
        offset = end + (size & 1);
    }
    let range = data_range
        .filter(|range| {
            range.len() >= (DICTATION_SAMPLE_RATE / 10 * 4) as usize && range.len() % 4 == 0
        })
        .ok_or_else(|| "The audio file is empty or shorter than 0.1 seconds".to_string())?;
    let max_samples = (DICTATION_SAMPLE_RATE * 60 * 5) as usize;
    if !format_ok || range.len() / 4 > max_samples {
        return Err(
            "This audio file is not valid 16 kHz mono audio or exceeds five minutes".into(),
        );
    }
    let mut samples = Vec::with_capacity(range.len() / 4);
    for chunk in bytes[range].chunks_exact(4) {
        let sample = f32::from_le_bytes(chunk.try_into().unwrap());
        if !sample.is_finite() {
            samples.fill(0.0);
            return Err("The audio contains invalid sample data".into());
        }
        samples.push(sample.clamp(-1.0, 1.0));
    }
    Ok(samples)
}

#[cfg(target_os = "macos")]
#[tauri::command]
async fn dictation_transcribe_audio_file(
    app: tauri::AppHandle,
) -> Result<DictationTranscript, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app
            .dialog()
            .file()
            .set_title("Choose audio to transcribe")
            .add_filter("Audio", &["wav", "mp3", "m4a"])
            .blocking_pick_file();
        let Some(selected) = selected else {
            return Err("Audio selection canceled".into());
        };
        let path = selected
            .into_path()
            .map_err(|_| "Choose a local audio file".to_string())?;
        let runtime = app.state::<DictationRuntime>();
        let (model, translate, language, prompt, engine) = {
            let mut current = runtime
                .0
                .lock()
                .map_err(|_| "Dictation model is unavailable".to_string())?;
            register_deferred_speech_model(&mut current)?;
            if !speech_model_available(&current) {
                return Err(
                    "Prepare the selected local speech model before transcribing audio".into(),
                );
            }
            if current.capture_active || current.meeting_recording {
                return Err("Stop the current recording before transcribing an audio file".into());
            }
            (
                current.model,
                current.translate_to_english,
                current.spoken_language.clone(),
                dictation_quality::build_initial_prompt(&current.vocabulary_terms, None),
                Arc::clone(current.engine.as_ref().unwrap()),
            )
        };
        let mut samples = decode_audio_file_to_samples(&path)?;
        let count = samples.len() as u64;
        let (result, translated) = match engine.lock() {
            Ok(mut engine) => {
                let source = transcribe_samples_buffer(
                    &mut engine,
                    model,
                    &samples,
                    false,
                    language.as_deref(),
                    prompt.as_deref(),
                );
                match source {
                    Ok(text) if translate => {
                        let translated = transcribe_samples_buffer(
                            &mut engine,
                            model,
                            &samples,
                            true,
                            language.as_deref(),
                            prompt.as_deref(),
                        )
                        .ok()
                        .filter(|text| !text.trim().is_empty());
                        (Ok(text), translated)
                    }
                    other => (other, None),
                }
            }
            Err(_) => (Err("Local transcription is busy; try again".into()), None),
        };
        samples.fill(0.0);
        let mut transcript = captured_transcript(result?, count)?;
        transcript.translated_text = translated;
        Ok(transcript)
    })
    .await
    .map_err(|_| "Audio transcription stopped unexpectedly".to_string())?
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
async fn dictation_transcribe_audio_file() -> Result<DictationTranscript, String> {
    Err("Local audio transcription is available in the macOS desktop app".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_capture_stop(
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationTranscript, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation capture is unavailable".to_string())?;
    stop_capture_locked(&mut current)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_capture_stop() -> Result<DictationTranscript, String> {
    Err("Local dictation capture is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
async fn quick_access_transcribe(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let runtime = app.state::<DictationRuntime>();
        let mut current = runtime
            .0
            .lock()
            .map_err(|_| "Dictation capture is unavailable".to_string())?;
        quick_capture_preflight(
            current.capture_active,
            current.tray_capture_generation.is_some(),
            current.meeting_recording,
            current.hotkey_state != HotkeyState::Disabled,
        )?;
        if current.capture_active {
            let Some(generation) = current.tray_capture_generation.take() else {
                return Err(
                    "Stop the current recording in OfficeKit before starting quick dictation"
                        .into(),
                );
            };
            let _ = workspace_native::quick_access_recording(app.clone(), false);
            if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                unsafe {
                    officekit_dictation_stop_capture();
                    officekit_dictation_clear_samples();
                }
                current.set_capture_active(false);
                current.clear_session_text();
                return Err("Dictation cancelled; no text was pasted.".into());
            }
            unsafe { officekit_dictation_overlay_processing(generation) };
            match stop_capture_locked(&mut current) {
                Ok(mut transcript) => {
                    if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                        return Err("Dictation cancelled; no text was pasted.".into());
                    }
                    transcript.capture_generation = Some(generation);
                    app.emit("dictation-transcript", transcript).map_err(|_| {
                        "The transcript could not be delivered to OfficeKit".to_string()
                    })?;
                    Ok(serde_json::json!({"recording":false}))
                }
                Err(error) => {
                    unsafe { officekit_dictation_overlay_finish(generation) };
                    let failure = attempt_failure_payload(&mut current, &error);
                    let _ = app.emit("dictation-attempt-failed", failure);
                    Err(error)
                }
            }
        } else {
            let generation = unsafe { officekit_dictation_overlay_begin() };
            if let Err(error) = start_capture_locked(&mut current) {
                unsafe { officekit_dictation_overlay_finish(generation) };
                return Err(error);
            }
            current.tray_capture_generation = Some(generation);
            drop(current);
            let _ = workspace_native::quick_access_recording(app.clone(), true);
            let preview_app = app.clone();
            let _ = thread::Builder::new()
                .name("officekit-tray-preview".into())
                .spawn(move || run_dictation_preview(preview_app, generation));
            Ok(serde_json::json!({"recording":true}))
        }
    })
    .await
    .map_err(|_| "Quick dictation is unavailable".to_string())?
}

fn quick_capture_preflight(
    capture_active: bool,
    has_target: bool,
    meeting: bool,
    shortcut: bool,
) -> Result<bool, String> {
    if meeting {
        return Err("Stop the meeting recording before using quick dictation".into());
    }
    if shortcut {
        return Err(
            "Use the enabled push-to-talk shortcut, or turn it off before starting quick dictation"
                .into(),
        );
    }
    if capture_active && !has_target {
        return Err(
            "Stop the current recording in OfficeKit before starting quick dictation".into(),
        );
    }
    Ok(capture_active)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
async fn quick_access_transcribe() -> Result<serde_json::Value, String> {
    Err("Local dictation is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
fn transcribe_samples_buffer(
    engine: &mut speech_model::SpeechModel<DictationEngine>,
    model: DictationModel,
    samples: &[f32],
    translate_to_english: bool,
    spoken_language: Option<&str>,
    initial_prompt: Option<&str>,
) -> Result<String, String> {
    let trimmed = dictation_quality::trim_silence(samples);
    if !trimmed.had_speech {
        return Ok(String::new());
    }
    let samples = &samples[trimmed.range];
    let engine = engine.get_or_load()?;
    match model {
        DictationModel::Qwen3Asr => match engine {
            DictationEngine::Fluid(engine) => transcribe_qwen3_chunks(samples, |chunk| {
                engine
                    .qwen3_transcribe_samples(chunk, None)
                    .map(|result| result.text)
                    .map_err(|_| "Local Qwen3 transcription failed".to_string())
            }),
            DictationEngine::Whisper(_) => Err("The selected speech engine is unavailable".into()),
        },
        DictationModel::WhisperTiny
        | DictationModel::WhisperBase
        | DictationModel::WhisperSmall
        | DictationModel::WhisperMedium
        | DictationModel::WhisperLargeV3
        | DictationModel::WhisperLargeV3Turbo
        | DictationModel::WhisperLargeV3TurboQ5 => match engine {
            DictationEngine::Whisper(context) => {
                if translate_to_english && !model.whisper_supports_english_translation() {
                    return Err(
                        "Choose Whisper Medium or Large v3 to translate speech into English".into(),
                    );
                }
                let mut state = context
                    .create_state()
                    .map_err(|_| "Could not start the local Whisper decoder".to_string())?;
                let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
                params.set_n_threads(
                    std::thread::available_parallelism()
                        .map(|parallelism| parallelism.get())
                        .unwrap_or(4)
                        .clamp(1, 8) as i32,
                );
                params.set_no_context(true);
                params.set_no_timestamps(true);
                params.set_translate(translate_to_english);
                params.set_language(spoken_language);
                if let Some(prompt) = initial_prompt {
                    params.set_initial_prompt(prompt);
                }
                params.set_print_progress(false);
                params.set_print_realtime(false);
                params.set_print_timestamps(false);
                state
                    .full(params, samples)
                    .map_err(|_| "Local Whisper transcription failed".to_string())?;
                Ok(state
                    .as_iter()
                    .map(|segment| segment.to_string())
                    .collect::<String>()
                    .trim()
                    .to_string())
            }
            DictationEngine::Fluid(_) => Err("The selected speech engine is unavailable".into()),
        },
        DictationModel::ParakeetV2 | DictationModel::ParakeetV3 => match engine {
            _ if translate_to_english => {
                Err("The selected speech model cannot translate audio".into())
            }
            DictationEngine::Fluid(engine) => engine
                .transcribe_samples(samples)
                .map(|result| result.text)
                .map_err(|_| "Local transcription failed".to_string()),
            DictationEngine::Whisper(_) => Err("The selected speech engine is unavailable".into()),
        },
    }
}

#[cfg(target_os = "macos")]
fn run_dictation_preview(app: tauri::AppHandle, generation: u64) {
    let mut processed_samples = 0_u64;
    let mut transcript_chunks = Vec::new();
    loop {
        thread::sleep(Duration::from_millis(200));
        if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
            // Reuse the existing preview polling lifecycle. Only its own cancelled
            // tray capture may be stopped; stale previews cannot stop a newer one.
            if let Some(runtime) = app.try_state::<DictationRuntime>() {
                if let Ok(mut current) = runtime.0.lock() {
                    if current.capture_active && current.tray_capture_generation == Some(generation)
                    {
                        unsafe {
                            officekit_dictation_stop_capture();
                            officekit_dictation_clear_samples();
                        }
                        current.set_capture_active(false);
                        current.clear_session_text();
                        current.tray_capture_generation = None;
                        let _ = workspace_native::quick_access_recording(app.clone(), false);
                        let _ = app.emit(
                            "quick-access-recording",
                            serde_json::json!({"recording":false}),
                        );
                        let _ = app.emit(
                            "dictation-error",
                            "Dictation cancelled; no text was pasted.",
                        );
                    }
                }
            }
            break;
        }
        let capture_is_active = app
            .try_state::<DictationRuntime>()
            .and_then(|runtime| runtime.0.lock().ok().map(|current| current.capture_active))
            .unwrap_or(false);
        if !capture_is_active {
            break;
        }
        commit_ready_segment(&app, generation);
        let available_samples = unsafe { officekit_dictation_sample_count() };
        let Some(range) = dictation_preview_range(processed_samples, available_samples) else {
            continue;
        };
        let mut samples = vec![0.0_f32; range.end - range.start];
        let copied = unsafe {
            officekit_dictation_copy_samples_range(
                samples.as_mut_ptr(),
                range.start as u64,
                samples.len() as u64,
            )
        };
        if copied != samples.len() as u64 {
            samples.fill(0.0);
            processed_samples = available_samples;
            continue;
        }
        let Some(runtime) = app.try_state::<DictationRuntime>() else {
            samples.fill(0.0);
            break;
        };
        let Ok(current) = runtime.0.lock() else {
            samples.fill(0.0);
            break;
        };
        if !current.capture_active {
            samples.fill(0.0);
            break;
        }
        let model = current.model;
        let spoken_language = current.spoken_language.clone();
        let prompt = dictation_quality::build_initial_prompt(
            &current.vocabulary_terms,
            current.focus_app_name().as_deref(),
        );
        let engine = current.engine.clone();
        let commit_state = Arc::clone(&current.commit_state);
        drop(current);
        let result = engine.and_then(|engine| {
            engine.lock().ok().map(|mut engine| {
                transcribe_samples_buffer(
                    &mut engine,
                    model,
                    &samples,
                    false,
                    spoken_language.as_deref(),
                    prompt.as_deref(),
                )
            })
        });
        let coach_pitch = app
            .try_state::<speech_coach::CoachRuntime>()
            .and_then(|coach| {
                speech_coach::current_status(&coach)
                    .ok()
                    .filter(|status| status.settings.enabled && !status.settings.paused)
                    .and_then(|_| speech_coach::estimate_pitch_stats(&samples, 16_000))
            });
        if let Some(pitch) = coach_pitch {
            unsafe {
                officekit_dictation_coach_pitch_stats(pitch.median_hz, pitch.range_hz, generation)
            };
        }
        samples.fill(0.0);
        processed_samples = available_samples;
        let Some(Ok(text)) = result else { continue };
        let text = text.trim();
        if text.is_empty() || unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
            continue;
        }
        let Ok(current) = runtime.0.lock() else { break };
        if !current.capture_active {
            break;
        }
        transcript_chunks.push(text.to_string());
        let preview = merge_qwen3_transcript_chunks(&transcript_chunks);
        unsafe {
            officekit_dictation_overlay_transcript(
                preview.as_ptr(),
                preview.len() as u64,
                generation,
            )
        };
        let finalized_text = commit_state
            .lock()
            .ok()
            .map(|state| state.committed_text())
            .unwrap_or_default();
        if !finalized_text.is_empty() {
            if let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() {
                let voiced_seconds = unsafe { officekit_dictation_coach_speech_seconds() };
                let mut workspace_pace = None;
                if let Some((pace, target_min, target_max)) =
                    speech_coach::pace_reading(&coach, &finalized_text, voiced_seconds)
                {
                    workspace_pace = Some(pace);
                    unsafe {
                        officekit_dictation_coach_pace(pace, target_min, target_max, generation)
                    };
                }
                // Speech Coach shows corrections and improvements in the private Live Workspace as you speak.
                if speech_coach::attach_on_dictation() {
                    coach_workspace::open_for_dictation(&app, generation);
                    if let Some(workspace) =
                        app.try_state::<coach_workspace::CoachWorkspaceRuntime>()
                    {
                        if workspace.record_transcript(generation, &finalized_text, workspace_pace)
                        {
                            pump_coach_workspace_checks(&app);
                        }
                    }
                }
                if let Some(cue) = speech_coach::live_cue(&coach, &finalized_text, voiced_seconds) {
                    unsafe {
                        officekit_dictation_coach_cue(cue.as_ptr(), cue.len() as u64, generation)
                    };
                }
                queue_speech_coach_language_suggestion(
                    &app,
                    &coach,
                    &finalized_text,
                    generation,
                    true,
                    None,
                );
            }
        }
        let _ = app.emit("dictation-preview", DictationPreview { text: preview });
    }
}

#[cfg(target_os = "macos")]
const COACH_ANALYSIS_MAX_SAMPLES: usize = 15 * 16_000;

#[cfg(target_os = "macos")]
fn queue_speech_coach_language_suggestion(
    app: &tauri::AppHandle,
    coach: &speech_coach::CoachRuntime,
    transcript: &str,
    capture_generation: u64,
    requires_active_dictation: bool,
    standalone_epoch: Option<u64>,
) {
    if SPEECH_COACH_LANGUAGE_SUGGESTION_PENDING
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return;
    }
    let Some((focus, sentence)) = speech_coach::reserve_language_suggestion(coach, transcript)
    else {
        SPEECH_COACH_LANGUAGE_SUGGESTION_PENDING.store(false, Ordering::Release);
        return;
    };
    let app = app.clone();
    thread::spawn(move || {
        let focus_code = match focus {
            speech_coach::CoachFocus::Grammar => 1,
            speech_coach::CoachFocus::Vocabulary => 2,
            _ => {
                SPEECH_COACH_LANGUAGE_SUGGESTION_PENDING.store(false, Ordering::Release);
                return;
            }
        };
        let mut output = [0_u8; 1_024];
        let written = unsafe {
            officekit_dictation_language_suggestion(
                sentence.as_ptr(),
                sentence.len() as u64,
                focus_code,
                output.as_mut_ptr(),
                output.len() as u64,
                5_000,
            )
        };
        let suggestion = usize::try_from(written)
            .ok()
            .filter(|length| *length > 0 && *length <= output.len())
            .and_then(|length| String::from_utf8(output[..length].to_vec()).ok())
            .and_then(|response| {
                speech_coach::validate_language_suggestion(focus, &sentence, &response)
            });
        output.fill(0);
        if let (Some(coach), Some(suggestion)) =
            (app.try_state::<speech_coach::CoachRuntime>(), suggestion)
        {
            let generation = unsafe { officekit_dictation_overlay_generation() };
            let origin_active = if requires_active_dictation {
                unsafe { officekit_dictation_overlay_valid(capture_generation) != 0 }
            } else {
                standalone_epoch.is_some_and(|epoch| {
                    speech_coach::standalone_analysis_is_current(&coach, epoch)
                })
            };
            if speech_coach::language_cue_capture_is_current(
                capture_generation,
                generation,
                origin_active,
            ) {
                speech_coach::publish_language_suggestion(
                    &coach,
                    focus,
                    &suggestion.pattern_id,
                    capture_generation,
                    standalone_epoch,
                    || unsafe {
                        officekit_dictation_coach_cue(
                            suggestion.message.as_ptr(),
                            suggestion.message.len() as u64,
                            generation,
                        )
                    },
                );
            }
        }
        SPEECH_COACH_LANGUAGE_SUGGESTION_PENDING.store(false, Ordering::Release);
    });
}

#[cfg(target_os = "macos")]
static COACH_PANEL_APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

/// The close button on the Listen In panel: ends the solo session and closes the Live Workspace.
/// Speech Coach itself stays on.
#[cfg(target_os = "macos")]
extern "C" fn on_coach_panel_close() {
    let Some(app) = COACH_PANEL_APP.get().cloned() else {
        return;
    };
    // Off the main thread: ending the session waits on the audio lifecycle lock.
    thread::spawn(move || {
        if let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() {
            let _ = speech_coach::speech_coach_set_listen_in(&coach, false);
        }
        coach_workspace::close_window(&app);
    });
}

#[cfg(target_os = "macos")]
static COACH_WORKSPACE_CHECKING: AtomicBool = AtomicBool::new(false);

/// Checks each newly completed sentence for the Live Workspace, one at a time, off the audio path.
#[cfg(target_os = "macos")]
fn pump_coach_workspace_checks(app: &tauri::AppHandle) {
    if COACH_WORKSPACE_CHECKING
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return;
    }
    let app = app.clone();
    thread::spawn(move || {
        if let Some(workspace) = app.try_state::<coach_workspace::CoachWorkspaceRuntime>() {
            // Apple's on-device model coaches sentence clarity; Harper is the offline grammar fallback.
            let apple_status = unsafe { officekit_dictation_polish_status() };
            let available = apple_status == 0;
            workspace.set_apple_status(apple_status);
            workspace.set_checks_available(true);
            while workspace.is_open() {
                let Some(sentence) = workspace.next_sentence() else {
                    break;
                };
                workspace.set_checking(true);
                let response = if available {
                    let mut output = [0_u8; 8_192];
                    let written = unsafe {
                        officekit_dictation_language_suggestion(
                            sentence.as_ptr(),
                            sentence.len() as u64,
                            3, // Whole-sentence clarity coaching, separate from brief HUD cues.
                            output.as_mut_ptr(),
                            output.len() as u64,
                            15_000,
                        )
                    };
                    let response = usize::try_from(written)
                        .ok()
                        .filter(|length| *length > 0 && *length <= output.len())
                        .and_then(|length| String::from_utf8(output[..length].to_vec()).ok());
                    output.fill(0);
                    response
                } else {
                    None
                };
                for fix in coach_grammar::check_workspace_sentence(&sentence, response.as_deref()) {
                    workspace.add_fix(fix);
                }
                workspace.set_checking(false);
            }
        }
        COACH_WORKSPACE_CHECKING.store(false, Ordering::Release);
    });
}

#[cfg(target_os = "macos")]
fn run_speech_coach_analyzer(app: tauri::AppHandle) {
    loop {
        thread::sleep(Duration::from_millis(250));
        let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() else {
            break;
        };
        let Some(dictation) = app.try_state::<DictationRuntime>() else {
            break;
        };
        let coach_ready = speech_coach::current_status(&coach)
            .is_ok_and(|status| status.settings.enabled && !status.settings.paused);
        if !coach_ready {
            continue;
        }
        let Ok(current) = dictation.0.lock() else {
            continue;
        };
        let analysis_ready = speech_model_available(&current);
        speech_coach::set_analysis_ready(&coach, analysis_ready);
        // A dictation owns the microphone window, so standalone coaching steps aside for it. A
        // meeting recording does not: the coach listens to the microphone in it, never to system audio.
        let meeting_coached = speech_coach::meeting_coach_active(&coach);
        if meeting_coached && !current.meeting_recording {
            // The recording ended without Stop (a failure): close the meeting's coaching note.
            speech_coach::set_meeting_coach(&coach, false);
        }
        // A meeting nobody is coaching has nothing to analyse, and any Listen In session pauses.
        if speech_coach::analyzer_steps_aside(
            current.capture_active,
            current.meeting_recording,
            meeting_coached,
        ) {
            drop(current);
            let _ = speech_coach::finish_standalone_session_for_runtime(&coach);
            continue;
        }
        if !analysis_ready {
            continue;
        }
        let model = current.model;
        let capture_mode_epoch = current.capture_mode_epoch;
        let spoken_language = current.spoken_language.clone();
        let prompt = dictation_quality::build_initial_prompt(&current.vocabulary_terms, None);
        let Some(engine) = current.engine.clone() else {
            continue;
        };
        drop(current);
        let Some(origin_epoch) = speech_coach::standalone_analysis_epoch(&coach) else {
            continue;
        };
        let origin_generation = unsafe { officekit_dictation_overlay_generation() };

        if unsafe { officekit_dictation_coach_window_sample_count() } == 0 {
            continue;
        }
        let engine_handle = engine.clone();
        let Ok(mut engine) = engine.try_lock() else {
            continue;
        };
        let mut samples = vec![0.0_f32; COACH_ANALYSIS_MAX_SAMPLES];
        let mut speech_seconds = 0.0_f64;
        let sample_count = unsafe {
            officekit_dictation_coach_drain_window(
                samples.as_mut_ptr(),
                samples.len() as u64,
                &mut speech_seconds,
            )
        } as usize;
        if sample_count == 0 || sample_count > samples.len() {
            samples.fill(0.0);
            continue;
        }
        samples.truncate(sample_count);
        let result = transcribe_samples_buffer(
            &mut engine,
            model,
            &samples,
            false,
            spoken_language.as_deref(),
            prompt.as_deref(),
        );
        let pitch = speech_coach::estimate_pitch_stats(&samples, 16_000);
        let initialization_error = engine.error().map(str::to_owned);
        drop(engine);
        samples.fill(0.0);
        if let Some(error) = initialization_error {
            report_speech_model_failure(&app, &engine_handle, &error, 0.0);
            continue;
        }
        let Ok(text) = result else { continue };
        let text = text.trim();
        if text.is_empty() {
            continue;
        }
        let Ok(dictation_mode) = dictation.0.lock() else {
            continue;
        };
        let overlay_generation = unsafe { officekit_dictation_overlay_generation() };
        if !speech_coach::standalone_window_matches_capture(
            capture_mode_epoch,
            dictation_mode.capture_mode_epoch,
            origin_generation,
            overlay_generation,
            speech_coach::analyzer_window_is_standalone(
                dictation_mode.capture_active,
                dictation_mode.meeting_recording,
            ),
        ) || !speech_coach::standalone_analysis_is_current(&coach, origin_epoch)
        {
            continue;
        }
        if !speech_coach::record_standalone_segment(
            &coach,
            text,
            speech_seconds,
            pitch,
            origin_epoch,
        ) {
            continue;
        }
        let generation = origin_generation;
        let mut workspace_pace = None;
        let published = speech_coach::publish_standalone_feedback(
            &coach,
            origin_epoch,
            text,
            speech_seconds,
            pitch,
            |pace, pitch, cue| {
                workspace_pace = pace.map(|(wpm, _, _)| wpm);
                if unsafe { officekit_dictation_overlay_generation() } != generation {
                    return;
                }
                if let Some((pace, target_min, target_max)) = pace {
                    unsafe {
                        officekit_dictation_coach_pace(pace, target_min, target_max, generation);
                    }
                }
                if let Some(pitch) = pitch {
                    unsafe {
                        officekit_dictation_coach_pitch_stats(
                            pitch.median_hz,
                            pitch.range_hz,
                            generation,
                        );
                    }
                }
                if let Some(cue) = cue {
                    unsafe {
                        officekit_dictation_coach_cue(cue.as_ptr(), cue.len() as u64, generation);
                    }
                }
            },
        );
        if !published {
            continue;
        }
        drop(dictation_mode);
        if let Some(workspace) = app.try_state::<coach_workspace::CoachWorkspaceRuntime>() {
            if workspace.record_segment(text, workspace_pace) {
                pump_coach_workspace_checks(&app);
            }
        }
        queue_speech_coach_language_suggestion(
            &app,
            &coach,
            text,
            generation,
            false,
            Some(origin_epoch),
        );
    }
}

#[cfg(target_os = "macos")]
fn run_meeting_recorder(app: tauri::AppHandle, rx: std::sync::mpsc::Receiver<()>) {
    let start_instant = std::time::Instant::now();
    let mut last_progress_instant = std::time::Instant::now();
    loop {
        thread::sleep(Duration::from_millis(200));

        let is_stop_requested = rx.try_recv().is_ok();
        let elapsed = start_instant.elapsed().as_secs_f64();

        if last_progress_instant.elapsed() >= Duration::from_millis(500) {
            last_progress_instant = std::time::Instant::now();
            let _ = app.emit(
                "dictation-meeting-progress",
                DictationMeetingProgress {
                    duration_seconds: elapsed,
                },
            );
        }

        let sample_count = unsafe { officekit_dictation_sample_count() };
        let should_drain = sample_count >= DICTATION_SAMPLE_RATE * 10
            || (is_stop_requested && sample_count >= DICTATION_SAMPLE_RATE / 2);

        if should_drain && sample_count > 0 {
            let mut initialization_failure = None;
            let mut chunk = vec![0.0f32; sample_count as usize];
            let drained =
                unsafe { officekit_dictation_drain_samples(chunk.as_mut_ptr(), sample_count) };
            chunk.truncate(drained as usize);

            if !chunk.is_empty() {
                if let Some(runtime) = app.try_state::<DictationRuntime>() {
                    if let Ok(current) = runtime.0.lock() {
                        let prompt = dictation_quality::build_initial_prompt(
                            &current.vocabulary_terms,
                            None,
                        );
                        if let Some(engine) = current.engine.as_ref() {
                            let engine_handle = engine.clone();
                            if let Ok(mut engine) = engine.lock() {
                                if let Ok(text) = transcribe_samples_buffer(
                                    &mut engine,
                                    current.model,
                                    &chunk,
                                    false,
                                    current.spoken_language.as_deref(),
                                    prompt.as_deref(),
                                ) {
                                    let trimmed = text.trim();
                                    if !trimmed.is_empty() {
                                        let translated_text = current
                                            .translate_to_english
                                            .then(|| {
                                                transcribe_samples_buffer(
                                                    &mut engine,
                                                    current.model,
                                                    &chunk,
                                                    true,
                                                    current.spoken_language.as_deref(),
                                                    prompt.as_deref(),
                                                )
                                                .ok()
                                            })
                                            .flatten()
                                            .filter(|translated| !translated.trim().is_empty());
                                        let _ = app.emit(
                                            "dictation-meeting-chunk",
                                            DictationMeetingChunk {
                                                text: trimmed.to_string(),
                                                translated_text,
                                                is_final: is_stop_requested,
                                            },
                                        );
                                    }
                                }
                                initialization_failure = engine
                                    .error()
                                    .map(|error| (engine_handle, error.to_owned()));
                            }
                        }
                    }
                }
            }
            chunk.fill(0.0);
            if let Some((engine, error)) = initialization_failure {
                report_speech_model_failure(&app, &engine, &error, elapsed);
                break;
            }
        }

        if is_stop_requested {
            let _ = app.emit(
                "dictation-meeting-stopped",
                DictationMeetingProgress {
                    duration_seconds: elapsed,
                },
            );
            break;
        }

        if let Some(runtime) = app.try_state::<DictationRuntime>() {
            if let Ok(current) = runtime.0.lock() {
                if !current.meeting_recording {
                    break;
                }
            }
        }
    }
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_meeting_record_start(
    app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
    source: Option<String>,
) -> Result<DictationMeetingStatus, String> {
    let source_str = source.unwrap_or_else(|| "microphone".into());
    let is_dual = source_str == "dual";

    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation state is unavailable".to_string())?;

    if current.meeting_recording {
        return Err("A meeting recording is already active".into());
    }
    if current.capture_active {
        return Err("Stop the current recording before starting a meeting".into());
    }
    register_deferred_speech_model(&mut current)?;
    if !speech_model_available(&current) {
        return Err("Prepare the local speech model before recording a meeting".into());
    }
    if microphone_permission_from_code(unsafe {
        officekit_dictation_microphone_permission_status()
    }) != MicrophonePermission::Granted
    {
        return Err("Allow microphone access before recording a meeting".into());
    }
    if is_dual && unsafe { officekit_dictation_screen_recording_permission_status() } != 0 {
        return Err("Allow Screen & System Audio Recording access in System Settings for dual meeting capture".into());
    }

    let start_code =
        unsafe { officekit_dictation_start_meeting_capture(if is_dual { 1 } else { 0 }) };
    if let Some(err) = capture_start_error_from_code(start_code) {
        return Err(match err {
            CaptureStartError::AlreadyActive
                if app
                    .try_state::<speech_coach::CoachRuntime>()
                    .is_some_and(|coach| speech_coach::listen_in_active(&coach)) =>
            {
                "Speech Coach is listening. End it before recording a meeting"
            }
            CaptureStartError::AlreadyActive => "Audio recording is already active",
            CaptureStartError::PermissionDenied => "Allow microphone access to record audio",
            CaptureStartError::NoInputDevice => "No microphone is connected. Connect a microphone and select it in macOS Sound settings.",
            _ => "Meeting audio recording could not be started",
        }
        .into());
    }

    current.meeting_recording = true;
    current.set_capture_active(true);
    let (tx, rx) = std::sync::mpsc::channel::<()>();
    current.meeting_stop_tx = Some(tx);
    drop(current);

    let monitor_app = app.clone();
    if thread::Builder::new()
        .name("officekit-meeting-recorder".into())
        .spawn(move || run_meeting_recorder(monitor_app, rx))
        .is_err()
    {
        unsafe { officekit_dictation_stop_capture() };
        if let Ok(mut current) = runtime.0.lock() {
            current.meeting_recording = false;
            current.set_capture_active(false);
            current.meeting_stop_tx = None;
        }
        return Err("Meeting recorder thread could not be started".into());
    }
    // Only a recording that is really running gets coached, so a failed start leaves nothing behind.
    attach_coach_to_meeting(&app);

    Ok(DictationMeetingStatus {
        is_recording: true,
        source: source_str,
        duration_seconds: 0.0,
    })
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_meeting_record_stop(
    _app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationMeetingStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation state is unavailable".to_string())?;

    if !current.meeting_recording {
        return Ok(DictationMeetingStatus {
            is_recording: false,
            source: "microphone".into(),
            duration_seconds: 0.0,
        });
    }

    if let Some(tx) = current.meeting_stop_tx.take() {
        let _ = tx.send(());
    }
    current.meeting_recording = false;
    current.set_capture_active(false);
    drop(current);

    thread::sleep(Duration::from_millis(350));
    unsafe { officekit_dictation_stop_capture() };
    if let Some(coach) = _app.try_state::<speech_coach::CoachRuntime>() {
        // Saves the one coaching note for this meeting.
        speech_coach::set_meeting_coach(&coach, false);
    }

    Ok(DictationMeetingStatus {
        is_recording: false,
        source: "microphone".into(),
        duration_seconds: 0.0,
    })
}

/// While Speech Coach is on, it coaches a meeting recording from the microphone only and opens the
/// Live Workspace. Off, paused or unavailable, the meeting records exactly as before.
#[cfg(target_os = "macos")]
fn attach_coach_to_meeting(app: &tauri::AppHandle) {
    speech_coach::attach_to_meeting(
        speech_coach::attach_on_dictation(),
        // 0 joined; anything else (1 not a meeting capture, 2 already coaching) did not.
        || unsafe { officekit_dictation_coach_start_for_meeting() } == 0,
        || {
            app.try_state::<speech_coach::CoachRuntime>()
                .is_some_and(|coach| speech_coach::set_meeting_coach(&coach, true))
        },
        || {
            let _ = coach_workspace::open_window(app);
        },
        speech_coach::release_attached_coach,
    );
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_meeting_status(
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationMeetingStatus, String> {
    let current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation state is unavailable".to_string())?;
    Ok(DictationMeetingStatus {
        is_recording: current.meeting_recording,
        source: "microphone".into(),
        duration_seconds: 0.0,
    })
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_screen_recording_permission() -> DictationScreenRecordingStatus {
    let granted = unsafe { officekit_dictation_screen_recording_permission_status() } == 0;
    DictationScreenRecordingStatus {
        permission: if granted { "granted" } else { "denied" },
        message: if granted {
            "Screen and system audio recording is allowed."
        } else {
            "Allow Screen & System Audio Recording in System Settings for dual meeting audio."
        },
    }
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_request_screen_recording_permission() -> DictationScreenRecordingStatus {
    unsafe { officekit_dictation_request_screen_recording_permission() };
    dictation_screen_recording_permission()
}

/// The Record button on a meeting or call reminder: the same local recorder as Meeting Recorder.
#[cfg(target_os = "macos")]
pub(crate) fn start_meeting_recording_from_reminder(app: &tauri::AppHandle) -> Result<(), String> {
    dictation_meeting_record_start(app.clone(), app.state(), Some("microphone".into())).map(|_| ())
}
#[cfg(not(target_os = "macos"))]
pub(crate) fn start_meeting_recording_from_reminder(_app: &tauri::AppHandle) -> Result<(), String> {
    Err("Meeting recording is only supported on macOS".into())
}

/// The Coach me button on a call or meeting reminder: the same Listen In session as Quick
/// Controls, with the Live Workspace. It records nothing; the call is coached from the microphone.
/// Like Quick Controls' Listen In it turns Speech Coach on and uses the Practice context; it refuses
/// while a meeting recording or another coached session already has the microphone.
#[cfg(target_os = "macos")]
pub(crate) fn start_coach_from_reminder(app: &tauri::AppHandle) -> Result<(), String> {
    if let Some(reason) = app
        .try_state::<speech_coach::CoachRuntime>()
        .and_then(|coach| {
            speech_coach::coach_me_blocker_for_runtime(&coach, meeting_recording_active(app))
        })
    {
        return Err(reason.into());
    }
    let status = speech_coach::speech_coach_status(app.state())?;
    if !status.settings.enabled || status.settings.paused {
        speech_coach::speech_coach_set_enabled(app.clone(), app.state(), true)?;
    }
    let status = speech_coach::speech_coach_status(app.state())?;
    speech_coach::speech_coach_configure(
        app.state(),
        listen_in_practice_settings(status.settings),
    )?;
    register_speech_model(app)?;
    speech_coach::speech_coach_set_listen_in(&app.state(), true)?;
    // From here the session ends with the call, whichever way the person or the call ends it.
    speech_coach::mark_coach_me(&app.state());
    coach_workspace::open_window(app)?;
    Ok(())
}
#[cfg(not(target_os = "macos"))]
pub(crate) fn start_coach_from_reminder(_app: &tauri::AppHandle) -> Result<(), String> {
    Err("Speech Coach is only supported on macOS".into())
}

/// Called every second. While a Coach me session runs it reads whether a call app holds the
/// microphone (whatever the record offer says) and ends the session, saving its note, once a call
/// that was there has gone for a while.
pub(crate) fn coach_me_call_tick(app: &tauri::AppHandle) {
    let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() else {
        return;
    };
    if !speech_coach::coach_me_active(&coach) {
        return;
    }
    speech_coach::coach_me_tick(&coach, call_detect::current_call().is_some());
}

#[cfg(target_os = "macos")]
pub(crate) fn meeting_recording_active(app: &tauri::AppHandle) -> bool {
    app.try_state::<DictationRuntime>()
        .and_then(|state| state.0.lock().ok().map(|state| state.meeting_recording))
        .unwrap_or(false)
}
#[cfg(not(target_os = "macos"))]
pub(crate) fn meeting_recording_active(_app: &tauri::AppHandle) -> bool {
    false
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_meeting_record_start() -> Result<DictationMeetingStatus, String> {
    Err("Meeting recording is only supported on macOS".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_meeting_record_stop() -> Result<DictationMeetingStatus, String> {
    Err("Meeting recording is only supported on macOS".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_meeting_status() -> DictationMeetingStatus {
    DictationMeetingStatus {
        is_recording: false,
        source: "microphone".into(),
        duration_seconds: 0.0,
    }
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_screen_recording_permission() -> DictationScreenRecordingStatus {
    DictationScreenRecordingStatus {
        permission: "unavailable",
        message: "System audio recording is unavailable on this platform.",
    }
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_request_screen_recording_permission() -> DictationScreenRecordingStatus {
    dictation_screen_recording_permission()
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_hotkey_status(
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationHotkeyStatus, String> {
    let current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation shortcut status is unavailable".to_string())?;
    Ok(DictationHotkeyStatus {
        state: current.hotkey_state,
        key: current.hotkey_key,
        custom_binding: current.custom_hotkey.clone(),
    })
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_hotkey_status() -> DictationHotkeyStatus {
    DictationHotkeyStatus {
        state: HotkeyState::Disabled,
        key: DictationHotkeyKey::default(),
        custom_binding: None,
    }
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_hotkey_configure(
    key: DictationHotkeyKey,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationHotkeyStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation shortcut is unavailable".to_string())?;
    if current.hotkey_state != HotkeyState::Disabled {
        return Err("Turn off the dictation shortcut before changing its key".into());
    }
    #[cfg(target_os = "macos")]
    if current.capture_active {
        return Err("Stop the current recording before changing its key".into());
    }
    current.hotkey_key = key;
    current.custom_hotkey = None;
    Ok(DictationHotkeyStatus {
        state: current.hotkey_state,
        key,
        custom_binding: None,
    })
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_hotkey_configure_custom(
    key_code: u16,
    modifier_mask: u8,
    label: String,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationHotkeyStatus, String> {
    let binding = validate_custom_hotkey(key_code, modifier_mask, label).map_err(str::to_string)?;
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation shortcut is unavailable".to_string())?;
    if current.hotkey_state != HotkeyState::Disabled {
        return Err("Turn off the dictation shortcut before changing its key".into());
    }
    if current.capture_active {
        return Err("Stop the current recording before changing its key".into());
    }
    current.hotkey_key = DictationHotkeyKey::Custom;
    current.custom_hotkey = Some(binding.clone());
    Ok(DictationHotkeyStatus {
        state: current.hotkey_state,
        key: current.hotkey_key,
        custom_binding: Some(binding),
    })
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_hotkey_configure(key: DictationHotkeyKey) -> Result<DictationHotkeyStatus, String> {
    let _ = key;
    Err("Configurable local dictation is unavailable on this platform".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_hotkey_configure_custom(
    _key_code: u16,
    _modifier_mask: u8,
    _label: String,
) -> Result<DictationHotkeyStatus, String> {
    Err("Configurable local dictation is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_hotkey_enable(
    app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationHotkeyStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation shortcut is unavailable".to_string())?;
    if current.hotkey_state != HotkeyState::Disabled {
        return Ok(DictationHotkeyStatus {
            state: current.hotkey_state,
            key: current.hotkey_key,
            custom_binding: current.custom_hotkey.clone(),
        });
    }
    let selected_key = current.hotkey_key;
    let custom_binding = current.custom_hotkey.clone();
    if selected_key == DictationHotkeyKey::Custom && custom_binding.is_none() {
        return Err("Record a custom shortcut before enabling dictation".into());
    }
    let selected_label = custom_binding.as_ref().map_or_else(
        || selected_key.display_name().to_string(),
        |binding| binding.label.clone(),
    );
    if current.capture_active {
        return Err(format!(
            "Stop the current recording before enabling the {selected_label} shortcut"
        ));
    }
    register_deferred_speech_model(&mut current)?;
    if !speech_model_available(&current) {
        return Err(format!(
            "Prepare the local speech model before enabling the {selected_label} shortcut"
        ));
    }
    if microphone_permission_from_code(unsafe {
        officekit_dictation_microphone_permission_status()
    }) != MicrophonePermission::Granted
    {
        return Err(format!(
            "Allow microphone access before enabling the {selected_label} shortcut"
        ));
    }
    if accessibility_permission_from_code(unsafe { officekit_dictation_accessibility_status() })
        != AccessibilityPermission::Granted
    {
        return Err(format!(
            "Allow Accessibility access before enabling the {selected_label} shortcut"
        ));
    }

    let key_code = custom_binding
        .as_ref()
        .map_or(-1, |binding| i32::from(binding.key_code));
    let modifier_mask = custom_binding
        .as_ref()
        .map_or(0, |binding| i32::from(binding.modifier_mask));
    let monitor_code = unsafe {
        officekit_dictation_start_hotkey_monitor(selected_key.native_id(), key_code, modifier_mask)
    };
    if let Some(error) = hotkey_monitor_start_error_from_code(monitor_code) {
        if error != HotkeyMonitorStartError::AlreadyActive {
            return Err(match error {
                HotkeyMonitorStartError::AlreadyActive => {
                    "The selected shortcut monitor is already active"
                }
                HotkeyMonitorStartError::PermissionRequired => {
                    "Allow Accessibility access before enabling the selected shortcut"
                }
                HotkeyMonitorStartError::Unavailable => {
                    "The selected shortcut monitor could not be started"
                }
            }
            .into());
        }
    }
    current.hotkey_state = transition_hotkey(HotkeyState::Disabled, HotkeyEvent::Enable).state;
    drop(current);

    let monitor_app = app.clone();
    if thread::Builder::new()
        .name("officekit-dictation-hotkey".into())
        .spawn(move || run_dictation_hotkey_monitor(monitor_app))
        .is_err()
    {
        unsafe { officekit_dictation_stop_hotkey_monitor() };
        if let Ok(mut current) = runtime.0.lock() {
            current.hotkey_state = HotkeyState::Disabled;
        }
        return Err("The selected shortcut monitor could not be started".into());
    }
    let status = DictationHotkeyStatus {
        state: HotkeyState::Ready,
        key: selected_key,
        custom_binding,
    };
    // Quick controls and the tool page are separate windows: tell the others the shortcut changed.
    let _ = app.emit("dictation-hotkey-state", status.clone());
    Ok(status)
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_hotkey_enable() -> Result<DictationHotkeyStatus, String> {
    Err("Local Fn dictation is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_hotkey_disable(
    app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationHotkeyStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation shortcut is unavailable".to_string())?;
    let mut finalize_error = None;
    if current.capture_active && !current.meeting_recording {
        let generation = current.tray_capture_generation.take();
        let was_cancelled = generation.is_some_and(
            |generation| unsafe { officekit_dictation_overlay_valid(generation) } == 0,
        );
        if was_cancelled {
            unsafe {
                officekit_dictation_stop_capture();
                officekit_dictation_clear_samples();
            }
            current.set_capture_active(false);
            current.clear_session_text();
        } else {
            if let Some(generation) = generation {
                unsafe { officekit_dictation_overlay_processing(generation) };
            }
            match stop_capture_locked(&mut current) {
                Ok(mut transcript) => {
                    transcript.capture_generation = generation;
                    if let Err(error) = app.emit("dictation-transcript", transcript) {
                        finalize_error = Some(format!("Transcript delivery failed: {error}"));
                    }
                    if let Some(generation) = generation {
                        unsafe { officekit_dictation_overlay_finish(generation) };
                    }
                }
                Err(error) => {
                    let failure = attempt_failure_payload(&mut current, &error);
                    let _ = app.emit("dictation-attempt-failed", failure);
                    finalize_error = Some(error);
                }
            }
        }
    }
    let transition = transition_hotkey(current.hotkey_state, HotkeyEvent::Disable);
    current.hotkey_state = transition.state;
    let key = current.hotkey_key;
    let custom_binding = current.custom_hotkey.clone();
    drop(current);
    unsafe { officekit_dictation_stop_hotkey_monitor() };
    let status = DictationHotkeyStatus {
        state: HotkeyState::Disabled,
        key,
        custom_binding,
    };
    let _ = app.emit("dictation-hotkey-state", status.clone());
    if let Some(error) = finalize_error {
        Err(error)
    } else {
        Ok(status)
    }
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_hotkey_disable() -> DictationHotkeyStatus {
    DictationHotkeyStatus {
        state: HotkeyState::Disabled,
        key: DictationHotkeyKey::default(),
        custom_binding: None,
    }
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct QuickControlsSnapshot {
    speech_coach: bool,
    listen_in: bool,
    speech_to_text: bool,
    window_manager: bool,
    ergonomics: bool,
    meeting_recorder: bool,
    clipboard_history: bool,
    menu_cpu: bool,
    menu_ram: bool,
    menu_storage: bool,
    menu_network: bool,
    menu_gpu: bool,
    menu_temperature: bool,
    menu_battery: bool,
    menu_bluetooth: bool,
    /// False on a desktop Mac, so the panel leaves out the Battery switch.
    has_battery: bool,
    hud_position: speech_coach::CoachPlacement,
}

/// True when macOS reports an internal battery. Asked once; a failed check keeps the switch visible.
fn has_internal_battery() -> bool {
    static PRESENT: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *PRESENT.get_or_init(|| {
        #[cfg(target_os = "macos")]
        {
            std::process::Command::new("/usr/bin/pmset")
                .args(["-g", "batt"])
                .output()
                .map(|out| battery_in_power_report(&String::from_utf8_lossy(&out.stdout)))
                .unwrap_or(true)
        }
        #[cfg(not(target_os = "macos"))]
        {
            true
        }
    })
}

fn battery_in_power_report(report: &str) -> bool {
    report.contains("InternalBattery")
}

fn listen_in_practice_settings(
    mut settings: speech_coach::CoachSettings,
) -> speech_coach::CoachSettings {
    settings.context = speech_coach::CoachContext::Practice;
    settings
}

fn quick_controls_snapshot(app: &tauri::AppHandle) -> Result<QuickControlsSnapshot, String> {
    let coach = speech_coach::speech_coach_status(app.state())?;
    let desktop = global_desktop::global_desktop_status(app.state());
    let ergonomics_enabled = app
        .try_state::<ergonomics::Runtime>()
        .and_then(|runtime| ergonomics::quick_controls_enabled(&runtime).ok())
        .unwrap_or(false);
    #[cfg(target_os = "macos")]
    let (speech_to_text, meeting_recorder) = {
        let runtime = app.state::<DictationRuntime>();
        let state = runtime
            .0
            .lock()
            .map_err(|_| "Speech tool status is unavailable".to_string())?;
        (
            state.hotkey_state == HotkeyState::Ready,
            state.meeting_recording,
        )
    };
    #[cfg(not(target_os = "macos"))]
    let (speech_to_text, meeting_recorder) = (false, false);
    let menu = menu_stats::status(app);
    Ok(QuickControlsSnapshot {
        speech_coach: coach.settings.enabled && !coach.settings.paused,
        listen_in: coach.settings.enabled
            && !coach.settings.paused
            && speech_coach::listen_in_active(&app.state::<speech_coach::CoachRuntime>()),
        speech_to_text,
        window_manager: desktop.settings.windows_enabled,
        ergonomics: ergonomics_enabled,
        meeting_recorder,
        clipboard_history: global_clipboard::history_enabled(app),
        menu_cpu: menu.cpu,
        menu_ram: menu.ram,
        menu_storage: menu.storage,
        menu_network: menu.network,
        menu_gpu: menu.gpu,
        menu_temperature: menu.temperature,
        menu_battery: menu.battery,
        menu_bluetooth: menu.bluetooth,
        has_battery: has_internal_battery(),
        hud_position: coach.settings.placement,
    })
}

/// Starts a microphone meeting recording, or stops the one in progress. Used by the launcher.
#[cfg(target_os = "macos")]
pub(crate) fn toggle_meeting_recording(app: &tauri::AppHandle) -> Result<bool, String> {
    let recording = app
        .state::<DictationRuntime>()
        .0
        .lock()
        .map_err(|_| "Meeting recording is unavailable".to_string())?
        .meeting_recording;
    if recording {
        dictation_meeting_record_stop(app.clone(), app.state())?;
        Ok(false)
    } else {
        dictation_meeting_record_start(app.clone(), app.state(), Some("microphone".into()))?;
        Ok(true)
    }
}

#[cfg(not(target_os = "macos"))]
pub(crate) fn toggle_meeting_recording(_app: &tauri::AppHandle) -> Result<bool, String> {
    Err("Meeting recording is available in the macOS desktop app".into())
}

#[tauri::command]
fn quick_controls_status(app: tauri::AppHandle) -> Result<QuickControlsSnapshot, String> {
    quick_controls_snapshot(&app)
}

#[tauri::command]
async fn quick_controls_set_tool(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    tool: String,
    enabled: bool,
) -> Result<QuickControlsSnapshot, String> {
    match tool.as_str() {
        "speechCoach" => {
            speech_coach::speech_coach_set_enabled(app.clone(), app.state(), enabled)?;
            if !enabled {
                coach_workspace::close_window(&app);
            }
        }
        "listenIn" => {
            if enabled {
                let status = speech_coach::speech_coach_status(app.state())?;
                if !status.settings.enabled || status.settings.paused {
                    speech_coach::speech_coach_set_enabled(app.clone(), app.state(), true)?;
                }
                let status = speech_coach::speech_coach_status(app.state())?;
                let settings = listen_in_practice_settings(status.settings);
                speech_coach::speech_coach_configure(app.state(), settings)?;
                #[cfg(target_os = "macos")]
                register_speech_model(&app)?;
                speech_coach::speech_coach_set_listen_in(&app.state(), true)?;
                coach_workspace::open_window(&app)?;
            } else {
                speech_coach::speech_coach_set_listen_in(&app.state(), false)?;
                coach_workspace::close_window(&app);
            }
        }
        "speechToText" => {
            #[cfg(target_os = "macos")]
            if enabled {
                dictation_hotkey_enable(app.clone(), app.state())?;
            }
            #[cfg(target_os = "macos")]
            if !enabled {
                dictation_hotkey_disable(app.clone(), app.state())?;
            }
            #[cfg(not(target_os = "macos"))]
            return Err("Local speech to text is available in the macOS desktop app".into());
        }
        "windowManager" => {
            let status = global_desktop::global_desktop_status(app.state());
            let mut settings = status.settings;
            settings.windows_enabled = enabled;
            global_desktop::global_desktop_configure(app.state(), settings)?;
        }
        "ergonomics" => {
            let runtime = app
                .try_state::<ergonomics::Runtime>()
                .ok_or("Ergonomics is unavailable in this build")?;
            ergonomics::ergonomics_quick_controls_set_enabled(
                window,
                app.clone(),
                runtime,
                enabled,
            )
            .await?;
        }
        "meetingRecorder" => {
            #[cfg(target_os = "macos")]
            if enabled {
                dictation_meeting_record_start(
                    app.clone(),
                    app.state(),
                    Some("microphone".into()),
                )?;
            } else {
                dictation_meeting_record_stop(app.clone(), app.state())?;
            }
            #[cfg(not(target_os = "macos"))]
            return Err("Meeting Recorder is available in the macOS desktop app".into());
        }
        "clipboardHistory" => global_clipboard::set_history_enabled(&app, enabled)?,
        "menuCpu" | "menuRam" | "menuStorage" | "menuNetwork" | "menuGpu" | "menuTemperature"
        | "menuBattery" | "menuBluetooth" => {
            menu_stats::set_stat(&app, &tool, enabled)?;
        }
        _ => return Err("Choose a supported OfficeKit tool".into()),
    }
    quick_controls_snapshot(&app)
}

#[tauri::command]
fn quick_controls_set_hud_position(
    app: tauri::AppHandle,
    placement: speech_coach::CoachPlacement,
) -> Result<QuickControlsSnapshot, String> {
    let status = speech_coach::speech_coach_status(app.state())?;
    let mut settings = status.settings;
    settings.placement = placement;
    speech_coach::speech_coach_configure(app.state(), settings)?;
    quick_controls_snapshot(&app)
}

#[tauri::command]
async fn quick_controls_disable_all(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<QuickControlsSnapshot, String> {
    let mut failures = Vec::new();
    #[cfg(target_os = "macos")]
    {
        let recording = app
            .state::<DictationRuntime>()
            .0
            .lock()
            .ok()
            .is_some_and(|state| state.meeting_recording);
        if recording {
            if let Err(error) = dictation_meeting_record_stop(app.clone(), app.state()) {
                failures.push(format!("Meeting Recorder: {error}"));
            }
        }
    }
    for (tool, enabled) in [
        ("speechCoach", false),
        ("speechToText", false),
        ("windowManager", false),
        ("clipboardHistory", false),
        ("ergonomics", false),
    ] {
        if let Err(error) =
            quick_controls_set_tool(window.clone(), app.clone(), tool.into(), enabled).await
        {
            failures.push(format!("{tool}: {error}"));
        }
    }
    if let Err(error) = menu_stats::disable_all(&app) {
        failures.push(format!("menu bar stats: {error}"));
    }
    if failures.is_empty() {
        quick_controls_snapshot(&app)
    } else {
        Err(failures.join("; "))
    }
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_paste_text(text: String) -> Result<(), String> {
    validate_paste_text(&text).map_err(|error| match error {
        crate::dictation::PasteTextError::Empty => {
            "There is no transcript text to paste".to_string()
        }
        crate::dictation::PasteTextError::TooLong => {
            "Transcript text exceeds the paste limit".to_string()
        }
        crate::dictation::PasteTextError::ContainsNull => {
            "Transcript contains unsupported characters".to_string()
        }
    })?;
    match paste_native_error_from_code(unsafe {
        officekit_dictation_paste_text(text.as_ptr(), text.len() as u64)
    }) {
        None => Ok(()),
        Some(PasteNativeError::PermissionRequired) => {
            Err("Allow Accessibility access before pasting into the focused app".into())
        }
        Some(PasteNativeError::Unavailable) => {
            Err("Text could not be pasted into the focused app".into())
        }
    }
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_paste_text(_text: String) -> Result<(), String> {
    Err("Local dictation paste-back is unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
async fn dictation_cleanup_and_paste(
    text: String,
    audio_duration_seconds: f64,
    dictionary: BTreeMap<String, String>,
    capture_generation: Option<u64>,
    mode: Option<String>,
    language: Option<String>,
    words: Option<Vec<String>>,
    fix_grammar: Option<bool>,
    app_modes: Option<BTreeMap<String, dictation_quality::AppMode>>,
    token: State<'_, BackendApiToken>,
    backend_address: State<'_, BackendApiAddress>,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationTranscript, String> {
    let fix_grammar = fix_grammar.unwrap_or(false);
    let app_modes = app_modes.unwrap_or_default();
    dictation_quality::validate_app_modes(&app_modes)
        .map_err(|_| "The per-app settings are invalid".to_string())?;
    let words = dictation_quality::validate_vocabulary_terms(&words.unwrap_or_default())
        .map_err(|_| "The personal word list is invalid".to_string())?;
    let smart = match mode.as_deref() {
        None | Some("rules") => false,
        Some("smart") => true,
        Some(_) => return Err("Choose a supported cleanup mode".into()),
    };
    let language = language
        .as_deref()
        .and_then(dictation_quality::validate_language_hint);
    // Context is consumed by exactly one cleanup and is dropped even when unused.
    let (focus_context, llm_polish) = runtime
        .0
        .lock()
        .ok()
        .map(|current| (current.take_focus_context(), current.llm_polish))
        .unwrap_or((None, false));
    // The focused app (only known when "Use the app you are typing in" is on) may carry its own
    // cleanup choices; everything else follows the global switches.
    let (smart, fix_grammar) =
        dictation_quality::resolve_app_mode(&app_modes, focus_context.as_ref(), smart, fix_grammar);
    let focused_app = dictation_quality::focused_app_label(focus_context.as_ref())
        .map(|(name, bundle_id)| DictationFocusedApp { name, bundle_id });
    let token = token.0.clone();
    let address = backend_address.0;
    let result = tauri::async_runtime::spawn_blocking(move || {
        if let Some(generation) = capture_generation {
            if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                return Err("Dictation cancelled".into());
            }
        }
        validate_transcript(&text, audio_duration_seconds)
            .map_err(|_| "The local transcript is invalid".to_string())?;
        validate_dictionary(&dictionary)
            .map_err(|_| "The personal dictionary is invalid".to_string())?;
        let outcome = cleanup_dictation_text_with(
            address,
            &token,
            &text,
            &dictionary,
            &dictation_quality::CleanupOptions {
                smart,
                language: language.as_deref(),
                context: focus_context.as_ref(),
            },
            &words,
        )?;
        let rules_text = outcome.text;
        // Harper's clear grammar fixes, only when asked. Anything the person keeps in their
        // dictionary or word list is never changed.
        let (grammar_text, grammar_fixes) = if fix_grammar {
            let protected: Vec<String> = dictionary
                .values()
                .cloned()
                .chain(words.iter().cloned())
                .collect();
            let (fixed, applied) = coach_grammar::fix_text(&rules_text, &protected);
            (Some(fixed), applied)
        } else {
            (None, Vec::new())
        };
        let before_polish = grammar_text.clone().unwrap_or_else(|| rules_text.clone());
        // The model only ever sees the rules and grammar result, and any guard failure keeps it.
        let (cleaned_text, polished) = if smart && llm_polish {
            match polish_with_system_model(&before_polish) {
                Ok(polished) => (polished, true),
                Err(_) => (before_polish.clone(), false),
            }
        } else {
            (before_polish.clone(), false)
        };
        let steps = DictationSteps {
            after_smart: outcome.after_smart,
            dictionary_changes: outcome.dictionary_changes,
            rules_text,
            grammar_text,
            grammar_fixes,
            polished,
        };
        validate_transcript(&cleaned_text, audio_duration_seconds)
            .map_err(|_| "Local transcript cleanup returned an invalid result".to_string())?;
        if let Some(generation) = capture_generation {
            if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                return Err("Dictation cancelled".into());
            }
        }
        let paste_code = unsafe {
            officekit_dictation_paste_session(
                cleaned_text.as_ptr(),
                cleaned_text.len() as u64,
                capture_generation.unwrap_or(0),
            )
        };
        let delivery_status = if paste_code == 4 {
            "target-changed-clipboard-retained"
        } else {
            match paste_native_error_from_code(paste_code) {
                None => "paste-requested-clipboard-retained",
                Some(PasteNativeError::PermissionRequired) => {
                    "permission-required-transcript-retained"
                }
                Some(PasteNativeError::Unavailable) => "paste-failed-transcript-retained",
            }
        };
        Ok(DictationTranscript {
            text: cleaned_text,
            translated_text: None,
            audio_duration_seconds,
            capture_generation,
            delivery_status: Some(delivery_status),
            capture: None,
            speech_coach_metrics: None,
            steps: Some(steps),
            model: None,
            raw_audio_expires_at: None,
            pieces: None,
            app: focused_app,
        })
    })
    .await
    .map_err(|_| "Dictation cleanup is unavailable".to_string())?;
    if let Some(generation) = capture_generation {
        unsafe { officekit_dictation_overlay_finish(generation) };
    }
    result
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_cleanup_and_paste(
    _text: String,
    _audio_duration_seconds: f64,
    _dictionary: BTreeMap<String, String>,
    _capture_generation: Option<u64>,
    _mode: Option<String>,
    _language: Option<String>,
    _words: Option<Vec<String>>,
    _fix_grammar: Option<bool>,
    _app_modes: Option<BTreeMap<String, dictation_quality::AppMode>>,
) -> Result<DictationTranscript, String> {
    Err("Local dictation cleanup and paste-back are unavailable on this platform".into())
}

#[cfg(target_os = "macos")]
fn run_dictation_hotkey_monitor(app: tauri::AppHandle) {
    let mut previous_pressed = false;
    loop {
        thread::sleep(Duration::from_millis(12));
        let Some(runtime) = app.try_state::<DictationRuntime>() else {
            break;
        };
        let current_state = match runtime.0.lock() {
            Ok(current) => current.hotkey_state,
            Err(_) => break,
        };
        if current_state == HotkeyState::Disabled {
            break;
        }
        let pressed = unsafe { officekit_dictation_hotkey_key_pressed() } != 0;
        if current_state == HotkeyState::Recording
            && unsafe {
                officekit_dictation_overlay_valid(officekit_dictation_overlay_generation())
            } == 0
        {
            unsafe {
                officekit_dictation_stop_capture();
                officekit_dictation_clear_samples();
            }
            if let Ok(mut current) = runtime.0.lock() {
                current.set_capture_active(false);
                current.clear_session_text();
                current.hotkey_state = HotkeyState::Ready;
                let _ = app.emit(
                    "dictation-hotkey-state",
                    DictationHotkeyStatus {
                        state: current.hotkey_state,
                        key: current.hotkey_key,
                        custom_binding: current.custom_hotkey.clone(),
                    },
                );
            }
            let _ = app.emit(
                "dictation-error",
                "Dictation cancelled; no text was pasted.",
            );
            previous_pressed = pressed;
            continue;
        }
        if pressed == previous_pressed {
            continue;
        }
        previous_pressed = pressed;
        let event = if pressed {
            HotkeyEvent::KeyDown
        } else {
            HotkeyEvent::KeyUp
        };
        let transition = transition_hotkey(current_state, event);
        if transition.state == current_state {
            continue;
        }
        if let Ok(mut current) = runtime.0.lock() {
            current.hotkey_state = transition.state;
        } else {
            continue;
        }

        match transition.action {
            HotkeyAction::StartCapture => {
                let generation = unsafe { officekit_dictation_overlay_begin() };
                let result = runtime
                    .0
                    .lock()
                    .map_err(|_| "Dictation capture is unavailable".to_string())
                    .and_then(|mut current| start_capture_locked(&mut current));
                if let Err(error) = result {
                    // The failure is shown on the overlay the user is looking at, not as an app error.
                    let text = overlay_failure_text(&error);
                    unsafe {
                        officekit_dictation_overlay_fail(
                            text.as_ptr(),
                            text.len() as u64,
                            generation,
                        )
                    };
                    if let Ok(mut current) = runtime.0.lock() {
                        if current.hotkey_state == HotkeyState::Recording {
                            current.hotkey_state = transition_hotkey(
                                HotkeyState::Recording,
                                HotkeyEvent::CaptureFailed,
                            )
                            .state;
                        }
                    }
                } else {
                    let preview_app = app.clone();
                    let _ = thread::Builder::new()
                        .name("officekit-dictation-preview".into())
                        .spawn(move || run_dictation_preview(preview_app, generation));
                }
            }
            HotkeyAction::StopAndTranscribe => {
                let generation = unsafe { officekit_dictation_overlay_generation() };
                if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                    unsafe {
                        officekit_dictation_stop_capture();
                        officekit_dictation_clear_samples();
                    }
                    if let Ok(mut current) = runtime.0.lock() {
                        current.set_capture_active(false);
                        current.clear_session_text();
                        current.hotkey_state = HotkeyState::Ready;
                    }
                    continue;
                }
                unsafe { officekit_dictation_overlay_processing(generation) };
                let result = runtime
                    .0
                    .lock()
                    .map_err(|_| "Dictation capture is unavailable".to_string())
                    .and_then(|mut current| stop_capture_locked(&mut current));
                if let Ok(mut current) = runtime.0.lock() {
                    if current.hotkey_state == HotkeyState::Processing {
                        current.hotkey_state = transition_hotkey(
                            HotkeyState::Processing,
                            HotkeyEvent::TranscriptionFinished,
                        )
                        .state;
                    }
                }
                match result {
                    Ok(mut transcript) => {
                        if unsafe { officekit_dictation_overlay_valid(generation) } == 0 {
                            continue;
                        }
                        unsafe {
                            officekit_dictation_overlay_transcript(
                                transcript.text.as_ptr(),
                                transcript.text.len() as u64,
                                generation,
                            )
                        };
                        // A short dictation may stop before any sentence was committed live, so the
                        // finished text still reaches the private Live Workspace for Speech Coach.
                        if speech_coach::attach_on_dictation() && !transcript.text.trim().is_empty()
                        {
                            coach_workspace::open_for_dictation(&app, generation);
                            if let Some(workspace) =
                                app.try_state::<coach_workspace::CoachWorkspaceRuntime>()
                            {
                                // The last sentence has no one left to finish it, so it is closed for checking.
                                let mut finished = transcript.text.trim().to_string();
                                if !finished.ends_with(['.', '?', '!']) {
                                    finished.push('.');
                                }
                                if workspace.record_transcript(generation, &finished, None) {
                                    pump_coach_workspace_checks(&app);
                                }
                            }
                        }
                        transcript.capture_generation = Some(generation);
                        let _ = app.emit("dictation-transcript", transcript);
                    }
                    Err(error) => {
                        unsafe { officekit_dictation_overlay_finish(generation) };
                        let failure = runtime
                            .0
                            .lock()
                            .ok()
                            .map(|mut current| attempt_failure_payload(&mut current, &error));
                        if let Some(failure) = failure {
                            let _ = app.emit("dictation-attempt-failed", failure);
                        }
                        let _ = app.emit("dictation-error", error);
                    }
                }
            }
            HotkeyAction::None
            | HotkeyAction::StopCaptureAndMonitor
            | HotkeyAction::StopMonitor => {}
        }
        let status = runtime.0.lock().map(|current| DictationHotkeyStatus {
            state: current.hotkey_state,
            key: current.hotkey_key,
            custom_binding: current.custom_hotkey.clone(),
        });
        if let Ok(status) = status {
            let _ = app.emit("dictation-hotkey-state", status);
        }
    }
    unsafe { officekit_dictation_stop_hotkey_monitor() };
}

impl DictationRuntime {
    fn new(model_directory: Option<&std::path::Path>, apple_silicon: bool) -> Self {
        let model = DictationModel::ParakeetV3;
        let model_state = if !apple_silicon {
            ModelState::Unsupported
        } else if model_directory
            .is_some_and(|path| model_files_present_for(path, DictationModel::ParakeetV3))
        {
            ModelState::Installed
        } else {
            ModelState::NotInstalled
        };
        Self(Mutex::new(DictationRuntimeState {
            model,
            model_state,
            model_progress: None,
            translate_to_english: false,
            spoken_language: None,
            vocabulary_terms: Vec::new(),
            context_options: dictation_quality::ContextOptions::default(),
            focus_context: Arc::new(Mutex::new(None)),
            streaming_commit: true,
            raw_audio_directory: None,
            llm_polish: false,
            last_failure_capture: None,
            commit_state: Arc::new(Mutex::new(dictation_quality::CommitState::default())),
            #[cfg(target_os = "macos")]
            capture_active: false,
            #[cfg(target_os = "macos")]
            capture_mode_epoch: 0,
            #[cfg(target_os = "macos")]
            tray_capture_generation: None,
            #[cfg(target_os = "macos")]
            hotkey_state: HotkeyState::Disabled,
            hotkey_key: DictationHotkeyKey::default(),
            custom_hotkey: None,
            #[cfg(target_os = "macos")]
            engine: None,
            #[cfg(target_os = "macos")]
            meeting_recording: false,
            #[cfg(target_os = "macos")]
            meeting_stop_tx: None,
        }))
    }
}

fn dictation_status_for(state: ModelState, model: DictationModel) -> DictationModelStatus {
    let message = match state {
        ModelState::Unsupported if model == DictationModel::Qwen3Asr => {
            "Qwen3 ASR requires an Apple silicon Mac running macOS 15 or later.".to_string()
        }
        ModelState::Unsupported => {
            format!("{} requires an Apple silicon Mac.", model.display_name())
        }
        ModelState::NotInstalled => format!(
            "Download {} once to use it offline. Audio stays on this Mac.",
            model.display_name()
        ),
        ModelState::Installed => format!(
            "{} is stored locally and ready to prepare.",
            model.display_name()
        ),
        ModelState::Preparing => format!(
            "Downloading or preparing {} locally. This may take a few minutes.",
            model.display_name()
        ),
        ModelState::Ready => format!(
            "{} is ready. Speech is processed on this Mac.",
            model.display_name()
        ),
        ModelState::Failed => {
            "Model setup failed. Check your connection and try again.".to_string()
        }
    };
    DictationModelStatus {
        model_id: model.id(),
        model: model.display_name(),
        language_support: model.supported_languages(),
        state,
        message,
        progress: None,
    }
}

#[cfg(target_os = "macos")]
fn update_dictation_model_progress(
    app: &tauri::AppHandle,
    model: DictationModel,
    progress: DictationModelProgress,
) {
    if let Some(runtime) = app.try_state::<DictationRuntime>() {
        if let Ok(mut current) = runtime.0.lock() {
            if current.model == model && current.model_state == ModelState::Preparing {
                current.model_progress = Some(progress);
            }
        }
    }
}

#[cfg(target_os = "macos")]
struct FluidModelProgressContext {
    app: tauri::AppHandle,
    model: DictationModel,
}

#[cfg(target_os = "macos")]
unsafe extern "C" fn fluid_model_progress_callback(
    fraction: f64,
    phase_code: i32,
    completed_files: i32,
    total_files: i32,
    context: *mut std::ffi::c_void,
) {
    if context.is_null() || !fraction.is_finite() {
        return;
    }
    let context = unsafe { &*(context as *const FluidModelProgressContext) };
    let phase = match phase_code {
        0 => "checking",
        1 => "downloading",
        2 => "loading",
        _ => "preparing",
    };
    update_dictation_model_progress(
        &context.app,
        context.model,
        DictationModelProgress {
            phase,
            fraction: Some(fraction.clamp(0.0, 1.0)),
            bytes_downloaded: None,
            bytes_total: None,
            completed_files: (total_files > 0).then_some(completed_files.max(0) as u32),
            total_files: (total_files > 0).then_some(total_files as u32),
        },
    );
}

#[cfg(target_os = "macos")]
fn qwen3_supported_on_current_os() -> bool {
    std::process::Command::new("/usr/bin/sw_vers")
        .args(["-productVersion"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .and_then(|version| version.trim().split('.').next()?.parse::<u32>().ok())
        .is_some_and(|major| major >= 15)
}

#[cfg(target_os = "macos")]
fn ensure_whisper_model_file(
    model: DictationModel,
    app: &tauri::AppHandle,
) -> Result<std::path::PathBuf, String> {
    use std::io::Read as _;
    let filename = model
        .whisper_filename()
        .ok_or_else(|| "Choose a supported Whisper model".to_string())?;
    let expected_bytes = model
        .whisper_file_size()
        .ok_or_else(|| "The selected model has no expected size".to_string())?;
    let expected_sha256 = model
        .whisper_sha256()
        .ok_or_else(|| "The selected model has no integrity checksum".to_string())?;
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "The local model folder is unavailable".to_string())?;
    let directory = model_cache_directory(&home, model);
    std::fs::create_dir_all(&directory)
        .map_err(|_| "Could not create the local model folder".to_string())?;
    let cache_root = home.join("Library/Application Support/OfficeKit/Models");
    if !path_is_safe_model_child(&cache_root, &directory) {
        return Err("The local model folder is not safe to use".to_string());
    }
    let metadata = std::fs::symlink_metadata(&directory)
        .map_err(|_| "Could not verify the local model folder".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("The local model folder is not safe to use".to_string());
    }
    cleanup_incomplete_whisper_downloads(&directory, filename);
    let model_path = directory.join(filename);
    if model_files_present_for(&directory, model) {
        if sha256_file(&model_path).as_deref() == Ok(expected_sha256) {
            return Ok(model_path);
        }
        std::fs::remove_file(&model_path)
            .map_err(|_| "The cached Whisper model failed integrity verification".to_string())?;
    }
    match std::fs::symlink_metadata(&model_path) {
        Ok(existing) if existing.file_type().is_symlink() || !existing.is_file() => {
            return Err("An unsafe item blocks the local model path".to_string());
        }
        Ok(_) => std::fs::remove_file(&model_path)
            .map_err(|_| "Could not replace the incomplete local model".to_string())?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("Could not verify the local model path".to_string()),
    }
    let url = format!("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/{filename}");
    let response = ureq::get(&url).call().map_err(|_| {
        "Whisper model download failed. Check your connection and retry.".to_string()
    })?;
    if response
        .headers()
        .get("content-length")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .is_some_and(|length| length != expected_bytes)
    {
        return Err("The model download did not match its expected size".to_string());
    }
    let temporary = directory.join(format!(".{filename}.{}.part", Uuid::new_v4()));
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| "Could not create a temporary model file".to_string())?;
    update_dictation_model_progress(
        app,
        model,
        DictationModelProgress {
            phase: "downloading",
            fraction: Some(0.0),
            bytes_downloaded: Some(0),
            bytes_total: Some(expected_bytes),
            completed_files: None,
            total_files: None,
        },
    );
    let mut reader = response.into_body().into_reader().take(expected_bytes + 1);
    let mut copied = 0_u64;
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let count = match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => count,
            Err(_) => {
                drop(file);
                let _ = std::fs::remove_file(&temporary);
                return Err("The Whisper model download was interrupted".to_string());
            }
        };
        if file.write_all(&buffer[..count]).is_err() {
            drop(file);
            let _ = std::fs::remove_file(&temporary);
            return Err("Could not save the downloaded Whisper model".to_string());
        }
        copied += count as u64;
        update_dictation_model_progress(
            app,
            model,
            DictationModelProgress {
                phase: "downloading",
                fraction: Some(
                    (copied.min(expected_bytes) as f64 / expected_bytes as f64).min(1.0),
                ),
                bytes_downloaded: Some(copied.min(expected_bytes)),
                bytes_total: Some(expected_bytes),
                completed_files: None,
                total_files: None,
            },
        );
    }
    if copied != expected_bytes {
        let _ = std::fs::remove_file(&temporary);
        return Err("The Whisper model download was incomplete".to_string());
    }
    if file.sync_all().is_err() {
        drop(file);
        let _ = std::fs::remove_file(&temporary);
        return Err("Could not save the Whisper model".to_string());
    }
    drop(file);
    update_dictation_model_progress(
        app,
        model,
        DictationModelProgress {
            phase: "verifying",
            fraction: Some(1.0),
            bytes_downloaded: Some(expected_bytes),
            bytes_total: Some(expected_bytes),
            completed_files: None,
            total_files: None,
        },
    );
    if sha256_file(&temporary).as_deref() != Ok(expected_sha256) {
        let _ = std::fs::remove_file(&temporary);
        return Err("The downloaded Whisper model failed integrity verification".to_string());
    }
    if std::fs::rename(&temporary, &model_path).is_err() {
        let _ = std::fs::remove_file(&temporary);
        return Err("Could not publish the local Whisper model".to_string());
    }
    Ok(model_path)
}

#[cfg(target_os = "macos")]
fn cleanup_incomplete_whisper_downloads(directory: &std::path::Path, filename: &str) {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return;
    };
    let prefix = format!(".{filename}.");
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if !name.starts_with(&prefix) || !name.ends_with(".part") {
            continue;
        }
        let path = entry.path();
        if std::fs::symlink_metadata(&path)
            .is_ok_and(|metadata| metadata.is_file() && !metadata.file_type().is_symlink())
        {
            let _ = std::fs::remove_file(path);
        }
    }
}

#[cfg(target_os = "macos")]
fn sha256_file(path: &std::path::Path) -> Result<String, String> {
    use sha2::Digest as _;
    let mut file =
        std::fs::File::open(path).map_err(|_| "Could not verify the Whisper model".to_string())?;
    let mut hasher = sha2::Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let bytes = file
            .read(&mut buffer)
            .map_err(|_| "Could not verify the Whisper model".to_string())?;
        if bytes == 0 {
            break;
        }
        hasher.update(&buffer[..bytes]);
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

#[cfg(target_os = "macos")]
fn load_whisper_context(
    model: DictationModel,
    app: &tauri::AppHandle,
) -> Result<WhisperContext, String> {
    let path = ensure_whisper_model_file(model, app)?;
    update_dictation_model_progress(
        app,
        model,
        DictationModelProgress {
            phase: "loading",
            fraction: Some(1.0),
            bytes_downloaded: None,
            bytes_total: None,
            completed_files: None,
            total_files: None,
        },
    );
    WhisperContext::new_with_params(&path, WhisperContextParameters::default())
        .map_err(|_| "Could not load this Whisper model on this Mac".to_string())
}

#[tauri::command]
fn dictation_model_status(
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationModelStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation model status is unavailable".to_string())?;
    #[cfg(target_os = "macos")]
    if current.model_state == ModelState::Installed {
        let resolved = current.engine.as_ref().and_then(|engine| {
            engine
                .try_lock()
                .ok()
                .map(|model| (model.is_loaded(), model.error().is_some()))
        });
        if let Some((loaded, failed)) = resolved {
            if loaded {
                current.model_state = ModelState::Ready;
            }
            if failed {
                current.model_state = ModelState::Failed;
            }
        }
    }
    let mut status = dictation_status_for(current.model_state, current.model);
    status.progress = current.model_progress.clone();
    Ok(status)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_model_inventory() -> Result<Vec<DictationModelInventoryEntry>, String> {
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "The local model folder is unavailable".to_string())?;
    Ok([
        DictationModel::ParakeetV3,
        DictationModel::ParakeetV2,
        DictationModel::Qwen3Asr,
        DictationModel::WhisperTiny,
        DictationModel::WhisperBase,
        DictationModel::WhisperSmall,
        DictationModel::WhisperMedium,
        DictationModel::WhisperLargeV3,
        DictationModel::WhisperLargeV3Turbo,
        DictationModel::WhisperLargeV3TurboQ5,
    ]
    .into_iter()
    .map(|model| {
        let directory = model_cache_directory(&home, model);
        let installed = model_files_present_for(&directory, model);
        let size_bytes = if installed {
            model_cache_size(&directory)
        } else {
            0
        };
        DictationModelInventoryEntry {
            model_id: model.id(),
            model: model.display_name(),
            state: if installed {
                ModelState::Installed
            } else {
                ModelState::NotInstalled
            },
            size_bytes,
        }
    })
    .collect())
}

#[cfg(target_os = "macos")]
fn model_cache_size(root: &std::path::Path) -> u64 {
    let Ok(entries) = std::fs::read_dir(root) else {
        return 0;
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| {
            let path = entry.path();
            let Ok(metadata) = std::fs::symlink_metadata(&path) else {
                return 0;
            };
            if metadata.file_type().is_symlink() {
                return 0;
            }
            if metadata.is_file() {
                metadata.len()
            } else if metadata.is_dir() {
                model_cache_size(&path)
            } else {
                0
            }
        })
        .sum()
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_model_delete(
    model_id: String,
    runtime: State<'_, DictationRuntime>,
) -> Result<Vec<DictationModelInventoryEntry>, String> {
    let model = DictationModel::from_id(&model_id)
        .ok_or_else(|| "Choose one of the supported local speech models".to_string())?;
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation model storage is unavailable".to_string())?;
    if !model_delete_allowed(
        current.model == model,
        current.model_state,
        current.capture_active,
        current.hotkey_state != HotkeyState::Disabled,
        current.meeting_recording,
    ) {
        return Err(format!(
            "{} is the model in use. Stop recording and turn off the {} shortcut, or switch to another model, before removing it",
            model.display_name(),
            current.hotkey_key.display_name()
        ));
    }
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "The local model folder is unavailable".to_string())?;
    let model_path = model_cache_directory(&home, model);
    let cache_root = if model.whisper_variant().is_some() {
        home.join("Library/Application Support/OfficeKit/Models")
    } else {
        home.join("Library/Application Support/FluidAudio/Models")
    };
    if !path_is_safe_model_child(&cache_root, &model_path) {
        return Err("The local model path is not safe to remove".into());
    }
    match std::fs::symlink_metadata(&model_path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            return Err("The local model folder is not safe to remove".into());
        }
        Ok(_) => std::fs::remove_dir_all(&model_path)
            .map_err(|_| "Could not remove this local model".to_string())?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("Could not verify the local model folder".into()),
    }
    if current.model == model {
        current.engine = None;
        current.model_state = ModelState::NotInstalled;
        current.model_progress = None;
    }
    drop(current);
    dictation_model_inventory()
}

#[cfg(target_os = "macos")]
fn path_is_safe_model_child(root: &std::path::Path, child: &std::path::Path) -> bool {
    if !root.is_absolute()
        || !child.is_absolute()
        || !child.starts_with(root)
        || child == root
        || child.components().any(|component| {
            matches!(
                component,
                std::path::Component::CurDir | std::path::Component::ParentDir
            )
        })
    {
        return false;
    }
    let mut current = std::path::PathBuf::from(std::path::MAIN_SEPARATOR.to_string());
    for component in child
        .components()
        .filter(|part| matches!(part, std::path::Component::Normal(_)))
    {
        current.push(component);
        match std::fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
                return false;
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return true,
            Err(_) => return false,
        }
    }
    true
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_model_inventory() -> Result<Vec<DictationModelInventoryEntry>, String> {
    Err("Local speech models are available in the macOS app".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_model_delete(_model_id: String) -> Result<Vec<DictationModelInventoryEntry>, String> {
    Err("Local speech models are available in the macOS app".into())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_model_select(
    model_id: String,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationModelStatus, String> {
    let model = DictationModel::from_id(&model_id)
        .ok_or_else(|| "Choose one of the supported local speech models".to_string())?;
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation model selection is unavailable".to_string())?;
    if current.model == model {
        let mut status = dictation_status_for(current.model_state, current.model);
        status.progress = current.model_progress.clone();
        return Ok(status);
    }
    if !model_switch_allowed(
        current.model_state,
        current.capture_active,
        current.hotkey_state != HotkeyState::Disabled,
    ) {
        return Err(format!(
            "Disable the {} shortcut, stop recording, and wait for setup before switching models",
            current.hotkey_key.display_name()
        ));
    }
    current.model = model;
    current.translate_to_english = false;
    current.spoken_language = None;
    current.engine = None;
    current.model_state = if !cfg!(target_arch = "aarch64")
        || (model == DictationModel::Qwen3Asr && !qwen3_supported_on_current_os())
    {
        ModelState::Unsupported
    } else if cfg!(target_arch = "aarch64") {
        let home = std::env::var_os("HOME").map(std::path::PathBuf::from);
        if home.is_some_and(|home| model_files_present_for(&model.cache_directory(&home), model)) {
            ModelState::Installed
        } else {
            ModelState::NotInstalled
        }
    } else {
        ModelState::Unsupported
    };
    current.model_progress = None;
    Ok(dictation_status_for(current.model_state, current.model))
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_set_translation_mode(
    enabled: bool,
    runtime: State<'_, DictationRuntime>,
) -> Result<bool, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation mode is unavailable".to_string())?;
    if current.capture_active || current.meeting_recording {
        return Err("Stop recording before changing dictation mode".into());
    }
    if enabled && !current.model.whisper_supports_english_translation() {
        return Err("Speech-to-English translation requires Whisper Medium or Large v3".into());
    }
    current.translate_to_english = enabled;
    Ok(enabled)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_set_spoken_language(
    language: String,
    runtime: State<'_, DictationRuntime>,
) -> Result<Option<String>, String> {
    const LANGUAGES: &[&str] = &[
        "ar", "bn", "de", "en", "es", "fr", "gu", "hi", "id", "ja", "kn", "ko", "ml", "mr", "ms",
        "pt", "ru", "si", "ta", "te", "th", "ur", "zh",
    ];
    let selected = if language == "auto" {
        None
    } else if LANGUAGES.contains(&language.as_str()) {
        Some(language)
    } else {
        return Err("Choose a supported spoken language or Auto-detect".into());
    };
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation language preference is unavailable".to_string())?;
    if current.capture_active || current.meeting_recording {
        return Err("Stop recording before changing the spoken language".into());
    }
    if selected.is_some() && current.model.whisper_variant().is_none() {
        return Err("Spoken-language hints are available with Whisper models".into());
    }
    current.spoken_language = selected.clone();
    Ok(selected)
}

#[tauri::command]
fn dictation_set_llm_polish(
    enabled: bool,
    runtime: State<'_, DictationRuntime>,
) -> Result<bool, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation cleanup settings are unavailable".to_string())?;
    current.llm_polish = enabled;
    Ok(enabled)
}

#[tauri::command]
fn dictation_polish_available() -> bool {
    #[cfg(target_os = "macos")]
    {
        unsafe { officekit_dictation_polish_available() != 0 }
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

#[tauri::command]
fn dictation_set_streaming_commit(
    enabled: bool,
    runtime: State<'_, DictationRuntime>,
) -> Result<bool, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation speed settings are unavailable".to_string())?;
    current.streaming_commit = enabled;
    Ok(enabled)
}

fn raw_audio_directory(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|directory| directory.join("raw-audio"))
        .map_err(|_| "The raw audio folder is unavailable".to_string())
}

/// Turn the troubleshooting copy of each dictation's raw audio on or off (off at every launch
/// until the page asks). Turning it off keeps what is saved until it expires or is cleared.
#[tauri::command]
fn dictation_set_raw_audio(
    enabled: bool,
    app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
) -> Result<bool, String> {
    let directory = enabled.then(|| raw_audio_directory(&app)).transpose()?;
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation settings are unavailable".to_string())?;
    current.raw_audio_directory = directory;
    Ok(enabled)
}

#[tauri::command]
fn raw_audio_status(app: tauri::AppHandle) -> Result<raw_audio::Stats, String> {
    Ok(raw_audio::stats(&raw_audio_directory(&app)?))
}

#[tauri::command]
fn raw_audio_clear(app: tauri::AppHandle) -> Result<usize, String> {
    Ok(raw_audio::clear(&raw_audio_directory(&app)?))
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn raw_audio_show(app: tauri::AppHandle) -> Result<(), String> {
    let directory = raw_audio_directory(&app)?;
    std::fs::create_dir_all(&directory)
        .map_err(|_| "The raw audio folder could not be opened".to_string())?;
    std::process::Command::new("open")
        .arg(&directory)
        .spawn()
        .map(|_| ())
        .map_err(|_| "The raw audio folder could not be opened".to_string())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn raw_audio_show(_app: tauri::AppHandle) -> Result<(), String> {
    Err("Showing the raw audio folder is available on macOS only".to_string())
}

/// Delete expired raw audio now and then every hour, whether or not the switch is on.
fn start_raw_audio_sweeper(app: &tauri::AppHandle) {
    let Ok(directory) = raw_audio_directory(app) else {
        return;
    };
    let _ = thread::Builder::new()
        .name("raw-audio-sweep".into())
        .spawn(move || loop {
            if let Some(now) = unix_now() {
                raw_audio::sweep(&directory, now);
            }
            thread::sleep(Duration::from_secs(60 * 60));
        });
}

#[tauri::command]
fn dictation_set_context_options(
    app_context: bool,
    field_text: bool,
    runtime: State<'_, DictationRuntime>,
) -> Result<(), String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation context settings are unavailable".to_string())?;
    current.context_options = dictation_quality::ContextOptions {
        app_context,
        field_text,
    };
    if !current.context_options.wants_context() {
        current.clear_focus_context();
    }
    Ok(())
}

#[tauri::command]
fn dictation_set_vocabulary(
    terms: Vec<String>,
    runtime: State<'_, DictationRuntime>,
) -> Result<usize, String> {
    let accepted = dictation_quality::validate_vocabulary_terms(&terms)?;
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation vocabulary is unavailable".to_string())?;
    current.vocabulary_terms = accepted;
    Ok(current.vocabulary_terms.len())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_set_spoken_language(_language: String) -> Result<Option<String>, String> {
    Err("Spoken-language hints are available in the macOS app".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_set_translation_mode(_enabled: bool) -> Result<bool, String> {
    Err("Local speech translation is available in the macOS app".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_model_select(_model_id: String) -> Result<DictationModelStatus, String> {
    Err(dictation_status_for(ModelState::Unsupported, DictationModel::ParakeetV3).message)
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn dictation_prepare_model(
    app: tauri::AppHandle,
    runtime: State<'_, DictationRuntime>,
) -> Result<DictationModelStatus, String> {
    let mut current = runtime
        .0
        .lock()
        .map_err(|_| "Dictation model setup is unavailable".to_string())?;
    match request_prepare(current.model_state) {
        PrepareDecision::Unsupported => {
            return Err(dictation_status_for(ModelState::Unsupported, current.model).message);
        }
        PrepareDecision::AlreadyPreparing => {
            let mut status = dictation_status_for(ModelState::Preparing, current.model);
            status.progress = current.model_progress.clone();
            return Ok(status);
        }
        PrepareDecision::AlreadyReady => {
            return Ok(dictation_status_for(ModelState::Ready, current.model))
        }
        PrepareDecision::Start => {
            current.model_state = ModelState::Preparing;
            current.model_progress = Some(DictationModelProgress {
                phase: "checking",
                fraction: Some(0.0),
                bytes_downloaded: None,
                bytes_total: None,
                completed_files: None,
                total_files: None,
            });
        }
    }
    let model = current.model;
    let registered_engine = current.engine.as_ref().and_then(|engine| {
        let failed = engine.try_lock().is_ok_and(|model| model.error().is_some());
        (!failed).then(|| engine.clone())
    });
    drop(current);

    let spawn_result = thread::Builder::new()
        .name("officekit-speech-model-setup".into())
        .spawn(move || {
            // Explicit preparation resolves the same registered slot as first use.
            // Do not load a second model alongside a preview or Coach decode.
            if let Some(engine) = registered_engine {
                let result = engine
                    .lock()
                    .map_err(|_| "The local speech model is unavailable".to_string())
                    .and_then(|mut model| model.get_or_load().map(|_| ()));
                if let Some(runtime) = app.try_state::<DictationRuntime>() {
                    if let Ok(mut current) = runtime.0.lock() {
                        current.model_state = if result.is_ok() {
                            ModelState::Ready
                        } else {
                            ModelState::Failed
                        };
                        current.model_progress = None;
                    }
                }
                return;
            }
            let prepared = if model.whisper_variant().is_some() {
                load_whisper_context(model, &app).map(DictationEngine::Whisper)
            } else {
                FluidAudio::new()
                    .map_err(|_| "Could not initialize local speech".to_string())
                    .and_then(|engine| {
                        if !engine.is_apple_silicon() {
                            return Err("This model requires Apple Silicon".to_string());
                        }
                        match model {
                            DictationModel::ParakeetV2 => {
                                let context = Box::new(FluidModelProgressContext {
                                    app: app.clone(),
                                    model,
                                });
                                let context_ptr = (&*context as *const FluidModelProgressContext)
                                    .cast_mut()
                                    .cast::<std::ffi::c_void>();
                                engine
                                    .init_asr_version_with_progress(
                                        2,
                                        fluid_model_progress_callback,
                                        context_ptr,
                                    )
                                    .map(|()| DictationEngine::Fluid(engine))
                                    .map_err(|_| "Could not load Parakeet v2".to_string())
                            }
                            DictationModel::ParakeetV3 => {
                                let context = Box::new(FluidModelProgressContext {
                                    app: app.clone(),
                                    model,
                                });
                                let context_ptr = (&*context as *const FluidModelProgressContext)
                                    .cast_mut()
                                    .cast::<std::ffi::c_void>();
                                engine
                                    .init_asr_version_with_progress(
                                        3,
                                        fluid_model_progress_callback,
                                        context_ptr,
                                    )
                                    .map(|()| DictationEngine::Fluid(engine))
                                    .map_err(|_| "Could not load Parakeet v3".to_string())
                            }
                            DictationModel::Qwen3Asr => {
                                let context = Box::new(FluidModelProgressContext {
                                    app: app.clone(),
                                    model,
                                });
                                let context_ptr = (&*context as *const FluidModelProgressContext)
                                    .cast_mut()
                                    .cast::<std::ffi::c_void>();
                                engine
                                    .init_qwen3_asr_with_progress(
                                        fluid_model_progress_callback,
                                        context_ptr,
                                    )
                                    .map(|()| DictationEngine::Fluid(engine))
                                    .map_err(|_| "Could not load Qwen3 ASR".to_string())
                            }
                            DictationModel::WhisperTiny
                            | DictationModel::WhisperBase
                            | DictationModel::WhisperSmall
                            | DictationModel::WhisperMedium
                            | DictationModel::WhisperLargeV3
                            | DictationModel::WhisperLargeV3Turbo
                            | DictationModel::WhisperLargeV3TurboQ5 => {
                                Err("The selected speech model is unavailable".to_string())
                            }
                        }
                    })
            };

            if let Some(runtime) = app.try_state::<DictationRuntime>() {
                if let Ok(mut current) = runtime.0.lock() {
                    match prepared {
                        Ok(engine) => {
                            current.engine = Some(Arc::new(Mutex::new(
                                speech_model::SpeechModel::loaded(engine),
                            )));
                            current.model_state = ModelState::Ready;
                            current.model_progress = None;
                        }
                        Err(_) => {
                            current.model_state = ModelState::Failed;
                            current.model_progress = None;
                        }
                    }
                }
            }
        });

    if spawn_result.is_err() {
        if let Ok(mut current) = runtime.0.lock() {
            current.model_state = ModelState::Failed;
        }
        return Err("Could not start speech model setup".into());
    }

    Ok(dictation_status_for(ModelState::Preparing, model))
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn dictation_prepare_model() -> Result<DictationModelStatus, String> {
    Err(dictation_status_for(ModelState::Unsupported, DictationModel::ParakeetV3).message)
}

#[tauri::command]
fn check_backend_status(
    token: State<'_, BackendApiToken>,
    address: State<'_, BackendApiAddress>,
) -> Result<String, String> {
    if backend_is_ready(address.0, &token.0) {
        Ok("OfficeKit local API is ready".into())
    } else {
        Err("OfficeKit local API is not ready".into())
    }
}

#[tauri::command]
fn officekit_api_token(token: State<'_, BackendApiToken>) -> String {
    token.0.clone()
}

#[tauri::command]
fn officekit_api_origin(address: State<'_, BackendApiAddress>) -> String {
    format!("http://{}", address.0)
}

#[tauri::command]
fn file_intake_pending(
    queue: State<'_, workspace_native::FileIntakeQueue>,
) -> Result<Vec<serde_json::Value>, String> {
    queue.pending()
}

#[tauri::command]
fn file_intake_ack(
    selection_id: String,
    queue: State<'_, workspace_native::FileIntakeQueue>,
) -> Result<(), String> {
    queue.acknowledge(&selection_id)
}

fn backend_is_ready(address: SocketAddr, token: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&address, BACKEND_CONNECT_TIMEOUT) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(BACKEND_CONNECT_TIMEOUT));
    let request = health_request(&address.to_string(), token);
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::with_capacity(512);
    if stream
        .take((MAX_HEALTH_RESPONSE_BYTES + 1) as u64)
        .read_to_end(&mut response)
        .is_err()
        || response.len() > MAX_HEALTH_RESPONSE_BYTES
    {
        return false;
    }
    health_response_is_accepted(&response)
}

fn health_request(address: &str, token: &str) -> String {
    format!(
        "GET /api/health HTTP/1.0\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    )
}

fn startup_event_is_failure(event: &CommandEvent) -> bool {
    matches!(event, CommandEvent::Terminated(_) | CommandEvent::Error(_))
}

fn health_response_is_accepted(response: &[u8]) -> bool {
    if response.len() > MAX_HEALTH_RESPONSE_BYTES {
        return false;
    }
    let Ok(response) = std::str::from_utf8(response) else {
        return false;
    };
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    if !headers
        .lines()
        .next()
        .is_some_and(|line| line.starts_with("HTTP/1.1 200 ") || line.starts_with("HTTP/1.0 200 "))
    {
        return false;
    }
    let Ok(payload) = serde_json::from_str::<serde_json::Value>(body) else {
        return false;
    };
    payload.get("service").and_then(|value| value.as_str()) == Some("officekit-api")
        && payload.get("status").and_then(|value| value.as_str()) == Some("ok")
        && payload.get("version").and_then(|value| value.as_str()) == Some(BACKEND_VERSION)
}

#[cfg(test)]
fn cleanup_dictation_text(
    address: SocketAddr,
    token: &str,
    transcript: &str,
    dictionary: &BTreeMap<String, String>,
) -> Result<String, String> {
    cleanup_dictation_text_with(
        address,
        token,
        transcript,
        dictionary,
        &dictation_quality::CleanupOptions::default(),
        &[],
    )
    .map(|outcome| outcome.text)
}

const POLISH_TIMEOUT_MILLISECONDS: u64 = 4_000;

#[cfg(target_os = "macos")]
fn polish_with_system_model(text: &str) -> Result<String, &'static str> {
    let mut output = vec![0_u8; text.len().saturating_mul(2).max(256)];
    let written = unsafe {
        officekit_dictation_polish(
            text.as_ptr(),
            text.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            POLISH_TIMEOUT_MILLISECONDS,
        )
    };
    let written = usize::try_from(written).map_err(|_| "output-too-large")?;
    if written == 0 {
        return Err("model-unavailable");
    }
    let rewritten = std::str::from_utf8(&output[..written]).map_err(|_| "invalid-output")?;
    dictation_quality::accept_llm_output(text, rewritten)
}

fn cleanup_dictation_text_with(
    address: SocketAddr,
    token: &str,
    transcript: &str,
    dictionary: &BTreeMap<String, String>,
    options: &dictation_quality::CleanupOptions<'_>,
    words: &[String],
) -> Result<CleanupOutcome, String> {
    if !address.ip().is_loopback()
        || !token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        || validate_dictionary(dictionary).is_err()
        || transcript.len() > 262_144
    {
        return Err("Dictation cleanup input is invalid".into());
    }
    let mut request = dictation_quality::cleanup_request_body(transcript, dictionary, options);
    request["include_steps"] = true.into();
    if !words.is_empty() {
        request["words"] = serde_json::json!(words);
    }
    let body =
        serde_json::to_vec(&request).map_err(|_| "Local transcript cleanup failed".to_string())?;
    if body.len() > MAX_DICTATION_CLEANUP_RESPONSE_BYTES {
        return Err("Dictation cleanup input is too large".into());
    }

    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(500))
        .map_err(|_| "Local transcript cleanup is unavailable".to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .map_err(|_| "Local transcript cleanup is unavailable".to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(5)))
        .map_err(|_| "Local transcript cleanup is unavailable".to_string())?;
    write!(
        stream,
        "POST /api/dictate/cleanup HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .and_then(|_| stream.write_all(&body))
    .map_err(|_| "Local transcript cleanup is unavailable".to_string())?;

    let mut response = Vec::new();
    stream
        .take((MAX_DICTATION_CLEANUP_RESPONSE_BYTES + 1) as u64)
        .read_to_end(&mut response)
        .map_err(|_| "Local transcript cleanup failed".to_string())?;
    if response.len() > MAX_DICTATION_CLEANUP_RESPONSE_BYTES {
        return Err("Local transcript cleanup returned an oversized response".into());
    }
    let boundary = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "Local transcript cleanup returned an invalid response".to_string())?;
    let headers = std::str::from_utf8(&response[..boundary])
        .map_err(|_| "Local transcript cleanup returned an invalid response".to_string())?;
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse::<u16>().ok());
    let response_body = &response[boundary + 4..];
    if status != Some(200) {
        return Err("Local transcript cleanup failed".into());
    }
    let content_length = headers.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse::<usize>().ok())
            .flatten()
    });
    if content_length != Some(response_body.len()) {
        return Err("Local transcript cleanup returned an incomplete response".into());
    }
    let payload: serde_json::Value = serde_json::from_slice(response_body)
        .map_err(|_| "Local transcript cleanup returned an invalid response".to_string())?;
    let cleaned = payload
        .get("cleaned_text")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "Local transcript cleanup returned an invalid response".to_string())?;
    validate_paste_text(cleaned)
        .map_err(|_| "Local transcript cleanup returned an invalid result".to_string())?;
    // The steps are best-effort: a missing or odd shape never blocks the paste.
    let steps = payload.get("steps");
    let after_smart = steps
        .and_then(|steps| steps.get("after_smart"))
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);
    let dictionary_changes = steps
        .and_then(|steps| steps.get("dictionary_changes"))
        .and_then(serde_json::Value::as_array)
        .map(|changes| {
            changes
                .iter()
                .filter_map(|change| {
                    Some(DictionaryChange {
                        from: change.get("from")?.as_str()?.to_string(),
                        to: change.get("to")?.as_str()?.to_string(),
                    })
                })
                .take(50)
                .collect()
        })
        .unwrap_or_default();
    Ok(CleanupOutcome {
        text: cleaned.to_string(),
        after_smart,
        dictionary_changes,
    })
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendProcess>() {
        if let Ok(mut child_slot) = state.0.lock() {
            if let Some(child) = child_slot.take() {
                let _ = child.kill();
            }
        }
    }
}

#[cfg(target_os = "macos")]
fn stop_dictation(app: &tauri::AppHandle) {
    if let Some(runtime) = app.try_state::<DictationRuntime>() {
        if let Ok(mut current) = runtime.0.lock() {
            current.hotkey_state = HotkeyState::Disabled;
            if current.meeting_recording {
                if let Some(tx) = current.meeting_stop_tx.take() {
                    let _ = tx.send(());
                }
                current.meeting_recording = false;
            }
            if current.capture_active {
                let _ = unsafe { officekit_dictation_stop_capture() };
                current.set_capture_active(false);
                current.clear_session_text();
            }
            unsafe { officekit_dictation_clear_samples() };
        }
    }
    unsafe { officekit_dictation_stop_hotkey_monitor() };
}

#[cfg(not(target_os = "macos"))]
fn stop_dictation(_app: &tauri::AppHandle) {}

fn license_guarded<R, F>(
    gate: LicenseGate,
    inner: F,
) -> impl Fn(tauri::ipc::Invoke<R>) -> bool + Send + Sync + 'static
where
    R: tauri::Runtime,
    F: Fn(tauri::ipc::Invoke<R>) -> bool + Send + Sync + 'static,
{
    license_guarded_with_clock(gate, unix_now, inner)
}

/// `license_guarded` with an injectable clock (a `None` reading denies every paid command).
fn license_guarded_with_clock<R, C, F>(
    gate: LicenseGate,
    clock: C,
    inner: F,
) -> impl Fn(tauri::ipc::Invoke<R>) -> bool + Send + Sync + 'static
where
    R: tauri::Runtime,
    C: Fn() -> Option<u64> + Send + Sync + 'static,
    F: Fn(tauri::ipc::Invoke<R>) -> bool + Send + Sync + 'static,
{
    move |invoke| {
        if let Err(code) = license_gate::command_guard(&gate, invoke.message.command(), clock()) {
            invoke.resolver.reject(code);
            return true;
        }
        inner(invoke)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    panic_log::install();
    crash_restart::startup();
    let gate = LicenseGate::new();
    license_startup_check(&gate);
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(
            GlobalShortcutBuilder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state == ShortcutState::Pressed
                        && shortcut == &workspace_native::media_clipboard_shortcut()
                    {
                        let _ = app.emit("officekit-media-clipboard-hotkey", ());
                    }
                })
                .build(),
        );
    let builder = builder.on_window_event(|window, event| {
        if let tauri::WindowEvent::Moved(position) = event {
            if window.label() == coach_workspace::WINDOW_LABEL {
                // The Live Workspace is dragged freely (also to another display) and reopens where it was left.
                coach_workspace::remember_position(window.app_handle(), position.x, position.y);
            } else if let Some(webview) = window.app_handle().get_webview_window(window.label()) {
                handle_window_moved(&webview);
            }
        }
        // A click on the reminder mascot focuses it before the web layer sends any action, and macOS can answer
        // the resulting activation with a reopen event. Noting the focus here means that reopen is ignored even
        // when it arrives after the mascot has already hidden.
        if window.label() == "ergonomics" && matches!(event, tauri::WindowEvent::Focused(true)) {
            ergonomics::note_companion_press();
        }
        #[cfg(target_os = "macos")]
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            if should_keep_background_after_main_window_close(window.label()) {
                api.prevent_close();
                let _ = window.hide();
            }
        }

        if let tauri::WindowEvent::DragDrop(tauri::DragDropEvent::Drop { paths, position }) = event
        {
            let media_target = window
                .try_state::<workspace_native::MediaDropEnabled>()
                .and_then(|enabled| enabled.target_at(position.x, position.y));
            let app = window.app_handle().clone();
            let window = window.clone();
            let paths = paths.clone();
            let address = app.state::<BackendApiAddress>().0;
            let api_token = app.state::<BackendApiToken>().0.clone();
            let native_token = app.state::<workspace_native::NativeGrantToken>().0.clone();
            tauri::async_runtime::spawn_blocking(move || {
                let result = if media_target.is_some() {
                    workspace_native::register_media_drop(paths, address, &native_token, &api_token)
                } else {
                    workspace_native::register_file_intake(
                        paths,
                        address,
                        &native_token,
                        &api_token,
                    )
                };
                if media_target.is_none() {
                    match result {
                        Ok(selection) => {
                            let id = selection
                                .get("id")
                                .cloned()
                                .unwrap_or(serde_json::Value::Null);
                            let queued = window
                                .state::<workspace_native::FileIntakeQueue>()
                                .push_with_source(selection, "drop");
                            let _ = window.emit(
                                if queued.is_ok() {
                                    "officekit-file-intake"
                                } else {
                                    "officekit-file-intake-error"
                                },
                                if queued.is_ok() {
                                    serde_json::json!({"selectionId":id})
                                } else {
                                    serde_json::json!({"message":queued.unwrap_err()})
                                },
                            );
                        }
                        Err(error) => {
                            let _ = window.emit(
                                "officekit-file-intake-error",
                                serde_json::json!({"message":error}),
                            );
                        }
                    }
                    return;
                }
                let event_name = if result.is_ok() {
                    "officekit-media-file-drop"
                } else {
                    "officekit-media-file-drop-error"
                };
                let payload = result
                    .map(|mut selection| {
                        if media_target
                            .as_deref()
                            .is_some_and(|target| target != "manual")
                        {
                            selection["presetZoneId"] =
                                serde_json::Value::String(media_target.unwrap());
                        }
                        selection
                    })
                    .unwrap_or_else(|error| serde_json::json!({"message":error}));
                let _ = window.emit(event_name, payload);
            });
        }
    });
    let builder = builder.setup(|app| {
        let coach_directory = app.path().app_data_dir()?;
        let coach_runtime = speech_coach::CoachRuntime::load(coach_directory);
        // Restoring only lets the coach join a dictation; no microphone engine is started at
        // launch (one started inside the setup hook delivered no audio).
        speech_coach::restore_saved_capture(&coach_runtime);
        #[cfg(target_os = "macos")]
        {
            let _ = COACH_PANEL_APP.set(app.handle().clone());
            unsafe { officekit_dictation_coach_set_close_callback(on_coach_panel_close) };
        }
        app.manage(coach_runtime);
        start_raw_audio_sweeper(app.handle());
        app.manage(coach_workspace::CoachWorkspaceRuntime::default());
        // Tell the webviews whenever the licence state changes so they can re-run initialisers
        // that were refused while locked. Payload: the lowercase state word only.
        let state_handle = app.handle().clone();
        app.state::<LicenseGate>().on_change(move |state| {
            let _ = state_handle.emit(license_gate::STATE_CHANGED_EVENT, state);
        });
        if ergonomics_access::profile_enabled(env!("OFFICEKIT_RELEASE_PROFILE")) {
            ergonomics::start(app.handle());
        }
        app.manage(WindowSnapState::default());
        app.manage(global_desktop::GlobalDesktopRuntime::default());
        app.manage(menu_stats::MenuStatsRuntime::default());
        menu_stats::restore(app.handle());
        app.manage(app_settings::AppSettingsRuntime::default());
        app_settings::restore(app.handle());
        if dictation_commands_enabled(env!("OFFICEKIT_RELEASE_PROFILE")) {
            window_runtime::start(app.handle());
            global_desktop::restore_on_launch(app.handle());
        }
        app.manage(workspace_native::MediaDropEnabled::default());
        app.manage(workspace_native::FileIntakeQueue::default());
        app.manage(workspace_native::MediaClipboardHotkeyEnabled::default());
        #[cfg(target_os = "macos")]
        let model_directory = app
            .path()
            .home_dir()
            .ok()
            .map(|home| model_cache_directory(&home, DictationModel::ParakeetV3));
        #[cfg(not(target_os = "macos"))]
        let model_directory: Option<std::path::PathBuf> = None;
        let apple_silicon = cfg!(target_os = "macos") && cfg!(target_arch = "aarch64");
        app.manage(DictationRuntime::new(
            model_directory.as_deref(),
            apple_silicon,
        ));
        #[cfg(target_os = "macos")]
        thread::Builder::new()
            .name("officekit-speech-coach-asr".into())
            .spawn({
                let handle = app.handle().clone();
                move || run_speech_coach_analyzer(handle)
            })
            .map_err(|error| {
                std::io::Error::other(format!("Speech Coach analyzer could not start: {error}"))
            })?;

        let address = select_backend_address()?;
        app.manage(BackendApiAddress(address));

        let api_token = Uuid::new_v4().to_string();
        let native_token = Uuid::new_v4().to_string();
        let backend_command = app
            .shell()
            .sidecar("officekit-backend")
            .map_err(|error| {
                std::io::Error::other(format!("OfficeKit backend sidecar is missing: {error}"))
            })?
            .env("OFFICEKIT_API_TOKEN", &api_token)
            .env("OFFICEKIT_NATIVE_GRANT_TOKEN", &native_token)
            .env("OFFICEKIT_APP_VERSION", env!("CARGO_PKG_VERSION"))
            .env(
                "OFFICEKIT_RELEASE_MANIFEST_URL",
                "https://officekit.app/releases/latest.json",
            )
            .env(
                "OFFICEKIT_RELEASE_PROFILE",
                env!("OFFICEKIT_RELEASE_PROFILE"),
            )
            .env("OFFICEKIT_API_PORT", address.port().to_string());
        #[cfg(debug_assertions)]
        let backend_command = {
            let candidate = format!(
                "{}/../.build/backend-sidecar/dist/officekit-backend/officekit-backend",
                env!("CARGO_MANIFEST_DIR")
            );
            if std::path::Path::new(&candidate).is_file() {
                backend_command.env("OFFICEKIT_BACKEND_EXECUTABLE", candidate)
            } else {
                backend_command
            }
        };
        let (mut events, child) = backend_command.spawn().map_err(|error| {
            std::io::Error::other(format!("OfficeKit backend failed to start: {error}"))
        })?;
        app.manage(BackendApiToken(api_token.clone()));
        let push_client =
            license_gate::LoopbackEntitlementClient::new(address, &api_token, &native_token)
                .map(Arc::new)
                .map_err(|_| {
                    std::io::Error::other("OfficeKit licence push could not be configured")
                })?;
        app.manage(LicensePushClient(push_client.clone()));
        if dictation_commands_enabled(env!("OFFICEKIT_RELEASE_PROFILE")) {
            global_clipboard::start(app.handle());
        }
        app.manage(workspace_native::NativeGrantToken(native_token));
        app.manage(BackendProcess(Mutex::new(Some(child))));
        if let Err(error) = workspace_native::install_tray(app.handle()) {
            stop_backend(app.handle());
            return Err(error.into());
        }

        let deadline = Instant::now() + BACKEND_START_TIMEOUT;
        while Instant::now() < deadline {
            if events
                .try_recv()
                .is_ok_and(|event| startup_event_is_failure(&event))
            {
                stop_backend(app.handle());
                return Err(std::io::Error::new(
                    std::io::ErrorKind::BrokenPipe,
                    "OfficeKit backend exited before it became healthy",
                )
                .into());
            }
            if backend_is_ready(address, &api_token) {
                // Startup push (the API answers /api/health), then every PUSH_INTERVAL.
                let gate = app.state::<LicenseGate>().inner().clone();
                thread::spawn(move || {
                    license_gate::run_push_loop(
                        |delay| {
                            thread::sleep(delay);
                            true
                        },
                        || license_push_tick(&gate, &push_client),
                    );
                });
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = events.recv().await {
                        if let CommandEvent::Terminated(_) = event {
                            break;
                        }
                    }
                });
                return Ok(());
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop_backend(app.handle());
        Err(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            "OfficeKit backend did not become healthy within 120 seconds",
        )
        .into())
    });
    // Every webview invoke passes `command_guard` first: exempt commands run, paid and
    // unclassified commands are rejected with `license_required` unless the licence is Active.
    let guard_gate = gate.clone();
    let builder = builder.manage(gate);
    let builder = if dictation_commands_enabled(env!("OFFICEKIT_RELEASE_PROFILE")) {
        builder.invoke_handler(restrict_companion_invoke(license_guarded(
            guard_gate,
            tauri::generate_handler![
                ergonomics::ergonomics_get_state,
                ergonomics::ergonomics_update_settings,
                ergonomics::ergonomics_reminder_action,
                ergonomics::ergonomics_preview,
                ergonomics::ergonomics_motion_action,
                ergonomics::ergonomics_calendar_action,
                ergonomics::ergonomics_quick_controls_status,
                ergonomics::ergonomics_quick_controls_set_enabled,
                window_snap,
                window_snap_set_edge_enabled,
                check_backend_status,
                open_network_settings,
                open_cloudflare_speed_test,
                officekit_api_token,
                officekit_api_origin,
                file_intake_pending,
                file_intake_ack,
                workspace_native::file_selection_open,
                invoice_native::invoice_library_reconnect,
                workspace_native::media_toolkit_drop_set_enabled,
                workspace_native::media_clipboard_hotkey_set_enabled,
                workspace_native::media_clipboard_revision,
                workspace_native::media_finder_action_status,
                workspace_native::media_finder_action_install,
                workspace_native::media_finder_action_remove,
                workspace_native::finder_open_in_status,
                workspace_native::finder_open_in_set,
                crash_restart::crash_restart_status,
                crash_restart::crash_restart_set,
                crash_restart::crash_notice_pending,
                crash_restart::crash_notice_dismiss,
                workspace_native::media_folder_watch_open,
                workspace_native::media_handoff_capabilities,
                workspace_native::media_handoff_open,
                workspace_native::file_job_reveal,
                agent_settings::agent_helper_status,
                agent_settings::agent_settings_read,
                agent_settings::agent_settings_write,
                agent_settings::agent_choose_folders,
                agent_settings::agent_reveal_output,
                agent_settings::agent_skill_status,
                agent_settings::agent_skill_install,
                workspace_native::pdf_signing_provider_open,
                workspace_native::storage_scan_start,
                workspace_native::storage_cleanup_apply,
                workspace_native::trash_restore_confirm,
                workspace_native::trash_restore_apply,
                workspace_native::trash_record_forget,
                workspace_native::trash_restore_reveal,
                workspace_native::storage_permissions_open,
                workspace_native::file_output_choose,
                workspace_native::result_copy_text,
                workspace_native::result_save,
                workspace_native::officekit_quit,
                workspace_native::quick_access_recording,
                workspace_native::tray_stats_update,
                workspace_native::menu_drawers_update,
                workspace_native::menu_drawers_remove,
                menu_stats::menu_stats_status,
                menu_stats::menu_stats_adopt_legacy,
                system_sensors::system_sensor_metrics,
                system_hardware::system_hardware_metrics,
                app_settings::app_settings_status,
                app_settings::app_settings_save,
                meeting_calendar::calendar_permission_status,
                meeting_calendar::calendar_permission_request,
                launcher_apps::list_installed_apps,
                global_clipboard::launcher_recent_tools,
                global_clipboard::global_panel_set_dictations,
                license_status,
                license_activate,
                license_deactivate,
                support_ticket_submit,
                support_ticket_updates,
                license_state,
                dictation_model_status,
                dictation_model_inventory,
                dictation_model_delete,
                dictation_model_select,
                dictation_set_translation_mode,
                dictation_set_spoken_language,
                dictation_set_vocabulary,
                dictation_set_context_options,
                dictation_set_streaming_commit,
                dictation_set_raw_audio,
                raw_audio_status,
                raw_audio_clear,
                raw_audio_show,
                dictation_set_llm_polish,
                dictation_polish_available,
                dictation_prepare_model,
                dictation_microphone_permission,
                dictation_request_microphone_permission,
                dictation_open_permission_settings,
                dictation_accessibility_permission,
                dictation_request_accessibility_permission,
                dictation_capture_start,
                dictation_capture_stop,
                dictation_transcribe_audio_file,
                quick_access_transcribe,
                coach_workspace::coach_workspace_snapshot,
                coach_workspace::coach_workspace_corrected_text,
                coach_workspace::coach_workspace_dismiss,
                coach_workspace::coach_workspace_done,
                coach_workspace::coach_workspace_clear,
                coach_workspace::coach_workspace_open_apple_intelligence,
                speech_coach::speech_coach_status,
                speech_coach::speech_coach_configure,
                speech_coach::speech_coach_set_enabled,
                speech_coach::speech_coach_set_paused,
                speech_coach::speech_coach_notes,
                coach_rules::speech_coach_rules,
                speech_coach::speech_coach_record_session,
                speech_coach::speech_coach_clear_notes,
                speech_coach::speech_coach_dismiss_pattern,
                speech_coach::speech_coach_set_pattern_dismissed,
                speech_coach::speech_coach_set_pattern_useful,
                dictation_hotkey_status,
                dictation_hotkey_configure,
                dictation_hotkey_configure_custom,
                dictation_hotkey_enable,
                dictation_hotkey_disable,
                dictation_paste_text,
                dictation_cleanup_and_paste,
                dictation_meeting_record_start,
                dictation_meeting_record_stop,
                dictation_meeting_status,
                dictation_screen_recording_permission,
                dictation_request_screen_recording_permission,
                global_desktop::global_desktop_status,
                global_desktop::global_desktop_configure,
                global_desktop::global_desktop_refresh,
                global_desktop::global_desktop_default_shortcuts,
                screenshot_shortcut_configure,
                screenshot_capture,
                quick_controls_status,
                quick_controls_set_tool,
                quick_controls_set_hud_position,
                quick_controls_disable_all
            ],
        )))
    } else {
        builder.invoke_handler(restrict_companion_invoke(license_guarded(
            guard_gate,
            tauri::generate_handler![
                window_snap,
                window_snap_set_edge_enabled,
                check_backend_status,
                open_network_settings,
                open_cloudflare_speed_test,
                officekit_api_token,
                officekit_api_origin,
                file_intake_pending,
                file_intake_ack,
                workspace_native::file_selection_open,
                invoice_native::invoice_library_reconnect,
                workspace_native::media_toolkit_drop_set_enabled,
                workspace_native::media_clipboard_hotkey_set_enabled,
                workspace_native::media_clipboard_revision,
                workspace_native::media_finder_action_status,
                workspace_native::media_finder_action_install,
                workspace_native::media_finder_action_remove,
                workspace_native::finder_open_in_status,
                workspace_native::finder_open_in_set,
                crash_restart::crash_restart_status,
                crash_restart::crash_restart_set,
                crash_restart::crash_notice_pending,
                crash_restart::crash_notice_dismiss,
                workspace_native::media_folder_watch_open,
                workspace_native::media_handoff_capabilities,
                workspace_native::media_handoff_open,
                workspace_native::file_job_reveal,
                agent_settings::agent_helper_status,
                agent_settings::agent_settings_read,
                agent_settings::agent_settings_write,
                agent_settings::agent_choose_folders,
                agent_settings::agent_reveal_output,
                agent_settings::agent_skill_status,
                agent_settings::agent_skill_install,
                workspace_native::pdf_signing_provider_open,
                workspace_native::storage_scan_start,
                workspace_native::storage_cleanup_apply,
                workspace_native::trash_restore_confirm,
                workspace_native::trash_restore_apply,
                workspace_native::trash_record_forget,
                workspace_native::trash_restore_reveal,
                workspace_native::storage_permissions_open,
                workspace_native::file_output_choose,
                workspace_native::result_copy_text,
                workspace_native::result_save,
                workspace_native::officekit_quit,
                workspace_native::quick_access_recording,
                workspace_native::tray_stats_update,
                workspace_native::menu_drawers_update,
                workspace_native::menu_drawers_remove,
                menu_stats::menu_stats_status,
                menu_stats::menu_stats_adopt_legacy,
                system_sensors::system_sensor_metrics,
                system_hardware::system_hardware_metrics,
                app_settings::app_settings_status,
                app_settings::app_settings_save,
                meeting_calendar::calendar_permission_status,
                meeting_calendar::calendar_permission_request,
                launcher_apps::list_installed_apps,
                global_clipboard::launcher_recent_tools,
                global_clipboard::global_panel_set_dictations,
                license_status,
                license_activate,
                license_deactivate,
                support_ticket_submit,
                support_ticket_updates,
                license_state,
                screenshot_shortcut_configure,
                screenshot_capture,
                ergonomics::ergonomics_quick_controls_status,
                ergonomics::ergonomics_quick_controls_set_enabled,
                quick_controls_status,
                quick_controls_set_tool,
                quick_controls_set_hud_position,
                quick_controls_disable_all
            ],
        )))
    };
    builder
        .build(tauri::generate_context!())
        .expect("error while building OfficeKit Tauri application")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let RunEvent::Opened { urls } = &event {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                let paths = urls
                    .iter()
                    .filter_map(|url| url.to_file_path().ok())
                    .collect::<Vec<_>>();
                if !paths.is_empty() {
                    let app_handle = app.clone();
                    let address = app.state::<BackendApiAddress>().0;
                    let api_token = app.state::<BackendApiToken>().0.clone();
                    let native_token = app.state::<workspace_native::NativeGrantToken>().0.clone();
                    tauri::async_runtime::spawn_blocking(move || {
                        let result = workspace_native::register_file_intake(
                            paths,
                            address,
                            &native_token,
                            &api_token,
                        );
                        match result {
                            Ok(selection) => {
                                let id = selection
                                    .get("id")
                                    .cloned()
                                    .unwrap_or(serde_json::Value::Null);
                                let queued = app_handle
                                    .state::<workspace_native::FileIntakeQueue>()
                                    .push_with_source(selection, "open_with");
                                let _ = app_handle.emit(
                                    if queued.is_ok() {
                                        "officekit-file-intake"
                                    } else {
                                        "officekit-file-intake-error"
                                    },
                                    if queued.is_ok() {
                                        serde_json::json!({"selectionId":id})
                                    } else {
                                        serde_json::json!({"message":queued.unwrap_err()})
                                    },
                                );
                            }
                            Err(error) => {
                                let _ = app_handle.emit(
                                    "officekit-file-intake-error",
                                    serde_json::json!({"message":error}),
                                );
                            }
                        }
                    });
                }
            }
            #[cfg(target_os = "macos")]
            if let RunEvent::Reopen {
                has_visible_windows,
                ..
            } = &event
            {
                if should_show_main_window_after_reopen(
                    *has_visible_windows,
                    ergonomics::companion_hid_recently()
                        || ergonomics::companion_visible(app)
                        || coach_workspace::closed_recently(),
                ) {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            if matches!(event, RunEvent::Exit) {
                if let Some(coach) = app.try_state::<speech_coach::CoachRuntime>() {
                    let _ = speech_coach::finish_standalone_session_for_runtime(&coach);
                }
                ergonomics::shutdown(app);
                headphone_motion::shutdown();
                global_desktop::shutdown();
                stop_dictation(app);
                stop_backend(app);
                crash_restart::shutdown();
            }
        });
}

fn dictation_commands_enabled(profile: &str) -> bool {
    matches!(profile, "development" | "private-beta")
}

fn restrict_companion_invoke<F>(
    handler: F,
) -> impl Fn(tauri::ipc::Invoke<tauri::Wry>) -> bool + Send + Sync + 'static
where
    F: Fn(tauri::ipc::Invoke<tauri::Wry>) -> bool + Send + Sync + 'static,
{
    move |invoke| {
        if ergonomics_access::command_allowed(
            invoke.message.webview_ref().label(),
            invoke.message.command(),
            env!("OFFICEKIT_RELEASE_PROFILE"),
        ) {
            handler(invoke)
        } else {
            invoke
                .resolver
                .reject("This window cannot perform that action.");
            true
        }
    }
}

#[cfg(test)]
mod tests {
    use super::battery_in_power_report;
    use super::cleanup_dictation_text_with;

    #[test]
    fn a_power_report_with_an_internal_battery_means_a_laptop() {
        assert!(battery_in_power_report(
            "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1) 80%; discharging"
        ));
        assert!(!battery_in_power_report("Now drawing from 'AC Power'\n"));
        assert!(!battery_in_power_report(""));
    }

    use super::{
        cleanup_dictation_text, dictation_accessibility_status_for,
        dictation_microphone_status_for, dictation_permission_settings_url, health_request,
        health_response_is_accepted, startup_event_is_failure, with_capture_numbers, CommandEvent,
        DictionaryChange, TerminatedPayload,
    };
    use crate::dictation::MicrophonePermission;
    use crate::dictation_quality;

    #[test]
    fn the_overlay_says_no_microphone_detected_and_keeps_other_messages_short() {
        let none = super::overlay_failure_text(
            "No microphone is connected. Connect a microphone and select it in macOS Sound settings.",
        );
        assert!(none.starts_with("No microphone detected"));
        assert!(none.chars().count() <= 100);
        assert_eq!(
            super::overlay_failure_text("Allow microphone access before recording"),
            "Allow microphone access before recording"
        );
        assert_eq!(
            super::overlay_failure_text(&"x".repeat(300))
                .chars()
                .count(),
            100
        );
    }

    #[test]
    fn listen_in_sets_practice_context_and_preserves_user_coach_settings() {
        let mut settings = crate::speech_coach::CoachSettings::default();
        settings.target_pace_min = 105;
        settings.target_pace_max = 155;
        let updated = super::listen_in_practice_settings(settings);
        assert_eq!(updated.context, crate::speech_coach::CoachContext::Practice);
        assert_eq!(updated.target_pace_min, 105);
        assert_eq!(updated.target_pace_max, 155);
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn cached_whisper_validation_rejects_same_size_corruption_and_unsafe_ancestors_without_modification(
    ) {
        let root =
            std::env::temp_dir().join(format!("officekit-integrity-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let directory = root.join("whisper.cpp/medium");
        std::fs::create_dir_all(&directory).unwrap();
        let file = directory.join("model.bin");
        std::fs::write(&file, b"cached").unwrap();
        let expected = super::sha256_file(&file).unwrap();
        assert_eq!(
            super::verified_cached_whisper_file(&root, &directory, "model.bin", 6, &expected)
                .unwrap(),
            file
        );
        std::fs::write(&file, b"broken").unwrap();
        assert!(
            super::verified_cached_whisper_file(&root, &directory, "model.bin", 6, &expected)
                .unwrap_err()
                .contains("integrity")
        );
        assert_eq!(
            std::fs::read(&file).unwrap(),
            b"broken",
            "first use must not delete or replace corrupt weights"
        );
        assert!(
            super::verified_cached_whisper_file(&root, &directory, "model.bin", 7, &expected)
                .is_err()
        );
        assert!(
            super::verified_cached_whisper_file(&root, &directory, "absent.bin", 6, &expected)
                .is_err()
        );
        let alias = root.join("alias");
        std::os::unix::fs::symlink(root.join("whisper.cpp"), &alias).unwrap();
        assert!(super::verified_cached_whisper_file(
            &root,
            &alias.join("medium"),
            "model.bin",
            6,
            &expected
        )
        .unwrap_err()
        .contains("not safe"));
        let linked_file = directory.join("linked.bin");
        std::os::unix::fs::symlink(&file, &linked_file).unwrap();
        assert!(
            super::verified_cached_whisper_file(&root, &directory, "linked.bin", 6, &expected)
                .is_err()
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn first_load_failure_stops_the_affected_meeting_without_touching_a_new_or_retrying_model() {
        let runtime = super::DictationRuntime::new(None, true);
        let mut current = runtime.0.lock().unwrap();
        let failed = std::sync::Arc::new(std::sync::Mutex::new(
            super::speech_model::SpeechModel::deferred(|| Err("Cached model unavailable".into())),
        ));
        assert!(failed.lock().unwrap().get_or_load().is_err());
        current.engine = Some(failed.clone());
        current.model_state = super::ModelState::Installed;
        current.meeting_recording = true;
        current.set_capture_active(true);
        current.meeting_stop_tx = Some(std::sync::mpsc::channel().0);
        assert_eq!(
            super::mark_speech_model_failed(&mut current, &failed),
            Some(true)
        );
        assert_eq!(current.model_state, super::ModelState::Failed);
        assert!(!current.meeting_recording);
        assert!(!current.capture_active);
        assert!(current.meeting_stop_tx.is_none());
        assert_eq!(
            super::mark_speech_model_failed(&mut current, &failed),
            None,
            "report a retained failure once"
        );
        let replacement = std::sync::Arc::new(std::sync::Mutex::new(
            super::speech_model::SpeechModel::deferred(|| Err("Another slot".into())),
        ));
        current.engine = Some(replacement.clone());
        current.model_state = super::ModelState::Installed;
        assert_eq!(
            super::mark_speech_model_failed(&mut current, &failed),
            None,
            "old failures cannot affect a switched model"
        );
        current.model_state = super::ModelState::Preparing;
        assert_eq!(
            super::mark_speech_model_failed(&mut current, &replacement),
            None,
            "an explicit retry owns its state"
        );
        current.model_state = super::ModelState::Installed;
        assert_eq!(
            super::mark_speech_model_failed(&mut current, &replacement),
            Some(false)
        );
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn registering_a_downloaded_model_does_not_initialize_it_and_rejects_missing_cache() {
        let path =
            std::env::temp_dir().join(format!("officekit-deferred-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&path).unwrap();
        let runtime = super::DictationRuntime::new(None, true);
        let mut current = runtime.0.lock().unwrap();
        assert!(!super::speech_model_available(&current));
        super::register_deferred_speech_model(&mut current).unwrap();
        assert!(
            current.engine.is_none(),
            "missing models do not trigger downloads"
        );
        current.model = super::DictationModel::WhisperMedium;
        current.model_state = super::ModelState::Installed;
        assert!(
            super::register_deferred_speech_model_from_cache(&mut current, path.clone()).is_err()
        );
        assert_eq!(current.model_state, super::ModelState::NotInstalled);
        assert!(current.engine.is_none());
        let file = std::fs::File::create(path.join("ggml-medium.bin")).unwrap();
        file.set_len(1_533_763_059).unwrap();
        current.model_state = super::ModelState::Installed;
        super::register_deferred_speech_model_from_cache(&mut current, path.clone()).unwrap();
        assert!(super::speech_model_available(&current));
        let registered = current.engine.clone().unwrap();
        assert!(!registered.lock().unwrap().is_loaded());
        super::register_deferred_speech_model(&mut current).unwrap();
        assert!(
            std::sync::Arc::ptr_eq(&registered, current.engine.as_ref().unwrap()),
            "registration reuses the same deferred slot"
        );
        drop(current);
        drop(runtime);
        drop(registered);
        std::fs::remove_dir_all(path).unwrap();
    }

    #[test]
    #[cfg(target_os = "macos")]
    #[ignore = "requires the existing cached Whisper model and a synthetic WAV fixture"]
    fn cached_speech_first_use_memory_profile() {
        use super::{dictation::DictationModel, speech_model::SpeechModel};
        let fixture =
            std::env::var("OFFICEKIT_SPEECH_MEMORY_FIXTURE").expect("synthetic fixture path");
        let home = std::path::PathBuf::from(std::env::var_os("HOME").expect("home"));
        let model_id = DictationModel::WhisperMedium;
        let path = super::model_cache_directory(&home, model_id);
        assert!(
            super::model_files_present_for(&path, model_id),
            "cached Whisper Medium required; this test never downloads"
        );
        let mut samples =
            super::decode_audio_file_to_samples(std::path::Path::new(&fixture)).unwrap();
        let footprint = || {
            let output = std::process::Command::new("/usr/bin/footprint")
                .args([
                    "--noCategories",
                    "-f",
                    "bytes",
                    &std::process::id().to_string(),
                ])
                .output()
                .expect("macOS footprint");
            assert!(output.status.success());
            String::from_utf8(output.stdout)
                .unwrap()
                .lines()
                .find_map(|line| {
                    line.trim()
                        .strip_prefix("phys_footprint:")
                        .and_then(|value| value.split_whitespace().next())
                        .and_then(|value| value.parse::<u64>().ok())
                })
                .expect("physical footprint in bytes")
        };
        let mut engine =
            SpeechModel::deferred(move || super::load_cached_speech_model(model_id, &path));
        assert!(!engine.is_loaded());
        let registered = footprint();
        let first = super::transcribe_samples_buffer(
            &mut engine,
            model_id,
            &samples,
            false,
            Some("en"),
            None,
        )
        .unwrap();
        assert!(
            !first.trim().is_empty(),
            "first invocation must transcribe, not just prepare"
        );
        assert!(engine.is_loaded());
        let first_use = footprint();
        let second = super::transcribe_samples_buffer(
            &mut engine,
            model_id,
            &samples,
            false,
            Some("en"),
            None,
        )
        .unwrap();
        assert_eq!(
            first, second,
            "the loaded engine is reused on the second invocation"
        );
        let second_use = footprint();
        samples.fill(0.0);
        assert!(
            first_use > registered + 400 * 1024 * 1024,
            "Whisper Medium weights must be deferred, not allocated at registration"
        );
        println!(
            "OFFICEKIT_SPEECH_MEMORY {}",
            serde_json::json!({"registeredBytes":registered,"firstUseBytes":first_use,"secondUseBytes":second_use,"model":"whisper_medium"})
        );
    }

    #[test]
    fn captured_text_is_gone_after_a_session_is_cleared() {
        let runtime = super::DictationRuntime::new(None, true);
        let state = runtime.0.lock().unwrap();
        *state.focus_context.lock().unwrap() = Some(crate::dictation_quality::FocusContext {
            app_name: Some("Mail".into()),
            field_text: Some("private draft".into()),
            ..Default::default()
        });
        {
            let mut commit = state.commit_state.lock().unwrap();
            commit.reset(7);
            assert!(commit.commit(7, 0, 100, "already decoded words"));
        }
        assert_eq!(state.focus_app_name().as_deref(), Some("Mail"));

        // Consuming the context for one cleanup leaves nothing behind.
        assert!(state.take_focus_context().is_some());
        assert!(state.take_focus_context().is_none());

        *state.focus_context.lock().unwrap() = Some(Default::default());
        state.clear_session_text();
        assert!(state.focus_context.lock().unwrap().is_none());
        assert!(state
            .commit_state
            .lock()
            .unwrap()
            .committed_text()
            .is_empty());
        assert_eq!(state.commit_state.lock().unwrap().committed_end(), 0);
    }

    #[test]
    fn restoring_window_exits_fullscreen_then_unmaximizes_before_applying_bounds() {
        let calls = std::cell::RefCell::new(Vec::new());
        super::leave_window_modes(
            true,
            true,
            || {
                calls.borrow_mut().push("exit-fullscreen");
                Ok(())
            },
            || {
                calls.borrow_mut().push("unmaximize");
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(*calls.borrow(), ["exit-fullscreen", "unmaximize"]);
    }

    #[test]
    fn window_layout_geometry_covers_halves_corners_and_fullscreen_area() {
        let area = super::WindowBounds {
            x: -1920,
            y: 24,
            width: 1920,
            height: 1056,
        };
        assert_eq!(
            super::snap_target_bounds("left-half", area),
            Some(super::WindowBounds {
                x: -1920,
                y: 24,
                width: 960,
                height: 1056
            })
        );
        assert_eq!(
            super::snap_target_bounds("top-right", area),
            Some(super::WindowBounds {
                x: -960,
                y: 24,
                width: 960,
                height: 528
            })
        );
        assert_eq!(super::snap_target_bounds("maximize", area), Some(area));
        assert_eq!(super::snap_target_bounds("unsupported", area), None);
    }

    #[test]
    fn monitor_move_centers_window_and_clamps_size_to_destination_work_area() {
        let current = super::WindowBounds {
            x: 100,
            y: 120,
            width: 1400,
            height: 900,
        };
        let destination = super::WindowBounds {
            x: 1920,
            y: -200,
            width: 1280,
            height: 800,
        };
        assert_eq!(
            super::move_to_monitor_bounds(current, destination),
            super::WindowBounds {
                x: 1920,
                y: -200,
                width: 1280,
                height: 800
            }
        );
        let smaller = super::WindowBounds {
            x: 1920,
            y: 40,
            width: 800,
            height: 600,
        };
        assert_eq!(
            super::move_to_monitor_bounds(
                super::WindowBounds {
                    x: 20,
                    y: 30,
                    width: 700,
                    height: 500
                },
                smaller
            ),
            super::WindowBounds {
                x: 1970,
                y: 90,
                width: 700,
                height: 500
            }
        );
    }

    #[test]
    fn dragged_window_edge_detection_prioritizes_corners_and_ignores_interior() {
        let area = super::WindowBounds {
            x: -100,
            y: 50,
            width: 1200,
            height: 900,
        };
        assert_eq!(
            super::edge_snap_action(
                super::WindowBounds {
                    x: -94,
                    y: 55,
                    width: 700,
                    height: 500
                },
                area,
                16
            ),
            Some("top-left")
        );
        assert_eq!(
            super::edge_snap_action(
                super::WindowBounds {
                    x: 400,
                    y: 200,
                    width: 700,
                    height: 500
                },
                area,
                16
            ),
            Some("right-half")
        );
        assert_eq!(
            super::edge_snap_action(
                super::WindowBounds {
                    x: 200,
                    y: 200,
                    width: 700,
                    height: 500
                },
                area,
                16
            ),
            None
        );
    }

    #[test]
    fn only_the_main_window_snaps_to_screen_edges() {
        assert!(super::window_snaps_to_edges("main"));
        assert!(!super::window_snaps_to_edges("quick-controls"));
        assert!(!super::window_snaps_to_edges("ergonomics"));
        assert!(!super::window_snaps_to_edges(""));
    }

    #[test]
    fn delayed_edge_snap_applies_only_for_the_current_enabled_preview() {
        assert!(super::edge_snap_should_apply(
            true,
            4,
            4,
            Some("left-half"),
            "left-half"
        ));
        assert!(!super::edge_snap_should_apply(
            false,
            4,
            4,
            Some("left-half"),
            "left-half"
        ));
        assert!(!super::edge_snap_should_apply(
            true,
            4,
            5,
            Some("left-half"),
            "left-half"
        ));
        assert!(!super::edge_snap_should_apply(
            true,
            4,
            4,
            Some("right-half"),
            "left-half"
        ));
        assert!(!super::edge_snap_should_apply(
            true,
            4,
            4,
            None,
            "left-half"
        ));
    }

    #[cfg(target_os = "macos")]
    fn f32_wav(samples: &[f32], rate: u32) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"RIFF");
        bytes.extend_from_slice(&0u32.to_le_bytes());
        bytes.extend_from_slice(b"WAVEfmt ");
        bytes.extend_from_slice(&16u32.to_le_bytes());
        bytes.extend_from_slice(&3u16.to_le_bytes());
        bytes.extend_from_slice(&1u16.to_le_bytes());
        bytes.extend_from_slice(&rate.to_le_bytes());
        bytes.extend_from_slice(&(rate * 4).to_le_bytes());
        bytes.extend_from_slice(&4u16.to_le_bytes());
        bytes.extend_from_slice(&32u16.to_le_bytes());
        bytes.extend_from_slice(b"data");
        bytes.extend_from_slice(&((samples.len() * 4) as u32).to_le_bytes());
        for sample in samples {
            bytes.extend_from_slice(&sample.to_le_bytes());
        }
        bytes
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn imported_audio_wav_requires_bounded_finite_mono_float_samples() {
        let valid = f32_wav(&vec![0.5; 1600], 16_000);
        let parsed = super::parse_mono_f32_wav(&valid).unwrap();
        assert_eq!(parsed.len(), 1600);
        assert!(parsed.iter().all(|sample| *sample == 0.5));

        let short = f32_wav(&vec![0.5; 100], 16_000);
        assert!(super::parse_mono_f32_wav(&short).is_err());
        let wrong_rate = f32_wav(&vec![0.5; 1600], 44_100);
        assert!(super::parse_mono_f32_wav(&wrong_rate).is_err());
        let non_finite = f32_wav(&vec![f32::NAN; 1600], 16_000);
        assert!(super::parse_mono_f32_wav(&non_finite).is_err());
    }

    #[test]
    fn backend_uses_a_free_loopback_port_when_the_default_is_occupied() {
        let occupied = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let preferred = occupied.local_addr().unwrap();
        assert!(std::net::TcpStream::connect_timeout(
            &preferred,
            std::time::Duration::from_millis(50)
        )
        .is_ok());
        let selected = super::select_backend_address_from(preferred).unwrap();
        assert_ne!(selected, preferred);
        let second_listener = std::net::TcpListener::bind(selected).unwrap();
        assert_eq!(second_listener.local_addr().unwrap(), selected);
    }

    #[test]
    fn capture_result_uses_sample_duration_and_reports_no_speech_without_generic_dto_error() {
        let result = super::captured_transcript("Recognized speech".into(), 16_000).unwrap();
        assert_eq!(result.audio_duration_seconds, 1.0);
        assert_eq!(result.text, "Recognized speech");
        assert_eq!(
            super::captured_transcript("  \n".into(), 16_000).unwrap_err(),
            "No speech was recognized. Check the microphone and try speaking again."
        );
        assert_eq!(
            super::captured_transcript("speech".into(), 0).unwrap_err(),
            "Captured audio duration is outside the supported limits. Try recording again."
        );
        assert_eq!(
            super::captured_transcript("speech".into(), 4_800_001).unwrap_err(),
            "Captured audio duration is outside the supported limits. Try recording again."
        );
        assert_eq!(
            super::captured_transcript("a".repeat(262_145), 16_000).unwrap_err(),
            "The transcript exceeds the 256 KiB text limit. Record a shorter passage."
        );
    }

    #[test]
    fn quick_capture_respects_meeting_shortcut_and_intended_target_ownership() {
        assert_eq!(
            super::quick_capture_preflight(false, false, false, false),
            Ok(false)
        );
        assert_eq!(
            super::quick_capture_preflight(true, true, false, false),
            Ok(true)
        );
        assert!(super::quick_capture_preflight(true, false, false, false)
            .unwrap_err()
            .contains("current recording"));
        assert!(super::quick_capture_preflight(false, false, true, false)
            .unwrap_err()
            .contains("meeting"));
        assert!(super::quick_capture_preflight(false, false, false, true)
            .unwrap_err()
            .contains("push-to-talk"));
    }
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::mpsc;
    use std::thread;

    #[cfg(target_os = "macos")]
    #[test]
    fn closing_the_main_window_keeps_background_dictation_available() {
        use super::{
            should_keep_background_after_main_window_close, should_show_main_window_after_reopen,
        };

        assert!(should_keep_background_after_main_window_close("main"));
        assert!(!should_keep_background_after_main_window_close("settings"));
        assert!(should_show_main_window_after_reopen(false, false));
        assert!(!should_show_main_window_after_reopen(true, false));
        // Closing the mascot hides the last window; that is not a Dock reopen.
        assert!(!should_show_main_window_after_reopen(false, true));
    }

    fn mock_cleanup_server(response: Vec<u8>) -> (std::net::SocketAddr, mpsc::Receiver<Vec<u8>>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind local cleanup fixture");
        let address = listener.local_addr().expect("read fixture address");
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept local cleanup request");
            let mut request = Vec::new();
            while !request.ends_with(b"\r\n\r\n") {
                let mut byte = [0_u8];
                stream.read_exact(&mut byte).expect("read cleanup header");
                request.push(byte[0]);
                assert!(request.len() < 16384);
            }
            let headers = std::str::from_utf8(&request).expect("UTF-8 cleanup headers");
            let length = headers
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().unwrap())
                })
                .expect("request content length");
            let mut body = vec![0_u8; length];
            stream.read_exact(&mut body).expect("read cleanup body");
            request.extend(body);
            let _ = sender.send(request);
            // Match the packaged ASGI server: a client EOF before the response
            // is a disconnect, not a request-body delimiter.
            stream
                .set_read_timeout(Some(std::time::Duration::from_millis(30)))
                .unwrap();
            if matches!(stream.peek(&mut [0_u8]), Ok(0)) {
                return;
            }
            stream.write_all(&response).expect("write cleanup response");
        });
        (address, receiver)
    }

    fn cleanup_response(status: u16, body: &[u8]) -> Vec<u8> {
        format!(
            "HTTP/1.0 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            body.len()
        )
        .into_bytes()
        .into_iter()
        .chain(body.iter().copied())
        .collect()
    }

    #[test]
    fn supported_local_profiles_register_dictation_commands() {
        assert!(super::dictation_commands_enabled("development"));
        assert!(super::dictation_commands_enabled("private-beta"));
        for profile in ["", "paid", "Development"] {
            assert!(!super::dictation_commands_enabled(profile));
        }
    }

    #[test]
    fn local_cleanup_sends_only_authenticated_loopback_json_and_reads_typed_text() {
        let response = cleanup_response(200, br#"{"cleaned_text":"Hello, OfficeKit."}"#);
        let (address, request_receiver) = mock_cleanup_server(response);
        let dictionary =
            std::collections::BTreeMap::from([("offis kit".to_string(), "OfficeKit".to_string())]);
        let cleaned = cleanup_dictation_text(address, "local-test-token", "hello", &dictionary)
            .expect("cleanup result");
        assert_eq!(cleaned, "Hello, OfficeKit.");

        let request = String::from_utf8(request_receiver.recv().expect("captured request"))
            .expect("UTF-8 request");
        assert!(request.starts_with("POST /api/dictate/cleanup HTTP/1.0\r\n"));
        assert!(request.contains("Authorization: Bearer local-test-token\r\n"));
        assert!(request.contains(r#""transcript":"hello""#));
        assert!(request.contains(r#""offis kit":"OfficeKit""#));
    }

    #[test]
    fn local_cleanup_asks_for_steps_sends_the_word_list_and_reads_each_stage() {
        let response = cleanup_response(
            200,
            br#"{"cleaned_text":"Ship easydp.","steps":{"after_smart":"ship easy D P","dictionary_changes":[{"from":"easy D P","to":"easydp"},{"from":1}]}}"#,
        );
        let (address, request_receiver) = mock_cleanup_server(response);
        let outcome = cleanup_dictation_text_with(
            address,
            "local-test-token",
            "um ship easy D P",
            &std::collections::BTreeMap::new(),
            &dictation_quality::CleanupOptions::default(),
            &["easydp".to_string()],
        )
        .expect("cleanup outcome");
        assert_eq!(outcome.text, "Ship easydp.");
        assert_eq!(outcome.after_smart.as_deref(), Some("ship easy D P"));
        assert_eq!(
            outcome.dictionary_changes,
            vec![DictionaryChange {
                from: "easy D P".into(),
                to: "easydp".into()
            }]
        );
        let request = String::from_utf8(request_receiver.recv().expect("captured request"))
            .expect("UTF-8 request");
        assert!(request.contains(r#""include_steps":true"#));
        assert!(request.contains(r#""words":["easydp"]"#));
    }

    #[test]
    fn local_cleanup_without_steps_in_the_response_still_returns_the_text() {
        let (address, _) = mock_cleanup_server(cleanup_response(200, br#"{"cleaned_text":"Hi."}"#));
        let outcome = cleanup_dictation_text_with(
            address,
            "token",
            "hi",
            &std::collections::BTreeMap::new(),
            &dictation_quality::CleanupOptions::default(),
            &[],
        )
        .expect("cleanup outcome");
        assert_eq!(outcome.text, "Hi.");
        assert!(outcome.after_smart.is_none() && outcome.dictionary_changes.is_empty());
    }

    #[test]
    fn failed_attempts_are_classified_from_the_error_message() {
        for (message, kind) in [
            ("No speech was recognized. Try again.", "no-speech"),
            ("Audio capture failed; please try again", "capture-error"),
            ("No audio was captured; please try again", "capture-error"),
            ("Dictation exceeded the five-minute limit", "capture-error"),
            ("Local transcription failed", "model-error"),
            ("The local speech model is not ready", "model-error"),
            (
                "Local transcription is busy; please try again",
                "model-error",
            ),
        ] {
            assert_eq!(super::attempt_failure_kind(message), kind, "{message}");
        }
    }

    #[test]
    fn no_speech_errors_carry_capture_numbers_and_other_errors_do_not() {
        let capture = dictation_quality::CaptureStats {
            recorded_seconds: 6.0,
            speech_seconds: 0.0,
            had_speech: false,
            level_db: Some(-58.0),
        };
        let message = with_capture_numbers("No speech was recognized. Try again.".into(), &capture);
        assert_eq!(
            message,
            "No speech was recognized. Try again. Recorded 6.0 s, speech found 0.0 s, loudest level -58 dB."
        );
        let silent = dictation_quality::CaptureStats {
            level_db: None,
            ..capture.clone()
        };
        assert!(
            with_capture_numbers("No speech was recognized.".into(), &silent)
                .ends_with("loudest level silent.")
        );
        assert_eq!(
            with_capture_numbers("Audio capture failed".into(), &capture),
            "Audio capture failed"
        );
    }

    #[test]
    fn local_cleanup_rejects_bad_status_incomplete_and_oversized_responses() {
        let (address, _) = mock_cleanup_server(cleanup_response(401, b"{}"));
        assert_eq!(
            cleanup_dictation_text(
                address,
                "token",
                "hello",
                &std::collections::BTreeMap::new()
            ),
            Err("Local transcript cleanup failed".into())
        );

        let (address, _) =
            mock_cleanup_server(b"HTTP/1.0 200 OK\r\nContent-Length: 9\r\n\r\n{}".to_vec());
        assert_eq!(
            cleanup_dictation_text(
                address,
                "token",
                "hello",
                &std::collections::BTreeMap::new()
            ),
            Err("Local transcript cleanup returned an incomplete response".into())
        );

        let (address, _) =
            mock_cleanup_server(vec![b'x'; super::MAX_DICTATION_CLEANUP_RESPONSE_BYTES + 1]);
        assert_eq!(
            cleanup_dictation_text(
                address,
                "token",
                "hello",
                &std::collections::BTreeMap::new()
            ),
            Err("Local transcript cleanup returned an oversized response".into())
        );
    }

    #[test]
    fn local_cleanup_rejects_remote_addresses_and_header_injection() {
        let remote = "192.0.2.1:8000"
            .parse()
            .expect("parse documentation address");
        assert_eq!(
            cleanup_dictation_text(remote, "token", "hello", &std::collections::BTreeMap::new()),
            Err("Dictation cleanup input is invalid".into())
        );
        let local = "127.0.0.1:8000".parse().expect("parse loopback address");
        assert_eq!(
            cleanup_dictation_text(
                local,
                "token\r\nX-Test: forged",
                "hello",
                &std::collections::BTreeMap::new()
            ),
            Err("Dictation cleanup input is invalid".into())
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn native_microphone_status_query_returns_a_known_os_state() {
        let code = unsafe { super::officekit_dictation_microphone_permission_status() };
        assert!((0..=3).contains(&code));
    }

    #[test]
    fn microphone_permission_messages_match_each_native_state() {
        for (permission, expected) in [
            (
                MicrophonePermission::Granted,
                "Microphone access is enabled.",
            ),
            (
                MicrophonePermission::Undetermined,
                "Allow microphone access to dictate.",
            ),
            (
                MicrophonePermission::Denied,
                "Allow microphone access in System Settings.",
            ),
            (
                MicrophonePermission::Unavailable,
                "Microphone access is unavailable on this Mac.",
            ),
        ] {
            let status = dictation_microphone_status_for(permission, true);
            assert_eq!(status.permission, permission);
            assert_eq!(status.message, expected);
        }
        let missing = dictation_microphone_status_for(MicrophonePermission::Granted, false);
        assert_eq!(missing.permission, MicrophonePermission::Granted);
        assert!(!missing.input_available);
        assert!(missing.message.contains("No microphone detected"));
    }

    #[test]
    fn accessibility_permission_messages_match_each_native_state() {
        for (permission, expected) in [
            (
                crate::dictation::AccessibilityPermission::Granted,
                "Accessibility access is enabled.",
            ),
            (
                crate::dictation::AccessibilityPermission::Denied,
                "Allow Accessibility access to use the dictation shortcut.",
            ),
            (
                crate::dictation::AccessibilityPermission::Unavailable,
                "Accessibility access is unavailable on this Mac.",
            ),
        ] {
            let status = dictation_accessibility_status_for(permission);
            assert_eq!(status.permission, permission);
            assert_eq!(status.message, expected);
        }
    }

    #[test]
    fn dictation_permission_settings_links_are_allowlisted() {
        assert_eq!(
            dictation_permission_settings_url("microphone"),
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
        );
        assert_eq!(
            dictation_permission_settings_url("accessibility"),
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        );
        assert_eq!(dictation_permission_settings_url("arbitrary"), None);
    }

    #[test]
    fn sidecar_startup_failure_events_are_distinguished_from_output() {
        assert!(startup_event_is_failure(&CommandEvent::Terminated(
            TerminatedPayload {
                code: Some(1),
                signal: None,
            },
        )));
        assert!(startup_event_is_failure(&CommandEvent::Error(
            "sidecar event error".to_string(),
        )));
        assert!(!startup_event_is_failure(&CommandEvent::Stdout(vec![b'o'])));
        assert!(!startup_event_is_failure(&CommandEvent::Stderr(vec![b'w'])));
    }

    #[test]
    fn readiness_request_carries_the_ephemeral_sidecar_token() {
        let request = health_request("127.0.0.1:8000", "secret-token");

        assert!(request.contains("Authorization: Bearer secret-token\r\n"));
        assert!(request.starts_with("GET /api/health HTTP/1.0\r\n"));
    }

    #[test]
    fn readiness_accepts_only_the_officekit_health_payload() {
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{{\"status\":\"ok\",\"service\":\"officekit-api\",\"version\":\"{}\"}}",
            env!("CARGO_PKG_VERSION")
        );

        assert!(health_response_is_accepted(response.as_bytes()));
    }

    #[test]
    fn readiness_rejects_non_success_http_statuses() {
        let response = b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\",\"service\":\"officekit-api\"}";

        assert!(!health_response_is_accepted(response));
    }

    #[test]
    fn readiness_rejects_an_unrelated_service() {
        let response = b"HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\",\"service\":\"other\"}";

        assert!(!health_response_is_accepted(response));
    }

    #[test]
    fn readiness_rejects_missing_or_mismatched_backend_versions() {
        let missing_version =
            b"HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\",\"service\":\"officekit-api\"}";
        let wrong_version = b"HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\",\"service\":\"officekit-api\",\"version\":\"0.0.0\"}";

        assert!(!health_response_is_accepted(missing_version));
        assert!(!health_response_is_accepted(wrong_version));
    }

    #[test]
    fn readiness_rejects_oversized_health_responses_even_if_json_is_valid() {
        let mut response = format!(
            "HTTP/1.1 200 OK\r\n\r\n{{\"status\":\"ok\",\"service\":\"officekit-api\",\"version\":\"{}\"}}",
            env!("CARGO_PKG_VERSION")
        )
        .into_bytes();
        response.extend(std::iter::repeat(b' ').take(16 * 1024));

        assert!(!health_response_is_accepted(&response));
    }

    #[test]
    fn readiness_rejects_malformed_or_incomplete_payloads() {
        assert!(!health_response_is_accepted(b"not http"));
        assert!(!health_response_is_accepted(
            b"HTTP/1.1 200 OK\r\n\r\nnot json"
        ));
        assert!(!health_response_is_accepted(
            b"HTTP/1.1 200 OK\r\n\r\n{\"service\":\"officekit-api\"}"
        ));
    }
}
