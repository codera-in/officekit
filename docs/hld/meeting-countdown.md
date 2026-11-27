# Animated local meeting countdown

Version: 1.0.0 · 2026-10-21 · Approved UI and macOS-first approach: owner “approved”.

Reuse the existing native corner companion. EventKit reads calendars configured in macOS Calendar after system authorization. Preferences belong to the local OS user: no tenancy, hosted service, database or cloud deployment. Persist only enablement, selection mode and calendar IDs. Event contents are bounded and session-only.

Swift reads EventKit on a serial background queue. Permission UI dispatches asynchronously, never waiting on the main queue while holding Rust runtime locks (P-177). A separate poller queries every ten seconds; stale feeds older than 45 seconds fail closed. Revoked access and errors drop event data. Absolute timestamps handle wake and clock edits. Recurring occurrences use event identifier plus occurrence timestamp. Skip all-day/cancelled/self-declined events; deterministic earliest-first selection handles overlaps. Hide suppresses one occurrence. At start, an eight-second wave precedes expiration.

Component tree: existing Ergonomics workbench → Meeting reminders card (enable, calendar selection, permission recovery, preview); shared Your companion placement/reduced motion/quiet hours and existing reserved save/pause dock. Shared overlay → existing bubble, countdown, canvas; meeting mode relabels Done to Hide this meeting and hides irrelevant Snooze/Pause actions. Meeting prompts have priority without replacing wellness settings or scheduling state; existing quiet hours and pause apply. Meetings do not require recent keyboard activity.

Contract: API-CONTRACT.md Ergonomics section. Companion keeps only its bounded state/action IPC. Native macOS permissions, focus/fullscreen/multi-monitor and installed acceptance remain separate from browser evidence; preserve development-only profile gating.
