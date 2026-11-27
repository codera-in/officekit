# OfficeKit architecture decisions

Version: 1.1.9 · Merge the System Stats and shared file-intake architecture decisions. Earlier: 1.1.6.

## Key decisions

### 2026-10-26 — Invoice working folder and global configuration

- **Status:** Owner approved initial invoice mock (“approved”) and selected direct-folder storage (“Work directly in the selected folder; I control its cloud sync”). Business settings/profile refinements and the subsequent SQLite workspace/backup/restore revision were accepted by the owner.
- **Decision:** Use the native-selected folder as the invoice library; do not add an OfficeKit sync engine. Preserve native path authority, atomic SQLite storage, full history, verified complete backup/restore, revision checks and local draft recovery. Currency, country-neutral tax profiles and bank/payment definitions are configurable per business and snapshotted on issued documents.
- **Alternatives considered:** A private local library with manual exchange into a cloud folder; rejected by the owner in favor of directly owning the working folder. A hosted/cloud database is outside scope.
- **Constraints:** One computer edits at a time; the external cloud provider controls its own sync. Do not silently overwrite external edits or renumber issued invoices. All invoice-specific code must meet the owner’s 100% module coverage gate.
- **Design records:** `docs/PRD-invoices.md`, `docs/hld/invoices.md`, `docs/invoices/API-CONTRACT.md`, `docs/ui-research/2026-10-26-approved-invoices.md`.

### 2026-10-24 — Local System Stats telemetry extension

- **Status:** Owner approved the Stats-inspired in-app and menu-bar mock (“Approve this mock”).
- **Decision:** Extend the existing `/api/system/metrics` snapshot with optional CPU-core, GPU, sensor and battery fields. Keep history in browser memory, use local OS/psutil sources, and add GPU/Battery drawers through the existing native drawer bridge. On macOS, read sensor temperatures through dynamically resolved IOKit HID functions in the native layer and merge them into the local view; unsupported symbols leave the optional field unavailable. Existing Quick Controls remain the user-facing menu-stat selection; GPU follows CPU, and detected battery is included whenever any menu stat is active. Sensors remain in the app view.
- **Reason:** Reuses the existing sampling, authentication and rendering paths without another endpoint, persistent state or cloud integration.
- **Alternatives considered:** (1) Add a separate system-monitor process/window, which duplicates sampling and native UI; (2) call OS commands from the webview, which bypasses the authenticated local API and native command boundaries.
- **Constraints:** Hardware APIs vary by OS/device. Optional readings remain null when unavailable. History is bounded and in memory. Native menu drawers increase from five to seven to keep dictation available alongside the four existing stats, GPU and battery.

### 2026-10-23 — Shared file intake for window drops and Finder Open With

- **Status:** Owner selected Option A (“shared intake and tool chooser”), approved the revised grouped-catalog mock (“approved”, 2026-10-23), and agreed to the HLD (“agreed”, 2026-10-24); initial native queue, content bridge, chooser, subsets and Finder metadata are implemented. App and packaged acceptance remain pending.
- **Owner refinement (2026-10-23):** “based on the droped / open file .. it should list the supported tools .. ex: pdf - ? anotate , edit , extract , zip , etc.. so think smart.” The intake must show the full set of tools that can use the received file, grouped and searchable; it must account for per-tool file-count and release limits, and explain content-specific requirements. For example, a PDF can be edited/annotated, have pages split/reordered/rotated/deleted, have text/tables extracted, be compressed/inspected/protected, or be placed into a ZIP. A tool requiring another file remains visible under a “needs more files” state.
- **Decision:** Route native drops on the OfficeKit window and macOS Finder Open With launches through one native intake queue and one UI flow. Match incoming files against declared tool input capabilities and let the user choose among eligible tools. Continue into the existing tool flow so its own validation and review/run steps remain authoritative. The existing Media Toolkit registered drop zones keep precedence for drops inside those targets. The native layer receives and validates host paths and creates the bounded selection/grant; the webview receives selection metadata and a capability to continue, not unrestricted host paths. Register only file types with implemented intake support.
- **Reason:** One shared path handles app-running and app-launch entry, avoids arbitrary extension-to-tool guesses, and gives overlapping formats an explicit choice.
- **Alternatives considered:** (1) direct static extension-to-tool routing, which misroutes overlapping formats and drifts from tool capabilities; (2) Open With for a narrow type set with no general window drop intake, which does not cover the requested tool family.
- **Constraints:** macOS-first because the request and native Open With surface are Finder-specific. Validate startup/release-profile event readiness, multi-file handoff, lost permissions/disappearing files, installed bundle registration, and current media-zone behavior in the HLD/LLD and packaged verification plan. No file operation starts automatically from intake.
- **Design records:** `review/file-open-and-drop/requirements.md`, `docs/hld/file-intake.md`, `docs/lld/file-intake.md`.

### 2026-10-22 — Parallel delivery of pending tool slices 2–6

- **Status:** Owner chose “Foundation first” on 2026-10-22.
- **Decision:** Land one foundation PR that gives every slice its own files before parallel work starts. It adds a per-slice catalogue module merged into `TOOL_REGISTRY`, a per-slice `APIRouter` module, a per-slice `assets/officekit-<slice>.js` that registers destinations, tabs and PDF operations through a shared hook, and a per-slice doc page. Tests and docs compute tool counts from the registry and release profile instead of hardcoding them. Generated `dist-ui/`, `officekit.css` and the CSP hash are rebuilt at each merge, not hand-merged. Then five agents (calculators, developer, files, image, PDF) build in separate worktrees. Engines, routers and tests start at once; UI code waits for each slice's approved mock. PRs merge one at a time after CI is green.
- **Reason:** Each new tool currently edits about 12 shared files at the same lines (registry tail, inline routes, `index.html` maps, hardcoded counts, doc headers, generated output), so five unprepared branches would conflict everywhere.
- **Alternatives considered:** (1) build in parallel and resolve conflicts at merge, which is cheap up front but slow and error-prone across about 12 files × 5 branches; (2) parallel engines with serial UI wiring, which leaves the UI as a single-threaded bottleneck.
- **Constraints:** S06 restore needs new native authority and ships only with its own approved design (owner approval 2026-10-23, recorded in `docs/ui-research/2026-10-22-approved-pending-tools.md`). The authority it adds is four native commands in `src-tauri/src/workspace_native.rs`: `trash_restore_confirm` and `trash_record_forget` show a native dialog before they act; `trash_restore_apply` runs only the restore that the confirm step approved; `trash_restore_reveal` only checks that its path is an absolute, existing, non-link path and opens it in Finder. The first three are grant-gated through the backend: the grant is minted only after the user confirms, and every mutating route needs the native grant header. `trash_restore_reveal` is not grant-gated, by design. F11 (symlinks) needs no new native authority: it uses the existing folder selection and the read-only link walk in the Files HLD section 4. New tools stay development-only until installed acceptance. See `review/pending-tools-slices/requirements.md`.

### 2026-10-21 — Local calendar meeting companion

Owner approved macOS-first EventKit integration and full watch-check/tap/point/wave animation with “approved”. Reuse the existing native corner companion, settings storage and main-only permission command rather than create another window or account flow. A separate serialized EventKit worker keeps calendar reads away from UI/runtime locks; a pure absolute-time policy selects the next meeting within 30 minutes. Calendar contents remain session-only. Alternatives were manual ICS imports (stale/manual updates) and direct provider accounts (new authentication/network scope). Existing development-only release gating stays. See `docs/hld/meeting-countdown.md` and `docs/lld/meeting-countdown.md`.

### ADR-lite: Paid activation with email + key, gates and gated delivery

- **Status:** Selected by the owner (“Our own OK1 keys”; “Amazon SES from the Lambda”; “Switch, drop encryption”). An encrypted paid payload was considered first and dropped.
- **Decision:** One installer, no Free edition; the app is locked until activated. Activation requires the purchase email and the `OK1` licence key. Licences are issued by a provider-neutral `issueLicense` (idempotent per source and source reference); a Dodo `payment.succeeded` webhook is the first adapter and SES delivers the key plus a short-lived signed download link. The signed device-bound entitlement is enforced in the Python sidecar (authoritative) and Rust, and the updater serves licensed devices only.
- **Reason:** The decryption key must reach every activated Mac, so encryption adds a lot of build risk (Rust crypto, a custom importer, packaging, per-release key rotation tied to updates) for little protection beyond the gate. Not publishing the installer, gating updates and revoking refunded licences give more practical protection per unit of effort.
- **Alternatives considered:** (1) encrypted paid payload with a per-device wrapped release key; (2) a separate Free and Paid installer; (3) Dodo-issued keys; (4) email delivery by Dodo receipt or a success page only; (5) a Mac App Store build (needs StoreKit, sandbox and no updater; out of scope).
- **Constraints:** Local software can be patched; this raises effort, it does not make offline processing uncrackable. Revocation reaches offline devices at the next optional online check (about 30 days, long grace). Channel adapters (AppSumo later) map tiers to device allowance and features and never change activation.
- **Compatibility:** `officekit.entitlement.v1` is replaced by v2 (adds `email_sha256`); the client fails closed on unknown schemas. `/api/license/activate` stays HTTP 501 locally. The `private-beta` release profile is removed when gating lands.

### ADR-lite: Local-first dictation quality pipeline

- **Status:** Selected by the owner (“everything in a single branch … multiple verified / tested commit”); field-text context is opt-in only.
- **Decision:** Keep ASR native and local. Add silence trimming, streaming commit, Whisper `initial_prompt` biasing, Accessibility app/field context, an opt-in downloaded local LLM cleanup pass with a deterministic fallback, and user-approved dictionary suggestions learned from edits.
- **Reason:** Most perceived quality in paid dictation tools comes from the stages around the ASR model (VAD, context, cleanup), not a custom model; each can run on-device.
- **Alternatives considered:** (1) rules and prompts only, which cannot handle messy phrasing; (2) phased rules then LLM, which defers the LLM and streaming; (3) cloud ASR or LLM, which violates the local-first and no-remote-recognition rules.
- **Constraints:** No audio, transcript or field text is logged or sent off-device. The LLM is an explicit, hash-pinned, licence-recorded download and never part of the DMG. Cleanup never blocks paste and falls back to deterministic cleanup. Secure fields are never read. New native dependencies must pass the full Tauri link path (P-158).
- **Compatibility:** `/api/dictate/cleanup` and the `dictation-transcript` event stay backward compatible; the manual dictionary keeps its 256-entry cap.

### ADR-lite: Cross-platform Archive Manager

- **Status:** Mock approved by the owner on 2026-10-18 (“looks good”); implement the recommended packaged multi-engine adapter.
- **Decision:** Use a packaged multi-engine adapter and per-format capability registry on macOS and Windows. The initial implementation bundles pinned 7-Zip only; libarchive and Unarchiver remain future adapters. The current registry reports read, extract and create separately and only enables operations implemented in OfficeKit. Use MacPacker for product behavior reference only; do not incorporate its GPL-3.0 application source into the commercial OfficeKit product.
- **Reason:** The existing archive tool is ZIP-only. 7-Zip documents broad read coverage but a narrower writer set; libarchive and Unarchiver provide complementary formats. The combined adapter can support local archive browsing and selection while keeping unsupported operations explicit.
- **Alternatives considered:** (1) depend on user-installed tools, which makes support vary by machine; (2) native OS APIs, which diverge and do not meet the requested format coverage; (3) one external engine, which leaves gaps in legacy formats and writers.
- **Constraints:** Pin binaries per target, ship license materials and comply with each engine’s terms, including the 7-Zip unRAR restriction. The first slice packages 7-Zip for macOS and Windows, lists supported archive contents, enables ZIP creation and safely extracts the fully supported 7-Zip format set. Partial variants remain browse-only. Broader format support is only claimed after implementation and validation on both platforms. No archive command uses a shell; extraction is staged, bounded and published through native output authority.
- **Compatibility:** Extend the existing direct file picker, output grants, activity/cancellation flow and file-job lifecycle; source archives remain unchanged.

### ADR-lite: OfficeKit-owned Media Toolkit

- **Status:** Selected by the owner with “go ahead”, 2026-10-18.
- **Decision:** Build the Clop-inspired media preparation capabilities as one OfficeKit Media Toolkit, reusing current local engines and adding OfficeKit-owned media adapters. Do not require Clop to be installed at runtime.
- **Reason:** The owner asked to include Clop's tools and merge them with OfficeKit's existing tools. A shared local workbench avoids duplicate image/PDF workflows and remains under OfficeKit's platform, privacy, packaging, and support rules.
- **Alternatives considered:** (1) delegate to installed Clop, which makes an external app/license and macOS-only runtime dependency; (2) separate wrapper screens, which duplicate current converter/resize/compress flows and leave batch/results inconsistent.
- **Constraints:** Every encoder/runtime must pass provenance, license, codec patent, packaging size, platform, and update review before bundling. Media processing remains local by default. Public URL import and upload/shelf handoff require explicit user actions and strict network boundaries. Clipboard and folder automation default off. Original files remain unchanged; PDF lossless behavior remains distinct from visual compression.
- **Compatibility:** Existing image conversion/resizing/metadata IDs remain exact searchable destinations into the unified image mode. Screenshot Editor, PDF page tools, voice transcription, and meeting notes stay independently accessible and may hand off results to the optimizer.

### ADR-lite: Finder image preparation handoff

- **Status:** Selected under the approved Finder/hotkey design, 2026-10-18.
- **Decision:** Package an image-only Automator Quick Action that invokes the existing bundled CLI with the built-in typed `optimize-image` preset. Install and remove it only from an explicit Automation screen action.
- **Reason:** Finder already supplies selected file arguments; the CLI already validates paths, preserves sources, and runs the same local optimizer. This keeps file paths out of the webview and avoids a second native job API.
- **Alternatives considered:** (1) Tauri file-open events would require file associations and UI queue/race handling; (2) a separate helper would duplicate packaging and operation validation; (3) workflow installation could be automatic but would add an unrequested OS integration side effect.
- **Constraints:** Quick Action accepts images only; it resolves OfficeKit by bundle identifier, uses argument vectors, never accepts scripts/recipes from Finder, and uses exclusive no-replace numbered sibling output on name collisions. Installer refuses to replace an existing workflow and removal requires the OfficeKit ownership marker.
- **Compatibility:** CLI `--recipe` behavior and default collision refusal remain unchanged. The Quick Action uses a separate built-in preset and explicit `--collision-policy suffix`.

### ADR-lite: Hybrid local PII detection

- **Status:** Selected by the owner in the goal “follow the plan to implement hybird approch and verify it with proper tests and eval and share the results”.
- **Decision:** Keep deterministic format/checksum recognizers authoritative for structured identifiers and add a local neural span recognizer only for contextual gaps. Resolve evidence and coverage deterministically before projecting findings into the existing public match DTO.
- **Reason:** Existing regex/validation behavior is valuable for predictable structured identifiers, while names and contextual identifiers need text context. The POC explicitly calls for the combined configuration and priority span resolution.
- **Alternatives considered:** (1) baseline-only, which does not address contextual recall; (2) neural-only, which discards existing structural validation and predictable ID detection; (3) baseline plus region-specific structural recognizers, which improves format coverage but does not resolve unstructured names/addresses.
- **Constraints:** The neural recognizer must be local and pinned. The Fastino GLiNER2 PII card currently claims seven European languages and its listed artifact is approximately 1.23 GB; BardsAI's multilingual ONNX artifact is approximately 1.11 GB. Neither is presumed to meet the POC's 200 MB packaged-addition target. A candidate that misses this gate may remain evaluation-only; any production recommendation must state that result.
- **Compatibility:** Public match fields and routes stay unchanged; source files remain untouched; scan results remain review-first; Mask stays the default and Redact remains full replacement.

### ADR-lite: Global desktop layer (clipboard, snippets, window manager)

- **Status:** Selected by the owner on 2026-10-19 ("A: native Swift panel"; window manager added to scope: "THIS IS WHAT I WANT GLOBAL WINDOW MANAGER").
- **Decision:** One native Swift layer inside the always-running OfficeKit process owns global shortcuts (Carbon `RegisterEventHotKey`), the floating key-capable panel host, pasteboard capture, snippet keyword expansion and Accessibility window control. Rust orchestrates and forwards to the existing Python store and API; clipboard history and snippets stay Python-owned. Window layout math stays in Rust, reusing `snap_target_bounds`, and Swift only reads and sets window frames.
- **Reason:** The process already survives window close, holds the Accessibility grant and has the dictation hotkey and paste code. Carbon hotkeys swallow the key and need no extra permission, unlike the observe-only NSEvent monitors. A native panel avoids the focus-stealing and latency risks of a webview picker.
- **Alternatives considered:** (1) a second Tauri webview as the picker, which reuses the web UI but steals focus and needs its own capability; (2) a Rust-owned SQLite store, which duplicates the Python store, routes and tests; (3) separate helper processes per feature, which multiplies permissions and background footprints.
- **Constraints:** Never log clipboard contents, typed keystrokes or window titles. The keystroke buffer is memory-only and at most 32 characters. Concealed and skip-listed sources are never stored. Real global delivery, pasting and moving other apps' windows are manual acceptance on an installed build.
- **Compatibility:** Existing `/api/clipboard/*` routes and the in-app Clipboard tab keep working; the dictation hotkey monitor and paste path are reused, not replaced; the in-window Rectangle snapping for OfficeKit's own window stays.
