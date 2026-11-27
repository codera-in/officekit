import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/network-diagnostics-workbench.html'), 'utf8');

function extract(source, pattern, name) {
  const match = source.match(pattern);
  assert.ok(match?.[0], `${name} is present`);
  return match[0];
}

const statuses = extract(html, /const OFFICEKIT_NETWORK_STATUSES = Object\.freeze\(\{[\s\S]*?\n        \}\);/, 'network status catalogue');
const dnsTypes = extract(html, /const OFFICEKIT_DNS_RECORD_TYPES = Object\.freeze\(\[[\s\S]*?\]\);/, 'supported DNS record types');
const selectableTypes = extract(html, /const OFFICEKIT_DNS_SELECTABLE_TYPES = Object\.freeze\(\[[\s\S]*?\]\);/, 'selectable DNS record types');
const dkimSelector = extract(html, /const OFFICEKIT_DKIM_SELECTOR = .*;/, 'DKIM selector pattern');
const explain = extract(html, /function officekitDnsExplain\([\s\S]*?\n        \}\n/, 'SPF and DKIM explanations');
const exact = extract(html, /function officekitNetworkExactKeys\([\s\S]*?\n        \}/, 'strict response key validator');
const finite = extract(html, /function officekitNetworkFinite\([\s\S]*?\n        \}/, 'finite number validator');
const validIp = extract(html, /function officekitNetworkValidIp\([\s\S]*?\n        \}/, 'IP address validator');
const addressFamily = extract(html, /function officekitNetworkAddressMatchesFamily\([\s\S]*?\n        \}/, 'IP family validator');
const validRequest = extract(html, /function officekitNetworkValidRequest\([\s\S]*?\n        \}/, 'network request validator');
const validate = extract(html, /function officekitValidateNetworkResponse\([\s\S]*?\n        \}/, 'network response validator');
const apiUrl = extract(html, /function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/, 'API URL helper');
const request = extract(html, /async function officekitNetworkRequest\([\s\S]*?\n        \}/, 'typed network client');
const queryDns = extract(html, /async function officekitNetworkQueryDns\([\s\S]*?\n        \}/, 'DNS all-types query helper');

function client(fetch = async () => ({ ok: true, json: async () => ({}) })) {
  const reader = async response => {
    if (response.ok) return response.json();
    const payload = await response.json();
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `OfficeKit request failed (${response.status})`);
  };
  const context = { Object, Number, Array, Set, URL, Error, JSON, window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${dnsTypes}\n${selectableTypes}\n${dkimSelector}\n${explain}\n${statuses}\n${apiUrl}\n${exact}\n${finite}\n${validIp}\n${addressFamily}\n${validRequest}\nconst officekitReadApiResponse = ${reader.toString()};\n${validate}\n${request}\n${queryDns}\nglobalThis.validate = officekitValidateNetworkResponse; globalThis.call = officekitNetworkRequest; globalThis.queryDns = officekitNetworkQueryDns; globalThis.validRequest = officekitNetworkValidRequest; globalThis.explain = officekitDnsExplain;`, context);
  return context;
}

const dns = (status, records = []) => ({ hostname: 'example.com', record_type: 'A', status, records, truncated: false, nameserver: null, duration_ms: 18 });
const ping = (status, extras = {}) => ({ target: 'example.com', status, packets_sent: null, packets_received: null, packet_loss_percent: null, latency_ms: null, ...extras });
const interfaceResult = (include_addresses, addresses = []) => ({
  include_addresses, privacy_notice: include_addresses ? 'Contains local IP addresses. Copy or export only the addresses you select.' : 'Local IP addresses are hidden. Include addresses only when you want to view them.',
  interfaces: [{ name: 'en0', is_up: true, address_count: 1, addresses_hidden: !include_addresses, addresses }], truncated: false,
});

test('network mock contrasts API-only state and a responsive user-triggered workbench', () => {
  for (const phrase of ['API only', 'DNS lookup', 'All record types', 'Ping', 'Network interfaces', 'hidden by default', 'Each action runs only when selected']) assert.match(mock, new RegExp(phrase, 'i'));
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
  assert.match(mock, /@media\(max-width:620px\)/);
});

test('DNS, ping and interface tools are catalogued and route to exact controls', () => {
  const destinations = extract(html, /const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{[\s\S]*?\n        \}\);/, 'stable tool destinations');
  const expected = {
    network_dns: "network_dns: { tab: 'network', focusId: 'network-dns-hostname' }",
    network_ping: "network_ping: { tab: 'network', focusId: 'network-ping-target' }",
    network_interfaces: "network_interfaces: { tab: 'network', focusId: 'network-interfaces-run' }",
  };
  for (const [id, route] of Object.entries(expected)) {
    assert.ok(registry.includes(`"id": "${id}"`));
    assert.match(registry, new RegExp(`"${id}":[^\\n]+\\[(?:[^\\]]+)\\]`));
    assert.ok(destinations.includes(route));
  }
  for (const id of ['network-dns-form', 'network-ping-form', 'network-interfaces-run']) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /id="network-interfaces-show-addresses" type="checkbox"/);
  assert.match(html, /id="network-dns-run" type="submit"/);
  assert.match(html, /id="network-ping-run" type="submit"/);
  assert.match(html, /No check runs until you choose it/);
  assert.match(html, /officekitBindNetworkWorkbench\(\);/);
});

test('network client uses only declared POST routes and validates responses before returning', async () => {
  const calls = [];
  const result = dns('success', ['93.184.216.34']);
  const c = client(async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => result }; });
  const response = await c.call('dns', { hostname: 'example.com', record_type: 'A', timeout_seconds: 3 });
  assert.deepEqual(JSON.parse(JSON.stringify(response)), result);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/network/dns');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { hostname: 'example.com', record_type: 'A', timeout_seconds: 3 });
  await assert.rejects(c.call('other', {}), /supported network diagnostic/);

  const malformed = client(async () => ({ ok: true, json: async () => ({ ...result, leaked: 'secret' }) }));
  await assert.rejects(malformed.call('dns', { hostname: 'example.com', record_type: 'A', timeout_seconds: 3 }), /incomplete or inconsistent/);
  const strict = client(async () => { throw new Error('Invalid request should not reach fetch'); });
  await assert.rejects(strict.call('dns', { hostname: 'example.com', record_type: 'A', timeout_seconds: 3, extra: true }), /inputs are invalid/);
  await assert.rejects(strict.call('interfaces', { include_addresses: true, device_id: 'private' }), /inputs are invalid/);
  const failed = client(async () => ({ ok: false, status: 501, json: async () => ({ detail: 'Ping is not supported on this platform yet.' }) }));
  await assert.rejects(failed.call('ping', { target: 'example.com', count: 4, timeout_seconds: 3 }), /not supported on this platform/);
});

test('DNS validates status/record combinations, MX shape, resolver and bounds', () => {
  const c = client();
  const requestA = { hostname: 'example.com', record_type: 'A', timeout_seconds: 3 };
  for (const status of ['nxdomain', 'no_records', 'timed_out', 'resolver_error']) assert.equal(c.validate('dns', dns(status), requestA), true, status);
  assert.equal(c.validate('dns', dns('success', ['93.184.216.34']), requestA), true);
  assert.equal(c.validate('dns', dns('success', ['2001:db8::1']), requestA), false);
  assert.equal(c.validate('dns', { ...dns('success', ['2001:db8::1']), record_type: 'AAAA' }, { ...requestA, record_type: 'AAAA' }), true);
  assert.equal(c.validate('dns', dns('success'), requestA), false);
  assert.equal(c.validate('dns', dns('nxdomain', ['93.184.216.34']), requestA), false);
  assert.equal(c.validate('dns', { ...dns('success', ['93.184.216.34']), duration_ms: 10_001 }, requestA), false);
  const requestMx = { hostname: 'example.com', record_type: 'MX', timeout_seconds: 3 };
  const mx = { ...dns('success'), record_type: 'MX', records: [{ preference: 10, exchange: 'mail.example.com' }] };
  assert.equal(c.validate('dns', mx, requestMx), true);
  assert.equal(c.validate('dns', { ...mx, records: [{ preference: -1, exchange: 'mail.example.com' }] }, requestMx), false);
  const custom = { ...dns('success', ['93.184.216.34']), nameserver: '2001:4860:4860::8888' };
  assert.equal(c.validate('dns', custom, { ...requestA, nameserver: '2001:4860:4860:0:0:0:0:8888' }), true);
  assert.equal(c.validate('dns', custom, requestA), false);
});

test('DNS accepts CNAME and NS target names as plain strings', () => {
  const c = client();
  for (const type of ['CNAME', 'NS']) {
    const request = { hostname: 'example.com', record_type: type, timeout_seconds: 3 };
    assert.equal(c.validate('dns', { ...dns('success', ['ns1.example.com']), record_type: type }, request), true, type);
    assert.equal(c.validate('dns', { ...dns('success', [{ preference: 1, exchange: 'x' }]), record_type: type }, request), false, type);
  }
  assert.match(html, /<option value="CNAME">CNAME · alias<\/option><option value="NS">NS · name servers<\/option>/);
});

test('DKIM needs a valid selector and SPF does not take one', async () => {
  const c = client();
  const base = { hostname: 'example.com', timeout_seconds: 3 };
  assert.equal(c.validRequest('dns', { ...base, record_type: 'DKIM', selector: 'google' }), true);
  assert.equal(c.validRequest('dns', { ...base, record_type: 'DKIM' }), false);
  assert.equal(c.validRequest('dns', { ...base, record_type: 'DKIM', selector: 'a;b' }), false);
  assert.equal(c.validRequest('dns', { ...base, record_type: 'SPF' }), true);
  assert.equal(c.validRequest('dns', { ...base, record_type: 'SPF', selector: 'google' }), false);
  const calls = [];
  await c.queryDns({ hostname: 'example.com', recordType: 'DKIM', selector: ' Google ', timeoutSeconds: 3 }, async (kind, payload) => { calls.push(payload); return {}; });
  assert.equal(calls[0].selector, 'google');
  await assert.rejects(c.queryDns({ hostname: 'example.com', recordType: 'DKIM', selector: '', timeoutSeconds: 3 }), /selector/);
  assert.match(html, /<option value="SPF">SPF · who may send email<\/option><option value="DKIM">DKIM · email signing key<\/option>/);
  assert.match(html, /dnsType\.value !== 'DKIM'/);
});

test('SPF and DKIM results are explained in plain language', () => {
  const c = client();
  const spf = c.explain('SPF', { records: ['v=spf1 include:_spf.google.com ip4:203.0.113.0/24 mx ~all'] });
  assert.match(spf.intro, /allowed to send email/);
  const text = JSON.stringify(spf.points);
  assert.match(text, /_spf\.google\.com/);
  assert.match(text, /203\.0\.113\.0\/24/);
  assert.match(text, /mail servers/);
  assert.match(text, /soft fail/);
  assert.match(JSON.stringify(c.explain('SPF', { records: ['v=spf1 -all'] }).points), /rejected/);
  assert.match(JSON.stringify(c.explain('SPF', { records: ['v=spf1 +all'] }).points), /protects nothing/);
  assert.match(JSON.stringify(c.explain('SPF', { records: ['v=spf1 -all', 'v=spf1 ~all'] }).points), /More than one SPF record/);
  assert.match(JSON.stringify(c.explain('SPF', { records: [] }).points), /No SPF record/);
  const dkim = c.explain('DKIM', { records: ['v=DKIM1; k=rsa; t=y; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A'] });
  assert.match(dkim.intro, /public key/);
  assert.match(JSON.stringify(dkim.points), /public key is published/);
  assert.match(JSON.stringify(dkim.points), /testing DKIM/);
  assert.match(JSON.stringify(c.explain('DKIM', { records: ['v=DKIM1; p='] }).points), /revoked/);
  assert.match(JSON.stringify(c.explain('DKIM', { records: [] }).points), /No DKIM key/);
  assert.equal(c.explain('A', { records: ['192.0.2.1'] }), null);
});

test('TXT records are parsed one by one and MX priorities are explained', () => {
  const c = client();
  const txt = c.explain('TXT', { records: [
    'v=spf1 include:amazonses.com include:_spf.google.com -all',
    'google-site-verification=0kUg264UXHXO9oFLF05Aov6YUP5tQoyrELW3AqhuvYY',
    'y5L9Htdno0oRVajoTNEh2mbsSpBFOdjrYUGtDNn1G4k',
    'v=DMARC1; p=reject',
    'amazonses:abc123',
  ] });
  const text = JSON.stringify(txt.points);
  assert.match(txt.intro, /free text/);
  assert.match(text, /SPF record: lists the servers allowed to send email/);
  assert.match(text, /SPF · include:amazonses\.com/);
  assert.match(text, /SPF · include:_spf\.google\.com/);
  assert.match(text, /SPF · -all: everything else is rejected/);
  assert.match(text, /Google site verification: proves to Google/);
  assert.match(text, /DMARC policy/);
  assert.match(text, /Amazon SES verification/);
  assert.match(text, /free text\. No standard meaning was recognised/);
  assert.equal(c.explain('TXT', { records: [] }), null);
  const mx = c.explain('MX', { records: [{ preference: 10, exchange: 'alt4.aspmx.l.google.com' }, { preference: 10, exchange: 'alt3.aspmx.l.google.com' }, { preference: 20, exchange: 'mail.example.com' }] });
  assert.match(mx.intro, /lowest number first/);
  assert.match(mx.points[0], /tried first\. This is Google Workspace/);
  assert.match(mx.points[1], /same priority as the one above/);
  assert.match(mx.points[2], /backup/);
  assert.match(c.explain('NS', { records: ['ns1.example.com'] }).intro, /hold this domain's DNS records/);
  assert.match(c.explain('CNAME', { records: ['edge.example.com'] }).intro, /alias/);
});

test('the DNS server presets are Cloudflare, Google and OpenDNS and only fill the IP box', () => {
  for (const ip of ['1.1.1.1', '8.8.8.8', '208.67.222.222']) {
    assert.match(html, new RegExp(`<option value="${ip.replaceAll('.', '\\.')}">`));
  }
  assert.match(html, /id="network-dns-resolver-preset"/);
  assert.match(html, /dnsPreset\.value !== 'custom'\) dnsServer\.value = dnsPreset\.value/);
});

test('All DNS type option issues six validated requests and preserves partial failures', async () => {
  const c = client();
  const calls = [];
  const outcomes = await c.queryDns({ hostname: 'example.com', recordType: 'ALL', nameserver: '1.1.1.1', timeoutSeconds: 2 }, async (kind, payload) => {
    calls.push({ kind, payload });
    if (payload.record_type === 'AAAA') throw new Error('resolver timed out');
    return { record_type: payload.record_type, hostname: payload.hostname };
  });
  assert.deepEqual(calls.map(call => call.payload.record_type), ['A', 'AAAA', 'CNAME', 'NS', 'MX', 'TXT']);
  assert.ok(calls.every(call => call.kind === 'dns' && call.payload.nameserver === '1.1.1.1' && call.payload.timeout_seconds === 2));
  assert.deepEqual(JSON.parse(JSON.stringify(outcomes.map(outcome => outcome.status))), ['fulfilled', 'rejected', 'fulfilled', 'fulfilled', 'fulfilled', 'fulfilled']);
  await assert.rejects(c.queryDns({ hostname: 'example.com', recordType: 'ANY', timeoutSeconds: 2 }), /inputs are invalid/);
  assert.match(html, /<option value="ALL">All record types<\/option>/);
});

test('ping validates every terminal status and reconciles packet counts, loss and latency', () => {
  const c = client();
  const req = { target: 'example.com', count: 4, timeout_seconds: 3 };
  for (const status of ['incomplete', 'permission_denied', 'timed_out']) assert.equal(c.validate('ping', ping(status), req), true, status);
  const reachable = ping('reachable', { packets_sent: 4, packets_received: 4, packet_loss_percent: 0, latency_ms: { min: 1, avg: 2, max: 3 } });
  assert.equal(c.validate('ping', reachable, req), true);
  assert.equal(c.validate('ping', ping('reachable', { ...reachable, packets_received: 3 }), req), false);
  assert.equal(c.validate('ping', ping('partial_loss', { packets_sent: 4, packets_received: 2, packet_loss_percent: 50, latency_ms: { min: 2, avg: 1, max: 3 } }), req), false);
  assert.equal(c.validate('ping', ping('partial_loss', { packets_sent: 4, packets_received: 2, packet_loss_percent: 25, latency_ms: null }), req), false);
  assert.equal(c.validate('ping', ping('no_reply', { packets_sent: 4, packets_received: 0, packet_loss_percent: 100, latency_ms: null }), req), true);
  assert.equal(c.validate('ping', ping('timed_out', { packets_sent: 4, packets_received: 0, packet_loss_percent: 100 }), req), false);
});

test('interface response keeps addresses hidden unless opted in and rejects malformed data', () => {
  const c = client();
  assert.equal(c.validate('interfaces', interfaceResult(false), { include_addresses: false }), true);
  const address = { family: 'IPv4', address: '192.168.1.2', netmask: '255.255.255.0', broadcast: '192.168.1.255' };
  assert.equal(c.validate('interfaces', interfaceResult(true, [address]), { include_addresses: true }), true);
  assert.equal(c.validate('interfaces', interfaceResult(false, [address]), { include_addresses: false }), false);
  assert.equal(c.validate('interfaces', { ...interfaceResult(false), interfaces: [{ ...interfaceResult(false).interfaces[0], mac: '00:11:22:33:44:55' }] }, { include_addresses: false }), false);
  assert.equal(c.validate('interfaces', { ...interfaceResult(false), include_addresses: true }, { include_addresses: false }), false);
});

test('network result renderers create text nodes for untrusted host and resolver content', () => {
  const dnsRenderer = extract(html, /function officekitRenderNetworkDns\([\s\S]*?\n        \}/, 'DNS result renderer');
  const textRenderer = extract(html, /function officekitNetworkRenderText\([\s\S]*?\n        \}/, 'safe text renderer');
  const statusLabel = extract(html, /function officekitNetworkStatusLabel\([\s\S]*?\n        \}/, 'network status labels');
  const pingRenderer = extract(html, /function officekitRenderNetworkPing\([\s\S]*?\n        \}/, 'ping result renderer');
  const interfaceRenderer = extract(html, /function officekitRenderNetworkInterfaces\([\s\S]*?\n        \}/, 'interface result renderer');
  const elements = new Map();
  function node(tag = 'div') {
    return {
      tag, children: [], textContent: '', className: '', hidden: true,
      append(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
    };
  }
  const document = {
    getElementById(id) { if (!elements.has(id)) elements.set(id, node(id)); return elements.get(id); },
    createElement: tag => node(tag),
  };
  const context = { document };
  vm.runInNewContext(`${textRenderer}\n${statusLabel}\n${explain}\n${dnsRenderer}\n${pingRenderer}\n${interfaceRenderer}\nglobalThis.renderDns = officekitRenderNetworkDns; globalThis.renderPing = officekitRenderNetworkPing; globalThis.renderInterfaces = officekitRenderNetworkInterfaces;`, context);
  context.renderDns(dns('success', ['<img src=x onerror=alert(1)>']));
  const dnsResult = elements.get('network-dns-result');
  assert.equal(dnsResult.hidden, false);
  const findText = element => [element.textContent, ...(element.children || []).map(findText)].join(' ');
  assert.match(findText(dnsResult), /<img src=x onerror=alert\(1\)>/);
  context.renderPing(ping('permission_denied'));
  assert.match(elements.get('network-ping-result').children[0].textContent, /permission/i);
  context.renderInterfaces(interfaceResult(false));
  assert.match(elements.get('network-interfaces-result').children[0].textContent, /hidden/);
  assert.doesNotMatch(`${textRenderer}\n${statusLabel}\n${dnsRenderer}\n${pingRenderer}\n${interfaceRenderer}`, /innerHTML\s*=/);
});
