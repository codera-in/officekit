# PDF AES-256 Protector: password mismatch guidance

## Decision

A password or confirmation mismatch is a correctable field error. Keep both fields editable, show the mismatch beside the confirmation field, and do not offer Report bug for local validation. Keep Protect PDF disabled until the values match. After correction and a successful run, show the normal three actions: Copy summary, Download, and Protect PDF.

This keeps bug reports available for actual processing failures while preventing a user-correctable typo from looking like an application fault. It also avoids leaving a result dock visible for credentials that have changed.

## Reviewed mock

- `design/mocks/pdf-protect-password-confirmation.html` shows the former Report bug state, editable mismatch guidance, and the recovered result.
- Each frame declares its button count: 1, 1, and 3. `node scripts/check-mock-buttons.mjs design/mocks/pdf-protect-password-confirmation.html` passes.
- The mock was opened in a fresh Superset Browser tab and inspected. Its console had no captured errors; review capture: `docs/verification/tool-unification/mock/pdf-protect-password-confirmation-reviewed-20261102.png`.
