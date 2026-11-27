import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const rust = readFileSync(new URL('../src-tauri/src/global_clipboard.rs', import.meta.url), 'utf8');
const lib = readFileSync(new URL('../src-tauri/src/lib.rs', import.meta.url), 'utf8');
const logic = readFileSync(new URL('../src-tauri/macos-global-logic.swift', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../src-tauri/macos-global.swift', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('the main window hands transcripts to the panel in memory only', () => {
  assert.match(html, /function syncDictationPanel\(\)/);
  assert.match(html, /invoke\('global_panel_set_dictations', \{ items \}\)/);
  assert.match(html, /function renderDictationHistory\(\) \{\s*syncDictationPanel\(\);/);
  assert.equal((lib.match(/global_clipboard::global_panel_set_dictations,/g) || []).length, 2);
  assert.match(rust, /static PANEL_DICTATIONS: std::sync::Mutex<Vec<PanelDictation>>/);
  // Transcripts never reach the clipboard database through the sidecar.
  assert.doesNotMatch(rust, /"\/api\/clipboard\/clips"[^;]*dictation/i);
});

test('the clipboard panel adds a read-only Dictation chip and pastes rows verbatim', () => {
  assert.match(rust, /add_dictations\(&mut panel, &mut entries, &held_dictations\(\), now_seconds\(\)\)/);
  assert.match(rust, /\{"id": "dictation", "label": "Dictation"\}/);
  assert.match(rust, /PanelEntry::Dictation \{ text \}, 0 \| 1\) => \{\s*self\.report_paste\(native::paste\(0, text\.as_bytes\(\), target\)\)/);
  // Pin and delete only act on clips, so a transcript row cannot be changed from the panel.
  assert.match(rust, /\(PanelEntry::Clip \{ \.\. \}, 2\)/);
  assert.match(rust, /\(PanelEntry::Clip \{ \.\. \}, 3\)/);
});

test('the native panel hides pin and delete on the Dictation tab and keeps transcripts off All', () => {
  assert.match(logic, /var readOnlyChips: \[String\] = \[\]/);
  assert.match(logic, /case "all": chipMatches = item\.kind != "dictation"/);
  assert.match(panel, /case "pin": if !readOnlySelected/);
  assert.match(panel, /case "delete": if !readOnlySelected/);
  assert.match(panel, /"Search dictation"/);
  assert.match(panel, /"↵ paste {3}⌘1–9 paste row {3}⇥ filter {3}esc close"/);
});
