import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const sourcePath = new URL('../assets/officekit-results.js', import.meta.url);
function load(extra = {}) {
  const context = { window: {}, navigator: {}, Blob, TextEncoder, Uint8Array, btoa, setTimeout, ...extra };
  vm.createContext(context);
  vm.runInContext(readFileSync(new URL('../assets/officekit-outcome.js', import.meta.url), 'utf8'), context);
  vm.runInContext(readFileSync(sourcePath, 'utf8'), context);
  return context.window;
}
test('full text copy awaits native clipboard and bounds UTF-8 before I/O', async () => {
  const calls = [];
  const window = { __TAURI__: { core: { invoke: async (...args) => { calls.push(args); } } } };
  const api = load({ window });
  assert.equal((await api.officekitCopyResultText('Hello\né')).state, 'copied');
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['result_copy_text', { text: 'Hello\né' }]]);
  await assert.rejects(api.officekitCopyResultText('é'.repeat(4 * 1024 * 1024 + 1)), /Too large/);
  assert.equal(calls.length, 1);
});
test('browser clipboard rejection remains an error; native rejection never silently falls back', async () => {
  let fallback = 0;
  const navigator = { clipboard: { writeText: async () => { fallback++; throw Error('secret'); } } };
  await assert.rejects(load({ navigator }).officekitCopyResultText('hello'), /Clipboard access failed/);
  const window = { __TAURI__: { core: { invoke: async () => { throw Error('private'); } } } };
  await assert.rejects(load({ window, navigator }).officekitCopyResultText('hello'), /Clipboard access failed/);
  assert.equal(fallback, 1);
});
test('native downloads preserve bytes and distinguish cancel from success', async () => {
  const calls = [];
  let response = null;
  const api = load({ window: { __TAURI__: { core: { invoke: async (...args) => { calls.push(args); return response; } } } } });
  assert.equal((await api.officekitDownloadResultBlob(new Blob(['é']), 'result.txt')).state, 'cancelled');
  assert.equal(calls[0][0], 'result_save');
  assert.equal(calls[0][1].base64Data, 'w6k=');
  response = { state: 'saved', name: 'result.txt' };
  assert.equal((await api.officekitDownloadResultBlob(new Blob(['a']), 'result.txt')).state, 'saved');
  await assert.rejects(api.officekitDownloadResultBlob(new Blob(['a']), '../secret'), /filename/);
});
test('snapshot serialization preserves all rows and meaningful inputs', () => {
  const api = load();
  const text = api.officekitResultSnapshotText({ title: 'Loan', inputs: { amount: 100 }, result: { total: 120, schedule: Array.from({ length: 70 }, (_, i) => ({ month: i + 1, payment: 2 })) } });
  assert.match(text, /Amount: 100/);
  assert.match(text, /Total: 120/);
  assert.match(text, /70\t2/);
});
test('table CSV guards formula strings while numeric negatives remain numeric', async () => {
  const api = load();
  const formats = api.officekitResultTableFormats([{ name: '=SUM(A1)', value: -2 }, { name: 'é', value: 5 }]);
  const csv = await formats.find(format => format.id === 'csv').serialize();
  assert.match(csv, /'=SUM\(A1\)/);
  assert.match(csv, /,-2/);
  assert.match(await formats.find(format => format.id === 'txt').serialize(), /é\t5/);
});

function fakeDocument() {
  const document = { activeElement: null };
  const make = tag => ({ tag, children: [], textContent: '', disabled: false, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    append(...children) { this.children.push(...children); children.forEach(child => { child.parent = this; }); },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); },
    querySelector(selector) { return this.children.find(child => `.${child.className}` === selector); },
    setAttribute() {}, addEventListener() {}, focus() { document.activeElement = this; }, click() { this.clicked = true; },
  });
  document.createElement = make;
  document.body = make('body');
  return document;
}
test('mount replaces its own action row and exposes awaited action feedback', async () => {
  const document = fakeDocument();
  let release;
  const api = load({ document, navigator: { clipboard: { writeText: () => new Promise(resolve => { release = resolve; }) } } });
  const container = document.createElement('section');
  api.officekitMountResultActions(container, { text: 'Old' });
  api.officekitMountResultActions(container, { text: 'Full result', download: async () => ({ state: 'cancelled' }) });
  assert.equal(container.children.length, 1);
  const [copy, download, status] = container.children[0].children;
  const pending = copy.onclick();
  assert.equal(copy.disabled, true);
  assert.equal(status.textContent, 'Copying…');
  release();
  await pending;
  assert.equal(status.textContent, 'Copied to clipboard.');
  await download.onclick();
  assert.equal(status.textContent, '');
});
test('browser reports started download, releases URL and does not claim saved', async () => {
  const document = fakeDocument();
  const revoked = [];
  const api = load({ document, URL: { createObjectURL: () => 'blob:1', revokeObjectURL: value => revoked.push(value) }, setTimeout: callback => callback() });
  assert.equal((await api.officekitDownloadResultBlob(new Blob(['whole report']), 'report.txt')).state, 'download-started');
  assert.deepEqual(revoked, ['blob:1']);
  assert.equal(document.body.children.length, 0);
});
test('oversized copy has a visible explanation and retains download', () => {
  const document = fakeDocument();
  const api = load({ document });
  const container = document.createElement('section');
  api.officekitMountResultActions(container, { text: 'a'.repeat(8 * 1024 * 1024 + 1), download: async () => ({ state: 'saved' }) });
  const [copy, download, status] = container.children[0].children;
  assert.equal(copy.disabled, true);
  assert.equal(download.disabled, false);
  assert.match(status.textContent, /Too large to copy/);
});
test('table exports keep an immutable full snapshot when source rows change', async () => {
  const api = load();
  const rows = [{ label: 'Original', value: 2 }];
  const formats = api.officekitResultTableFormats(rows);
  rows[0].label = 'Changed';
  rows.push({ label: 'New', value: 3 });
  assert.equal(await formats[0].serialize(), 'Label\tValue\nOriginal\t2');
});
test('snapshot includes declared units, table units and explicit assumptions', () => {
  const api = load({ window: { officekitResultFieldUnit: (_snapshot, key, section) => key === 'amount' ? 'USD' : key === 'payment' && section === 'table' ? 'USD' : null } });
  const text = api.officekitResultSnapshotText({ title: 'Estimate', inputs: { amount: 10 }, result: { schedule: [{ payment: 12 }] }, assumptions: ['No fees included.'] });
  assert.match(text, /Amount: 10 USD/);
  assert.match(text, /Payment \(USD\)/);
  assert.match(text, /Assumptions\nNo fees included\./);
});
test('CSV copy handles complete quoted records, unicode and trailing empty cells', () => {
  const api = load();
  assert.equal(api.officekitCsvToTsv('Name,Note,Amount,\r\n"é, Jane","line1\nline2 ""yes""",-2,\r\n'), 'Name\tNote\tAmount\t\né, Jane\tline1 line2 "yes"\t-2\t');
  assert.equal(api.officekitCsvToTsv('a,b\n"=SUM(A1)",2'), "a\tb\n'=SUM(A1)\t2");
});
test('CSV copy rejects malformed records rather than silently truncating', () => {
  const api = load();
  for (const csv of ['a,b\n"unterminated,2', 'a,b\n"quoted"junk,2', 'a,b\nun"quoted,2', 'a,b\n1,2,3']) assert.throws(() => api.officekitCsvToTsv(csv), /CSV/);
});
test('capabilities can release cleared result references', () => {
  const api = load();
  api.officekitRegisterResultCapability('password', { text: 'secret' });
  assert.equal(api.officekitUnregisterResultCapability('password'), true);
  assert.equal(api.officekitGetResultCapability('password'), undefined);
});
