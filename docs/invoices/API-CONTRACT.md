# Invoice module API contract

Version: 1.2.1 · 2026-10-26 · Aligned collection and query rows with the implemented router. Initial release remains development-profile only.

## Boundary and resources

All endpoints use existing OfficeKit desktop authentication and are currently available in development builds; the private-beta release gate returns 403. Resources belong to the OS-user-owned library opened through a native file-selection grant. There is no hosted tenant or user-supplied tenant ID. Attach consumes the opaque file-selection ID; reconnect additionally requires the native grant credential. Library UUIDs never grant filesystem access by themselves. Paths are rejected in web DTOs. Folder storage currently requires POSIX no-follow descriptor support and fails closed on unsupported platforms.

Prefix `L` below means `/api/invoice-libraries/{library_id}`. Item IDs are UUIDs. Listed collections return typed `{items, next_cursor}` pages; limit 1..100, default 50, opaque bounded cursor <=512 characters. GET operations never mutate storage. Errors use `{error:{code,message,details}}`; fixed safe messages avoid bank information, full paths and raw exceptions. Request validation returns a bounded generic 422. See router DTOs for exact field constraints; this contract is synchronized with `officekit/invoices/routes.py` and `models.py`.

## Implemented endpoint table

| Method | URL | Request DTO | Response DTO / content | Success / additional failures | Tenant-scoped |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/invoice-libraries` | `Attachment` (`selection_id`) | `LibraryState` | 201; file-selection grant required | No: local OS-user library |
| POST | `/api/invoice-restorations` | `Restoration` (new parent and selected backup grant IDs) | `LibraryState` | 201; creates a new workspace | No: local OS-user library |
| GET | `/api/invoice-libraries` | — | `Page` of safe remembered binding metadata | 200 | No: local library index |
| GET | `L` | UUID path | `LibraryState` | 200 | No: local library |
| POST | `L/reconnections` | Empty body + `X-OfficeKit-Native-Grant` | `LibraryState` | 200; native authorization required | No: local library |
| POST | `L/reloads` | Empty body | `LibraryState` | 200; detects external folder changes | No: local library |
| GET | `L/history` | — | `History` | 200; append-only workspace changes | No: local library |
| POST | `L/backups` | Empty body | ZIP binary | 200 `application/zip`; full verified backup | No: local library |
| GET/POST | `L/businesses`, `/L/businesses/{id}` GET/PUT | `Page` / `BusinessWrite` | `Page`, `BusinessRecord` | 200 / 201 | No: local library |
| GET/POST | `L/clients`, `/L/clients/{id}` GET/PUT | `Page` / `ClientWrite` | `Page`, `ClientRecord` | 200 / 201 | No: local library |
| GET/POST | `L/items`, `/L/items/{id}` GET/PUT | `Page` / `ItemWrite` | `Page`, `ItemRecord` | 200 / 201 | No: local library |
| GET/POST | `L/schedules` | `Page` / `ScheduleWrite` | `Page`, `ScheduleRecord` | 200 / 201 | No: local library |
| GET/PUT | `L/schedules/{id}` | UUID path / `ScheduleWrite` | `ScheduleRecord` | 200 | No: local library |
| GET/POST/PUT | `L/documents`, `/L/documents/{id}` GET/PUT | `Page` / `DraftWrite` | `Page`, `DocumentRecord` | 200 / 201 | No: local library |
| POST | `L/documents/{id}/transitions` | `Transition` | `DocumentRecord` | 200; issue/accept/decline/void | No: local library |
| POST | `L/documents/{id}/archives` | `Revision` | `DocumentRecord` | 200; retry pending issued-PDF archive | No: local library |
| GET | `L/documents/{id}/pdf` | — | PDF binary | 200 `application/pdf` | No: local library |
| POST | `L/document-previews` | `Preview` | PDF binary | 200 `application/pdf`; no state mutation | No: local library |
| POST | `L/document-conversions` | `Conversion` | `ConversionResult` | 201; idempotent quote/deposit/balance conversion | No: local library |
| GET | `L/documents/{id}/payments` | — | `PaymentPage` | 200 | No: local library |
| POST | `L/documents/{id}/payments` | `Payment` | `PaymentResult` | 201 | No: local library |
| POST | `L/documents/{id}/payment-corrections` | `PaymentCorrection` | `PaymentResult` | 201; append-only correction | No: local library |
| POST | `L/recurring-draft-batches` | `RecurringBatch` | `RecurringResult` | 200; draft generation only | No: local library |
| POST | `L/assets` | `AssetWrite` (selection ID) | `AssetRecord` | 201; native-selected normalized logo | No: local library |
| GET | `L/assets/{sha256}` | — | PNG binary | 200 `image/png` | No: local library |
| GET | `L/reports` | query parameters: business, currency, date range, optional client | `InvoiceReport` | 200 | No: local library |
| GET | `L/reports.csv` | same query parameters | CSV binary | 200 `text/csv` | No: local library |

PDF/CSV/ZIP/PNG headers include `Content-Disposition`, `Content-Length`, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. Preview/asset dispositions are inline; downloads use fixed/generated filenames. Binary response types are declared in OpenAPI. CORS exposes download headers and allows the native grant header from trusted OfficeKit origins.

## DTO specification

All models forbid extra fields. Text is bounded Unicode without control characters except allowed multiline whitespace. IDs and references are verified within the current authorized library/business. Every stored mutation input includes `expected_revision` (nonnegative integer) and succeeds only against that exact revision. Returned records include `id`, `library_revision`, `created_at`, `updated_at` plus their declared fields. Decimal inputs and results are canonical strings, never floating-point JSON money.

- **LibraryState:** library UUID, schema version, revision, safe folder label, status (`ready`, `changed`, `unavailable`, `read-only`, `reconnect-required`, `invalid`, `recovery-available`), capabilities, safe error, business summaries. No host paths. Native attachment/reconnection accepts server/native-owned folder selection/binding handles only; 128-character maximum, no raw web path.
- **CurrencyDefinition:** UUID, code `[A-Z0-9]{2,12}`, name <=80, symbol <=12, precision integer 0..8, placement (`before`, `after`, `code`), grouping (`western`, `indian`, `none`), decimal separator (`.`, `,`), grouping separator (`,`, `.`, space, none); separators must differ. Presets are conveniences. Never use Intl currency formatting for unknown custom codes; use the explicit definition.
- **TaxProfile:** UUID/name <=160, inclusive boolean, <=6 ordered rows `{label<=80, rate:decimal 0..100 with <=6 fractional places, registration_label<=80, registration_number<=160, mode:additive|compound}`. Line exemptions suppress the profile for that line. Empty profile means No tax.
- **PaymentMethod:** UUID, type (`bank`, `link`, `local`, `cash-cheque`, `custom`), label <=80, enabled boolean, <=20 named/visible fields with labels <=80 and values <=512; optional link <=2,048, QR payload <=2,048, instructions <=8,000. Payment-link schemes limited to HTTPS; local QR payload is printable data and never auto-invoked. Banking fields include holder/bank/address/account/IBAN/SWIFT/routing/sort/branch/local-code. No network account validation.
- **TemplateDefinition:** UUID/name <=160, layout enum Classic/Compact/Bold, paper A4/Letter, optional validated logo hash, size small/medium/large, placement left/center/right, accent `#RRGGBB`, locale string <=80, <=20 bounded custom label pairs, visible column enum list, footer <=8,000, payment-field visibility. Font/glyph support is checked at render time.
- **Business fields:** name <=160, address <=4,000, contact <=512, <=20 registration label/value pairs, <=100 currencies, <=50 tax profiles, <=20 payment methods, <=20 templates, valid default IDs, numbering `{invoice_prefix,quote_prefix,estimate_prefix: <=40 safe literal characters, next_counter:1..999999999, padding:1..9, reset:never|yearly}`. NewBusiness adds expected revision; BusinessUpdate includes the complete validated business definition plus expected revision. Defaults use no tax; user chooses currency.
- **Client fields:** business UUID, name <=160, address <=4,000, contact/email/customer reference <=512, optional tax-profile ID, terms days 0..3650, archived boolean. NewClient/ClientUpdate add expected revision. No hard delete of referenced clients.
- **Item fields:** business UUID, private name <=160, printed description <=4,000, unit <=40, default quantity/rate decimal strings, exemption boolean, archived boolean. NewItem/ItemUpdate add expected revision.
- **Line:** description <=4,000, optional item UUID, unit <=40, optional calendar date, quantity/rate decimal strings 0..10^12 with <=8 fractional places, tax exemption boolean, optional section label <=160. <=200 lines/document. Quantity must be positive; money magnitude after calculation <=10^15 and all intermediate arithmetic is bounded.
- **Draft fields:** business UUID, kind invoice/quote/estimate, client UUID, issue/due/valid-until dates as applicable, currency/profile/template IDs or validated draft overrides, line list, discount `{kind:none|percent|fixed,value:decimal}`, notes/terms <=8,000, selected payment-method IDs. NewDocument adds expected revision and optional source draft ID; DraftUpdate supplies the full draft and expected revision. The service resolves snapshots and computes totals; client-supplied totals are forbidden.
- **DocumentRecord:** draft fields with resolved immutable snapshots, assigned/provisional number, lifecycle state/derived status, line/tax/discount totals, grand total, paid and balance decimal strings, related-document and recurrence references. Issued number uniqueness is business/kind scoped. Snapshot and payment currencies must match.
- **DocumentTransition:** expected revision, action issue/accept/decline/void, optional manually chosen number <=80, optional reason <=1,000. Server validates permitted state edges. Due/overdue status is server-derived.
- **QuoteConversion:** expected revision, source quote UUID, kind full/deposit/balance, bounded decimal amount for partial conversion, idempotency UUID. ConversionResult returns linked documents and allocations. Full repeat returns original result; key reuse for different payload returns 409.
- **NewPayment:** expected revision, positive amount string, payment calendar date, method label <=80, reference <=512, idempotency UUID. PaymentCorrection includes original payment UUID, reason <=1,000 and optional validated replacement. PaymentResult includes updated document and append-only payment/correction entries. Corrected payments cannot be corrected again without referencing the latest entry.
- **PreviewRequest:** full draft fields or saved document UUID (exactly one), expected revision, optional template override for drafts. Response is the generated PDF; no state mutation. NativeLogoSelection includes native selection ID and expected revision; AssetRecord includes hash ID, dimensions, PNG MIME and byte count.
- **Schedule fields:** business UUID, draft snapshot, frequency weekly/monthly/quarterly/yearly, anchor date, optional end date/count, paused boolean, catch-up each/ask. `ScheduleWrite` includes expected revision; changes cannot rewrite already-generated occurrences. `RecurringBatch` includes expected revision and approved catch-up IDs (when required), not a caller-supplied clock. `RecurringResult` includes created document IDs, existing occurrence count and remaining count.
- **Queries:** BusinessPageQuery adds business UUID and optional bounded search <=160. DocumentPageQuery adds kind/status, inclusive calendar-date range and sort date/amount, ascending/descending. ReportQuery requires business UUID, start/end date and currency-definition UUID; optional client UUID. Ranges <=10 years and start<=end. Report results contain period/currency, invoiced/received/outstanding/overdue and <=5,000 client rows; CSV <=10 MiB.

## Native commands

The UI calls the existing native `file_selection_open` command for read-write folders and read-only backup/logo selections. It POSTs only the opaque selection ID; the backend attaches through the trusted file-selection store. `invoice_library_reconnect({bindingId})` is the invoice-specific native command and validates the remembered binding identity before reauthorizing access; if moved/replaced, the user must choose the folder again. A web-provided path cannot create or retarget a binding. Native state stores binding paths privately; all invoice-specific native command branches are part of the coverage inventory.

Use existing native Save As for downloaded PDF/CSV; no invoice-specific arbitrary file-write command. No cloud endpoints or AWS topology are added. Deterministic code handles all money, permissions, lifecycle and matching; no probabilistic model is involved.
