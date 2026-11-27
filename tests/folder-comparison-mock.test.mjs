import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const mock = await readFile(new URL('../design/mocks/folder-comparison-workbench.html', import.meta.url), 'utf8');

test('folder comparison mock shows a complete local-copy compare and cleanup flow', () => {
  for (const expected of [
    'Before → proposed',
    'Folder A',
    'Folder B',
    'Identical',
    'Changed',
    'Only in A',
    'Only in B',
    'Download CSV report',
    'Clear temporary copies',
    'originals remain unchanged',
    'Includes empty folders',
    'Folder structure',
    'Exports/empty-draft',
  ]) {
    assert.ok(mock.includes(expected), `mock is missing ${expected}`);
  }
});

test('folder comparison mock stays self-contained and supports a dark theme', () => {
  assert.doesNotMatch(mock, /<(?:script|link|img)[^>]+(?:src|href)=["']https?:/i);
  assert.match(mock, /data-theme="dark"/);
  assert.match(mock, /aria-pressed/);
  assert.match(mock, /<script>[\s\S]*?document\.documentElement\.dataset\.theme/);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|navigator\.clipboard|showOpenFilePicker/);
});
