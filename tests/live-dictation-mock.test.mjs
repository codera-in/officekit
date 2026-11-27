import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const mock = fs.readFileSync(path.join(root, 'design/mocks/live-dictation-workbench.html'), 'utf8');

test('Live Dictation mock presents permission, offline, recording and review states', () => {
  for (const state of ['Ready', 'Microphone permission', 'Offline recognition unavailable', 'Recording', 'Transcript ready']) {
    assert.match(mock, new RegExp(state.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(mock, /Audio stays on this Mac/);
  assert.match(mock, /never falls back to network recognition/);
  assert.match(mock, /No audio will be sent/);
  assert.match(mock, /Paste a transcript below/);
  assert.match(mock, /Generate meeting notes/);
  assert.match(mock, /Clear transcript and notes/);
});

test('Live Dictation mock uses local design tokens, accessible controls, themes and responsive states', () => {
  assert.match(mock, /stylesheet" href="\.\.\/officekit-tokens\.css"/);
  assert.match(mock, /aria-label="OfficeKit navigation"/);
  assert.match(mock, /aria-current="page"/);
  assert.match(mock, /aria-live="polite"/);
  assert.match(mock, /aria-label="Color theme"/);
  assert.match(mock, /prefers-reduced-motion:reduce/);
  assert.match(mock, /@media\(max-width:760px\)/);
  assert.doesNotMatch(mock, /https?:\/\//);
});

test('Live Dictation mock cannot capture audio, send requests or persist transcript data', () => {
  assert.doesNotMatch(mock, /\b(fetch|XMLHttpRequest|WebSocket|MediaRecorder|getUserMedia|SpeechRecognition)\b/);
  assert.doesNotMatch(mock, /\b(localStorage|sessionStorage|indexedDB|document\.cookie)\b/);
});
