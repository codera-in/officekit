import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const desktopScript = readFileSync(path.join(root, 'assets', 'officekit-global-desktop.js'), 'utf8');
const registry = readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const apiContract = readFileSync(path.join(root, 'API-CONTRACT.md'), 'utf8');

// The screen budget from AGENTS.md: no page shows more than three buttons at once.
const BUTTON_LIMIT = 3;

// The HTML of one <section id="..."> including its nested sections, found by counting tags.
function sectionHtml(id) {
  const start = html.indexOf(`<section id="${id}"`);
  assert.notEqual(start, -1, `section ${id} exists`);
  const tag = /<\/?section\b/g;
  tag.lastIndex = start;
  let depth = 0;
  let match;
  while ((match = tag.exec(html))) {
    depth += match[0] === '</section' ? -1 : 1;
    if (depth === 0) return html.slice(start, tag.lastIndex + '>'.length);
  }
  assert.fail(`section ${id} closes`);
}

const buttonsIn = block => (block.match(/<button\b/g) || []).length;

test('the clipboard and snippets block shows at most three buttons (Resume, clipboard shortcut, snippets shortcut)', () => {
  const block = sectionHtml('global-desktop-card');
  assert.equal(buttonsIn(block), 3);
  assert.ok(buttonsIn(block) <= BUTTON_LIMIT);
  // The accessibility notice's action is a text link, and the skipped-apps editor is a disclosure, so neither adds a button.
  assert.match(block, /<a href="#" id="global-desktop-open-accessibility"/);
  assert.match(block, /<details id="global-desktop-edit-panel"/);
  assert.doesNotMatch(block, /id="global-desktop-edit-save"/);
});

test('the global launcher page shows at most three buttons (launcher shortcut, change key, reset)', () => {
  const block = sectionHtml('tab-global-launcher');
  assert.equal(buttonsIn(block), 3);
  assert.ok(buttonsIn(block) <= BUTTON_LIMIT);
  assert.match(block, /id="global-launcher-filter-name"/);
  assert.doesNotMatch(block, /data-global-action="launcher\.filter\./);
});

test('every pause and panel choice has a radio button with the value the store accepts', () => {
  const block = sectionHtml('global-clipboard-card');
  for (const value of ['off', '15m', '1h', 'until_resume']) assert.match(block, new RegExp(`name="global-clipboard-pause" value="${value}"`));
  for (const value of ['all', 'text', 'images', 'links', 'pinned']) assert.match(block, new RegExp(`name="global-clipboard-panel" value="${value}"`));
  assert.match(block, /id="global-clipboard-panel-text"[^>]*checked/);
  assert.match(block, /id="global-clipboard-pause-off"[^>]*checked/);
});

test('the desktop script only reads element ids that the markup defines', () => {
  const ids = new Set([...desktopScript.matchAll(/byId\('([^']+)'\)/g)].map(match => match[1]));
  assert.ok(ids.size > 30, 'the script reads its controls by id');
  const missing = [...ids].filter(id => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, []);
});

test('the launcher page is a sidebar tool with its own tab, and the clipboard tab keeps its route', () => {
  assert.match(registry, /"id": "global_launcher", "name": "Global Launcher"[^\n]*"tab": "global-launcher"/);
  assert.match(html, /global_launcher: \{ tab: 'global-launcher' \}/);
  assert.match(html, /'clipboard', 'global-launcher', 'password'/);
  assert.match(html, /\(tab === 'global-launcher' && officekitReleaseAllowsTool\('global_launcher'\)\)/);
  assert.match(html, /id="tab-clipboard"/);
});

test('the API contract documents the pause and panel settings and their choices', () => {
  assert.match(apiContract, /`capture_pause` \(`off`, `15m`, `1h`, `until_resume`\)/);
  assert.match(apiContract, /`panel_default_filter` \(`all`, `text`, `images`, `links`, `pinned`\)/);
  assert.match(apiContract, /clients cannot send `capture_paused_until`/);
  assert.match(apiContract, /1\.80\.0 · Global Launcher split, capture pause and panel-filter settings/);
});

test('the desktop script keeps the approved Clipboard history wording for the pause banner', () => {
  assert.match(desktopScript, /Capture paused until you resume/);
  assert.match(desktopScript, /Capture paused until \$\{until\.toLocaleTimeString/);
});
