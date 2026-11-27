# Reusable themed date picker

## Approved decision

Use one themed, keyboard-operable calendar for OfficeKit date fields. Keep the original date inputs, IDs, ISO values, bounds, native text entry, and tool-specific validation/results. Localize calendar labels, use shared light/dark design tokens, and hide stale result actions while the calendar is open. Selecting a date dispatches the existing input/change events so each tool refreshes its own result and actions.

The reviewed mock was `design/mocks/reusable-themed-date-picker.html`. It showed the native-versus-shared comparison, dark and light tools, and the recovered result state. The mock passed the three-button checker and was inspected in a fresh Superset Browser tab. Its temporary HTML was removed after review.

## Evidence and limits

Implementation: `assets/officekit-date-picker.js` and `assets/officekit-date-picker.css`; calculator date fields and dynamic file-date options use the same component. `tests/date-picker.test.mjs` covers strict ISO parsing, locale week layout, shared-field wiring, accessibility hooks, and lifecycle cleanup.

Current-source captures: `docs/verification/tool-unification/after/date-picker-dark-current-source-20261031.png`, `date-picker-light-age-current-source-20261031.png`, and `date-picker-light-age-recovered-current-source-20261031.png`.

Focused date-picker/calculator suites pass (48 tests), `npm run build:ui` passes, and `git diff --check` passes. Installed native picker behavior, compact-window placement, and screen-reader interaction remain to be checked on a platform run.
