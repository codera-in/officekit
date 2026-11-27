# Compress PDF result visibility

## Live source run

The reviewed mock was inspected in Superset Browser and passed `node scripts/check-mock-buttons.mjs design/mocks/pdf-compress-result-visible.html`. Before screenshot `before/pdf_compress-result-clipped-source-superset-20261103.png` shows the preview covered by the dock: preview bottom y=903.6, dock top y=895. After the fix, a ResizeObserver-backed reveal keeps the preview above the dock as its feedback changes height; after Copy, preview bottom y=833.6 and dock top y=846 (12.4 px gap). Before/after screenshots also include the initial screen and corrupt-input recovery.

A synthetic three-page PDF (780 bytes) with the Balanced preset produced a 602-byte PDF (77.2% of source). The `%PDF-` signature was present. The local page-thumbnail API reopened both source and output as three pages with matching 300 × 400 pt page dimensions; source bytes were unchanged. The Copy adapter captured `Compress PDF\nOutput: three-page-source_compressed.pdf\nSize: 602 bytes`. The Download action was intercepted before the operating-system handoff; its anchor named `three-page-source_compressed.pdf` and referenced the same 602-byte PDF blob. This checks the UI payload and file bytes, not the native save dialog.

A 24-byte corrupt PDF with a valid PDF header reached the API and showed the specific invalid-file message with Report bug available. Replacing it with the valid fixture and running again produced the PDF result and removed the failure action.

## Checks

- `npm run build:ui`
- `node --test tests/pdf-compress-result-reveal.test.mjs tests/pdf-split-result-reveal.test.mjs tests/pdf-workbench-ui.test.mjs tests/pdf-group-split-mock.test.mjs` — 35 passed
- `pytest -q tests/test_pdf_endpoints.py -k 'compress_route or compress_rejects or merge_split_compress'` — 4 passed
- `node --check ui-tests/pdf-protect.spec.mjs`
- Mock button checker — passed

The targeted Playwright Compress PDF case was not run; WebKit had aborted during launch before test setup in the adjacent PDF Split run. Compact, keyboard, native clipboard/download and installed behavior remain open.

Mock review and live captures: `mock/pdf-compress-result-visible-review-20261103.png`, `mock/pdf-compress-result-visible-review-bottom-20261103.png`, `before/pdf_compress-initial-source-superset-20261103.png`, `before/pdf_compress-result-clipped-source-superset-20261103.png`, `before/pdf_compress-corrupt-input-source-live-20261103.png`, and `after/pdf_compress-result-visible-source-superset-20261103.png`.
