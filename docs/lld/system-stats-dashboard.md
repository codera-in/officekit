# LLD: System Stats dashboard and battery telemetry

version: 1.0.5 · Implements `docs/hld/system-stats-dashboard.md` 1.0.5; adds a native in-place process quit confirmation and collapsed-by-default CPU/RAM detail groups. Earlier: 1.0.4 · Adds app-attributed CPU, GPU and RAM rows to the menu-bar drawers. Earlier: 1.0.3.

## File map

| File | Change | Contract / design |
| --- | --- | --- |
| `officekit/engines/engine_system_metrics.py` | Add bounded local GPU, sensor, per-core CPU and battery providers; keep provider errors isolated and nullable. | HLD data and failure behavior |
| `officekit/engines/engine_process_manager.py` | Resolve enclosing app bundle display names, sample Apple GPU client time by PID, and aggregate all active processes into bounded app totals. Unavailable GPU readings remain null. | Local process snapshot and app grouping |
| `app.py`, `API-CONTRACT.md` | Add strict application aggregate DTOs and nullable process GPU/app-name fields to the existing process route. | Versioned process snapshot contract |
| `app.py` | Add strict response models and optional fields to `SystemMetricsResponse`. | API contract `GET /api/system/metrics` |
| `API-CONTRACT.md` | Document the new optional fields and bump contract version. | Existing metrics route |
| `index.html`, `assets/officekit.input.css`, `assets/officekit-workspace.js` | Replace the summary tiles with the approved telemetry cards, in-memory history charts, and matching tray payload details. Preserve process controls. | Approved UI mock |
| `src-tauri/macos-global-logic.swift` | Allow seven bounded menu drawers and parse the battery settings action. | Native drawer payload |
| `src-tauri/macos-drawers.swift`, `src-tauri/macos-global-logic.swift` | Render bounded application process details, collapsed CPU/RAM history and details, and inline native quit confirmation while preserving drawer payload limits. | Approved menu-bar action and compact stats mock |
| `src-tauri/src/workspace_native.rs` | Relay confirmed quit/cancel actions to the WebView without showing or focusing the OfficeKit window. | Local process API bridge |
| `src-tauri/macos-sensors.swift`, `src-tauri/src/system_sensors.rs` | Dynamically read bounded Apple HID temperature events and expose them through a local Tauri command. | Optional sensor provider; unsupported symbols yield no data |
| `tests/test_system_metrics_unittest.py`, `tests/macos-global-logic-tests.swift`, `tests/macos-sensors-tests.swift`, `ui-tests/system-metrics.spec.mjs` | Cover provider parsing, dashboard rendering, tray fields, seven drawers, battery action parsing, and bounded native sensor readings. | System Stats test plan |
| `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ui-research/2026-10-24-approved-systemstats.md` | Record acceptance, ADR-lite and approved UI. | Durable product record |

## Data shapes

- `GET /api/system/processes` retains its process rows and adds up to 100 application aggregates with process count, up to four process names, representative PID, combined CPU and RAM, nullable GPU use and a killability flag. App aggregates are computed before the returned list limit, so helper totals are complete for each returned app.
- `cpu_cores_percent`: bounded array of finite values from 0 to 100, or null.
- `gpu`: optional device, renderer and tiler percentages, each finite and within 0–100.
- `sensors`: null or at most sixteen `{name,current_c,high_c}` readings; temperature bounded to −20–150 °C.
- `battery`: null or charge percentage, `ac`/`battery` source, `charging`/`charged`/`discharging`/`unknown` state, remaining seconds, cycle count, designed/full mAh, maximum-capacity percentage, and a bounded condition label.
- The one-second cache continues to return snapshots, not persisted history. The browser keeps at most 90 samples per series.

## UI and tray flow

The page continues to poll the existing metrics endpoint while visible or while a menu stat is active. A battery card/drawer is constructed only for a detected battery. CPU controls remain the source for GPU drawer visibility; existing menu-stat choices are otherwise unchanged. The native parser caps payload size, labels, rows, histories, and item count. User process actions remain behind the existing authenticated API and native confirmation.

CPU and RAM menu drawers render their Top applications rows below a single “Show history and details” control. It is collapsed at drawer open and resets when the drawer closes; expanding it reveals the existing history, cores, frequencies and breakdown values without hiding or reordering the application list. A row's Quit action opens a confirmation in the same native drawer. Only confirmation emits the process ID to the WebView; the WebView calls the existing local terminate route with `force: false` and sends bounded working/error feedback back in the drawer model. Neither request nor cancellation activates the OfficeKit window.

## Verification notes

The mock button count passed `node scripts/check-mock-buttons.mjs design/mocks/systemstats-laptop-battery.html`; the mock was inspected in Superset Browser at desktop and compact widths. `npm run build:ui` completed. Gate 3 passed the full Node, native, and Python suites; focused System Stats browser checks passed in both layouts; the configured c8 table reports 100% across its licensing modules. Cargo compiled the Swift bridge but stopped at Tauri resource validation because `src-tauri/binaries/officekit-media` is absent from this checkout. Battery and sensor readings still need a laptop/device check; macOS sensor temperatures remain unavailable when the OS does not expose them through psutil.
