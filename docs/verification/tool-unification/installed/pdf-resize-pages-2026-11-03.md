# Resize PDF Pages — installed verification — 2026-11-03

## Run

- App version: 1.0.77.
- Input: `tests/fixtures/pdf-page-management-source.pdf` (three pages, each 300 × 400 pt).
- Settings: A4 (210 × 297 mm), keep each page's orientation, Scale to fit, all pages.
- Result status: `Done · resized copy`; Download started and reported that the original remains unchanged.
- Downloaded `pdf-page-management-source-resized.pdf` (2 KB) from Downloads.
- Reopened the downloaded file in View metadata. It reported three pages, each 210 × 297 mm, and no encryption.

## UX finding

The installed 1.0.77 run completed with two task actions (Select PDFs and Download). Its dock title remained `PDF workbench`, and the selected 780-byte PDF appeared as `0.00 MiB`. The resize result status did not state the output dimensions; the separate metadata check confirmed them.

## Checks and screenshots

- `node --test tests/pdf-workbench-ui.test.mjs tests/pdf-tools-ui.test.mjs`: 83 passed.
- `pytest -q tests/test_pdf_tools_api_unittest.py::ResizeRouteTests tests/test_pdf_tools_page_tools_unittest.py::ResizePagesTests`: 18 passed, 11 subtests passed.
- Existing before/ready/saved captures are indexed in `docs/verification/tool-unification/README.md` under Resize PDF Pages.
- The native CUA screenshots could be inspected but not persisted locally through the documented API. Linked captures are current-source evidence, not screenshots of installed 1.0.77.

Compact layout, keyboard/VoiceOver and matching installed-build checks remain open.
