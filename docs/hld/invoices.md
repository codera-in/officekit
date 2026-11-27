# Folder-based invoice tool

**Version:** 1.6.3 · 2026-10-28 · Label recurring line rates with the configured currency code.

## Decisions and scope

The owner approved the initial invoice mock with “approved” on 2026-10-26, then chose “Work directly in the selected folder; I control its cloud sync”. Subsequent refinements require a global product, configurable currencies and bank/payment details. The owner accepted the business settings, catalogue and independent profiles refinements with “ok”, and explicitly approved the SQLite workspace/backup/restore flow. Durable decisions are in `docs/ui-research/2026-10-26-approved-invoices.md`; temporary mocks are removed after approval.

The owner approved the revised two-step first-run profile wizard on 2026-10-27 with “look much better”. The temporary inspected mock was removed after approval; the accepted behavior is recorded in the UI mapping below.

Deliver the full scope in `docs/PRD-invoices.md`: business profiles, clients/items, invoices/quotes, deposits/balances, payments, recurrence, reports and branded PDF templates. No hosted service, account, OfficeKit synchronization, automatic sending or automatic currency conversion. Initial release remains development-only until native/packaged acceptance.

## Components and ownership

- Existing OfficeKit shell and extension registry open one invoice destination. Documents, Clients & items, Recurring, Reports and Settings are local sections; no duplicate top-level tool or alternative invoice editor.
- A thin Pydantic/FastAPI invoice router calls invoice services; only the repository accesses durable records. Existing desktop app authentication protects all routes.
- A native main-window command selects/reattaches the working folder and grants the backend bounded access. The webview receives an opaque library handle and display label, never arbitrary host-path authority.
- The repository owns schema-versioned SQLite, revision checks, full change history and atomic publication. New Python models, money, lifecycle, recurrence, PDF and repository modules remain separate for testability.
- ReportLab generates the actual PDF used for both preview and download. Existing local font/escaping, native save and result-streaming conventions are reused. No remote font or template fetches.

## Local ownership rather than hosted tenancy

This is a local desktop feature owned by the signed-in OS user, not a hosted multitenant service. No auth tenant exists, so no synthetic tenant, JWT or RLS is introduced. Every stored record belongs to one library; repository instances are constructed only from an authorized native folder binding, and record IDs cannot select a different library. Business IDs are ordinary data partitions inside that library. All records, assets and recovery copies inherit this same OS-user/library ownership. Test independent libraries and authorization boundaries.

## Storage and external folder changes

Create an OfficeKit-owned `officekit-invoices/` subdirectory inside the chosen parent folder. Existing unrelated files are never renamed, scanned for invoices or replaced. A library has an opaque UUID and schema version, `config/officekit.sqlite3` containing all structured records and change history, `assets/logos/` for immutable hash-named normalized logos, `data/YYYY/MM/` for generated documents and `backups/` for complete backup bundles. Store money as canonical decimal strings, dates as ISO calendar dates and instants as UTC.

Bound the structured library to 16 MiB, 5,000 documents, 5,000 clients, 5,000 items, 50 businesses, 500 schedules, 50,000 payment/correction entries and 100 templates. Each document has at most 200 lines; names <=160 characters, descriptions <=4,000, notes/instructions <=8,000. Resource counts and serialized-byte limits are checked before publication. Fail with a useful capacity error rather than partially writing. Native-selected logos are bounded to 5 MiB and 16 million decoded pixels and normalized locally; reject SVG/active content as logos in this version.

Every write validates folder/file identities without following symlinks, verifies the loaded file digest/revision, stages SQLite in memory, writes and fsyncs a private same-directory temporary file, then atomically publishes only the known library file. SQLite's backup API creates a consistent database snapshot for complete ZIP backups; each bundle carries hashes and is verified before restore. Do not claim distributed locking against cloud providers: one computer at a time remains required. The descriptor-relative implementation currently needs POSIX no-follow operations and rejects unsupported platforms; test the replacement/recheck race and fail closed on unsupported filesystem semantics.

Persist the selected binding in native app data, not browser localStorage. On relaunch validate the remembered directory identity, current permissions and library identity before reauthorizing backend access. A moved/replaced/missing folder requires explicit reconnect. Store a bounded local draft-recovery copy, linked to library/document/revision, after input edits; do not automatically publish recovered drafts into another library. Folder read-only/unavailable states preserve this draft and disable durable mutations.

External file-digest or revision changes return 409 and preserve the unsaved local draft. Explicit reload displays the latest folder version alongside the recovery version; applying a reviewed result requires the latest revision. Duplicate issued numbers remain unresolved conflicts, never silent renumbering. Cloud files arriving incompletely, invalid schemas, missing logos or corruption show recovery state and do not get overwritten. OfficeKit never calls a cloud API or runs a Sync job.

## SQLite publication, backup and restore

To preserve descriptor-based no-follow guarantees with Python’s sqlite3 API, load a bounded verified database image into an in-memory connection, apply SQLite transactions, serialize the completed image and atomically publish it through the selected-folder descriptor. No live WAL/journal sidecars are shared with a cloud provider. Bound each current structured state to 16 MiB and the full database including history to 256 MiB. Detect external digest/identity changes before publication. Never silently rewrite incompatible or corrupted databases.

Each committed mutation retains an append-only history entry; configuration changes, document transitions and payment changes survive backup/restore. Create backups using SQLite Connection.backup, run integrity checks and package the verified snapshot plus bounded assets and dated documents into a manifest/checksum-verified `.officekit-backup` ZIP. Do not recursively include earlier backups. Restore through native-selected backup and destination grants, reject unsafe archive paths/links/duplicates/bombs, verify integrity and hashes, then publish into a new workspace only. Interrupted or invalid restore preserves both the original workspace and backup.

Issued PDFs are rendered and validated before financial publication; archive the saved copy under the issue-date year/month. An archive failure after commit leaves the invoice issued with a visible pending archive state. The existing Download PDF action can explicitly retry archival through a POST archive resource; GET PDF remains read-only.

## Models and indexes

SQLite stores a validated application envelope, metadata and append-only change history. The in-process repository exposes collections keyed by UUID inside the envelope `{schema_version, library_id, revision, businesses, currencies, tax_profiles, templates, clients, items, documents, payments, schedules}`. A transaction updates one full envelope; maintain in-memory indexes rebuilt only from valid data:

| Record | Fields and relationships | Index / constraint |
| --- | --- | --- |
| Business | ID, name/address/contact, registrations, default currency/taxes/template, numbering policy, payment methods | Unique ID; defaults reference this business's records |
| Currency | ID, business ID, code, name, symbol, precision 0..8, placement, number format | `(business_id, normalized code)` unique; snapshot definition on document |
| Tax profile | ID, business ID, name, ordered rows with labels/rates/registration and additive/compound mode, inclusive/exclusive treatment | `(business_id,id)`; <=6 rows/profile |
| Template | ID, business ID, name, Classic/Compact/Bold, logo hash/size/placement, accent, paper, labels/columns/footer | `(business_id,id)`; validated font and layout capabilities |
| Client | ID, business ID, name/address/contact/customer reference and default tax/payment terms | `(business_id,id)`; bounded normalized search index |
| Item | ID, business ID, private name, printed description, unit, quantity/rate and tax behavior | `(business_id,id)` |
| Document | ID, business ID, kind/state, number, issue/due/validity dates, client/business/template/currency/tax/payment snapshots, lines, totals, quote/deposit/balance links, recurrence key | `(business_id,kind,number)` unique once issued; `(business_id,state,date)` list index |
| Payment | ID, document ID, amount/date/method/reference, optional correction/reversal link | `(document_id,date)`; amounts use document currency |
| Schedule | ID, business ID, source draft snapshot, frequency, anchor/end, pause state, catch-up policy | `(schedule_id,occurrence_date)` unique across documents |

The generic harness's hosted tenant columns/RLS do not apply; the explicit ownership decision above is the justification for these local entities.

## Configurable currencies, taxes and payments

Provide international currency presets plus custom definitions: 2..12 uppercase ASCII letters/digits for code, display name, symbol, 0..8 decimal places, placement and separator/grouping format. Choose a business default and override per draft. Precision and currency identity are captured in each document. If the same display code has different precision definitions, reports distinguish those definitions. Changing business defaults does not reinterpret existing amounts.

Use Python Decimal with fixed context and explicit magnitude/precision bounds; reject nonfinite values, booleans, excess precision and negative quantities/rates. Monetary inputs are decimal strings. Round each line's discounted net and each tax component once using ROUND_HALF_UP to currency precision. Percentage discounts are applied before tax; fixed document discounts are allocated proportionally with residual units assigned deterministically by line order. Inclusive tax is extracted from gross using the ordered additive/compound profile; test equation reconciliation. Totals equal the sum of displayed rounded components. Reject negative totals and overpayments; use explicit correction/reversal records for payment mistakes.

Default to No tax. Users create named profiles with labels/rates/registration numbers, multiple tax rows, inclusive/exclusive prices, additive/compound calculation and line exemptions. Presets may be examples but never forced by locale. No automatic jurisdiction/compliance inference.

Payment methods have configurable labels and enabled fields: bank/account holder, bank name/address, account number, IBAN, SWIFT/BIC, routing/sort/branch/local codes, payment URL, QR payload and free text. Validate payload bounds and safe supported URL schemes; do not open payment URLs automatically. Each invoice chooses printable methods and snapshots them. Never log bank details. QR generation is local and opt-in. Email creates a local draft/attachment for user review, never sends automatically.

## Lifecycle, numbering and recurrence

Documents begin as drafts. Issue atomically assigns/validates the business's configurable number and snapshots the final invoice. Number formats support literal prefixes, year and padded counters; counters advance only on successful issue and scope by business/kind/reset period. Draft PDFs are visibly drafts. Issued financial fields cannot be silently edited; duplicate as a draft, explicitly void or correct payment records instead.

Invoice status derives from issue/void state, remaining balance and due date: Draft, Issued, Partially paid, Paid, Overdue, Void. Quotes have Draft, Issued, Accepted, Declined and Expired. Acceptance is recorded by the user. Quote conversion is idempotent and links the source to its invoice(s). Deposit/balance invoices use explicit allocations; payments and deposits cannot be counted twice, and unrelated currency allocations are rejected.

On opening the invoice module, submit an idempotent recurring-draft generation request using a server-side current calendar date and stored occurrence keys. Frequency supports weekly, monthly, quarterly and yearly; month-end anchors clamp to that month's final date without drifting subsequent anchors. End-by-date/count, pause and missed-occurrence policies follow the mock. Cap generation to 100 drafts per request and surface remaining catch-up work; no unbounded startup loop. A transaction both creates drafts and records occurrence identity. Reopening, clock changes and retried requests do not duplicate drafts.

## PDF and reports

Render Classic/Compact/Bold using one authoritative document snapshot and shared totals. Preserve logo aspect ratio, readable text, wrapping, repeat table headers and final-page totals/terms; cap at 100 pages/20 MiB. Preview uses generated PDF bytes, not independently calculated HTML. Validate supported glyphs against packaged fonts; never claim universal language support. Escape user text and keep document paper opaque.

Reports filter business/date/currency and return invoice totals, payments received, outstanding/overdue and client breakdown. Payment totals use payment dates; invoice totals use issue dates. Draft/void documents are excluded. Different currency definitions are never summed. CSV uses the same report DTO and protects spreadsheet formula-leading text.

## UI mapping and approval boundaries

Existing shell controls stay. Add only the invoice tool entry and its five sections. On a new workspace, open profile setup automatically; the workspace is not ready for invoice creation until the required business name is saved. Use a two-step wizard for both create and edit: business identity first, then currency/tax/design defaults and optional logo. Show the selected logo immediately. Put New profile and Edit profile links in the profile settings section; leave only a concise Save action in the sticky settings bar. Draft editor retains Save draft, Download PDF and Issue invoice (three counted buttons); issued documents expose Download PDF, Draft email and Record payment. Data-folder settings expose Choose folder and recovery Reconnect; remove the earlier proposed Review sync changes/Apply reviewed sync controls because the owner selected direct-folder storage.

The initial mock approval is recorded in `docs/ui-research/2026-10-26-approved-invoices.md`. Global settings and the SQLite workspace/backup/restore revisions were accepted by the owner. No page exceeds three counted buttons; row actions, tabs and inline links remain contextual and do not duplicate primary actions.

The editor clears a prior document preview when opening another document and marks the current PDF stale as draft fields change; the user refreshes it before relying on it. Recurring setup collects client, currency and line details before schedule settings, then keeps the line descriptions, quantities and currency-formatted rates with their configured currency codes visible beside frequency and dates until the schedule is saved. Reports clear prior values while a filter or profile query runs and label the selected profile, currency and period. Save and Issue focus the client field when it is missing.

## Verification and rollout

The owner's 100% line/branch/function coverage gate applies to every invoice-specific Python/JS/Rust implementation file; track the inventory explicitly. Use coverage.py with branch coverage, c8 for JS and llvm source coverage for native additions. Function coverage must be measured or explicitly derived from executed function entries; do not infer it from line coverage alone. Missing native coverage tooling remains an unresolved gate, not a waiver.

Test malformed inputs, all lifecycle branches, Decimal precision/rounding, inclusive/compound taxes, currency formatting, numbering conflicts, external writes, disk failures, folder identity/reconnect, library isolation, recurrence edge dates and correction/deposit accounting. Add real PDF extraction/render checks and UI workflows at desktop/compact widths. Run relevant repository, Rust and packaged smoke checks; installed platform acceptance is separate evidence. No tests may write to the user's real invoice folder or bank details.

Pitfalls addressed: P-211 folder chooser remains accessible narrowly; P-203/P-195 count every screen's buttons and retain approved controls; P-245 actual glyph coverage is verified; P-242 explicit binary response declarations; P-204 independent fixed date fixtures; bounded snapshots address P-180/P-220; external-file checks and no-follow filesystem access address file identity/race pitfalls.

## Approval record

The approved direction uses direct-folder SQLite storage with atomic saves/revision conflict detection and complete backup/restore, configurable global currency/tax/payment definitions, independent profiles, immutable issued snapshots, recurring drafts for review and the 100% measured module coverage gate. Approval is not a claim that implementation or verification has completed.
