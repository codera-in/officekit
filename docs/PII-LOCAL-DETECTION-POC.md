# Global Local PII Detection POC

## Current POC status (2026-10-17)

The hybrid adapter/resolver and opt-in local-model integration are implemented. The adapter is disabled unless `OFFICEKIT_PII_CONTEXT_MODEL` points to a local model directory. The Python ONNX route exceeded memory limits on long text; the optional offline GLiNER.cpp route passed measured latency, memory, package-size, and offline smoke gates. The direct baseline-plus-context path did not meet the held-out recall-lift target, and the stronger MaskFlow-plus-context candidate is not integrated into the production path. The product now also runs dependency-free English document cues for labeled people and organizations, company suffixes/domains, top-line all-caps names, and school terms; these appear as possible, unchecked review candidates across supported text extraction paths. The model remains disabled by default. See the [evaluation report](results/pii-hybrid-evaluation.md), machine-readable results under `docs/results/`, and tests for exact evidence and limitations. The synthetic corpus is small and does not establish production or multilingual recall.

## Goal

Measure whether adding local contextual PII detection improves OfficeKit's global document scan and redaction flow while meeting agreed CPU, latency, memory, offline, and installer-size budgets. The POC makes no claim of complete discovery or regulatory compliance.

## Current state and integration points

- `officekit/engines/engine_pii_redaction.py` extracts/scans text using regular expressions and format-specific validation. It currently labels findings `high` or `possible` using fixed rule classifications.
- `officekit/engines/engine_rapidocr.py` performs local OCR with bundled RapidOCR ONNX models. Text from images and scanned PDF pages is currently grouped by OCR line; selectable PDF text is also scanned line-by-line.
- `PiiRedactionEngine.redact()` rescans to validate selected IDs, and format-specific output paths may perform detection again. Measure the full user flow and detector call count, not only one model inference.
- `requirements.txt` already pins ONNX Runtime. The sidecar build explicitly collects RapidOCR models/data; any PII model, tokenizer, and runtime assets need equally explicit, pinned packaging.
- Preserve the public match fields (`id`, `type`, `label`, `confidence`, `value`, `location`), deterministic selection IDs, source-file preservation, review-before-redaction, partial Mask default, and full Redact behavior.

## Candidates

Compare these configurations using the same extracted text and common entity mapping:

1. Existing OfficeKit detector as the baseline.
2. Baseline plus MaskFlow international recognizers; include its India pack as a regional add-on measurement, not as the global detector.
3. Baseline plus a pinned multilingual neural model. Start with Fastino GLiNER2 PII and BardsAI multilingual ONNX; include Knowledgator Edge as a compact English/coverage comparator. Evaluate the English Ai4Privacy ModernBERT model only for English, since its model card says it is fine-tuned exclusively on English.
4. Baseline plus the best global neural candidate plus the compatible international structural recognizers. Measure the combined footprint and accuracy.

Record exact model repository, revision/hash, license, tokenizer, quantization, runtime, artifact sizes, and language claims for every candidate. Do not treat advertised latency or benchmark scores as OfficeKit results.

## Global evaluation corpus

Build a synthetic, manually reviewed and labelled corpus with document templates, not just isolated sentences. Keep related templates and paraphrases in one split to prevent leakage. Use a development split for threshold selection and a held-out split for final comparisons.

Cover English, Spanish, French, German, Portuguese, Arabic, Hindi, Chinese, and Japanese. Include representative regional names, addresses, phone formats, government/tax identifiers, banking identifiers, email/IP/username patterns, dates, and false-positive controls such as order IDs and timestamps. Mark a language/entity cell unsupported when a model has no credible coverage evidence rather than inferring global capability from a multilingual label.

Include clean text and OCR-derived text separately. Add fixtures for TXT/CSV/Markdown, vector and scanned PDFs, images, DOCX, XLSX, and PPTX. Include tables, wrapped/multiline values, split text runs, mixed scripts, OCR noise, and 1-, 10-, and 50-page PDFs. Keep test documents within the engine's current input, text, page, pixel, match, and output bounds.

## Priority span resolution

Keep evidence and coverage as separate concerns. A resolved finding should retain source recognizers, confidence/evidence, and validation kind internally while presenting a single review item for the same value.

1. **Checksum-validated structural spans:** highest classification priority when a defined checksum passes (for example, Luhn, IBAN mod-97, or Aadhaar Verhoeff). A checksum establishes mathematical consistency, not that an identifier was issued or belongs to a person.
2. **High-specificity structural/format spans:** prefer country- and entity-specific recognizers over generic model labels when their format and applicable context checks pass. Track checksum, format, registry, and context validation separately; MaskFlow's `validated=True` can represent checksum or format validation.
3. **Neural contextual spans:** fill unstructured gaps such as names, addresses, and context-dependent identifiers. Preserve model offsets and scores for user review.

Resolution rules: collapse exact duplicate spans and retain all evidence; for nested spans, prefer the stronger entity classification while retaining the union of sensitive character coverage; for partial overlaps, preserve the union of coverage and record the conflict; do not merge adjacent spans unless the entity mapping explicitly supports it. Tie-break deterministically so rescans produce stable IDs. Test false priority overrides as well as duplicate removal.

## Measurements

### Detection quality

- Per-language and per-entity precision, recall, F1, and support counts.
- Exact-boundary span score and sensitive-character coverage.
- Documents with at least one missed labelled span.
- False positives per 1,000 words and review items per document.
- OCR and clean-text results reported separately.
- Combined results before and after span resolution, including duplicate count, overlap count, and incorrectly overridden spans.
- For selected matches, verify the final Redact output has no extractable target value; separately verify partial Mask preserves only its specified hints.

### Efficiency

Measure extraction/OCR, model cold load, first detection, warm detection, span resolution, export, and total scan-to-export independently. Report wall-clock median/p95, words/second, pages/second, process-tree peak RSS, CPU time, and model/dependency/installed-app/installer size delta. Measure one, two, and four inference threads; run 30 warm repetitions and at least five cold process starts on documented hardware. Run 100 consecutive scans to check bounded memory and stable latency. Report model download/installation time separately from inference.

Use a dedicated machine-readable benchmark runner with a fixed manifest, model hashes, corpus version, hardware/OS/runtime versions, warm/cold conditions, and JSON results. The existing general benchmark script is not PII quality evidence and its RSS figure is not sampled peak memory.

## Provisional decision gates

Set final thresholds after the development corpus is characterized. Initial targets for discussion:

- At least 10 percentage points recall improvement for contextual entities over the current baseline in each claimed supported language, with no major precision collapse.
- No material regression for existing structured categories; report per-entity changes and held-out sample counts.
- Warm detection p95 at or below one second per 1,000 words, excluding OCR; cold readiness at or below five seconds.
- Incremental peak RSS at or below 500 MB and packaged model/runtime addition at or below 200 MB for the default configuration.
- No network access required after installation; cached offline scan succeeds with network denied.
- Stable selected-match IDs and complete safe redaction through scan, selection, and export.

These are POC gates, not safety guarantees. If no candidate meets the global quality and resource targets, report the language/entity gaps and keep model use optional rather than implying global coverage.

## POC sequence and deliverables

1. Pin candidate artifacts and licenses; implement a standalone text-detector adapter and machine-readable corpus manifest.
2. Run held-out detector-only comparisons, tune thresholds solely on development data, and inspect per-language errors.
3. Implement and benchmark the priority resolver, including adversarial overlap/conflict fixtures.
4. Connect the selected candidates to real OfficeKit extraction and redaction paths; measure detector repeat work, coordinates, stable IDs, and final outputs.
5. Package the leading configuration in a local sidecar build, measure installed-size delta and peak memory, then repeat the offline run with networking disabled.
6. Deliver reproducible scripts, labelled fixture manifest, raw aggregate JSON/CSV, per-language error analysis, resource report, and an adopt/tune/reject recommendation.

Estimated effort: 3–4 working days for corpus, text benchmark, resolver evaluation, and recommendation; packaged multi-format and platform acceptance follows as a separate stage.
