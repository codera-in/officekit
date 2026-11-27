import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

// S06 Restore from Trash (approved mock v5). The screen, the Storage cleanup review and the duplicate result share one fake DOM.
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const filesSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-files.js'), 'utf8');
const sliceSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-files.js'), 'utf8');
const storageSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-storage.js'), 'utf8');

// Copy from the approved mock (pending-files-s06.html, section A). The curly apostrophe is U+2019.
const COPY = {
  title: 'You can put these back for 30 days',
  short: 'OfficeKit keeps a private list of what it moves to Trash, so you can put items back for 30 days. The list stays on this Mac.',
  open: 'Open Restore from Trash to put items back or forget them.',
  kept: 'To let you put items back, OfficeKit keeps a private list of what it moves to Trash: each item’s name, original folder, size and when it was moved. The list stays on this Mac, is readable only by your account, and is never logged, exported or sent anywhere. Entries are removed after 30 days, or sooner when you choose Forget.',
  skippedNote: 'Skipped items stay in the list, where you can use Restore to…',
  emptyNote: 'Items OfficeKit moves to Trash from Duplicate finder or Storage cleanup appear here for 30 days.',
};

let registry = null;
class FakeNode {
  constructor(tagName = '', id = '') {
    this.tagName = String(tagName).toUpperCase(); this.children = []; this.text = ''; this.parent = null;
    this.hidden = false; this.disabled = false; this.checked = false; this.value = ''; this.type = ''; this.title = '';
    this.className = ''; this.dataset = {}; this.style = {}; this.attributes = {}; this.onclick = null; this.onchange = null;
    this._id = ''; if (id) this.id = id;
  }
  get id() { return this._id; }
  set id(value) { this._id = value; if (registry && value) registry.set(value, this); }
  get classes() { return new Set(String(this.className).split(/\s+/).filter(Boolean)); }
  get classList() {
    const node = this;
    const write = set => { node.className = [...set].join(' '); };
    return {
      add: (...names) => { const set = node.classes; names.forEach(name => set.add(name)); write(set); },
      remove: (...names) => { const set = node.classes; names.forEach(name => set.delete(name)); write(set); },
      toggle: (name, on) => { const set = node.classes; const want = on ?? !set.has(name); if (want) set.add(name); else set.delete(name); write(set); return want; },
      contains: name => node.classes.has(name),
    };
  }
  get textContent() { return this.children.length ? this.children.map(child => (typeof child === 'string' ? child : child.textContent)).join('') : this.text; }
  set textContent(value) { this.children = []; this.text = String(value ?? ''); }
  get parentElement() { return this.parent; }
  append(...nodes) {
    for (const node of nodes) {
      if (node && typeof node === 'object') { if (node.parent) node.parent.children = node.parent.children.filter(child => child !== node); node.parent = this; }
      this.children.push(node);
    }
    if (this.tagName === 'SELECT' && !this.value && nodes[0] && typeof nodes[0] === 'object') this.value = nodes[0].value ?? '';
  }
  prepend(...nodes) { this.children.unshift(...nodes); nodes.forEach(node => { if (node && typeof node === 'object') node.parent = this; }); }
  replaceChildren(...nodes) { this.children.forEach(child => { if (child && typeof child === 'object') child.parent = null; }); this.children = []; this.text = ''; this.append(...nodes); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener() {}
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  querySelectorAll(selector) { const found = []; walk(this, node => { if (node !== this && matches(node, selector)) found.push(node); }); return found; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}
function matches(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classes.has(selector.slice(1));
  return node.tagName === selector.toUpperCase();
}
function walk(node, visit) { if (!node || typeof node !== 'object') return; visit(node); for (const child of node.children) walk(child, visit); }
function allNodes(root) { const out = []; walk(root, node => out.push(node)); return out; }
// Counted buttons: every button except in-text links and list-row actions (AGENTS.md Button Limit).
function countedButtons(root) { return allNodes(root).filter(node => node.tagName === 'BUTTON' && !node.classes.has('ok-text-link') && !node.classes.has('row-act')); }
function linkNamed(root, text) { return allNodes(root).find(node => node.tagName === 'BUTTON' && node.classes.has('ok-text-link') && node.textContent === text) ?? null; }
function buttonNamed(root, text) { return allNodes(root).find(node => node.tagName === 'BUTTON' && node.textContent === text) ?? null; }
function tableRows(root) { const table = allNodes(root).find(node => node.tagName === 'TABLE'); return table ? allNodes(table).filter(node => node.tagName === 'TR') : []; }
function cellsOf(row) { return row.children.filter(child => child.tagName === 'TD'); }
function checkboxOf(cell) { return cell.children.find(child => child.tagName === 'INPUT') ?? null; }

const fixtures = {
  // moved_at is epoch seconds, as GET /api/trash-records sends it (API-CONTRACT: moved_at is epoch seconds).
  restorable: { id: 'r1', name: 'report-final.pdf', original_folder_display: '~/Documents/Work', moved_at: Date.UTC(2026, 9, 23, 10, 42) / 1000, size_bytes: 1024, state: 'restorable' },
  second: { id: 'r2', name: 'IMG_2041 copy.jpg', original_folder_display: '~/Pictures/Trip', moved_at: Date.UTC(2026, 9, 23, 10, 42) / 1000, size_bytes: 2048, state: 'restorable' },
  taken: { id: 'r3', name: 'notes.txt', original_folder_display: '~/Desktop', moved_at: Date.UTC(2026, 9, 22, 9) / 1000, size_bytes: 4096, state: 'name-taken' },
  changed: { id: 'r4', name: 'old-build', original_folder_display: '~/Code/app', moved_at: Date.UTC(2026, 9, 20, 9) / 1000, size_bytes: 1048576, state: 'changed' },
  missing: { id: 'r5', name: 'setup.dmg', original_folder_display: '~/Downloads', moved_at: Date.UTC(2026, 9, 11, 9) / 1000, size_bytes: 98304, state: 'missing' },
};
const sample = () => Object.values(fixtures).map(record => ({ ...record }));

function jsonResponse(body, status = 200) { return { ok: status < 400, status, json: async () => body }; }

// Loads the Files screen, the Files slice and the Storage module into one sandbox, with an invoke and a fetch the test controls.
function loadUi({ records = sample(), handlers = {}, listFails = false } = {}) {
  registry = new Map();
  const invokes = [], fetches = [];
  new FakeNode('section', 'tab-workspace');
  for (const id of ['direct-file-results', 'direct-file-title', 'direct-file-description', 'direct-selections', 'direct-file-status']) new FakeNode('div', id);
  const document = {
    createElement: tag => new FakeNode(tag),
    getElementById: id => registry.get(id) ?? null,
    querySelectorAll: () => [],
    querySelector: () => null,
    body: new FakeNode('body'),
  };
  const invoke = (command, args) => {
    // Values built inside the vm context carry that realm's prototypes; record them as plain data.
    invokes.push({ command, args: JSON.parse(JSON.stringify(args ?? null)) });
    if (!handlers[command]) throw Error(`unexpected ${command}`);
    return handlers[command](args);
  };
  const context = {
    console, Date, Math, Number, Promise, Error, JSON, Object, Array, String, Map, Set, Intl, structuredClone,
    setTimeout: (fn, ms) => { const timer = globalThis.setTimeout(fn, ms); timer.unref?.(); return timer; },
    clearTimeout: globalThis.clearTimeout,
    document,
    Event: class { constructor(type) { this.type = type; } },
    WORKSPACE_TOOL_COPY: {},
    tauriInvoke: () => invoke,
    officekitApiUrl: requestPath => requestPath,
    fetch: async requestPath => {
      fetches.push(requestPath);
      if (listFails) return jsonResponse({ detail: 'raw server text' }, 500);
      const offset = Number(new URL(requestPath, 'http://local').searchParams.get('offset'));
      return jsonResponse({ records: records.slice(offset, offset + 200), hasMore: offset + 200 < records.length });
    },
    officekitMountResultActions: (container) => {
      const row = new FakeNode('div'); row.className = 'officekit-result-actions';
      const copy = new FakeNode('button'); copy.className = 'btn btn-outline'; copy.textContent = 'Copy report';
      const download = new FakeNode('button'); download.className = 'btn btn-outline officekit-result-download'; download.textContent = 'Download';
      row.append(copy, download); container.append(row);
      return { element: row };
    },
    OfficeKitExtensions: { register: config => { context.registration = config; } },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(filesSource, context);
  vm.runInContext(sliceSource, context);
  vm.runInContext(storageSource, context);
  context.officekitDirectFilesReady = true;
  return { context, registry, invokes, fetches };
}

async function openRestore(options) {
  const ui = loadUi(options);
  await ui.context.officekitTrashRestoreOpen();
  return { ...ui, screen: ui.registry.get('trash-restore') };
}

test('the Restore screen loads the list on open with GET pages and no Load or Refresh button', async () => {
  const records = Array.from({ length: 201 }, (_, index) => ({ ...fixtures.restorable, id: `p${index}`, name: `file-${index}.txt` }));
  const ui = await openRestore({ records });
  assert.deepEqual(ui.fetches, ['/api/trash-records?offset=0&limit=200', '/api/trash-records?offset=200&limit=200']);
  assert.equal(tableRows(ui.screen).length - 1, 201);
  assert.equal(ui.screen.textContent.includes('201 items moved by OfficeKit in the last 30 days · 201 selected'), true);
  assert.equal(countedButtons(ui.screen).some(button => /Load|Refresh/.test(button.textContent)), false);
});

test('the catalogue and the Files slice route the Restore ID to the Files workspace', () => {
  const ui = loadUi();
  assert.equal(ui.context.registration.destinations.trash_restore.sliceView, 'trash_restore');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.context.registration.destinations.trash_restore)), { tab: 'workspace', sliceView: 'trash_restore' });
});

test('each row state shows the mock label, the checkbox state and the row links', async () => {
  const ui = await openRestore();
  const rows = tableRows(ui.screen).slice(1);
  const expected = [
    ['Restorable', false, ['Forget']],
    ['Restorable', false, ['Forget']],
    ['Name taken', true, ['Restore to…', 'Forget']],
    ['Folder changed', true, ['Restore to…', 'Forget']],
    ['Not in Trash', null, ['Forget']],
  ];
  assert.equal(rows.length, expected.length);
  rows.forEach((row, index) => {
    const [label, disabled, links] = expected[index];
    const cells = cellsOf(row);
    const box = checkboxOf(cells[0]);
    if (disabled === null) assert.equal(box, null, 'missing items have no checkbox');
    else { assert.ok(box, 'checkbox'); assert.equal(box.disabled, disabled); }
    assert.equal(allNodes(cells[5]).find(node => node.tagName === 'SPAN').textContent, label);
    assert.deepEqual(allNodes(cells[6]).filter(node => node.tagName === 'BUTTON').map(node => node.textContent), links);
  });
  assert.equal(checkboxOf(cellsOf(rows[0])[0]).checked, true, 'restorable rows start selected, as in the mock');
});

test('the summary, dock status and counted buttons match the list (E) frame', async () => {
  const ui = await openRestore();
  assert.equal(ui.screen.textContent.includes('5 items moved by OfficeKit in the last 30 days · 2 selected'), true);
  assert.equal(ui.screen.textContent.includes('2 selected · 3.0 KB'), true);
  const counted = countedButtons(ui.screen);
  assert.deepEqual(counted.map(button => button.textContent), ['Restore selected']);
  assert.equal(counted[0].disabled, false);
  assert.equal(counted[0].classes.has('btn-primary'), true);
});

test('deselecting every row disables Restore selected, and selecting again enables it', async () => {
  const ui = await openRestore();
  const rows = tableRows(ui.screen).slice(1);
  const action = buttonNamed(ui.screen, 'Restore selected');
  const first = checkboxOf(cellsOf(rows[0])[0]), second = checkboxOf(cellsOf(rows[1])[0]);
  first.checked = false; first.onchange();
  assert.equal(action.disabled, false);
  second.checked = false; second.onchange();
  assert.equal(action.disabled, true);
  assert.equal(ui.screen.textContent.includes('0 selected · 0 bytes'), true);
  first.checked = true; first.onchange();
  assert.equal(action.disabled, false);
  assert.equal(ui.screen.textContent.includes('1 selected · 1.0 KB'), true);
});

test('with nothing restorable the empty selection disables Restore selected', async () => {
  const ui = await openRestore({ records: [fixtures.taken, fixtures.missing] });
  const action = buttonNamed(ui.screen, 'Restore selected');
  assert.equal(action.disabled, true);
  assert.equal(countedButtons(ui.screen).length, 1);
});

test('empty state shows the approved copy and one disabled counted button', async () => {
  const ui = await openRestore({ records: [] });
  assert.equal(ui.screen.textContent.includes('Nothing to restore.'), true);
  assert.equal(ui.screen.textContent.includes(COPY.emptyNote), true);
  const counted = countedButtons(ui.screen);
  assert.deepEqual(counted.map(button => [button.textContent, button.disabled]), [['Restore selected', true]]);
  assert.equal(ui.screen.textContent.includes('No items'), true);
});

test('the narrow layout keeps the sub-line and hides the three desktop-only columns', async () => {
  const ui = await openRestore();
  const headers = allNodes(ui.screen).filter(node => node.tagName === 'TH');
  const hidden = headers.filter(node => node.classes.has('ok-phone-hide')).map(node => node.textContent);
  assert.deepEqual(hidden, ['Original folder', 'Moved', 'Size']);
  const firstRow = tableRows(ui.screen)[1];
  const sub = allNodes(cellsOf(firstRow)[1]).find(node => node.tagName === 'SMALL');
  assert.equal(sub.classes.has('ok-phone-show'), true);
  assert.equal(sub.textContent.startsWith('~/Documents/Work · '), true);
  assert.equal(cellsOf(firstRow).slice(2, 5).every(cell => cell.classes.has('ok-phone-hide')), true);
});

test('Restore selected confirms natively, then applies the returned grant to the selected ids', async () => {
  const handlers = {
    trash_restore_confirm: () => 'grant-1',
    trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null }, { id: 'r2', state: 'restored', reason: null }], restored_bytes: 3072 }),
  };
  const ui = await openRestore({ handlers });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  assert.deepEqual(ui.invokes.map(call => call.command), ['trash_restore_confirm', 'trash_restore_apply']);
  assert.deepEqual(ui.invokes[0].args, { items: [{ id: 'r1', name: 'report-final.pdf', folder: '~/Documents/Work' }, { id: 'r2', name: 'IMG_2041 copy.jpg', folder: '~/Pictures/Trip' }], destinationGrantId: null });
  assert.deepEqual(ui.invokes[1].args, { restoreGrantId: 'grant-1', recordIds: ['r1', 'r2'] });
  assert.equal(ui.screen.textContent.includes('Result'), true);
  assert.equal(ui.screen.textContent.includes('2 restored to their original folders · 3.0 KB'), true);
  assert.equal(ui.screen.textContent.includes('Skipped items stay in the list'), false, 'the note is shown only when a row was skipped');
  assert.equal(allNodes(ui.screen).filter(node => node.tagName === 'SPAN' && node.textContent === 'Restored').length, 2);
  assert.deepEqual(countedButtons(ui.screen).map(button => button.textContent), ['Done']);
  assert.equal(ui.screen.textContent.includes('Done · 2 restored'), true);
});

test('a null grant from the native confirmation is a cancel: nothing is applied and the list stays', async () => {
  const ui = await openRestore({ handlers: { trash_restore_confirm: () => null } });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  assert.deepEqual(ui.invokes.map(call => call.command), ['trash_restore_confirm']);
  assert.equal(ui.screen.textContent.includes('Result'), false);
  assert.equal(buttonNamed(ui.screen, 'Restore selected').disabled, false);
});

test('running state disables the one counted button and says Restoring while the native call is open', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const ui = await openRestore({ handlers: { trash_restore_confirm: () => pending } });
  const run = buttonNamed(ui.screen, 'Restore selected').onclick();
  assert.deepEqual(countedButtons(ui.screen).map(button => [button.textContent, button.disabled]), [['Restore selected', true]]);
  assert.equal(ui.screen.textContent.includes('Restoring…'), true);
  release(null);
  await run;
  assert.equal(buttonNamed(ui.screen, 'Restore selected').disabled, false);
});

test('Restore to… asks for a directory with the trash-restore job, then restores into the chosen folder', async () => {
  const handlers = {
    file_output_choose: () => ({ id: 'out-1', path: '/Users/demo/Desktop/notes.txt' }),
    trash_restore_confirm: () => 'grant-2',
    trash_restore_apply: () => ({ items: [{ id: 'r3', state: 'restored', reason: null, restored_to: '/Users/demo/Desktop/notes.txt' }], restored_bytes: 4096 }),
    trash_restore_reveal: () => null,
  };
  const ui = await openRestore({ handlers });
  const rows = tableRows(ui.screen).slice(1);
  await cellsOf(rows[2])[6].children.find(node => node.textContent === 'Restore to…').onclick();
  assert.deepEqual(ui.invokes[0], { command: 'file_output_choose', args: { kind: 'directory', suggestedName: 'notes.txt', jobKind: 'trash-restore', overwrite: false } });
  assert.deepEqual(ui.invokes[1].args.destinationGrantId, 'out-1');
  assert.deepEqual(ui.invokes[2].args, { restoreGrantId: 'grant-2', recordIds: ['r3'] });
  const reveal = linkNamed(ui.screen, 'Show in Finder');
  await reveal.onclick();
  assert.deepEqual(ui.invokes.at(-1), { command: 'trash_restore_reveal', args: { path: '/Users/demo/Desktop/notes.txt' } });
});

test('a null output from Restore to… makes no confirm call', async () => {
  const ui = await openRestore({ handlers: { file_output_choose: () => null } });
  const rows = tableRows(ui.screen).slice(1);
  await cellsOf(rows[2])[6].children.find(node => node.textContent === 'Restore to…').onclick();
  assert.deepEqual(ui.invokes.map(call => call.command), ['file_output_choose']);
});

test('Show in Finder on a restored row reveals the path the server restored to, and only that path', async () => {
  const handlers = {
    trash_restore_confirm: () => 'grant-1',
    trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null, restored_to: '/Users/demo/Documents/Work/report-final.pdf' }], restored_bytes: 1024 }),
    trash_restore_reveal: () => null,
  };
  const ui = await openRestore({ handlers });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  const reveal = ui.screen.textContent.includes('Show in Finder');
  assert.equal(reveal, true);
  await linkNamed(ui.screen, 'Show in Finder').onclick();
  assert.deepEqual(ui.invokes.at(-1), { command: 'trash_restore_reveal', args: { path: '/Users/demo/Documents/Work/report-final.pdf' } });
});

test('a skipped item shows its plain reason in the result and is not restored', async () => {
  const handlers = {
    trash_restore_confirm: () => 'grant-1',
    trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null }, { id: 'r2', state: 'skipped', reason: 'name-taken' }], restored_bytes: 1024 }),
  };
  const ui = await openRestore({ handlers });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  assert.equal(ui.screen.textContent.includes('Name taken. Nothing was replaced.'), true);
  assert.equal(ui.screen.textContent.includes(COPY.skippedNote), true);
  assert.equal(ui.screen.textContent.includes('1 restored to their original folders · 1.0 KB'), true);
});

test('Done returns to a fresh list, and the restored items are gone from it', async () => {
  let listed = sample();
  const handlers = {
    trash_restore_confirm: () => 'grant-1',
    trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null }, { id: 'r2', state: 'restored', reason: null }], restored_bytes: 3072 }),
  };
  const ui = await openRestore({ handlers, records: listed });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  listed = listed.filter(record => !['r1', 'r2'].includes(record.id));
  ui.context.fetch = async requestPath => { ui.fetches.push(requestPath); return jsonResponse({ records: listed, hasMore: false }); };
  await buttonNamed(ui.screen, 'Done').onclick();
  assert.equal(ui.screen.textContent.includes('Result'), false);
  assert.equal(tableRows(ui.screen).length - 1, 3);
});

test('Forget calls the native forget, reloads on true, and keeps the row on false', async () => {
  const records = sample();
  let answer = false;
  const handlers = { trash_record_forget: () => answer };
  const ui = await openRestore({ handlers, records });
  const rows = () => tableRows(ui.screen).slice(1);
  const forgetOn = index => cellsOf(rows()[index])[6].children.find(node => node.textContent === 'Forget');
  await forgetOn(0).onclick();
  assert.deepEqual(ui.invokes.at(-1), { command: 'trash_record_forget', args: { recordId: 'r1', name: 'report-final.pdf' } });
  assert.equal(rows().length, 5, 'false keeps the row');
  assert.equal(ui.fetches.length, 1, 'false does not reload');
  answer = true;
  await forgetOn(0).onclick();
  assert.equal(ui.fetches.length, 2, 'true reloads the list');
});

test('a 403 shows the fixed approval text, a 404 the missing-item text, and anything else the fallback; no server text', async () => {
  const cases = [
    [Object.assign(Error('raw server text'), { status: 403 }), 'Choose the items again.'],
    [Object.assign(Error('raw server text'), { status: 404 }), 'That item is no longer in the list.'],
    [Error('raw server text'), 'The items could not be restored. Try again.'],
  ];
  for (const [error, expected] of cases) {
    const ui = await openRestore({ handlers: { trash_restore_confirm: () => { throw error; } } });
    await buttonNamed(ui.screen, 'Restore selected').onclick();
    assert.equal(ui.screen.textContent.includes(expected), true, expected);
    assert.equal(ui.screen.textContent.includes('raw server text'), false);
  }
});

test('a failed list load shows the list fallback and no raw server text', async () => {
  const ui = await openRestore({ listFails: true });
  assert.equal(ui.screen.textContent.includes('The Trash list could not be loaded. Try again.'), true);
  assert.equal(ui.screen.textContent.includes('raw server text'), false);
});

test('the Restore screen shows the disclosure copy, and What is kept expands in place', async () => {
  const ui = await openRestore();
  const block = allNodes(ui.screen).find(node => node.classes.has('ok-trash-disclosure'));
  assert.equal(block.textContent.includes(COPY.short), true);
  const kept = allNodes(block).find(node => node.classes.has('ok-trash-kept'));
  assert.equal(kept.hidden, true);
  assert.equal(kept.textContent, COPY.kept);
  linkNamed(block, 'What is kept').onclick();
  assert.equal(kept.hidden, false);
  assert.equal(allNodes(ui.screen).some(node => node.tagName === 'BUTTON' && node.textContent === 'Restore selected'), true);
});

test('the storage review shows the boxed disclosure, and its dialog keeps exactly two buttons', async () => {
  const ui = loadUi({ handlers: {} });
  const candidate = { id: 'candidate-1', name: 'old.zip', path: '/Users/demo/Downloads/old.zip', category: 'downloads', sizeBytes: 20, modifiedAt: 100, createdAt: null, method: 'trash', eligible: true, reason: 'Old download', impact: 'Review personal file.' };
  const plan = { id: 'plan-1', expiresAt: Date.now() / 1000 + 300, items: [candidate], estimatedBytes: 20, impact: 'Move to Trash.' };
  vm.runInContext(`officekitStorageMount(); officekitStorage.selected = new Set(['candidate-1']); officekitStorage.cleanupAllowed = true; officekitStorage.scan = 'scan-1';`, ui.context);
  ui.context.fetch = async () => jsonResponse(plan);
  await ui.context.officekitStorageReview();
  const dialog = registry.get('storage-confirm');
  assert.equal(dialog.open, true);
  assert.deepEqual(countedButtons(dialog).map(button => button.textContent), ['Back to results', 'Confirm cleanup']);
  const items = registry.get('storage-confirm-items');
  assert.equal(items.textContent.includes(COPY.title), true);
  assert.equal(items.textContent.includes(`${COPY.short} ${COPY.open}`), true);
  const block = allNodes(items).find(node => node.classes.has('ok-trash-disclosure'));
  assert.equal(block.classes.has('boxed'), true);
  linkNamed(block, 'What is kept').onclick();
  assert.equal(allNodes(block).find(node => node.classes.has('ok-trash-kept')).textContent, COPY.kept);
});

test('the duplicate result keeps exactly three counted buttons and shows the line above the move action', async () => {
  const ui = loadUi({ handlers: {} });
  vm.runInContext(`officekitDirectFilesState.action = 'duplicates'; officekitDirectFilesState.job = 'job-1'; officekitDirectFilesState.selections = [{ id: 'sel-1', displayNames: ['Copies'], mode: 'folder', access: 'read-write' }];`, ui.context);
  const report = {
    match_kind: 'files', complete: true, trash_supported: true, files_scanned: 3,
    groups: [{ size_bytes: 1024, hash: 'h1', entries: [
      { id: 'f1', name: 'a.txt', display_name: 'a.txt', full_path: '/x/a.txt', modified_at: '2026-10-20T00:00:00Z' },
      { id: 'f2', name: 'b.txt', display_name: 'b.txt', full_path: '/x/b.txt', modified_at: '2026-10-20T00:00:00Z' },
    ] }],
  };
  ui.context.officekitRenderDirectReport(report, 'job-1');
  const container = registry.get('direct-file-results');
  assert.deepEqual(countedButtons(container).map(button => button.textContent), ['Copy report', 'Download', 'Move selected to Trash']);
  const disclosure = allNodes(container).find(node => node.classes.has('ok-trash-disclosure'));
  assert.equal(disclosure.textContent.includes(COPY.short), true);
  assert.equal(linkNamed(disclosure, 'What is kept') !== null, true);
  const trash = registry.get('duplicate-trash');
  assert.equal(trash.parent.classes.has('officekit-result-actions'), true, 'the move action stays in the result dock');
});

// S06 review round 1 (QA-1, UX-1, UX-5, UX-6, UX-7, UX-8, UX-9, UX-11, CR-3, CR-4).
function alertTexts(root) { return allNodes(root).filter(node => node.getAttribute('role') === 'alert').map(node => node.textContent); }

test('QA-1: the Moved cell shows the local date for the epoch seconds the API sends', async () => {
  const ui = await openRestore();
  const cells = cellsOf(tableRows(ui.screen)[1]);
  assert.equal(cells[3].textContent, new Date(fixtures.restorable.moved_at * 1000).toLocaleString());
  assert.equal(cells[3].textContent.includes('Unavailable'), false);
});

test('UX-1: a failed list load is announced as an alert, not a status', async () => {
  const ui = await openRestore({ listFails: true });
  assert.deepEqual(alertTexts(ui.screen), ['The Trash list could not be loaded. Try again.']);
});

test('UX-1: a failed restore is an alert, and a successful one is not', async () => {
  const failing = await openRestore({ handlers: { trash_restore_confirm: () => { throw Error('raw server text'); } } });
  await buttonNamed(failing.screen, 'Restore selected').onclick();
  assert.deepEqual(alertTexts(failing.screen), ['The items could not be restored. Try again.']);
  const working = await openRestore({
    handlers: {
      trash_restore_confirm: () => 'grant-1',
      trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null }, { id: 'r2', state: 'restored', reason: null }], restored_bytes: 3072 }),
    },
  });
  await buttonNamed(working.screen, 'Restore selected').onclick();
  assert.deepEqual(alertTexts(working.screen), []);
});

test('UX-7: a failed restore keeps the list in place; the error sits in the dock status', async () => {
  const ui = await openRestore({ handlers: { trash_restore_confirm: () => { throw Error('raw server text'); } } });
  const before = ui.screen.children[2].children.map(node => node.tagName);
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  const panel = ui.screen.children[2];
  assert.deepEqual(panel.children.map(node => node.tagName), before);
  assert.equal(panel.children.some(node => node.getAttribute('role') === 'alert'), false);
  const status = allNodes(ui.screen).find(node => node.tagName === 'SPAN' && node.classes.has('status'));
  assert.equal(status.textContent, 'The items could not be restored. Try again.');
  assert.equal(status.getAttribute('role'), 'alert');
});

test('UX-8 / CR-3: Restore to a folder waits for a running file job, as the other file tools do', () => {
  const ui = loadUi();
  vm.runInContext('officekitDirectFilesState.busy = true;', ui.context);
  assert.equal(ui.context.officekitOpenDirectFileTool('trash_restore'), false);
  assert.equal(ui.registry.get('trash-restore') ?? null, null, 'the Restore screen is not opened');
  assert.equal(ui.fetches.length, 0);
  assert.equal(ui.registry.get('direct-file-status').textContent.includes('Wait for this operation'), true);
});

test('UX-5 / CR-4: Restore to… confirms the folder the user chose, never the placeholder', async () => {
  const handlers = {
    file_output_choose: () => ({ id: 'out-9', path: '/Users/demo/Desktop/notes.txt' }),
    trash_restore_confirm: () => null,
  };
  const ui = await openRestore({ handlers });
  await cellsOf(tableRows(ui.screen)[3])[6].children.find(node => node.textContent === 'Restore to…').onclick();
  assert.deepEqual(ui.invokes[1], { command: 'trash_restore_confirm', args: { items: [{ id: 'r3', name: 'notes.txt', folder: '/Users/demo/Desktop' }], destinationGrantId: 'out-9' } });
  assert.equal(JSON.stringify(ui.invokes).includes('Chosen folder'), false);
});

async function reviewPlan(methods) {
  const ui = loadUi({ handlers: {} });
  const items = methods.map((method, index) => ({ id: `candidate-${index}`, name: `old-${index}.zip`, path: `/Users/demo/Downloads/old-${index}.zip`, category: 'downloads', sizeBytes: 20, modifiedAt: 100, createdAt: null, method, eligible: true, reason: 'Old download', impact: 'Review personal file.' }));
  const plan = { id: 'plan-1', expiresAt: Date.now() / 1000 + 300, items, estimatedBytes: 20 * items.length, impact: 'Review the items.' };
  vm.runInContext(`officekitStorageMount(); officekitStorage.selected = new Set(${JSON.stringify(items.map(item => item.id))}); officekitStorage.cleanupAllowed = true; officekitStorage.scan = 'scan-1';`, ui.context);
  const calls = [];
  ui.context.fetch = async (url, init) => { calls.push({ url, init }); return jsonResponse(plan); };
  await ui.context.officekitStorageReview();
  // QA-9: exactly one plan POST, with the selected candidate ids in order.
  assert.equal(calls.length, 1, 'one storage-plan request');
  assert.equal(calls[0].url, '/api/storage-cleanup-plans');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), { scanId: 'scan-1', candidateIds: items.map(item => item.id) });
  return registry.get('storage-confirm-items');
}

test('UX-6 / PM-1: a review whose items all move to Trash shows the boxed disclosure', async () => {
  const items = await reviewPlan(['trash', 'trash']);
  const block = allNodes(items).find(node => node.classes.has('ok-trash-disclosure'));
  assert.equal(block.classes.has('boxed'), true);
});

test('UX-6 / PM-1: a mixed review shows the disclosure and still labels the permanent item', async () => {
  const items = await reviewPlan(['trash', 'tool']);
  assert.equal(allNodes(items).some(node => node.classes.has('ok-trash-disclosure')), true);
  assert.equal(items.textContent.includes('Permanent cleanup — cannot be undone'), true);
});

test('UX-6 / PM-1: a permanent-only review shows no Trash disclosure', async () => {
  const items = await reviewPlan(['tool']);
  assert.equal(allNodes(items).some(node => node.classes.has('ok-trash-disclosure')), false);
  assert.equal(items.textContent.includes(COPY.title), false);
  assert.equal(items.textContent.includes('Permanent cleanup — cannot be undone'), true);
});

test('UX-9 / UX-11: the result note is shown only when a row was skipped, and promises no link the rows lack', async () => {
  const handlers = {
    trash_restore_confirm: () => 'grant-1',
    trash_restore_apply: () => ({ items: [{ id: 'r1', state: 'restored', reason: null }, { id: 'r2', state: 'skipped', reason: 'name-taken' }], restored_bytes: 1024 }),
  };
  const ui = await openRestore({ handlers });
  await buttonNamed(ui.screen, 'Restore selected').onclick();
  assert.equal(ui.screen.textContent.includes(COPY.skippedNote), true);
  assert.equal(ui.screen.textContent.includes('Restored items leave this list'), false);
});

const sliceCss = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-files.css'), 'utf8');
function trashCompactRules(css) {
  const start = css.indexOf('/* Restore from Trash compact layout');
  assert.notEqual(start, -1, 'the compact layout block exists');
  const open = css.indexOf('@media (max-width: 900px) {', start);
  return css.slice(open, css.indexOf('\n}\n', open));
}

test('UX-2: no desktop rule forces the phone sub-line to display at every width', () => {
  const rule = sliceCss.match(/\.ok-trash-table small \{[^}]*\}/)[0];
  assert.equal(/display:\s*block/.test(rule), false);
  assert.match(sliceCss, /@media \(max-width: 900px\) \{ \.ok-phone-show \{ display: block; \} \}/);
});

test('UX-3 / UX-4: below 900px the table loses its 760px minimum, state and links stack, and links get a 44px tap height', () => {
  const compact = trashCompactRules(sliceCss);
  assert.match(compact, /\.ok-trash-table \{ min-width: 0; \}/);
  assert.match(compact, /\.ok-trash-table \.acts \{[^}]*grid-row: 2;/);
  assert.match(compact, /\.ok-trash-table \.acts \.ok-text-link \{[^}]*min-height: 44px;/);
  assert.match(compact, /\.ok-trash-table td\.ok-phone-hide \{ display: none; \}/);
});
