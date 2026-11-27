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

test('Image Color Adjustments only validates quality when the chosen format uses it', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_adjust"]').click();
  await page.screenshot({ path: path.join(evidence, `image_adjust-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const input = page.locator('#tab-image-tools input[type=file][data-slot=file]');
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 2;
    canvas.height = 2;
    const context = canvas.getContext('2d');
    context.fillStyle = '#808080';
    context.fillRect(0, 0, 2, 2);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await input.setInputFiles({ name: 'neutral.png', mimeType: 'image/png', buffer: Buffer.from(base64, 'base64') });

  const quality = page.locator('#tab-image-tools [data-param=quality]');
  const format = page.locator('#tab-image-tools [data-param=format]');
  const save = page.locator('#tab-image-tools [data-action=save]');
  const preview = page.locator('#tab-image-tools [data-role=preview]');
  await expect(preview).toHaveJSProperty('naturalWidth', 2);
  await expect(quality).toBeDisabled();
  await expect(quality).toHaveValue('90');
  await expect(page.locator('#image-quality-hint')).toHaveText('Only used for JPEG or WebP copies.');
  await page.screenshot({ path: path.join(evidence, `image_adjust-current-source-quality-disabled-${testInfo.project.name}-20261103.png`), fullPage: true });

  await format.selectOption('jpeg');
  await expect(quality).toBeEnabled();
  await quality.fill('101');
  await expect(quality).toHaveAttribute('aria-invalid', 'true');
  await expect(save).toBeDisabled();
  await page.screenshot({ path: path.join(evidence, `image_adjust-current-source-quality-invalid-${testInfo.project.name}-20261103.png`), fullPage: true });
  await format.selectOption('png');
  await expect(quality).toBeDisabled();
  await expect(quality).toHaveValue('101');
  await expect(save).toBeEnabled();
  await format.selectOption('jpeg');
  await expect(save).toBeDisabled();
  await quality.fill('90');
  await expect(save).toBeEnabled();

  await page.locator('#tab-image-tools [data-param=brightness]').fill('50');
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Preview updated.');
  const previewPixels = await page.evaluate(async () => {
    const image = document.querySelector('#tab-image-tools [data-role=preview]');
    const canvas = document.createElement('canvas');
    canvas.width = 2;
    canvas.height = 2;
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0);
    return [...context.getImageData(0, 0, 1, 1).data];
  });
  expect(previewPixels[0]).toBeGreaterThan(128);

  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__adjustedResult = { blob, name };
      return { state: 'saved' };
    };
  });
  await save.click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your original is unchanged.');
  const saved = await page.evaluate(async () => {
    const { blob, name } = window.__adjustedResult;
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    return { name, type: blob.type, width: canvas.width, height: canvas.height, pixels: [...context.getImageData(0, 0, 1, 1).data] };
  });
  expect(saved).toEqual({
    name: 'neutral-adjusted.png',
    type: 'image/png',
    width: 2,
    height: 2,
    pixels: previewPixels,
  });
  await page.screenshot({ path: path.join(evidence, `image_adjust-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
});
