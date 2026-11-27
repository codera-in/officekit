# EXIF Viewer error mock review

## Decision and scope

Reviewed the existing unreadable-image mock in Superset Browser. Keep the selected filename and Change image link on a failed read, move the failure into the shared dock, and clear stale metadata and location-inclusive Copy details. The same dock remains through the reading/loading state.

Correctable image-input responses (HTTP 400, 413, 415 and 422) are local input guidance and must not offer Report bug. Unexpected server failures remain reportable.

## Mock evidence

- Mock: `design/mocks/image-metadata-error-dock.html`
- Fresh Superset Browser capture: `docs/verification/tool-unification/mock/image-metadata-error-review-20261102.png`
- The capture shows before and after states together. The after state keeps the source context and visible error dock; both states show 0/3 counted buttons.
- `node scripts/check-mock-buttons.mjs design/mocks/image-metadata-error-dock.html` passes.

## Source and test evidence

No product code changed in this review. Current source clears metadata before reading, keeps the dock mounted during loading, and shows request errors in its shared alert dock. The fresh capture is mock evidence, not a source-render or installed-app pass.

Focused verification passed:

- `node --test tests/image-tools-ui.test.mjs` — 47/47
- `pytest -q tests/image_routes_unittest.py -k MetadataRouteTests` — 3 passed
- `pytest -q tests/engine_image_tools_unittest.py -k MetadataReportTests` — 13 passed

## Current-source recovery follow-up — 2026-11-03

In a fresh Superset Browser tab, an invalid `broken.png` retained the filename and Change image control, cleared the old table and Copy details action, and kept the shared dock. Before the fix, the correctable HTTP 422 also showed Report bug. The reviewed recovery mock now shows that CTA removed. Current source marks HTTP 400/413/415/422 metadata input errors as non-reportable; unexpected server failures retain normal reporting.

The valid synthetic 3 × 2 PNG reports its dimensions and all 16 metadata fields as missing. Intercepted Copy details captured all 16 report lines and omitted `Location:`. Replacing the invalid image with the valid one restores the report and Copy details.

Fresh source captures: `docs/verification/tool-unification/before/image_exif_view-current-source-empty-20261103.png` and `docs/verification/tool-unification/after/image_exif_view-current-source-{valid,invalid,recovered}-20261103.png`. Mock review capture: `docs/verification/tool-unification/mock/image-metadata-error-review-20261103.png`.

`node --test tests/image-tools-ui.test.mjs tests/image-metadata-ui.test.mjs` passes 51/51; metadata routes pass 3/3; metadata engine reports pass 13/13. The browser E2E spec was updated and syntax-checked but not run in Playwright. Native clipboard, compact, keyboard/focus and installed behavior remain open.

Installed behavior, a GPS-rich live view, compact layout, keyboard/focus and native clipboard/save remain open.
