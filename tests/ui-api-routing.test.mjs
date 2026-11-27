import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceHtml = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');
const bundledHtml = fs.readFileSync(path.join(repoRoot, 'dist-ui/index.html'), 'utf8');
const helper = sourceHtml.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const startupRequestHelper = sourceHtml.match(/const OFFICEKIT_STARTUP_API_TIMEOUT_MS = \d+;\n        function officekitStartupFetch\(path, timeoutMs = OFFICEKIT_STARTUP_API_TIMEOUT_MS\) \{[\s\S]*?\n        \}/)?.[0];

function resolveApiUrl(protocol, hostname, pathValue) {
  assert.ok(helper, 'OfficeKit API URL helper exists');
  const context = { window: { location: { protocol, hostname } } };
  return vm.runInNewContext(`${helper}; officekitApiUrl(${JSON.stringify(pathValue)})`, context);
}

test('Tauri custom protocol sends API calls to the loopback sidecar', () => {
  assert.equal(resolveApiUrl('tauri:', 'localhost', '/api/health'), 'http://127.0.0.1:8000/api/health');
});

test('Windows Tauri origin sends API calls to the loopback sidecar', () => {
  assert.equal(resolveApiUrl('http:', 'tauri.localhost', '/api/health'), 'http://127.0.0.1:8000/api/health');
});

test('browser development keeps same-origin API paths', () => {
  assert.equal(resolveApiUrl('http:', '127.0.0.1', '/api/health'), '/api/health');
});

test('every current API fetch is explicitly routed through the helper', () => {
  const fetchLines = sourceHtml.split('\n').filter(line => line.includes('fetch('));
  assert.ok(fetchLines.length > 0);
  assert.ok(fetchLines.every(line => line.includes('officekitApiUrl(')));
  assert.equal(sourceHtml, bundledHtml, 'Tauri bundle must match the tested source HTML');
});

test('delegated action arguments accept booleans but still reject arbitrary identifiers', () => {
  const parser = sourceHtml.match(/function officekitParseDelegatedArguments\(source, event, element\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(parser, 'the delegated action argument parser exists');
  const parse = source => vm.runInNewContext(
    `${parser}; officekitParseDelegatedArguments(${JSON.stringify(source)}, { type: 'click' }, { value: 'kept' })`,
  );
  assert.deepEqual(Array.from(parse('true, false')), [true, false]);
  assert.deepEqual(Array.from(parse("'manual', this.value")), ['manual', 'kept']);
  assert.equal(parse('globalThis'), null);
});

test('Tauri API fetches attach a cached bearer token and non-API requests stay untouched', async () => {
  const authBlock = sourceHtml.match(/let officekitApiTokenPromise[\s\S]*?officekitInstallApiAuth\(\);/)?.[0];
  assert.ok(authBlock, 'Tauri API authentication client is installed');
  const calls = [];
  const token = '0123456789abcdef0123456789abcdef';
  const window = {
    location: { protocol: 'tauri:', hostname: 'localhost', href: 'tauri://localhost/' },
    __TAURI__: { core: { invoke: async (command) => {
      if (command === 'officekit_api_token') return token;
      if (command === 'officekit_api_origin') return 'http://127.0.0.1:8017';
      assert.fail(`unexpected command ${command}`);
    } } },
    fetch: async (input, init) => {
      calls.push({ input, init });
      return { ok: true };
    },
  };
  const context = { window, URL, Headers, Request, Promise };
  vm.runInNewContext(authBlock, context);

  await window.fetch('http://127.0.0.1:8000/api/tools/search');
  await window.fetch('https://cdn.example/assets.css');

  assert.equal(calls.length, 2);
  assert.equal(calls[0].input, 'http://127.0.0.1:8017/api/tools/search');
  assert.equal(new Headers(calls[0].init.headers).get('authorization'), `Bearer ${token}`);
  assert.equal(Object.keys(calls[1].init).length, 0);
});

test('Tauri API client fails closed when IPC cannot provide a valid token', async () => {
  const authBlock = sourceHtml.match(/let officekitApiTokenPromise[\s\S]*?officekitInstallApiAuth\(\);/)?.[0];
  assert.ok(authBlock, 'Tauri API authentication client is installed');
  let requestCount = 0;
  const window = {
    location: { protocol: 'tauri:', hostname: 'localhost', href: 'tauri://localhost/' },
    __TAURI__: { core: { invoke: async () => 'bad' } },
    fetch: async () => { requestCount += 1; return { ok: true }; },
  };
  vm.runInNewContext(authBlock, { window, URL, Headers, Request, Promise });

  await assert.rejects(window.fetch('http://127.0.0.1:8000/api/health'), /invalid local API credential/);
  assert.equal(requestCount, 0);
});

test('catalogue startup requests time out when the local API or Tauri bridge hangs', async () => {
  assert.ok(startupRequestHelper, 'startup API requests have a bounded wait');
  assert.match(sourceHtml, /fetchToolSearchResults\(''\)/);

  let requestSignal;
  const window = {
    setTimeout,
    clearTimeout,
    fetch: (_url, init) => {
      requestSignal = init.signal;
      return new Promise(() => {});
    },
  };
  const context = { window, AbortController, Promise, officekitApiUrl: path => path };
  vm.runInNewContext(startupRequestHelper, context);

  await assert.rejects(context.officekitStartupFetch('/api/tools/search?q=', 5), /request timed out/);
  assert.equal(requestSignal.aborted, true, 'the timed-out HTTP request is aborted');
});
