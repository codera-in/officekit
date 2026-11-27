# Image ↔ Data URI: round trip and decode recovery

Added an isolated browser regression for the complete encode/decode path. A generated 2×2 PNG encodes to the exact copied URI; Save .txt preserves the full URI. In decode mode, a syntactically valid but malformed PNG URI stays editable and Save remains available after the API returns 422. Replacing it with the valid URI downloads byte-identical PNG data and reports “Image saved.” The test captures empty, encoded, malformed and recovered states when Playwright can launch, and checks the three-button cap.

Fresh `DataUriRouteTests` pass 6 tests plus 2 subtests. The shared image UI contract suite passes 47/47, and the focused browser spec passes `node --check`. The browser test has not run: WebKit 2359 aborts before setup. Existing source captures for malformed/recovered and valid/invalid actions remain under `docs/verification/tool-unification/{before,after}/image_data_uri-*`.

Still open: execution and fresh screenshots in a working browser, other supported image formats, native clipboard/save interaction, and installed behavior. `/Applications/OfficeKit.app` cannot open through LaunchServices (`kLSNoExecutableErr`); direct execution exits 134, and CUA cannot attach to an OfficeKit window. This milestone adds verification only and keeps the previously approved recovery design.
