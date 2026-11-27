# Split by Pages: readable file sizes

**Milestone:** Split by Pages, one tool per commit.

Small valid source PDFs and grouped ZIP output could both display as `0.00 MiB`. Split by Pages now uses the shared file-size formatter for the selected PDF and completed ZIP. Named page groups, order, ZIP filename, unchanged-source note and title-correct three-action dock remain visible.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-split-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-split-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k split`.

**Remaining:** Fresh current-source result capture, compact/keyboard behavior, and installed native download remain open.
