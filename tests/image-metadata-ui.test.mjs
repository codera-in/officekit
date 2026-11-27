import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* IMAGE METADATA CLIENT START \*\/([\s\S]*?)\/\* IMAGE METADATA CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(client, 'image metadata client exists');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, FormData, Blob };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

function response({ ok = true, type = 'image/jpeg', name = 'photo_metadata_removed.jpg', bytes = [0xff, 0xd8, 0xff, 0xd9] } = {}) {
  const blob = new Blob([Uint8Array.from(bytes)], { type });
  return {
    ok,
    headers: { get: key => key.toLowerCase() === 'content-type' ? type : `attachment; filename="${name}"` },
    blob: async () => blob,
    json: async () => ({ detail: 'Choose a supported image file.' }),
  };
}

test('EXIF cleanup has a dedicated searchable screen with local-copy and clear states', () => {
  for (const id of ['image-metadata-panel', 'image-metadata-input', 'image-metadata-selected', 'image-metadata-run', 'image-metadata-download', 'image-metadata-clear', 'image-metadata-status']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /image_exif_strip: \{ tab: 'converter', converterMode: 'image_metadata'/);
  assert.match(html, /Original file remains unchanged/i);
  assert.match(html, /EXIF fields such as camera details, capture time and GPS/i);
  assert.match(html, /No account or network connection required/i);
  assert.match(html, /imageMetadataOutput = null;[\s\S]*?image-metadata-download'\)\.hidden = true;[\s\S]*?status\.className = 'mt-3 min-h-6 text-sm text-slate-600'/);
});

test('metadata cleanup client posts one supported image to the local endpoint and validates output', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => { calls.push({ url, options }); return response(); });
  const file = new Blob(['image'], { type: 'image/jpeg' });
  Object.defineProperty(file, 'name', { value: 'photo.jpg' });

  const output = await context.officekitStripImageMetadata(file);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/image/metadata');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('file').name, 'photo.jpg');
  assert.equal(output.name, 'photo_metadata_removed.jpg');
  assert.equal(output.blob.type, 'image/jpeg');
});

test('metadata cleanup refuses unsupported, empty, oversized, malformed and mislabeled files', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return response(); });
  const text = new Blob(['x']);
  Object.defineProperty(text, 'name', { value: 'notes.txt' });
  await assert.rejects(context.officekitStripImageMetadata(text), /supported image/);
  await assert.rejects(context.officekitStripImageMetadata({ name: 'empty.png', size: 0 }), /empty/);
  await assert.rejects(context.officekitStripImageMetadata({ name: 'huge.png', size: 67_108_865 }), /64 MiB/);
  assert.equal(calls, 0);

  const contextBadMime = loadClient(async () => response({ type: 'text/html' }));
  const png = new Blob(['x']);
  Object.defineProperty(png, 'name', { value: 'photo.png' });
  await assert.rejects(contextBadMime.officekitStripImageMetadata(png), /valid image attachment/);

  const contextBadSignature = loadClient(async () => response({ type: 'image/png', name: 'photo_metadata_removed.png' }));
  await assert.rejects(contextBadSignature.officekitStripImageMetadata(png), /valid PNG/);
});

test('tool search route opens the exact metadata cleanup workbench', () => {
  assert.match(html, /image_exif_strip: \{ tab: 'converter', converterMode: 'image_metadata', focusId: 'image-metadata-input'/);
  assert.match(html, /selectSearchTool[\s\S]*?if \(destination\.converterMode\) setConverterMode\(destination\.converterMode\)/);
});
