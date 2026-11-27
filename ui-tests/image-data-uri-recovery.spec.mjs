import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
});

test('Image ↔ Data URI copies and saves an encoded URI, then recovers a malformed image URI', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_data_uri"]').click();
  await page.screenshot({ path: path.join(evidence, `image_data_uri-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const pngBase64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 2;
    canvas.height = 2;
    const context = canvas.getContext('2d');
    context.fillStyle = '#663399';
    context.fillRect(0, 0, 2, 2);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const png = Buffer.from(pngBase64, 'base64');
  const expectedUri = `data:image/png;base64,${png.toString('base64')}`;
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({ name: 'pixel.png', mimeType: 'image/png', buffer: png });
  const result = page.locator('#tab-image-tools [data-role=uri-result]');
  await expect(result).toContainText('image/png');
  await expect(result).toContainText(`${png.length} bytes`);
  await page.screenshot({ path: path.join(evidence, `image_data_uri-current-source-encoded-${testInfo.project.name}-20261103.png`), fullPage: true });
  await page.evaluate(() => {
    window.__uriClipboard = '';
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => { window.__uriClipboard = value; } } });
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__uriDownload = { blob, name };
      return { state: 'saved' };
    };
  });
  await result.locator('[data-action=copy-uri]').click();
  await expect.poll(() => page.evaluate(() => window.__uriClipboard)).toBe(expectedUri);
  await result.locator('[data-action=save-txt]').click();
  const textDownload = await page.evaluate(async () => ({
    name: window.__uriDownload.name,
    type: window.__uriDownload.blob.type,
    text: await window.__uriDownload.blob.text(),
  }));
  expect(textDownload).toEqual({ name: 'pixel-data-uri.txt', type: 'text/plain;charset=utf-8', text: expectedUri });

  await page.locator('#tab-image-tools [data-param=direction]').selectOption('decode');
  const uriInput = page.locator('#tab-image-tools [data-param=data_uri]');
  await uriInput.fill('data:image/png;base64,aGVsbG8=');
  const save = page.locator('#tab-image-tools [data-action=save-decode]');
  await expect(save).toBeEnabled();
  await page.screenshot({ path: path.join(evidence, `image_data_uri-current-source-malformed-${testInfo.project.name}-20261103.png`), fullPage: true });
  const rejectedResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/data-uri-images');
  await save.click();
  expect((await rejectedResponse).status()).toBe(422);
  await expect(uriInput).toHaveAttribute('aria-invalid', 'true');
  await expect(uriInput).toHaveValue('data:image/png;base64,aGVsbG8=');
  await expect(page.locator('#tab-image-tools [data-role=uri-check]')).toHaveText('The file contents do not match its image type.');
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveClass(/ok-image-error/);
  await expect(save).toBeEnabled();

  await uriInput.fill(expectedUri);
  const recoveredResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/data-uri-images');
  await save.click();
  expect((await recoveredResponse).status()).toBe(200);
  const recovered = await page.evaluate(async () => ({
    name: window.__uriDownload.name,
    type: window.__uriDownload.blob.type,
    bytes: [...new Uint8Array(await window.__uriDownload.blob.arrayBuffer())],
  }));
  expect(recovered).toEqual({ name: 'decoded-image.png', type: 'image/png', bytes: [...png] });
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Image saved.');
  await expect(uriInput).not.toHaveAttribute('aria-invalid', 'true');
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_data_uri-current-source-recovered-${testInfo.project.name}-20261103.png`), fullPage: true });
});
