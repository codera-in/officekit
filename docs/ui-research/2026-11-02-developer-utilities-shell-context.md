# Developer Utilities shell context

## Decision

When a specialized tool is open inside the converter workspace, hide the generic “Convert a file” intro and the unrelated “Open Media Toolkit” link. Keep the specialized panel heading and its existing shared action dock. Generic file conversion continues to show its own intro and the Media Toolkit link.

This avoids showing navigation and descriptions for a different destination above the active tool. The result dock already has an operation-specific title; the change keeps the rest of the page shell aligned with it.

## Evidence

- Installed OfficeKit 1.0.77 showed “Convert a file” and “Open Media Toolkit” above Developer Utilities, while the dock incorrectly said “Media Toolkit.” The installed build also showed Report bug for malformed JSON; current source already has a regression for suppressing that local validation CTA.
- Reviewed the before/after mock in a new Superset Browser tab. Button counts: 3/3 in both states. Review image: `docs/verification/tool-unification/mock/developer-utilities-shell-context-review.png`.
- Current-source UI was served from the rebuilt worktree to the Superset Browser. In Developer Utilities mode, `#converter-general-intro` and `#open-media-toolkit` are hidden, the tool panel and action dock are visible, and the dock title is “JSON & YAML Formatter.” Captures: `docs/verification/tool-unification/before/developer-utilities-shell-context-source-reproduction.png` (old visibility reproduced) and `docs/verification/tool-unification/after/developer-utilities-shell-context-source.png`.
- `node --test tests/developer-utilities-ui.test.mjs` passes 21/21; the mode-visibility behavioral regression passes; `npm run build:ui` passes.

## Limits

The source UI preview could not reach the local API because it is served outside the Tauri authenticated origin. This pass verifies rendered shell visibility and existing source contracts; it does not reverify current-source JSON API output, clipboard or save dialogs. Installed 1.0.77 still exhibits the old shell and validation CTA until a newer app bundle is installed.
