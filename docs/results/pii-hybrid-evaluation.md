# PII hybrid evaluation report

Corpus manifest version **1.1.0**, SHA-256 `1e3b0d388f3672ba34791e8b3ff445cc1698236702fa66afc3bb4e458781d002`: 40 synthetic document groups, 153 labelled spans, nine languages, and eight template families. Development and held-out splits each contain 20 documents; support is 90 and 63 spans respectively. Template families are isolated across splits. These results are directional evidence from synthetic fixtures, not production recall estimates.

The pooled exact-span baseline reached character coverage 62.2%, missed at least one labelled span in 38/40 documents, and emitted 42.2 false positives per 1,000 words. MaskFlow patterns plus resolver reached 71.4% character coverage, missed 29/40 documents, and emitted 38.3 false positives per 1,000 words. Its exact-span F1 was 0.680 on clean text and 0.566 on OCR-like text. Every result JSON includes exact-boundary metrics, document miss counts, false-positive rates, per-language/entity support, and clean/OCR-like breakdowns.

## Structural detector comparison

| Candidate | Split | Precision | Recall | F1 | TP / FP / FN |
| --- | --- | ---: | ---: | ---: | ---: |
| OfficeKit baseline | Dev | .643 | .400 | .493 | 36 / 20 / 54 |
| MaskFlow patterns + resolver | Dev | .672 | .433 | .527 | 39 / 19 / 51 |
| MaskFlow NER + resolver | Dev | .551 | .422 | .478 | 38 / 31 / 52 |
| OfficeKit baseline | Held out | .733 | .524 | .611 | 33 / 12 / 30 |
| MaskFlow patterns + resolver | Held out | .818 | .714 | .763 | 45 / 10 / 18 |
| MaskFlow NER + resolver | Held out | .657 | .698 | .677 | 44 / 23 / 19 |

## Context model results

The Knowledgator Edge int8 ONNX candidate is English-only per its model metadata. Threshold was selected using development results; held-out was evaluated once at 0.5. The direct candidate uses OfficeKit baseline plus contextual findings and the production span resolver. The combined candidate additionally uses MaskFlow patterns.

| Candidate | Split | Precision | Recall | F1 | TP / FP / FN |
| --- | --- | ---: | ---: | ---: | ---: |
| OfficeKit baseline | Dev, English | .800 | .667 | .727 | 12 / 3 / 6 |
| Direct + context, threshold .5 | Dev, English | .882 | .833 | .857 | 15 / 2 / 3 |
| OfficeKit baseline | Held out, English | .750 | .600 | .667 | 9 / 3 / 6 |
| Direct + context, threshold .5 | Held out, English | .833 | .667 | .741 | 10 / 2 / 5 |
| MaskFlow patterns + context, threshold .5 | Dev, English | .789 | .833 | .811 | 15 / 4 / 3 |
| MaskFlow patterns + context, threshold .5 | Held out, English | .750 | .800 | .774 | 12 / 4 / 3 |

The direct path gains 16.7 percentage points of English recall on dev and 6.7 points held out, below the planned 10-point held-out gate. The combined variant gains 16.7 and 20 points, respectively, with no English held-out precision change; however, that MaskFlow candidate is not integrated into the production scan path. Each English split has only four documents and support of 18/15 spans. Keep the model disabled by default.

## Resolver audit

The evaluator records exact duplicate, nested, and partial overlap pairs, merged components, and likely wrong primary-type overrides in each JSON result. The resolver now prefers an IP address over a broad address label and keeps an explicit international phone span from being relabelled as a nested Luhn-valid card substring. Regression tests cover both cases. On held-out English, the direct model candidate resolved four exact duplicate pairs and one nested pair with zero partial overlaps and zero wrong type overrides. The combined candidate resolved 15 duplicate pairs and five nested pairs, also with zero wrong type overrides. The MaskFlow structural held-out run resolved one previously observed wrong type override to zero.

Python and C++ runtime adapters produced matching resolved candidate metrics at threshold 0.5. Refreshed raw results, including additional development thresholds, are in the adjacent `pii-*.json` files. Stale v1.0.0 candidate outputs have been removed from this report set.

## Runtime and packaging

Resource runs were measured on macOS 27.0.1, Apple arm64, 10 reported CPUs. The C++ daemon was driven from Python 3.14.7 and used ONNX Runtime 1.25.1. Python ONNX long-text scans still exceeded both the p95 and incremental-memory gates: 1.094 s p95 and 574 MB incremental peak across 30 repeated 1,000-word scans. The C++ daemon with four inference threads passed the measured POC limits:

| Measure | C++ result | Gate |
| --- | ---: | ---: |
| Warm 1,000-word scan p95, 30 repeats | 0.408 s | ≤ 1 s |
| Process-tree peak RSS, 1,000-word run | 286 MB total (258 MB incremental) | incremental ≤ 500 MB |
| Model load across five fresh processes | 0.229–0.336 s | ≤ 5 s |
| Model, tokenizer, runtime libraries, daemon | ~86.4 MB | ≤ 200 MB |

The 100-scan short-input thread sweep measured warm p95 of 19.5 ms / 16.3 ms / 15.9 ms at 1 / 2 / 4 threads. Four threads were used for long-document measurements. The 1,000-word run averaged 0.362 s across 30 scans; process-tree CPU total was 44.1 CPU seconds. Resource captures include environment and artifact hashes in `pii-resource-*.json`.

The measured binary/model bundle comprised the 45,820,894-byte ONNX graph, 3,583,593-byte tokenizer, 8,400,272-byte GLiNER library, 28,418,248-byte ONNX Runtime library, and 149,800-byte daemon. Build revisions and reproducible upstream fixes are recorded in `scripts/pii_cpp_runtime/README.md`. The model and binaries are not bundled with the default app.

## Offline integration smoke and decision

With network sockets denied and Hugging Face offline mode enabled, the real C++ route detected a synthetic contextual person value, left it as a possible finding, preserved the source, returned a stable ID on rescan, and removed the selected value on explicit Mask and Redact. TXT, CSV, Markdown, vector PDF, DOCX, XLSX, PPTX, and PNG pathways were exercised. PDF, Office archive, and text outputs were checked for target removal; the regression suite also scans and redacts 10- and 50-page vector PDFs. PNG used supplied synthetic OCR observations and verified pixel redaction, so OCR recognition itself was not validated. Evidence is in `pii-model-smoke-cpp-offline.json`.

The optional C++ route passes the measured package, cold-start, long-text latency, memory, and offline smoke gates. The direct detector misses the held-out recall-lift gate, and the higher-recall combined detector is not the production candidate. Keep the model integration opt-in and disabled by default. Next evidence should evaluate the actual complete production detector on a substantially larger, independently authored corpus and validate packaged cross-platform scan-to-export behavior before reconsidering default enablement.
