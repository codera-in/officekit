# Approved Title Bar Cleanup, Activity Screen Simplification, and App Tour

On 2026-10-18, the user requested removing the microphone shortcut and Activity button from the title bar, introducing an interactive on-device App Tour, and simplifying the Activity screen. The user approved the proposals with “approved”.

The approved mocks were reviewed from `design/mocks/app-tour-review.html` and `design/mocks/activity-simplification-review.html`. Visual evidence is retained at `docs/ui-research/2026-10-18-app-tour-approved-mock.png` and `docs/ui-research/2026-10-18-activity-simplification-approved-mock.png`. Per the repository mock review workflow, the temporary mock files are removed after approval.

## Approved Decisions

### 1. Title Bar Cleanup
- **Remove Microphone Shortcut:** Speech-to-Text Studio is already permanently available in the sidebar navigation with its `PTT` badge and searchable via ⌘K Spotlight.
- **Remove Activity Button:** Activity is already permanently available in the sidebar navigation rail with live count badges and searchable via ⌘K Spotlight.
- **Add App Tour Button:** A dedicated, lightweight `Tour` trigger (`<button id="officekit-tour-trigger" ...><i class="fa-solid fa-compass"></i> Tour</button>`) sits beside the `100% On-Device` badge and provides on-demand access to the interactive walkthrough.

### 2. Interactive App Tour
- **On-Device Guided Spotlight Walkthrough:** 5 focused steps highlighting:
  1. `100% On-Device Privacy` (Header privacy badge)
  2. `Spotlight Quick Search (⌘K)` (Header search bar)
  3. `Workspaces & Tool Gallery` (Sidebar tool suites)
  4. `Speech-to-Text Studio` (Sidebar PTT item)
  5. `Live Activity Monitor` (Sidebar Activity item)
- **Controls & Persistence:** Keyboard navigation (<kbd>→</kbd>, <kbd>←</kbd>, <kbd>Esc</kbd>), step dots indicator, and "Don't show on start" preference stored in `localStorage.getItem('officekit.tour.seen_v1')`.
- **Zero Telemetry:** 100% client-side, zero network calls.

### 3. Activity Screen Simplification
- **Streamlined Empty State:** Replaces verbose, multi-section disclaimers with a single, clean Apple-grade empty state card ("No active operations") and a compact saved results section.
- **Preserved DOM Contracts:** Keeps `#officekit-activity-content` and `#officekit-activity-history` for live job tracking and test compatibility.
