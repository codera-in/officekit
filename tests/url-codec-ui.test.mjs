import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/url-codec-workbench.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* URL CODEC CLIENT START \*\/([\s\S]*?)\/\* URL CODEC CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(client, 'strict URL codec client exists');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, TextEncoder };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

test('URL codec mock documents the local, direct encode/decode flow', () => {
  for (const text of ['Before', 'After', 'Encode', 'Decode', 'URI-component', 'malformed percent escapes', 'Copy result', 'Clear']) assert.ok(mock.includes(text), text);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('URL codec is searchable and opens its dedicated converter panel', () => {
  assert.match(registry, /"id": "url_codec"/);
  assert.match(registry, /"url_codec": \[[^\]]*percent encode[^\]]*percent decode/);
  assert.match(html, /url_codec: \{ tab: 'converter', converterMode: 'url_codec', focusId: 'url-codec-input' \}/);
  for (const id of ['url-codec-panel','url-codec-mode-encode','url-codec-mode-decode','url-codec-input','url-codec-run','url-codec-output','url-codec-copy','url-codec-clear','url-codec-status']) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /not saved to History/);
});

test('URL Codec mode selectors retain readable segmented-button sizing after mode changes', () => {
  for (const id of ['url-codec-mode-encode', 'url-codec-mode-decode']) {
    const button = html.match(new RegExp(`<button[^>]*id="${id}"[^>]*>`))?.[0];
    assert.ok(button, `${id} exists`);
    assert.match(button, /\bbtn\b/);
    assert.doesNotMatch(button, /\bbtn-square\b/, `${id} has a text label, so it must not use square icon sizing`);
  }
  const modeHandler = html.match(/function setUrlCodecMode\(operation\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(modeHandler, 'mode handler exists');
  assert.match(modeHandler, /className = encode \? '[^']*\bbtn btn-primary'/);
  assert.match(modeHandler, /className = !encode \? '[^']*\bbtn btn-primary'/);
});

test('encode and decode use the typed local developer-tools operation', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ result: calls.length === 1 ? 'Search%20%26%20filter%20%2F%20caf%C3%A9' : 'Search & filter / café' }) };
  });
  const encoded = await context.officekitProcessUrlText('Search & filter / café', 'url_encode');
  const decoded = await context.officekitProcessUrlText(encoded, 'url_decode');
  assert.equal(encoded, 'Search%20%26%20filter%20%2F%20caf%C3%A9');
  assert.equal(decoded, 'Search & filter / café');
  assert.deepEqual(calls.map(({ url }) => url), ['http://127.0.0.1:8000/api/devtools/process', 'http://127.0.0.1:8000/api/devtools/process']);
  assert.deepEqual(calls.map(({ options }) => JSON.parse(options.body)), [
    { operation: 'url_encode', content: 'Search & filter / café' },
    { operation: 'url_decode', content: encoded },
  ]);
});

test('URL codec rejects invalid modes, malformed DTOs, invalid Unicode and oversized UTF-8 before use', async () => {
  let requests = 0;
  const context = loadClient(async () => { requests += 1; return { ok: true, json: async () => ({ result: 'ok' }) }; });
  await assert.rejects(context.officekitProcessUrlText('text', 'base64_encode'), /Choose URL encode or decode/);
  await assert.rejects(context.officekitProcessUrlText('\ud800', 'url_encode'), /valid Unicode/);
  await assert.rejects(context.officekitProcessUrlText('😀'.repeat(262145), 'url_encode'), /1 MiB in UTF-8/);
  await assert.rejects(context.officekitProcessUrlText('x'.repeat(1_048_577), 'url_encode'), /1 MiB/);
  assert.equal(requests, 0);

  const malformed = loadClient(async () => ({ ok: true, json: async () => ({ result: 'x', extra: true }) }));
  await assert.rejects(malformed.officekitProcessUrlText('x', 'url_decode'), /invalid URL conversion response/);
  const invalidStatus = loadClient(async () => ({ ok: false, status: 422, json: async () => ({ detail: 'unsafe details' }) }));
  const invalidInputError = await invalidStatus.officekitProcessUrlText('%GG', 'url_decode').then(() => null, error => error);
  assert.match(invalidInputError.message, /Check percent escapes/);
  assert.equal(invalidInputError.inputError, true);
  const serverFailure = loadClient(async () => ({ ok: false, status: 500, json: async () => ({ detail: 'private details' }) }));
  const serverError = await serverFailure.officekitProcessUrlText('%GG', 'url_decode').then(() => null, error => error);
  assert.match(serverError.message, /could not be converted/);
  assert.equal(serverError.inputError, undefined);
  const oversized = loadClient(async () => ({ ok: true, json: async () => ({ result: 'x'.repeat(3_145_729) }) }));
  await assert.rejects(oversized.officekitProcessUrlText('x', 'url_encode'), /supported size limit/);
});

test('URL codec clear removes transient text and clipboard denial leaves the result intact', async () => {
  const clearResult = html.match(/function clearUrlCodecResult\(\) \{[\s\S]*?\n        \}/)?.[0];
  const clear = html.match(/function clearUrlCodec\(\) \{[\s\S]*?\n        \}/)?.[0];
  const copy = html.match(/async function copyUrlCodecResult\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(clear, 'clear action is explicit');
  assert.ok(clearResult, 'result reset helper is explicit');
  assert.ok(copy, 'clipboard action is explicit');
  const elements = new Map([
    ['url-codec-input', { value: 'secret / text' }],
    ['url-codec-output', { value: 'secret%20%2F%20text' }],
    ['url-codec-copy', { disabled: false }],
    ['url-codec-count', { textContent: '' }],
    ['url-codec-status', {
      id: 'url-codec-status', textContent: 'Check percent escapes', className: '',
      dataset: { officekitNoBugReport: 'true' },
      getAttribute(name) { return name === 'aria-describedby' ? this.describedBy : null; },
      setAttribute(name, value) { if (name === 'role') this.role = value; },
      removeAttribute(name) { if (name === 'aria-describedby') this.describedBy = undefined; },
      querySelector() { return null; },
    }],
  ]);
  const input = elements.get('url-codec-input');
  input.setAttribute = function(name, value) { this[name] = value; };
  input.removeAttribute = function(name) { delete this[name]; };
  input.getAttribute = function(name) { return this[name] ?? null; };
  elements.get('url-codec-output').parentElement = { querySelector() { return null; } };
  const clearContext = {
    TextEncoder,
    document: { getElementById: id => elements.get(id) },
    officekitOutcome: { show() {}, clear(status) { status.textContent = ''; } },
    officekitUnregisterResultCapability() {},
  };
  vm.runInNewContext(`${clearResult}\n${clear}\nupdateUrlCodecCount = () => {};\nclearUrlCodec();`, clearContext);
  assert.equal(elements.get('url-codec-input').value, '');
  assert.equal(elements.get('url-codec-output').value, '');
  assert.equal(elements.get('url-codec-copy').disabled, true);
  assert.equal(input['aria-invalid'], undefined);
  assert.equal(input['aria-describedby'], undefined);
  assert.equal(elements.get('url-codec-status').dataset.officekitNoBugReport, undefined);
  assert.equal(elements.get('url-codec-status').textContent, '');

  elements.get('url-codec-output').value = 'secret%20%2F%20text';
  const copyContext = {
    navigator: { clipboard: { writeText: async () => { throw new Error('denied'); } } },
    document: { getElementById: id => elements.get(id) },
  };
  vm.runInNewContext(copy, copyContext);
  await copyContext.copyUrlCodecResult();
  assert.equal(elements.get('url-codec-output').value, 'secret%20%2F%20text');
  assert.match(elements.get('url-codec-status').textContent, /denied/i);
  assert.doesNotMatch(elements.get('url-codec-status').textContent, /secret/);
});

test('URL Codec exposes decode validation on the field and clears it when input changes', async () => {
  const clearResult = html.match(/function clearUrlCodecResult\(\) \{[\s\S]*?\n        \}/)?.[0];
  const run = html.match(/async function runUrlCodec\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(clearResult && run, 'URL decode state handlers exist');
  const attributes = new Map();
  const status = {
    id: 'url-codec-status', textContent: '', className: '', dataset: {},
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name] ?? null; },
    removeAttribute(name) { delete this[name]; },
    querySelector() { return null; },
  };
  const input = {
    value: '%ZZ',
    setAttribute(name, value) { attributes.set(name, value); },
    getAttribute(name) { return attributes.get(name) ?? null; },
    removeAttribute(name) { attributes.delete(name); },
  };
  const output = { value: 'stale result', parentElement: { querySelector() { return null; } } };
  const runButton = { disabled: false };
  const copy = { disabled: false };
  const elements = new Map([
    ['url-codec-input', input], ['url-codec-output', output], ['url-codec-run', runButton],
    ['url-codec-copy', copy], ['url-codec-status', status],
  ]);
  const context = {
    document: { getElementById: id => elements.get(id) },
    TextEncoder,
    urlCodecOperation: 'url_decode',
    officekitUnregisterResultCapability() {},
    officekitProcessUrlText: async () => { const error = new Error('Check percent escapes'); error.inputError = true; throw error; },
    officekitPublishTextResult() {},
    officekitOutcome: {
      clear(slot) { slot.textContent = ''; },
      show(slot, { state, text }) { slot.textContent = text; slot.role = state === 'error' ? 'alert' : 'status'; },
    },
  };
  vm.runInNewContext(`${clearResult}\n${run}`, context);
  await context.runUrlCodec();
  assert.equal(output.value, '');
  assert.equal(attributes.get('aria-invalid'), 'true');
  assert.equal(attributes.get('aria-describedby'), 'url-codec-status');
  assert.equal(status.dataset.officekitNoBugReport, 'true');
  assert.match(status.textContent, /Check percent escapes/);
  assert.equal(runButton.disabled, false);
  context.clearUrlCodecResult();
  assert.equal(attributes.has('aria-invalid'), false);
  assert.equal(attributes.has('aria-describedby'), false);
  assert.equal(status.dataset.officekitNoBugReport, undefined);
  assert.equal(status.textContent, '');
});
