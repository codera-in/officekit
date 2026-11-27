# PDF editing, annotation and DSC signing

Version: 1.0.2 · 2026-10-15 · Status: architecture and UI approved; implementation in review.

## Scope and decision

The owner selected a unified Windows/macOS workspace supporting existing-text/image editing, added content, editable OCR reconstruction, screenshot-style annotations, visual signatures and USB DSC / PKCS#12 certificate signatures. UI approval: “APPROVED”, 2026-10-15. Preserve local-first processing and the current HTML/JS, FastAPI and Tauri architecture. No new frontend framework, remote processing service, database, tenant model or infrastructure.

## Components and controls

One Edit / Annotate mode selector precedes contextual toolbars. Annotate reuses Screenshot Editor's icon order: Select, Freehand, Shapes menu, Highlight, Text, Callouts menu, Eraser; view group contains Pan, Zoom out/in and Fit; history contains Undo/Redo. Add Signature appearance and Sign with certificate to this toolbar. Main/Outer colors and stroke widths appear only for relevant tools. Annotation selector and Delete selected remain in the contextual row. Existing image capture/paste, image-only crop/blur/mask/pixelate/rotation controls stay in Screenshot Editor; no implicit PDF redaction claim.

Edit mode replaces that toolbar with Edit text, Edit images, Add text, Add image and Recognise scanned text, with contextual font, size, fill and image properties. The PDF canvas retains page navigation and thumbnails; zoom/fit controls move into its shared toolbar. Certificate options appear only during certificate signing, releasing canvas width while annotating. The source filename and document overflow own replace/clear. A single bottom dock owns export, signing status and final download; no second signing destination or duplicate export toolbar.

## Engines

1. Bounded document inspection/rendering reuses pypdfium2 and existing preview limits. Introduce canonical unrotated PDF-point coordinates, with explicit crop-box and rotation transforms; all gestures, keyboard placement and exports use the same model. Process PDFium operations in serialized isolated workers, not concurrent calls into a shared document.
2. Content editing uses PDFium object inspection and mutation through supported pypdfium2/raw PDFium APIs. Object handles are server-derived IDs bound to a document revision, never client pointers. Text is editable only after checking encoding/font support; missing fonts require an explicit replacement choice. Shared XObjects are isolated before instance-specific image edits. Complex or unsupported objects fail with a region-specific explanation; no silent white-box overlay masquerading as replacement. Prove round-trip text replacement and image isolation before enabling those capabilities.
3. Annotation DTOs preserve separate editable objects in the session and export native PDF annotations where interoperable; appearances must match the approved preview. Visual signature images are appearances only. Eraser deletes annotations, never original content. Return to Select after placement. Editing/annotation output is a new draft; do not claim original signature preservation during general PDF rewriting.
4. Existing local OCR supplies bounded recognition. Extend it to return region geometry and text rather than only statement-oriented rows. Searchable-layer output leaves visible scans intact. Editable reconstruction requires reviewed region text, erases corresponding scanned pixels in a derived page image and adds editable PDF text; expose font/layout differences and keep a comparison preview. Re-encode derived images so replaced glyph pixels are not retained in that image; do not advertise this operation as comprehensive secure redaction. Avoid destroying a complete page image to correct a single region without review. Unsupported language packs report unavailable.
5. Add pyHanko for incremental certificate signing and verification; PKCS#12 loads only in the signing worker. PKCS#11 uses the vendor's installed library through pyHanko/python-pkcs11. The private token key never leaves the token. Vendor library selection is a native-authorised executable-code boundary, not an arbitrary HTTP path parameter. Pin versions after a Windows/macOS compatibility spike. Do not bundle vendor middleware or promise support for every token. Tokens exposing only proprietary CSP/KSP interfaces require an additional adapter and are reported unsupported by the initial PKCS#11 adapter.

## Sessions, native boundary and secrets

Use existing native picker grants to read originals directly. Desktop API exchanges use the existing per-launch authentication and native-authorisation scheme; never put credentials in URLs. Browser-only previews use bounded explicit uploads, not arbitrary filesystem paths. Server sessions and bounded output artifacts are private, revocable, revisioned and expire after 30 minutes idle; cap at four documents and 256 MiB aggregate derived artifacts. A changed source identity/revision invalidates edits. Cleanup disposes PDF handles, token sessions and temporary derived outputs. Do not copy input folder trees.

Passwords/PINs enter only the one-shot signing request and are never in history, job status, exceptions, telemetry, disk drafts or result metadata. Python cannot guarantee memory zeroisation; worker termination limits lifetime. Do not retry a PIN automatically. Certificate enumeration avoids login where possible; providers requiring authentication are explicitly handled. Do not allow an untrusted page to choose/load a shared library. Native grants bind provider file identity, architecture and owner permission.

There is no new database. These are per-app-process document sessions scoped to the authenticated local desktop instance, not shared SaaS entities. No tenant column, migration or RLS applies. Existing tool history may store the tool shortcut only; no document/certificate/PIN/OCR contents are implicitly persisted.

## Signature sequence and trust

Inspect signature fields and document modification permissions at open. Reject prohibited edits. Existing signed documents open read-only for content editing; no derived unsigned-copy action is exposed. Preserve the original. Append permitted additional signatures incrementally to the exact completed draft, not a PDFium rewrite. Freeze that revision during signing. Cancellation before signing stops work; once the token operation starts do not promise rollback or automatic retry. Verify output before presenting completion. Undo/Redo creates a new authoritative head from an immutable old snapshot under an expected-head check, so subsequent editing and signing work without weakening stale-request protection.

Owner's actual token is HYP2003. Official driver source: https://www.hypersecu.com/india-support (currently reports pending new downloads); nCode's official driver page also lists HYP2003 Windows/macOS packages: https://www.ncodesolutions.com/token-drivers.php. Hardware acceptance requires the appropriate installed vendor middleware and matching CPU architecture; no driver is downloaded or installed automatically by OfficeKit.

Report integrity, certificate chain trust, revocation, timestamp and modification permissions separately. Offline checks do not assert current revocation/trust. Timestamping and online checks require explicit consent per operation and bounded HTTPS clients. Arbitrary service URLs must not become SSRF: block loopback/private/link-local targets, unsafe redirects and DNS rebinding; impose response/timeout limits. Do not hand unchecked URLs to a library's unrestricted fetcher.

## Contract and failure behavior

Feature contract: review/pdf-annotate-sign/API-CONTRACT.md. Stable public errors include malformed/encrypted PDF, stale revision, unsupported font/object, OCR unavailable/limit, missing/incompatible middleware, disconnected/locked token, wrong password/PIN, cancelled operation and failed output verification. Do not echo secrets, full paths or library diagnostics. Jobs expose measured progress or phase/elapsed time, never fabricated percentages. Export/download references point to the same immutable completed artifact.

## Verification and pitfalls

P-070/P-071: form/outline/signature preservation tested explicitly; never inferred from page-copy success. P-016: public parser errors are stable and sanitised. P-159: placement returns to Select. Cover rotated/cropped pages, mixed sizes, shared image objects, embedded/subset fonts, malformed/encrypted PDFs, existing signatures/DocMDP, OCR recognition and extraction parity, incorrect PIN with no retries, disconnected tokens and offline trust. Distinguish unit/API/browser evidence from packaged macOS/Windows and real hardware results. Follow the normal review board and full repository test gates after implementation.

## Implementation sequence

Capability spikes → session/DTO/geometry foundation → editing and OCR → native annotations/shared toolbar → PKCS#12 signing/verification → PKCS#11 native provider integration → packaging and hardware acceptance. These are implementation checkpoints within the chosen unified product, not a phased scope reduction. Product UI is not enabled for an unimplemented capability.

## Sources

- PDFium wrapper/object APIs: https://pypdfium2.readthedocs.io/en/stable/python_api.html
- pyHanko signing and incremental writer: https://github.com/MatthiasValvekens/pyHanko/blob/master/docs/lib-guide/signing.rst
- pyHanko PKCS#11 support: https://github.com/MatthiasValvekens/pyHanko

Architecture agreement: owner said “hld approved”, 2026-10-15. Implementation and hardware acceptance remain separate gates.
