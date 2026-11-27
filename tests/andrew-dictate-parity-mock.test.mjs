import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const mock = fs.readFileSync('design/mocks/andrew-dictate-core-parity.html', 'utf8');

test('Andrew-Dictate core parity mock keeps current and proposed workflows distinct', () => {
  assert.match(mock, /Current OfficeKit/);
  assert.match(mock, /Hold Fn to dictate anywhere/);
  assert.match(mock, /focused field/);
  assert.match(mock, /Parakeet English model is installed/);
});

test('Andrew-Dictate parity mock exposes permissions, local cleanup and model setup', () => {
  for (const text of ['Microphone permission', 'Accessibility permission', 'Download model', 'Personal dictionary', 'No audio upload']) {
    assert.ok(mock.includes(text), `expected mock to include ${text}`);
  }
  assert.doesNotMatch(mock, /\b(fetch|XMLHttpRequest|WebSocket|MediaRecorder|getUserMedia|SpeechRecognition)\b/);
});

test('Andrew-Dictate parity mock is responsive and keyboard-visible without decorative motion', () => {
  assert.match(mock, /@media\(max-width:760px\)/);
  assert.match(mock, /:focus-visible/);
  assert.doesNotMatch(mock, /@keyframes|animation:/);
});
