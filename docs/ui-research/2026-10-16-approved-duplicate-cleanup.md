# Duplicate cleanup and shared tool hierarchy

Approved 2026-10-16. The before/after mock was `design/mocks/duplicate-finder-review.html`, opened in a new Superset Browser tab and inspected in light/dark themes, including selection and confirmation. The temporary mock is removed after approval under the repository's mock-review workflow.

User approval: “looks good to me”. Scope extension: “follow the same for all tools”. Color correction: “button colors look bit odd ‘move selected to trash’”.

## Approved behavior

- All tool page titles use the existing 28px title token and clear heading weight.
- Task controls follow input settings. Result Copy/Download/Save controls follow the output. They must not be prepended above results or float across result rows.
- Duplicate Finder shows one file per table row, identifies a retained file in each group, and offers individual checkboxes, Select copies and Clear selection.
- The bottom completion area includes the selected count and Move selected to Trash. The main Trash button uses the same neutral outline treatment as secondary actions. The explicit final confirmation uses a restrained error outline and starts focus on Cancel.
- No file moves on scan, selection or cancellation. At least one verified file remains in every group. Cleanup is bound to the original scan, selected file identities and a native read-write grant. Changed files, expired/revoked authority and invalid IDs fail safely. Partial failures are reported per file.
- Cleanup currently uses the existing macOS Trash implementation; unsupported platforms retain scan/report and disclose the unavailable move action. Limit each move request to 10,000 selected copies and explain batch behavior when necessary.
- After a cleanup attempt, consume the original selection and prompt for fresh picker authority. This avoids rescanning stale individual-file roots after their selected copies moved.

## Verification

Engine regressions use disposable directories and an injected Trash adapter. Browser confirmation tests reject the actual mutation request and verify unchanged fixtures. Native scan/browser checks use disposable files only; they do not clean the developer's Downloads or Trash.

Route hierarchy checks must enumerate the authenticated registry and inspect desktop, compact and phone widths in both themes. An empty-route geometry pass is not evidence of a complete tool result flow. Report native installed acceptance and browser-engine limitations separately.
