# Delete PDF Pages: keep the new PDF visible

**Milestone:** Delete PDF Pages, one tool per commit.

After a valid page removal, the completed PDF summary was not included in shared result-reveal handling. The fixed dock could cover the output filename, new page count and unchanged-source note.

**Decision:** On success, reveal the result 12px above the dock and reposition it if the dock changes height. Keep the page-selection guidance and existing Copy summary / Download / Select PDFs actions unchanged. The Superset-reviewed mock shows both states with 3/3 buttons; capture: `docs/verification/tool-unification/mock/pdf-delete-pages-result-reveal-review-20261103.png`.

**Implementation:** The shared result path now includes `delete-pages`. The browser regression asserts at least 8px clearance.

**Checks:** `npm run build:ui` passed. `node --test tests/pdf-delete-pages-result-visibility.test.mjs tests/pdf-workbench-ui.test.mjs tests/pdf-page-management-mock.test.mjs` passes 34/34. `pytest -q tests/test_pdf_endpoints.py -k test_delete_pages` passes 10/10. `node --check ui-tests/pdf-page-management.spec.mjs` and mock button check pass. Browser execution remains blocked before setup by the local browser-engine launch failures; compact/keyboard and installed native download remain unverified.
