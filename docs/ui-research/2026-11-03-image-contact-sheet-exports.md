# Contact Sheet: multipage PDF and PNG ZIP

Added a focused browser regression with four synthetic PNGs in a two-column, one-row landscape Letter layout. The empty state disables Preview and Save; after input, the test checks the two-page estimate and preview response, inspects a two-page PDF export, then switches to PNG ZIP and verifies both numbered entries have valid PNG signatures. It checks the three-button cap and captures empty, ready, preview, PDF and ZIP screen states when the browser is available.

Fresh contact-sheet routes pass 3/3; engine tests pass 11/11; the shared image UI contracts pass 47/47. The focused spec passes `node --check` but has not run because WebKit 2359 aborts before setup. Existing archived compact captures show a blank preview/washed out dock and should be refreshed when the browser is available.

The multipage form and output behavior are verified at route/engine level. Runtime, fresh screenshots, other page/orientation/grid boundaries and installed behavior remain open. `previewOrdered()` has the same possible late-status race as Image Collage and still needs runtime reproduction and a reviewed mock. `/Applications/OfficeKit.app` fails to open through LaunchServices (`kLSNoExecutableErr`); direct execution exits 134, and CUA cannot attach to the app window.
