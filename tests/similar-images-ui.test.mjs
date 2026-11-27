import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const clientSource = html.match(/async function officekitSimilarImageReport\([\s\S]*?\n        \}\n/)?.[0];

function loadClient(fetchImpl, readResponse = async (response) => {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}) {
  assert.ok(clientSource, 'similar-image client exists');
  const context = { fetch: fetchImpl, officekitReadApiResponse: readResponse, officekitApiUrl: (url) => url };
  vm.runInNewContext(`${clientSource}\nglobalThis.call = officekitSimilarImageReport;`, context);
  return context.call;
}

test('similar-image search opens the selected-copy workspace tool', () => {
  assert.match(registry, /"id": "similar_images"/);
  assert.match(registry, /"similar_images": \[[^\]]*burst/);
  assert.match(html, /similar_images: \{ tab: 'workspace', fileTool: 'similar_images' \}/);
  assert.match(html, /similar_images: \{ title: 'Find similar images'/);
  assert.match(html, /id="workspace-similar-images-tools"/);
  assert.match(html, /id="workspace-similar-threshold"/);
});

test('client sends bounded workspace-relative names and the threshold then validates the full report', async () => {
  let request;
  const client = loadClient(async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({
      pairs: [{ left: 'burst/a.jpg', right: 'burst/b.jpg', distance: 3 }],
      groups: [{ files: ['burst/a.jpg', 'burst/b.jpg'] }], scanned_images: 2,
      skipped_files: [], errors: [], complete: true, method: 'dct-perceptual-hash', frames_per_file: 1,
    }) };
  });
  const report = await client('a'.repeat(32), ['burst/a.jpg', 'burst/b.jpg'], 8);
  assert.equal(request.url, `/api/workspaces/${'a'.repeat(32)}/similar-image-reports`);
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), { filenames: ['burst/a.jpg', 'burst/b.jpg'], threshold: 8 });
  assert.equal(report.scanned_images, 2);
});

test('client rejects invalid workspace, path list, threshold and inconsistent DTOs', async () => {
  const invalidClient = loadClient(async () => ({ ok: true, json: async () => ({}) }));
  await assert.rejects(invalidClient('../workspace', ['a.jpg'], 8), /workspace/);
  await assert.rejects(invalidClient('a'.repeat(32), [], 8), /image files/);
  await assert.rejects(invalidClient('a'.repeat(32), ['../outside.jpg'], 8), /relative/);
  await assert.rejects(invalidClient('a'.repeat(32), ['a.jpg', 'a.jpg'], 8), /unique/);
  await assert.rejects(invalidClient('a'.repeat(32), ['a.jpg'], 65), /threshold/);
  await assert.rejects(invalidClient('a'.repeat(32), ['a.jpg'], 8), /valid similar-image report/);
});

test('similar-image result rendering uses text nodes and explains incomplete/unsupported scans', () => {
  assert.match(html, /function renderSimilarImageReport\(/);
  const renderer = html.match(/function renderSimilarImageReport\([\s\S]*?\n        \}/)?.[0];
  assert.ok(renderer);
  assert.match(html.match(/function appendWorkspaceResultLine\([\s\S]*?\n        \}/)?.[0] || '', /textContent/);
  assert.match(renderer, /skipped_files/);
  assert.match(renderer, /errors/);
  assert.match(renderer, /complete/);
  assert.doesNotMatch(renderer, /innerHTML/);
  assert.match(renderer, /No files were changed or deleted/);
});

test('similar-image report renders hostile workspace names as text', () => {
  const renderer = html.match(/function renderSimilarImageReport\([\s\S]*?\n        \}/)?.[0];
  const helper = html.match(/function appendWorkspaceResultLine\([\s\S]*?\n        \}/)?.[0];
  assert.ok(renderer && helper);
  const lines = [];
  const container = { replaceChildren() { lines.length = 0; }, appendChild(node) { lines.push(node.textContent); }, classList: { remove() {} } };
  const context = { document: { getElementById: () => container, createElement: () => ({ textContent: '', className: '' }) } };
  const report = { scanned_images: 2, groups: [{ files: ['<img src=x onerror=alert(1)>', 'photo.jpg'] }], complete: true, pairs: [{ left: '<img src=x onerror=alert(1)>', right: 'photo.jpg', distance: 2 }], skipped_files: [], errors: [] };
  vm.runInNewContext(`${helper}\n${renderer}\nrenderSimilarImageReport(report);`, { ...context, report });
  assert.ok(lines.includes('<img src=x onerror=alert(1)>'));
  assert.equal(lines.some(line => line.includes('<img')), true);
});
