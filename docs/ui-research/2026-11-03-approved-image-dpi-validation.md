# Image DPI / PPI validation behavior

## Decision

Keep horizontal and vertical density values editable when they are invalid, attach the range guidance to each invalid field, and mark the field with `aria-invalid`. Hide the calculated print size until both values are whole numbers from 1 to 2,400. Explain the correction in the shared action dock and disable Save copy until the values are valid. Once corrected, restore the print-size calculation and Save copy action. Keep the existing one-action dock and preserve the image's pixel dimensions.

This keeps a user from mistaking a fabricated print size for a valid measurement, tells them exactly which value needs attention, and avoids discarding their input. The three-state mock showed one counted button per state and passed `scripts/check-mock-buttons.mjs` before being removed after review.

## Current-source review

Reviewed in Superset Browser on 2026-11-03 using a generated 300×150 PNG. At x=2401 per cm, the current source marks Horizontal density invalid, links the inline message to the field, suppresses the print-size calculation, and disables Save copy. Correcting to 150×75 per cm restores `2.0 cm × 2.0 cm` and enables Save copy. Saving through the result adapter returns `print-size-dpi.png` as PNG at 300×150 px with `pHYs` values 15000×7500 pixels/meter (unit=1); the dock reports that the original is unchanged.

Screenshots:

- Before, invalid value: `docs/verification/tool-unification/before/image_dpi-current-source-invalid-20261103.png`
- After, invalid guidance: `docs/verification/tool-unification/after/image_dpi-current-source-invalid-20261103.png`
- After, corrected values: `docs/verification/tool-unification/after/image_dpi-current-source-recovered-20261103.png`
- After, saved result: `docs/verification/tool-unification/after/image_dpi-current-source-saved-20261103.png`
- Reviewed mock: `docs/verification/tool-unification/mock/image-dpi-invalid-guidance-review-20261103.png`

This verifies the current-source web flow. Installed/native behavior and fresh automated tests remain unverified in this milestone.
