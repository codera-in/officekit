# Watermark PDF — installed check — 2026-11-03

## Installed run

- App: OfficeKit 1.0.77.
- Input: the three-page PDF created in the preceding Resize PDF Pages check.
- Invalid state: cleared the Text field. The field remained editable, the inline rule explained the 1–200 character requirement, and Add watermark stayed disabled. The installed app also showed Report bug for this local input correction.
- Recovery: entered `REVIEW COPY`, ran Watermark, and received `Done · …-watermarked.pdf · 3 pages`.
- Download: saved the generated PDF. The Downloads picker showed the new file at 18 KB.
- Output check: reopened the newest download with Extract PDF text. It reported text on all three pages, each containing `REVIEW COPY`; the source remained unchanged.
- This binary-output tool has no Copy action. Its result uses Download, and the downloaded artifact was checked through the app’s PDF text extractor.

## UX and source change

The invalid field itself gave actionable guidance, so its generic Report bug link was misleading. The `pdf-slice-validation` region is dedicated to correctable form guidance; it now carries `data-officekit-no-bug-report`. Server and processing messages use a separate region, so real application failures can still be reported.

The reviewed two-state proposal is archived at [`pdf-watermark-validation-guidance-review-20261103.png`](../mock/pdf-watermark-validation-guidance-review-20261103.png). Both states stay below the three-button cap. The temporary mock HTML and preview server were removed after review.

## Checks and remaining evidence

- `node --test tests/pdf-tools-ui.test.mjs`: 56 passed.
- `pytest -q tests/test_pdf_tools_api_unittest.py -k WatermarkRouteTests`: 11 passed, 18 subtests passed.
- `npm run build:ui`: passed.
- `node scripts/check-mock-buttons.mjs design/mocks/pdf-watermark-validation-guidance.html`: passed before removing the temporary mock.
- The native installed screenshot could be viewed in CUA but could not be saved locally through its documented screenshot API. The archived image is the reviewed mock, not an installed-app capture.
- OfficeKit 1.0.77 predates the source change, so installed invalid-state behavior still shows Report bug. The matching-build native check remains open.
- The installed PDF dock still says `PDF workbench` rather than `Watermark`; small selected files can still display as `0.00 MiB`. These shared dock and size findings remain open in the broader audit.
