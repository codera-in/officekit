# Shared file intake for window drop and Finder Open With — LLD

**Version:** 1.0.8 · 2026-10-25 · Record review fixes, pre-stream validation, and regression cases. Earlier: 1.0.7.
Parent contract: `docs/hld/file-intake.md` (all API work implements §7).
Requirements: `review/file-open-and-drop/requirements.md`.

Status: Implemented; application suites and packaged DMG smoke pass. Native installed Finder delivery and physical drop remain manual acceptance.

## 1. File-by-file change map

| File | Planned change | Contract / HLD reference |
| --- | --- | --- |
| `src-tauri/src/lib.rs` | Manage an eight-selection FIFO queue; route window drops after Media Toolkit target precedence; handle `RunEvent::Opened { urls }`; register inputs natively; expose pending/ack commands and emit path-free `officekit-file-intake` notifications. | HLD §§6–8; native event and queue DTO in §2. |
| `src-tauri/src/workspace_native.rs` | Factor path validation/selection registration so general file drops reuse native grant, canonical path, regular-file/no-link/special-file/duplicate/batch checks. Reject folders. Existing Media Toolkit behavior stays on its current function and bound. | HLD §§4, 6, 8. |
| `src-tauri/tauri.conf.json` | Add only the extension/type union explicitly declared ingestible by at least one capability. Set Finder association to alternate rank; do not claim default ownership. | HLD §§2, 7, 11. |
| `src-tauri/tauri.macos.conf.json` | Add any macOS-only document type/rank override required by Tauri's generated Info.plist. Ensure the base configuration and platform override merge as expected. | HLD §§2, 7, 11. |
| `officekit/engines/engine_file_selections.py` | Add bounded lookup of one `SelectedFile` by opaque file ID within a live selection, preserving existing walk cap and identity signature; do not accept paths from callers. | `API-CONTRACT.md` 1.91.2; HLD §§7–8. |
| `app.py` | Add authenticated binary content and subset routes; validate file identity before returning the bounded selection/file-ID stream, derive subsets from a live selection only, enforce 64 MiB upload ceiling, safe filename, fixed errors, no-store/nosniff, and an explicit binary OpenAPI response. | `API-CONTRACT.md` 1.91.4; HLD §7. |
| `API-CONTRACT.md` | Keep selection content stream complete: method, URL, empty request DTO/query, declared binary OpenAPI response, success headers, 401/403/404/413/422 and local non-tenant justification. Any changed contract increments its version/history. | API contract table, HLD §7. |
| `assets/file-intake-capabilities.js` (new; loaded after routing definitions) | Add release-filtered type/count/size capability rows and build-specific Media Toolkit operations; search/group rows and connect existing native-selection or bounded upload adapters. | HLD §§3, 5. |
| `scripts/build-ui-assets.mjs` | Copy the new capability asset into `dist-ui/assets` as part of the authoritative UI build. | HLD §11. |
| `index.html` | Add the Open files view, per-file checkboxes, search, task groups, count/size states, one Continue action, startup queue drain, release filtering and adapter dispatch. Reuse existing tool routing. | Approved mock decision; HLD §§3, 5–9. |
| `dist-ui/index.html` | Generated from the authoritative `index.html` by the existing build task; never hand-edit. | HLD §11. |
| `assets/file-intake-capabilities.js` | Load the shared chooser; capability rows are exercised by the WebKit intake scenario. | HLD §§3, 5, 9. |
| `tests/test_direct_file_api.py`; `tests/test_file_selections_unittest.py` | Validate authenticated content reads, selection-ID-only subsets, safe headers, identity checks, and path-free metadata. | API contract; HLD §§7–8, 11. |
| `src-tauri/src/workspace_native.rs` unit tests; `src-tauri/src/lib.rs` native tests | Validate selection bounds, local URL parsing, queue capacity/acknowledgement, display DTO privacy, and Media Toolkit precedence. | HLD §§6, 8, 11. |
| `ui-tests/file-intake.spec.mjs` | Desktop/compact WebKit integration: PDF candidate list, explicit subset rules, asset load, destination handoff, and cleanup through the local sidecar. | HLD §§10–11. |
| `npm run build`; `npm run test:macos-dmg`; generated app `Info.plist` inspection | Build the signed app/DMG, exercise the packaged sidecar, and verify Alternate-rank file associations. Installed Finder delivery and physical drop remain manual acceptance. | HLD §11. |
| `docs/TOOL-GUIDE.md` | Document intake/capability coverage and evidence after implementation. Do not claim packaged/release verification before those checks pass. | HLD §§5, 11. |
| `docs/VERSION-HISTORY.md` | Append version transitions for every versioned doc changed in each checkpoint. | House rule. |

The selection routes currently live in `app.py`; implementation should keep the content route there beside their existing lifecycle. The lookup helper belongs to `engine_file_selections.py`, next to the identity-bound `open_file` method.

## 2. Interfaces and DTOs

### Capability entry

```ts
type FileIntakeCapability = {
  tool_id: string;
  accepted_kinds: string[];
  extensions: string[];
  root_kind: 'file';
  min_files: number;
  max_files: number;
  same_kind: boolean;
  subset_allowed: boolean;
  max_file_bytes: number;
  max_total_bytes: number;
  prerequisites: Array<{ id: string; label: string; check: 'user_confirmed' | 'destination_validates' }>;
  group: 'edit_secure' | 'pages' | 'extract_convert' | 'inspect_optimize_package' | 'images' | 'data' | 'media' | 'files';
  label: string;
  description: string;
  search_terms: string[];
  sort_order: number;
  adapter: 'upload_file' | 'native_selection';
};
```

Every `tool_id` must exist in the live tool catalogue, resolve through `officekitToolDestination` (core or registered extension slice), and be authorized by the ready release profile. Every capability carries explicit positive `max_file_bytes` and `max_total_bytes` copied from its destination contract; do not interpret a missing or zero limit as unbounded. `subset_allowed` defaults false and is true only for a destination with a tested subset flow. `user_confirmed` means the user must explicitly provide/confirm a value inside the existing tool; it does not collect or retain secrets in intake. `destination_validates` is descriptive, not a pre-validation claim.

### Native intake DTOs

```ts
type FileIntakeSource = 'window_drop' | 'finder_open_with';

type FileIntakeItem = {
  intake_id: string;       // opaque UUID generated in native process
  selection_id: string;    // opaque FileSelectionStore ID
  source: FileIntakeSource;
  display_names: string[]; // basename only; max 30
  files: Array<{ id: string; name: string; size_bytes: number; extension: string | null }>;
  created_at: number;
};

type FileIntakeNotice = { intake_id: string };
type FileIntakeAck = { intake_id: string };
```

Native queue entries retain paths internally until selection registration succeeds. `FileIntakeItem`, `FileIntakeNotice`, API responses, UI state, error DTOs, and logs contain no absolute paths. `files` is the selection's exact file manifest. File count and display strings are bounded and validated before emission.

### Native command contract

| Command / event | Input | Output | Rule |
| --- | --- | --- | --- |
| Tauri event `officekit-file-intake` | `{ intake_id }` notice | none | Wake-up only; carries no paths or file bytes. |
| `file_intake_pending` | none | `FileIntakeItem[]` (maximum 8 batches, 30 files each) | Returns registered, unacknowledged items in FIFO order. Repeat reads are safe. |
| `file_intake_ack` | `{ intake_id }` | `{ accepted: true }` or fixed error | Removes that pending item only after the UI accepts it into the Open files view; idempotent for an already-acked ID. |
| `file_intake_release` | `{ selection_id }` | `{ released: true }` | Revokes/releases the selection through the existing local API. Must not accept paths. |

Native command registration must be included in the same `invoke_handler!` build as current workspace commands. The UI installs its event listener before its first pending drain. Event delivery is advisory; the pending command is the source of truth.

### Content stream

`GET /api/file-selections/{selection_id}/files/{file_id}/content` is the route row added to `API-CONTRACT.md`. It has no body/query DTO. It returns a bounded `application/octet-stream` stream with a safe `Content-Disposition` filename, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`, declared as a binary OpenAPI response. Require the desktop app bearer; validate UUID IDs; resolve only through the live selection manifest. Open and validate the descriptor inside the route error boundary before returning the stream, then stream bounded chunks. Map missing/expired to 404, missing app auth to 401, unauthorized native state to 403, size >64 MiB to 413, and identity/open validation failures to 422 with a fixed public message. The path never appears in the URL or response.

## 3. Catalog matching rules

1. Wait for the existing release client to reach `ready`. Never use a fallback list on failure. Filter records by `tool_id` in verified `tool_ids` before search or display.
2. Derive each selected item's extension from its safe name. Unknown extensions remain unknown. A recognized extension adds candidate tool IDs; content parsing stays with the selected tool. If known signature and extension differ, surface the existing file-type mismatch information or a generic “type needs checking” note; do not automatically redirect to a guessed tool.
3. A capability is a normal enabled candidate only when every included file/root is in its declared kind/extension, file count is within min/max, and both per-file and aggregate byte limits pass.
4. If a capability matches type but the selection is below `min_files`, keep it as a disabled row with an exact “needs N more …” message. Above `max_files`, it is not a candidate; show a concise count message in the selection status if it prevents all actions.
5. For a mixed selection, require `same_kind` contracts to match all files. A capability may opt into a compatible subset only if its metadata explicitly declares `subset_allowed`; absent means false. No implicit omission.
6. Content prerequisites are descriptive in intake. “Known PDF password” is a user-supplied input in Unlock PDF; selectable text/table recognition and supported statement layouts are validated by their destination. Do not inspect file contents or promise extraction success in the chooser.
7. Group enabled and needs-more choices, then filter both group labels and searchable terms. Search has deterministic case-insensitive matching; no scoring/judgment model.
8. Preselect first enabled candidate using declared stable `sort_order`. If there is no enabled candidate, no radio is selected and Continue is disabled.
9. Continue verifies selection still exists, profile remains ready and authorized, and capability still matches. It invokes the existing destination's setup. Failure clears selection-specific navigation and presents a safe message.

## 4. Intake queue state machine

```text
RECEIVED
  ├─ invalid/over-bound ───────────────> REJECTED (fixed status; no partial selection)
  └─ validated local roots ────────────> QUEUED
QUEUED
  ├─ sidecar unavailable ─────────────> QUEUED (bounded retry while startup is active)
  ├─ queue full ───────────────────────> REJECTED (newest batch; visible overflow status)
  └─ POST /api/file-selections 201 ───> REGISTERED
REGISTERED
  ├─ UI not ready ────────────────────> REGISTERED (retained for pull drain)
  ├─ event signal ────────────────────> REGISTERED (signal does not consume)
  └─ UI accepts and acks intake_id ───> ACKED (selection remains leased by chooser)
ACKED
  ├─ Continue ────────────────────────> DESTINATION (selection ownership transfers)
  ├─ cancel/remove-last-file ─────────> RELEASED
  └─ expiry/app exit ─────────────────> EXPIRED
```

Use an in-memory FIFO capped at 8 batches and 30 regular file paths per batch. Preserve path order. Reject duplicates within a batch. One batch registers atomically; if any path is invalid/unreadable, reject the batch instead of silently dropping it. Queue overflow rejects the newest batch and retains an overflow notice for the UI. Keep `intake_id` stable for retries so duplicate notifications never create duplicate selections. Show one active batch; when that chooser completes or cancels, drain the next registered batch in FIFO order. Retain the current 30-minute selection TTL; `FileSelectionStore` prunes expired selections. The chooser explicitly releases canceled/removed selections. After Continue, the destination owns cleanup using its existing lifecycle. App exit clears in-memory queue state and selection store as it does today.

## 5. Existing-tool adapters

### `upload_file`

For existing browser `File` destinations, fetch each selected file's content subresource with the desktop bearer, verify HTTP status, `Content-Length` when present, actual blob length and declared capability limits, then construct a browser `File` using the safe manifest `name` and expected MIME hint. Pass it to the same function used by the current file picker. Do not duplicate the tool's UI validation or API request. For multiple files, preserve manifest order and fail the adapter atomically if any file cannot be materialized.

### `native_selection`

For file jobs/archive/file-info workflows that already consume a `selection_id` or opaque item IDs, pass these IDs through the existing native selection API. Do not download/re-upload bytes. Folder-root workflows remain on their existing folder picker and are not destinations for this file intake.

Adapters are mapped by capability record and tested against the destination's existing setup signature. Any destination with neither an adapter nor a resolvable `officekitToolDestination` entry cannot appear in the catalog.

## 6. Error handling and atomicity

| Error | Layer | Contract |
| --- | --- | --- |
| More than 30 roots, repeated path, unsupported URL, invalid/special/symlink path | Native | Reject whole batch, no partial `/api/file-selections` creation; safe fixed summary. |
| Root missing or permission lost before registration | Native/API | No selection; “File unavailable or access was denied. Reopen it in Finder and try again.” |
| Sidecar startup timeout/temporary API error | Native queue | Retain bounded batch while backend starts; on terminal startup error surface fixed status, clear raw paths. |
| 8-batch queue overflow | Native queue | Reject newest whole batch; preserve current queue; report that some files could not be queued. |
| Expired/revoked selection or unknown file ID | API/UI | 404; return to intake error state; do not try an absolute path fallback. |
| >64 MiB content stream used by `upload_file` adapter | API/UI | 413 and adapter refusal; selection-native destinations may remain if their declared bounds permit. |
| File identity changed/symlink swap during read | API | 422 fixed “Selected file changed; select it again”; close stream; never emit partial attachment as success. |
| Release profile unavailable or tool removed during startup | UI | Clear queued navigation/candidates; show the existing unavailable-profile state, no development fallback. |
| Destination rejects PDF/input/password/layout | Destination | Existing tool-specific safe error/review behavior remains in control. |

## 7. Test plan hooks

### Rust/native unit tests

- `file_intake_accepts_ordered_unique_regular_files_within_30` and rejects 31 without creating a partial selection.
- `file_intake_rejects_duplicate_symlink_special_and_missing_roots`.
- `file_intake_rejects_folder_roots`.
- `finder_open_accepts_local_file_urls_only_and_preserves_order`.
- `file_intake_queue_is_bounded_fifo_and_acknowledges_by_selection_id`; `drop_and_finder_open_with_share_the_pending_startup_queue` exercises source labeling, FIFO pending delivery, and acknowledgement for both native intake sources.
- `file_intake_notice_is_not_authority_and_pending_drain_is_idempotent`.
- `file_intake_waits_for_backend_and_webview_readiness_without_losing_cold_launch`.
- `file_intake_event_dto_never_contains_absolute_paths`.
- `media_target_drop_keeps_priority_and_does_not_enqueue_shared_intake`.

### API/Python tests

- `test_file_selection_content_requires_app_bearer` and `test_file_selection_content_refuses_unknown_or_expired_ids`.
- `test_file_selection_content_streams_manifest_item_with_safe_headers_and_name`, `test_file_intake_content_errors_are_mapped_before_streaming`, and `test_file_intake_content_openapi_declares_binary_success`.
- `test_file_selection_content_enforces_64_mib_limit_without_partial_success` (exact-boundary and one-byte-over cases).
- `test_file_selection_content_uses_no_follow_identity_check` (symlink substitution, replacement before open, in-place mutation during stream).
- `test_file_selection_content_rejects_file_id_outside_selection` and `test_file_selection_content_never_accepts_path_input`.
- `test_file_selection_content_expiry_and_release_stop_subsequent_reads`.

### UI/catalog tests

- Catalog schema shape, duplicate IDs, tool registry/search existence, destination existence, and no unsupported Open With extension.
- Development/private-beta profiles show exactly their compatible declared tool IDs; loading queues only; unavailable clears; no fallback route.
- One PDF shows PDF-specific entries (including separate PDF operations and Create ZIP); a second PDF enables Merge; a mixed PDF/image list excludes PDF-only actions but keeps ZIP when both types are accepted.
- Search finds “annotate”, “extract text”, “merge”, “zip”, and “checksum”; group collapse and empty search are accessible.
- Known-password/selectable-text/support-layout prerequisites remain descriptions, not automatic parser success claims.
- File remove, cancel, expiry, mismatch, unsupported type and Continue route; source bytes remain unchanged.
- Assert no more than three visible action buttons in before-selection, selected, no-tools, error, and scrolled/result states; mock itself passes `scripts/check-mock-buttons.mjs`.

### Desktop and package acceptance

- Desktop/compact real-sidecar flow opens PDF, image, CSV, JSON, ZIP and audio through native drop; includes multi-file PDF merge and ZIP create; verifies the expected destination and source preservation.
- Finder Open With installed-app flow for cold launch, already-running app, 2+ selected files, and user cancellation; verify macOS Info.plist registration after build/install/upgrade.
- Drop onto a registered Media Toolkit target and assert original preset-zone selection/event is unchanged; drop onto other app-window areas and assert shared intake appears.
- Verify restricted/private beta shows only allowed tools and a missing/unreadable profile never reveals development choices.
- Verify lost permission/disappearing file and >30-file selection failures render safe errors without host paths.

## 8. Checkpoint plan and implementation gate

Implementation is split only after HLD agreement:

1. **Contract + queue** — confirm/update API contract; implement capability schema/tests and native queue/path registration with Rust/API tests. Checkpoint commit: `feat(file-intake): queue native file selections`.
2. **Chooser + adapters** — add capability catalog, Open files view, API content adapter, destinations, cleanup, and UI tests. Checkpoint commit: `feat(file-intake): route files through compatible tools`.
3. **macOS association + installed acceptance** — add generated document association configuration, build/install, verify Finder behavior and app packaging. Checkpoint commit: `feat(tauri): add OfficeKit Open With associations`.
4. **Review/evidence** — update Tool Guide/PRD/version history with measured evidence, run `/se-review`, close findings, then focused and full project verification.

The mock button checker passed before approval. `npm run build:ui` generated `dist-ui`; `cargo fmt` formatted native changes. Application tests, packaged Finder registration, real drop/Open With acceptance, Tool Guide updates, and the review board remain pending.
