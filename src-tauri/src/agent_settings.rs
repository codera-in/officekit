//! Native support for Settings → Connect AI agents: the saved agent settings that
//! `officekit-media --agent-mcp` / `--agent-cli` read on start, the bundled helper path,
//! folder pickers and the Claude Code skill install. Python re-validates the settings file
//! and falls back to its restrictive defaults, so this module only has to refuse bad input.
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

const SETTINGS_VERSION: u64 = 1;
const TOOL_GROUPS: [&str; 6] = ["calc", "dev", "pdf", "image", "privacy", "system"];
const MAX_ALLOWED_DIRS: usize = 20;
const MAX_PATH_CHARS: usize = 1024;
const SETTINGS_ENV: &str = "OFFICEKIT_AGENT_SETTINGS";
const HELPER_RESOURCE: &str = "binaries/officekit-media";
const SKILL_TEMPLATE: &str = include_str!("../../assets/agent-skill/SKILL.md");
const SKILL_PLACEHOLDER: &str = "{{OFFICEKIT_BIN}}";
const SKILL_OWNER_PREFIX: &str = "---\nname: officekit\n";

fn settings_path(override_path: Option<std::ffi::OsString>, home: &Path) -> PathBuf {
    match override_path {
        Some(path) if !path.is_empty() => PathBuf::from(path),
        _ => home.join(".officekit").join("agent-settings.json"),
    }
}

fn default_allowed_dirs(home: &Path) -> Vec<String> {
    ["Documents", "Downloads", "Desktop"]
        .iter()
        .map(|name| home.join(name).to_string_lossy().into_owned())
        .collect()
}

fn default_output_dir(home: &Path) -> String {
    home.join("OfficeKit Output").to_string_lossy().into_owned()
}

fn validate_folder(value: &Value) -> Result<String, String> {
    let text = value.as_str().ok_or("Folders must be paths")?;
    if text.is_empty() || text.chars().count() > MAX_PATH_CHARS || text.contains('\0') {
        return Err("Folders must be non-empty paths".into());
    }
    let path = Path::new(text);
    if !path.is_absolute() {
        return Err("Folders must be absolute paths".into());
    }
    if path.parent().is_none() {
        return Err("A whole drive cannot be shared with agents".into());
    }
    Ok(text.to_string())
}

fn validate_settings(value: &Value) -> Result<Value, String> {
    let object = value
        .as_object()
        .ok_or("Agent settings must be an object")?;
    if object.get("version").and_then(Value::as_u64) != Some(SETTINGS_VERSION) {
        return Err("Unsupported agent settings version".into());
    }
    if let Some(key) = object
        .keys()
        .find(|key| !["version", "tools", "allowed_dirs", "output_dir"].contains(&key.as_str()))
    {
        return Err(format!("Unknown agent setting: {key}"));
    }
    let mut result = serde_json::Map::new();
    result.insert("version".into(), json!(SETTINGS_VERSION));
    if let Some(tools) = object.get("tools") {
        let names = tools.as_array().ok_or("tools must be a list")?;
        let mut seen = Vec::new();
        for name in names {
            let name = name.as_str().ok_or("tools must be names")?;
            if !TOOL_GROUPS.contains(&name) || seen.contains(&name) {
                return Err("tools must be known, unique tool groups".into());
            }
            seen.push(name);
        }
        result.insert("tools".into(), json!(seen));
    }
    if let Some(folders) = object.get("allowed_dirs") {
        let folders = folders.as_array().ok_or("allowed_dirs must be a list")?;
        if folders.is_empty() || folders.len() > MAX_ALLOWED_DIRS {
            return Err(format!(
                "allowed_dirs must list 1 to {MAX_ALLOWED_DIRS} folders"
            ));
        }
        let checked: Result<Vec<String>, String> = folders.iter().map(validate_folder).collect();
        result.insert("allowed_dirs".into(), json!(checked?));
    }
    if let Some(folder) = object.get("output_dir") {
        result.insert("output_dir".into(), json!(validate_folder(folder)?));
    }
    Ok(Value::Object(result))
}

fn read_settings(path: &Path) -> Value {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|value| validate_settings(&value).ok())
        .unwrap_or_else(|| json!({ "version": SETTINGS_VERSION }))
}

fn write_settings(path: &Path, settings: &Value) -> Result<(), String> {
    let directory = path.parent().ok_or("Agent settings location is invalid")?;
    std::fs::create_dir_all(directory)
        .map_err(|_| "The agent settings folder could not be created".to_string())?;
    let temporary = directory.join(format!(".agent-settings-{}.tmp", uuid::Uuid::new_v4()));
    let text = serde_json::to_string_pretty(settings)
        .map_err(|_| "Agent settings could not be saved".to_string())?;
    std::fs::write(&temporary, text)
        .map_err(|_| "Agent settings could not be saved".to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(&temporary, path).map_err(|_| {
        let _ = std::fs::remove_file(&temporary);
        "Agent settings could not be saved".to_string()
    })
}

fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "'\\''"))
}

fn render_skill(helper: &Path) -> String {
    SKILL_TEMPLATE.replace(
        SKILL_PLACEHOLDER,
        &format!("{} --agent-cli", shell_quote(helper)),
    )
}

/// Agents that read a `SKILL.md`: id, label, the folder whose presence means it is on this Mac,
/// and where its per-user skills live. Codex reads user skills from `~/.agents/skills`.
const SKILL_TARGETS: [(&str, &str, &str, &str); 2] = [
    ("claude-code", "Claude Code", ".claude", ".claude/skills"),
    ("codex", "Codex", ".codex", ".agents/skills"),
];

fn skill_target(
    id: &str,
) -> Option<&'static (&'static str, &'static str, &'static str, &'static str)> {
    SKILL_TARGETS.iter().find(|target| target.0 == id)
}

fn skill_path(home: &Path, id: &str) -> Option<PathBuf> {
    let target = skill_target(id)?;
    Some(home.join(target.3).join("officekit").join("SKILL.md"))
}

/// Present when the agent's own folder exists, or when it already holds an OfficeKit skill.
fn agent_present(home: &Path, id: &str) -> bool {
    let Some(target) = skill_target(id) else {
        return false;
    };
    home.join(target.2).is_dir() || skill_path(home, id).is_some_and(|path| path.exists())
}

fn target_status(home: &Path, id: &str, rendered: Option<&str>) -> Value {
    let target = skill_target(id).expect("known skill target");
    let path = skill_path(home, id).expect("known skill target");
    let state = match rendered {
        Some(rendered) => skill_state(&path, rendered),
        None => "unavailable",
    };
    json!({
        "id": target.0,
        "label": target.1,
        "path": path.to_string_lossy(),
        "present": agent_present(home, id),
        "state": state,
    })
}

fn skill_targets_status(home: &Path, rendered: Option<&str>) -> Value {
    json!({ "targets": SKILL_TARGETS.iter().map(|target| target_status(home, target.0, rendered)).collect::<Vec<_>>() })
}

/// Installs into each selected agent that is on this Mac. A foreign skill is left alone and reported
/// as such; unknown ids and agents that are not here are skipped.
fn install_skill_targets(
    home: &Path,
    rendered: &str,
    selected: &[String],
) -> Result<Value, String> {
    let mut installed = 0;
    for id in selected {
        let Some(path) = skill_path(home, id) else {
            continue;
        };
        if !agent_present(home, id) || skill_state(&path, rendered) == "foreign" {
            continue;
        }
        install_skill(&path, rendered)?;
        installed += 1;
    }
    if installed == 0 {
        return Err("None of the selected agents can be updated on this Mac".into());
    }
    Ok(skill_targets_status(home, Some(rendered)))
}

fn skill_state(path: &Path, rendered: &str) -> &'static str {
    match std::fs::read_to_string(path) {
        Err(_) if !path.exists() => "not-installed",
        Err(_) => "foreign",
        Ok(text) if text == rendered => "installed",
        Ok(text) if text.starts_with(SKILL_OWNER_PREFIX) => "outdated",
        Ok(_) => "foreign",
    }
}

fn install_skill(path: &Path, rendered: &str) -> Result<&'static str, String> {
    if skill_state(path, rendered) == "foreign" {
        return Err("A different skill already uses the OfficeKit name".into());
    }
    let directory = path.parent().ok_or("Skill location is invalid")?;
    std::fs::create_dir_all(directory)
        .map_err(|_| "The skill folder could not be created".to_string())?;
    std::fs::write(path, rendered).map_err(|_| "The skill could not be installed".to_string())?;
    Ok("installed")
}

fn helper_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        let path = app
            .path()
            .resolve(HELPER_RESOURCE, tauri::path::BaseDirectory::Resource)
            .ok()?;
        return path.is_file().then_some(path);
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        None
    }
}

fn home_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .home_dir()
        .map_err(|_| "Your home folder is unavailable".to_string())
}

fn saved_settings_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(settings_path(
        std::env::var_os(SETTINGS_ENV),
        &home_dir(app)?,
    ))
}

#[tauri::command]
pub fn agent_helper_status(app: tauri::AppHandle) -> Value {
    match helper_path(&app) {
        Some(path) => json!({ "available": true, "path": path.to_string_lossy() }),
        None => json!({ "available": false, "path": null }),
    }
}

#[tauri::command]
pub fn agent_settings_read(app: tauri::AppHandle) -> Result<Value, String> {
    let home = home_dir(&app)?;
    let path = settings_path(std::env::var_os(SETTINGS_ENV), &home);
    Ok(json!({
        "settings": read_settings(&path),
        "defaults": { "allowed_dirs": default_allowed_dirs(&home), "output_dir": default_output_dir(&home) },
    }))
}

#[tauri::command]
pub fn agent_settings_write(app: tauri::AppHandle, settings: Value) -> Result<Value, String> {
    let checked = validate_settings(&settings)?;
    write_settings(&saved_settings_path(&app)?, &checked)?;
    Ok(checked)
}

#[tauri::command]
pub async fn agent_choose_folders(
    app: tauri::AppHandle,
    purpose: String,
) -> Result<Vec<String>, String> {
    if purpose != "read" && purpose != "output" {
        return Err("Unknown folder purpose".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let dialog = app.dialog().file().set_title(if purpose == "read" {
            "Choose folders agents may read from"
        } else {
            "Choose where agents save results"
        });
        let picked = if purpose == "read" {
            dialog.blocking_pick_folders().unwrap_or_default()
        } else {
            dialog.blocking_pick_folder().into_iter().collect()
        };
        picked
            .into_iter()
            .map(|folder| {
                folder
                    .into_path()
                    .map(|path| path.to_string_lossy().into_owned())
                    .map_err(|_| "Only local folders can be shared".to_string())
            })
            .collect()
    })
    .await
    .map_err(|_| "The folder picker closed unexpectedly".to_string())?
}

#[tauri::command]
pub fn agent_reveal_output(app: tauri::AppHandle) -> Result<(), String> {
    let home = home_dir(&app)?;
    let saved = read_settings(&settings_path(std::env::var_os(SETTINGS_ENV), &home));
    let folder = saved
        .get("output_dir")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(default_output_dir(&home)));
    std::fs::create_dir_all(&folder)
        .map_err(|_| "The output folder could not be created".to_string())?;
    #[cfg(target_os = "macos")]
    let opener = "/usr/bin/open";
    #[cfg(target_os = "windows")]
    let opener = "explorer";
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let opener = "xdg-open";
    std::process::Command::new(opener)
        .arg(&folder)
        .spawn()
        .map(|_| ())
        .map_err(|_| "The output folder could not be opened".to_string())
}

#[tauri::command]
pub fn agent_skill_status(app: tauri::AppHandle) -> Result<Value, String> {
    let home = home_dir(&app)?;
    let rendered = helper_path(&app).map(|helper| render_skill(&helper));
    Ok(skill_targets_status(&home, rendered.as_deref()))
}

#[tauri::command]
pub fn agent_skill_install(app: tauri::AppHandle, targets: Vec<String>) -> Result<Value, String> {
    if targets.is_empty() || targets.len() > SKILL_TARGETS.len() {
        return Err("Choose at least one agent".into());
    }
    let helper =
        helper_path(&app).ok_or("The OfficeKit agent helper is not available in this build")?;
    install_skill_targets(&home_dir(&app)?, &render_skill(&helper), &targets)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("officekit-agent-{name}-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn accepts_a_full_settings_document() {
        let value = json!({
            "version": 1, "tools": ["pdf", "calc"],
            "allowed_dirs": ["/Users/me/Documents"], "output_dir": "/Users/me/OfficeKit Output"
        });
        assert_eq!(validate_settings(&value).unwrap(), value);
    }

    #[test]
    fn rejects_unsafe_settings() {
        for bad in [
            json!({ "version": 2 }),
            json!({ "version": 1, "surprise": true }),
            json!({ "version": 1, "tools": ["pdf", "pdf"] }),
            json!({ "version": 1, "tools": ["clipboard"] }),
            json!({ "version": 1, "allowed_dirs": [] }),
            json!({ "version": 1, "allowed_dirs": ["relative"] }),
            json!({ "version": 1, "allowed_dirs": ["/"] }),
            json!({ "version": 1, "output_dir": "" }),
            json!("text"),
        ] {
            assert!(validate_settings(&bad).is_err(), "{bad}");
        }
        let many: Vec<String> = (0..21).map(|index| format!("/tmp/folder{index}")).collect();
        assert!(validate_settings(&json!({ "version": 1, "allowed_dirs": many })).is_err());
    }

    #[test]
    fn writes_atomically_and_reads_back_with_private_permissions() {
        let directory = scratch("settings");
        let path = directory.join("nested").join("agent-settings.json");
        let settings = json!({ "version": 1, "tools": [] });
        write_settings(&path, &settings).unwrap();
        assert_eq!(read_settings(&path), settings);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        let leftovers = std::fs::read_dir(path.parent().unwrap()).unwrap().count();
        assert_eq!(leftovers, 1, "no temporary files remain");
    }

    #[test]
    fn unreadable_settings_fall_back_to_the_default_document() {
        let directory = scratch("bad");
        let path = directory.join("agent-settings.json");
        assert_eq!(read_settings(&path), json!({ "version": 1 }));
        std::fs::write(&path, "{not json").unwrap();
        assert_eq!(read_settings(&path), json!({ "version": 1 }));
    }

    #[test]
    fn default_locations_live_under_the_home_folder() {
        let home = Path::new("/Users/me");
        assert_eq!(
            settings_path(None, home),
            home.join(".officekit/agent-settings.json")
        );
        assert_eq!(
            settings_path(Some("/tmp/x.json".into()), home),
            PathBuf::from("/tmp/x.json")
        );
        assert_eq!(default_allowed_dirs(home)[1], "/Users/me/Downloads");
        assert_eq!(default_output_dir(home), "/Users/me/OfficeKit Output");
    }

    #[test]
    fn skill_embeds_the_helper_path_quoted_for_a_shell() {
        let rendered = render_skill(Path::new(
            "/Applications/O'Kit.app/Contents/Resources/binaries/officekit-media",
        ));
        assert!(!rendered.contains(SKILL_PLACEHOLDER));
        assert!(rendered.contains("'/Applications/O'\\''Kit.app/Contents/Resources/binaries/officekit-media' --agent-cli call"));
        assert!(rendered.starts_with(SKILL_OWNER_PREFIX));
    }

    #[test]
    fn skill_install_never_overwrites_a_foreign_skill() {
        let home = scratch("skill");
        let path = skill_path(&home, "claude-code").unwrap();
        let rendered = render_skill(Path::new("/opt/officekit-media"));
        assert_eq!(skill_state(&path, &rendered), "not-installed");
        assert_eq!(install_skill(&path, &rendered).unwrap(), "installed");
        assert_eq!(skill_state(&path, &rendered), "installed");

        std::fs::write(
            &path,
            format!("{SKILL_OWNER_PREFIX}description: old\n---\n"),
        )
        .unwrap();
        assert_eq!(skill_state(&path, &rendered), "outdated");
        assert_eq!(install_skill(&path, &rendered).unwrap(), "installed");

        std::fs::write(&path, "---\nname: something-else\n---\n").unwrap();
        assert_eq!(skill_state(&path, &rendered), "foreign");
        assert!(install_skill(&path, &rendered).is_err());
        assert!(std::fs::read_to_string(&path)
            .unwrap()
            .contains("something-else"));
    }

    #[test]
    fn codex_skills_live_under_the_user_agents_folder() {
        let home = Path::new("/Users/me");
        assert_eq!(
            skill_path(home, "codex").unwrap(),
            PathBuf::from("/Users/me/.agents/skills/officekit/SKILL.md")
        );
        assert_eq!(
            skill_path(home, "claude-code").unwrap(),
            PathBuf::from("/Users/me/.claude/skills/officekit/SKILL.md")
        );
        assert!(skill_path(home, "unknown").is_none());
    }

    #[test]
    fn install_goes_to_each_selected_agent_that_is_on_this_mac() {
        let home = scratch("targets");
        let rendered = render_skill(Path::new("/opt/officekit-media"));
        std::fs::create_dir_all(home.join(".claude")).unwrap();
        // Codex is not on this Mac, so choosing it installs nothing there.
        let status = install_skill_targets(
            &home,
            &rendered,
            &["claude-code".to_string(), "codex".to_string()],
        )
        .unwrap();
        let targets = status["targets"].as_array().unwrap();
        assert_eq!(targets[0]["state"], "installed");
        assert_eq!(targets[1]["present"], false);
        assert_eq!(targets[1]["state"], "not-installed");
        assert!(!home.join(".agents").exists());

        std::fs::create_dir_all(home.join(".codex")).unwrap();
        let status = install_skill_targets(&home, &rendered, &["codex".to_string()]).unwrap();
        assert_eq!(status["targets"][1]["state"], "installed");
        assert!(home.join(".agents/skills/officekit/SKILL.md").is_file());
    }

    #[test]
    fn install_skips_a_foreign_skill_and_refuses_when_nothing_can_be_installed() {
        let home = scratch("foreign-target");
        let rendered = render_skill(Path::new("/opt/officekit-media"));
        let path = skill_path(&home, "codex").unwrap();
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "---\nname: something-else\n---\n").unwrap();
        assert!(install_skill_targets(&home, &rendered, &["codex".to_string()]).is_err());
        assert!(install_skill_targets(&home, &rendered, &["nope".to_string()]).is_err());
        assert!(std::fs::read_to_string(&path)
            .unwrap()
            .contains("something-else"));
        let status = skill_targets_status(&home, Some(&rendered));
        assert_eq!(status["targets"][1]["state"], "foreign");
    }

    #[test]
    fn status_is_unavailable_without_the_helper() {
        let home = scratch("nohelper");
        let status = skill_targets_status(&home, None);
        assert_eq!(status["targets"][0]["state"], "unavailable");
    }
}
