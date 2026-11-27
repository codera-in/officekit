//! Global desktop layer: shortcut settings, persistence and native registration shared by
//! clipboard history, snippets and the window manager.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;
use std::sync::{Mutex, OnceLock};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};

use crate::dictation::validate_global_shortcut;
use crate::window_manager::{self, WindowOptions};

pub const ACTION_CLIPBOARD_HISTORY: &str = "clipboard.history";
pub const ACTION_SNIPPETS_PANEL: &str = "snippets.panel";
pub const ACTION_LAUNCHER: &str = "launcher.open";

const MAX_WINDOW_GAP: u32 = 64;
const MAX_SKIP_APPS: usize = 64;
const MAX_BUNDLE_ID_CHARS: usize = 200;
const MIN_QUICK_PASSWORD_LENGTH: u8 = 8;
const MAX_QUICK_PASSWORD_LENGTH: u8 = 128;
const DEFAULT_QUICK_PASSWORD_SYMBOLS: &str = "!@#$%&*?-_+=";

/// Every action that can own a global shortcut: the two clipboard panels, then each window
/// layout. A native hotkey id is the index in this list.
pub fn known_actions() -> &'static [String] {
    static ACTIONS: OnceLock<Vec<String>> = OnceLock::new();
    ACTIONS.get_or_init(|| {
        let mut actions = vec![
            ACTION_CLIPBOARD_HISTORY.to_string(),
            ACTION_SNIPPETS_PANEL.to_string(),
            ACTION_LAUNCHER.to_string(),
        ];
        actions.extend(
            window_manager::LAYOUTS
                .iter()
                .map(|layout| window_manager::action_name(layout)),
        );
        actions
    })
}

fn is_window_action(action: &str) -> bool {
    action.starts_with(window_manager::ACTION_PREFIX)
}

const MAX_SETTINGS_BYTES: u64 = 64 * 1024;
const SETTINGS_FILE: &str = "global-desktop.json";
const KEY_CODE_V: u16 = 9;
const KEY_CODE_SPACE: u16 = 49;
const MODIFIERS_CONTROL_OPTION: u8 = 0b0011;
const KEY_CODE_S: u16 = 1;
const MODIFIERS_COMMAND_OPTION: u8 = 0b1010;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShortcutSetting {
    pub key_code: u16,
    pub modifier_mask: u8,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct GlobalDesktopSettings {
    /// Clipboard history and snippets shortcuts.
    pub enabled: bool,
    pub open_at_login: bool,
    /// Window layout shortcuts act on other apps' windows.
    pub windows_enabled: bool,
    /// Dragging a window to a screen edge snaps it.
    pub edge_drag: bool,
    /// Pixels between tiled windows and screen edges.
    pub window_gap: u32,
    /// Bundle ids the window manager leaves alone.
    pub window_skip_apps: Vec<String>,
    pub shortcuts: BTreeMap<String, ShortcutSetting>,
    /// Keys that switch the launcher's filter while its panel is open; not global hotkeys.
    pub launcher_filters: BTreeMap<String, ShortcutSetting>,
    /// Off releases the launcher shortcut so another app can use it.
    pub launcher_enabled: bool,
    /// Off releases the snippets panel shortcut so another app can use it.
    pub snippets_enabled: bool,
    /// Installed apps and Finder commands listed in the launcher.
    pub launcher_show_apps: bool,
    /// OfficeKit tools listed in the launcher.
    pub launcher_show_tools: bool,
    /// Snippets listed in the launcher.
    pub launcher_show_snippets: bool,
    /// Sums and percentages typed into the launcher (the calculation row).
    pub quick_calculator: bool,
    /// UUID rows typed as "uuid" or "guid".
    pub quick_uuid: bool,
    /// Password rows typed as "pw" or "password", with an optional length.
    pub quick_password: bool,
    /// Default password length when the launcher query has no explicit length.
    pub quick_password_length: u8,
    /// Allowed ASCII punctuation in launcher-generated passwords; empty disables symbols.
    pub quick_password_symbols: String,
}

/// Launcher filter names, in the order the panel shows them.
pub const LAUNCHER_FILTERS: [&str; 4] = ["all", "app", "tool", "snippet"];

/// macOS key codes for digits 1 to 9 and 0, P and Delete: panel keys when paired with Command alone.
const PANEL_COMMAND_KEYS: [u16; 12] = [18, 19, 20, 21, 23, 22, 26, 28, 25, 29, 35, 51];
const MODIFIER_COMMAND: u8 = 0b1000;

pub fn default_launcher_filters() -> BTreeMap<String, ShortcutSetting> {
    // Control-1 to Control-4; Command-1 to Command-9 already pick rows.
    LAUNCHER_FILTERS
        .iter()
        .zip([18_u16, 19, 20, 21])
        .map(|(name, key_code)| {
            (
                (*name).to_string(),
                ShortcutSetting {
                    key_code,
                    modifier_mask: 0b0001,
                },
            )
        })
        .collect()
}

pub fn default_shortcuts() -> BTreeMap<String, ShortcutSetting> {
    let mut shortcuts = BTreeMap::from([
        (
            ACTION_CLIPBOARD_HISTORY.to_string(),
            ShortcutSetting {
                key_code: KEY_CODE_V,
                modifier_mask: MODIFIERS_COMMAND_OPTION,
            },
        ),
        (
            ACTION_SNIPPETS_PANEL.to_string(),
            ShortcutSetting {
                key_code: KEY_CODE_S,
                modifier_mask: MODIFIERS_COMMAND_OPTION,
            },
        ),
        (
            ACTION_LAUNCHER.to_string(),
            ShortcutSetting {
                key_code: KEY_CODE_SPACE,
                modifier_mask: MODIFIERS_CONTROL_OPTION,
            },
        ),
    ]);
    for (layout, key_code, modifier_mask) in window_manager::DEFAULT_SHORTCUTS {
        shortcuts.insert(
            window_manager::action_name(layout),
            ShortcutSetting {
                key_code: *key_code,
                modifier_mask: *modifier_mask,
            },
        );
    }
    shortcuts
}

impl Default for GlobalDesktopSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            open_at_login: false,
            windows_enabled: false,
            edge_drag: false,
            window_gap: 0,
            window_skip_apps: Vec::new(),
            shortcuts: default_shortcuts(),
            launcher_filters: default_launcher_filters(),
            launcher_enabled: true,
            snippets_enabled: true,
            launcher_show_apps: true,
            launcher_show_tools: true,
            launcher_show_snippets: true,
            quick_calculator: true,
            quick_uuid: true,
            quick_password: true,
            quick_password_length: 20,
            quick_password_symbols: DEFAULT_QUICK_PASSWORD_SYMBOLS.to_string(),
        }
    }
}

fn valid_bundle_id(id: &str) -> bool {
    !id.is_empty()
        && id.chars().count() <= MAX_BUNDLE_ID_CHARS
        && id.starts_with(|c: char| c.is_ascii_alphanumeric())
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
}

/// Which result kinds the launcher lists and which quick-result rows it may compute.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LauncherOptions {
    pub apps: bool,
    pub tools: bool,
    pub snippets: bool,
    pub calculator: bool,
    pub uuid: bool,
    pub password: bool,
    pub password_length: u8,
    pub password_symbols: String,
}

impl Default for LauncherOptions {
    fn default() -> Self {
        Self {
            apps: true,
            tools: true,
            snippets: true,
            calculator: true,
            uuid: true,
            password: true,
            password_length: 20,
            password_symbols: DEFAULT_QUICK_PASSWORD_SYMBOLS.to_string(),
        }
    }
}

impl GlobalDesktopSettings {
    pub fn launcher_options(&self) -> LauncherOptions {
        LauncherOptions {
            apps: self.launcher_show_apps,
            tools: self.launcher_show_tools,
            snippets: self.launcher_show_snippets,
            calculator: self.quick_calculator,
            uuid: self.quick_uuid,
            password: self.quick_password,
            password_length: self.quick_password_length,
            password_symbols: self.quick_password_symbols.clone(),
        }
    }

    /// What the window manager needs at the moment a layout is applied.
    pub fn window_options(&self) -> WindowOptions {
        WindowOptions {
            gap: i64::from(self.window_gap),
            skip_apps: self.window_skip_apps.clone(),
        }
    }
}

/// Checks the launcher filter keys and fills any missing filter with its default.
fn validate_launcher_filters(settings: &mut GlobalDesktopSettings) -> Result<(), &'static str> {
    for (name, shortcut) in &settings.launcher_filters {
        if !LAUNCHER_FILTERS.contains(&name.as_str()) {
            return Err("Unknown launcher filter.");
        }
        if shortcut.key_code > 127 || shortcut.modifier_mask == 0 || shortcut.modifier_mask > 0b1111
        {
            return Err("A launcher filter shortcut needs a modifier key.");
        }
        if shortcut.modifier_mask == MODIFIER_COMMAND
            && PANEL_COMMAND_KEYS.contains(&shortcut.key_code)
        {
            return Err("That key is used by the launcher panel.");
        }
    }
    for (name, shortcut) in default_launcher_filters() {
        settings.launcher_filters.entry(name).or_insert(shortcut);
    }
    let mut seen = HashSet::new();
    for shortcut in settings.launcher_filters.values() {
        if !seen.insert((shortcut.key_code, shortcut.modifier_mask)) {
            return Err("Two launcher filters cannot share the same shortcut.");
        }
    }
    let global: HashSet<(u16, u8)> = settings
        .shortcuts
        .values()
        .map(|shortcut| (shortcut.key_code, shortcut.modifier_mask))
        .collect();
    if settings
        .launcher_filters
        .values()
        .any(|shortcut| global.contains(&(shortcut.key_code, shortcut.modifier_mask)))
    {
        return Err("That shortcut is already used by another OfficeKit action.");
    }
    Ok(())
}

/// Validates settings and fills any missing action with its default shortcut.
pub fn validate_settings(
    mut settings: GlobalDesktopSettings,
) -> Result<GlobalDesktopSettings, &'static str> {
    if !(MIN_QUICK_PASSWORD_LENGTH..=MAX_QUICK_PASSWORD_LENGTH)
        .contains(&settings.quick_password_length)
    {
        return Err("The launcher password length must be between 8 and 128.");
    }
    let mut symbols = HashSet::new();
    if settings.quick_password_symbols.len() > 32
        || !settings
            .quick_password_symbols
            .chars()
            .all(|character| character.is_ascii_punctuation() && symbols.insert(character))
    {
        return Err(
            "Use up to 32 unique ASCII punctuation characters for launcher password symbols.",
        );
    }
    if settings.window_gap > MAX_WINDOW_GAP {
        return Err("The window gap must be between 0 and 64 pixels.");
    }
    let mut skip_apps: Vec<String> = Vec::new();
    for id in &settings.window_skip_apps {
        let id = id.trim();
        if !valid_bundle_id(id) {
            return Err("Skipped apps must be app ids like com.apple.Safari.");
        }
        if !skip_apps.iter().any(|known| known.eq_ignore_ascii_case(id)) {
            skip_apps.push(id.to_string());
        }
    }
    if skip_apps.len() > MAX_SKIP_APPS {
        return Err("Skip at most 64 apps.");
    }
    settings.window_skip_apps = skip_apps;
    for (action, shortcut) in &settings.shortcuts {
        if !known_actions().contains(action) {
            return Err("Unknown shortcut action.");
        }
        // The launcher may take Command-Space from Spotlight; the user turns Spotlight's own shortcut off.
        let replaces_spotlight = action == ACTION_LAUNCHER
            && shortcut.key_code == KEY_CODE_SPACE
            && shortcut.modifier_mask == MODIFIER_COMMAND;
        if !replaces_spotlight {
            validate_global_shortcut(shortcut.key_code, shortcut.modifier_mask)?;
        }
    }
    // The two panels always keep a shortcut; a window layout may be left unassigned.
    for (action, shortcut) in default_shortcuts() {
        if !is_window_action(&action) {
            settings.shortcuts.entry(action).or_insert(shortcut);
        }
    }
    let mut seen = HashSet::new();
    for shortcut in settings.shortcuts.values() {
        if !seen.insert((shortcut.key_code, shortcut.modifier_mask)) {
            return Err("Two actions cannot share the same shortcut.");
        }
    }
    validate_launcher_filters(&mut settings)?;
    Ok(settings)
}

/// Reads saved settings; a missing, oversized, corrupt or invalid file yields the defaults.
pub fn load_settings(directory: &Path) -> GlobalDesktopSettings {
    let path = directory.join(SETTINGS_FILE);
    let Ok(metadata) = std::fs::metadata(&path) else {
        return GlobalDesktopSettings::default();
    };
    if !metadata.is_file() || metadata.len() > MAX_SETTINGS_BYTES {
        return GlobalDesktopSettings::default();
    }
    std::fs::read(&path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<GlobalDesktopSettings>(&bytes).ok())
        .and_then(|settings| validate_settings(settings).ok())
        .unwrap_or_default()
}

/// Writes settings atomically through a temporary file in the same directory.
pub fn save_settings(directory: &Path, settings: &GlobalDesktopSettings) -> Result<(), String> {
    std::fs::create_dir_all(directory)
        .map_err(|_| "Could not save desktop settings".to_string())?;
    let bytes = serde_json::to_vec_pretty(settings)
        .map_err(|_| "Could not save desktop settings".to_string())?;
    let temporary = directory.join(format!("{SETTINGS_FILE}.tmp"));
    std::fs::write(&temporary, bytes).map_err(|_| "Could not save desktop settings".to_string())?;
    std::fs::rename(&temporary, directory.join(SETTINGS_FILE))
        .map_err(|_| "Could not save desktop settings".to_string())
}

pub fn action_for_id(id: i32) -> Option<&'static str> {
    usize::try_from(id)
        .ok()
        .and_then(|index| known_actions().get(index))
        .map(String::as_str)
}

pub fn accessibility_label(code: i32) -> &'static str {
    if code == 0 {
        "trusted"
    } else {
        "needs-access"
    }
}

pub fn login_item_label(code: i32) -> &'static str {
    match code {
        0 => "off",
        1 => "on",
        2 => "needs-approval",
        _ => "unavailable",
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GlobalDesktopStatus {
    pub available: bool,
    pub accessibility: &'static str,
    pub login_item: &'static str,
    pub settings: GlobalDesktopSettings,
    pub registration_failures: Vec<String>,
}

#[derive(Default)]
struct GlobalDesktopState {
    settings: GlobalDesktopSettings,
    directory: Option<std::path::PathBuf>,
    registration_failures: Vec<String>,
}

#[derive(Default)]
pub struct GlobalDesktopRuntime(Mutex<GlobalDesktopState>);

#[cfg(target_os = "macos")]
mod native {
    use std::sync::{mpsc, Mutex, OnceLock};

    #[allow(dead_code)]
    unsafe extern "C" {
        fn officekit_global_hotkey_set_callback(callback: extern "C" fn(i32));
        fn officekit_global_hotkey_register(id: i32, key_code: i32, modifier_mask: i32) -> i32;
        fn officekit_global_hotkey_unregister_all();
        fn officekit_global_login_item_status() -> i32;
        fn officekit_global_login_item_set(enabled: i32) -> i32;
        fn officekit_global_panel_set_callback(callback: extern "C" fn(*const u8, u64, i32));
        fn officekit_global_panel_show(bytes: *const u8, length: u64) -> i32;
        fn officekit_global_panel_hide();
        fn officekit_global_panel_target_pid() -> i32;
        fn officekit_dictation_accessibility_status() -> i32;
    }

    static ACTION_SENDER: OnceLock<Mutex<mpsc::Sender<i32>>> = OnceLock::new();

    extern "C" fn on_hotkey(id: i32) {
        if let Some(sender) = ACTION_SENDER.get() {
            if let Ok(sender) = sender.lock() {
                let _ = sender.send(id);
            }
        }
    }

    /// Installs the native callback once and returns the receiver of fired hotkey ids.
    pub fn install_callback() -> Option<mpsc::Receiver<i32>> {
        let (sender, receiver) = mpsc::channel();
        ACTION_SENDER.set(Mutex::new(sender)).ok()?;
        unsafe { officekit_global_hotkey_set_callback(on_hotkey) };
        Some(receiver)
    }

    pub fn unregister_all() {
        unsafe { officekit_global_hotkey_unregister_all() };
    }

    /// Registers one shortcut; returns false when macOS refuses it.
    pub fn register(id: i32, key_code: u16, modifier_mask: u8) -> bool {
        unsafe {
            officekit_global_hotkey_register(id, i32::from(key_code), i32::from(modifier_mask)) == 0
        }
    }

    pub fn accessibility_code() -> i32 {
        unsafe { officekit_dictation_accessibility_status() }
    }

    pub fn login_item_code() -> i32 {
        unsafe { officekit_global_login_item_status() }
    }

    pub fn set_login_item(enabled: bool) -> i32 {
        unsafe { officekit_global_login_item_set(i32::from(enabled)) }
    }
}

#[cfg(not(target_os = "macos"))]
mod native {
    use std::sync::mpsc;

    pub fn install_callback() -> Option<mpsc::Receiver<i32>> {
        None
    }
    pub fn unregister_all() {}
    pub fn register(_id: i32, _key_code: u16, _modifier_mask: u8) -> bool {
        false
    }
    pub fn accessibility_code() -> i32 {
        2
    }
    pub fn login_item_code() -> i32 {
        3
    }
    pub fn set_login_item(_enabled: bool) -> i32 {
        3
    }
}

/// Registers hotkeys with the OS. The native implementation marshals onto the main thread, so
/// unit tests use a fake instead of calling into Swift from a test thread.
trait HotkeyRegistrar {
    fn unregister_all(&mut self);
    fn register(&mut self, id: i32, key_code: u16, modifier_mask: u8) -> bool;
}

struct NativeRegistrar;

impl HotkeyRegistrar for NativeRegistrar {
    fn unregister_all(&mut self) {
        native::unregister_all();
    }
    fn register(&mut self, id: i32, key_code: u16, modifier_mask: u8) -> bool {
        native::register(id, key_code, modifier_mask)
    }
}

/// Whether the part that owns a clipboard or launcher shortcut is switched on. Clipboard history
/// keeps its shortcut while the master switch is on: its panel still shows saved clips when capture
/// is off or paused.
fn part_enabled(settings: &GlobalDesktopSettings, action: &str) -> bool {
    match action {
        ACTION_LAUNCHER => settings.launcher_enabled,
        ACTION_SNIPPETS_PANEL => settings.snippets_enabled,
        _ => true,
    }
}

/// Re-registers every enabled shortcut and returns the actions the OS refused.
fn apply_with(
    registrar: &mut impl HotkeyRegistrar,
    settings: &GlobalDesktopSettings,
) -> Vec<String> {
    registrar.unregister_all();
    let mut failures = Vec::new();
    for (index, action) in known_actions().iter().enumerate() {
        let wanted = if is_window_action(action) {
            settings.windows_enabled
        } else {
            settings.enabled && part_enabled(settings, action)
        };
        if !wanted {
            continue;
        }
        if let Some(shortcut) = settings.shortcuts.get(action) {
            let id = i32::try_from(index).unwrap_or(i32::MAX);
            if !registrar.register(id, shortcut.key_code, shortcut.modifier_mask) {
                failures.push(action.clone());
            }
        }
    }
    failures
}

fn apply_registrations(settings: &GlobalDesktopSettings) -> Vec<String> {
    apply_with(&mut NativeRegistrar, settings)
}

fn status_for(state: &GlobalDesktopState) -> GlobalDesktopStatus {
    GlobalDesktopStatus {
        available: cfg!(target_os = "macos"),
        accessibility: accessibility_label(native::accessibility_code()),
        login_item: login_item_label(native::login_item_code()),
        settings: state.settings.clone(),
        registration_failures: state.registration_failures.clone(),
    }
}

/// Loads saved settings, registers shortcuts and starts forwarding fired actions to the webview.
pub fn restore_on_launch(app: &AppHandle) {
    let Some(runtime) = app.try_state::<GlobalDesktopRuntime>() else {
        return;
    };
    let directory = app.path().app_data_dir().ok();
    let settings = directory.as_deref().map(load_settings).unwrap_or_default();
    if let Ok(mut state) = runtime.0.lock() {
        state.registration_failures = apply_registrations(&settings);
        crate::window_runtime::configure(&settings);
        state.settings = settings;
        state.directory = directory;
    }
    if let Some(receiver) = native::install_callback() {
        let _ = std::thread::Builder::new()
            .name("officekit-global-desktop".into())
            .spawn(move || {
                while let Ok(id) = receiver.recv() {
                    match action_for_id(id) {
                        Some(action) if is_window_action(action) => {
                            crate::window_runtime::handle_action(action);
                        }
                        Some(action) => crate::global_clipboard::handle_action(action),
                        None => {}
                    }
                }
            });
    }
}

/// Whether the user switched the global desktop tools on.
pub fn desktop_enabled(app: &AppHandle) -> bool {
    app.try_state::<GlobalDesktopRuntime>()
        .and_then(|runtime| runtime.0.lock().ok().map(|state| state.settings.enabled))
        .unwrap_or(false)
}

/// The user's "Skip these apps" list. Clipboard capture and snippet typing honor it as well as window snapping.
pub fn skip_apps(app: &AppHandle) -> Vec<String> {
    app.try_state::<GlobalDesktopRuntime>()
        .and_then(|runtime| {
            runtime
                .0
                .lock()
                .ok()
                .map(|state| state.settings.window_skip_apps.clone())
        })
        .unwrap_or_default()
}

/// Whether the Window Manager switch is on.
pub fn windows_enabled(app: &AppHandle) -> bool {
    app.try_state::<GlobalDesktopRuntime>()
        .and_then(|runtime| {
            runtime
                .0
                .lock()
                .ok()
                .map(|state| state.settings.enabled && state.settings.windows_enabled)
        })
        .unwrap_or(false)
}

/// The launcher's filter keys as currently saved.
pub fn launcher_filters(app: &AppHandle) -> BTreeMap<String, ShortcutSetting> {
    app.try_state::<GlobalDesktopRuntime>()
        .and_then(|runtime| {
            runtime
                .0
                .lock()
                .ok()
                .map(|state| state.settings.launcher_filters.clone())
        })
        .unwrap_or_else(default_launcher_filters)
}

/// The launcher's result kinds and quick rows as currently saved.
pub fn launcher_options(app: &AppHandle) -> LauncherOptions {
    app.try_state::<GlobalDesktopRuntime>()
        .and_then(|runtime| {
            runtime
                .0
                .lock()
                .ok()
                .map(|state| state.settings.launcher_options())
        })
        .unwrap_or_default()
}

/// The shortcuts a reset restores.
#[tauri::command]
pub fn global_desktop_default_shortcuts() -> BTreeMap<String, ShortcutSetting> {
    default_shortcuts()
}

/// Re-reads capture settings and snippet keywords after the user changed them in the app.
#[tauri::command]
pub fn global_desktop_refresh() {
    crate::global_clipboard::request_refresh();
}

pub fn shutdown() {
    native::unregister_all();
}

#[tauri::command]
pub fn global_desktop_status(runtime: State<'_, GlobalDesktopRuntime>) -> GlobalDesktopStatus {
    match runtime.0.lock() {
        Ok(state) => status_for(&state),
        Err(poisoned) => status_for(&poisoned.into_inner()),
    }
}

#[tauri::command]
pub fn global_desktop_configure(
    runtime: State<'_, GlobalDesktopRuntime>,
    settings: GlobalDesktopSettings,
) -> Result<GlobalDesktopStatus, String> {
    let settings = validate_settings(settings).map_err(str::to_string)?;
    let mut state = runtime
        .0
        .lock()
        .map_err(|_| "Desktop settings are unavailable".to_string())?;
    if settings.open_at_login != state.settings.open_at_login {
        let code = native::set_login_item(settings.open_at_login);
        if settings.open_at_login && !matches!(code, 1 | 2) {
            return Err("macOS did not allow OfficeKit to open at login".into());
        }
    }
    if let Some(directory) = state.directory.clone() {
        save_settings(&directory, &settings)?;
    }
    state.registration_failures = apply_registrations(&settings);
    crate::window_runtime::configure(&settings);
    state.settings = settings;
    let status = status_for(&state);
    drop(state);
    crate::global_clipboard::request_refresh();
    Ok(status)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_directory(name: &str) -> std::path::PathBuf {
        let directory = std::env::temp_dir().join(format!(
            "officekit-global-desktop-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).unwrap();
        directory
    }

    fn with(action: &str, key_code: u16, modifier_mask: u8) -> GlobalDesktopSettings {
        let mut settings = GlobalDesktopSettings::default();
        settings.shortcuts.insert(
            action.to_string(),
            ShortcutSetting {
                key_code,
                modifier_mask,
            },
        );
        settings
    }

    #[test]
    fn launcher_password_options_are_bounded_and_allow_an_empty_symbol_set() {
        let defaults = GlobalDesktopSettings::default();
        assert_eq!(defaults.quick_password_length, 20);
        assert_eq!(
            defaults.quick_password_symbols,
            DEFAULT_QUICK_PASSWORD_SYMBOLS
        );

        for length in [7, 129] {
            let mut settings = defaults.clone();
            settings.quick_password_length = length;
            assert!(validate_settings(settings).is_err());
        }
        let invalid_symbols = vec![
            "a".to_string(),
            "! !".to_string(),
            "!!".to_string(),
            "é".to_string(),
            "!".repeat(33),
        ];
        for symbols in invalid_symbols {
            let mut settings = defaults.clone();
            settings.quick_password_symbols = symbols.clone();
            assert!(validate_settings(settings).is_err(), "{symbols:?}");
        }
        let mut no_symbols = defaults;
        no_symbols.quick_password_symbols.clear();
        assert_eq!(validate_settings(no_symbols.clone()), Ok(no_symbols));
    }

    #[test]
    fn defaults_are_valid_off_and_use_command_option_v_and_s() {
        let defaults = GlobalDesktopSettings::default();
        assert!(!defaults.enabled && !defaults.open_at_login);
        assert_eq!(
            defaults.shortcuts[ACTION_CLIPBOARD_HISTORY],
            ShortcutSetting {
                key_code: 9,
                modifier_mask: 0b1010
            }
        );
        assert_eq!(
            defaults.shortcuts[ACTION_SNIPPETS_PANEL],
            ShortcutSetting {
                key_code: 1,
                modifier_mask: 0b1010
            }
        );
        assert_eq!(validate_settings(defaults.clone()), Ok(defaults));
    }

    #[test]
    fn validation_rejects_unknown_actions_bare_keys_reserved_chords_and_duplicates() {
        assert!(validate_settings(with("window.left", 123, 0b0011)).is_err());
        assert!(validate_settings(with(ACTION_SNIPPETS_PANEL, 1, 0)).is_err());
        assert!(validate_settings(with(ACTION_SNIPPETS_PANEL, 12, 0b1000)).is_err());
        // Only the launcher may take Command-Space from Spotlight.
        assert!(validate_settings(with(
            ACTION_SNIPPETS_PANEL,
            KEY_CODE_SPACE,
            MODIFIER_COMMAND
        ))
        .is_err());
        assert!(validate_settings(with(ACTION_LAUNCHER, KEY_CODE_SPACE, MODIFIER_COMMAND)).is_ok());
        assert!(validate_settings(with(ACTION_LAUNCHER, 12, MODIFIER_COMMAND)).is_err());
        assert_eq!(
            validate_settings(with(ACTION_SNIPPETS_PANEL, 9, 0b1010)),
            Err("Two actions cannot share the same shortcut.")
        );
    }

    fn with_filter(filter: &str, key_code: u16, modifier_mask: u8) -> GlobalDesktopSettings {
        let mut settings = GlobalDesktopSettings::default();
        settings.launcher_filters.insert(
            filter.to_string(),
            ShortcutSetting {
                key_code,
                modifier_mask,
            },
        );
        settings
    }

    #[test]
    fn launcher_filters_default_to_control_one_to_four_and_pass_validation() {
        let defaults = GlobalDesktopSettings::default();
        let keys: Vec<(&str, u16, u8)> = defaults
            .launcher_filters
            .iter()
            .map(|(name, shortcut)| (name.as_str(), shortcut.key_code, shortcut.modifier_mask))
            .collect();
        assert_eq!(
            keys,
            vec![
                ("all", 18, 1),
                ("app", 19, 1),
                ("snippet", 21, 1),
                ("tool", 20, 1)
            ]
        );
        assert_eq!(validate_settings(defaults.clone()), Ok(defaults));
    }

    #[test]
    fn launcher_filters_accept_a_new_key_and_fill_missing_filters() {
        // Control-Option-T is already a window layout, so use Control-Shift-Command-T.
        let mut settings = with_filter("tool", 17, 0b1101);
        settings.launcher_filters.remove("snippet");
        let validated = validate_settings(settings).unwrap();
        assert_eq!(validated.launcher_filters["tool"].key_code, 17);
        assert_eq!(validated.launcher_filters["snippet"].key_code, 21);
        assert_eq!(validated.launcher_filters.len(), 4);
    }

    #[test]
    fn launcher_filters_reject_unknown_names_bare_keys_panel_keys_and_clashes() {
        assert_eq!(
            validate_settings(with_filter("files", 18, 1)),
            Err("Unknown launcher filter.")
        );
        assert_eq!(
            validate_settings(with_filter("tool", 17, 0)),
            Err("A launcher filter shortcut needs a modifier key.")
        );
        assert_eq!(
            validate_settings(with_filter("tool", 200, 1)),
            Err("A launcher filter shortcut needs a modifier key.")
        );
        // Command-1 to Command-9 pick rows, Command-P pins and Command-Delete removes.
        for key_code in [18, 25, 35, 51] {
            assert_eq!(
                validate_settings(with_filter("tool", key_code, 0b1000)),
                Err("That key is used by the launcher panel."),
                "key {key_code}"
            );
        }
        // Command with another modifier is fine.
        assert!(validate_settings(with_filter("tool", 18, 0b1001)).is_ok());
        assert_eq!(
            validate_settings(with_filter("tool", 18, 1)),
            Err("Two launcher filters cannot share the same shortcut.")
        );
        assert_eq!(
            validate_settings(with_filter("tool", 9, 0b1010)),
            Err("That shortcut is already used by another OfficeKit action.")
        );
    }

    #[test]
    fn launcher_filters_missing_from_an_older_settings_file_get_defaults() {
        let directory = temp_directory("older-file");
        std::fs::write(
            directory.join(SETTINGS_FILE),
            br#"{"enabled":true,"windowGap":4}"#,
        )
        .unwrap();
        let loaded = load_settings(&directory);
        assert!(loaded.enabled);
        assert_eq!(loaded.launcher_filters.len(), 4);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn validation_fills_missing_actions_and_accepts_function_keys_alone() {
        let mut settings = GlobalDesktopSettings {
            shortcuts: BTreeMap::new(),
            ..GlobalDesktopSettings::default()
        };
        settings.shortcuts.insert(
            ACTION_SNIPPETS_PANEL.to_string(),
            ShortcutSetting {
                key_code: 105,
                modifier_mask: 0,
            },
        );
        let validated = validate_settings(settings).unwrap();
        assert_eq!(
            validated.shortcuts.len(),
            3,
            "window layouts are not auto-assigned"
        );
        assert_eq!(validated.shortcuts[ACTION_SNIPPETS_PANEL].key_code, 105);
        assert_eq!(validated.shortcuts[ACTION_CLIPBOARD_HISTORY].key_code, 9);
    }

    #[test]
    fn settings_round_trip_through_an_atomic_save() {
        let directory = temp_directory("round-trip");
        let mut settings = with(ACTION_SNIPPETS_PANEL, 2, 0b1010);
        settings.enabled = true;
        save_settings(&directory, &settings).unwrap();
        assert!(!directory.join("global-desktop.json.tmp").exists());
        assert_eq!(load_settings(&directory), settings);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn loading_falls_back_to_defaults_for_missing_corrupt_oversized_or_invalid_files() {
        let directory = temp_directory("fallback");
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        let file = directory.join("global-desktop.json");
        std::fs::write(&file, b"not json").unwrap();
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        std::fs::write(&file, vec![b' '; (MAX_SETTINGS_BYTES + 1) as usize]).unwrap();
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        std::fs::write(&file, br#"{"enabled":true,"surprise":1}"#).unwrap();
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        std::fs::write(
            &file,
            br#"{"enabled":true,"shortcuts":{"snippets.panel":{"keyCode":1,"modifierMask":0}}}"#,
        )
        .unwrap();
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        std::fs::remove_file(&file).unwrap();
        std::fs::create_dir(&file).unwrap();
        assert_eq!(load_settings(&directory), GlobalDesktopSettings::default());
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn saving_reports_failure_when_the_directory_cannot_be_created() {
        let directory = temp_directory("blocked");
        let blocker = directory.join("file");
        std::fs::write(&blocker, b"x").unwrap();
        assert!(save_settings(&blocker.join("child"), &GlobalDesktopSettings::default()).is_err());
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn native_codes_and_hotkey_ids_map_to_stable_labels() {
        assert_eq!(accessibility_label(0), "trusted");
        assert_eq!(accessibility_label(2), "needs-access");
        assert_eq!(login_item_label(0), "off");
        assert_eq!(login_item_label(1), "on");
        assert_eq!(login_item_label(2), "needs-approval");
        assert_eq!(login_item_label(3), "unavailable");
        assert_eq!(action_for_id(0), Some(ACTION_CLIPBOARD_HISTORY));
        assert_eq!(action_for_id(1), Some(ACTION_SNIPPETS_PANEL));
        assert_eq!(action_for_id(2), Some(ACTION_LAUNCHER));
        assert_eq!(action_for_id(3), Some("window.left-half"));
        assert_eq!(
            action_for_id(i32::try_from(known_actions().len()).unwrap()),
            None
        );
        assert_eq!(action_for_id(-1), None);
    }

    #[test]
    fn window_defaults_follow_rectangle_and_pass_validation() {
        let defaults = GlobalDesktopSettings::default();
        assert!(!defaults.windows_enabled && !defaults.edge_drag && defaults.window_gap == 0);
        assert_eq!(
            defaults.shortcuts["window.left-half"],
            ShortcutSetting {
                key_code: 123,
                modifier_mask: 0b0011
            }
        );
        assert_eq!(
            defaults.shortcuts["window.next-display"],
            ShortcutSetting {
                key_code: 124,
                modifier_mask: 0b1011
            }
        );
        assert!(!defaults.shortcuts.contains_key("window.center-half"));
        assert_eq!(validate_settings(defaults.clone()), Ok(defaults));
    }

    #[test]
    fn window_options_are_bounded_trimmed_and_deduplicated() {
        let base = GlobalDesktopSettings::default();
        let mut settings = base.clone();
        settings.window_gap = 65;
        assert!(validate_settings(settings).is_err());
        let mut settings = base.clone();
        settings.window_skip_apps = vec![
            " com.apple.Safari ".into(),
            "COM.APPLE.SAFARI".into(),
            "org.mozilla.firefox".into(),
        ];
        let validated = validate_settings(settings).unwrap();
        assert_eq!(
            validated.window_skip_apps,
            vec!["com.apple.Safari", "org.mozilla.firefox"]
        );
        assert_eq!(validated.window_options().skip_apps.len(), 2);
        for bad in ["", "has space", "bad/id", "-leading", "semi;colon"] {
            let mut settings = base.clone();
            settings.window_skip_apps = vec![bad.into()];
            assert!(validate_settings(settings).is_err(), "{bad:?}");
        }
        let mut settings = base.clone();
        settings.window_skip_apps = (0..65).map(|n| format!("com.example.app{n}")).collect();
        assert!(validate_settings(settings).is_err());
        let mut settings = base;
        settings.window_skip_apps = vec![format!("a{}", "b".repeat(200))];
        assert!(validate_settings(settings).is_err());
    }

    #[test]
    fn control_arrow_chords_are_allowed_with_option_but_not_alone() {
        let base = GlobalDesktopSettings::default();
        let mut alone = base.clone();
        alone.shortcuts.insert(
            "window.left-half".into(),
            ShortcutSetting {
                key_code: 123,
                modifier_mask: 0b0001,
            },
        );
        assert!(validate_settings(alone).is_err());
        let mut moved = base.clone();
        moved.shortcuts.insert(
            "window.left-half".into(),
            ShortcutSetting {
                key_code: 123,
                modifier_mask: 0b0101,
            },
        );
        assert!(validate_settings(moved).is_ok());
        let mut clash = base;
        clash.shortcuts.insert(
            ACTION_SNIPPETS_PANEL.into(),
            ShortcutSetting {
                key_code: 123,
                modifier_mask: 0b0011,
            },
        );
        assert_eq!(
            validate_settings(clash),
            Err("Two actions cannot share the same shortcut.")
        );
    }

    #[test]
    fn window_shortcuts_register_only_when_the_window_manager_is_enabled() {
        let mut registrar = FakeRegistrar::default();
        let mut settings = GlobalDesktopSettings::default();
        settings.windows_enabled = true;
        assert!(apply_with(&mut registrar, &settings).is_empty());
        assert_eq!(
            registrar.registered.len(),
            window_manager::DEFAULT_SHORTCUTS.len()
        );
        assert!(registrar.registered.iter().all(|(id, _, _)| *id >= 3));
        settings.windows_enabled = false;
        settings.enabled = true;
        let mut registrar = FakeRegistrar::default();
        apply_with(&mut registrar, &settings);
        assert_eq!(registrar.registered.len(), 3);
    }

    #[derive(Default)]
    struct FakeRegistrar {
        unregistered: usize,
        registered: Vec<(i32, u16, u8)>,
        refuse_id: Option<i32>,
    }

    impl HotkeyRegistrar for FakeRegistrar {
        fn unregister_all(&mut self) {
            self.unregistered += 1;
            self.registered.clear();
        }
        fn register(&mut self, id: i32, key_code: u16, modifier_mask: u8) -> bool {
            if self.refuse_id == Some(id) {
                return false;
            }
            self.registered.push((id, key_code, modifier_mask));
            true
        }
    }

    #[test]
    fn disabled_settings_clear_registrations_and_register_nothing() {
        let mut registrar = FakeRegistrar::default();
        assert!(apply_with(&mut registrar, &GlobalDesktopSettings::default()).is_empty());
        assert_eq!(registrar.unregistered, 1);
        assert!(registrar.registered.is_empty());
    }

    #[test]
    fn enabled_settings_register_each_action_with_its_hotkey_id() {
        let mut registrar = FakeRegistrar::default();
        let settings = GlobalDesktopSettings {
            enabled: true,
            ..GlobalDesktopSettings::default()
        };
        assert!(apply_with(&mut registrar, &settings).is_empty());
        assert_eq!(
            registrar.registered,
            vec![(0, 9, 0b1010), (1, 1, 0b1010), (2, 49, 0b0011)]
        );
    }

    #[test]
    fn refused_registrations_are_reported_by_action_without_stopping_the_rest() {
        let mut registrar = FakeRegistrar {
            refuse_id: Some(0),
            ..FakeRegistrar::default()
        };
        let settings = GlobalDesktopSettings {
            enabled: true,
            ..GlobalDesktopSettings::default()
        };
        assert_eq!(
            apply_with(&mut registrar, &settings),
            vec![ACTION_CLIPBOARD_HISTORY.to_string()]
        );
        assert_eq!(registrar.registered, vec![(1, 1, 0b1010), (2, 49, 0b0011)]);
    }

    #[test]
    fn switching_off_the_launcher_or_snippets_releases_only_its_shortcut() {
        let mut registrar = FakeRegistrar::default();
        let mut settings = GlobalDesktopSettings {
            enabled: true,
            launcher_enabled: false,
            ..GlobalDesktopSettings::default()
        };
        apply_with(&mut registrar, &settings);
        // Clipboard history (0) and snippets (1) stay; the launcher (2) is released.
        assert_eq!(registrar.registered, vec![(0, 9, 0b1010), (1, 1, 0b1010)]);
        settings.snippets_enabled = false;
        apply_with(&mut registrar, &settings);
        assert_eq!(registrar.registered, vec![(0, 9, 0b1010)]);
    }

    #[test]
    fn the_master_switch_still_releases_every_clipboard_and_launcher_shortcut() {
        let mut registrar = FakeRegistrar::default();
        apply_with(&mut registrar, &GlobalDesktopSettings::default());
        assert!(registrar.registered.is_empty());
    }

    #[test]
    fn settings_files_from_before_the_launcher_split_load_with_everything_on() {
        let directory = temp_directory("before-launcher-split");
        let file = directory.join("global-desktop.json");
        std::fs::write(&file, br#"{"enabled":true,"openAtLogin":false}"#).unwrap();
        let loaded = load_settings(&directory);
        assert!(loaded.enabled);
        assert!(loaded.launcher_enabled && loaded.snippets_enabled);
        assert!(
            loaded.launcher_show_apps
                && loaded.launcher_show_tools
                && loaded.launcher_show_snippets
        );
        assert!(loaded.quick_calculator && loaded.quick_uuid && loaded.quick_password);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn the_new_launcher_fields_round_trip_through_the_settings_file() {
        let directory = temp_directory("launcher-fields");
        let settings = GlobalDesktopSettings {
            launcher_enabled: false,
            launcher_show_tools: false,
            quick_password: false,
            ..GlobalDesktopSettings::default()
        };
        save_settings(&directory, &settings).unwrap();
        assert_eq!(load_settings(&directory), settings);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn actions_without_a_saved_shortcut_are_skipped() {
        let mut registrar = FakeRegistrar::default();
        let settings = GlobalDesktopSettings {
            enabled: true,
            shortcuts: BTreeMap::new(),
            ..GlobalDesktopSettings::default()
        };
        assert!(apply_with(&mut registrar, &settings).is_empty());
        assert!(registrar.registered.is_empty());
    }
}
