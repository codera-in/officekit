//! In-app support reports. A report is sent to OfficeKit support as a ticket, and the app keeps the
//! ticket reference and a private token so it can tell the user when a fix ships. Nothing about the
//! user's files is ever sent: only the typed text, the optional reply email, the app and macOS
//! versions, the Mac model, a hash of a random install id and, when licensed, a hash of the activation id.

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::license_client::configured_license_api_base_url;

pub const MAX_TITLE_CHARS: usize = 160;
pub const MAX_DESCRIPTION_CHARS: usize = 8000;
pub const MAX_DISPLAY_NAME_CHARS: usize = 80;
const MAX_TRACKED_TICKETS: usize = 50;
const MAX_STATUS_CHECKS: usize = 20;
const MAX_RESPONSE_BYTES: usize = 8 * 1024;
const LEDGER_FILE: &str = "support-tickets.json";
const INSTALL_ID_FILE: &str = "support-install-id";
const TOKEN_HEADER: &str = "x-officekit-ticket-token";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupportError {
    Invalid,
    RateLimited,
    Offline,
    Unavailable,
}

impl SupportError {
    pub fn public_message(self) -> &'static str {
        match self {
            Self::Invalid => {
                "That report could not be sent. Check the title and your text, then try again."
            }
            Self::RateLimited => "Too many reports from this Mac today. Try again tomorrow.",
            Self::Offline => {
                "Could not reach OfficeKit support. Nothing was sent and your text is kept here. Try again when you are online."
            }
            Self::Unavailable => {
                "OfficeKit support is temporarily unavailable. Nothing was sent. Try again later."
            }
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TicketDraft {
    pub kind: String,
    pub title: String,
    pub description: String,
    pub email: Option<String>,
    pub display_name: Option<String>,
    pub publication_consent: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceInfo {
    pub app_version: String,
    pub os_version: String,
    pub model: String,
    pub device_hash: String,
    pub license_hash: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreatedTicket {
    pub ticket_id: String,
    pub token: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TicketStatus {
    pub fixed_in: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FixedNotice {
    pub ticket_id: String,
    pub fixed_in: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrackedTicket {
    pub ticket_id: String,
    pub token: String,
    #[serde(default)]
    pub announced: bool,
}

pub trait SupportApi {
    fn create(&mut self, body: &Value) -> Result<CreatedTicket, SupportError>;
    fn status(&mut self, ticket_id: &str, token: &str) -> Result<TicketStatus, SupportError>;
}

fn is_hex(value: &str, length: usize) -> bool {
    value.len() == length && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn clean(value: &str, max_chars: usize, single_line: bool) -> Option<String> {
    let trimmed = value.trim();
    let chars = trimmed.chars().count();
    let bad = trimmed.chars().any(|ch| {
        (ch.is_control() && ch != '\n' && ch != '\r' && ch != '\t')
            || (single_line && (ch == '\n' || ch == '\r'))
    });
    (chars >= 1 && chars <= max_chars && !bad).then(|| trimmed.to_string())
}

/// The JSON body for the support API, or `Invalid` before anything leaves the Mac.
pub fn build_request(draft: &TicketDraft, info: &DeviceInfo) -> Result<Value, SupportError> {
    if !matches!(draft.kind.as_str(), "bug" | "feature" | "testimonial") {
        return Err(SupportError::Invalid);
    }
    let title = clean(&draft.title, MAX_TITLE_CHARS, true).ok_or(SupportError::Invalid)?;
    let description =
        clean(&draft.description, MAX_DESCRIPTION_CHARS, false).ok_or(SupportError::Invalid)?;
    if !is_hex(&info.device_hash, 64)
        || info.license_hash.as_deref().is_some_and(|h| !is_hex(h, 64))
    {
        return Err(SupportError::Invalid);
    }
    let mut body = json!({
        "type": draft.kind,
        "title": title,
        "description": description,
        "device_hash": info.device_hash,
        "app_version": info.app_version,
        "os_version": info.os_version,
        "model": info.model,
    });
    let map = body.as_object_mut().expect("object literal");
    if let Some(email) = draft
        .email
        .as_deref()
        .map(str::trim)
        .filter(|e| !e.is_empty())
    {
        if !email.contains('@') || email.len() > 254 || email.chars().any(char::is_whitespace) {
            return Err(SupportError::Invalid);
        }
        map.insert("email".into(), json!(email));
    }
    if let Some(hash) = &info.license_hash {
        map.insert("license_hash".into(), json!(hash));
    }
    if draft.kind == "testimonial" {
        if let Some(name) = draft
            .display_name
            .as_deref()
            .map(str::trim)
            .filter(|n| !n.is_empty())
        {
            let name = clean(name, MAX_DISPLAY_NAME_CHARS, true).ok_or(SupportError::Invalid)?;
            map.insert("display_name".into(), json!(name));
        }
        map.insert(
            "publication_consent".into(),
            json!(draft.publication_consent == Some(true)),
        );
    }
    Ok(body)
}

fn ledger_path(dir: &Path) -> PathBuf {
    dir.join(LEDGER_FILE)
}

fn load_ledger(dir: &Path) -> Vec<TrackedTicket> {
    fs::read(ledger_path(dir))
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Vec<TrackedTicket>>(&bytes).ok())
        .unwrap_or_default()
}

fn save_ledger(dir: &Path, tickets: &[TrackedTicket]) {
    let start = tickets.len().saturating_sub(MAX_TRACKED_TICKETS);
    if let Ok(bytes) = serde_json::to_vec(&tickets[start..]) {
        let _ = fs::write(ledger_path(dir), bytes);
    }
}

/// Sends the report. On success the reference is remembered so a later fix can be announced.
pub fn submit_ticket(
    draft: &TicketDraft,
    info: &DeviceInfo,
    api: &mut impl SupportApi,
    data_dir: &Path,
) -> Result<String, SupportError> {
    let body = build_request(draft, info)?;
    let created = api.create(&body)?;
    let mut tickets = load_ledger(data_dir);
    tickets.push(TrackedTicket {
        ticket_id: created.ticket_id.clone(),
        token: created.token,
        announced: false,
    });
    save_ledger(data_dir, &tickets);
    Ok(created.ticket_id)
}

/// Asks the service about each ticket not yet announced and returns the newly fixed ones, once each.
pub fn collect_updates(api: &mut impl SupportApi, data_dir: &Path) -> Vec<FixedNotice> {
    let mut tickets = load_ledger(data_dir);
    let mut fixed = Vec::new();
    for ticket in tickets
        .iter_mut()
        .filter(|ticket| !ticket.announced)
        .take(MAX_STATUS_CHECKS)
    {
        if let Ok(TicketStatus {
            fixed_in: Some(version),
        }) = api.status(&ticket.ticket_id, &ticket.token)
        {
            ticket.announced = true;
            fixed.push(FixedNotice {
                ticket_id: ticket.ticket_id.clone(),
                fixed_in: version,
            });
        }
    }
    if !fixed.is_empty() {
        save_ledger(data_dir, &tickets);
    }
    fixed
}

/// A stable, anonymous id for this install: a hash of a random id kept in the app data folder.
pub fn install_hash(data_dir: &Path) -> String {
    let path = data_dir.join(INSTALL_ID_FILE);
    let id = fs::read_to_string(&path)
        .ok()
        .map(|text| text.trim().to_string())
        .filter(|text| text.len() == 36)
        .unwrap_or_else(|| {
            let fresh = uuid::Uuid::new_v4().to_string();
            let _ = fs::create_dir_all(data_dir);
            let _ = fs::write(&path, &fresh);
            fresh
        });
    sha256_hex(&format!("officekit-support:{id}"))
}

pub fn sha256_hex(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Letters, digits and a few separators only, so the server's strict field patterns always accept it.
pub fn sanitize_field(value: &str, fallback: &str, max_chars: usize, allowed: &str) -> String {
    let cleaned: String = value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric() || allowed.contains(*ch))
        .take(max_chars)
        .collect();
    if cleaned.trim().is_empty() {
        fallback.to_string()
    } else {
        cleaned
    }
}

pub struct HttpSupportApi {
    base_url: String,
    agent: ureq::Agent,
}

fn map_http_error(error: ureq::Error) -> SupportError {
    match error {
        ureq::Error::StatusCode(429) => SupportError::RateLimited,
        ureq::Error::StatusCode(400 | 413 | 415 | 422) => SupportError::Invalid,
        ureq::Error::StatusCode(_) => SupportError::Unavailable,
        _ => SupportError::Offline,
    }
}

impl HttpSupportApi {
    pub fn new() -> Result<Self, SupportError> {
        let base_url = configured_license_api_base_url().map_err(|_| SupportError::Unavailable)?;
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(20)))
            .build()
            .into();
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            agent,
        })
    }

    fn read_json(response: ureq::http::Response<ureq::Body>) -> Result<Value, SupportError> {
        let mut bytes = Vec::with_capacity(512);
        response
            .into_body()
            .into_reader()
            .take((MAX_RESPONSE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| SupportError::Offline)?;
        if bytes.is_empty() || bytes.len() > MAX_RESPONSE_BYTES {
            return Err(SupportError::Unavailable);
        }
        serde_json::from_slice(&bytes).map_err(|_| SupportError::Unavailable)
    }
}

impl SupportApi for HttpSupportApi {
    fn create(&mut self, body: &Value) -> Result<CreatedTicket, SupportError> {
        let response = self
            .agent
            .post(&format!("{}/v1/support-tickets", self.base_url))
            .send_json(body)
            .map_err(map_http_error)?;
        let value = Self::read_json(response)?;
        match (value["ticket_id"].as_str(), value["token"].as_str()) {
            (Some(ticket_id), Some(token)) if !ticket_id.is_empty() && token.len() == 22 => {
                Ok(CreatedTicket {
                    ticket_id: ticket_id.to_string(),
                    token: token.to_string(),
                })
            }
            _ => Err(SupportError::Unavailable),
        }
    }

    fn status(&mut self, ticket_id: &str, token: &str) -> Result<TicketStatus, SupportError> {
        let response = self
            .agent
            .get(&format!("{}/v1/support-tickets/{ticket_id}", self.base_url))
            .header(TOKEN_HEADER, token)
            .call()
            .map_err(map_http_error)?;
        let value = Self::read_json(response)?;
        let fixed_in = (value["status"] == "fixed")
            .then(|| value["fixed_in"].as_str().map(str::to_string))
            .flatten();
        Ok(TicketStatus { fixed_in })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HASH: &str = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";

    fn info() -> DeviceInfo {
        DeviceInfo {
            app_version: "1.0.115".into(),
            os_version: "macOS 27.2".into(),
            model: "Mac13,1".into(),
            device_hash: HASH[..64].to_string(),
            license_hash: None,
        }
    }

    fn draft() -> TicketDraft {
        TicketDraft {
            kind: "bug".into(),
            title: "  Snippets do not expand ".into(),
            description: "Typed the keyword.\nNothing happened.".into(),
            email: Some(" user@example.com ".into()),
            display_name: None,
            publication_consent: None,
        }
    }

    fn scratch(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("officekit-support-{name}-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[derive(Default)]
    struct FakeApi {
        created: Vec<Value>,
        fail_create: Option<SupportError>,
        fixed: Vec<(String, String)>,
        status_calls: Vec<String>,
        fail_status: bool,
    }

    impl SupportApi for FakeApi {
        fn create(&mut self, body: &Value) -> Result<CreatedTicket, SupportError> {
            if let Some(error) = self.fail_create {
                return Err(error);
            }
            self.created.push(body.clone());
            Ok(CreatedTicket {
                ticket_id: format!("OK-{}", self.created.len()),
                token: "T".repeat(22),
            })
        }

        fn status(&mut self, ticket_id: &str, _token: &str) -> Result<TicketStatus, SupportError> {
            self.status_calls.push(ticket_id.to_string());
            if self.fail_status {
                return Err(SupportError::Offline);
            }
            Ok(TicketStatus {
                fixed_in: self
                    .fixed
                    .iter()
                    .find(|(id, _)| id == ticket_id)
                    .map(|(_, version)| version.clone()),
            })
        }
    }

    #[test]
    fn a_bug_report_carries_only_the_typed_text_and_basic_device_facts() {
        let body = build_request(&draft(), &info()).unwrap();
        assert_eq!(body["type"], "bug");
        assert_eq!(body["title"], "Snippets do not expand");
        assert_eq!(body["email"], "user@example.com");
        assert_eq!(body["app_version"], "1.0.115");
        assert!(body.get("license_hash").is_none());
        let mut keys: Vec<_> = body.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        assert_eq!(
            keys,
            [
                "app_version",
                "description",
                "device_hash",
                "email",
                "model",
                "os_version",
                "title",
                "type"
            ]
        );
    }

    #[test]
    fn an_empty_email_is_dropped_and_a_bad_one_is_refused() {
        let mut no_email = draft();
        no_email.email = Some("   ".into());
        assert!(build_request(&no_email, &info())
            .unwrap()
            .get("email")
            .is_none());
        for bad in ["nope", "a b@c.com"] {
            let mut report = draft();
            report.email = Some(bad.into());
            assert_eq!(build_request(&report, &info()), Err(SupportError::Invalid));
        }
        let mut long = draft();
        long.email = Some(format!("{}@x.com", "a".repeat(260)));
        assert_eq!(build_request(&long, &info()), Err(SupportError::Invalid));
    }

    #[test]
    fn bad_drafts_never_leave_the_mac() {
        let cases: Vec<Box<dyn Fn(&mut TicketDraft)>> = vec![
            Box::new(|d| d.kind = "other".into()),
            Box::new(|d| d.title = "".into()),
            Box::new(|d| d.title = "a\nb".into()),
            Box::new(|d| d.title = "x".repeat(MAX_TITLE_CHARS + 1)),
            Box::new(|d| d.description = " ".into()),
            Box::new(|d| d.description = "x".repeat(MAX_DESCRIPTION_CHARS + 1)),
            Box::new(|d| d.description = "bad\u{0}char".into()),
        ];
        for change in cases {
            let mut report = draft();
            change(&mut report);
            assert_eq!(build_request(&report, &info()), Err(SupportError::Invalid));
        }
        let mut bad_info = info();
        bad_info.device_hash = "short".into();
        assert_eq!(
            build_request(&draft(), &bad_info),
            Err(SupportError::Invalid)
        );
        let mut bad_license = info();
        bad_license.license_hash = Some("short".into());
        assert_eq!(
            build_request(&draft(), &bad_license),
            Err(SupportError::Invalid)
        );
    }

    #[test]
    fn a_licensed_mac_sends_a_hash_and_a_testimonial_sends_its_permission() {
        let mut licensed = info();
        licensed.license_hash = Some(HASH[..64].to_string());
        assert_eq!(
            build_request(&draft(), &licensed).unwrap()["license_hash"],
            HASH[..64]
        );

        let mut testimonial = draft();
        testimonial.kind = "testimonial".into();
        testimonial.display_name = Some(" Ada ".into());
        testimonial.publication_consent = Some(true);
        let body = build_request(&testimonial, &info()).unwrap();
        assert_eq!(body["display_name"], "Ada");
        assert_eq!(body["publication_consent"], true);

        testimonial.display_name = Some("  ".into());
        testimonial.publication_consent = None;
        let body = build_request(&testimonial, &info()).unwrap();
        assert!(body.get("display_name").is_none());
        assert_eq!(body["publication_consent"], false);

        testimonial.display_name = Some("x".repeat(MAX_DISPLAY_NAME_CHARS + 1));
        assert_eq!(
            build_request(&testimonial, &info()),
            Err(SupportError::Invalid)
        );
    }

    #[test]
    fn a_sent_report_is_remembered_and_a_failed_one_is_not() {
        let dir = scratch("submit");
        let mut api = FakeApi::default();
        assert_eq!(
            submit_ticket(&draft(), &info(), &mut api, &dir),
            Ok("OK-1".to_string())
        );
        assert_eq!(load_ledger(&dir).len(), 1);
        assert!(!load_ledger(&dir)[0].announced);

        api.fail_create = Some(SupportError::Offline);
        assert_eq!(
            submit_ticket(&draft(), &info(), &mut api, &dir),
            Err(SupportError::Offline)
        );
        let mut bad = draft();
        bad.title.clear();
        api.fail_create = None;
        assert_eq!(
            submit_ticket(&bad, &info(), &mut api, &dir),
            Err(SupportError::Invalid)
        );
        assert_eq!(load_ledger(&dir).len(), 1);
        assert_eq!(api.created.len(), 1);
    }

    #[test]
    fn a_fix_is_announced_once() {
        let dir = scratch("updates");
        let mut api = FakeApi::default();
        submit_ticket(&draft(), &info(), &mut api, &dir).unwrap();
        submit_ticket(&draft(), &info(), &mut api, &dir).unwrap();

        assert!(collect_updates(&mut api, &dir).is_empty());
        api.fixed.push(("OK-2".into(), "1.0.116".into()));
        assert_eq!(
            collect_updates(&mut api, &dir),
            vec![FixedNotice {
                ticket_id: "OK-2".into(),
                fixed_in: "1.0.116".into()
            }]
        );
        api.status_calls.clear();
        assert!(collect_updates(&mut api, &dir).is_empty());
        assert_eq!(
            api.status_calls,
            vec!["OK-1".to_string()],
            "the announced ticket is not asked about again"
        );
    }

    #[test]
    fn a_status_failure_leaves_the_ticket_for_next_time() {
        let dir = scratch("status-fail");
        let mut api = FakeApi::default();
        submit_ticket(&draft(), &info(), &mut api, &dir).unwrap();
        api.fail_status = true;
        api.fixed.push(("OK-1".into(), "1.0.116".into()));
        assert!(collect_updates(&mut api, &dir).is_empty());
        api.fail_status = false;
        assert_eq!(collect_updates(&mut api, &dir).len(), 1);
    }

    #[test]
    fn the_ledger_is_bounded_and_a_damaged_file_is_ignored() {
        let dir = scratch("ledger");
        let many: Vec<TrackedTicket> = (0..70)
            .map(|index| TrackedTicket {
                ticket_id: format!("OK-{index}"),
                token: "T".repeat(22),
                announced: true,
            })
            .collect();
        save_ledger(&dir, &many);
        let kept = load_ledger(&dir);
        assert_eq!(kept.len(), MAX_TRACKED_TICKETS);
        assert_eq!(kept[0].ticket_id, "OK-20");
        fs::write(ledger_path(&dir), b"not json").unwrap();
        assert!(load_ledger(&dir).is_empty());
    }

    #[test]
    fn the_install_hash_is_stable_anonymous_and_recreated_when_damaged() {
        let dir = scratch("install");
        let first = install_hash(&dir);
        assert_eq!(first.len(), 64);
        assert_eq!(first, install_hash(&dir));
        assert!(!fs::read_to_string(dir.join(INSTALL_ID_FILE))
            .unwrap()
            .contains(&first));
        fs::write(dir.join(INSTALL_ID_FILE), "short").unwrap();
        assert_ne!(first, install_hash(&dir));
        let nested = dir.join("a").join("b");
        assert_eq!(install_hash(&nested).len(), 64);
    }

    #[test]
    fn fields_are_reduced_to_what_the_server_accepts() {
        assert_eq!(sanitize_field("Mac13,1\n", "Mac", 40, " ,._-"), "Mac13,1");
        assert_eq!(sanitize_field("<>;", "Mac", 40, " ,._-"), "Mac");
        assert_eq!(sanitize_field("abcdef", "x", 3, ""), "abc");
        assert_eq!(sha256_hex("a").len(), 64);
    }

    #[test]
    fn messages_say_nothing_was_sent_when_it_was_not() {
        assert!(SupportError::Offline
            .public_message()
            .contains("Nothing was sent"));
        assert!(SupportError::Unavailable
            .public_message()
            .contains("Nothing was sent"));
        assert!(SupportError::RateLimited
            .public_message()
            .contains("tomorrow"));
        assert!(SupportError::Invalid
            .public_message()
            .contains("Check the title"));
    }

    #[test]
    fn http_errors_map_to_user_facing_kinds() {
        assert_eq!(
            map_http_error(ureq::Error::StatusCode(429)),
            SupportError::RateLimited
        );
        assert_eq!(
            map_http_error(ureq::Error::StatusCode(400)),
            SupportError::Invalid
        );
        assert_eq!(
            map_http_error(ureq::Error::StatusCode(413)),
            SupportError::Invalid
        );
        assert_eq!(
            map_http_error(ureq::Error::StatusCode(503)),
            SupportError::Unavailable
        );
        assert_eq!(
            map_http_error(ureq::Error::Timeout(ureq::Timeout::Global)),
            SupportError::Offline
        );
    }
}
