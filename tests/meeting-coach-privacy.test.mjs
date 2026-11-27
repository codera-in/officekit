import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

// The coach is for the speaker, so every surface it shows during a call must stay out of screen
// shares and recordings. These read the sources because the windows only exist in the packaged app.
// A Rust builder chain is one statement (no semicolon between the window URL and its flags), and a
// Swift panel is set up inside one block (no closing brace), so each match is pinned to its own window
// and cannot be satisfied by another window's flag later in the file.
const count = (source, pattern) => (source.match(pattern) ?? []).length;

test('the Live Workspace window is excluded from screen capture', () => {
  const source = read('src-tauri/src/coach_workspace.rs');
  assert.match(source, /WebviewUrl::App\("assets\/coach-workspace\.html"[^;]*?\.content_protected\(true\)/);
  assert.equal(count(source, /\.content_protected\(true\)/g), 1, 'one window, one flag');
});

test('the reminder companion, which carries Record and Coach me, is excluded from screen capture', () => {
  const source = read('src-tauri/src/ergonomics.rs');
  assert.match(source, /WebviewUrl::App\("assets\/ergonomics-companion\.html"[^;]*?\.content_protected\(true\)/);
  assert.equal(count(source, /\.content_protected\(true\)/g), 1, 'the companion is the only protected window here');
});

test('the coach HUD panel is excluded from screen capture', () => {
  const swift = read('src-tauri/macos-dictation.swift');
  assert.match(swift, /let panel = DictationOverlayPanel\([^}]*?panel\.sharingType = \.none/);
  assert.equal(count(swift, /sharingType = \.none/g), 1, 'one HUD panel, one flag');
});

test('the coach reads only the microphone window during a meeting, never system audio', () => {
  const swift = read('src-tauri/macos-dictation.swift');
  assert.match(swift, /if coachActive && \(!dictationActive \|\| isMeetingMode\) \{[\s\S]*?coachWindowSamples\.append/);
  const system = swift.match(/func appendExternalSamples[\s\S]*?\n    \}/)?.[0] ?? '';
  assert.ok(system.length > 0, 'system audio has its own entry point');
  assert.doesNotMatch(system, /coachWindowSamples/);
});

// The recording wires: the coach joins only after the recorder thread started, and the stop
// command ends the meeting's coaching (which saves its one note) after the capture has stopped.
test('a meeting recording joins the coach after the recorder starts and leaves it when it stops', () => {
  const source = read('src-tauri/src/lib.rs');
  const start = source.match(/fn dictation_meeting_record_start[\s\S]*?\n\}\n/)?.[0] ?? '';
  assert.match(start, /Meeting recorder thread could not be started"[\s\S]*?attach_coach_to_meeting\(&app\)/);
  const stop = source.match(/fn dictation_meeting_record_stop[\s\S]*?\n\}\n/)?.[0] ?? '';
  assert.match(stop, /officekit_dictation_stop_capture\(\)[\s\S]*?set_meeting_coach\(&coach, false\)/);
});
