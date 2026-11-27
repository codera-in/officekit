# PDF table extractor — HLD

Version: 1.0.0 · Status: implemented, focused tests passing; full release gates remain open.

## Problem and scope

OfficeKit has statement-specific PDF-to-CSV/XLSX extraction, but ordinary selectable PDF tables have no export flow. This feature adds a separate searchable workflow in the existing PDF workbench. It lists tables found in selectable text PDFs, previews the first 12 rows, and exports one selected table to CSV or XLSX.

Scanned-PDF OCR, unruled-layout reconstruction, automatic header inference, type inference, table editing, multi-table batching, and claims of universal PDF conversion are out of scope. The statement extractor remains the route for supported bank statements and balance reconciliation.

## Architecture

- `engine_pdf_tables.py` owns bounded extraction, table selection and formula-safe export.
- `app.py` exposes preview and export endpoints. It accepts PDF bytes only; host paths never cross the API boundary.
- `engine_comms.py` registers `pdf_table_extractor` and PDF-context search aliases. `index.html` routes it into the existing PDF workbench, displays the selected table using text nodes, and invokes the declared multipart API.
- `docs/mocks/pdf-table-extractor.html` shows the before/after workflow. The user waived waiting for mock approval: “dont wait for my approvals.. go ahead with your recommendatins.” (2026-10-08).

## Safety and failure behavior

Inputs are local and remain unchanged. Page, character, table, row, column, cell, cell-text and output limits are enforced server-side. Exports re-extract the table from the selected PDF; the browser sends only page/table indices and format. CSV/XLSX cells stay text and formula-like content is escaped. An empty table result means no selectable table was detected; encrypted, malformed and over-limit PDFs return fixed safe errors. No OCR or guessed values are presented as successful extraction.

## Release conditions

Engine/API/client tests cover ruled table detection, no-table results, bounds, formula neutralization, identifiers, CSV/XLSX read-back, selection errors and desktop/compact browser export. Packaged-sidecar and installed-Mac visual interaction remain separate release checks. The tool is not included in the 23-tool private-beta allowlist.
