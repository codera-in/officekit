# Animated meeting countdown implementation

Version: 1.0.0 · 2026-10-21.

| File | Change | Contract |
| --- | --- | --- |
| macos-calendar.swift | Serial EventKit feed, async permission, JSON ABI with paired free | Local read/permission |
| meeting_calendar.rs | Strict bounded DTOs, absolute-time selection, stale feed, occurrence hiding, preview | Meeting state/settings |
| ergonomics.rs | Compatible preference defaults, poller, snapshot composition, main-only permission command | Native Ergonomics commands |
| lib.rs, build.rs, Info.plist, Entitlements.plist | IPC registration, framework compile/link and permission declarations | Native integration |
| officekit-ergonomics.js | Calendar card and selection, permission/error/platform states, existing save dock | Settings/update/preview |
| ergonomics-companion.js/.css | Meeting text/countdown, looping pose stages, hide and reduced-motion static frame | State/action |
| assets/ergonomics/meeting.png + asset allowlist | Bundle approved v2 sheet | Packaging |
| engine_comms.py + index.html | Search and route Meeting Countdown to shared workbench | Discovery |

Errors use fixed messages; no calendar content/native error logging. User-supplied event titles use textContent. Strict calendar settings are atomically persisted through the existing store; serde defaults migrate prior settings. Cache is cleared on disable. No changes to events or local Calendar databases.

Test plan: Rust boundary/overlap/staleness/selection/preview/dismissal tests; native command authorization; Swift compile; browser permission/settings, live pose frames, stage transitions and reduced motion; tool search; full npm/Rust suites; desktop build/packaged smoke. Real system permission UI, synced events, wake/fullscreen/focus require installed-app checks and are never inferred from fixtures.
