# Approved dictation model catalog and shell contrast

**Date:** 2026-10-13
**Approval:** The user reviewed the model catalog mock with per-model speed and accuracy fields, spoken-language and transcript-output controls, high-contrast banner dismissal and sidebar navigation, and a footer version label, then said **"ok build it"**.

## Approved behavior

- Show Speed and Accuracy beside every model in the expanded speech-model picker.
- **Update 2026-11-19 (owner: use reference scores for now, mock `stt-model-ratings` approved):** show reference Speed and Accuracy scores (0–10, ten dots plus number) for Parakeet v3/v2 (9.9/9.4), Whisper Base (8.5/7.2), Whisper Large v3 (3.0/9.5) and Large v3 Turbo (7.5/9.4). Models without a reference score (Qwen3 ASR, Whisper Small, Medium) show "—". The hint says these are reference scores, not measured on this Mac. Replace with OfficeKit's own measured results when available. **Owner rule (2026-11-19): no third-party product is named anywhere in the open-source frontend, tests or docs.**
- **Tags (2026-11-19, mock `stt-model-tags` approved):** each picker row shows tags instead of a free-text subtitle: language scope (English or Multilingual), download size, and "Translates to English" only on Whisper Medium and Large v3. No "Streaming" tag, because live preview is identical for every shipped model.
- **Two more Whisper models (2026-11-19, milestone 6a):** Whisper Tiny (78 MB, reference 9.5/6.0) and Whisper Large v3 Turbo Quantized (574 MB, reference 7.5/9.4), both multilingual, MIT-licensed whisper.cpp files pinned to the same Hugging Face commit and SHA-256 as the existing Whisper models, neither translating. They reuse the approved row layout, tags and scores exactly (a longer list, no new control, no new button), so no new mock was made; the owner can ask for one. Parakeet Ultra/Unified and Nemotron need a newer FluidAudio and SenseVoice a licence review, so they are not included yet.
- Original rule (superseded above for the five scored models): keep benchmark values empty until OfficeKit has comparable results for the selected language and device. Do not copy unverified model scores from unrelated sources.
- Expose both the spoken language and transcript output language. Current native translation support remains limited to Whisper-to-English on Whisper Medium and Large v3; unsupported target languages must not be presented as available translations.
- Make the notice dismiss control and collapsed-sidebar icons easy to see and focus.
- Show the application version in the compact footer.

## Benchmark basis

models.dev includes a general benchmark metadata field but documents its currently supported catalog type as `decision`; it does not provide comparable local ASR speed and accuracy results for OfficeKit's speech models. OfficeKit's accuracy values require reviewed reference transcripts. Speed requires measured inference on the current device and audio sample. Until then the picker displays an unavailable marker.

## Mock

`design/mocks/notice-and-rail-contrast.html` is the inspected Superset Browser mock. It was updated after review to put per-model Speed and Accuracy directly in the model picker rows.
