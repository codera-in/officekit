# LLD: Global desktop tools (clipboard, snippets, window manager)

Version: 1.0.0 · 2026-10-19

HLD: `docs/hld/global-desktop-tools.md`. Contract rows C1–C5 below are the HLD's contract-surface rows in order: C1 `POST /api/clipboard/clips`, C2 `GET /api/clipboard/history`, C3 `GET/PUT /api/clipboard/global-settings`, C4 `POST /api/clipboard/snippets`, C5 Tauri commands.

## Phase 0: shared layer

| File | Change | Ref |
| --- | --- | --- |
| `src-tauri/macos-global.swift` (new) | `OfficeKitHotkeys` (Carbon register/unregister by id, callback `(id) -> Void` through a `@convention(c)` pointer), `OfficeKitPanelHost` (key-capable non-activating `NSPanel`, captures frontmost PID, shows a JSON-described list, calls back selection), `OfficeKitLoginItem` (`SMAppService.mainApp`), `officekitGlobalAccessibilityStatus`. All exported with `@_cdecl("officekit_global_*")`. | C5 |
| `src-tauri/macos-global-bridge.swift` pure logic file `src-tauri/macos-global-logic.swift` (new) | Pure, AppKit-free types: `GlobalShortcut` parsing and normalization, `KeywordBuffer` and `KeywordMatcher`, `ClipFilter`, `DragEdgeClassifier`. Compiled into both the app and the Swift test binary so logic is testable without NSEvent. | HLD quality evidence |
| `src-tauri/build.rs` | `compile_macos_dictation_bridge` compiles `macos-dictation.swift`, `macos-global.swift` and `macos-global-logic.swift` together in one `swiftc` call with `-wmo` (required for several inputs with one `-o`); add `rerun-if-changed` for each; link `Carbon` and `ServiceManagement` frameworks. | all |
| `src-tauri/src/global_desktop.rs` (new module, `mod global_desktop;` in `lib.rs`) | Rust side: `GlobalDesktopSettings` (serde, `deny_unknown_fields`), validation (shortcut allowlist shared with dictation, no duplicates across features, gap 0–20, skip list ≤64 bundle ids), atomic persistence to `<data dir>/global-desktop.json` (size bound 64 KiB), `extern "C"` declarations for the Swift exports, event dispatcher thread, and the Tauri commands `global_desktop_status`, `global_desktop_configure`, `global_desktop_open_permission_settings`. Commands are registered only where `dictation_commands_enabled` is true. | C5 |
| `src-tauri/src/lib.rs` | `mod global_desktop;`, register commands, call `global_desktop::restore_on_launch(app)` in `setup` after the sidecar is healthy, call `global_desktop::shutdown()` on `RunEvent::Exit`. | C5 |
| `src-tauri/Info.plist` | No new usage string needed (Accessibility has none); confirm no change. | - |
| `docs/PITFALLS.md` | Add entries as review catches them; none up front. | - |

Error handling: every Swift export returns an `Int32` code (0 ok, 1 already active, 2 permission, 3 failure, 4 invalid input) mapped to typed Rust errors and user-visible strings, matching the dictation bridge.

Tests: Rust unit tests for settings validation, conflicts and persistence round-trip (including corrupt and oversized files falling back to defaults); Swift tests for `GlobalShortcut` parsing and the allowlist parity with the Rust list; `scripts/run-macos-global-tests.mjs` (new, copy of the dictation runner) compiles the logic file with `tests/macos-global-logic.swift`; add to `npm test`.

Checkpoint commit: "feat(tauri): add global desktop shell with settings and shortcut registry".

## Phase 1: clipboard history and snippets

| File | Change | Ref |
| --- | --- | --- |
| `officekit/engines/engine_clipboard.py` | Add `source_bundle_id` column (additive migration on open), index `(pinned, last_used_at)`, unique index on non-null `snippets.trigger_key`, `settings` table with get/set for the C3 keys, dedupe against any identical unpinned clip (move to top), retention by age and count in `prune`, `types` filter in `list_clips`, trigger validation (2–32 chars, no whitespace, unique, prefix-free) raising typed errors. | C1 C2 C3 C4 |
| `app.py` | Update clip create and history models; add `GlobalClipboardSettings` strict DTO and `GET/PUT /api/clipboard/global-settings`; map trigger errors to 409/422; keep existing routes and responses compatible. | C1–C4 |
| `src-tauri/macos-global.swift` | `OfficeKitPasteboardWatcher`: 300 ms main-run-loop timer on `changeCount`; skips concealed or transient types, skip-listed frontmost bundle ids and its own writes (`ownChangeCount`); reads text (≤5 MB) or PNG data; delivers `(kind, bytes, bundleId, appName)` to a C callback. Never logs contents. `OfficeKitKeywordMonitor`: observe-only global key monitor feeding `KeywordBuffer`; on match calls the trigger callback with the trigger id; Swift then sends Backspaces, pastes through `OfficeKitTranscriptPaster`, restores the clipboard from a bounded snapshot. | HLD clipboard and snippets |
| `src-tauri/macos-dictation.swift` | Make `OfficeKitTranscriptPaster` reachable from `macos-global.swift` (drop `private`); add `pasteRestoring(_:expectedPID:)` that snapshots, pastes and restores after a delay; no behavior change to the dictation path. | P-081 |
| `src-tauri/src/global_desktop.rs` | Capture queue draining on a worker thread that posts to `/api/clipboard/clips` through the existing loopback helper (bounded body, 500 ms connect and 5 s I/O timeouts, drop-oldest when the queue exceeds 64 items); hotkey events fetch `/api/clipboard/history` or `/snippets`, render snippet templates through `/snippets/render`, and call `officekit_global_panel_show`; trigger table refresh on snippet changes. | C1 C2 C4 |
| `assets/officekit-clipboard.js` and `index.html` (Clipboard tab) | Add the "Global clipboard and snippets" settings card from the approved mock (capture, two shortcuts, keyword expansion, skipped apps, retention, open at login, Accessibility banner); card calls the C5 commands and C3 routes; existing history and snippet UI unchanged. Snippet form shows keyword validation errors. | C3 C5 |
| `tests/test_clipboard_snippets.py` | Add cases for dedupe move-to-top, retention by age, `types` filter, trigger validation (length, spaces, uniqueness, prefix), settings DTO bounds and unknown fields, migration on an existing database. | C1–C4 |
| `ui-tests/clipboard-snippets.spec.mjs` | Settings card renders in desktop and compact widths; toggles and shortcut recording call the mocked bridge; banner shows when Accessibility is missing. | mock |
| `tests/macos-global-logic.swift` | Matcher tests: exact suffix match, prefix-free table, buffer reset on navigation keys, 32-character cap, pause reset, no match inside longer words only when configured; clip filter tests for concealed types and skip list. | HLD |

Checkpoint commits: "feat(clipboard): background capture and global history panel", "feat(snippets): global panel and keyword expansion".

## Phase 2: window manager

| File | Change | Ref |
| --- | --- | --- |
| `src-tauri/src/lib.rs` | Extend `snap_target_bounds` with thirds, two thirds, center half, almost maximize, maximize height, larger, smaller and move left/right/up/down; add `wm_cycle_width` for repeated halves; keep existing actions and tests. | HLD window manager |
| `src-tauri/src/window_manager.rs` (new) | Pure functions over `WindowBounds`: `apply_gap`, `relative_move_between_screens(window, from_area, to_area)`, `next_display_index(current, count, direction)` with wrap, `restore` bookkeeping keyed by window id, `edge_action_for_point`; command `window_manager_apply(layout)` that asks Swift for the focused window context, computes the target and calls Swift to set it; Rectangle default shortcut table. | C5 |
| `src-tauri/macos-global.swift` | `OfficeKitWindowControl`: focused window via `AXUIElementCreateApplication(frontmostPID)` and `kAXFocusedWindowAttribute`; read position and size, set position then size then position (Rectangle's approach for apps that clamp), screens' visible frames sorted by arrangement, window id from `CFHash`; refuses full-screen, minimized and non-settable windows with code 4; `OfficeKitDragMonitor` (left-mouse dragged and up global monitors) feeding `DragEdgeClassifier`, with a click-through overlay `NSPanel` for the preview. | HLD window manager |
| `src-tauri/macos-global-logic.swift` | `DragEdgeClassifier` (edge band thickness, corner size, hold delay), screen ordering helper. | HLD |
| `assets` and `index.html` | Window Manager section from the approved mock: toggles, gap, skip list, shortcut grid and editor, reset; existing in-window Rectangle menu unchanged. | mock |
| `docs/TESTING.md`, `docs/FIRST-MAC-RELEASE.md` | Record the manual acceptance checklist and keep source evidence separate. | HLD |

Tests: Rust unit tests for each layout (including odd widths and negative-origin secondary displays), gap handling, relative move between screens of different sizes, next/previous with wrap, restore, repeated-half cycling and edge classification; Swift tests for `DragEdgeClassifier` and screen ordering; Playwright for the Window Manager section.

Checkpoint commits: "feat(windows): global layouts and restore", "feat(windows): next/previous display and drag-to-edge".

## Cross-cutting

- Versioned docs: bump `API-CONTRACT.md` with the C1–C5 rows, `docs/TESTING.md`, this LLD and the HLD with matching `docs/VERSION-HISTORY.md` rows on every edit.
- Coverage: 100% unit coverage on new Python and pure Rust/Swift logic; native AppKit/Carbon glue is covered by manual acceptance and called out as such.
- Review: `/se-review` after each phase; UX reviewer checks the shipped cards against `design/README.md`'s approval record.
- Hold-out: dictation fixes in the main checkout stay uncommitted and separate.
