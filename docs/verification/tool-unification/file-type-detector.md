# File Type Detector verification

## Source change

Results now show each inspected file as a readable fact card: size, extension, detected type, MIME type, and whether the extension matches. A mismatch is written as “No,” and the result explains that signature detection is not malware scanning. The shared result actions retain the complete JSON payload.

## Evidence

- Before: [empty state](before/file_type-initial-desktop-webkit.png)
- After: [readable result cards](after/file_type-result-readable-cards-source-20261031.png)
- Source UI tests: `node --test tests/files-tools-ui.test.mjs` — 58 passed.
- File type engine/API checks: 11 engine tests plus 28 subtests, and 1 API test plus 14 subtests passed.
- Installed app 1.0.77: tested text, empty, PDF, and JPEG-signature files (including JPEG data named `photo.png`). Detection, Copy, and JSON download returned the expected data. This installed build still renders the older raw table and leaves “PDF workbench” in the global footer.
- Current-source Playwright screenshot test could not launch either WebKit or Chrome in this environment (WebKit abort trap; Chrome crashpad abort) before test setup. No new automated screenshot was produced in this run.

The installed-build mismatch remains open for packaged-app verification after the source build is refreshed.
