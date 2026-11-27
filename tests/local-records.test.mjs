import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const source = html.match(/\/\* OFFICEKIT RECORD STORE START \*\/([\s\S]*?)\/\* OFFICEKIT RECORD STORE END \*\//)?.[1];
assert.ok(source, 'the testable versioned local-record store exists in the application');

function makeStore(initial = null, options = {}) {
  const values = new Map();
  if (initial !== null) values.set('officekit.records.v1', initial);
  let nextId = 0;
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => {
      if (options.failWrites) throw new Error('quota exceeded');
      values.set(key, value);
    },
  };
  const context = { globalThis: null, Date, JSON, Object, Array, Set, WeakSet, Number, String, RegExp };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  const store = context.createOfficeKitRecordStore(
    storage,
    options.idFactory || (() => `00000000-0000-4000-8000-${String(++nextId).padStart(12, '0')}`),
    () => '2026-10-06T12:00:00.000Z',
  );
  return { store, values };
}

test('favorites use stable tool IDs and toggle without duplicate records', () => {
  const { store } = makeStore();
  const added = store.toggleFavorite('image_converter');
  assert.equal(added.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(added.favorites)), ['image_converter']);
  const removed = store.toggleFavorite('image_converter');
  assert.equal(removed.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(removed.favorites)), []);
  assert.equal(store.toggleFavorite('../image_converter').code, 'invalid-tool-id');
});

test('recents stay bounded at 50 without evicting saved result snapshots', () => {
  const { store } = makeStore();
  const saved = store.saveResultSnapshot({
    toolId: 'calculator.loan-emi', title: 'April loan', inputs: { principal: 300000 }, result: { emi: 10100.25 },
  });
  assert.equal(saved.ok, true);
  for (let index = 0; index < 100; index += 1) store.recordRecent(`tool-${index}`);
  const state = store.read();
  assert.equal(state.ok, true);
  assert.equal(state.state.recents.length, 50);
  assert.equal(state.state.recents[0].toolId, 'tool-99');
  assert.equal(state.state.savedResults.length, 1);
  assert.equal(state.state.savedResults[0].id, saved.snapshot.id);
});

test('saved result snapshots are independent of later input/result mutation', () => {
  const { store } = makeStore();
  const inputs = { principal: 1000, options: { term: 12 } };
  const result = { total: 1100, schedule: [{ month: 1, balance: 1000 }] };
  const saved = store.saveResultSnapshot({ toolId: 'calculator.simple-interest', title: 'Saved', inputs, result });
  assert.equal(saved.ok, true);
  inputs.principal = 9;
  result.schedule[0].balance = 9;
  const reopened = store.read().state.savedResults[0];
  assert.equal(reopened.inputs.principal, 1000);
  assert.equal(reopened.result.schedule[0].balance, 1000);
});

test('meeting-note bookmarks preserve edited Markdown but never require transcript or audio persistence', () => {
  const { store, values } = makeStore();
  const markdown = '## Decisions\n- Ship Friday.\n\n## Full Transcript\nThe team agreed.\n\n<script>alert(1)</script>';
  const saved = store.saveResultSnapshot({
    kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Meeting notes', inputs: {}, result: { markdown },
  });
  assert.equal(saved.ok, true);
  assert.equal(saved.snapshot.kind, 'meeting-notes');
  assert.deepEqual(JSON.parse(JSON.stringify(saved.snapshot.inputs)), {});
  assert.deepEqual(JSON.parse(JSON.stringify(saved.snapshot.result)), { markdown });
  assert.equal(store.read().state.savedResults[0].result.markdown, markdown);
  const storedSnapshot = JSON.parse(values.get('officekit.records.v1')).savedResults[0];
  assert.deepEqual(Object.keys(storedSnapshot).sort(), ['id', 'inputs', 'kind', 'result', 'savedAt', 'title', 'toolId'].sort());
  assert.deepEqual(storedSnapshot.inputs, {});
  assert.deepEqual(Object.keys(storedSnapshot.result), ['markdown']);
  assert.match(storedSnapshot.result.markdown, /## Full Transcript/);

  assert.equal(store.saveResultSnapshot({ kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Empty', inputs: {}, result: { markdown: '  ' } }).code, 'invalid-snapshot');
  assert.equal(store.saveResultSnapshot({ kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Too large', inputs: {}, result: { markdown: 'x'.repeat(262145) } }).code, 'snapshot-too-large');
  assert.equal(store.saveResultSnapshot({ kind: 'unknown', toolId: 'dictate_stt', title: 'Unknown', inputs: {}, result: { markdown } }).code, 'invalid-snapshot');
  assert.equal(store.read().state.savedResults.length, 1);
});

test('meeting-note bookmark accepts the declared maximum and returns a clean error one character over', () => {
  const { store, values } = makeStore();
  const max = store.saveResultSnapshot({
    kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Maximum notes', inputs: {}, result: { markdown: 'x'.repeat(262144) },
  });
  assert.equal(max.ok, true);
  const before = values.get('officekit.records.v1');
  const over = store.saveResultSnapshot({
    kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Too long', inputs: {}, result: { markdown: 'x'.repeat(262145) },
  });
  assert.equal(over.code, 'snapshot-too-large');
  assert.equal(values.get('officekit.records.v1'), before);
  assert.equal(store.read().state.savedResults[0].result.markdown.length, 262144);
});

test('meeting-note save reports unavailable storage without claiming success or discarding editor content', () => {
  const { store, values } = makeStore(null, { failWrites: true });
  const before = values.get('officekit.records.v1') ?? null;
  const result = store.saveResultSnapshot({
    kind: 'meeting-notes', toolId: 'dictate_stt', title: 'Storage failure', inputs: {}, result: { markdown: 'Notes remain in the editor.' },
  });
  assert.equal(result.code, 'storage-unavailable');
  assert.equal(values.get('officekit.records.v1') ?? null, before);
});

test('saved result snapshots retain a valid calculation time while accepting older stored records', () => {
  const { store, values } = makeStore();
  const saved = store.saveResultSnapshot({
    toolId: 'calculator.loan-emi', title: 'Timed result', createdAt: '2026-10-06T11:59:00.000Z',
    inputs: { principal: 1000 }, result: { total: 1100 },
  });
  assert.equal(saved.ok, true);
  assert.equal(saved.snapshot.createdAt, '2026-10-06T11:59:00.000Z');
  assert.equal(store.read().state.savedResults[0].createdAt, saved.snapshot.createdAt);

  const older = JSON.parse(values.get('officekit.records.v1'));
  delete older.savedResults[0].createdAt;
  values.set('officekit.records.v1', JSON.stringify(older));
  assert.equal(store.read().ok, true);
});

test('invalid calculation times are rejected without changing the record store', () => {
  const { store, values } = makeStore();
  const before = values.get('officekit.records.v1') ?? null;
  const result = store.saveResultSnapshot({
    toolId: 'calculator.x', title: 'Bad time', createdAt: 'not-a-time', inputs: {}, result: { total: 1 },
  });
  assert.equal(result.code, 'invalid-id-or-time');
  assert.equal(values.get('officekit.records.v1') ?? null, before);
});

test('sensitive fields and oversized/non-JSON snapshots are rejected without persistence', () => {
  const { store } = makeStore();
  for (const inputs of [
    { password: 'do not save' },
    { nested: { access_token: 'do not save' } },
    { jwt: 'do not save' },
  ]) {
    assert.equal(store.saveResultSnapshot({ toolId: 'dev.jwt', title: 'Sensitive', inputs, result: {} }).code, 'sensitive-input');
  }
  const circular = {};
  circular.self = circular;
  assert.equal(store.saveResultSnapshot({ toolId: 'calculator.x', title: 'bad', inputs: {}, result: circular }).code, 'invalid-snapshot');
  assert.equal(store.saveResultSnapshot({ toolId: 'calculator.x', title: 'large', inputs: {}, result: { text: 'x'.repeat(140_000) } }).code, 'snapshot-too-large');
  assert.equal(store.read().state.savedResults.length, 0);
});

test('corrupt and unknown-version state fails closed instead of being overwritten', () => {
  for (const raw of ['{broken', JSON.stringify({ version: 99, favorites: [], recents: [], savedResults: [] })]) {
    const { store, values } = makeStore(raw);
    const result = store.recordRecent('image_converter');
    assert.equal(result.ok, false);
    assert.match(result.code, /corrupt|unsupported-version/);
    assert.equal(values.get('officekit.records.v1'), raw);
  }
});

test('storage quota failures preserve previous records and return a recoverable error', () => {
  const { store, values } = makeStore(null, { failWrites: true });
  const result = store.recordRecent('image_converter');
  assert.equal(result.ok, false);
  assert.equal(result.code, 'storage-unavailable');
  assert.equal(values.has('officekit.records.v1'), false);
});

test('aggregate storage cap refuses a new bookmark without evicting existing bookmarks', () => {
  const { store, values } = makeStore();
  let last;
  let rejected = null;
  for (let index = 0; index < 30; index += 1) {
    last = store.saveResultSnapshot({
      toolId: `tool-${index}`, title: `Snapshot ${index}`, inputs: {}, result: { text: 'x'.repeat(100_000) },
    });
    if (!last.ok) {
      rejected = last;
      break;
    }
  }
  assert.equal(rejected?.code, 'storage-full');
  const before = values.get('officekit.records.v1');
  assert.equal(store.read().state.savedResults.length, 19);
  assert.equal(store.saveResultSnapshot({
    toolId: 'still-full', title: 'Still full', inputs: {}, result: { text: 'y'.repeat(100_000) },
  }).code, 'storage-full');
  assert.equal(values.get('officekit.records.v1'), before);
});

test('an explicitly deleted bookmark is removed while other saved results survive', () => {
  const { store } = makeStore();
  const first = store.saveResultSnapshot({ toolId: 'calc.a', title: 'First', inputs: {}, result: { value: 1 } });
  const second = store.saveResultSnapshot({ toolId: 'calc.b', title: 'Second', inputs: {}, result: { value: 2 } });
  assert.equal(store.deleteSavedResult(first.snapshot.id).ok, true);
  assert.deepEqual(store.read().state.savedResults.map(item => item.id), [second.snapshot.id]);
});

test('duplicate recent IDs are rejected without corrupting the existing list', () => {
  const fixed = () => '00000000-0000-4000-8000-000000000001';
  const { store } = makeStore(null, { idFactory: fixed });
  assert.equal(store.recordRecent('tool-one').ok, true);
  assert.equal(store.recordRecent('tool-two').code, 'id-collision');
  assert.deepEqual(JSON.parse(JSON.stringify(store.read().state.recents.map(item => item.toolId))), ['tool-one']);
});
