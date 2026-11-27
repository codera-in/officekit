# Password Generator result actions — 2026-11-03

## Change

The password and passphrase result use the same catalog title, while the Copy label names the result type. The shared result action writer no longer receives a file format for generated credentials, and the generated-secret Download control is explicitly hidden. Generate again and Clear remain available beside the settings. The page is capped at three visible actions.

This keeps a generated secret out of a newly created file. Copy remains an explicit action, and the screen continues to say that generation has not saved the secret.

## Evidence

- `pytest -q tests/test_password_generator_unittest.py`: 15 passed, 34 subtests passed.
- `node --test tests/password-generator-ui.test.mjs`: 6/6 passed. The UI contract asserts the stable title and hidden Download action.
- Mock button check passed for `design/mocks/password-generator-secret-result-actions.html`; reviewed in a fresh Superset Browser tab. Screenshot: `docs/verification/tool-unification/mock/password-generator-secret-actions-review-20261103.png`.
- Before screenshot: `docs/verification/tool-unification/before/password_generator-initial-desktop-webkit.png`.
- A loaded-result Playwright attempt did not reach the page: Chrome aborted during launch at the macOS Crashpad child-port handshake (exit signal `SIGABRT`, code 141). No product interaction result is inferred from that attempt.
- The installed OfficeKit window was not attachable through CUA (`cgWindowNotFound`), so installed Copy and native clipboard behavior remain unchecked.

## Remaining checks

Verify the current installed build, keyboard/focus flow, and actual Copy behavior when the desktop window is reachable. The screenshots above are mock/source evidence and do not prove installed behavior.
