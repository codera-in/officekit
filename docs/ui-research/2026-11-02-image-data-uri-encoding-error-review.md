# Image ↔ Data URI encoding-error review

## Decision and scope

Reviewed the existing file-to-URI error mock in Superset Browser. Keep the selected source file and Change image link visible; keep the shared dock visible during encoding and after failure; clear stale URI data and hide Copy/Save until a successful retry. This review covers file-to-URI encoding. The separately approved pasted-URI decode validation behavior remains unchanged.

## Mock evidence

- Mock: `design/mocks/image-data-uri-encode-error-dock.html`
- Fresh Superset Browser capture: `docs/verification/tool-unification/mock/image-data-uri-encode-error-review-20261102.png`
- The capture shows before and after states together. The reviewed after state keeps an assertive dock error and the selected file context; both states show 0/3 counted buttons.
- `node scripts/check-mock-buttons.mjs design/mocks/image-data-uri-encode-error-dock.html` passes.

## Source and test evidence

No product code changed in this review. The current source encoder clears `state.dataUri` before each request, shows a loading dock, and replaces it with an alert dock without Copy/Save on failure. Existing live source evidence for the paired Data URI error/recovery flow is recorded in the tool acceptance matrix; this Superset capture is mock evidence and does not claim a fresh source render or installed-app check.

Focused verification passed:

- `node --test tests/image-tools-ui.test.mjs` — 47/47
- `pytest -q tests/image_routes_unittest.py -k DataUriRouteTests` — 6 passed, 2 subtests
- `pytest -q tests/engine_image_tools_unittest.py -k DataUriTests` — 12 passed, 14 subtests

Installed 1.0.77 behavior, native clipboard/save, compact layout, keyboard/focus and installed-build parity remain open.
