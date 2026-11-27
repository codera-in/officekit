# Rotate PDF Pages — installed verification — 2026-11-03

## Run

- App version: 1.0.77.
- Input: `tests/fixtures/pdf-protect-source.pdf` (626 bytes, one page; original left unchanged).
- Settings: 90° right, all pages.
- Run status: `Done · 1 page turned`.
- Download: started and produced `pdf-protect-source-rotated.pdf` (616 bytes) in Downloads.
- Output validation: opened the downloaded file in View metadata. The report showed one page and `rotate 90`; the original title remained `OfficeKit PDF test fixture`, and the output was unencrypted.

## UX finding

The installed result state stayed within the three-button limit, but the shared dock title remained `PDF workbench`. The selected 626-byte input displayed as `0.00 MiB`. The source screenshots in the existing evidence log show the reviewed result layout but are browser-source captures, not captures of this installed 1.0.77 run.

## Checks and evidence

- `node --test tests/pdf-tools-ui.test.mjs`: 55 passed.
- `pytest -q tests/test_pdf_tools_api_unittest.py::RotationRouteTests`: 6 passed, 11 subtests passed.
- The existing before/ready/saved screen captures are linked in `docs/verification/tool-unification/README.md` under Rotate PDF Pages.
- Native CUA showed the result and metadata in the installed app; its documented screenshot interface did not persist image bytes to a local file.

Compact layout, keyboard/focus, alternate angle/range, and installed matching-build checks remain open.
