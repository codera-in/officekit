# Rotate & Flip Image: saved status survives late previews

Added two focused browser regressions for the approved recovery rule. Each starts a rotation preview and deliberately holds its response, saves the rotated image, then releases the older preview as either a 422 failure or a successful PNG. Both cases require the dock to retain “Saved. Your original is unchanged.” The success case also verifies a decoded preview remains visible; both check the saved PNG response, three-button cap, and pending/completed screenshots.

Fresh flip route check passes 1/1 and engine RotateFlip tests pass 5/5. The shared image UI contracts pass 47/47 and the new browser spec passes `node --check`. Playwright execution and fresh screenshots remain blocked because WebKit 2359 aborts before setup. The historical pixel-exact rotation/horizontal/vertical export flow and approved mock are archived under `docs/verification/tool-unification/{before,after}/image_rotate_flip-*` and `docs/ui-research/2026-10-29-approved-tool-recovery-details.md`.

Installed behavior remains unchecked: `/Applications/OfficeKit.app` fails to launch through LaunchServices (`kLSNoExecutableErr`), direct execution exits 134, and CUA cannot attach to an OfficeKit window.
