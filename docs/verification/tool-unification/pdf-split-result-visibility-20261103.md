# Extract PDF Pages result visibility

The reviewed result-visibility mock keeps the selected PDF and editable page groups in the work area, then places the completed ZIP preview above the shared action dock. The mock was opened and inspected in Superset Browser before implementation, and passed the 3-button checker.

## Live source evidence

With a synthetic three-page PDF (779 bytes), valid groups `cover.pdf: 1` and `appendix.pdf: 2-3` produced a 1,422-byte ZIP with the `PK\u0003\u0004` signature. Before the fix, the result preview ended at y=1,195.6 while the dock began at y=846, leaving the preview 349.6 px behind the dock. After the fix, and after the Copy confirmation expanded the dock to 170 px, the preview ended at y=755.6 and the dock began at y=768, leaving a 12.4 px gap.

The result state retains exactly three visible actions: Copy summary, Download and Select PDFs. “Add another PDF” is hidden while output is ready, so it cannot make the body-plus-dock total 4; it returns after a group edit clears the result. Screenshot: [after/pdf-split-result-visible-source-live-20261103.png](after/pdf-split-result-visible-source-live-20261103.png). Before screenshots record the empty state, selected defaults, invalid default range and result hidden below the dock in `before/pdf-split-*-source-live-20261103.png`. Reviewed mock capture: [mock/pdf-split-result-reveal-review-20261103.png](mock/pdf-split-result-reveal-review-20261103.png).

The browser clipboard permission denied the first synthetic Copy click. A clipboard spy then captured the exact payload—`Extract PDF Pages\nOutput: three-pages_split-pages.zip\nSize: 1.4 KiB`—and the action showed success. This verifies the payload construction and success state; it does not verify the operating system clipboard.

Focused checks passed: `npm run build:ui`; 33 PDF workbench and grouped-split UI tests; `node --check ui-tests/pdf-protect.spec.mjs`; mock button checker; and `pytest -q tests/test_pdf_endpoints.py -k 'split_route_preserves or split_rejects_corrupt or split_groups_route'` (16 passed). The Playwright browser scenario was updated but not run in this milestone.

## Follow-up: safe initial page ranges

The reviewed mock replaces guessed `1-3` / `4-6` values with blank, example-guided ranges. The live source starts with both ranges empty and disables Create PDFs until every group has a range; this avoids a failed API request and works for any source length. After entering `1-2` and `3` for the same three-page fixture, the real local route produced `three-page-source_split-pages.zip` (1,422 bytes), with the completed preview 12.4 px above the dock. Before/after live captures: `before/pdf-split-blank-ranges-source-live-20261103.png` and `after/pdf-split-empty-ranges-recovered-source-live-20261103.png`. The proposal capture is `mock/pdf-split-empty-page-ranges-review-20261103.png`.

Focused checks now pass 34/34 PDF UI contracts, including blank defaults and disabled action gating; `ui-tests/pdf-protect.spec.mjs` syntax checks. The reviewed mock passes the button checker. The targeted Playwright split test was attempted but WebKit aborts during launch, before test setup. Compact, keyboard, native clipboard and native download checks remain open.
