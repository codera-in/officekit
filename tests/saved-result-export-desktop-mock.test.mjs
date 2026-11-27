import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const mock = fs.readFileSync(new URL('../design/mocks/saved-result-export-desktop.html', import.meta.url), 'utf8');

test('saved-result desktop mock compares current output with result, export and saved-detail states', () => {
  for (const phrase of [
    'Current · calculation result',
    'Proposed · one saved snapshot across three states',
    '1 · Result', '2 · Export preview', '3 · Reopen from History',
    'Saved results', 'Recent tools', 'Open result', 'Export original', 'Reuse inputs',
  ]) assert.ok(mock.includes(phrase), `mock includes ${phrase}`);
});

test('saved-result mock communicates immutable snapshots and complete, non-truncated exports', () => {
  for (const phrase of [
    'reopening never reruns the calculator',
    'Assumptions are stored with this result so future formula changes do not alter it.',
    'All 60 schedule rows included',
    'The export never silently drops rows or columns.',
    'PNG/JPEG are one-page summaries',
    'Delete saved result',
  ]) assert.ok(mock.includes(phrase), `mock explains ${phrase}`);
});

test('saved-result mock offers accessible state navigation, focus styles, responsive and dark states', () => {
  assert.match(mock, /role="tablist"/);
  assert.match(mock, /role="tabpanel"/);
  assert.match(mock, /aria-pressed/);
  assert.match(mock, /:focus-visible/);
  assert.match(mock, /@media\(max-width:760px\)/);
  assert.match(mock, /data-theme="dark"/);
  assert.match(mock, /prefers-reduced-motion:reduce/);
});

test('saved-result mock stays local and does not claim to create downloads', () => {
  assert.match(mock, /Mock only: this preview does not create or download a file\./);
  assert.doesNotMatch(mock, /\bfetch\s*\(/);
  assert.doesNotMatch(mock, /<script[^>]+src=/i);
  assert.doesNotMatch(mock, /<link[^>]+href="https?:/i);
});
