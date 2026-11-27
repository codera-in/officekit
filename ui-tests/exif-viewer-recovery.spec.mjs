import { test, expect } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

test('EXIF Viewer keeps correctable image errors local and restores the complete report after replacement', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  await page.getByRole('button', { name: 'All Tools', exact: true }).click();
  await page.locator('#tool-gallery-results [data-open-tool="image_exif_view"]').click();

  const input = page.locator('#tab-image-tools input[type=file][data-slot=file]');
  const exif = page.locator('#tab-image-tools [data-role=exif]');
  const validImage = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 3;
    canvas.height = 2;
    canvas.getContext('2d').fillRect(0, 0, 3, 2);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const validFile = { name: 'metadata-sample.png', mimeType: 'image/png', buffer: Buffer.from(validImage, 'base64') };

  await input.setInputFiles(validFile);
  await expect(exif).toContainText('PNG · 3 × 2 px');
  await expect(exif.locator('[data-action=copy]')).toHaveCount(1);
  await page.evaluate(() => {
    window.__officekitTestClipboard = '';
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => { window.__officekitTestClipboard = value; } } });
  });
  await exif.locator('[data-action=copy]').click();
  const copied = await page.evaluate(() => window.__officekitTestClipboard);
  expect(copied.split('\n')).toHaveLength(16);
  expect(copied).toContain('Make: missing');
  expect(copied).not.toContain('Location:');

  await input.setInputFiles({ name: 'broken.png', mimeType: 'image/png', buffer: Buffer.from('not an image') });
  const alert = exif.locator('[role=alert]');
  await expect(alert).toHaveText('The image file is invalid or cannot be decoded.');
  await expect(alert).toHaveAttribute('data-officekit-no-bug-report', '');
  await expect(exif.locator('.officekit-bug-report-cta')).toHaveCount(0);
  await expect(exif.locator('[data-action=copy]')).toHaveCount(0);
  await expect(exif.locator('table')).toHaveCount(0);
  await expect(exif.locator('.ok-action-dock')).toBeVisible();

  await input.setInputFiles(validFile);
  await expect(exif).toContainText('PNG · 3 × 2 px');
  await expect(exif.locator('[data-action=copy]')).toHaveCount(1);
  await expect(exif.locator('[role=alert]')).toHaveCount(0);
});
