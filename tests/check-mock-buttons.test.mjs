import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { BUTTON_LIMIT, checkMock, countButtons, frames } from '../scripts/check-mock-buttons.mjs';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'check-mock-buttons.mjs');
const button = (label, cls = 'btn') => `<button class="${cls}" type="button">${label}</button>`;
const frame = (body, count, extra = '') => `<div class="frame${extra}"><h1>Screen</h1>${body}${count === undefined ? '' : `<p class="count">${count}</p>`}</div>`;

test('the limit matches the AGENTS.md Button Limit', () => {
  assert.equal(BUTTON_LIMIT, 3);
});

test('a screen within the limit with a matching count passes', () => {
  const html = frame(button('Run', 'btn btn-primary') + button('Copy') + button('Download'), 'Buttons: 3/3');
  assert.deepEqual(checkMock(html), []);
});

test('a fourth button fails the limit', () => {
  const html = frame(['A', 'B', 'C', 'D'].map((label) => button(label)).join(''), 'Buttons: 4/3');
  assert.deepEqual(checkMock(html), ['frame 1 · Screen: 4 buttons, limit 3']);
});

test('links, row actions, tabs, toggles and tool-list entries are not counted', () => {
  const body = [
    button('Copy result', 'link'),
    button('Show', 'ok-text-link'),
    button('Forget', 'btn btn-sm row-act'),
    button('Remove', 'btn ok-row-action'),
    button('Text lines', 'btn ok-segment'),
    button('PDF', 'tl'),
    '<button class="btn" role="tab">Tab</button>',
    '<button class="btn" aria-pressed="true">90° right</button>',
    '<button type="button" aria-label="Remove UTC">×</button>',
    button('Run', 'btn btn-primary'),
  ].join('');
  assert.equal(countButtons(body), 1);
  assert.deepEqual(checkMock(frame(body, 'Buttons: 1/3')), []);
});

test('a btn-class link counts as a button', () => {
  assert.equal(countButtons('<a class="btn" href="#">Open</a>'), 1);
});

test('a count line that disagrees with the mock fails', () => {
  assert.deepEqual(checkMock(frame(button('A') + button('B'), 'Buttons: 1/3')), ['frame 1 · Screen: count line says 1, mock has 2']);
});

test('a count line with another limit fails', () => {
  assert.deepEqual(checkMock(frame(button('A'), 'Buttons: 1/4')), ['frame 1 · Screen: count line uses limit 4, limit is 3']);
});

test('a screen with no count line fails, and still reports an over-limit screen', () => {
  assert.deepEqual(checkMock(frame(button('A'))), ['frame 1 · Screen: no "Buttons: N/3" count line']);
  const four = ['A', 'B', 'C', 'D'].map((label) => button(label)).join('');
  assert.deepEqual(checkMock(frame(four)), ['frame 1 · Screen: no "Buttons: N/3" count line', 'frame 1 · Screen: 4 buttons, limit 3']);
});

test('a count note without a number passes only when the screen has no buttons', () => {
  assert.deepEqual(checkMock(frame('', 'Opens in place (no button)')), []);
  assert.deepEqual(checkMock(frame(button('A'), 'Opens in place')), ['frame 1 · Screen: 1 buttons but the count line gives no number']);
});

test('a Before frame marked (over) is exempt from the limit but not from the count', () => {
  const four = ['A', 'B', 'C', 'D'].map((label) => button(label)).join('');
  assert.deepEqual(checkMock(frame(four, 'Buttons: 4 (over)')), []);
  assert.deepEqual(checkMock(frame(four, 'Buttons: 5 (over)')), ['frame 1 · Screen: count line says 5, mock has 4']);
});

test('the count may sit in a caption span and frames may carry variant classes', () => {
  const html = `<div class="v2-frame"><div class="v2-cap">Desktop <span class="bc ok">Buttons: 1</span></div>${button('A')}</div>`
    + `<div class="frame compact"><div class="cap">Narrow <span class="bc">Buttons: 2</span></div>${button('A')}</div>`;
  assert.equal(frames(html).length, 2);
  assert.deepEqual(checkMock(html), ['frame 2 · Narrow: count line says 2, mock has 1']);
});

test('native dialogs and load-time clones are skipped', () => {
  const four = ['A', 'B', 'C', 'D'].map((label) => button(label)).join('');
  const html = `<div class="frame"><div class="native">${four}</div></div>`
    + '<div class="v2-frame compact" data-clone="x"><div class="v2-cap">Phone <span>Buttons: 9</span></div></div>';
  assert.deepEqual(checkMock(html), []);
});

test('a file with no screens fails', () => {
  assert.deepEqual(checkMock('<p>no frames</p>'), ['no <div class="frame"> screens found']);
});

test('the command reports each file and exits 1 on any failure', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ok-mock-buttons-'));
  const good = path.join(dir, 'good.html');
  const bad = path.join(dir, 'bad.html');
  fs.writeFileSync(good, frame(button('A'), 'Buttons: 1/3'));
  fs.writeFileSync(bad, frame(['A', 'B', 'C', 'D'].map((label) => button(label)).join(''), 'Buttons: 4/3'));
  const run = spawnSync(process.execPath, [script, good, bad], { encoding: 'utf8' });
  assert.equal(run.status, 1);
  assert.match(run.stdout, /^ok {3}.*good\.html$/m);
  assert.match(run.stdout, /^FAIL .*bad\.html\n {2}frame 1 · Screen: 4 buttons, limit 3$/m);
  const pass = spawnSync(process.execPath, [script, good], { encoding: 'utf8' });
  assert.equal(pass.status, 0);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('the command without files prints usage and exits 2', () => {
  const run = spawnSync(process.execPath, [script], { encoding: 'utf8' });
  assert.equal(run.status, 2);
  assert.match(run.stderr, /usage: node scripts\/check-mock-buttons\.mjs/);
});
