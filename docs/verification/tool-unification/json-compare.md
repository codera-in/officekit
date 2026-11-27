# JSON Compare verification

## Inputs and expected output

- Original: `{"a":1,"items":[1,2]}`
- Changed: `{"a":2,"items":[1,3],"b":true}`
- Expected differences: `/a` changed, `/b` added, and `/items/1` changed.
- Recovery case: Original `{` remains editable, receives linked JSON correction guidance, clears any previous report, hides result actions, and does not show Report bug. Correcting it to `{"a":1}` allows Compare to run again and restores result actions.

## Evidence

- Before: [invalid JSON with stale result actions and Report bug](after/json_compare-invalid-malformed-live-source-superset.png)
- After, invalid state: [field guidance with Compare as the only dock action](after/json_compare-invalid-after-fix-live-source-20261031.png)
- After, recovered state: [valid comparison with result actions restored](after/json_compare-recovered-after-fix-live-source-20261031.png)
- Reviewed mock: [JSON Compare shared actions and recovery](../../../design/mocks/json-compare-shared-actions.html)
- Mock screenshot: [invalid and recovered layout review](mock/json_compare-shared-actions-invalid-review.png)

The saved screenshots were captured on 2026-10-31. The focused automated regression was rerun against the source in this milestone; the browser engine still aborts before a fresh Playwright session can start.

## Checks

- `node --test --test-name-pattern='JSON compare|malformed JSON Compare|server JSON refusal' tests/developer-slice-ui.test.mjs` — 3 passed.
- `pytest -q tests/developer_routes_unittest.py -k json` — 3 passed.
- `node scripts/check-mock-buttons.mjs design/mocks/json-compare-shared-actions.html` — passed.
- Full `tests/developer-slice-ui.test.mjs` — 60 passed, 1 failed in an unrelated timestamp test because its assertion reads the uncommitted `index.html` state; the failure is outside JSON Compare's changes.
