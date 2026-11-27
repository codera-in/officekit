# Time Zone Converter — current-source verification (2026-11-02)

The current source UI was rendered in Superset Browser against the local development API.

- Valid: 2026-01-15 12:00 America/New_York converts to 2026-01-15T17:00:00Z and Europe/London 17:00 GMT. The shared Copy / Save / Download dock shows three actions.
- Invalid DST gap: changing the input to 2026-03-08 02:30 America/New_York keeps the previous conversion labeled with its original inputs, marks the time field invalid with correction guidance, suppresses Report bug, and disables all three result actions.
- Recovery: correcting the time to 03:30 clears the stale notice and field error and returns 2026-03-08T07:30:00Z with all three result actions enabled.
- Captures: `after/time_zone_converter-valid-current-source-20261102.png`, `after/time_zone_stale-result-invalid-current-source-20261102.png`, and `after/time_zone_stale-result-recovered-current-source-20261102.png`.
- Focused checks: `node --test tests/calculators-slice-ui.test.mjs tests/time-zone-stale-result.test.mjs` (31/31); `pytest -q tests/test_calculators_extra_api.py -k time_zone` (5 passed plus 2 fold subtests).

These are current-source desktop captures. Installed-app behavior, compact layout, keyboard/VoiceOver, native clipboard/save bytes, and a fresh rendered repeated-hour earlier/later interaction remain open. Historical WebKit captures and aborted Playwright startup are not counted as current evidence.
