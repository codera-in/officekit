# PDF workspace implementation plan

Version: 1.0.0 · 2026-10-15 · HLD v1.0.1 approved.

## Ownership and interfaces

- `officekit/engines/pdf_editor_models.py`: strict discriminated DTOs, geometry/operation bounds and typed engine result schemas for document, objects, revisions and OCR resources.
- `officekit/engines/engine_pdf_editor.py`: serialized PDFium inspection/rendering/content mutation, annotation appearances, bounded OCR region recognition and reviewed reconstruction. No raw handles reach the client. Source bytes remain immutable.
- `officekit/engines/engine_pdf_signing.py`: pyHanko PKCS#12/PKCS#11 signing, certificate summaries and separate verification statuses; no unapproved network requests, secret persistence or automatic PIN retries.
- `officekit/engines/engine_pdf_workspace.py`: process-local bounded document/revision/artifact/job/provider lifecycle, source identity checking and revision conflicts. One worker serializes PDF processing; provider signing is exclusive. Contract: all resources in feature API-CONTRACT.md.
- `officekit/pdf_workspace_routes.py`, `app.py`: thin typed FastAPI router, native-selection resolution, registered body limits and sanitised failures. POST creates include Location; binary artifacts carry explicit content type/disposition.
- `assets/officekit-pdf-editor.js` and `.css`, `index.html`: mount approved edit/annotate/sign workspace; reuse screenshot toolbar order and shared theme tokens, accessible selected-object tools, pointer/keyboard placement, immutable export/download snapshots and cancellation/status handling.
- Native provider picker command in `src-tauri/src/workspace_native.rs` (and command registration): privileged provider grant; generic read grants never imply executable library-load permission. Main-process authorised registration is the only path for PKCS#11 library loading.
- Registry/search/release-profile files: one canonical PDF workspace tool; aliases for edit/annotate/sign/DSC open the same destination. Private-beta enablement is contingent on complete acceptance, not routing alone.
- `requirements.txt` and sidecar dependency collection: pinned signing libraries, native wheels tested per platform; no vendor middleware bundled.

## Error and state handling

Strict request DTOs reject unknown/nonfinite/out-of-page values. Session resources use opaque IDs, expected revisions and idle expiry; private source/output IDs are never paths. Workers report phase and actual progress when available. Results publish atomically after output validation and budget checks. Stale/missing permissions fail before mutation, secrets are one-shot and omitted from response/history/logs. Cancellation has a commit boundary and never claims reversal of a token action. Signed documents are inspected before edits; general editing cannot silently invalidate an existing signature. Network timestamp/trust controls remain unavailable until safe explicit-consent fetch handling exists, rather than making unchecked requests.

## Meaningful checks and implementation checkpoints

1. Red engine tests for real editable text replacement, image isolation, rotated geometry, annotation output and bounds; capability spikes must pass before frontend enables editing.
2. Red signing tests with generated temporary certificates, real cryptographic verification, wrong password, malformed input, incremental signatures and token adapter boundaries. Real device tests remain an independent Windows/macOS requirement.
3. Red session/API tests for TTL, revision races, input/output caps, source identity, opaque grants, secret exclusion, cancellation and signed-content permission guards.
4. Browser desktop/compact flows for choose → preview → modify → export → read-back, OCR correction → apply, PKCS#12 sign → verify → download, and recoverable missing-token states.
5. Focused coverage and full npm tests, Rust format/tests for native changes, sidecar packaging and installed/hardware checks where available. Review board sign-offs and actual platform limitations are recorded separately.

No commit, PR or release is implied by these checkpoints. Review/contract files are retained as required evidence even though `review/` is ignored by the repository default.
