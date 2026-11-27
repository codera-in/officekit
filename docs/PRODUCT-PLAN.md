# OfficeKit product and implementation plan

Version: 1.5.0 · Status: consolidated planning baseline. Commit authorized; application implementation and specific brand/screens not yet approved.

## Goal and boundaries

OfficeKit — The everyday toolbox for your computer. A beautifully simple, offline-first desktop utility for macOS, Windows and Linux. Find a tool, complete a task, export or save its result, and return later. Prefer reusable processing engines to hundreds of disconnected screens. Local sensitive processing by default; clearly label online tools and OS-specific availability. One-time desktop purchase first; future cloud/API services have separate entitlements and pricing after demand validation.

The original product universe covers documents/PDF, images, calculators, unit/data conversion, files, storage/cleanup, privacy, developer tools, network and system utilities. Roughly 400–450 candidates and 100 launch capabilities are planning targets, not release promises. Deduplicate overlapping capabilities. First polish 20–30 working tools; expand only after reliability and real usage justify it. Broad storage cleanup, OCR/AI/chat, complex office conversions, signing/redaction, authenticator/encryption, process termination and SaaS require separate feasibility/security/licensing work.

## Current repository assessment

Rebased onto origin/main at d6567a9; Tauri 2 replaced Electron. The app retains Python engines and a large HTML UI. Search metadata often points at broad tabs rather than exact tool screens; backend capabilities do not establish usable frontend coverage. No shared persistent result/history model is implemented in the inspected code. Support currently stores local JSON tickets while presenting delivery/triage expectations. Batch infrastructure has partial-failure/order handling but no demonstrated cancellable persistent lifecycle API. UI assets use external resources despite offline messaging. Some financial labels assume dollars and results lack generic export/bookmark actions.

The inspected Tauri Rust entry registers a status command and shell plugin, not backend startup; config has no sidecar declaration and CSP is null. Treat the shell migration as present, and verify complete Python delivery/startup, frontend asset build, security and clean-machine packaging. Earlier Electron-specific findings are historical, not current migration tasks. Existing tests and README coverage/performance claims need fresh evidence before release promises.

## Proposed UX

Navigation: Tools, Favorites, History, with Help & feedback and Settings at the bottom. Tools is a Mac-style gallery/list page grouped by category, with local search, favorite shortcuts and a short recent-tools list. Groups: PDF & Documents, Images, Calculators, Unit & Data Converters, Files, Storage & Cleanup, Privacy & Security, Developer Tools, Network and System; Dictation may have its own group while supported. Gallery/List share registry, query, category filter and favorites, with locally remembered view preference. Search opens an exact stable tool destination and never advertises unavailable functionality as usable. Licensing, updates and other administration belong in Settings.

Gallery shows compact icon/name/one-line-purpose tiles and favorite actions under category headings with accurate counts. List offers denser rows with the same data/actions. Default alphabetical ordering within groups; omit empty categories. No promotional heroes, rating/price badges, copied third-party assets or invented tool counts. Both views support keyboard use and empty-search recovery. Category grouping is the assumption for the user's unfinished “grouped by” request; adjust if they prefer task-based grouping.

| Concept | Meaning | Record |
| --- | --- | --- |
| Favorite | A deliberately pinned tool | tool ID, optional order |
| Recent tool | A deduplicated recently opened tool | tool ID and last-opened time |
| History | A deliberately executed operation | immutable result record and lightweight summary |
| Saved result | A specific operation kept for later | bookmark linked to operation, optional title/note |

History uses All/Saved/tool filters over the same records. Do not introduce chat-history language unless a real chat feature is introduced. Common anatomy: heading, essential inputs, advanced options, one execution action, result summary, shared Copy/Export/Save actions, expandable assumptions/details. Reopened results do not silently rerun; Use these inputs seeds a new draft. Changed inputs mark the old displayed snapshot as stale. Job status includes queued, running, completed, partial completion, failed and cancelled where supported; no fake cancellation or fabricated progress.

## Branding and design contract

Canonical reference: `DESIGN_SYSTEM.md`; tokens: `design/officekit-tokens.css`; complete review flow: `design/mocks/officekit-final-flow.html`. Blue + Toolkit is provisional. Compare alternate palettes and vector marks in `design/mocks/officekit-branding.html`; obtain a specific selection and screen approval before wiring into the app. Use System/Light/Dark with one approved identity, semantic status tokens, native/system typography, readable numbers, understated borders and no permanent marketing banner. Follow the component ownership and state rules in `design/COMPONENT_STRUCTURE.md`.

The mock demonstrates a real deterministic loan calculation with session-only records and export previews. It is not production code, storage, a PDF/image exporter or a server implementation. See `design/README.md` for walkthrough, checks and limits. Commit authorization does not imply runtime implementation permission or visual sign-off.

## Application architecture

```text
Tauri desktop / UI source
        ↓ typed application boundary
Tool registry + execution service
        ↓
Python/Rust processing engines + platform adapters
        ↓
Safe filesystem + local SQLite + managed artifact directory

Separate explicit network purposes:
optional telemetry / feedback delivery / updates / licensing
```

Build on Tauri, retain working Python engines initially, and migrate individual engine paths to Rust only for a demonstrated packaging/performance/safety benefit. Establish a single frontend source/build pipeline; do not edit root and dist-ui as divergent sources. A React/TypeScript component organization is proposed, not installed. Start with narrow typed commands and validated engine-specific DTOs; permission metadata never grants filesystem access. Do not expose broad shell access to the webview.

Registry fields: stable tool ID, aliases, category, exact route, availability/platforms, offline/network requirements, input/output schemas, result/export capabilities, required permissions and retention classification. Version option/result schemas. Instant local search does not require AI.

Shared execution: validate selected inputs and limits; bounded concurrency and resource use; honest progress; cooperative cancellation where supported; input order and per-item outcomes; temporary writes followed by atomic finalize where feasible; originals preserved; explicit overwrite policy; meaningful failure categories. Persist lifecycle records. A cancelled job's late completion must not be presented as successful saved output without reconciliation.

SQLite in native app-data stores favorites, recents, operations, per-item outcomes, artifact references, saved labels, preferences, feedback drafts and consent-aware outbox state. Managed files live separately from database records. Migrations, database transactions and backup/upgrade behavior are release responsibilities. No account or tenant infrastructure for local-only state; future hosted products require authenticated ownership independently.

## Saved results and retention

Persist allowed validated inputs, units, assumptions, results, tool/engine version and original time. Never automatically retain passwords, JWT contents, generated secrets or sensitive documents. Ordinary history should be lightweight by default. Proposed unsaved-history expiry: 30 days; user-configurable/off. Saved results stay until removed. Clearing history excludes saved items unless explicitly included.

File-result bookmarks default to retaining an explicitly chosen managed output copy; an external reference is an advanced choice with a clear missing-file state. Source-file retention is a separate explicit option. Locate file reconnects a moved external artifact. Removing a bookmark/history row never removes a user-owned original/export. Managed artifact deletion needs clear ownership, orphan detection, a review of affected results and the applicable destructive-action confirmation.

## Export plan

One shared dialog, format capabilities per tool, local generation from immutable snapshots. PDF: printable report, assumptions and optional complete table. CSV: structured numeric data, units and separate schedule when relevant. JPEG: shareable result summary. PNG: sharper lossless summary. XLSX for appropriate tabular tools. Copy/TXT for text. Converted file outputs use their actual formats and deliberate native save destinations, not generic screenshot exports.

Add Markdown for AI-chat context packs, self-contained offline HTML for quick sharing, editable PowerPoint (.pptx) summaries, versioned JSON result bundles and selected ZIP handoff packs where meaningful. Prepare for AI chat previews selected assumptions/results/redactions locally and never automatically uploads to a model provider. PPT is a designed editable deck, not screenshots pasted onto slides; HTML contains no remote resources/tracking or untrusted scripts. Export formats are shared capabilities, not additional counted tools. The expanded detailed release target is [123 capabilities](RELEASE-123-TOOLS.md), each with depth and verification cases, plus batch/presets/fixed recipes/scenario comparisons; this supersedes the approximate 100-capability launch target as planning scope, not a shipping claim.

Footer: optional removable `Generated with OfficeKit · officekit.app`, with an optional export timestamp/timezone. Creator metadata is separately optional and off by default. Metadata excludes device/license IDs, usernames and source paths. No pixels or promotional rows added to CSV; use a separate metadata JSON inside a selected ZIP bundle. No branding injected into converted user PDFs/images without explicit selection. No tracking links or remote export rendering. Store original operation time separately from export time and local user preferences separately from snapshots.

## Help and feedback

Three entry choices: Report a bug, Request a feature, Leave a testimonial. Intent-specific fields, optional reply contact, optional previewable redacted diagnostics. Testimonial publication permission is separate. States reflect reality: draft, waiting for connection, sending, sent/received only after acknowledgement, delivery failed; remotely verified lifecycle updates only. Draft persistence, bounded retries and duplicate submission handling belong to a separate online support boundary. Never attach files/secrets automatically or present local fabricated triage.

## Version history, updates and quick communications

Provide Help → What's new with browsable shipped-version release notes; Settings → Updates with current version, last check, explicit checking/install actions and a quiet update badge; and a single relevant dismissible banner for timely notices. Post-upgrade What's new is acknowledged once, not a recurring startup interruption. No perpetual promotional banner. Public validated/cached release-note and announcement feeds are separate from analytics, and updater artifacts/metadata need signature verification. Manual requests and explicit automatic-check/network preferences govern service traffic; local tools continue offline. See [COMMUNICATIONS-PLAN.md](COMMUNICATIONS-PLAN.md) for schemas, version/dismissal rules and release checks.

## Telemetry and heartbeat

Independent unchecked opt-ins, tools fully usable with sharing off. Ask once after a completed task or in Settings, never gate use or repeat refusals. No recording/queue before consent or retrospective collection. Recheck permission immediately before sending; opt-out cancels pending work where possible and purges unsent data. Fresh consent for material scope expansion.

Usage: locally aggregate stable tool IDs, action counts, export formats and allowlisted broad errors; app version/OS family only. No query text, exact interaction timestamps, inputs/results/files, clipboard, raw exceptions, paths, emails, tokens or persistent installation identifiers. Heartbeat: at most once per 24 hours while open, coarse active-app signal, no background daemon/device ID. Cannot measure unique users reliably; disclose that limitation. Network infrastructure sees IPs even with identity-free payloads; exclude them from analytics and minimize separate operational logs.

Proposed server: dedicated HTTPS ingest with strict schemas, enums, small payload limits, rate limiting and short-lived batch deduplication. Suggested small AWS API Gateway/Lambda/DynamoDB shape depends on volume validation, not a deployment commitment. Distributed clients cannot safeguard a shared embedded secret; metrics are approximate/untrusted and never billing/entitlement evidence. Bounded offline queues, timeouts, backoff/jitter, seven-day TTL and proposed 256KB cap. Proposed raw batch retention seven days; daily aggregates 90 days, then coarse totals if justified. Authenticate admin access. Disable body logs and test actual retention. Detailed proposal: `design/officekit-branding-and-privacy-plan.md`.

## Safety, packaging and commercial requirements

Licensing proposal: one shared codebase with a Free sampler build containing only a few actual implementations, plus a Paid installer with signed device-bound activation. Exclude paid implementations/dependencies from Free artifacts rather than hiding UI; use server-only signing authority, native/execution-boundary authorization, self-service device recovery and a reviewed managed licensing service where suitable. Required: per-key single-device and multi-device policies with server-enforced capacity and separate device entitlements; device count is independent of feature edition and does not require separate installers. Suggested sampler: five to ten free tools and initial online activation with offline verification afterward; exact offers remain provisional. Perpetual offline entitlement cannot guarantee immediate revocation after transfer/refund; strict control needs disclosed renewable leases. See [LICENSING-PLAN.md](LICENSING-PLAN.md) for complete policy, build boundaries, attack limitations and validation.

User-selected scope, path/symlink validation, input size/time/resource limits, safe subprocess arguments, archive traversal/bomb defenses and no silent overwrites/deletions. Cleanup remains scan → review exact paths/actions → confirm → native Trash where possible → audit/recheck, with exclusions and honest undo limits. Library maintenance/license/codec redistribution review is a distinct task; no implied commercial clearance.

Validate supported OS versions, Python/native-library packaging, Tauri capabilities/CSP, signed installers and updates, startup/shutdown, permissions, long/Unicode paths and native dialogs. Replace embedded license-signing authority with public-key verification and separate issuance. Verify speech/audio locality before absolute privacy claims. Document desktop entitlement/device/update/support scope, refunds and separately paid future cloud services. Defer SaaS, risky cleanup and large feature counts until local workflows and demand are established.

## Delivery roadmap

| Phase | Deliverable | Exit condition |
| --- | --- | --- |
| 0: baseline | Capability inventory, exact route map, dependency review, Tauri backend packaging audit | Supported tools have usable destinations; clean machine runs representative PDF/image operations |
| 1: design approval | Brand choice, complete-flow light/dark mock, error/long-job/artifact states | Exact approved artifacts and dated approval recorded |
| 2: local foundation | Typed registry/commands, execution model, SQLite/artifacts, safe outputs | Restart, cancellation/partial failures and privacy retention behave correctly |
| 3: core UX | Shell/search, favorites/recents/history/saved results, first polished tool | Find → calculate → save → restart → reopen preserves original result |
| 4: outputs | Shared exports, attribution preferences, converters/batches | Export fidelity, clean CSV, original snapshots, output safety proven |
| 5: feedback/privacy | Three feedback paths, reviewed optional telemetry consent/ingest | Honest delivery, independent consent, opt-out purge, offline resilience proven |
| 6: release quality | 20–30 reliable tools, documentation, three-OS install/update checks | Tests and release evidence meet `docs/TESTING.md`; no marketing overclaims |
| 7: expansion | Demand-led batches/presets/file/developer tools; safe storage later | Evidence supports 50–70 then ~100 capabilities; APIs/SaaS validated independently |

Fixed typed pipelines and reusable presets may follow proven batch usage. Defer general visual workflow editors, cloud sync, collections and complex chat features. Do not give calendar dates until baseline packaging/processing scope is measured.

## Evidence and approval

Tests/checks must distinguish current engine coverage, prototype checks and future product acceptance. Canonical guidelines: `docs/TESTING.md`. Prior mock checks are documented, browser visual/accessibility verification remains outstanding. Specific brand/screen approval remains pending in `review/officekit-design/requirements.md`. Commit all design/planning artifacts as a reviewable baseline; do not treat that commit as a deployed product or approved implementation.
