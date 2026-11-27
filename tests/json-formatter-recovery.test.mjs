import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const client = html.match(/\/\* DEVELOPER UTILITIES CLIENT START \*\/([\s\S]*?)\/\* DEVELOPER UTILITIES CLIENT END \*\//)?.[1];
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];

function loadClient(fetch) {
  assert.ok(apiUrlHelper && client, 'developer utility client is present');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, TextEncoder };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

test('Format JSON preserves values and returns correctly indented output', async () => {
  let request;
  const context = loadClient(async (url, options) => {
    request = { url, body: JSON.parse(options.body) };
    return { ok: true, json: async () => ({ result: '{\n  "name": "Ada",\n  "active": true\n}' }) };
  });
  const input = '{"name":"Ada","active":true}';
  assert.equal(await context.officekitProcessDeveloperText('format_json', input), '{\n  "name": "Ada",\n  "active": true\n}');
  assert.equal(request.url, 'http://127.0.0.1:8000/api/devtools/process');
  assert.deepEqual(request.body, { operation: 'format_json', content: input });
});

test('malformed JSON stays editable and gets linked local guidance without result actions', async () => {
  let requests = 0;
  const context = loadClient(async () => { requests += 1; throw new Error('invalid JSON must stop before fetch'); });
  await assert.rejects(context.officekitProcessDeveloperText('format_json', '{"name":'), error => {
    assert.equal(error.jsonSyntax, true);
    assert.equal(error.inputError, true);
    assert.equal(error.message, 'This JSON is not valid. Check commas, brackets and quoted property names, then format again.');
    return true;
  });
  assert.equal(requests, 0);
  assert.match(html, /error\?\.jsonSyntax \|\| error\?\.inputError[\s\S]*?aria-invalid', 'true'[\s\S]*?data-officekit-no-bug-report/);
  assert.match(html, /id="developer-tools-copy" disabled hidden/);
  assert.match(html, /id="developer-tools-download" disabled hidden/);
  assert.match(html, /developer-tools-copy'\)\.hidden = false/);
  assert.match(html, /developer-tools-download'\)\.hidden = true/);
});
