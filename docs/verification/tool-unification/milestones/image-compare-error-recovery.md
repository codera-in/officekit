# Compare Images: request-error recovery

The existing Compare Images implementation was committed in `54bbcbc2` (`fix(compare-images): clear stale results on failure`). A failed comparison clears the previous map and summary, retains both selected image inputs, and leaves the shared dock visible with the error and a disabled “Save difference image” action.

The before/after proposal was opened in a fresh Superset Browser tab and visually inspected. Capture: `docs/verification/tool-unification/mock/image-compare-request-error-dock-review-20261102.png`. The mock button checker passes and the browser console had no output.

**Checks:** `pytest -q tests/image_routes_unittest.py -k ComparisonRouteTests` passes 5/5; `node --test tests/image-tools-ui.test.mjs` passes 47/47, including the failed-request stale-result regression.

**Remaining:** Fresh source error-state capture, compact/keyboard checks, installed behavior, and exact saved PNG byte comparison remain open. Earlier current-source valid comparison and Save action verification are documented in the acceptance matrix.
