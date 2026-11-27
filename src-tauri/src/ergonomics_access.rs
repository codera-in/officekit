/// Ergonomics ships in every build the app has (owner decision, 2026-10-23); an unknown profile gets none.
pub fn profile_enabled(profile: &str) -> bool {
    matches!(profile, "development" | "private-beta")
}

/// The secondary reminder webview never receives the main window's IPC authority.
pub fn command_allowed(window: &str, command: &str, profile: &str) -> bool {
    if command.starts_with("quick_controls_") {
        return window == "quick-controls";
    }
    // The Live Workspace shows spoken text, so its webview reaches nothing but its own commands.
    if command.starts_with("coach_workspace_") {
        return window == "coach-workspace";
    }
    if window == "coach-workspace" {
        return false;
    }
    // The page that samples the numbers owns the menu bar; Quick controls changes it through its own command.
    // Restore from Trash commands are used only by the main window's Files screen (DEVOPS-2).
    if command.starts_with("menu_stats_")
        || command.starts_with("app_settings_")
        || command.starts_with("calendar_permission_")
        || command.starts_with("trash_")
        || command.starts_with("invoice_")
    {
        return window == "main";
    }
    if window == "quick-controls"
        && matches!(
            command,
            "ergonomics_quick_controls_status" | "ergonomics_quick_controls_set_enabled"
        )
    {
        return true;
    }
    if window == "ergonomics" {
        return profile_enabled(profile)
            && matches!(
                command,
                "ergonomics_get_state" | "ergonomics_reminder_action"
            );
    }
    if command.starts_with("ergonomics_") {
        return window == "main" && profile_enabled(profile);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::command_allowed;

    #[test]
    fn menu_stats_commands_belong_to_the_main_window_only() {
        for command in [
            "menu_stats_status",
            "menu_stats_adopt_legacy",
            "app_settings_status",
            "app_settings_save",
            "calendar_permission_status",
            "calendar_permission_request",
        ] {
            assert!(command_allowed("main", command, "production"));
            for window in ["quick-controls", "ergonomics", "coach-workspace"] {
                assert!(!command_allowed(window, command, "production"));
            }
        }
    }

    #[test]
    fn companion_has_only_two_development_commands() {
        assert!(command_allowed(
            "ergonomics",
            "ergonomics_get_state",
            "development"
        ));
        assert!(command_allowed(
            "ergonomics",
            "ergonomics_reminder_action",
            "development"
        ));
        for (command, profile) in [
            ("ergonomics_get_state", "unknown"),
            ("ergonomics_update_settings", "development"),
            ("ergonomics_preview", "development"),
            ("plugin:event|listen", "development"),
        ] {
            assert!(!command_allowed("ergonomics", command, profile));
        }
    }

    #[test]
    fn trash_restore_commands_are_main_window_only() {
        for command in [
            "trash_restore_confirm",
            "trash_restore_apply",
            "trash_record_forget",
            "trash_restore_reveal",
            "invoice_library_reconnect",
        ] {
            assert!(command_allowed("main", command, "development"));
            assert!(command_allowed("main", command, "private-beta"));
            assert!(!command_allowed("quick-controls", command, "development"));
            assert!(!command_allowed("ergonomics", command, "development"));
        }
    }

    #[test]
    fn main_ergonomics_commands_work_in_every_build_and_other_commands_pass_through() {
        for profile in ["development", "private-beta"] {
            assert!(command_allowed(
                "main",
                "ergonomics_update_settings",
                profile
            ));
        }
        assert!(!command_allowed(
            "main",
            "ergonomics_update_settings",
            "unknown"
        ));
        assert!(!command_allowed(
            "other",
            "ergonomics_update_settings",
            "development"
        ));
        assert!(command_allowed("main", "ordinary_command", "private-beta"));
        assert!(command_allowed("other", "ordinary_command", "development"));
    }

    #[test]
    fn coach_workspace_window_gets_only_its_own_commands() {
        for command in [
            "coach_workspace_snapshot",
            "coach_workspace_dismiss",
            "coach_workspace_corrected_text",
            "coach_workspace_done",
        ] {
            assert!(command_allowed("coach-workspace", command, "production"));
            assert!(!command_allowed("main", command, "production"));
            assert!(!command_allowed("quick-controls", command, "production"));
        }
        for command in [
            "speech_coach_status",
            "dictation_start",
            "ergonomics_get_state",
            "quick_controls_set_tool",
        ] {
            assert!(!command_allowed("coach-workspace", command, "development"));
        }
    }

    #[test]
    fn quick_controls_get_only_pause_and_resume_authority() {
        assert!(command_allowed(
            "quick-controls",
            "ergonomics_quick_controls_status",
            "private-beta"
        ));
        assert!(command_allowed(
            "quick-controls",
            "ergonomics_quick_controls_set_enabled",
            "production"
        ));
        assert!(!command_allowed(
            "quick-controls",
            "ergonomics_update_settings",
            "development"
        ));
    }
}
