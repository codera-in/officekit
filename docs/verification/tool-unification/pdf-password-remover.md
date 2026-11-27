# PDF Password Remover verification

## Installed run — 2026-11-02

Tested in OfficeKit 1.0.77 with a synthetic one-page encrypted PDF (300 × 400 pt; title `Synthetic password removal audit`; R6 encryption). The known password was `safe-passphrase-42`.

The valid password produced `encrypted_unlocked.pdf`; the native Save dialog reported success. Reopening the saved file with `pikepdf` verified it is no longer encrypted, has one page, preserves its title, and leaves the encrypted source intact.

The wrong-password path displayed “Incorrect password. Please enter the valid password provided by your bank or institution.” with a Report bug button. After restoring the correct password, the successful output returned, but the prior generic “The PDF file is invalid or the requested operation is unsupported” error and Report bug action remained visible. That generic error first appeared on an earlier selected invalid PDF and persisted after removing it, changing tools and successfully unlocking this synthetic file. On return to File Age Finder, the shared footer still showed the checksum tool’s SHA-512 result and Copy report / Download actions.

This leaves competing feedback, stale output actions and multiple Report bug actions on the PDF screen; it exceeds the three-button screen limit. The installed build also rounds the 1 KB input and output to `0.00 MiB`. These are installed 1.0.77 observations; they do not establish that the current source has the same behavior.

## Current-source checks and screenshots

- `node --test tests/pdf-workbench-ui.test.mjs`: 28/28 passed. The suite checks that a known-password rejection is correction guidance, not an app bug.
- `pytest -q tests/test_pdf_endpoints.py -k unlock`: 3 passed, 80 deselected.
- Historical source captures: `before/pdf-before-pdf-password-flow-uses-the-real-api-produces-an-encrypted-copy-and-verifies-unlock-output-desktop-webkit.png` and `after/pdf-regression-pdf-password-flow-uses-the-real-api-produces-an-encrypted-copy-and-verifies-unlock-output-desktop-webkit.png`. The pair is useful for the form/result layout but does not match the synthetic fixture used in this installed run. A current-source empty-state capture is `after/pdf_unlock-current-source-desktop-superset.png`.
- The installed success and error screens were inspected live; the available native screenshot interface did not persist them.

Exact clipboard contents, keyboard/focus, compact layout, save cancellation and current-source installed parity remain open.

## Follow-up: readable selected-file size (2026-11-02)

The installed screenshot and the reviewed wrong-password mock both expose the selected PDF size; the mock shows `1 KB`, while the installed 1.0.77 build rounds the same small input to `0.00 MiB`. The shared PDF workbench now uses `OfficeKitFormatters.fileSize()` for every selected PDF, including Unlock. `node --test tests/pdf-workbench-ui.test.mjs tests/pdf-unlock-bundle.test.mjs` passes 30/30, including the 1-byte, 1,023-byte, 1,024-byte and MiB boundary labels. `pytest -q tests/test_pdf_endpoints.py -k unlock` passes 3/3, and `npm run build:ui` succeeds. A fresh rendered screenshot of the selected Unlock file remains open because CUA could not attach to Chrome/Paradev during this pass; the 1 KB mock and installed 1.0.77 capture are not current-source after evidence.

## Current-source output-size correction — 2026-11-03

The successful unlock result also used the legacy two-decimal MiB label, so a 692-byte output could read `0.00 MiB`. The shared PDF workbench now formats Password Remover output with the shared file-size formatter; 692 bytes displays as `692 bytes`. The before/after mock was inspected in a fresh Superset Browser tab, with the reviewed capture at `mock/pdf-unlock-output-size-reviewed-20261103.png`. Both mock states show the title-correct shared dock with three actions.

- `node --test tests/pdf-unlock-output-size.test.mjs tests/pdf-workbench-ui.test.mjs`: 30/30 passed.
- `pytest -q tests/test_pdf_endpoints.py -k unlock`: 3 passed.
- UI build and live source result flow remain to verify; the source desktop app could not open a visible window in this session. Native save, clipboard, compact and keyboard checks remain open.

## Current-source recovery and result visibility — 2026-11-03

The unlock flow was replayed in a fresh Superset Browser source tab with a 626-byte synthetic PDF protected using `safe-passphrase-42`. Entering `wrong-passphrase` in the visible **Known PDF password** field produced the expected inline correction guidance, retained the value, and offered no Report bug or stale result action. Retrying with the known password produced `source_protected_unlocked.pdf` at 692 bytes. Copy summary placed exactly `PDF Password Remover\nOutput: source_protected_unlocked.pdf\nSize: 692 bytes` on the clipboard, and the dock showed exactly three actions: Select PDFs, Copy summary, and Download.

The first recovered screenshot exposed a real viewport issue: the result preview remained below the sticky dock because its reveal was deferred to `requestAnimationFrame`, which did not run while the browser pane was backgrounded. The helper now scrolls immediately while preserving reduced-motion behavior. Replaying the valid flow placed the preview at y=768–846 px above the dock at y=846 px. Same-size before/after captures are `before/pdf-unlock-result-hidden-by-dock-source-20261103.png` and `after/pdf-unlock-result-visible-above-dock-source-20261103.png`; the invalid retry state is `after/pdf-unlock-invalid-source-live-20261103.png`.

The reviewed layout proposal is captured at `mock/pdf-password-remover-result-reveal-review-20261103.png`; the corresponding temporary mock passed the three-button checker and was removed after implementation.

- `node --test tests/pdf-workbench-ui.test.mjs tests/pdf-unlock-output-size.test.mjs`: 30/30 passed.
- `node --test tests/pdf-unlock-result-reveal.test.mjs`: immediate scroll, end alignment and reduced-motion behavior pass.
- `pytest -q tests/test_pdf_endpoints.py -k unlock`: 3 passed, 80 deselected.
- `npm run build:ui`, `node --check ui-tests/pdf-protect.spec.mjs`, the mock button-limit checker, and targeted `git diff --check` pass.
- The real WebKit flow remains blocked before test setup: Playwright's bundled WebKit exits with Abort trap 6 at launch. The source browser flow and Copy contents were verified directly; a successful download event, compact/keyboard behavior, and installed build parity remain open.

## Installed 1.0.77 retry and export — 2026-11-03

I repeated the native run using a fresh one-page encrypted 300 × 400 pt fixture with a known test password and title `OfficeKit Installed Unlock Fixture`.

- Selecting the PDF succeeded. Its 1,413-byte size appeared as `0.00 MiB` in this installed build.
- An incorrect password showed correction text, but also exposed **Report bug**. Retrying with the correct password succeeded and cleared that error action.
- The result was `officekit-unlock-installed-fixture_unlocked.pdf` (700 bytes). Copy summary was pasted into a temporary TextEdit document and verified as:
  `PDF output\nOutput: officekit-unlock-installed-fixture_unlocked.pdf\nSize: 700 bytes`.
- Download saved `officekit-unlocked-installed-output.pdf` in `/tmp`. Independent `pikepdf` inspection confirmed the saved file is unencrypted, one page, 300 × 400 pt, with the source title preserved.
- In 1.0.77, the shared bottom dock still says `PDF workbench` and keeps an `Unlock PDF` action after success. The intended current-source flow uses the specific PDF Password Remover title and success actions. This is installed-build lag: the current source and `dist-ui` bundle regression verifies that incorrect passwords do not offer Report bug; `node --test tests/pdf-unlock-bundle.test.mjs tests/pdf-workbench-ui.test.mjs` passes 29/29.

The native CUA interface did not provide a supported way to persist its screenshot bytes locally. The current-source before/invalid/recovered screenshots remain linked above; they are not labeled as captures of this 1.0.77 run. A matching installed build, native screenshot persistence, compact/keyboard flow, and save cancellation remain open.
