# LLD: Rectangle-style window snapping

Version: 1.0.1 · 2026-10-18

## UI and commands

The `#officekit-window-snap` menu invokes `window_snap` with a bounded action ID. `window_snap_set_edge_enabled` stores the edge-snap preference in native state. Native preview events carry an optional action; the UI presents the matching pause-to-snap message. The shortcut recorder persists validated key names in `officekit.window-snap-shortcuts` and handles chords only when the app is focused.

## Layout and movement

- Layout helpers derive halves, corners, center, maximize, and restore bounds from the monitor work area.
- Fullscreen delegates to the Tauri window fullscreen state.
- Next/previous screen wraps the connected-monitor list, keeps the current size when it fits, and centers the window in the destination work area.
- Edge movement chooses the nearest supported edge/corner action, emits preview state, and applies after a 240 ms pause.
- Programmatic moves suppress their own follow-up movement events to avoid recursively snapping.
- Restore exits fullscreen and native maximized state before applying the saved bounds; the previous bounds entry is removed only after the restore succeeds.

## Shortcut behavior

Rectangle defaults are Control+Option+arrows for halves, Control+Option+U/I/J/K for corners, Control+Option+C for center, Control+Option+Enter for maximize, and Control+Option+Backspace for restore. Reset removes the saved mapping and restores these bindings plus OfficeKit defaults for fullscreen and monitor movement. Duplicate key/modifier pairs are rejected.

## Verification

`src-tauri/src/lib.rs` contains geometry and edge-state unit tests. `ui-tests/window-layout.spec.mjs` checks menu actions, edge preview, drag-snap persistence, narrow viewport containment, and editing/resetting shortcuts in desktop and compact WebKit projects. Browser bridge tests do not prove OS-level fullscreen, drag notifications, or physical multi-display movement.
