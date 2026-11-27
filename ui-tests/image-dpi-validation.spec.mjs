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

test('Image DPI / PPI keeps invalid densities editable and exports new resolution without resampling', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_dpi"]').click();
  await page.screenshot({ path: path.join(evidence, `image_dpi-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 300;
    canvas.height = 150;
    const context = canvas.getContext('2d');
    context.fillStyle = '#336699';
    context.fillRect(0, 0, 300, 150);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const original = Buffer.from(base64, 'base64');
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({
    name: 'print-size.png', mimeType: 'image/png', buffer: original,
  });
  const x = page.locator('#tab-image-tools [data-param=x]');
  const y = page.locator('#tab-image-tools [data-param=y]');
  const save = page.locator('#tab-image-tools [data-action=save]');
  const printSize = page.locator('#tab-image-tools [data-role=print-size]');
  await expect(printSize).toContainText('1.00 in × 0.50 in');
  await page.locator('#tab-image-tools [data-param=unit]').selectOption('cm');
  await x.fill('0');
  await expect(x).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#image-dpi-horizontal-error')).toHaveText('Use a whole number from 1 to 2,400.');
  await expect(save).toBeDisabled();
  await expect(printSize).toContainText('unavailable until the density values are corrected');
  await page.screenshot({ path: path.join(evidence, `image_dpi-current-source-invalid-${testInfo.project.name}-20261103.png`), fullPage: true });

  await x.fill('150');
  await y.fill('75');
  await expect(x).toHaveAttribute('aria-invalid', 'false');
  await expect(save).toBeEnabled();
  await expect(printSize).toContainText('2.0 cm × 2.0 cm');
  await page.screenshot({ path: path.join(evidence, `image_dpi-current-source-recovered-${testInfo.project.name}-20261103.png`), fullPage: true });
  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__dpiResult = { blob, name };
      return { state: 'saved' };
    };
  });
  await save.click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your original is unchanged.');
  const output = await page.evaluate(async () => {
    const { blob, name } = window.__dpiResult;
    const bitmap = await createImageBitmap(blob);
    const result = {
      name,
      type: blob.type,
      width: bitmap.width,
      height: bitmap.height,
      bytes: [...new Uint8Array(await blob.arrayBuffer())],
    };
    bitmap.close();
    return result;
  });
  expect(output.name).toBe('print-size-dpi.png');
  expect(output.type).toBe('image/png');
  expect([output.width, output.height]).toEqual([300, 150]);
  const bytes = Buffer.from(output.bytes);
  let density;
  for (let offset = 8; offset + 12 <= bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.toString('ascii', offset + 4, offset + 8);
    if (type === 'pHYs' && length === 9) {
      density = { xPixelsPerMeter: bytes.readUInt32BE(offset + 8), yPixelsPerMeter: bytes.readUInt32BE(offset + 12), unit: bytes[offset + 16] };
      break;
    }
    offset += length + 12;
  }
  expect(density).toEqual({ xPixelsPerMeter: 15000, yPixelsPerMeter: 7500, unit: 1 });
  expect(original.toString('base64')).toBe(base64);
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.ok-text-link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_dpi-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
});
