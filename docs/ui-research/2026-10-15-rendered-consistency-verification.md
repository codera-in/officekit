# Rendered consistency verification — 2026-10-15

Source: `ffdc4eb` with uncommitted changes. Development release profile: 50 registered tools and 21 shell destinations. This report concerns rendered UI consistency; it does not certify installed native permissions, real microphone capture or every tool's complete native export flow.

## Confirmed fixes

- Sidebar workspace, category and quick-access entries share one icon column, row height and label baseline. Long labels remain one line.
- Single-line inputs, selects and buttons use 40px desktop and 44px compact sizing. Textareas use a common minimum. Primary actions use the Ice Blue theme tokens.
- Narrow header controls reflow without horizontal overflow. The loaded native-bridge failure state exposed another overflow: the longer “License unavailable” label. Explicit header width, intrinsic select width and a bounded status label correct it.
- PDF Fit uses the canvas's measured dimensions. Zoom requests a sharper preview. PDF selects retain their arrow, and the status/action row follows the workspace instead of floating over the document.
- Color-result Copy and PDF password action rows no longer stretch buttons to the height of adjacent content.

## Evidence

| Check | Observed result | Evidence |
| --- | --- | --- |
| Registry-derived route sweep, light/dark, desktop/compact/390px | Passed before the final header refinement | `ui-tests/design-consistency.spec.mjs`; focused run: 16 passed |
| Sidebar column, heights and one-line labels at 1440/900/390px | Passed | Same focused run |
| Loaded PDF, real API, certificate inspector, Fit, select arrow and nonoverlapping action row at 1440/900/390px in both themes | Passed after the final header refinement | `ui-tests/pdf-editor-api.spec.mjs`; one desktop-project test runs all six combinations |
| PDF annotation editing, native-save adapter and unchanged original | Passed | Same real-API test; native picker/save are injected adapters |
| Final desktop route screenshot capture | 71 screenshots captured before WebKit exited during subsequent viewport resizing | `.test-artifacts/ui/design-consistency-*/visual-audit-*` |
| Node tests | 585 passed, 1 skipped; enforced licensing coverage 100% | `npm test` |
| macOS shortcut state tests | 42 checks passed | `npm test` |
| Python tests | 1,523 passed, 4 skipped; 1,653 subtests passed | `npm test` |
| Full browser rerun after final header refinement | Incomplete: 46 tests passed, then WebKit exited; subsequent launches aborted before opening a page | `.test-artifacts/test-ui-final.log` |
| Final package build | UI, sidecar and native executable compiled; DMG creation failed in both Tauri and the fallback with `hdiutil: create failed - Device not configured` | `.test-artifacts/build-final.log` |

The original full browser run had 256 passes and 20 skips, with two obsolete `select-bordered` assertions. Those assertions were updated for daisyUI 5 and passed in the 16-test focused run. That earlier run is not a green final full-suite result.

## Remaining acceptance work

Repeat the full browser suite when the WebKit launch preflight succeeds. The final attempt failed independently in `node scripts/ui-browser-preflight.mjs` with `Abort trap: 6`, including after the test processes stopped. Do not count cascading browser-launch failures as application behavior or silently mark them passed.

Rebuild and smoke-test the DMG after the macOS image-creation service works again. The earlier smoke-verified DMG predates the final header correction; it must not be described as the final artifact. The last build used an ad-hoc signature because the development signing identity was unavailable to that build.

Follow-up host diagnosis: the system crash report places the WebKit abort in macOS `_RegisterApplication` during `NSApplication` initialization, before OfficeKit loads. `launchctl print gui/502` fails with `141: Reentrancy avoided`; `diskutil image create from --help` cannot access the DiskManagement/DiskArbitration framework, and `security find-identity -v -p codesigning` returns zero identities. These independent checks establish a host session/service limitation. Restarting or logging out the user's session is outside this UI fix's automatic repair scope; preserve the open session and resume verification after those services are available.

The existing per-tool functional acceptance matrix remains separate. Route navigation and rendered dimensions do not prove all result, Copy, Download, permission and cancellation paths. Installed native interaction and actual browser zoom acceptance remain unverified by this report.

## Packaging recovery — 2026-10-16

The packaging fallback now handles the confirmed `Device not configured` creation failure by writing an HFS+ filesystem with `hdiutil makehybrid -hfs`, then converting it into a compressed UDZO image. The copied app's signature and final image checksum must verify before atomic publication. Other failures remain errors. Existing verified installers survive conversion or checksum failures.

Created `src-tauri/target/release/bundle/dmg/OfficeKit_1.0.0_aarch64.dmg` from the current app bundle. SHA-256: `9313ff14777507c34b1fcc81493a7cdf64aea22f5c4807368bfdf6621da1f51e`. The image checksum passes. All 28 focused packaging, smoke-contract and eject tests pass. The mounted-package smoke still stops at image attachment with `Device not configured`; this does not establish installed acceptance. The app remains ad-hoc signed and unnotarized.
