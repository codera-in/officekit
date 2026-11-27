//! Installed-application discovery for the global launcher. Reads only the names and paths of
//! `.app` bundles in the standard Applications folders; nothing leaves the Mac.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

/// Most applications the launcher lists, so the panel stays within its item limit.
pub const MAX_APPS: usize = 400;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InstalledApp {
    pub name: String,
    pub path: String,
}

/// The folders searched, one level deep each.
pub fn application_folders(home: Option<&Path>) -> Vec<PathBuf> {
    let mut folders = vec![
        PathBuf::from("/Applications"),
        PathBuf::from("/Applications/Utilities"),
        PathBuf::from("/System/Applications"),
        PathBuf::from("/System/Applications/Utilities"),
    ];
    if let Some(home) = home {
        folders.push(home.join("Applications"));
    }
    folders
}

fn is_listable_name(name: &str) -> bool {
    !name.is_empty() && !name.starts_with('.') && !name.chars().any(char::is_control)
}

/// Applications found in `folders`, sorted by name; the first folder wins when a name repeats.
pub fn discover_apps(folders: &[PathBuf]) -> Vec<InstalledApp> {
    let mut seen = HashSet::new();
    let mut apps = Vec::new();
    for folder in folders {
        let Ok(entries) = std::fs::read_dir(folder) else {
            continue;
        };
        let mut found: Vec<InstalledApp> = entries
            .flatten()
            .filter_map(|entry| {
                let path = entry.path();
                if path.extension().and_then(|ext| ext.to_str()) != Some("app") {
                    return None;
                }
                let name = path.file_stem()?.to_str()?.to_string();
                let path = path.to_str()?.to_string();
                // A symlink or file called X.app is not a bundle.
                let metadata = std::fs::metadata(&path).ok()?;
                (metadata.is_dir() && is_listable_name(&name))
                    .then_some(InstalledApp { name, path })
            })
            .collect();
        found.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
        for app in found {
            if seen.insert(app.name.to_lowercase()) {
                apps.push(app);
            }
        }
    }
    apps.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    apps.truncate(MAX_APPS);
    apps
}

/// Core system apps that live outside the standard folders (Finder and Keychain Access are in CoreServices).
const SYSTEM_APPS: [(&str, &str); 2] = [
    ("Finder", "/System/Library/CoreServices/Finder.app"),
    (
        "Keychain Access",
        "/System/Library/CoreServices/Applications/Keychain Access.app",
    ),
];

/// Everything the launcher lists: the standard folders plus the core system apps found in `system`.
pub fn apps_with_system(mut apps: Vec<InstalledApp>, system: &[(&str, &str)]) -> Vec<InstalledApp> {
    for (name, path) in system {
        let is_bundle = std::fs::metadata(path).map(|m| m.is_dir()).unwrap_or(false);
        if is_bundle && !apps.iter().any(|app| app.name.eq_ignore_ascii_case(name)) {
            apps.push(InstalledApp {
                name: (*name).into(),
                path: (*path).into(),
            });
        }
    }
    apps.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    apps.truncate(MAX_APPS);
    apps
}

/// The installed apps for `home`, including Finder.
pub fn installed_apps(home: Option<&Path>) -> Vec<InstalledApp> {
    apps_with_system(discover_apps(&application_folders(home)), &SYSTEM_APPS)
}

/// An installed app the user can pick in Settings: its display name and bundle identifier.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppChoice {
    pub name: String,
    pub bundle_id: String,
}

/// A bundle identifier the clipboard skip list accepts: letters, digits, dots, dashes, underscores.
fn is_bundle_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
}

/// `CFBundleIdentifier` from an XML Info.plist, or None for a binary plist or a missing key.
fn bundle_id_from_xml(plist: &[u8]) -> Option<String> {
    let text = std::str::from_utf8(plist).ok()?;
    let after_key = text.split("<key>CFBundleIdentifier</key>").nth(1)?;
    let value = after_key
        .split("<string>")
        .nth(1)?
        .split("</string>")
        .next()?;
    let value = value.trim();
    is_bundle_id(value).then(|| value.to_string())
}

/// The bundle identifier of an `.app`; binary plists fall back to `plutil` (no shell, fixed arguments).
fn bundle_id_of(app_path: &str) -> Option<String> {
    let plist_path = Path::new(app_path).join("Contents/Info.plist");
    let bytes = std::fs::read(&plist_path)
        .ok()
        .filter(|bytes| bytes.len() <= 1024 * 1024)?;
    if let Some(id) = bundle_id_from_xml(&bytes) {
        return Some(id);
    }
    let output = std::process::Command::new("/usr/bin/plutil")
        .args(["-extract", "CFBundleIdentifier", "raw", "-o", "-"])
        .arg(&plist_path)
        .output()
        .ok()
        .filter(|output| output.status.success())?;
    let value = String::from_utf8(output.stdout).ok()?;
    let value = value.trim();
    is_bundle_id(value).then(|| value.to_string())
}

/// Installed apps with their bundle identifiers, for the clipboard "skip these apps" picker.
#[tauri::command]
pub async fn list_installed_apps(app: tauri::AppHandle) -> Result<Vec<AppChoice>, String> {
    use tauri::Manager;
    let home = app.path().home_dir().ok();
    tauri::async_runtime::spawn_blocking(move || {
        installed_apps(home.as_deref())
            .into_iter()
            .filter_map(|app| {
                bundle_id_of(&app.path).map(|bundle_id| AppChoice {
                    name: app.name,
                    bundle_id,
                })
            })
            .collect()
    })
    .await
    .map_err(|_| "Installed apps could not be listed".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_bundle_id_from_an_xml_plist_and_rejects_bad_values() {
        let plist = b"<dict><key>CFBundleName</key><string>Safari</string>\n<key>CFBundleIdentifier</key>\n\t<string>com.apple.Safari</string></dict>";
        assert_eq!(
            bundle_id_from_xml(plist).as_deref(),
            Some("com.apple.Safari")
        );
        assert_eq!(bundle_id_from_xml(b"<dict></dict>"), None);
        assert_eq!(bundle_id_from_xml(&[0xff, 0xfe]), None);
        assert_eq!(
            bundle_id_from_xml(b"<key>CFBundleIdentifier</key><string>has space</string>"),
            None
        );
        assert_eq!(
            bundle_id_from_xml(b"<key>CFBundleIdentifier</key><string></string>"),
            None
        );
        assert!(!is_bundle_id(&"a".repeat(129)));
        assert!(is_bundle_id("com.agilebits.onepassword7"));
    }

    #[test]
    fn bundle_id_of_reads_an_xml_info_plist_from_a_bundle_folder() {
        let root = std::env::temp_dir().join(format!("officekit-bundleid-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("Demo.app/Contents")).unwrap();
        std::fs::write(
            root.join("Demo.app/Contents/Info.plist"),
            "<key>CFBundleIdentifier</key><string>app.demo.Demo</string>",
        )
        .unwrap();
        let app = root.join("Demo.app");
        assert_eq!(
            bundle_id_of(app.to_str().unwrap()).as_deref(),
            Some("app.demo.Demo")
        );
        assert_eq!(
            bundle_id_of(root.join("Missing.app").to_str().unwrap()),
            None
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    fn temp_directory(name: &str) -> PathBuf {
        let directory =
            std::env::temp_dir().join(format!("officekit-launcher-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).unwrap();
        directory
    }

    #[test]
    fn lists_app_bundles_sorted_and_skips_files_hidden_and_non_apps() {
        let root = temp_directory("sorted");
        std::fs::create_dir_all(root.join("Safari.app")).unwrap();
        std::fs::create_dir_all(root.join("notes.app")).unwrap();
        std::fs::create_dir_all(root.join(".Hidden.app")).unwrap();
        std::fs::create_dir_all(root.join("Folder")).unwrap();
        std::fs::write(root.join("Fake.app"), b"not a bundle").unwrap();
        std::fs::write(root.join("readme.txt"), b"x").unwrap();
        let apps = discover_apps(&[root.clone()]);
        let names: Vec<&str> = apps.iter().map(|app| app.name.as_str()).collect();
        assert_eq!(names, vec!["notes", "Safari"]);
        assert_eq!(apps[1].path, root.join("Safari.app").to_str().unwrap());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn system_apps_are_added_once_when_their_bundle_exists() {
        let root = temp_directory("system");
        std::fs::create_dir_all(root.join("Finder.app")).unwrap();
        let finder = root.join("Finder.app");
        let finder = finder.to_str().unwrap();
        let listed = apps_with_system(
            Vec::new(),
            &[("Finder", finder), ("Ghost", "/nonexistent/Ghost.app")],
        );
        assert_eq!(listed.len(), 1);
        assert_eq!(
            (listed[0].name.as_str(), listed[0].path.as_str()),
            ("Finder", finder)
        );
        let again = apps_with_system(listed, &[("finder", finder)]);
        assert_eq!(again.len(), 1);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_built_in_system_apps_include_finder_and_keychain_access() {
        let names: Vec<&str> = SYSTEM_APPS.iter().map(|(name, _)| *name).collect();
        assert_eq!(names, vec!["Finder", "Keychain Access"]);
        for (_, path) in SYSTEM_APPS {
            assert!(path.starts_with("/System/Library/CoreServices/") && path.ends_with(".app"));
        }
        // On a Mac the real bundles are listed even though no standard folder holds them.
        if std::path::Path::new("/System/Library/CoreServices/Applications/Keychain Access.app")
            .is_dir()
        {
            let listed = installed_apps(None);
            assert!(listed.iter().any(|app| app.name == "Keychain Access"));
        }
    }

    #[test]
    fn the_first_folder_wins_for_a_repeated_name_and_missing_folders_are_skipped() {
        let first = temp_directory("first");
        let second = temp_directory("second");
        std::fs::create_dir_all(first.join("Mail.app")).unwrap();
        std::fs::create_dir_all(second.join("Mail.app")).unwrap();
        std::fs::create_dir_all(second.join("Maps.app")).unwrap();
        let missing = std::env::temp_dir().join("officekit-launcher-does-not-exist");
        let apps = discover_apps(&[missing, first.clone(), second.clone()]);
        assert_eq!(apps.len(), 2);
        assert_eq!(apps[0].path, first.join("Mail.app").to_str().unwrap());
        let _ = std::fs::remove_dir_all(&first);
        let _ = std::fs::remove_dir_all(&second);
    }

    #[test]
    fn the_list_is_capped() {
        let root = temp_directory("cap");
        for index in 0..(MAX_APPS + 20) {
            std::fs::create_dir_all(root.join(format!("App{index:04}.app"))).unwrap();
        }
        assert_eq!(discover_apps(&[root.clone()]).len(), MAX_APPS);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn standard_folders_include_the_users_applications_only_when_known() {
        assert_eq!(application_folders(None).len(), 4);
        let with_home = application_folders(Some(Path::new("/Users/someone")));
        assert_eq!(with_home.len(), 5);
        assert_eq!(with_home[4], PathBuf::from("/Users/someone/Applications"));
    }
}
