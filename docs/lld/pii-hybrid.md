# Hybrid local PII detection implementation plan

Version: 1.0.6

| Path | Responsibility | Verification |
| --- | --- | --- |
| `officekit/engines/engine_pii_redaction.py` | Always add bounded English document-cue candidates; optionally add local contextual-model spans; preserve current extraction geometry and public DTO. | Engine tests for text/OCR/PDF/Office, stable scan/redact IDs, source preservation. |
| `index.html` | List supported input formats; show post-output download and manual image-editor handoff; preserve the output extension when response headers are incomplete. | UI contract tests for support copy, filename fallback and image/non-image editor paths. |
| `src-tauri/src/workspace_native.rs` | Restore the suggested extension if the native save dialog returns a destination without one. | Rust unit test covers missing, present and absent suggested extensions. |
| `officekit/engines/pii_context_detector.py` | Pinned, lazy local contextual model adapter; validate output type, offsets, entity mapping, score and bounded span count; enforce startup/inference timeouts for the C++ protocol. | Fake adapter contract tests plus stuck-startup/inference regressions and real pinned-model smoke/evaluation. |
| `scripts/pii_gliner_cpp_daemon.cpp` / `scripts/pii_cpp_runtime/CMakeLists.txt` | Optional persistent, offline GLiNER.cpp/ONNX Runtime daemon for lower resource use; built separately and selected by runtime env. | Native build and real-model smoke with network denied; thread and long-text process-tree resource measurements. |
| `officekit/engines/pii_span_resolver.py` | Deterministic duplicate/overlap resolution, specificity rules and canonical identities. | Unit tests for checksum/format priority, IP/address and phone/card specificity, exact duplicate, nested, partial, adjacent, tie and invalid spans. |
| `tests/fixtures/pii-eval/manifest.jsonl` | Synthetic labelled document groups across nine languages, clean/OCR-like text, development/held-out splits. | Manifest validator checks offsets, values, language/entity coverage, family split isolation. |
| `scripts/pii_eval.py` | Run baseline and hybrid detectors on same records; emit machine-readable metrics and error examples. | Deterministic fixture run; report aggregates recomputed from raw JSON. |
| `tests/test_pii_hybrid_unittest.py` | Unit and redaction regression tests for adapter/resolver integration. | Focused pytest with coverage on changed engine modules. |
| `requirements-pii-eval.txt` (if needed) | Pinned evaluation-only candidate dependencies, separate from default app unless packaging passes. | Clean environment install and recorded wheel sizes. |
| `scripts/build-backend-sidecar.mjs` (only if candidate passes) | Explicit offline model/runtime collection. | Sidecar contents/hash/size and network-denied scan smoke. |
| `docs/PII-LOCAL-DETECTION-POC.md` | Record completed stage evidence and limitations. | Cross-check metrics, hashes, resource report and final decision. |

## Error handling

Malformed model results, invalid offsets, unsupported labels, scores outside `[0,1]`, timeouts, and resource overages are rejected before they can become selectable spans. The baseline remains independently testable. Model state is explicit: disabled, ready, unavailable, or failed; no invalid output is silently converted to no matches.

## Checkpoints

1. Candidate metadata and corpus/evaluator.
2. Resolver and adapter contracts.
3. Engine integration and selected-output regressions.
4. Held-out accuracy/latency/resource report.
5. Packaged/offline decision and final recommendation.

## Integration status

The contextual-model path is opt-in through `OFFICEKIT_PII_CONTEXT_MODEL` and only loads from the configured local directory. The bundled default sidecar does not include the PII model or GLiNER runtime. Model and English document-cue findings are returned as possible matches with the approved label hint and remain unchecked. The English cues are part of the default local scanner and need no model dependency.

The optional C++ route also requires `OFFICEKIT_PII_CONTEXT_RUNTIME=cpp`, a locally built daemon selected through `OFFICEKIT_PII_CONTEXT_CPP_BINARY`, and the local model directory. Startup is bounded to 30 seconds and each request/response exchange to 60 seconds; timeout terminates the child and fails the scan explicitly. Username and IP-address model candidates are accepted by the backend and UI DTO allowlists, then remain unchecked possible matches. The pinned upstream source revision, licensing, and build fixes are recorded in `scripts/pii_cpp_runtime/README.md`. The English-only direct model candidate missed the held-out recall-lift target, so runtime packaging remains disabled by default.
