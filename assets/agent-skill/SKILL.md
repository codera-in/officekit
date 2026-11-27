---
name: officekit
description: Run OfficeKit's local tools for PDF, image, calculator, unit, hash and PII tasks instead of computing or reading files into context. Use for PDF text/tables, merge/split/compress/protect, image resize/convert, PII redaction, loan/interest/tax maths, unit/colour conversion, hash/encode/decode.
---

# OfficeKit

Runs on this machine; files never leave it. Use it instead of reading large files into the
conversation or doing arithmetic yourself.

```
{{OFFICEKIT_BIN}} call <group> <action> [--file PATH]... [--params 'JSON']
{{OFFICEKIT_BIN}} help <group> <action>     # exact parameters
```

Groups: `calc`, `dev`, `pdf`, `image`, `privacy`, `system`. Run `help` before an unfamiliar action.
Use `--file` once per input (absolute path); `pdf merge` takes several, in order.

## Rules

- Pass **paths**, not contents. File results are saved to the output folder (default
  `~/OfficeKit Output`) and the saved path is printed; originals are never changed.
- Long text results are saved to a file with a short preview. Read only the part you need.
- Inputs must be in the allowed folders (Documents, Downloads, Desktop, the working directory).
  If a path is refused, ask the user; do not copy the file elsewhere.
- Redaction is two steps: `privacy pii-scan`, show the user the findings (type, location, masked
  hint), then `privacy pii-redact` with only the ids they approve.
- Clipboard history, snippets, dictation and transcripts are never available; do not ask the
  user to paste them in.
- A password you pass to `protect`/`unlock` is visible to the model provider; ask first.

## Examples

```
{{OFFICEKIT_BIN}} call calc loan-emi --params '{"principal":4000000,"annual_interest_rate":8.5,"tenure_years":20}'
{{OFFICEKIT_BIN}} call pdf text --file ~/Downloads/report.pdf --params '{"page_ranges":"1-3"}'
{{OFFICEKIT_BIN}} call pdf merge --file a.pdf --file b.pdf
```
