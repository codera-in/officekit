import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const client = html.match(/\/\* SCREENSHOT EDITOR CLIENT START \*\/([\s\S]*?)\/\* SCREENSHOT EDITOR CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(client, 'the screenshot editor client helper exists');
  const context = {
    fetch,
    officekitApiUrl: path => `http://127.0.0.1:8000${path}`,
    FormData,
    Blob,
    File,
    TextEncoder,
    Uint8Array,
    Buffer: undefined,
  };
  vm.runInNewContext(client, context);
  return context;
}

test('screenshot editor is discoverable and provides accessible paste, preview, edit, undo and export controls', () => {
  for (const id of [
    'tab-screenshot', 'screenshot-select-button', 'screenshot-paste-button', 'screenshot-file-input',
    'screenshot-canvas', 'screenshot-undo-button', 'screenshot-redo-button', 'screenshot-tool-crop',
    'screenshot-tool-blur', 'screenshot-tool-mask', 'screenshot-tool-pixelate', 'screenshot-tool-eraser', 'screenshot-tool-pan', 'screenshot-tool-highlight', 'screenshot-tool-circle', 'screenshot-tool-rectangle', 'screenshot-rotate', 'screenshot-zoom-in', 'screenshot-zoom-out', 'screenshot-fit-view', 'screenshot-export-format', 'screenshot-export-button',
    'screenshot-copy-button', 'screenshot-clear-button', 'screenshot-status',
  ]) assert.ok(html.includes(`id="${id}"`), `${id} exists`);
  assert.match(html, /screenshot_editor: \{ tab: 'screenshot' \}/);
  assert.match(html, /role="application"|aria-label="Screenshot editing canvas"/);
  assert.match(html, /window\.__TAURI__\?\.clipboardManager/);
  assert.match(html, /Paste from clipboard/);
  assert.match(html, /screenshot-editor/);
});

test('screenshot editor screen shows at most three buttons: Choose image, Save and More', () => {
  const sourceStart = html.indexOf('<div id="screenshot-source-actions"');
  const sourceEnd = html.indexOf('<input id="screenshot-file-input"', sourceStart);
  assert.ok(sourceStart >= 0 && sourceEnd > sourceStart, 'source actions row exists');
  const sourceButtons = html.slice(sourceStart, sourceEnd).match(/<button\b/g) ?? [];
  assert.equal(sourceButtons.length, 1, 'the source row keeps only Choose image as a button');
  const dockStart = html.indexOf('<footer id="screenshot-action-dock"');
  const dockEnd = html.indexOf('</footer>', dockStart);
  assert.ok(dockStart >= 0 && dockEnd > dockStart, 'action dock exists');
  const dock = html.slice(dockStart, dockEnd);
  const menuStart = dock.indexOf('<div class="ok-screenshot-more__menu">');
  const dockOutsideMenu = dock.slice(0, menuStart) + dock.slice(dock.indexOf('</details>', menuStart));
  assert.equal(dockOutsideMenu.match(/<button\b/g)?.length, 1, 'the dock shows Save as its only button');
  assert.equal(dockOutsideMenu.match(/<summary\b/g)?.length, 1, 'the dock shows one More menu');
  const menu = dock.slice(menuStart, dock.indexOf('</details>', menuStart));
  assert.match(menu, /id="screenshot-copy-button"/, 'Copy image sits inside More');
  assert.match(menu, /id="screenshot-media-toolkit-button"/, 'Optimize edited copy sits inside More');
  assert.match(dock, /id="screenshot-export-button"[^>]*>Save</, 'the export button is labelled Save');
});

test('screenshot editor controls expose hover tooltips and shape menus use an opaque theme surface', () => {
  const toolbarStart = html.indexOf('<div id="screenshot-toolbar"');
  const toolbarEnd = html.indexOf('<section class="flex min-w-0 flex-col" aria-label="Screenshot preview"', toolbarStart);
  assert.ok(toolbarStart >= 0 && toolbarEnd > toolbarStart, 'screenshot toolbar section exists');
  const toolbar = html.slice(toolbarStart, toolbarEnd);
  const interactiveControls = [...toolbar.matchAll(/<(button|summary|select|input)\b([^>]*)>/gi)];
  assert.ok(interactiveControls.length >= 30, 'all annotation, adjustment, and export controls are covered');
  for (const [, tag, attributes] of interactiveControls) {
    assert.match(attributes, /\btitle=(?:"[^"]+"|'[^']+')/, `${tag} has a descriptive hover tooltip`);
  }
  const css = fs.readFileSync('assets/officekit.input.css', 'utf8');
  assert.match(css, /#screenshot-toolbar details > div\s*\{[^}]*background:\s*var\(--ok-bg\)\s*!important/);
});

test('screenshot client sends original bytes and ordered operations to the authenticated local API', async () => {
  const calls = [];
  const bytes = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 13, 10, 26, 10, 1]);
  const context = loadClient(async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      headers: { get: name => name.toLowerCase() === 'content-type' ? 'image/jpeg' : null },
      blob: async () => new Blob([Uint8Array.from([0xff, 0xd8, 0xff, 0xd9])], { type: 'image/jpeg' }),
    };
  });
  const input = new Blob([bytes], { type: 'image/png' });
  Object.defineProperty(input, 'name', { value: 'clipboard.png' });
  const operations = [
    { type: 'crop', x: 2, y: 3, width: 20, height: 10 },
    { type: 'mask', x: 1, y: 1, width: 4, height: 4, color: '#201A2B' },
  ];

  const result = await context.officekitEditScreenshot(input, operations, 'jpeg');

  assert.equal(result.fileName, 'screenshot-edited.jpg');
  assert.equal(result.contentType, 'image/jpeg');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/screenshot/edit');
  assert.equal(calls[0].options.method, 'POST');
  const form = calls[0].options.body;
  assert.equal(form.get('file').name, 'clipboard.png');
  assert.equal(form.get('format'), 'jpeg');
  assert.deepEqual(JSON.parse(form.get('operations')), operations);
});

test('screenshot client rejects invalid file, operation bounds, formats, MIME, signatures and output limits', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; throw new Error('must not fetch'); });
  const file = new Blob(['image'], { type: 'image/png' });
  const valid = [{ type: 'mask', x: 0, y: 0, width: 1, height: 1, color: '#000000' }];
  await assert.rejects(context.officekitEditScreenshot(null, valid, 'png'), /select an image/i);
  await assert.rejects(context.officekitEditScreenshot(file, [], 'png'), /operation/i);
  await assert.rejects(context.officekitEditScreenshot(file, Array.from({ length: 51 }, () => valid[0]), 'png'), /50/i);
  await assert.rejects(context.officekitEditScreenshot(file, valid, 'gif'), /format/i);
  assert.equal(calls, 0);

  const wrongMime = loadClient(async () => ({ ok: true, headers: { get: () => 'application/json' }, blob: async () => new Blob(['no']) }));
  await assert.rejects(wrongMime.officekitEditScreenshot(file, valid, 'png'), /unexpected image format/i);
  const wrongSignature = loadClient(async () => ({ ok: true, headers: { get: () => 'image/png' }, blob: async () => new Blob(['not png'], { type: 'image/png' }) }));
  await assert.rejects(wrongSignature.officekitEditScreenshot(file, valid, 'png'), /invalid image/i);
  const empty = loadClient(async () => ({ ok: true, headers: { get: () => 'image/png' }, blob: async () => new Blob([]) }));
  await assert.rejects(empty.officekitEditScreenshot(file, valid, 'png'), /empty/i);
});

test('clipboard is read only after the explicit user action and editor cleanup releases image resources', () => {
  const pasteHandler = html.match(/async function officekitPasteScreenshotFromClipboard\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(pasteHandler, 'clipboard read is contained in an explicit button handler');
  assert.match(pasteHandler, /officekitReadScreenshotClipboardFile/);
  assert.match(html, /window\.__TAURI__\?\.clipboardManager/);
  assert.match(html.slice(html.indexOf('async function officekitReadScreenshotClipboardFile'), html.indexOf('async function officekitWriteScreenshotClipboardImage')), /image\/(png|jpeg)/);
  assert.match(html, /function clearScreenshotEditor/);
  assert.match(html, /URL\.revokeObjectURL/);
  assert.match(html, /addEventListener\('paste'/);
  assert.match(html, /addEventListener\('keydown'/);
});

test('native screenshot paste converts a bounded Tauri clipboard image to a PNG file', async () => {
  const context = loadClient(async () => { throw new Error('not used'); });
  const receivedPixels = [];
  const clipboardPng = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
  context.ImageData = class ImageData {
    constructor(data, width, height) { this.data = data; this.width = width; this.height = height; }
  };
  context.document = {
    createElement: name => {
      assert.equal(name, 'canvas');
      return {
        width: 0,
        height: 0,
        getContext: () => ({ putImageData: imageData => receivedPixels.push(imageData) }),
        toBlob: callback => callback(new Blob([clipboardPng], { type: 'image/png' })),
      };
    },
  };
  let rgbaCalls = 0;
  const nativeClipboard = {
    readImage: async () => ({
      size: async () => ({ width: 2, height: 1 }),
      rgba: async () => { rgbaCalls += 1; return new Uint8Array([1, 2, 3, 255, 4, 5, 6, 255]); },
      close: async () => { receivedPixels.push('closed'); },
    }),
  };

  const file = await context.officekitReadScreenshotClipboardFile(nativeClipboard, null);

  assert.equal(file.name, 'pasted-screenshot.png');
  assert.equal(file.type, 'image/png');
  assert.deepEqual([...new Uint8Array(await file.arrayBuffer())], [...clipboardPng]);
  assert.equal(rgbaCalls, 1);
  assert.equal(receivedPixels[0].width, 2);
  assert.equal(receivedPixels[0].height, 1);
  assert.equal(receivedPixels[1], 'closed');
});

test('native screenshot paste rejects excessive dimensions before reading RGBA and keeps the browser fallback', async () => {
  const context = loadClient(async () => { throw new Error('not used'); });
  let rgbaCalls = 0;
  const oversizedNative = {
    readImage: async () => ({
      size: async () => ({ width: 4097, height: 4096 }),
      rgba: async () => { rgbaCalls += 1; return new Uint8Array(); },
    }),
  };
  await assert.rejects(
    context.officekitReadScreenshotClipboardFile(oversizedNative, null),
    /16 million pixels/i,
  );
  assert.equal(rgbaCalls, 0, 'oversized clipboard images are rejected before allocating RGBA bytes');

  const browserBlob = new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], { type: 'image/png' });
  const browserClipboard = {
    read: async () => [{
      types: ['text/plain', 'image/png'],
      getType: async type => type === 'image/png' ? browserBlob : null,
    }],
  };
  const fallbackFile = await context.officekitReadScreenshotClipboardFile(
    { readImage: async () => { throw new Error('No image on native clipboard'); } },
    browserClipboard,
  );
  assert.equal(fallbackFile.name, 'pasted-screenshot.png');
  assert.equal(fallbackFile.type, 'image/png');
});

test('native screenshot copy writes image pixels to Tauri clipboard and closes native resources', async () => {
  const context = loadClient(async () => { throw new Error('not used'); });
  const calls = [];
  const rgba = new Uint8ClampedArray([1, 2, 3, 255]);
  const bitmap = { width: 1, height: 1, close: () => calls.push('bitmap-close') };
  context.createImageBitmap = async blob => {
    assert.equal(blob.type, 'image/png');
    return bitmap;
  };
  context.document = {
    createElement: name => {
      assert.equal(name, 'canvas');
      return {
        width: 0,
        height: 0,
        getContext: () => ({
          drawImage: image => assert.equal(image, bitmap),
          getImageData: () => ({ data: rgba }),
        }),
      };
    },
  };
  const nativeClipboard = { writeImage: async image => calls.push(['write', image]) };
  const nativeImage = {
    new: async (pixels, width, height) => {
      assert.deepEqual([...pixels], [1, 2, 3, 255]);
      assert.equal(width, 1);
      assert.equal(height, 1);
      return { close: async () => calls.push('image-close') };
    },
  };

  await context.officekitWriteScreenshotClipboardImage(
    new Blob(['encoded-png'], { type: 'image/png' }), nativeClipboard, nativeImage, null, null,
  );

  assert.equal(calls[0][0], 'write');
  assert.deepEqual(calls.slice(1), ['image-close', 'bitmap-close']);
});

test('screenshot copy falls back to browser clipboard and reports empty clipboard as no image', async () => {
  const context = loadClient(async () => { throw new Error('not used'); });
  const blob = new Blob(['encoded-png'], { type: 'image/png' });
  let copied;
  class ClipboardItemStub {
    constructor(items) { this.items = items; }
  }
  const webClipboard = {
    write: async items => { copied = items[0]; },
  };
  await context.officekitWriteScreenshotClipboardImage(blob, null, null, webClipboard, ClipboardItemStub);
  assert.ok(copied instanceof ClipboardItemStub);
  assert.equal(copied.items['image/png'], blob);

  assert.equal(await context.officekitReadScreenshotClipboardFile(null, { read: async () => [] }), null);
});

test('Tauri registers only the explicit native image clipboard permissions used by screenshot editing', () => {
  const cargo = fs.readFileSync('src-tauri/Cargo.toml', 'utf8');
  const rust = fs.readFileSync('src-tauri/src/lib.rs', 'utf8');
  const capability = JSON.parse(fs.readFileSync('src-tauri/capabilities/default.json', 'utf8'));
  assert.match(cargo, /^tauri-plugin-clipboard-manager\s*=\s*"2\./m);
  assert.match(rust, /\.plugin\(tauri_plugin_clipboard_manager::init\(\)\)/);
  assert.deepEqual(capability.permissions, [
    'core:event:default',
    'clipboard-manager:allow-read-image',
    'clipboard-manager:allow-write-image',
  ]);
});
