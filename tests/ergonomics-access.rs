#[path = "../src-tauri/src/ergonomics_access.rs"]
mod access;

#[test]
fn companion_cannot_reach_privileged_application_commands() {
    for command in [
        "officekit_api_token",
        "file_selection_open",
        "dictation_capture_start",
        "license_activate",
        "ergonomics_update_settings",
        "ergonomics_motion_action",
        "ergonomics_preview",
        "ergonomics_calendar_action",
    ] {
        assert!(
            !access::command_allowed("ergonomics", command, "development"),
            "{command}"
        );
    }
    for command in ["ergonomics_get_state", "ergonomics_reminder_action"] {
        assert!(access::command_allowed(
            "ergonomics",
            command,
            "development"
        ));
        assert!(access::command_allowed(
            "ergonomics",
            command,
            "private-beta"
        ));
        assert!(!access::command_allowed("ergonomics", command, "unknown"));
    }
    for command in ["plugin:event|listen", "plugin:event|unlisten"] {
        assert!(!access::command_allowed(
            "ergonomics",
            command,
            "development"
        ));
    }
}

#[test]
fn main_ergonomics_commands_require_development_and_auxiliary_windows_have_no_authority() {
    for command in [
        "ergonomics_get_state",
        "ergonomics_update_settings",
        "ergonomics_reminder_action",
        "ergonomics_preview",
        "ergonomics_motion_action",
        "ergonomics_calendar_action",
    ] {
        assert!(access::command_allowed("main", command, "development"));
        assert!(access::command_allowed("main", command, "private-beta"));
        assert!(!access::command_allowed("main", command, "unknown"));
        assert!(!access::command_allowed("other", command, "development"));
    }
    assert!(access::command_allowed(
        "main",
        "officekit_api_token",
        "private-beta"
    ));
    assert!(access::command_allowed(
        "main",
        "file_selection_open",
        "development"
    ));
}
