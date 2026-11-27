import { test, expect } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

test.beforeEach(async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
});

test('Grayscale disables unused quality, validates recovery and exports matching grayscale pixels', async ({ page }) => {
  await page.locator('[data-image-tool-link="image_grayscale"]').click();
  const input = page.locator('#tab-image-tools input[type=file][data-slot=file]');
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 2;
    canvas.height = 2;
    const context = canvas.getContext('2d');
    const pixels = context.createImageData(2, 2);
    pixels.data.set([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 235, 140, 20, 0]);
    context.putImageData(pixels, 0, 0);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await input.setInputFiles({ name: 'primary-colors.png', mimeType: 'image/png', buffer: Buffer.from(base64, 'base64') });

  const preview = page.locator('#tab-image-tools [data-role=preview]');
  await expect(preview).toBeVisible();
  await expect(preview).toHaveJSProperty('naturalWidth', 2);
  await expect(preview).toHaveJSProperty('naturalHeight', 2);
  const quality = page.locator('#tab-image-tools [data-param=quality]');
  const format = page.locator('#tab-image-tools [data-param=format]');
  const save = page.locator('#tab-image-tools [data-action=save]');
  await expect(quality).toBeDisabled();
  await expect(quality).toHaveValue('90');
  await expect(page.locator('#image-quality-hint')).toHaveText('Only used for JPEG or WebP copies.');

  await format.selectOption('jpeg');
  await expect(quality).toBeEnabled();
  await quality.fill('101');
  await expect(quality).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#image-quality-error')).toHaveText('Use a whole number from 1 to 100.');
  await expect(save).toBeDisabled();
  await quality.fill('80');
  await expect(save).toBeEnabled();
  await format.selectOption('png');
  await expect(quality).toBeDisabled();
  await expect(quality).toHaveValue('80');

  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__grayscaleResult = { blob, name };
      return { state: 'saved' };
    };
  });
  await save.click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your original is unchanged.');
  const output = await page.evaluate(async () => {
    const { blob, name } = window.__grayscaleResult;
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
      pixels: [...context.getImageData(0, 0, 2, 2).data],
    };
  });
  expect(output).toEqual({
    name: 'primary-colors-grayscale.png',
    type: 'image/png',
    width: 2,
    height: 2,
    pixels: [76, 76, 76, 255, 150, 150, 150, 255, 29, 29, 29, 255, 0, 0, 0, 0],
  });

  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
});
