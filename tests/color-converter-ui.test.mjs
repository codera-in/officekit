import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = readFileSync(path.join(root, 'design/mocks/color-converter-workbench.html'), 'utf8');
const clientSource = html.match(/async function officekitConvertColor\([\s\S]*?\n        \}\n/)?.[0];
const previewSource = html.match(/function officekitColorPreviewCss\([\s\S]*?\n        \}\n/)?.[0];

function loadClient(fetchImpl, readResponse = async response => {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}) {
  assert.ok(clientSource, 'typed color conversion client exists');
  const context = { fetch: fetchImpl, fetchImpl, officekitReadApiResponse: readResponse, officekitApiUrl: value => value };
  vm.runInNewContext(`${clientSource}\nglobalThis.convert = officekitConvertColor;`, context);
  return context.convert;
}

test('color converter mock documents current route and simple after flow', () => {
  assert.match(mock, /Before/);
  assert.match(mock, /After/);
  assert.match(mock, /HEX/);
  assert.match(mock, /RGB/);
  assert.match(mock, /HSL/);
  assert.match(mock, /HSV/);
  assert.match(mock, /alpha/i);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('color conversion is searchable and routed to a dedicated screen', () => {
  assert.match(registry, /"id": "color_converter"/);
  assert.match(registry, /"color_converter": \[[^\]]*hex/);
  assert.match(html, /color_converter: \{ tab: 'color' \}/);
  assert.match(html, /id="tab-color"/);
  assert.match(html, /id="color-convert-button"/);
  assert.doesNotMatch(html, /id="color-copy-button"/);
  assert.match(html, /id="color-picker" type="color"/);
  assert.match(html, /id="color-preview-status"/);
  assert.match(html, /checkerboard/i);
});

test('color picker previews valid formats live and keeps invalid values out of CSS', () => {
  assert.ok(previewSource, 'preview parser exists');
  const context = { CSS: { supports: (_property, value) => /^(?:rgb|hsl)a?\(/i.test(value) } };
  vm.runInNewContext(`${previewSource}\nglobalThis.preview = officekitColorPreviewCss;`, context);
  assert.equal(context.preview('#1f6feb80', 'hex'), '#1f6feb80');
  assert.equal(context.preview('hsl(120, 100%, 50%)', 'hsl'), 'hsl(120, 100%, 50%)');
  assert.equal(context.preview('hsv(0, 100%, 100%)', 'hsv'), 'rgb(255, 0, 0)');
  assert.equal(context.preview('hsva(240, 100%, 100%, 0.25)', 'hsv'), 'rgba(0, 0, 255, 0.25)');
  assert.equal(context.preview('hsv(361, 100%, 100%)', 'hsv'), '');
  assert.equal(context.preview('#bad; color: red', 'hex'), '');
});

test('color converter keeps syntax feedback local and restores shared dock actions', () => {
  const preview = html.match(/function officekitUpdateColorPreview\(\) \{[\s\S]*?\n        \}/)?.[0];
  const clearActions = html.match(/function officekitClearColorResultActions\(\) \{[\s\S]*?\n        \}/)?.[0];
  const convert = html.match(/async function officekitRunColorConversion\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.match(html, /id="color-action-dock"/);
  assert.match(html, /aria-label="Color converter actions"/);
  assert.match(preview, /aria-invalid/);
  assert.match(preview, /data-officekit-no-bug-report/);
  assert.match(convert, /officekitColorPreviewCss\(input\.value\.trim\(\)/);
  assert.match(convert, /dockControls\.replaceChildren\(document\.getElementById\('color-clear-button'\), resultActions, button\)/);
  assert.match(clearActions, /#tab-color \.officekit-result-actions/);
});

test('editing the color invalidates a stale converted result and updates the live preview', () => {
  const clearActions = html.match(/function officekitClearColorResultActions\(\) \{[\s\S]*?\n        \}/)?.[0];
  const preview = html.match(/function officekitColorPreviewCss\([\s\S]*?\n        \}\n/)?.[0];
  const update = html.match(/function officekitUpdateColorPreview\([\s\S]*?\n        \}\n/)?.[0];
  const draft = html.match(/function officekitColorDraftChanged\([\s\S]*?\n        \}\n/)?.[0];
  const bind = html.match(/function officekitBindColorPicker\([\s\S]*?\n        \}\n/)?.[0];
  const events = new Map();
  const elements = new Map([
    ['color-input', { value: '#00ff00', closest: () => ({ setAttribute() {}, removeAttribute() {} }), setAttribute() {}, removeAttribute() {}, addEventListener: (name, callback) => events.set(`color-input:${name}`, callback) }],
    ['color-picker', { value: '#ff0000', addEventListener: (name, callback) => events.set(`color-picker:${name}`, callback) }],
    ['color-source-format', { value: 'hex', addEventListener: (name, callback) => events.set(`color-source-format:${name}`, callback) }],
    ['color-target-format', { value: 'rgb' }],
    ['color-swatch', { style: {}, setAttribute() {} }],
    ['color-preview-status', { textContent: '', setAttribute() {} }],
    ['color-output', { textContent: 'rgb(255, 0, 0)' }],
    ['color-convert-button', { hidden: true }],
    ['color-clear-button', { hidden: false }],
    ['color-status', { textContent: 'Converted locally.' }],
  ]);
  const context = {
    officekitConvertedColor: 'rgb(255, 0, 0)', CSS: { supports: () => true },
    window: { officekitUnregisterResultCapability() {}, OfficeKitToolActions: { schedule() {} } },
    document: { getElementById: id => elements.get(id), querySelector: () => null },
  };
  vm.runInNewContext(`${clearActions}\n${preview}\n${update}\n${draft}\n${bind}\nofficekitBindColorPicker();`, context);
  events.get('color-input:input')();
  assert.equal(context.officekitConvertedColor, '');
  assert.equal(elements.get('color-output').textContent, 'Convert to see the result.');
  assert.equal(elements.get('color-status').textContent, '');
  assert.equal(elements.get('color-swatch').style.backgroundColor, '#00ff00');
});

test('client uses the typed local API and validates response formats and color value', async () => {
  let request;
  const convert = loadClient(async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ value: 'rgba(255, 0, 0, 0.5)', source_format: 'hex', target_format: 'rgb' }) };
  });
  const result = await convert({ value: '#f008', sourceFormat: 'hex', targetFormat: 'rgb' });
  assert.equal(request.url, '/api/colors/convert');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), { value: '#f008', source_format: 'hex', target_format: 'rgb' });
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { value: 'rgba(255, 0, 0, 0.5)', sourceFormat: 'hex', targetFormat: 'rgb' });
});

test('client rejects empty, oversized, unsupported and malformed conversion data', async () => {
  const invalid = loadClient(async () => ({ ok: true, json: async () => ({ value: '#fff', source_format: 'hex', target_format: 'rgb', extra: true }) }));
  await assert.rejects(invalid({ value: '', sourceFormat: 'hex', targetFormat: 'rgb' }), /color value/);
  await assert.rejects(invalid({ value: 'x'.repeat(129), sourceFormat: 'hex', targetFormat: 'rgb' }), /128/);
  await assert.rejects(invalid({ value: '#fff', sourceFormat: 'cmyk', targetFormat: 'rgb' }), /format/);
  await assert.rejects(invalid({ value: '#fff', sourceFormat: 'hex', targetFormat: 'rgb' }), /valid color response/);
});

test('color results expose copy and download through the shared result action component', () => {
  assert.doesNotMatch(html, /id="color-copy-button"/);
  assert.match(html, /officekitPublishComputedResult\(document\.getElementById\('color-status'\)\.parentElement/);
  assert.match(html, /dockControls\.replaceChildren\(document\.getElementById\('color-clear-button'\), resultActions, button\)/);
});

test('clear removes only the transient input and output from the screen', () => {
  const clearActions = html.match(/function officekitClearColorResultActions\(\) \{[\s\S]*?\n        \}/)?.[0];
  const clearHandler = html.match(/function officekitClearColor\([\s\S]*?\n        \}/)?.[0];
  assert.ok(clearHandler, 'clear action has an explicit handler');
  const elements = new Map([
    ['color-input', { value: '#ff00aa', closest: () => ({ setAttribute() {}, removeAttribute() {} }), setAttribute() {}, removeAttribute() {} }],
    ['color-output', { textContent: '#ff00aa' }],
    ['color-status', { textContent: 'Copied converted color.' }],
    ['color-convert-button', { hidden: true }],
    ['color-clear-button', { hidden: false }],
    ['color-swatch', { style: { backgroundColor: '#ff00aa' }, setAttribute() {} }],
    ['color-picker', { value: '#ff00aa' }],
    ['color-source-format', { value: 'hex' }],
    ['color-preview-status', { textContent: '', setAttribute() {} }],
  ]);
  const preview = html.match(/function officekitColorPreviewCss\([\s\S]*?\n        \}\n/)?.[0];
  const update = html.match(/function officekitUpdateColorPreview\([\s\S]*?\n        \}\n/)?.[0];
  const context = {
    officekitConvertedColor: '#ff00aa', CSS: { supports: () => false },
    window: { officekitUnregisterResultCapability() {}, OfficeKitToolActions: { schedule() {} } },
    document: { getElementById: id => elements.get(id), querySelector: () => null },
  };
  vm.runInNewContext(`${clearActions}\n${preview}\n${update}\n${clearHandler}\nofficekitClearColor();`, context);
  assert.equal(context.officekitConvertedColor, '');
  assert.equal(elements.get('color-input').value, '');
  assert.equal(elements.get('color-output').textContent, 'Convert to see the result.');
  assert.equal(elements.get('color-status').textContent, '');
  assert.equal(elements.get('color-swatch').style.backgroundColor, '');
  assert.equal(elements.get('color-picker').value, '#000000');
  assert.equal(elements.get('color-preview-status').textContent, 'Enter a valid color to preview it.');
});
