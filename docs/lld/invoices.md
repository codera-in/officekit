# Invoice implementation map

**Version:** 1.6.3 · 2026-10-28 · Map configured currency codes beside recurring invoice line rates.

## Accepted direction

The initial mock was approved; subsequent refinements were accepted through the owner's “ok” messages after reviewing business settings, reusable catalogue-only items and multiple profiles (INR/USD examples). Proceed with the refined direct-folder/global design. Keep business identity in settings; item edits are invoice-local; profiles have independent currency/tax/payment/branding/numbering defaults. No stock ledger or OfficeKit sync engine.

For an empty invoice workspace, route directly to Settings and open a two-step profile wizard. Require the printed business name; keep profile label, address, contact and logo optional. Step two configures currency, tax and invoice-design defaults. A completed profile is immediately selectable for invoice creation. Reuse the same wizard to edit a profile, and render the uploaded or existing logo as an immediate image preview. Keep New profile/Edit profile in the profile settings section and the sticky action bar to one Save button. Browser API tests run against a temporary `OFFICEKIT_DATA_DIR`; `scripts/ui-test-api-server.mjs` owns its creation and cleanup, while `invoice_bindings_path` ensures bindings follow that configured root.

The editor stores preview freshness alongside the object URL, marks it stale on any draft-field or line change, and revokes it when the active document changes. Recurring creation uses a two-step local draft: invoice client/currency/lines first, then schedule dates and frequency; the second step displays every line description, quantity and currency-formatted rate with its configured currency code until save. Reports clear results before loading new filters and after failures; profile changes reset the report currency to that profile's default. The document editor validates the required client before save/issue, renders an inline error and returns focus to that select.

## File ownership and interfaces

| Files | Implementation | Contract reference |
| --- | --- | --- |
| `officekit/invoices/storage.py` | Folder library, authorized selection attach, remembered native reconnect, atomic bounded SQLite, revision/digest guards, recovery | LibraryState, native attachment, HLD Storage |
| `officekit/invoices/models.py` | Strict Pydantic business/currency/tax/template/client/item/document/payment/schedule/request/response DTOs | Contract DTO specification |
| `officekit/invoices/domain.py` | Decimal totals, independent profiles, lifecycle, numbering, quote allocations, payments, recurrence, report/CSV | Document/payment/schedule/report resources |
| `officekit/invoices/pdf.py` | Snapshot-driven Classic/Compact/Bold ReportLab PDF and normalized logos/QR, bounded rendering | Preview/PDF/asset resources |
| `officekit/invoices/routes.py` | Router factory with typed response models, fixed error mapping and native authorization | Endpoint table |
| `assets/officekit-slice-invoices.js`, `assets/officekit-slice-invoices.css` | Approved invoice workbench, settings, catalogue and document flows; exposed logic test hooks | UI mapping and all public routes |
| `officekit/tool_catalog/invoices.py`, shared catalogue/build/app integration | Discovery/search/routing, release gating and packaged assets | Resource discovery |
| `src-tauri/src/invoice_native.rs`, command registration | Fixed native reconnect command; no arbitrary paths | Native commands |
| `tests/test_invoices_*.py`, `tests/invoices*.test.mjs`, `ui-tests/invoices.spec.mjs`, coverage gate script | Red-first behavior checks, source inventory, 100% Python/JS/native coverage plus real end-to-end evidence | HLD Verification |

### Shared storage interface

`InvoiceLibraries(selections, settings_path)` holds native-authorized libraries. `attach(selection_id)` requires a selected single read-write folder and returns a library state. `reconnect(library_id, credential)` uses `selections.authorize(credential)`, validates persisted binding identity and returns state. `get(library_id)` returns a repository only for an attached/reconnected library. `list_bindings()` returns safe ID/label metadata only, without granting access.

`LibraryRepository.read()` returns a deep-copy envelope (`schema_version`, `library_id`, `revision`, and UUID-keyed collections). `transaction(expected_revision, mutate)` stages the bounded envelope through SQLite deserialize/transaction/serialize, then publishes atomically through no-follow selected-folder descriptors. An append-only history table records change metadata. `backup()` uses SQLite's backup API and stores a complete verified ZIP including logos and dated PDFs. `archive_document()` writes PDFs beneath `data/YYYY/MM`. `InvoiceStorageError(code,message,status)` provides fixed safe mapping. A successful explicit `reload()` updates the baseline without overwriting the unsaved UI draft. POSIX descriptor operations are required; other platforms fail closed.

Domain/router constructors receive this manager; no file paths in web DTOs. Backend agents coordinate exact public interfaces before writing dependent calls. UUID-keyed collections avoid file-per-record traversal. Native bindings remain separate from invoice content.

## SQLite and backup amendment

Keep the repository callback/envelope interface while the storage implementation uses sqlite3 deserialize/transaction/serialize through safe selected-folder descriptors. Add history(), backup() via SQLite backup API with verified ZIP bundle, archive_document() under data/YYYY/MM, and manager.restore() into a fresh native-selected destination. Endpoint models and UI include full history/backup/restore. The native bridge is `src-tauri/src/invoice_native.rs`; its command delegates remembered identity validation to the backend and never accepts a web path.

## Checkpoints and validation

1. Models/domain and repository red tests → implementation → measured focused coverage.
2. Typed router/PDF resources and native adapter → API/real PDF/folder regressions.
3. UI integration → meaningful logic coverage and browser workflows including three-button assertions, profile/currency switching and invoice-local item edits.
4. Enforced source-inventory coverage gate, full repository tests, native formatting/tests/coverage, build/packaged evidence and review board. No unmeasured gate is called passed.

Do not silently deviate from the contract: update the design and version/history with the concrete implementation before declaring completion. Keep every unsatisfied verification item explicit.
