# Developer Utilities: Format JSON verification

## Current worktree evidence

On 2026-11-02, the current worktree client was checked with valid input `{"name":"Ada","active":true}` and malformed input `{"name":`. The valid result preserved the values and was formatted with two-space indentation. Malformed JSON was rejected before a request, retained for editing, and returned focused syntax guidance. The source UI state clears stale output and result actions and omits Report bug; valid retry restores the result actions.

- `node --test tests/developer-utilities-ui.test.mjs`: 21/21 passed.
- `pytest -q tests/test_e2e_modular_api.py::test_devtools_api_json_and_hashes tests/test_devtools_validation_unittest.py -k json`: 17 passed, 36 subtests passed.
- A focused current-worktree Format JSON client check: 2/2 passed.
- Before/after source captures: [invalid input](../after/devtools-format-invalid-current-source-20261031.png) and [recovered result](../after/devtools-format-recovered-current-source-20261031.png). The reviewed mock capture is [here](../mock/devtools-format-invalid-recovery-superset.png).

The mock contrasts the installed stale-result/report-bug state (4 controls, over the limit) with retained editable input, field guidance, no report action, and one Run action. Its button checker passed and the mock was viewed in a new Superset Browser tab.

## Installed OfficeKit 1.0.77 evidence

The installed build correctly formatted valid JSON, and Copy/Download matched the displayed result. For malformed JSON it retained the input but showed generic processing feedback plus Report bug; correcting the input did not clear the error until Run. This is the earlier installed behavior, not a failure of the current worktree source. The full installed screenshots are in the adjacent `json-formatter-*-officekit-1-0-77.jpg` files.

This milestone commits the source recovery for the Developer Utilities workspace. The installed 1.0.77 build still predates it. Fresh current-source native Copy/Download verification and a matching installed build remain open.
