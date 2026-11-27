# PDF Password Remover milestone — 2026-11-03

## Scope and build

Verified the current source UI served from `dist-ui` through the isolated source/API preview. This is browser-source evidence only; it does not establish installed-app parity. Fixture: a disposable 1,360-byte encrypted PDF, `source_protected.pdf`.

## Observed flow

- Empty state offers Unlock PDF and Select PDFs.
- Selecting the fixture shows its name and size and keeps the source selected after errors.
- A wrong password shows inline correction guidance, keeps Unlock PDF available for retry, and does not show Report bug or stale Protect PDF result actions.
- Retrying with the fixture password produces `source_protected_unlocked.pdf` (692 bytes). Its bytes begin with `%PDF-`; an independent page-count request reopens it and reports one page. The source remains `source_protected.pdf` (1,360 bytes).
- The recovered screen shows the PDF Password Remover title, output-ready status and three actions: Copy summary, Download, Select PDFs.

Screenshots:

- Before: `before/pdf_unlock-current-source-empty-20261103.png`
- Selected fixture: `after/pdf_unlock-current-source-input-ready-20261103.png`
- Wrong-password recovery: `after/pdf_unlock-wrong-password-source-20261103.png`
- Recovered output: `after/pdf_unlock-recovered-output-source-20261103.png`

Copy and Download were visible in the recovered state but their browser adapters were not independently exercised in this milestone. Native save behavior, compact viewport, keyboard/focus flow and installed-build parity remain open.

## Checks

- `pytest -q tests/test_pdf_endpoints.py -k unlock` — 3 passed.
- `node --test tests/pdf-unlock-bundle.test.mjs tests/pdf-workbench-ui.test.mjs` — 29 passed.
- `node --check ui-tests/pdf-protect.spec.mjs` — passed.
- `git diff --check` — passed.
- `node --test tests/pdf-tools-ui.test.mjs tests/pdf-tools-shell-wiring.test.mjs` — failed in a separate stale source contract at `tests/pdf-tools-ui.test.mjs:856`; it expects an older PDF operation list and does not assert the Password Remover behavior above.
