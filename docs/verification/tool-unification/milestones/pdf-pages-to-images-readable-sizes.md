# PDF Pages to PNG / JPEG: readable sizes

**Milestone:** PDF Pages to PNG / JPEG, one tool per commit.

The selected PDF and ZIP result could display as `0.00 MiB` even when valid and non-empty. This tool now uses the shared file-size formatter for both values. The chosen format, resolution, JPEG quality, page count, ZIP filename, source-preservation note and three-action result dock remain visible.

**Mock:** Reviewed in a fresh Superset Browser tab; capture: `docs/verification/tool-unification/mock/pdf-pages-to-images-readable-sizes-review-20261102.png`. The mock button checker passes.

**Checks:** `node --test tests/pdf-pages-to-images-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k images`.

**Remaining:** Fresh current-source post-fix screen capture, compact/keyboard interaction and installed native save remain open.

## Result visibility follow-up — 2026-11-03

**Decision:** When PNG/JPEG rendering completes, scroll the ZIP preview into view with a 12px margin above the shared fixed action dock. This keeps the output filename, readable size, page count and source-preservation note visible without adding controls; the existing three actions stay unchanged. Reviewed mock: `docs/verification/tool-unification/mock/pdf-images-result-reveal-review-20261103.png` (3/3 buttons per state; checker passes).

**Implementation:** The result-reveal path now includes `images` and rechecks the preview if the shared dock changes size. The source and packaged-UI regression asserts both paths.

**Checks:** `node --test tests/pdf-images-result-visibility.test.mjs tests/pdf-pages-to-images-readable-sizes.test.mjs`; `pytest -q tests/test_pdf_endpoints.py -k pdf_images_route` (4 passed); UI asset build passes. The result geometry is also asserted in `ui-tests/private-beta-pdf-images.spec.mjs`, but a fresh run is blocked before test setup: local WebKit exits with `Abort trap: 6`, and cached Chromium exits with a macOS Mach port bootstrap error. No live before/after source capture or native save was produced.
