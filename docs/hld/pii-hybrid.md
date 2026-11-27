# Hybrid local PII detection

Version: 1.0.7

## Problem and scope

The current local PII scanner detects structured values with regexes and format checks but has weak contextual recall for names, addresses, and less structured identifiers. This design combines the existing checks with one pinned local neural recognizer and a deterministic span resolver. It includes corpus evaluation and end-to-end redaction verification. It does not claim complete discovery or regulatory compliance.

## Current state

- `PiiRedactionEngine.scan` dispatches text files to `_find_matches`, OCR files to `_matches_in_ocr`, PDFs to `_scan_pdf`, and Office archives to `_scan_office_archive`.
- `redact` calls `scan` to validate selected IDs and then performs format-specific detection again. PDF redaction scans again as well.
- `_find_matches` creates stable IDs from group, type, offsets, and value. Existing OCR/PDF/Office code carries boxes, page numbers, and archive group identity.
- The public match DTO is `{id,type,label,confidence,value,location}`. The existing UI supports generic match rows and has no new controls in this design.
- The contextual PII model remains opt-in and is not included in the default sidecar. The shipped scanner also adds dependency-free English document cues for top-line all-caps names, labeled person and organization fields, company suffixes/domains, and school terms. These are possible, unchecked review candidates, not model detections. Optional model findings for usernames and IP addresses are also reviewable, unchecked candidates.
- After a copy is created, the UI offers download and image-copy actions. Image outputs can continue into Screenshot Editor; non-image outputs explain that the editor needs a captured page image. The supported input extensions are listed explicitly before file selection.

## Contract surface

No route, request, or public response field changes. `/api/privacy/pii/scan` continues to return the same match fields; `/api/privacy/pii/redact` accepts IDs from a fresh scan, preserves the original, defaults to partial Mask, and supports full Redact. Full recognizer evidence and scores stay inside the engine. The user-approved review hint is encoded in the existing label for possible context matches as “· Context match”; the UI renders it as an amber badge. Download names retain the output format extension even when the native save dialog returns a path without one.

## Approved result-flow UI

The user approved the reviewed post-processing direction with “lgtm” on 2026-10-17. The PII result lists the generated copy and provides download plus a manual annotation handoff for image outputs. Other output types explain that the Screenshot Editor needs a page captured as an image. Supported input formats and the 64 MiB limit are stated before file selection. The temporary HTML mock and preview were removed after approval as required by the repository workflow.

## Flow

1. Each extracted text group is bounded and passed to the structural detector and dependency-free English document cues. If `OFFICEKIT_PII_CONTEXT_MODEL` points to a local model directory, it is also passed to the cached contextual adapter. `OFFICEKIT_PII_CONTEXT_RUNTIME=cpp` selects the persistent local GLiNER.cpp daemon; otherwise the Python ONNX adapter is used.
2. Adapter output is validated against the original text and normalized into internal spans with evidence source, score, entity mapping, validation kind, and coverage bounds.
3. The resolver collapses exact duplicates, selects a deterministic primary classification, and retains the union of sensitive coverage for nested and partial overlaps. It uses entity specificity to prefer IP addresses over broad address labels and to keep explicit international phone spans from being relabelled by nested card-like substrings.
4. Stable IDs are computed from canonical group identity, resolved type, canonical covered offsets, and original source text so scan and redact rescans agree.
5. Public projection removes internal evidence. Existing review and redaction paths use canonical spans and retain PDF/image geometry.
6. Missing or invalid optional model assets produce a deliberate fixed failure for an explicitly model-enabled run. C++ runtime startup and inference have bounded timeouts and terminate a stuck process. The model path is local-only; scan never downloads assets. The contextual model is disabled by default because the direct baseline-plus-model path missed the held-out recall gate. English document cues run by default and remain review-only.

## Entity precedence

Checksum-valid structural findings outrank format/context recognizers; format-specific validated findings outrank neural classifications. Within equivalent validation/source strength, entity specificity breaks ties. Neural contextual spans fill gaps. Checksum validation means mathematical consistency only. Exact duplicates keep all evidence. Nested spans choose one classification and retain coverage union. Partial overlaps retain coverage union and record conflict internally. Adjacent spans are separate unless entity mapping says otherwise. Tie-breaking is deterministic and audited against labelled spans.

## Resource and privacy boundaries

Respect current input, text, archive, match, PDF-page/pixel, image-pixel, and output bounds. Model load is lazy and cached once per process. Set inference thread count explicitly (1–4); both adapters window long text. Use no model download or remote inference from scan/redact. Do not log text, entity values, or model output. Keep model files and compiled binaries out of source control; the POC report records exact artifact hashes and sizes.

## Pitfall coverage

There are no active PII-specific entries in `docs/PITFALLS.md`. The known repeat-scan/ID coupling is addressed by canonical span IDs and explicit scan/redact tests. OCR and archive geometry are retained through resolution.

## Acceptance evidence

See `review/pii-hybrid/requirements.md`, `docs/lld/pii-hybrid.md`, the evaluation manifest/results, focused tests, full test gate, and the final candidate decision report. The expanded corpus contains 40 synthetic documents across nine languages and eight template families. Current evidence is insufficient to enable the model by default.
