# Invoice tool design decisions

**Version:** 1.2.0 · 2026-10-28. Earlier: 1.1.0 · 2026-10-26.

The owner approved the initial invoice mock with **“approved”**. It was inspected in a new Superset Browser tab and all nine frames passed `scripts/check-mock-buttons.mjs`.

Approved visual direction: invoice library with search/status filtering, editor with PDF preview, per-business branding and Classic/Compact/Bold templates, quotes/deposits/payments, recurring drafts and currency-separated reports. Keep at most three counted buttons on every screen.

Subsequent owner decisions:

- **“Work directly in the selected folder; I control its cloud sync”**. The selected folder is the working library. No OfficeKit sync process or sync-review/apply buttons.
- **“currency shoudl be configguraable”**. Business defaults and draft overrides include international presets and custom currency definitions, symbols, precision and formatting.
- **“its a global product”**, illustrated with the India-specific tax options, and **“Bank / PAYMENT DETAILS”**. Default to No tax and configurable named tax profiles. Provide global bank/local-payment fields and custom labels/instructions.
- **“wiht 100 % test covergge for this module”**. This remains an implementation/release gate; this document claims no code coverage result.

The owner accepted the business settings, editable catalogue and independent profiles refinements with “ok”. Profile settings include business name/logo/address plus each profile’s currency, tax/payment defaults, templates and independent numbering.

For the invoice review fixes, the owner approved the before/after mock with **“Approve as shown”** on 2026-10-28. The mock was inspected in a new Superset Browser tab and passed `scripts/check-mock-buttons.mjs`. Approved behavior: label a stale PDF preview after edits and refresh it on request; collect and review invoice details before saving a recurring schedule; clear report values while filters or profile changes reload and show the selected period; focus and identify the missing client inline before save or issue.

The owner then requested SQLite storage and a config/data/year/month folder structure, and explicitly selected **“Approve this approach and backup/restore UI (recommended)”**. Approved workspace layout: `config/officekit.sqlite3`, `assets/logos/`, `data/YYYY/MM/`, `backups/`. Workspace settings show Choose folder, Create backup and Restore backup (three buttons), with an inline history link. Restore selects a backup file and destination parent, verifies the complete contents and creates a new workspace; no overwrite. History remains in the database and backups. The revised mock was inspected in a new Superset Browser tab and passed the three-button checker in all twelve frames. Temporary mock/preview files are removed after approval; this decision record persists.
