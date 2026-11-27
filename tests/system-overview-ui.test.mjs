import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/system-overview-workbench.html'), 'utf8');

function extract(source, pattern, name) {
  const match = source.match(pattern);
  assert.ok(match?.[0], `${name} is present`);
  return match[0];
}

const exact = extract(html, /function officekitSystemExactKeys\([\s\S]*?\n        \}/, 'exact system response key validator');
const finite = extract(html, /function officekitNetworkFinite\([\s\S]*?\n        \}/, 'finite numeric validator');
const apiUrl = extract(html, /function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/, 'API URL helper');
const infoValidator = extract(html, /function officekitValidateSystemInfo\([\s\S]*?\n        \}/, 'redacted system report validator');
const resourceValidator = extract(html, /function officekitValidateSystemResources\([\s\S]*?\n        \}/, 'resource metrics validator');
const formatGb = extract(html, /function officekitFormatGb\([\s\S]*?\n        \}/, 'gigabyte formatter');
const recommender = extract(html, /function officekitSystemRecommendations\([\s\S]*?\n        \}/, 'system recommendation rules');
const loader = extract(html, /async function officekitLoadSystemData\([\s\S]*?\n        \}/, 'system API client');
const binder = extract(html, /function officekitBindSystemWorkbench\([\s\S]*?\n        \}/, 'system workbench actions');

const info = {
  os_name: 'macOS', os_version: '15.5', architecture: 'arm64', logical_cpu_count: 8, physical_cpu_count: 4,
  memory_total_bytes: 16 * 1024 ** 3, memory_total_gb: 16,
  privacy_notice: 'Contains macOS version, architecture, CPU core counts and memory capacity only. Device identifiers and host/account names are excluded.',
  report_text: 'Operating system: macOS 15.5\nArchitecture: arm64\nCPU cores: 4 physical, 8 logical\nMemory: 16 GB',
};
const resources = {
  cpu_count: 8, cpu_percent: 12.5, cpu_sample_interval_seconds: 0.1, total_ram_gb: 16, available_ram_gb: 6,
  memory_total_bytes: 16 * 1024 ** 3, memory_available_bytes: 6 * 1024 ** 3, memory_used_estimate_bytes: 10 * 1024 ** 3,
  memory_percent: 62.5, optimal_workers: 6, cached: false, sample_age_ms: 0,
};

function load(fetch = async () => ({ ok: true, json: async () => ({}) })) {
  const read = async response => {
    if (response.ok) return response.json();
    const body = await response.json();
    throw new Error(typeof body.detail === 'string' ? body.detail : `OfficeKit request failed (${response.status})`);
  };
  const context = { Object, Number, Array, Math, JSON, Error, URL, window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${apiUrl}\n${finite}\n${exact}\nconst officekitReadApiResponse = ${read.toString()};\n${infoValidator}\n${resourceValidator}\n${loader}\nglobalThis.validateInfo = officekitValidateSystemInfo; globalThis.validateResources = officekitValidateSystemResources; globalThis.load = officekitLoadSystemData;`, context);
  return context;
}

test('system overview mock is responsive, local-only and distinguishes both tasks', () => {
  for (const phrase of ['API only', 'System overview', 'Refresh metrics', 'Redacted system report', 'does not monitor continuously', 'identifiers are excluded']) assert.match(mock, new RegExp(phrase, 'i'));
  assert.match(mock, /@media\(max-width:620px\)/);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('system tools are searchable and route to their dedicated actions', () => {
  const destinations = extract(html, /const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{[\s\S]*?\n        \}\);/, 'stable destinations');
  for (const [id, route] of [
    ['system_info', "system_info: { tab: 'system', focusId: 'system-refresh' }"],
    ['system_resources', "system_resources: { tab: 'system', focusId: 'system-refresh' }"],
  ]) {
    assert.ok(registry.includes(`"id": "${id}"`));
    assert.ok(destinations.includes(route));
  }
  assert.match(html, /id="tab-system"/);
  assert.match(html, /id="system-info-run"/);
  assert.match(html, /id="system-resources-run"/);
  assert.match(html, /id="system-recommendations-run"/);
  assert.match(html, /role="status" aria-live="polite" class="mt-3 min-h-6 text-sm text-slate-700"><\/p>\s*<div id="system-recommendations-result"/);
});

test('system API client uses exact local GET routes and validates full payloads', async () => {
  const calls = [];
  const c = load(async url => {
    calls.push(url);
    return { ok: true, json: async () => url.endsWith('/info') ? info : resources };
  });
  assert.deepEqual(JSON.parse(JSON.stringify(await c.load('info'))), info);
  assert.deepEqual(JSON.parse(JSON.stringify(await c.load('resources'))), resources);
  assert.deepEqual(calls, ['http://127.0.0.1:8000/api/system/info', 'http://127.0.0.1:8000/api/system/resources']);
  await assert.rejects(c.load('unknown'), /supported system report/);
  const malformed = load(async () => ({ ok: true, json: async () => ({ ...info, hostname: 'private-host' }) }));
  await assert.rejects(malformed.load('info'), /incomplete or inconsistent/);
  const unsupported = load(async () => ({ ok: false, status: 501, json: async () => ({ detail: 'System information is not supported on this platform.' }) }));
  await assert.rejects(unsupported.load('info'), /not supported on this platform/);
});

test('system validators reject identifiers, inconsistent report text, impossible CPU and memory data', () => {
  const c = load();
  assert.equal(c.validateInfo(info), true);
  assert.equal(c.validateInfo({ ...info, hostname: 'private-host' }), false);
  assert.equal(c.validateInfo({ ...info, report_text: `${info.report_text}\nSerial: secret` }), false);
  assert.equal(c.validateInfo({ ...info, physical_cpu_count: 9 }), false);
  assert.equal(c.validateInfo({ ...info, memory_total_gb: 15 }), false);
  assert.equal(c.validateResources(resources), true);
  assert.equal(c.validateResources({ ...resources, memory_used_estimate_bytes: 1 }), false);
  assert.equal(c.validateResources({ ...resources, memory_percent: 100 }), false);
  assert.equal(c.validateResources({ ...resources, cpu_percent: 101 }), false);
  assert.equal(c.validateResources({ ...resources, optimal_workers: 33 }), false);
  assert.equal(c.validateResources({ ...resources, extra: 'device id' }), false);
});

test('system recommendations distinguish app compatibility, dictation requirements and performance limits', () => {
  const context = { Math };
  vm.runInNewContext(`${formatGb}\n${recommender}\nglobalThis.recommend = officekitSystemRecommendations;`, context);
  const current = context.recommend(info, resources);
  assert.equal(current.compatible, true);
  assert.match(current.dictation, /Qwen3/);
  assert.match(current.performance, /not a benchmark/i);
  assert.match(current.limit, /cannot predict its speed/i);
  const older = context.recommend({ ...info, os_version: '14.4', architecture: 'arm64' }, resources);
  assert.equal(older.compatible, true);
  assert.match(older.dictation, /Qwen3 needs macOS 15 or later/);
  const unsupported = context.recommend({ ...info, os_version: '13.6', architecture: 'x86_64' }, resources);
  assert.equal(unsupported.compatible, false);
  assert.match(unsupported.compatibility, /requires macOS 14 or later and Apple silicon/);
  assert.match(unsupported.dictation, /require Apple silicon/);
});

test('System screen loads only on click, renders reconciled values and gives safe clipboard feedback', async () => {
  const elements = new Map();
  const document = { querySelectorAll() { return []; }, getElementById(id) {
    if (!elements.has(id)) elements.set(id, { listeners: {}, addEventListener(name, listener) { this.listeners[name] = listener; }, setAttribute(name, value) { this[name] = value; } });
    return elements.get(id);
  } };
  let calls = 0;
  const copied = [];
  const context = { Error, document, navigator: { clipboard: { writeText: async value => { copied.push(value); } } }, officekitSystemRecommendations: (systemInfo, systemResources) => ({ compatible: true, compatibilityTitle: 'Compatible', compatibility: 'ok', tools: 'ok', dictation: 'ok', performance: 'not a benchmark', limit: 'local' }), officekitLoadSystemData: async kind => { calls += 1; return kind === 'info' ? info : resources; } };
  vm.runInNewContext(`${formatGb}\n${binder}\nofficekitBindSystemWorkbench();`, context);
  assert.equal(calls, 0);
  assert.equal(typeof elements.get('system-resources-run').listeners.click, 'function');
  assert.equal(typeof elements.get('system-info-run').listeners.click, 'function');
  assert.equal(typeof elements.get('system-info-copy').listeners.click, 'function');
  assert.equal(typeof elements.get('system-recommendations-run').listeners.click, 'function');
  await elements.get('system-recommendations-run').listeners.click({ currentTarget: elements.get('system-recommendations-run') });
  assert.equal(calls, 2);
  assert.equal(elements.get('system-recommendations-result').hidden, false);
  assert.equal(elements.get('system-recommendations-performance').textContent, 'not a benchmark');
  context.officekitLoadSystemData = async () => { throw new Error('System information is not supported on this platform.'); };
  await elements.get('system-recommendations-run').listeners.click({ currentTarget: elements.get('system-recommendations-run') });
  assert.match(elements.get('system-recommendations-status').textContent, /not supported on this platform/);
  assert.equal(elements.get('system-recommendations-result').hidden, true);
  assert.equal(elements.get('system-recommendations-run').disabled, false);
  context.officekitLoadSystemData = async kind => { calls += 1; return kind === 'info' ? info : resources; };
  await elements.get('system-info-run').listeners.click({ currentTarget: elements.get('system-info-run') });
  assert.equal(calls, 3);
  assert.equal(elements.get('system-info-report').textContent, info.report_text);
  assert.equal(elements.get('system-info-result').hidden, false);
  await elements.get('system-info-copy').listeners.click();
  assert.deepEqual(copied, [info.report_text]);
  await elements.get('system-resources-run').listeners.click({ currentTarget: elements.get('system-resources-run') });
  assert.equal(calls, 4);
  assert.equal(elements.get('system-cpu-value').textContent, '12.5%');
  assert.equal(elements.get('system-memory-bar').value, 62.5);
  assert.equal(elements.get('system-memory-bar')['aria-valuenow'], '62.5');
  assert.equal(elements.get('system-workers-value').textContent, '6 concurrent jobs · heuristic');
  assert.equal(elements.get('system-memory-value').textContent, '10 of 16 GB');
  assert.match(html, /officekitFormatGb\(result\.total_ram_gb - result\.available_ram_gb\)/);
  context.navigator.clipboard.writeText = async () => { throw new Error('clipboard denied'); };
  await elements.get('system-info-copy').listeners.click();
  assert.match(elements.get('system-info-copy-status').textContent, /select the report text and copy it manually/i);
});
