import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('file intake requests go through officekitApiUrl so they work in the desktop webview', () => {
  const source = readFileSync(new URL('../assets/file-intake-capabilities.js', import.meta.url), 'utf8');
  assert.match(source, /const fetch = \(path, init\) => window\.fetch\(typeof officekitApiUrl === 'function' \? officekitApiUrl\(path\) : path, init\)/);
  assert.ok(!/window\.fetch\(['`]\/api/.test(source), 'no request may bypass the wrapper');
  assert.match(source, /switchTab\('file-intake'\);\s*\}\s*\}/, 'a failed open shows the intake page and its message');
});
