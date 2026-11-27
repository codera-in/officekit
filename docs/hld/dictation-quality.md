# Dictation quality pipeline

Version: 1.2.0 · 2026-10-20 · Mock approved by the owner (“approved”, `design/mocks/dictation-quality-upgrade.html`, since removed from the tree per AGENTS.md; this document is the durable record); HLD agreed by the owner (“agree, do it through new worktree”). 1.2.0 describes the system as built: pause-aligned R2, the OS on-device model instead of a downloaded LLM, and field text kept out of the sidecar.

## Problem and scope

Dictation is accurate but raw: filler words and false starts stay in the text, silence can produce hallucinated phrases, the final pass re-decodes the whole utterance, Whisper receives no vocabulary hint, the dictionary only substitutes what the user typed by hand, and no application context is used. Paid tools close this gap with stages around the ASR model, not a custom model.

In scope (all local, one branch, independently verified commits): R1 silence trimming, R2 streaming commit, R3 Whisper `initial_prompt`, R4 opt-in local LLM cleanup with deterministic fallback, R5a/R5b Accessibility app and optional field-text context, R6 dictionary suggestions from edits, R7 deterministic filler and self-correction rules.

Out of scope: cloud ASR or LLM, retraining ASR models, non-macOS changes, changing hotkey, permission or paste delivery behavior.

## Current integration points

- `src-tauri/src/lib.rs`: `transcribe_samples_buffer` (Whisper params, no prompt or VAD), `run_dictation_preview` (200 ms poll, 1.5 s windows), `run_dictation_hotkey_monitor`, `cleanup_dictation_text` (loopback HTTP, 5 s timeout), Tauri commands and events.
- `src-tauri/src/dictation.rs`: model catalog, preview windows, Qwen3 chunking, hashes.
- `src-tauri/macos-dictation.swift`: capture, hotkey, paste, focused-element role check.
- `officekit/engines/engine_dictation_cleanup.py`, `app.py`: `POST /api/dictate/cleanup`.
- `index.html`: dictation settings, dictionary (`localStorage`), history, transcript editor.
- Tests: `tests/dictation-ui.test.mjs`, `tests/test_dictation_cleanup_*`, Rust `dictation::tests`, Swift tests under `tests/macos-dictation-*`.

## Proposed architecture

```
mic → capture (Swift) → samples
        │
        ├─ R1 trim (Rust)  ──► speech-only samples
        │
        ├─ R2 (Rust): while speaking, audio that ends in a pause is decoded and committed;
        │       key release decodes only the remaining tail and joins (full decode on any failure)
        │       engine call carries R3 prompt (Whisper only)
        │
        ▼
   raw transcript ──► R5 context (Swift AX: app name, bundle id, role) joins the request
        │                (field text stays in the native runtime)
        ▼
   cleanup (sidecar route): rules, plus smart rules (R7) in smart mode
        │
        ▼
   optional R4 rewrite (native, OS model, off by default, hidden): guards → else keep rules text
        ▼
   paste (unchanged delivery) ─► history; edits in the transcript editor ─► R6 suggestions (frontend)
```

Decisions:

1. **R1 VAD in Rust before decode, for every engine.** A dependency-free energy gate (20 ms frames, noise-floor percentile, peak-fraction cap, absolute-level rule for clips with no dynamic range), chosen over the Silero-based `whisper-rs` VAD because that needs an extra model file and helps only Whisper. Trimming is conservative (keep padding at both ends) and empty speech returns the existing no-speech error. Hash-pinned artifacts follow the existing model-download rules.
2. **R2 commit logic is pure and engine-agnostic** (`dictation_quality.rs`): audio is committed at a pause (at least 700 ms of silence after at least 1 s of speech, with at least 3 s pending), cutting mid-silence, so no word is split and no prefix-stability guess is needed. The committed segment is decoded in the background; the final pass decodes only the remaining tail and joins. A separate leaf-lock commit state avoids a deadlock with the stop path. A full re-decode remains the fallback when a background decode fails, so correctness never depends on the optimization.
3. **R3 prompt** is built from dictionary replacement targets, then the app name, bounded to a token budget, deduplicated, and passed with `set_initial_prompt`. Parakeet and Qwen3 ignore it explicitly; the UI does not claim biasing for them.
4. **R5 context in Swift** adds one `@_cdecl` getter returning app name, bundle id and field role, and optional bounded field text. Secure text fields and the denylist roles are never read. The read runs on a short background thread (it hops to the main queue and must not run under the runtime lock) into a leaf-lock cell, is consumed by one cleanup, and is cleared on every cancel and error path. Field text is read only when both “Use text around the cursor” and the on-device rewrite are on, is length-capped, held in memory for one dictation, never logged, never sent to the sidecar and never sent to the page.
5. **R4 runtime is the OS on-device model.** Apple Foundation Models through a weak-linked Swift bridge (`macos-dictation-polish.swift`), chosen after a spike over a downloaded llama.cpp server (needs an explicit weights download and licence review) and an in-process crate (P-158 link risk, `ggml` clash with `whisper-rs`). There is no provider seam, no model download and no model lifecycle commands in this release. `build.rs` probes the SDK and only links the framework when it exists, so older toolchains still build and macOS 14 and 15 still launch.
   **Spike result (2026-10-20, Apple silicon, macOS 27):** option (b) builds with plain `swiftc` (no download, no ggml clash) and `SystemLanguageModel.default` reports available. Warm latency 1.5–3.0 s per short phrase (first call about 4 s even with `prewarm()`), so enabling it adds that delay before paste (hard-capped at 4 s, then the rules text is pasted). That is why it is a separate opt-in that is off by default and labelled slower; it is not part of the default path. Quality is mixed: it applied "john, I mean maria" correctly and dropped fillers, but turned "three no four" into "three on four", a meaning error that a word-stem guard cannot see (every output word exists in the input). Consequence: LLM output is only accepted when guards pass, and `rules` stays the default engine until a quality eval set justifies more. Options (a) and (c) are not started: (a) needs an explicit weights download and licence review, (c) carries the P-158 link risk.
6. **R4 guards** are deterministic and run in Rust on every model output (`accept_llm_output`): reject when the length ratio leaves 0.4–1.25 of the input, when a digit sequence appears that the input lacks, or when a word neither equals an input word nor shares a four-letter prefix with one; a timeout of 4 s also keeps the rules text. Guards cannot see a meaning change that reuses input words (the spike turned “three no four” into “three on four”), which is why the rewrite only ever sees the rules result, is off by default and has no UI yet. Prompt injection: the dictated text is passed as the user message, the instructions are fixed, and added content is rejected by the guards; omitted words are not detected.
7. **R7 rules** extend `engine_dictation_cleanup.py` with a conservative filler list, repeated function words, marked number corrections (“no”, “I mean”, “sorry”) and “scratch that” / “strike that” only at a clause boundary or when it ends the clause or starts a new thought, all English only (explicit language, else a text heuristic). Anything ambiguous is left untouched.
8. **R6 suggestions** are computed in the frontend (`createOfficeKitDictationSuggestions` in `index.html`) by word-level diff between the pasted transcript and the edited transcript. Only substitutions of one to three words with a similarity ratio of at most 0.5 become suggestions; a changed spelling with a capital or digit is immediate, other spelling fixes need two sightings, and capital-only fixes need a word of five or more letters and three sightings. Bounded counts, dismissal remembered, never auto-added.

## Contract surface

Backward compatible extension of `POST /api/dictate/cleanup`:

- Request adds optional `context` (`app_name`, `bundle_id`, `field_role`; no `field_text`: the sidecar has no use for it) , optional `language` (short alphabetic tag) and optional `mode` (`rules` | `smart`, default `rules`). Existing bounds and extra-field rejection stay; new fields have their own length caps and control-character rejection.
- Response adds `engine` (`rules` | `smart_rules`, echoing the requested mode) and `fallback_reason` (reserved: the field exists in the model but is always null today); `cleaned_text` unchanged. The on-device rewrite lives in the native layer and is not reported through this route.

New Tauri commands: `dictation_set_vocabulary`, `dictation_set_context_options`, `dictation_set_streaming_commit`, `dictation_set_llm_polish` and `dictation_polish_available`; `dictation_cleanup_and_paste` gains `mode` and `language`. No `dictation-transcript` event fields were added.

`API-CONTRACT.md` and its version row update in the same commit as the route change. No new network endpoint is added; nothing is downloaded by this release.

## Data model

No database tables. This is a single-user local desktop app: there is no tenant, so the multi-tenant rules do not apply, and no stored entity is added. New client preferences use `localStorage` keys beside the existing `officekit.dictation.*` keys: smart cleanup, app context, field text (default off), faster results, and dismissed suggestions (bounded). The LLM weights live in the OfficeKit-owned model cache with the existing validation. Field text and audio are never persisted.

## Flows

1. Key down: capture starts, context (app, role) is read once on a background thread, the Whisper prompt is prepared.
2. While speaking: finished phrases that end in a pause are decoded and committed in the background.
3. Key up: trim, decode the uncommitted tail, join, send the transcript plus app context to cleanup.
4. Cleanup: rules always, smart rules in smart mode; the optional on-device rewrite (off, hidden) may replace the text if the guards pass, else the rules text is pasted.
5. Paste through the existing delivery states; history stores the pasted text as today.
6. The user edits in the transcript editor; closing or saving the edit computes suggestions; the user adds or dismisses.

## Privacy, errors and pitfalls

- No audio, transcript, field text or prompt is logged, on any layer. Tests assert error and log strings contain none of it.
- Secure fields are never read; a role or attribute failure means no context, not an error.
- Every enhancement fails open to today’s behavior: VAD failure uses untrimmed audio, commit-join failure re-decodes, LLM failure uses rules, context failure omits context.
- There is no model process and no model download in this release; the OS model runs in-process through the Swift bridge, and the sidecar stays loopback-only with its per-launch token.
- P-158: the spike links through the full Tauri build before any code depends on it. P-078: no remote recognition or cloud fallback. P-081/P-082: trimming and tail decode read the final audio callback’s samples only after capture has stopped; paste delivery code is not changed. Hotkey, permission and paste states are untouched.
- Prompt injection: see decision 6; the transcript is data, the instructions are fixed and the guards reject added content.

## Alternatives rejected

Cloud cleanup or ASR (violates local-first and P-078). Rules only (cannot handle messy phrasing). An in-process second ggml runtime as the default (link and symbol-clash risk, P-158). Auto-adding suggested dictionary terms (silent vocabulary drift).

## Verification

Per-requirement unit tests (see requirements acceptance), a recorded-clip corpus for VAD and commit equality, Rust and Python suites through `npm test`, Swift tests for context role handling, UI tests for the new card and suggestions panel, then installed-Mac acceptance for permission, hotkey, paste and latency, which remains manual and is reported as such.
