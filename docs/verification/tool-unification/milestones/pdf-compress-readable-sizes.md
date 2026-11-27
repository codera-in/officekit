# Compress PDF: readable file sizes

**Milestone:** Compress PDF, one tool per commit.

Tiny source and compressed PDFs could both show as `0.00 MiB`, hiding the actual size change. Compress PDF now formats the selected source, output, and source-size comparison with the shared formatter. The lossless preset, output ratio, unchanged-source explanation and three-action dock remain in place; the ratio continues to use the actual output/input byte counts.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-compress-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-compress-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k compress`.

**Remaining:** Fresh source result capture, compact/keyboard behavior, and installed native download remain open.
