# PDF Editor compact layout implementation

The approved compact editor uses Mode, Tool, View and History selectors; keeps the page number field reachable; replaces page-navigation buttons with those controls; and stacks the inspector in the page flow. Replace PDF is a link beside the three task actions, preserving the three-button cap. The specialized annotation canvas remains intact.

Reviewed mock screenshot: `docs/verification/tool-unification/mock/pdf-editor-loaded-compact-action-cap-review-20261031.png`. Existing empty compact source capture and limitations are recorded in `docs/ui-research/tool-unification-todo.md` (2026-10-30 PDF Editor compact current-source capture). A fresh loaded source screenshot is not claimed because Playwright browsers abort before page setup on this machine.

Verification: `node --test tests/pdf-editor-ui.test.mjs` passes 6/6; `node --check ui-tests/pdf-editor.spec.mjs` passes; Playwright lists the new loaded compact regression in desktop and compact projects; `npm run build:ui` and `git diff --check` pass. The loaded compact test was not run. Installed editing/export/signing, native save, keyboard and live compact behavior remain open.
