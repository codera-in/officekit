# OfficeKit invoices — delivery plan

**Version:** 1.6.2 · 2026-10-28 · Identify the currency beside each formatted recurring line rate.

## Confirmed product scope

Owner approved the SQLite workspace/backup/restore revision with “Approve this approach and backup/restore UI (recommended)” on 2026-10-26. Keep one database for all independent business profiles (for example INR and USD profiles), configuration, invoices, payments and full history. The selected workspace contains `config/officekit.sqlite3`, `assets/logos/`, `data/YYYY/MM/` and `backups/`. Explicit full backups contain the database plus related assets/documents, and restore verifies the bundle and creates a new workspace without overwriting the current one. Cloud sync remains externally controlled; completed backup bundles are the recommended cloud handoff.

Business name, logo, address, contact details and tax registrations live in Settings → Business profile. New drafts inherit those defaults; issued invoices retain their saved details.

On first use, an empty invoice workspace automatically opens a two-step business-profile wizard. The business name is required; profile name, address, contact details, and logo are optional. The second step sets currency, tax, and invoice design defaults. A completed profile is ready for invoice creation immediately. Existing profiles can be edited through the same wizard, and logo upload shows an immediate preview. Profile creation and editing live within the Business profile settings area; the page action bar has one concise Save action.

Saved invoice items form a reusable product/service catalogue. The owner explicitly selected “Reusable item catalogue only; no stock quantities”. Selecting an item copies its description, unit, rate and tax defaults into an editable invoice line. Add invoice-specific details, specifications or notes and change quantity/rate without silently changing the catalogue entry or other invoices. Allow ad-hoc invoice lines without a saved item. No stock balances, reservations or stock movements are in scope.

Add an OfficeKit invoice tool with saved clients/items, invoices, quotes, deposit/balance documents, partial-payment tracking, PDF preview/export, recurring drafts and reports. Support multiple business profiles with customizable currencies, tax labels/rates/registrations, numbering, document labels, columns, terms and payment details.

The editor signals when a preview no longer matches changed draft details and clears the previous preview on document switch. Recurring schedule creation requires reviewing invoice details first. Report values identify the active profile/currency/period and clear when those inputs change. Missing client validation points to the client field before the document is saved or issued.

Branding includes per-business logo upload, size and placement, accent color, footer, A4/Letter paper, three PDF layouts (Classic, Compact, Bold) and reusable named templates. Issued documents retain snapshots of their business/client/item/template details. This structured template editor is proposed; a free-form document designer has not been approved.

The owner selected folder-based data, manual sync, one computer editing at a time, and recurring drafts created when the invoice tool opens for human review. No automatic sending or OfficeKit background sync is authorized. Built-in cloud accounts come later.

## Storage decision and alternatives considered

1. **Not selected — local copy with manual sync: local working library plus explicit exchange with a selected folder.** Work from a transactional local store; exchange versioned document records, assets and a manifest only after reviewing changes. The selected exchange folder may be managed by a cloud provider. Pros: reliable local operation and explicit OfficeKit sync; avoids an actively open database inside a provider-managed folder. Cons: two copies need reconciliation and version tracking. Effort/risk: large/moderate; no cloud infrastructure required. The external provider still controls its own network activity.
2. **Selected by the owner — direct folder library.** Open the selected folder as the working library and save versioned records there, with local recovery copies. The user manages any cloud-provider sync externally. Pros: portable working folder and simpler ownership model. Cons: OfficeKit cannot make the provider's background syncing manual; offline/provider conflicts still need detection. Effort/risk: medium/moderate; no cloud infrastructure required.

Owner selection (2026-10-26): “Work directly in the selected folder; I control its cloud sync”. There will be no OfficeKit Sync process or sync buttons. The revised global settings also explicitly configure custom currencies, country-neutral tax profiles and bank/payment fields. Neither approach claims simultaneous editing support. Detect external changes, duplicate document numbers and conflicting edits; preserve both copies for review. Existing temporary file-selection grants cannot provide persistent library authorization unchanged.

## Delivery sequence and gates

1. Agree the storage choice and inspected UI mock. Mock: `design/mocks/invoice-tool.html`; the first inspection used a new Superset Browser tab and the mock button checker passes all nine frames. The initial mock was approved with “approved” on 2026-10-26. The SQLite folder/backup/restore refinement was subsequently approved; see `docs/ui-research/2026-10-26-approved-invoices.md`.
2. Agree the HLD: persistent folder authority, storage schemas, revision/conflict handling, Decimal money policy, document state transitions, recurring occurrence identity, authenticated resource APIs, PDF layouts and release visibility. Write the file-by-file LLD and API contract before implementation.
3. Implement data models, storage/recovery, business/client/item records, authoritative invoice totals and document lifecycle with regression tests first.
4. Add branded PDF rendering, multipage layouts, logo validation, fonts and matching previews. Preserve issued-document snapshots and separate currency totals.
5. Add quotes/deposits/payments, recurring draft catch-up and reports. Recurrence generation must be idempotent; cloud sync is controlled by the folder provider.
6. Integrate catalogue/search and approved UI; verify all states respect the three-button limit, keyboard/focus behavior, narrow layouts, draft preservation and useful recovery errors.
7. Complete the review board, module coverage gate, whole-repository checks and required native/packaged tests. Enable shipping visibility only after the appropriate acceptance evidence.

HLD: `docs/hld/invoices.md`. Feature API contract: `docs/invoices/API-CONTRACT.md`.

## Required verification

The owner's explicit gate is **100% lines, branches and functions for this module**, including frontend logic, backend and invoice-specific native code. Inventory covered source files and enforce per-language thresholds; do not hide untested paths through exclusions. If native coverage tooling cannot measure the relevant code, coverage remains unproven until that is resolved; a passing test count is insufficient.

- Money: supported currency precision, rounding ties, quantities/rates, taxes, tax-exempt lines, discounts, extreme values and invalid/nonfinite input.
- Documents: numbering uniqueness, snapshot preservation, state transitions, quote conversion, deposit allocation, partial/overpayment policy, voiding and balances.
- Storage: folder choice/cancel/relaunch, missing or read-only targets, unsafe links/path replacement, disk/write failures, interrupted writes, external edits, restore/recovery, duplicate numbers and isolated libraries.
- Folder changes: explicit reload, changed-file conflict detection, backup integrity, restore to a new workspace, asset integrity, interrupted writes and unchanged unrelated files. OfficeKit does not run a sync process.
- Recurrence: missed occurrences, month ends, leap years, date/time changes, reopening, pause/end conditions and no automatic sending.
- PDFs: content and page counts, long descriptions, multipage tables, logo scaling, Unicode/font limits, all templates/paper sizes, preview/export equality and rendered visual inspection.
- UI: real create/reopen/edit/export/payment/quote/recurrence/report flows, request arguments and failure responses, routing/search, draft preservation, button counts and accessible field errors.
- Run focused coverage, `npm test`, relevant Rust checks/tests and packaged smoke tests. Report source, packaged and installed evidence separately; never claim coverage before measurement.

## Existing constraints and reuse

Reuse catalogue/router/UI extension patterns, native opaque folder grants and ReportLab export conventions. Processing workspaces are temporary, so add a durable invoice store. Preserve local-only processing and native path authority. Relevant existing pitfalls include narrow folder chooser availability, button counts, authoritative API DTOs/binary response declarations, Unicode font claims, bounded persisted records and external-file identity checks.

Discovery decisions and exact owner wording are recorded in `docs/ui-research/2026-10-26-approved-invoices.md` and the requirements decisions above. Implementation evidence and remaining platform acceptance are recorded in the reviewed delivery record before release.
