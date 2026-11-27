# On-demand speech model implementation

version: 1.0.1

Implements `docs/hld/speech-model-lifecycle.md`.

1. `src-tauri/src/speech_model.rs`: deferred/loaded/failed generic holder; resolving
   under the existing engine mutex initializes once and retains either outcome.
2. `src-tauri/src/lib.rs`: register a cached deferred engine at native speech entry
   points; resolve it in the shared sample decoder after silence validation. Reconcile
   installed/ready/failed status from the holder without blocking on its mutex.
3. `src-tauri/src/dictation.rs`: permit an installed model with a registered deferred
   engine to record. Missing/unregistered/preparing models remain rejected.
4. `src-tauri/vendor/fluidaudio-rs`: cached-only Parakeet/Qwen3 FFI and Swift loaders;
   retain explicit download APIs. Whisper first use opens its cached model directly.
5. `src-tauri/src/speech_coach.rs`: register deferred ASR on explicit Coach enable;
   saved settings/background status do not initialize it.
6. `index.html`, `assets/officekit-setup.js`: remove eager preparation on startup,
   model selection and shortcut enable; restore shortcuts for installed cached models.
7. Tests: lifecycle and cached-loader native tests, installed readiness regression,
   client startup/selection/shortcut tests, full Node/Python/macOS checks.

Lock order is unchanged: runtime → engine for final decoding. Lazy initialization
must not reacquire runtime or capture an AppHandle; cached loaders return directly
to the engine owner. Preview/Coach already release runtime before locking engine.
Model switches/drop discard an unloaded holder without executing it. Errors remain
local and fixed; microphone samples retain existing clearing and duration limits.

Review refinements: `verified_cached_whisper_file` preserves pinned checksum and
safe-ancestor validation without file mutation. Coach preparation runs before the
CoachRuntime mutex. `mark_speech_model_failed` rejects stale slots and active retries;
background failures stop affected capture, clear samples, update analysis readiness
and send existing meeting-stopped/dictation-error events. Installed-model selection
reuses the existing idle Prepare action.
