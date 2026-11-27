# Speech Coach sentence clarity

version: 1.0.0

The Live Workspace uses a dedicated Apple Intelligence review to offer clearer, simpler sentences. It removes empty qualifiers and repairs tangled structure while preserving intent, examples, uncertainty, names and numbers. Brief HUD suggestions retain their conservative grammar/vocabulary behavior. No text leaves the Mac.

The four-sentence challenge-app brainstorm is preserved verbatim in `tests/fixtures/speech-coach/clarity.json`. Its suggested rewrites express the desired quality; the model need not reproduce their exact wording. Rust tests pass model-shaped responses through validation, the real sentence cursor, workspace marking and corrected Copy text. They also reject changed numbers, invented source quotes, malformed responses and replacements over 2,000 UTF-8 bytes. Unavailable, invalid and NONE responses fall back to Harper, without overlapping rewrite/grammar cards.

Run deterministic checks with `TAURI_CONFIG='{"bundle":{"resources":[]}}' cargo test --manifest-path src-tauri/Cargo.toml --lib`. This test-only override avoids requiring packaged media resources in a fresh source checkout; it does not change release configuration.

Run `npm run test:coach-model` for an explicit real-model acceptance check. It compiles the shipping Swift bridge and asks the installed Apple model to improve all four original sentences. It checks grounded quotes, useful changes, removal of the broken contest clause and repeated qualifiers, and no rewrites for two already-clear sentences. Unavailable Apple Intelligence is reported as SKIP, never as a successful model acceptance. The initial test failed before the dedicated workspace mode existed. After the fix, all four sentences received rewrites and the clear sentences returned NONE.

Sentence coaching requires available Apple Intelligence on supported macOS. Harper remains the basic grammar fallback. This check does not prove microphone transcription, installed application behavior or equality with a larger cloud model. The installed app must be rebuilt to pick up the native bridge change.

Verification on 2026-10-27: full `npm test` gate passed (1,094 Node checks passed, one skipped; 3,605 Python tests passed, five skipped; 2,477 subtests passed; native shortcut/global checks passed). All 418 Rust library tests passed. LLVM coverage found no uncovered code regions in the workspace-selection helper or the shared sentence validator and its workspace wrapper. The explicit real-model check passed all four brainstorm rewrites and both clear-sentence contrasts. Rust formatting and `git diff --check` passed. No UI layout or controls changed.
