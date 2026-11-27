# Shared file intake for window drops and Finder Open With — HLD

**Version:** 1.0.8 · 2026-10-25 · Record review fixes for filtered tool choice, assertive intake errors, and pre-stream file validation. Earlier: 1.0.7.
Status: Implemented; Rust/API/UI suites and the signed ARM64 DMG smoke test pass. Bundle associations are present at alternate rank. Installed Finder delivery and native drag gesture acceptance remain manual checks.
Requirements: `review/file-open-and-drop/requirements.md`.
Approved mock decision: recorded in the requirements and `docs/ARCHITECTURE.md`; visual preview was removed after approval.

## 1. Problem and outcome

OfficeKit already has native window-drop handling for registered Media Toolkit zones, native file-selection grants, many browser file inputs, and file-aware tool destinations. A file dropped elsewhere on the app window is ignored, and Finder has no OfficeKit **Open With** association. A user who does hand a file to the app should see the OfficeKit tools that can accept that file and choose one deliberately.

Deliver one macOS-first intake path for window drops and Finder Open With. It presents a grouped, searchable catalog based on the received file selection, selected count, tool input limits, prerequisites, and the verified release profile. Each choice opens the existing tool workflow. Intake never starts the operation or bypasses its existing validation, review, confirmation, result, or cleanup steps.

## 2. Scope and boundaries

### In scope

- Native file drops on the OfficeKit window and Finder **Open With → OfficeKit**, for one or more supported files.
- The same bounded selection lifecycle and chooser for both sources, with the entry source shown for context.
- Deterministic capability declarations that map existing tool IDs to accepted file kinds/extensions, single-vs-multiple cardinality and size limits, prerequisites, task group, destination, and searchable terms.
- Matching against the active `/api/release` profile. Tools not present in the verified `tool_ids` are not listed. No capability metadata grants access by itself.
- Open-With registration only for file types OfficeKit can ingest in at least one shipped tool. Finder association is alternate (not default) rank.
- Existing Media Toolkit drop target precedence.
- Selection cleanup, safe failures, native packaging registration, and focused source/browser/package verification.

### Out of scope

- Automatically choosing or running a tool; automatic format conversion, OCR, password recovery, malware scanning, or content judgment.
- File editing in the chooser, a new processing engine, persistent recent-file history, cloud upload, or remote service.
- Folder drops. This intake accepts regular files; directory selection remains with existing folder-specific workflows.
- Promising that an extension proves actual file contents. Existing tool parsers remain authoritative and reject invalid or mismatched input.
- Non-macOS shell Open With integration. General Tauri window drop routing can be implemented for supported desktop platforms, but platform-specific acceptance is a release gate.

## 3. User-visible behavior

1. A single or multi-file drop outside a registered Media Toolkit zone opens **Open files** with a safe display name/type/size row per item. Finder Open With opens the same page and may deliver several files.
2. OfficeKit groups compatible choices by task (for example, PDF edit & secure, pages, extract & convert, inspect/optimize/package), provides search, and shows a useful empty/error state when no tool accepts the selection.
3. Every eligible supported tool in the active release is discoverable. A tool with a cardinality gap remains visible but disabled with the missing requirement (e.g. “Merge PDFs — needs another PDF”). Choices that cannot accept the current file type are not shown. Count-specific actions become enabled when their requirements are met.
4. Mixed selections only offer an action when all selected items satisfy its contract, or when that tool explicitly supports selecting a compatible subset. Intake never silently drops an item.
5. Required prerequisites are stated plainly (known password, selectable text/layout where relevant, another file, or a supported statement layout). Content-dependent checks remain in the destination tool; a description is not a promise that the input will pass parsing.
6. The first eligible, low-risk destination may be preselected for convenience, but no operation begins. **Continue** opens the existing destination and transfers the selection through that destination's declared adapter.
7. Existing per-tool size/count limits and profile authorization are enforced again by the destination. A tool's own screen retains its current confirmation, review, source-preservation, output, and cleanup behavior.
8. Removing a file recalculates the catalog. Closing/canceling the chooser releases its selection. Unsupported, duplicate, unreadable, expired, inaccessible, too-large, or changed files receive a concise actionable status and are never routed to an unrelated tool.

The approved design is the PDF catalog preview approved by the owner (“approved”, 2026-10-23), documented in `review/file-open-and-drop/requirements.md`. It has four task groups, search, a disabled merge choice that says it needs another PDF, one Continue action, and a note that the live list is release-, type-, count-, limit-, and prerequisite-aware.

## 4. Current state and reuse

| Area | Current behavior | Planned integration |
| --- | --- | --- |
| `src-tauri/src/lib.rs` | `WindowEvent::DragDrop::Drop` routes only when `MediaDropEnabled::target_at` returns a registered target; all other drops return. `RunEvent` handles Reopen and Exit. | Preserve media target routing first, add generic intake otherwise; queue `RunEvent::Opened` URLs and deliver them through the same bounded intake path. |
| `src-tauri/src/workspace_native.rs` | Registered media drop validates up to 30 distinct regular files, canonicalizes, and registers `/api/file-selections`. Workspace native grant and local API helpers already exist. | Reuse native validation/grant calls for regular files; reject folders/symlinks/special files. Keep Finder input file-only. |
| `officekit/engines/engine_file_selections.py` | Process-local selection store, no staging/copying, 10,000-root storage bound, 30-minute TTL, paginated opaque manifests, no-follow open, stable identity checks. | Use selection IDs and file IDs; do not expose absolute paths to the webview. Set a smaller product intake bound of 30 roots, matching the current media-drop limit. |
| `app.py` and `API-CONTRACT.md` | Existing POST selection, GET paginated manifest, DELETE release; native-grant authorization is applied to registration. | Add bounded authenticated content and subset routes. Subsets accept manifest IDs only and preserve no-follow identity checks. |
| `index.html` | Existing tool destinations include PDF workbench, PDF editor, statement, PII, file workspace, archive tools, image and media workflows; profile discovery already distinguishes loading/ready/unavailable. | Add Open files intake view, a chooser, and a selection adapter; reuse `officekitToolDestination` (core plus registered extension slices) and destination renderers. Queue navigation only while release discovery is loading; fail closed after unavailable. |
| `src-tauri/tauri.conf.json` + macOS override | No `bundle.fileAssociations`; current macOS override supplies resources only. | Declare supported document associations and configure Finder ranking as alternate. Validate the packaged app's Open With registration. |

## 5. Catalog and capability contract

The catalog is a deterministic product capability lookup, not AI ranking. It uses declared tool input metadata and the verified release profile. The capability record should include:

| Field | Purpose |
| --- | --- |
| `tool_id` | Existing catalogue/release-profile ID; must resolve through `officekitToolDestination` (core or registered extension destination). |
| `accepted_kinds` / `extensions` | File kinds/extensions this tool can ingest; file-kind matching is a candidate filter only, never parser authorization. |
| `root_kind` | `file` only for this intake. Folder actions remain in their folder-specific workflow. |
| `min_files`, `max_files`, `same_kind` | Cardinality and homogeneous-selection rules; the destination remains authoritative. |
| `max_file_bytes`, `max_total_bytes` | Intake/adapter ceilings where they differ from the shared 64 MiB upload ceiling. |
| `prerequisites` | Plain-text explanation or declarative check such as known password, selectable text, or supported layout. No secrets are stored in intake metadata. |
| `group`, `label`, `description`, `search_terms`, `sort_order` | Searchable, task-grouped presentation and stable UI order. |
| `adapter` | `upload_file` for existing multipart File workflows or `native_selection` for workflows already consuming selection/file IDs. |

The registry lives beside the existing UI tool-destination metadata and is intentionally declarative. A completeness test must cross-check every entry against the actual tool registry/search catalogue and `officekitToolDestination` (including registered extension slices); no stale or unknown ID may be surfaced. Every existing file-accepting tool must have an explicit supported/unsupported intake decision. The active profile removes unavailable tools before grouping or search. A capability record cannot bypass direct-entry profile checks or backend guards.

PDF is the design example, not a special-case router. In the development profile, the catalog should include each implemented compatible PDF destination separately: edit/annotate/sign; protect; known-password unlock; PII review/redaction; split/extract pages; merge PDFs; reorder, rotate, delete pages; watermark; page numbers; resize; flatten; text extraction; table extraction; supported bank-statement extraction; pages-to-images; compression; grayscale; metadata view/removal; create ZIP; and generic file operations whose contracts accept an individual PDF (file details, file type, checksum, rename, split/join). Compare files remains visible as “needs another file” for a one-file selection. The private-beta profile is narrower and therefore exposes only its allowed tool IDs. Never combine separate tool IDs into a misleading single row.

## 6. Native-to-UI flow

```mermaid
sequenceDiagram
    participant OS as Finder / Window drop
    participant T as Tauri native shell
    participant S as Local selection API
    participant U as OfficeKit webview
    participant C as Capability catalog
    participant D as Existing tool destination
    OS->>T: file URLs / dropped paths
    T->>T: Preserve Media Toolkit target precedence; validate bounds and roots
    T->>S: POST /api/file-selections with native grant
    S-->>T: selection ID, display names, expiry
    T->>U: bounded file-intake event or startup queue item (opaque IDs only)
    U->>S: GET selection manifest pages
    U->>C: match type + count + release + capability limits
    C-->>U: grouped eligible catalog and unmet-count states
    U->>D: user selects a tool and presses Continue
    alt upload_file adapter
        D->>S: GET selection file content (bounded octet stream)
        S-->>D: File/Blob with safe manifest name
        D->>D: existing validation, review and run flow
    else native_selection adapter
        D->>D: use selection/file IDs through existing native-selection flow
    end
```

### Intake event and queue

- Use one Tauri-managed queue for cold-start Finder Open With and files received before the webview/release profile is ready. Each queue item contains a source kind and file URLs/paths only inside the native process until registration succeeds. Each OS event is a distinct batch; do not merge unrelated events. After the active chooser completes or cancels, show the next registered batch in FIFO order.
- Queue and batch are bounded. A batch accepts 1–30 unique regular files; reject overflow as one operation with no partial intake. Queue capacity and overflow behavior are specified in the LLD. No dropped event is silently discarded: the app reports a bounded “could not open all files” state.
- On a window drop, test the registered Media Toolkit target first; its current preset/session semantics remain unchanged. Outside those bounds, validate regular files, register a general selection, and open shared intake. Reject folder roots.
- On Finder Open With, parse `RunEvent::Opened { urls }`, accept local file URLs only, preserve their order, and register the set through the same store. Ignore non-file URLs with an explicit status. The Tauri queue survives until UI readiness and exposes a drain operation/event that is idempotent (event notification plus pull-based drain cannot process the same queue item twice).
- Re-check release readiness at drain and at navigation. Queue only while profile state is `loading`; clear and report on `unavailable`, following P-124/P-130.

## 7. API, data, tenancy, and infrastructure

### Route contract

No new persistent or multi-tenant resource is introduced. Reuse these routes and add the content and subset rows to `API-CONTRACT.md`:

| Method and URL | Request | Response | Statuses | Tenant-scoped |
| --- | --- | --- | --- | --- |
| `POST /api/file-selections` (existing) | strict `{paths, access}` body, native grant header | `FileSelectionResponse` with opaque ID/display names/expiry and Location | 201, 403, 404, 422 | No — process-local, authenticated desktop selection; there is no tenant concept. |
| `GET /api/file-selections/{selection_id}` (existing) | offset ≥0, limit 1–200 | `FileManifestResponse`, safe names/opaque file IDs/size | 200, 403, 404, 422 | No — process-local selection. |
| `POST /api/file-selections/{selection_id}/subsets` | strict `{fileIds}` with 1–30 unique manifest IDs; no paths; app bearer | read-only `FileSelectionResponse` for the explicitly selected files | 201, 401, 404, 409, 422, 503 | No — derived from an existing process-local selection. |
| `GET /api/file-selections/{selection_id}/files/{file_id}/content` | opaque selection and manifest file IDs; no body/query; app bearer | `200 application/octet-stream` stream with explicit binary OpenAPI schema, safe attachment filename, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` | 200, 401/403, 404, 413, 422 | No — same-process local selection, no account data. |
| `DELETE /api/file-selections/{selection_id}` (existing) | opaque selection ID | 204; release/revoke selection | 204, 403, 404, 409, 422 | No — process-local selection. |

The subset route derives file roots only from the live parent selection and manifest IDs, then revalidates each no-follow file identity. The content route opens and validates a manifest item through the same identity-checked path before returning its streaming response, checks its size against the 64 MiB upload adapter ceiling, and streams in bounded chunks. It never resolves a path supplied by the webview. Native-selection adapters receive the derived selection directly. Inputs larger than an adapter's limit are disabled for that tool.

The API contract is version 1.91.3. Existing app bearer and native-grant checks remain the authentication boundary; selection IDs are identifiers, not authority.

### Data and tenancy (DBA review)

- **No schema, migration, repository, or persistent record.** `FileSelectionStore` remains process-local and is cleared when the sidecar exits; roots, selection IDs, and expiry metadata are transient.
- No tenant ID is applicable: this is a single-user local desktop process with no tenant/account entity. Selection scope is authorized by the existing local app bearer and native-grant mechanism; do not add tenant-like request fields.
- No cloud DB, event bus, Lambda, or AWS trigger. Native Tauri queue + local FastAPI sidecar are the deployment topology. All file bytes stay on-device.

### Native command/event surface

- Native event: `officekit-file-intake` with a DTO containing `intake_id`, `selection_id`, safe display metadata, `source` (`window_drop`/`finder_open_with`), and `created_at`; no absolute host paths.
- Native drain: one narrow command/API that returns the next bounded pending intake ID/DTO after the webview is ready; acknowledging or draining is idempotent. Exact command naming and queue state transitions are fixed in the LLD.
- `RunEvent::Opened` inputs are queued natively; generic paths are registered with `POST /api/file-selections` using the native grant exactly as current media selection does.
- Content transfer is not a new Tauri command: an authenticated local API stream adapts to existing browser `File` APIs, while selection-native tools receive the opaque IDs.

## 8. Security and privacy

- Reject folders, symbolic links, special files, duplicate roots, malformed/non-local Finder URLs, missing paths, unavailable permissions, and batches over 30. Canonicalize/validate within native code; never accept a path from webview input.
- Native paths are submitted only to the loopback backend with the existing native grant. They are not included in events, URLs, UI state, analytics, errors, or logs. UI receives safe basename, type hint, size, opaque selection/file IDs, and source.
- Content reads use the existing selection store's descriptor-relative no-follow open, identity-at-open and identity-after-read checks; failure is closed and mapped to fixed safe errors. `Cache-Control: no-store`; no partial download is surfaced as a valid input.
- App-bearer auth applies to content reads; native-grant auth applies to native selection creation. A guessed or expired opaque ID must not disclose host paths or file bytes.
- No AI model, provider, telemetry, or external network call is used for file matching. Extension/MIME and simple signature hints select candidate tools only; destination parsers validate contents.
- Original files remain read-only. Existing tools own output-grant, no-overwrite, confirmation, and cleanup semantics.

## 9. Failure and degraded states

| Condition | User outcome |
| --- | --- |
| No compatible tool in this release | “No tools in this OfficeKit build support this file.” Keep safe file list; allow removal/cancel. |
| Valid tool needs more files | Disabled row with count requirement; add another compatible file and catalog recalculates. |
| Release profile still loading | Keep the intake queued; show loading without exposing candidate tools prematurely. |
| Release profile unavailable | Clear queued navigation; show profile error and retry through existing startup handling; never fall back to development tools. |
| File vanished, access denied, identity changed, selection expired | Clear failed item or whole selection according to atomicity; fixed message; re-drop/reopen; never use stale path. |
| More than 30, duplicate, symlink, special file, unsupported URL | Reject the batch (no partial dispatch), identify the safe display label where available, and explain the input constraint. |
| Content stream exceeds 64 MiB or transport fails | Do not continue into an upload adapter; show size/retry message. Preserve selection-native choices only when their own bound permits. |
| Unknown/mismatched extension or parser rejects | Candidate tool is shown only by the declared input rule; the destination displays its existing validation error. Never guess another operation. |
| Media Toolkit target receives drop | Existing target flow wins and no shared chooser appears. |

## 10. Active pitfalls and mitigations

| Pitfall | Risk to this feature | HLD mitigation |
| --- | --- | --- |
| P-001 — engines mistaken for usable desktop tools (Active) | Merely finding an engine/catalog row can lead to dead-end chooser destinations or missing lifecycle. | Every capability is cross-checked to destination and release profile; trace a full chosen-tool workflow and preserve select → process → output → cleanup behavior. |
| P-157 — pathname validation not bound to authorized entry | A path can be swapped between validation and open. | Reuse process-local selected entries and descriptor-relative no-follow identity checks; never let the UI send paths. Test replacement/disappearance during stream and use. |
| P-124 — startup navigation lost during release-profile loading (fixed but relevant) | Cold Finder launch can deliver before UI/profile is ready. | Native bounded pending queue plus pull/drain and one event; apply only after profile validation. |
| P-130 — loading conflated with release failure (fixed but relevant) | On failure, candidate tool routes could queue or fall back to an unintended profile. | Explicit loading/ready/unavailable state; only loading queues; unavailable clears; backend and UI profile authorization remain authoritative. |

## 11. HLD acceptance and verification plan

### Acceptance

1. Window drop outside Media Toolkit target and Finder Open With produce the same file-centered chooser, including multiple files and cold/warm startup.
2. The catalog lists every declared compatible tool for the active release; groups/search are accurate; tool IDs resolve to existing destinations; count/prerequisite states and mixed-file behavior are explicit.
3. Continue opens the selected existing tool with the selected file set; no processing begins in the chooser and all destination validations remain active.
4. Files over the file-count/size/type limits, folder roots, unsupported URL, duplicate paths, symlink/special/missing/access-denied files, changed identity, profile failure, and stream failure are handled without leaking path details or processing unrelated input.
5. Media Toolkit preset-zone drops retain precedence and behavior.
6. `bundle.fileAssociations` makes OfficeKit available in Finder **Open With** for implemented supported file types at alternate rank. A signed/packaged installed Mac check verifies the registration, delivery, warm launch, cold launch and multiple-file case.
7. Mock button check and UI button-count assertions stay at or below the repository's three-button limit.

### Verification matrix

| Layer | Required checks |
| --- | --- |
| Rust/native | capability-target precedence, file URL parsing, max 30, FIFO queue/dedup/overflow/ack idempotence, readiness timing, no path in event DTO, startup/cold/warm behavior, directory policy, fixed native failure mapping. |
| API/Python | selection content route auth, unknown/expired selection/file, 64 MiB boundary, safe Content-Disposition, no-store/nosniff, no-follow/symlink replacement, missing file and identity change during transfer, fixed response errors, selection release. |
| UI/catalog | capability completeness against actual tool registry + destination map; profile loading/ready/unavailable; extension/kind/capability filtering; count and mixed-kind recompute; prerequisites/search; remove/cancel/release; Continue adapter mapping; 3-button assertions per visible state. |
| Integration | a representative PDF, image, tabular file, text/data file and ZIP through both input sources; PDF tool selection into the existing tool flow; multi-file merge/archive; no compatible-tool outcome; local sidecar auth and original preservation. |
| Packaged macOS | Finder Open With association install/update/uninstall behavior, cold and already-running app delivery, several files, dropped window file, Media Toolkit target precedence, permission/access failures, clean signed bundle. |

The approved mock button checker passed before approval. `npm test` passed (1,044 Node tests; 3,410 Python tests, 4 skipped); `cargo test --manifest-path src-tauri/Cargo.toml` passed (324 tests); the file-intake Playwright flow passed in desktop and compact WebKit. `npm run build` produced a signed ARM64 app and DMG; `npm run test:macos-dmg` passed, and the generated `Info.plist` contains all six alternate-rank associations. Notarization was skipped because Apple notarization credentials are not configured. An attempt to inspect the launched app through native accessibility returned `cgWindowNotFound`, so installed Finder Open With event delivery and physical window drop remain manual acceptance checks.

## 12. References

- [Tauri v2 bundle `fileAssociations` configuration](https://v2.tauri.app/reference/config/#bundleconfig) and [`RunEvent::Opened`](https://docs.rs/tauri/latest/x86_64-apple-darwin/tauri/enum.RunEvent.html).
- Current implementation: `src-tauri/src/lib.rs`, `src-tauri/src/workspace_native.rs`, `officekit/engines/engine_file_selections.py`, `app.py`, `index.html`, `src-tauri/tauri.conf.json`.
- Approved product direction: ADR in `docs/ARCHITECTURE.md`; `review/file-open-and-drop/requirements.md`.
