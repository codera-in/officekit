import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/image-resize-workbench.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/\/\* IMAGE RESIZE CLIENT START \*\/([\s\S]*?)\/\* IMAGE RESIZE CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(client, 'image resize client exists');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch, FormData, Blob };
  vm.runInNewContext(`${apiUrlHelper}\n${client}`, context);
  return context;
}

function pngResponse({ type = 'image/png', disposition = 'attachment; filename="lamp_resized.png"', bytes = [137,80,78,71,13,10,26,10,1], width = '800', height = '600' } = {}) {
  return {
    ok: true,
    headers: { get: key => ({ 'content-type': type, 'content-disposition': disposition, 'x-officekit-image-width': width, 'x-officekit-image-height': height }[key.toLowerCase()] || null) },
    blob: async () => new Blob([Uint8Array.from(bytes)], { type }),
  };
}

test('image resize mock describes the dimensions, preservation and download behavior', () => {
  for (const text of ['Before · generic converter', 'After · resize workbench', 'Maximum width (px)', 'Maximum height (px)', 'never enlarges smaller images', 'Up to 50 images', '64 MiB total', 'ZIP', 'originals remain unchanged']) assert.ok(mock.includes(text), text);
  const [, script] = mock.match(/<script>([\s\S]*?)<\/script>/) ?? [];
  assert.ok(script);
  assert.doesNotThrow(() => new vm.Script(script));
  assert.doesNotMatch(script, /fetch\s*\(|XMLHttpRequest|FileReader/);
});

test('resize workbench is searchable and clearly describes limits and preservation behavior', () => {
  for (const id of ['image-resize-panel','image-resize-input','image-resize-width','image-resize-height','image-resize-run','image-resize-download','image-resize-clear','image-resize-status']) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /image_resize: \{ tab: 'converter', converterMode: 'media_toolkit', mediaKind: 'image', mediaOperation: 'image-resize'/);
  assert.match(html, /setConverterMode\(destination\.converterMode\)/);
  assert.match(html, /never enlarges smaller images/i);
  assert.match(html, /animated GIF\/WebP frames and TIFF pages stay intact/i);
});

test('single-image resize sends bounded form data and validates attachment dimensions and signature', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => { calls.push({ url, options }); return pngResponse(); });
  const file = new Blob(['source'], { type: 'image/png' });
  Object.defineProperty(file, 'name', { value: 'lamp.png' });
  const output = await context.officekitResizeImages([file], 1600, 1200);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/image/resize');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('file').name, 'lamp.png');
  assert.equal(calls[0].options.body.get('max_width'), '1600');
  assert.equal(calls[0].options.body.get('max_height'), '1200');
  assert.equal(output.name, 'lamp_resized.png');
  assert.deepEqual([output.width, output.height], [800, 600]);
});

test('batch resize posts at most 50 supported files and accepts only a bounded ZIP', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, headers: { get: key => key.toLowerCase() === 'content-type' ? 'application/zip' : 'attachment; filename="resized_images.zip"' }, blob: async () => new Blob([Uint8Array.from([80,75,3,4,1])], { type: 'application/zip' }) };
  });
  const files = [new Blob(['one']), new Blob(['two'])];
  files.forEach((file, index) => Object.defineProperty(file, 'name', { value: `photo-${index}.jpg` }));
  const output = await context.officekitResizeImages(files, 800, 600);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/images/resize');
  assert.equal(calls[0].options.body.getAll('files').length, 2);
  assert.equal(output.name, 'resized_images.zip');
  assert.equal(output.batch, true);
});

test('resize client rejects unsafe sizes, count, dimensions and malformed attachments before download', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return pngResponse(); });
  const file = new Blob(['x']);
  Object.defineProperty(file, 'name', { value: 'photo.jpg' });
  await assert.rejects(context.officekitResizeImages([], 100, 100), /Select one or more/);
  await assert.rejects(context.officekitResizeImages([file], 0, 100), /between 1 and 10000/);
  await assert.rejects(context.officekitResizeImages(Array.from({ length: 51 }, () => file), 100, 100), /at most 50/);
  const contextBad = loadClient(async () => pngResponse({ type: 'text/html' }));
  await assert.rejects(contextBad.officekitResizeImages([file], 100, 100), /valid image attachment/);
  const contextWrongSignature = loadClient(async () => pngResponse({ bytes: [1,2,3,4,5,6,7,8], width: '80', height: '60' }));
  await assert.rejects(contextWrongSignature.officekitResizeImages([file], 100, 100), /valid PNG/);
  assert.equal(calls, 0);
});

test('resize client surfaces the batch pixel-work limit as a clear recoverable error', async () => {
  const message = 'The image batch requires too much processing; select fewer or smaller images.';
  const context = loadClient(async () => ({
    ok: false,
    json: async () => ({ detail: message }),
  }));
  const files = [new Blob(['one']), new Blob(['two'])];
  files.forEach((file, index) => Object.defineProperty(file, 'name', { value: `photo-${index}.jpg` }));

  await assert.rejects(context.officekitResizeImages(files, 800, 600), error => error.message === message);
});
