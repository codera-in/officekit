# Compare Images request-error mock review

## Decision and scope

Reviewed the existing request-error mock in Superset Browser. On comparison failure, clear the previous comparison visual/result, retain both selected images and their Change controls, announce the request error in the shared dock, and leave Save difference image visible but disabled. This restores a clear retry path without presenting stale output.

## Mock evidence

- Mock: `design/mocks/image-compare-request-error-dock.html`
- Fresh Superset Browser captures: `docs/verification/tool-unification/mock/image-compare-request-error-review-20261102.png` and `docs/verification/tool-unification/mock/image-compare-request-error-review-bottom-20261102.png`.
- The captures show both before and after states; the lower scroll position includes the complete after-state dock. Button counts are 0 before and 1/3 after.
- `node scripts/check-mock-buttons.mjs design/mocks/image-compare-request-error-dock.html` passes.

## Source and test evidence

No product code changed in this review. The current source clears the stale comparison, removes prior visual content, retains the selected files, and shows an accessible error dock with Save disabled. These are mock captures, not a fresh source render or installed-app pass.

Focused verification passed:

- `node --test tests/image-tools-ui.test.mjs` — 47/47
- `pytest -q tests/image_routes_unittest.py -k ComparisonRouteTests` — 5 passed
- `pytest -q tests/engine_image_tools_unittest.py -k CompareTests` — 13 passed

Native save, compact layout, keyboard/focus and installed behavior remain open.
