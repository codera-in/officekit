---
version: 1.0.4
---
# Network Stats Mac menu-bar health view (LLD)

Date: 2026-10-27 · HLD: `docs/hld/network-health.md` 1.0.4

## File map

| Path | Change | Contract |
|---|---|---|
| `officekit/engines/engine_network_health.py` | Bounded default-route discovery, TCP probes, three-sample aggregation and typed result statuses | `POST /api/network/health` |
| `app.py` | Strict empty request DTO, response DTO, service instance and thin route | `POST /api/network/health` |
| `API-CONTRACT.md` | Version bump and documented network health route | API 1.94.1 |
| `assets/officekit-workspace.js` | Builds native Network drawer data, sends the explicit health request, validates and formats the returned diagnosis | `/api/system/metrics`, `/api/network/health` |
| `index.html` | Removes the duplicate app-header Network chip and popover | Approved mock |
| `assets/officekit.input.css` | Removes styles used only by the deleted app-header Network widget | Approved mock |
| `src-tauri/macos-drawers.swift` | Draws spread rate gauges and line history; renders health status, link, and keyboard-focusable native actions | Approved mock |
| `src-tauri/macos-global-logic.swift` | Validates health presentation fields and counts Network actions | Native model contract |
| `src-tauri/src/workspace_native.rs` | Emits the explicit Network check action from the native drawer to the WebView | Quick-access event |
| `docs/PRD.md` | Updates approved placement and version | Product requirement |
| `design/README.md` | Record the approved decision and retained existing diagnostics | Design record |
| `tests/test_network_health_unittest.py` | Route selection, platform adapters, probe outcomes and API error regressions | Backend contract |
| `tests/network-health-ui.test.mjs` | Explicit native event to single health request, response validation, wired results and action accessibility | UI/event contract |
| `tests/macos-global-logic-tests.swift` | Native health-payload validation, busy state and Network drawer action-count contract | Native model contract |

## Service behavior

- Route discovery returns only the interface, route type and gateway address internally; the response never includes gateway or local IP values.
- macOS reads `route -n get default` with a fixed argument vector and timeout. Linux reads `/proc/net/route` and chooses the lowest metric; Windows uses the locale-independent `Get-NetRoute` ActiveStore, sorts by combined route/interface metric, and serializes at most 512 candidates to JSON. Persistent routes are excluded. Unsupported platforms return `unsupported`.
- Router-port discovery tries 53, 80 and 443. TCP refusal counts as a host response. Each probe has a one-second timeout.
- Three samples are taken one second apart. Each sample probes the router and both fixed public IPs concurrently. The faster successful internet probe represents that sample; both failing means a lost sample.
- Median RTT and loss share are computed from three samples. The response has explicit `healthy`, `router_slow`, `internet_slow`, `offline`, `incomplete`, `router_unmeasured` and `no_route` states and nullable RTTs.
- The route is Wired unless the active interface is identified as Wi-Fi. The API does not collect SSID, signal, hardware address or local address.

## UI behavior

- Existing system metrics polling updates the native Network drawer rate and line chart; no second system-metrics loop is added.
- The native Run network check button dispatches a `network-check` quick-access event. Only that explicit event sends the API request.
- Run network check disables while the request is in progress, gives a working label and never auto-retries.
- Run network check, Cloudflare Speed Test and Network Settings are keyboard-focusable in visual order with a visible focus indicator.
- Validate response fields and numeric bounds before rendering. Render returned strings with `textContent`. A recheck clears previous readings while pending and on failure.
- The Cloudflare link is a fixed HTTPS URL opened from the native drawer; it never runs automatically.
- Network Settings uses the operating system's settings URI. Preserve the existing local-address row; health results never contain an IP address.

## Error behavior

- `503`: route/probe service unavailable; show an actionable retry message.
- `501`: unsupported host platform; retain traffic counters and show the unsupported diagnosis state.
- Timeout/no response is represented as measured loss, not an exception or zero latency.
- Invalid response shape is discarded and readings are marked unavailable.

## Checkpoint plan

1. Add the validated backend contract/service and update API docs.
2. Reuse the existing system-metrics stream in the Mac menu-bar drawer, remove the duplicate app-header widget, and route the explicit check through the native event bridge.
3. Build generated UI assets, inspect the approved mock, and verify native model and callback/event behavior.
