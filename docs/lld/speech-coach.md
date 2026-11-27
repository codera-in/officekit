# Speech Coach and menu bar controls LLD

version: 1.12.0 · 2026-10-27 · Implements `docs/hld/speech-coach.md` 1.12.0.

Workspace sentence coaching calls `officekit_dictation_language_suggestion` with focus 3, an 8,192-byte output buffer and a 15-second upper deadline. Foundation Models generates a typed improvement flag and replacement; the bridge supplies the verbatim source quote. Rust validates 2,000-byte phrase bounds, supported category, unchanged digit runs and safe response fields. `check_workspace_sentence` returns one valid whole-sentence rewrite or Harper corrections, avoiding overlapping Copy alternatives. HUD focus 1/2 retains its existing prompt, 160-byte phrase bounds and five-second deadline. `npm run test:coach-model` explicitly tests the shipping bridge against the actual local model; Rust fixtures independently exercise sentence extraction, validation, transcript marking, Copy and fallback paths.

## Current implementation boundary

- The native panel and coach capture lease share the STT microphone engine. Coach-only local ASR drains bounded 10–15 second windows only when STT and meeting recording are idle; temporary samples are cleared after inference. The worker uses the selected local model and skips a window if the model lock is busy.
- Coach-only sessions aggregate recognized-word, filler and pace metrics in memory and save them at pause, disable or app exit. Persisted notes contain no recognized text or audio. STT sessions continue to save after their normal completed transcript event.
- The local model interface has no calibrated confidence score. The implementation gates cues on at least 20 recognized words and 10 seconds of voiced time, labels pace as estimated and does not show a confidence badge. Noise and overlapping-speaker abstention still need real-device validation.
- Pitch median and variation are computed from voiced frames, displayed descriptively in the HUD during coach-only and STT sessions, and aggregated for history. Synthetic voiced/silence/noise tests cover the estimator; microphone accuracy, model/device variation and meaningful personal-baseline trends remain unvalidated.
- User-selected grammar/vocabulary focus analyzes only complete sentences with Apple's Foundation Models when the local system model is available. It validates exact source quotes and a fixed issue-category allowlist, emits at most one optional suggestion, and persists only bounded category counts/pattern IDs. Transcript text and model wording remain transient; no remote fallback exists. Human correctness and accent evaluation remain required before claiming dependable corrections.
- The workspace webview stores only the Auto-clear minute choice (`0`, `5` or `10`) in local storage. It watches the raw transcript represented by snapshots; a changed transcript resets the inactivity deadline. On expiry it invokes the existing `coach_workspace_clear` command, which clears transient transcript/fixes and preserves the open listening session. A refresh epoch prevents an already-running snapshot poll from restoring text cleared by a timer or manual Clear.

## Interfaces and settings

- Add versioned, bounded local coach settings: enabled, paused, overlay visible, placement preset/custom normalized coordinates, context preset, cue interval and history retention. Defaults keep coach disabled until the user opts in. Parse unknown fields strictly and reject oversized files atomically.
- Native capture lifecycle is a single owner in Swift. Consumers are tracked by purpose (`stt`, `meeting`, `coach`); a recursive lifecycle lock serializes start, upgrade and stop transitions so concurrent coach/STT requests cannot construct competing engines. The mic engine is stopped only when no consumer needs it. Meeting system-audio samples never enter coach features. STT's current explicit capture continues to function when coaching is paused or disabled.
- Runtime reports distinct `disabled`, `paused`, `waiting_for_speech`, `analyzing`, `coaching`, and `unavailable` states plus `languageModelAvailable`. State transitions update tray controls. When a model is unavailable, its mode abstains and the UI states why.
- Coach analysis consumes bounded ephemeral 16 kHz mono frames. Compute voice activity, YIN-style pitch median/range and speech duration; erase frame buffers after analysis. During STT, calculate pitch on transient decoder chunks and summarize at most four evenly spaced three-second windows at session end. Pace is computed only from finalized recognized phrase word counts and eligible speech duration. No interim preview is counted twice.
- A cue is eligible only after minimum eligible data and sufficient ASR/analysis quality. Use a cooldown and one active cue; the same actionable pace cue may recur after the cooldown. Language analysis runs asynchronously, only for a newly completed sentence and the selected grammar/vocabulary focus; exact source quote, number preservation, allowed issue ID, response bounds, opt-in model availability, active originating capture and matching capture generation are required before display. The cue says to check it against intended meaning.
- Standalone analysis snapshots a coach capture epoch, dictation capture-mode epoch, and overlay generation before draining a microphone window. Recheck all three after inference before recording session metrics or emitting live cues; asynchronous language results also retain the originating coach epoch. Discard stale windows after pause, disable, context change, dictation, meeting recording, or a new standalone session.
- Store bounded session summaries and optionally retained text examples in an atomic versioned JSON file. Summary schema includes context, user-selected focus, next-session practice goal, timestamps, speech seconds, recognized-word count, pace windows, filler counts, pitch statistics, language issue-category counts/IDs, metric availability, insight usefulness feedback and dismissed cue identifiers. No raw audio, recognized sentence or generated suggestion is persisted by default. Aggregates are recomputed from retained sessions and excluded examples.

## Native commands, events and menu

- Add Tauri commands for coach settings/status, explicit start, pause/resume, enable/disable, hide/show, placement, session end, notes list/retention/clear/dismiss, and `disable_all`.
- All commands validate state transitions and return resulting status; menu actions call the same state functions as UI actions.
- Add native menu toggle items for coach, Listen In, STT, Window Manager, Ergonomics and Meeting Recorder, a Disable all item, and placement choices. Listen In sets the existing coach context to `practice`, starts shared coach capture, and stops it when switched off. Derive its active state from enabled coach settings plus Practice context; do not add a second toggle store. Tooltips/accessibility descriptions name each action. Reflect state from the owner subsystem.
- Window Manager pause reuses `GlobalDesktopSettings.windows_enabled`; Ergonomics pause updates reminder scheduling without deleting preferences; Meeting Recorder stop uses its existing normal finalization/publish path; STT pause suppresses new capture starts while finalizing current text safely.
- `disable_all` pauses triggers, stops coach-only capture, then asks active STT and meeting recording to finalize. Return per-tool results and do not claim success until owners report terminal state. Preserve transcripts/recording outputs.
- Native HUD is one NSPanel per session, non-activating, screen-bounded and positioned using stored placement. It contains one pace-zone bar with a marker, one live cue and descriptive pitch. Configured capture exclusion is attempted where supported and verified; never claim a panel is hidden from full-display share absent verified OS behavior.

## In-app Coach notes UI

- Extend Audio & Dictation with three task tabs. For Voice Transcription, use Dictate, Speech Coach, and Setup & history. For Meeting Notes, adapt them to Record & transcript, Meeting notes, and Setup & history; move recorder and transcript-clear actions into exclusive setup disclosures, and show generated-note actions in Meeting notes. Keep the model/permission controls, audio-file import, dictionary, and transcript history in disclosures that open one at a time so no panel exceeds three visible action buttons. Use semantic daisyUI cards, stats, tabs and buttons with responsive Tailwind layout and existing theme tokens.
- Session setup allows choosing a context and one coaching focus. The recap shows one improvement, one recurring pattern and one practice goal; users can mark an insight useful or dismiss it. Carry the chosen practice goal into the next session unless the user changes it.
- Keep setup lightweight: context + one goal, with optional calibration only after the first reliable release. Establish a baseline from multiple comparable sessions, record the metric/model version, and ask the user to confirm a detected recurring pattern before it becomes the default practice prompt. Use usefulness/dismissal feedback to reduce noisy repetition; do not infer accent or ability.
- Provide a concise text-first recap and an optional history/trend view. Label all metrics and periods; chart only comparable samples and show baseline-building/insufficient-data states and sample counts. Show common language issue categories and counts without source phrases; dismiss/useful feedback applies to the category. Pitch and volume remain distinct; show pitch as descriptive median/variation until enough comparable personal-baseline data supports a trend. No composite score, streak or ranking in the initial release.
- Add optional short example retention, dismiss cue, retention period and clear history. Confirm irreversible history clearing in-app; provide accessible empty/error states.

## File map

| Path | Change |
| --- | --- |
| `src-tauri/macos-dictation.swift` | Shared capture consumers, live RMS/voiced pitch frames, one configurable native coach HUD with pace-zone meter, shared-STT generation handling, lifecycle and display migration. |
| `src-tauri/macos-dictation-polish.swift` | Bounded optional Foundation Models suggestion call; only on-device when available. |
| `src-tauri/src/speech_coach.rs` (new) | DTOs, bounded persistence, pure metrics, cue gating, state transition model and commands. |
| `src-tauri/src/lib.rs` | Register coach module/commands, join finalized STT segments, coordinate Disable all and shutdown. |
| `src-tauri/src/workspace_native.rs` | Menu bar icon state controls and action routing. |
| `src-tauri/src/global_desktop.rs` | Expose idempotent window-manager pause/resume through existing settings owner. |
| `src-tauri/src/ergonomics.rs` | Expose reminder pause/resume without clearing saved preferences. |
| `index.html`, `assets/officekit-ergonomics.js` | Coach notes, progress, controls, menu synchronization and real measured values. |
| `tests/` and `ui-tests/` | Metric/state/persistence/capture coordination, menu and notes UI, privacy, bounds and failure regressions. |
| `DESIGN_SYSTEM.md`, `docs/VERSION-HISTORY.md`, `docs/TESTING.md` | Record approved widget/controls, doc versions, validation and native acceptance evidence. |

## Build checkpoints

1. Pure metrics, settings/session DTOs, bounded atomic store, and state-machine tests.
2. Native shared-capture hooks, bounded coach-only ASR windows and Swift bridge tests; no second mic engine during STT. Validate local model accuracy on installed hardware before calling standalone cues dependable.
3. Runtime commands/events and menu bar actions, including safe Disable all finalization.
4. HUD placement and privacy/position behavior, then in-app notes and progress UI.
5. Focused tests, full applicable suites, installed app checks, review, release build and PR.
6. After first-release reliability is established, evaluate optional calibration and context-specific baseline comparisons; ship personalization only when its metrics and prompts remain understandable, comparable, and useful in human evaluation.

## Test cases

- Pace has no estimate below minimum speech/word evidence; pause and silence don't inflate the denominator; transcript revisions are deduplicated.
- Pitch rejects unvoiced/noisy frames and reports median/range separately from loudness; synthetic checks do not replace installed microphone validation or justify universal pitch targets.
- Language suggestions require a complete sentence, exact quoted source substring, supported category ID, unchanged numeric runs, response size bounds and no duplicate within the recent window. Tests cover invalid/unavailable/no-op model responses and ensure only issue IDs/counts enter session history.
- Low quality suppresses cues. Cue cooldown bounds prompts; dismissed patterns stay suppressed.
- Settings/session store rejects unknown/oversized/corrupt payload without losing previous valid file; retention and clear recompute aggregates.
- STT + coach share capture; pausing/disabling coach doesn't stop STT. Meeting playback/system audio doesn't enter speaker metrics.
- Device/route changes, permission revoke, model unavailable and app shutdown cleanly release consumer leases and HUD.
- Disable all preserves active STT and meeting outputs and reports owner failures truthfully.
- Tray actions mirror actual owner state, persist intended preferences, and remain accessible with tooltips. Listen In can start and stop solo practice without STT or a meeting app, and stays synchronized with Speech Coach. HUD placement remains visible after screen topology changes.
- Notes empty, baseline-building, comparable-history, recap usefulness/dismissal, focus/goal persistence, error, clear-confirmation, compact width, keyboard, button count and theme behavior.
