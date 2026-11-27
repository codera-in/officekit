//! Global clipboard history and snippets: native capture and picker events are forwarded to the
//! local sidecar store, and panel content is built from its responses.

use std::collections::{BTreeMap, HashMap};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use base64::Engine as _;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::global_desktop::{
    LauncherOptions, ShortcutSetting, ACTION_CLIPBOARD_HISTORY, ACTION_LAUNCHER,
    ACTION_SNIPPETS_PANEL,
};
use crate::launcher_apps::{self, InstalledApp};

const MAX_RESPONSE_BYTES: usize = 16 * 1024 * 1024;
const MAX_TITLE_CHARS: usize = 90;
const MAX_QUEUED_CAPTURES: usize = 64;
const MAX_PROMPT_ANSWER_BYTES: usize = 64 * 1024;
const MAX_CLIPBOARD_TEXT_BYTES: usize = 256 * 1024;
const BACKEND_WAIT_ATTEMPTS: usize = 120;

// ---------------------------------------------------------------------------
// Sidecar client
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Sidecar {
    pub address: SocketAddr,
    pub token: String,
}

impl Sidecar {
    pub fn request(
        &self,
        method: &str,
        path: &str,
        body: Option<&Value>,
    ) -> Result<(u16, Value), String> {
        if !self.address.ip().is_loopback()
            || !self
                .token
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
            || !path.starts_with("/api/")
            || path.bytes().any(|byte| byte <= b' ' && byte != b' ')
            || path.contains(' ')
        {
            return Err("The local store request is invalid".into());
        }
        let payload = match body {
            Some(value) => serde_json::to_vec(value)
                .map_err(|_| "The local store request is invalid".to_string())?,
            None => Vec::new(),
        };
        let mut stream = TcpStream::connect_timeout(&self.address, Duration::from_millis(500))
            .map_err(|_| "The local store is unavailable".to_string())?;
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .and_then(|_| stream.set_write_timeout(Some(Duration::from_secs(10))))
            .map_err(|_| "The local store is unavailable".to_string())?;
        write!(
            stream,
            "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            self.token,
            payload.len()
        )
        .and_then(|_| stream.write_all(&payload))
        .map_err(|_| "The local store is unavailable".to_string())?;

        let mut response = Vec::new();
        stream
            .take((MAX_RESPONSE_BYTES + 1) as u64)
            .read_to_end(&mut response)
            .map_err(|_| "The local store did not answer".to_string())?;
        if response.len() > MAX_RESPONSE_BYTES {
            return Err("The local store returned an oversized response".into());
        }
        let boundary = response
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .ok_or_else(|| "The local store returned an invalid response".to_string())?;
        let status = std::str::from_utf8(&response[..boundary])
            .ok()
            .and_then(|headers| headers.lines().next())
            .and_then(|line| line.split_whitespace().nth(1))
            .and_then(|code| code.parse::<u16>().ok())
            .ok_or_else(|| "The local store returned an invalid response".to_string())?;
        let body = &response[boundary + 4..];
        let value = if body.is_empty() {
            Value::Null
        } else {
            serde_json::from_slice(body)
                .map_err(|_| "The local store returned invalid data".to_string())?
        };
        Ok((status, value))
    }

    fn ok(&self, method: &str, path: &str, body: Option<&Value>) -> Result<Value, String> {
        match self.request(method, path, body)? {
            (200..=299, value) => Ok(value),
            // A locked app is a state, not a fault: pass the code through so the page can stay quiet
            // instead of showing "The local store rejected the request".
            (403, value) if value["error"]["code"] == "license_required" => {
                Err("license_required".into())
            }
            _ => Err("The local store rejected the request".into()),
        }
    }
}

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

// ---------------------------------------------------------------------------
// Panel content (pure)
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PanelEntry {
    Clip {
        has_image: bool,
    },
    Snippet {
        content: String,
    },
    /// A saved dictation transcript, pasted exactly as written (never rendered as a template).
    Dictation {
        text: String,
    },
    Tool {
        id: String,
    },
    /// An installed application, opened by its bundle path.
    App {
        path: String,
    },
    /// A built-in Finder command, named by one of `LAUNCHER_COMMANDS`.
    Command {
        name: String,
    },
    /// An OfficeKit action run natively: a window layout (`window.left-half`) or `quick-controls`.
    Native {
        action: String,
    },
}

/// The launcher's native action that starts a meeting recording, or stops the one in progress.
pub const MEETING_RECORDING_ACTION: &str = "meeting-recording";
/// Native rows listed with the tools besides the window layouts: meeting recording and Quick controls.
const LAUNCHER_NATIVE_EXTRAS: usize = 2;

/// Window layouts listed with the tools: layout name, title, subtitle and hidden search words.
const LAUNCHER_WINDOW_COMMANDS: [(&str, &str, &str, &str); 12] = [
    (
        "left-half",
        "Left half",
        "Move the front window to the left half of this screen",
        "snap tile window",
    ),
    (
        "right-half",
        "Right half",
        "Move the front window to the right half",
        "snap tile window",
    ),
    (
        "top-half",
        "Top half",
        "Move the front window to the top half",
        "snap tile window",
    ),
    (
        "bottom-half",
        "Bottom half",
        "Move the front window to the bottom half",
        "snap tile window",
    ),
    (
        "top-left",
        "Top left",
        "Move the front window to the top-left corner",
        "snap tile window quarter",
    ),
    (
        "top-right",
        "Top right",
        "Move the front window to the top-right corner",
        "snap tile window quarter",
    ),
    (
        "bottom-left",
        "Bottom left",
        "Move the front window to the bottom-left corner",
        "snap tile window quarter",
    ),
    (
        "bottom-right",
        "Bottom right",
        "Move the front window to the bottom-right corner",
        "snap tile window quarter",
    ),
    (
        "center",
        "Center",
        "Center the front window on this screen",
        "window middle",
    ),
    (
        "maximize",
        "Maximize",
        "Fill this screen with the front window",
        "window full bigger",
    ),
    (
        "next-display",
        "Next screen",
        "Send the front window to the next display",
        "window monitor move",
    ),
    (
        "previous-display",
        "Previous screen",
        "Send the front window to the previous display",
        "window monitor move",
    ),
];

/// Finder commands listed beside the apps: name, title, subtitle and hidden search words.
const LAUNCHER_COMMANDS: [(&str, &str, &str, &str); 2] = [
    (
        "open-trash",
        "Open Trash",
        "Show the Trash in Finder",
        "bin deleted files",
    ),
    (
        "empty-trash",
        "Empty Trash",
        "Finder asks before erasing",
        "bin delete erase permanently",
    ),
];

/// The fixed AppleScript for a launcher command. Nothing from the panel is placed in it.
fn command_script(name: &str) -> Option<&'static str> {
    match name {
        "open-trash" => Some("tell application \"Finder\"\nactivate\nopen trash\nend tell"),
        "empty-trash" => Some("tell application \"Finder\" to empty trash"),
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum PanelMode {
    #[default]
    Clipboard,
    Snippets,
    Launcher,
}

pub fn age_label(now_seconds: f64, created_seconds: f64) -> String {
    let elapsed = (now_seconds - created_seconds).max(0.0) as u64;
    match elapsed {
        0..=59 => "now".into(),
        60..=3599 => format!("{}m", elapsed / 60),
        3600..=86399 => format!("{}h", elapsed / 3600),
        _ => format!("{}d", elapsed / 86400),
    }
}

pub fn clip_title(text: &str, content_type: &str) -> String {
    if content_type == "image" {
        return "Image".into();
    }
    let collapsed = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.chars().count() > MAX_TITLE_CHARS {
        let mut title: String = collapsed.chars().take(MAX_TITLE_CHARS).collect();
        title.push('…');
        title
    } else {
        collapsed
    }
}

pub fn clip_kind(content_type: &str) -> &'static str {
    match content_type {
        "link" => "link",
        "image" => "image",
        _ => "text",
    }
}

/// Most transcripts the panel lists, and the longest one it keeps, so the in-memory handoff stays small.
const MAX_PANEL_DICTATIONS: usize = 50;
const MAX_DICTATION_PANEL_CHARS: usize = 20_000;

/// One saved transcript handed over by the main window. Held in memory only.
#[derive(Clone, Debug, PartialEq)]
pub struct PanelDictation {
    pub id: String,
    pub text: String,
    /// Seconds since the Unix epoch.
    pub created_at: f64,
}

static PANEL_DICTATIONS: std::sync::Mutex<Vec<PanelDictation>> = std::sync::Mutex::new(Vec::new());

/// Keeps the newest transcripts with a valid id and non-blank text; text is cut to a bounded length.
pub fn sanitize_dictations(mut items: Vec<PanelDictation>) -> Vec<PanelDictation> {
    items.retain(|item| valid_id(&item.id) && !item.text.trim().is_empty());
    items.sort_by(|a, b| b.created_at.total_cmp(&a.created_at));
    items.truncate(MAX_PANEL_DICTATIONS);
    for item in &mut items {
        if item.text.chars().count() > MAX_DICTATION_PANEL_CHARS {
            item.text = item.text.chars().take(MAX_DICTATION_PANEL_CHARS).collect();
        }
    }
    items
}

/// The main window hands over its recent transcripts; they stay in memory and are never stored or logged.
#[tauri::command]
pub fn global_panel_set_dictations(items: Vec<serde_json::Value>) {
    let parsed = items
        .iter()
        .take(MAX_PANEL_DICTATIONS * 2)
        .filter_map(|item| {
            Some(PanelDictation {
                id: item["id"].as_str()?.to_string(),
                text: item["text"].as_str()?.to_string(),
                created_at: item["createdAt"].as_f64().unwrap_or(0.0) / 1000.0,
            })
        })
        .collect();
    if let Ok(mut held) = PANEL_DICTATIONS.lock() {
        *held = sanitize_dictations(parsed);
    }
}

/// Adds the Dictation rows to a clipboard panel and registers them for pasting.
pub fn add_dictations(
    panel: &mut Value,
    entries: &mut HashMap<String, PanelEntry>,
    dictations: &[PanelDictation],
    now_seconds: f64,
) {
    let mut rows = Vec::new();
    for dictation in dictations {
        let id = format!("dictation-{}", dictation.id);
        if !valid_id(&id) {
            continue;
        }
        entries.insert(
            id.clone(),
            PanelEntry::Dictation {
                text: dictation.text.clone(),
            },
        );
        rows.push(json!({
            "id": id,
            "title": clip_title(&dictation.text, "text"),
            "subtitle": "Dictation",
            "badge": age_label(now_seconds, dictation.created_at),
            "kind": "dictation",
            "pinned": false,
        }));
    }
    if let Some(chips) = panel["chips"].as_array_mut() {
        chips.push(json!({"id": "dictation", "label": "Dictation"}));
    }
    if let Some(items) = panel["items"].as_array_mut() {
        items.extend(rows);
    }
    panel["readOnlyChips"] = json!(["dictation"]);
}

fn held_dictations() -> Vec<PanelDictation> {
    PANEL_DICTATIONS
        .lock()
        .map(|held| held.clone())
        .unwrap_or_default()
}

/// Builds the picker JSON and the lookup table for the clipboard history panel.
pub fn clips_panel(history: &Value, now_seconds: f64) -> (Value, HashMap<String, PanelEntry>) {
    let mut entries = HashMap::new();
    let mut items = Vec::new();
    for clip in history["clips"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or(&[])
    {
        let Some(id) = clip["id"].as_str().filter(|id| valid_id(id)) else {
            continue;
        };
        let content_type = clip["content_type"].as_str().unwrap_or("text");
        let has_image = content_type == "image"
            || clip["has_image"].as_i64().unwrap_or(0) == 1
            || clip["image_data"]
                .as_str()
                .is_some_and(|data| !data.is_empty());
        entries.insert(id.to_string(), PanelEntry::Clip { has_image });
        items.push(json!({
            "id": id,
            "title": clip_title(clip["text_content"].as_str().unwrap_or(""), content_type),
            "subtitle": clip["source_app"].as_str().unwrap_or(""),
            "badge": age_label(now_seconds, clip["created_at"].as_f64().unwrap_or(now_seconds)),
            "kind": clip_kind(content_type),
            "pinned": clip["pinned"].as_i64().unwrap_or(0) == 1,
        }));
    }
    let panel = json!({
        "title": "Clipboard history",
        "placeholder": "Search clipboard history",
        "chips": [
            {"id": "all", "label": "All"},
            {"id": "text", "label": "Text"},
            {"id": "image", "label": "Images"},
            {"id": "link", "label": "Links"},
            {"id": "pinned", "label": "Pinned"},
        ],
        "items": items,
    });
    (panel, entries)
}

/// Builds the picker JSON and the lookup table for the snippets panel; folders become filter chips.
pub fn snippets_panel(snippets: &Value, folders: &Value) -> (Value, HashMap<String, PanelEntry>) {
    let mut entries = HashMap::new();
    let mut items = Vec::new();
    for snippet in snippets["snippets"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or(&[])
        .iter()
        // The native picker refuses more than 500 rows.
        .take(500)
    {
        let Some(id) = snippet["id"].as_str().filter(|id| valid_id(id)) else {
            continue;
        };
        entries.insert(
            id.to_string(),
            PanelEntry::Snippet {
                content: snippet["content"].as_str().unwrap_or("").to_string(),
            },
        );
        items.push(json!({
            "id": id,
            "title": clip_title(snippet["title"].as_str().unwrap_or(""), "text"),
            "subtitle": snippet["trigger_key"].as_str().unwrap_or(""),
            "badge": snippet["folder_name"].as_str().unwrap_or(""),
            "kind": snippet["folder_id"].as_str().unwrap_or("default"),
            "pinned": false,
        }));
    }
    let mut chips = vec![json!({"id": "all", "label": "All"})];
    for folder in folders["folders"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or(&[])
    {
        if let (Some(id), Some(name)) = (folder["id"].as_str(), folder["name"].as_str()) {
            if valid_id(id) && id != "all" && id != "pinned" && chips.len() < 12 {
                chips.push(json!({"id": id, "label": clip_title(name, "text")}));
            }
        }
    }
    let panel = json!({
        "title": "Snippets",
        "placeholder": "Search snippets by name or keyword",
        "chips": chips,
        "items": items,
    });
    (panel, entries)
}

/// Everything the launcher panel lists, besides the OfficeKit tools and snippets it is given.
pub struct LauncherSources<'a> {
    pub apps: &'a [InstalledApp],
    /// Item keys opened recently, newest first; they sort ahead of the rest.
    pub recent: &'a [String],
    pub filters: &'a BTreeMap<String, ShortcutSetting>,
    /// Which result kinds are listed and which quick-result rows the native panel may compute.
    pub options: LauncherOptions,
}

const LAUNCHER_ITEM_LIMIT: usize = 1000;
const MAX_RECENT_LAUNCHES: usize = 20;

/// Asks the worker to re-read settings after `delay`, so a timed pause ends on time without polling.
fn schedule_refresh_after(delay: Duration) {
    let _ = std::thread::Builder::new()
        .name("officekit-clipboard-pause".into())
        .spawn(move || {
            std::thread::sleep(delay + Duration::from_millis(100));
            send(Event::Refresh);
        });
}

/// Tool ids the web layer opened recently, newest first, so the launcher can list them first.
static WEB_RECENT_TOOLS: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

fn is_tool_id(id: &str) -> bool {
    let mut chars = id.chars();
    id.len() <= 120
        && chars
            .next()
            .is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        && chars
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '.' | '_' | '-'))
}

/// Replaces the web layer's recent tool list; ids that are not tool ids are dropped.
fn set_web_recent_tools(ids: &[String]) {
    let valid: Vec<String> = ids
        .iter()
        .filter(|id| is_tool_id(id))
        .take(MAX_RECENT_LAUNCHES)
        .cloned()
        .collect();
    if let Ok(mut recent) = WEB_RECENT_TOOLS.lock() {
        *recent = valid;
    }
}

/// Recent launcher keys, newest first: what was launched natively, then tools opened in the app.
fn combined_recent(native: &[String]) -> Vec<String> {
    let mut combined: Vec<String> = native.to_vec();
    if let Ok(web) = WEB_RECENT_TOOLS.lock() {
        for id in web.iter() {
            let key = format!("tool-{id}");
            if !combined.contains(&key) {
                combined.push(key);
            }
        }
    }
    combined
}

/// The web layer reports the tools the user opened most recently.
#[tauri::command]
pub fn launcher_recent_tools(ids: Vec<String>) {
    set_web_recent_tools(&ids);
}

/// Lookup key for an application: stable between opens so recency can follow it.
fn app_key(name: &str, taken: &HashMap<String, PanelEntry>) -> String {
    let slug: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .take(100)
        .collect();
    let mut key = format!("app-{slug}");
    let mut suffix = 2;
    while taken.contains_key(&key) {
        key = format!("app-{slug}-{suffix}");
        suffix += 1;
    }
    key
}

/// "tool|<catalog icon>|<category>" so the native row can draw the tool's own symbol in its
/// category colour. A missing or odd icon name or category keeps the plain "tool" wrench.
fn tool_icon(icon: Option<&str>, category: &str) -> String {
    let icon_ok = |name: &str| {
        !name.is_empty()
            && name.len() <= 48
            && name
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
    };
    match icon {
        Some(name) if icon_ok(name) && !category.contains('|') && category.len() <= 64 => {
            format!("tool|{name}|{category}")
        }
        _ => "tool".to_string(),
    }
}

/// Builds the launcher panel: installed applications and Mac tools (Finder commands) first, then
/// OfficeKit tools, then snippets. Recently opened rows come before all of them, and the panel
/// keeps that order for ties when it ranks matches, so a Mac app wins a tie with a tool.
pub fn launcher_panel(
    tools: &Value,
    snippets: &Value,
    sources: &LauncherSources,
) -> (Value, HashMap<String, PanelEntry>) {
    let mut entries = HashMap::new();
    let mut items = Vec::new();
    // Tools are collected here and listed after the Mac apps and commands.
    let mut tool_items = Vec::new();
    let options = &sources.options;
    let tool_limit = if options.tools { 300 } else { 0 };
    for tool in tools["tools"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or(&[])
        .iter()
        .take(tool_limit)
    {
        let Some(id) = tool["id"].as_str().filter(|id| valid_id(id)) else {
            continue;
        };
        let name = tool["name"].as_str().unwrap_or("");
        if name.is_empty() {
            continue;
        }
        // Tool, application and snippet ids share one lookup table, so tools get their own prefix.
        let key = format!("tool-{id}");
        entries.insert(key.clone(), PanelEntry::Tool { id: id.to_string() });
        let category = tool["category"].as_str().unwrap_or("");
        let description = clip_title(tool["desc"].as_str().unwrap_or(""), "text");
        // Search aliases ("compress image") stay hidden but make the tool findable.
        let keywords = tool["keywords"]
            .as_array()
            .map(|words| {
                words
                    .iter()
                    .filter_map(Value::as_str)
                    .take(24)
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default();
        let searchable = format!("{description} {keywords}").trim().to_string();
        tool_items.push(json!({
            "id": key,
            "title": clip_title(name, "text"),
            "subtitle": if category.is_empty() { description.as_str() } else { category },
            // Not shown in the launcher, but searchable.
            "badge": searchable,
            "kind": "tool",
            "icon": tool_icon(tool["icon"].as_str(), category),
            "pinned": false,
        }));
    }
    let apps: &[InstalledApp] = if options.apps { sources.apps } else { &[] };
    for app in apps {
        let key = app_key(&app.name, &entries);
        entries.insert(
            key.clone(),
            PanelEntry::App {
                path: app.path.clone(),
            },
        );
        items.push(json!({
            "id": key,
            "title": clip_title(&app.name, "text"),
            "subtitle": app.path,
            "badge": "",
            "kind": "app",
            "icon": format!("app:{}", app.path),
            "pinned": false,
        }));
    }
    // Finder commands are listed with the applications.
    let commands: &[(&str, &str, &str, &str)] = if options.apps {
        &LAUNCHER_COMMANDS
    } else {
        &[]
    };
    for &(name, title, subtitle, words) in commands {
        let key = format!("command-{name}");
        entries.insert(
            key.clone(),
            PanelEntry::Command {
                name: name.to_string(),
            },
        );
        items.push(json!({
            "id": key,
            "title": title,
            "subtitle": subtitle,
            "badge": words,
            "kind": "command",
            "icon": format!("command-{name}"),
            "pinned": false,
        }));
    }
    items.extend(tool_items);
    let listed_snippets = if options.snippets {
        snippets
    } else {
        &Value::Null
    };
    let (snippet_panel, snippet_entries) = snippets_panel(listed_snippets, &Value::Null);
    for item in snippet_panel["items"]
        .as_array()
        .cloned()
        .unwrap_or_default()
    {
        if items.len() >= LAUNCHER_ITEM_LIMIT {
            break;
        }
        let mut item = item;
        let trigger = item["subtitle"].as_str().unwrap_or("").to_string();
        let folder = item["badge"].as_str().unwrap_or("").to_string();
        item["subtitle"] = json!([trigger, folder]
            .iter()
            .filter(|part| !part.is_empty())
            .cloned()
            .collect::<Vec<_>>()
            .join(" · "));
        item["badge"] = json!("");
        item["kind"] = json!("snippet");
        item["icon"] = json!("snippet");
        items.push(item);
    }
    // The window layouts and Quick controls below always fit inside the native item limit.
    let native_rows = if options.tools {
        LAUNCHER_WINDOW_COMMANDS.len() + LAUNCHER_NATIVE_EXTRAS
    } else {
        0
    };
    items.truncate(LAUNCHER_ITEM_LIMIT - native_rows);
    entries.extend(snippet_entries);
    // Window layouts and the Quick controls panel sit with the tools.
    if options.tools {
        for (layout, title, subtitle, words) in LAUNCHER_WINDOW_COMMANDS {
            let key = format!("command-window-{layout}");
            entries.insert(
                key.clone(),
                PanelEntry::Native {
                    action: crate::window_manager::action_name(layout),
                },
            );
            items.push(json!({
                "id": key,
                "title": title,
                "subtitle": subtitle,
                "badge": words,
                "kind": "command",
                "icon": "command-window",
                "pinned": false,
            }));
        }
        entries.insert(
            "native-meeting-recording".to_string(),
            PanelEntry::Native {
                action: MEETING_RECORDING_ACTION.into(),
            },
        );
        items.push(json!({
            "id": "native-meeting-recording",
            "title": "Start or stop meeting recording",
            "subtitle": "Records the microphone for meeting notes, or stops the recording in progress",
            "badge": "record meeting notes transcript toggle",
            "kind": "tool",
            "icon": "tool",
            "pinned": false,
        }));
        entries.insert(
            "native-quick-controls".to_string(),
            PanelEntry::Native {
                action: "quick-controls".into(),
            },
        );
        items.push(json!({
            "id": "native-quick-controls",
            "title": "OfficeKit Quick controls",
            "subtitle": "Switch Speech, Desktop and menu bar tools on or off",
            "badge": "control center switches settings toggle",
            "kind": "tool",
            "icon": "tool",
            "pinned": false,
        }));
    }
    // Recent rows first, newest first; everything else keeps its order.
    let rank = |item: &Value| {
        let id = item["id"].as_str().unwrap_or("");
        sources
            .recent
            .iter()
            .position(|recent| recent == id)
            .unwrap_or(usize::MAX)
    };
    items.sort_by_key(rank);
    // Say why a row is up here.
    for item in items.iter_mut() {
        if rank(item) != usize::MAX {
            let subtitle = item["subtitle"].as_str().unwrap_or("").to_string();
            item["subtitle"] = json!(if subtitle.is_empty() {
                "Recent".to_string()
            } else {
                format!("Recent · {subtitle}")
            });
        }
    }
    let chip = |id: &str, label: &str| {
        let mut chip = json!({"id": id, "label": label});
        if let Some(shortcut) = sources.filters.get(id) {
            chip["keyCode"] = json!(shortcut.key_code);
            chip["modifierMask"] = json!(shortcut.modifier_mask);
        }
        chip
    };
    // A chip is shown only for a kind the launcher lists; "All" is always there.
    let mut chips = vec![chip("all", "All")];
    if options.apps {
        chips.push(chip("app", "Apps"));
    }
    if options.tools {
        chips.push(chip("tool", "Tools"));
    }
    if options.snippets {
        chips.push(chip("snippet", "Snippets"));
    }
    let panel = json!({
        "style": "launcher",
        "title": "Launcher",
        "placeholder": "Search apps, tools and snippets",
        "chips": chips,
        // The native panel computes these rows itself, so only their switches cross the boundary.
        "quickResults": {
            "calculator": options.calculator,
            "uuid": options.uuid,
            "password": options.password,
            "passwordLength": options.password_length,
            "passwordSymbols": options.password_symbols,
        },
        "items": items,
    });
    (panel, entries)
}

/// Moves `key` to the front of the recent list, dropping repeats and the oldest beyond the limit.
fn remember_launch(recent: &mut Vec<String>, key: &str) {
    recent.retain(|known| known != key);
    recent.insert(0, key.to_string());
    recent.truncate(MAX_RECENT_LAUNCHES);
}

/// Names of `{{variable}}` placeholders that need typed input (everything but the built-ins).
pub fn template_prompt_variables(template: &str) -> Vec<String> {
    let mut names: Vec<String> = Vec::new();
    let mut rest = template;
    while let Some(start) = rest.find("{{") {
        let after = &rest[start + 2..];
        let Some(end) = after.find("}}") else { break };
        let name = &after[..end];
        let valid = !name.is_empty()
            && name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b':' | b'-'));
        if valid {
            let lower = name.to_ascii_lowercase();
            let builtin = lower == "date"
                || lower.starts_with("date:")
                || lower == "time"
                || lower.starts_with("time:")
                || lower == "clipboard"
                || lower == "uuid";
            if !builtin && !names.iter().any(|existing| existing == name) {
                names.push(name.to_string());
            }
            rest = &after[end + 2..];
        } else {
            rest = &rest[start + 2..];
        }
    }
    names
}

pub fn template_uses_clipboard(template: &str) -> bool {
    template.to_ascii_lowercase().contains("{{clipboard}}")
}

/// Keywords that can expand without asking for input, mapped to their snippet template.
pub fn expansion_table(snippets: &Value) -> HashMap<String, String> {
    let mut table = HashMap::new();
    for snippet in snippets["snippets"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or(&[])
    {
        let trigger = snippet["trigger_key"].as_str().unwrap_or("").trim();
        let content = snippet["content"].as_str().unwrap_or("");
        // Imported snippets skip the editor's keyword rules, so the shape is checked again here.
        if trigger.chars().count() < 2
            || trigger.chars().count() > 32
            || trigger.chars().any(char::is_whitespace)
            || content.is_empty()
            || !template_prompt_variables(content).is_empty()
        {
            continue;
        }
        table.insert(trigger.to_string(), content.to_string());
    }
    table
}

// ---------------------------------------------------------------------------
// Native bridge
// ---------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod native {
    #[allow(dead_code)]
    unsafe extern "C" {
        fn officekit_global_panel_set_callback(callback: extern "C" fn(*const u8, u64, i32));
        fn officekit_global_panel_show(bytes: *const u8, length: u64) -> i32;
        fn officekit_global_panel_update(bytes: *const u8, length: u64) -> i32;
        fn officekit_global_panel_target_pid() -> i32;
        fn officekit_global_clipboard_set_callback(
            callback: extern "C" fn(i32, *const u8, u64, *const u8, u64, *const u8, u64),
        );
        fn officekit_global_clipboard_start(bytes: *const u8, length: u64) -> i32;
        fn officekit_global_clipboard_stop();
        fn officekit_global_clipboard_text(output: *mut u8, capacity: u64) -> i64;
        fn officekit_global_paste(kind: i32, bytes: *const u8, length: u64, target_pid: i32)
            -> i32;
        fn officekit_global_prompt(
            bytes: *const u8,
            length: u64,
            target_pid: i32,
            output: *mut u8,
            capacity: u64,
        ) -> i64;
        fn officekit_global_keywords_set_callback(callback: extern "C" fn(*const u8, u64));
        fn officekit_global_keywords_configure(bytes: *const u8, length: u64, enabled: i32) -> i32;
        fn officekit_global_expand(
            trigger: *const u8,
            trigger_length: u64,
            text: *const u8,
            text_length: u64,
        ) -> i32;
    }

    pub fn set_panel_callback(callback: extern "C" fn(*const u8, u64, i32)) {
        unsafe { officekit_global_panel_set_callback(callback) }
    }
    pub fn set_capture_callback(
        callback: extern "C" fn(i32, *const u8, u64, *const u8, u64, *const u8, u64),
    ) {
        unsafe { officekit_global_clipboard_set_callback(callback) }
    }
    pub fn set_keyword_callback(callback: extern "C" fn(*const u8, u64)) {
        unsafe { officekit_global_keywords_set_callback(callback) }
    }
    pub fn panel_show(json: &[u8]) -> bool {
        unsafe { officekit_global_panel_show(json.as_ptr(), json.len() as u64) == 0 }
    }
    pub fn panel_update(json: &[u8]) -> bool {
        unsafe { officekit_global_panel_update(json.as_ptr(), json.len() as u64) == 0 }
    }
    pub fn panel_target_pid() -> i32 {
        unsafe { officekit_global_panel_target_pid() }
    }
    pub fn capture_start(skip_json: &[u8]) -> i32 {
        unsafe { officekit_global_clipboard_start(skip_json.as_ptr(), skip_json.len() as u64) }
    }
    pub fn capture_stop() {
        unsafe { officekit_global_clipboard_stop() }
    }
    pub fn clipboard_text(capacity: usize) -> Option<String> {
        let mut buffer = vec![0u8; capacity];
        let written =
            unsafe { officekit_global_clipboard_text(buffer.as_mut_ptr(), capacity as u64) };
        let length = usize::try_from(written).ok()?;
        buffer.truncate(length);
        String::from_utf8(buffer).ok()
    }
    pub fn paste(kind: i32, payload: &[u8], target_pid: i32) -> i32 {
        unsafe { officekit_global_paste(kind, payload.as_ptr(), payload.len() as u64, target_pid) }
    }
    /// Some(answer JSON) when answered, None when cancelled or unavailable.
    pub fn prompt(names_json: &[u8], target_pid: i32, capacity: usize) -> Option<Vec<u8>> {
        let mut buffer = vec![0u8; capacity];
        let written = unsafe {
            officekit_global_prompt(
                names_json.as_ptr(),
                names_json.len() as u64,
                target_pid,
                buffer.as_mut_ptr(),
                capacity as u64,
            )
        };
        let length = usize::try_from(written).ok()?;
        buffer.truncate(length);
        Some(buffer)
    }
    pub fn keywords_configure(triggers_json: &[u8], enabled: bool) -> i32 {
        unsafe {
            officekit_global_keywords_configure(
                triggers_json.as_ptr(),
                triggers_json.len() as u64,
                i32::from(enabled),
            )
        }
    }
    pub fn expand(trigger: &str, text: &str) -> i32 {
        unsafe {
            officekit_global_expand(
                trigger.as_ptr(),
                trigger.len() as u64,
                text.as_ptr(),
                text.len() as u64,
            )
        }
    }
}

#[cfg(not(target_os = "macos"))]
mod native {
    pub fn set_panel_callback(_callback: extern "C" fn(*const u8, u64, i32)) {}
    pub fn set_capture_callback(
        _callback: extern "C" fn(i32, *const u8, u64, *const u8, u64, *const u8, u64),
    ) {
    }
    pub fn set_keyword_callback(_callback: extern "C" fn(*const u8, u64)) {}
    pub fn panel_show(_json: &[u8]) -> bool {
        false
    }
    pub fn panel_update(_json: &[u8]) -> bool {
        false
    }
    pub fn panel_target_pid() -> i32 {
        0
    }
    pub fn capture_start(_skip_json: &[u8]) -> i32 {
        3
    }
    pub fn capture_stop() {}
    pub fn clipboard_text(_capacity: usize) -> Option<String> {
        None
    }
    pub fn paste(_kind: i32, _payload: &[u8], _target_pid: i32) -> i32 {
        3
    }
    pub fn prompt(_names_json: &[u8], _target_pid: i32, _capacity: usize) -> Option<Vec<u8>> {
        None
    }
    pub fn keywords_configure(_triggers_json: &[u8], _enabled: bool) -> i32 {
        3
    }
    pub fn expand(_trigger: &str, _text: &str) -> i32 {
        3
    }
}

// ---------------------------------------------------------------------------
// Worker
// ---------------------------------------------------------------------------

enum Event {
    Action(String),
    Panel { id: String, action: i32 },
    Capture(Captured),
    Keyword(String),
    Refresh,
}

struct Captured {
    kind: i32,
    payload: Vec<u8>,
    bundle_id: Option<String>,
    app_name: Option<String>,
}

static EVENTS: OnceLock<Mutex<Sender<Event>>> = OnceLock::new();
static QUEUED_CAPTURES: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn send(event: Event) -> bool {
    EVENTS
        .get()
        .and_then(|sender| sender.lock().ok())
        .is_some_and(|sender| sender.send(event).is_ok())
}

/// The saved-settings change that switches clipboard history on or off. Off is an open-ended pause,
/// the same one the menu-bar item offers: capture stops and everything already saved stays.
fn history_settings_body(enabled: bool) -> Value {
    if enabled {
        json!({"capture_enabled": true, "capture_pause": "off"})
    } else {
        json!({"capture_pause": "until_resume"})
    }
}

/// Whether the saved settings are capturing what you copy.
fn history_is_on(settings: &Value) -> bool {
    settings["capture_enabled"].as_bool().unwrap_or(true)
        && !settings["capture_paused"].as_bool().unwrap_or(false)
}

fn app_sidecar(app: &AppHandle) -> Result<Sidecar, String> {
    let address = app
        .try_state::<crate::BackendApiAddress>()
        .ok_or("Clipboard history is starting. Try again in a moment.")?
        .0;
    let token = app
        .try_state::<crate::BackendApiToken>()
        .ok_or("Clipboard history is starting. Try again in a moment.")?
        .0
        .clone();
    Ok(Sidecar { address, token })
}

/// Clipboard history as Quick controls shows it; unavailable reads as off.
pub fn history_enabled(app: &AppHandle) -> bool {
    app_sidecar(app)
        .and_then(|sidecar| sidecar.ok("GET", "/api/clipboard/global-settings", None))
        .map(|value| history_is_on(&value["settings"]))
        .unwrap_or(false)
}

/// Switches clipboard history on or off and tells the watcher right away.
pub fn set_history_enabled(app: &AppHandle, enabled: bool) -> Result<(), String> {
    app_sidecar(app)?
        .ok(
            "POST",
            "/api/clipboard/global-settings",
            Some(&history_settings_body(enabled)),
        )
        .map_err(|_| "Clipboard history could not be changed".to_string())?;
    send(Event::Refresh);
    Ok(())
}

unsafe fn slice_from<'a>(bytes: *const u8, length: u64) -> &'a [u8] {
    if bytes.is_null() || length == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(bytes, length as usize) }
    }
}

extern "C" fn on_panel_event(bytes: *const u8, length: u64, action: i32) {
    let id = unsafe { slice_from(bytes, length) };
    if id.len() <= 128 {
        if let Ok(id) = std::str::from_utf8(id) {
            send(Event::Panel {
                id: id.to_string(),
                action,
            });
        }
    }
}

extern "C" fn on_capture(
    kind: i32,
    payload: *const u8,
    payload_length: u64,
    bundle: *const u8,
    bundle_length: u64,
    name: *const u8,
    name_length: u64,
) {
    use std::sync::atomic::Ordering;
    if QUEUED_CAPTURES.load(Ordering::Relaxed) >= MAX_QUEUED_CAPTURES {
        return;
    }
    let text = |bytes, length| {
        std::str::from_utf8(unsafe { slice_from(bytes, length) })
            .ok()
            .filter(|value| !value.is_empty())
            .map(str::to_string)
    };
    QUEUED_CAPTURES.fetch_add(1, Ordering::Relaxed);
    let queued = send(Event::Capture(Captured {
        kind,
        payload: unsafe { slice_from(payload, payload_length) }.to_vec(),
        bundle_id: text(bundle, bundle_length),
        app_name: text(name, name_length),
    }));
    if !queued {
        QUEUED_CAPTURES.fetch_sub(1, Ordering::Relaxed);
    }
}

extern "C" fn on_keyword(bytes: *const u8, length: u64) {
    if let Ok(trigger) = std::str::from_utf8(unsafe { slice_from(bytes, length) }) {
        send(Event::Keyword(trigger.to_string()));
    }
}

/// Installs the native callbacks and starts the worker that talks to the sidecar.
pub fn start(app: &AppHandle) {
    let (sender, receiver) = mpsc::channel();
    if EVENTS.set(Mutex::new(sender)).is_err() {
        return;
    }
    native::set_panel_callback(on_panel_event);
    native::set_capture_callback(on_capture);
    native::set_keyword_callback(on_keyword);
    let app = app.clone();
    let _ = std::thread::Builder::new()
        .name("officekit-global-clipboard".into())
        .spawn(move || Worker::new(app).run(receiver));
}

/// Opens the clipboard or snippets panel for a fired shortcut action.
pub fn handle_action(action: &str) {
    send(Event::Action(action.to_string()));
}

/// Re-reads capture settings and snippet keywords and applies them to the native monitors.
pub fn request_refresh() {
    send(Event::Refresh);
}

/// Set while capture is paused, so a capture already in the queue is dropped as well.
static CAPTURE_PAUSED: AtomicBool = AtomicBool::new(false);

/// A timed pause is at most one hour, so a clock jump cannot leave capture off for long.
const MAX_PAUSE_WAIT_SECONDS: f64 = 3600.0;

/// The clipboard panel chip that opens first, for the saved "Panel opens on" choice.
pub fn panel_start_chip(choice: &str) -> &'static str {
    match choice {
        "all" => "all",
        "images" => "image",
        "links" => "link",
        "pinned" => "pinned",
        _ => "text",
    }
}

/// Apps whose copies and typing are never captured: the clipboard list plus the user's
/// "Skip these apps" setting, matched without regard to case and without duplicates.
pub fn capture_skip_list(clipboard_skip: &Value, desktop_skip: &[String]) -> Vec<String> {
    let mut skip: Vec<String> = Vec::new();
    let clipboard = clipboard_skip
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str);
    for id in clipboard.chain(desktop_skip.iter().map(String::as_str)) {
        let id = id.trim();
        let valid = !id.is_empty()
            && id.len() <= 255
            && id
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'));
        if valid && !skip.iter().any(|known| known.eq_ignore_ascii_case(id)) {
            skip.push(id.to_string());
        }
    }
    skip
}

/// How long until a timed capture pause ends; None once it has ended or the end is not a finite time.
pub fn pause_remaining(paused_until: f64, now: f64) -> Option<Duration> {
    let remaining = paused_until - now;
    if !remaining.is_finite() || remaining <= 0.0 {
        return None;
    }
    Some(Duration::from_secs_f64(
        remaining.min(MAX_PAUSE_WAIT_SECONDS),
    ))
}

struct Worker {
    app: AppHandle,
    mode: PanelMode,
    entries: HashMap<String, PanelEntry>,
    keywords: HashMap<String, String>,
    /// Launcher rows opened this session, newest first. Kept in memory only.
    recent: Vec<String>,
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs_f64())
        .unwrap_or(0.0)
}

impl Worker {
    fn new(app: AppHandle) -> Self {
        Self {
            app,
            mode: PanelMode::default(),
            entries: HashMap::new(),
            keywords: HashMap::new(),
            recent: Vec::new(),
        }
    }

    fn run(mut self, receiver: mpsc::Receiver<Event>) {
        self.wait_for_backend();
        self.refresh();
        while let Ok(event) = receiver.recv() {
            match event {
                Event::Action(action) => self.open_panel(&action),
                Event::Panel { id, action } => self.handle_panel(&id, action),
                Event::Capture(captured) => {
                    self.store_capture(captured);
                    QUEUED_CAPTURES.fetch_sub(1, std::sync::atomic::Ordering::Relaxed);
                }
                Event::Keyword(trigger) => self.expand(&trigger),
                Event::Refresh => self.refresh(),
            }
        }
    }

    fn sidecar(&self) -> Option<Sidecar> {
        let address = self.app.try_state::<crate::BackendApiAddress>()?.0;
        let token = self.app.try_state::<crate::BackendApiToken>()?.0.clone();
        Some(Sidecar { address, token })
    }

    fn wait_for_backend(&self) {
        for _ in 0..BACKEND_WAIT_ATTEMPTS {
            if self.sidecar().is_some_and(|sidecar| {
                sidecar
                    .request("GET", "/api/clipboard/global-settings", None)
                    .is_ok()
            }) {
                return;
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    }

    fn notice(&self, code: &str, message: &str) {
        let _ = self.app.emit(
            "global-desktop-notice",
            json!({"code": code, "message": message}),
        );
    }

    fn refresh(&mut self) {
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        let enabled = crate::global_desktop::desktop_enabled(&self.app);
        let settings = sidecar
            .ok("GET", "/api/clipboard/global-settings", None)
            .map(|value| value["settings"].clone())
            .unwrap_or(Value::Null);
        // A pause stops the watcher but keeps saved history; a timed pause wakes the worker when it ends.
        let paused = settings["capture_paused"].as_bool().unwrap_or(false);
        CAPTURE_PAUSED.store(paused, Ordering::Relaxed);
        if let Some(remaining) = settings["capture_paused_until"]
            .as_f64()
            .filter(|_| paused)
            .and_then(|until| pause_remaining(until, now_seconds()))
        {
            schedule_refresh_after(remaining);
        }
        crate::workspace_native::set_clipboard_paused_menu(&self.app, paused);
        let capture = enabled && !paused && settings["capture_enabled"].as_bool().unwrap_or(false);
        if capture {
            let skip = serde_json::to_vec(&capture_skip_list(
                &settings["skip_bundle_ids"],
                &crate::global_desktop::skip_apps(&self.app),
            ))
            .unwrap_or_else(|_| b"[]".to_vec());
            native::capture_start(&skip);
        } else {
            native::capture_stop();
        }
        let snippets = sidecar
            .ok("GET", "/api/clipboard/snippets", None)
            .unwrap_or(Value::Null);
        self.keywords = expansion_table(&snippets);
        let triggers: Vec<&String> = self.keywords.keys().collect();
        let expansion = enabled && settings["expansion_enabled"].as_bool().unwrap_or(false);
        let code = native::keywords_configure(
            &serde_json::to_vec(&triggers).unwrap_or_else(|_| b"[]".to_vec()),
            expansion,
        );
        if code == 1 {
            self.notice(
                "accessibility",
                "Allow Accessibility access so snippet keywords can expand in other apps.",
            );
        }
    }

    fn store_capture(&self, captured: Captured) {
        if CAPTURE_PAUSED.load(Ordering::Relaxed) {
            return;
        }
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        let mut body = json!({
            "source_app": captured.app_name,
            "source_bundle_id": captured.bundle_id,
        });
        if captured.kind == 1 {
            body["text_content"] = json!("");
            body["content_type"] = json!("image");
            body["image_data"] =
                json!(base64::engine::general_purpose::STANDARD.encode(&captured.payload));
        } else if let Ok(text) = String::from_utf8(captured.payload) {
            body["text_content"] = json!(text);
        } else {
            return;
        }
        let _ = sidecar.request("POST", "/api/clipboard/clips", Some(&body));
    }

    fn open_panel(&mut self, action: &str) {
        let Some(sidecar) = self.sidecar() else {
            self.notice(
                "store-unavailable",
                "The local clipboard store is not ready yet.",
            );
            return;
        };
        let built = if action == ACTION_CLIPBOARD_HISTORY {
            self.mode = PanelMode::Clipboard;
            sidecar
                .ok(
                    "GET",
                    "/api/clipboard/history?limit=100&include_images=false",
                    None,
                )
                .map(|history| {
                    let (mut panel, mut entries) = clips_panel(&history, now_seconds());
                    add_dictations(&mut panel, &mut entries, &held_dictations(), now_seconds());
                    let choice = sidecar
                        .ok("GET", "/api/clipboard/global-settings", None)
                        .ok()
                        .and_then(|value| {
                            value["settings"]["panel_default_filter"]
                                .as_str()
                                .map(str::to_string)
                        })
                        .unwrap_or_else(|| "text".to_string());
                    panel["initialChip"] = json!(panel_start_chip(&choice));
                    (panel, entries)
                })
        } else if action == ACTION_SNIPPETS_PANEL {
            self.mode = PanelMode::Snippets;
            sidecar
                .ok("GET", "/api/clipboard/snippets", None)
                .and_then(|snippets| {
                    let folders = sidecar
                        .ok("GET", "/api/clipboard/folders", None)
                        .unwrap_or(Value::Null);
                    Ok(snippets_panel(&snippets, &folders))
                })
        } else if action == ACTION_LAUNCHER {
            self.mode = PanelMode::Launcher;
            sidecar
                .ok("GET", "/api/tools/search?q=", None)
                .and_then(|tools| {
                    let snippets = sidecar
                        .ok("GET", "/api/clipboard/snippets", None)
                        .unwrap_or(Value::Null);
                    let home = self.app.path().home_dir().ok();
                    let apps = launcher_apps::installed_apps(home.as_deref());
                    let filters = crate::global_desktop::launcher_filters(&self.app);
                    let recent = combined_recent(&self.recent);
                    let sources = LauncherSources {
                        apps: &apps,
                        recent: &recent,
                        filters: &filters,
                        options: crate::global_desktop::launcher_options(&self.app),
                    };
                    Ok(launcher_panel(&tools, &snippets, &sources))
                })
        } else {
            return;
        };
        match built {
            Ok((panel, entries)) => {
                self.entries = entries;
                if let Ok(bytes) = serde_json::to_vec(&panel) {
                    native::panel_show(&bytes);
                }
            }
            Err(message) => self.notice("store-unavailable", &message),
        }
    }

    fn refresh_panel(&mut self) {
        // Only clipboard clips can be pinned or deleted from the panel; snippets are edited in the app.
        if self.mode != PanelMode::Clipboard {
            return;
        }
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        if let Ok(history) = sidecar.ok(
            "GET",
            "/api/clipboard/history?limit=100&include_images=false",
            None,
        ) {
            let (mut panel, mut entries) = clips_panel(&history, now_seconds());
            add_dictations(&mut panel, &mut entries, &held_dictations(), now_seconds());
            self.entries = entries;
            if let Ok(bytes) = serde_json::to_vec(&panel) {
                native::panel_update(&bytes);
            }
        }
    }

    fn handle_panel(&mut self, id: &str, action: i32) {
        if !valid_id(id) {
            return;
        }
        let Some(entry) = self.entries.get(id).cloned() else {
            return;
        };
        let target = native::panel_target_pid();
        match (entry, action) {
            (PanelEntry::Clip { has_image }, 0 | 1) => self.paste_clip(id, has_image, target),
            (PanelEntry::Clip { .. }, 2) => {
                if let Some(sidecar) = self.sidecar() {
                    let _ = sidecar.request(
                        "POST",
                        &format!("/api/clipboard/clips/{id}/pin"),
                        Some(&json!({})),
                    );
                }
                self.refresh_panel();
            }
            (PanelEntry::Clip { .. }, 3) => {
                if let Some(sidecar) = self.sidecar() {
                    let _ = sidecar.request("DELETE", &format!("/api/clipboard/clips/{id}"), None);
                }
                self.refresh_panel();
            }
            (PanelEntry::Snippet { content }, 0 | 1) => self.insert_snippet(&content, target),
            (PanelEntry::Dictation { text }, 0 | 1) => {
                self.report_paste(native::paste(0, text.as_bytes(), target));
            }
            (PanelEntry::Tool { id: tool }, 0 | 1) => {
                remember_launch(&mut self.recent, id);
                self.open_tool(&tool);
            }
            (PanelEntry::App { path }, 0 | 1) => {
                remember_launch(&mut self.recent, id);
                self.open_app(&path);
            }
            (PanelEntry::Command { name }, 0 | 1) => {
                remember_launch(&mut self.recent, id);
                self.run_command(&name);
            }
            (PanelEntry::Native { action }, 0 | 1) => {
                remember_launch(&mut self.recent, id);
                self.run_native(&action);
            }
            _ => {}
        }
    }

    /// Runs a window layout on the window you were using, or opens the Quick controls panel.
    fn run_native(&self, action: &str) {
        if action == "quick-controls" {
            crate::workspace_native::show_quick_controls(&self.app);
            return;
        }
        if action == MEETING_RECORDING_ACTION {
            if let Err(message) = crate::toggle_meeting_recording(&self.app) {
                self.notice("meeting-recording", &message);
            }
            return;
        }
        if crate::window_manager::layout_of(action).is_none() {
            return;
        }
        if !crate::global_desktop::windows_enabled(&self.app) {
            self.notice(
                "window-manager-off",
                "Turn on Window Manager in Quick controls to use window layouts.",
            );
            return;
        }
        // Give focus a moment to return to the window you were using once the panel has closed.
        let action = action.to_string();
        let _ = std::thread::Builder::new()
            .name("officekit-launcher-window".into())
            .spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                crate::window_runtime::handle_action(&action);
            });
    }

    /// Runs a built-in Finder command through the fixed script for its name. Finder asks for
    /// confirmation before erasing the Trash, and macOS asks once to let OfficeKit control Finder.
    fn run_command(&self, name: &str) {
        let Some(script) = command_script(name) else {
            return;
        };
        let started = std::process::Command::new("/usr/bin/osascript")
            .arg("-e")
            .arg(script)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .is_ok();
        if !started {
            self.notice(
                "command-failed",
                "OfficeKit could not ask Finder to do that.",
            );
        }
    }

    /// Launches an application the panel listed. The path never comes from the panel itself, only
    /// from the lookup table built when it opened, and is passed as one argument, not through a shell.
    fn open_app(&self, path: &str) {
        let opened = std::process::Command::new("/usr/bin/open")
            .arg(path)
            .status()
            .map(|status| status.success())
            .unwrap_or(false);
        if !opened {
            self.notice(
                "app-open-failed",
                "OfficeKit could not open that application.",
            );
        }
    }

    /// Brings OfficeKit forward and asks the webview to open the tool.
    fn open_tool(&self, id: &str) {
        if !valid_id(id) {
            return;
        }
        if let Some(window) = self.app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.unminimize();
            let _ = window.set_focus();
        }
        let _ = self.app.emit("launcher-open-tool", json!({ "toolId": id }));
    }

    fn report_paste(&self, code: i32) {
        match code {
            0 => {}
            1 => self.notice(
                "accessibility",
                "Allow Accessibility access so OfficeKit can paste into other apps. The item is on your clipboard.",
            ),
            4 => self.notice("paste-target", "Nothing here accepts a paste. The item is on your clipboard."),
            _ => self.notice("paste-failed", "OfficeKit could not paste. Try copying the item again."),
        }
    }

    fn paste_clip(&self, id: &str, has_image: bool, target: i32) {
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        let Ok(response) = sidecar.ok("GET", &format!("/api/clipboard/clips/{id}"), None) else {
            return;
        };
        let clip = &response["clip"];
        let code = if has_image {
            match clip["image_data"]
                .as_str()
                .and_then(|data| base64::engine::general_purpose::STANDARD.decode(data).ok())
            {
                Some(png) => native::paste(1, &png, target),
                None => 3,
            }
        } else {
            native::paste(
                0,
                clip["text_content"].as_str().unwrap_or("").as_bytes(),
                target,
            )
        };
        // The item that was just used goes to the top of the history, whether or not the watcher
        // sees the paste as a new copy.
        if code == 0 {
            let _ = sidecar.ok(
                "POST",
                &format!("/api/clipboard/clips/{id}/use"),
                Some(&json!({})),
            );
        }
        self.report_paste(code);
    }

    fn render(&self, sidecar: &Sidecar, template: &str, values: Value) -> Option<String> {
        let clipboard = if template_uses_clipboard(template) {
            native::clipboard_text(MAX_CLIPBOARD_TEXT_BYTES).unwrap_or_default()
        } else {
            String::new()
        };
        let body = json!({"template": template, "values": values, "current_clipboard": clipboard});
        sidecar
            .ok("POST", "/api/clipboard/snippets/render", Some(&body))
            .ok()
            .and_then(|value| value["rendered"].as_str().map(str::to_string))
    }

    fn insert_snippet(&self, content: &str, target: i32) {
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        let variables = template_prompt_variables(content);
        let values = if variables.is_empty() {
            json!({})
        } else {
            let names = serde_json::to_vec(&variables).unwrap_or_default();
            match native::prompt(&names, target, MAX_PROMPT_ANSWER_BYTES)
                .and_then(|answer| serde_json::from_slice::<Value>(&answer).ok())
            {
                Some(values) if values.is_object() => values,
                _ => return,
            }
        };
        match self.render(&sidecar, content, values) {
            Some(rendered) if !rendered.is_empty() => {
                self.report_paste(native::paste(0, rendered.as_bytes(), target));
            }
            _ => self.notice("paste-failed", "OfficeKit could not prepare that snippet."),
        }
    }

    fn expand(&self, trigger: &str) {
        let Some(template) = self.keywords.get(trigger) else {
            return;
        };
        let Some(sidecar) = self.sidecar() else {
            return;
        };
        let Some(rendered) = self.render(&sidecar, template, json!({})) else {
            return;
        };
        if rendered.is_empty() {
            return;
        }
        if native::expand(trigger, &rendered) == 1 {
            self.notice(
                "accessibility",
                "Allow Accessibility access so snippet keywords can expand in other apps.",
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    #[test]
    fn capture_skips_apps_from_the_clipboard_list_and_the_apps_to_skip_setting() {
        let clipboard = json!(["com.1password.1password", "com.apple.Passwords"]);
        let desktop = vec![
            "COM.APPLE.PASSWORDS".to_string(),
            "org.example.Vault".to_string(),
        ];
        assert_eq!(
            capture_skip_list(&clipboard, &desktop),
            vec![
                "com.1password.1password".to_string(),
                "com.apple.Passwords".to_string(),
                "org.example.Vault".to_string(),
            ],
            "the Apps to skip setting joins the clipboard list without case-variant duplicates"
        );
        assert_eq!(
            capture_skip_list(&Value::Null, &desktop),
            desktop,
            "a missing or invalid clipboard list still honors the user's skipped apps"
        );
        assert!(capture_skip_list(&json!("not a list"), &[]).is_empty());
        let junk = json!([1, null, "", "ok.app", "bad id"]);
        assert_eq!(capture_skip_list(&junk, &[]), vec!["ok.app".to_string()]);
    }

    fn serve_once(response: Vec<u8>) -> (SocketAddr, std::thread::JoinHandle<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut chunk = [0u8; 4096];
            loop {
                let read = stream.read(&mut chunk).unwrap();
                request.extend_from_slice(&chunk[..read]);
                if let Some(boundary) = request.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..boundary]).to_string();
                    let length = headers
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .and_then(|value| value.trim().parse::<usize>().ok())
                        .unwrap_or(0);
                    if request.len() >= boundary + 4 + length {
                        break;
                    }
                }
                if read == 0 {
                    break;
                }
            }
            stream.write_all(&response).unwrap();
            String::from_utf8_lossy(&request).to_string()
        });
        (address, handle)
    }

    fn sidecar(address: SocketAddr) -> Sidecar {
        Sidecar {
            address,
            token: "abc-123".into(),
        }
    }

    #[test]
    fn request_sends_auth_and_body_and_parses_json() {
        let (address, handle) = serve_once(
            b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}".to_vec(),
        );
        let (status, value) = sidecar(address)
            .request(
                "POST",
                "/api/clipboard/clips",
                Some(&json!({"text_content": "hi"})),
            )
            .unwrap();
        assert_eq!((status, value["ok"].as_bool()), (200, Some(true)));
        let request = handle.join().unwrap();
        assert!(request.starts_with("POST /api/clipboard/clips HTTP/1.0"));
        assert!(request.contains("Authorization: Bearer abc-123"));
        assert!(request.ends_with("{\"text_content\":\"hi\"}"));
    }

    #[test]
    fn request_reports_status_and_tolerates_empty_bodies() {
        let (address, _) = serve_once(b"HTTP/1.0 404 Not Found\r\n\r\n".to_vec());
        assert_eq!(
            sidecar(address).request("GET", "/api/x", None).unwrap(),
            (404, Value::Null)
        );
        let (address, _) = serve_once(b"HTTP/1.0 404 Not Found\r\n\r\n{}".to_vec());
        assert!(sidecar(address).ok("GET", "/api/x", None).is_err());
        let (address, _) = serve_once(b"HTTP/1.0 200 OK\r\n\r\n{\"a\":1}".to_vec());
        assert_eq!(sidecar(address).ok("GET", "/api/x", None).unwrap()["a"], 1);
    }

    #[test]
    fn a_locked_app_reports_license_required_not_a_generic_rejection() {
        let (address, _) = serve_once(
            b"HTTP/1.0 403 Forbidden\r\n\r\n{\"error\":{\"code\":\"license_required\"}}".to_vec(),
        );
        assert_eq!(
            sidecar(address).ok("GET", "/api/x", None).unwrap_err(),
            "license_required"
        );
        let (address, _) =
            serve_once(b"HTTP/1.0 403 Forbidden\r\n\r\n{\"error\":{\"code\":\"other\"}}".to_vec());
        assert_eq!(
            sidecar(address).ok("GET", "/api/x", None).unwrap_err(),
            "The local store rejected the request"
        );
    }

    #[test]
    fn request_rejects_unsafe_targets_tokens_and_malformed_answers() {
        let loopback: SocketAddr = "127.0.0.1:1".parse().unwrap();
        let remote: SocketAddr = "8.8.8.8:80".parse().unwrap();
        assert!(Sidecar {
            address: remote,
            token: "a".into()
        }
        .request("GET", "/api/x", None)
        .is_err());
        assert!(Sidecar {
            address: loopback,
            token: "bad token".into()
        }
        .request("GET", "/api/x", None)
        .is_err());
        assert!(sidecar(loopback).request("GET", "/other", None).is_err());
        assert!(sidecar(loopback).request("GET", "/api/x y", None).is_err());
        assert!(sidecar(loopback)
            .request("GET", "/api/x\r\nHost: evil", None)
            .is_err());
        assert!(
            sidecar(loopback).request("GET", "/api/x", None).is_err(),
            "nothing listens on port 1"
        );
        let (address, _) = serve_once(b"not http".to_vec());
        assert!(sidecar(address).request("GET", "/api/x", None).is_err());
        let (address, _) = serve_once(b"HTTP/1.0 xyz\r\n\r\n".to_vec());
        assert!(sidecar(address).request("GET", "/api/x", None).is_err());
        let (address, _) = serve_once(b"HTTP/1.0 200 OK\r\n\r\n<html>".to_vec());
        assert!(sidecar(address).request("GET", "/api/x", None).is_err());
    }

    #[test]
    fn ids_are_limited_to_safe_path_characters() {
        assert!(valid_id("3f2a-9b"));
        assert!(valid_id("default"));
        assert!(!valid_id(""));
        assert!(!valid_id("a/b"));
        assert!(!valid_id("a b"));
        assert!(!valid_id(&"x".repeat(129)));
    }

    #[test]
    fn age_labels_step_from_now_to_days() {
        assert_eq!(age_label(100.0, 100.0), "now");
        assert_eq!(age_label(100.0, 200.0), "now");
        assert_eq!(age_label(160.0, 100.0), "1m");
        assert_eq!(age_label(100.0 + 3599.0, 100.0), "59m");
        assert_eq!(age_label(100.0 + 7200.0, 100.0), "2h");
        assert_eq!(age_label(100.0 + 3.0 * 86400.0, 100.0), "3d");
    }

    #[test]
    fn titles_collapse_whitespace_clip_long_text_and_label_images() {
        assert_eq!(
            clip_title("  Invoice\n\n2041   due ", "text"),
            "Invoice 2041 due"
        );
        assert_eq!(clip_title("anything", "image"), "Image");
        let long = "word ".repeat(60);
        let title = clip_title(&long, "text");
        assert_eq!(title.chars().count(), MAX_TITLE_CHARS + 1);
        assert!(title.ends_with('…'));
        assert_eq!(
            (
                clip_kind("code"),
                clip_kind("json"),
                clip_kind("link"),
                clip_kind("image")
            ),
            ("text", "text", "link", "image")
        );
    }

    fn dictation(id: &str, text: &str, created_at: f64) -> PanelDictation {
        PanelDictation {
            id: id.into(),
            text: text.into(),
            created_at,
        }
    }

    #[test]
    fn dictations_are_sanitized_sorted_newest_first_and_bounded() {
        let mut items = vec![
            dictation("old", "older", 10.0),
            dictation("bad id", "skipped", 99.0),
            dictation("blank", "   ", 98.0),
            dictation("new", "newer", 20.0),
        ];
        items.push(dictation(
            "long",
            &"x".repeat(MAX_DICTATION_PANEL_CHARS + 5),
            5.0,
        ));
        let kept = sanitize_dictations(items);
        let ids: Vec<&str> = kept.iter().map(|item| item.id.as_str()).collect();
        assert_eq!(ids, ["new", "old", "long"]);
        assert_eq!(kept[2].text.chars().count(), MAX_DICTATION_PANEL_CHARS);
        let many: Vec<PanelDictation> = (0..80)
            .map(|index| dictation(&format!("d{index}"), "text", f64::from(index)))
            .collect();
        let kept = sanitize_dictations(many);
        assert_eq!(kept.len(), MAX_PANEL_DICTATIONS);
        assert_eq!(kept[0].id, "d79");
    }

    #[test]
    fn dictation_tab_adds_a_read_only_chip_and_paste_only_rows() {
        let (mut panel, mut entries) = clips_panel(&json!({"clips": []}), 1000.0);
        add_dictations(
            &mut panel,
            &mut entries,
            &[dictation("t1", "Please   send the\nproposal", 940.0)],
            1000.0,
        );
        let chips = panel["chips"].as_array().unwrap();
        assert_eq!(chips.last().unwrap()["id"], "dictation");
        assert_eq!(chips.last().unwrap()["label"], "Dictation");
        assert_eq!(panel["readOnlyChips"], json!(["dictation"]));
        let row = &panel["items"][0];
        assert_eq!(row["id"], "dictation-t1");
        assert_eq!(row["kind"], "dictation");
        assert_eq!(row["title"], "Please send the proposal");
        assert_eq!(row["badge"], "1m");
        assert_eq!(row["pinned"], false);
        assert_eq!(
            entries["dictation-t1"],
            PanelEntry::Dictation {
                text: "Please   send the\nproposal".into()
            }
        );
    }

    #[test]
    fn clipboard_panel_lists_clips_with_kind_age_pin_and_image_flags() {
        let history = json!({"clips": [
            {"id": "a1", "content_type": "link", "text_content": "https://example.com", "source_app": "Safari", "created_at": 90.0, "pinned": 1},
            {"id": "b2", "content_type": "image", "text_content": "", "has_image": 1, "created_at": 0.0, "pinned": 0},
            {"id": "c3", "content_type": "text", "text_content": "hello", "image_data": "", "created_at": 100.0},
            {"id": "bad/id", "content_type": "text", "text_content": "skipped"},
            {"content_type": "text", "text_content": "no id"},
        ]});
        let (panel, entries) = clips_panel(&history, 100.0);
        let items = panel["items"].as_array().unwrap();
        assert_eq!(items.len(), 3);
        assert_eq!(items[0]["kind"], "link");
        assert_eq!(items[0]["subtitle"], "Safari");
        assert_eq!(items[0]["badge"], "now");
        assert_eq!(items[0]["pinned"], true);
        assert_eq!(items[1]["title"], "Image");
        assert_eq!(items[2]["pinned"], false);
        assert_eq!(entries["b2"], PanelEntry::Clip { has_image: true });
        assert_eq!(entries["c3"], PanelEntry::Clip { has_image: false });
        assert_eq!(panel["chips"].as_array().unwrap().len(), 5);
        let (empty, none) = clips_panel(&Value::Null, 0.0);
        assert!(empty["items"].as_array().unwrap().is_empty() && none.is_empty());
        let with_data = json!({"clips": [{"id": "d4", "content_type": "text", "text_content": "x", "image_data": "AAAA"}]});
        assert_eq!(
            clips_panel(&with_data, 0.0).1["d4"],
            PanelEntry::Clip { has_image: true }
        );
    }

    #[test]
    fn snippet_panel_uses_folders_as_chips_and_keeps_templates_for_pasting() {
        let snippets = json!({"snippets": [
            {"id": "s1", "title": "Signature", "content": "Best,\nA", "trigger_key": ";sig", "folder_id": "default", "folder_name": "General"},
            {"id": "s2", "title": "Bug", "content": "Steps", "folder_id": "dev"},
            {"id": "bad id", "title": "skipped"},
        ]});
        let folders = json!({"folders": [
            {"id": "default", "name": "General"}, {"id": "dev", "name": "Dev"},
            {"id": "all", "name": "Sneaky"}, {"id": "pinned", "name": "Sneaky"}, {"id": "bad id", "name": "x"}, {"name": "no id"},
        ]});
        let (panel, entries) = snippets_panel(&snippets, &folders);
        let chips: Vec<&str> = panel["chips"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["id"].as_str().unwrap())
            .collect();
        assert_eq!(chips, vec!["all", "default", "dev"]);
        let items = panel["items"].as_array().unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(
            (
                items[0]["subtitle"].as_str(),
                items[0]["badge"].as_str(),
                items[0]["kind"].as_str()
            ),
            (Some(";sig"), Some("General"), Some("default"))
        );
        assert_eq!(items[1]["subtitle"], "");
        assert_eq!(
            entries["s1"],
            PanelEntry::Snippet {
                content: "Best,\nA".into()
            }
        );
        let many: Vec<Value> = (0..20)
            .map(|n| json!({"id": format!("f{n}"), "name": format!("F{n}")}))
            .collect();
        let (capped, _) = snippets_panel(&Value::Null, &json!({"folders": many}));
        assert_eq!(capped["chips"].as_array().unwrap().len(), 12);
    }

    #[test]
    fn template_scanner_finds_only_typed_input_placeholders() {
        assert!(template_prompt_variables("Hello world").is_empty());
        assert!(template_prompt_variables(
            "{{date}} {{time:%H}} {{Clipboard}} {{uuid}} {{DATE:x}}"
        )
        .is_empty());
        assert_eq!(
            template_prompt_variables("Hi {{name}}, {{company}} {{name}}"),
            vec!["name", "company"]
        );
        assert!(template_prompt_variables("{{}} {{bad name}} {{unterminated").is_empty());
        assert_eq!(template_prompt_variables("{{ {{name}}"), vec!["name"]);
        assert!(template_uses_clipboard("Paste {{Clipboard}} here"));
        assert!(!template_uses_clipboard("Nothing"));
    }

    #[test]
    fn expansion_table_skips_blank_long_empty_and_prompting_snippets() {
        let snippets = json!({"snippets": [
            {"trigger_key": ";sig", "content": "Best"},
            {"trigger_key": ";date", "content": "{{date}}"},
            {"trigger_key": ";ask", "content": "Hi {{name}}"},
            {"trigger_key": "  ", "content": "x"},
            {"trigger_key": null, "content": "x"},
            {"trigger_key": ";empty", "content": ""},
            {"trigger_key": "x".repeat(33), "content": "x"},
        ]});
        let table = expansion_table(&snippets);
        let mut keys: Vec<&String> = table.keys().collect();
        keys.sort();
        assert_eq!(keys, vec![";date", ";sig"]);
        assert!(expansion_table(&Value::Null).is_empty());
    }

    fn app(name: &str, path: &str) -> InstalledApp {
        InstalledApp {
            name: name.into(),
            path: path.into(),
        }
    }

    fn sample_tools() -> Value {
        json!({"tools": [
            {"id": "pdf_merge", "name": "Merge PDFs", "category": "PDF & Documents", "desc": "Combine PDFs", "keywords": ["join pdf", "combine pdf"]},
            {"id": "bad id", "name": "Skipped", "category": "x", "desc": ""},
            {"id": "nameless", "name": "", "category": "x", "desc": ""},
        ]})
    }

    fn sample_snippets() -> Value {
        json!({"snippets": [
            {"id": "pdf_merge", "title": "Sig", "trigger_key": ";sig", "content": "Best", "folder_name": "Mail", "folder_id": "mail"},
        ]})
    }

    #[test]
    fn only_the_known_trash_commands_have_a_script() {
        for (name, _, _, _) in LAUNCHER_COMMANDS {
            assert!(command_script(name).is_some_and(|script| script.contains("Finder")));
        }
        assert_eq!(command_script("empty-trash; rm -rf ~"), None);
        assert_eq!(command_script(""), None);
    }

    #[test]
    fn tool_icons_carry_the_catalog_icon_and_category_or_fall_back_to_the_wrench() {
        assert_eq!(
            tool_icon(Some("fa-file-zipper"), "PDF & Documents"),
            "tool|fa-file-zipper|PDF & Documents"
        );
        assert_eq!(tool_icon(None, "Images"), "tool");
        assert_eq!(tool_icon(Some(""), "Images"), "tool");
        assert_eq!(tool_icon(Some("fa-x|y"), "Images"), "tool");
        assert_eq!(tool_icon(Some("Fa-Key"), "Images"), "tool");
        assert_eq!(tool_icon(Some("fa-key"), "A|B"), "tool");
        assert_eq!(tool_icon(Some(&"a".repeat(49)), "Images"), "tool");
        let tools = json!({"tools": [
            {"id": "pdf_compress", "name": "Compress PDF", "category": "PDF & Documents", "desc": "", "icon": "fa-file-zipper"},
        ]});
        let filters = crate::global_desktop::default_launcher_filters();
        let sources = LauncherSources {
            apps: &[],
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, _) = launcher_panel(&tools, &Value::Null, &sources);
        let tool_row = panel["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|item| item["id"] == "tool-pdf_compress")
            .unwrap();
        assert_eq!(tool_row["icon"], "tool|fa-file-zipper|PDF & Documents");
    }

    #[test]
    fn clipboard_history_switch_maps_to_the_saved_pause_setting() {
        assert_eq!(
            history_settings_body(false),
            json!({"capture_pause": "until_resume"})
        );
        assert_eq!(
            history_settings_body(true),
            json!({"capture_enabled": true, "capture_pause": "off"})
        );
        assert!(history_is_on(
            &json!({"capture_enabled": true, "capture_paused": false})
        ));
        assert!(!history_is_on(
            &json!({"capture_enabled": true, "capture_paused": true})
        ));
        assert!(!history_is_on(
            &json!({"capture_enabled": false, "capture_paused": false})
        ));
        assert!(
            history_is_on(&json!({})),
            "a fresh store captures by default"
        );
    }

    #[test]
    fn launcher_lists_window_layouts_and_quick_controls_with_tools() {
        let filters = crate::global_desktop::default_launcher_filters();
        let sources = LauncherSources {
            apps: &[],
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, entries) = launcher_panel(&Value::Null, &Value::Null, &sources);
        let items = panel["items"].as_array().unwrap();
        let windows: Vec<&Value> = items
            .iter()
            .filter(|item| {
                item["id"]
                    .as_str()
                    .unwrap_or("")
                    .starts_with("command-window-")
            })
            .collect();
        assert_eq!(windows.len(), LAUNCHER_WINDOW_COMMANDS.len());
        assert_eq!(windows[0]["title"], "Left half");
        assert_eq!(windows[0]["kind"], "command");
        assert_eq!(
            entries["command-window-left-half"],
            PanelEntry::Native {
                action: "window.left-half".into()
            }
        );
        for (layout, ..) in LAUNCHER_WINDOW_COMMANDS {
            assert!(
                crate::window_manager::layout_of(&crate::window_manager::action_name(layout))
                    .is_some(),
                "{layout} must be a real layout"
            );
        }
        let controls = items
            .iter()
            .find(|item| item["id"] == "native-quick-controls")
            .expect("Quick controls is listed");
        let meeting = items
            .iter()
            .find(|item| item["id"] == "native-meeting-recording")
            .expect("Meeting recording is listed");
        assert_eq!(meeting["title"], "Start or stop meeting recording");
        assert_eq!(
            entries["native-meeting-recording"],
            PanelEntry::Native {
                action: MEETING_RECORDING_ACTION.into()
            }
        );
        assert_eq!(controls["title"], "OfficeKit Quick controls");
        assert_eq!(controls["kind"], "tool");
        assert_eq!(
            entries["native-quick-controls"],
            PanelEntry::Native {
                action: "quick-controls".into()
            }
        );
    }

    #[test]
    fn launcher_hides_window_layouts_and_quick_controls_when_tools_are_hidden() {
        let filters = crate::global_desktop::default_launcher_filters();
        let mut options = LauncherOptions::default();
        options.tools = false;
        let sources = LauncherSources {
            apps: &[],
            recent: &[],
            filters: &filters,
            options,
        };
        let (panel, entries) = launcher_panel(&Value::Null, &Value::Null, &sources);
        let ids: Vec<&str> = panel["items"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|item| item["id"].as_str())
            .collect();
        assert!(!ids.iter().any(|id| id.starts_with("command-window-")
            || *id == "native-quick-controls"
            || *id == "native-meeting-recording"));
        assert!(!entries
            .values()
            .any(|entry| matches!(entry, PanelEntry::Native { .. })));
    }

    #[test]
    fn launcher_lists_tools_apps_then_snippets_with_distinct_lookup_keys() {
        let filters = crate::global_desktop::default_launcher_filters();
        let apps = [app("Safari", "/Applications/Safari.app")];
        let sources = LauncherSources {
            apps: &apps,
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, entries) = launcher_panel(&sample_tools(), &sample_snippets(), &sources);
        let items = panel["items"].as_array().unwrap();
        assert_eq!(
            items.len(),
            5 + LAUNCHER_WINDOW_COMMANDS.len() + LAUNCHER_NATIVE_EXTRAS
        );
        // Mac apps and Finder commands come first, then OfficeKit tools, then snippets.
        assert_eq!(items[0]["id"], "app-safari");
        assert_eq!(items[0]["kind"], "app");
        assert_eq!(items[0]["subtitle"], "/Applications/Safari.app");
        assert_eq!(items[0]["icon"], "app:/Applications/Safari.app");
        assert_eq!(items[1]["id"], "command-open-trash");
        assert_eq!(items[1]["kind"], "command");
        assert_eq!(items[2]["title"], "Empty Trash");
        assert_eq!(items[3]["id"], "tool-pdf_merge");
        assert_eq!(items[3]["kind"], "tool");
        assert_eq!(items[3]["subtitle"], "PDF & Documents");
        assert_eq!(
            items[3]["badge"], "Combine PDFs join pdf combine pdf",
            "description and aliases stay searchable"
        );
        assert_eq!(items[3]["icon"], "tool");
        assert_eq!(
            entries["command-empty-trash"],
            PanelEntry::Command {
                name: "empty-trash".into()
            }
        );
        assert_eq!(items[4]["kind"], "snippet");
        assert_eq!(items[4]["subtitle"], ";sig · Mail");
        assert_eq!(items[4]["badge"], "");
        assert_eq!(
            entries["tool-pdf_merge"],
            PanelEntry::Tool {
                id: "pdf_merge".into()
            }
        );
        assert_eq!(
            entries["app-safari"],
            PanelEntry::App {
                path: "/Applications/Safari.app".into()
            }
        );
        assert!(matches!(entries["pdf_merge"], PanelEntry::Snippet { .. }));
        assert_eq!(panel["style"], "launcher");
        assert_eq!(
            panel["title"], "Launcher",
            "the header must not repeat OfficeKit"
        );
        let (empty, none) = launcher_panel(
            &Value::Null,
            &Value::Null,
            &LauncherSources {
                apps: &[],
                recent: &[],
                filters: &filters,
                options: LauncherOptions::default(),
            },
        );
        // With no tools, apps or snippets, only OfficeKit's own rows remain: the two Finder commands,
        // the window layouts and Quick controls.
        let ids: Vec<&str> = empty["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids[..2], ["command-open-trash", "command-empty-trash"]);
        assert_eq!(
            ids.len(),
            2 + LAUNCHER_WINDOW_COMMANDS.len() + LAUNCHER_NATIVE_EXTRAS
        );
        assert_eq!(ids.last(), Some(&"native-quick-controls"));
        assert_eq!(none.len(), ids.len());
    }

    #[test]
    fn launcher_chips_carry_the_users_filter_keys() {
        let mut filters = crate::global_desktop::default_launcher_filters();
        filters.insert(
            "tool".into(),
            ShortcutSetting {
                key_code: 17,
                modifier_mask: 0b0011,
            },
        );
        filters.remove("snippet");
        let sources = LauncherSources {
            apps: &[],
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, _) = launcher_panel(&Value::Null, &Value::Null, &sources);
        let chips = panel["chips"].as_array().unwrap();
        let ids: Vec<&str> = chips
            .iter()
            .map(|chip| chip["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, vec!["all", "app", "tool", "snippet"]);
        assert_eq!(chips[0]["keyCode"], 18);
        assert_eq!(chips[0]["modifierMask"], 1);
        assert_eq!(chips[2]["keyCode"], 17);
        assert_eq!(chips[2]["modifierMask"], 3);
        assert!(
            chips[3].get("keyCode").is_none(),
            "an unbound filter has no key"
        );
    }

    #[test]
    fn launcher_puts_recent_rows_first_newest_first() {
        let filters = crate::global_desktop::default_launcher_filters();
        let apps = [
            app("Mail", "/Applications/Mail.app"),
            app("Safari", "/Applications/Safari.app"),
        ];
        let recent = vec!["app-safari".to_string(), "tool-pdf_merge".to_string()];
        let sources = LauncherSources {
            apps: &apps,
            recent: &recent,
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, _) = launcher_panel(&sample_tools(), &sample_snippets(), &sources);
        let ids: Vec<&str> = panel["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["id"].as_str().unwrap())
            .collect();
        // The window layouts and Quick controls follow these rows.
        assert_eq!(
            ids[..6],
            [
                "app-safari",
                "tool-pdf_merge",
                "app-mail",
                "command-open-trash",
                "command-empty-trash",
                "pdf_merge"
            ]
        );
        let subtitles: Vec<&str> = panel["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["subtitle"].as_str().unwrap())
            .collect();
        assert!(subtitles[0].starts_with("Recent"));
        assert!(subtitles[1].starts_with("Recent · "));
        assert!(!subtitles[2].starts_with("Recent"));
    }

    #[test]
    fn web_recent_tools_are_validated_bounded_and_listed_after_native_launches() {
        assert!(is_tool_id("pdf_merge"));
        assert!(is_tool_id("a.b-c_9"));
        for bad in ["", "-x", "Upper", "has space", "a/b", &"a".repeat(121)] {
            assert!(!is_tool_id(bad), "{bad}");
        }
        let many: Vec<String> = (0..40).map(|n| format!("tool{n}")).collect();
        set_web_recent_tools(&many);
        assert_eq!(combined_recent(&[]).len(), MAX_RECENT_LAUNCHES);
        set_web_recent_tools(&[
            "pdf_merge".to_string(),
            "bad id".to_string(),
            "image_resize".to_string(),
        ]);
        let native = vec!["app-safari".to_string(), "tool-image_resize".to_string()];
        assert_eq!(
            combined_recent(&native),
            vec!["app-safari", "tool-image_resize", "tool-pdf_merge"]
        );
        set_web_recent_tools(&[]);
    }

    #[test]
    fn launcher_app_keys_stay_unique_and_valid() {
        let filters = crate::global_desktop::default_launcher_filters();
        let apps = [
            app("Notes", "/Applications/Notes.app"),
            app("notes!", "/Applications/Utilities/notes!.app"),
            app("Ünïcode App", "/Applications/Ünïcode App.app"),
        ];
        let sources = LauncherSources {
            apps: &apps,
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, entries) = launcher_panel(&Value::Null, &Value::Null, &sources);
        let ids: Vec<&str> = panel["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["id"].as_str().unwrap())
            .collect();
        // Three apps, the two built-in Finder commands, the window layouts and Quick controls.
        let native = LAUNCHER_WINDOW_COMMANDS.len() + LAUNCHER_NATIVE_EXTRAS;
        assert_eq!(ids.len(), 5 + native);
        assert_eq!(entries.len(), 5 + native);
        assert!(ids.iter().all(|id| valid_id(id)), "{ids:?}");
    }

    #[test]
    fn launcher_never_exceeds_the_native_item_limit() {
        let filters = crate::global_desktop::default_launcher_filters();
        let apps: Vec<InstalledApp> = (0..400)
            .map(|n| app(&format!("App{n}"), &format!("/Applications/App{n}.app")))
            .collect();
        let tools = json!({"tools": (0..300)
            .map(|n| json!({"id": format!("t{n}"), "name": format!("Tool {n}"), "category": "c", "desc": "d"}))
            .collect::<Vec<_>>()});
        let snippets = json!({"snippets": (0..450)
            .map(|n| json!({"id": format!("s{n}"), "title": format!("Snip {n}"), "trigger_key": format!(";s{n}"), "content": "x"}))
            .collect::<Vec<_>>()});
        let sources = LauncherSources {
            apps: &apps,
            recent: &[],
            filters: &filters,
            options: LauncherOptions::default(),
        };
        let (panel, _) = launcher_panel(&tools, &snippets, &sources);
        assert_eq!(panel["items"].as_array().unwrap().len(), 1000);
    }

    #[test]
    fn remembering_a_launch_moves_it_to_the_front_without_repeats_and_is_bounded() {
        let mut recent = vec!["a".to_string(), "b".to_string()];
        remember_launch(&mut recent, "b");
        assert_eq!(recent, vec!["b", "a"]);
        for n in 0..30 {
            remember_launch(&mut recent, &format!("k{n}"));
        }
        assert_eq!(recent.len(), MAX_RECENT_LAUNCHES);
        assert_eq!(recent[0], "k29");
    }

    #[test]
    fn imported_keywords_must_be_two_characters_without_whitespace() {
        let snippets = json!({"snippets": [
            {"trigger_key": "a", "content": "x"},
            {"trigger_key": ";a b", "content": "x"},
            {"trigger_key": ";a", "content": "x"},
        ]});
        let table = expansion_table(&snippets);
        assert_eq!(table.keys().collect::<Vec<_>>(), vec![";a"]);
    }

    #[test]
    fn only_exact_builtin_names_skip_the_placeholder_prompt() {
        assert_eq!(
            template_prompt_variables("{{dateOfBirth}} {{timezone}} {{date:%Y}} {{time}} {{uuid}}"),
            vec!["dateOfBirth", "timezone"]
        );
    }

    #[test]
    fn the_clipboard_panel_opens_on_the_chip_the_user_chose() {
        assert_eq!(panel_start_chip("text"), "text");
        assert_eq!(panel_start_chip("all"), "all");
        assert_eq!(panel_start_chip("images"), "image");
        assert_eq!(panel_start_chip("links"), "link");
        assert_eq!(panel_start_chip("pinned"), "pinned");
        // Anything unexpected falls back to the default, Text.
        assert_eq!(panel_start_chip("videos"), "text");
        assert_eq!(panel_start_chip(""), "text");
    }

    #[test]
    fn a_timed_pause_has_a_bounded_wait_and_an_ended_pause_has_none() {
        assert_eq!(
            pause_remaining(1_900.0, 1_000.0),
            Some(Duration::from_secs(900))
        );
        assert_eq!(pause_remaining(1_000.0, 1_000.0), None);
        assert_eq!(pause_remaining(999.0, 1_000.0), None);
        // A far-future end time waits at most an hour, so a clock change cannot strand the watcher.
        assert_eq!(
            pause_remaining(1.0e12, 1_000.0),
            Some(Duration::from_secs(3600))
        );
        assert_eq!(pause_remaining(f64::NAN, 1_000.0), None);
        assert_eq!(pause_remaining(f64::INFINITY, 1_000.0), None);
    }

    #[test]
    fn launcher_result_kinds_can_be_switched_off_individually() {
        let filters = crate::global_desktop::default_launcher_filters();
        let apps = [app("Safari", "/Applications/Safari.app")];
        let snippets = sample_snippets();
        let listed = |options: LauncherOptions| {
            let sources = LauncherSources {
                apps: &apps,
                recent: &[],
                filters: &filters,
                options,
            };
            let (panel, _) = launcher_panel(&sample_tools(), &snippets, &sources);
            let kinds: Vec<String> = panel["items"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| item["kind"].as_str().unwrap().to_string())
                .collect();
            let chips: Vec<String> = panel["chips"]
                .as_array()
                .unwrap()
                .iter()
                .map(|chip| chip["id"].as_str().unwrap().to_string())
                .collect();
            (kinds, chips)
        };
        let (all_kinds, all_chips) = listed(LauncherOptions::default());
        assert!(
            all_kinds.iter().any(|kind| kind == "app")
                && all_kinds.iter().any(|kind| kind == "tool")
        );
        assert_eq!(all_chips, vec!["all", "app", "tool", "snippet"]);

        let no_apps = listed(LauncherOptions {
            apps: false,
            ..LauncherOptions::default()
        });
        // Window layouts are commands that sit with the tools, so only the apps are gone.
        assert!(no_apps.0.iter().all(|kind| kind != "app"));
        assert_eq!(no_apps.1, vec!["all", "tool", "snippet"]);

        let tools_only = listed(LauncherOptions {
            apps: false,
            snippets: false,
            ..LauncherOptions::default()
        });
        assert!(tools_only
            .0
            .iter()
            .all(|kind| kind == "tool" || kind == "command"));
        assert_eq!(tools_only.1, vec!["all", "tool"]);

        let nothing = listed(LauncherOptions {
            apps: false,
            tools: false,
            snippets: false,
            ..LauncherOptions::default()
        });
        assert!(nothing.0.is_empty());
        assert_eq!(nothing.1, vec!["all"]);
    }

    #[test]
    fn the_quick_result_switches_are_passed_to_the_native_panel() {
        let filters = crate::global_desktop::default_launcher_filters();
        let sources = LauncherSources {
            apps: &[],
            recent: &[],
            filters: &filters,
            options: LauncherOptions {
                calculator: false,
                uuid: true,
                password: false,
                ..LauncherOptions::default()
            },
        };
        let (panel, _) = launcher_panel(&sample_tools(), &sample_snippets(), &sources);
        assert_eq!(
            panel["quickResults"],
            json!({"calculator": false, "uuid": true, "password": false, "passwordLength": 20, "passwordSymbols": "!@#$%&*?-_+="})
        );
    }
}
