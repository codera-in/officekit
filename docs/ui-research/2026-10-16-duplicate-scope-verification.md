# Duplicate scope and result navigation verification

2026-10-16. Implements `2026-10-16-approved-duplicate-scope.md` after the user's “approved”.

## Verified behavior

- Direct-folder default excludes nested files; explicit recursive scope includes them. Neither mode follows external file/directory symlinks. Invalid boolean options fail DTO validation.
- Native-picked folder locations include the folder prefix. Duplicate entries carry modification dates for display and sorting.
- Name/date/size sorts operate on whole groups, keeping the scan's original keeper. Date sort uses the latest group timestamp. Pagination counts groups, supports 10/25/50/100 per page, resets on sort/page-size changes and preserves selected IDs across pages.
- Select all duplicates spans the full report, retaining one file per group and preserving the existing 10,000-copy batch bound. Clear selection spans every page.
- A bounded scrollable table keeps selection, pagination and report/Trash actions reachable. Compact widths use a shorter list so wrapped actions remain visible. Light/dark desktop and compact screenshots were inspected.
- Changing scan scope hides the old report and requires a fresh scan. Explicit Trash confirmation, read-write native authority, verified file identities, retained originals and complete report exports remain intact.

## Checks

- `npm run build:ui`: pass.
- `npm test`: 592 Node tests passed, one skipped; 1,541 Python tests passed, four skipped; 1,653 subtests passed; macOS hotkey harness passed. Configured Node coverage gates passed.
- Focused duplicate/selection/jobs/API tests: 126 passed. The default-scope regression failed against the old recursive behavior before implementation.
- Final `npx playwright test ui-tests/workspace-files.spec.mjs`: 12 passed across desktop/compact WebKit. Workspace plus production CSP navigation run: 18 passed before the final compact-height adjustment; workspace tests passed again after that adjustment.
- Standard-library coverage.py run: 65 focused backend tests passed; new scope/options/metadata executable lines were covered. pytest-cov is not installed, so coverage.py was used directly.
- `git diff --check`: pass.

Screenshot artifacts are generated under `.test-artifacts/ui/workspace-files-duplicate--1ced3--selection-across-all-pages-{desktop,compact}-webkit/duplicate-pagination-{light,dark}.png`.

## Review and limits

Self-review checked strict API input validation, no arbitrary paths in cleanup requests, unchanged native authority/identity checks, no network or dependency additions, stable keeper identity, bounded selection/report resources, no new database/tenant surface, accessible control labels, and no overlapping action controls. Existing unrelated worktree changes were preserved. Temporary approved mock/preview files were removed and the preview server was stopped.

This verifies source and built web assets against the local API. The installed desktop app and packaged sidecar were not rebuilt or replaced; installed behavior remains separate acceptance. No developer files were moved to Trash.
