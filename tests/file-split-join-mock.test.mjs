import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const mock = fs.readFileSync(path.join(root, 'design/mocks/file-split-join-workbench.html'), 'utf8');
const script = mock.match(/<script>([\s\S]*?)<\/script>/)?.[1];

test('file split/join mock reflects the bounded workspace API and exact downloadable artifacts', () => {
  for (const expected of [
    'Split a file',
    'Join OfficeKit parts',
    'Maximum size per part',
    'MiB',
    'Temporary local copies',
    'selected original remains unchanged',
    'SHA-256',
    'archive-backup.dat.zip',
    'joined/archive-backup.dat',
    'Clear temporary copies',
  ]) {
    assert.ok(mock.includes(expected), `mock is missing ${expected}`);
  }
  assert.match(mock, /id="part-size"[^>]*type="number"[^>]*min="1"[^>]*max="512"/);
  assert.match(mock, /512 MiB workspace limit/);
});

test('file split/join mock uses accessible tabs, responsive light/dark styling and no external I/O', () => {
  assert.match(mock, /role="tablist"/);
  assert.match(mock, /role="tab"[^>]*aria-selected="true"/);
  assert.match(mock, /role="tabpanel"/);
  assert.match(mock, /@media\s*\(max-width:\s*850px\)/);
  assert.match(mock, /@media\s*\(prefers-color-scheme:\s*dark\)/);
  assert.doesNotMatch(mock, /<(?:script|link|img)[^>]+(?:src|href)=["']https?:/i);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|showOpenFilePicker|navigator\.clipboard/);
  assert.ok(script, 'mock has an inline tab controller');
  assert.doesNotThrow(() => new vm.Script(script));
});

test('file split/join tabs switch panels and selection state by click and keyboard', () => {
  class FakeTab {
    constructor(id, panelId) {
      this.id = id;
      this.attributes = new Map([['aria-controls', panelId], ['aria-selected', 'false']]);
      this.listeners = new Map();
      this.focused = false;
    }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    getAttribute(name) { return this.attributes.get(name); }
    focus() { this.focused = true; }
  }
  const tabs = [new FakeTab('split-tab', 'split-panel'), new FakeTab('join-tab', 'join-panel')];
  const panels = new Map([['split-panel', { hidden: false }], ['join-panel', { hidden: true }]]);
  const document = {
    querySelectorAll(selector) { return selector === '[role="tab"]' ? tabs : []; },
    getElementById(id) { return panels.get(id); },
  };
  vm.runInNewContext(script, { document });

  tabs[1].listeners.get('click')();
  assert.equal(tabs[0].getAttribute('aria-selected'), 'false');
  assert.equal(tabs[1].getAttribute('aria-selected'), 'true');
  assert.equal(panels.get('split-panel').hidden, true);
  assert.equal(panels.get('join-panel').hidden, false);
  tabs[1].listeners.get('keydown')({ key: 'ArrowLeft', preventDefault() {} });
  assert.equal(tabs[0].focused, true);
  assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
  assert.equal(panels.get('split-panel').hidden, false);
  assert.equal(panels.get('join-panel').hidden, true);
});
