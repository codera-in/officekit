# Extract PDF Text: reveal the complete result

**Milestone:** Extract PDF Text, one tool per commit.

The result used a separate `requestAnimationFrame` scroll to the top of the preview. The shared workbench `finally` flow did not include the text tool, so dock resizing could leave the summary or extracted text preview behind the fixed action bar. The text-specific scroll could also compete with the shared result positioning.

**Decision:** After a successful extraction, align the result preview above the dock with 12px clearance and let the shared dock `ResizeObserver` keep it visible after Copy/status changes. Keep the existing Copy text, Download and Select PDFs actions unchanged. The before/after mock has 3/3 buttons in both states and passed `node scripts/check-mock-buttons.mjs`; browser review capture: `docs/verification/tool-unification/mock/pdf-text-result-reveal-review-20261103.png`.

**Implementation:** The text tool now uses the shared result-reveal path, and its former start-aligned animation frame is removed. The browser regression asserts the preview bottom stays at least 8px above the dock.

**Checks:** `npm run build:ui` passed. `node --test tests/pdf-text-result-visibility.test.mjs tests/pdf-workbench-ui.test.mjs tests/pdf-tools-ui.test.mjs` passes 84/84. `pytest -q tests/test_pdf_text.py` passes 20/20. `node --check ui-tests/pdf-text-extraction.spec.mjs` and mock button check pass. Fresh browser execution remains unavailable: WebKit aborts before setup and cached Chromium fails macOS Mach port bootstrap before setup. Therefore current-source geometry, compact runtime, keyboard and installed native save remain unverified.
