# OfficeKit product requirements

**Version:** 1.0.41 · Keep process quit and collapsible CPU/RAM details in native System Stats menu-bar drawers. Earlier: 1.0.40 · Move Network diagnostics into the existing Mac menu-bar drawer, remove the app-header duplicate, and improve the gauge/history layout. Earlier: 1.0.39 · Network Stats supports Wi-Fi and wired routes on macOS, Linux and Windows. Earlier: 1.0.38 · Approved Network Stats title-bar rates, router-versus-internet check, and Cloudflare Speed Test shortcut. Earlier: 1.0.37 · Merge System Stats and shared file-intake requirements. Earlier: 1.0.36 · Clarify tray scope and Mac sensor availability, 2026-10-25. Earlier: 1.0.35 · Add shared native file intake and approved System Stats scope.

## Network Stats Mac menu-bar view

- Show current upload/download rates, in-memory traffic history, interface and since-startup totals in the existing macOS Network menu-bar drawer. Do not add a duplicate Network chip to the OfficeKit app header.
- Run gateway-versus-internet diagnostics only after the user chooses Run network check. Support Wi-Fi and wired routes; an isolated LAN reports that internet is unavailable.
- Show router and internet timing separately, provide the Cloudflare Speed Test shortcut, and preserve the existing local-address row in the native drawer. The health response itself does not return gateway or local IP addresses.
- Spread the rate gauges across the drawer and draw history across the available chart width.

## System Stats dashboard acceptance

Approved scope: `docs/ui-research/2026-10-24-approved-systemstats.md`.

1. Replace the four-value summary with a local telemetry dashboard for CPU (including per-core usage and history), GPU, memory, disk, sensors, network, and existing process controls.
2. On laptops with readable battery telemetry, show current charge/source/state, battery health or maximum capacity, cycle count, and charge history. Hide the battery section when no battery is detected.
3. Expose optional GPU and battery data to the native tray drawers while preserving existing menu-stat Quick Controls; sensor readings stay in the app view and use native Mac temperature telemetry when available. Unsupported fields are unavailable, never guessed.
4. Keep metrics local and session-only. Add no network service, telemetry storage, database, or tenant fields.

## System Stats menu-bar drawer behavior

- Keep the Top applications list at the bottom of CPU and RAM drawers with the existing rows, order, metrics and row actions.
- A process Quit action shows an inline confirmation in the native drawer. Confirming terminates that process through the existing bounded local process API, refreshes the list in place, and does not foreground the OfficeKit window. Cancel leaves the process list unchanged. Preserve the confirmation that unsaved work may be lost and never force-terminate.
- CPU and RAM drawers start with history and advanced metrics collapsed under one “Show history and details” disclosure. Expanding reveals the existing history, per-core activity, frequency, chip, average-load and memory-breakdown values in place. The sections collapse again when the drawer closes; no preference is persisted.

## OfficeKit shell: shared file intake and Finder Open With

Owner-approved direction (Option A): native window drops and macOS Finder **Open With → OfficeKit** share one file intake and tool chooser. The revised PDF catalog mock was approved by the owner (“approved”, 2026-10-23); the durable approval record is `docs/hld/file-intake.md`.

1. A received file selection shows every compatible tool available in the verified OfficeKit release, grouped by task and searchable. Compatibility uses declared file kinds/extensions, file and folder support, selection count, byte bounds, prerequisites, and release availability.
2. Keep a supported tool visible but disabled when its minimum file count is unmet; state the exact requirement. Do not show tools for unrelated input or silently omit files from a mixed selection.
3. Continue opens the selected tool's existing workflow. Intake never starts processing or bypasses tool-specific validation, review, confirmation, output, or cleanup.
4. Finder Open With supports cold and already-running OfficeKit and multi-file handoff. Window drops use the same intake except a registered Media Toolkit drop target keeps precedence.
5. Native code owns paths and selection grants. The webview sees bounded safe display metadata and opaque IDs only. File content is streamed locally with identity checks when adapting into existing upload-based tools; native-selection tools reuse the opaque selection.
6. Reject unsafe, unsupported, duplicate, unavailable, over-bound, or changed inputs with a useful fixed message. Preserve source files and local-only processing.
7. Advertise only implemented supported file types in Finder at alternate rank. Validate installed macOS registration and cold/warm launch behavior before release.

## Media Toolkit: unified local media preparation

### Animated meeting countdown acceptance

Approved scope: `docs/ui-research/2026-10-21-approved-meeting-countdown.md`.

1. Opt-in local macOS calendars; clear permission, denied, empty, unavailable and failure states. Selected calendars persist without storing event contents.
2. Next eligible timed meeting appears within 30 minutes, live absolute countdown, full watch-check/tap/point/wave character poses and static reduced-motion fallback.
3. All-day, cancelled and self-declined events are excluded; edits, recurring occurrences, overlap, wake/clock changes and stale feeds behave safely.
4. Hide affects one occurrence. At start, a brief wave completes before expiry. Calendar prompts share corner, quiet hours and pause; wellness schedules remain independent.
5. No cloud API/event mutations or calendar-content logs. Main-only calendar permission command; companion keeps only bounded state/action IPC.
6. Source/UI tests, native build and installed calendar/focus/wake acceptance are reported separately; existing development-only gate remains.

## Problem

OfficeKit has useful file tools, but image conversion, image resizing, image metadata removal, PDF compression, screenshot editing, and audio transcription lead to separate flows. It has no shared media preparation queue or Clop-level automation layer. People must choose tools and repeat file handoffs to reach a share-ready result.

## Product outcome

Provide one local Media Toolkit that accepts images, video, PDF, and audio, prepares bounded outputs for a chosen format/size/dimension/quality goal, explains the result, and preserves originals. Reuse existing OfficeKit operations and connect distinct existing tools instead of copying their controls into a second implementation.

## Scope

The complete Clop capability and integration checklist, OfficeKit joins, and acceptance criteria are maintained in [the feature requirements](../review/clop-media-toolkit/requirements.md). This scope includes manual, batch, and automation entry points; image/video/PDF/audio transformations; settings; command-line/MCP; and optional explicit external integrations. Platform availability is reported truthfully. The plan does not copy Clop’s branding, pricing, or licensing model.

## Product behavior

- Common workbench: add/select files, choose media mode and operations, review estimates and fidelity notes, run/cancel, compare per-file source/output sizes, see whether a size target was met, and save a new copy.
- Existing source operations are composed/reused through stable internal operation IDs. Existing user-facing tool IDs and query terms continue to resolve during migration.
- Screenshot Editor sends its explicit edited export into Media Toolkit through an app-private, verified, one-use image staging grant; the editor export and original remain unchanged.
- Voice Transcription can send an explicitly selected local audio file into Audio optimization using the existing read-only native file-selection grant. Transcription stays a separate action and the source is never overwritten.
- Every optimization starts from the selected original. Existing source paths remain unchanged. Results are privately staged, validated, then saved only to the user's chosen destination or a deliberately configured automation destination.
- Automated triggers have distinct opt-in controls and an always-visible pause/disable state. Control+Shift+C is an explicit one-shot action that reads only an image after the keypress; it does not enable clipboard monitoring. A watched folder or monitoring operation never silently expands its file or network scope.
- Network integrations require a user-selected integration and explicit handoff for each result or an explicitly configured recipe. Local transformations do not require network access.
- A public HTTPS media URL may be imported only through a deliberate user action. Show the resolved host and known size before download. Never fetch a URL implicitly from clipboard monitoring, a watched folder, or a pipeline. Reject credentials, private/reserved addresses, unsafe redirects, and responses over the media-import limit.

## Delivery sequence

1. Shared toolkit and queue; merge existing image conversion/resize/metadata routes; common review/save behavior; image fit-under-size and batch.
2. PDF optimization modes and target-size behavior alongside existing lossless compression; page/device crop only where fidelity can be shown.
3. Video compatibility, optimization, crop/downscale, speed, mute, GIF, batch, cancellation, and detected recording handoff.
4. Audio compression/conversion, cover-art handling, loudness normalization, batch, and size targeting; transcription stays a separate action.
5. Opt-in clipboard and watched-folder rules, preset zones, bounded operation pipelines, hotkeys, native file actions, local CLI, and MCP.
6. Explicit upload/file-shelf integrations and platform-specific completion, followed by full packaged and installed acceptance.

Phases are dependency gates, not a claim that later capabilities are available when the initial workbench ships.

## Implemented vertical slice

The capability API lists 27 desktop Clop-inspired media operations with per-build availability. The typed operation model contains 30 IDs, including three pipeline-only operations: PDF page-image export, audio speed, and video watermark overlay. The development-profile workbench joins existing image conversion/resizing/metadata removal and lossless PDF compression into the native-selection batch job and streamed copy-save flow. Image and video watermark overlays accept a private, short-lived logo grant through the job API; workbench controls await approval of their mock. PDF visual optimization and fit-to-size rasterize pages under bounds and disclose fidelity loss; centered crop preserves vector content; copy-only `pdf-uncrop` restores each page CropBox to its MediaBox while retaining searchable text and the source. The bounded pipeline CLI exports PDF pages as ordered PNG/JPEG images and ZIPs, applies audio speed as a separate M4A, and renders video watermarks as a new MOV while retaining audio. The typed operation defaults are also inspectable and editable through CLI settings commands shared with the app and MCP. Public URL preview uses a single-use grant before the explicit download. macOS exposes video optimize/size-fit, bounded resize, crop/speed/mute/metadata removal/GIF, plus AV1-in-MP4, H.264 MP4, VP9 WebM, and software x265/HEVC MP4 when bounded local FFmpeg video/audio encoder probes succeed; these optional formats are available to typed jobs, CLI, and MCP while desktop selection awaits mock approval; audio convert/optimize/size-fit/artwork, capability-probed FLAC output, optional typed MP3 output after a host `libmp3lame` probe, and measured mono/stereo LUFS normalization use local adapters. FFmpeg is not bundled and receives only fixed local-file inputs for AV1 or MP3 work. LUFS supports 0.4–120 seconds, uses a -2 dBFS sample-peak ceiling, and does not claim true-peak limiting. Saved typed pipelines and watched folders support validated output-name templates with `{name}`, `{ext}`, and `{media}` placeholders while writing collision-safe sibling copies. The approved Automations view manages opt-in clipboard monitoring, watched-folder grants, safe naming, allowlisted pipelines and recent outcomes; preset-zone bindings stay private and session-only. An enabled native drop target automatically runs its bound pipeline through the normal local job path and creates a separate copy. An optional image-only Finder Quick Action uses the same typed CLI, installs only on user request, refuses collisions with other workflows, and publishes numbered sibling copies. Downscale/crop shortcuts and external integrations remain in progress.

## Success criteria

- One searchable, discoverable Media Toolkit route covers all supported media preparation operations.
- Existing tools remain functional and no duplicate engine path is introduced for operations OfficeKit already implements.
- Every Clop capability in the requirements checklist is mapped to an implemented, platform-available operation or a visible accurate status.
- Source preservation, local-first behavior, bounds, cancellation, and explicit external handoff are verified in tests and packaged acceptance.
