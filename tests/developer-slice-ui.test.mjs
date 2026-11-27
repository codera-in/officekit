import strictAssert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

// Objects built inside the vm context carry another realm's prototypes, so deep comparisons go through JSON.
const assert = {
  ...strictAssert,
  deepEqual: (actual, expected, message) => strictAssert.deepStrictEqual(JSON.parse(JSON.stringify(actual)), expected, message),
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sliceSource = fs.readFileSync(path.join(repoRoot, 'assets', 'officekit-slice-developer.js'), 'utf8');
const catalogueSource = fs.readFileSync(path.join(repoRoot, 'officekit', 'tool_catalog', 'developer.py'), 'utf8');
const NEW_TOOL_IDS = ['json_compare', 'text_diff', 'timestamp_converter', 'uuid_generator', 'qr_generator', 'text_metrics', 'text_case'];

// ---- minimal DOM -------------------------------------------------------------

class FakeText {
  constructor(data) { this.nodeType = 3; this.data = data; this.parentNode = null; }
  get textContent() { return this.data; }
}

class FakeElement {
  constructor(tag, ownerDocument) {
    this.nodeType = 1;
    this.localName = tag;
    this.tagName = tag.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.attributes = new Map();
    this.children = [];
    this.listeners = {};
    this.parentNode = null;
    this.hidden = false;
    this.disabled = false;
    this.className = '';
    this._value = undefined;
    this.scrollIntoViewOptions = null;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === 'hidden') this.hidden = true;
    if (name === 'disabled') this.disabled = true;
  }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === 'hidden') this.hidden = false;
    if (name === 'disabled') this.disabled = false;
  }
  get id() { return this.getAttribute('id') ?? ''; }
  get dataset() {
    const out = {};
    for (const [key, value] of this.attributes) {
      if (key.startsWith('data-')) out[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
    return out;
  }
  get value() {
    if (this._value !== undefined) return this._value;
    if (this.localName === 'select') {
      const first = this.children.find(child => child.localName === 'option');
      return first ? first.getAttribute('value') ?? first.textContent : '';
    }
    return this.getAttribute('value') ?? '';
  }
  set value(next) { this._value = String(next); }
  get textContent() { return this.children.map(child => child.textContent).join(''); }
  set textContent(next) {
    this.replaceChildren();
    if (next !== '' && next !== null && next !== undefined) this.append(String(next));
  }
  append(...nodes) {
    for (const node of nodes.flat()) {
      if (node === null || node === undefined || node === false) continue;
      const child = typeof node === 'object' ? node : new FakeText(String(node));
      child.parentNode = this;
      this.children.push(child);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  scrollIntoView(options) { this.scrollIntoViewOptions = options; }
  click() {
    this.attachedAtClick = this.parentNode !== null;
    for (const handler of this.listeners.click || []) handler({ target: this });
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
  change() { for (const handler of this.listeners.change || []) handler({ target: this }); }
  input() { for (const handler of this.listeners.input || []) handler({ target: this }); }
  get classList() {
    const node = this;
    return {
      toggle(name, force) {
        const names = new Set(node.className.split(/\s+/).filter(Boolean));
        const on = force ?? !names.has(name);
        if (on) names.add(name); else names.delete(name);
        node.className = [...names].join(' ');
        return on;
      },
    };
  }
  closest() { return null; }
  querySelectorAll(selector) {
    const attribute = selector.match(/^\[([a-z-]+)\]$/)?.[1];
    const found = [];
    const walk = node => {
      for (const child of node.children) {
        if (child.nodeType !== 1) continue;
        if (attribute && child.attributes.has(attribute)) found.push(child);
        walk(child);
      }
    };
    walk(this);
    return found;
  }
}

class FakeDocument {
  constructor() { this.all = []; this.body = this.createElement('body'); }
  createElement(tag) { const node = new FakeElement(tag, this); this.all.push(node); return node; }
  createTextNode(text) { return new FakeText(text); }
  getElementById(id) { return this.all.find(node => node.getAttribute('id') === id) || null; }
  querySelectorAll(selector) {
    const attribute = selector.match(/^\[([a-z-]+)\]$/)?.[1];
    return this.all.filter(node => attribute && node.attributes.has(attribute));
  }
}

// ---- loader ------------------------------------------------------------------

function loadSlice({ fetchResponses = [], clipboard, toasts = [] } = {}) {
  const registrations = [];
  const doc = new FakeDocument();
  const ctx = {
    OfficeKitExtensions: { register: config => registrations.push(config) },
    document: doc,
    TextEncoder,
    officekitApiUrl: path => path,
    showAppFeedbackToast: (message, state) => toasts.push({ message, state }),
    navigator: clipboard ? { clipboard } : {},
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} },
    Blob: class { constructor(parts, options) { this.parts = parts; this.type = options?.type; } },
    officekitLocalTimeZone: () => 'UTC',
    ClipboardItem: class { constructor(items) { this.items = items; } },
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    setTimeout: () => 0,
    fetchCalls: [],
    fetch: async (url, init) => {
      ctx.fetchCalls.push({ url, init });
      const next = fetchResponses.shift();
      if (next instanceof Error) throw next;
      return next;
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(sliceSource, ctx, { filename: 'officekit-slice-developer.js' });
  for (const id of ['tab-developer', 'developer-tools-input', 'developer-tools-input-label', 'developer-tools-hint', 'developer-slice-fields', 'developer-slice-result', 'developer-tools-output', 'developer-tools-output-label']) {
    const node = doc.createElement('section');
    node.setAttribute('id', id);
  }
  return { ctx, doc, registrations, slice: ctx.OfficeKitDeveloperSlice, toasts };
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function textOf(node) { return node.textContent; }

function collectElements(node, found = []) {
  if (node.nodeType === 1) found.push(node);
  for (const child of node.children || []) collectElements(child, found);
  return found;
}

// ---- routing -----------------------------------------------------------------

test('every new catalogue ID routes to a registered developer destination with the catalogue tab', () => {
  const { registrations } = loadSlice();
  assert.equal(registrations.length, 1);
  assert.equal(registrations[0].slice, 'developer');
  assert.deepEqual(registrations[0].tabs, ['developer']);
  const catalogueTabs = Object.fromEntries([...catalogueSource.matchAll(/\{"id": "([a-z_]+)".*?"tab": "([a-z]+)"/g)].map(match => [match[1], match[2]]));
  for (const id of NEW_TOOL_IDS) {
    const destination = registrations[0].destinations[id];
    assert.ok(destination, `${id} has a destination`);
    assert.equal(destination.tab, catalogueTabs[id], `${id} tab matches the catalogue`);
  }
  assert.equal(Object.keys(registrations[0].destinations).length, NEW_TOOL_IDS.length);
});

test('Compare, UUID and QR destinations open their own panels in the developer tab', () => {
  const { registrations, slice, doc } = loadSlice();
  const destinations = registrations[0].destinations;
  slice.openView(destinations.json_compare.sliceView);
  assert.equal(doc.getElementById('developer-compare-panel').hidden, false);
  assert.equal(doc.getElementById('developer-uuid-panel'), null);
  assert.equal(doc.getElementById('developer-compare-mode').querySelectorAll('[data-compare-mode]').length, 2);
  assert.equal(doc.getElementById('developer-compare-json-details').hidden, false);
  assert.equal(doc.getElementById('developer-compare-text-details').hidden, true);

  slice.openView(destinations.text_diff.sliceView);
  assert.equal(doc.getElementById('developer-compare-text-details').hidden, false);
  assert.equal(doc.getElementById('developer-compare-layout').hidden, false);

  slice.openView(destinations.uuid_generator.sliceView);
  assert.equal(doc.getElementById('developer-uuid-panel').hidden, false);
  assert.equal(doc.getElementById('developer-compare-panel').hidden, true);

  slice.openView(destinations.qr_generator.sliceView);
  assert.equal(doc.getElementById('developer-qr-panel').hidden, false);
  assert.equal(doc.getElementById('developer-uuid-panel').hidden, true);

  slice.openView('unknown-view');
  assert.equal(doc.getElementById('developer-qr-panel').hidden, false, 'unknown views are ignored');
});

test('developer select operations are routed to the slice only for its three operations', () => {
  const { slice } = loadSlice();
  for (const operation of ['text_metrics', 'text_case', 'timestamp_convert']) assert.equal(slice.handles(operation), true);
  for (const operation of ['format_json', 'hashes', 'decode_jwt', 'base64_encode']) assert.equal(slice.handles(operation), false);
});

// ---- request building --------------------------------------------------------

test('JSON and text diff requests send only the documented fields and reject bad options', () => {
  const { slice } = loadSlice();
  assert.deepEqual(slice.jsonDiffRequest({ original: '{}', changed: '[]' }).body, { original: '{}', changed: '[]', array_order: 'ordered', numeric: 'value' });
  assert.throws(() => slice.jsonDiffRequest({ original: 1, changed: '2' }), { message: slice.MESSAGES.jsonOriginal });
  assert.throws(() => slice.jsonDiffRequest({ original: '{}', changed: '[' }), { message: slice.MESSAGES.jsonChanged });
  assert.throws(() => slice.jsonDiffRequest({ original: '{}', changed: '{}', arrayOrder: 'sorted' }), { message: slice.MESSAGES.json });
  const diff = slice.textDiffRequest({ original: 'a', changed: 'b', whitespace: 'ignore_all', lineEndings: 'exact', unicodeNfc: 1 });
  assert.deepEqual(diff.body, { original: 'a', changed: 'b', whitespace: 'ignore_all', line_endings: 'exact', unicode_nfc: true });
  assert.throws(() => slice.textDiffRequest({ original: 'a', changed: 'b', whitespace: 'loose' }), { message: slice.MESSAGES.text });
  assert.throws(() => slice.jsonDiffRequest({ original: 'x'.repeat(1_048_577), changed: '' }), { message: slice.MESSAGES.jsonOriginal });
  // Limits are UTF-8 bytes (PM-6): two quotes plus 524,287 two-byte characters is exactly 1,048,576 bytes.
  assert.doesNotThrow(() => slice.jsonDiffRequest({ original: `"${'é'.repeat(524_287)}"`, changed: '1' }));
  assert.throws(() => slice.jsonDiffRequest({ original: `"${'é'.repeat(524_287)}"x`, changed: '1' }), { message: slice.MESSAGES.jsonOriginal });
});

test('text case and text analysis requests validate style, locale and empty input', () => {
  const { slice } = loadSlice();
  assert.deepEqual(slice.textCaseRequest({ text: 'straße', style: 'upper', locale: 'tr' }).body, { text: 'straße', style: 'upper', locale: 'tr' });
  assert.equal(slice.textCaseRequest({ text: 'a', style: 'lower' }).body.locale, 'root');
  assert.throws(() => slice.textCaseRequest({ text: 'a', style: 'shout' }), { message: slice.MESSAGES.textInput });
  assert.throws(() => slice.textCaseRequest({ text: 'a', style: 'lower', locale: 'de' }), { message: slice.MESSAGES.textInput });
  assert.throws(() => slice.textAnalysisRequest(''), { message: slice.MESSAGES.empty });
  assert.deepEqual(slice.textAnalysisRequest('é\nab').body, { text: 'é\nab' });
});

test('timestamp requests dedupe zones, require a source zone for local times and cap zones at eight', () => {
  const { slice } = loadSlice();
  assert.deepEqual(
    slice.timestampRequest({ value: ' 0 ', inputType: 'unix_seconds', targetZones: ['UTC', ' UTC ', 'Asia/Tokyo', ''] }).body,
    { value: '0', input_type: 'unix_seconds', target_zones: ['UTC', 'Asia/Tokyo'] },
  );
  assert.deepEqual(
    slice.timestampRequest({ value: '2026-11-01T01:30', inputType: 'local_datetime', sourceZone: 'America/New_York', fold: 'earlier', targetZones: ['UTC'] }).body,
    { value: '2026-11-01T01:30', input_type: 'local_datetime', target_zones: ['UTC'], source_zone: 'America/New_York', fold: 'earlier' },
  );
  assert.throws(() => slice.timestampRequest({ value: '2026-11-01T01:30', inputType: 'local_datetime', targetZones: ['UTC'] }), { message: slice.MESSAGES.timestamp });
  assert.throws(() => slice.timestampRequest({ value: '  ', inputType: 'unix_seconds', targetZones: ['UTC'] }), { message: slice.MESSAGES.timestamp });
  assert.throws(() => slice.timestampRequest({ value: '0', inputType: 'unix_seconds', targetZones: [] }), { message: slice.MESSAGES.timestamp });
  const nine = ['UTC', 'Asia/Tokyo', 'Europe/Paris', 'Asia/Kolkata', 'Asia/Dubai', 'Asia/Baku', 'Europe/Berlin', 'America/Chicago', 'Pacific/Auckland'];
  assert.throws(() => slice.timestampRequest({ value: '0', inputType: 'unix_seconds', targetZones: nine }), { message: slice.MESSAGES.timestamp });
  assert.equal(slice.timestampRequest({ value: '0', inputType: 'unix_seconds', targetZones: nine.slice(0, 8) }).body.target_zones.length, 8);
});

test('UUID requests bound the batch, pin v5 to one name and forbid names outside v5', () => {
  const { slice } = loadSlice();
  assert.deepEqual(slice.uuidRequest({ version: 4, count: 1000 }).body, { version: 4, count: 1000, case: 'lower', style: 'canonical' });
  assert.throws(() => slice.uuidRequest({ version: 4, count: 1001 }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 4, count: 0 }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 4, count: Number.NaN }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 3, count: 1 }), { message: slice.MESSAGES.uuid });
  assert.deepEqual(
    slice.uuidRequest({ version: 5, count: 1, namespace: 'DNS', name: 'python.org' }).body,
    { version: 5, count: 1, namespace: 'dns', name: 'python.org', case: 'lower', style: 'canonical' },
  );
  assert.equal(slice.uuidRequest({ version: 5, count: 1, namespace: '6BA7B810-9DAD-11D1-80B4-00C04FD430C8', name: 'a' }).body.namespace, '6ba7b810-9dad-11d1-80b4-00c04fd430c8');
  assert.throws(() => slice.uuidRequest({ version: 5, count: 2, namespace: 'dns', name: 'a' }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 5, count: 1, namespace: 'dns', name: '' }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 5, count: 1, namespace: 'dns', name: 'a'.repeat(1025) }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 5, count: 1, namespace: 'not-a-namespace', name: 'a' }), { message: slice.MESSAGES.uuid });
  assert.throws(() => slice.uuidRequest({ version: 4, count: 1, letters: 'mixed' }), { message: slice.MESSAGES.uuid });
});

test('QR requests enforce payload, ECC capacity by UTF-8 bytes and size bounds', () => {
  const { slice } = loadSlice();
  assert.deepEqual(
    slice.qrRequest({ payload: 'https://example.com', errorCorrection: 'H', sizePx: 256, format: 'svg' }).body,
    { payload: 'https://example.com', error_correction: 'H', size_px: 256, format: 'svg' },
  );
  assert.throws(() => slice.qrRequest({ payload: '' }), { message: slice.MESSAGES.qr });
  assert.throws(() => slice.qrRequest({ payload: 'é'.repeat(1477), errorCorrection: 'L' }), { message: slice.MESSAGES.qr });
  assert.equal(slice.qrRequest({ payload: 'é'.repeat(1165), errorCorrection: 'L' }).body.payload.length, 1165);
  assert.throws(() => slice.qrRequest({ payload: 'a', sizePx: 127 }), { message: slice.MESSAGES.qr });
  assert.throws(() => slice.qrRequest({ payload: 'a', errorCorrection: 'X' }), { message: slice.MESSAGES.qr });
  assert.throws(() => slice.qrRequest({ payload: 'a', format: 'gif' }), { message: slice.MESSAGES.qr });
  assert.deepEqual(slice.qrCapacity('é', 'M'), { used: 2, limit: 2331 });
});

// ---- response validation -----------------------------------------------------

test('responses are validated before they reach the DOM', () => {
  const { slice } = loadSlice();
  assert.throws(() => slice.parseJsonDiffResponse(null), { message: slice.MESSAGES.invalidResponse });
  assert.throws(() => slice.parseJsonDiffResponse({ equal: 'yes', changes: [], truncated: false, counts: {} }), { message: slice.MESSAGES.invalidResponse });
  assert.throws(() => slice.parseJsonDiffResponse({ equal: true, changes: [], truncated: false }), { message: slice.MESSAGES.invalidResponse });
  assert.equal(slice.parseJsonDiffResponse({ equal: true, changes: [], truncated: false, counts: {} }).equal, true);
  assert.throws(() => slice.parseTextDiffResponse({ equal: true, rows: 'x', patch: '' }), { message: slice.MESSAGES.invalidResponse });
  assert.throws(() => slice.parseUuidResponse({ uuids: ['a', 3] }), { message: slice.MESSAGES.invalidResponse });
  assert.throws(() => slice.parseQrResponse({ format: 'png', data: '<img src=x onerror=alert(1)>' }), { message: slice.MESSAGES.invalidResponse });
  assert.throws(() => slice.parseQrResponse({ format: 'gif', data: 'R0lG' }), { message: slice.MESSAGES.invalidResponse });
  assert.equal(slice.parseQrResponse({ format: 'png', data: 'iVBORw0KGgo=' }).format, 'png');
});

test('UUID export produces plain text and CSV with one identifier per line', () => {
  const { slice } = loadSlice();
  assert.equal(slice.uuidExport(['a', 'b'], 'txt'), 'a\nb\n');
  assert.equal(slice.uuidExport(['a', 'b'], 'csv'), 'uuid\na\nb\n');
});

// ---- network and error states ------------------------------------------------

test('text metrics runs through the analysis route and renders the stat lines', async () => {
  const { slice, ctx } = loadSlice({
    fetchResponses: [jsonResponse({ graphemes: 4, code_points: 5, utf8_bytes: 6, utf16_units: 5, words: 2, lines: 2, blank_lines: 0, whitespace: 2, longest_line_graphemes: 3 })],
  });
  const output = await slice.run('text_metrics', 'é👩‍👩‍👧 x\nab');
  assert.match(output, /^Graphemes: 4$/m);
  assert.match(output, /^Longest line \(graphemes\): 3$/m);
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/text-analyses');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { text: 'é👩‍👩‍👧 x\nab' });
});

test('server 422 and 413 responses map to the fixed client messages without echoing the body', async () => {
  const { slice } = loadSlice({
    fetchResponses: [
      jsonResponse({ detail: 'ZZ-ECHO-MARKER' }, 422),
      jsonResponse({}, 413),
      { ok: true, status: 200, json: async () => { throw new SyntaxError('bad json'); } },
    ],
  });
  await assert.rejects(() => slice.run('text_metrics', 'abc'), error => error.message === slice.MESSAGES.textInput && !error.message.includes('ZZ-ECHO'));
  await assert.rejects(() => slice.run('text_metrics', 'abc'), { message: slice.MESSAGES.tooLarge });
  await assert.rejects(() => slice.run('text_metrics', 'abc'), { message: slice.MESSAGES.invalidResponse });
});

test('a failed network call reports the local-service message', async () => {
  const { slice } = loadSlice({ fetchResponses: [new TypeError('connection refused')] });
  await assert.rejects(() => slice.run('text_case', 'abc'), { message: slice.MESSAGES.network });
});

test('empty metrics input is rejected before any request is sent', async () => {
  const { slice, ctx } = loadSlice();
  await assert.rejects(() => slice.run('text_metrics', ''), { message: slice.MESSAGES.empty });
  assert.equal(ctx.fetchCalls.length, 0);
});

test('timestamp conversion sends the chosen input form and formats the zone lines', async () => {
  const { slice, ctx, doc } = loadSlice({
    fetchResponses: [jsonResponse({ zones: ['UTC'], local_zone: 'UTC' }), jsonResponse({
      instant_utc: '1970-01-01T00:00:00Z',
      unix_seconds: '0',
      unix_milliseconds: '0',
      unix_microseconds: '0',
      conversions: [{ zone: 'UTC', local_iso: '1970-01-01T00:00:00+00:00', offset: '+00:00', abbreviation: 'UTC', is_dst: false, weekday: 'Thursday' }],
      warnings: ['magnitude_suggests_milliseconds'],
    })],
  });
  slice.syncOperation('timestamp_convert');
  doc.getElementById('developer-slice-ts-type').value = 'unix_seconds';
  const output = await slice.run('timestamp_convert', '0');
  assert.match(output, /^Instant \(UTC\): 1970-01-01T00:00:00Z$/m);
  assert.match(output, /^UTC: 1970-01-01T00:00:00\+00:00 UTC \(\+00:00\), Thursday$/m);
  assert.match(output, /^Warning: magnitude_suggests_milliseconds$/m);
  assert.equal(ctx.fetchCalls.length, 2);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/time-zones');
  assert.equal(ctx.fetchCalls[1].url, '/api/developer/timestamp-conversions');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { value: '0', input_type: 'unix_seconds', target_zones: ['UTC'] });
});

test('text metrics shows the approved stat grid with a How these are counted Details, and hides the text result', async () => {
  const { slice, doc, ctx } = loadSlice({
    fetchResponses: [jsonResponse({ graphemes: 22, code_points: 27, utf8_bytes: 49, utf16_units: 27, words: 4, lines: 2, blank_lines: 0, whitespace: 5, longest_line_graphemes: 15 })],
  });
  slice.syncOperation('text_metrics');
  assert.equal(doc.getElementById('developer-tools-output').hidden, true, 'the text result is replaced by the stat grid');
  await slice.run('text_metrics', 'Café 👩‍👩‍👧 flag 🇮🇳\ndéjà vu\n');
  const host = doc.getElementById('developer-slice-result');
  assert.equal(host.hidden, false);
  assert.deepEqual(host.scrollIntoViewOptions, { block: 'start' }, 'the completed metrics are brought into view above the dock');
  const tiles = collectElements(host).filter(node => String(node.className).split(/\s+/).includes('ok-dev-stat'));
  assert.deepEqual(tiles.map(tile => [textOf(tile.children[0]), textOf(tile.children[1])]), [
    ['22', 'Characters you see (graphemes)'],
    ['27', 'Unicode code points'],
    ['49', 'UTF-8 bytes'],
    ['4', 'Words'],
    ['2', 'Lines'],
    ['0', 'Blank lines'],
  ]);
  const details = collectElements(host).find(node => node.localName === 'details');
  assert.ok(details, 'the counting rules are in a Details');
  assert.equal(details.getAttribute('open'), null, 'the Details is closed');
  assert.match(textOf(details), /How these are counted/);
  assert.match(textOf(details), /extended grapheme clusters/);
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/text-analyses');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { text: 'Café 👩‍👩‍👧 flag 🇮🇳\ndéjà vu\n' });
});

const TIMESTAMP_TABLE_BODY = {
  instant_utc: '2023-11-14T22:13:20Z',
  unix_seconds: '1700000000',
  unix_milliseconds: '1700000000000',
  unix_microseconds: '1700000000000000',
  conversions: [
    { zone: 'UTC', local_iso: '2023-11-14T22:13:20.000Z', offset: '+00:00', abbreviation: 'UTC', is_dst: false, weekday: 'Tuesday' },
    { zone: 'America/New_York', local_iso: '2023-11-14T17:13:20.000-05:00', offset: '-05:00', abbreviation: 'EST', is_dst: false, weekday: 'Tuesday' },
  ],
  warnings: [],
};

test('Convert timestamp hides the shared Input, uses a single-line Value and chips for zones, and draws a table', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse(TIMESTAMP_TABLE_BODY)] });
  slice.syncOperation('timestamp_convert');
  assert.equal(doc.getElementById('developer-tools-input').hidden, true, 'the shared Input textarea is hidden');
  assert.equal(doc.getElementById('developer-tools-input-label').hidden, true);
  assert.equal(doc.getElementById('developer-tools-output').hidden, true, 'the text result is replaced by the table');
  assert.equal(doc.getElementById('developer-slice-ts-value').tagName, 'INPUT');
  const chips = collectElements(doc.getElementById('developer-slice-ts-zones')).filter(node => String(node.className).includes('ok-chip')).map(textOf);
  assert.deepEqual(chips.map(text => text.replace('×', '')), ['UTC']);
  doc.getElementById('developer-slice-ts-add').click();
  assert.equal(doc.getElementById('developer-slice-ts-zone-input').hidden, false);
  doc.getElementById('developer-slice-ts-zone-input').value = 'America/New_York';
  doc.getElementById('developer-slice-ts-zone-input').change();
  doc.getElementById('developer-slice-ts-type').value = 'unix_seconds';
  await slice.run('timestamp_convert', '1700000000');
  assert.equal(ctx.fetchCalls.length, 2);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/time-zones');
  assert.equal(ctx.fetchCalls[1].url, '/api/developer/timestamp-conversions');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { value: '1700000000', input_type: 'unix_seconds', target_zones: ['UTC', 'America/New_York'] });
  const table = collectElements(doc.getElementById('developer-slice-result')).find(node => node.localName === 'table');
  assert.ok(table, 'the result is a table');
  const headers = collectElements(table).filter(node => node.localName === 'th').map(textOf);
  assert.deepEqual(headers, ['Zone', 'Date and time', 'Offset', 'Note']);
  const rows = collectElements(table).filter(node => node.localName === 'tr').slice(1).map(row => collectElements(row).filter(node => node.localName === 'td').map(textOf));
  assert.deepEqual(rows, [
    ['UTC', '2023-11-14T22:13:20.000Z', '+00:00', 'Tuesday'],
    ['America/New_York', '2023-11-14T17:13:20.000-05:00', 'EST -05:00', 'Tuesday · standard time'],
  ]);
});

test('a seconds value that looks like milliseconds offers Read as milliseconds and converts that way', async () => {
  const warned = { ...TIMESTAMP_TABLE_BODY, instant_utc: '7357-01-31T14:13:20Z', warnings: ['magnitude_suggests_milliseconds'] };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse(warned), jsonResponse({ ...TIMESTAMP_TABLE_BODY, warnings: [] })] });
  slice.syncOperation('timestamp_convert');
  doc.getElementById('developer-slice-ts-type').value = 'unix_seconds';
  doc.getElementById('developer-slice-ts-value').value = '170000000000';
  await slice.run('timestamp_convert', '170000000000');
  const link = collectElements(doc.getElementById('developer-slice-result')).find(node => node.localName === 'button' && textOf(node) === 'Read as milliseconds');
  assert.ok(link, 'the action is an in-text link');
  assert.equal(String(link.className).includes('ok-text-link'), true);
  link.click();
  await settle();
  assert.equal(doc.getElementById('developer-slice-ts-type').value, 'unix_milliseconds');
  assert.equal(ctx.fetchCalls.length, 3);
  assert.equal(ctx.fetchCalls[2].url, '/api/developer/timestamp-conversions');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[2].init.body), { value: '170000000000', input_type: 'unix_milliseconds', target_zones: ['UTC'] });
});

test('the DST fold is a segmented Earlier and Later choice with an inline warning when a time is ambiguous', async () => {
  const earlier = { ...TIMESTAMP_TABLE_BODY, conversions: [{ zone: 'America/New_York', local_iso: '2026-11-01T01:30:00-04:00', offset: '-04:00', abbreviation: 'EDT', is_dst: true, weekday: 'Sunday' }] };
  const later = { ...earlier, conversions: [{ ...earlier.conversions[0], local_iso: '2026-11-01T01:30:00-05:00', offset: '-05:00', abbreviation: 'EST', is_dst: false }] };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse({ detail: 'x' }, 422), jsonResponse(earlier), jsonResponse(later), jsonResponse(later)] });
  slice.syncOperation('timestamp_convert');
  doc.getElementById('developer-slice-ts-type').value = 'local_datetime';
  doc.getElementById('developer-slice-ts-source').value = 'America/New_York';
  doc.getElementById('developer-slice-ts-value').value = '2026-11-01T01:30';
  await slice.run('timestamp_convert', '2026-11-01T01:30');
  const host = doc.getElementById('developer-slice-result');
  const warning = collectElements(host).find(node => node.localName === 'div' && String(node.className).includes('ok-dev-alert-warn'));
  assert.match(textOf(warning), /01:30 happens twice in America\/New_York\. Choose which one you mean\./);
  const folds = collectElements(host).filter(node => String(node.className).includes('ok-segment'));
  assert.deepEqual(folds.map(textOf), ['Earlier (-04:00)', 'Later (-05:00)']);
  assert.equal(folds[0].getAttribute('aria-pressed'), 'true');
  folds[1].click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 5);
  assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/time-zones', ...Array(4).fill('/api/developer/timestamp-conversions')]);
  assert.deepEqual(ctx.fetchCalls.slice(1, 4).map(call => JSON.parse(call.init.body).fold), ['reject', 'earlier', 'later']);
  assert.deepEqual(JSON.parse(ctx.fetchCalls[4].init.body), { value: '2026-11-01T01:30', input_type: 'local_datetime', target_zones: ['UTC'], source_zone: 'America/New_York', fold: 'later' });
  assert.equal(doc.getElementById('developer-slice-result').hidden, false);
});

test('a local time in a DST gap keeps the value editable with field guidance and nothing is shifted', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse({ detail: 'x' }, 422), jsonResponse({ detail: 'x' }, 422), jsonResponse({ detail: 'x' }, 422)] });
  slice.syncOperation('timestamp_convert');
  doc.getElementById('developer-slice-ts-type').value = 'local_datetime';
  doc.getElementById('developer-slice-ts-source').value = 'America/New_York';
  await assert.rejects(() => slice.run('timestamp_convert', '2026-03-08T02:30'), { message: slice.MESSAGES.gap });
  assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/time-zones', ...Array(3).fill('/api/developer/timestamp-conversions')]);
  assert.deepEqual(ctx.fetchCalls.slice(1).map(call => JSON.parse(call.init.body).fold), ['reject', 'earlier', 'later']);
  assert.equal(JSON.parse(ctx.fetchCalls[1].init.body).value, '2026-03-08T02:30');
  const value = doc.getElementById('developer-slice-ts-value');
  const guidance = doc.getElementById('developer-slice-ts-gap-guidance');
  assert.equal(value.getAttribute('aria-invalid'), 'true');
  assert.equal(value.getAttribute('aria-describedby'), 'developer-slice-ts-gap-guidance');
  assert.match(guidance.textContent, /does not exist in America\/New_York because clocks move forward/);
  assert.equal(guidance.hidden, false);
  assert.equal(guidance.getAttribute('data-officekit-no-bug-report'), 'true');
  assert.equal(doc.getElementById('developer-slice-result').hidden, true, 'a correctable gap is not shown as a result failure');
  value.value = '2026-03-08T03:30';
  value.input();
  assert.equal(value.getAttribute('aria-invalid'), null, 'editing clears invalid state');
  assert.equal(guidance.hidden, true, 'editing clears field guidance');
});

test('Clear on Text metrics empties the stat grid and hides the result (UX-18)', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ graphemes: 4, code_points: 4, utf8_bytes: 4, utf16_units: 4, words: 1, lines: 1, blank_lines: 0, whitespace: 0, longest_line_graphemes: 4 })] });
  slice.syncOperation('text_metrics');
  await slice.run('text_metrics', 'abcd');
  const host = doc.getElementById('developer-slice-result');
  assert.equal(host.hidden, false);
  assert.ok(collectElements(host).length > 0, 'the stat grid is drawn before Clear');
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/text-analyses');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { text: 'abcd' });
  slice.clear();
  assert.equal(host.hidden, true);
  assert.equal(host.children.length, 0, 'no tile survives Clear');
});

test('Clear on Convert timestamp resets the value, the fold and the zones, and makes no request (UX-18)', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse(TIMESTAMP_TABLE_BODY)] });
  slice.syncOperation('timestamp_convert');
  const chipText = () => collectElements(doc.getElementById('developer-slice-ts-zones')).filter(node => String(node.className).includes('ok-chip')).map(textOf);
  const initialChips = chipText();
  doc.getElementById('developer-slice-ts-add').click();
  doc.getElementById('developer-slice-ts-zone-input').value = 'America/New_York';
  doc.getElementById('developer-slice-ts-zone-input').change();
  doc.getElementById('developer-slice-ts-type').value = 'unix_seconds';
  doc.getElementById('developer-slice-ts-value').value = '1700000000';
  await slice.run('timestamp_convert', '1700000000');
  assert.equal(doc.getElementById('developer-slice-result').hidden, false);
  assert.notDeepEqual(chipText(), initialChips, 'a zone was added before Clear');
  assert.equal(ctx.fetchCalls.length, 2);
  assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/time-zones', '/api/developer/timestamp-conversions']);
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { value: '1700000000', input_type: 'unix_seconds', target_zones: ['UTC', 'America/New_York'] });
  const callsBeforeClear = ctx.fetchCalls.length;
  slice.clear();
  assert.equal(doc.getElementById('developer-slice-result').hidden, true);
  assert.equal(doc.getElementById('developer-slice-ts-value').value, '');
  assert.deepEqual(chipText(), initialChips, 'the zone chips return to the defaults');
  assert.equal(ctx.fetchCalls.length, callsBeforeClear, 'Clear makes no request');
});

test('a failed run after a successful one leaves no stale result, and Run and Clear reset it in the page (UX-18)', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ graphemes: 4, code_points: 4, utf8_bytes: 4, utf16_units: 4, words: 1, lines: 1, blank_lines: 0, whitespace: 0, longest_line_graphemes: 4 }), jsonResponse({ detail: 'x' }, 422)] });
  slice.syncOperation('text_metrics');
  await slice.run('text_metrics', 'abcd');
  const host = doc.getElementById('developer-slice-result');
  assert.equal(host.hidden, false);
  slice.clearResult();
  await assert.rejects(() => slice.run('text_metrics', 'abcd'), { message: slice.MESSAGES.textInput });
  assert.equal(ctx.fetchCalls.length, 2);
  assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/text-analyses', '/api/developer/text-analyses']);
  assert.deepEqual(ctx.fetchCalls.map(call => JSON.parse(call.init.body)), [{ text: 'abcd' }, { text: 'abcd' }]);
  assert.equal(host.hidden, true, 'the failed run shows no previous grid');
  assert.equal(host.children.length, 0);
  const runBody = indexHtml.slice(indexHtml.indexOf('async function runDeveloperTools'), indexHtml.indexOf('async function copyDeveloperToolsResult'));
  assert.match(runBody, /OfficeKitDeveloperSlice\?\.clearResult\(\)/, 'Run clears the previous slice result before it starts');
  const clearBody = indexHtml.slice(indexHtml.indexOf('function clearDeveloperTools'), indexHtml.indexOf('function updateDeveloperToolsMode'));
  assert.match(clearBody, /OfficeKitDeveloperSlice\?\.clear\(\)/, 'Clear resets the slice state');
});

test('after a Convert timestamp result the dock shows exactly Run locally and Copy result, with Download hidden (UX-20)', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse(TIMESTAMP_TABLE_BODY)] });
  slice.syncOperation('timestamp_convert');
  doc.getElementById('developer-slice-ts-type').value = 'unix_seconds';
  await slice.run('timestamp_convert', '1700000000');
  assert.equal(doc.getElementById('developer-slice-result').hidden, false, 'the timestamp table is shown');
  assert.equal(ctx.fetchCalls.length, 2);
  assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/time-zones', '/api/developer/timestamp-conversions']);
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { value: '1700000000', input_type: 'unix_seconds', target_zones: ['UTC'] });
  assert.equal(slice.offersDownload('timestamp_convert'), false, 'the timestamp result is not downloadable');
  assert.equal(slice.offersDownload('text_metrics'), true);
  assert.equal(slice.offersDownload('text_case'), true);
  const dock = indexHtml.match(/<footer id="developer-tools-action-dock"[\s\S]*?<\/footer>/)?.[0] ?? '';
  const dockButtons = [...dock.matchAll(/<button\b[^>]*\bid="([^"]+)"[^>]*>([^<]*)/g)].map(match => ({ id: match[1], label: match[2].trim() }));
  assert.deepEqual(dockButtons.map(button => button.id), ['developer-tools-run', 'developer-tools-copy', 'developer-tools-download']);
  const visible = dockButtons.filter(button => button.id !== 'developer-tools-download' || slice.offersDownload('timestamp_convert')).map(button => button.label);
  assert.deepEqual(visible, ['Run locally', 'Copy result'], 'the approved two-button frame');
  const modeBody = indexHtml.slice(indexHtml.indexOf('function updateDeveloperToolsMode'), indexHtml.indexOf('async function runDeveloperTools'));
  const runBody = indexHtml.slice(indexHtml.indexOf('async function runDeveloperTools'), indexHtml.indexOf('async function copyDeveloperToolsResult'));
  // Each function sets Download's hidden state exactly once, and that assignment is driven by !offersDownload,
  // so an added `.hidden = false` (un-hiding Download on timestamp) turns this red (QA-12).
  // A mode change and a failed run only ever hide Download; a successful run shows it only when !offersDownload is false.
  for (const [name, body] of [['updateDeveloperToolsMode', modeBody], ['runDeveloperTools', runBody]]) {
    assert.doesNotMatch(body, /developer-tools-download'\)\.hidden\s*=\s*false/, `${name} never un-hides Download unconditionally`);
  }
  assert.match(modeBody, /developer-tools-download'\)\.hidden\s*=\s*true;/, 'a mode change hides Download until a result exists');
  assert.equal(runBody.match(/developer-tools-download'\)\.hidden\s*=\s*!offersDownload;/g)?.length, 1, 'runDeveloperTools drives Download from !offersDownload exactly once');
});

test('change case shows the length hint and keeps the text result', () => {
  const { slice, doc } = loadSlice();
  slice.syncOperation('text_case');
  assert.equal(doc.getElementById('developer-tools-hint').textContent, 'Some characters change length, for example ß becomes SS.');
  assert.equal(doc.getElementById('developer-tools-output').hidden, false);
  assert.equal(doc.getElementById('developer-tools-output-label').hidden, false);
});

test('the client text limit counts UTF-8 bytes, so a paste the server would refuse is refused before any request (PM-6)', async () => {
  const { slice, ctx } = loadSlice();
  // 349,526 three-byte characters: 349,526 code points (under the code-point count) but 1,048,578 UTF-8 bytes.
  await assert.rejects(() => slice.run('text_case', '€'.repeat(349_526)), { message: slice.MESSAGES.textInput });
  assert.equal(ctx.fetchCalls.length, 0);
});

test('case conversion sends the selected style and locale', async () => {
  const { slice, ctx, doc } = loadSlice({ fetchResponses: [jsonResponse({ result: 'İSTANBUL', style: 'upper', locale: 'tr' })] });
  slice.syncOperation('text_case');
  doc.getElementById('developer-slice-case-style').value = 'upper';
  doc.getElementById('developer-slice-case-locale').value = 'tr';
  assert.equal(await slice.run('text_case', 'istanbul'), 'İSTANBUL');
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/text-case-conversions');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { text: 'istanbul', style: 'upper', locale: 'tr' });
});

test('JSON compare renders each change with textContent and reports the counts', async () => {
  const body = {
    equal: false,
    changes: [{ path: '/a', kind: 'changed', before: '1', after: '2' }],
    truncated: false,
    counts: { added: 0, removed: 0, changed: 1, type_changed: 0 },
  };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(body)] });
  slice.openView('compare-json');
  doc.getElementById('developer-compare-original').value = '{"a":1}';
  doc.getElementById('developer-compare-changed').value = '{"a":2}';
  doc.getElementById('developer-compare-run').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/json-diffs');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { original: '{"a":1}', changed: '{"a":2}', array_order: 'ordered', numeric: 'value' });
  const paths = collectElements(doc.getElementById('developer-compare-results')).filter(node => node.localName === 'td').map(textOf);
  assert.deepEqual(paths, ['/a', 'changed', '1 → 2']);
  assert.equal(doc.getElementById('developer-compare-status').textContent, 'Compared locally. 1 difference.');
});

test('malformed JSON Compare input stays editable, shows linked guidance and recovers without a bug report', async () => {
  const equalResult = { equal: true, changes: [], truncated: false, counts: { added: 0, removed: 0, changed: 0, type_changed: 0 } };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(equalResult)] });
  slice.openView('compare-json');
  const original = doc.getElementById('developer-compare-original');
  const guidance = doc.getElementById('developer-compare-original-guidance');
  original.value = '{';
  doc.getElementById('developer-compare-changed').value = '{}';
  doc.getElementById('developer-compare-run').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 0);
  assert.equal(original.getAttribute('aria-invalid'), 'true');
  assert.equal(original.getAttribute('aria-describedby'), 'developer-compare-original-guidance');
  assert.match(guidance.textContent, /incomplete or invalid/);
  assert.equal(guidance.hidden, false);
  assert.equal(guidance.getAttribute('data-officekit-no-bug-report'), 'true');
  assert.equal(doc.getElementById('developer-compare-status').textContent, 'Correct the highlighted JSON before comparing.');
  assert.equal(doc.getElementById('developer-compare-status').dataset.officekitNoBugReport, 'true');
  assert.equal(doc.getElementById('developer-compare-results').children.length, 0);
  assert.equal(doc.getElementById('developer-compare-copy').hidden, true);
  assert.equal(doc.getElementById('developer-compare-download').hidden, true);
  assertWithinButtonLimit(visibleButtons(doc.getElementById('developer-compare-panel')), 'JSON Compare local validation');
  original.value = '{"a":1}';
  original.input();
  assert.equal(original.getAttribute('aria-invalid'), null);
  assert.equal(guidance.hidden, true);
  assert.equal(doc.getElementById('developer-compare-status').textContent, '');
  doc.getElementById('developer-compare-run').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(doc.getElementById('developer-compare-status').textContent, 'Compared locally. No differences.');
  assert.equal(doc.getElementById('developer-compare-copy').hidden, false);
  assert.equal(doc.getElementById('developer-compare-download').hidden, false);
});

test('a server JSON refusal shows the fixed message without echoing parser details', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ detail: 'ZZ-ECHO-MARKER' }, 422)] });
  slice.openView('compare-json');
  doc.getElementById('developer-compare-original').value = '{"a":1}';
  doc.getElementById('developer-compare-changed').value = '{}';
  doc.getElementById('developer-compare-run').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 1, 'valid syntax reaches the local service');
  assert.equal(doc.getElementById('developer-compare-status').textContent, slice.MESSAGES.json);
  assert.equal(doc.getElementById('developer-compare-status').className.includes('ok-dev-error'), true);
  assert.equal(textOf(doc.getElementById('developer-compare-results')), slice.MESSAGES.json);
});

test('JSON result is a Path, Change and Original → Changed table with a summary, and options sit in one Details', () => {
  const body = {
    equal: false,
    changes: [{ path: '/active', kind: 'type_changed', before: 'true', after: '1' }, { path: '/note', kind: 'removed', before: 'null', after: null }],
    truncated: false,
    counts: { added: 0, removed: 1, changed: 0, type_changed: 1 },
  };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(body)] });
  slice.openView('compare-json');
  doc.getElementById('developer-compare-original').value = '{}';
  doc.getElementById('developer-compare-changed').value = '{}';
  doc.getElementById('developer-compare-run').click();
  return settle().then(() => {
    assert.equal(ctx.fetchCalls.length, 1);
    assert.equal(ctx.fetchCalls[0].url, '/api/developer/json-diffs');
    assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { original: '{}', changed: '{}', array_order: 'ordered', numeric: 'value' });
    const results = doc.getElementById('developer-compare-results');
    const headers = collectElements(results).filter(node => node.localName === 'th').map(textOf);
    assert.deepEqual(headers, ['Path', 'Change', 'Original → Changed']);
    assert.equal(textOf(collectElements(results).find(node => node.localName === 'span')), 'type changed');
    assert.match(textOf(results), /2 differences · keys reordered \(ignored\)/);
    assert.equal(textOf(collectElements(results).filter(node => node.localName === 'td').at(-1)), 'null → (missing)');
    assert.equal(doc.getElementById('developer-compare-json-details').getAttribute('open'), '');
    assert.equal(doc.getElementById('developer-compare-text-details').getAttribute('open'), null);
    assert.equal(doc.getElementById('developer-compare-text-details').hidden, true);
  });
});

test('Swap exchanges the two inputs and Copy and Download follow the mode', async () => {
  const { slice, doc } = loadSlice();
  slice.openView('compare-json');
  doc.getElementById('developer-compare-original').value = 'left';
  doc.getElementById('developer-compare-changed').value = 'right';
  doc.getElementById('developer-compare-swap').click();
  assert.equal(doc.getElementById('developer-compare-original').value, 'right');
  assert.equal(doc.getElementById('developer-compare-changed').value, 'left');
  assert.equal(doc.getElementById('developer-compare-copy').textContent, 'Copy differences');
  assert.equal(doc.getElementById('developer-compare-download').textContent, 'Download JSON');
  assert.equal(doc.getElementById('developer-compare-format').hidden, true);
  doc.querySelectorAll('[data-compare-mode]').find(node => node.dataset.compareMode === 'text').click();
  assert.equal(doc.getElementById('developer-compare-copy').textContent, 'Copy patch');
  assert.equal(doc.getElementById('developer-compare-format').hidden, false);
  assert.equal(doc.getElementById('developer-compare-text-details').hidden, false);
  assert.equal(doc.getElementById('developer-compare-text-details').getAttribute('open'), null, 'text options are closed by default');
  assert.equal(doc.getElementById('developer-compare-json-details').hidden, true);
});

test('changing a Text Diff option retains the old comparison but pauses Copy and Download', async () => {
  const body = {
    equal: false,
    rows: [{ op: 'change', left_no: 1, right_no: 1, left: 'old', right: 'new' }],
    patch: '--- original\n+++ changed\n-old\n+new\n',
    stats: { inserted: 0, deleted: 0, changed: 1 },
  };
  const recoveredBody = {
    ...body,
    rows: [{ op: 'change', left_no: 1, right_no: 1, left: 'old', right: 'cosmos' }],
    patch: '--- original\n+++ changed\n-old\n+cosmos\n',
  };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(body), jsonResponse(recoveredBody)] });
  slice.openView('compare-text');
  doc.getElementById('developer-compare-original').value = 'old';
  doc.getElementById('developer-compare-changed').value = 'new';
  doc.getElementById('developer-compare-run').click();
  await settle();

  const results = doc.getElementById('developer-compare-results');
  const copy = doc.getElementById('developer-compare-copy');
  const download = doc.getElementById('developer-compare-download');
  assert.equal(copy.disabled, false);
  assert.equal(download.disabled, false);
  assert.match(textOf(results), /old/);
  assert.match(textOf(results), /new/);

  const changed = doc.getElementById('developer-compare-changed');
  changed.value = 'cosmos';
  changed.input();
  assert.match(textOf(results), /Inputs changed — compare again to update\./);
  assert.equal(copy.disabled, true);
  assert.equal(download.disabled, true);
  assert.equal(doc.getElementById('developer-compare-status').textContent, 'Inputs changed. Compare again to update the result.');
  doc.getElementById('developer-compare-run').click();
  await settle();
  assert.equal(copy.disabled, false);
  assert.equal(download.disabled, false);
  assert.match(textOf(results), /cosmos/);

  const whitespace = doc.getElementById('developer-compare-whitespace');
  whitespace.value = 'ignore_all';
  whitespace.change();
  assert.match(textOf(results), /Inputs changed — compare again to update\./);
  assert.match(textOf(results), /old/);
  assert.match(textOf(results), /cosmos/);
  assert.equal(copy.disabled, true);
  assert.equal(download.disabled, true);
  assert.equal(doc.getElementById('developer-compare-status').textContent, 'Inputs changed. Compare again to update the result.');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), {
    original: 'old', changed: 'new', whitespace: 'exact', line_endings: 'normalize', unicode_nfc: false,
  });
});

test('UUID generation lists each identifier as text and enables the export actions', async () => {
  const uuids = ['0190b7a0-0000-7000-8000-000000000001', '0190b7a0-0000-7000-8000-000000000002'];
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ uuids, version: 7, count: 2 })] });
  slice.openView('uuid');
  doc.getElementById('developer-uuid-version').value = '7';
  doc.getElementById('developer-uuid-count').value = '2';
  doc.getElementById('developer-uuid-generate').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/uuids');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { version: 7, count: 2, case: 'lower', style: 'canonical' });
  const items = collectElements(doc.getElementById('developer-uuid-list')).filter(node => node.localName === 'li');
  assert.deepEqual(items.map(textOf), uuids);
  assert.equal(doc.getElementById('developer-uuid-copy').disabled, false);
  assert.equal(doc.getElementById('developer-uuid-download').disabled, false);
  assert.match(doc.getElementById('developer-uuid-status').textContent, /Generated 2 UUIDs/);
});

test('UUID v5 fixes How many at 1 and disables the field until another version is chosen', () => {
  const { slice, doc } = loadSlice();
  slice.openView('uuid');
  const version = doc.getElementById('developer-uuid-version');
  const count = doc.getElementById('developer-uuid-count');
  version.value = '5';
  version.change();
  assert.equal(count.value, '1');
  assert.equal(count.disabled, true);
  version.value = '7';
  version.change();
  assert.equal(count.disabled, false);
});

test('leaving UUID v5 restores the How many count that was set before it (UX-19)', () => {
  const { slice, doc } = loadSlice();
  slice.openView('uuid');
  const version = doc.getElementById('developer-uuid-version');
  const count = doc.getElementById('developer-uuid-count');
  count.value = '7';
  version.value = '5';
  version.change();
  assert.equal(count.value, '1');
  assert.equal(count.disabled, true);
  version.value = '4';
  version.change();
  assert.equal(count.disabled, false);
  assert.equal(count.value, '7', 'the count the user chose before v5 comes back');
});

test('the Custom UUID namespace slot keeps its space with visibility, not hidden, so nothing moves (UX-12)', () => {
  const { slice, doc } = loadSlice();
  slice.openView('uuid');
  const wrap = doc.getElementById('developer-uuid-custom-wrap');
  const namespace = doc.getElementById('developer-uuid-namespace');
  const version = doc.getElementById('developer-uuid-version');
  assert.equal(wrap.hidden, false, 'the slot is never display:none');
  assert.equal(String(wrap.className).includes('ok-dev-invisible'), true, 'v7 keeps the slot reserved');
  version.value = '5';
  version.change();
  assert.equal(wrap.hidden, false);
  assert.equal(String(wrap.className).includes('ok-dev-invisible'), true, 'v5 with a preset namespace keeps the slot reserved');
  namespace.value = 'custom';
  namespace.change();
  assert.equal(String(wrap.className).includes('ok-dev-invisible'), false, 'Custom UUID shows the field in the reserved slot');
});

test('UUID out-of-range input is rejected locally with the batch message', async () => {
  const { slice, doc, ctx } = loadSlice();
  slice.openView('uuid');
  doc.getElementById('developer-uuid-count').value = '1001';
  doc.getElementById('developer-uuid-generate').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(doc.getElementById('developer-uuid-status').textContent, slice.MESSAGES.uuid);
  assert.equal(ctx.fetchCalls.length, 0);
});

test('QR generation previews PNG as a data URL and enables download', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ format: 'png', data: 'iVBORw0KGgo=', qr_version: 1, modules: 21, payload_bytes: 19, size_px: 512 })] });
  slice.openView('qr');
  doc.getElementById('developer-qr-payload').value = 'https://example.com';
  doc.getElementById('developer-qr-ecc').value = 'M';
  doc.getElementById('developer-qr-size').value = '512';
  doc.getElementById('developer-qr-format').value = 'png';
  doc.getElementById('developer-qr-generate').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/qr-codes');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { payload: 'https://example.com', error_correction: 'M', size_px: 512, format: 'png' });
  const image = collectElements(doc.getElementById('developer-qr-preview')).find(node => node.localName === 'img');
  assert.ok(image);
  assert.equal(image.getAttribute('src'), 'data:image/png;base64,iVBORw0KGgo=');
  assert.equal(doc.getElementById('developer-qr-download').disabled, false);
});

test('UUID keeps the approved hint, defaults to v7, and tucks Letters and Format into a closed Details', () => {
  const { slice, doc } = loadSlice();
  slice.openView('uuid');
  assert.equal(doc.getElementById('developer-uuid-version').value, '7', 'v7 is the default version');
  assert.match(doc.getElementById('developer-uuid-hint').textContent, /v7 sorts by creation time and includes it, so do not use v7 where the creation time should stay private/);
  const details = doc.getElementById('developer-uuid-details');
  assert.equal(details.getAttribute('open'), null, 'Letters and Format stay closed');
  assert.ok(doc.getElementById('developer-uuid-letters') && doc.getElementById('developer-uuid-style'));
  assert.equal(doc.getElementById('developer-uuid-clear').className, 'ok-text-link');
});

test('UUID v5 fields keep their slot when hidden, so Generate and the dock do not move (UX-12)', () => {
  const { slice, doc } = loadSlice();
  slice.openView('uuid');
  const v5 = doc.getElementById('developer-uuid-v5');
  assert.equal(v5.hidden, false, 'the slot is not display:none');
  assert.equal(String(v5.className).includes('ok-dev-invisible'), true, 'v7 keeps the v5 slot reserved');
  doc.getElementById('developer-uuid-version').value = '5';
  doc.getElementById('developer-uuid-version').change();
  assert.equal(String(v5.className).includes('ok-dev-invisible'), false);
});

test('UUID Clear empties the list and leaves the version and count as they are', async () => {
  const uuids = ['a-1', 'a-2'];
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ uuids, version: 7, count: 2 })] });
  slice.openView('uuid');
  doc.getElementById('developer-uuid-count').value = '2';
  doc.getElementById('developer-uuid-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/uuids');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { version: 7, count: 2, case: 'lower', style: 'canonical' });
  doc.getElementById('developer-uuid-clear').click();
  assert.equal(ctx.fetchCalls.length, 1, 'Clear makes no request');
  assert.equal(collectElements(doc.getElementById('developer-uuid-list')).filter(node => node.localName === 'li').length, 0);
  assert.equal(doc.getElementById('developer-uuid-download').disabled, true);
  assert.equal(doc.getElementById('developer-uuid-count').value, '2');
});

test('UUID download uses the chosen format and is attached to the document only while it is clicked', async () => {
  const saved = [];
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ uuids: ['x', 'y'], version: 7, count: 2 })] });
  ctx.URL.createObjectURL = () => 'blob:csv';
  slice.openView('uuid');
  doc.getElementById('developer-uuid-count').value = '2';
  doc.getElementById('developer-uuid-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/uuids');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { version: 7, count: 2, case: 'lower', style: 'canonical' });
  doc.getElementById('developer-uuid-format').value = 'csv';
  doc.getElementById('developer-uuid-download').click();
  const anchor = doc.all.filter(node => node.localName === 'a').at(-1);
  assert.equal(anchor.download, 'officekit-uuids.csv');
  assert.equal(anchor.attachedAtClick, true, 'the anchor is in the document when click() runs (CR-9)');
  assert.equal(anchor.parentNode, null, 'the anchor is removed afterwards');
  saved.push(anchor.href);
  assert.deepEqual(saved, ['blob:csv']);
});

test('QR Create QR code, Copy image and Download follow the approved wording, and the server size is shown', async () => {
  const writes = [];
  const clipboard = { writeText: async () => {}, write: async items => { writes.push(items); } };
  const { slice, doc, ctx } = loadSlice({ clipboard, fetchResponses: [jsonResponse({ format: 'png', data: 'iVBORw0KGgo=', size_px: 300 })] });
  slice.openView('qr');
  assert.equal(doc.getElementById('developer-qr-generate').textContent, 'Create QR code');
  assert.equal(doc.getElementById('developer-qr-copy').textContent, 'Copy image');
  assert.equal(doc.getElementById('developer-qr-copy').disabled, true);
  doc.getElementById('developer-qr-payload').value = 'https://example.com';
  doc.getElementById('developer-qr-size').value = '512';
  doc.getElementById('developer-qr-ecc').value = 'M';
  doc.getElementById('developer-qr-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/qr-codes');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { payload: 'https://example.com', error_correction: 'M', size_px: 512, format: 'png' });
  const image = collectElements(doc.getElementById('developer-qr-preview')).find(node => node.localName === 'img');
  assert.equal(image.getAttribute('width'), '300', 'the preview uses the size the server returned, not the size requested (CR-6)');
  assert.equal(doc.getElementById('developer-qr-copy').disabled, false);
  doc.getElementById('developer-qr-copy').click();
  await settle();
  assert.equal(writes.length, 1);
  assert.equal(writes[0][0].items['image/png'].type, 'image/png');
});

test('QR capacity meter reports the bytes used against the chosen error-correction limit', () => {
  const { slice, doc } = loadSlice();
  slice.openView('qr');
  doc.getElementById('developer-qr-payload').value = 'é'.repeat(10);
  doc.getElementById('developer-qr-ecc').value = 'H';
  doc.getElementById('developer-qr-payload').listeners.input?.forEach(handler => handler({ target: doc.getElementById('developer-qr-payload') }));
  for (const handler of doc.getElementById('developer-qr-ecc').listeners.change || []) handler({});
  assert.equal(doc.getElementById('developer-qr-capacity-text').textContent, '20 of 1,273 bytes at High error correction.');
  assert.equal(doc.getElementById('developer-qr-meter').value, '20');
});

test('copy denial raises an error toast through the global toast', async () => {
  const toasts = [];
  const { slice, doc } = loadSlice({ toasts, clipboard: { writeText: async () => { throw new Error('denied'); } } });
  slice.openView('uuid');
  doc.getElementById('developer-uuid-copy').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(toasts.at(-1), { message: slice.MESSAGES.copyDenied, state: 'error' });
  assert.equal(doc.getElementById('developer-uuid-status').textContent, slice.MESSAGES.copyDenied);
});

test('copy success writes the list and raises a success toast', async () => {
  const toasts = [];
  const written = [];
  const { slice, doc } = loadSlice({ toasts, clipboard: { writeText: async text => { written.push(text); } }, fetchResponses: [jsonResponse({ uuids: ['x', 'y'], version: 4, count: 2 })] });
  slice.openView('uuid');
  doc.getElementById('developer-uuid-count').value = '2';
  doc.getElementById('developer-uuid-version').value = '4';
  doc.getElementById('developer-uuid-generate').click();
  await new Promise(resolve => setImmediate(resolve));
  doc.getElementById('developer-uuid-copy').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(written, ['x\ny']);
  assert.deepEqual(toasts.at(-1), { message: slice.MESSAGES.copied, state: 'success' });
});

// ---- escaping (P-011) --------------------------------------------------------

const MARKUP = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

test('hostile markup in diff rows, highlights and JSON paths is rendered as text only', () => {
  const { slice } = loadSlice();
  const rows = [{ op: 'change', left_no: 1, right_no: 1, left: MARKUP, right: MARKUP, left_spans: [{ start: 0, end: 4 }], right_spans: null }];
  for (const layout of ['side', 'unified']) {
    const nodes = slice.textRowNodes(rows, layout);
    const elements = nodes.flatMap(node => collectElements(node));
    assert.equal(elements.some(node => node.localName === 'img' || node.localName === 'script'), false, `${layout} has no injected elements`);
    assert.ok(nodes.some(node => textOf(node).includes(MARKUP)), `${layout} shows the raw text`);
  }
  const changes = slice.jsonChangeNodes({ changes: [{ path: `/${MARKUP}`, kind: 'changed', before: MARKUP, after: MARKUP }] });
  assert.equal(collectElements(changes[0]).some(node => node.localName === 'img' || node.localName === 'script'), false);
  assert.ok(textOf(changes[0]).includes(`/${MARKUP}`));
});

test('span highlights split on code points and never create markup from the text', () => {
  const { slice } = loadSlice();
  const parts = slice.spanNodes('a👩‍👩‍👧b', [{ start: 1, end: 2 }], 'mark-class');
  assert.equal(parts[0], 'a');
  assert.equal(parts[1].localName, 'mark');
  assert.equal(parts[1].textContent, '👩');
  assert.equal(slice.spanNodes('plain', null, 'x').join(''), 'plain');
});

test('the slice module never builds markup from strings', () => {
  for (const pattern of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/]) {
    assert.equal(pattern.test(sliceSource), false, `${pattern} is not used`);
  }
});

test('an SVG QR preview is an img with a Blob URL and is never inlined', () => {
  const { slice, doc } = loadSlice({ fetchResponses: [jsonResponse({ format: 'svg', data: MARKUP, qr_version: 1, modules: 21, payload_bytes: 4, size_px: 512 })] });
  slice.openView('qr');
  doc.getElementById('developer-qr-payload').value = 'https://example.com';
  doc.getElementById('developer-qr-generate').click();
  return new Promise(resolve => setImmediate(resolve)).then(() => {
    const image = collectElements(doc.getElementById('developer-qr-preview')).find(node => node.localName === 'img');
    assert.ok(image, 'SVG preview is an img, never inlined');
    assert.equal(image.getAttribute('src'), 'blob:test');
    assert.equal(collectElements(doc.getElementById('developer-qr-preview')).some(node => node.localName === 'svg'), false);
  });
});

// ---- button limit (AGENTS.md "Button Limit") ---------------------------------
// At most three visible buttons per screen. Tabs and segmented toggles (ok-segment), in-text links
// (ok-text-link) and row actions (ok-row-action) are not counted. Disabled buttons still count.

const BUTTON_LIMIT = 3;
const UNCOUNTED_BUTTON_CLASSES = ['ok-text-link', 'ok-segment', 'ok-row-action'];
const indexHtml = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');

function isUncounted(classes) {
  return UNCOUNTED_BUTTON_CLASSES.some(name => classes.includes(name));
}

function labelOf(button) {
  return textOf(button).trim() || button.getAttribute('aria-label') || '(unlabelled)';
}

function visibleButtons(root) {
  const hiddenWithin = node => {
    for (let current = node; current && current !== root.parentNode; current = current.parentNode) {
      if (current.hidden) return true;
    }
    return false;
  };
  return collectElements(root)
    .filter(node => node.localName === 'button' && !hiddenWithin(node) && !isUncounted(node.className.split(/\s+/)))
    .map(labelOf);
}

// The developer dock and panel are static markup in index.html, which the Node harness does not render.
// Their visible buttons are read from that markup. A shared result row mounted into the dock adds two
// buttons (copy and download) once a result exists, so each mount call is counted as those two.
function staticDeveloperButtons() {
  const panelStart = indexHtml.indexOf('<section id="developer-tools-panel"');
  const panel = indexHtml.slice(panelStart, indexHtml.indexOf('</section>', panelStart));
  const dockStart = indexHtml.indexOf('<footer id="developer-tools-action-dock"');
  const dock = indexHtml.slice(dockStart, indexHtml.indexOf('</footer>', dockStart));
  const labels = [];
  for (const match of `${panel}${dock}`.matchAll(/<button\b([^>]*)>([^<]*)/g)) {
    if (/\shidden(\s|=|$)/.test(match[1])) continue;
    const classes = (match[1].match(/class="([^"]*)"/)?.[1] ?? '').split(/\s+/);
    if (isUncounted(classes)) continue;
    labels.push(match[2].trim() || 'button');
  }
  return labels;
}

function assertWithinButtonLimit(labels, state) {
  assert.ok(labels.length <= BUTTON_LIMIT, `${state}: ${labels.length} visible buttons, limit ${BUTTON_LIMIT}: ${labels.join(' | ')}`);
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const TIMESTAMP_BODY = {
  instant_utc: '2023-11-14T22:13:20Z',
  unix_seconds: '1700000000',
  unix_milliseconds: '1700000000000',
  unix_microseconds: '1700000000000000',
  conversions: [{ zone: 'UTC', local_iso: '2023-11-14T22:13:20+00:00', offset: '+00:00', abbreviation: 'UTC', is_dst: false, weekday: 'Tuesday' }],
  warnings: [],
};

test('developer utilities dock stays within three buttons in every operation and result state', async () => {
  const cases = [
    {
      operation: 'text_metrics',
      input: 'Café',
      responses: [jsonResponse({ graphemes: 4, code_points: 4, utf8_bytes: 5, utf16_units: 4, words: 1, lines: 1, blank_lines: 0, whitespace: 0, longest_line_graphemes: 4 })],
      urls: ['/api/developer/text-analyses'],
      bodies: [{ text: 'Café' }],
    },
    {
      operation: 'text_case',
      input: 'istanbul',
      responses: [jsonResponse({ result: 'İSTANBUL' })],
      setup: doc => {
        doc.getElementById('developer-slice-case-style').value = 'upper';
        doc.getElementById('developer-slice-case-locale').value = 'root';
      },
      urls: ['/api/developer/text-case-conversions'],
      bodies: [{ text: 'istanbul', style: 'upper', locale: 'root' }],
    },
    {
      operation: 'timestamp_convert',
      input: '1700000000000',
      responses: [jsonResponse({ zones: ['UTC'] }), jsonResponse(TIMESTAMP_BODY)],
      setup: doc => { doc.getElementById('developer-slice-ts-type').value = 'unix_milliseconds'; },
      urls: ['/api/developer/time-zones', '/api/developer/timestamp-conversions'],
      bodies: [{ value: '1700000000000', input_type: 'unix_milliseconds', target_zones: ['UTC'] }],
    },
  ];
  for (const scenario of cases) {
    const { slice, doc, ctx } = loadSlice({ fetchResponses: scenario.responses });
    slice.syncOperation(scenario.operation);
    scenario.setup?.(doc);
    const fields = doc.getElementById('developer-slice-fields');
    const resultArea = doc.getElementById('developer-slice-result');
    assertWithinButtonLimit([...staticDeveloperButtons(), ...visibleButtons(fields), ...visibleButtons(resultArea)], `${scenario.operation}, no result`);
    await slice.run(scenario.operation, scenario.input);
    assert.deepEqual(ctx.fetchCalls.map(call => call.url), scenario.urls, `${scenario.operation}: request URLs`);
    assert.deepEqual(ctx.fetchCalls.filter(call => call.init?.body).map(call => JSON.parse(call.init.body)), scenario.bodies, `${scenario.operation}: request bodies`);
    assertWithinButtonLimit([...staticDeveloperButtons(), ...visibleButtons(fields), ...visibleButtons(resultArea)], `${scenario.operation}, with result`);
  }
});

test('timestamp DST fold states (ambiguous warning and gap error) stay within three buttons', async () => {
  const ambiguous = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse({ detail: 'x' }, 422), jsonResponse(TIMESTAMP_BODY), jsonResponse(TIMESTAMP_BODY)] });
  const gap = loadSlice({ fetchResponses: [jsonResponse({ zones: ['UTC'] }), jsonResponse({ detail: 'x' }, 422), jsonResponse({ detail: 'x' }, 422), jsonResponse({ detail: 'x' }, 422)] });
  for (const { slice, doc, ctx } of [ambiguous, gap]) {
    slice.syncOperation('timestamp_convert');
    doc.getElementById('developer-slice-ts-type').value = 'local_datetime';
    doc.getElementById('developer-slice-ts-source').value = 'America/New_York';
    await slice.run('timestamp_convert', '2026-11-01T01:30').catch(() => {});
    assert.deepEqual(ctx.fetchCalls.map(call => call.url), ['/api/developer/time-zones', ...Array(3).fill('/api/developer/timestamp-conversions')], 'DST probe: zones, then reject, earlier and later');
    assert.deepEqual(ctx.fetchCalls.slice(1).map(call => JSON.parse(call.init.body).fold), ['reject', 'earlier', 'later']);
    assertWithinButtonLimit([...staticDeveloperButtons(), ...visibleButtons(doc.getElementById('developer-slice-fields')), ...visibleButtons(doc.getElementById('developer-slice-result'))], 'timestamp DST fold');
  }
});

test('Compare JSON stays within three buttons with and without a result', async () => {
  const body = { equal: false, changes: [{ path: '/a', kind: 'changed', before: '1', after: '2' }], truncated: false, counts: { added: 0, removed: 0, changed: 1, type_changed: 0 } };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(body)] });
  slice.openView('compare-json');
  const panel = doc.getElementById('developer-compare-panel');
  assertWithinButtonLimit(visibleButtons(panel), 'Compare JSON, no result');
  assert.equal(ctx.fetchCalls.length, 0, 'no request before Compare');
  doc.getElementById('developer-compare-original').value = '{"a":1}';
  doc.getElementById('developer-compare-changed').value = '{"a":2}';
  doc.getElementById('developer-compare-run').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/json-diffs');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { original: '{"a":1}', changed: '{"a":2}', array_order: 'ordered', numeric: 'value' });
  assertWithinButtonLimit(visibleButtons(panel), 'Compare JSON, with result');
});

test('Compare text stays within three buttons with and without a result, in both layouts', async () => {
  const body = { equal: false, rows: [{ op: 'change', left_no: 1, right_no: 1, left: 'a', right: 'b' }], patch: '--- a\n+++ b\n', stats: { inserted: 0, deleted: 0, changed: 1 }, hunks: 1 };
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse(body)] });
  slice.openView('compare-text');
  const panel = doc.getElementById('developer-compare-panel');
  assertWithinButtonLimit(visibleButtons(panel), 'Compare text, no result');
  assert.equal(ctx.fetchCalls.length, 0, 'no request before Compare');
  doc.getElementById('developer-compare-original').value = 'a';
  doc.getElementById('developer-compare-changed').value = 'b';
  doc.getElementById('developer-compare-run').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/text-diffs');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { original: 'a', changed: 'b', whitespace: 'exact', line_endings: 'normalize', unicode_nfc: false });
  assertWithinButtonLimit(visibleButtons(panel), 'Compare text, side by side, with result');
  doc.querySelectorAll('[data-compare-layout]').find(node => node.dataset.compareLayout === 'unified').click();
  assertWithinButtonLimit(visibleButtons(panel), 'Compare text, unified, with result');
  assert.equal(ctx.fetchCalls.length, 1, 'switching the layout makes no request');
});

test('UUID stays within three buttons for v4 and v7 with and without a result, and for v5', async () => {
  const uuids = Array.from({ length: 25 }, (_, index) => `0190b7a0-0000-7000-8000-${String(index).padStart(12, '0')}`);
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ uuids, version: 7, count: 25 }), jsonResponse({ uuids: ['cfbff0d1-9375-5685-968c-48ce8b15ae17'], version: 5, count: 1 })] });
  slice.openView('uuid');
  const panel = doc.getElementById('developer-uuid-panel');
  assertWithinButtonLimit(visibleButtons(panel), 'UUID v7, no result');
  doc.getElementById('developer-uuid-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/uuids');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { version: 7, count: 25, case: 'lower', style: 'canonical' });
  assertWithinButtonLimit(visibleButtons(panel), 'UUID v7, with result');
  doc.getElementById('developer-uuid-version').value = '4';
  doc.getElementById('developer-uuid-version').change();
  assertWithinButtonLimit(visibleButtons(panel), 'UUID v4, after switching');
  assert.equal(ctx.fetchCalls.length, 1, 'switching the version makes no request');
  doc.getElementById('developer-uuid-version').value = '5';
  doc.getElementById('developer-uuid-version').change();
  assertWithinButtonLimit(visibleButtons(panel), 'UUID v5, no result');
  doc.getElementById('developer-uuid-name').value = 'example';
  doc.getElementById('developer-uuid-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 2);
  assert.equal(ctx.fetchCalls[1].url, '/api/developer/uuids');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { version: 5, count: 1, namespace: 'dns', name: 'example', case: 'lower', style: 'canonical' });
  assertWithinButtonLimit(visibleButtons(panel), 'UUID v5, with result');
});

// ---- tokens, compact layout and touch targets (UX-5, UX-9, UX-10) -------------

const developerCss = fs.readFileSync(path.join(repoRoot, 'assets', 'officekit-slice-developer.css'), 'utf8');
const shellCss = fs.readFileSync(path.join(repoRoot, 'assets', 'officekit.input.css'), 'utf8');
const RAW_PALETTE = /\b(?:bg|text|border|divide|ring|from|to)-(?:white|black|slate|gray|zinc|neutral|indigo|rose|emerald|amber|red|green|sky|blue)(?:-\d{2,3})?\b|\btext-xl\b/;

function developerPanelMarkup() {
  const start = indexHtml.indexOf('<section id="developer-tools-panel"');
  const end = indexHtml.indexOf('</footer>', indexHtml.indexOf('<footer id="developer-tools-action-dock"'));
  return indexHtml.slice(start, end);
}

test('developer panels use the --ok-* tokens and no raw Tailwind palette classes', () => {
  assert.equal(RAW_PALETTE.test(sliceSource), false, `slice JS: ${sliceSource.match(RAW_PALETTE)?.[0]}`);
  assert.equal(RAW_PALETTE.test(developerPanelMarkup()), false, `index.html developer panel: ${developerPanelMarkup().match(RAW_PALETTE)?.[0]}`);
  assert.match(developerCss, /var\(--ok-accent\)/);
});

test('stat values and badges use the type scale tokens, not a pixel size outside it (UX-17)', () => {
  const statRule = developerCss.match(/\.ok-dev-stat b\s*\{([^}]*)\}/)?.[1] ?? '';
  const badgeRule = developerCss.match(/\.ok-dev-badge\s*\{([^}]*)\}/)?.[1] ?? '';
  assert.match(statRule, /font-size:\s*var\(--ok-text-lg\)/, '22px is not a scale step; the stat value uses --ok-text-lg (18px)');
  assert.match(badgeRule, /font-size:\s*var\(--ok-text-xs\)/, '11px is below the 12px floor; the badge uses --ok-text-xs');
  assert.doesNotMatch(statRule, /font-size:\s*\d+px/);
  assert.doesNotMatch(badgeRule, /font-size:\s*\d+px/);
});

test('panel titles sit on the 28px --ok-title token', () => {
  assert.match(developerCss, /\.ok-dev-title\s*\{[^}]*font-size:\s*var\(--ok-title\)/);
});

test('compact width (600px and below) shows unified results only, and the layout toggle is not offered', () => {
  const { slice } = loadSlice();
  assert.equal(slice.layoutFor(600, 'side'), 'unified');
  assert.equal(slice.layoutFor(320, 'side'), 'unified');
  assert.equal(slice.layoutFor(601, 'side'), 'side');
  assert.equal(slice.layoutFor(601, 'unified'), 'unified');
});

test('buttons, toggles and in-text links reach 44px at 900px and below', () => {
  const block = developerCss.match(/@media \(max-width:\s*900px\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? '';
  assert.match(block, /min-height:\s*44px/);
  for (const selector of ['.ok-dev-panel button', '.ok-segment', '.ok-text-link', '#developer-tools-action-dock button']) {
    assert.ok(block.includes(selector), `${selector} is sized in the 900px rule`);
  }
});

test('QR stays within three buttons for PNG and SVG with and without a result', async () => {
  const { slice, doc, ctx } = loadSlice({ fetchResponses: [jsonResponse({ format: 'png', data: 'iVBORw0KGgo=', size_px: 512 }), jsonResponse({ format: 'svg', data: '<svg/>', size_px: 512 })] });
  slice.openView('qr');
  const panel = doc.getElementById('developer-qr-panel');
  assertWithinButtonLimit(visibleButtons(panel), 'QR PNG, no result');
  doc.getElementById('developer-qr-payload').value = 'https://example.com';
  doc.getElementById('developer-qr-ecc').value = 'M';
  doc.getElementById('developer-qr-size').value = '512';
  doc.getElementById('developer-qr-format').value = 'png';
  doc.getElementById('developer-qr-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 1);
  assert.equal(ctx.fetchCalls[0].url, '/api/developer/qr-codes');
  assert.deepEqual(JSON.parse(ctx.fetchCalls[0].init.body), { payload: 'https://example.com', error_correction: 'M', size_px: 512, format: 'png' });
  assertWithinButtonLimit(visibleButtons(panel), 'QR PNG, with result');
  doc.getElementById('developer-qr-format').value = 'svg';
  doc.getElementById('developer-qr-generate').click();
  await settle();
  assert.equal(ctx.fetchCalls.length, 2);
  assert.deepEqual(JSON.parse(ctx.fetchCalls[1].init.body), { payload: 'https://example.com', error_correction: 'M', size_px: 512, format: 'svg' });
  assertWithinButtonLimit(visibleButtons(panel), 'QR SVG, with result');
});
test('disabled shared-dock actions have a visible disabled treatment', () => {
  assert.match(shellCss, /\.ok-app\s+\[data-officekit-docked\]:disabled\s*\{\s*cursor:\s*not-allowed;\s*opacity:\s*\.48;\s*\}/);
});
