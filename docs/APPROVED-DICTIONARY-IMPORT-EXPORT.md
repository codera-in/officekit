# Approved personal dictionary variants, import and export

**Date:** 2026-11-19
**Approval:** The owner reviewed the inspected Superset Browser mock `dictionary-import-export` (before and after, 1 of 3 buttons) and said **"mock approved, build it"**. The mock file was removed from the tree after approval, per AGENTS.md; this document is the durable record.

## Approved behavior

- **Variants:** "Often misheard as" accepts several variants separated by commas. Each variant is saved as its own entry for the same word, so the stored format and the engine are unchanged. Variants are trimmed and de-duplicated without regard to case. Variants already in the dictionary are skipped and counted; terms over 64 characters or with control characters are not saved and are counted.
- **Export:** a text link beside the term count saves a versioned JSON file (`officekit-dictation-dictionary`, version 1, `entries` of `source` and `replacement`) named `officekit-dictionary-YYYY-MM-DD.json`. With an empty dictionary it reports that there is nothing to export.
- **Import:** a text link beside the count opens a file chooser (in the card, not the bottom bar). It reads JSON (`{"entries": [...]}` or a bare array, strings for plain words) or CSV/TSV with `misheard,word` columns (an optional header row, quoted fields, one column for a plain word). The result line reports terms imported, skipped as already present, skipped as unreadable and skipped because they did not fit under 256.
- **Limits:** 256 entries, 64 characters per term, a 1 MB file and 2,000 rows per import. A rejected file (empty, not valid JSON, no entries, too large) changes nothing.
- **Buttons:** Import and Export are text links, not buttons. The card keeps one button (Add), within the 3-button limit.
- **Privacy:** the dictionary stays in the app's local storage; import and export touch only a file the user chooses.

## Tests

`tests/dictation-ui.test.mjs`: variants, merge counts, JSON and CSV import, export round trip, limits and rejected files, and the card markup (text links, registered actions).
