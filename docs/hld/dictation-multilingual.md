# Multilingual dictation, translation, and insights

Version: 1.0.2 · 2026-10-13 · UI direction approved; microphone discovery and model lifecycle feedback implemented in source, installed/runtime verification pending.

## Problem and scope

Current dictation uses FluidAudio Parakeet v2/v3 and Qwen3 ASR, with a new whisper.cpp runtime implemented in source. Whisper supports on-device multilingual transcription and an English translation task for selected model variants. Installed microphone/model inference, Tamil quality, latency, memory, and offline behavior remain unverified. The meeting-note formatter is deterministic English-oriented extraction.

In scope: provide a local multilingual speech runtime with a bounded model catalog; persist model/language preferences; expose the currently supported English translation task; distinguish transcript, translation, and deterministic notes/insights; expose copy/download for each full result. Preserve native capture, push-to-talk, meeting capture, source transcript, and local-only guarantees. Arbitrary target-language translation remains future work.

Device setup separates macOS microphone permission from current audio-input discovery so a permitted-but-missing device cannot look ready. Model lifecycle status is polled from the native runtime and includes the progress fields the library exposes: Whisper byte totals; FluidAudio fraction and file totals. Inventory and allowlisted removal commands manage model-specific caches only; deletion is refused while recording/capturing, the shortcut is active, or model setup is underway. Transcript storage does not depend on model cache retention.

Out of scope: cloud inference, replacing existing Parakeet/Qwen models, automatic transcript mutation, and claims of semantic insight quality without a local language model.

## Current integration points

- `src-tauri/src/dictation.rs`: model IDs, cache locations, artifact validation and status.
- `src-tauri/src/lib.rs`: native model lifecycle, capture-to-inference paths and Tauri commands.
- `src-tauri/vendor/fluidaudio-rs`: vendored Swift package/build bridge for current ASR.
- `src-tauri/macos-dictation.swift`: microphone capture, permissions, and paste delivery.
- `index.html`: model setup, transcript, meeting notes, result actions and preferences.
- `officekit/engines/engine_dictate.py`, `app.py`: local deterministic meeting-note formatter and API contract.
- Existing tests: `tests/dictation-ui.test.mjs`, `tests/test_module2_dictate.py`, Rust dictation tests and opt-in native runtime checks.

## Proposed architecture

The pinned `whisper-rs`/whisper.cpp runtime is implemented in native Rust (rather than the Python sidecar), keeping ASR in the local capture/model lifecycle and avoiding SwiftUI linker requirements or a second Python/MLX runtime. It enables Metal on Apple Silicon, defines a bounded Whisper catalog, pins model artifacts with SHA-256 validation, downloads into an OfficeKit-owned cache, and preserves explicit model/setup state. Source implementation is not proof of installed inference: model download, checksum, Tamil audio accuracy, latency, memory and offline behavior still require runtime verification.

The current implementation exposes Whisper's English translation mode only for Medium and Large v3; it preserves source and translation as separate editable/copyable/downloadable results, including meeting chunks. It does not yet provide arbitrary target-language selection or OS translation. Insights remain a clearly labeled deterministic notes result until a separate local language model is selected and validated.

## Flows

1. User selects a model; UI displays verified language coverage, estimated download/storage size, compatibility, and setup state.
2. Setup downloads to an OfficeKit-owned cache, validates expected artifacts, then initializes the engine. Verify download interruption, checksum rejection, cache reuse and fallback on a clean installed build.
3. User selects a spoken-language hint or Auto. Pass the hint only when supported; otherwise disable it with an explanation.
4. Capture transcribes locally. Deliver the full source transcript to the editor and history using the existing recoverable paste flow.
5. Translate to English creates a separate, editable result with Whisper Medium or Large v3. Other target languages are not offered until a local provider and its language pairs are verified. Failure keeps the source text.
6. Insights run separately and are named “Meeting notes” unless a semantic engine is actually used. Copy and download always act on the complete visible result.

## Privacy, errors, and pitfalls

- P-078: never describe an unverified engine as local; never fall back to browser or remote speech recognition. The new Whisper runtime still needs installed microphone/model verification.
- Preserve native dictation's complete transcript and recoverable copy path; keep errors visible in context.
- Do not infer translation availability from transcription language coverage; current Whisper translation is English-only and model-specific.
- Network access is limited to explicit model downloads. Inference and translation content remain on-device.
- Model downloads are size-bounded and checksum-verified before publication; reject symlinks and partial artifacts.
- Do not label regex/keyword extraction as AI-generated insights.

## API and data changes

No persistent database or Python API schema is required for native ASR. Store only model and language preferences locally; transcript content follows existing in-memory/history behavior. Arbitrary OS translation and any future semantic insight engine need their own explicit capability and data contract.

## Verification gates

- Unit tests for model IDs, metadata, path safety, cache validation, size bounds and language mapping.
- Native runtime tests with a short Tamil sample and representative existing-language audio, measuring transcription accuracy/latency and English translation output.
- UI tests for available/unsupported pair states, model setup errors, retained source transcript, complete copy/download, and result invalidation after edits.
- Packaged macOS verification on supported OS versions, including offline inference after model download. Never report release-ready without installed microphone/paste checks.
