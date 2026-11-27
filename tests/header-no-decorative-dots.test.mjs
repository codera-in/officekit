import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const read = path => fs.readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the header draws no fake window buttons; the real ones are in the macOS title bar', () => {
  const html = read('index.html');
  const header = html.slice(html.indexOf('<header'), html.indexOf('</header>'));
  assert.ok(header.includes('ok-header-brand'), 'the header and its brand button are found');
  assert.doesNotMatch(header, /traffic-(?:lights|dot)|dot-(?:red|yellow|green)/);
  assert.doesNotMatch(read('assets/officekit.input.css'), /\.traffic-(?:lights|dot)|\.dot-(?:red|yellow|green)/);
});

test('the brand button is the first control in the header', () => {
  const html = read('index.html');
  const header = html.slice(html.indexOf('<header'), html.indexOf('</header>'));
  const row = header.slice(header.indexOf('<div class="flex items-center gap-2">'));
  assert.ok(row.slice(0, 200).includes('aria-label="Open Home"'), 'nothing sits before the brand button');
});
