# On-demand speech models

version: 1.0.1

## Requirement and decision

2026-10-27: user chose first-use loading: “load the model first time when the speech
feature is being invoked, whether the speech coach or the speech to text is invoked
by the user.” This supersedes launch loading for an enabled shortcut in CR-335.

Startup and shortcut restoration must not allocate ASR weights. A downloaded model
may be registered as a lightweight deferred engine. Microphone capture starts
immediately; its first actual speech decode loads the cached model. The same
mutex-protected engine is shared by dictation, preview, Coach, audio imports and
meetings. Later uses retain the loaded model until switching models or quitting.

## Choice

Deferred decoding reuses the existing engine mutex and bounded audio buffers.
Compared with waiting before capture, it preserves the first shortcut utterance
and key release. Compared with a separate background loader/future lifecycle, it
avoids a second synchronization protocol and model publication under the runtime
lock. Explicit Download/Prepare remains an authorized setup operation; ordinary
first use loads existing cache only and cannot silently download missing models.

No new controls, layout, copy or animation. Existing recording/processing feedback
remains applicable. No new HTTP API, storage schema or network operation.

## Safety and acceptance

- Off and enabled-shortcut launches both avoid weight allocation (P-272).
- First speech is captured before decoding begins; release stops capture normally.
- One shared engine mutex permits only one initialization, including concurrent use.
- Cached load failure is retained until explicit retry, preventing polling retry loops.
- Background first-load failures stop affected meeting/Listen In capture and publish
  existing error feedback; stale failures cannot overwrite a replacement model/retry.
- Whisper cached loading retains safe-path, file-type/size and pinned SHA-256 checks.
- Registration precedes CoachRuntime locking, matching the analyzer's lock order.
- Explicit setup reuses an already registered engine, avoiding duplicate initialization.
- No AppHandle is retained in a managed model closure; capture only model ID/path.
- Cancellation and overlay generation guards continue to gate transcript delivery.
- Native cached loaders never enter a download or vocabulary-repair network path
  (P-083/P-110 still require the complete cache).

## Verification

Pure Rust lifecycle tests exercise no eager initialization, first-use initialization,
reuse, concurrent requests, failure retention and explicit replacement. Native
readiness tests distinguish an installed deferred model from missing models.
Client tests exercise lightweight startup/shortcut restore and explicit selection.
Run full suites and native compilation; compare rebuilt desktop footprint with
speech unused and after first use before claiming measured savings.
