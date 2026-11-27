import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\/ WORKSPACE API CLIENT START([\s\S]*?)\/\/ WORKSPACE API CLIENT END/)?.[1];
const captureSelection = html.match(/function officekitCaptureFileSelection\(input\) \{[\s\S]*?\n        \}/)?.[0];
const captureDirectories = html.match(/async function officekitCaptureDirectorySelection\(input\) \{[\s\S]*?\n        \}/)?.[0];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(client, 'workspace request helpers exist');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, FormData };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

function jsonResponse(data, ok = true) {
  return { ok, json: async () => data };
}

test('ZIP selection has an accessible extraction, status, download and clear flow', () => {
  assert.match(html, /id="generic-file-select-button"[^>]*>Choose file…<\/button>/);
  for (const id of [
    'zip-extraction-panel', 'zip-select-button', 'zip-output-name', 'zip-extract-button',
    'zip-workspace-status', 'zip-download-button', 'zip-clear-button', 'zip-result-files',
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /role="status"[^>]*id="zip-workspace-status"|id="zip-workspace-status"[^>]*role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /original archive stays untouched/i);
});

test('inline application scripts remain syntactically valid JavaScript', () => {
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length > 0);
  for (const [, source] of scripts) new vm.Script(source);
});

test('archive import uploads only the user-selected ZIP and returns its scoped workspace ID', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ workspace_id: 'a'.repeat(32), files: [{ name: 'project.zip', size_bytes: 8 }], directories: [] });
  });
  const zip = new Blob(['zip data'], { type: 'application/zip' });
  Object.defineProperty(zip, 'name', { value: 'project.zip' });

  const workspace = await context.officekitImportArchive(zip);

  assert.equal(workspace.workspaceId, 'a'.repeat(32));
  assert.equal(workspace.archiveName, 'project.zip');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/workspaces');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('files').name, 'project.zip');
});

test('filesystem import copies selected files and preserves folder-relative names', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({
      workspace_id: 'd'.repeat(32),
      files: [
        { name: 'reports/january.csv', size_bytes: 3 },
        { name: 'notes.txt', size_bytes: 4 },
      ],
      directories: ['reports'],
    });
  });
  const fileA = new Blob(['jan']);
  const fileB = new Blob(['note']);
  Object.defineProperty(fileA, 'name', { value: 'january.csv' });
  Object.defineProperty(fileA, 'webkitRelativePath', { value: 'reports/january.csv' });
  Object.defineProperty(fileB, 'name', { value: 'notes.txt' });

  const workspace = await context.officekitImportFiles([fileA, fileB]);

  assert.equal(workspace.workspaceId, 'd'.repeat(32));
  assert.equal(workspace.files.length, 2);
  assert.deepEqual(workspace.directories, ['reports']);
  assert.equal(calls[0].options.body.getAll('files').length, 2);
  assert.equal(calls[0].options.body.getAll('files')[0].name, 'reports/january.csv');
  assert.equal(calls[0].options.body.getAll('files')[1].name, 'notes.txt');
});

test('filesystem selection capture keeps the native file input intact until upload finishes', () => {
  assert.ok(captureSelection, 'filesystem selection is captured by a reusable helper');
  const context = {};
  vm.runInNewContext(captureSelection, context);
  const selected = [{ name: 'same-file.txt', size: 4 }];
  const input = { files: selected, value: 'C:\\fakepath\\same-file.txt' };

  const captured = context.officekitCaptureFileSelection(input);

  assert.equal(captured.length, 1);
  assert.equal(captured[0].name, selected[0].name);
  assert.equal(captured[0].size, selected[0].size);
  assert.equal(input.value, 'C:\\fakepath\\same-file.txt');
  const repeated = context.officekitCaptureFileSelection(input);
  assert.equal(repeated.length, 1);
  assert.equal(repeated[0].name, selected[0].name);
  assert.equal(input.value, 'C:\\fakepath\\same-file.txt');
});

test('directory selection capture includes empty nested folders from WebKit entries', async () => {
  assert.ok(captureDirectories, 'folder entry capture is reusable');
  const entry = (fullPath, children = []) => ({
    fullPath,
    isDirectory: true,
    createReader() {
      let sent = false;
      return { readEntries(resolve) { resolve(sent ? [] : (sent = true, children)); } };
    },
  });
  const context = {};
  vm.runInNewContext(captureDirectories, context);
  const input = { files: [], webkitEntries: [entry('/picked', [entry('/picked/before', [entry('/picked/before/empty')]), entry('/picked/after')])] };

  const folders = await context.officekitCaptureDirectorySelection(input);

  assert.deepEqual(Array.from(folders), ['picked', 'picked/after', 'picked/before', 'picked/before/empty']);
});

test('directory-only import uploads empty folder paths and returns the workspace inventory', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ workspace_id: 'e'.repeat(32), files: [], directories: ['before', 'before/empty', 'after'] });
  });

  const workspace = await context.officekitImportFiles([], context.fetch, ['before', 'before/empty', 'after']);

  assert.equal(workspace.files.length, 0);
  assert.deepEqual(workspace.directories, ['before', 'before/empty', 'after']);
  assert.deepEqual(calls[0].options.body.getAll('directories'), ['before', 'before/empty', 'after']);
});

test('filesystem import rejects unsafe names, oversized selections and empty files before networking', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return jsonResponse({}); });
  const unsafe = new Blob(['x']);
  Object.defineProperty(unsafe, 'name', { value: 'bad.txt' });
  Object.defineProperty(unsafe, 'webkitRelativePath', { value: '../bad.txt' });
  const oversized = { name: 'large.bin', size: 536_870_913 };

  await assert.rejects(context.officekitImportFiles([]), /Select at least one file or folder/);
  await assert.rejects(context.officekitImportFiles([unsafe]), /relative path/);
  await assert.rejects(context.officekitImportFiles([oversized]), /512 MiB/);
  assert.equal(calls, 0);
});

test('archive extraction sends typed names, downloads the scoped artifact and clears the workspace', async () => {
  const calls = [];
  const archiveBlob = new Blob(['bundle']);
  const context = loadClient(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/extractions')) return jsonResponse({
      artifact_id: 'b'.repeat(32), output_name: 'extracted', file_count: 1, total_bytes: 7,
      files: ['docs/readme.txt'], download_name: 'extracted.zip',
    });
    if (url.endsWith('/artifacts/' + 'b'.repeat(32))) return { ok: true, blob: async () => archiveBlob };
    if (options.method === 'DELETE') return { ok: true, status: 204 };
    throw new Error(`Unexpected request ${url}`);
  });
  const workspaceId = 'a'.repeat(32);

  const result = await context.officekitExtractArchive(workspaceId, 'project.zip', 'extracted');
  const downloaded = await context.officekitDownloadArtifact(workspaceId, result.artifact_id);
  await context.officekitClearWorkspace(workspaceId);

  assert.equal(result.artifact_id, 'b'.repeat(32));
  assert.equal(downloaded, archiveBlob);
  assert.equal(calls.length, 3);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { archive_name: 'project.zip', output_name: 'extracted' });
  assert.equal(calls[1].options.method || 'GET', 'GET');
  assert.equal(calls[2].options.method, 'DELETE');
});

test('batch rename previews and creates artifacts only inside the selected workspace', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/rename-previews')) {
      return jsonResponse({ files: [{ source: 'report.txt', target: 'invoice_01.txt', size_bytes: 6 }] });
    }
    if (url.endsWith('/renamed-artifacts')) {
      return jsonResponse({
        artifact_id: 'c'.repeat(32), file_count: 1, total_bytes: 6,
        files: ['invoice_01.txt'], download_name: 'renamed-files.zip',
      });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  const request = {
    filenames: ['report.txt'], pattern_type: 'sequence', prefix: 'invoice_',
    start_num: 1, digits: 2,
  };

  const preview = await context.officekitPreviewRename('a'.repeat(32), request);
  const artifact = await context.officekitCreateRenameArtifact('a'.repeat(32), request);

  assert.equal(preview.files[0].target, 'invoice_01.txt');
  assert.equal(artifact.artifact_id, 'c'.repeat(32));
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, `http://127.0.0.1:8000/api/workspaces/${'a'.repeat(32)}/rename-previews`);
  assert.equal(calls[1].url, `http://127.0.0.1:8000/api/workspaces/${'a'.repeat(32)}/renamed-artifacts`);
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[1].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), request);
  assert.deepEqual(JSON.parse(calls[1].options.body), request);
});

test('batch rename client rejects empty selections and malformed server responses', async () => {
  let calls = 0;
  const context = loadClient(async () => {
    calls += 1;
    return jsonResponse({ files: [{ source: 'x', target: 'y', size_bytes: -1 }] });
  });

  await assert.rejects(context.officekitPreviewRename('a'.repeat(32), { filenames: [] }), /Select at least one file/);
  await assert.rejects(context.officekitPreviewRename('a'.repeat(32), { filenames: ['x'] }), /valid rename preview/);
  assert.equal(calls, 1);
});

test('duplicate and storage reports request only the active workspace and bounded options', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/duplicate-reports')) {
      return jsonResponse({ groups: [], files_scanned: 2, skipped_symlinks: 0, complete: true, errors: [] });
    }
    if (url.endsWith('/storage-reports')) {
      return jsonResponse({
        total_files: 2, total_size_bytes: 9, total_size_mb: 0,
        largest_files: [{ name: 'docs/a.txt', size_bytes: 5, size_mb: 0 }],
        largest_folders: [{ name: 'docs', file_count: 1, size_bytes: 5 }],
        complete: true, skipped_symlinks: 0, errors: [],
      });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  const workspaceId = 'a'.repeat(32);

  const duplicates = await context.officekitDuplicateReport(workspaceId, 250);
  const storage = await context.officekitStorageReport(workspaceId, 10);

  assert.equal(duplicates.complete, true);
  assert.equal(storage.largest_files[0].name, 'docs/a.txt');
  assert.equal(JSON.parse(calls[0].options.body).max_entries, 250);
  assert.deepEqual(JSON.parse(calls[1].options.body), { top_n: 10 });
  assert.ok(calls.every(call => !Object.hasOwn(JSON.parse(call.options.body), 'path')));
});

test('duplicate and storage report clients reject unbounded requests and malformed results', async () => {
  let calls = 0;
  const context = loadClient(async () => {
    calls += 1;
    return jsonResponse({ groups: [], files_scanned: -1, skipped_symlinks: 0, complete: true, errors: [] });
  });

  await assert.rejects(context.officekitDuplicateReport('a'.repeat(32), 10_001), /entry limit/);
  await assert.rejects(context.officekitDuplicateReport('a'.repeat(32), 10), /valid duplicate report/);
  await assert.rejects(context.officekitStorageReport('a'.repeat(32), 1001), /result limit/);
  assert.equal(calls, 1);
});

test('duplicate report client rejects host paths, unsafe group names and incomplete complete-scans', async () => {
  const safeError = { name: 'folder/unreadable.txt', message: 'A file could not be read during the duplicate scan.' };
  const invalidReports = [
    { groups: [], files_scanned: 1, skipped_symlinks: 0, complete: false, errors: [{ ...safeError, name: '/Users/private/secret.txt' }] },
    { groups: [], files_scanned: 1, skipped_symlinks: 0, complete: false, errors: [{ ...safeError, name: '../secret.txt' }] },
    { groups: [], files_scanned: 1, skipped_symlinks: 0, complete: false, errors: [{ ...safeError, message: 'Permission denied: /private/secret.txt' }] },
    { groups: [], files_scanned: 1, skipped_symlinks: 0, complete: true, errors: [safeError] },
    { groups: [{ hash: 'a'.repeat(64), size_bytes: 10, files: ['folder/a.txt', '../secret.txt'] }], files_scanned: 2, skipped_symlinks: 0, complete: true, errors: [] },
  ];

  for (const report of invalidReports) {
    const context = loadClient(async () => jsonResponse(report));
    await assert.rejects(context.officekitDuplicateReport('a'.repeat(32)), /valid duplicate report/);
  }
});

test('storage report validates bounded folder totals and reconciled size summaries', async () => {
  const valid = {
    total_files: 3, total_size_bytes: 900, total_size_mb: 0,
    largest_files: [{ name:'nested/a.txt', size_bytes:400, size_mb:0 }],
    largest_folders: [{ name:'nested', file_count:2, size_bytes:700 }],
    complete:true, skipped_symlinks:0, errors:[],
  };
  const good = loadClient(async () => jsonResponse(valid));
  const report = await good.officekitStorageReport('a'.repeat(32), 10);
  assert.equal(report.largest_folders[0].name, 'nested');

  const invalids = [
    { ...valid, largest_folders: undefined },
    { ...valid, total_size_mb: 1 },
    { ...valid, largest_folders: [{ name:'../outside', file_count:2, size_bytes:700 }] },
    { ...valid, largest_folders: [{ name:'nested', file_count:4, size_bytes:700 }] },
    { ...valid, largest_folders: [{ name:'nested', file_count:2, size_bytes:901 }] },
    { ...valid, largest_files: [{ name:'nested/a.txt', size_bytes:400, size_mb:3 }] },
    { ...valid, complete:true, errors:[{ name:null, message:'A file could not be read during the storage scan.' }] },
  ];
  for (const malformed of invalids) {
    const client = loadClient(async () => jsonResponse(malformed));
    await assert.rejects(client.officekitStorageReport('a'.repeat(32), 10), /valid storage report/);
  }
});

test('storage result renders largest files and nested folder totals as safe text', () => {
  const renderer = html.match(/\/\* STORAGE REPORT RENDERER START \*\/([\s\S]*?)\/\* STORAGE REPORT RENDERER END \*\//)?.[1];
  assert.ok(renderer, 'storage report has a testable renderer');
  const children = [];
  const container = { children, classList:{ remove(){} }, replaceChildren(){ children.length=0; }, appendChild(node){ children.push(node); } };
  const context = { document:{ createElement: tag => ({ tag, textContent:'', className:'' }), getElementById: id => id === 'workspace-results' ? container : null } };
  vm.runInNewContext(`${renderer}\n${html.match(/function appendWorkspaceResultLine\(container, text, className = 'text-sm text-slate-700'\) \{[\s\S]*?\n        \}/)?.[0]}\nrenderWorkspaceStorageReport({total_files:3,total_size_bytes:900,total_size_mb:0,largest_files:[{name:'a<b.txt',size_bytes:400,size_mb:0}],largest_folders:[{name:'nested',file_count:2,size_bytes:700}],complete:true,skipped_symlinks:0,errors:[]});`, context);
  const text = children.map(child => child.textContent).join('\n');
  assert.match(text, /a<b\.txt/);
  assert.match(text, /Largest folders/);
  assert.match(text, /nested · 2 files · 0\.00 MiB/);
  assert.match(text, /include nested contents and can overlap/);
  assert.doesNotMatch(text, /<b[^>]*>/);
});

test('file split and join clients send scoped requests and validate full artifact metadata', async () => {
  const calls = [];
  const workspaceId = 'a'.repeat(32);
  const digest = 'b'.repeat(64);
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/splits')) return jsonResponse({
      artifact_id: 'c'.repeat(32), original_name: 'docs/archive.bin', total_bytes: 7,
      chunk_size_bytes: 4, chunk_count: 2, sha256: digest,
      parts: [
        { index: 1, name: 'part-00001.bin', size_bytes: 4, sha256: digest },
        { index: 2, name: 'part-00002.bin', size_bytes: 3, sha256: digest },
      ], download_name: 'archive.bin.split.zip',
    });
    if (url.endsWith('/joins')) return jsonResponse({
      artifact_id: 'd'.repeat(32), output_name: 'restored.bin', total_bytes: 7,
      part_count: 2, sha256: digest, download_name: 'restored.bin.zip',
    });
    throw new Error(`Unexpected request ${url}`);
  });

  const split = await context.officekitCreateWorkspaceSplit(workspaceId, 'docs/archive.bin', 7, 4);
  const joined = await context.officekitCreateWorkspaceJoin(workspaceId, 'parts.zip', 'restored.bin');

  assert.equal(split.chunk_count, 2);
  assert.equal(joined.part_count, 2);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, `http://127.0.0.1:8000/api/workspaces/${workspaceId}/splits`);
  assert.deepEqual(JSON.parse(calls[0].options.body), { filename: 'docs/archive.bin', chunk_size_bytes: 4 });
  assert.equal(calls[1].url, `http://127.0.0.1:8000/api/workspaces/${workspaceId}/joins`);
  assert.deepEqual(JSON.parse(calls[1].options.body), { archive_name: 'parts.zip', output_name: 'restored.bin' });
});

test('file split and join clients reject unsafe requests and inconsistent success payloads', async () => {
  let calls = 0;
  const workspaceId = 'a'.repeat(32);
  const splitPayload = {
    artifact_id: 'c'.repeat(32), original_name: 'source.bin', total_bytes: 4,
    chunk_size_bytes: 4, chunk_count: 1, sha256: 'b'.repeat(64),
    parts: [{ index: 1, name: 'part-00001.bin', size_bytes: 4, sha256: 'b'.repeat(64) }],
    download_name: 'source.bin.split.zip',
  };
  const joinPayload = {
    artifact_id: 'd'.repeat(32), output_name: 'restored.bin', total_bytes: 4,
    part_count: 1, sha256: 'invalid-digest', download_name: 'restored.bin.zip',
  };
  const context = loadClient(async () => { calls += 1; return jsonResponse(calls === 1 ? splitPayload : joinPayload); });

  await assert.rejects(context.officekitCreateWorkspaceSplit('../workspace', 'source.bin', 4, 1), /workspace is no longer available/);
  await assert.rejects(context.officekitCreateWorkspaceSplit(workspaceId, '../source.bin', 4, 1), /relative workspace path/);
  await assert.rejects(context.officekitCreateWorkspaceSplit(workspaceId, 'source.bin', 4, 0), /part size/);
  await assert.rejects(context.officekitCreateWorkspaceJoin(workspaceId, 'parts.zip', '../restored.bin'), /single filename/);
  assert.equal(calls, 0);

  await assert.rejects(context.officekitCreateWorkspaceSplit(workspaceId, 'source.bin', 5, 4), /valid split result/);
  await assert.rejects(context.officekitCreateWorkspaceJoin(workspaceId, 'parts.zip', 'restored.bin'), /valid join result/);
  assert.equal(calls, 2);

  const missingParts = loadClient(async () => jsonResponse({ ...splitPayload, parts: undefined }));
  await assert.rejects(
    missingParts.officekitCreateWorkspaceSplit(workspaceId, 'source.bin', 4, 4),
    /valid split result/,
  );
});

test('approved split/join workbench exposes accessible operations, bounded settings and output actions', () => {
  for (const id of [
    'workspace-split-join-tabs', 'workspace-split-tab', 'workspace-join-tab',
    'workspace-split-panel', 'workspace-join-panel', 'workspace-part-size-mib',
    'workspace-join-output-name',
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /data-file-tool="split_join"/);
  assert.match(html, /aria-controls="workspace-split-panel"/);
  assert.match(html, /aria-controls="workspace-join-panel"/);
  assert.match(html, /Selected originals stay unchanged/i);
  assert.match(html, /Select an OfficeKit split ZIP/i);
  assert.match(html, /Download.*before clearing/i);
});

test('invalid inputs and API errors surface as useful failures without extra requests', async () => {
  const calls = [];
  const context = loadClient(async (url) => {
    calls.push(url);
    return jsonResponse({ detail: 'Archive is malformed.' }, false);
  });
  const notZip = new Blob(['text']);
  Object.defineProperty(notZip, 'name', { value: 'notes.txt' });

  await assert.rejects(context.officekitImportArchive(notZip), /Choose a ZIP archive/);
  await assert.rejects(context.officekitExtractArchive('a'.repeat(32), 'x.zip', 'out'), /Archive is malformed/);
  assert.equal(calls.length, 1);
});

test('archive extraction rejects malformed workspace fields before making a request', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return jsonResponse({}); });

  await assert.rejects(context.officekitExtractArchive('../workspace', 'x.zip', 'out'), /workspace is no longer available/);
  await assert.rejects(context.officekitExtractArchive('a'.repeat(32), '', 'out'), /Choose an archive/);
  await assert.rejects(context.officekitExtractArchive('a'.repeat(32), 'x.zip', 42), /Output folder name/);
  await assert.rejects(context.officekitExtractArchive('a'.repeat(32), 'x.zip', 'x'.repeat(256)), /255 characters/);
  assert.equal(calls, 0);
});

test('archive extraction rejects malformed success payloads instead of reporting false success', async () => {
  const context = loadClient(async () => jsonResponse({
    artifact_id: 'not-an-id', output_name: 'out', file_count: 2, total_bytes: 5,
    files: ['safe.txt'], download_name: 'out.zip',
  }));

  await assert.rejects(
    context.officekitExtractArchive('a'.repeat(32), 'x.zip', 'out'),
    /OfficeKit did not return a valid extraction result/,
  );
});

test('generic server errors show the safe message from the standard error envelope', async () => {
  const context = loadClient(async () => jsonResponse({
    error: { code: 'internal_error', message: 'The operation could not be completed. Try again.' },
  }, false));

  await assert.rejects(
    context.officekitExtractArchive('a'.repeat(32), 'x.zip', 'out'),
    /The operation could not be completed\. Try again\./,
  );
});
