# Page Numbers — installed verification — 2026-11-03

## Run

- App version: 1.0.77.
- Input: `tests/fixtures/pdf-page-management-source.pdf` (three pages, each 300 × 400 pt).
- Settings: Arabic `1, 2, 3` format, start at 1, bottom center, page selection `1,3`.
- The run completed with `Done · 2 of 3 pages numbered`.
- Clicking Download displayed `Download started. Your original PDF remains unchanged.`
- The completed state showed two visible task actions: Select PDFs and Download. The dock title remained the generic `PDF workbench`; the selected file still appeared as `0.00 MiB`.

## Output validation status

The installed app reported success and began the download. I could not reopen the downloaded file for an independent text/visual inspection during this pass, so the numbered glyphs on pages 1 and 3 are not counted as validated installed output. Current-source UI/API evidence covers page selection, the result count, page-range recovery and generated PDF responses.

## Checks and screenshots

- `node --test tests/pdf-tools-ui.test.mjs tests/pdf-workbench-ui.test.mjs`: 83 passed.
- `pytest -q tests/test_pdf_tools_api_unittest.py::PageNumberRouteTests`: 5 passed, 14 subtests passed.
- Existing before/after and selected-page recovery captures are listed in `docs/verification/tool-unification/README.md` and under `docs/verification/tool-unification/after/pdf_page_numbers-*`.
- The native CUA screenshot could be inspected but not persisted locally through the documented API. The linked source captures are not represented as screenshots from installed 1.0.77.

Compact, keyboard/VoiceOver, native download re-open, and matching installed-build checks remain open.
