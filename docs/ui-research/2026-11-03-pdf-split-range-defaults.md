# Extract PDF Pages range defaults

## Decision

Start the two required output groups with blank page ranges. Keep the example format in each field placeholder and disable Create PDFs until every group has a range.

## Reasoning

The page selection is specific to each source PDF, but the screen cannot safely infer a user's intended grouping. Prefilled ranges can point past the end of shorter documents and cause an avoidable failed run. Blank fields make the user choice explicit, work for any document length, and keep the selected PDF and named output groups available for correction.

## Verification

- The mock was opened and inspected in the Superset Browser and passed `node scripts/check-mock-buttons.mjs design/mocks/pdf-split-empty-page-ranges.html`.
- On live source, both ranges were blank after selecting a three-page PDF and Create PDFs was disabled. Entering `1-2` and `3` produced a 1,422-byte ZIP with the preview above the dock.
- Before/after screenshots and focused test results are recorded in [the PDF Split result visibility evidence](../verification/tool-unification/pdf-split-result-visibility-20261103.md).
