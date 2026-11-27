import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const read = path => fs.readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const tokens = read('design/officekit-tokens.css');
const css = read('assets/officekit.input.css');

test('the preview canvas token is defined for light and dark, so the dark theme no longer falls back to light', () => {
  const light = tokens.slice(tokens.indexOf(':root {'), tokens.indexOf(':root[data-theme="dark"]'));
  const dark = tokens.slice(tokens.indexOf(':root[data-theme="dark"]'));
  assert.match(light, /--ok-canvas: #eef3f6;/);
  assert.match(dark, /--ok-canvas: #0e1721;/);
  assert.match(read('index.html'), /id="screenshot-canvas-stage"[^>]*bg-\[var\(--ok-canvas,#EEF3F6\)\]/);
});

test('the dark canvas gets a dot grid and the image a shadow', () => {
  assert.match(css, /\[data-theme="dark"\] \.ok-app #screenshot-canvas-stage \{[^}]*radial-gradient/);
  assert.match(css, /\[data-theme="dark"\] \.ok-app #screenshot-canvas \{ box-shadow:/);
});

test('the annotation list and the format list leave room for the arrow', () => {
  const rule = css.match(/\.ok-app #screenshot-object-list, \.ok-app #screenshot-export-format \{([^}]*)\}/)?.[1] ?? '';
  assert.match(rule, /padding-right: 1\.75rem/);
  assert.match(rule, /min-width: 9\.5rem/);
  assert.match(rule, /text-overflow: ellipsis/);
});
