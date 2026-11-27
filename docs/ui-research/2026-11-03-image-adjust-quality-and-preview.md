# Image Color Adjustments: format-aware quality

The shared image rendition controls now disable Quality when the selected output is PNG or the source format does not use a quality setting. The value stays visible and is retained so switching back to JPEG or WebP is reversible. When quality applies, values outside 1–100 stay editable, show linked field guidance, and disable Save until corrected. This matches the approved shared image rendition treatment reviewed for Grayscale Image.

The dedicated browser regression `ui-tests/image-adjust-quality.spec.mjs` covers a 2×2 PNG, disabled/enabled format states, invalid-quality recovery, brightness preview, saved-output pixels, and the three-button cap. The API adjustment regression passes (1/1), and the shared image UI contract suite passes (47/47).

The focused browser run was attempted on 2026-11-03. Playwright WebKit 2359 aborts during browser launch with `Abort trap: 6`, before test setup or assertions. No fresh browser screenshots were captured in that run. Archived tool screenshots remain available at `docs/verification/tool-unification/before/image_adjust-initial-branch-baseline-superset.png` and `docs/verification/tool-unification/after/image_adjust-{initial,preview,saved}-desktop-webkit.png` and the corresponding compact captures.

Still open: fresh browser screenshots and execution, keyboard reset interaction, Copy image through the live adapter, and installed/native behavior. This tool remains in progress until those checks have evidence.
