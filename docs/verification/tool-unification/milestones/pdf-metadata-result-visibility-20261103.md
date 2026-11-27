# Remove PDF Metadata: keep the cleaned copy visible

**Milestone:** Remove PDF Metadata, one tool per commit.

The tool creates a cleaned PDF and publishes its summary to the shared result preview, but its success path was not included in the shared result-reveal handling. On a long screen the preview could remain beneath the fixed dock, hiding the filename and output size.

**Decision:** Bring the completed preview above the dock with 12px clearance and reposition it if dock height changes. Preserve the scope note and existing Copy summary / Download / Select PDFs actions. The Superset-reviewed mock shows before/after states with 3/3 buttons; capture: `docs/verification/tool-unification/mock/pdf-metadata-result-reveal-review-20261103.png`.

**Implementation:** The shared result-reveal path now covers metadata removal; source and packaged UI checks assert the reveal and dock observer. A browser regression checks for at least 8px clearance.

**Checks:** `npm run build:ui` passed. `node --test tests/pdf-metadata-result-visibility.test.mjs tests/pdf-metadata-readable-sizes.test.mjs tests/pdf-workbench-ui.test.mjs` passes 30/30. `pytest -q tests/test_pdf_endpoints.py -k metadata_route` passes 3/3. Browser test execution is blocked before page setup by local WebKit/Chromium launch failures. Fresh current-source geometry, compact/keyboard and installed native save remain unverified.
