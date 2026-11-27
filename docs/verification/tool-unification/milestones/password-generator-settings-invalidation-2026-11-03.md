# Password Generator: invalidate stale secrets when settings change

## Finding

In installed OfficeKit 1.0.77, changing password length after generation left the old secret visible and its Copy action available. That makes the displayed settings disagree with the secret a user can copy. The installed build predates the current source changes, so this is recorded as the reproduction build, not as current-source behavior.

## Change

Changing password length or the Include symbols setting now clears a generated password and invalidates an in-flight generation. The screen explains that settings changed, keeps the new settings editable, and requires Generate again before Copy is available. A late generation response cannot restore a result created under the old settings.

## Evidence

- Reviewed state mock: [redacted screenshot](../mock/password-generator-settings-stale-state-review-20261103.png). The temporary HTML mock was removed after implementation.
- Current-source rendered after state: [password settings changed](../after/password_generator-settings-changed-source-20261103.png). The image contains no generated secret.
- Mock button-limit check: `node scripts/check-mock-buttons.mjs design/mocks/password-generator-settings-stale-state.html` passed before the temporary mock was removed (3/3 controls in the before state; 1/3 after).
- Focused regression tests: `node --test tests/password-generator-ui.test.mjs tests/password-generator-mock.test.mjs` passed 10/10.
- Source build: `npm run build:ui` completed successfully.
- Current-source runtime: generated a password, changed the length through keyboard input, and confirmed the secret and Copy action disappeared with the settings guidance. A real source API was used on a separate local port because the installed app's API rejected the source preview with 401. Password-symbol invalidation and recovery are covered by source handlers/tests, but were not separately repeated in the rendered runtime during this pass.

## Remaining verification

This check does not close the entire Password Generator audit. Clipboard contents, compact layout, keyboard traversal across every control, a matching installed build, and passphrase settings/recovery still need direct verification. The full app-wide 113-tool audit remains in progress.
