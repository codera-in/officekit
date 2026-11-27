import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const apiClientSource = html.match(/function createOfficekitPasswordClient\([\s\S]*?\n        \}\n/)?.[0];

function loadClient(fetchImpl, readResponse = async (response) => {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}) {
  assert.ok(apiClientSource, 'password API client exists');
  const context = { fetchImpl, readResponse, officekitApiUrl: (url) => url, URLSearchParams };
  vm.runInNewContext(`${apiClientSource}\nglobalThis.client = createOfficekitPasswordClient({ fetchImpl, readResponse, apiUrl: officekitApiUrl });`, context);
  return context.client;
}

test('password screen is searchable and has a stable screen destination', () => {
  assert.match(html, /id="tab-password"/);
  assert.match(html, /password_generator: \{ tab: 'password' \}/);
  assert.match(registry, /"password_generator": \[[^\]]*passphrase/);
  assert.match(html, /const shellTabs = \[[^\]]*'password', 'color', 'network', 'system', 'quick-stats', 'ergonomics', \.\.\.officekitExtensionShellTabs\]/);
  assert.match(html, /id="password-generate-button"/);
  assert.match(html, /toolId:'password_generator',title:'Password & Passphrase Generator',text:result\.value/);
  assert.ok(html.includes("querySelector('.officekit-result-download')?.setAttribute('hidden', '')"));
  assert.match(html, /id="passphrase-generate-button"/);
});

test('password generator calls the bounded local API without retaining the result', async () => {
  let request;
  const client = loadClient(async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ password: 'A1!bcdefghij', theoretical_search_space_bits: 75.4 }) };
  });
  const result = await client.generatePassword({ length: 12, includeSymbols: true });
  assert.equal(request.url, '/api/crypto/password?length=12&include_symbols=true');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.cache, 'no-store');
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { value: 'A1!bcdefghij', bits: 75.4 });
  assert.equal(JSON.stringify(request).includes(result.value), false);
});

test('passphrase generation sends only validated options and accepts configured separator', async () => {
  let request;
  const client = loadClient(async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ passphrase: 'amber.river.cloud.gentle.stone.moon', word_count: 6, separator: '.', theoretical_search_space_bits: 77.5 }) };
  });
  const result = await client.generatePassphrase({ wordCount: 6, separator: '.' });
  assert.equal(request.url, '/api/crypto/passphrase');
  assert.deepEqual(JSON.parse(request.options.body), { word_count: 6, separator: '.' });
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { value: 'amber.river.cloud.gentle.stone.moon', bits: 77.5 });
});

test('invalid bounds and malformed API success payloads fail closed', async () => {
  const client = loadClient(async () => ({ ok: true, json: async () => ({ password: 'short', theoretical_search_space_bits: 1 }) }));
  await assert.rejects(client.generatePassword({ length: 11, includeSymbols: true }), /length/);
  await assert.rejects(client.generatePassword({ length: 12, includeSymbols: true }), /response/);
  await assert.rejects(client.generatePassphrase({ wordCount: 5, separator: ' ' }), /word count/);
  await assert.rejects(client.generatePassphrase({ wordCount: 6, separator: '-' }), /separator/);
});

test('screen exposes explicit copy and clear actions, and never invokes persistence or telemetry', () => {
  assert.match(html, /id="password-copy-button"/);
  assert.match(html, /id="password-clear-button"/);
  assert.match(html, /id="passphrase-copy-button"/);
  assert.match(html, /id="passphrase-clear-button"/);
  const screen = html.match(/<section id="tab-password"[\s\S]*?(?=\n\n        <section id="tab-screenshot")/)?.[0];
  assert.ok(screen, 'password workbench screen exists');
  assert.match(screen, /never saved to recents, favorites, bookmarks or telemetry/i);
  assert.doesNotMatch(screen, /localStorage|recordRecent|saveResult|telemetry\s*\(/i);
});

test('changing password settings clears a stale or in-flight secret and its copy action', () => {
  const clearHandler = html.match(/function clearPasswordSecret\([\s\S]*?\n        \}/)?.[0];
  const invalidateHandler = html.match(/function officekitInvalidatePasswordSettings\([\s\S]*?\n        \}/)?.[0];
  assert.ok(clearHandler, 'secret clearing handler exists');
  assert.ok(invalidateHandler, 'settings invalidation handler exists');
  assert.match(html, /password-symbols'\)\.addEventListener\('change', \(\) => \{\s*officekitInvalidatePasswordSettings\(\)/);

  for (const { secret, generating } of [
    { secret: 'redacted-test-secret', generating: false },
    { secret: '', generating: true },
  ]) {
    const removedActions = [];
    const output = { textContent: 'secret still visible', parentElement: { querySelector: () => ({ remove: () => removedActions.push(true) }) } };
    const copy = { disabled: false };
    const clear = { disabled: false, hidden: false };
    const generate = { disabled: generating };
    const status = {};
    const nodes = {
      'password-output': output,
      'password-copy-button': copy,
      'password-clear-button': clear,
      'password-generate-button': generate,
      'password-generator-status': status,
    };
    const messages = [];
    const context = {
      officekitPasswordRequest: 1,
      officekitPasswordSecret: secret,
      document: { getElementById: (id) => nodes[id] },
      officekitOutcome: { show: (_node, outcome) => messages.push(outcome) },
    };
    vm.runInNewContext(`${clearHandler}\n${invalidateHandler}\nofficekitInvalidatePasswordSettings();`, context);

    assert.equal(context.officekitPasswordSecret, '');
    assert.equal(output.textContent, 'Generate to show your password here.');
    assert.equal(copy.disabled, true);
    assert.equal(clear.disabled, true);
    assert.equal(clear.hidden, true);
    assert.equal(generate.disabled, false);
    assert.deepEqual(removedActions, [true]);
    assert.equal(messages.at(-1).text, 'Settings changed. Generate again to use the selected options.');
  }
});

test('clipboard denial is presented without logging the generated secret', async () => {
  const clickHandler = html.match(/async function copyPasswordSecret\([\s\S]*?\n        \}/)?.[0];
  assert.ok(clickHandler, 'explicit copy handler exists');
  const writes = [];
  const messages = [];
  const context = {
    navigator: { clipboard: { writeText: async (value) => { writes.push(value); throw new Error('denied'); } } },
    officekitPasswordSecret: 'Sensitive-password-42!',
    officekitPassphraseSecret: '',
    document: { getElementById: () => ({ set textContent(value) { messages.push(value); } }) },
  };
  vm.runInNewContext(`${clickHandler}\ncopyPasswordSecret();`, context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(writes, ['Sensitive-password-42!']);
  assert.equal(messages.join(' ').includes('Sensitive-password-42!'), false);
  assert.match(messages.join(' '), /clipboard permission/i);
});
