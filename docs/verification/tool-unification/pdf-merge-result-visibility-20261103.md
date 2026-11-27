# Merge PDFs result visibility

The reviewed mock keeps both selected files and the three shared actions while bringing the merged filename and size above the fixed action dock. It was inspected in Superset Browser before implementation.

On the live source screen, the result initially ended 27.6 px beneath the dock. The Merge PDFs completion path now scrolls the preview into view with a 12 px margin. A `ResizeObserver` repeats that adjustment if action feedback expands the dock, such as after Copy.

Verification on 2026-11-03 used two synthetic 626-byte PDFs. The merged result was `first_merged.pdf` (1.0 KiB), and the exact copied summary was:

```text
Merge PDFs
Output: first_merged.pdf
Size: 1.0 KiB
```

After the Copy confirmation expanded the dock, the preview remained visible with a 12.4 px gap. The action bar retained exactly three buttons: Select PDFs, Copy summary and Download. Source screenshot: [after/pdf-merge-output-visible-source-20261103.png](after/pdf-merge-output-visible-source-20261103.png). Reviewed mock screenshot: [mock/pdf-merge-result-reveal-review-20261103.png](mock/pdf-merge-result-reveal-20261103.png).

Focused checks passed: `npm run build:ui`; three PDF result-reveal Node tests; `node --check ui-tests/pdf-protect.spec.mjs`; and `pytest -q tests/test_pdf_endpoints.py -k merge` (7 passed). The Playwright merge scenario now checks preview visibility both before and after Copy feedback; this browser test was not run in this milestone.
