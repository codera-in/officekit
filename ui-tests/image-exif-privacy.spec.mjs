import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true });
  await routeAuthenticatedApi(page);
  let requestCount = 0;
  await page.route('**/api/image-metadata-reports', async route => {
    requestCount += 1;
    const includeLocation = requestCount === 2;
    const report = {
      format: 'JPEG',
      width: 6,
      height: 4,
      frames: 1,
      groups: [
        { group: 'date', tag: 'DateTimeOriginal', label: 'Capture time', value: '2024:05:01 12:34:56', status: 'present' },
        { group: 'camera', tag: 'Make', label: 'Camera', value: 'Canon', status: 'present' },
        { group: 'exposure', tag: 'FNumber', label: 'Aperture', value: '2.8', status: 'present' },
        { group: 'image', tag: 'ImageWidth', label: 'Image width', value: '6 px', status: 'present' },
      ],
      location: includeLocation
        ? { present: true, withheld: false, latitude: 37.7749167, longitude: -122.4195, altitude_m: 16 }
        : { present: true, withheld: true, latitude: null, longitude: null, altitude_m: null },
      has_icc: false,
      has_xmp: false,
      has_iptc: false,
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(report) });
  });
  await page.goto('/');
  await waitForAppReady(page);
});

test('EXIF Viewer hides GPS by default, allows explicit reveal and omits it again when hidden', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_exif_view"]').click();
  await page.screenshot({ path: path.join(evidence, `image_exif_view-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 6;
    canvas.height = 4;
    const context = canvas.getContext('2d');
    context.fillStyle = '#285078';
    context.fillRect(0, 0, 6, 4);
    return canvas.toDataURL('image/jpeg', 0.9).split(',')[1];
  });
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({
    name: 'gps-photo.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(base64, 'base64'),
  });

  const exif = page.locator('#tab-image-tools [data-role=exif]');
  await expect(exif).toContainText('Present, hidden');
  await expect(exif).toContainText('Canon');
  await expect(exif).not.toContainText('37.7749167');
  await expect(exif).not.toContainText('-122.4195');
  await page.screenshot({ path: path.join(evidence, `image_exif_view-current-source-location-hidden-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.evaluate(() => {
    window.__exifCopiedText = '';
    window.officekitCopyResultText = async value => { window.__exifCopiedText = value; };
  });
  await exif.getByRole('button', { name: 'Copy details' }).click();
  await expect.poll(() => page.evaluate(() => window.__exifCopiedText)).toBe(
    'Capture time: 2024:05:01 12:34:56\nCamera: Canon\nAperture: 2.8\nImage width: 6 px',
  );
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Details copied.');

  const show = exif.getByRole('button', { name: 'Show location' });
  await show.focus();
  await show.press('Enter');
  await expect(exif).toContainText('37.7749167, -122.4195');
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Location will be included in Copy.');
  await page.screenshot({ path: path.join(evidence, `image_exif_view-current-source-location-visible-${testInfo.project.name}-20261103.png`), fullPage: true });
  await exif.getByRole('button', { name: 'Copy details' }).click();
  await expect.poll(() => page.evaluate(() => window.__exifCopiedText)).toBe(
    'Capture time: 2024:05:01 12:34:56\nCamera: Canon\nAperture: 2.8\nImage width: 6 px\nLocation: 37.7749167, -122.4195',
  );

  const hide = exif.getByRole('button', { name: 'Hide' });
  await hide.focus();
  await hide.press('Enter');
  await expect(exif).toContainText('Present, hidden');
  await expect(exif).not.toContainText('37.7749167');
  await exif.getByRole('button', { name: 'Copy details' }).click();
  await expect.poll(() => page.evaluate(() => window.__exifCopiedText)).not.toContain('Location:');
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.ok-text-link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_exif_view-current-source-location-hidden-again-${testInfo.project.name}-20261103.png`), fullPage: true });
});
