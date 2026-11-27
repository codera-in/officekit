# Global Launcher password options verification

## Source implementation checks — 2026-11-02

- Current source exposes a default password length of 8–128 characters (default 20) and an allowed-special-characters field (up to 32 unique ASCII punctuation characters). `pw 32` remains an explicit per-query length override; an empty symbol set produces letters and digits only.
- `node --test tests/global-launcher-password-options.test.mjs tests/global-tools-settings.test.mjs`: 9/9 passed. These checks cover the controls, persistence wiring, native settings fields, quick-result option forwarding, and launcher button cap.
- `cargo test --manifest-path src-tauri/Cargo.toml launcher_password_options_are_bounded_and_allow_an_empty_symbol_set`: 1/1 passed.
- `npm run test:macos-global`: all macOS global-logic tests passed, including requested lengths 8/20/128, required character classes, custom symbol restriction, empty-symbol output, duplicate-symbol rejection, and length bounds. The generated password is not included in this note or screenshot evidence.

## Installed app gap

OfficeKit 1.0.77’s Global Launcher settings screen exposes the Password generator toggle but does not show the Default length or Allowed special characters fields. The visible toggle help also lacks the current source’s “Add a length to override the default” wording. Therefore the installed UI does not yet prove the requested options end to end, despite the current source and native generation tests passing.

The installed settings screen was inspected in the running app; its capture could not be persisted with the available desktop capture interface. The reviewed before/after proposal is retained at `mock/global-launcher-password-options.png`. Installed/current-build UI parity and an end-to-end generated-password alphabet check remain open.
