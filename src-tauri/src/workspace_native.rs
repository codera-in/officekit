//! Native pickers and OS file drops issue filesystem grants. Paths and credentials
//! stay native; the webview receives opaque selections. Finder actions resolve IDs.
use base64::Engine;
#[cfg(target_os = "macos")]
use objc2_app_kit::NSWorkspace;
#[cfg(target_os = "macos")]
use objc2_foundation::NSString;
use serde_json::{json, Value};
use std::io::Write;
use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};

pub struct MediaClipboardHotkeyEnabled(std::sync::Mutex<bool>);

#[derive(Default)]
pub struct FileIntakeQueue(std::sync::Mutex<std::collections::VecDeque<Value>>);

impl FileIntakeQueue {
    pub fn push_with_source(&self, mut selection: Value, source: &str) -> Result<(), String> {
        if !matches!(source, "drop" | "open_with") {
            return Err("The file intake source is invalid".into());
        }
        selection["intakeSource"] = Value::String(source.into());
        self.push(selection)
    }

    pub fn push(&self, selection: Value) -> Result<(), String> {
        let mut queue = self
            .0
            .lock()
            .map_err(|_| "The file queue is unavailable".to_string())?;
        if queue.len() >= 8 {
            return Err("OfficeKit already has eight file batches waiting".into());
        }
        queue.push_back(selection);
        Ok(())
    }

    pub fn pending(&self) -> Result<Vec<Value>, String> {
        self.0
            .lock()
            .map(|queue| queue.iter().cloned().collect())
            .map_err(|_| "The file queue is unavailable".into())
    }

    pub fn acknowledge(&self, selection_id: &str) -> Result<(), String> {
        let mut queue = self
            .0
            .lock()
            .map_err(|_| "The file queue is unavailable".to_string())?;
        if let Some(index) = queue
            .iter()
            .position(|item| item.get("id").and_then(Value::as_str) == Some(selection_id))
        {
            queue.remove(index);
        }
        Ok(())
    }
}

impl Default for MediaClipboardHotkeyEnabled {
    fn default() -> Self {
        Self(std::sync::Mutex::new(false))
    }
}

pub fn media_clipboard_shortcut() -> Shortcut {
    "Control+Shift+C"
        .parse()
        .expect("fixed media clipboard shortcut is valid")
}

const MEDIA_FINDER_WORKFLOW: &str = "OfficeKit Optimize Image.workflow";
const MEDIA_FINDER_MARKER: &str = "app.officekit.media.optimize-image";
const MEDIA_FINDER_CONTENTS: [&str; 2] = ["Info.plist", "document.wflow"];

fn media_finder_contents_match(names: &[std::ffi::OsString]) -> bool {
    names.len() == MEDIA_FINDER_CONTENTS.len()
        && MEDIA_FINDER_CONTENTS.iter().all(|name| {
            names
                .iter()
                .any(|entry| entry == std::ffi::OsStr::new(name))
        })
}

/// A Finder Quick Action OfficeKit may install into `~/Library/Services`.
struct FinderWorkflow {
    name: &'static str,
    marker: &'static str,
}

const MEDIA_FINDER: FinderWorkflow = FinderWorkflow {
    name: MEDIA_FINDER_WORKFLOW,
    marker: MEDIA_FINDER_MARKER,
};

const OPEN_IN_FINDER_WORKFLOW: &str = "Open in OfficeKit.workflow";
const OPEN_IN_FINDER: FinderWorkflow = FinderWorkflow {
    name: OPEN_IN_FINDER_WORKFLOW,
    marker: "app.officekit.finder.open-in-officekit",
};

fn media_finder_workflow_path(home: &std::path::Path) -> std::path::PathBuf {
    finder_workflow_path(home, &MEDIA_FINDER)
}

fn finder_workflow_path(home: &std::path::Path, workflow: &FinderWorkflow) -> std::path::PathBuf {
    home.join("Library").join("Services").join(workflow.name)
}

fn media_finder_workflow_is_owned(path: &std::path::Path) -> bool {
    finder_workflow_is_owned(path, &MEDIA_FINDER)
}

fn finder_workflow_is_owned(path: &std::path::Path, workflow: &FinderWorkflow) -> bool {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return false;
    };
    if !metadata.file_type().is_dir() {
        return false;
    }
    let contents = path.join("Contents");
    let Ok(contents_metadata) = std::fs::symlink_metadata(&contents) else {
        return false;
    };
    if !contents_metadata.file_type().is_dir() {
        return false;
    }
    let info = contents.join("Info.plist");
    let Ok(info_metadata) = std::fs::symlink_metadata(&info) else {
        return false;
    };
    if !info_metadata.file_type().is_file() {
        return false;
    }
    std::fs::read_to_string(info).is_ok_and(|contents| contents.contains(workflow.marker))
}

fn media_finder_workflow_matches(path: &std::path::Path, resource: &std::path::Path) -> bool {
    finder_workflow_matches(path, resource, &MEDIA_FINDER)
}

fn finder_workflow_matches(
    path: &std::path::Path,
    resource: &std::path::Path,
    workflow: &FinderWorkflow,
) -> bool {
    if !finder_workflow_is_owned(path, workflow) {
        return false;
    }
    let Ok(root_entries) = std::fs::read_dir(path) else {
        return false;
    };
    let Ok(root_entries) = root_entries.collect::<std::io::Result<Vec<_>>>() else {
        return false;
    };
    if root_entries.len() != 1 {
        return false;
    }
    let Ok(entries) = std::fs::read_dir(path.join("Contents")) else {
        return false;
    };
    let Ok(entries) = entries.collect::<std::io::Result<Vec<_>>>() else {
        return false;
    };
    let names: Vec<_> = entries.into_iter().map(|entry| entry.file_name()).collect();
    if !media_finder_contents_match(&names) {
        return false;
    }
    MEDIA_FINDER_CONTENTS.iter().all(|name| {
        let installed = path.join("Contents").join(name);
        let bundled = resource.join("Contents").join(name);
        let installed_regular = std::fs::symlink_metadata(&installed)
            .is_ok_and(|metadata| metadata.file_type().is_file());
        let bundled_regular = std::fs::symlink_metadata(&bundled)
            .is_ok_and(|metadata| metadata.file_type().is_file());
        installed_regular
            && bundled_regular
            && std::fs::read(installed).ok() == std::fs::read(bundled).ok()
    })
}

fn media_finder_action_install_at(
    home: &std::path::Path,
    resource: &std::path::Path,
) -> Result<String, String> {
    finder_action_install_at(home, resource, &MEDIA_FINDER)
}

fn finder_action_install_at(
    home: &std::path::Path,
    resource: &std::path::Path,
    workflow: &FinderWorkflow,
) -> Result<String, String> {
    let target = finder_workflow_path(home, workflow);
    if target.exists() {
        return if finder_workflow_matches(&target, resource, workflow) {
            Ok("installed".to_string())
        } else {
            Err("A different Finder Quick Action already uses the OfficeKit name".to_string())
        };
    }
    if !finder_workflow_is_owned(resource, workflow) {
        return Err("The bundled Finder Quick Action failed its ownership check".to_string());
    }
    let contents = target.join("Contents");
    std::fs::create_dir_all(
        target
            .parent()
            .ok_or_else(|| "Finder Quick Action location is invalid".to_string())?,
    )
    .map_err(|_| "The Finder Quick Action folder could not be created".to_string())?;
    std::fs::create_dir(&target)
        .map_err(|_| "A Finder Quick Action already uses the OfficeKit name".to_string())?;
    if std::fs::create_dir(&contents).is_err() {
        let _ = std::fs::remove_dir(&target);
        return Err("The Finder Quick Action folder could not be prepared".to_string());
    }
    let copy_result = (|| {
        for name in ["Info.plist", "document.wflow"] {
            let source = resource.join("Contents").join(name);
            let metadata = std::fs::symlink_metadata(&source)
                .map_err(|_| "A bundled Finder Quick Action file is unavailable".to_string())?;
            if !metadata.file_type().is_file() {
                return Err("The bundled Finder Quick Action contains an unsafe file".to_string());
            }
            std::fs::copy(source, contents.join(name))
                .map_err(|_| "The Finder Quick Action could not be installed".to_string())?;
        }
        Ok::<(), String>(())
    })();
    if let Err(error) = copy_result {
        let _ = std::fs::remove_file(contents.join("Info.plist"));
        let _ = std::fs::remove_file(contents.join("document.wflow"));
        let _ = std::fs::remove_dir(&contents);
        let _ = std::fs::remove_dir(&target);
        return Err(error);
    }
    Ok("installed".to_string())
}

fn media_finder_action_remove_at(
    home: &std::path::Path,
    resource: &std::path::Path,
) -> Result<String, String> {
    finder_action_remove_at(home, resource, &MEDIA_FINDER)
}

fn finder_action_remove_at(
    home: &std::path::Path,
    resource: &std::path::Path,
    workflow: &FinderWorkflow,
) -> Result<String, String> {
    let target = finder_workflow_path(home, workflow);
    if !target.exists() {
        return Ok("not-installed".to_string());
    }
    if !finder_workflow_matches(&target, resource, workflow) {
        return Err("OfficeKit will not remove an unrecognized Finder Quick Action".to_string());
    }
    std::fs::remove_dir_all(target)
        .map_err(|_| "The Finder Quick Action could not be removed".to_string())?;
    Ok("not-installed".to_string())
}

#[tauri::command]
pub fn media_finder_action_status(app: tauri::AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        let home = app
            .path()
            .home_dir()
            .map_err(|_| "Finder Quick Action location is unavailable".to_string())?;
        let path = media_finder_workflow_path(&home);
        if !path.exists() {
            return Ok("not-installed".to_string());
        }
        let resource = app
            .path()
            .resolve(
                format!("resources/{MEDIA_FINDER_WORKFLOW}"),
                tauri::path::BaseDirectory::Resource,
            )
            .map_err(|_| "The bundled Finder Quick Action is unavailable".to_string())?;
        return if media_finder_workflow_matches(&path, &resource) {
            Ok("installed".to_string())
        } else {
            Err("A different Finder Quick Action already uses the OfficeKit name".to_string())
        };
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Finder Quick Actions are supported on macOS in this build".to_string())
    }
}

#[tauri::command]
pub fn media_finder_action_install(app: tauri::AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        use tauri::path::BaseDirectory;
        let home = app
            .path()
            .home_dir()
            .map_err(|_| "Finder Quick Action location is unavailable".to_string())?;
        let resource = app
            .path()
            .resolve(
                format!("resources/{MEDIA_FINDER_WORKFLOW}"),
                BaseDirectory::Resource,
            )
            .map_err(|_| "The bundled Finder Quick Action is unavailable".to_string())?;
        return media_finder_action_install_at(&home, &resource);
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Finder Quick Actions are supported on macOS in this build".to_string())
    }
}

#[tauri::command]
pub fn media_finder_action_remove(app: tauri::AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        use tauri::path::BaseDirectory;
        let home = app
            .path()
            .home_dir()
            .map_err(|_| "Finder Quick Action location is unavailable".to_string())?;
        let resource = app
            .path()
            .resolve(
                format!("resources/{MEDIA_FINDER_WORKFLOW}"),
                BaseDirectory::Resource,
            )
            .map_err(|_| "The bundled Finder Quick Action is unavailable".to_string())?;
        return media_finder_action_remove_at(&home, &resource);
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Finder Quick Actions are supported on macOS in this build".to_string())
    }
}

/// Whether the bundled "Open in OfficeKit" Finder Quick Action is installed for this user.
pub fn open_in_finder_action_installed(app: &tauri::AppHandle) -> bool {
    #[cfg(target_os = "macos")]
    {
        let Ok(home) = app.path().home_dir() else {
            return false;
        };
        let Ok(resource) = app.path().resolve(
            format!("resources/{OPEN_IN_FINDER_WORKFLOW}"),
            tauri::path::BaseDirectory::Resource,
        ) else {
            return false;
        };
        return finder_workflow_matches(
            &finder_workflow_path(&home, &OPEN_IN_FINDER),
            &resource,
            &OPEN_IN_FINDER,
        );
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        false
    }
}

/// Installs or removes the "Open in OfficeKit" Finder Quick Action.
pub fn open_in_finder_action_set(app: &tauri::AppHandle, enabled: bool) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let home = app
            .path()
            .home_dir()
            .map_err(|_| "Finder Quick Action location is unavailable".to_string())?;
        let resource = app
            .path()
            .resolve(
                format!("resources/{OPEN_IN_FINDER_WORKFLOW}"),
                tauri::path::BaseDirectory::Resource,
            )
            .map_err(|_| "The bundled Finder Quick Action is unavailable".to_string())?;
        if enabled {
            finder_action_install_at(&home, &resource, &OPEN_IN_FINDER)?;
        } else {
            finder_action_remove_at(&home, &resource, &OPEN_IN_FINDER)?;
        }
        return Ok(());
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, enabled);
        Err("Finder Quick Actions are supported on macOS in this build".to_string())
    }
}

#[tauri::command]
pub fn finder_open_in_status(app: tauri::AppHandle) -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    return Ok(open_in_finder_action_installed(&app));
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Finder Quick Actions are supported on macOS in this build".to_string())
    }
}

#[tauri::command]
pub fn finder_open_in_set(app: tauri::AppHandle, enabled: bool) -> Result<bool, String> {
    open_in_finder_action_set(&app, enabled)?;
    Ok(enabled)
}

#[tauri::command]
pub fn media_clipboard_hotkey_set_enabled(
    app: tauri::AppHandle,
    enabled: bool,
    state: State<'_, MediaClipboardHotkeyEnabled>,
) -> Result<bool, String> {
    let mut current = state
        .0
        .lock()
        .map_err(|_| "The media shortcut state is unavailable".to_string())?;
    if *current == enabled {
        return Ok(*current);
    }
    let shortcut = media_clipboard_shortcut();
    if enabled {
        app.global_shortcut().register(shortcut).map_err(|_| {
            "Control+Shift+C is unavailable or already used by another app".to_string()
        })?;
    } else {
        app.global_shortcut()
            .unregister(shortcut)
            .map_err(|_| "The Media Toolkit shortcut could not be disabled".to_string())?;
    }
    *current = enabled;
    Ok(enabled)
}

#[tauri::command]
pub fn media_clipboard_revision() -> Result<i64, String> {
    #[cfg(target_os = "macos")]
    {
        use objc2_app_kit::NSPasteboard;
        let value = NSPasteboard::generalPasteboard().changeCount();
        return Ok(value as i64);
    }
    #[cfg(not(target_os = "macos"))]
    Err("Clipboard automation is supported on macOS in this build.".to_string())
}

pub struct NativeGrantToken(pub String);
pub struct MediaDropEnabled {
    enabled: std::sync::atomic::AtomicBool,
    bounds: std::sync::Mutex<Option<[f64; 4]>>,
    targets: std::sync::Mutex<Vec<MediaDropTarget>>,
}

#[derive(Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MediaDropTarget {
    id: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl Default for MediaDropEnabled {
    fn default() -> Self {
        Self {
            enabled: std::sync::atomic::AtomicBool::new(false),
            bounds: std::sync::Mutex::new(None),
            targets: std::sync::Mutex::new(Vec::new()),
        }
    }
}

impl MediaDropEnabled {
    fn set(&self, enabled: bool, bounds: Option<[f64; 4]>, targets: Vec<MediaDropTarget>) {
        if !enabled {
            self.enabled
                .store(false, std::sync::atomic::Ordering::Release);
        }
        if let Ok(mut current) = self.bounds.lock() {
            *current = if enabled { bounds } else { None };
        }
        if let Ok(mut current) = self.targets.lock() {
            *current = if enabled { targets } else { Vec::new() };
        }
        if enabled {
            self.enabled
                .store(true, std::sync::atomic::Ordering::Release);
        }
    }

    pub fn target_at(&self, x: f64, y: f64) -> Option<String> {
        if !self.enabled.load(std::sync::atomic::Ordering::Acquire) {
            return None;
        }
        if let Ok(targets) = self.targets.lock() {
            if let Some(target) = targets.iter().find(|target| {
                x >= target.x
                    && y >= target.y
                    && x <= target.x + target.width
                    && y <= target.y + target.height
            }) {
                return Some(target.id.clone());
            }
        }
        self.bounds.lock().ok().and_then(|bounds| {
            bounds
                .filter(|[left, top, width, height]| {
                    x >= *left && y >= *top && x <= *left + *width && y <= *top + *height
                })
                .map(|_| "manual".to_string())
        })
    }
}

#[tauri::command]
pub fn media_toolkit_drop_set_enabled(
    enabled: bool,
    x: Option<f64>,
    y: Option<f64>,
    width: Option<f64>,
    height: Option<f64>,
    targets: Option<Vec<MediaDropTarget>>,
    state: State<'_, MediaDropEnabled>,
) {
    let bounds = match (x, y, width, height) {
        (Some(x), Some(y), Some(width), Some(height))
            if [x, y, width, height].into_iter().all(f64::is_finite)
                && x >= 0.0
                && y >= 0.0
                && width > 0.0
                && height > 0.0 =>
        {
            Some([x, y, width, height])
        }
        _ => None,
    };
    let targets: Vec<MediaDropTarget> = targets
        .unwrap_or_default()
        .into_iter()
        .filter(|target| {
            uuid::Uuid::parse_str(&target.id).is_ok_and(|id| id.to_string() == target.id)
                && target.id.len() <= 64
                && [target.x, target.y, target.width, target.height]
                    .into_iter()
                    .all(f64::is_finite)
                && target.x >= 0.0
                && target.y >= 0.0
                && target.width > 0.0
                && target.height > 0.0
        })
        .take(30)
        .collect();
    state.set(
        enabled && (bounds.is_some() || !targets.is_empty()),
        bounds,
        targets,
    );
}

struct QuickAccessState(
    std::sync::Mutex<tauri::menu::MenuItem<tauri::Wry>>,
    std::sync::Mutex<(bool, String)>,
);

/// The menu-bar row shown while clipboard capture is paused.
const CLIPBOARD_PAUSED_LABEL: &str = "● Clipboard paused";
static TRAY_CLIPBOARD_PAUSED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);
const AUDIO_FILE_EXTENSIONS: &[&str] = &["wav", "mp3", "m4a", "aiff", "aif", "flac", "caf"];
const MAX_MEDIA_AUDIO_SELECTION: usize = 30;
const MAX_COPY_BYTES: usize = 8 * 1024 * 1024;
const MAX_SAVE_BYTES: usize = 64 * 1024 * 1024;
const MAX_MEDIA_HANDOFF_BYTES: usize = 64 * 1024 * 1024;
const MAX_MEDIA_SHORTCUT_LIST_BYTES: usize = 32 * 1024;
const MAX_MEDIA_SHORTCUT_NAMES: usize = 100;

fn validate_dropped_files(
    paths: Vec<std::path::PathBuf>,
) -> Result<Vec<std::path::PathBuf>, String> {
    if paths.is_empty() {
        return Err("Drop at least one media file".into());
    }
    if paths.len() > MAX_MEDIA_AUDIO_SELECTION {
        return Err("Drop at most 30 files at a time".into());
    }
    let mut seen = std::collections::HashSet::new();
    let mut files = Vec::with_capacity(paths.len());
    for path in paths {
        let metadata = std::fs::symlink_metadata(&path)
            .map_err(|_| "A dropped file is no longer available".to_string())?;
        if !metadata.file_type().is_file() {
            return Err("Drop files only; folders and symbolic links are not supported".into());
        }
        let path = path
            .canonicalize()
            .map_err(|_| "A dropped file is no longer available".to_string())?;
        if !seen.insert(path.clone()) {
            return Err("The same file was dropped more than once".into());
        }
        files.push(path);
    }
    Ok(files)
}

pub fn register_media_drop(
    paths: Vec<std::path::PathBuf>,
    address: std::net::SocketAddr,
    token: &str,
    api_token: &str,
) -> Result<Value, String> {
    let paths = validate_dropped_files(paths)?;
    #[cfg(target_os = "macos")]
    for path in &paths {
        if let Some(parent) = path.parent() {
            let _ = std::fs::read_dir(parent);
        }
    }
    register(
        address,
        token,
        api_token,
        "file-selections",
        json!({"paths":paths,"access":"read"}),
    )
}

/// Register files for the shared OfficeKit intake chooser.
pub fn register_file_intake(
    paths: Vec<std::path::PathBuf>,
    address: std::net::SocketAddr,
    token: &str,
    api_token: &str,
) -> Result<Value, String> {
    let paths = validate_dropped_files(paths)?;
    #[cfg(target_os = "macos")]
    for path in &paths {
        if let Some(parent) = path.parent() {
            let _ = std::fs::read_dir(parent);
        }
    }
    register(
        address,
        token,
        api_token,
        "file-selections",
        json!({"paths":paths,"access":"read"}),
    )
}

fn validate_reveal_ids(job_id: &str, item_id: &str) -> Result<(), String> {
    for value in [job_id, item_id] {
        let id = uuid::Uuid::parse_str(value).map_err(|_| "Invalid scanned item".to_string())?;
        if id.to_string() != value {
            return Err("Invalid scanned item".into());
        }
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn finder_command(path: &str) -> Result<std::process::Command, String> {
    if !std::path::Path::new(path).is_absolute() {
        return Err("Scanned item has an invalid location".into());
    }
    let mut command = std::process::Command::new("/usr/bin/open");
    command.arg("-R").arg(path);
    Ok(command)
}

#[tauri::command]
pub async fn file_job_reveal(
    job_id: String,
    item_id: String,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<(), String> {
    validate_reveal_ids(&job_id, &item_id)?;
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let result = register(
            address,
            &credential,
            &api_credential,
            &format!("file-jobs/{job_id}/reveals"),
            json!({"itemId":item_id}),
        )?;
        let path = result["path"]
            .as_str()
            .ok_or("Scanned location is unavailable")?;
        #[cfg(target_os = "macos")]
        {
            let status = finder_command(path)?
                .status()
                .map_err(|_| "Finder could not be opened")?;
            if !status.success() {
                return Err("Finder could not reveal this item".into());
            }
            Ok(())
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = path;
            Err("Show in Finder is available on macOS".into())
        }
    })
    .await
    .map_err(|_| "Finder is unavailable".to_string())?
}

#[cfg(target_os = "macos")]
fn publish_new(source: &std::path::Path, destination: &std::path::Path) -> std::io::Result<()> {
    use std::os::unix::ffi::OsStrExt;
    unsafe extern "C" {
        fn renamex_np(
            from: *const std::ffi::c_char,
            to: *const std::ffi::c_char,
            flags: u32,
        ) -> i32;
    }
    let from = std::ffi::CString::new(source.as_os_str().as_bytes())?;
    let to = std::ffi::CString::new(destination.as_os_str().as_bytes())?;
    // macOS SDK sys/stdio.h: RENAME_EXCL = 0x00000004. Supports native
    // exclusive atomic rename without depending on filesystem hard-link support.
    const RENAME_EXCL: u32 = 0x00000004;
    if unsafe { renamex_np(from.as_ptr(), to.as_ptr(), RENAME_EXCL) } == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(target_os = "windows")]
fn publish_new(source: &std::path::Path, destination: &std::path::Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn publish_new(source: &std::path::Path, destination: &std::path::Path) -> std::io::Result<()> {
    std::fs::hard_link(source, destination)?;
    std::fs::remove_file(source)
}

#[tauri::command]
pub fn officekit_quit(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
pub fn quick_access_recording(app: tauri::AppHandle, recording: bool) -> Result<(), String> {
    let state = app.state::<QuickAccessState>();
    let mut title = state
        .1
        .lock()
        .map_err(|_| "Quick access is unavailable".to_string())?;
    title.0 = recording;
    state
        .0
        .lock()
        .map_err(|_| "Quick access is unavailable".to_string())?
        .set_text(if recording {
            "Transcribe · Stop recording"
        } else {
            "Transcribe · Start recording"
        })
        .map_err(|_| "Quick access could not be updated".to_string())?;
    if let Some(tray) = app.tray_by_id("officekit-quick-access") {
        let _ = tray.set_tooltip(Some(if recording {
            "OfficeKit · Recording"
        } else {
            "OfficeKit quick access"
        }));
        #[cfg(target_os = "macos")]
        let _ = tray.set_title(Some(quick_title(title.0, &title.1)));
    }
    Ok(())
}

fn quick_title(recording: bool, stats: &str) -> String {
    if recording {
        format!("● {stats}").trim_end().to_string()
    } else {
        stats.to_string()
    }
}

#[tauri::command]
pub fn tray_stats_update(app: tauri::AppHandle, text: String) -> Result<(), String> {
    if text.len() > 256 || text.chars().any(char::is_control) {
        return Err("Menu-bar statistics text is invalid".into());
    }
    #[cfg(target_os = "macos")]
    {
        let state = app.state::<QuickAccessState>();
        let mut title = state
            .1
            .lock()
            .map_err(|_| "Quick access is unavailable".to_string())?;
        title.1 = text;
        if let Some(tray) = app.tray_by_id("officekit-quick-access") {
            tray.set_title(Some(quick_title(title.0, &title.1)))
                .map_err(|_| "Menu-bar statistics could not be updated".to_string())?;
        }
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Persistent menu-bar statistics are available on macOS".into())
    }
}

const MAX_MENU_DRAWERS_BYTES: usize = 64 * 1024;

/// Checks a drawers payload before it reaches the native layer: bounded size, valid JSON, a `drawers` list.
fn menu_drawers_payload_is_valid(payload: &str) -> bool {
    payload.len() <= MAX_MENU_DRAWERS_BYTES
        && serde_json::from_str::<serde_json::Value>(payload)
            .ok()
            .is_some_and(|value| {
                value
                    .get("drawers")
                    .is_some_and(serde_json::Value::is_array)
            })
}

#[cfg(target_os = "macos")]
static MENU_DRAWERS_APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_drawers_set_callback(callback: extern "C" fn(i32));
    fn officekit_drawers_set_quit_cancel_callback(callback: extern "C" fn(i32));
    fn officekit_drawers_set_storage_callback(callback: extern "C" fn());
    fn officekit_drawers_set_network_check_callback(callback: extern "C" fn());
    fn officekit_drawers_update(bytes: *const u8, length: u64) -> i32;
    fn officekit_drawers_remove();
}

/// The quick-access event a Storage analyser click in a drawer sends to the web layer.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn drawer_storage_event() -> serde_json::Value {
    json!({"action":"drawer-open","tool":"storage"})
}

/// The Network drawer's explicit check asks the WebView to run one bounded health request.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn drawer_network_check_event() -> serde_json::Value {
    json!({"action":"network-check"})
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn drawer_quit_event(pid: i32) -> serde_json::Value {
    json!({"action":"drawer-quit","pid":pid})
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn drawer_quit_cancel_event(pid: i32) -> serde_json::Value {
    json!({"action":"drawer-quit-cancel","pid":pid})
}

/// A confirmed in-drawer Quit sends the selected process to the local WebView handler without focusing OfficeKit.
#[cfg(target_os = "macos")]
extern "C" fn on_menu_drawer_quit(pid: i32) {
    if let Some(app) = MENU_DRAWERS_APP.get() {
        let _ = app.emit("quick-access", drawer_quit_event(pid));
    }
}

/// A cancelled process confirmation clears its inline status without opening OfficeKit.
#[cfg(target_os = "macos")]
extern "C" fn on_menu_drawer_quit_cancel(pid: i32) {
    if let Some(app) = MENU_DRAWERS_APP.get() {
        let _ = app.emit("quick-access", drawer_quit_cancel_event(pid));
    }
}

/// A Storage analyser click in the Disk drawer: bring OfficeKit forward and let the web layer open the tool.
#[cfg(target_os = "macos")]
extern "C" fn on_menu_drawer_storage() {
    if let Some(app) = MENU_DRAWERS_APP.get() {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.set_focus();
        }
        let _ = app.emit("quick-access", drawer_storage_event());
    }
}

/// A Run network check click asks the existing WebView to make the one-shot health request.
#[cfg(target_os = "macos")]
extern "C" fn on_menu_drawer_network_check() {
    if let Some(app) = MENU_DRAWERS_APP.get() {
        let _ = app.emit("quick-access", drawer_network_check_event());
    }
}

/// Shows or refreshes the CPU / RAM / SSD menu-bar drawers from a `{"drawers":[...]}` payload.
#[tauri::command]
pub fn menu_drawers_update(app: tauri::AppHandle, payload: String) -> Result<(), String> {
    if !menu_drawers_payload_is_valid(&payload) {
        return Err("Menu-bar drawers content is invalid".into());
    }
    #[cfg(target_os = "macos")]
    {
        if MENU_DRAWERS_APP.set(app).is_ok() {
            unsafe { officekit_drawers_set_callback(on_menu_drawer_quit) };
            unsafe { officekit_drawers_set_quit_cancel_callback(on_menu_drawer_quit_cancel) };
            unsafe { officekit_drawers_set_storage_callback(on_menu_drawer_storage) };
            unsafe { officekit_drawers_set_network_check_callback(on_menu_drawer_network_check) };
        }
        let status = unsafe { officekit_drawers_update(payload.as_ptr(), payload.len() as u64) };
        if status == 0 {
            Ok(())
        } else {
            Err("Menu-bar drawers content is invalid".into())
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("Menu-bar drawers are available on macOS".into())
    }
}

/// Removes every drawer item from the menu bar.
#[tauri::command]
pub fn menu_drawers_remove() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        unsafe { officekit_drawers_remove() };
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    Err("Menu-bar drawers are available on macOS".into())
}

fn publish_result(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    let temp = path.with_file_name(format!(".officekit-save-{}", uuid::Uuid::new_v4()));
    let outcome = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        // Save dialogs choose a new result file. Exclusive publication closes
        // the race between the picker and the final write without replacing
        // a file created by another process in the meantime.
        publish_new(&temp, path)
    })();
    if outcome.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    outcome
}

fn validate_name(name: &str) -> Result<(), String> {
    if name.is_empty()
        || name.len() > 255
        || name == "."
        || name == ".."
        || name
            .chars()
            .any(|c| c.is_control() || matches!(c, '/' | '\\' | ':'))
    {
        return Err("Choose a valid output filename".into());
    }
    Ok(())
}

fn ensure_suggested_extension(
    mut selected_path: std::path::PathBuf,
    suggested_name: &str,
) -> std::path::PathBuf {
    if selected_path.extension().is_none() {
        if let Some(extension) = std::path::Path::new(suggested_name).extension() {
            selected_path.set_extension(extension);
        }
    }
    selected_path
}

fn planned_directory(
    parent: &std::path::Path,
    suggested_name: Option<&str>,
) -> Result<std::path::PathBuf, String> {
    let name = suggested_name.unwrap_or("extracted-files");
    validate_name(name)?;
    let path = parent.join(name);
    if std::fs::symlink_metadata(&path).is_ok() {
        return Err(
            "The output folder already exists. Choose another parent folder or output folder name"
                .into(),
        );
    }
    Ok(path)
}

fn register(
    address: std::net::SocketAddr,
    token: &str,
    api_token: &str,
    route: &str,
    body: Value,
) -> Result<Value, String> {
    let response = ureq::post(format!("http://{address}/api/{route}"))
        .header("Authorization", &format!("Bearer {api_token}"))
        .header("X-OfficeKit-Native-Grant", token)
        .send_json(body)
        .map_err(|_| "The selected files could not be authorized".to_string())?;
    response
        .into_body()
        .with_config()
        .limit(1024 * 1024)
        .read_json::<Value>()
        .map_err(|_| "The selected files returned invalid metadata".into())
}

fn validate_selection_filter(
    paths: &[std::path::PathBuf],
    filter_kind: Option<&str>,
) -> Result<(), String> {
    if paths.len() > MAX_MEDIA_AUDIO_SELECTION && filter_kind == Some("audio") {
        return Err("Select at most 30 audio files at a time".into());
    }
    match filter_kind {
        None => Ok(()),
        Some("audio")
            if paths.iter().all(|path| {
                !path.is_dir()
                    && path
                        .extension()
                        .and_then(std::ffi::OsStr::to_str)
                        .is_some_and(|extension| {
                            AUDIO_FILE_EXTENSIONS
                                .iter()
                                .any(|allowed| extension.eq_ignore_ascii_case(allowed))
                        })
            }) =>
        {
            Ok(())
        }
        Some("audio") => Err("Choose supported local audio files".into()),
        Some(_) => Err("Choose a supported file selection".into()),
    }
}

#[tauri::command]
pub async fn file_selection_open(
    app: tauri::AppHandle,
    mode: String,
    access: String,
    filter_kind: Option<String>,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Option<Value>, String> {
    if !matches!(mode.as_str(), "files" | "folder")
        || !matches!(access.as_str(), "read" | "read-write")
    {
        return Err("Choose a supported file selection".into());
    }
    validate_selection_filter(&[], filter_kind.as_deref())?;
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let mut dialog = app.dialog().file().set_title(if access == "read-write" {
            "Choose original files to change in place"
        } else {
            "Choose files to process directly"
        });
        if filter_kind.as_deref() == Some("audio") {
            dialog = dialog.add_filter("Audio", AUDIO_FILE_EXTENSIONS);
        }
        let selected = if mode == "folder" {
            dialog.blocking_pick_folder().map(|p| vec![p])
        } else {
            dialog.blocking_pick_files()
        };
        let Some(selected) = selected else {
            return Ok(None);
        };
        let paths: Result<Vec<_>, _> = selected.into_iter().map(|p| p.into_path()).collect();
        let paths = paths.map_err(|_| "Only local files are supported".to_string())?;
        validate_selection_filter(&paths, filter_kind.as_deref())?;
        #[cfg(target_os = "macos")]
        {
            for path in &paths {
                if path.is_dir() {
                    let _ = std::fs::read_dir(path);
                } else if let Some(parent) = path.parent() {
                    let _ = std::fs::read_dir(parent);
                }
            }
        }
        register(
            address,
            &credential,
            &api_credential,
            "file-selections",
            json!({"paths":paths,"access":access}),
        )
        .map(Some)
    })
    .await
    .map_err(|_| "File selection is unavailable".to_string())?
}

/// Grant one folder for session-scoped automatic preparation. The path stays
/// in the native/backend grant and is never returned to the webview.
#[tauri::command]
pub async fn media_folder_watch_open(
    app: tauri::AppHandle,
    pipeline_id: String,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Option<Value>, String> {
    let pipeline = uuid::Uuid::parse_str(&pipeline_id)
        .map_err(|_| "Choose a saved media pipeline".to_string())?;
    if pipeline.to_string() != pipeline_id {
        return Err("Choose a saved media pipeline".into());
    }
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app
            .dialog()
            .file()
            .set_title("Choose a folder OfficeKit may watch and save prepared copies into")
            .blocking_pick_folder();
        let Some(selected) = selected else {
            return Ok(None);
        };
        let path = selected
            .into_path()
            .map_err(|_| "Only a local folder can be watched".to_string())?;
        if !path.is_dir() {
            return Err("Choose a folder to watch".into());
        }
        #[cfg(target_os = "macos")]
        {
            let _ = std::fs::read_dir(&path)
                .map_err(|_| "OfficeKit could not access the selected folder".to_string())?;
        }
        let selection = register(
            address,
            &credential,
            &api_credential,
            "file-selections",
            json!({"paths":[path],"access":"read-write"}),
        )?;
        let selection_id = selection
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| "The folder grant was not created".to_string())?;
        register(
            address,
            &credential,
            &api_credential,
            "media-folder-watches",
            json!({"selectionId":selection_id,"pipelineId":pipeline.to_string()}),
        )
        .map(Some)
    })
    .await
    .map_err(|_| "Folder automation is unavailable".to_string())?
}

fn media_handoff_shortcut_names() -> Result<Vec<String>, String> {
    #[cfg(target_os = "macos")]
    {
        let mut child = std::process::Command::new("/usr/bin/shortcuts")
            .arg("list")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .map_err(|_| "Apple Shortcuts is unavailable".to_string())?;

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Installed shortcuts could not be listed".to_string())?;
        let reader = std::thread::spawn(move || {
            let mut stdout = stdout;
            let mut captured = Vec::with_capacity(MAX_MEDIA_SHORTCUT_LIST_BYTES);
            let mut buffer = [0u8; 4096];
            let mut exceeded_limit = false;
            loop {
                let read = match std::io::Read::read(&mut stdout, &mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(read) => read,
                };
                let remaining = MAX_MEDIA_SHORTCUT_LIST_BYTES.saturating_sub(captured.len());
                captured.extend_from_slice(&buffer[..read.min(remaining)]);
                exceeded_limit |= read > remaining;
            }
            (captured, exceeded_limit)
        });
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) => {}
                Err(_) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    let _ = reader.join();
                    return Err("Installed shortcuts could not be listed".into());
                }
            }
            if std::time::Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                let _ = reader.join();
                return Err("Installed shortcuts could not be listed".into());
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        };
        let (stdout, exceeded_limit) = reader
            .join()
            .map_err(|_| "Installed shortcuts could not be listed".to_string())?;
        if !status.success() || exceeded_limit {
            return Err("Installed shortcuts could not be listed".into());
        }
        return parse_media_shortcut_names(&stdout);
    }
    #[cfg(not(target_os = "macos"))]
    Err("Apple Shortcuts handoff is available on macOS".into())
}

fn parse_media_shortcut_names(output: &[u8]) -> Result<Vec<String>, String> {
    if output.len() > MAX_MEDIA_SHORTCUT_LIST_BYTES {
        return Err("Installed shortcuts could not be listed".into());
    }
    let output = std::str::from_utf8(output)
        .map_err(|_| "Installed shortcuts could not be listed".to_string())?;
    let names = output
        .lines()
        .map(str::trim)
        .filter(|name| !name.is_empty() && name.len() <= 128 && !name.chars().any(char::is_control))
        .take(MAX_MEDIA_SHORTCUT_NAMES)
        .map(str::to_string)
        .collect();
    Ok(names)
}

#[allow(deprecated)] // Name lookup avoids hard-coding third-party bundle identifiers.
fn media_handoff_destination_available(destination: &str) -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    {
        let app_name = match destination {
            "dropshare" => "Dropshare",
            "yoink" => "Yoink",
            "dockside" => "Dockside",
            "dropover" => "Dropover",
            "atoll" => "Atoll",
            "shortcut" => return Ok(std::path::Path::new("/usr/bin/shortcuts").is_file()),
            _ => return Err("Choose a supported media destination".into()),
        };
        let workspace = NSWorkspace::sharedWorkspace();
        return Ok(workspace
            .fullPathForApplication(&NSString::from_str(app_name))
            .is_some());
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = destination;
        Err("External media handoffs are available on macOS".into())
    }
}

fn encode_url_query_value(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(byte));
        } else {
            encoded.push('%');
            encoded.push_str(&format!("{byte:02X}"));
        }
    }
    encoded
}

fn media_handoff_command(
    destination: &str,
    file_path: &std::path::Path,
    shortcut_name: Option<&str>,
) -> Result<std::process::Command, String> {
    let path = file_path
        .to_str()
        .ok_or_else(|| "The saved file name cannot be handed to this app".to_string())?;
    let mut command = match destination {
        "dropshare" => {
            let url = format!(
                "dropshare5:///action/upload?file={}",
                encode_url_query_value(path)
            );
            let mut command = std::process::Command::new("/usr/bin/open");
            command.arg("-u").arg(url);
            command
        }
        "dockside" => {
            let url = format!(
                "dockside://action/add?file={}",
                encode_url_query_value(path)
            );
            let mut command = std::process::Command::new("/usr/bin/open");
            command.arg("-u").arg(url);
            command
        }
        "yoink" | "dropover" | "atoll" => {
            let app_name = match destination {
                "yoink" => "Yoink",
                "dropover" => "Dropover",
                _ => "Atoll",
            };
            let mut command = std::process::Command::new("/usr/bin/open");
            command.args(["-a", app_name, "--"]).arg(file_path);
            command
        }
        "shortcut" => {
            let name = shortcut_name.ok_or_else(|| "Choose an installed shortcut".to_string())?;
            if name.trim() != name
                || name.is_empty()
                || name.len() > 128
                || name.chars().any(char::is_control)
            {
                return Err("Choose an installed shortcut".into());
            }
            let mut command = std::process::Command::new("/usr/bin/shortcuts");
            command.args(["run", name, "--input-path", path]);
            command
        }
        _ => return Err("Choose a supported media destination".into()),
    };
    command
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    Ok(command)
}

fn run_media_handoff_command(
    mut command: std::process::Command,
    shortcut: bool,
) -> Result<(), String> {
    let mut child = command
        .spawn()
        .map_err(|_| "The selected app could not be opened".to_string())?;
    let timeout = if shortcut {
        std::time::Duration::from_secs(60)
    } else {
        std::time::Duration::from_secs(10)
    };
    let deadline = std::time::Instant::now() + timeout;
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|_| "The selected app could not be opened".to_string())?
        {
            return if status.success() {
                Ok(())
            } else {
                Err("The selected app did not accept the prepared copy".into())
            };
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(
                "The selected handoff took too long. The saved copy is still available.".into(),
            );
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

fn fetch_media_handoff_artifact(
    address: std::net::SocketAddr,
    artifact_id: uuid::Uuid,
    api_credential: &str,
) -> Result<Vec<u8>, String> {
    fetch_media_handoff_artifact_with_timeout(
        address,
        artifact_id,
        api_credential,
        std::time::Duration::from_secs(30),
    )
}

fn fetch_media_handoff_artifact_with_timeout(
    address: std::net::SocketAddr,
    artifact_id: uuid::Uuid,
    api_credential: &str,
    timeout: std::time::Duration,
) -> Result<Vec<u8>, String> {
    let artifact_url = format!("http://{address}/api/media-artifacts/{artifact_id}");
    let agent = ureq::Agent::new_with_config(
        ureq::config::Config::builder()
            .max_redirects(0)
            .timeout_global(Some(timeout))
            .build(),
    );
    let response = agent
        .get(&artifact_url)
        .header("Authorization", &format!("Bearer {api_credential}"))
        .call()
        .map_err(|_| "The prepared copy is no longer available".to_string())?;
    let bytes = response
        .into_body()
        .with_config()
        .limit(MAX_MEDIA_HANDOFF_BYTES as u64)
        .read_to_vec()
        .map_err(|_| "The prepared copy exceeds the handoff size limit".to_string())?;
    if bytes.is_empty() || bytes.len() > MAX_MEDIA_HANDOFF_BYTES {
        return Err("The prepared copy is empty or exceeds the handoff size limit".into());
    }
    Ok(bytes)
}

#[tauri::command]
pub fn media_handoff_capabilities() -> Value {
    #[cfg(target_os = "macos")]
    {
        let apps = ["dropshare", "yoink", "dockside", "dropover", "atoll"]
            .into_iter()
            .map(|destination| {
                let available = media_handoff_destination_available(destination).unwrap_or(false);
                (destination.to_string(), Value::Bool(available))
            })
            .collect::<serde_json::Map<_, _>>();
        let shortcuts = media_handoff_shortcut_names().unwrap_or_default();
        return json!({"available":true,"apps":apps,"shortcuts":shortcuts});
    }
    #[cfg(not(target_os = "macos"))]
    json!({"available":false,"apps":{},"shortcuts":[]})
}

#[tauri::command]
pub async fn media_handoff_open(
    app: tauri::AppHandle,
    artifact_id: String,
    suggested_name: String,
    destination: String,
    shortcut_name: Option<String>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Value, String> {
    let artifact_uuid = uuid::Uuid::parse_str(&artifact_id)
        .map_err(|_| "The prepared copy is no longer available".to_string())?;
    if artifact_uuid.to_string() != artifact_id {
        return Err("The prepared copy is no longer available".into());
    }
    validate_name(&suggested_name)?;
    let available = media_handoff_destination_available(&destination)?;
    if !available {
        return Err("Install the selected app or save the copy for another time".into());
    }
    let shortcut_name = if destination == "shortcut" {
        let name = shortcut_name.ok_or_else(|| "Choose an installed shortcut".to_string())?;
        if !media_handoff_shortcut_names()?
            .iter()
            .any(|installed| installed == &name)
        {
            return Err("Choose a shortcut from the installed list".into());
        }
        Some(name)
    } else {
        if shortcut_name.is_some() {
            return Err("Shortcut selection is not valid for this destination".into());
        }
        None
    };
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let bytes = fetch_media_handoff_artifact(address, artifact_uuid, &api_credential)?;
        let Some(selected) = app
            .dialog()
            .file()
            .set_title("Choose where to save the prepared copy before handing it off")
            .set_file_name(suggested_name.clone())
            .blocking_save_file()
        else {
            return Ok(json!({"state":"cancelled"}));
        };
        let selected_path = selected
            .into_path()
            .map_err(|_| "Only local save locations are supported".to_string())?;
        let output_path = ensure_suggested_extension(selected_path, &suggested_name);
        publish_result(&output_path, &bytes).map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                "A file already exists there. Choose a new name to keep both copies.".to_string()
            } else {
                "The prepared copy could not be saved safely".to_string()
            }
        })?;
        let command = media_handoff_command(&destination, &output_path, shortcut_name.as_deref())?;
        match run_media_handoff_command(command, destination == "shortcut") {
            Ok(()) => Ok(json!({
                "state":"handoff-requested",
                "destination":destination,
                "savedName":output_path.file_name().and_then(|name| name.to_str()).unwrap_or("prepared copy"),
            })),
            Err(message) => Ok(json!({
                "state":"saved-handoff-failed",
                "destination":destination,
                "savedName":output_path.file_name().and_then(|name| name.to_str()).unwrap_or("prepared copy"),
                "message":message,
            })),
        }
    })
    .await
    .map_err(|_| "The native media handoff could not finish".to_string())?
}

/// Loading a PKCS#11 provider executes native code. The webview cannot supply
/// a path: the user must select the installed provider in this native picker.
#[tauri::command]
pub async fn pdf_signing_provider_open(
    app: tauri::AppHandle,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Option<Value>, String> {
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app
            .dialog()
            .file()
            .set_title("Choose a trusted installed DSC provider library (runs native code)")
            .add_filter("PKCS#11 provider", &["dll", "dylib", "so"])
            .blocking_pick_file();
        let Some(selected) = selected else {
            return Ok(None);
        };
        let path = selected
            .into_path()
            .map_err(|_| "Only local provider libraries are supported".to_string())?;
        register(
            address,
            &credential,
            &api_credential,
            "pdf-signing-providers/native",
            json!({"path": path}),
        )
        .map(Some)
    })
    .await
    .map_err(|_| "DSC provider selection is unavailable".to_string())?
}

fn storage_scan_body(older_than_days: u32) -> Result<Value, String> {
    if !(1..=3650).contains(&older_than_days) {
        return Err("Choose an age between 1 and 3,650 days".into());
    }
    Ok(json!({"olderThanDays": older_than_days}))
}

fn storage_plan_route(plan_id: &str) -> Result<String, String> {
    let parsed =
        uuid::Uuid::parse_str(plan_id).map_err(|_| "The cleanup plan is invalid".to_string())?;
    if parsed.to_string() != plan_id {
        return Err("The cleanup plan is invalid".into());
    }
    Ok(format!("storage-cleanup-plans/{plan_id}/execution"))
}

/// Opens the OS-owned permission screen; the user grants access there.
#[tauri::command]
pub async fn storage_permissions_open() -> Result<Value, String> {
    #[cfg(target_os = "macos")]
    {
        tauri::async_runtime::spawn_blocking(|| {
            let status = std::process::Command::new("/usr/bin/open")
                .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")
                .status()
                .map_err(|_| {
                    "Open System Settings → Privacy & Security → Full Disk Access".to_string()
                })?;
            if !status.success() {
                return Err("Open System Settings → Privacy & Security → Full Disk Access".into());
            }
            Ok(json!({"state": "opened"}))
        })
        .await
        .map_err(|_| "System Settings could not be opened".to_string())?
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("Review file access permissions in your operating system settings".into())
    }
}

/// Storage scope is discovered by the local service, never supplied by JavaScript.
#[tauri::command]
pub async fn storage_scan_start(
    older_than_days: u32,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Value, String> {
    let body = storage_scan_body(older_than_days)?;
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        register(address, &credential, &api_credential, "storage-scans", body)
    })
    .await
    .map_err(|_| "Storage scan is unavailable".to_string())?
}

/// Only a reviewed, expiring service-issued plan can authorize cleanup.
#[tauri::command]
pub async fn storage_cleanup_apply(
    plan_id: String,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Value, String> {
    let route = storage_plan_route(&plan_id)?;
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        register(address, &credential, &api_credential, &route, json!({}))
    })
    .await
    .map_err(|_| "Storage cleanup is unavailable".to_string())?
}

#[tauri::command]
pub async fn file_output_choose(
    app: tauri::AppHandle,
    kind: String,
    suggested_name: Option<String>,
    job_kind: String,
    overwrite: bool,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Option<Value>, String> {
    if !matches!(kind.as_str(), "file" | "directory")
        || !matches!(
            job_kind.as_str(),
            "split" | "join" | "archive-create" | "archive-extract" | "trash-restore"
        )
    {
        return Err("Choose a supported output destination".into());
    }
    if let Some(name) = &suggested_name {
        validate_name(name)?;
    }
    if kind == "directory" && overwrite {
        return Err(
            "Choose a new output folder; replacing existing folders is not supported".into(),
        );
    }
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let mut dialog = app.dialog().file().set_title(if kind == "directory" {
            "Choose a parent folder for the new output folder"
        } else { "Choose where to save output" });
        if let Some(name) = &suggested_name {
            dialog = dialog.set_file_name(name);
        }
        let selected = if kind == "directory" {
            dialog.blocking_pick_folder()
        } else {
            dialog.blocking_save_file()
        };
        let Some(selected) = selected else {
            return Ok(None);
        };
        let mut path = selected
            .into_path()
            .map_err(|_| "Only local destinations are supported".to_string())?;
        if kind == "directory" { path = planned_directory(&path, suggested_name.as_deref())?; }
        if overwrite && !app.dialog().message("Allow this operation to replace existing output files in the selected destination?")
            .title("Replace existing output?")
            .buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom("Replace".into(), "Cancel".into()))
            .blocking_show() {
            return Ok(None);
        }
        #[cfg(target_os = "macos")]
        {
            let target_parent = if kind == "directory" { Some(path.as_path()) } else { path.parent() };
            if let Some(parent) = target_parent {
                let _ = std::fs::read_dir(parent);
            }
        }
        register(
            address,
            &credential,
            &api_credential,
            "file-output-grants",
            json!({"path":path,"kind":kind,"job_kind":job_kind,"overwrite":overwrite}),
        )
        .map(Some)
    })
    .await
    .map_err(|_| "Output selection is unavailable".to_string())?
}

const MAX_TRASH_RESTORE_ITEMS: usize = 100;
const MAX_TRASH_DIALOG_LINES: usize = 20;
const MAX_TRASH_NAME_BYTES: usize = 255;
const MAX_TRASH_FOLDER_BYTES: usize = 4096;
const MAX_TRASH_PATH_BYTES: usize = 4096;
const TRASH_RESTORE_INTRO: &str = "They go back to their original folders. Nothing is replaced: if a name is taken, that item is skipped.";
const TRASH_FORGET_MESSAGE: &str = "OfficeKit removes it from this list. The item stays in Trash, and you can still drag it out yourself in Finder.";

/// One Trash item the user chose to restore. `folder` is the original folder, or the
/// chosen destination folder when a destination grant is used.
#[derive(serde::Deserialize)]
pub struct TrashRestoreItem {
    pub id: String,
    pub name: String,
    pub folder: String,
}

fn canonical_uuid(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|id| id.to_string() == value)
}

fn validate_trash_text(value: &str, max_bytes: usize) -> Result<(), String> {
    if value.is_empty() || value.len() > max_bytes || value.contains('\0') {
        return Err("The item is invalid".into());
    }
    Ok(())
}

fn validate_record_ids(ids: &[&str]) -> Result<(), String> {
    if ids.is_empty() || ids.len() > MAX_TRASH_RESTORE_ITEMS {
        return Err("Choose 1 to 100 items to restore".into());
    }
    let mut seen = std::collections::HashSet::new();
    for id in ids {
        if !canonical_uuid(id) || !seen.insert(*id) {
            return Err("The selected items are invalid".into());
        }
    }
    Ok(())
}

fn validate_restore_items(items: &[TrashRestoreItem]) -> Result<(), String> {
    let ids: Vec<&str> = items.iter().map(|item| item.id.as_str()).collect();
    validate_record_ids(&ids)?;
    for item in items {
        validate_trash_text(&item.name, MAX_TRASH_NAME_BYTES)?;
        validate_trash_text(&item.folder, MAX_TRASH_FOLDER_BYTES)?;
    }
    Ok(())
}

fn validate_destination(destination: Option<&str>, item_count: usize) -> Result<(), String> {
    match destination {
        None => Ok(()),
        Some(grant) if item_count == 1 && canonical_uuid(grant) => Ok(()),
        Some(_) => Err("Choose one item to restore to a folder".into()),
    }
}

fn restore_dialog_title(count: usize) -> String {
    if count == 1 {
        "Restore 1 item?".into()
    } else {
        format!("Restore {count} items?")
    }
}

/// `lines` holds one "name → folder" entry per item; at most 20 are shown.
fn restore_dialog_message(lines: &[String]) -> String {
    let mut message = TRASH_RESTORE_INTRO.to_string();
    for line in lines.iter().take(MAX_TRASH_DIALOG_LINES) {
        message.push('\n');
        message.push_str(line);
    }
    let hidden = lines.len().saturating_sub(MAX_TRASH_DIALOG_LINES);
    if hidden > 0 {
        message.push_str(&format!("\nand {hidden} more."));
    }
    message
}

fn restore_line(name: &str, folder: &str) -> String {
    format!("{name} → {folder}")
}

fn forget_dialog_title(name: &str) -> String {
    format!("Forget \u{201C}{name}\u{201D}?")
}

fn restore_grant_body(record_ids: &[&str], destination: Option<&str>) -> Value {
    json!({"recordIds": record_ids, "destinationGrantId": destination})
}

fn restore_apply_body(record_ids: &[&str], restore_grant_id: &str) -> Value {
    json!({"recordIds": record_ids, "restoreGrantId": restore_grant_id})
}

fn validate_reveal_path(path: &str) -> Result<(), String> {
    let unavailable = || "The restored item is not available to show".to_string();
    if path.len() > MAX_TRASH_PATH_BYTES
        || path.contains('\0')
        || !std::path::Path::new(path).is_absolute()
    {
        return Err(unavailable());
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable())?;
    if metadata.file_type().is_symlink() {
        return Err(unavailable());
    }
    Ok(())
}

fn delete_record(
    address: std::net::SocketAddr,
    token: &str,
    api_token: &str,
    record_id: &str,
) -> Result<(), String> {
    let agent =
        ureq::Agent::new_with_config(ureq::config::Config::builder().max_redirects(0).build());
    let response = agent
        .delete(format!("http://{address}/api/trash-records/{record_id}"))
        .header("Authorization", &format!("Bearer {api_token}"))
        .header("X-OfficeKit-Native-Grant", token)
        .call()
        .map_err(|_| "The item could not be removed from the list".to_string())?;
    if response.status().as_u16() == 204 {
        Ok(())
    } else {
        Err("The item could not be removed from the list".into())
    }
}

/// Native confirm step: the user approves the exact items, then the service issues a grant.
#[tauri::command]
pub async fn trash_restore_confirm(
    app: tauri::AppHandle,
    items: Vec<TrashRestoreItem>,
    destination_grant_id: Option<String>,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Option<String>, String> {
    validate_restore_items(&items)?;
    validate_destination(destination_grant_id.as_deref(), items.len())?;
    let ids: Vec<String> = items.iter().map(|item| item.id.clone()).collect();
    let lines: Vec<String> = items
        .iter()
        .map(|item| restore_line(&item.name, &item.folder))
        .collect();
    let title = restore_dialog_title(items.len());
    let message = restore_dialog_message(&lines);
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let approved = app
            .dialog()
            .message(message)
            .title(title)
            .buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom(
                "Restore".into(),
                "Cancel".into(),
            ))
            .blocking_show();
        if !approved {
            return Ok(None);
        }
        let ids: Vec<&str> = ids.iter().map(String::as_str).collect();
        let response = register(
            address,
            &credential,
            &api_credential,
            "trash-restore-grants",
            restore_grant_body(&ids, destination_grant_id.as_deref()),
        )?;
        response["id"]
            .as_str()
            .filter(|id| canonical_uuid(id))
            .map(|id| Some(id.to_string()))
            .ok_or_else(|| "The restore could not be approved".to_string())
    })
    .await
    .map_err(|_| "Restore is unavailable".to_string())?
}

/// Runs the restore that the confirm step already approved. No dialog here.
#[tauri::command]
pub async fn trash_restore_apply(
    restore_grant_id: String,
    record_ids: Vec<String>,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<Value, String> {
    if !canonical_uuid(&restore_grant_id) {
        return Err("The restore could not be approved".into());
    }
    let ids: Vec<&str> = record_ids.iter().map(String::as_str).collect();
    validate_record_ids(&ids)?;
    let body = restore_apply_body(&ids, &restore_grant_id);
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        register(
            address,
            &credential,
            &api_credential,
            "trash-restorations",
            body,
        )
    })
    .await
    .map_err(|_| "Restore is unavailable".to_string())?
}

/// Removes a record from the OfficeKit list only; the item stays in Trash.
#[tauri::command]
pub async fn trash_record_forget(
    app: tauri::AppHandle,
    record_id: String,
    name: String,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, super::BackendApiToken>,
    backend_address: State<'_, super::BackendApiAddress>,
) -> Result<bool, String> {
    if !canonical_uuid(&record_id) {
        return Err("The item is invalid".into());
    }
    validate_trash_text(&name, MAX_TRASH_NAME_BYTES)?;
    let title = forget_dialog_title(&name);
    let credential = token.0.clone();
    let api_credential = api_token.0.clone();
    let address = backend_address.0;
    tauri::async_runtime::spawn_blocking(move || {
        let approved = app
            .dialog()
            .message(TRASH_FORGET_MESSAGE)
            .title(title)
            .buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom(
                "Forget".into(),
                "Cancel".into(),
            ))
            .blocking_show();
        if !approved {
            return Ok(false);
        }
        delete_record(address, &credential, &api_credential, &record_id)?;
        Ok(true)
    })
    .await
    .map_err(|_| "The item could not be removed from the list".to_string())?
}

/// Reveals a restored item in Finder after checking it is a real, non-symlink path.
#[tauri::command]
pub async fn trash_restore_reveal(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        validate_reveal_path(&path)?;
        #[cfg(target_os = "macos")]
        {
            let status = finder_command(&path)?
                .status()
                .map_err(|_| "Finder could not be opened")?;
            if !status.success() {
                return Err("Finder could not reveal this item".into());
            }
            Ok(())
        }
        #[cfg(not(target_os = "macos"))]
        {
            Err("Show in Finder is available on macOS".into())
        }
    })
    .await
    .map_err(|_| "Finder is unavailable".to_string())?
}

#[tauri::command]
pub fn result_copy_text(app: tauri::AppHandle, text: String) -> Result<(), String> {
    if text.len() > MAX_COPY_BYTES {
        return Err("Too large to copy—download the complete result".into());
    }
    app.clipboard()
        .write_text(text)
        .map_err(|_| "Clipboard access failed. Download the result instead".into())
}

#[tauri::command]
pub async fn result_save(
    app: tauri::AppHandle,
    suggested_name: String,
    base64_data: String,
) -> Result<Option<Value>, String> {
    validate_name(&suggested_name)?;
    if base64_data.len() > MAX_SAVE_BYTES.div_ceil(3) * 4 {
        return Err("Result exceeds the 64 MiB save limit".into());
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(base64_data)
        .map_err(|_| "Result encoding is invalid".to_string())?;
    if bytes.len() > MAX_SAVE_BYTES {
        return Err("Result exceeds the 64 MiB save limit".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let Some(selected) = app.dialog().file().set_file_name(suggested_name.clone()).blocking_save_file() else { return Ok(None) };
        let path = selected.into_path().map_err(|_| "Only local destinations are supported".to_string())?;
        let path = ensure_suggested_extension(path, &suggested_name);
        #[cfg(target_os = "macos")]
        {
            if let Some(parent) = path.parent() {
                let _ = std::fs::read_dir(parent);
            }
        }
        // Save dialog supplies overwrite consent. Publish only after a complete write.
        if publish_result(&path, &bytes).is_err() { return Err("The result could not be saved. Choose another destination".into()); }
        Ok(Some(json!({"state":"saved","name":path.file_name().map(|n| n.to_string_lossy().to_string())})))
    }).await.map_err(|_| "Saving is unavailable".to_string())?
}

/// Builds the quick-access menu, with the paused row first while capture is paused. Returns the
/// menu and its transcribe row, which the recording state updates.
fn quick_access_menu(
    app: &tauri::AppHandle,
    paused: bool,
) -> tauri::Result<(
    tauri::menu::Menu<tauri::Wry>,
    tauri::menu::MenuItem<tauri::Wry>,
)> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
    let transcribe = MenuItem::with_id(
        app,
        "transcribe",
        "Transcribe · Start / Stop",
        super::dictation_commands_enabled(env!("OFFICEKIT_RELEASE_PROFILE")),
        None::<&str>,
    )?;
    let mut rows: Vec<Box<dyn tauri::menu::IsMenuItem<tauri::Wry>>> = Vec::new();
    if paused {
        rows.push(Box::new(MenuItem::with_id(
            app,
            "clipboard-paused",
            CLIPBOARD_PAUSED_LABEL,
            false,
            None::<&str>,
        )?));
        rows.push(Box::new(PredefinedMenuItem::separator(app)?));
    }
    rows.push(Box::new(transcribe.clone()));
    rows.push(Box::new(MenuItem::with_id(
        app,
        "screenshot",
        "Capture screenshot",
        true,
        None::<&str>,
    )?));
    rows.push(Box::new(MenuItem::with_id(
        app,
        "system-stats",
        "System stats",
        true,
        None::<&str>,
    )?));
    rows.push(Box::new(MenuItem::with_id(
        app,
        "open",
        "Open OfficeKit",
        true,
        None::<&str>,
    )?));
    rows.push(Box::new(MenuItem::with_id(
        app,
        "quit",
        "Quit OfficeKit",
        true,
        None::<&str>,
    )?));
    let refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        rows.iter().map(|row| row.as_ref()).collect();
    let menu = Menu::with_items(app, &refs)?;
    Ok((menu, transcribe))
}

/// Shows or hides the "● Clipboard paused" row in the menu-bar menu. Rebuilds the menu only on a change.
/// Menu items are AppKit objects, so the rebuild runs on the main thread.
pub fn set_clipboard_paused_menu(app: &tauri::AppHandle, paused: bool) {
    use std::sync::atomic::Ordering;
    if TRAY_CLIPBOARD_PAUSED.swap(paused, Ordering::Relaxed) == paused {
        return;
    }
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || rebuild_clipboard_paused_menu(&handle, paused));
}

fn rebuild_clipboard_paused_menu(app: &tauri::AppHandle, paused: bool) {
    let Ok((menu, transcribe)) = quick_access_menu(app, paused) else {
        return;
    };
    let recording = app
        .try_state::<QuickAccessState>()
        .and_then(|state| state.1.lock().ok().map(|title| title.0))
        .unwrap_or(false);
    if recording {
        let _ = transcribe.set_text("Transcribe · Stop recording");
    }
    if let Some(state) = app.try_state::<QuickAccessState>() {
        if let Ok(mut slot) = state.0.lock() {
            *slot = transcribe;
        }
    }
    if let Some(tray) = app.tray_by_id("officekit-quick-access") {
        let _ = tray.set_menu(Some(menu));
    }
}

const QUICK_CONTROLS_WIDTH: f64 = 360.0;
const QUICK_CONTROLS_HEIGHT: f64 = 860.0;
/// Room kept for the menu bar and the Dock on a short screen.
const QUICK_CONTROLS_SCREEN_MARGIN: f64 = 96.0;

/// The panel's height: its full height, or the screen's height less a margin so a MacBook never clips it.
fn fit_quick_controls_height(screen_height: f64) -> f64 {
    QUICK_CONTROLS_HEIGHT.min((screen_height - QUICK_CONTROLS_SCREEN_MARGIN).max(320.0))
}

fn quick_controls_height(window: &tauri::WebviewWindow) -> f64 {
    match window.current_monitor() {
        Ok(Some(monitor)) => {
            fit_quick_controls_height(monitor.size().height as f64 / monitor.scale_factor())
        }
        _ => QUICK_CONTROLS_HEIGHT,
    }
}

/// Sizes the panel to the screen it opens on; the content scrolls when the screen is shorter than the panel.
fn fit_quick_controls(window: &tauri::WebviewWindow) {
    let _ = window.set_size(tauri::LogicalSize::new(
        QUICK_CONTROLS_WIDTH,
        quick_controls_height(window),
    ));
}

pub fn install_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let (menu, transcribe) = quick_access_menu(app, false)?;
    app.manage(QuickAccessState(
        std::sync::Mutex::new(transcribe),
        std::sync::Mutex::new((false, String::new())),
    ));
    let quick_window = WebviewWindowBuilder::new(
        app,
        "quick-controls",
        WebviewUrl::App("quick-controls.html".into()),
    )
    .title("OfficeKit Quick Controls")
    .inner_size(360.0, 860.0)
    .resizable(false)
    .decorations(false)
    .transparent(true)
    // The card draws its own shadow; a native one outlines the whole transparent window as a black rectangle.
    .shadow(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .visible(false)
    .build()?;
    let quick_window_for_events = quick_window.clone();
    quick_window.on_window_event(move |event| {
        if matches!(event, WindowEvent::Focused(false)) {
            let _ = quick_window_for_events.hide();
        }
    });
    let mut tray = tauri::tray::TrayIconBuilder::with_id("officekit-quick-access")
        .tooltip("OfficeKit quick access")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click {
                rect,
                button: tauri::tray::MouseButton::Left,
                button_state: tauri::tray::MouseButtonState::Up,
                ..
            } = event
            {
                if let Some(window) = tray.app_handle().get_webview_window("quick-controls") {
                    if window.is_visible().unwrap_or(false) {
                        let _ = window.hide();
                        return;
                    }
                    fit_quick_controls(&window);
                    let scale = window.scale_factor().unwrap_or(1.0);
                    let width = (QUICK_CONTROLS_WIDTH * scale) as i32;
                    let height = (quick_controls_height(&window) * scale) as i32;
                    let (tray_x, tray_y, tray_width, tray_height) = match (rect.position, rect.size)
                    {
                        (tauri::Position::Physical(position), tauri::Size::Physical(size)) => (
                            position.x as i32,
                            position.y as i32,
                            size.width as i32,
                            size.height as i32,
                        ),
                        (tauri::Position::Logical(position), tauri::Size::Logical(size)) => (
                            (position.x * scale) as i32,
                            (position.y * scale) as i32,
                            (size.width * scale) as i32,
                            (size.height * scale) as i32,
                        ),
                        _ => return,
                    };
                    let mut x = tray_x + tray_width / 2 - width / 2;
                    let mut y = tray_y + tray_height;
                    if let Ok(Some(monitor)) = window.current_monitor() {
                        let origin = monitor.position();
                        let size = monitor.size();
                        if tray_y > origin.y + size.height as i32 / 2 {
                            y = tray_y - height;
                        }
                        x = x.clamp(origin.x, origin.x + size.width as i32 - width);
                        y = y.clamp(origin.y, origin.y + size.height as i32 - height);
                    }
                    let _ = window.set_position(tauri::Position::Physical(
                        tauri::PhysicalPosition::new(x, y),
                    ));
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        })
        .on_menu_event(|app, event| {
            let action = event.id.as_ref();
            if matches!(action, "system-stats" | "open") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            let _ = app.emit("quick-access", json!({"action":action}));
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// Opens the Quick controls panel in the middle of the screen, for when it is not opened from the menu bar icon.
pub fn show_quick_controls(app: &tauri::AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window("quick-controls") {
            fit_quick_controls(&window);
            let _ = window.center();
            let _ = window.show();
            let _ = window.set_focus();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quick_controls_height_fits_short_screens() {
        assert_eq!(fit_quick_controls_height(1440.0), 860.0);
        assert_eq!(fit_quick_controls_height(900.0), 804.0);
        assert_eq!(fit_quick_controls_height(700.0), 604.0);
        assert_eq!(fit_quick_controls_height(100.0), 320.0);
    }

    const ID_A: &str = "5f0c6a52-2d7e-4b8a-9c3d-1e2f3a4b5c6d";
    const ID_B: &str = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
    const GRANT: &str = "0b9d8c7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e";

    #[test]
    fn file_intake_queue_is_bounded_fifo_and_acknowledges_by_selection_id() {
        let queue = FileIntakeQueue::default();
        for index in 0..8 {
            queue
                .push(json!({"id": format!("selection-{index}"), "intakeSource": "drop"}))
                .unwrap();
        }
        assert_eq!(queue.pending().unwrap().len(), 8);
        assert!(queue.push(json!({"id": "overflow"})).is_err());
        queue.acknowledge("selection-0").unwrap();
        let pending = queue.pending().unwrap();
        assert_eq!(pending.len(), 7);
        assert_eq!(pending[0]["id"], "selection-1");
        assert_eq!(pending[6]["id"], "selection-7");
        queue.acknowledge("already-removed").unwrap();
        assert_eq!(queue.pending().unwrap(), pending);
    }

    #[test]
    fn drop_and_finder_open_with_share_the_pending_startup_queue() {
        let queue = FileIntakeQueue::default();
        queue
            .push_with_source(json!({"id": "drop-1"}), "drop")
            .unwrap();
        queue
            .push_with_source(json!({"id": "finder-1"}), "open_with")
            .unwrap();

        let pending = queue.pending().unwrap();
        assert_eq!(pending.len(), 2);
        assert_eq!(pending[0]["intakeSource"], "drop");
        assert_eq!(pending[1]["intakeSource"], "open_with");
        queue.acknowledge("drop-1").unwrap();
        assert_eq!(queue.pending().unwrap(), vec![pending[1].clone()]);
    }

    fn trash_item(id: &str, name: &str, folder: &str) -> TrashRestoreItem {
        TrashRestoreItem {
            id: id.into(),
            name: name.into(),
            folder: folder.into(),
        }
    }

    #[test]
    fn trash_ids_must_be_canonical_lowercase_uuids() {
        assert!(canonical_uuid(ID_A));
        assert!(!canonical_uuid(&ID_A.to_uppercase()));
        assert!(!canonical_uuid(&format!("{{{ID_A}}}")));
        assert!(!canonical_uuid(&ID_A.replacen('-', "", 1)));
        assert!(!canonical_uuid("../x"));
        assert!(!canonical_uuid(""));
        assert!(validate_record_ids(&[ID_A]).is_ok());
        assert!(validate_record_ids(&["../x"]).is_err());
    }

    #[test]
    fn trash_item_count_is_bounded_and_ids_are_unique() {
        assert!(validate_record_ids(&[]).is_err());
        let many: Vec<String> = (0..101).map(|_| uuid::Uuid::new_v4().to_string()).collect();
        let refs: Vec<&str> = many.iter().map(String::as_str).collect();
        assert!(validate_record_ids(&refs[..101]).is_err());
        assert!(validate_record_ids(&refs[..100]).is_ok());
        assert!(validate_record_ids(&[ID_A, ID_A]).is_err());
    }

    #[test]
    fn trash_restore_items_validate_names_and_folders() {
        let ok = vec![trash_item(ID_A, "a.txt", "/Users/me/Documents")];
        assert!(validate_restore_items(&ok).is_ok());
        assert!(validate_restore_items(&[trash_item(ID_A, "", "/x")]).is_err());
        assert!(validate_restore_items(&[trash_item(ID_A, "a\0b", "/x")]).is_err());
        assert!(validate_restore_items(&[trash_item(ID_A, &"n".repeat(256), "/x")]).is_err());
        assert!(validate_restore_items(&[trash_item(ID_A, &"n".repeat(255), "/x")]).is_ok());
        assert!(validate_restore_items(&[trash_item(ID_A, "a", "")]).is_err());
        assert!(validate_restore_items(&[trash_item(ID_A, "a", &"f".repeat(4097))]).is_err());
    }

    #[test]
    fn trash_destination_needs_exactly_one_item() {
        assert!(validate_destination(None, 3).is_ok());
        assert!(validate_destination(Some(GRANT), 1).is_ok());
        assert_eq!(
            validate_destination(Some(GRANT), 2),
            Err("Choose one item to restore to a folder".into())
        );
        assert!(validate_destination(Some("not-a-grant"), 1).is_err());
    }

    #[test]
    fn restore_dialog_names_the_folder_the_user_chose() {
        let message = restore_dialog_message(&[restore_line("notes.txt", "/Users/demo/Desktop")]);
        assert!(message.contains("notes.txt → /Users/demo/Desktop"));
        assert!(!message.contains("Chosen folder"));
    }

    #[test]
    fn trash_dialog_titles_follow_the_item_count() {
        assert_eq!(restore_dialog_title(1), "Restore 1 item?");
        assert_eq!(restore_dialog_title(3), "Restore 3 items?");
        assert_eq!(
            forget_dialog_title("report.pdf"),
            "Forget \u{201C}report.pdf\u{201D}?"
        );
    }

    #[test]
    fn trash_dialog_lists_at_most_twenty_items() {
        let lines: Vec<String> = (0..20)
            .map(|i| restore_line(&format!("f{i}"), "/d"))
            .collect();
        let message = restore_dialog_message(&lines);
        assert!(message.starts_with(TRASH_RESTORE_INTRO));
        assert_eq!(message.lines().count(), 21);
        assert!(!message.contains("more."));
        assert!(message.contains("f0 → /d"));

        let lines: Vec<String> = (0..21)
            .map(|i| restore_line(&format!("f{i}"), "/d"))
            .collect();
        let message = restore_dialog_message(&lines);
        assert_eq!(message.lines().count(), 22);
        assert!(message.ends_with("\nand 1 more."));
        assert!(!message.contains("f20 →"));
    }

    #[test]
    fn trash_request_bodies_have_the_contract_shape() {
        assert_eq!(
            restore_apply_body(&[ID_A], GRANT).to_string(),
            format!(r#"{{"recordIds":["{ID_A}"],"restoreGrantId":"{GRANT}"}}"#)
        );
        // serde_json keeps object keys sorted here, so the grant body serializes alphabetically.
        assert_eq!(
            restore_grant_body(&[ID_A, ID_B], None).to_string(),
            format!(r#"{{"destinationGrantId":null,"recordIds":["{ID_A}","{ID_B}"]}}"#)
        );
        assert_eq!(
            restore_grant_body(&[ID_A], Some(GRANT)),
            json!({"recordIds": [ID_A], "destinationGrantId": GRANT})
        );
    }

    #[test]
    fn trash_reveal_path_must_be_an_absolute_real_entry() {
        assert!(validate_reveal_path("relative/file.txt").is_err());
        assert!(validate_reveal_path("/tmp/with\0nul").is_err());
        let long = format!("/{}", "a".repeat(MAX_TRASH_PATH_BYTES));
        assert!(validate_reveal_path(&long).is_err());

        let dir =
            std::env::temp_dir().join(format!("officekit-trash-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("restored.txt");
        std::fs::write(&file, b"restored").unwrap();
        assert!(validate_reveal_path(file.to_str().unwrap()).is_ok());
        #[cfg(unix)]
        {
            let link = dir.join("link.txt");
            std::os::unix::fs::symlink(&file, &link).unwrap();
            assert!(validate_reveal_path(link.to_str().unwrap()).is_err());
        }
        std::fs::remove_dir_all(&dir).unwrap();
        assert!(validate_reveal_path(file.to_str().unwrap()).is_err());
    }

    #[test]
    fn drawer_storage_event_asks_the_web_layer_to_open_the_storage_analyser() {
        assert_eq!(
            drawer_storage_event(),
            json!({"action":"drawer-open","tool":"storage"})
        );
    }

    #[test]
    fn drawer_network_check_event_asks_the_web_layer_to_run_the_check() {
        assert_eq!(
            drawer_network_check_event(),
            json!({"action":"network-check"})
        );
    }

    #[test]
    fn drawer_quit_events_keep_confirmation_and_cancellation_in_the_native_drawer() {
        assert_eq!(
            drawer_quit_event(421),
            json!({"action":"drawer-quit","pid":421})
        );
        assert_eq!(
            drawer_quit_cancel_event(421),
            json!({"action":"drawer-quit-cancel","pid":421})
        );
    }

    #[test]
    fn menu_drawers_payload_accepts_only_a_bounded_drawers_list() {
        assert!(menu_drawers_payload_is_valid(r#"{"drawers":[]}"#));
        assert!(menu_drawers_payload_is_valid(
            r#"{"drawers":[{"id":"cpu","bar":"CPU 4%"}]}"#
        ));
        assert!(!menu_drawers_payload_is_valid("not json"));
        assert!(!menu_drawers_payload_is_valid(r#"{"drawers":1}"#));
        assert!(!menu_drawers_payload_is_valid(r#"{"other":[]}"#));
        assert!(!menu_drawers_payload_is_valid(r#"[]"#));
        let oversized = format!(
            r#"{{"drawers":[],"pad":"{}"}}"#,
            "x".repeat(MAX_MENU_DRAWERS_BYTES)
        );
        assert!(!menu_drawers_payload_is_valid(&oversized));
    }

    #[test]
    fn media_clipboard_shortcut_is_control_shift_c() {
        let shortcut = media_clipboard_shortcut();
        assert_eq!(shortcut.key, tauri_plugin_global_shortcut::Code::KeyC);
        assert!(shortcut
            .mods
            .contains(tauri_plugin_global_shortcut::Modifiers::CONTROL));
        assert!(shortcut
            .mods
            .contains(tauri_plugin_global_shortcut::Modifiers::SHIFT));
    }

    #[test]
    fn media_handoff_encodes_url_query_paths_without_shell_interpolation() {
        assert_eq!(
            encode_url_query_value("/tmp/a file;echo.webp"),
            "%2Ftmp%2Fa%20file%3Becho.webp"
        );
        assert_eq!(
            encode_url_query_value("/tmp/é.webp"),
            "%2Ftmp%2F%C3%A9.webp"
        );
        assert_eq!(MAX_MEDIA_HANDOFF_BYTES, 64 * 1024 * 1024);
    }

    #[test]
    fn media_handoff_accepts_only_fixed_destinations_and_single_safe_shortcut_name() {
        let path = std::path::Path::new("/tmp/prepared copy.png");
        let dropshare = media_handoff_command("dropshare", path, None).unwrap();
        assert_eq!(dropshare.get_program(), "/usr/bin/open");
        assert_eq!(
            dropshare
                .get_args()
                .map(|argument| argument.to_string_lossy().into_owned())
                .collect::<Vec<_>>(),
            [
                "-u",
                "dropshare5:///action/upload?file=%2Ftmp%2Fprepared%20copy.png"
            ]
        );
        let dockside = media_handoff_command("dockside", path, None).unwrap();
        assert_eq!(
            dockside
                .get_args()
                .map(|argument| argument.to_string_lossy().into_owned())
                .collect::<Vec<_>>(),
            [
                "-u",
                "dockside://action/add?file=%2Ftmp%2Fprepared%20copy.png"
            ]
        );
        for destination in ["yoink", "dropover", "atoll"] {
            let command = media_handoff_command(destination, path, None).unwrap();
            assert_eq!(command.get_program(), "/usr/bin/open");
            let app_name = match destination {
                "yoink" => "Yoink",
                "dropover" => "Dropover",
                _ => "Atoll",
            };
            assert_eq!(
                command
                    .get_args()
                    .map(|argument| argument.to_string_lossy().into_owned())
                    .collect::<Vec<_>>(),
                ["-a", app_name, "--", "/tmp/prepared copy.png"]
            );
        }
        let shortcut = media_handoff_command("shortcut", path, Some("Send to Notes")).unwrap();
        assert_eq!(shortcut.get_program(), "/usr/bin/shortcuts");
        assert_eq!(
            shortcut
                .get_args()
                .map(|argument| argument.to_string_lossy().into_owned())
                .collect::<Vec<_>>(),
            [
                "run",
                "Send to Notes",
                "--input-path",
                "/tmp/prepared copy.png"
            ]
        );
        assert!(media_handoff_command("shortcut", path, Some("  ")).is_err());
        assert!(media_handoff_command("shortcut", path, Some("Send\nto Notes")).is_err());
        assert!(media_handoff_command("shell", path, Some("rm -rf /tmp")).is_err());
    }

    #[test]
    fn media_handoff_shortcut_listing_is_utf8_bounded_and_filters_unsafe_names() {
        let mut lines = (0..105)
            .map(|index| format!("Shortcut {index}\n"))
            .collect::<String>();
        lines.push_str("Bad\u{0007}Name\n");
        let names = parse_media_shortcut_names(lines.as_bytes()).unwrap();
        assert_eq!(names.len(), MAX_MEDIA_SHORTCUT_NAMES);
        assert_eq!(names.first().map(String::as_str), Some("Shortcut 0"));
        assert_eq!(names.last().map(String::as_str), Some("Shortcut 99"));
        assert!(
            parse_media_shortcut_names(&vec![b'x'; MAX_MEDIA_SHORTCUT_LIST_BYTES + 1]).is_err()
        );
        assert!(parse_media_shortcut_names(&[0xff]).is_err());
    }

    #[test]
    fn media_handoff_artifact_fetch_does_not_follow_redirects() {
        let redirect_target = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        redirect_target.set_nonblocking(true).unwrap();
        let redirect_target_address = redirect_target.local_addr().unwrap();
        let target_thread = std::thread::spawn(move || {
            let deadline = std::time::Instant::now() + std::time::Duration::from_millis(300);
            loop {
                match redirect_target.accept() {
                    Ok(_) => return true,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        if std::time::Instant::now() >= deadline {
                            return false;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(10));
                    }
                    Err(_) => return false,
                }
            }
        });
        let redirect_source = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let source_address = redirect_source.local_addr().unwrap();
        let source_thread = std::thread::spawn(move || {
            let (mut stream, _) = redirect_source.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(1)))
                .unwrap();
            let mut request = [0u8; 2048];
            let _ = std::io::Read::read(&mut stream, &mut request);
            write!(
                stream,
                "HTTP/1.1 302 Found\r\nLocation: http://{redirect_target_address}/capture\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            .unwrap();
        });

        let result =
            fetch_media_handoff_artifact(source_address, uuid::Uuid::new_v4(), "test-token");
        source_thread.join().unwrap();
        assert!(result.is_err());
        assert!(!target_thread.join().unwrap());
    }

    #[test]
    fn media_handoff_artifact_fetch_obeys_its_total_timeout() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server_thread = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(1)))
                .unwrap();
            let mut request = [0u8; 2048];
            let _ = std::io::Read::read(&mut stream, &mut request);
            std::thread::sleep(std::time::Duration::from_millis(350));
            let _ = write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nimage"
            );
        });
        let started = std::time::Instant::now();
        let result = fetch_media_handoff_artifact_with_timeout(
            address,
            uuid::Uuid::new_v4(),
            "test-token",
            std::time::Duration::from_millis(100),
        );
        server_thread.join().unwrap();
        assert!(result.is_err());
        assert!(started.elapsed() < std::time::Duration::from_secs(2));
    }

    #[test]
    fn finder_quick_action_path_is_fixed_under_the_user_services_folder() {
        let home = std::path::Path::new("/tmp/officekit-home");
        assert_eq!(
            media_finder_workflow_path(home),
            home.join("Library/Services/OfficeKit Optimize Image.workflow")
        );
    }

    #[test]
    fn finder_quick_action_ownership_requires_a_regular_marker_file() {
        let root =
            std::env::temp_dir().join(format!("officekit-finder-test-{}", uuid::Uuid::new_v4()));
        let workflow = root.join(MEDIA_FINDER_WORKFLOW);
        let contents = workflow.join("Contents");
        std::fs::create_dir_all(&contents).unwrap();
        assert!(!media_finder_workflow_is_owned(&workflow));
        std::fs::write(contents.join("Info.plist"), MEDIA_FINDER_MARKER).unwrap();
        assert!(media_finder_workflow_is_owned(&workflow));
        let resource = root.join("resource.workflow");
        let resource_contents = resource.join("Contents");
        std::fs::create_dir_all(&resource_contents).unwrap();
        std::fs::write(resource_contents.join("Info.plist"), MEDIA_FINDER_MARKER).unwrap();
        std::fs::write(resource_contents.join("document.wflow"), "workflow").unwrap();
        std::fs::write(contents.join("document.wflow"), "workflow").unwrap();
        assert!(media_finder_workflow_matches(&workflow, &resource));
        std::fs::write(contents.join("document.wflow"), "modified workflow").unwrap();
        assert!(!media_finder_workflow_matches(&workflow, &resource));
        std::fs::remove_file(contents.join("Info.plist")).unwrap();
        std::fs::remove_file(contents.join("document.wflow")).unwrap();
        std::fs::create_dir(contents.join("Info.plist")).unwrap();
        assert!(!media_finder_workflow_is_owned(&workflow));
        std::fs::remove_dir_all(root).unwrap();
    }

    fn finder_fixture() -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "officekit-finder-lifecycle-{}",
            uuid::Uuid::new_v4()
        ));
        let home = root.join("home");
        let resource = root.join("bundled").join(MEDIA_FINDER_WORKFLOW);
        let resource_contents = resource.join("Contents");
        std::fs::create_dir_all(&resource_contents).unwrap();
        std::fs::write(
            resource_contents.join("Info.plist"),
            format!("<plist>{MEDIA_FINDER_MARKER}</plist>"),
        )
        .unwrap();
        std::fs::write(
            resource_contents.join("document.wflow"),
            "approved workflow",
        )
        .unwrap();
        (root, home, resource)
    }

    #[test]
    fn finder_quick_action_lifecycle_installs_idempotently_and_removes_exact_bundle() {
        let (root, home, resource) = finder_fixture();
        assert_eq!(
            media_finder_action_install_at(&home, &resource).unwrap(),
            "installed"
        );
        let installed = media_finder_workflow_path(&home);
        assert!(media_finder_workflow_matches(&installed, &resource));
        assert_eq!(
            media_finder_action_install_at(&home, &resource).unwrap(),
            "installed"
        );
        assert_eq!(
            media_finder_action_remove_at(&home, &resource).unwrap(),
            "not-installed"
        );
        assert!(!installed.exists());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn open_in_officekit_quick_action_installs_from_the_real_bundle_and_never_touches_the_image_action(
    ) {
        let resource = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("resources")
            .join(OPEN_IN_FINDER_WORKFLOW);
        assert!(finder_workflow_is_owned(&resource, &OPEN_IN_FINDER));
        assert!(!finder_workflow_is_owned(&resource, &MEDIA_FINDER));
        let root = std::env::temp_dir().join(format!("officekit-open-in-{}", uuid::Uuid::new_v4()));
        let home = root.join("home");
        assert_eq!(
            finder_action_install_at(&home, &resource, &OPEN_IN_FINDER).unwrap(),
            "installed"
        );
        let installed = finder_workflow_path(&home, &OPEN_IN_FINDER);
        assert_eq!(
            installed,
            home.join("Library/Services/Open in OfficeKit.workflow")
        );
        assert!(finder_workflow_matches(
            &installed,
            &resource,
            &OPEN_IN_FINDER
        ));
        assert!(!media_finder_workflow_path(&home).exists());
        assert_eq!(
            finder_action_install_at(&home, &resource, &OPEN_IN_FINDER).unwrap(),
            "installed"
        );
        assert_eq!(
            finder_action_remove_at(&home, &resource, &OPEN_IN_FINDER).unwrap(),
            "not-installed"
        );
        assert!(!installed.exists());
        assert_eq!(
            finder_action_remove_at(&home, &resource, &OPEN_IN_FINDER).unwrap(),
            "not-installed"
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn open_in_officekit_quick_action_script_sends_at_most_thirty_regular_files_to_the_app() {
        let wflow = std::fs::read_to_string(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("resources")
                .join(OPEN_IN_FINDER_WORKFLOW)
                .join("Contents/document.wflow"),
        )
        .unwrap();
        assert!(wflow.contains("$# &gt; 30"));
        assert!(wflow.contains("! -L \"$file\""));
        assert!(wflow.contains("/usr/bin/open -a \"$app_path\" \"${files[@]}\""));
    }

    #[test]
    fn finder_quick_action_lifecycle_refuses_collision_and_modified_removal() {
        let (root, home, resource) = finder_fixture();
        let installed = media_finder_workflow_path(&home);
        std::fs::create_dir_all(&installed).unwrap();
        std::fs::write(&installed.join("keep.txt"), "user data").unwrap();
        assert!(media_finder_action_install_at(&home, &resource).is_err());
        assert_eq!(
            std::fs::read_to_string(installed.join("keep.txt")).unwrap(),
            "user data"
        );
        std::fs::remove_dir_all(&installed).unwrap();
        media_finder_action_install_at(&home, &resource).unwrap();
        std::fs::write(
            installed.join("Contents/document.wflow"),
            "user modified data",
        )
        .unwrap();
        assert!(media_finder_action_remove_at(&home, &resource).is_err());
        assert!(installed.exists());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn finder_quick_action_contents_match_rejects_non_utf8_names() {
        use std::os::unix::ffi::OsStrExt;
        let names = vec![
            std::ffi::OsString::from("Info.plist"),
            std::ffi::OsString::from("document.wflow"),
            std::ffi::OsStr::from_bytes(b"extra-\xff").to_os_string(),
        ];
        assert!(!media_finder_contents_match(&names));
    }

    #[test]
    fn finder_reveal_accepts_only_canonical_scan_ids() {
        let id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        assert!(validate_reveal_ids(id, id).is_ok());
        for invalid in [
            "",
            "../../file-selections",
            "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
            "not-a-uuid",
        ] {
            assert!(validate_reveal_ids(invalid, id).is_err());
            assert!(validate_reveal_ids(id, invalid).is_err());
        }
    }

    #[test]
    fn media_drop_accepts_only_distinct_regular_files_within_the_batch_limit() {
        let directory =
            std::env::temp_dir().join(format!("officekit-drop-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&directory).unwrap();
        let file = directory.join("image.png");
        std::fs::write(&file, b"fixture").unwrap();
        let canonical = file.canonicalize().unwrap();
        assert_eq!(
            validate_dropped_files(vec![file.clone()]).unwrap(),
            vec![canonical]
        );
        assert!(validate_dropped_files(Vec::new()).is_err());
        assert!(validate_dropped_files(vec![file.clone(), file.clone()]).is_err());
        assert!(validate_dropped_files(vec![directory.clone()]).is_err());
        assert!(validate_dropped_files(vec![file.clone(); MAX_MEDIA_AUDIO_SELECTION + 1]).is_err());
        #[cfg(unix)]
        {
            let link = directory.join("image-link.png");
            std::os::unix::fs::symlink(&file, &link).unwrap();
            assert!(validate_dropped_files(vec![link]).is_err());
        }
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn media_drop_is_enabled_only_inside_the_visible_drop_target() {
        let state = MediaDropEnabled::default();
        assert_eq!(state.target_at(50.0, 40.0), None);
        state.set(true, Some([10.0, 20.0, 100.0, 50.0]), Vec::new());
        assert_eq!(state.target_at(10.0, 20.0), Some("manual".into()));
        assert_eq!(state.target_at(110.0, 70.0), Some("manual".into()));
        assert_eq!(state.target_at(111.0, 70.0), None);
        assert_eq!(state.target_at(50.0, 71.0), None);
        state.set(false, Some([10.0, 20.0, 100.0, 50.0]), Vec::new());
        assert_eq!(state.target_at(50.0, 40.0), None);
    }

    #[test]
    fn media_drop_routes_only_inside_registered_enabled_zone_bounds() {
        let state = MediaDropEnabled::default();
        let zone_id = "99999999-9999-4999-8999-999999999999".to_string();
        let target = MediaDropTarget {
            id: zone_id.clone(),
            x: 20.0,
            y: 30.0,
            width: 80.0,
            height: 40.0,
        };
        state.set(true, None, vec![target]);
        assert_eq!(state.target_at(40.0, 50.0), Some(zone_id));
        assert_eq!(state.target_at(101.0, 50.0), None);
        state.set(false, None, vec![]);
        assert_eq!(state.target_at(40.0, 50.0), None);
    }

    #[test]
    fn media_audio_filter_accepts_only_supported_audio_files() {
        use std::path::PathBuf;
        let valid = vec![PathBuf::from("meeting.M4A"), PathBuf::from("voice.wav")];
        assert!(validate_selection_filter(&valid, Some("audio")).is_ok());
        let too_many = vec![PathBuf::from("voice.wav"); 31];
        assert!(validate_selection_filter(&too_many, Some("audio")).is_err());
        assert!(validate_selection_filter(&[PathBuf::from("meeting.mp4")], Some("audio")).is_err());
        assert!(validate_selection_filter(&[PathBuf::from("folder")], Some("audio")).is_err());
        assert!(validate_selection_filter(&valid, Some("anything")).is_err());
        assert!(validate_selection_filter(&valid, None).is_ok());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn finder_reveal_passes_one_literal_absolute_path_without_a_shell() {
        let path = "/tmp/filename with spaces;$(echo example).txt";
        let command = finder_command(path).unwrap();
        assert_eq!(command.get_program(), "/usr/bin/open");
        assert_eq!(command.get_args().collect::<Vec<_>>(), vec!["-R", path]);
        assert!(finder_command("relative/path").is_err());
    }
    #[test]
    fn storage_native_requests_are_bounded_and_cannot_retarget_routes() {
        assert_eq!(storage_scan_body(1).unwrap(), json!({"olderThanDays":1}));
        assert_eq!(
            storage_scan_body(3650).unwrap(),
            json!({"olderThanDays":3650})
        );
        assert!(storage_scan_body(0).is_err());
        assert!(storage_scan_body(3651).is_err());
        let id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        assert_eq!(
            storage_plan_route(id).unwrap(),
            format!("storage-cleanup-plans/{id}/execution")
        );
        for invalid in [
            "",
            "../../file-selections",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/execution",
            "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        ] {
            assert!(storage_plan_route(invalid).is_err());
        }
    }
    #[test]
    fn output_names_cannot_retarget_native_picker() {
        for name in [
            "",
            ".",
            "..",
            "../secret",
            "folder/file",
            "folder\\file",
            "a\0b",
            "disk:name",
        ] {
            assert!(validate_name(name).is_err());
        }
        assert!(validate_name("report.csv").is_ok());
        assert!(validate_name("Résumé.txt").is_ok());
        assert!(validate_name(&"a".repeat(256)).is_err());
    }

    #[test]
    fn native_save_restores_suggested_extension_when_picker_omits_it() {
        let directory = std::path::Path::new("/selected");
        assert_eq!(
            ensure_suggested_extension(directory.join("masked-copy"), "report-masked.pdf"),
            directory.join("masked-copy.pdf")
        );
        assert_eq!(
            ensure_suggested_extension(directory.join("masked-copy.txt"), "report-masked.pdf"),
            directory.join("masked-copy.txt")
        );
        assert_eq!(
            ensure_suggested_extension(directory.join("masked-copy"), "report-masked"),
            directory.join("masked-copy")
        );
    }

    #[test]
    fn directory_output_uses_a_new_child_without_authorizing_parent_contents() {
        let parent = std::path::Path::new("/selected-parent");
        assert_eq!(
            planned_directory(parent, None).unwrap(),
            parent.join("extracted-files")
        );
        assert_eq!(
            planned_directory(parent, Some("split-parts")).unwrap(),
            parent.join("split-parts")
        );
        assert!(planned_directory(parent, Some("../outside")).is_err());
        assert!(planned_directory(parent, Some("/absolute")).is_err());
        let actual =
            std::env::temp_dir().join(format!("officekit-output-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(actual.join("extracted-files")).unwrap();
        assert!(planned_directory(&actual, None).is_err());
        std::fs::remove_dir_all(actual).unwrap();
    }

    #[test]
    fn save_publishes_complete_bytes_and_leaves_no_partial_files() {
        let dir =
            std::env::temp_dir().join(format!("officekit-save-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&dir).unwrap();
        let path = dir.join("result.txt");
        publish_result(&path, b"complete Unicode \xc3\xa9").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"complete Unicode \xc3\xa9");
        assert!(publish_result(&path, b"replacement").is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"complete Unicode \xc3\xa9");
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 1);
        let missing = dir.join("missing/result.txt");
        assert!(publish_result(&missing, b"must not publish").is_err());
        assert!(!missing.exists());
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 1);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn exclusive_publication_never_replaces_a_destination_created_during_write() {
        let dir =
            std::env::temp_dir().join(format!("officekit-publish-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&dir).unwrap();
        let source = dir.join("complete.tmp");
        let destination = dir.join("new-result.txt");
        std::fs::write(&source, b"new result").unwrap();
        std::fs::write(&destination, b"concurrent user file").unwrap();
        assert!(publish_new(&source, &destination).is_err());
        assert_eq!(
            std::fs::read(&destination).unwrap(),
            b"concurrent user file"
        );
        std::fs::remove_file(&destination).unwrap();
        publish_new(&source, &destination).unwrap();
        assert_eq!(std::fs::read(&destination).unwrap(), b"new result");
        assert!(!source.exists());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
