# Approved ergonomics companion

Version: 1.0.1 · Approved 2026-10-21; source implementation recorded.

The owner approved the inspected interactive animation/corner mock with **“looks good to me”**. Earlier feedback accepted the character with **“i like character”**, required actual cap-opening/drinking and stretch/eye-rest animation, independently configurable timing for every ergonomics tool, and configurable placement in all four corners. Bose was explicitly excluded with **“leave the bose for now”**. AirPods Pro is the optional sensing target.

## Approved behavior

- Original soft white pear-headed creature with small body, expressive face and blue neckerchief. Water opens a big bottle, sips and recaps; stretching and eye-rest have distinct pose sequences. Retain an accessible static reduced-motion state. The reviewed stop-motion samples establish this visual direction.
- Break, eye-rest, water and optional AirPods head-angle reminders share one Ergonomics workbench and independent opt-in/timing. Expose intervals, durations where meaningful, individual snooze and posture dwell/cooldown, quiet hours, pause/resume and preview.
- Top-left, top-right, bottom-left and bottom-right positions move companion and prompt together. Present without stealing the user's current app focus. Keep actions inside the screen's usable area.
- Head motion is a calibrated relative head-angle estimate, not a spine/posture diagnosis. No camera, microphone, cloud processing or stored motion history.
- Reminders continue while the macOS main window is hidden, end on explicit Quit, and do not install autostart. Permission denial/disconnection is visible; timed reminders remain usable.

## Evidence and scope

The temporary settings and animation mocks were inspected in new Superset Browser tabs. All three animations advance, all four corners fit at 1280px and 390px without horizontal overflow, and reduced motion freezes the character. The exact generated prompts, source sheets and playable GIFs are retained in `design/assets/`; sample verification is in `design/assets/ergonomics-animation-samples.md`. Desktop screenshot: `design/assets/ergonomics-companion-v2-preview.png`.

Approved implementation sequence follows `docs/hld/pending-tools-and-ergonomics.md`: ergonomics first, then the remaining roadmap groups. Source, browser, native hardware and installer acceptance remain separate. This approval does not claim real AirPods data, native focus retention, smooth rigged animation or release readiness have been tested.
