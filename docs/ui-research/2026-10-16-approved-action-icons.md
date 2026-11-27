# App-wide action icons

Approved 2026-10-16 with “ok do it for all the screens”, following the icon-and-label proposal. The HTML before/after mock was opened in a new Superset Browser tab and visually inspected; retained evidence is `.test-artifacts/action-icons-mock.png`.

## Shared rule

Use the existing Font Awesome set inside daisyUI buttons, with 16px decorative icons and an 8px label gap. Keep action labels and accessible names. Reuse existing icons rather than inserting duplicates. Cancel, Clear, Reset and Close are quiet text actions. Sidebar, tabs, tool cards and canvas tool affordances retain their established patterns.

Use explicit semantic icons for the reusable file-tool Run button. Preserve icons when pending states or native file selections replace button text; update the icon when the action changes. Main task actions retain Ice Blue; secondary and Trash actions retain their approved neutral treatment. Final destructive confirmation retains its explicit error treatment.

## Evidence and limits

- Node regressions cover action semantics, quiet exceptions, bundled Font Awesome glyph availability and desktop asset inclusion.
- Superset Chromium inspected all 71 authenticated tool/shell destinations at 1440, 900 and 390px in light/dark themes (426 route/layout checks). No horizontal overflow, duplicate owned icons or icon size/gap failures.
- Live DOM regressions cover initial insertion, pending updates, changed actions, existing icons, excluded tabs, selected filenames, and computed/text/binary result actions. These use synthetic results without clipboard, file writes or Trash operations.
- This is an icon/layout acceptance pass, not evidence that every engine's result flow passed. Native WebKit launch and installed DMG mounting remain blocked by this session's macOS GUI/disk-image services. The earlier HEIC Similar Images failure is outside this change and remains unresolved.

The full Node suite passed (592 passed, one skipped). `npm run build` succeeded using the verified disk-image fallback. The refreshed `OfficeKit_1.0.0_aarch64.dmg` is ad hoc signed and unnotarized; SHA256 `c6af073c90c2a8e270a4bad8885193e4f7ccd7dc44ee5d4a60c9b8e6f0650d0e`. No installed/native acceptance is claimed.
