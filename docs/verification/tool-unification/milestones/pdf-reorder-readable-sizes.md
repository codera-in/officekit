# Reorder PDF Pages: readable file sizes

**Milestone:** Reorder PDF Pages, one tool per commit.

Reordered PDFs can be smaller than one MiB, so the input and generated result appeared as `0.00 MiB`. Reorder PDF Pages now uses the shared size formatter in both the source and packaged UI. Page order, page dimensions, unchanged-source guidance, and the three-action dock remain visible.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-reorder-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-reorder-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k reorder_pages`.

**Remaining:** Compact and installed-app result checks, native download confirmation, and assistive keyboard testing remain open.
