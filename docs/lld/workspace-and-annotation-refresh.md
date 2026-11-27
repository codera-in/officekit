# Implementation plan

Version: 1.0.3 · 2026-10-21 · Release-profile references removed (S3 commit 3a); 1.0.2 · 2026-10-13 · Combined package approved with "lgtm"; implementation verification remains in progress.

| Slice | Files | Implementation and contract references | Verification |
| --- | --- | --- | --- |
| 1 Shell/Home | `index.html`, `assets/officekit.input.css` | Shared tokens; grid auto chrome; rail preference/drawer; five recents; full views; preserve tool state | Gallery/routing/search regression; no hardcoded counts; focus/zoom/themes |
| 2 Result adapters | `index.html`, existing result export API/engine | Typed per-tool capability matrix; full immutable snapshot serialization; one Copy/Download row; `R-1` | Every result-producing registry entry mapped; no preview truncation; stale inputs, clipboard rejection, CSV safety, formats |
| 3 Native save/copy | `src-tauri/src/lib.rs`, `src-tauri/capabilities/default.json`, `src-tauri/Cargo.toml` if native dialog dependency needed | Await native text/image clipboard; scoped Save As/output grant; `N-1`, `N-2` | Permission failure, cancellation, partial write, output collision, packaged native save |
| 4 Transcript history | `index.html`, history UI tests | Open/Copy/Download/Remove; complete entry values; no extra history dataset | Full Unicode/line breaks, errors, permission rejection, saved-entry removal |
| 5 Annotations | `index.html`, `app.py`, `officekit/engines/engine_screenshot_editor.py` | Extend operation DTOs; object IDs, geometry/styles; outline colors; arrows/freehand; `A-1` | Move/delete/undo, crop-relative geometry, text clipping/font metrics, preview/export pixel fidelity, bounds |
| 6 Selection/job boundary | `src-tauri/src/lib.rs`, `app.py`, new `officekit/engines/engine_file_selections.py`, new `officekit/engines/engine_file_jobs.py` | Native-only registration credentials; opaque session refs; bounded job executor; `F-1`–`F-7` | Arbitrary path rejection, ID expiry/revocation, root scope, races/symlinks, cancellation |
| 7 Direct-file engines | `officekit/engines/engine_workspaces.py`, `engine_file_ops.py`, existing scan/export engines, `index.html` | Reuse engine logic with original scoped paths; streaming scans; rename in-place; split/join/extraction output grants; remove import step | Multi-GB no copies; named memory bounds; rename cycles/rollback; archive traversal; file changes; output limits |
| 8 Contract/release migration | `API-CONTRACT.md` (the release profile and its manifest were removed in S3 commit 3a) | Document implemented selection/job routes; release allowlist/caller migration; retire workspace handlers only after parity | Beta route permissions, native/sidecar smoke, no stale paths/hidden copy fallback |
| 9 Dictation | `src-tauri/macos-dictation.swift`, `src-tauri/src/lib.rs`, existing hotkey tests | Reproduce installed/source mismatch, clipboard race, focus/cleanup failures; `D-1` | Busy targets, UTF-8 limits, target switches, clipboard ownership, uncertain status/full recovery |
| 10 Tray/stats | `src-tauri/src/lib.rs`, `officekit/engines/engine_system_resources.py`, `app.py`, `index.html` | Native menu actions/controller; expand metric snapshot `S-1`; lifecycle/polling prefs | Stop/start, no focus theft, capture cancellation, first rate sample/reset, opt-in polling, platform availability |

## Interfaces and validation

ResultCapability: toolId/resultType, declared copy variants, format IDs backed by serializers, fullSnapshotRef and scope. Existing result DTOs remain the engine contract; adapter is not an unvalidated generic blob. UI statuses: idle, running, partial, ready, failed, cancelled; clipboard/save maintain separate pending/succeeded/failed/cancelled state.

SelectionRef: opaque UUID, safe display labels/counts/access only. Backend SelectionGrant: approved roots, identities and permissions, private to backend/native. Job options are discriminated strict DTOs by kind; file IDs are session-relative identifiers, not arbitrary absolute paths. Native output grants bind one job and an unused destination; publication is exclusive and refuses existing paths. Direct-file route responses use validated DTOs.

AnnotationOperation: discriminated crop/blur/mask/text/highlight/ellipse/rectangle/arrow/freehand. Initial limits retain 50 operations, ≤32 KiB encoded operation JSON and current pixel/work caps; each freehand ≤512 points and aggregate ≤1,024, further constrained by byte limit; main/outer widths 1–32 image px with expanded clipping bounds; text remains bounded to 200 chars until multiline has separate accepted semantics. Unknown fields/colors/nonfinite coordinates reject. DTO/client parity and boundary tests precede implementation.

Clipboard text is capped at 8 MiB encoded UTF-8. Oversized results retain complete Download and show a visible explanation instead of truncated Copy; optional Copy summary is explicit. Rename previews expire after five minutes, bind immutable mapping/identities and are consumed by an attempted apply; output grants expire after ten unused minutes, bind destination/kind and are consumed by one accepted job. Directory extraction traverses a private staging directory relative to held descriptors and removes it only while its identity still matches. Contract resource ownership/recovery semantics are authoritative.

MetricsSnapshot v2: capturedAt/sampleAge, nullable metric values with availability reasons, CPU percent, RAM totals/use, volume label/used/total bytes, network up/down bytesPerSecond and interval. Missing values never coerce to zero. Network counters remain local, not device telemetry.

## Checkpoints

One reviewable commit per slice with Conventional Commit prefix. Before each production UI slice record approved screen/controls; after it compare complete screens. Generate a result coverage matrix from actual registry and manually assess representations. Do not assert completion until every capability row and regression is checked. Update versioned docs with matching history rows when implementation changes contract details. Finish with /se-review and relevant full/package checks; this plan does not claim those checks have run.
