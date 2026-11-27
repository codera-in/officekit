# Speech Coach and menu bar quick controls

version: 1.12.0 · 2026-10-27 · Status: source implements workspace sentence coaching and optional inactivity clearing; installed acceptance pending.

Live Workspace offers clearer and simpler full-sentence phrasing through Apple's on-device model, including filler reduction and tangled-clause repair. This mode is separate from conservative short HUD cues. Its structured rewrite preserves source evidence and numbers; unavailable or invalid model output falls back to Harper grammar checks. The transcript remains unchanged, and Copy applies the suggested version. See `docs/verification/speech-coach-clarity.md` for the real brainstorm regression and model acceptance evidence.

## Outcome and approval record

Provide a personal speaking coach that offers a useful cue during speech and one useful lesson afterward. Accuracy takes priority over response speed. Success means fewer repeated mistakes and fewer distracting or incorrect prompts, not more prompts.

The owner approved the single Siri-style HUD (“ok approved”), configurable positioning, simultaneous STT coaching, menu bar quick controls, common-mistake notes inside the app, and progress/retrospection (“looks good to me”). The owner subsequently accepted the revised offering and requested “ok update the plan accordingly”. The owner approved a before/after Audio & Dictation mock that groups actions into Dictate, Speech Coach, and Setup & history; the implementation keeps each section within the three-button page limit. The owner also requested Listen In as a direct solo-practice mode in Quick Controls. Earlier HTML mock numbers, confidence badges and charts were illustrative, not measured results.

Approved visual direction: one compact floating HUD, a Control Center-style OfficeKit menu bar popover with tool icons, enabled/disabled state and hover/keyboard-focus tooltips, and an in-app Coach notes/progress view. Preserve these decisions when removing temporary mocks after approval, per AGENTS.md.

## Delivery sequence

1. **Capture and controls:** native capture coordination, manual coach sessions, pause/disable/hide semantics, configurable HUD position, simultaneous OfficeKit STT, and truthful menu bar state.
2. **Reliable live coaching:** pace, pauses and recognized filler patterns, one cue at a time, sufficient observation windows and suppression of uncertain or stale feedback. Pitch variation can be displayed descriptively when reliable; do not invent an ideal voice or a pitch quality score.
3. **Notes and retrospectives:** local session summaries, recurring patterns, dismissible incorrect feedback, comparable progress metrics, retention and clear-history controls.
4. **Language coaching:** optional grammar and vocabulary suggestions after a complete sentence, using only Apple's on-device language model when available. Require an exact source quote, a bounded issue category, and explicit “possible suggestion” wording. Persist only category counts and pattern IDs by default; users can dismiss patterns. Do not send audio or text to a remote service.
5. **Automatic activation:** microphone-activity detection as a convenience alongside manual start. Validate on supported macOS versions and devices before enabling it by default; avoid triggering or sustaining activation from OfficeKit's own capture.

6. **Personalized improvement loop:** after the reliable first release, add lightweight setup calibration, a user-confirmed baseline, and context-specific comparisons. Use the user's selected goal and prior useful/dismissed feedback to choose one next-session practice prompt. Keep calibration optional and explain what each metric means; never infer accent, confidence, or communication ability from pitch or pace. Evaluate whether prompts are accurate and useful across different voices before broadening automation.

First release prioritizes reliable pace and pitch monitoring, filler tracking, STT coexistence, placement, quick controls and useful session retrospectives. Grammar/vocabulary coaching is user-selected and available only when Apple's on-device language model reports ready; otherwise pace and pitch remain available. Quick Controls includes Listen In for solo practice; it selects Practice context and starts the existing local coach monitor without requiring STT or a meeting app. Audio & Dictation keeps three task sections for both transcription and meeting notes; the labels adapt to the active task, and recording controls, transcript actions, and history stay in Setup & history disclosures so each section remains within three visible actions. The core offering is a repeatable loop: choose a context and one focus, get restrained live cues, review an evidence-backed recap, then carry one practice goal into the next session. No cloud processing or new downloaded-model dependency is implied by this plan.

The session-informed product improvements are staged behind that reliability bar: make setup a short choice of context and one goal; keep live feedback quiet and immediately actionable; end with a compact recap that distinguishes measured change from missing or weak evidence; and let the user correct or dismiss a pattern before it shapes future prompts. Add personalization only when repeated, comparable sessions support it. Treat reduced distraction and user-rated usefulness as product outcomes alongside metric changes.

## Implementation boundary and next work

The current source implementation shares the microphone engine with STT. Coach-only mode uses the selected local dictation model on bounded 10–15 second windows when STT and meeting recording are idle; recognized text stays transient, and completed coach-only sessions save aggregate pace/filler and descriptive pitch metrics. While STT is active, its finalized speech drives the pace meter and its bounded audio windows drive pitch display and recap metrics. Complete-sentence grammar/vocabulary suggestions use Apple's on-device language model only when available; accepted outputs quote a verbatim source phrase and persist only issue-category counts and pattern IDs. The overlay displays pitch median and variation without judging them as good or bad. If a required local model is unavailable, its specific coaching mode abstains and reports the reason. This path has unit and native bridge coverage, but real microphone/model accuracy, language-suggestion quality, pitch reliability, route changes, overlap handling and conference-app behavior still need installed acceptance.

Live pitch measurement and display, plus optional on-device grammar/vocabulary suggestions, are implemented in source but have not passed real-device accuracy validation. Live pause/filler cues remain planned. The current local ASR interface does not expose calibrated recognition confidence, so minimum word/time evidence and “estimated”/“possible suggestion” wording are safeguards, not proof of correction accuracy. Do not show a confidence badge or present ASR-derived words as certain. Keep language suggestions visibly optional and evaluate human correctness across accents and contexts before describing them as dependable.

Next, validate standalone recognition, pitch measurements and language suggestions with supported local models and real microphone samples; improve abstention for noise and overlapping speakers before calling them dependable. Establish a personal pitch baseline before adding any trend interpretation, and only add live pause/filler cues after their detection thresholds pass the same accuracy gate. Preserve STT-backed pace and pitch behavior when standalone recognition is unavailable.

## Live widget behavior

- One native, non-activating floating widget across apps and Spaces; no mandatory tool page for live use. Coach and OfficeKit STT share the widget and microphone capture instead of competing or stacking overlays.
- Default placement: top center. Offer position presets, display selection and drag positioning; remember placement locally and restore within available screen bounds after display changes.
- Show one concise actionable cue at a time with a configurable quiet interval, alongside the pace-zone bar and marker. Prefer a cue useful for the next sentence; do not demand repetition or interrupt speech with audio.
- Wait for enough speech to estimate pace, and for a completed phrase to assess language. Mark unavailable measurements as unavailable. Do not equate ASR confidence with correction accuracy or display an unsupported “confidence high” badge.
- Learn a baseline over several sessions. Allow context selection: solo practice, casual conversation, presentation, interview or dictation. Targets are user-adjustable; accent is not treated as a mistake.
- Pitch means fundamental-frequency variation; volume means loudness. Measure, label and store them separately. A volume drop is not a pitch error.
- Other apps' mute controls do not necessarily mute OfficeKit. Make OfficeKit's own capture state visible. Monitor microphone input for the speaker; exclude system playback from coaching and suppress uncertain samples with overlapping voices.
- Full-display sharing may include the HUD. Do not promise exclusion or automatic sharing detection. Provide Hide overlay and allow placement on another display; verify capture behavior per supported conferencing app.

## Menu bar and control semantics

Include Speech Coach, Listen In, Speech to text, Window Manager, Ergonomics and Meeting Recorder, with icons, state and tooltips. Listen In starts a solo practice session without requiring an STT shortcut or meeting app, selects the Practice context, and shares the same mic engine, HUD and notes as Speech Coach. Its state derives from the Speech Coach owner settings; stopping Listen In stops coach-only monitoring. Use existing feature settings as the source of truth; reflect changes made elsewhere. Keep the approved Disable all action. Preserve the repository's button limit through row actions/native switch controls, and count actual rendered buttons rather than disguising extra actions.

| Control | Required behavior |
| --- | --- |
| Pause coach | Temporarily suspend analysis, prompts and notes. Release capture if only the coach needs it; keep active STT capture running. Explicit Resume restores coaching. |
| Disable coach | Persist off; prevent automatic reactivation until explicitly enabled. Do not stop STT. |
| Hide overlay | Hide presentation only. Keep an obvious menu bar indication when analysis/capture continues. |
| STT pause/disable | Suspend new dictation activation; finish/preserve active work safely and expose the resulting state. Never silently discard pending transcript text. |
| Window Manager pause/disable | Suspend its owned global shortcuts and snapping using existing settings; preserve configured bindings. |
| Ergonomics pause/disable | Suspend reminders through the existing reminder controller; preserve schedule/preferences. |
| Meeting Recorder stop/disable | Finish and preserve the active recording/transcript before becoming disabled. Enabling availability must not silently start recording. |
| Disable all | Suspend automatic triggers immediately, then finish and preserve active recording/STT work and release unused capture. Show stopping/error state until completed; never report all disabled if a component failed. Restore only by explicit user action. |

## In-app notes and progress

Each session has a context, duration, analyzed speech duration, recognized-word count, metric availability and exclusion reasons. Before a session, the user can choose a context and a single focus (for example, slower pace or fewer fillers); retain the selection with the session and use it to prioritize relevant cues. Retrospective presents **one improvement, one recurring pattern, and one practice goal**. With no comparable history, show a baseline-building summary instead of an improvement claim. The next session can reuse or change the goal, making practice intentional without turning the experience into a score-chasing game.

- Notes include repeated filler patterns, pace/pause patterns, and optional grammar/vocabulary issue categories with suggestion counts. Do not retain quoted text or corrections by default. Vocabulary alternatives are suggestions, not errors.
- Users can dismiss incorrect feedback. Exclude dismissed items from pattern counts and use local suppression preferences to avoid repeating the same unwanted suggestion.
- Live Workspace offers Auto-clear Off, 5 min or 10 min in its bottom bar. The selected duration is remembered locally; after that much inactivity since the last recognized speech, clear the in-memory transcript and fixes while keeping the workspace open and listening. New recognized speech restarts the timer; manual Clear and closing the panel retain their existing behavior.
- Compare similar contexts with adequate observation time. Normalize fillers per 100 recognized words; report time within the user's pace range as a percentage of eligible speech windows. Explain the metric and denominator.
- Show a short session recap first, with an optional history view for trends across weeks. Keep the recap readable without charts; use trends only when enough comparable sessions exist, and always show the number of sessions included.
- Let users mark a recap insight useful or dismiss it. Use this feedback to suppress unhelpful prompts locally; do not treat a thumbs-up as proof of linguistic correctness.
- Offer a lightweight practice prompt for the next session based on the user's chosen focus and observed pattern. Do not add gamified streaks, competitive rankings or a single composite speaking score to the initial offering.
- Label chart axes, units, dates and sample sizes. Use separate scales/charts for different units. Show missing data and “not enough data”; do not draw invented continuous trends through missing sessions.
- Record target and analysis versions so changing targets/models does not masquerade as improvement. Separate changes in speaking behavior from changes in recognition quality.
- Report pitch descriptively against personal baseline; avoid universal good/bad thresholds and aggregate speaking scores without validated meaning.
- Save summary metrics locally by default. Short text examples are optional; retain no audio. Provide retention choice and clear-history. Bound stored data, rolling audio buffers and analysis queues.

## Integration and implementation constraints

- `src-tauri/macos-dictation.swift`: existing shared AVAudioEngine capture, live RMS feed and native NSPanel. Introduce coordinated consumers and bounded feature analysis; do not start a second OfficeKit mic engine for coaching during STT.
- `src-tauri/src/lib.rs`: dictation runtime, recognized-segment events, model availability, stop/finalization and command state. Coach observes original recognized phrases before cleanup, with segment identifiers to prevent double counting interim revisions.
- `src-tauri/src/workspace_native.rs`: existing menu bar icon and quick-access routing. Extend with real feature-state ownership and the approved native popover presentation.
- Existing Window Manager and Ergonomics controllers own their settings and stop/resume paths; locate and reuse them during implementation. Do not duplicate their enable flags in the coach.
- `index.html` and existing UI modules: add Coach notes/progress within Audio & Dictation; use existing design tokens/daisyUI and navigation conventions.
- Local persistence: define validated bounded DTOs for preferences, session summaries and optional examples before wiring the UI. No tenancy/authentication boundary is introduced for this local desktop feature.
- Follow P-177: no synchronous main-queue hops while holding DictationRuntime. Follow existing weak-link/availability conventions for optional native frameworks. Handle mic disconnects, Bluetooth route changes, sleep/wake and app shutdown explicitly.

## Acceptance and release evidence

1. A manual session works alongside supported call apps and OfficeKit STT; the latter shares capture and produces its normal transcript. Automatic detection is released only after device/app checks establish reliable behavior.
2. Live cues remain bounded and readable; silence, noise, poor recognition and other speakers do not produce confident corrections. Filler/pace metrics use finalized original segments without double counting.
3. Pause, disable and hide have distinct observable behavior; Disable all preserves ongoing work and accurately reports partial failures. Listen In starts and ends an intentional solo session from Quick Controls, and its state stays synchronized with Speech Coach and the selected Practice context. Disabled settings survive restart without silently reopening the microphone.
4. Placement persists, stays on-screen after display changes, and avoids duplicate coach/STT panels. Full-screen and screen-share behavior is documented from real-app checks.
5. Notes derive from actual sessions; session recaps and normalized progress comparisons include units, context, sample size and baseline/insufficient-data states. Chosen focus and next-session practice goal survive navigation/restart. Dismissal, usefulness feedback, retention and clearing affect notes and aggregates correctly.
6. Focused native/unit checks cover lifecycle races, finalization, bounded buffers, segment revisions and persistence. UI checks cover control states, tooltips, keyboard access, compact widths, button limit and empty/error states. Installed-app checks cover calls, STT, device changes and global controls; mocks alone do not count as native evidence.

## Reliability update

Serialize shared microphone start/upgrade/stop transitions so simultaneous Speech Coach and STT activation cannot create more than one engine. Discard an asynchronous language suggestion if its originating capture is no longer active or its generation has changed. Pace cues may repeat after the cooldown when the same condition remains actionable.

Standalone analysis is also tied to the session that produced its audio window. Capture coach and dictation mode epochs before inference; discard results when the user pauses, disables, changes coaching context, starts a new session, or enters dictation/meeting recording before inference finishes.
7. Before language coaching release, evaluate suggestions on consented speech samples across accents and contexts with human correctness judgments. Set explicit acceptance thresholds for false corrections and useful suggestions before evaluation; abstain when evidence is insufficient. Track erroneous/dismissed cues and distraction, not just latency or cue count.

## Corrections to the approved illustrative mocks

Implementation must replace placeholder session counts/trends with real data, remove unsupported certainty claims, separate pitch from volume, and use labelled progress metrics. These are accuracy requirements accepted in the revised offering, not new visual scope. The approved references are retained here as decisions; temporary HTML mock files are removed after approval under AGENTS.md.
