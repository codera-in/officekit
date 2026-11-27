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

test('Image Collage preserves tile order, disables incomplete exports and matches preview pixels', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_collage"]').click();
  await page.screenshot({ path: path.join(evidence, `image_collage-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const encoded = await page.evaluate(() => [
    ['#ffff00', '#ff0000', '#0000ff', '#00ff00'],
    ['#ff00ff', '#000000', '#ffffff', '#00ffff'],
  ].map(colors => {
    const canvas = document.createElement('canvas');
    canvas.width = 8;
    canvas.height = 4;
    const context = canvas.getContext('2d');
    colors.forEach((color, index) => { context.fillStyle = color; context.fillRect(index * 2, 0, 2, 4); });
    return canvas.toDataURL('image/png').split(',')[1];
  }));
  const files = encoded.map((data, index) => ({
    name: `tile-${index + 1}.png`, mimeType: 'image/png', buffer: Buffer.from(data, 'base64'),
  }));
  const picker = page.locator('#tab-image-tools input[type=file][data-slot=files]');
  await picker.setInputFiles(files);
  const rows = page.locator('#tab-image-tools [data-role=order] li');
  await rows.nth(0).getByRole('button', { name: 'Move down' }).click();
  await expect(rows.nth(0)).toContainText('tile-2.png');
  await expect(rows.nth(1)).toContainText('tile-1.png');
  await page.screenshot({ path: path.join(evidence, `image_collage-current-source-reordered-${testInfo.project.name}-20261103.png`), fullPage: true });

  await rows.nth(1).getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#tab-image-tools [data-role=order] li')).toHaveCount(1);
  await expect(page.locator('#tab-image-tools [data-action=save]')).toBeDisabled();
  await page.screenshot({ path: path.join(evidence, `image_collage-current-source-one-file-${testInfo.project.name}-20261103.png`), fullPage: true });
  await picker.setInputFiles(files[0]);
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('tile-2.png');
  await expect(rows.nth(1)).toContainText('tile-1.png');

  await page.locator('#tab-image-tools [data-param=cell_width]').fill('16');
  await page.locator('#tab-image-tools [data-param=cell_height]').fill('16');
  await page.locator('#tab-image-tools [data-param=gap]').fill('1');
  await page.locator('#tab-image-tools [data-param=padding]').fill('1');
  await page.locator('#tab-image-tools [data-param=format]').selectOption('png');
  await expect(page.locator('#tab-image-tools [data-role=canvas-size]')).toHaveText('Canvas 35 × 18 px');
  const previewResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/image-collages');
  await page.locator('#tab-image-tools [data-action=preview]').click();
  expect((await previewResponse).status()).toBe(200);
  const preview = page.locator('#tab-image-tools [data-role=ordered-img]');
  await expect(preview).toBeVisible();
  await expect(preview).toHaveJSProperty('naturalWidth', 35);
  await expect(preview).toHaveJSProperty('naturalHeight', 18);
  const previewPixels = await page.evaluate(async () => {
    const image = document.querySelector('#tab-image-tools [data-role=ordered-img]');
    const bitmap = await createImageBitmap(image);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    return { width: canvas.width, height: canvas.height, pixels: [...context.getImageData(0, 0, canvas.width, canvas.height).data] };
  });
  expect(previewPixels.width).toBe(35);
  expect(previewPixels.height).toBe(18);
  await page.screenshot({ path: path.join(evidence, `image_collage-current-source-preview-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__collageResult = { blob, name };
      return { state: 'saved' };
    };
  });
  const saveResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/image-collages');
  await page.locator('#tab-image-tools [data-action=save]').click();
  expect((await saveResponse).status()).toBe(200);
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your originals are unchanged.');
  const savedPixels = await page.evaluate(async () => {
    const { blob, name } = window.__collageResult;
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    return { name, type: blob.type, width: canvas.width, height: canvas.height, pixels: [...context.getImageData(0, 0, canvas.width, canvas.height).data] };
  });
  expect(savedPixels).toEqual({ name: 'collage.png', type: 'image/png', ...previewPixels });
  await page.screenshot({ path: path.join(evidence, `image_collage-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.image-tools__moves button')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
});
