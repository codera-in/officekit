# Image DPI / PPI: correction and resolution metadata

Added a focused browser regression for a 300×150 PNG. It checks the initial print size, enters invalid horizontal density 0 and verifies linked guidance, disabled Save, and retained editable input; correcting X/Y to 150/75 per cm restores the 2×2 cm reading and Save. The saved PNG test checks dimensions remain 300×150, its `pHYs` chunk records 15,000×7,500 pixels per meter, the original bytes are unchanged, and the shared action bar remains under the button cap. Empty, invalid, recovered and saved screen captures are included for future browser runs.

Fresh density route check passes 1/1; engine density tests pass 8/8 plus 6 subtests; the shared image UI contracts pass 47/47. The focused browser spec passes `node --check` but has not run because WebKit 2359 aborts before setup. Historical desktop/compact screenshots remain under `docs/verification/tool-unification/{before,after}/image_dpi-*`.

Installed behavior remains unchecked. The installed app currently fails to launch through LaunchServices (`kLSNoExecutableErr`), direct execution exits 134, and CUA cannot attach to an OfficeKit window.
