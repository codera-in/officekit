//! Local calendar DTOs and absolute-time meeting selection. No event data is persisted.
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

pub const LEAD_SECONDS: u64 = 30 * 60;
pub const START_GESTURE_SECONDS: u64 = 8;
/// With "Offer to record calls" on, a meeting that has started keeps its Record offer this long.
pub const RECORD_OFFER_SECONDS: u64 = 120;
/// A call app must hold the microphone this long before it is offered, so a blip is ignored.
const CALL_DEBOUNCE_SECONDS: u64 = 5;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MeetingSettings {
    pub enabled: bool,
    pub all_calendars: bool,
    pub calendar_ids: Vec<String>,
    /// Off by default: show a Record button when a meeting starts or a call app takes the microphone.
    #[serde(default)]
    pub offer_recording: bool,
}
impl Default for MeetingSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            all_calendars: true,
            calendar_ids: vec![],
            offer_recording: false,
        }
    }
}
/// What the call watcher found on the microphone, shown as a reminder with a Record button.
#[derive(Clone, Debug, PartialEq)]
pub struct CallOffer {
    pub id: String,
    /// The call app's name, or None when only a browser holds the microphone.
    pub app: Option<String>,
}
#[derive(Default)]
struct CallWatch {
    since: Option<u64>,
    app: Option<String>,
    declined: bool,
    seq: u64,
}
impl MeetingSettings {
    pub fn validate(&self) -> Result<(), String> {
        if self.calendar_ids.len() > 256
            || self
                .calendar_ids
                .iter()
                .any(|id| id.is_empty() || id.len() > 2048)
        {
            return Err("Select at most 256 valid calendars".into());
        }
        let unique: HashSet<_> = self.calendar_ids.iter().collect();
        if unique.len() != self.calendar_ids.len() {
            return Err("Calendar selections must be unique".into());
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Calendar {
    pub id: String,
    pub title: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Event {
    pub id: String,
    pub calendar_id: String,
    pub title: String,
    pub calendar_title: String,
    pub start: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Feed {
    pub status: String,
    pub calendars: Vec<Calendar>,
    pub events: Vec<Event>,
}
impl Feed {
    pub fn empty(status: &str) -> Self {
        Self {
            status: status.into(),
            calendars: vec![],
            events: vec![],
        }
    }
    fn valid(&self) -> bool {
        [
            "allowed",
            "permission-needed",
            "denied",
            "restricted",
            "requesting",
            "unavailable",
            "error",
        ]
        .contains(&self.status.as_str())
            && self.calendars.len() <= 256
            && self.events.len() <= 2048
            && self
                .calendars
                .iter()
                .all(|c| !c.id.is_empty() && c.id.len() <= 2048 && c.title.len() <= 4096)
            && self.events.iter().all(|e| {
                !e.id.is_empty()
                    && e.id.len() <= 4096
                    && e.calendar_id.len() <= 2048
                    && e.title.len() <= 4096
                    && e.calendar_title.len() <= 4096
                    && e.start <= 253402300799
            })
    }
}
#[derive(Default)]
pub struct CalendarCore {
    feed: Option<Feed>,
    fetched_at: u64,
    hidden: HashMap<String, u64>,
    preview_until: Option<u64>,
    call: CallWatch,
    recording: bool,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarSnapshot {
    pub status: String,
    pub calendars: Vec<Calendar>,
    pub selected_event: Option<Event>,
    pub preview: bool,
}
impl CalendarCore {
    pub fn replace(&mut self, feed: Feed, now: u64) {
        self.feed = Some(if feed.valid() {
            feed
        } else {
            Feed::empty("error")
        });
        self.fetched_at = now;
        self.hidden
            .retain(|_, start| start.saturating_add(RECORD_OFFER_SECONDS) > now);
    }
    /// `call` is None when no app is capturing the microphone, otherwise the call app's name
    /// (itself None for a browser). While OfficeKit is recording, the current call counts as handled.
    pub fn observe_call(&mut self, call: Option<Option<&str>>, own_recording: bool, now: u64) {
        self.recording = own_recording;
        let Some(app) = call else {
            self.call = CallWatch {
                seq: self.call.seq,
                ..CallWatch::default()
            };
            return;
        };
        if self.call.since.is_none() {
            self.call.since = Some(now);
            self.call.seq += 1;
        }
        self.call.app = app.map(str::to_owned);
        if own_recording {
            self.call.declined = true;
        }
    }
    pub fn recording(&self) -> bool {
        self.recording
    }
    pub fn call_offer(&self, now: u64) -> Option<CallOffer> {
        let since = self.call.since?;
        (!self.call.declined && now.saturating_sub(since) >= CALL_DEBOUNCE_SECONDS).then(|| {
            CallOffer {
                id: format!("call-{}", self.call.seq),
                app: self.call.app.clone(),
            }
        })
    }
    pub fn decline_call(&mut self) {
        self.call.declined = true;
    }
    pub fn clear(&mut self) {
        self.feed = None;
        self.fetched_at = 0;
        self.preview_until = None;
    }
    pub fn preview(&mut self, now: u64) {
        self.preview_until = Some(now + 20);
    }
    pub fn close_preview(&mut self) {
        self.preview_until = None;
    }
    pub fn hide(&mut self, id: &str, settings: &MeetingSettings, now: u64) -> Result<(), String> {
        let selected = self
            .snapshot(settings, now)
            .selected_event
            .ok_or("This meeting has expired")?;
        if selected.id != id {
            return Err("This meeting has changed; use the current reminder".into());
        }
        self.hidden.insert(selected.id, selected.start);
        self.preview_until = None;
        Ok(())
    }
    pub fn snapshot(&self, settings: &MeetingSettings, now: u64) -> CalendarSnapshot {
        if self.preview_until.is_some_and(|until| now < until) {
            return CalendarSnapshot {
                status: "preview".into(),
                calendars: vec![],
                preview: true,
                selected_event: Some(Event {
                    id: "meeting-preview".into(),
                    calendar_id: "preview".into(),
                    title: "Product catch-up".into(),
                    calendar_title: "Sample calendar".into(),
                    // Preview runs all three animation phases within 20 seconds.
                    start: self.preview_until.unwrap() - 8,
                }),
            };
        }
        let feed = self.feed.as_ref();
        let fresh = self.fetched_at <= now && now - self.fetched_at <= 45;
        let status = if !cfg!(target_os = "macos") {
            "unavailable"
        } else if !settings.enabled {
            "disabled"
        } else if !fresh {
            "refreshing"
        } else {
            feed.map_or("refreshing", |f| f.status.as_str())
        };
        let start_window = if settings.offer_recording {
            RECORD_OFFER_SECONDS
        } else {
            START_GESTURE_SECONDS
        };
        let selected_event = if settings.enabled && fresh {
            feed.filter(|f| f.status == "allowed").and_then(|f| {
                f.events
                    .iter()
                    .filter(|e| {
                        (settings.all_calendars || settings.calendar_ids.contains(&e.calendar_id))
                            && e.start <= now.saturating_add(LEAD_SECONDS)
                            && e.start.saturating_add(start_window) > now
                            && !self.hidden.contains_key(&e.id)
                    })
                    .min_by(|a, b| a.start.cmp(&b.start).then_with(|| a.id.cmp(&b.id)))
                    .cloned()
            })
        } else {
            None
        };
        CalendarSnapshot {
            status: status.into(),
            calendars: feed.map_or_else(Vec::new, |f| f.calendars.clone()),
            selected_event,
            preview: false,
        }
    }
}

#[cfg(all(target_os = "macos", not(test)))]
pub fn read(enabled: bool) -> Feed {
    use std::ffi::CStr;
    unsafe {
        let ptr = officekit_calendar_snapshot(enabled);
        if ptr.is_null() {
            return Feed::empty("error");
        }
        let bytes = CStr::from_ptr(ptr).to_bytes();
        let feed = if bytes.len() <= 2_000_000 {
            serde_json::from_slice(bytes).unwrap_or_else(|_| Feed::empty("error"))
        } else {
            Feed::empty("error")
        };
        officekit_calendar_free(ptr);
        feed
    }
}
#[cfg(any(not(target_os = "macos"), test))]
pub fn read(_enabled: bool) -> Feed {
    Feed::empty("unavailable")
}

/// The Calendar feed status in the permission words Setup and Settings use for every permission.
pub fn permission_word(status: &str) -> &'static str {
    match status {
        "allowed" => "granted",
        "permission-needed" | "requesting" => "undetermined",
        _ => "denied",
    }
}

#[derive(Serialize)]
pub struct CalendarPermission {
    pub permission: &'static str,
}

/// Reads only the access state; no calendar or event data is touched.
#[tauri::command]
pub fn calendar_permission_status() -> CalendarPermission {
    CalendarPermission {
        permission: permission_word(&read(false).status),
    }
}

/// Shows the macOS prompt when macOS still asks; afterwards the status is read again by the caller.
#[tauri::command]
pub fn calendar_permission_request() -> CalendarPermission {
    request_permission();
    calendar_permission_status()
}

#[cfg(all(target_os = "macos", not(test)))]
pub fn request_permission() {
    unsafe {
        officekit_calendar_request_access();
    }
}
#[cfg(any(not(target_os = "macos"), test))]
pub fn request_permission() {}
#[cfg(all(target_os = "macos", not(test)))]
unsafe extern "C" {
    fn officekit_calendar_snapshot(enabled: bool) -> *mut std::ffi::c_char;
    fn officekit_calendar_free(pointer: *mut std::ffi::c_char);
    fn officekit_calendar_request_access();
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn calendar_status_maps_to_the_permission_words() {
        assert_eq!(permission_word("allowed"), "granted");
        for status in ["permission-needed", "requesting"] {
            assert_eq!(permission_word(status), "undetermined");
        }
        for status in ["denied", "restricted", "error", "unavailable", ""] {
            assert_eq!(permission_word(status), "denied", "{status}");
        }
    }
    fn event(id: &str, start: u64) -> Event {
        Event {
            id: id.into(),
            calendar_id: "work".into(),
            title: "Meeting".into(),
            calendar_title: "Work".into(),
            start,
        }
    }
    fn ready(events: Vec<Event>) -> CalendarCore {
        let mut c = CalendarCore::default();
        c.replace(
            Feed {
                status: "allowed".into(),
                calendars: vec![],
                events,
            },
            1000,
        );
        c
    }
    fn settings() -> MeetingSettings {
        MeetingSettings {
            enabled: true,
            ..Default::default()
        }
    }
    #[test]
    fn a_call_is_offered_after_the_debounce_and_only_once_until_it_ends() {
        let mut c = CalendarCore::default();
        c.observe_call(Some(Some("Zoom")), false, 100);
        assert_eq!(c.call_offer(104), None, "a blip is ignored");
        let offer = c.call_offer(105).unwrap();
        assert_eq!(offer.app.as_deref(), Some("Zoom"));
        c.decline_call();
        c.observe_call(Some(Some("Zoom")), false, 200);
        assert_eq!(c.call_offer(200), None, "declined until the call ends");
        c.observe_call(None, false, 210);
        c.observe_call(Some(None), false, 300);
        let next = c.call_offer(306).unwrap();
        assert_eq!(next.app, None);
        assert_ne!(next.id, offer.id, "a new call is a new offer");
    }

    #[test]
    fn recording_in_progress_counts_the_call_as_handled() {
        let mut c = CalendarCore::default();
        c.observe_call(Some(Some("Slack")), false, 100);
        c.observe_call(Some(Some("Slack")), true, 110);
        assert!(c.recording());
        c.observe_call(Some(Some("Slack")), false, 200);
        assert_eq!(
            c.call_offer(300),
            None,
            "stopping the recording does not re-offer"
        );
    }

    #[test]
    fn a_started_meeting_keeps_the_record_offer_only_when_recording_is_offered() {
        let mut s = settings();
        // The feed is refreshed at `now`, as the calendar thread does every few seconds.
        let at = |s: &MeetingSettings, now| {
            let mut c = CalendarCore::default();
            c.replace(
                Feed {
                    status: "allowed".into(),
                    calendars: vec![],
                    events: vec![event("a", 1000)],
                },
                now,
            );
            c.snapshot(s, now).selected_event.is_some()
        };
        assert!(!at(&s, 1000 + START_GESTURE_SECONDS));
        s.offer_recording = true;
        assert!(at(&s, 1000 + START_GESTURE_SECONDS));
        assert!(at(&s, 1000 + RECORD_OFFER_SECONDS - 1));
        assert!(!at(&s, 1000 + RECORD_OFFER_SECONDS));
    }

    #[test]
    fn window_boundaries_and_start_handoff() {
        for (start, expected) in [
            (2801, false),
            (2800, true),
            (1000, true),
            (993, true),
            (992, false),
        ] {
            assert_eq!(
                ready(vec![event("a", start)])
                    .snapshot(&settings(), 1000)
                    .selected_event
                    .is_some(),
                expected
            );
        }
    }
    #[test]
    fn selections_overlap_dismissal_and_expiry() {
        let mut c = ready(vec![event("b", 1100), event("a", 1100), event("c", 1200)]);
        assert_eq!(
            c.snapshot(&settings(), 1000).selected_event.unwrap().id,
            "a"
        );
        assert!(c.hide("stale", &settings(), 1000).is_err());
        c.hide("a", &settings(), 1000).unwrap();
        assert_eq!(
            c.snapshot(&settings(), 1000).selected_event.unwrap().id,
            "b"
        );
        let mut s = settings();
        s.all_calendars = false;
        assert!(c.snapshot(&s, 1000).selected_event.is_none());
        s.calendar_ids = vec!["work".into()];
        assert!(c.snapshot(&s, 1000).selected_event.is_some());
        s.enabled = false;
        assert!(c.snapshot(&s, 1000).selected_event.is_none());
    }
    #[test]
    fn stale_clock_changes_denial_and_deleted_events_hide_prompts() {
        let mut c = ready(vec![event("a", 1100)]);
        assert!(c.snapshot(&settings(), 1046).selected_event.is_none());
        assert!(c.snapshot(&settings(), 999).selected_event.is_none());
        for status in ["denied", "restricted", "error", "requesting"] {
            c.replace(
                Feed {
                    status: status.into(),
                    calendars: vec![],
                    events: vec![event("a", 1100)],
                },
                1000,
            );
            assert!(c.snapshot(&settings(), 1000).selected_event.is_none());
        }
        c.replace(Feed::empty("allowed"), 1000);
        assert!(c.snapshot(&settings(), 1000).selected_event.is_none());
    }
    #[test]
    fn bounded_inputs_preview_and_no_event_persistence() {
        let mut s = settings();
        s.calendar_ids = vec!["work".into(), "work".into()];
        assert!(s.validate().is_err());
        s.calendar_ids = vec!["".into()];
        assert!(s.validate().is_err());
        s.calendar_ids = vec!["x".repeat(2049)];
        assert!(s.validate().is_err());
        s.calendar_ids = vec!["work".into()];
        assert!(s.validate().is_ok());
        let mut c = ready(vec![event("a", 1100)]);
        c.preview(1000);
        assert!(c.snapshot(&s, 1000).preview);
        c.close_preview();
        assert!(!c.snapshot(&s, 1000).preview);
        c.preview(1000);
        assert!(!c.snapshot(&s, 1020).preview);
        c.clear();
        assert!(c.snapshot(&s, 1000).selected_event.is_none());
        let mut invalid = Feed::empty("bogus");
        invalid.events.push(event("a", 1100));
        c.replace(invalid, 1000);
        assert!(c.snapshot(&s, 1000).selected_event.is_none());
    }
}
