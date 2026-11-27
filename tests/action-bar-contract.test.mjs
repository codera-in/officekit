import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const dock = read('assets/officekit-tool-actions.js');
const css = read('assets/officekit.input.css');
const outcome = read('assets/officekit-outcome.js');

test('the bottom bar has a fixed 64px height and no tool title', () => {
  assert.match(dock, /BAR_HEIGHT = 64/);
  assert.match(css, /#officekit-tool-actions\s*\{[^}]*height: 64px;[^}]*max-height: 64px/);
  assert.match(css, /#officekit-tool-action-summary\s*\{\s*display: none/);
  assert.match(dock, /summary\.textContent = ''/);
});

test('every docked button gets the same 168px by 40px slot', () => {
  assert.match(css, /ok-tool-action-source[^{]*\{[^}]*width: 168px;[^}]*height: 40px/);
});

test('success is a toast and errors are a popup, never drawn in the bar', () => {
  assert.match(outcome, /state === 'success'\) toast\(/);
  assert.match(outcome, /state === 'error'\) popup\(/);
  assert.match(css, /\[data-state="success"\],\s*\.ok-app \[data-officekit-message\]\[data-state="error"\][^{]*\{[^}]*display: none !important/);
  assert.match(css, /\.ok-toast\s*\{[^}]*bottom: 80px/);
  assert.match(outcome, /TOAST_MS = 4000/);
  assert.match(outcome, /Report issue/);
});

test('Storage report actions are inline header actions, not bar buttons', () => {
  assert.match(read('assets/officekit-storage.js'), /toolId:'storage_analyzer',inline:true/);
  assert.match(dock, /officekit-result-actions--inline/);
});
