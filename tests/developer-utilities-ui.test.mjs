import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const sliceSource = fs.readFileSync(path.join(root, 'assets/officekit-slice-developer.js'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/developer-utilities-workbench.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* DEVELOPER UTILITIES CLIENT START \*\/([\s\S]*?)\/\* DEVELOPER UTILITIES CLIENT END \*\//)?.[1];
const converterModeFunction = html.match(/function setConverterMode\(mode\) \{[\s\S]*?\n        \}/)?.[0];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'local API URL helper exists');
  assert.ok(client, 'developer utilities client exists');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, TextEncoder };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

test('developer utilities mock covers local processing and secret handling', () => {
  for (const text of ['JSON &amp; YAML', 'Base64', 'JWT inspector', 'Text hashes', 'Run locally', 'Copy result', 'Download result', 'never added to History', 'unverified', 'HMAC']) assert.ok(mock.includes(text), text);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('developer tool IDs search into the dedicated workbench', () => {
  for (const id of ['devtools_format', 'jwt_inspector', 'crypto_hashes']) assert.match(registry, new RegExp(`"id": "${id}"`));
  assert.match(html, /devtools_format: \{ tab: 'converter', converterMode: 'developer_tools'/);
  assert.match(html, /jwt_inspector: \{ tab: 'converter', converterMode: 'developer_tools'/);
  assert.match(html, /crypto_hashes: \{ tab: 'converter', converterMode: 'developer_tools'/);
  for (const id of ['developer-tools-panel', 'developer-tools-operation', 'developer-tools-input', 'developer-tools-secret', 'developer-tools-run', 'developer-tools-output', 'developer-tools-clear', 'developer-tools-status']) assert.match(html, new RegExp(`id="${id}"`));
});

test('specialized converter tools hide the generic converter title and unrelated Media Toolkit link', () => {
  assert.match(html, /id="converter-general-intro" class="text-center[^\"]*">\s*<h1 id="converter-title"/);
  assert.match(html, /converter-general-intro'\)\.classList\.toggle\('hidden', converterMode !== 'convert'\)/);
  assert.match(html, /open-media-toolkit'\)\.classList\.toggle\('hidden', converterMode !== 'convert'\)/);
});

test('converter intro and cross-link visibility follows the selected mode', () => {
  assert.ok(converterModeFunction, 'converter mode handler exists');
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, { classList: { toggle(name, force) { if (force) classes.add(name); else classes.delete(name); }, contains: name => classes.has(name) }, hidden: false, accept: '', focus() {} });
    }
    return elements.get(id);
  };
  const context = {
    document: { getElementById: get },
    window: { officekitMediaToolkit: { init() {} } },
    officekitIsPrivateBeta: () => false,
    officekitReleaseAllowsTool: () => true,
    clearGenericImagePreview() {},
    selectedGenericFile: null,
  };
  vm.runInNewContext(`${converterModeFunction}\nthis.setConverterMode = setConverterMode;`, context);
  for (const mode of ['developer_tools', 'url_codec', 'image_metadata', 'image_resize', 'media_toolkit']) {
    context.setConverterMode(mode);
    assert.equal(get('converter-general-intro').classList.contains('hidden'), true, `${mode} hides the generic converter intro`);
    assert.equal(get('open-media-toolkit').classList.contains('hidden'), true, `${mode} hides the unrelated Media Toolkit link`);
  }
  context.setConverterMode('convert');
  assert.equal(get('converter-general-intro').classList.contains('hidden'), false, 'generic conversion restores its heading');
  assert.equal(get('open-media-toolkit').classList.contains('hidden'), false, 'generic conversion restores the Media Toolkit link');
});

test('developer utilities place run, clear, status and shared result actions in the bottom dock', () => {
  assert.match(html, /<footer id="developer-tools-action-dock" class="ok-action-dock/);
  assert.match(html, /id="developer-tools-action-controls" class="ok-action-dock__controls"[\s\S]*?id="developer-tools-run"/);
  assert.match(html, /<button type="button" id="developer-tools-copy" disabled/);
  assert.match(html, /<button type="button" id="developer-tools-download" disabled/);
  assert.doesNotMatch(html, /developer-tools-action-controls'\),rendered,'Developer result'/);
  assert.match(html, /developer-tools-action-controls'\)\.querySelector\('\.officekit-result-actions'\)\?\.remove\(\)/);
});

test('Timestamp Converter DST gaps stay linked to the field and suppress generic bug reporting', () => {
  const timestampRun = html.slice(html.indexOf('async function runDeveloperTools'), html.indexOf('async function copyDeveloperToolsResult'));
  assert.match(timestampRun, /status\.removeAttribute\('data-officekit-no-bug-report'\)/, 'a later run can report a genuine processing failure');
  const catchStart = html.indexOf('if (error?.validationField) {');
  assert.notEqual(catchStart, -1, 'the run handler links any validation field named by the error');
  const timestampCatch = html.slice(catchStart, html.indexOf('\n                } else {', catchStart));
  assert.match(sliceSource, /clocks move forward\. Choose a later time\./);
  assert.match(timestampCatch, /getElementById\(error\.validationField\)/);
  assert.match(timestampCatch, /setAttribute\('aria-invalid', 'true'\)/);
  assert.match(timestampCatch, /setAttribute\('aria-describedby', error\.validationGuidance\)/);
  assert.match(timestampCatch, /data-officekit-no-bug-report/);
});

test('Text Metrics keeps the result visible above editable input and recovers from blank input locally', () => {
  assert.match(sliceSource, /function showMetricsResult\(node\)[\s\S]*?insertBefore\(result, inputLabel\.parentNode\)[\s\S]*?scrollIntoView\?\.\(\{ block: 'start' \}\)/);
  assert.match(sliceSource, /function clearSliceResult\(\)[\s\S]*?insertBefore\(result, outputLabel\)/);
  const runBody = html.slice(html.indexOf('async function runDeveloperTools'), html.indexOf('async function copyDeveloperToolsResult'));
  assert.match(runBody, /operation === 'text_metrics' && !input\.trim\(\)[\s\S]*?aria-invalid', 'true'[\s\S]*?aria-describedby', 'developer-tools-status'[\s\S]*?data-officekit-no-bug-report'[\s\S]*?Enter text to process\./);
  const inputBody = html.slice(html.indexOf("developer-tools-input').addEventListener('input'"), html.indexOf("developer-tools-secret').addEventListener('input'"));
  assert.match(inputBody, /operation === 'text_metrics'[\s\S]*?clearResult\?\.\(\)[\s\S]*?removeAttribute\('aria-invalid'\)[\s\S]*?removeAttribute\('data-officekit-no-bug-report'\)[\s\S]*?Input updated\. Run locally to process it\./);
});

test('Change Case keeps blank input editable, disables stale result actions and recovers locally', () => {
  const runBody = html.slice(html.indexOf('async function runDeveloperTools'), html.indexOf('async function copyDeveloperToolsResult'));
  const emptyCheck = runBody.indexOf("operation === 'text_case' && !input.trim()");
  assert.ok(runBody.indexOf("getElementById('developer-tools-copy').disabled = true") < emptyCheck);
  assert.ok(runBody.indexOf("getElementById('developer-tools-download').disabled = true") < emptyCheck);
  assert.match(runBody, /operation === 'text_case' && !input\.trim\(\)[\s\S]*?aria-invalid', 'true'[\s\S]*?aria-describedby', 'developer-tools-status'[\s\S]*?data-officekit-no-bug-report'[\s\S]*?Enter text to change its case\./);
  const inputBody = html.slice(html.indexOf("developer-tools-input').addEventListener('input'"), html.indexOf("developer-tools-secret').addEventListener('input'"));
  assert.match(inputBody, /removeAttribute\('aria-invalid'\)[\s\S]*?removeAttribute\('aria-describedby'\)[\s\S]*?removeAttribute\('data-officekit-no-bug-report'\)[\s\S]*?Input updated\. Run locally to process it\./);
});

test('strict bounded operations use only the typed local endpoints', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return { ok: true, json: async () => calls.at(-1).url.endsWith('/hashes') ? { md5:'0'.repeat(32), sha1:'1'.repeat(40), sha256:'2'.repeat(64), sha512:'3'.repeat(128), crc32:'4'.repeat(8), hmac_sha256:'5'.repeat(64) } : calls.at(-1).body.operation === 'jwt_decode' ? { header:{alg:'none'}, payload:{sub:'42'}, is_verified:false, notice:'Signature not verified.' } : { result:'{"ok":true}' } };
  });
  assert.equal(await context.officekitProcessDeveloperText('format_json', '{"ok":true}'), '{"ok":true}');
  const jwt = await context.officekitProcessDeveloperText('decode_jwt', 'eyJhbGciOiJub25lIn0.eyJzdWIiOiI0MiJ9.x');
  assert.equal(jwt.is_verified, false);
  const hashes = await context.officekitProcessHashes('sample', 'transient-secret');
  assert.equal(hashes.sha256.length, 64);
  assert.deepEqual(calls.map(call => call.url), ['http://127.0.0.1:8000/api/devtools/process', 'http://127.0.0.1:8000/api/devtools/process', 'http://127.0.0.1:8000/api/crypto/hashes']);
  assert.deepEqual(calls.map(call => call.body), [
    { operation: 'format_json', content: '{"ok":true}' },
    { operation: 'jwt_decode', content: 'eyJhbGciOiJub25lIn0.eyJzdWIiOiI0MiJ9.x' },
    { text: 'sample', secret: 'transient-secret' },
  ]);
});

test('developer client rejects secret-size errors and malformed response DTOs', async () => {
  let requests = 0;
  const normal = loadClient(async () => { requests += 1; return { ok: true, json: async () => ({ result:'ok' }) }; });
  await assert.rejects(normal.officekitProcessDeveloperText('decode_jwt', 'x'.repeat(1_048_577)), /1 MiB/);
  await assert.rejects(normal.officekitProcessDeveloperText('format_json', '\ud800'), /valid Unicode/);
  await assert.rejects(normal.officekitProcessHashes('\ud800'), /valid Unicode/);
  await assert.rejects(normal.officekitProcessDeveloperText('unknown', 'x'), /Choose a supported/);
  const malformed = loadClient(async () => ({ ok:true, json:async () => ({ result:'ok', extra:true }) }));
  await assert.rejects(malformed.officekitProcessDeveloperText('format_json', '{}'), /invalid developer-tool response/);
  const badHash = loadClient(async () => ({ ok:true, json:async () => ({ md5:'bad', sha1:'1'.repeat(40), sha256:'2'.repeat(64), sha512:'3'.repeat(128), crc32:'4'.repeat(8) }) }));
  await assert.rejects(badHash.officekitProcessHashes('abc'), /invalid hash response/);
  const rejected = loadClient(async () => ({ ok:false, json:async () => ({ detail:'secret backend detail' }) }));
  await assert.rejects(rejected.officekitProcessDeveloperText('decode_jwt', 'bad'), /locally/);
  assert.equal(requests, 0);
});

test('developer utilities stay transient and clear clipboard output safely', () => {
  assert.match(html, /stay out of History, Favorites, bookmarks and telemetry/i);
  assert.match(html, /signatures are not verified/i);
  assert.match(html, /function clearDeveloperTools\(\)/);
  assert.match(html, /async function copyDeveloperToolsResult\(\)/);
});

test('JWT screen operation maps to the declared jwt_decode API operation', async () => {
  let body;
  const client = loadClient(async (_url, options) => {
    body = JSON.parse(options.body);
    return { ok: true, json: async () => ({ header: { alg: 'HS256' }, payload: { sub: 'reference' }, is_verified: false, notice: 'Signature not verified.' }) };
  });
  const decoded = await client.officekitProcessDeveloperText('decode_jwt', 'header.payload.signature');
  assert.equal(body.operation, 'jwt_decode');
  assert.equal(decoded.is_verified, false);
});
