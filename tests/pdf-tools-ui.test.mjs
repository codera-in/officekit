import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { loadToolCatalog, parseSliceDestinations, sliceAssetPath } from '../scripts/tool-catalog.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = relative => fs.readFileSync(path.join(repoRoot, relative), 'utf8');
const sliceSource = read(sliceAssetPath('pdf_tools'));
const sliceCss = read(sliceAssetPath('pdf_tools', 'css'));
const html = read('index.html');
const routes = read('officekit/routes/pdf_tools.py');

const NEW_OPERATIONS = {
  rotate: 'pdf_rotate_pages',
  'images-to-pdf': 'pdf_from_images',
  'metadata-view': 'pdf_metadata_view',
  watermark: 'pdf_watermark',
  'page-numbers': 'pdf_page_numbers',
  'resize-pages': 'pdf_resize_pages',
  grayscale: 'pdf_grayscale',
  flatten: 'pdf_flatten',
};
const ENDPOINTS = {
  rotate: '/api/pdf/page-rotations',
  'images-to-pdf': '/api/pdf/image-pdfs',
  'metadata-view': '/api/pdf/inspections',
  watermark: '/api/pdf/watermarks',
  'page-numbers': '/api/pdf/page-numbers',
  'resize-pages': '/api/pdf/page-sizes',
  grayscale: '/api/pdf/grayscale-conversions',
  flatten: '/api/pdf/flattenings',
};

// Minimal DOM: records text and attributes, never parses markup. Enough for the builders under test.
class FakeNode {
  constructor(tag = '') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.className = '';
    this.textNodes = [];
    this.value = '';
    this._text = '';
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { for (const node of nodes) this.children.push(typeof node === 'string' ? new FakeText(node) : node); }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  get childElementCount() { return this.children.length; }
}
class FakeText { constructor(text) { this.textContent = text; } }

function fakeDocument() {
  const byId = {};
  return {
    byId,
    createElement: tag => new FakeNode(tag),
    createTextNode: text => new FakeText(text),
    getElementById: id => (byId[id] ||= new FakeNode('div')),
    querySelectorAll: () => [],
  };
}

function loadSlice() {
  const registrations = [];
  const document = fakeDocument();
  const window = {
    OfficeKitExtensions: { register: config => registrations.push(config) },
    setTimeout: () => 0,
    clearTimeout: () => {},
  };
  const context = {
    window, document, console,
    FormData, Blob, File, Response, Headers, TextDecoder, Uint8Array, URL, AbortController, Promise,
    setTimeout: () => 0,
    clearTimeout: () => {},
  };
  vm.runInNewContext(sliceSource, context, { filename: 'officekit-slice-pdf-tools.js' });
  return { slice: window.OfficeKitPdfSlice, registrations, document };
}

function pdfFile(name = 'board-pack.pdf', size = 64) {
  return new File([new Uint8Array(size)], name, { type: 'application/pdf' });
}

function imageFile(name = 'photo.png', type = 'image/png') {
  return new File([new Uint8Array(32)], name, { type });
}

function pdfBlob(text = '%PDF-1.7\n') {
  return new Blob([text], { type: 'application/pdf' });
}

function response(body, { status = 200, headers = {} } = {}) {
  return new Response(body, { status, headers });
}

function optionsOf(form) {
  return JSON.parse(form.get('options'));
}

const { slice, registrations } = loadSlice();

test('slice registers first, with one destination per new ID routed to its pdfTool', () => {
  const firstStatement = sliceSource.split('\n').find(line => line.trim() && !line.trim().startsWith('//'));
  assert.match(firstStatement, /^window\.OfficeKitExtensions\.register\(\{$/);
  assert.equal(registrations.length, 1);
  assert.equal(registrations[0].slice, 'pdf_tools');
  const destinations = parseSliceDestinations(sliceSource);
  const parsed = Object.fromEntries(destinations.map(match => [match[1], { tab: match[2], pdfTool: match[3] }]));
  assert.deepEqual(Object.keys(parsed).sort(), Object.values(NEW_OPERATIONS).sort());
  for (const [pdfTool, toolId] of Object.entries(NEW_OPERATIONS)) {
    assert.equal(registrations[0].destinations[toolId].pdfTool, pdfTool, toolId);
    assert.equal(registrations[0].destinations[toolId].tab, 'pdf', toolId);
  }
});

test('every new catalogue ID is a PDF slice tool and has an operation, copy entry and nav button', () => {
  const catalogue = loadToolCatalog().tools.map(tool => tool.id);
  for (const [pdfTool, toolId] of Object.entries(NEW_OPERATIONS)) {
    assert.ok(catalogue.includes(toolId), `${toolId} is in the live catalogue`);
    assert.ok(slice.isOperation(pdfTool), `${pdfTool} is an operation`);
    assert.equal(slice.toolId(pdfTool), toolId);
    assert.match(html, new RegExp(`['"]?${pdfTool}['"]?: \\{ id: '${toolId}'`), `${pdfTool} copy entry`);
    assert.match(html, new RegExp(`data-pdf-tool="${pdfTool}"`), `${pdfTool} nav button`);
  }
  assert.equal(slice.isOperation('merge'), false, 'core operations stay outside the slice');
});

test('each operation calls only the route it declares, and that route exists', () => {
  const declared = [...routes.matchAll(/@router\.post\("([^"]+)"/g)].map(match => match[1]);
  for (const [pdfTool, endpoint] of Object.entries(ENDPOINTS)) {
    assert.ok(declared.includes(endpoint), `${pdfTool} -> ${endpoint} exists on the router`);
  }
  const requests = Object.keys(ENDPOINTS).map(pdfTool => slice.buildRequest(pdfTool, pdfTool === 'images-to-pdf' ? [imageFile()] : [pdfFile()]).endpoint);
  assert.deepEqual(requests, Object.keys(ENDPOINTS).map(key => ENDPOINTS[key]));
});

test('request building: rotate sends the angle and ranges, and names the output', () => {
  slice.reset('rotate');
  Object.assign(slice.state('rotate'), { angle: 270, pageRanges: '2, 4-5' });
  const request = slice.buildRequest('rotate', [pdfFile('scan.pdf')]);
  assert.equal(request.name, 'scan-rotated.pdf');
  assert.deepEqual(optionsOf(request.form), { angle: 270, page_ranges: '2, 4-5' });
  assert.equal(request.form.get('file').name, 'scan.pdf');
});

test('request building: images keep the ordered batch and send only the image options', () => {
  slice.reset('images-to-pdf');
  Object.assign(slice.state('images-to-pdf'), { pageSize: 'letter', orientation: 'landscape', fit: 'cover', marginMm: 0 });
  const images = [imageFile('b.png'), imageFile('a.jpg', 'image/jpeg'), imageFile('c.webp', 'image/webp')];
  const request = slice.buildRequest('images-to-pdf', images);
  assert.deepEqual(request.form.getAll('files').map(file => file.name), ['b.png', 'a.jpg', 'c.webp']);
  assert.equal(request.name, 'images.pdf');
  assert.deepEqual(optionsOf(request.form), { page_size: 'letter', orientation: 'landscape', fit: 'cover', margin_mm: 0 });
});

test('request building: metadata view sends the file only, with no options field', () => {
  const request = slice.buildRequest('metadata-view', [pdfFile()]);
  assert.equal(request.form.get('options'), null);
  assert.equal(request.result, 'json');
});

test('request building: watermark sends text or the image part, never both', () => {
  slice.reset('watermark');
  const text = slice.buildRequest('watermark', [pdfFile()]);
  assert.equal(optionsOf(text.form).text, 'CONFIDENTIAL');
  assert.equal(text.form.get('image'), null);
  assert.equal(text.name, 'board-pack-watermarked.pdf');
  const state = slice.state('watermark');
  Object.assign(state, { kind: 'image', imageFile: imageFile('logo.png') });
  const image = slice.buildRequest('watermark', [pdfFile()]);
  assert.equal(optionsOf(image.form).text, undefined);
  assert.equal(image.form.get('image').name, 'logo.png');
  slice.reset('watermark');
});

test('request building: page numbers send the template only for custom format', () => {
  slice.reset('page-numbers');
  assert.equal(optionsOf(slice.buildRequest('page-numbers', [pdfFile()]).form).template, undefined);
  Object.assign(slice.state('page-numbers'), { format: 'custom', template: 'Página {n} de {total}', countSkipped: true });
  const custom = optionsOf(slice.buildRequest('page-numbers', [pdfFile()]).form);
  assert.equal(custom.template, 'Página {n} de {total}');
  assert.equal(custom.count_skipped, true);
  slice.reset('page-numbers');
});

test('request building: resize sends custom size and anchor only where they apply', () => {
  slice.reset('resize-pages');
  assert.equal(optionsOf(slice.buildRequest('resize-pages', [pdfFile()]).form).anchor, undefined);
  Object.assign(slice.state('resize-pages'), { preset: 'custom', width: '210', height: '297.5', unit: 'mm', mode: 'canvas', anchor: 'center-left' });
  const custom = optionsOf(slice.buildRequest('resize-pages', [pdfFile()]).form);
  assert.deepEqual(
    { preset: custom.preset, width: custom.width, height: custom.height, unit: custom.unit, mode: custom.mode, anchor: custom.anchor },
    { preset: 'custom', width: '210', height: '297.5', unit: 'mm', mode: 'canvas', anchor: 'center-left' },
  );
  slice.reset('resize-pages');
});

test('request building: grayscale sends DPI only for rasterizing; flatten sends the acknowledgement', () => {
  slice.reset('grayscale');
  assert.equal(optionsOf(slice.buildRequest('grayscale', [pdfFile()]).form).dpi, undefined);
  Object.assign(slice.state('grayscale'), { method: 'raster', dpi: 300 });
  assert.deepEqual(optionsOf(slice.buildRequest('grayscale', [pdfFile()]).form), { method: 'raster', dpi: 300 });
  slice.reset('grayscale');
  Object.assign(slice.state('flatten'), { signed: true, acknowledge: true, scope: 'forms' });
  assert.deepEqual(optionsOf(slice.buildRequest('flatten', [pdfFile()]).form), { scope: 'forms', acknowledge_signature_loss: true });
  slice.reset('flatten');
});

test('validation: page ranges must be strict and ascending, never repaired', () => {
  for (const good of ['', '1', '1-3, 5', '2, 4-5']) assert.equal(slice.validPageRanges(good), true, good);
  for (const bad of ['5, 1-3', '3-1', '0', '1-3, 3', 'a', '1..3', '1-3;5']) assert.equal(slice.validPageRanges(bad), false, bad);
  assert.equal(slice.validPageRanges('1'.repeat(4100)), false);
});

test('validation: watermark text needs NFC, 1–200 characters and no control characters', () => {
  const base = slice.state('watermark');
  const message = (overrides, files = [pdfFile()]) => slice.validate('watermark', files, { ...base, ...overrides });
  assert.equal(message({ text: 'Résumé Ωμέγα Жизнь' }), null);
  assert.match(message({ text: '' }), /Enter 1–200 characters/);
  assert.match(message({ text: 'a'.repeat(201) }), /Enter 1–200 characters/);
  assert.match(message({ text: 'bad\u0007text' }), /Control characters/);
  assert.match(message({ text: 'é' }), /Enter 1–200 characters/, 'decomposed text is refused, not rewritten');
  assert.match(message({ kind: 'image', imageFile: null }), /Choose a PNG or JPEG image/);
  assert.match(message({ color: 'red' }), /#RRGGBB/);
  assert.match(message({ opacity: 4 }), /Opacity/);
  assert.match(message({ angle: 91 }), /Angle/);
});

test('validation: page numbers accept only {n} and {total}, and roman numerals stop at 3,999', () => {
  const base = slice.state('page-numbers');
  const message = overrides => slice.validate('page-numbers', [pdfFile()], { ...base, ...overrides });
  assert.equal(message({ format: 'custom', template: 'p.{n}/{total}' }), null);
  assert.match(message({ format: 'custom', template: 'p.{name}' }), /\{n\} and \{total\}/);
  assert.match(message({ format: 'custom', template: 'open { brace' }), /\{n\} and \{total\}/);
  assert.match(message({ format: 'custom', template: '' }), /\{n\} and \{total\}/);
  assert.match(message({ format: 'roman-lower', start: 0 }), /Roman numbers start at 1/);
  assert.match(message({ format: 'roman-upper', start: 4000 }), /3,999/);
  assert.match(message({ start: 10000 }), /0 to 9,999/);
});

test('validation: custom page size must convert to 72–14,400 pt and carry a unit', () => {
  const base = slice.state('resize-pages');
  const message = overrides => slice.validate('resize-pages', [pdfFile()], { ...base, ...overrides });
  assert.equal(message({ preset: 'a4' }), null);
  assert.equal(message({ preset: 'custom', width: '210', height: '297', unit: 'mm' }), null);
  assert.match(message({ preset: 'custom', width: '20', height: '297', unit: 'mm' }), /72 and 14,400/);
  assert.match(message({ preset: 'custom', width: '210.123', height: '297', unit: 'mm' }), /two decimal/);
  assert.match(message({ preset: 'custom', width: '1', height: '1', unit: 'px' }), /mm, in or pt/);
});

test('validation: images batch is 1–200 image files, and PDFs are one file', () => {
  assert.match(slice.validate('images-to-pdf', []), /Choose 1–200 images/);
  assert.match(slice.validate('images-to-pdf', [imageFile('notes.pdf', 'application/pdf')]), /Choose PNG, JPEG, WebP, TIFF, GIF or BMP/);
  assert.equal(slice.validate('images-to-pdf', Array.from({ length: 200 }, (_, index) => imageFile(`i${index}.png`))), null);
  assert.match(slice.validate('images-to-pdf', Array.from({ length: 201 }, (_, index) => imageFile(`i${index}.png`))), /Choose 1–200 images/);
  assert.match(slice.validate('rotate', [pdfFile(), pdfFile('b.pdf')]), /one PDF/);
  assert.match(slice.validate('rotate', [imageFile()]), /one PDF/);
});

test('validation: flatten needs the signature acknowledgement only when a signed field exists', () => {
  const base = slice.state('flatten');
  assert.equal(slice.validate('flatten', [pdfFile()], { ...base, signed: false, acknowledge: false }), null);
  assert.match(slice.validate('flatten', [pdfFile()], { ...base, signed: true, acknowledge: false }), /Confirm the signature warning/);
  assert.equal(slice.validate('flatten', [pdfFile()], { ...base, signed: true, acknowledge: true }), null);
});

test('error states: typed refusals keep their code, and untyped bodies never echo parser text', async () => {
  const typed = await slice.readRefusal(response(JSON.stringify({ detail: { code: 'grayscale_needs_raster', message: 'Rasterize to continue.' } }), { status: 422, headers: { 'content-type': 'application/json' } }));
  assert.equal(typed.code, 'grayscale_needs_raster');
  assert.equal(typed.message, 'Rasterize to continue.');
  const plain = await slice.readRefusal(response(JSON.stringify({ detail: 'The watermark text uses characters the bundled font can\'t draw.' }), { status: 422, headers: { 'content-type': 'application/json' } }));
  assert.equal(plain.code, '');
  assert.match(plain.message, /can't draw/);
  const opaque = await slice.readRefusal(response('<html>QPDF: /Root tampered</html>', { status: 500 }));
  assert.equal(opaque.code, '');
  assert.doesNotMatch(opaque.message, /QPDF|tampered|Root/);
});

test('error states: a 409 signature refusal surfaces the acknowledgement code to the caller', async () => {
  const fetchImpl = async () => response(JSON.stringify({ detail: { code: 'signature_ack_required', message: 'Confirm the signature warning.' } }), { status: 409, headers: { 'content-type': 'application/json' } });
  await assert.rejects(slice.run('flatten', [pdfFile()], fetchImpl), error => error.code === 'signature_ack_required' && error.status === 409);
});

test('response validation: wrong media type, non-PDF bytes and oversized outputs are rejected', async () => {
  const wrongType = async () => response('ok', { headers: { 'content-type': 'text/plain' } });
  await assert.rejects(slice.run('rotate', [pdfFile()], wrongType), /valid file/);
  const notPdf = async () => response(new Blob(['<html>not a pdf</html>'], { type: 'application/pdf' }), { headers: { 'content-type': 'application/pdf' } });
  await assert.rejects(slice.run('rotate', [pdfFile()], notPdf), /valid file/);
  const oversized = async () => response(pdfBlob(), { headers: { 'content-type': 'application/pdf', 'content-length': String(65 * 1024 * 1024) } });
  await assert.rejects(slice.run('rotate', [pdfFile()], oversized), /oversized/);
});

test('response validation: inspection must be a complete report with the expected shape', async () => {
  const valid = {
    pdf_version: '1.7', page_count: 2, docinfo: [], dates: {}, xmp: { present: false, entries: [] },
    page_sizes: [], other_count: 0, forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, encrypted: false, truncated: false,
  };
  const ok = await slice.run('metadata-view', [pdfFile()], async () => response(JSON.stringify(valid), { headers: { 'content-type': 'application/json' } }));
  assert.equal(ok.kind, 'json');
  assert.equal(ok.report.page_count, 2);
  const broken = { ...valid, forms: { fields: 'many' } };
  await assert.rejects(
    slice.run('metadata-view', [pdfFile()], async () => response(JSON.stringify(broken), { headers: { 'content-type': 'application/json' } })),
    /valid report/,
  );
  const withoutEncrypted = { ...valid };
  delete withoutEncrypted.encrypted;
  await assert.rejects(
    slice.run('metadata-view', [pdfFile()], async () => response(JSON.stringify(withoutEncrypted), { headers: { 'content-type': 'application/json' } })),
    /valid report/,
  );
});

// Button Limit (AGENTS.md): at most 3 buttons per screen. Every visible BUTTON counts: the drop zone
// (index.html), option controls such as segmented toggles, the message host and the bottom dock.
// In-text links (class pdf-slice-link), table row actions and chip remove controls are not counted.
function bodyButtons(node, found = []) {
  for (const child of node.children || []) {
    if (child.tagName === 'BUTTON' && !String(child.className).split(' ').includes('pdf-slice-link')) found.push(child);
    bodyButtons(child, found);
  }
  return found;
}

// The drop zone is static markup in index.html. Its only button is the "Select PDFs" in-text link (UX-17).
function dropZoneButtons() {
  const start = html.indexOf('id="pdf-workbench-dropzone"');
  const end = html.indexOf('id="pdf-workbench-files"', start);
  assert.ok(start > 0 && end > start, 'the drop zone is in index.html');
  const tags = [...html.slice(start, end).matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
  assert.equal(tags.length, 1, 'the drop zone has one button, the Select PDFs link');
  assert.match(tags[0], /id="pdf-workbench-select-button"/);
  assert.match(tags[0], /class="[^"]*\bpdf-slice-link\b/, 'Select PDFs is an in-text link, not a button');
  return tags.filter(tag => !/\bpdf-slice-link\b/.test(tag)).length;
}

test('button limit: every operation shows at most 3 visible buttons, idle and after a result', () => {
  const dropZone = dropZoneButtons();
  // Each operation's default state, plus the two states whose controls differ (QA-15).
  const states = [
    ...Object.keys(NEW_OPERATIONS).map(key => ({ label: key, key, setup: () => {} })),
    { label: 'watermark with Stamp set to Image', key: 'watermark', setup: local => { local.state('watermark').kind = 'image'; } },
    { label: 'resize-pages with Content set to Change canvas', key: 'resize-pages', setup: local => { local.state('resize-pages').mode = 'canvas'; } },
  ];
  for (const { label, key, setup } of states) {
    const { slice: local, document } = loadSlice();
    setup(local);
    const container = new FakeNode('div');
    local.renderOptions(key, container, { notify: () => {} });
    // Grayscale's refusal offers "Rasterize instead" in the message host; every other refusal is text only.
    const error = key === 'grayscale'
      ? { code: 'grayscale_needs_raster', message: 'Rasterize to continue.' }
      : { code: 'pdf_refused', message: 'The PDF could not be processed.' };
    local.showError(key, error, { onRasterize: () => {} });
    const message = bodyButtons(document.byId['pdf-slice-message']).length;
    for (const phase of ['idle', 'result']) {
      const count = dropZone + bodyButtons(container).length + message + local.dockFor(key, phase).length;
      assert.ok(count <= 3, `${label} ${phase}: ${count} buttons`);
    }
  }
});

test('button limit: the dock shows one primary action per phase', () => {
  assert.deepEqual(Array.from(slice.dockFor('watermark', 'idle')), ['run']);
  assert.deepEqual(Array.from(slice.dockFor('watermark', 'result')), ['download']);
  assert.deepEqual(Array.from(slice.dockFor('metadata-view', 'result')), ['copy']);
  assert.deepEqual(Array.from(slice.dockFor('flatten', 'result')), ['download']);
});

test('ARCH-5: image batches append up to the 200 cap and refuse the 201st with the operation copy', () => {
  const images = Array.from({ length: 200 }, (_, index) => imageFile(`scan-${index}.png`));
  const first = slice.acceptFiles('images-to-pdf', [], images);
  assert.equal(first.files.length, 200);
  // Results are created in the vm realm, so compare fields rather than whole objects.
  assert.equal(slice.acceptFiles('images-to-pdf', first.files, [imageFile('extra.png')]).error, 'Images to PDF accepts no more than 200 images.');
  const wrongType = 'Select non-empty PNG, JPEG, WebP, TIFF, GIF or BMP images only.';
  assert.equal(slice.acceptFiles('images-to-pdf', [], [pdfFile()]).error, wrongType);
  assert.equal(slice.acceptFiles('images-to-pdf', [], [new File([], 'empty.png', { type: 'image/png' })]).error, wrongType);
});

test('ARCH-5: PDF tasks replace the selection, accept one file and refuse the 64 MiB total', () => {
  const kept = slice.acceptFiles('rotate', [pdfFile('a.pdf')], [pdfFile('b.pdf')]);
  assert.deepEqual(Array.from(kept.files, file => file.name), ['b.pdf'], 'a new PDF replaces the old one');
  assert.equal(slice.acceptFiles('rotate', [], [pdfFile('a.pdf'), pdfFile('b.pdf')]).error, 'This task accepts one PDF. Choose a single file.');
  assert.equal(slice.acceptFiles('rotate', [], [pdfFile('scan.png', 8)]).error, 'Select non-empty PDF files only.');
  assert.equal(slice.acceptFiles('rotate', [], [{ name: 'huge.pdf', size: 67_108_865 }]).error, 'Selected PDF files exceed the 64 MiB processing limit.');
});

test('ARCH-5: Alt+ArrowDown on an image row reorders the batch through the slice, and only with Alt', () => {
  const files = ['a', 'b', 'c'].map(name => imageFile(`${name}.png`));
  let prevented = 0;
  const press = (key, altKey = true) => ({ key, altKey, preventDefault: () => { prevented += 1; } });
  const moved = slice.keyboardMove(press('ArrowDown'), files, 0);
  assert.deepEqual(Array.from(moved, file => file.name), ['b.png', 'a.png', 'c.png']);
  assert.equal(prevented, 1, 'the arrow key does not also scroll the page');
  assert.equal(files[0].name, 'a.png', 'the caller list is not mutated');
  assert.equal(slice.keyboardMove(press('ArrowDown', false), files, 0), null, 'no Alt, no move');
  assert.equal(slice.keyboardMove(press('ArrowUp'), files, 0), null, 'the first row cannot move up');
  assert.equal(slice.keyboardMove(press('ArrowDown'), files, 2), null, 'the last row cannot move down');
  assert.equal(slice.keyboardMove(press('Enter'), files, 0), null, 'other keys are ignored');
  assert.equal(slice.keyboardMove(null, files, 0), null);
});

test('ARCH-5: only the images operation reorders rows', () => {
  for (const key of Object.keys(NEW_OPERATIONS)) {
    assert.equal(slice.reordersRows(key), key === 'images-to-pdf', key);
  }
  assert.equal(slice.reordersRows('merge'), false, 'not a slice task');
});

test('UX-8: the generic output preview is hidden for every slice operation', () => {
  for (const key of Object.keys(NEW_OPERATIONS)) {
    assert.equal(slice.workbenchPreviewVisible(key), false, key);
  }
  assert.equal(slice.workbenchPreviewVisible('merge'), true, 'the generic preview stays for non-slice tools');
});

// Stub of the workbench shell: records what runWorkbench writes to the dock status and the output.
function stubShell(tool, files, fetchImpl) {
  const log = { status: [], phases: [], output: null, reports: [], cleared: 0 };
  return {
    log, tool, files, fetch: fetchImpl,
    busy() {}, clearOutput() { log.cleared += 1; }, refresh() {}, rerender() {},
    status: (text, isError, reportBug) => log.status.push({ text, isError: Boolean(isError), reportBug }),
    phase: value => log.phases.push(value),
    setOutput: (blob, name) => { log.output = name; },
    report: value => log.reports.push(value),
  };
}

test('UX-8 and UX-19: the dock status names the PDF output, and the metadata status is the report status', async () => {
  const pdf = stubShell('rotate', [pdfFile('board-pack.pdf')], async () => response(pdfBlob(), { headers: { 'content-type': 'application/pdf', 'x-officekit-affected-pages': '3' } }));
  await slice.runWorkbench(pdf);
  const pdfStatus = pdf.log.status.at(-1);
  assert.equal(pdfStatus.isError, false);
  assert.equal(pdfStatus.text, 'Done · 3 pages turned', 'the approved frame wording, with the count from the route header');
  assert.doesNotMatch(pdfStatus.text, /Download it when you are ready/, 'the trailing sentence is dropped (UX-20)');
  assert.equal(pdf.log.output.endsWith('.pdf'), true, 'the output is still named for the download');

  const report = {
    pdf_version: '1.7', page_count: 2, docinfo: [], dates: {}, xmp: { present: false, entries: [] },
    page_sizes: [], other_count: 0, forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, encrypted: false, truncated: false,
  };
  const json = stubShell('metadata-view', [pdfFile()], async () => response(JSON.stringify(report), { headers: { 'content-type': 'application/json' } }));
  await slice.runWorkbench(json);
  assert.equal(json.log.status.at(-1).text, slice.reportStatus(json.log.reports[0]));
  assert.match(json.log.status.at(-1).text, /of 9 standard fields read/);
  assert.doesNotMatch(json.log.status.at(-1).text, /original PDF is unchanged/);
});

test('invalid metadata PDF clears stale report and suppresses bug reporting while retaining retry', async () => {
  const { slice: local, document: localDocument } = loadSlice();
  const shell = stubShell('metadata-view', [pdfFile('broken.pdf')], async () => response(JSON.stringify({
    detail: 'The PDF file is invalid or the requested operation is unsupported.',
  }), { status: 422, headers: { 'content-type': 'application/json' } }));
  await local.runWorkbench(shell);
  assert.equal(shell.log.cleared, 1);
  assert.equal(shell.log.reports.length, 0);
  assert.equal(shell.log.phases.at(-1), undefined);
  assert.equal(shell.log.status.at(-1).isError, true);
  assert.equal(shell.log.status.at(-1).reportBug, false);
  const alert = localDocument.byId['pdf-slice-message'].children[0];
  assert.equal(alert.attributes['data-officekit-no-bug-report'], '');
});

const MiB64 = 64 * 1024 * 1024;

test('QA-13: exactly 64 MiB in total is accepted for a PDF and for an image batch, and one byte more is refused', () => {
  assert.equal(slice.acceptFiles('rotate', [], [{ name: 'exact.pdf', size: MiB64 }]).files.length, 1, 'a PDF at the limit is accepted');
  assert.equal(slice.acceptFiles('rotate', [], [{ name: 'over.pdf', size: MiB64 + 1 }]).error, 'Selected PDF files exceed the 64 MiB processing limit.');
  const half = MiB64 / 2;
  const batch = [{ name: 'a.png', type: 'image/png', size: half }, { name: 'b.png', type: 'image/png', size: half }];
  assert.equal(slice.acceptFiles('images-to-pdf', [], batch).files.length, 2, 'two images totalling exactly 64 MiB are accepted');
  const over = [{ name: 'a.png', type: 'image/png', size: half }, { name: 'b.png', type: 'image/png', size: half + 1 }];
  assert.equal(slice.acceptFiles('images-to-pdf', [], over).error, 'Selected PDF files exceed the 64 MiB processing limit.', 'one byte more is refused');
});

test('UX-20: the dock status uses the approved "Done" frames, with the count from the route headers', () => {
  const result = (name, headers = {}) => ({ name, headers });
  assert.equal(slice.doneLine('watermark', result('watermarked.pdf', { pageCount: 14 })), 'Done · watermarked.pdf · 14 pages');
  assert.equal(slice.doneLine('rotate', result('turned.pdf', { affectedPages: 3 })), 'Done · 3 pages turned');
  assert.equal(slice.doneLine('rotate', result('turned.pdf', { affectedPages: 1 })), 'Done · 1 page turned');
  assert.equal(slice.doneLine('rotate', result('turned.pdf')), 'Done · pages turned', 'a missing count does not show undefined');
  assert.equal(slice.doneLine('watermark', result('watermarked.pdf')), 'Done · watermarked.pdf', 'a missing count does not show undefined');
  assert.equal(slice.doneLine('resize-pages', result('resized.pdf')), 'Done · resized copy');
  // PM-9 / UX-21, owner answer 2026-10-22 "Match the mock (Recommended)": a bare "Done" for these three.
  assert.equal(slice.doneLine('images-to-pdf', result('images.pdf', { pageCount: 1 })), 'Done');
  assert.equal(slice.doneLine('grayscale', result('gray.pdf', { grayscaleMethod: 'raster' })), 'Done');
  assert.equal(slice.doneLine('flatten', result('flat.pdf', { flattenedFields: 2, flattenedAnnotations: 0 })), 'Done');
  assert.equal(slice.doneLine('page-numbers', result('numbered.pdf')), 'Done', 'no page count, no count shown');
});

test('PM-9: page numbers reads "Done · N of M pages numbered", N from the selection and M from the page count', () => {
  const result = (pageCount) => ({ name: 'numbered.pdf', headers: { pageCount } });
  assert.equal(slice.doneLine('page-numbers', result(14), { pageRanges: '' }), 'Done · 14 of 14 pages numbered', 'blank selects every page');
  assert.equal(slice.doneLine('page-numbers', result(14), { pageRanges: '3-14' }), 'Done · 12 of 14 pages numbered', 'pages 1 and 2 left out');
  assert.equal(slice.doneLine('page-numbers', result(14), { pageRanges: '5-7, 14' }), 'Done · 4 of 14 pages numbered', 'a range and a single page');
  assert.equal(slice.doneLine('page-numbers', result(14), { pageRanges: '13-20' }), 'Done · 2 of 14 pages numbered', 'pages past the end are clipped');
  assert.equal(slice.doneLine('page-numbers', result(1), { pageRanges: '' }), 'Done · 1 of 1 page numbered', 'singular page for a one-page file');
  assert.equal(slice.numberedPageCount('2-3, 3', 5), 2, 'an overlapping selection counts each page once');
});

test('PM-9: a page-numbers run shows the selection count in the dock status', async () => {
  const shell = stubShell('page-numbers', [pdfFile()], async () => response(pdfBlob(), { headers: { 'content-type': 'application/pdf', 'x-officekit-page-count': '14' } }));
  try {
    slice.state('page-numbers').pageRanges = '3-14';
    await slice.runWorkbench(shell);
    assert.equal(shell.log.status.at(-1).text, 'Done · 12 of 14 pages numbered');
  } finally {
    slice.state('page-numbers').pageRanges = '';
  }
});

test('ARCH-13 and CR-11: the slice counts the same labelled pages as the engine for every row of the shared table', () => {
  // tests/pdf_page_range_counts.json is also read by PageNumberCountParityTests (Python). Refused rows are the
  // selections the server never labels; their count is the slice's defensive clip and de-duplicate result.
  const rows = JSON.parse(fs.readFileSync(path.join(repoRoot, 'tests/pdf_page_range_counts.json'), 'utf8'));
  assert.ok(rows.length >= 6, 'the table has the blank, range, overlap and past-the-end rows');
  for (const row of rows) {
    assert.equal(slice.numberedPageCount(row.selection, row.total), row.labelled, `${JSON.stringify(row.selection)} of ${row.total}`);
  }
});

test('ARCH-5: the images limit line is supplied by the slice from its cap, and only images has one', () => {
  assert.equal(
    slice.limitFor('images-to-pdf'),
    'Choose 1–200 images (PNG, JPEG, WebP, TIFF, GIF, BMP) · 64 MiB total · up to 40 MP each.',
  );
  assert.equal(slice.limitFor('rotate'), null, 'a task without a file-limit line returns null');
  assert.equal(slice.limitFor('merge'), null, 'a non-slice task returns null');
});

test('rotate turns through a select, and watermark image choice is an in-text link', () => {
  const { slice: local } = loadSlice();
  const rotate = new FakeNode('div');
  local.renderOptions('rotate', rotate, { notify: () => {} });
  assert.equal(bodyButtons(rotate).length, 0);
  assert.match(rotate.textContent, /Turn/);
  local.state('watermark').kind = 'image';
  const image = new FakeNode('div');
  local.renderOptions('watermark', image, { notify: () => {} });
  const links = bodyButtons(image, []);
  assert.equal(links.length, 2, 'Text and Image toggles are counted; the link is not');
  assert.match(image.textContent, /Choose image…/);
  assert.match(image.textContent, /PNG or JPEG, up to 8 MiB\. No image chosen\./);
});

test('watermark and page numbers keep secondary options under a Details disclosure', () => {
  const { slice: local } = loadSlice();
  const watermark = new FakeNode('div');
  local.renderOptions('watermark', watermark, { notify: () => {} });
  const details = watermark.children.find(child => child.tagName === 'DETAILS');
  assert.ok(details, 'watermark has a Details disclosure');
  assert.match(details.textContent, /Font size/);
  assert.match(details.textContent, /Angle/);
  assert.match(details.textContent, /Color/);
  assert.match(details.textContent, /Pages/);
  const numbers = new FakeNode('div');
  local.renderOptions('page-numbers', numbers, { notify: () => {} });
  const numberDetails = numbers.children.find(child => child.tagName === 'DETAILS');
  assert.match(numberDetails.textContent, /Count unnumbered pages/);
  assert.match(numberDetails.textContent, /Example: with pages 1–2 left out and the box unchecked, page 3 shows “1”\./);
  assert.match(numbers.textContent, /Number these pages \(blank = all\)/);
  assert.equal(local.state('page-numbers').countSkipped, false, 'count unnumbered pages defaults unchecked');
});

test('preview sheets are described in the options: watermark page 1 and first landscape, numbers pages 1, 2 and first selected', () => {
  const { slice: local } = loadSlice();
  const watermark = new FakeNode('div');
  local.renderOptions('watermark', watermark, { notify: () => {} });
  assert.match(watermark.textContent, /Preview · page 1 and first landscape page/);
  local.state('page-numbers').pageRanges = '5-7';
  const numbered = new FakeNode('div');
  local.renderOptions('page-numbers', numbered, { notify: () => {} });
  assert.match(numbered.textContent, /Preview · pages 1, 2 and the first selected page/);
  assert.equal(numbered.children.find(child => child.id === 'pdf-slice-preview').tagName, 'DIV');
});

test('file facts and the report status are copy the workbench can show', () => {
  const { slice: local } = loadSlice();
  assert.equal(local.factsLine('flatten'), '', 'no facts before a file is read');
  const report = {
    pdf_version: '1.7', page_count: 1, encrypted: true,
    docinfo: [
      { key: 'Title', label: 'Title', standard: true, present: true, value: 'Board pack', truncated: false },
      { key: 'Author', label: 'Author', standard: true, present: false, value: null, truncated: false },
      { key: 'Custom', label: 'Custom', standard: false, present: true, value: 'x', truncated: false },
    ],
    dates: {}, xmp: { present: false, entries: [] }, page_sizes: [], other_count: 0,
    forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, truncated: false,
  };
  assert.equal(local.reportStatus(report), '1 of 9 standard fields read · 8 not set');
  assert.match(local.reportText(report), /Encrypted: Yes/);
  assert.match(local.reportText(report), /Author: Not set/);
});

test('metadata copy contains the complete document, XMP and page-structure report', () => {
  const { slice: local } = loadSlice();
  const report = {
    pdf_version: '1.7', page_count: 3, encrypted: false,
    docinfo: [
      { key: 'Title', label: 'Title', standard: true, present: true, value: 'Quarterly report', truncated: false },
      { key: 'Author', label: 'Author', standard: true, present: false, value: null, truncated: false },
    ],
    dates: {},
    xmp: { present: true, entries: [
      { name: 'dc:title', value: 'Résumé', truncated: false },
      { name: 'dc:creator[0]', value: 'A. Author', truncated: true },
    ] },
    page_sizes: [
      { count: 2, width_pt: 612, height_pt: 792, rotate: 0 },
      { count: 1, width_pt: 792, height_pt: 612, rotate: 90 },
    ],
    other_count: 0,
    forms: { fields: 2, signature_fields: 1, signed: true, xfa: true },
    annotations: 3,
    truncated: true,
  };
  assert.equal(local.reportText(report), [
    'Document information',
    'PDF version: 1.7',
    'Pages: 3',
    'Encrypted: No',
    'Title: Quarterly report',
    'Author: Not set',
    'XMP metadata',
    'dc:title: Résumé',
    'dc:creator[0]: A. Author … (shortened)',
    'Pages and structure',
    'Page sizes: 2 × 216 × 279 mm · 1 × 279 × 216 mm (rotate 90)',
    'Form fields: 2 (signed)',
    'Signature fields: 1',
    'Annotations: 3',
    'XFA forms: Yes',
    'Some values were shortened to 2,000 characters.',
    'Nothing is changed or saved.',
  ].join('\n'));
});

test('copy report writes plain text, and refuses when the clipboard is unavailable', async () => {
  const { slice: local } = loadSlice();
  const report = { pdf_version: '1.4', page_count: 1, encrypted: false, docinfo: [], dates: {}, xmp: { present: false, entries: [] }, page_sizes: [], other_count: 0, forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, truncated: false };
  let written = '';
  await local.copyReport(report, { writeText: async text => { written = text; } });
  assert.match(written, /PDF version: 1\.4/);
  await assert.rejects(local.copyReport(report, undefined), /Copy is not available/);
});

test('syncSelection returns the reason only as an inline note and blocks Run, without touching a server message', () => {
  const { slice: local, document } = loadSlice();
  const shell = { tool: 'rotate', files: [], };
  assert.equal(local.syncSelection(shell), true, 'no file blocks Run');
  assert.equal(document.byId['pdf-slice-validation'].textContent, '', 'no note before a file is chosen');
  Object.assign(local.state('rotate'), { angle: 45 });
  shell.files = [pdfFile()];
  assert.equal(local.syncSelection(shell), true);
  assert.match(document.byId['pdf-slice-validation'].textContent, /90°, 180° or 270°/);
  Object.assign(local.state('rotate'), { angle: 90 });
  assert.equal(local.syncSelection(shell), false);
  assert.equal(document.byId['pdf-slice-validation'].textContent, '');
});

test('grayscale resolution is always shown and enabled only for rasterizing', () => {
  const { slice: local } = loadSlice();
  const container = new FakeNode('div');
  local.renderOptions('grayscale', container, { notify: () => {} });
  const resolution = container.children.find(child => child.tagName === 'LABEL' && /Rasterize resolution/.test(child.textContent));
  assert.ok(resolution, 'resolution control is present');
  assert.equal(resolution.children.find(child => child.tagName === 'SELECT').disabled, true);
  local.state('grayscale').method = 'raster';
  const raster = new FakeNode('div');
  local.renderOptions('grayscale', raster, { notify: () => {} });
  assert.equal(raster.children.find(child => child.tagName === 'LABEL' && /Rasterize resolution/.test(child.textContent)).children.find(child => child.tagName === 'SELECT').disabled, false);
});

test('metadata view has no option note, and flatten keeps its facts off the options', () => {
  const { slice: local } = loadSlice();
  const metadata = new FakeNode('div');
  local.renderOptions('metadata-view', metadata, { notify: () => {} });
  assert.equal(metadata.children.length, 0);
  const flatten = new FakeNode('div');
  local.renderOptions('flatten', flatten, { notify: () => {} });
  assert.doesNotMatch(flatten.textContent, /Choose a PDF to see/);
});

test('response validation: success headers are read as bounded integers and summarized in copy', async () => {
  const headers = { 'content-type': 'application/pdf', 'x-officekit-flattened-fields': '6', 'x-officekit-flattened-annotations': '3', 'x-officekit-scale': '0.9700', 'x-officekit-overlap-pages': '6, 9', 'x-officekit-page-count': '14' };
  const result = await slice.run('flatten', [pdfFile()], async () => response(pdfBlob(), { headers }));
  assert.equal(result.headers.flattenedFields, 6);
  assert.equal(slice.doneLine('flatten', result), 'Done');
  const resized = await slice.run('resize-pages', [pdfFile()], async () => response(pdfBlob(), { headers }));
  assert.equal(slice.doneLine('resize-pages', resized), 'Done · resized copy');
  const hostile = await slice.run('rotate', [pdfFile()], async () => response(pdfBlob(), { headers: { 'content-type': 'application/pdf', 'x-officekit-affected-pages': '<img src=x>' } }));
  assert.equal(hostile.headers.affectedPages, null);
});

test('request building refuses invalid input before any network call', () => {
  assert.throws(() => slice.buildRequest('rotate', [pdfFile()], { angle: 45, pageRanges: '' }), /90°, 180° or 270°/);
  assert.throws(() => slice.buildRequest('rotate', []), /Choose one PDF/);
  assert.throws(() => slice.buildRequest('merge', [pdfFile()]), /unsupported/);
});

test('preview requests reuse the same options and ask for one page', () => {
  slice.reset('watermark');
  const request = slice.buildPreviewRequest('watermark', [pdfFile()], slice.state('watermark'), 1);
  assert.equal(request.endpoint, '/api/pdf/watermarks/previews');
  assert.equal(optionsOf(request.form).preview_page, 1);
  assert.throws(() => slice.buildPreviewRequest('rotate', [pdfFile()]), /no preview/);
});

test('HTML escaping: the report renders hostile values as text and the module never writes markup', () => {
  assert.doesNotMatch(sliceSource, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
  const { slice: local } = loadSlice();
  const host = new FakeNode('div');
  const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
  local.renderJsonReport({
    pdf_version: '1.7', page_count: 1,
    docinfo: [{ key: 'Title', label: 'Title', standard: true, present: true, value: hostile, truncated: false }],
    dates: {}, xmp: { present: true, entries: [{ name: 'dc:title', value: hostile, truncated: false }] },
    page_sizes: [{ width_pt: 595, height_pt: 842, rotate: 0, count: 1 }], other_count: 0,
    forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, truncated: false,
  }, host, {});
  assert.ok(host.textContent.includes(hostile), 'hostile value is shown as plain text');
  const created = [];
  const collect = node => { created.push(node.tagName); node.children.forEach(collect); };
  collect(host);
  assert.equal(created.some(tag => tag === 'IMG' || tag === 'SCRIPT'), false, 'no markup elements are created');
});

test('absent metadata fields are listed as not set rather than hidden or invented', () => {
  const { slice: local } = loadSlice();
  const host = new FakeNode('div');
  local.renderJsonReport({
    pdf_version: '1.4', page_count: 1,
    docinfo: [{ key: 'Subject', label: 'Subject', standard: true, present: false, value: null, truncated: false }],
    dates: {}, xmp: { present: false, entries: [] }, page_sizes: [], other_count: 0,
    forms: { fields: 0, signature_fields: 0, signed: false, xfa: false }, annotations: 0, truncated: false,
  }, host, {});
  assert.match(host.textContent, /Subject/);
  assert.match(host.textContent, /Not set/);
  assert.match(host.textContent, /No XMP metadata packet/);
});

test('renders options for every operation without touching the page until called', () => {
  const { slice: local, document } = loadSlice();
  assert.equal(Object.keys(document.byId).length, 0, 'loading the module touches no element');
  for (const pdfTool of Object.keys(NEW_OPERATIONS)) {
    const container = new FakeNode('div');
    local.renderOptions(pdfTool, container, { notify: () => {} });
    if (pdfTool === 'metadata-view') {
      assert.equal(container.children.length, 0, 'metadata has no option controls');
      continue;
    }
    assert.ok(container.children.length > 0, `${pdfTool} renders controls`);
  }
});

test('flatten shows the signed-field acknowledgement only when the file has a signed field', () => {
  const { slice: local } = loadSlice();
  const container = new FakeNode('div');
  Object.assign(local.state('flatten'), { signed: true });
  local.renderOptions('flatten', container, { notify: () => {} });
  assert.match(container.textContent, /signed signature field/);
  assert.match(container.textContent, /I understand the signature will no longer be valid/);
  Object.assign(local.state('flatten'), { signed: true, signatureFields: 2 });
  const several = new FakeNode('div');
  local.renderOptions('flatten', several, { notify: () => {} });
  assert.match(several.textContent, /This PDF has 2 signed signature fields/);
  Object.assign(local.state('flatten'), { signed: false, signatureFields: 0 });
  const plain = new FakeNode('div');
  local.renderOptions('flatten', plain, { notify: () => {} });
  assert.doesNotMatch(plain.textContent, /signed signature field/);
  assert.match(plain.textContent, /can’t be undone/);
});

test('slice stylesheet uses semantic tokens only: no literal colours, rem sizes or stray pixel values', () => {
  // DESIGN_SYSTEM.md: production components use --ok-* tokens, not literal colours, radii, spacing or type sizes.
  assert.doesNotMatch(sliceCss, /#[0-9a-fA-F]{3,8}\b/, 'literal hex colour');
  assert.doesNotMatch(sliceCss, /\b(?:rgb|hsl)a?\(/, 'literal functional colour');
  assert.doesNotMatch(sliceCss, /\b\d*\.?\d+rem\b/, 'literal rem size');
  const declarations = [...sliceCss.matchAll(/^\s*([a-z-]+):\s*([^;]+);/gm)]
    .filter(([, property]) => /^(color|background|border|border-radius|padding|margin|gap|font-size|min-height|outline|margin-right|margin-bottom|top|right|bottom|left)/.test(property));
  for (const [, property, value] of declarations) {
    const literalPixels = [...value.matchAll(/\b(\d+)px\b/g)].map(([, digits]) => Number(digits));
    const allowed = property.startsWith('outline') || property.startsWith('border');
    for (const pixels of literalPixels) {
      assert.ok(allowed && pixels <= 3, `${property}: ${value.trim()} uses a literal ${pixels}px`);
    }
  }
});

test('slice stylesheet keeps the grouped nav and compact menu responsive', () => {
  assert.match(sliceCss, /\.pdf-nav-wide/);
  assert.match(sliceCss, /\.pdf-compact-menu/);
  assert.match(sliceCss, /@media \(max-width: 1023px\)/);
  assert.match(html, /<details class="pdf-grp" data-pdf-group="combine" open>/);
});
test('PDF text success reveals its preview above the shared dock', () => {
  const runTask = html.slice(html.indexOf('async function runPdfWorkbenchTask'), html.indexOf('function downloadPdfWorkbenchOutput'));
  const textTask = runTask.slice(runTask.indexOf("if (activePdfTool === 'text') {"), runTask.indexOf("const task = activePdfTool === 'split'"));
  const finallyBlock = runTask.slice(runTask.indexOf('finally {'));
  assert.doesNotMatch(textTask, /requestAnimationFrame|scrollIntoView/);
  const revealTools = finallyBlock.match(/\[([^\]]+)\]\.includes\(activePdfTool\) && pdfOutputBlob instanceof Blob/);
  assert.ok(revealTools, 'completed PDF results should use the shared reveal path');
  assert.match(revealTools[1], /'text'/, 'Extract PDF Text should be included in the shared reveal path');
  assert.match(finallyBlock, /revealPdfWorkbenchResult\(preview, 'end', true\)/);
  assert.match(finallyBlock, /scroll-margin-bottom', '12px'/);
});

test('PDF inline validation host never turns correctable input guidance into a bug report', () => {
  assert.match(html, /<p id="pdf-slice-validation"[^>]*data-officekit-no-bug-report/);
});
