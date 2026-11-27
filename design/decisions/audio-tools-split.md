# Audio tools split decision

**Status:** Approved by the product owner on 2026-10-17.

OfficeKit will present Voice Transcription and Meeting Notes as two distinct
tools. Both tools use the same on-device speech model inventory, model cache,
selected-model preference, and language settings. A model is installed once and
can be used from either destination.

Voice Transcription supports live dictation and importing an audio file for an
editable transcript. Translation is offered only to English, and only for the
Whisper models that already support it. Meeting Notes supports recording or
importing audio, then presents the transcript and the existing heuristic notes
formatter for review. Audio and generated text remain on the device.

Imported recordings are decoded and inferred locally. The app must validate a
user-selected file through native file-picker authority, enforce bounded input
size and duration, and clear decoded sample buffers after processing. The UI
must distinguish unsupported or unreadable audio from model setup errors.

The current meeting-note formatter is extractive and heuristic. Do not describe
its output as a semantic or AI-generated summary. Audio model setup remains an
explicit user action. Keep existing dictation shortcuts, transcript history,
and saved meeting-note compatibility while splitting tool navigation.

The review mock showed WAV, MP3, and M4A as candidate input formats. The app
must verify decoder support before advertising each format. No arbitrary
translation target languages are part of this approval.
