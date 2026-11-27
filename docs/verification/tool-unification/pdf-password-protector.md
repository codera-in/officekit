# PDF AES-256 Protector verification

## Installed run — 2026-11-02

OfficeKit 1.0.77 protected a synthetic one-page 300 × 400 pt PDF titled `Synthetic password protector audit`. Reopening the saved output with `pikepdf` verified that it is encrypted, still has one page, and preserves its title. The plain input stayed unchanged.

With a mismatched confirmation, the fields stayed editable and the Protect PDF action disabled. The installed app also showed Report bug for “Passwords do not match.” After correcting the confirmation, Protect PDF recovered and produced the expected encrypted output. The mismatch state retained the old result summary and Copy / Download actions. A generic invalid-PDF error and a stale SHA-512 footer from the earlier tool also persisted. The installed 1.0.77 build showed the 634-byte source as `0.00 MiB`.

## Current-source change and evidence

- The local password-confirmation message now carries `data-officekit-no-bug-report`, so the global observer does not add a bug-report action to a correctable typo. Genuine PDF processing errors keep their existing reporting path.
- The reviewed three-state mock is `design/mocks/pdf-protect-password-confirmation.html`; its Superset Browser capture is `mock/pdf-protect-password-confirmation-reviewed-20261102.png`.
- Existing source captures `before/pdf_protect-initial-branch-baseline-superset.png` and `after/pdf_protect-current-source-desktop-superset.png` show the empty-form layout. They do not show this exact mismatch/recovery fixture. The installed states were inspected live but the native screenshot API did not persist them.
- `node scripts/build-ui.mjs` regenerated the packaged UI and its CSP hash for the current worktree.
- `node --test tests/pdf-workbench-ui.test.mjs tests/ui-csp.test.mjs tests/ui-build.test.mjs`: 39/39 passed.
- `pytest -q tests/test_pdf_endpoints.py -k protect`: 6 passed, 77 deselected.

The mock button checker passes at 1/3, 1/3, and 3/3. Exact clipboard bytes, keyboard/focus, compact layout, and installed/current-source parity remain open.

## Current-source output-size correction — 2026-11-03

The successful Protect PDF result still formatted files under 1 MiB with two decimal MiB, so a small result could read `0.00 MiB`. The shared PDF workbench now uses `OfficeKitFormatters.fileSize` for Protect output. A 1,360-byte result renders as `1.3 KiB`, consistent with the shared file-size format. The reviewed mock shows this recovered result and is captured at `mock/pdf-protect-password-size-reviewed-20261103.png`.

- `node --test tests/pdf-protector-output-size.test.mjs tests/pdf-workbench-ui.test.mjs`: 30/30 passed.
- `pytest -q tests/test_pdf_endpoints.py -k protect`: 6 passed, 77 deselected.
- `npm run build:ui` succeeded.
- The source UI has not been exercised through the native app for this result state. The Playwright regression remains pending; the desktop app has no attachable window in this session. Native save, clipboard, compact and keyboard checks remain open.

## Current-source result visibility — 2026-11-03

The real source UI was exercised with a 626-byte synthetic `source.pdf` and matching password `safe-passphrase-42`. A mismatch between the new password and confirmation kept both fields editable, marked the confirmation field invalid, disabled Protect PDF, and did not offer Report bug. Matching passwords produced `source_protected.pdf` at 1,360 bytes (1.3 KiB). The selected source remained unchanged.

The first live result capture showed the output preview below the sticky dock. The PDF workbench refreshed password-field guidance after completing the task, which canceled the earlier scroll. Result reveal now runs after that refresh and uses immediate end alignment for password operations. The preview now ends at y=846 px, directly above the dock at y=846 px. The dock title is PDF AES-256 Protector and the three actions are Select PDFs, Copy summary, and Download. Copy summary reads exactly `PDF AES-256 Protector\nOutput: source_protected.pdf\nSize: 1.3 KiB`.

Before/invalid/after source screenshots are `before/pdf-protect-result-hidden-by-dock-source-20261103.png`, `after/pdf-protect-mismatch-source-live-20261103.png`, and `after/pdf-protect-result-visible-above-dock-source-20261103.png`. Empty and selected source states are also saved under `before/` and `after/`. The reviewed proposal is `mock/pdf-password-protector-result-reveal-review-20261103.png`; its temporary HTML mock passed the three-button checker and was removed after implementation.

- `node --test tests/pdf-protect-result-reveal.test.mjs tests/pdf-unlock-result-reveal.test.mjs tests/pdf-workbench-ui.test.mjs tests/pdf-unlock-output-size.test.mjs`: 31/31 passed.
- `pytest -q tests/test_pdf_endpoints.py -k protect`: 6 passed, 77 deselected.
- `npm run build:ui`, `node --check ui-tests/pdf-protect.spec.mjs`, the mock button-limit checker, and `git diff --check` pass.
- Playwright WebKit aborts at browser launch (Abort trap 6), before its API-backed end-to-end test starts. Native download, compact, keyboard and installed-build checks remain open.
