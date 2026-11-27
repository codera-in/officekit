# Merge PDFs: readable sizes

**Milestone:** Merge PDFs, one tool per commit.

The PDF workbench showed valid small input files and merged output as `0.00 MiB`. The Merge PDFs rows and output summary now use the shared file-size formatter, which displays byte counts below 1 KiB and KiB below 1 MiB. File ordering and the result action dock do not change.

**Evidence:** `design/mocks/pdf-merge-readable-sizes.html` and its reviewed Superset Browser capture at `docs/verification/tool-unification/mock/pdf-merge-readable-sizes-review-20261102.png`.

**Automated check:** `node --test tests/pdf-merge-readable-sizes.test.mjs`; mock button limit: `node scripts/check-mock-buttons.mjs design/mocks/pdf-merge-readable-sizes.html`.

**Remaining:** The source UI does not currently produce a post-fix screenshot because the available Playwright WebKit runtime aborts before test setup. Installed native save behavior, compact layout, and keyboard checks remain open.
