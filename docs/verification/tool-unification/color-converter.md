# Color Converter verification

## Installed run — 2026-11-02

In OfficeKit 1.0.77, entered `not-a-color` as HEX and pressed Convert color. The field stayed editable and the converter correctly rejected it, but the screen showed both “Enter a valid color to preview it.” and “HEX color must use #RGB, #RGBA, #RRGGBB or #RRGGBBAA” with two Report bug buttons. It also kept a disabled Copy button. The invalid screen therefore showed five buttons: two Report bug actions, Copy, Convert color, and Clear.

Corrected the field to `#0f0` and converted it to RGB. The result was `rgb(0, 255, 0)`. The output still showed the preview Report bug action, while Convert, Clear, Copy and Download remained visible (five buttons). Download saved a text report; the saved text preserves the input format/value, target format and exact result. It was saved temporarily as `/tmp/color-converter-audit-20261102.txt` and removed after inspection.

The installed app’s bottom action container remained stale from the previously opened Files tool: it read “Empty file finder” with a disabled “Find files” action while Color Converter was active. This confirms a live installed-build mismatch in shared action ownership as well as the tool-specific button-count issue.

## Current-source checks and screenshots

- `node --test tests/color-converter-ui.test.mjs`: 9/9 passed. The current-source regression covers local invalid guidance, stale-result clearing, bug-report suppression, shared action state, and the three-action successful result dock.
- `pytest -q tests/test_color_converter_api.py`: 4/4 passed.
- Before/after screenshots: `before/color_converter-invalid-desktop-webkit.png` shows the pre-fix validation Report bug CTA and inline action; `after/color_converter-current-source-invalid-20261031.png` shows editable invalid input with only Convert/Clear in the shared dock; `after/color_converter-current-source-recovered-20261031.png` shows `#0f0` and the Clear/Copy/Download dock.
- The installed screen was captured in the audit session but the available desktop capture interface did not persist it. The source screenshot pair is retained; it does not claim installed/source screenshot parity.

The source implementation already has the approved recovery behavior. This milestone records the old installed bundle’s reproducible defect and the current-source evidence; installed/current-build parity, native clipboard, compact layout and keyboard checks remain open.
