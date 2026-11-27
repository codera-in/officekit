# Bank Statement Extractor: invalid file recovery

## Reviewed behavior

The invalid-file mock keeps the statement page open, explains how to correct a malformed PDF, and leaves the file picker available as “Choose another statement.” It removes the generic crash dialog and bug-report action for correctable file errors. A valid retry returns to the shared three-action result dock.

Mock: `design/mocks/bank-statement-invalid-input-recovery.html`

Reviewed mock captures: `mock/bank-statement-invalid-input-recovery-reviewed-20261102.png` and `mock/bank-statement-invalid-input-recovery-reviewed-20261102-bottom.png`

Current-source error-state capture: `after/bank_statement-invalid-input-current-source-20261102.png`

## Verification

- Installed OfficeKit 1.0.77 accepted the synthetic statement PDF and extracted the expected Coffee Shop debit of 25.00 with ending balance 975.00. CSV save completed and the saved content matched the extracted rows.
- The installed build showed the generic “This operation didn’t finish” dialog and offered Report bug for a malformed local PDF. Its bottom dock also retained a stale SHA-512 summary from the prior tool. The installed build is older than this worktree (1.0.76), so it does not verify this patch.
- Current-source simulation returned the file-specific inline guidance, retained the file chooser, marked the error as local/correctable, and kept the shared dock scoped to Bank Statement Extractor.
- `node --test tests/statement-corrections-ui.test.mjs tests/statement-locale-controls-ui.test.mjs tests/statement-copy-scope.test.mjs`: 12 passed.
- `pytest -q tests/test_e2e_api.py -k statement`: 19 passed, 43 deselected, 15 subtests passed.
- `node scripts/check-mock-buttons.mjs design/mocks/bank-statement-invalid-input-recovery.html`: passed.
- The Playwright WebKit process aborted before test setup (exit 134); no browser assertions ran.

## Remaining checks

Verify this exact build in the installed app, confirm the dock refreshes after switching tools, and capture the corrected and recovered states in a full, unclipped source screenshot. Compact, keyboard, native save, and accessibility checks remain open.
