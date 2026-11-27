# Pending tools and ergonomics — proposed architecture

version: 1.0.9 · 2026-10-26 · Eye-rest prompts guide far focus, slow blinking and side-to-side gaze with cue-matched poses.

## Scope and delivery order

Use the existing local Python API, Tauri shell and vanilla JavaScript workbenches. No framework migration, cloud account, tenancy database, or AI runtime is required. Source registry and exact frontend destinations remain the discovery authority. The existing roadmap remains a depth contract, not a completion count.

| Slice | Roadmap coverage / work | Reuse |
| --- | --- | --- |
| 1 | New break, eye-rest, water and AirPods head-angle companion | Tauri lifecycle, shared tokens, local settings patterns |
| 2 | C06–C07 and C15–C25: average/weighted average, fractions, ROI, CAGR, date difference, age, business days, work hours, time zones, quadratic, GCD/LCM, statistics, geometry | Existing calculator form/result/export patterns; exact rational/calendar policies |
| 3 | D04, D10–D11, D15–D17: structural JSON diff, timestamp, UUID, QR, text metrics/case, text diff | Developer workbench, strict JSON handling, local exports |
| 4 | F02, F05, F09–F11; S05; complete S06 restore policy; expose existing F06/F07/F12 archive discovery | Native selection grants, bounded scans/jobs, archive engine, reviewed cleanup |
| 5 | I06–I07, I10–I12, I14–I20: rotate/flip, EXIF view, DPI, grayscale, adjustments, borders, palette, Base64, icon pack, collage, contact sheet, visual comparison | Pillow image engines, Media Toolkit and Screenshot Editor where equivalent |
| 6 | P06, P08, P10, P12–P13, P15–P17: page rotation, ordered images→PDF, metadata view, watermark, numbering, page dimensions, grayscale, flatten | Existing PDF workbench and bounded encode limits; verify real rendered content |
| 7 | Remaining depth gaps and installed acceptance across all original roadmap rows | Existing unit converters, system/network, audio, Media Toolkit, PDF/image/file engines |

P14 crop, image watermark/crop/blur and image compression already have meaningful implementations in media/editor tools; route and complete their depth instead of duplicating them. Each slice requires an approved mock for its visible changes and its own concrete contract before implementation. Slices 2–7 are not silently deferred out of the requested scope.

### Slice 7: promoting a tool to private beta

Slices 2–6 ship development-only. A tool moves into private beta during slice 7 only when it passes installed acceptance. Its promotion PR does all of the following together:

1. Adds its ID and routes to `release-profile.json`.
2. Adds its agent action to the matching `officekit_*` group in `officekit/mcp/registry.py`. The groups are `officekit_calc` (calculators), `officekit_dev` (developer tools), `officekit_pdf` and `officekit_image`. The parameters come from the OpenAPI schema, so `officekit_help` covers the new action with no extra work.
3. Adds the action to the agent skill and to the tools table in `docs/MCP-AGENT-SUPPORT.md`.
4. Extends `tests/mcp_server_unittest.py`, which checks that every action maps to a route in `release-profile.json`.

The existing agent safety model still applies:

- No action may generate a secret, delete a file or overwrite a file.
- Inputs must stay inside the allowed folders.
- File-job tools are not exposed to agents. These are the files slice's file info, compare, age and empty-file/folder finders, plus the archive jobs, because they rely on native file grants.
- The sensitive-route check in `assert_no_sensitive_actions()` is never bypassed.

A tool that cannot meet these rules stays app-only, and its promotion PR records why. Development-only tools are never exposed to agents early; the release-profile check in the MCP tests stays as it is.

## Ergonomics architecture

One Rust-owned scheduler handles all reminder types independently of WebView throttling. A small separate companion window renders a bundled original creature and the current reminder. It is hidden by default, borderless and transparent where supported, stays above normal windows, and does not activate on presentation. Explicit keyboard access opens it deliberately. Native behavior on full-screen Spaces, multiple displays and task switching requires installed checks; unsupported platforms report limitations.

Character direction: the owner requested more playful physical comedy like Vodafone ZooZoo. Use an original matte soft creature with an oversized expressive head and tiny body, replacing the initial robot concept. Break prompts stretch, eye prompts look away, water prompts mime a sip, and head-angle prompts gently reset. No speech/audio is necessary; short nonlooping gestures carry the cue, with static poses for reduced motion. Asset generation is design exploration, not approval or a claim of finished animation.

The owner accepted the character identity and clarified that actual animation is required: water opens a large bottle cap, drinks and recaps; stretch shows a complete stretch-and-relax cycle; eye-rest guides far focus, slow blinking and side-to-side gaze with a matching pose for each cue. Generated pose sheets are prototype inputs, not proof of smooth animation. Persist a validated four-value corner preference (top-left/top-right/bottom-left/bottom-right). Anchor the character and prompt as one unit inside the selected display's usable bounds; recalculate on display/work-area changes so no control is offscreen. Browser mock positioning does not establish native multi-display behavior.

The main Ergonomics workbench owns enablement, timing, quiet hours, motion preference, preview and AirPods calibration. It receives typed state events; the companion polls only a narrow native state command and uses the current-reminder action. The companion has no event-plugin permission, file grants, microphone, arbitrary shell, licensing secrets or general web navigation access. A Tauri invoke guard restricts commands to the intended windows.

Every reminder has independent configurable timing: break/eye/water intervals, break/eye durations, and per-kind snooze. AirPods nudges expose sustained-tilt dwell and minimum spacing rather than pretending sensing is a periodic timer. Applying a changed schedule re-arms that reminder from now; it cannot cause immediate catch-up prompts. Save validates the complete timing set atomically and retains previous settings on failure.

Persist versioned validated preferences through the existing app-data settings pattern, with atomic writes and safe defaults. All reminders and sensing start disabled. Runtime due dates, raw sensor samples and current prompt remain in memory; restart begins a fresh interval. System sleep/wake re-arms intervals without replaying missed prompts. Quiet hours are interpreted in local wall time; interval durations use monotonic elapsed time while awake. Only one prompt is active; coincident reminders coalesce or queue with a short bounded expiry, never stack windows.

Only deliver automatic reminders while the user appears active: system keyboard, mouse or trackpad input within five minutes, or non-silent audio within the same window from an already-authorized OfficeKit voice-capture session. A silent open microphone does not count. Mic activity uses a short RMS level check inside the existing capture callback; it installs no additional capture, requests no new permission, exposes no audio samples to the scheduler, and persists no signal history. Microphone use by other apps is not inspected. If inactive, automatic prompts hide and due reminders remain pending until activity resumes; previews remain immediate. The current native activity detector supports macOS; other platforms fail closed, and the workbench states that automatic reminders are unavailable there.

AirPods uses a small macOS Swift Core Motion adapter behind a Rust boundary. Query authorization/availability before starting, request permission only on deliberate enablement, and tear down updates on disable/Quit. A short still calibration establishes pitch/roll reference. Compare relative orientation with named threshold, dwell and cooldown constants; suppress motion while unstable, disconnected or stale. Hardware data informs a gentle head-position nudge only. No biometric classification, camera, audio capture or persistent sensor history.

## Implemented native boundary

| Native command/event | Request / result |
| --- | --- |
| `ergonomics_get_state` | No input → versioned settings, enabled/paused states, next-due summaries, motion status |
| `ergonomics_update_settings` | Strict bounded settings → validated resulting state; reject unknown keys/invalid timing |
| `ergonomics_reminder_action` | Current opaque reminder ID + start/done/snooze/pause → resulting state; stale ID rejected |
| `ergonomics_preview` | Allowed reminder kind → visible preview without changing live schedules |
| `ergonomics_motion_action` | enable/disable/calibrate → not-enabled/permission-needed/denied/unavailable/calibrating/ready/disconnected/stale/error |
| `ergonomics:state` (main only) | Bounded typed state snapshots; the companion does not subscribe to general events |

DTO ranges, actions and window restrictions are now recorded in API-CONTRACT.md. No HTTP routes or stored entities are needed for the reminder slice.

## Pitfalls avoided

- P-177/P-175: no main-thread synchronous native work while holding scheduler/runtime locks. Collect state first, then dispatch UI work without the lock.
- P-176/P-142: preserve macOS 14 minimum; gate Core Motion availability and verify the bundled helper's deployment metadata.
- P-175: test settings in an isolated data directory; distinguish browser mocks from native runtime evidence.
- P-124/P-130: new tool destinations honor release discovery loading/failure and private-beta restrictions.
- P-128: browser success is not proof of native window/permission/sensor behavior.
- P-143: hidden main window leaves the scheduler alive; explicit Quit terminates it.

## Release evidence

Source verification covers deterministic scheduler and motion-policy tests, strict settings/persistence behavior, UI routing and animation, Python search, complete Rust unit/integration suites and source bundling. Installed AirPods permission/calibration, non-activating focus behavior, sleep/wake, multi-display placement and packaged sidecar checks remain open. Ergonomics tools stay development-only. Later groups inherit their roadmap verification cases and file-processing bounds from docs/TESTING.md. A mock or a routed card cannot establish a tool is finished.
