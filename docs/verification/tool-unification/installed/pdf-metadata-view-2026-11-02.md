# View PDF Metadata: installed verification

OfficeKit 1.0.77 was checked in the installed desktop app on 2026-11-02.

- The 626-byte `tests/fixtures/pdf-protect-source.pdf` produced a one-page metadata report with the expected fixture title. Copy report worked; the result dock showed two actions.
- Replacing it with a 9-byte text file named `officekit-broken.pdf` initially left the old report visible. Running Read metadata showed “The PDF file is invalid or the requested operation is unsupported.” with Report bug, while the stale metadata remained visible.
- Selecting the valid fixture and running Read metadata again recovered the report. This recovery was observed during the live session; the saved images capture the initial, valid, malformed-selection and post-error states.
- The installed screen shows the generic “PDF workbench” page and dock titles instead of the active task title “View metadata.” At this window size, the dock overlaps the lower error content. The selected 9-byte input is rounded to `0.00 MiB`.

The source regression for invalid PDF content clearing the previous report and omitting Report bug is already in commit `dfdb9651` (`fix(pdf-metadata-view): clear invalid report state`). Its focused test passes 1/1. The installed 1.0.77 build predates that change; source-rendered verification and verification in an installed build containing it are still pending.

![Initial View metadata state](./pdf_metadata_view-before-20261102.jpg)

![Valid one-page metadata report](./pdf_metadata_view-valid-20261102.jpg)

![Malformed file selected while the previous report is still visible](./pdf_metadata_view-invalid-20261102.jpg)

![Error after running Read metadata on malformed content](./pdf_metadata_view-error-20261102.jpg)

## Current-source checks (2026-11-02)

- `node --test --test-name-pattern='invalid PDF content clears stale report output and does not offer Report bug' tests/pdf-tools-ui.test.mjs`: 1/1 passed.
- `pytest -q tests/test_pdf_endpoints.py -k metadata`: 3 passed.
- Reviewed the archived source comparison: `before/pdf_metadata_view-stale-report-after-invalid-live-source-20261031.png` shows the stale report and Report bug; `after/pdf_metadata_view-invalid-file-guidance-live-source-20261031.png` shows the malformed file without the prior report, and `after/pdf_metadata_view-recovered-live-source-20261031.png` shows the valid one-page report returned. These are 2026-10-31 source captures, not fresh screenshots from today.
- CUA could not attach to Chrome or Paradev during this pass (`cgWindowNotFound`), so I could not capture a fresh current-source state. The installed 1.0.77 screenshots above remain evidence of the older behavior. Fresh rendered source, compact, keyboard/focus, native Copy, and behavior in an installed build containing `dfdb9651` remain open.

## Installed recheck and dock-title milestone (2026-11-03)

- Repeated the installed 1.0.77 flow with `tests/fixtures/statements/weak-vector-raster-statement.pdf`: the report shows one page, nine standard fields, no XMP packet, and no form fields. Copy report reports “Report copied. The original PDF is unchanged.”
- Replaced that file with a 9-byte malformed PDF. The old metadata table remained visible, and the error displayed “Report bug” in both the result area and the fixed dock. This confirms the installed build still predates `dfdb9651`; it is a build-parity failure, not a regression in the current source fix.
- Selecting the valid PDF again and running Read metadata restored the report. The fixed dock title remained “PDF workbench” both on View metadata and after switching to Unlock PDF. The current source sets the active PDF task identity but did not explicitly refresh the shared dock at that point.
- Added an explicit title refresh to `openPdfTool` and a regression contract. Reviewed mock: [`pdf-metadata-dock-title-review-20261103.png`](../mock/pdf-metadata-dock-title-review-20261103.png). `node --test tests/shared-action-titles-ui.test.mjs tests/pdf-tools-ui.test.mjs` passes 63/63; `npm run build:ui` passes.
- The installed app remains 1.0.77, so the new title refresh and the stale-report recovery fix need a matching packaged build before native parity can be closed. Existing installed screenshots are from 2026-11-02; the live 2026-11-03 CUA state was inspected but its screenshot could not be persisted through the documented CUA screenshot API.
