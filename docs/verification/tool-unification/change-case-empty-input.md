# Change Case: blank-input recovery

## Decision

For blank input, keep the editor available, mark it invalid, and show “Enter text to change its case.” as local field-linked guidance. Clear any stale result and keep Copy and Download disabled; do not offer Report bug for this correctable input. On edit, clear the invalid state and replace stale completion feedback. A valid run restores the output and the normal three-action dock.

The user-approved mock is retained as `mock/text-case-empty-input-superset.png`; it shows the prior completion state and corrected state, each at 3/3 actions. The separate edited-input status mock was reviewed previously and is documented in `docs/ui-research/2026-10-31-tool-ux-fixes.md`.

## Verification

- Full developer-slice UI suite: 62 passed.
- Change Case blank/edit recovery contract: 1 passed.
- `pytest -q tests/developer_routes_unittest.py -k text_case`: 2 passed.
- `pytest -q tests/engine_developer_unittest.py -k case`: 19 passed.
- `git diff --check`: passed.
- No fresh app screenshot was captured in this milestone; existing source screenshots are historical audit evidence, not a new run of this commit.

## Remaining checks

Compact layout, keyboard/focus, native clipboard/save and installed-app behavior remain open.
