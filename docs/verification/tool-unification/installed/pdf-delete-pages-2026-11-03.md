# Delete PDF Pages — installed verification — 2026-11-03

## Run

- App version: 1.0.77.
- Input: `tests/fixtures/pdf-page-management-source.pdf` (780 bytes, three pages, each 300 × 400 pt).
- Selected page 2. The UI reported `1 page selected for removal · 2 will remain` and enabled **Create PDF without selected pages**.
- Created `pdf-page-management-source_pages-removed.pdf` and saved it as `/tmp/officekit-pages-removed-installed.pdf`.
- Independent `pikepdf` validation confirmed two readable pages remain, matching source pages 1 and 3 in the same order and dimensions. The source bytes were unchanged.

## UX finding

After success, the installed 1.0.77 page still showed **Select PDFs**, **Copy summary**, and **Download** in the page plus a stale **Create PDF without selected pages** action in the fixed dock. That is four visible actions. The dock title remained **PDF workbench**. Both source and output sizes rounded to `0.00 MiB`.

Current source already has result-reveal, size-formatting and page-selection coverage. The shared PDF workbench now hides the create action after binary output exists; focused regression checks below pass. These source checks do not establish installed-build parity.

## Checks and screenshots

- `node --test tests/pdf-delete-pages-result-visibility.test.mjs tests/pdf-delete-pages-readable-sizes.test.mjs tests/pdf-page-management-mock.test.mjs tests/pdf-workbench-ui.test.mjs`: 35 passed.
- `pytest -q tests/test_pdf_endpoints.py -k delete_pages`: 13 passed.
- Reviewed before/after mock screenshot: `docs/verification/tool-unification/mock/pdf-delete-pages-readable-sizes-review-20261102.png`.
- Existing source screen captures are indexed in `docs/verification/tool-unification/README.md` under Delete PDF Pages.
- The native CUA screenshot could be inspected but not persisted locally through the documented API; the installed app state is not represented as a saved screenshot.

Compact, keyboard/VoiceOver, and matching installed-build checks remain open.
