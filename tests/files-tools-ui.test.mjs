import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';
import { loadToolCatalog } from '../scripts/tool-catalog.mjs';

// QA-2: pin a zone where local time and UTC differ, so a Date.UTC mutant in the file-age bounds goes red on any runner.
process.env.TZ = 'America/Los_Angeles';
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const filesSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-files.js'), 'utf8');
const sliceSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-files.js'), 'utf8');
const formattersSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-formatters.js'), 'utf8');
const FILE_IDS = ['zip_create', 'zip_extract', 'archive_inspector', 'file_info', 'file_compare', 'file_age_finder', 'empty_file_finder', 'empty_folder_finder', 'symlink_inspector', 'trash_restore'];

// Minimal DOM: enough for the Files screens to build and read their own text. innerHTML writes are counted.
let htmlWrites = 0;
// Registry of the UI under test: an element that takes an id is reachable through getElementById, as in the DOM.
let registry = null;
class FakeElement {
  constructor(id = '', tagName = '') {
    this.tagName = String(tagName).toUpperCase(); this._id = ''; if (id) this.id = id;
    this.children = []; this.text = ''; this.hidden = false; this.disabled = false; this.checked = false;
    this.value = ''; this.type = ''; this.className = ''; this.title = ''; this.dataset = {}; this.style = {};
    this.attributes = {}; this.events = []; this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      toggle: (name, on) => { if (on ?? !this.classes.has(name)) this.classes.add(name); else this.classes.delete(name); },
      contains: name => this.classes.has(name),
    };
  }
  get className() { return this._className; }
  set className(value) { this._className = String(value); this.classes = new Set(this._className.split(/\s+/).filter(Boolean)); }
  get id() { return this._id; }
  set id(value) { this._id = value; if (registry && value) registry.set(value, this); }
  get textContent() { return this.children.length ? this.children.map(child => child.textContent).join('') : this.text; }
  set textContent(value) { this.children = []; this.text = String(value); }
  set innerHTML(value) { htmlWrites += 1; this.children = []; this.text = String(value); }
  get parentElement() { return this.parent ?? null; }
  // A select takes its first option's value, as a browser does.
  // Appending a node moves it, as the browser does: it leaves its previous parent.
  append(...nodes) {
    for (const node of nodes) {
      if (typeof node !== 'object') continue;
      if (node.parent) node.parent.children = node.parent.children.filter(child => child !== node);
      node.parent = this;
    }
    this.children.push(...nodes);
    if (this.tagName === 'SELECT' && !this.value && nodes[0]) this.value = nodes[0].value ?? '';
  }
  showModal() { this.open = true; }
  close() { this.open = false; }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.text = ''; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type) { this.events.push(type); }
  dispatchEvent(event) { this.events.push(event.type); return true; }
  focus() {}
  remove() {}
  // Descendant lookup for a tag, #id or .class selector, as the duplicate renderer uses them.
  querySelector(selector) { let found = null; walk(this, node => { if (!found && node !== this && matchesSelector(node, selector)) found = node; }); return found; }
  querySelectorAll(selector) { const found = []; walk(this, node => { if (node !== this && matchesSelector(node, selector)) found.push(node); }); return found; }
}
function matchesSelector(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classes.has(selector.slice(1));
  return node.tagName === selector.toUpperCase();
}

// Text nodes are plain strings in this fake DOM (a browser keeps them as Text nodes); they have no children.
function walk(node, visit) { if (typeof node === 'string') return; visit(node); for (const child of node.children) walk(child, visit); }
function findNode(root, predicate) {
  let found = null;
  walk(root, node => { if (!found && predicate(node)) found = node; });
  return found;
}
// Values built inside the vm context carry that realm's prototypes; compare them as plain data.
const plain = value => JSON.parse(JSON.stringify(value));
function findLeaf(root, text) {
  let found = null;
  walk(root, node => { if (!found && node.children.length === 0 && node.text === text) found = node; });
  return found;
}

// Stands in for the shared result module (officekit-results.js mountActions): Copy report is outline and
// Download is primary with the officekit-result-download class; the duplicate dock restyles Download by that class.
function mountResultActionsStub(container, doc, options = {}, sink = {}) {
  sink.mounted = options;
  const row = doc.createElement('div');
  row.className = 'officekit-result-actions';
  const copy = doc.createElement('button'); copy.className = 'btn btn-outline'; copy.textContent = 'Copy report';
  const download = doc.createElement('button'); download.className = 'btn btn-primary officekit-result-download'; download.textContent = 'Download';
  row.append(copy, download);
  container.append(row);
}

function loadFilesUi(responder = null) {
  const elements = new Map();
  registry = elements;
  const registrations = [], requests = [], mountSink = {};
  const context = {
    console, Date, Math, Number, Promise, Error, JSON, Object, Array, String, Map, Set, setTimeout,
    document: {
      createElement: tag => new FakeElement('', tag),
      getElementById: id => { if (!elements.has(id)) elements.set(id, new FakeElement(id)); return elements.get(id); },
      body: new FakeElement('', 'body'),
    },
    Event: class { constructor(type) { this.type = type; } },
    // Defined in index.html: the titles the tools without an inspect entry need.
    WORKSPACE_TOOL_COPY: {
      file_type: { title: 'File type detector', description: 'Identify file formats from contents and compare them with extensions.' },
      rename: { title: 'Batch rename' }, duplicates: { title: 'Duplicate finder' }, storage: { title: 'Storage analyser' },
      folder_compare: { title: 'Folder compare' }, similar_images: { title: 'Similar images' }, file_hash: { title: 'File checksum generator' },
      split_join: { title: 'Split and join files' },
    },
    // Desktop bridge: a split or join asks for an output grant; the harness grants one.
    tauriInvoke: () => async () => ({ id: 'grant-1', kind: 'file' }),
    officekitMountResultActions: (container, options) => mountResultActionsStub(container, context.document, options, mountSink),
    officekitCopyResultText: async text => { context.__officekitCopiedText = text; return { state: 'copied' }; },
    officekitDownloadResultBlob: async (blob, suggestedName) => { context.__officekitDownloadedFile = { text: await blob.text(), suggestedName }; },
  };
  context.window = context;
  context.OfficeKitExtensions = { register: config => registrations.push(config) };
  vm.createContext(context);
  vm.runInContext(formattersSource, context);
  vm.runInContext(filesSource, context);
  // Overrides the network boundary after load: the files script declares officekitDirectFetch itself.
  context.officekitDirectFetch = async (requestPath, options = {}) => {
    requests.push({ path: requestPath, method: options.method ?? 'GET', body: options.body ? JSON.parse(options.body) : null });
    if (!responder) throw Error('unexpected request');
    return responder(requestPath);
  };
  vm.runInContext(sliceSource, context);
  context.officekitDirectFilesReady = true;
  const state = () => vm.runInContext('officekitDirectFilesState', context);
  const element = id => context.document.getElementById(id);
  const mountedActions = () => mountSink.mounted;
  return { context, registrations, requests, elements, state, element, mountedActions, filesRegistration: registrations[0] };
}

function scanResponder({ report = {}, jobState = 'ready', error, resultRef = 'result-1' } = {}) {
  return requestPath => {
    if (requestPath === '/api/file-jobs') return { json: async () => ({ id: 'job-1' }) };
    if (requestPath === '/api/file-jobs/job-1') return { json: async () => ({ state: jobState, progress: 1, total: 1, phase: jobState, error, resultRef }) };
    if (requestPath.startsWith('/api/file-jobs/job-1/results')) return { json: async () => report, blob: async () => ({ size: 2, text: async () => JSON.stringify(report) }) };
    throw Error(`unexpected ${requestPath}`);
  };
}

const fileA = { id: 'sel-1', displayNames: ['a.txt'], mode: 'files', access: 'read' };
const fileB = { id: 'sel-2', displayNames: ['b.txt'], mode: 'files', access: 'read' };
const folder = { id: 'sel-1', displayNames: ['Projects'], mode: 'folder', access: 'read' };

test('Files destinations route each new ID to the Files workspace', () => {
  const { filesRegistration } = loadFilesUi();
  const catalogueIds = loadToolCatalog().tools.map(tool => tool.id);
  assert.equal(filesRegistration.slice, 'files');
  assert.deepEqual(Object.keys(plain(filesRegistration.destinations)).sort(), [...FILE_IDS].sort());
  for (const id of FILE_IDS) assert.ok(catalogueIds.includes(id), `${id} is in the catalogue`);
  assert.deepEqual(plain(filesRegistration.destinations.zip_create), { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-create' });
  // UX-4 (owner: add the two search IDs): both open Archive tools in browse and extract mode.
  assert.deepEqual(plain(filesRegistration.destinations.zip_extract), { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-extract' });
  assert.deepEqual(plain(filesRegistration.destinations.archive_inspector), { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-inspect' });
  for (const id of FILE_IDS.filter(id => !id.startsWith('zip_') && id !== 'archive_inspector')) assert.deepEqual(plain(filesRegistration.destinations[id]), { tab: 'workspace', sliceView: id });
  assert.match(sliceSource, /^window\.OfficeKitExtensions\.register\(\{/m);
});

test('openView does nothing before the workspace is bound, then selects Create ZIP mode and opens scans', () => {
  const ui = loadFilesUi();
  ui.context.officekitDirectFilesReady = false;
  ui.filesRegistration.openView('archive-create');
  assert.equal(ui.elements.has('direct-archive-mode'), false, 'no DOM work before binding');

  ui.context.officekitDirectFilesReady = true;
  ui.context.officekitOpenDirectFileTool('archive');
  const mode = ui.element('direct-archive-mode');
  ui.filesRegistration.openView('archive-create');
  assert.equal(mode.value, 'archive-create');
  assert.deepEqual(mode.events, ['change']);

  ui.filesRegistration.openView('file_compare');
  assert.equal(ui.state().action, 'file_compare');
  assert.equal(ui.element('direct-file-title').textContent, 'Compare two files');
  assert.equal(ui.element('direct-file-run').textContent, 'Compare two files');
  assert.equal(ui.element('direct-choose-folder').hidden, true, 'compare takes files, not folders');
  assert.equal(ui.element('direct-folder-b').textContent, 'Choose file B…');
});

test('choosers say Change once something is chosen, and the empty-folder finder keeps the files link (UX-7)', () => {
  const ui = loadFilesUi();
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('empty_folder_finder');
  assert.equal(ui.element('direct-choose-files').hidden, false, 'the empty-folder finder shows the files link');
  assert.equal(ui.element('direct-choose-files').textContent, 'Choose files…');
  ui.state().selections = [folder];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-choose-files').textContent, 'Change files…');
  assert.equal(ui.element('direct-choose-folder').textContent, 'Change folder…');
  ui.context.officekitOpenDirectFileTool('file_compare');
  ui.state().selections = [fileA, fileB];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-choose-files').textContent, 'Change file A…');
  assert.equal(ui.element('direct-folder-b').textContent, 'Change file B…');
});

test('inspect tables leave the row-action column header empty (UX-7)', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('empty_folder_finder');
  ui.state().selections = [folder];
  ui.context.officekitRenderInspectReport({ folders: [{ id: 'folder-1', name: 'free', state: 'empty' }], scanned_folders: 1, skipped_links: 0, skipped_other_volume: 0, skipped_bundles: 0, excluded_protected: 0, denied_folders: 0, complete: true }, 'job-1');
  const headers = [];
  walk(ui.element('direct-file-results'), node => { if (node.tagName === 'TH') headers.push(node.textContent); });
  assert.deepEqual(headers, ['Folder', 'State', '']);
});

test('scan requests carry the kind, the selections and validated options', async () => {
  const cases = [
    { action: 'file_info', selections: [folder], prepare: ui => { ui.element('direct-include-subfolders').checked = true; }, kind: 'file-info', selectionIds: ['sel-1'], options: { includeSubfolders: true } },
    { action: 'file_compare', selections: [fileA, fileB], kind: 'compare-files', selectionIds: ['sel-1', 'sel-2'], options: {} },
    {
      action: 'file_age_finder', selections: [folder],
      prepare: ui => { ui.element('direct-include-subfolders').checked = true; ui.element('direct-age-field').value = 'created'; ui.element('direct-age-from').value = '2025-01-01'; ui.element('direct-age-to').value = '2025-12-31'; },
      kind: 'file-age', selectionIds: ['sel-1'],
      // Literal epoch seconds: 2025-01-01 00:00 and 2025-12-31 23:59:59 in America/Los_Angeles (UTC-8).
      options: { dateField: 'created', notBefore: 1735718400, notAfter: 1767254399, includeSubfolders: true },
    },
    { action: 'empty_file_finder', selections: [folder], kind: 'empty-files', selectionIds: ['sel-1'], options: { includeSubfolders: false } },
    { action: 'empty_folder_finder', selections: [folder], kind: 'empty-folders', selectionIds: ['sel-1'], options: {} },
    { action: 'symlink_inspector', selections: [folder], kind: 'symlinks', selectionIds: ['sel-1'], options: { includeSubfolders: true } },
  ];
  for (const scan of cases) {
    const ui = loadFilesUi(scanResponder({ report: scanReport(scan.action) }));
    ui.filesRegistration.openView(scan.action);
    ui.state().selections = scan.selections;
    scan.prepare?.(ui);
    await ui.context.officekitRunDirectFiles();
    const post = ui.requests.find(request => request.method === 'POST');
    assert.deepEqual(post.body, { kind: scan.kind, selectionIds: scan.selectionIds, options: scan.options }, scan.action);
  }
});

test('file age needs at least one date and an ordered range, and sends nothing when invalid', async () => {
  const ui = loadFilesUi(scanResponder());
  ui.filesRegistration.openView('file_age_finder');
  ui.state().selections = [folder];
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-status').textContent, 'Enter a From date, a To date, or both.');
  ui.element('direct-age-from').value = '2025-06-01';
  ui.element('direct-age-to').value = '2025-01-01';
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-status').textContent, 'The From date must be on or before the To date.');
  assert.equal(ui.requests.length, 0, 'no job is created for an invalid range');
});

test('compare runs only with two selections and names them File A and File B', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_compare');
  ui.state().selections = [fileA];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-file-run').disabled, true);
  ui.state().selections = [fileA, fileB];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-file-run').disabled, false);
  assert.equal(ui.element('direct-selection-summary').textContent, 'File A: a.txt · File B: b.txt');
});

test('a failed, denied or cancelled job reports its state without a result', async () => {
  const denied = loadFilesUi(scanResponder({ jobState: 'failed', error: 'Permission denied. OfficeKit needs access to this folder.', resultRef: null }));
  denied.filesRegistration.openView('file_info');
  denied.state().selections = [folder];
  await denied.context.officekitRunDirectFiles();
  assert.equal(denied.element('direct-file-status').textContent, 'Permission denied. OfficeKit needs access to this folder.');
  assert.equal(denied.element('direct-file-results').hidden, true);

  const cancelled = loadFilesUi(scanResponder({ jobState: 'cancelled' }));
  cancelled.filesRegistration.openView('empty_file_finder');
  cancelled.state().selections = [folder];
  await cancelled.context.officekitRunDirectFiles();
  assert.equal(cancelled.element('direct-file-status').textContent, 'Operation cancelled.');
});

test('dynamic file names are written as text, never as HTML', async () => {
  const hostile = '<img src=x onerror=alert(1)>';
  const ui = loadFilesUi(scanResponder({ report: { ...scanReport('file_info'), files: [{ id: 'f1', name: hostile, size_bytes: 2048, modified_at: '2025-03-01T10:00:00Z', created_at: null, mode: 'rw-r--r--', hidden: false, hard_links: 1 }] } }));
  ui.filesRegistration.openView('file_info');
  ui.state().selections = [folder];
  const before = htmlWrites;
  await ui.context.officekitRunDirectFiles();
  const results = ui.element('direct-file-results');
  assert.ok(findLeaf(results, hostile), 'the hostile name is shown literally');
  assert.equal(findLeaf(results, 'Unavailable') !== null, true, 'missing creation dates read as unavailable');
  assert.equal(htmlWrites - before, 0);
});

test('compare results describe each state and never claim identity on a difference', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_compare');
  ui.state().selections = [fileA, fileB];
  const renderer = ui.context.officekitRenderInspectReport;
  const results = ui.element('direct-file-results');

  renderer(compareReport({ equal: true, first_difference_offset: null, hunks: [] }), 'job-1');
  assert.ok(findLeaf(results, 'Files are identical.'));

  renderer(compareReport({ same_file: true, equal: true, first_difference_offset: null, hunks: [] }), 'job-1');
  assert.ok(findLeaf(results, 'Same file selected twice.'));

  renderer(compareReport({ first_difference_offset: 42, hunks: [{ a_start: 1, a_lines: 1, b_start: 1, b_lines: 1, lines: [{ op: '-', text: 'old' }, { op: '+', text: '<b>new</b>' }] }] }), 'job-1');
  assert.ok(findLeaf(results, 'Files differ · first difference at byte 42'));
  assert.ok(findLeaf(results, '+ <b>new</b>'), 'diff lines keep their text literal');
});

test('file info and empty-file results disable Show in Finder outside the desktop app', () => {
  const ui = loadFilesUi(scanResponder());
  ui.filesRegistration.openView('empty_file_finder');
  ui.state().selections = [folder];
  ui.context.officekitRenderInspectReport({ files: [{ id: 'f1', name: 'empty.txt', modified_at: '2025-03-01T10:00:00Z' }], scanned: 4, skipped_links: 0, denied_folders: 0, complete: true }, 'job-1');
  const button = findNode(ui.element('direct-file-results'), node => node.dataset.actionIcon === 'folder-open');
  assert.ok(button);
  assert.equal(button.textContent, 'Show', 'row action uses the approved short label');
  assert.equal(button.classes.has('row-act'), true, 'row actions are marked so the button count skips them');
  assert.equal(button.disabled, true);
});

test('file info names skipped reasons in plain words and says how many skipped items are not listed', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_info');
  ui.state().selections = [folder];
  ui.context.officekitRenderInspectReport({ ...scanReport('file_info'), skipped: [{ name: 'alias', reason: 'link' }, { name: 'pipe', reason: 'special' }], skipped_links: 1, skipped_truncated: 3 }, 'job-1');
  const results = ui.element('direct-file-results');
  assert.ok(findLeaf(results, 'Symbolic link, not followed'), 'link reason is spelled out');
  assert.ok(findLeaf(results, 'Special file'), 'special reason is spelled out');
  assert.equal(findLeaf(results, 'link'), null, 'no raw reason code is shown');
  assert.ok(findLeaf(results, '3 more skipped items are not listed. The counts above are complete.'), 'truncation is stated');
});

test('File Info summary uses singular and plural file counts correctly', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_info');
  ui.state().selections = [fileA];
  const renderer = ui.context.officekitRenderInspectReport;
  const one = { ...scanReport('file_info'), total_files: 1, total_bytes: 32, files: [{ id: 'one', name: 'notes.txt', size_bytes: 32, modified_at: null, created_at: null, mode: 'rw-------', hidden: false, hard_links: 1 }] };
  renderer(one, 'job-1');
  const results = ui.element('direct-file-results');
  assert.ok(findLeaf(results, '1 file · 32 bytes'));
  assert.equal(findLeaf(results, '1 files · 32 bytes'), null);

  const two = { ...one, total_files: 2, total_bytes: 64, files: [...one.files, { ...one.files[0], id: 'two', name: 'second.txt' }] };
  renderer(two, 'job-1');
  assert.ok(findLeaf(results, '2 files · 64 bytes'));
});

test('Empty File Finder uses singular and plural summary labels', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('empty_file_finder');
  ui.state().selections = [folder];
  const renderer = ui.context.officekitRenderInspectReport;
  const results = ui.element('direct-file-results');
  renderer({ ...scanReport('empty_file_finder'), scanned: 1, files: [{ id: 'one', name: 'zero-byte.txt', modified_at: null }] }, 'job-1');
  assert.ok(findLeaf(results, '1 empty file among 1 scanned'));
  assert.equal(findLeaf(results, '1 empty files among 1 scanned'), null);

  renderer({ ...scanReport('empty_file_finder'), scanned: 2, files: [
    { id: 'one', name: 'zero-byte.txt', modified_at: null },
    { id: 'two', name: 'second-zero-byte.txt', modified_at: null },
  ] }, 'job-1');
  assert.ok(findLeaf(results, '2 empty files among 2 scanned'));
});

test('compare shows one SHA-256 match row instead of two hash prefixes', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_compare');
  ui.state().selections = [fileA, fileB];
  const results = ui.element('direct-file-results');
  ui.context.officekitRenderInspectReport(compareReport({ sha256_a: 'a'.repeat(64), sha256_b: 'b'.repeat(64) }), 'job-1');
  assert.equal(findLeaf(results, 'aaaaaaaaaaaaaaaa…'), null, 'no truncated hash is shown');
  assert.ok(findLeaf(results, 'Differ'), 'a differing hash reads as Differ');
  ui.context.officekitRenderInspectReport(compareReport({ equal: true, first_difference_offset: null, hunks: [], sha256_a: 'c'.repeat(64), sha256_b: 'c'.repeat(64) }), 'job-1');
  assert.ok(findLeaf(results, 'Match'), 'an equal hash reads as Match');
});

test('compare diff lines use design-system wash tokens and the files asset holds no literal colours', () => {
  const ui = loadFilesUi();
  ui.filesRegistration.openView('file_compare');
  ui.state().selections = [fileA, fileB];
  const results = ui.element('direct-file-results');
  ui.context.officekitRenderInspectReport(compareReport({ hunks: [{ a_start: 1, a_lines: 1, b_start: 1, b_lines: 1, lines: [{ op: '-', text: 'old' }, { op: '+', text: 'new' }] }] }), 'job-1');
  assert.ok(findNode(results, node => node.classes.has('ok-diff-line-remove')), 'removed lines carry the error wash class');
  assert.ok(findNode(results, node => node.classes.has('ok-diff-line-add')), 'added lines carry the success wash class');
  assert.doesNotMatch(filesSource, /rgba\(|#[0-9a-fA-F]{3,8}\b/, 'colours come from design tokens');
});

// Counted buttons on a Files screen: visible BUTTON elements, excluding in-text links, list-row actions and segmented toggles (AGENTS.md Button Limit).
function countedButtons(root) {
  const counted = [];
  const visit = (node, hidden) => {
    if (typeof node === 'string') return;
    const isHidden = hidden || node.hidden === true;
    if (!isHidden && node.tagName === 'BUTTON' && !node.classes.has('ok-text-link') && !node.classes.has('row-act') && node.getAttribute('aria-pressed') === null) counted.push(node);
    node.children.forEach(child => visit(child, isHidden));
  };
  visit(root, false);
  return counted;
}

// Twelve duplicate groups over two pages (the mock's frame 1 fixture), each with two copies, the second one selectable.
function duplicateReport() {
  const groups = Array.from({ length: 12 }, (_, index) => ({
    hash: `hash-${index}`, size_bytes: 1000 + index,
    entries: [
      { id: `keep-${index}`, name: `Group ${index}/keep.jpg`, display_name: 'keep.jpg', full_path: `/Downloads/g${index}/keep.jpg`, modified_at: '2026-03-03T09:14:00Z', size: 1000 + index },
      { id: `copy-${index}`, name: `Group ${index}/copy.jpg`, display_name: 'copy.jpg', full_path: `/Downloads/g${index}/copy.jpg`, modified_at: '2026-03-09T16:02:00Z', size: 1000 + index },
    ],
  }));
  return { groups, match_kind: 'files', files_scanned: 24, complete: true, trash_supported: true };
}

// Each Files tool at the build's real screen states. `after` is the approved set of counted buttons once a result is shown.
const buttonScreens = [
  { action: 'file_type', selections: [fileA], report: scanReport('file_type'), after: ['Copy report', 'Download'] },
  { action: 'file_info', selections: [folder], report: scanReport('file_info'), after: ['Copy report', 'Download'] },
  { action: 'file_compare', selections: [fileA, fileB], report: scanReport('file_compare'), after: ['Copy report', 'Download'] },
  { action: 'file_age_finder', selections: [folder], report: scanReport('file_age_finder'), after: ['Copy report', 'Download'] },
  { action: 'empty_file_finder', selections: [folder], report: scanReport('empty_file_finder'), after: ['Copy report', 'Download'] },
  { action: 'empty_folder_finder', selections: [folder], report: scanReport('empty_folder_finder'), after: ['Copy report', 'Download'] },
  { action: 'symlink_inspector', selections: [folder], report: symlinkReport(), before: ['Inspect links'], after: ['Copy report', 'Download'] },
  // Approved v3 re-mock: Run hides after a result (3 to 2).
  { action: 'file_hash', selections: [fileA], report: { files: [{ name: 'a.txt', algorithm: 'sha256', digest: 'a'.repeat(64) }], complete: true }, after: ['Copy report', 'Download'] },
  { action: 'folder_compare', selections: [folder, { id: 'sel-2', displayNames: ['Other'], mode: 'folder', access: 'read' }], report: { only_a: [], only_b: [], changed: [], same: [], complete: true }, after: ['Copy report', 'Download'] },
  { action: 'similar_images', selections: [folder], report: { pairs: [{ a: 'x.jpg', b: 'y.jpg', distance: 2 }], complete: true }, after: ['Copy report', 'Download'] },
  // Batch rename is a preview, so Run stays as Apply rename (not a read-only result).
  { action: 'rename', selections: [folder], report: { previewId: 'preview-1', items: [{ from: 'a.txt', to: 'b.txt' }], complete: true }, after: ['Apply rename', 'Copy report', 'Download'] },
  // Split writes files, so Run stays as the primary.
  { action: 'split_join', selections: [fileA], report: { parts: [{ name: 'part-1' }], complete: true }, after: ['Split and join files', 'Copy report', 'Download'] },
  // Approved v3 re-mock, frame 1: Run hides, and the dock is Copy report, Download and Move selected to Trash.
  { action: 'duplicates', selections: [{ ...fileA, access: 'read-write' }], report: duplicateReport(), after: ['Copy report', 'Download', 'Move selected to Trash'] },
];

for (const screen of buttonScreens) {
  test(`${screen.action}: at most three counted buttons before, with and after a selection, a result and a run`, async t => {
    const ui = loadFilesUi(scanResponder({ report: screen.report }));
    ui.context.officekitBindDirectFiles();
    ui.context.officekitOpenDirectFileTool(screen.action);
    const workspace = ui.element('tab-workspace');
    const counted = () => countedButtons(workspace);
    const names = () => counted().map(button => button.textContent);
    t.diagnostic(`${screen.action} before a selection: ${counted().length} ${JSON.stringify(names())}`);
    assert.ok(counted().length <= 3, `before a selection: ${counted().length}`);
    if (screen.before) assert.deepEqual(names(), screen.before, 'the approved button before a selection');
    ui.state().selections = screen.selections;
    ui.context.officekitDirectUpdateSelection();
    t.diagnostic(`${screen.action} with a selection: ${counted().length}`);
    assert.ok(counted().length <= 3, `with a selection: ${counted().length}`);
    if (screen.before) assert.deepEqual(names(), screen.before, 'the approved button with a selection');
    ui.state().busy = true;
    ui.context.officekitDirectUpdateSelection();
    assert.ok(counted().length <= 3, `during a run: ${counted().length}`);
    assert.equal(ui.element('direct-file-cancel').hidden, false, 'Cancel joins the busy primary');
    ui.state().busy = false;
    if (screen.action === 'file_age_finder') { ui.element('direct-age-from').value = '2025-01-01'; ui.element('direct-age-to').value = '2025-12-31'; }
    await ui.context.officekitRunDirectFiles();
    t.diagnostic(`${screen.action} after a result: ${counted().length} ${JSON.stringify(names())} status=${ui.element('direct-file-status').textContent}`);
    assert.deepEqual(names().sort(), [...screen.after].sort(), 'after a result');
    assert.ok(counted().length <= 3, `after a result: ${counted().length}`);
  });
}

test('archive inspector: Previous 100 and Next 100 are links, so the middle page counts 1 (approved v3 frame 3)', async t => {
  const page = { format: 'zip', entries: [{ id: 'e-1', name: 'reports/q1.csv', kind: 'file', size_bytes: 18204, extractable: true, encrypted: false }], offset: 100, hasMore: true, total: 348 };
  const ui = loadFilesUi(requestPath => {
    if (requestPath.startsWith('/api/file-selections/sel-1/archive-entries')) return { json: async () => page };
    throw Error(`unexpected ${requestPath}`);
  });
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('archive');
  ui.state().selections = [{ ...fileA, displayNames: ['backup-2026.zip'] }];
  const workspace = ui.element('tab-workspace');
  const names = () => countedButtons(workspace).map(button => button.textContent);
  await ui.context.officekitLoadArchiveEntries('sel-1', 100);
  t.diagnostic(`archive middle page: ${countedButtons(workspace).length} ${JSON.stringify(names())}`);
  assert.deepEqual(names(), ['Extract selected or all'], 'Run is the one counted button');
  assert.equal(countedButtons(workspace).length, 1);
});

test('archive create: Run stays as the primary after a ZIP is written, with Copy report and Download (3 counted)', async t => {
  const ui = loadFilesUi(scanResponder({ report: { output: 'backup.zip', complete: true } }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('archive');
  ui.element('direct-archive-mode').value = 'archive-create';
  ui.element('direct-archive-mode').onchange();
  ui.state().selections = [fileA, fileB];
  const workspace = ui.element('tab-workspace');
  const names = () => countedButtons(workspace).map(button => button.textContent);
  await ui.context.officekitRunDirectFiles();
  t.diagnostic(`archive create after a result: ${names().length} ${JSON.stringify(names())}`);
  assert.deepEqual(names().sort(), ['Copy report', 'Create ZIP', 'Download'].sort());
  assert.ok(countedButtons(workspace).length <= 3);
});

test('file checksum hides Run after a result and shows it again once the result is cleared (approved v3 frame 4; Download stays primary, UX-13)', async () => {
  const ui = loadFilesUi(scanResponder({ report: { files: [{ name: 'a.txt', digest: 'a'.repeat(64) }], complete: true } }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('file_hash');
  ui.state().selections = [fileA];
  ui.context.officekitDirectUpdateSelection();
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-run').hidden, true);
  const download = findNode(ui.element('direct-file-results'), node => node.tagName === 'BUTTON' && node.textContent === 'Download');
  assert.ok(download.classes.has('btn-primary') && !download.classes.has('btn-outline'), 'Download is primary on a read-only result');
  ui.state().report = null;
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-file-run').hidden, false, 'Run returns once the result is cleared');
});

test('file checksum input: dashed empty area with a hint, Reset only after a choice, SHA-256 / SHA-512 toggle (approved mock 2026-10-26)', () => {
  const ui = loadFilesUi(scanResponder({}));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('file_hash');
  assert.match(ui.element('direct-file-description').textContent, /fingerprint of a file/);
  assert.equal(ui.element('direct-selection-line').dataset.empty, 'true');
  assert.equal(ui.element('direct-selection-hint').hidden, false);
  assert.equal(ui.element('direct-reset-selection').hidden, true);
  const toggle = findNode(ui.element('direct-file-options'), node => node.classes.has('ok-hash-algorithm'));
  const choices = toggle.children;
  assert.deepEqual(choices.map(choice => [choice.textContent, choice.getAttribute('aria-pressed')]), [['SHA-256', 'true'], ['SHA-512', 'false']]);
  choices[1].onclick();
  assert.equal(ui.element('direct-hash-algorithm').value, 'sha512');
  assert.deepEqual(choices.map(choice => choice.getAttribute('aria-pressed')), ['false', 'true']);
  ui.state().selections = [fileA];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-selection-line').dataset.empty, 'false');
  assert.equal(ui.element('direct-selection-hint').hidden, true);
  assert.equal(ui.element('direct-reset-selection').hidden, false);
  assert.equal(countedButtons(ui.element('tab-workspace')).length, 1, 'only the run button is counted');
});

test('file checksum result is one titled card with File / Size / Checksum, a copy icon per digest and no id column (approved mock 2026-10-25)', async () => {
  const digest = 'a'.repeat(64);
  const ui = loadFilesUi(scanResponder({ report: { algorithm: 'sha256', files: [{ id: 'internal-id', name: 'a.txt', size_bytes: 526, digest }], total_files: 1, total_bytes: 526, complete: true } }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('file_hash');
  assert.equal(ui.element('direct-file-run').textContent, 'Calculate checksum');
  ui.state().selections = [fileA];
  await ui.context.officekitRunDirectFiles();
  const results = ui.element('direct-file-results');
  const headers = [];
  walk(results, node => { if (node.tagName === 'TH') headers.push(node.textContent); });
  assert.deepEqual(headers, ['File', 'Size', 'Checksum']);
  assert.equal(findNode(results, node => node.tagName === 'H2').textContent, 'SHA-256 · 1 file · 526 bytes');
  assert.ok(findNode(results, node => node.tagName === 'CODE' && node.textContent === digest), 'digest is shown whole');
  const copy = findNode(results, node => node.tagName === 'BUTTON' && node.classes.has('ok-hash-copy'));
  assert.match(copy.attributes?.['aria-label'] ?? copy.getAttribute?.('aria-label') ?? '', /Copy a\.txt checksum to clipboard/);
  assert.equal(findNode(results, node => node.textContent === 'internal-id'), null, 'the internal id is not shown');
  assert.notEqual(ui.element('direct-file-status').textContent, 'Result ready.');
});

test('duplicate finder: the Open column header is empty and Download is outline beside Move to Trash (UX-14, UX-13)', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [{ ...fileA, access: 'read-write' }];
  await ui.context.officekitRunDirectFiles();
  const headers = [];
  walk(ui.element('direct-file-results'), node => { if (node.tagName === 'TH') headers.push(node.textContent); });
  assert.ok(headers.includes(''), 'the Open column header is empty');
  assert.equal(headers.includes('Open'), false, 'no Open header text');
  const download = findNode(ui.element('direct-file-results'), node => node.tagName === 'BUTTON' && node.textContent === 'Download');
  assert.ok(download.classes.has('btn-outline') && !download.classes.has('btn-primary'), 'Download is outline in the duplicate dock');
});

test('duplicate Move to Trash opens a two-button confirmation outside the screen count (approved v3 frame 2)', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [{ ...fileA, access: 'read-write' }];
  await ui.context.officekitRunDirectFiles();
  const copy = findNode(ui.element('direct-file-results'), node => node.tagName === 'INPUT' && node.attributes['aria-label'] === 'Select Group 0/copy.jpg');
  assert.ok(copy, 'a copy can be selected');
  copy.checked = true;
  copy.onchange();
  ui.element('duplicate-trash').onclick();
  const dialog = findNode(ui.context.document.body, node => node.tagName === 'DIALOG');
  assert.ok(dialog, 'the confirmation opens');
  assert.deepEqual(countedButtons(dialog).map(button => button.textContent), ['Cancel', 'Move to Trash']);
});

test('a duplicate result is cleared by the manual reset and Run returns', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [fileA];
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-run').hidden, true);
  ui.state().report = null;
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-file-run').hidden, false);
});

test('a duplicate result sets no shared status line, only the controls status (UX-16)', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [{ ...fileA, access: 'read-write' }];
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-status').textContent, '', 'no "Duplicate search complete." line');
  const controls = findNode(ui.element('direct-file-results'), node => node.id === 'duplicate-selection-status');
  assert.equal(controls.textContent, 'No copies selected');
});

test('Files tools hide the folder chooser at phone width, and the duplicate finder hides Date modified (UX-15, UX-18)', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [{ ...fileA, access: 'read-write' }];
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-choose-folder').classes.has('ok-phone-hide'), true, 'folder chooser is marked');
  const dateHeader = findNode(ui.element('direct-file-results'), node => node.tagName === 'TH' && node.classes.has('ok-phone-hide'));
  assert.ok(dateHeader, 'the Date modified header is marked');
  assert.ok(findNode(dateHeader, node => node.attributes?.['aria-label'] === 'Sort by Date modified'), 'the marked header is Date modified');
  assert.ok(findNode(ui.element('direct-file-results'), node => node.tagName === 'TD' && node.classes.has('ok-phone-hide')), 'Date modified cells are marked');
  const css = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-files.css'), 'utf8');
  assert.ok(css.includes('@media (max-width: 900px) { .ok-phone-hide { display: none; } }'), 'the phone rule hides the marked elements at 900px and below');
  ui.context.officekitOpenDirectFileTool('file_info');
  assert.equal(ui.element('direct-choose-folder').classes.has('ok-phone-hide'), true, 'file info also hides the folder chooser at phone width');
});

// Every Files tool, by the action names the JS icon map uses.
const FILES_TOOLS = ['rename', 'duplicates', 'storage', 'folder_compare', 'similar_images', 'file_hash', 'file_type', 'split_join', 'archive', 'file_info', 'file_compare', 'file_age_finder', 'empty_file_finder', 'empty_folder_finder', 'symlink_inspector'];

test('at phone width every Files tool keeps a chooser, and only the symlink inspector shows the folder chooser (UX-10, P-211)', () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  for (const action of FILES_TOOLS) {
    ui.context.officekitOpenDirectFileTool(action);
    ui.context.officekitDirectUpdateSelection();
    const folderAtPhone = !ui.element('direct-choose-folder').classes.has('ok-phone-hide');
    const filesAtPhone = !ui.element('direct-choose-files').hidden;
    // Folder-only tools (symlink inspector, similar images) have no files chooser, so the folder one stays.
    assert.equal(folderAtPhone, ['symlink_inspector', 'similar_images'].includes(action), `${action}: folder chooser at phone width`);
    assert.ok(folderAtPhone || filesAtPhone, `${action}: a chooser is visible at phone width`);
  }
});

test('the symlink inspector selection line shows the folder name alone, and says where to start (UX-5)', () => {
  const ui = loadFilesUi(scanResponder({ report: symlinkReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('symlink_inspector');
  assert.equal(ui.element('direct-selection-summary').textContent, 'Choose a folder to begin.');
  ui.state().selections = [folder];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-selection-summary').textContent, 'Projects');
  ui.context.officekitOpenDirectFileTool('file_info');
  ui.state().selections = [folder];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-selection-summary').textContent, 'Selected: Projects', 'other tools keep the labelled line');
});

test('the symlink inspector offers only the folder chooser, and the other tools keep the files chooser (UX-1)', () => {
  const ui = loadFilesUi(scanResponder({ report: symlinkReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('symlink_inspector');
  assert.equal(ui.element('direct-choose-files').hidden, true, 'no files chooser for a folder-only tool');
  assert.equal(ui.element('direct-choose-folder').hidden, false, 'the folder chooser shows');
  ui.context.officekitOpenDirectFileTool('file_info');
  assert.equal(ui.element('direct-choose-files').hidden, false, 'other tools keep the files chooser');
});

test('Find similar images is folder-only, lists the chosen folders with counts and blocks Run over the limit', () => {
  const ui = loadFilesUi(scanResponder({ report: {} }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('similar_images');
  assert.equal(ui.element('direct-choose-files').hidden, true, 'no files chooser for a folder tool');
  assert.equal(ui.element('direct-selection-summary').textContent, 'No folder selected.');
  ui.state().selections = [folder];
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-selection-summary').textContent, 'Counting images…');
  assert.equal(ui.element('direct-file-run').disabled, true, 'Run waits for the count');
  const summary = { folders: [{ name: 'Pictures', images: 4988 }], images: 4988, skipped: 3, limit: 10000 };
  ui.state().imageSummary = summary;
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-selection-summary').textContent, '4,988 images in 1 folder · 3 files skipped (not images)');
  assert.equal(ui.element('direct-image-ready').textContent, 'Ready: 4,988 of 10,000 images.');
  assert.equal(ui.element('direct-image-list').children.length, 1, 'one row per selected folder');
  assert.equal(ui.element('direct-file-run').disabled, false);
  ui.state().imageSummary = { ...summary, folders: [{ name: 'Pictures', images: 12310 }], images: 12310 };
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-image-ready').textContent, '2,310 over the 10,000 image limit. Choose a smaller folder.');
  assert.equal(ui.element('direct-file-run').disabled, true, 'Run is blocked over the limit');
  ui.state().imageSummary = { folders: [], images: 0, skipped: 2, limit: 10000 };
  ui.context.officekitDirectUpdateSelection();
  assert.equal(ui.element('direct-image-ready').textContent, 'No supported images in this selection.');
  assert.equal(ui.element('direct-file-run').disabled, true);
});

test('a normal text compare shows the Text view line under the headline, too-large text does not (UX-17)', async () => {
  const ui = loadFilesUi(scanResponder({ report: scanReport('file_compare') }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('file_compare');
  ui.state().selections = [fileA, fileB];
  await ui.context.officekitRunDirectFiles();
  assert.ok(findNode(ui.element('direct-file-results'), node => node.textContent === 'Text view, 2 files, both under 2 MiB.'), 'the Text view line is shown');
  const large = loadFilesUi(scanResponder({ report: { ...scanReport('file_compare'), mode: 'text-too-large' } }));
  large.context.officekitBindDirectFiles();
  large.context.officekitOpenDirectFileTool('file_compare');
  large.state().selections = [fileA, fileB];
  await large.context.officekitRunDirectFiles();
  assert.ok(!findNode(large.element('direct-file-results'), node => node.textContent === 'Text view, 2 files, both under 2 MiB.'), 'no Text view line for too-large text');
});

test('the duplicate match-type change returns Run before the next scan', async () => {
  const ui = loadFilesUi(scanResponder({ report: duplicateReport() }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('duplicates');
  ui.state().selections = [fileA];
  await ui.context.officekitRunDirectFiles();
  assert.equal(ui.element('direct-file-run').hidden, true);
  ui.element('direct-duplicate-mode').onchange();
  assert.equal(ui.element('direct-file-run').hidden, false);
});

test('Files screens use the approved mock copy for titles and descriptions', () => {
  const approved = {
    file_info: ['File info', 'See size, dates and basic attributes of selected originals. Nothing is changed.'],
    file_compare: ['Compare two files', 'Check whether two files are identical, and see where they differ. Nothing is merged or changed.'],
    file_age_finder: ['File age finder', 'List files whose modified or created date falls inside the range. Both dates are included.'],
    empty_folder_finder: ['Empty-folder finder', 'Check folders from the deepest level up. Review only; nothing is removed.'],
    symlink_inspector: ['Symlink inspector', 'Find links in a folder and see where each one points, without following them.'],
  };
  for (const [action, [title, description]] of Object.entries(approved)) {
    const ui = loadFilesUi();
    ui.context.officekitOpenDirectFileTool(action);
    assert.equal(ui.element('direct-file-title').textContent, title, action);
    assert.equal(ui.element('direct-file-description').textContent, description, action);
  }
});

async function runSymlinkScan(report) {
  const ui = loadFilesUi(scanResponder({ report }));
  ui.context.officekitBindDirectFiles();
  ui.context.officekitOpenDirectFileTool('symlink_inspector');
  ui.state().selections = [folder];
  ui.context.officekitDirectUpdateSelection();
  await ui.context.officekitRunDirectFiles();
  return ui;
}

function symlinkStateTags(results) {
  const tags = [];
  walk(results, node => { if (node.tagName === 'SPAN' && node.classes.has('badge')) tags.push(node.textContent); });
  return tags;
}

test('symlink inspector: the summary, the state tags and the note use the approved copy (F11)', async () => {
  const ui = await runSymlinkScan(symlinkReport());
  const results = ui.element('direct-file-results');
  assert.equal(findNode(results, node => node.classes.has('ok-file-summary')).textContent, '5 links · 1 resolves inside the folder, 2 broken or circular, 2 point outside');
  const headers = [];
  walk(results, node => { if (node.tagName === 'TH') headers.push(node.textContent); });
  assert.deepEqual(headers, ['Link', 'Points to (as written)', 'Type', 'State']);
  assert.deepEqual(symlinkStateTags(results), ['Resolves inside folder', 'Outside selected folder · not checked', 'Broken', 'Circular (2 hops)', 'Outside selected folder · not checked']);
  assert.ok(findNode(results, node => node.tagName === 'SPAN' && node.textContent === 'src/current' && node.classes.has('ok-phone-hide')), 'the folder-relative path is a phone-hidden sub-line');
  assert.ok(findLeaf(results, 'releases/v2'), 'the target is shown as written');
  assert.ok(findLeaf(results, 'Links are never followed outside the selection. Targets outside it are shown as written, never opened or checked.'), 'the approved note');
});

test('symlink inspector hides the Type column at phone width and keeps the other columns (F11 phone frame)', async () => {
  const ui = await runSymlinkScan(symlinkReport());
  const table = findNode(ui.element('direct-file-results'), node => node.tagName === 'TABLE');
  const [head] = table.children.filter(node => node.tagName === 'THEAD');
  const columns = head.children[0].children;
  assert.deepEqual(columns.map(th => th.classes.has('ok-phone-hide')), [false, false, true, false]);
  const [body] = table.children.filter(node => node.tagName === 'TBODY');
  for (const row of body.children) assert.equal(row.children[2].classes.has('ok-phone-hide'), true, 'each Type cell is marked');
});

test('a partial symlink scan names the denied folder and the entry cap in one banner (approved partial frame)', async () => {
  const ui = await runSymlinkScan(symlinkReport({ denied_folders: 1, entry_limit_reached: true, complete: false }));
  const results = ui.element('direct-file-results');
  assert.equal(findNode(results, node => node.classes.has('ok-file-summary')).textContent, '5 links found so far');
  assert.ok(findLeaf(results, 'Partial result: 1 folder could not be read (permission denied) and the scan stopped at 100,000 entries.'), 'the banner');
  assert.ok(findNode(results, node => node.tagName === 'TABLE'), 'the links found so far stay on screen');
  assert.equal(findLeaf(results, 'Links are never followed outside the selection. Targets outside it are shown as written, never opened or checked.'), null, 'the note waits for a complete result');
});

test('the banner reads its entry cap from the report, not from a copy in the script', async () => {
  const ui = await runSymlinkScan(symlinkReport({ denied_folders: 0, entry_limit: 3, entry_limit_reached: true, complete: false }));
  assert.ok(findLeaf(ui.element('direct-file-results'), 'Partial result: the scan stopped at 3 entries.'), 'the banner names the report limit');
});

test('a folder with no links says how many items it checked, and says so when the scan is partial (UX-3)', async () => {
  const ui = await runSymlinkScan(symlinkReport({ links: [], total_links: 0, resolves_inside: 0, broken_or_circular: 0, outside_selection: 0, scanned_items: 1204 }));
  const results = ui.element('direct-file-results');
  assert.equal(findNode(results, node => node.classes.has('ok-file-summary')).textContent, 'No links found in 1,204 items.');
  assert.equal(findNode(results, node => node.tagName === 'TABLE'), null, 'no table without links');
  const partial = await runSymlinkScan(symlinkReport({ links: [], total_links: 0, resolves_inside: 0, broken_or_circular: 0, outside_selection: 0, scanned_items: 1204, denied_folders: 1, complete: false }));
  assert.equal(findNode(partial.element('direct-file-results'), node => node.classes.has('ok-file-summary')).textContent, 'No links found so far in 1,204 items.');
});

test('the two states that are not checks say so: not supported here, and permission denied with a partial banner', async () => {
  const ui = await runSymlinkScan(symlinkReport({
    links: [
      { name: 'w', relative_path: 'w', points_to: null, type: null, state: 'unsupported', hops: 0 },
      { name: 'p', relative_path: 'p', points_to: 'locked/x', type: 'relative', state: 'denied', hops: 1 },
    ],
    total_links: 2, resolves_inside: 0, broken_or_circular: 0, outside_selection: 0, not_checked: 1, unsupported: 1, scanned_items: 2, complete: false,
  }));
  const results = ui.element('direct-file-results');
  assert.deepEqual(symlinkStateTags(results), ['Not supported on this system', 'Not checked · permission denied']);
  assert.ok(findLeaf(results, 'Partial result: 1 link target could not be read (permission denied).'), 'the banner counts the unchecked target once');
  assert.ok(findLeaf(results, '—'), 'a link with no readable target shows a dash');
});

test('symlink inspector counts a single link and names unsupported links in the summary (F11)', async () => {
  const single = await runSymlinkScan(symlinkReport({
    links: [{ name: 'self', relative_path: 'self', points_to: 'self', type: 'relative', state: 'circular', hops: 1 }],
    total_links: 1, resolves_inside: 0, broken_or_circular: 1, outside_selection: 0, scanned_items: 1, complete: true,
  }));
  const singleResults = single.element('direct-file-results');
  assert.equal(findNode(singleResults, node => node.classes.has('ok-file-summary')).textContent, '1 link · 0 resolves inside the folder, 1 broken or circular, 0 point outside');
  assert.deepEqual(symlinkStateTags(singleResults), ['Circular (1 hop)']);
  const unsupported = await runSymlinkScan(symlinkReport({
    links: [{ name: 'w', relative_path: 'w', points_to: null, type: null, state: 'unsupported', hops: 0 }],
    total_links: 1, resolves_inside: 0, broken_or_circular: 0, outside_selection: 0, unsupported: 1, scanned_items: 1, complete: true,
  }));
  assert.equal(findNode(unsupported.element('direct-file-results'), node => node.classes.has('ok-file-summary')).textContent, '1 link · 0 resolves inside the folder, 0 broken or circular, 0 point outside');
});

test('a partial symlink banner counts every folder and target, and a long result says the preview is 200 rows (F11)', async () => {
  const ui = await runSymlinkScan(symlinkReport({ denied_folders: 2, not_checked: 2, complete: false, hasMore: true }));
  const results = ui.element('direct-file-results');
  assert.ok(findLeaf(results, 'Partial result: 2 folders and 2 link targets could not be read (permission denied).'), 'the banner says the permission denial once');
  assert.ok(findLeaf(results, 'Preview shows 200 rows. Copy and Download use the complete result.'), 'the preview note');
});

// The approved symlink-inspector frame: one link per state the screen names.
function symlinkReport(overrides = {}) {
  return {
    links: [
      { name: 'current', relative_path: 'src/current', points_to: 'releases/v2', type: 'relative', state: 'inside', hops: 1 },
      { name: 'docs', relative_path: 'src/docs', points_to: '../shared/docs', type: 'relative', state: 'out-of-scope', hops: 1 },
      { name: 'old', relative_path: 'src/old', points_to: 'archive/missing', type: 'relative', state: 'broken', hops: 1 },
      { name: 'loop-a', relative_path: 'src/loop-a', points_to: 'loop-b', type: 'relative', state: 'circular', hops: 2 },
      { name: 'sdk', relative_path: 'src/sdk', points_to: '/opt/sdk', type: 'absolute', state: 'out-of-scope', hops: 1 },
    ],
    total_links: 5, resolves_inside: 1, broken_or_circular: 2, outside_selection: 2, not_checked: 0, unsupported: 0,
    scanned_items: 12, denied_folders: 0, entry_limit: 100000, entry_limit_reached: false, complete: true,
    ...overrides,
  };
}

function scanReport(action) {
  if (action === 'symlink_inspector') return symlinkReport({ links: [], total_links: 0, resolves_inside: 0, broken_or_circular: 0, outside_selection: 0, scanned_items: 0 });
  if (action === 'file_compare') return compareReport();
  if (action === 'file_info') return { files: [], total_files: 0, total_bytes: 0, skipped: [], skipped_links: 0, denied_folders: 0, platform_limits: [], complete: true };
  if (action === 'file_age_finder') return { files: [], scanned: 0, matched: 0, matched_bytes: 0, unavailable_dates: 0, date_field: 'created', complete: true };
  if (action === 'empty_file_finder') return { files: [], scanned: 0, skipped_links: 0, denied_folders: 0, complete: true };
  return { folders: [], scanned_folders: 0, skipped_links: 0, skipped_other_volume: 0, skipped_bundles: 0, excluded_protected: 0, denied_folders: 0, complete: true };
}

function compareReport(overrides = {}) {
  return {
    equal: false, same_file: false, size_a: 10, size_b: 12, sha256_a: 'a'.repeat(64), sha256_b: 'b'.repeat(64),
    first_difference_offset: 42, bytes_a: null, bytes_b: null, mode: 'text', encoding_a: 'utf-8', encoding_b: 'utf-8',
    line_endings_a: 'lf', line_endings_b: 'lf', equal_ignoring_line_endings: false, hunks: [], truncated: false, complete: true,
    ...overrides,
  };
}

test('File Type Detector renders readable facts and keeps complete JSON in shared actions', async () => {
  const report = {
    total_files: 1,
    complete: true,
    files: [{ name:'photo.png', size_bytes:60_605, extension:'.png', detected_type:'JPEG', mime_type:'image/jpeg', extension_matches:false, method:'magic-bytes+utf8' }],
  };
  const expected = JSON.stringify(report);
  const ui = loadFilesUi(scanResponder({ report }));
  ui.filesRegistration.openView('file_type');
  ui.state().selections = [fileA];
  ui.context.officekitRenderDirectReport(report, 'job-1');

  const results = ui.element('direct-file-results');
  for (const label of ['photo.png', 'Size', '59.2 KiB', 'Extension', '.png', 'Detected type', 'JPEG', 'MIME type', 'image/jpeg', 'Matches extension?', 'No', 'File contents are identified by signature. This does not scan for malware.']) {
    assert.ok(findLeaf(results, label), `rendered result includes ${label}`);
  }
  assert.equal(findLeaf(results, 'false'), null, 'boolean mismatch is presented in plain language');
  assert.equal(findNode(results, node => node.classes.has('ok-file-type-record'))?.tagName, 'ARTICLE');
  const actions = ui.mountedActions();
  assert.equal(actions.toolId, 'file_type');
  assert.equal(typeof actions.copy, 'function');
  assert.equal(typeof actions.download, 'function');
  await actions.copy();
  assert.equal(ui.context.__officekitCopiedText, expected);
  await actions.download();
  assert.deepEqual(ui.context.__officekitDownloadedFile, { text: expected, suggestedName: 'file-result.json' });
});
