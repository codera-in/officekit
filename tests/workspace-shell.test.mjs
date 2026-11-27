import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const html = fs.readFileSync('index.html', 'utf8');
test('Home caps recent shortcuts without truncating the full recent view', () => {
  const source = html.match(/function officekitRecentHomeIds\(recents\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(source);
  const context = {};
  vm.runInNewContext(source, context);
  const list = [{toolId:'a'},{toolId:'b'},{toolId:'a'},{toolId:'c'},{toolId:'d'},{toolId:'e'},{toolId:'f'}];
  assert.deepEqual(Array.from(context.officekitRecentHomeIds(list)), ['a','b','c','d','e']);
  assert.equal(list.length, 7);
});
test('shell exposes Home and reversible labelled navigation controls', () => {
  assert.match(html, /id="tab-home"/);
  assert.match(html, /id="tab-recents"/);
  assert.match(html, /id="sidebar-toggle"[^>]*aria-expanded=/);
  assert.match(html, /id="app-shell"/);
  assert.match(html, /id="app-main"/);
  assert.match(html, /aria-label="Open Home"/);
});
test('shell keeps the notice close control, sidebar icons and build label visible', () => {
  assert.match(html, /aria-label="Dismiss announcement"[^>]*min-h-9 min-w-9[^>]*border-slate-500[^>]*bg-white[^>]*text-slate-800/);
  assert.match(html, /id="app-build-version"[^>]*>Version \d+\.\d+\.\d+</);
  const css = fs.readFileSync('assets/officekit.input.css', 'utf8');
  assert.match(css, /#app-sidebar nav button \{ color: var\(--ok-text\); \}/);
  assert.match(css, /#app-sidebar nav button\[aria-current="page"\].*aria-current="true"/);
});
test('All Tools has a visible inline grid icon independent of the icon font', () => {
  const button = html.match(/<button[^>]*data-sidebar-tab="tools"[^>]*>[\s\S]*?<\/button>/)?.[0];
  assert.ok(button);
  assert.match(button, /<svg[^>]*viewBox="0 0 16 16"[^>]*aria-hidden="true"/);
  assert.match(button, /<rect[^>]*x="1\.5"[^>]*y="1\.5"/);
  assert.match(button, /<span class="ok-nav-label">All Tools<\/span>/);
});
