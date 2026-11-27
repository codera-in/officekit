import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/workspace-file-inspector.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* WORKSPACE INSPECTOR CLIENT START \*\/([\s\S]*?)\/\* WORKSPACE INSPECTOR CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(apiUrlHelper);
  assert.ok(client);
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

test('file inspector mock presents the selected-copy workflow and clear action', () => {
  for (const text of ['Inspect selected files', 'Detect actual file types', 'Calculate checksums', 'Compare checksum', 'SHA-256', 'SHA-512', 'originals stay unchanged', 'Clear temporary workspace']) assert.ok(mock.includes(text), text);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('file hash and type detection are discoverable and use the shared workspace', () => {
  for (const id of ['file_hash', 'file_type']) assert.match(registry, new RegExp(`"id": "${id}"`));
  assert.match(html, /file_hash: \{ tab: 'workspace', fileTool: 'file_hash' \}/);
  assert.match(html, /file_type: \{ tab: 'workspace', fileTool: 'file_type' \}/);
  assert.match(html, /file_hash: \{ tab: 'workspace', fileTool: 'file_hash' \}/);
  assert.match(html, /file_type: \{ tab: 'workspace', fileTool: 'file_type' \}/);
  assert.match(html, /id="workspace-expected-checksum"/);
  assert.match(html, /officekitCompareWorkspaceChecksums/);
});

test('hash client validates ordered records, digest algorithm, names and byte totals', async () => {
  const calls = [];
  const files = [{ name:'a.txt', size_bytes:3, digest:'a'.repeat(64) }, { name:'dir/b.bin', size_bytes:5, digest:'b'.repeat(64) }];
  const context = loadClient(async (url, options) => { calls.push({ url, body:JSON.parse(options.body) }); return { ok:true, json:async () => ({ algorithm:'sha256', total_files:2, total_bytes:8, complete:true, files }) }; });
  const result = await context.officekitWorkspaceHashReport('1234567890abcdef1234567890abcdef', ['a.txt','dir/b.bin'], 'sha256');
  assert.equal(result.total_bytes, 8);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/workspaces/1234567890abcdef1234567890abcdef/hash-reports');
  assert.deepEqual(calls[0].body, { filenames:['a.txt','dir/b.bin'], algorithm:'sha256' });
  const wrongDigest = loadClient(async () => ({ ok:true, json:async () => ({ algorithm:'sha512', total_files:1, total_bytes:3, complete:true, files:[{ name:'a.txt', size_bytes:3, digest:'a'.repeat(64) }] }) }));
  await assert.rejects(wrongDigest.officekitWorkspaceHashReport('1234567890abcdef1234567890abcdef', ['a.txt'], 'sha512'), /inconsistent hash/);
});

test('checksum comparison accepts a matching digest and reports mismatches for every file', () => {
  const context = loadClient(async () => { throw new Error('comparison must not make a network request'); });
  const files = [
    { name:'a.txt', size_bytes:3, digest:'a'.repeat(64) },
    { name:'b.bin', size_bytes:5, digest:'b'.repeat(64) },
  ];
  assert.deepEqual(JSON.parse(JSON.stringify(context.officekitCompareWorkspaceChecksums(files, `  SHA-256: ${'A'.repeat(64)}  `, 'sha256'))), [
    { name:'a.txt', matches:true },
    { name:'b.bin', matches:false },
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(context.officekitCompareWorkspaceChecksums(
    [{ name:'archive.zip', size_bytes:1, digest:'c'.repeat(128) }], `SHA-512: ${'c'.repeat(128)}`, 'sha512',
  ))), [{ name:'archive.zip', matches:true }]);
  assert.equal(context.officekitCompareWorkspaceChecksums(files, '   ', 'sha256'), null);
});

test('checksum comparison rejects wrong algorithm, malformed digest and invalid report records', () => {
  const context = loadClient(async () => { throw new Error('comparison must not make a network request'); });
  const files = [{ name:'a.txt', size_bytes:3, digest:'a'.repeat(64) }];
  assert.throws(() => context.officekitCompareWorkspaceChecksums(files, 'a'.repeat(63), 'sha256'), /valid SHA-256 checksum/);
  assert.throws(() => context.officekitCompareWorkspaceChecksums(files, `SHA-512: ${'a'.repeat(64)}`, 'sha256'), /valid SHA-256 checksum/);
  assert.throws(() => context.officekitCompareWorkspaceChecksums(files, 'a'.repeat(64), 'md5'), /Choose SHA-256 or SHA-512/);
  assert.throws(() => context.officekitCompareWorkspaceChecksums([{ ...files[0], digest:'not-a-digest' }], 'a'.repeat(64), 'sha256'), /inconsistent hash report/);
});

test('file type client validates exact bounded detection records', async () => {
  const record = { name:'report.pdf', size_bytes:7, extension:'.pdf', detected_type:'PDF document', mime_type:'application/pdf', extension_matches:true, method:'magic-bytes+utf8' };
  const context = loadClient(async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/workspaces/1234567890abcdef1234567890abcdef/file-type-reports');
    assert.deepEqual(JSON.parse(options.body), { filenames:['report.pdf'] });
    return { ok:true, json:async () => ({ total_files:1, complete:true, files:[record] }) };
  });
  const result = await context.officekitWorkspaceFileTypeReport('1234567890abcdef1234567890abcdef', ['report.pdf']);
  assert.equal(result.files[0].detected_type, 'PDF document');
  const malformed = loadClient(async () => ({ ok:true, json:async () => ({ total_files:2, complete:true, files:[record] }) }));
  await assert.rejects(malformed.officekitWorkspaceFileTypeReport('1234567890abcdef1234567890abcdef', ['report.pdf']), /inconsistent file-type/);
});

test('workspace inspector rejects unsafe names, unsupported algorithms and malformed HTTP responses', async () => {
  let requests = 0;
  const context = loadClient(async () => { requests += 1; return { ok:true, json:async () => ({}) }; });
  await assert.rejects(context.officekitWorkspaceHashReport('1234567890abcdef1234567890abcdef', ['../escape'], 'sha256'), /valid workspace file/);
  await assert.rejects(context.officekitWorkspaceHashReport('1234567890abcdef1234567890abcdef', ['ok.txt'], 'md5'), /SHA-256 or SHA-512/);
  await assert.rejects(context.officekitWorkspaceFileTypeReport('1234567890abcdef1234567890abcdef', Array.from({length:1001}, (_, i) => `${i}.txt`)), /between 1 and 1,000/);
  assert.equal(requests, 0);
});
