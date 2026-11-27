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

test('Compare Images explains size mismatch, recovers by scaling, and saves the full difference PNG', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_compare"]').click();
  await expect(page.locator('#tab-image-tools')).toBeVisible();
  await page.screenshot({ path: path.join(evidence, `image_compare-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const generated = await page.evaluate(() => {
    const make = (width, height, color) => {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d');
      context.fillStyle = color;
      context.fillRect(0, 0, width, height);
      return canvas.toDataURL('image/png').split(',')[1];
    };
    return { a: make(2, 2, '#000000'), b: make(4, 4, '#000000') };
  });
  await page.locator('#tab-image-tools input[type=file][data-slot=a]').setInputFiles({ name: 'before.png', mimeType: 'image/png', buffer: Buffer.from(generated.a, 'base64') });
  await page.locator('#tab-image-tools input[type=file][data-slot=b]').setInputFiles({ name: 'after.png', mimeType: 'image/png', buffer: Buffer.from(generated.b, 'base64') });
  const result = page.locator('#tab-image-tools [data-role=compare-result]');
  await expect(result).toContainText('The images are different sizes.');
  await expect(result).toContainText('No pixel difference was computed.');
  await expect(result).not.toContainText(/\d+(?:\.\d+)?%/);
  await expect(page.getByRole('button', { name: 'Scale B to A' })).toBeVisible();
  await expect(page.locator('#tab-image-tools [data-role=threshold-control]')).toBeHidden();
  await expect(result.locator('[data-action=save-diff]')).toBeDisabled();
  await page.screenshot({ path: path.join(evidence, `image_compare-current-source-mismatch-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.getByRole('button', { name: 'Scale B to A' }).click();
  await expect(result).toContainText('No pixel differed by more than 0 at 2 × 2.');
  await page.getByRole('tab', { name: 'Overlay' }).click();
  const opacity = page.locator('#tab-image-tools [data-param=overlay-opacity]');
  await expect(opacity).toBeVisible();
  await opacity.evaluate(node => {
    node.value = '25';
    node.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(page.locator('#tab-image-tools [data-role=overlay-output]')).toHaveText('25%');
  await expect(page.locator('#tab-image-tools .image-tools__overlay-top')).toHaveCSS('opacity', '0.25');
  await page.screenshot({ path: path.join(evidence, `image_compare-current-source-overlay-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.getByRole('tab', { name: 'Difference' }).click();
  const difference = page.locator('#tab-image-tools img[alt="Difference map"]');
  await expect(difference).toBeVisible();
  await expect(page.locator('#tab-image-tools [data-role=threshold-control]')).toBeVisible();
  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__differenceResult = { blob, name };
      return { state: 'saved' };
    };
  });
  await page.locator('#tab-image-tools [data-action=save-diff]').click();
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Difference image saved.');
  const saved = await page.evaluate(async () => {
    const { blob, name } = window.__differenceResult;
    const bitmap = await createImageBitmap(blob);
    const output = { name, type: blob.type, width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return output;
  });
  expect(saved).toEqual({ name: 'before-vs-after-difference.png', type: 'image/png', width: 2, height: 2 });
  const actionButtonCount = await page.locator('#tab-image-tools button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.ok-text-link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_compare-current-source-saved-${testInfo.project.name}-20261103.png`), fullPage: true });
});
