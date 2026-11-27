//! Which system stats (CPU, RAM, Storage, Network) show in the macOS menu bar.
//!
//! Four independent switches, saved next to the other app settings. The page that samples the numbers
//! reads this state and only shows the drawers that are on. Nothing here touches process data.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager, State};

const SETTINGS_FILE: &str = "menu-stats.json";
const MAX_SETTINGS_BYTES: u64 = 4 * 1024;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct MenuStats {
    pub cpu: bool,
    pub ram: bool,
    pub storage: bool,
    pub network: bool,
    /// GPU, temperature, battery and Bluetooth are off until chosen, so a Mac never shows an item with no switch.
    pub gpu: bool,
    pub temperature: bool,
    pub battery: bool,
    pub bluetooth: bool,
    /// False until the user (or the one-time adoption of the old single switch) has chosen.
    pub configured: bool,
}

impl MenuStats {
    pub fn any(&self) -> bool {
        self.cpu
            || self.ram
            || self.storage
            || self.network
            || self.gpu
            || self.temperature
            || self.battery
            || self.bluetooth
    }

    /// Sets one stat by its Quick controls name; every other name is refused.
    pub fn set(&mut self, name: &str, enabled: bool) -> Result<(), String> {
        match name {
            "menuCpu" => self.cpu = enabled,
            "menuRam" => self.ram = enabled,
            "menuStorage" => self.storage = enabled,
            "menuNetwork" => self.network = enabled,
            "menuGpu" => self.gpu = enabled,
            "menuTemperature" => self.temperature = enabled,
            "menuBattery" => self.battery = enabled,
            "menuBluetooth" => self.bluetooth = enabled,
            _ => return Err("Choose a supported menu bar stat".into()),
        }
        self.configured = true;
        Ok(())
    }

    pub fn all_off(&mut self) {
        *self = MenuStats {
            configured: true,
            ..MenuStats::default()
        };
    }

    /// One-time carry-over of the old single "show stats in the menu bar" switch.
    pub fn adopt_legacy(&mut self, was_on: bool) {
        if self.configured {
            return;
        }
        if was_on {
            self.cpu = true;
            self.ram = true;
            self.storage = true;
            self.network = true;
        }
        self.configured = true;
    }
}

#[derive(Default)]
pub struct MenuStatsRuntime {
    state: Mutex<MenuStats>,
    directory: Mutex<Option<PathBuf>>,
}

pub fn load(directory: &Path) -> MenuStats {
    let path = directory.join(SETTINGS_FILE);
    let Ok(metadata) = std::fs::metadata(&path) else {
        return MenuStats::default();
    };
    if !metadata.is_file() || metadata.len() > MAX_SETTINGS_BYTES {
        return MenuStats::default();
    }
    std::fs::read(&path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

pub fn save(directory: &Path, stats: &MenuStats) -> Result<(), String> {
    let failed = || "Could not save menu bar stats".to_string();
    std::fs::create_dir_all(directory).map_err(|_| failed())?;
    let bytes = serde_json::to_vec_pretty(stats).map_err(|_| failed())?;
    let temporary = directory.join(format!("{SETTINGS_FILE}.tmp"));
    std::fs::write(&temporary, bytes).map_err(|_| failed())?;
    std::fs::rename(&temporary, directory.join(SETTINGS_FILE)).map_err(|_| failed())
}

/// Loads the saved choice at launch.
pub fn restore(app: &tauri::AppHandle) {
    let runtime = app.state::<MenuStatsRuntime>();
    let directory = app.path().app_data_dir().ok();
    if let (Some(directory), Ok(mut state)) = (directory.as_ref(), runtime.state.lock()) {
        *state = load(directory);
    }
    if let Ok(mut slot) = runtime.directory.lock() {
        *slot = directory;
    };
}

fn read(runtime: &MenuStatsRuntime) -> MenuStats {
    match runtime.state.lock() {
        Ok(state) => *state,
        Err(poisoned) => *poisoned.into_inner(),
    }
}

fn change(
    app: &tauri::AppHandle,
    apply: impl FnOnce(&mut MenuStats) -> Result<(), String>,
) -> Result<MenuStats, String> {
    let runtime = app.state::<MenuStatsRuntime>();
    let mut state = runtime
        .state
        .lock()
        .map_err(|_| "Menu bar stats are unavailable".to_string())?;
    let mut next = *state;
    apply(&mut next)?;
    if let Ok(directory) = runtime.directory.lock() {
        if let Some(directory) = directory.as_ref() {
            save(directory, &next)?;
        }
    }
    *state = next;
    drop(state);
    // The main window samples the numbers; tell it to start, stop or re-filter the drawers.
    let _ = app.emit("menu-stats-changed", next);
    Ok(next)
}

pub fn status(app: &tauri::AppHandle) -> MenuStats {
    read(&app.state::<MenuStatsRuntime>())
}

pub fn set_stat(app: &tauri::AppHandle, name: &str, enabled: bool) -> Result<MenuStats, String> {
    change(app, |stats| stats.set(name, enabled))
}

pub fn disable_all(app: &tauri::AppHandle) -> Result<MenuStats, String> {
    change(app, |stats| {
        stats.all_off();
        Ok(())
    })
}

#[tauri::command]
pub fn menu_stats_status(runtime: State<'_, MenuStatsRuntime>) -> MenuStats {
    read(&runtime)
}

/// The main window hands over the old single switch once, so nobody loses their menu bar stats.
#[tauri::command]
pub fn menu_stats_adopt_legacy(app: tauri::AppHandle, was_on: bool) -> Result<MenuStats, String> {
    change(&app, |stats| {
        stats.adopt_legacy(was_on);
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let directory = std::env::temp_dir().join(format!("officekit-menu-stats-{name}"));
        let _ = std::fs::remove_dir_all(&directory);
        directory
    }

    #[test]
    fn each_stat_switches_on_its_own() {
        let mut stats = MenuStats::default();
        stats.set("menuRam", true).unwrap();
        assert!(stats.ram && !stats.cpu && !stats.storage && !stats.network);
        assert!(stats.configured && stats.any());
        stats.set("menuRam", false).unwrap();
        assert!(!stats.any());
    }

    #[test]
    fn an_unknown_stat_is_refused_and_changes_nothing() {
        let mut stats = MenuStats::default();
        assert!(stats.set("menuFans", true).is_err());
        assert_eq!(stats, MenuStats::default());
    }

    #[test]
    fn gpu_temperature_battery_and_bluetooth_have_their_own_switches_and_start_off() {
        let mut stats = MenuStats::default();
        assert!(!stats.any());
        for name in ["menuGpu", "menuTemperature", "menuBattery", "menuBluetooth"] {
            let mut one = MenuStats::default();
            one.set(name, true).unwrap();
            assert!(one.any() && !one.cpu && !one.ram, "{name} turns on alone");
            one.set(name, false).unwrap();
            assert!(!one.any());
        }
        stats.adopt_legacy(true);
        assert!(!stats.gpu && !stats.temperature && !stats.battery && !stats.bluetooth);
    }

    #[test]
    fn a_file_saved_before_the_new_switches_loads_with_them_off() {
        let directory = scratch("old-file");
        std::fs::create_dir_all(&directory).unwrap();
        std::fs::write(
            directory.join(SETTINGS_FILE),
            r#"{"cpu":true,"ram":true,"storage":false,"network":true,"configured":true}"#,
        )
        .unwrap();
        let loaded = load(&directory);
        assert!(loaded.cpu && loaded.network && loaded.configured);
        assert!(!loaded.gpu && !loaded.temperature && !loaded.battery && !loaded.bluetooth);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn disable_all_turns_every_stat_off_and_keeps_the_choice() {
        let mut stats = MenuStats::default();
        for name in ["menuCpu", "menuRam", "menuStorage", "menuNetwork"] {
            stats.set(name, true).unwrap();
        }
        stats.all_off();
        assert!(!stats.any() && stats.configured);
    }

    #[test]
    fn the_old_switch_carries_over_once_and_never_again() {
        let mut stats = MenuStats::default();
        stats.adopt_legacy(true);
        assert!(stats.cpu && stats.ram && stats.storage && stats.network);
        stats.all_off();
        stats.adopt_legacy(true);
        assert!(!stats.any(), "a later choice is never overwritten");
        let mut off = MenuStats::default();
        off.adopt_legacy(false);
        assert!(!off.any() && off.configured);
    }

    #[test]
    fn saved_choices_come_back_after_a_restart() {
        let directory = scratch("roundtrip");
        let mut stats = MenuStats::default();
        stats.set("menuCpu", true).unwrap();
        stats.set("menuNetwork", true).unwrap();
        save(&directory, &stats).unwrap();
        assert_eq!(load(&directory), stats);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn a_missing_oversized_or_corrupt_file_gives_the_defaults() {
        let directory = scratch("bad");
        assert_eq!(load(&directory), MenuStats::default());
        std::fs::create_dir_all(&directory).unwrap();
        std::fs::write(directory.join(SETTINGS_FILE), "not json").unwrap();
        assert_eq!(load(&directory), MenuStats::default());
        std::fs::write(
            directory.join(SETTINGS_FILE),
            vec![b' '; (MAX_SETTINGS_BYTES + 1) as usize],
        )
        .unwrap();
        assert_eq!(load(&directory), MenuStats::default());
        let _ = std::fs::remove_dir_all(&directory);
    }
}
