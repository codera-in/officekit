# Timestamp Converter: daylight-saving gap recovery

## Decision

When a local wall time falls inside a daylight-saving gap, keep the value editable, mark the Value field invalid, and attach zone-specific correction guidance to it. Clear the stale conversion result, suppress Report bug for this correctable input, and leave Run locally available. Editing the value clears the field guidance; a successful retry restores the conversion and Copy action. Download is not offered for this tool.

The reviewed mock showed the previous four-button state (Run, Copy and duplicate Report bug actions) reduced to two controls (Run and disabled Copy). The mock passed `node scripts/check-mock-buttons.mjs` before implementation. Its temporary HTML was removed after implementation; the review capture remains under `docs/verification/tool-unification/mock/`.

## Evidence

- Source invalid-state capture, recorded 2026-10-31: `after/timestamp_converter-dst-gap-after-fix-live-source-20261031.png`.
- Source recovered-state capture, recorded 2026-10-31: `after/timestamp_converter-dst-gap-recovered-source-20261031.png`.
- Reviewed mock capture: `mock/timestamp-converter-dst-gap-guidance-superset.png`.
- `node scripts/check-mock-buttons.mjs design/mocks/timestamp-converter-dst-gap-guidance.html` passed before the temporary mock was removed.
- Focused Timestamp/DST UI regressions passed (2 matching tests).
- `pytest -q tests/developer_routes_unittest.py -k timestamp`: 1 passed.
- `pytest -q tests/engine_developer_unittest.py -k timestamp`: 22 passed.
- The broader `tests/developer-slice-ui.test.mjs` and `tests/developer-utilities-ui.test.mjs` run has one unrelated failure: a generic converter-heading assertion does not match the current `index.html`. The DST tests pass.
- No new browser or installed-app capture was made in this milestone. The screenshots above are existing 2026-10-31 captures.

## Remaining checks

Search synonyms, compact layout, keyboard/focus, native clipboard, and installed-app behavior remain open.
