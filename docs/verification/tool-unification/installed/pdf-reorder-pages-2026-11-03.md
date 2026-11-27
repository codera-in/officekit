# Reorder PDF Pages — installed verification — 2026-11-03

## Run

- App version: 1.0.77.
- Input: `tests/fixtures/pdf-page-management-source.pdf` (780 bytes, three pages, all 300 × 400 pt).
- Reordered through the page controls from 1, 2, 3 to 2, 3, 1.
- Created `pdf-page-management-source_reordered.pdf` and saved it as `/tmp/officekit-reordered-test.pdf`.
- Independent `pikepdf` validation confirmed the output is readable, retains three pages and their dimensions, and its page content streams match source pages 2, 3, 1 in that order. The checked-in original remained unchanged.
- The completed preview showed the expected order, `pdf-page-management-source_reordered.pdf`, and `Output is ready`.

## UX finding

The installed 1.0.77 result state showed **Select PDFs**, **Copy summary**, and **Download** in the page, plus a stale **Create reordered PDF** action in the fixed dock (4 visible actions). The dock title remained **PDF workbench**. The source file size and result size both appeared as `0.00 MiB`.

Current source already has result-reveal and readable-size coverage for this tool. The shared PDF workbench source also hides the create action after a binary result exists; its focused tests pass. These current-source checks do not establish parity in installed 1.0.77.

## Checks and screenshots

- `node --test tests/pdf-reorder-pages-result-visibility.test.mjs tests/pdf-reorder-readable-sizes.test.mjs tests/pdf-page-management-mock.test.mjs tests/pdf-workbench-ui.test.mjs`: 35 passed.
- `pytest -q tests/test_pdf_endpoints.py -k reorder_pages`: 14 passed.
- The reviewed before/after prototype screenshot is `docs/verification/tool-unification/mock/pdf-reorder-pages-result-reveal-review-20261103.png`; the temporary mock HTML was removed after implementation.
- Existing source screenshots and regressions are listed in the Rotate/Reorder sections of `docs/verification/tool-unification/README.md`.
- The native CUA screenshot could be inspected but not saved locally through the documented API, so no installed screenshot is claimed here.

Compact, keyboard/VoiceOver, and matching installed-build checks remain open.
