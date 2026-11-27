# PDF table extractor — LLD

Version: 1.0.0 · HLD: [pdf-table-extractor.md](../hld/pdf-table-extractor.md)

## File map

| File | Change |
| --- | --- |
| `engine_pdf_tables.py` | Bounded selectable-table extraction and CSV/XLSX serialization; keep full rows server-side |
| `app.py` | Add typed multipart preview/export routes and request-size limits |
| `engine_comms.py` | Register the tool and search aliases; require PDF context for generic PDF table matches |
| `index.html` | Add the PDF workbench task, strict DTO client, table selector, safe text preview and explicit CSV/XLSX downloads |
| `tests/test_pdf_tables.py` | Engine and HTTP boundaries, invalid/corrupt/encrypted files, text fidelity and exports |
| `tests/pdf-workbench-ui.test.mjs` | DTO/request bounds, response signatures, selection and format errors |
| `ui-tests/pdf-table-extractor.spec.mjs` | Desktop/compact real-API preview and CSV/XLSX download flow |
| `API-CONTRACT.md` | Define endpoint payloads, limits and safe error behavior |
| `docs/FIRST-MAC-RELEASE.md`, `docs/TOOL-GUIDE.md` | Update inventory and release evidence |

## Contract and state

`POST /api/pdf/tables` takes one `file` and returns `page_count` plus at most 40 table descriptors. Each descriptor has 1-based page/table numbers, dimensions and at most 12 rows of strings. `POST /api/pdf/tables/export` takes the same source PDF plus page number, table number and `format=csv|xlsx`; the server re-extracts the selected table and returns an attachment. The UI stores only the preview DTO and selection, never a host path or altered cell payload.

The view states are: no file, ready to inspect, inspecting, tables found, no selectable tables, exporting, download started, and safe recoverable error. Changing the PDF clears its prior result. Changing the table updates the preview and export target. No source is modified.

## Verification checklist

- Verify ruled multi-column extraction, stable page/table identifiers and at-most-12-row previews.
- Verify no-table, malformed, encrypted, oversized and invalid-selection behavior.
- Verify leading-zero identifiers, punctuation, Unicode, empty cells and formula-like text survive as safe text in CSV/XLSX.
- Verify desktop/compact route, table selection, both downloads, unchanged source and actionable errors against the local API.
- Run focused Python/Node/WebKit cases, `npm test`, `npm run test:ui`, Rust tests when native code changes, and packaged-sidecar smoke before promotion.
