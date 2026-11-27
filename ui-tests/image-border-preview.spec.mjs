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

test('Image Border preview matches the saved PNG and preserves transparent corners', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_border"]').click();
  await page.screenshot({ path: path.join(evidence, `image_border-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });

  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 4;
    canvas.height = 4;
    const context = canvas.getContext('2d');
    context.fillStyle = '#00ff00';
    context.fillRect(0, 0, 4, 4);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const original = Buffer.from(base64, 'base64');
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({
    name: 'frame.png', mimeType: 'image/png', buffer: original,
  });
  await page.locator('#tab-image-tools [data-param=width]').fill('2');
  await page.locator('#tab-image-tools [data-param=corner_radius]').fill('4');
  await page.locator('#tab-image-tools [data-param=fill]').fill('#ff0000');
  await page.locator('#tab-image-tools [data-param=fill_opacity]').fill('100');

  const preview = page.locator('#tab-image-tools [data-role=preview]');
  await expect(preview).toHaveJSProperty('naturalWidth', 8);
  await expect(preview).toBeVisible();
  await expect(page.locator('#tab-image-tools [data-role=preview-state]')).toBeHidden();
  const previewPixels = await page.evaluate(async () => {
    const image = document.querySelector('#tab-image-tools [data-role=preview]');
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0);
    return {
      width: canvas.width,
      height: canvas.height,
      corner: [...context.getImageData(0, 0, 1, 1).data],
      top: [...context.getImageData(4, 0, 1, 1).data],
      center: [...context.getImageData(3, 3, 1, 1).data],
    };
  });
  expect(previewPixels).toEqual({ width: 8, height: 8, corner: [0, 0, 0, 0], top: [255, 0, 0, 255], center: [0, 255, 0, 255] });
  await page.screenshot({ path: path.join(evidence, `image_border-current-source-preview-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__borderResult = { blob, name };
      return { state: 'saved' };
    };
  });
  await page.locator('#tab-image-tools [data-action=save]').click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your original is unchanged.');
  const saved = await page.evaluate(async () => {
    const { blob, name } = window.__borderResult;
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    return {
      name,
      type: blob.type,
      width: canvas.width,
      height: canvas.height,
      corner: [...context.getImageData(0, 0, 1, 1).data],
      top: [...context.getImageData(4, 0, 1, 1).data],
      center: [...context.getImageData(3, 3, 1, 1).data],
    };
  });
  expect(saved).toEqual({ name: 'frame-border.png', type: 'image/png', ...previewPixels });
  expect(original.toString('base64')).toBe(base64);
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_border-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
});
