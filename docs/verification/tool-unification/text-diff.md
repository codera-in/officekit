# Text Diff verification

## Input and expected output

- Original: `hello\nworld`
- Changed: `hello\nplanet`
- Expected patch: one deleted line (`world`) and one inserted line (`planet`).
- After a result, editing either text input or changing a text option keeps the old diff visible as a previous comparison and pauses Copy patch / Download until a new comparison runs. Re-running uses the edited input and restores both actions.

## Evidence

- Result state: [current-source diff and action dock](after/text_diff-valid-live-source-superset.png)
- Edited state: [previous diff retained with export actions paused](after/text_diff-stale-input-live-source-superset.png)
- Mock before: [matching result](review/text-diff-stale-proposal.png)
- Mock after: [edited input and paused exports](review/text-diff-stale-proposal-after.png)
- Reviewed mock source: [Text Diff stale result](../../../design/mocks/text-diff-stale-result.html)

The source and mock screenshots were saved on 2026-10-31. The mock screenshots were inspected visually in this review; the HTML passes the three-button checker. Browser automation still aborts before a fresh app session, so this milestone does not claim a new runtime screenshot.

## Checks

- `node --test --test-name-pattern='changing a Text Diff option|JSON compare renders|Swap exchanges' tests/developer-slice-ui.test.mjs` — 3 passed, including edit → stale state → rerun recovery → option change.
- `pytest -q tests/developer_routes_unittest.py -k text_diff` — 1 passed.
- `pytest -q tests/engine_developer_unittest.py -k text_diff` — 4 passed.
- `node scripts/check-mock-buttons.mjs design/mocks/text-diff-stale-result.html` — passed.
