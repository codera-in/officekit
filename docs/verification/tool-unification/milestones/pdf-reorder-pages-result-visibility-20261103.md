# Reorder PDF Pages: keep the new order visible

**Milestone:** Reorder PDF Pages, one tool per commit.

The completed reordered PDF was not included in the shared result-reveal path. The fixed dock could overlap the output filename, page count and source-preservation note after the order was created.

**Decision:** Reveal the result 12px above the dock and reposition it when the dock resizes. Keep the ordered page list, mixed-page-size note and existing Copy summary / Download / Select PDFs actions unchanged. The Superset-reviewed mock shows the new order and completed result with 3/3 buttons; capture: `docs/verification/tool-unification/mock/pdf-reorder-pages-result-reveal-review-20261103.png`.

**Implementation:** The shared result path now includes `reorder-pages`; the browser regression checks at least 8px clearance.

**Checks:** `npm run build:ui` passed. `node --test tests/pdf-reorder-pages-result-visibility.test.mjs tests/pdf-workbench-ui.test.mjs tests/pdf-page-management-mock.test.mjs` passes 34/34. `pytest -q tests/test_pdf_endpoints.py -k reorder_pages` passes 14/14. Browser execution remains blocked before setup by local engine launch failures; compact/keyboard runtime and installed native download remain unverified.
