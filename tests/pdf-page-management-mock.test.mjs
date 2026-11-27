import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const mock = fs.readFileSync('design/mocks/pdf-page-management-workbench.html', 'utf8');

test('PDF page management mock presents bounded delete and reorder tasks in the OfficeKit shell', () => {
  assert.match(mock, /PDF workbench/);
  assert.match(mock, /Delete pages/);
  assert.match(mock, /Reorder pages/);
  assert.match(mock, /3 pages · 2\.4 MB/);
  assert.match(mock, /letter · landscape/i);
  assert.match(mock, /A5 · portrait/i);
  assert.match(mock, /Create PDF with/);
  assert.match(mock, /Create reordered PDF/);
});

test('delete mock previews retained pages and prevents deleting every page', () => {
  assert.match(mock, /aria-pressed="true" data-page="2"/);
  assert.match(mock, /kept = \[1, 2, 3\]\.filter\(page => !removed\.includes\(page\)\)/);
  assert.match(mock, /Select at least one page to keep/);
  assert.match(mock, /Page removal is not secure redaction/);
  assert.match(mock, /Your original will not change/);
});

test('reorder mock offers drag, keyboard and button controls with a live output order', () => {
  assert.match(mock, /draggable="true"/);
  assert.match(mock, /event\.altKey && event\.key === 'ArrowUp'/);
  assert.match(mock, /event\.altKey && event\.key === 'ArrowDown'/);
  assert.match(mock, /data-move="up"/);
  assert.match(mock, /data-move="down"/);
  assert.match(mock, /Output order: \$\{order\.join\(', '\)\}/);
});

test('mock supports keyboard navigation, theme choice, reduced motion and responsive layouts', () => {
  assert.match(mock, /<nav class="tool-list" aria-label="PDF tools">/);
  assert.match(mock, /aria-current="page"/);
  assert.match(mock, /taskButtons\.forEach\(\(button, index\) => button\.addEventListener\('click', \(\) => openTask\(index\)\)\)/);
  assert.match(mock, /id="theme-toggle"/);
  assert.match(mock, /prefers-reduced-motion: reduce/);
  assert.match(mock, /@media \(max-width: 760px\)/);
  assert.match(mock, /officekit-icon\.svg/);
});

test('mock is a local prototype and does not make network or filesystem requests', () => {
  assert.doesNotMatch(mock, /https?:\/\//i);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|localStorage|FileReader/);
  assert.match(mock, /Mock only:/);
});
