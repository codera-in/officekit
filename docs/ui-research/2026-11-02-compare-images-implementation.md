# Compare Images implementation

On comparison request failure, clear the previous visual and result, retain both selected images, and show an accessible shared-dock error with Save difference image disabled. The difference map is constrained to the work area and brought into view after it loads.

Approved before/after mock evidence is `docs/verification/tool-unification/mock/image-compare-request-error-review-20261102.png` and `image-compare-request-error-review-bottom-20261102.png`; the mock review decision is in `2026-11-02-compare-images-error-mock-review.md`. Existing source success captures are listed in the acceptance matrix. No fresh source failure screenshot is claimed because WebKit and Chrome both aborted before page setup during the adjacent Image Tools browser run.

Verification: image UI contracts pass 47/47; `pytest -q tests/image_routes_unittest.py -k ComparisonRouteTests` passes 5/5; `pytest -q tests/engine_image_tools_unittest.py -k CompareTests` passes 13/13. Browser-rendered failure/recovery, exact PNG download bytes, compact, keyboard/focus, native save and installed behavior remain open.
