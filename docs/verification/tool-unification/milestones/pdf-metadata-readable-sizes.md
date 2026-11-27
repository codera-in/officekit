# Remove PDF Metadata: readable file sizes

**Milestone:** Remove PDF Metadata, one tool per commit.

The selected file row and output preview rounded tiny PDFs to `0.00 MiB`, making valid files appear empty. Remove PDF Metadata now uses the shared file-size formatter for those two values: byte counts below 1 KiB and KiB below 1 MiB. Its privacy note, output name, source-preservation message and three-action result dock stay unchanged.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-metadata-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-metadata-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k metadata`.

**Remaining:** Fresh source invalid/recovery screenshots, compact/keyboard behavior and installed native save remain open.
