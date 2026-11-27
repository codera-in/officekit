# OfficeKit consistent workspace experience

Version: 1.0.2 · 2026-10-13 · Combined mock and architecture approved with "lgtm"; implementation verification remains in progress.

## Scope and decisions

One local-first shell and design system; Home with five deduplicated recent shortcuts plus favorites; shared full-result Copy/Download; editable dual-color annotations; direct original-file processing; recoverable long dictation; native quick access. Use the current HTML/JS, Python and Tauri structure. No new frontend framework, cloud service, database or source-tree cloning.

Approved option: focused Home/tool workspaces with shared adapters. The user approved the complete screens and architecture with "lgtm" on 2026-10-12. A smaller patch leaves inconsistent flows; a larger workspace overhaul adds unnecessary state.

## Component ownership and control migration

AppShell owns actual-height title/notice rows, expanded/collapsed rail and main scrolling. Home owns five recent shortcuts/favorites; All tools retains existing query/category/Gallery/List. Preserve drafts/jobs on shell transitions. Registry-backed result capabilities feed ResultActions and DownloadDialog. Remove old per-format and duplicate result action bars after each migrated tool is verified.

Compute/text, files/batches and canvas/live share fields, buttons, focus, status and results. File selection removes Copy selection to workspace/Selected copies/Clear temporary workspace. Screenshot changes all-settings inspector to contextual controls and top Copy/Download; adds Select/Arrow/Freehand and object deletion. Transcript rows retain Open/Remove and gain full-text Copy/Download. Tray controller invokes existing execution adapters and never routes through main-window activation before dictation/capture.

## Contracts

Feature-local draft contract: `review/workspace-and-annotation-refresh/API-CONTRACT.md`. The root API-CONTRACT.md now records the implemented selection/job routes and typed responses. Active file-tool screens use opaque native grants and process chosen originals directly without input workspace copies.

Native selection is the authority for local filesystem grants. The native shell registers chosen paths with a process-owned backend using a native-only secret distinct from the webview bearer. The webview receives opaque selection IDs, display-safe names, counts and capability metadata, never grant-issuer credentials. A valid webview token alone cannot register arbitrary paths. Scope is the approved selected roots, not the entire disk.

## Data model and isolation

No shared server database, tenants, RLS or AWS topology. All resources belong to this local app process; explicit justification for absent tenant columns. Selection sessions hold random ID, approved roots, granted access, file identities, creation/expiry and active job references. Jobs hold kind, immutable selected scope/options, state, progress, bounded full-result/artifact references and per-item errors. Retention is bounded and sensitive values are not logged or persisted generically.

Expiry: unused selection sessions expire after 30 minutes; active jobs pin necessary references. Reset revokes new access and cancels supported jobs; completed user-owned files remain. App exit releases grants and temporary artifacts. No source-content staging directory. Large report rows may stream to a result-only artifact; bounded memory means not retaining millions of rows in an array. This is not an input clone.

Existing local favorites/history storage remains. New annotation state is session-only unless explicitly saved; no automatic bitmap/history persistence. Existing saved result schemas remain backward compatible. Native quick-access preference stores only explicit compact-metric enablement and navigation preferences.

## Execution flows

File scans enumerate incrementally; hash in 1 MiB chunks; default two content/decode workers, hard cap four; image decoding obeys existing pixel limits. Size/metadata prune duplicate comparisons. Name report/result limits and pagination separately from source byte size. Open file handles and identity checks reduce path races; do not assume path-string validation eliminates replacement races.

Rename creates a complete validated preview, detects conflicts and stale identity, stages names in the original directory and rolls back on failure where possible. Cross-volume moves are not implied. Apply is explicit and mutates originals; recoverable partial outcomes never claim atomic success. Generated split/join/archive outputs go to chosen destinations with exclusive no-replace publication; existing destinations fail closed. Archive extraction holds the authorized parent and creates/cleans only its owned staging directory through descriptors. Cancel never removes completed user-owned outputs.

Result adapters capture immutable typed full snapshots. Copy serializes the full declared scope up to 8 MiB UTF-8; beyond this show a clear oversized-copy state and retain complete Download, with an explicitly labelled summary copy where useful. Download uses existing serializers/capabilities, validating all bounds and CSV formula handling. Native save writes only after destination choice and reports success after close/publication. Missing/partial/stale results preserve clear state and recoverable data. Rename preview and output-grant expiry/consumption rules are fixed in the feature contract.

Annotations hold id/type/geometry, main/outer color, main/outer width, text/font metrics or bounded points. Crop transforms coordinates consistently. Preview and export share semantics, including stroke bounds, text outlines and clipping. Delete removes objects; undo/redo restores state. Source bitmap stays immutable. Fixed blur is bounded; masks are opaque.

Dictation reproduction precedes changing clipboard timing. Separate capture, cleanup, target focus and delivery. Native send-events returns Paste requested until insertion can be verified; preserve complete transcript when status is uncertain. Clipboard restore only while ownership and complete snapshot rules hold. App switches/permissions/timeouts/UTF-8 bounds get distinct recovery.

## Native quick access and metrics

Tauri tray-icon feature is already enabled. Add one template menu-bar icon/native tray menu; Transcribe Start/Stop, Capture screenshot, System stats, Open OfficeKit and Quit. Capture/dialog failures open contextual recovery only when required. Quit resolves active recording/jobs explicitly. No automatic launch-at-login change.

Reuse `/api/system/resources` for CPU/RAM. Extend a versioned metric snapshot for selected volume capacity and network counter-derived rates. Rate sampling requires two monotonic timestamps; the first sample is warming up. Exclude loopback and define interface aggregation/deduplication; prevent negative rates after resets. Stats update every two seconds while visible, no overlapping requests. Opt-in persistent display samples at five-second intervals. Collectors target <1% of one CPU core averaged over 60 seconds and bounded sample state; measure in packaged build, do not promise unmeasured performance. Unavailable metrics show labels. SSD is capacity usage, not activity.

## Pitfalls, validation and rollout

P-081 complete clipboard restore and ownership; P-082 final capture callback; P-152 visible operation errors; P-155 cleanup transport; P-028 file replacement/rollback; P-027 archive symlink race; P-026 rename race; P-150 registry/release count assumptions. Regression tests must preserve each boundary. Release profile allowlists must migrate selection/job routes before old workspace consumers are retired.

Rollout slices: shell → result adapter/representative tools → full registry → transcript copy → annotation model → direct-file bridge/engines → reproduced paste fix → quick access. The approved mock and architecture gate is satisfied. Source and browser evidence remains distinct from installed/native acceptance; implementation is not complete until the ledger records the shipped build and each required manual boundary.
