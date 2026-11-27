# HLD: System Stats dashboard and battery telemetry

version: 1.0.5 · 2026-10-27 · Keep process termination in the native drawer and collapse CPU/RAM history and detail values by default. Earlier: 1.0.4 · 2026-10-27 · Menu-bar CPU, GPU and RAM drawers group processes under application display names and show combined resource use. Earlier: 1.0.3 · 2026-10-25.

## Goal

Make the existing local System Stats page and menu-bar drawers present the hardware detail and history shown in the approved Stats-inspired mock, including laptop battery status and health.

## Current state

- `GET /api/system/metrics` already returns aggregate CPU, memory breakdown/pressure/swap, disk and network rates, CPU time breakdown, load average and uptime.
- `assets/officekit-workspace.js` samples the metrics page every two seconds and builds native drawer payloads. History is memory-only.
- `src-tauri/macos-global-logic.swift` bounds native drawers at nine items. Quick Controls currently select CPU, RAM, disk and network; the dictation drawer is retained.

## Design

- Extend the existing metrics DTO, without adding a route, storage, network calls, or tenant state. New optional fields are per-core CPU percentages, GPU utilization percentages, up to sixteen sensor temperature readings, and battery status/capacity/health/cycle metadata.
- The Python sidecar uses psutil for per-core, portable battery, and portable sensor values; on macOS it reads fixed `ioreg` and `pmset` sources for GPU and battery health details. The Tauri app also reads bounded Apple HID temperature events through dynamically resolved IOKit functions when available. Each optional provider fails to `null` independently.
- The in-app page becomes a telemetry dashboard with CPU, GPU, memory, disk, sensors, battery (only when detected), network and the existing process table. Usage/charge histories stay in memory and clear when sampling stops.
- Keep existing Quick Controls. GPU follows the CPU menu-stat switch. Battery is shown in the tray when hardware exists and any menu stat is enabled. Native drawer capacity rises to seven to fit CPU, GPU, RAM, disk, network, battery and dictation. The disk drawer keeps its Storage analyser action; the battery drawer has its settings action.
- Menu-bar CPU, GPU and RAM drawers show the top applications, combining helper-process CPU and RAM values. The process count and a short list of underlying process names remain visible, and the existing confirmation protects the application process action.
- Keep the Top applications list at the bottom of CPU and RAM drawers with its current ordering, rows, metrics and Quit row actions. A Quit click opens an inline native confirmation; confirmation calls the existing bounded local termination API without bringing the OfficeKit window forward. Success refreshes the list in the still-open drawer, while failure remains actionable there. Cancellation leaves the list unchanged; force termination is never used.
- In CPU and RAM drawers, group history and detailed values under one disclosure control, collapsed each time the drawer opens. Expanding it reveals the existing charts and metrics in place. Do not persist expansion state.
- App names come from local macOS app-bundle metadata when available; unresolved processes retain their process name. Apple GPU client time is sampled as a best-effort per-process percentage. Unsupported, malformed or stale GPU readings remain unavailable, while the system GPU utilization stays visible.
- Existing process filtering, sorting, refresh, protected-process state and termination flow remain available.

## Implementation and validation

- Implemented in the existing local metrics route, app dashboard and native tray drawers. The battery tray drawer retains the Activity Monitor header shortcut and adds a Battery settings footer action.
- `npm run build:ui` completed and produced the local `dist-ui` UI output.
- Gate 5 passed: 1,045 Node tests (1,044 passed, 1 skipped), 72 native dictation checks and 19 focus-context checks passed, and 3,424 Python tests passed (5 skipped). The configured c8 coverage table reports 100% statements, branches, functions and lines for its eight licensing modules. Focused System Stats browser tests passed in both desktop and compact layouts (4 tests); focused metrics engine tests passed all 64 cases with 100% statement coverage.
- `cargo check --manifest-path src-tauri/Cargo.toml` compiled the Swift bridge, then stopped in Tauri resource validation because `src-tauri/binaries/officekit-media` is missing from this checkout.
- `node scripts/run-macos-global-tests.mjs` compiles and runs the optional HID sensor reader check on macOS; a machine without readable readings reports that state without failing.

## Data and failure behavior

- Battery absence on desktops is `null`, so the app hides the battery card and native drawer.
- Unavailable GPU, health, sensor, or timing fields stay null and render as “Unavailable” or an explicit unsupported state. No values are inferred from generic CPU data.
- Metrics are read on demand and are never persisted or sent off-device. The API retains its one-second cache and bounded provider timeouts.
- macOS GPU/sensor values are best effort because their host interfaces vary. Per-process Apple GPU attribution reads local IOKit registry counters without root; missing or changing registry fields produce null attribution without affecting device metrics. The private HID event functions are dynamically resolved and missing symbols produce no readings without preventing startup.

## Acceptance

See `docs/ui-research/2026-10-24-approved-systemstats.md`. The UI must match the approved in-app and tray mock, stay under the three-button screen limit, and keep unsupported hardware states honest.
