# Icon Pack Generator: platform selection and ZIP outputs

Added a focused browser regression that uploads a synthetic icon, verifies an empty platform selection shows correction guidance without sending a request, restores all three platforms, chooses Crop, and inspects the complete ZIP. It checks Web, Windows and macOS filenames, PNG signatures/dimensions, ICO signatures, upscale guidance, saved status, the one-action dock, and three-button maximum. Empty, ready, invalid and saved captures are included for future browser runs.

Fresh icon-pack route tests pass 2 tests plus 10 subtests; engine tests pass 8/8; shared image UI contracts pass 47/47. The browser spec passes `node --check` but has not run because WebKit 2359 aborts before setup. Existing source screenshots document the earlier Web + Windows case at `docs/verification/tool-unification/after/image_icon_pack-*`; the new three-platform screenshots await browser access.

Installed Finder/Dock behavior remains open. The current installed bundle cannot be opened through LaunchServices (`kLSNoExecutableErr`), its executable exits 134 when launched directly, and CUA cannot attach to an OfficeKit window.
