# Grayscale Image: quality control and preview behavior

## Decision

Disable the Quality field when the selected output format does not support it, while retaining the current value so it returns if the user switches to JPEG or WebP. Keep the guidance visible: “Only used for JPEG or WebP copies.” Enable the field again for supported formats and keep its existing range validation. This prevents a control that has no effect from appearing editable.

The shared image rendition preview now uses `createImageBitmap` to decode the returned blob when available, with `Image.decode()` as a fallback. In the live source preview, `Image.decode()` remained pending for a valid PNG even though canvas decoding succeeded, which left the view stuck on “Preparing preview…”. Decoding the blob directly resolves that stall before the result is displayed.

## Current-source review

Reviewed in Superset Browser on 2026-11-03. The tool keeps the shared bottom dock with one Save copy button and a format selector. A synthetic 2×2 red/green/blue/transparent PNG previews as ITU-R 601 grayscale pixels `[76,76,76,255]`, `[150,150,150,255]`, `[29,29,29,255]`, and `[0,0,0,0]`. The saved PNG retains the same dimensions, grayscale values, and transparent alpha.

For same-as-source PNG, Quality remains at 90 but is disabled. Switching to JPEG or WebP enables it. Quality 101 stays editable, receives linked range guidance, and disables Save; correcting it to 80 restores Save. JPEG and WebP copies save at 2×2 and 1×1 respectively with grayscale output. A rejected text-file replacement leaves the valid source and preview in place, shows retry guidance in the dock, and permits recovery by selecting a valid image.

Screenshots:

- Before, active unused Quality field and valid preview: `docs/verification/tool-unification/before/image_grayscale-current-source-preview-20261103.png`
- After, disabled Quality and working preview: `docs/verification/tool-unification/after/image_grayscale-current-source-quality-disabled-20261103.png`
- After, JPEG Quality enabled: `docs/verification/tool-unification/after/image_grayscale-current-source-jpeg-quality-enabled-20261103.png`
- After, invalid Quality guidance: `docs/verification/tool-unification/after/image_grayscale-current-source-quality-invalid-20261103.png`
- After, JPEG saved: `docs/verification/tool-unification/after/image_grayscale-current-source-jpeg-saved-20261103.png`
- After, WebP saved: `docs/verification/tool-unification/after/image_grayscale-current-source-webp-saved-20261103.png`
- After, PNG saved: `docs/verification/tool-unification/after/image_grayscale-current-source-png-saved-20261103.png`
- After, invalid replacement: `docs/verification/tool-unification/after/image_grayscale-current-source-invalid-replacement-20261103.png`
- After, valid recovery: `docs/verification/tool-unification/after/image_grayscale-current-source-recovered-20261103.png`
- Reviewed mock: `docs/verification/tool-unification/mock/image-grayscale-unused-quality-review-20261103.png`

The mock showed the active, disabled, and JPEG-enabled states with one counted button per state and passed `scripts/check-mock-buttons.mjs`. The temporary mock HTML was removed after review. The current-source page shows one counted action button, Save copy. `node --test tests/image-tools-ui.test.mjs` passes 47/47. The new Playwright regression was attempted, but WebKit 2359 aborted before setup (`Abort trap: 6`), so the interactive behavior is verified through the Superset Browser flow documented above. Installed/native behavior remains unchecked.
