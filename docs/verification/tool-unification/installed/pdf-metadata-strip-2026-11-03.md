# PDF Metadata removal verification — 2026-11-03

## Installed app run

- App version: 1.0.77.
- Input: checked-in `tests/fixtures/pdf-protect-source.pdf` (626 bytes), one page, title `OfficeKit PDF test fixture`.
- Action: Remove metadata.
- Result preview: `pdf-protect-source_metadata-removed.pdf · 0.00 MiB · source unchanged`.
- Copy summary: succeeded and displayed `Copied to clipboard.`
- Download: saved as `/tmp/officekit-metadata-removed.pdf`; app displayed the saved filename.
- Output validation: the original retained `/Title: OfficeKit PDF test fixture`; the downloaded output had no standard document-info fields, no XMP metadata, and retained one page.

## UX finding

The installed 1.0.77 result state showed `Select PDFs`, `Copy summary`, and `Download` in the page body while the fixed dock still showed `Create cleaned PDF`. That makes four visible actions and leaves a stale primary action after success. The UI also rounded the small output size to `0.00 MiB`.

The current source hides the workbench run action after a binary result exists. The shared result-action dock then owns the result actions and the file-selection task action, keeping the screen within the three-button limit. The output size uses the shared file-size formatter. The existing reviewed mock is `design/mocks/pdf-metadata-readable-sizes.html`; its checker passes and its saved before/after review image is `docs/verification/tool-unification/mock/pdf-metadata-readable-sizes-review-20261102.png`.

## Source verification

- `node --test tests/pdf-metadata-dock.test.mjs tests/pdf-tools-ui.test.mjs tests/pdf-tools-shell-wiring.test.mjs`: 62 passed.
- `node scripts/check-mock-buttons.mjs design/mocks/pdf-metadata-readable-sizes.html`: passed.
- `npm run build:ui`: passed.

## Screenshot note

The installed app state was inspected directly. The available computer-use screenshot output could be viewed but not persisted to a local file through the documented API. The retained mock screenshot shows the reviewed three-action result state; it is not presented as a new capture from installed 1.0.77.
