# Speech model memory verification

version: 1.0.1

CR-335 · 2026-10-27 · Apple silicon, macOS 27.0.1.

## Installed baseline

Process-level profiling of installed OfficeKit 1.0.72 using `footprint` and
`vmmap -summary` measured 1544 MB native physical footprint (1888 MB peak),
130 MB backend, and 26 MB multiprocessing helper. RSS hid most of the native
charge because about 1.4 GB was compressed/swapped. This was a snapshot shortly
after launch, not an allocation-stack trace or a controlled restart experiment.

## Real cached-model experiment

Command: `npm run measure:speech-memory`. This invokes the ignored native test
`tests::cached_speech_first_use_memory_profile` with a synthetic local `say` WAV,
existing cached Whisper Medium, and `footprint --noCategories -f bytes`.
The benchmark neither records the microphone nor downloads a model.

| Phase | Physical footprint, bytes | Approximate MiB |
| --- | ---: | ---: |
| Deferred registration, before first decode | 4,342,408 | 4.1 |
| First speech decode, model loaded | 1,714,980,832 | 1635.5 |
| Second speech decode, model reused | 1,721,829,344 | 1642.0 |

The first call returned a non-empty transcript. The second reused the holder and
returned the same transcript. The test asserts that the first decode adds at least
400 MiB for this specific model, so an eager registration cannot pass unnoticed.
These numbers cover the native decode test process, excluding desktop UI/backend.
They confirm deferral of the large model allocation; they are not a post-fix total
desktop footprint. A desktop rebuild/restart comparison remains unmeasured.

## Other verification

- Pure Rust lifecycle tests exercise unused registration/drop, first resolution,
  reuse, eight simultaneous requests, retained failures and explicit replacement.
- Native registration tests use a sparse cached-file fixture without loading it;
  missing models do not trigger downloads. Installed deferred engines can capture
  immediately; missing/unregistered models and denied microphone access cannot.
- Client tests cover startup, model selection, installed-shortcut restoration and
  Settings/shortcut enable without eager preparation.
- Cached Parakeet/Qwen3 bridge argument, missing-directory and corrupt-vocabulary
  tests pass, including the Swift cached subset with network denied. Successful
  Parakeet/Qwen3 inference is unverified here because those weights are absent.
- Explicit setup shares an existing deferred holder instead of loading a second
  model beside preview/Coach. Cached failures persist until explicit retry.
- Full `npm test` passed: JavaScript 1105 passed / 1 skipped; Python 3606 passed /
  4 skipped (2477 subtests); native macOS hotkey and focus suites passed. The
  separate Rust library suite passed 433 tests with 1 ignored.
- Mutation checks observed failures when installed-model readiness was rejected,
  cache completeness or pinned integrity checks were removed, or first-load
  failure reporting was bypassed. The deferred lifecycle lines have 100% test
  coverage; this is a targeted module measurement, not whole-repository coverage.
- Final PM, QA, UX and correctness delta reviews could not complete because the
  review agents hit their usage limits. The earlier review catches were fixed
  and covered by regressions, but this change has no final reviewer sign-off.

No UI layout, controls or copy changed. Existing recording/processing feedback is
used during the first decode. The model stays resident for subsequent use until
switching models, removal where permitted, or app exit.
