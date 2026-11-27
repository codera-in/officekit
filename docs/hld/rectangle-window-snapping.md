# HLD: Rectangle-style window snapping

Version: 1.0.0 · 2026-10-18

## Goal

Let users arrange the OfficeKit desktop window with Rectangle-style layouts, keyboard shortcuts, drag-edge snapping, fullscreen, and movement across connected displays.

## Boundaries

- The header menu and shortcut editor are part of the existing Tauri UI.
- Rust commands own native window sizing, fullscreen, screen movement, edge snapping, and restoration.
- Window geometry is calculated against the active monitor's usable work area.
- Shortcut choices and the drag-snap preference are local to the app's webview.
- The feature does not add global shortcuts; key commands work while OfficeKit is focused.

## Product rules

Provide halves, corners, center, maximize, restore, fullscreen, and previous/next screen actions. Dragging near a screen edge previews a layout; pausing applies it. Users can record custom key chords and reset to Rectangle's standard layout bindings.

## Quality evidence

Rust tests cover layout geometry, fullscreen-area sizing, monitor destination sizing, edge-action selection, and state transitions. Playwright tests cover the focused UI bridge, saved shortcut changes and reset, edge-preview rendering, drag-snap persistence, fullscreen and monitor actions, and compact menu bounds. A physical multi-display check remains platform verification beyond the single-display test environment.
