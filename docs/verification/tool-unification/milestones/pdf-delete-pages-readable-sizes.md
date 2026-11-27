# Delete PDF Pages: readable file sizes

**Milestone:** Delete PDF Pages, one tool per commit.

The source and generated PDF can be smaller than one MiB, so displaying both as `0.00 MiB` made the output look empty. Delete PDF Pages now uses the shared file-size formatter for both selected input and generated output. Page selection, the unchanged-source note, and the three-action result dock remain intact.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-delete-pages-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-delete-pages-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k delete`.

**Remaining:** Fresh installed-app result capture, keyboard and compact layout behavior, and native download confirmation remain open.
