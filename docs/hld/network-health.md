---
version: 1.0.4
---
# Network Stats Mac menu-bar health view (HLD)

Date: 2026-10-27

## Scope

Add the user-triggered gateway/internet health check and Cloudflare Speed Test shortcut to the existing macOS Network menu-bar drawer. Keep its local byte-counter rates, recent in-memory traffic history, interface, local-address and since-startup totals. Do not duplicate the Network chip or popover in the OfficeKit app header. The check compares TCP round trips to the active gateway and the public internet. Wi-Fi and wired routes are supported. No network probes run when the drawer opens or in the background. Existing DNS, Ping and Interfaces tools remain available.

The Cloudflare Speed Test is an external link, activated only by the user. It does not supply the router comparison. The local health check does not identify a provider name or send measurement data.

## Decisions

- Reuse `GET /api/system/metrics` for rates, totals and interface; preserve the existing delta-over-monotonic-interval calculations and in-memory history.
- Add `POST /api/network/health` as a one-shot local API operation. It discovers the default gateway, measures the gateway and fixed IP endpoints concurrently, and returns one bounded summary after three samples. It is invoked only by Run network check.
- Use TCP handshakes (no application payload) to gateway port 53, 80 or 443 and internet targets 1.1.1.1 and 8.8.8.8 on 443. The lower responding internet RTT is used per sample.
- Use WiFi or ISP's headline categories and thresholds: router median >40 ms or loss ≥25%; internet median >100 ms slower than router or loss ≥25%; offline when the last two internet samples are both lost. Fewer than two usable internet samples remain “Measurement incomplete”.
- Gateway discovery uses platform-native route information on macOS, Linux and Windows. Linux and Windows choose the lowest-metric active IPv4 default route; Windows uses the locale-independent ActiveStore, limits serialized route candidates to the 512 lowest metrics, and excludes persistent routes. A wired default route is classified as Wired; Wi-Fi signal is omitted when unavailable.
- The health response never includes a router or local IP. The existing Mac drawer may continue showing its current local-address row from system metrics. Health results and traffic history are memory-only.

## Flow

1. The existing local-metrics poll updates the Mac menu-bar rates and network chart.
2. The user opens the Network menu-bar drawer. This reads local metrics; it does not send a probe.
3. The user chooses Run network check. `POST /api/network/health` discovers the active route and takes three bounded probe samples.
4. The UI renders the measured status, RTTs, interface type, and update time. Missing readings stay unavailable.
5. The Cloudflare link opens the official external speed-test page only when clicked.

## Risks and limits

- Some routers silently drop all candidate ports; in that case the router is not measured and the UI must not claim a precise ISP-versus-router cause.
- A one-shot three-sample check is a snapshot, not a continuous monitor or history. It can vary from WiFi or ISP's longer six-sample window.
- An isolated LAN can measure its gateway, but cannot produce an ISP verdict without an internet route.
- Wired connections have no Wi-Fi signal value.

## Pitfall coverage

- Preserve explicit network consent: diagnostics remain user-triggered; menu-bar rates are local OS counters only.
- Keep tauri webview API calls on the established `officekitApiUrl` path.
- Show unavailable and warming-up states instead of zero or fabricated readings.
