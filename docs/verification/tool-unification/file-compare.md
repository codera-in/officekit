# Compare two files verification

## Current source change

The page heading and Run action now use the catalog name “Compare two files,” matching the tool action title. The result continues to label File A and File B and reports the first differing byte.

## Evidence

- Reviewed title mock before/after captures: `docs/verification/tool-unification/mock/file-compare-tool-title-review-current-20261031.png` and `docs/verification/tool-unification/mock/file-compare-tool-title-after-review-current-20261031.png` (2/3 actions per frame).
- Current-source screenshots: `docs/verification/tool-unification/after/file_compare-initial-aligned-title-current-source-20261031.png` and `docs/verification/tool-unification/after/file_compare-result-aligned-title-current-source-20261031.png`.
- Installed 1.0.77 native files: `left.txt` (15 bytes, `alpha\nbeta\nend\n`) and `right.txt` (16 bytes, `alpha\ngamma\nend\n`). Result said “Files differ · first difference at byte 6,” showed the changed line and valid UTF-8/LF metadata. The saved `file-result.json` is 646 bytes and reports the same sizes, offset, and diff hunk; both originals remained unchanged. Copy confirmed in the app; native clipboard bytes were not read back.
- Focused Files UI suite passes 59/59. The real-folder Playwright scenario is recorded in `ui-tests/workspace-files.spec.mjs`; browser launch is currently unavailable on this machine (WebKit and Chrome abort before test setup).
- Installed 1.0.77 still shows the old “Compare files” heading/run label and the stale “PDF workbench” footer/actions. The current-source title and dock screenshots are from the source app, not the installed bundle; a matching installed build and a persisted native screenshot remain open.
