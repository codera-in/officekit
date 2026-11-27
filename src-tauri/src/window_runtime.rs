//! Runs window-manager actions on a worker thread: shortcut layouts, drag-to-edge snapping and
//! the native Accessibility calls behind them.

use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::global_desktop::GlobalDesktopSettings;
use crate::window_manager::{
    self, apply, apply_to_window, DragTracker, FocusedWindow, History, Outcome, Preview, Rect,
    WindowBackend, WindowError, WindowOptions,
};

const FOCUSED_BUFFER_BYTES: usize = 16 * 1024;
const DROP_SETTLE: Duration = Duration::from_millis(80);
const PRESS_SETTLE: Duration = Duration::from_millis(40);

// Unit tests use the stub: the Swift side marshals onto the main thread, which a test thread
// would deadlock on.
#[cfg(all(target_os = "macos", not(test)))]
mod native {
    unsafe extern "C" {
        fn officekit_wm_focused(output: *mut u8, capacity: u64) -> i64;
        fn officekit_wm_set_frame(pid: i32, x: f64, y: f64, width: f64, height: f64) -> i32;
        fn officekit_wm_drag_set_callback(callback: extern "C" fn(i32, f64, f64));
        fn officekit_wm_drag_configure(enabled: i32) -> i32;
        fn officekit_wm_preview(visible: i32, x: f64, y: f64, width: f64, height: f64);
        fn officekit_wm_diag(bytes: *const u8, length: u64);
    }

    pub fn diag(message: &str) {
        unsafe { officekit_wm_diag(message.as_ptr(), message.len() as u64) };
    }

    pub fn focused(buffer: &mut [u8]) -> i64 {
        unsafe { officekit_wm_focused(buffer.as_mut_ptr(), buffer.len() as u64) }
    }
    pub fn set_frame(pid: i32, x: i64, y: i64, width: i64, height: i64) -> i32 {
        unsafe { officekit_wm_set_frame(pid, x as f64, y as f64, width as f64, height as f64) }
    }
    pub fn set_drag_callback(callback: extern "C" fn(i32, f64, f64)) {
        unsafe { officekit_wm_drag_set_callback(callback) }
    }
    pub fn drag_configure(enabled: bool) {
        unsafe { officekit_wm_drag_configure(i32::from(enabled)) };
    }
    pub fn preview(rect: Option<(i64, i64, i64, i64)>) {
        let (visible, x, y, w, h) = match rect {
            Some((x, y, w, h)) => (1, x, y, w, h),
            None => (0, 0, 0, 0, 0),
        };
        unsafe { officekit_wm_preview(visible, x as f64, y as f64, w as f64, h as f64) };
    }
}

#[cfg(not(all(target_os = "macos", not(test))))]
mod native {
    pub fn focused(_buffer: &mut [u8]) -> i64 {
        -2
    }
    pub fn set_frame(_pid: i32, _x: i64, _y: i64, _width: i64, _height: i64) -> i32 {
        3
    }
    pub fn diag(_message: &str) {}
    pub fn set_drag_callback(_callback: extern "C" fn(i32, f64, f64)) {}
    pub fn drag_configure(_enabled: bool) {}
    pub fn preview(_rect: Option<(i64, i64, i64, i64)>) {}
}

fn rect_from(value: &Value) -> Option<Rect> {
    Some(Rect::new(
        value["x"].as_i64()?,
        value["y"].as_i64()?,
        value["w"].as_i64()?,
        value["h"].as_i64()?,
    ))
}

fn rects_from(value: &Value) -> Vec<Rect> {
    value
        .as_array()
        .map(|items| items.iter().filter_map(rect_from).collect())
        .unwrap_or_default()
}

/// Parses the native focused-window JSON.
pub fn parse_focused(bytes: &[u8]) -> Option<FocusedWindow> {
    let value: Value = serde_json::from_slice(bytes).ok()?;
    Some(FocusedWindow {
        pid: i32::try_from(value["pid"].as_i64()?).ok()?,
        bundle_id: value["bundleId"]
            .as_str()
            .unwrap_or("")
            .chars()
            .take(200)
            .collect(),
        frame: rect_from(&value)?,
        screens: rects_from(&value["screens"]),
        frames: rects_from(&value["frames"]),
        resizable: value["resizable"].as_bool().unwrap_or(false),
        fullscreen: value["fullscreen"].as_bool().unwrap_or(false),
    })
}

struct NativeBackend;

impl WindowBackend for NativeBackend {
    fn focused(&mut self) -> Result<FocusedWindow, WindowError> {
        let mut buffer = vec![0u8; FOCUSED_BUFFER_BYTES];
        match native::focused(&mut buffer) {
            -1 => Err(WindowError::NoAccessibility),
            length if length > 0 => {
                buffer.truncate(length as usize);
                parse_focused(&buffer).ok_or(WindowError::NoWindow)
            }
            _ => Err(WindowError::NoWindow),
        }
    }

    fn set_frame(&mut self, pid: i32, frame: Rect) -> Result<(), WindowError> {
        match native::set_frame(pid, frame.x, frame.y, frame.w, frame.h) {
            0 => Ok(()),
            1 => Err(WindowError::NoAccessibility),
            2 => Err(WindowError::NoWindow),
            _ => Err(WindowError::Failed),
        }
    }
}

#[derive(Clone, Default)]
struct Config {
    enabled: bool,
    edge_drag: bool,
    options: WindowOptions,
}

enum Event {
    Layout(String),
    Mouse(i32, i64, i64),
}

static EVENTS: OnceLock<Mutex<Sender<Event>>> = OnceLock::new();
static CONFIG: Mutex<Option<Config>> = Mutex::new(None);

fn config() -> Config {
    CONFIG
        .lock()
        .ok()
        .and_then(|config| config.clone())
        .unwrap_or_default()
}

fn send(event: Event) {
    if let Some(sender) = EVENTS.get().and_then(|sender| sender.lock().ok()) {
        let _ = sender.send(event);
    }
}

extern "C" fn on_mouse(kind: i32, x: f64, y: f64) {
    send(Event::Mouse(kind, x.round() as i64, y.round() as i64));
}

/// Applies the window settings: the layout options and whether dragging to an edge snaps.
pub fn configure(settings: &GlobalDesktopSettings) {
    let next = Config {
        enabled: settings.windows_enabled,
        edge_drag: settings.windows_enabled && settings.edge_drag,
        options: settings.window_options(),
    };
    let drag = next.edge_drag;
    if let Ok(mut config) = CONFIG.lock() {
        *config = Some(next);
    }
    native::drag_configure(drag);
    if !drag {
        native::preview(None);
    }
}

/// Runs the layout named by a fired window shortcut (`window.left-half`).
pub fn handle_action(action: &str) {
    if let Some(layout) = window_manager::layout_of(action) {
        send(Event::Layout(layout.to_string()));
    }
}

pub fn start(app: &AppHandle) {
    let (sender, receiver) = mpsc::channel();
    if EVENTS.set(Mutex::new(sender)).is_err() {
        return;
    }
    native::set_drag_callback(on_mouse);
    let app = app.clone();
    let _ = std::thread::Builder::new()
        .name("officekit-window-manager".into())
        .spawn(move || Worker::new(app).run(receiver));
}

struct Worker {
    app: AppHandle,
    history: History,
    tracker: DragTracker,
    backend: NativeBackend,
}

impl Worker {
    fn new(app: AppHandle) -> Self {
        Self {
            app,
            history: History::default(),
            tracker: DragTracker::default(),
            backend: NativeBackend,
        }
    }

    fn run(mut self, receiver: Receiver<Event>) {
        let mut pending = None;
        loop {
            let event = match pending.take() {
                Some(event) => event,
                None => match receiver.recv() {
                    Ok(event) => event,
                    Err(_) => return,
                },
            };
            match event {
                Event::Layout(layout) => self.layout(&layout),
                Event::Mouse(1, mut x, mut y) => {
                    // Drags arrive far faster than Accessibility can answer; act on the latest.
                    while let Ok(next) = receiver.try_recv() {
                        match next {
                            Event::Mouse(1, nx, ny) => (x, y) = (nx, ny),
                            other => {
                                pending = Some(other);
                                break;
                            }
                        }
                    }
                    self.mouse_drag((x, y));
                }
                Event::Mouse(0, x, y) => self.mouse_down((x, y)),
                Event::Mouse(_, _, _) => self.mouse_up(),
            }
        }
    }

    fn notice(&self, code: &str, message: &str) {
        let _ = self.app.emit(
            "global-desktop-notice",
            json!({"code": code, "message": message}),
        );
    }

    fn report(&self, error: WindowError) {
        match error {
            WindowError::NoAccessibility => self.notice(
                "accessibility",
                "Allow Accessibility access so OfficeKit can move other apps' windows.",
            ),
            WindowError::NoWindow => {}
            WindowError::Failed => self.notice("window-failed", "That window could not be moved."),
        }
    }

    fn layout(&mut self, layout: &str) {
        let config = config();
        if !config.enabled {
            return;
        }
        match apply(
            &mut self.history,
            &mut self.backend,
            layout,
            &config.options,
        ) {
            Ok(Outcome::Refused(message)) => self.notice("window-refused", message),
            Ok(_) => {}
            Err(error) => self.report(error),
        }
    }

    fn mouse_down(&mut self, cursor: (i64, i64)) {
        if !config().edge_drag {
            return;
        }
        // The click may be raising the window it hit; give the app a moment to finish.
        std::thread::sleep(PRESS_SETTLE);
        let window = self.backend.focused().ok();
        native::diag(&format!("press window={}", window.is_some()));
        self.tracker.on_down(cursor, window);
    }

    fn mouse_drag(&mut self, cursor: (i64, i64)) {
        let config = config();
        if !config.edge_drag {
            return;
        }
        let backend = &mut self.backend;
        let preview = self
            .tracker
            .on_move(cursor, &mut || backend.focused().ok(), &config.options);
        match preview {
            Preview::Unchanged => {}
            Preview::Show(rect) => {
                native::diag("preview shown");
                native::preview(Some((rect.x, rect.y, rect.w, rect.h)));
            }
            Preview::Hide => {
                native::diag("preview hidden");
                native::preview(None);
            }
        }
    }

    fn mouse_up(&mut self) {
        native::preview(None);
        let Some(drop) = self.tracker.on_up() else {
            native::diag("release without snap");
            return;
        };
        native::diag(&format!("release snap={}", drop.layout));
        let config = config();
        if !config.edge_drag {
            return;
        }
        std::thread::sleep(DROP_SETTLE);
        let Ok(window) = self.backend.focused() else {
            return;
        };
        if window.pid != drop.window.pid {
            return;
        }
        match apply_to_window(
            &mut self.history,
            &mut self.backend,
            &window,
            drop.layout,
            &config.options,
            Some(drop.area),
        ) {
            Ok(Outcome::Refused(message)) => self.notice("window-refused", message),
            Ok(_) => {}
            Err(error) => self.report(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_the_native_focused_window_payload() {
        let bytes = br#"{"pid":42,"bundleId":"com.apple.Safari","x":10,"y":20,"w":800,"h":600,
            "resizable":true,"fullscreen":false,
            "screens":[{"x":0,"y":25,"w":1440,"h":875}],
            "frames":[{"x":0,"y":0,"w":1440,"h":900}]}"#;
        let window = parse_focused(bytes).unwrap();
        assert_eq!(window.pid, 42);
        assert_eq!(window.bundle_id, "com.apple.Safari");
        assert_eq!(window.frame, Rect::new(10, 20, 800, 600));
        assert_eq!(window.screens, vec![Rect::new(0, 25, 1440, 875)]);
        assert_eq!(window.frames, vec![Rect::new(0, 0, 1440, 900)]);
        assert!(window.resizable && !window.fullscreen);
    }

    #[test]
    fn malformed_payloads_are_rejected_and_optional_fields_default() {
        assert!(parse_focused(b"not json").is_none());
        assert!(parse_focused(br#"{"pid":1}"#).is_none());
        assert!(parse_focused(br#"{"pid":99999999999,"x":0,"y":0,"w":1,"h":1}"#).is_none());
        let minimal =
            parse_focused(br#"{"pid":1,"x":0,"y":0,"w":1,"h":1,"screens":[{"x":1}]}"#).unwrap();
        assert_eq!(minimal.bundle_id, "");
        assert!(minimal.screens.is_empty() && !minimal.resizable);
        let long = format!(
            r#"{{"pid":1,"bundleId":"{}","x":0,"y":0,"w":1,"h":1}}"#,
            "a".repeat(500)
        );
        assert_eq!(parse_focused(long.as_bytes()).unwrap().bundle_id.len(), 200);
    }

    #[test]
    fn configure_enables_dragging_only_when_the_window_manager_is_on() {
        let mut settings = GlobalDesktopSettings::default();
        settings.edge_drag = true;
        configure(&settings);
        assert!(
            !config().edge_drag,
            "edge drag needs the window manager enabled"
        );
        settings.windows_enabled = true;
        settings.window_gap = 8;
        settings.window_skip_apps = vec!["com.example.Skip".into()];
        configure(&settings);
        let active = config();
        assert!(active.enabled && active.edge_drag);
        assert_eq!(active.options.gap, 8);
        assert_eq!(
            active.options.skip_apps,
            vec!["com.example.Skip".to_string()]
        );
        configure(&GlobalDesktopSettings::default());
        assert!(!config().enabled);
    }
}
