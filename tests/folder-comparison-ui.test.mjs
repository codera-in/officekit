import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const relativeNameHelper = html.match(/function officekitWorkspaceRelativeName\(name, label\) \{[\s\S]*?\n        \}/)?.[0];
const responseHelper = html.match(/async function officekitReadApiResponse\(response\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* FOLDER COMPARISON CLIENT START \*\/([\s\S]*?)\/\* FOLDER COMPARISON CLIENT END \*\//)?.[1];
const folderOptions = html.match(/function populateFolderComparisonOptions\(\) \{[\s\S]*?\n        \}/)?.[0];
const folderRenderer = html.match(/function renderFolderComparison\(report\) \{[\s\S]*?\n        \}/)?.[0];
const appendResultLine = html.match(/function appendWorkspaceResultLine\(container, text, className = 'text-sm text-slate-700'\) \{[\s\S]*?\n        \}/)?.[0];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(relativeNameHelper, 'workspace-relative path validator exists');
  assert.ok(responseHelper, 'shared API error parser exists');
  assert.ok(client, 'folder comparison client helpers exist');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, Blob, Uint8Array };
  vm.runInNewContext(`${apiUrlHelper}\n${relativeNameHelper}\n${responseHelper}\n${client}`, context);
  return context;
}

const report = {
  left_folder: 'before', right_folder: 'after', files_compared: 6, total_paths: 4,
  summary: { identical: 1, changed: 1, left_only: 1, right_only: 1 },
  directory_summary: { identical: 1, changed: 1, left_only: 1, right_only: 0 },
  directories: [
    { path: 'shared-empty', status: 'identical', left_empty: true, right_empty: true },
    { path: 'drafts', status: 'changed', left_empty: true, right_empty: false },
    { path: 'only-left', status: 'left-only', left_empty: true, right_empty: null },
  ],
  files: [
    { path: 'same.txt', status: 'identical', left_name: 'before/same.txt', right_name: 'after/same.txt', left_size_bytes: 4, right_size_bytes: 4, left_sha256: 'a'.repeat(64), right_sha256: 'a'.repeat(64) },
    { path: 'changed.csv', status: 'changed', left_name: 'before/changed.csv', right_name: 'after/changed.csv', left_size_bytes: 2, right_size_bytes: 3, left_sha256: 'b'.repeat(64), right_sha256: 'c'.repeat(64) },
    { path: 'only-left.txt', status: 'left-only', left_name: 'before/only-left.txt', right_name: null, left_size_bytes: 1, right_size_bytes: null, left_sha256: 'd'.repeat(64), right_sha256: null },
    { path: 'only-right.txt', status: 'right-only', left_name: null, right_name: 'after/only-right.txt', left_size_bytes: null, right_size_bytes: 1, left_sha256: null, right_sha256: 'e'.repeat(64) },
  ],
  complete: true,
};

test('folder comparison is searchable and routes into the shared safe workspace', () => {
  for (const id of ['workspace-folder-compare-tools', 'workspace-folder-left', 'workspace-folder-right', 'workspace-run-button', 'workspace-folder-csv-button']) {
    assert.ok(html.includes(`id="${id}"`), `${id} is present`);
  }
  assert.match(html, /folder_compare: \{ tab: 'workspace', fileTool: 'folder_compare' \}/);
  assert.match(html, /workspace.*local copies|temporary local/i);
  assert.ok(fs.existsSync(path.join(root, 'design/mocks/folder-comparison-workbench.html')));
  assert.match(html, /function renderFolderComparison/);
  assert.match(html, /\.textContent\s*=/);
  assert.doesNotMatch(folderRenderer || '', /innerHTML/);
});

test('folder choices derive from imported paths and default to non-overlapping trees', () => {
  const nodes = {
    'workspace-folder-left': { value: '', children: [], replaceChildren(...children) { this.children = children; }, add(option) { this.children.push(option); }, disabled: false },
    'workspace-folder-right': { value: '', children: [], replaceChildren(...children) { this.children = children; }, add(option) { this.children.push(option); }, disabled: false },
    'workspace-folder-compare-hint': { textContent: '' },
  };
  class TestOption { constructor(text, value) { this.text = text; this.value = value; } }
  const context = {
    document: { getElementById: id => nodes[id] },
    fileWorkspaceFiles: [
      { name: 'before/one.txt' }, { name: 'before/nested/two.txt' },
      { name: 'after/one.txt' }, { name: 'after/archive/three.txt' }, { name: 'loose.txt' },
    ],
    fileWorkspaceDirectories: ['before/empty-only'],
    Option: TestOption,
  };
  assert.ok(folderOptions);
  vm.runInNewContext(folderOptions, context);
  context.populateFolderComparisonOptions();
  assert.equal(nodes['workspace-folder-left'].value, 'after');
  assert.equal(nodes['workspace-folder-right'].value, 'before');
  assert.ok(nodes['workspace-folder-left'].children.some(option => option.value === 'before/nested'));
  assert.ok(nodes['workspace-folder-left'].children.some(option => option.value === 'before/empty-only'));
  assert.equal(nodes['workspace-folder-left'].disabled, false);
});

test('comparison renderer uses text nodes for hostile filenames and displays reconciled classifications', () => {
  const makeNode = () => ({
    children: [], attributes: {}, className: '', textContent: '',
    classList: { remove() {} },
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this.attributes[name] = value; },
  });
  const container = makeNode();
  const document = { getElementById: () => container, createElement: () => makeNode() };
  const context = { document };
  assert.ok(folderRenderer && appendResultLine);
  vm.runInNewContext(`${appendResultLine}\n${folderRenderer}`, context);
  const hostile = { ...report, files: [{ ...report.files[0], path: '<img src=x onerror=alert(1)>' }] };
  context.renderFolderComparison(hostile);
  assert.equal(container.children.at(-1).textContent.includes('6 temporary file copies'), true);
  assert.equal(container.children.some(node => node.textContent === 'Folder structure'), true);
  const descendants = node => [node, ...(node.children || []).flatMap(descendants)];
  assert.equal(descendants(container).some(node => node.textContent === 'Empty state differs'), true);
  assert.equal(container.children[1].children[0].children[1].children[0].children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(container.innerHTML, undefined);
});

test('comparison client sends only relative folder names and validates all report classifications', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => report };
  });
  const workspaceId = 'a'.repeat(32);

  const result = await context.officekitCompareFolders(workspaceId, 'before', 'after');

  assert.equal(result.total_paths, 4);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `http://127.0.0.1:8000/api/workspaces/${workspaceId}/folder-comparisons`);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { left_folder: 'before', right_folder: 'after' });
  assert.equal(Object.hasOwn(JSON.parse(calls[0].options.body), 'tenant_id'), false);
});

test('comparison client rejects invalid scopes, overlapping folders and malformed or inconsistent reports', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return { ok: true, json: async () => report }; });
  const id = 'a'.repeat(32);
  await assert.rejects(context.officekitCompareFolders('../workspace', 'before', 'after'), /workspace/i);
  await assert.rejects(context.officekitCompareFolders(id, 'before', 'before'), /distinct|overlap/i);
  await assert.rejects(context.officekitCompareFolders(id, 'before', 'before/child'), /distinct|overlap/i);
  await assert.rejects(context.officekitCompareFolders(id, '../before', 'after'), /relative|folder/i);
  assert.equal(calls, 0);

  const mismatch = { ...report, summary: { ...report.summary, identical: 0 } };
  const bad = loadClient(async () => ({ ok: true, json: async () => mismatch }));
  await assert.rejects(bad.officekitCompareFolders(id, 'before', 'after'), /folder comparison/i);
  const unknown = { ...report, diagnostic_path: '/tmp/private' };
  const badExtra = loadClient(async () => ({ ok: true, json: async () => unknown }));
  await assert.rejects(badExtra.officekitCompareFolders(id, 'before', 'after'), /folder comparison/i);
  const unsafe = { ...report, files: report.files.map((item, index) => index ? item : { ...item, path: '/private/secret' }) };
  const badPath = loadClient(async () => ({ ok: true, json: async () => unsafe }));
  await assert.rejects(badPath.officekitCompareFolders(id, 'before', 'after'), /folder comparison/i);
  const extraField = { ...report, files: report.files.map((item, index) => index ? item : { ...item, server_path: '/tmp/private' }) };
  const badFile = loadClient(async () => ({ ok: true, json: async () => extraField }));
  await assert.rejects(badFile.officekitCompareFolders(id, 'before', 'after'), /folder comparison/i);
});

test('CSV export uses the declared CSV route and rejects wrong attachments or size violations', async () => {
  const bytes = new Blob(['path,status\nfile.txt,identical\n'], { type: 'text/csv' });
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, headers: { get: name => name === 'content-type' ? 'text/csv; charset=utf-8' : 'attachment; filename="folder-comparison.csv"' }, blob: async () => bytes };
  });
  const output = await context.officekitDownloadFolderComparisonCsv('a'.repeat(32), 'before', 'after');
  assert.equal(output, bytes);
  assert.match(calls[0].url, /folder-comparisons\?format=csv$/);
  assert.equal(calls[0].options.method, 'POST');

  const wrongType = loadClient(async () => ({ ok: true, headers: { get: () => 'application/json' }, blob: async () => bytes }));
  await assert.rejects(wrongType.officekitDownloadFolderComparisonCsv('a'.repeat(32), 'before', 'after'), /CSV attachment/i);
  const wrongName = loadClient(async () => ({ ok: true, headers: { get: name => name === 'content-type' ? 'text/csv' : 'attachment; filename="folder-comparison.csv.exe"' }, blob: async () => bytes }));
  await assert.rejects(wrongName.officekitDownloadFolderComparisonCsv('a'.repeat(32), 'before', 'after'), /CSV attachment/i);
  const oversized = loadClient(async () => ({ ok: true, headers: { get: name => name === 'content-type' ? 'text/csv' : 'attachment; filename="folder-comparison.csv"' }, blob: async () => new Blob([new Uint8Array(4 * 1024 * 1024 + 1)]) }));
  await assert.rejects(oversized.officekitDownloadFolderComparisonCsv('a'.repeat(32), 'before', 'after'), /4 MiB/i);
});
