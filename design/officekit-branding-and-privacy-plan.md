# OfficeKit branding, exports and optional telemetry

Status: proposal for review. No application implementation is authorized by this document. Branding choices are unapproved.

## Product direction

OfficeKit — The everyday toolbox for your computer.

Keep the proposed Tools / Favorites / History navigation and exact tool destinations. Saved is a History filter; a tool's history is another filter. The branch has been rebased onto main at d6567a9, which already migrated the desktop shell to Tauri 2 and removed Electron dependencies. Build on that migration rather than proposing a new shell migration. Validate existing Python backend integration, packaged startup/shutdown and installation across supported OS/architectures as release checks.

Read-only integration finding after rebase: `src-tauri/src/lib.rs` registers a status command and shell plugin, but does not show Python backend startup; `tauri.conf.json` has no externalBin declaration and CSP is null. The inspected release workflow has no sidecar packaging references. The shell migration is present; functional backend delivery and the security policy remain verification/planning items, not completed claims. Review the frontend asset build as well before treating dist-ui as the final UI source.

## Branding choices

Interactive artifact: `mocks/officekit-branding.html`. Three palettes and three independently selectable SVG marks, with light/dark app previews, monochrome marks and app-icon concepts.

| Palette | Light action | Dark action | Character |
| --- | --- | --- | --- |
| Utility blue | #185C89 | #8CC9F0 | Clear, familiar utility identity |
| Workshop teal | #146557 | #83D6B9 | Practical and approachable |
| Studio plum | #70418A | #D2A7EE | More distinctive personal productivity identity |

Marks: Toolkit (literal utility case/document), Modules (shared tools/workspace), OK monogram (initials). Recommendation: Utility blue + Toolkit. Alternative: Workshop teal + Modules. Finalize only after user selection, 16/24/32 px checks, monochrome checks, OS icon safe-area checks, and trademark similarity review. These marks have no clearance claim.

Use bundled system-font stacks for UI and tabular numeric figures. Theme tokens: background, surface, text, muted text, border, accent, on-accent, accent surface; add independent semantic success/warning/error tokens. Never infer status from color alone. Provide System / Light / Dark; default System, remember a local override, honor OS changes only in System mode. App theme does not determine PDF/image export background. Verify text contrast, focus visibility, disabled states, reduced motion, high DPI and keyboard interaction in all palettes. Mock options are not a promise to ship nine user-selectable brands: choose one identity and support its two themes.

## Export contract

All exports come from the recorded result snapshot, not DOM screenshots or a rerun. Share a versioned report model containing tool ID/version, allowed input/assumption summary, units, result sections, optional tables, original calculation timestamp, export timestamp and selected attribution preferences. Do not inject secrets into reports. Run exporters locally; no telemetry permission is needed for export.

| Format | Attribution / metadata policy |
| --- | --- |
| PDF | Small removable footer: `Generated with OfficeKit · officekit.app`; optional timestamp with timezone; repeated discreetly on multipage reports; document Creator/App version metadata is separately optional |
| JPEG/PNG | Render a designed summary with optional footer, white default background and adequate margins. Do not show window/navigation chrome. Omit image metadata by default; an explicit metadata option may include nonpersonal creator/time fields |
| CSV | Preserve a rectangular interoperable dataset. Do not append a promotional row or prepend comments. Optional ZIP export includes summary.csv, schedule.csv where applicable, and metadata.json with attribution; plain CSV stays clean |
| XLSX where supported | A Report info sheet can carry creator, tool/version, inputs/assumptions, timestamp and optional attribution; data sheets remain clean |
| Copy / TXT | Optional attribution line, excluded when copying a single value |

Use `Generated with OfficeKit` rather than `Generated on officekit.app`, because local processing is not a website upload. Link only the clean homepage; no tracking parameters, remotely loaded pixels, license identifiers or job IDs. Allow users to remove footer and metadata at no added cost. A visible footer is a proposed export default; metadata is off by default. Remember preferences locally. Do not alter user's source files to add branding. For conversion outputs, keep files clean: attribution belongs in an optional report, not in image pixels or merged document pages without explicit selection. Structured input/output data that explains a result is distinct from optional creator metadata.

## Telemetry consent UX

Two independent unchecked options in Settings → Privacy: Share anonymous usage counts; Share an activity heartbeat. Both off initially. Explain fields, frequency and destination before consent. Provide equally accessible Keep sharing off and Save my choices. Ask once after a first successful operation or offer it only in Settings; never block initial use or repeat after refusal. No events are recorded or queued before opt-in. No retrospective collection. A material expansion of fields or purposes requires fresh consent. Updates, licensing, support submissions and telemetry have separate network purposes and permissions.

Do not call data completely anonymous without qualifying infrastructure exposure: network providers/server edges see source IPs even when the payload has no identity. Never put analytics scripts or tracking SDKs in the UI. Include a reviewed privacy notice before release.

### Usage collection

Aggregate locally by tool ID and a coarse time window. Example fields: schema_version, app_version, os_family, tool_id, action enum (opened/completed/failed/exported), count, optional export format enum and allowlisted broad error category. No raw error messages, stack traces, search queries, precise interaction timestamps, inputs, results, documents, clipboard, filenames, paths, emails, tokens, passwords, license IDs, machine names or persistent installation identifiers. Tool identifiers can themselves reveal categories of work; explicitly disclose them and let the user keep sharing off.

Send at most one usage batch per day while the app is running, with a bounded local queue (proposed seven-day TTL and 256 KB cap), request timeouts, exponential retry and jitter. Drop expired/overflow data. Never affect a tool's execution or launch a background daemon. Queue only eligible aggregate counts after consent; immediate opt-out cancels pending sends where possible and purges unsent data. Previously received anonymous data cannot reliably be located/deleted per device without adding identity; disclose that limitation. Avoid retaining payload-level unique identifiers; short-lived random batch IDs may support retry deduplication but must not identify installations.

### Heartbeat

An opt-in daily activity signal, not a liveness monitor: at most once per 24 hours, only while app is open. Payload: schema_version, app_version, os_family, event=`active`. No persistent identity, exact location, uptime, device inventory or background service. It measures coarse activity volume, not unique people/devices; retries and reinstalls limit interpretation. If accurate unique active devices are later required, present a separate identity proposal and seek new consent rather than silently adding a stable ID. Offline use remains fully functional.

### Server boundary

Proposed dedicated HTTPS ingest, separate from document processing and support: POST /v1/telemetry/batches and POST /v1/telemetry/heartbeats. Strict request/response DTOs, enum allowlists, timestamp checks, small payload caps, rate limiting and short-lived deduplication. No embedded client secret treated as authentication; a distributed app cannot keep it secret. Treat anonymous metrics as untrusted and approximate, not as billing or entitlement evidence.

Suggested small AWS deployment, subject to actual volumes: API Gateway + Lambda + DynamoDB TTL. Store daily aggregates, not documents or a full per-event clickstream. No accounts, synchronization service or dedicated tenant system needed for anonymous ingestion. Review infrastructure defaults: disable request-body logging and keep IP/security logs separate from analytics with the shortest operationally justified retention. Proposed raw validated batch retention: seven days maximum, then only daily aggregate counts for 90 days; roll older data into coarse totals if necessary. Align consent copy, actual logging and expiry tests before shipping. Admin dashboards require authentication; mobile/desktop ingest does not expose read access. Server receipt returns accepted/rejected counts without echoing sensitive payloads.

Metrics: tool popularity, completion/failure counts, chosen export formats, app-version adoption, and coarse active-app signals. They cannot establish conversion fidelity, personal retention, unique-user cohorts or willingness to pay. Feature requests and optional interviews provide the qualitative evidence.

## Architecture additions

Frontend theme tokens + selected logo assets; application-level ResultSnapshot and local export adapters; SQLite history/artifacts/preferences; a separate consent-aware metrics collector and outbox. The metrics collector consumes sanitized allowlisted execution events after consent. Engines never send their own network requests for analytics. Central network policy checks consent again immediately before sending, including queued events, and handles app-close cancellation. Telemetry cannot gate processing, licensing, bookmarks, favorites, recents or export.

## Delivery sequence after approval

1. Choose palette and logo, refine final marks and approve key light/dark screens.
2. Audit working capabilities and validate the existing Tauri packaging and Python backend lifecycle on clean machines.
3. Define typed registry, execution, persistence and result snapshot contracts; implement local foundation only when authorized.
4. Apply approved tool/history UX and light/dark tokens; add favorites, recents and saved results.
5. Implement report exports and attribution preferences; validate PDF layout, data integrity and metadata exclusions.
6. Prepare telemetry payload examples, privacy notice, retention and server design for review; then implement optional ingestion and consent controls when authorized.
7. Complete three feedback paths and cross-platform release checks.

Acceptance: no telemetry network traffic or event recording before consent; choices persist across restart; opt-out purges queued data; usage and heartbeat can be enabled independently; offline/failed server never slows tools; exported snapshots survive engine-version changes; clean CSV opens in common spreadsheet tools; no branding added to converted user content without selection; both app themes retain readable status/focus states; favorites/history survive restart. Include bounded retry, payload rejection, privacy logging, artifact retention and clean-machine packaging tests.
