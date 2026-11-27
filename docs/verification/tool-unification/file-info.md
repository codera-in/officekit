# File Info verification

## Current source change

The result summary now uses “1 file” for one inspected item and “N files” for multiple items. This is a copy-only correction; the shared Copy report and Download actions stay unchanged.

## Evidence

- Before result screenshot: `docs/verification/tool-unification/after/file_info-result-tool-scoped-dock-source-20261031.png` (shows the former “1 files” wording).
- Reviewed before/after mock capture: `docs/verification/tool-unification/mock/file-info-singular-summary-reviewed.png`. Each frame shows the same two result actions; `scripts/check-mock-buttons.mjs` passes and the Superset console was empty. The temporary mock HTML was removed after review.
- Source regression: `node --test --test-name-pattern='File Info summary uses singular' tests/files-tools-ui.test.mjs` passes 1/1; `node --test tests/files-tools-ui.test.mjs` passes 59/59.
- File inspection API: `pytest -q tests/test_file_inspect_api.py` passes 27/27.
- Installed 1.0.77 native selection: a 32-byte `notes.txt` returned one file, timestamps, `rw-------` permissions and 32 total bytes. Copy showed confirmation; Download opened the native Save dialog and the saved JSON was checked for the full metadata record. The saved test filename includes the dialog’s default base name because the automation replaced only its selected stem; this was an input-method artifact.
- Installed 1.0.77 still shows “Include subfolders” for the single-file selection, “1 files,” and the stale “PDF workbench” footer. Current source already hides the folder option for one selected file; the corrected singular count is covered by the source test. The installed screenshot was inspected in-session but could not be persisted with the available native capture APIs.

Compact and keyboard interaction, exact OS clipboard bytes, a fresh rendered current-source result screenshot, and matching installed-build behavior remain open.
