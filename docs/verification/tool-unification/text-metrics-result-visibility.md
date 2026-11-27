# Text Metrics: keep completed results in view

## Decision

After a successful run, move the six metric summary above the editable input and scroll it into view. Keep the shared action dock visible. When the input changes, clear the old summary and completion state; an empty submission keeps the input editable, marks it invalid with linked guidance, clears stale result actions, and suppresses Report bug. Correcting and rerunning restores the metrics and normal result actions.

The mock was opened and inspected in a fresh Superset Browser tab. Its first preview exposed a clipped summary and dock controls constrained by the shared CSS, so I corrected the scroll position and mock layout before implementation. The final desktop mock shows all six metrics, the editable input, and exactly three dock buttons in the successful state. The button checker passes.

## Evidence

- Mock before: `mock/text-metrics-result-visibility-before-superset-20261102.png`.
- Mock after: `mock/text-metrics-result-visibility-after-superset-20261102.png`.
- `node scripts/check-mock-buttons.mjs design/mocks/text-metrics-result-visibility.html`: passed before the temporary mock was removed.
- `node --test --test-reporter=tap tests/developer-slice-ui.test.mjs`: 62 passed.
- Focused Text Metrics recovery contract: 1 passed.
- `pytest -q tests/developer_routes_unittest.py -k text_analyses`: 2 passed.
- `pytest -q tests/engine_developer_unittest.py -k TextMetrics`: 9 passed.
- No fresh source-app or installed-app capture was made for this milestone.

## Remaining checks

Compact layout, keyboard/focus, native clipboard/save and installed-app behavior remain open.
