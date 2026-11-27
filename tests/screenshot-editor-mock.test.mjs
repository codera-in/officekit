import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const mock = new URL('../design/mocks/screenshot-editor-workbench.html', import.meta.url);
const html = await readFile(mock, 'utf8');
const review = await readFile(new URL('../design/mocks/screenshot-editor-review.html', import.meta.url), 'utf8');

test('screenshot editor mock contains the requested local edit and export flow', () => {
  for (const feature of ['Paste', 'Crop', 'Blur', 'Solid mask', 'Undo', 'PNG', 'JPEG', 'Local editing']) {
    assert.match(html, new RegExp(feature, 'i'));
  }
  assert.match(html, /Remove image metadata on export/);
  assert.match(html, /@media\(max-width:690px\)/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /data-theme="dark"/);
  assert.match(html, /toggleTheme\(\)/);
});

test('screenshot editor mock script parses and does not read clipboard or upload files', () => {
  const [, script] = html.match(/<script>([\s\S]*?)<\/script>/) ?? [];
  assert.ok(script, 'mock must include its interaction script');
  assert.doesNotThrow(() => new vm.Script(script));
  assert.doesNotMatch(script, /navigator\.clipboard|fetch\s*\(|XMLHttpRequest/);
  assert.match(script, /clipboard access is not requested/);
});

test('screenshot editor review mock shows current absence and accessible responsive proposal', () => {
  assert.match(review, /Current app/);
  assert.match(review, /Proposed/);
  for (const feature of ['Paste image', 'Choose image', 'Crop', 'Blur', 'Opaque mask', 'Undo', 'Redo', 'PNG', 'JPEG', 'Clear editor']) {
    assert.match(review, new RegExp(feature, 'i'));
  }
  assert.match(review, /clipboard is never read on launch/);
  assert.match(review, /20 undo steps/);
  assert.match(review, /metadata-free PNG\/JPEG/);
  assert.match(review, /@media\(max-width:820px\)/);
  assert.match(review, /prefers-color-scheme:dark/);
  assert.match(review, /:root\[data-theme="dark"\]/);
  assert.match(review, /aria-label="Edit tools"/);
});
