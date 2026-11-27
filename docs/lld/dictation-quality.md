# Dictation quality pipeline — low-level design

Version: 1.1.0 · 2026-10-20 · Implements `docs/hld/dictation-quality.md` 1.1.0. 1.1.0 replaces the planned design with what was built (pause-aligned R2, Swift bridges, Rust-side guards).

## Principles

- Every enhancement fails open to today’s behavior.
- `mode: "rules"` (default) keeps the original behaviour, with one deliberate fix: punctuation spacing no longer splits `4:15`, `3.5` or `1,000`. R7 filler and self-correction rules apply only under `mode: "smart"` and only to English.
- Pure logic lives in `src-tauri/src/dictation_quality.rs` with unit tests; `lib.rs` only wires it. No transcript, audio, prompt or field text in any log or error string; `FocusContext` redacts field text in `Debug`, and `CommitState` is deliberately not `Debug`.
- Locks: runtime → engine, and `commit_state` and `focus_context` are leaf locks never held while taking another lock. The Accessibility read runs on a short background thread, never under the runtime lock, because it hops to the main queue.

## File map (as built)

| Path | Change | Ref |
| --- | --- | --- |
| `src-tauri/src/dictation_quality.rs` (new) | `trim_silence`, `find_commit_boundary`, `CommitState`, `join_committed`, `build_initial_prompt`, `validate_vocabulary_terms`, `ContextOptions`, `FocusContext`, `parse_focus_context`, `cleanup_request_body`, `accept_llm_output` | R1 R2 R3 R4 R5 |
| `src-tauri/src/lib.rs` | trim before decode; `initial_prompt`; runtime fields `vocabulary_terms`, `context_options`, `focus_context` (leaf lock), `streaming_commit`, `llm_polish`, `commit_state`; `commit_ready_segment`; `polish_with_system_model`; commands `dictation_set_vocabulary`, `dictation_set_context_options`, `dictation_set_streaming_commit`, `dictation_set_llm_polish`, `dictation_polish_available`; `dictation_cleanup_and_paste` takes `mode` and `language` | R1–R5 |
| `src-tauri/macos-dictation-context.swift` (new) | AX reader, `officekit_dictation_focus_context`; secure fields never read | R5 |
| `src-tauri/macos-dictation-polish.swift` (new) | `officekit_dictation_polish_available`, `officekit_dictation_polish` using Apple Foundation Models behind `canImport` and `#available(macOS 26)` | R4 |
| `src-tauri/build.rs` | compile the two new Swift files with `-wmo`; when the SDK has `FoundationModels.framework`, suppress autolink and link it weakly | R4 |
| `officekit/engines/engine_dictation_cleanup.py` | `mode`, `language`, `context`, `smart_rules` (fillers, repeated function words, marked number corrections, “scratch that” only at a clause boundary), `_looks_english`, `_space_punctuation` | R7 |
| `app.py` | request fields `mode`, `language`, `context`; response `engine`, `fallback_reason` | contract |
| `API-CONTRACT.md` | cleanup row; five Tauri command rows; versions logged in `docs/VERSION-HISTORY.md` | contract |
| `index.html` | Smart dictation card (four switches), preference store, vocabulary sync, edit-learned suggestions panel (`createOfficeKitDictationSuggestions`, inline), cleanup call passes `mode` and `language` | R3 R6 |
| `tests/` | Rust `dictation_quality::tests`; Python cleanup unit and API tests; `tests/dictation-ui.test.mjs`; `tests/macos-dictation-focus-context-tests.swift`; Playwright `ui-tests/dictation-smart-settings.spec.mjs`, `ui-tests/dictation-suggestions.spec.mjs` | all |

Not built (and not needed): `CleanupProvider` seam, `engine_dictation_llm.py`, model download commands, a `dictation-transcript` `context` or `committed_ms` field, a separate `assets/dictation-suggestions.mjs`. See HLD 1.1.0 for why the runtime is the OS model instead.

## Interfaces

```rust
pub struct TrimResult { pub range: Range<usize>, pub had_speech: bool }
pub fn trim_silence(samples: &[f32]) -> TrimResult;
pub fn find_commit_boundary(pending: &[f32]) -> Option<usize>;   // 700 ms pause, >= 1 s speech, >= 3 s pending, cut mid-silence
pub struct CommitState { /* generation, committed_end, texts */ }
pub fn accept_llm_output(input: &str, output: &str) -> Result<String, &'static str>;
// length 0.4..=1.25 of input; no changed digit run; every word equals an input word or shares a 4-letter prefix with one
```

Cleanup request body: `{transcript, dictionary}` in rules mode; smart mode adds `mode`, `language` and `context` with only `app_name`, `bundle_id` and `field_role`. Optional field text is never sent to the sidecar; it stays in the native runtime and is read only when both “Use text around the cursor” and on-device cleanup are on. Response: `cleaned_text`, `engine` (`rules` | `smart_rules`, echoing the mode requested), and `fallback_reason`, which is reserved: the model field exists but nothing sets it today. Whether the on-device rewrite ran is not reported to the page; the guards’ rejection reasons stay in Rust.

On-device rewrite: runs in smart mode only, off by default, on the rules result, with a 4 s timeout, before paste when enabled; any failure or guard rejection keeps the rules text.

## Commits (as shipped)

R1 trimming → R3 vocabulary prompt → R5 focus context → R7 and contract → UI card → R6 suggestions → R2 pause-aligned commit → R4 guards and spike record → R4 on-device polish → docs. Review-round fixes follow.

## Error handling

Each stage returns “no change” on internal error: trim failure → untrimmed samples; prompt failure → no prompt; context failure → no context; background decode failure → one full decode; polish timeout, unavailability or guard rejection → rules text. User-visible failures stay limited to today’s states.

## Test hooks

Rust `dictation_quality::tests`; Python `tests/test_dictation_cleanup_unittest.py` and `tests/test_dictation_cleanup_api.py`; Node `tests/dictation-ui.test.mjs`; Swift `tests/macos-dictation-focus-context-tests.swift` run by `scripts/run-macos-dictation-hotkey-tests.mjs`; Playwright specs above. Not covered by automation (needs a microphone and a real focused app): the stop-path join with background commits, the polish path inside `dictation_cleanup_and_paste`, and clearing of captured text on cancel; these are listed for manual verification in `docs/TESTING.md`.
