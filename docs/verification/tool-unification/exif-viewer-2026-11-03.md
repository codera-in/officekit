# EXIF Viewer milestone — 2026-11-03

## Scope and build

Verified current `dist-ui` in a visible Superset Browser pane with the isolated OfficeKit test API. This is source-browser evidence, not installed-app verification. The valid fixture was a generated 3 × 2 PNG with no EXIF data; the invalid fixture was 12 bytes of non-image text named `broken.png`.

## Observed flow

- Empty state keeps Choose image in the shared dock under the catalog title EXIF Viewer.
- Valid input reports PNG dimensions and one frame; each absent metadata field is labelled Missing.
- Intercepted Copy details captured the complete 16-line report. It contains no `Location:` line, consistent with the default privacy behavior.
- Invalid input initially showed “The image file is invalid or cannot be decoded.” plus Report bug. The filename and Change image were retained, but stale metadata and Copy details were cleared.
- After the fix, HTTP 400/413/415/422 metadata input errors remain in the dock, carry `data-officekit-no-bug-report`, and do not show Report bug. Unexpected failures remain reportable.
- Replacing the invalid image with the valid fixture restores the report and Copy details action.

Screenshots:

- Empty: `before/image_exif_view-current-source-empty-20261103.png`
- Valid: `after/image_exif_view-current-source-valid-20261103.png`
- Invalid after fix: `after/image_exif_view-current-source-invalid-20261103.png`
- Recovered: `after/image_exif_view-current-source-recovered-20261103.png`
- Reviewed recovery mock: `mock/image-metadata-error-review-20261103.png`

Keyboard/focus, compact viewport, native clipboard, GPS-rich rendered fixture and installed-build parity remain open.

## Checks

- `node --test tests/image-tools-ui.test.mjs tests/image-metadata-ui.test.mjs` — 51 passed.
- `pytest -q tests/image_routes_unittest.py -k MetadataRouteTests` — 3 passed.
- `pytest -q tests/engine_image_tools_unittest.py -k MetadataReportTests` — 13 passed.
- `node --check ui-tests/tool-unification-baseline.spec.mjs` — passed.
- `node scripts/check-mock-buttons.mjs design/mocks/image-metadata-error-dock.html` — passed at 0/3 for both states.
- `git diff --check` — passed.
