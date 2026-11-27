# Pending tools and ergonomics — implementation sequence

version: 1.1.2 · 2026-10-26 · Eye cues draw their matching gaze, blink and side-to-side sprite frames; reduced motion keeps the current cue's first pose.

## Slice 1 file map

The approved paths below are implemented in source. Generated `dist-ui` assets come from the UI build.

| Path | Change / HLD boundary |
| --- | --- |
| `API-CONTRACT.md` | Versioned native ergonomics settings/state/action/event DTOs; strict validation, permission and stale-action failures |
| `src-tauri/src/ergonomics.rs` | Clock-injected scheduler, independent schedules, quiet hours, snooze/pause, single prompt, wake reconciliation, validated preferences and tests |
| `src-tauri/macos-user-activity.swift` / `src-tauri/macos-dictation.swift` / Rust FFI | Poll keyboard/mouse/trackpad idle age and recent non-silent signal from OfficeKit's already-authorized voice capture; silent mic streams do not count, and automatic prompts hide while inactive |
| `src-tauri/src/headphone_motion.rs` | Platform-neutral status/relative-angle policy; stale samples, calibration, dwell, hysteresis and cooldown tests |
| `src-tauri/src/macos_headphone_motion.swift` | macOS Core Motion permission/availability/connect/disconnect/sample bridge, with bounded lifecycle |
| `src-tauri/build.rs` / app Info.plist | Compile helper against existing minimum OS and add explicit motion-purpose string |
| `src-tauri/src/lib.rs` | Register commands, scheduler lifecycle, independent companion window and shutdown; no UI dispatch under mutex |
| `src-tauri/capabilities/` / `tauri.conf.json` | Narrow companion-window permissions and CSP; local assets only |
| `index.html` / `assets/officekit-ergonomics.js` | Approved workbench, exact routes, validated state client, keyboard access and persistent action-dock controls |
| `assets/ergonomics-companion.html` / companion JS/assets | Approved original animated character, prompt actions, bounded state polling, cue-matched stretch and eye frames, static reduced-motion equivalent |
| `officekit/engines/engine_comms.py` | Search entries/synonyms for break, eyes, water and head angle; exact shared-workbench modes |
| `scripts/build-ui-assets.mjs` | Bundle new source assets and companion entry; never hand-edit dist-ui |
| `tests/` / `ui-tests/ergonomics.spec.mjs` | Search/routing/profile/DTO tests, reminder actions, activity-gated scheduler, native-size corner bounds and animation flows |
| `docs/TOOL-GUIDE.md`, `docs/TESTING.md`, review evidence | Actual supported behavior, test results and outstanding installed checks; bump versions/history when edited |

## Ordered checkpoints

1. Approve recommended delivery order, ergonomics mock and HLD together. Record exact owner wording. Remove temporary mock/server after approval, retaining screenshots and durable decision.
2. Finalize native DTO contract and settings bounds. Break interval proposed 5–180 minutes, duration 20–900 seconds; eye interval 5–120 minutes, duration 10–120 seconds; water interval 5–240 minutes. These are UI configuration bounds, not health recommendations. No water-volume target.
3. Implement and test pure scheduler first. Test disabled defaults, independent enable/disable, monotonic timing, midnight/DST quiet hours, one prompt, duplicate actions, snooze, pause expiry, settings edits, restart, sleep/wake and clock adjustments. Invalid persistence must never turn features on.
4. Implement motion policy and native adapter. Calibrate only on sufficient fresh stable samples; initial engineering proposal: 5-second calibration, 15-degree relative pitch threshold, 20-second default dwell (editable 5–120 sec), 5-degree hysteresis, 5-minute default cooldown (editable 1–60 min). Every reminder also has an independently editable 1–60 minute snooze. Tune angle thresholds using real AirPods data, expose angle sensitivity only if approved. Disconnect/stale data invalidates detection; reconnect requires a trustworthy baseline, with recalibration if needed.
5. Add the companion window and main workbench faithfully to the mock. Present without focus stealing. Start/done/snooze/pause are native actions scoped to the current reminder; preview cannot modify live schedules. A countdown runs only after Start. Water requires no countdown. Never render raw exception text. Use distinct water cap-open/drink/recap, stretch and eye-rest animation states, with static reduced-motion poses. Validate frame anatomy, alignment, loop seams and prop continuity before bundling. Add a four-value corner setting; test all corner placements against logical work-area geometry, taskbars/Dock, mixed-DPI monitors and display removal. Corner changes move the whole prompt/character unit without resetting a reminder.
6. Wire discovery and package assets. Keep new tools development-only until verified; no beta profile expansion without an explicit release decision.
7. Run focused suites then npm test, Rust checks and package smoke. Use isolated app data. Review the complete diff through se-review with UX. Record installed hardware checks separately.
8. Continue slices 2–7 from the HLD, with per-group endpoint contracts, mock approval and independent numerical/file-output fixtures. Prefer real engine reuse over the disconnected dispatcher.

## Failure behavior

Unsupported OS activity detector: automatic reminders fail closed, and the workbench discloses that they currently require macOS; previews remain available. Unsupported headphones: motion explains unavailable. Denied motion permission: no retry loop or automatic settings launch. AirPods disconnect: stop detection and clear dwell; no catch-up nudge. Report posture cooldown/next eligibility with the other next-due states. Window display failure: retain an actionable error in the main workbench, without claiming delivery. Corrupt settings: keep features disabled and offer reset. Shut down native updates and timers on explicit Quit. Never persist raw sensor samples, secrets or selected file contents.

## Validation record

The owner-approved mock is recorded in `docs/ui-research/2026-10-21-approved-ergonomics.md`. The full Rust suite passes 252 tests (three opt-in inference tests ignored); `cargo check --bin officekit`, Swift compilation and Rust formatting pass. Activity-gate regression tests verify reminders stay queued while inactive, pause ready and active prompt deadlines until activity returns, hide automatic prompts when presence expires, and release them after recent keyboard/pointer or OfficeKit voice input. A silent microphone does not count, and manual previews remain visible. Focused Node routing/UI checks pass, Python ergonomics search tests pass, and all 20 focused desktop/compact WebKit checks pass, including the real companion's 300×460 bounds, keyboard focus order and shared action-dock fit. UI bundling and generated CSP output pass. Full `npm test` passes (2,379 Python tests, four skipped, 1,716 subtests), and the packaged media MCP launcher test passes after a sidecar build. Installed native interaction, physical AirPods calibration, and packaged DMG smoke remain open. The review scripts/templates were unavailable on the host; three reviewer perspectives signed off after fixes. `cargo llvm-cov --manifest-path src-tauri/Cargo.toml --lib` reports 95.38% line coverage for the native ergonomics scheduler and 98.97% for the headphone policy; the harness's 100% backend-coverage gate remains open under the owner's ship exception.
