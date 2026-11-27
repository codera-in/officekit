# Dominant Colors milestone — 2026-11-03

## Scope and build

Verified the current `dist-ui` source in a visible Superset Browser pane using the isolated OfficeKit test API. This is source-browser evidence, not installed-app verification. Fixtures were generated in the page: a 4-pixel PNG split evenly between red and blue, and a fully transparent PNG.

## Observed flow

- Empty state offers Choose image.
- The red/blue image produces `#0000FF` and `#FF0000` swatches, each at 50.0%, and reports 4 sampled pixels.
- Copy CSV was intercepted at the UI adapter, leaving the system clipboard unchanged. Captured complete text:

  ```text
  hex,r,g,b,share
  #0000FF,0,0,255,50.0%
  #FF0000,255,0,0,50.0%
  ```

- Replacing it with the fully transparent image clears the old palette and displays “The image has no opaque pixels to sample.” The image can be changed; no Report bug action appears.
- Replacing the invalid image with the red/blue image restores the swatches and Copy CSV action.
- Button count: empty 1; valid/recovered 3 (two in-swatch Convert buttons plus Copy CSV); invalid 0. This tool exports by copying CSV; it has no Download action.

Screenshots:

- Empty: `before/dominant_colors-source-empty-20261103.png`
- Valid: `after/dominant_colors-source-valid-20261103.png`
- Invalid: `after/dominant_colors-source-invalid-20261103.png`
- Recovered: `after/dominant_colors-source-recovered-20261103.png`

Keyboard/focus behavior, compact viewport, native clipboard behavior and installed-app parity remain open.

## Checks

- `node --test --test-name-pattern='palette' tests/image-tools-ui.test.mjs` — 4 passed.
- `pytest -q tests/image_routes_unittest.py -k palette` — 4 passed, 10 subtests passed.
- `git diff --check` — passed.
- Browser console capture — no console output.
