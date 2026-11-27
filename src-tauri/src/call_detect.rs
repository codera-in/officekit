//! Which call app, if any, is capturing the microphone. Only app identifiers are read; no audio is
//! opened, heard or recorded, and nothing here is logged or stored.

const OWN_BUNDLE: &str = "app.officekit.desktop";
const CALL_APPS: &[(&str, &str)] = &[
    ("us.zoom.xos", "Zoom"),
    ("com.tinyspeck.slackmacgap", "Slack"),
    ("com.microsoft.teams2", "Teams"),
    ("com.microsoft.teams", "Teams"),
    ("com.apple.FaceTime", "FaceTime"),
    ("Cisco-Systems.Spark", "Webex"),
    ("com.cisco.webexmeetingsapp", "Webex"),
    ("com.hnc.Discord", "Discord"),
    ("com.skype.skype", "Skype"),
];
const BROWSERS: &[&str] = &[
    "com.google.Chrome",
    "com.apple.Safari",
    "com.apple.WebKit",
    "company.thebrowser.Browser",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "com.brave.Browser",
];

/// A bundle id matches an app when it is that id or one of its helpers ("<id>.helper").
fn is_app(bundle: &str, id: &str) -> bool {
    bundle == id
        || bundle
            .strip_prefix(id)
            .is_some_and(|rest| rest.starts_with('.'))
}

/// `bundles` is one bundle id per line, the apps holding the microphone right now.
/// Returns None for no call, `Some(Some(name))` for a known call app and `Some(None)` when only a
/// browser holds the microphone. OfficeKit itself and every other app (voice memos, music) is ignored.
pub fn classify(bundles: &str) -> Option<Option<&'static str>> {
    let mut browser = false;
    for bundle in bundles.lines().map(str::trim).filter(|b| !b.is_empty()) {
        if is_app(bundle, OWN_BUNDLE) {
            continue;
        }
        if let Some((_, name)) = CALL_APPS.iter().find(|(id, _)| is_app(bundle, id)) {
            return Some(Some(name));
        }
        browser |= BROWSERS.iter().any(|id| is_app(bundle, id));
    }
    browser.then_some(None)
}

#[cfg(all(target_os = "macos", not(test)))]
unsafe extern "C" {
    fn officekit_call_input_bundles(buffer: *mut std::os::raw::c_char, capacity: i32) -> i32;
}

#[cfg(all(target_os = "macos", not(test)))]
pub fn current_call() -> Option<Option<&'static str>> {
    let mut buffer = vec![0_u8; 4096];
    let written =
        unsafe { officekit_call_input_bundles(buffer.as_mut_ptr().cast(), buffer.len() as i32) };
    let written = usize::try_from(written).ok()?.min(buffer.len() - 1);
    classify(std::str::from_utf8(&buffer[..written]).ok()?)
}

#[cfg(any(not(target_os = "macos"), test))]
pub fn current_call() -> Option<Option<&'static str>> {
    None
}

#[cfg(test)]
mod tests {
    use super::classify;

    #[test]
    fn a_known_call_app_is_named_and_beats_a_browser() {
        assert_eq!(
            classify("com.google.Chrome\nus.zoom.xos"),
            Some(Some("Zoom"))
        );
        assert_eq!(
            classify("com.tinyspeck.slackmacgap.helper"),
            Some(Some("Slack"))
        );
        assert_eq!(classify("com.microsoft.teams2"), Some(Some("Teams")));
    }

    #[test]
    fn only_a_browser_is_a_call_without_a_name() {
        assert_eq!(classify("com.google.Chrome.helper"), Some(None));
        assert_eq!(classify("com.apple.Safari"), Some(None));
    }

    #[test]
    fn officekit_voice_memos_and_other_apps_are_never_a_call() {
        assert_eq!(classify(""), None);
        assert_eq!(classify("app.officekit.desktop"), None);
        assert_eq!(
            classify("app.officekit.desktop.helper\ncom.apple.VoiceMemos"),
            None
        );
        assert_eq!(classify("com.spotify.client"), None);
        // A look-alike id is not the app.
        assert_eq!(classify("us.zoom.xosfake"), None);
    }
}
