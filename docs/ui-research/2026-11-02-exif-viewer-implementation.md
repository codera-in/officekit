# EXIF Viewer implementation

The approved unreadable-image recovery now clears prior metadata and location-inclusive copy state before a new read, keeps the shared dock visible while reading, and reports request failures in that dock. The selected file context remains available for correction and retry.

Mock decision and before/after capture: `2026-11-02-exif-viewer-error-mock-review.md` and `docs/verification/tool-unification/mock/image-metadata-error-review-20261102.png`. That image is mock evidence, not a fresh source render.

Verification: the image UI contract suite passes 47/47, `pytest -q tests/image_routes_unittest.py -k MetadataRouteTests` passes 3/3, and `pytest -q tests/engine_image_tools_unittest.py -k metadata` passes 13/13. The WebKit and Chrome browser launch attempts for the adjacent Image Tools milestone aborted before page setup; fresh rendered and installed EXIF failure/recovery, GPS-rich content, compact, keyboard/focus and native Copy checks remain open.
