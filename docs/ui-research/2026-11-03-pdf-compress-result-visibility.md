# Compress PDF result visibility

## Decision

When Merge PDFs, Extract PDF Pages or Compress PDF creates a file, scroll the result preview above the shared bottom action dock and retain a 12 px gap. Re-run that positioning if the dock changes height.

## Reasoning

The fixed dock can cover the result even though the PDF operation succeeded. People need to read the output name and size comparison before choosing Copy or Download. Sharing one reveal path across these three PDF workbench tools prevents their result layouts from drifting.

## Verification

- The mock was opened in Superset Browser and passed the 3-button checker.
- Live source showed the completed Compress PDF preview 8.6 px behind the dock before the fix. After the fix, the preview remained 12.4 px above the dock after Copy feedback.
- Focused checks and source/native limits are recorded in [the Compress PDF evidence](../verification/tool-unification/pdf-compress-result-visibility-20261103.md).
