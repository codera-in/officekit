//! What first-run setup and the Settings page remember between launches.
//!
//! One small file in the app data folder: whether setup has run (and when), and the speech model the
//! owner chose. The tool switches and permissions are not copied here; they stay with the code that owns
//! them (desktop settings, the dictation shortcut, macOS itself), so nothing can disagree.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{Manager, State};

use crate::dictation::DictationModel;

const SETTINGS_FILE: &str = "app-settings.json";
const MAX_SETTINGS_BYTES: u64 = 4 * 1024;
/// Bump when setup gains a step that existing users should see once.
pub const SETUP_VERSION: u32 = 1;
const MAX_DATE_CHARS: usize = 40;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct AppSettings {
    pub setup_done: bool,
    pub setup_version: u32,
    /// ISO date text from the window, shown as "Setup done · 23 Oct 2026".
    pub setup_completed_at: Option<String>,
    pub model_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct AppSettingsUpdate {
    pub setup_done: Option<bool>,
    pub setup_completed_at: Option<String>,
    pub model_id: Option<String>,
}

impl AppSettings {
    /// Applies one update; an invalid field refuses the whole update and changes nothing.
    pub fn apply(&mut self, update: AppSettingsUpdate) -> Result<(), String> {
        if let Some(id) = update.model_id.as_deref() {
            if DictationModel::from_id(id).is_none() {
                return Err("Choose one of the supported local speech models".into());
            }
        }
        if let Some(date) = update.setup_completed_at.as_deref() {
            if date.chars().count() > MAX_DATE_CHARS || date.chars().any(char::is_control) {
                return Err("The setup date is not valid".into());
            }
        }
        if let Some(done) = update.setup_done {
            self.setup_done = done;
            self.setup_version = if done { SETUP_VERSION } else { 0 };
            if !done {
                self.setup_completed_at = None;
            }
        }
        if self.setup_done {
            if let Some(date) = update.setup_completed_at {
                self.setup_completed_at = Some(date);
            }
        }
        if let Some(id) = update.model_id {
            self.model_id = Some(id);
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct AppSettingsRuntime {
    state: Mutex<AppSettings>,
    directory: Mutex<Option<PathBuf>>,
}

pub fn load(directory: &Path) -> AppSettings {
    let path = directory.join(SETTINGS_FILE);
    let Ok(metadata) = std::fs::metadata(&path) else {
        return AppSettings::default();
    };
    if !metadata.is_file() || metadata.len() > MAX_SETTINGS_BYTES {
        return AppSettings::default();
    }
    std::fs::read(&path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

pub fn save(directory: &Path, settings: &AppSettings) -> Result<(), String> {
    let failed = || "Could not save settings".to_string();
    std::fs::create_dir_all(directory).map_err(|_| failed())?;
    let bytes = serde_json::to_vec_pretty(settings).map_err(|_| failed())?;
    let temporary = directory.join(format!("{SETTINGS_FILE}.tmp"));
    std::fs::write(&temporary, bytes).map_err(|_| failed())?;
    std::fs::rename(&temporary, directory.join(SETTINGS_FILE)).map_err(|_| failed())
}

/// Loads the saved settings at launch.
pub fn restore(app: &tauri::AppHandle) {
    let runtime = app.state::<AppSettingsRuntime>();
    let directory = app.path().app_data_dir().ok();
    if let (Some(directory), Ok(mut state)) = (directory.as_ref(), runtime.state.lock()) {
        *state = load(directory);
    }
    if let Ok(mut slot) = runtime.directory.lock() {
        *slot = directory;
    };
}

fn read(runtime: &AppSettingsRuntime) -> AppSettings {
    match runtime.state.lock() {
        Ok(state) => state.clone(),
        Err(poisoned) => poisoned.into_inner().clone(),
    }
}

#[tauri::command]
pub fn app_settings_status(runtime: State<'_, AppSettingsRuntime>) -> AppSettings {
    read(&runtime)
}

#[tauri::command]
pub fn app_settings_save(
    runtime: State<'_, AppSettingsRuntime>,
    update: AppSettingsUpdate,
) -> Result<AppSettings, String> {
    let mut state = runtime
        .state
        .lock()
        .map_err(|_| "Settings are unavailable".to_string())?;
    let mut next = state.clone();
    next.apply(update)?;
    if let Ok(directory) = runtime.directory.lock() {
        if let Some(directory) = directory.as_ref() {
            save(directory, &next)?;
        }
    }
    *state = next.clone();
    Ok(next)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let directory = std::env::temp_dir().join(format!("officekit-app-settings-{name}"));
        let _ = std::fs::remove_dir_all(&directory);
        directory
    }

    fn done(date: &str) -> AppSettingsUpdate {
        AppSettingsUpdate {
            setup_done: Some(true),
            setup_completed_at: Some(date.into()),
            ..AppSettingsUpdate::default()
        }
    }

    #[test]
    fn a_new_mac_has_not_run_setup() {
        let settings = AppSettings::default();
        assert!(!settings.setup_done && settings.setup_version == 0);
        assert!(settings.setup_completed_at.is_none() && settings.model_id.is_none());
    }

    #[test]
    fn finishing_setup_records_the_version_and_date() {
        let mut settings = AppSettings::default();
        settings.apply(done("2026-10-23")).unwrap();
        assert!(settings.setup_done);
        assert_eq!(settings.setup_version, SETUP_VERSION);
        assert_eq!(settings.setup_completed_at.as_deref(), Some("2026-10-23"));
    }

    #[test]
    fn marking_setup_not_done_clears_the_date() {
        let mut settings = AppSettings::default();
        settings.apply(done("2026-10-23")).unwrap();
        settings
            .apply(AppSettingsUpdate {
                setup_done: Some(false),
                ..AppSettingsUpdate::default()
            })
            .unwrap();
        assert!(!settings.setup_done && settings.setup_version == 0);
        assert!(settings.setup_completed_at.is_none());
    }

    #[test]
    fn only_a_supported_model_can_be_saved() {
        let mut settings = AppSettings::default();
        let bad = AppSettingsUpdate {
            model_id: Some("gpt".into()),
            setup_done: Some(true),
            ..AppSettingsUpdate::default()
        };
        assert!(settings.apply(bad).is_err());
        assert_eq!(
            settings,
            AppSettings::default(),
            "a refused update changes nothing"
        );
        settings
            .apply(AppSettingsUpdate {
                model_id: Some("whisper_small".into()),
                ..AppSettingsUpdate::default()
            })
            .unwrap();
        assert_eq!(settings.model_id.as_deref(), Some("whisper_small"));
    }

    #[test]
    fn the_date_is_bounded_and_has_no_control_characters() {
        let mut settings = AppSettings::default();
        assert!(settings
            .apply(done(&"x".repeat(MAX_DATE_CHARS + 1)))
            .is_err());
        assert!(settings.apply(done("2026\n10")).is_err());
        assert_eq!(settings, AppSettings::default());
    }

    #[test]
    fn a_date_without_finishing_setup_is_ignored() {
        let mut settings = AppSettings::default();
        settings
            .apply(AppSettingsUpdate {
                setup_completed_at: Some("2026-10-23".into()),
                ..AppSettingsUpdate::default()
            })
            .unwrap();
        assert!(settings.setup_completed_at.is_none());
    }

    #[test]
    fn saved_settings_come_back_after_a_restart() {
        let directory = scratch("roundtrip");
        let mut settings = AppSettings::default();
        settings.apply(done("2026-10-23")).unwrap();
        settings
            .apply(AppSettingsUpdate {
                model_id: Some("parakeet_v3".into()),
                ..AppSettingsUpdate::default()
            })
            .unwrap();
        save(&directory, &settings).unwrap();
        assert_eq!(load(&directory), settings);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn a_missing_oversized_or_corrupt_file_means_not_set_up() {
        let directory = scratch("bad");
        assert_eq!(load(&directory), AppSettings::default());
        std::fs::create_dir_all(&directory).unwrap();
        std::fs::write(directory.join(SETTINGS_FILE), "not json").unwrap();
        assert_eq!(load(&directory), AppSettings::default());
        std::fs::write(
            directory.join(SETTINGS_FILE),
            vec![b' '; (MAX_SETTINGS_BYTES + 1) as usize],
        )
        .unwrap();
        assert_eq!(load(&directory), AppSettings::default());
        let _ = std::fs::remove_dir_all(&directory);
    }
}
