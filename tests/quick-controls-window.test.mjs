import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const native = fs.readFileSync(path.join(root, 'src-tauri/src/workspace_native.rs'), 'utf8');
const page = fs.readFileSync(path.join(root, 'quick-controls.html'), 'utf8');

test('the transparent Quick controls window has no native shadow, so no black outline frames the card', () => {
  const window = native.match(/WebviewWindowBuilder::new\(\s*app,\s*"quick-controls"[\s\S]*?\.build\(\)\?/)?.[0] ?? '';
  assert.match(window, /\.transparent\(true\)/);
  assert.match(window, /\.shadow\(false\)/);
  assert.doesNotMatch(window, /\.shadow\(true\)/);
  assert.match(page, /#quick-controls \{[^}]*box-shadow: var\(--ok-shadow\)/, 'the card keeps its own shadow');
});
