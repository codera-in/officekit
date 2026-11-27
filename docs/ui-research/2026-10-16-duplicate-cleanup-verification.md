# Duplicate cleanup and shared hierarchy verification

Approved decision: `docs/ui-research/2026-10-16-approved-duplicate-cleanup.md`, mirrored in `review/duplicate-cleanup/requirements.md`. Current dirty worktree, development profile: 50 tools and 21 shell destinations.

## Rendered evidence

Superset Browser (Chromium) loaded the current built UI against an isolated authenticated local API. The API/native picker fixture used disposable files. Native Copy/Save were injected adapters; the developer's clipboard and files were not changed.

- All 71 destinations at 1440px, 900px and 390px in light/dark: 426 route checks passed for 28px page titles, heading weight and page overflow. Evidence: `.test-artifacts/tool-hierarchy-evidence.json`.
- Duplicate Finder: actual API scan displayed two file rows, identified `invoice.pdf` as the retained file, selected one copy, placed actions after the table, and opened confirmation with focus on Cancel. The main Trash button uses `btn btn-outline`. Cancellation sent no mutation. A confirmed request sent one opaque copy ID; a synthetic 422 error surfaced correctly, and rescanning recovered the unchanged fixture.
- Real API loan EMI: $1,200 at zero interest over one year returned $100.00 per month. Result actions were the last child of the result and in document flow.
- Shared computed, text and binary result publishers retained their content and rendered actions after it, in document flow.

These Chromium observations do not establish a passing WebKit run. `node scripts/ui-browser-preflight.mjs` still fails at browser launch with `Abort trap: 6` before OfficeKit loads. Browser regressions were added to the existing suite for the new requirements.

## Engine and HTTP evidence

136 focused tests pass across `test_duplicate_trash_unittest.py`, `test_direct_file_api.py`, `test_file_jobs_unittest.py` and `test_api_contract_unittest.py`, plus 8 subtests. They cover selected-only moves, retained files, changed keepers/copies, symlink replacement, expired scans, unknown/duplicate/oversized IDs, scan/selection ownership, read-only/revoked authority, native-service partial failure and consumed selection authority. The HTTP test exercises scan → rejection of every-file selection → rejection of read-only authority → selected-copy cleanup → complete report using a synthetic Trash directory.

The broader `npm test` run passed 589 Node tests (one skip), 42 macOS shortcut checks, and 1,529 Python tests (four skips), but failed one HEIC similar-image matching test: it grouped an unrelated fixture with a matching pair. That matching engine was not modified by this change. The full suite is therefore not recorded as green.

## Release limits

The final app/sidecar and Apple Silicon DMG were rebuilt from this source on 2026-10-16. The fallback installer creation and image checksum verification succeeded. DMG SHA-256: `086585d92a171aac35a9ca0214aff92b5499395c6d1e8171fd9f671c37c68272` (211 MB). The app is ad-hoc signed and unnotarized. Mounted-package smoke remains limited by this session's unavailable disk-image attachment service. Real native picker, Trash and installed-window acceptance remain distinct from the injected adapters and disposable-fixture checks above.

The packaged backend smoke was also run. It started successfully but failed the same HEIC similarity check as the broader Python suite: an unrelated image was grouped with a matching pair. Log: `.test-artifacts/duplicate-cleanup-sidecar.log`. This is an outstanding Find Similar Images failure; do not describe the complete sidecar smoke as passed.
