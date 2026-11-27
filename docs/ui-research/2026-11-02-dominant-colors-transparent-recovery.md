# Dominant Colors transparent-image recovery

## Change

An all-transparent image returns HTTP 422 because there are no opaque pixels to sample. Keep the error as an accessible message in the shared dock, but mark this correctable input state as non-reportable. Unexpected errors remain reportable. The image and sampling options stay available for correction; stale palette output is cleared before each request.

## Mock and source evidence

- Approved mock: `design/mocks/palette-transparent-error-dock.html`; it was reopened and inspected in a new Superset Browser tab. The 3-button checker passes. Fresh mock captures show the before and after states at the top and the complete dock at the lower scroll position: `docs/verification/tool-unification/mock/palette-transparent-error-review-20261102.png` and `docs/verification/tool-unification/mock/palette-transparent-error-review-bottom-20261102.png`.
- Current-source screenshots show the transparent-only error and recovery to a red palette: `docs/verification/tool-unification/after/image_palette-transparent-only-error-current-source-20261031.png` and `docs/verification/tool-unification/after/image_palette-recovered-current-source-20261031.png`.

## Verification

- `node --test tests/image-tools-ui.test.mjs` — 47/47
- `pytest -q tests/image_routes_unittest.py -k PaletteRouteTests` — 4 passed, 10 subtests
- `pytest -q tests/engine_image_tools_unittest.py -k PaletteTests` — 9 passed, 4 subtests
- `npm run build:ui` and `git diff --check` — passed

Native clipboard, compact/keyboard behavior and installed-build parity remain open.
