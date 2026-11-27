# HLD: Global desktop tools (clipboard, snippets, window manager)

Version: 1.0.1 · 2026-10-20

## Goal

Replace several separate Mac utilities with one local-first background tool. The OfficeKit process that already runs voice dictation also provides system-wide clipboard history, snippets with keyword expansion, and a window manager for other apps' windows, all behind the Accessibility access dictation already uses. Chosen approach, mock approvals and owner quotes: `review/global-desktop-tools/requirements.md`, `docs/ARCHITECTURE.md` (ADR-lite: Global desktop layer) and `design/README.md`.

## Current state

- The window hides on close and the sidecar keeps running (`lib.rs`, P-143). A tray icon exists in `workspace_native.rs`. There is no launch at login.
- Dictation has observe-only NSEvent monitors, an Accessibility flow, a non-key overlay panel and a native Cmd+V paster in `src-tauri/macos-dictation.swift`.
- Clipboard history and snippets are Python-owned (`engine_clipboard.py`, `/api/clipboard/*`) but capture only runs from the webview when the window regains focus, text only. `trigger_key` is stored and never expands.
- Rectangle-style snapping in `lib.rs` moves only OfficeKit's own window; its layout math (`snap_target_bounds`, `edge_snap_action`) is tested and reusable.

## Boundaries

- **Swift (new `macos-global.swift`)** owns everything that touches macOS: Carbon hotkeys, the panel host, pasteboard polling, keyword matching on the keystroke stream, Accessibility window reads and moves, the drag monitor and preview overlay, login item.
- **Rust** owns orchestration: settings validation and persistence, the event loop between Swift callbacks and the sidecar, and window layout math. It reuses the existing blocking loopback HTTP helper for sidecar calls.
- **Python** keeps clips, snippets and folders; it gains source app, retention by age, trigger uniqueness and a `global-settings` resource. Window manager settings are local JSON owned by Rust because the window manager must work even when the sidecar is unavailable.
- **Webview** gets one settings card per feature in the existing Clipboard tab and a Window Manager section; it never touches the pasteboard or other windows itself.
- The feature does not add a second Tauri window, a network call or a new sidecar. Everything stays on this Mac.

## Shared layer

| Piece | Behavior |
| --- | --- |
| Shortcut registry | Carbon `RegisterEventHotKey` per binding; swallows the key; no Accessibility needed for the shortcut itself. Bindings are validated in Rust (modifiers required except F-keys, no duplicates across features, no reserved system chords) and re-registered when settings change. |
| Panel host | Non-activating, key-capable `NSPanel`, floating over full-screen Spaces. Captures the frontmost app's PID before showing and passes it as `expectedPID` to the paster. Closes on Esc, on losing key status or after paste. |
| Permission surface | One status value (`trusted`, `needs-access`) reused by every feature; features that need Accessibility show the banner from the mock and never fail silently. |
| Lifecycle | Settings persisted locally and restored at launch only when permissions are ready (P-150). Open at login uses `SMAppService.mainApp` and is off by default. |
| Privacy | No logging of clip contents, typed text or window titles; only counts, codes and bundle ids. |

## Clipboard history

1. **Capture:** a main-run-loop timer reads `NSPasteboard.changeCount` every 300 ms. A change is skipped when the pasteboard carries a concealed or transient type, when the frontmost app's bundle id is on the skip list, or when it matches the change count recorded after OfficeKit's own write. Text up to 5 MB and images up to the engine's existing preview limit are queued to Rust, which posts them to `/api/clipboard/clips` with `source_app`. Dedupe moves from "latest clip only" to "any identical unpinned clip moves to the top".
2. **Panel:** ⌘⌥V asks Rust for the newest clips (limit 100, query as the user types), which Rust fetches from the sidecar and hands to Swift as JSON. Swift renders the list, keeps its own filtering for type chips, and on Enter pastes the chosen clip into the saved target app.
3. **Retention:** 500 clips and 30 days by default, pinned clips exempt; pruning runs on insert.

## Snippets

1. **Panel:** ⌘⌥S lists snippets by folder with search over title and keyword. Enter renders built-in variables through `/api/clipboard/snippets/render` and pastes; snippets with prompt variables show one inline field per variable first.
2. **Keyword expansion:** Swift holds a trigger table pushed from Rust whenever snippets change. A global key monitor (observe-only) appends typed characters to a memory-only buffer of at most 32 characters, clears it on navigation keys, mouse clicks, app switches and a 3-second pause, and matches the buffer's suffix against the trigger table. On a match Swift sends the right number of Backspaces, then pastes the rendered snippet through the existing paster and restores the previous clipboard after the paste lands. It does nothing when secure event input is on, when the setting is off, or in a skipped app. Triggers must be 2–32 characters without spaces, unique, and not a prefix of another trigger, so expansion is unambiguous.
3. Undo is the host app's own undo; OfficeKit makes no promise about it.

## Window manager

0. **Rectangle parity:** the action set is Rectangle's: halves, quarters, thirds, two thirds, center half, maximize, almost maximize, maximize height, larger, smaller, center, restore, move left/right/up/down, next/previous display, plus repeated-half width cycling. Next/previous display preserves the window's relative position and size on the destination screen, orders screens by their arrangement, wraps around, and re-clamps to the destination's visible frame. Default shortcuts are Rectangle's.
1. **Layouts:** a shortcut tells Rust the layout id. Rust asks Swift for the focused window's frame and the visible frame of the screen it is on, computes the target rectangle with the shared layout math (extended with thirds and two thirds), applies the configured gap, and tells Swift to set the frame through the Accessibility API. The pre-snap frame is remembered per window for Restore.
2. **Drag to edge:** a global left-mouse-drag monitor tracks the dragged window; near an edge or corner Rust's `edge_snap_action` picks the layout, Swift shows a click-through preview overlay on that screen, and releasing applies the layout.
3. **Safety:** full-screen, minimized or non-resizable windows are left alone with a short notice; skipped apps are ignored; multi-display uses the window's screen, with next and previous display moving to an adjacent screen's visible frame. Nothing reads or stores window titles.

## Launcher

`launcher.open` (default ⌃⌥Space, configurable, gated by the master toggle) opens the same native panel as clipboard history and snippets. Rust lists every OfficeKit tool from `GET /api/tools/search?q=` followed by the snippets; chips filter All, Tools and Snippets. Enter on a tool brings OfficeKit forward and emits `launcher-open-tool`, which the webview handles with `selectSearchTool`; Enter on a snippet inserts it like the snippets panel. Approved mock: "Approve as is". **Deferred:** dropping files on the launcher. Files from other apps need native filesystem grants (see `workspace_native.rs`), so that is a separate security-reviewed change; the mock's drop and "recent tools" sections are not built yet.

## Contract surface

New or changed rows go in `API-CONTRACT.md` (version bump and `docs/VERSION-HISTORY.md` row at implementation):

| Surface | Change |
| --- | --- |
| `POST /api/clipboard/clips` | Adds `source_bundle_id?`; image content accepted as before; dedupe against any identical unpinned clip. |
| `GET /api/clipboard/history` | Adds `types` filter (text, image, link, pinned). |
| `GET/PUT /api/clipboard/global-settings` | Strict DTO: capture enabled, skip bundle ids (≤64), retention clips (50–5,000) and days (1–365), expansion enabled. |
| `POST /api/clipboard/snippets` | `trigger_keyword` validated for length, no spaces, uniqueness and prefix-freedom; 409 on collision. |
| Tauri commands | `global_desktop_status`, `global_desktop_configure` (shortcuts, toggles, gap, skip list), `global_desktop_open_permission_settings`, `window_manager_apply(layout)`; gated to the same profiles as dictation commands. |

## Data model

Local single-user desktop app; there is no tenant concept, so the multi-tenant rule does not apply. `clips` gains `source_bundle_id` and an index on `(pinned, last_used_at)`; `snippets.trigger_key` gets a unique index; a `settings` key-value table holds the global settings. Migration is additive and run by the engine on open. Window manager settings are `window-manager.json` in the OfficeKit data directory, written atomically with a size bound.

## Pitfalls check

- P-081: the paster stays snapshot-bounded and fail-closed; expansion restores the clipboard only through the same bounded snapshot.
- P-109: no new webview, so no capability change.
- P-131: Carbon hotkeys avoid modifier-release state queries.
- P-134: Rust allowlist for recordable keys matches what the shortcut editor offers; one shared allowlist for all three features.
- P-143: close-to-hide is required for any of this to work, and is not changed.
- P-150: settings restore only when permissions are ready.
- No paste, window move or expansion claims success without a verified step; delivery into other apps is reported as requested, not confirmed.

## Quality evidence

- Python: store and API tests for dedupe, retention, trigger validation, settings DTO bounds, image and concealed handling.
- Rust: settings and shortcut validation, conflict rejection, layout math including thirds and gaps, drag-edge selection, restore bookkeeping.
- Swift source-compile tests (`scripts/run-macos-dictation-hotkey-tests.mjs` pattern): keyword buffer and matcher, clip filter, shortcut parsing, drag-edge geometry.
- Playwright: the two settings cards in desktop and compact widths.
- Manual installed-build acceptance, recorded separately from source evidence: hotkey delivery in common apps, pasting into native and Electron apps, expansion in several apps and in a password field, moving Safari, Finder, Terminal and an Electron app, two displays, full-screen apps.

## Phasing

Phase 0 shared layer, Phase 1 clipboard and snippets, Phase 2 window manager. Each phase ships behind its own toggle and passes review before the next starts. Saved named layouts are a follow-up.
