# Multilingual dictation, translation, and insights: implementation plan

Version: 1.0.2 · 2026-10-13 · Source implementation recorded; installed runtime verification pending.

| Area | Change | Verification |
| --- | --- | --- |
| Native ASR dependency | Pinned `whisper-rs` with Metal is in `src-tauri/Cargo.toml`; current FluidAudio engines remain intact. CMake is required for native builds. | Focused Cargo checks/tests pass; packaged macOS build and clean-machine CMake validation remain pending. |
| Model metadata/lifecycle | `src-tauri/src/dictation.rs` defines Whisper IDs, language coverage, pinned artifact size/hash, cache path, required file and readiness checks. Native download validates size/hash before use. | Rust tests cover IDs, metadata, hash/size validation, path handling and cache readiness; live download interruption and recovery still need a clean-cache run. |
| Progress, inventory, and removal | Whisper streams bounded chunks into a temporary file and reports exact bytes, then verification and loading phases. FluidAudio forwards its public `DownloadUtils.ProgressHandler` fraction and file counts through a C callback. Inventory reports each allowlisted model cache and disk size; deletion verifies the model path and refuses while recording, capture, shortcut, or setup is active. | Rust unit suite and UI tests; validate clean-cache downloads, interruption/termination cleanup, exact removed bytes, and live FluidAudio progress on a packaged Mac. FluidAudio byte totals are not exposed by its public callback. |
| Microphone recovery | Swift reports physical audio-input availability separately from AV permission; Tauri returns both fields. The card provides an assertive no-device message and a recheck action. | Unit-test granted-without-input as a distinct state; verify reconnect and permission-denied paths on macOS hardware. |
| Appearance | Root preference resolves System/Light/Dark before paint; explicit choices persist and System follows OS changes. Semantic dark utility overrides cover shared tool surfaces, forms, dialogs, and selection states. | Browser tests exercise all registered tool destinations plus System/Light/Dark persistence at desktop and compact viewports; inspect visual contrast and image/export surfaces manually. |
| Inference | `src-tauri/src/lib.rs` uses a `DictationEngine` enum to retain FluidAudio engines and invoke Whisper through `WhisperContext`; optional language and transcription/English-translation task are wired. | Opt-in `src-tauri/tests/whisper_runtime.rs` needs real Tamil/English fixtures and must measure recognition quality, latency and memory. |
| Tauri commands | Model status/select/prepare APIs plus translation and spoken-language commands are implemented in `src-tauri/src/lib.rs`; capture/output guards remain. | Rust command tests and installed capture/model lifecycle verification. |
| Language preferences | `index.html` has model-aware spoken-language hints and local preference persistence; Auto remains available. | DOM/UI tests cover model-specific choices and unavailable models; installed persistence check remains. |
| Translation | Whisper English translation is exposed for Medium and Large v3, remains separate from source, and appears for push-to-talk and meeting chunks. Other target languages are not supported yet. | UI checks cover source retention and complete result actions; real translated Tamil/English fixtures and quality review remain open. |
| Results and insights | Transcript and English translation are separate editable panels with Copy/Download. Existing deterministic meeting notes remain labeled as notes, not AI insights. | UI checks for full content, clipboard rejection, correct file extension, edit invalidation and save behavior. |
| Durable guidance | Decisions are in `review/dictation-voicebox-reference/requirements.md`, HLD/LLD, `docs/TESTING.md`, and `docs/PITFALLS.md`. | Version-history rows match versioned document edits. |

## Implementation order

1. Complete focused Node/Rust checks and inspect runtime-test compilation.
2. Run opted-in inference with real Tamil/English fixtures; record quality, speed and memory.
3. Verify model download, checksum rejection, cache reuse and offline inference on the installed app.
4. Test microphone, meeting audio, translation output, copy/download and focused-app paste-back on the rebuilt app.
5. Add a separate local translation provider only when arbitrary target-language support can be verified and clearly exposed.

## Known acceptance limit

Whisper model selection and English translation are implemented in source. They are not release-verified until real local model inference and installed capture/paste checks pass. Tamil is a supported Whisper language claim, not an accuracy guarantee. Arbitrary translation destinations and semantic AI insights are not implemented.
