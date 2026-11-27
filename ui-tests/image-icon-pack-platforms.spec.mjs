import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { inflateRawSync } from 'node:zlib';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');

function unzipEntries(buffer) {
  const entries = new Map();
  let offset = 0;
  while (offset + 30 <= buffer.length && buffer.readUInt32LE(offset) === 0x04034b50) {
    const method = buffer.readUInt16LE(offset + 8);
    const compressedSize = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const dataStart = offset + 30;
    const name = buffer.toString('utf8', dataStart, dataStart + nameLength);
    const payloadStart = dataStart + nameLength + extraLength;
    const compressed = buffer.subarray(payloadStart, payloadStart + compressedSize);
    entries.set(name, method === 8 ? inflateRawSync(compressed) : compressed);
    offset = payloadStart + compressedSize;
  }
  return entries;
}

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
});

test('Icon Pack Generator validates platform choice and exports the complete three-platform ZIP', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_icon_pack"]').click();
  await page.screenshot({ path: path.join(evidence, `image_icon_pack-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 16;
    canvas.height = 8;
    const context = canvas.getContext('2d');
    context.fillStyle = '#663399';
    context.fillRect(0, 0, 16, 8);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({
    name: 'test-icon.png', mimeType: 'image/png', buffer: Buffer.from(base64, 'base64'),
  });
  const body = page.locator('#tab-image-tools .image-tools__body');
  const save = body.locator('[data-action=save-zip]');
  const web = body.locator('[data-param=web]');
  const windows = body.locator('[data-param=windows]');
  const macos = body.locator('[data-param=macos]');
  await expect(save).toBeVisible();
  await expect(page.locator('#tab-image-tools .ok-action-dock button:visible')).toHaveCount(1);
  await page.screenshot({ path: path.join(evidence, `image_icon_pack-current-source-ready-${testInfo.project.name}-20261103.png`), fullPage: true });

  await web.uncheck();
  let invalidRequests = 0;
  const track = request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/icon-packs') invalidRequests += 1; };
  page.on('request', track);
  await save.click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Choose at least one platform.');
  expect(invalidRequests).toBe(0);
  page.off('request', track);
  await page.screenshot({ path: path.join(evidence, `image_icon_pack-current-source-invalid-${testInfo.project.name}-20261103.png`), fullPage: true });

  await web.check();
  await windows.check();
  await macos.check();
  await body.locator('[data-param=fit]').selectOption('crop');
  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__iconPackResult = { blob, name };
      return { state: 'saved' };
    };
  });
  const responseReady = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/icon-packs');
  await save.click();
  const response = await responseReady;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/zip');
  expect(response.headers()['x-officekit-upscaled-sizes']).toBe('16,24,32,48,64,128,180,192,256,512,1024');
  expect(response.request().postDataBuffer().toString()).toContain('name="platforms"\r\n\r\nweb,windows,macos');
  expect(response.request().postDataBuffer().toString()).toContain('name="fit"\r\n\r\ncrop');
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('ZIP saved.');
  const saved = await page.evaluate(async () => ({
    name: window.__iconPackResult.name,
    type: window.__iconPackResult.blob.type,
    bytes: [...new Uint8Array(await window.__iconPackResult.blob.arrayBuffer())],
  }));
  expect(saved.name).toBe('test-icon-icons.zip');
  expect(saved.type).toBe('application/zip');
  const entries = unzipEntries(Buffer.from(saved.bytes));
  expect([...entries.keys()].sort()).toEqual([
    'web/favicon-16x16.png', 'web/favicon-32x32.png', 'web/android-chrome-192x192.png',
    'web/android-chrome-512x512.png', 'web/apple-touch-icon.png', 'web/favicon.ico', 'windows/app.ico',
    'macos/icon.iconset/icon_16x16.png', 'macos/icon.iconset/icon_16x16@2x.png',
    'macos/icon.iconset/icon_32x32.png', 'macos/icon.iconset/icon_32x32@2x.png',
    'macos/icon.iconset/icon_128x128.png', 'macos/icon.iconset/icon_128x128@2x.png',
    'macos/icon.iconset/icon_256x256.png', 'macos/icon.iconset/icon_256x256@2x.png',
    'macos/icon.iconset/icon_512x512.png', 'macos/icon.iconset/icon_512x512@2x.png',
  ].sort());
  for (const [name, size] of new Map([
    ['web/favicon-16x16.png', 16], ['web/favicon-32x32.png', 32],
    ['web/android-chrome-192x192.png', 192], ['web/android-chrome-512x512.png', 512],
    ['web/apple-touch-icon.png', 180],
    ['macos/icon.iconset/icon_16x16.png', 16], ['macos/icon.iconset/icon_16x16@2x.png', 32],
    ['macos/icon.iconset/icon_32x32.png', 32], ['macos/icon.iconset/icon_32x32@2x.png', 64],
    ['macos/icon.iconset/icon_128x128.png', 128], ['macos/icon.iconset/icon_128x128@2x.png', 256],
    ['macos/icon.iconset/icon_256x256.png', 256], ['macos/icon.iconset/icon_256x256@2x.png', 512],
    ['macos/icon.iconset/icon_512x512.png', 512], ['macos/icon.iconset/icon_512x512@2x.png', 1024],
  ])) {
    const image = entries.get(name);
    expect(image.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    expect([image.readUInt32BE(16), image.readUInt32BE(20)]).toEqual([size, size]);
  }
  for (const name of ['web/favicon.ico', 'windows/app.ico']) {
    expect(entries.get(name).subarray(0, 4)).toEqual(Buffer.from([0, 0, 1, 0]));
  }
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.ok-text-link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_icon_pack-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
});
