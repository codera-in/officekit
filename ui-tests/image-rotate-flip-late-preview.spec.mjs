import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aT8AAAAASUVORK5CYII=', 'base64');

for (const latePreview of [
  { name: 'failure', status: 422 },
  { name: 'success', status: 200 },
]) {
  test(`Rotate & Flip keeps Saved after a late ${latePreview.name} preview`, async ({ page }, testInfo) => {
    await mkdir(evidence, { recursive: true });
    await routeAuthenticatedApi(page);
    let finishPreview;
    const heldPreview = new Promise(resolve => { finishPreview = resolve; });
    let markPreviewStarted;
    const previewStarted = new Promise(resolve => { markPreviewStarted = resolve; });
    let requestCount = 0;
    await page.route('**/api/image-renditions', async route => {
      requestCount += 1;
      if (requestCount === 1) {
        markPreviewStarted();
        await heldPreview;
        if (latePreview.status === 422) {
          await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Preview could not be made.' }) });
        } else {
          await route.fulfill({ status: 200, contentType: 'image/png', body: png });
        }
        return;
      }
      await route.fulfill({ status: 200, contentType: 'image/png', body: png });
    });

    try {
      await page.goto('/');
      await waitForAppReady(page);
      await page.locator('[data-image-tool-link="image_rotate_flip"]').click();
      await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({
        name: 'orientation.png', mimeType: 'image/png', buffer: png,
      });
      await page.locator('#tab-image-tools [data-turn="90"]').click();
      await previewStarted;
      await page.screenshot({ path: path.join(evidence, `image_rotate_flip-current-source-preview-pending-${latePreview.name}-${testInfo.project.name}-20261103.png`), fullPage: true });

      await page.evaluate(() => {
        window.officekitDownloadResultBlob = async (blob, name) => {
          window.__rotateFlipResult = { blob, name };
          return { state: 'saved' };
        };
      });
      const saveResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/image-renditions');
      await page.locator('#tab-image-tools [data-action=save]').click();
      expect((await saveResponse).status()).toBe(200);
      const status = page.locator('#tab-image-tools .ok-action-dock__status');
      await expect(status).toHaveText('Saved. Your original is unchanged.');
      const saved = await page.evaluate(async () => ({
        name: window.__rotateFlipResult.name,
        type: window.__rotateFlipResult.blob.type,
        bytes: [...new Uint8Array(await window.__rotateFlipResult.blob.arrayBuffer())],
      }));
      expect(saved.name).toBe('orientation-rotated.png');
      expect(saved.type).toBe('image/png');
      expect(Buffer.from(saved.bytes).subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));

      const lateResponse = page.waitForResponse(response => response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/image-renditions' && response.status() === latePreview.status);
      finishPreview();
      expect((await lateResponse).status()).toBe(latePreview.status);
      await expect(status).toHaveText('Saved. Your original is unchanged.');
      if (latePreview.status === 200) await expect(page.locator('#tab-image-tools [data-role=preview]')).toHaveAttribute('src', /^blob:/);
      const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
        buttons.filter(button => !button.matches('[role=tab],.link,.ok-text-link')).length,
      );
      expect(actionButtonCount).toBeLessThanOrEqual(3);
      await page.screenshot({ path: path.join(evidence, `image_rotate_flip-current-source-saved-after-late-${latePreview.name}-${testInfo.project.name}-20261103.png`), fullPage: true });
    } finally {
      finishPreview();
      await page.unroute('**/api/image-renditions');
    }
  });
}
