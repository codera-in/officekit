# Compare Images: size mismatch and recovery

Added a focused browser regression using generated 2×2 and 4×4 images. The mismatch state has correction guidance, no computed metrics, a hidden threshold, and a disabled difference export. Scaling B to A recovers the comparison; the test then checks Overlay opacity, the Difference view, saved PNG type/name/dimensions, and the three-button cap. It captures empty, mismatch, overlay and saved states when the browser can launch.

Fresh comparison route checks pass 5/5, engine checks pass 13/13, and the shared image UI contracts pass 47/47. The focused browser spec passes `node --check` but has not run because WebKit 2359 aborts before setup. Earlier source captures and a changed-pixel/difference-map browser flow are recorded in `docs/verification/tool-unification/after/image_compare-*`.

The new test expands the prior flow to size-mismatch recovery and Overlay interaction. Compact review and installed behavior remain open. The installed app fails to launch through LaunchServices (`kLSNoExecutableErr`); its direct executable exits 134 and CUA cannot attach to an OfficeKit window.
