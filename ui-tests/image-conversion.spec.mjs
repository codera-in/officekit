import { test, expect } from '@playwright/test';
import { expectGalleryMatchesCatalog } from './gallery-count.mjs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

let externalRequests;
let pageErrors;

test.beforeEach(async ({ context, page }) => {
  externalRequests = [];
  pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const request = route.request();
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...request.headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expectGalleryMatchesCatalog(page, expect);
});

test.afterEach(() => {
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

function jpegHasExifApp1(bytes) {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return false;
  let offset = 2;
  while (offset + 4 <= bytes.length) {
    if (bytes[offset] !== 0xff) return false;
    while (bytes[offset] === 0xff) offset += 1;
    const marker = bytes[offset++];
    if (marker === 0xda || marker === 0xd9) return false;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (offset + 2 > bytes.length) return false;
    const segmentLength = bytes.readUInt16BE(offset);
    if (segmentLength < 2 || offset + segmentLength > bytes.length) return false;
    if (marker === 0xe1 && bytes.subarray(offset + 2, offset + 8).equals(Buffer.from('Exif\0\0', 'binary'))) return true;
    offset += segmentLength;
  }
  return false;
}

function addMinimalExifApp1(jpeg) {
  const tiff = Buffer.from([0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]);
  const payload = Buffer.concat([Buffer.from('Exif\0\0', 'binary'), tiff]);
  const length = Buffer.alloc(2);
  length.writeUInt16BE(payload.length + 2);
  const segment = Buffer.concat([Buffer.from([0xff, 0xe1]), length, payload]);
  return Buffer.concat([jpeg.subarray(0, 2), segment, jpeg.subarray(2)]);
}

test('image converter creates a real WebP download from a selected local image', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/similar-images/cc0/dandelion.jpg');
  const original = await fs.readFile(sourcePath);

  await page.locator('#tool-gallery-search').fill('Image Converter');
  await page.locator('[data-open-tool="image_converter"]').click();
  await expect(page.locator('#tab-converter')).toBeVisible();
  await expect(page.locator('#developer-tools-action-dock')).toBeHidden();

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles(sourcePath);
  await expect(page.locator('#converter-status')).toContainText('Image ·');
  await expect(page.locator('#converter-image-preview-panel')).toBeVisible();
  await expect(page.locator('#converter-image-preview')).toHaveAttribute('alt', 'Preview of dandelion.jpg');
  await expect.poll(() => page.locator('#converter-image-preview').evaluate(image => image.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('#converter-image-preview-caption')).toContainText('dandelion.jpg ·');
  await page.locator('#format-options button', { hasText: /^webp$/i }).click();

  const actionDock = page.locator('#converter-action-dock');
  await expect(actionDock).toHaveCSS('position', 'fixed');
  await expect(page.locator('#convert-btn').locator('xpath=..')).toHaveAttribute('id', 'converter-action-controls');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
  const dockDimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    dock: document.getElementById('converter-action-dock').getBoundingClientRect().width,
    button: document.getElementById('convert-btn').getBoundingClientRect(),
  }));
  expect(dockDimensions.page).toBeLessThanOrEqual(dockDimensions.viewport);
  expect(dockDimensions.dock).toBeLessThanOrEqual(dockDimensions.viewport);
  expect(dockDimensions.button.height).toBeGreaterThanOrEqual(44);
  expect(dockDimensions.button.right).toBeLessThanOrEqual(dockDimensions.viewport);

  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  await expect(page.locator('#convert-btn')).toBeHidden();
  const downloadReady = page.waitForEvent('download');
  await expect(page.locator('#converter-action-controls .officekit-result-actions')).toHaveCSS('position', 'static');
  await expect(page.locator('#converter-action-controls .officekit-result-actions').getByRole('button', { name: 'Copy summary', exact: true })).toBeVisible();
  await page.locator('#converter-action-controls .officekit-result-actions').getByRole('button', { name: 'Download' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('dandelion.webp');
  const output = await fs.readFile(await download.path());
  expect(output.length).toBeGreaterThan(12);
  expect(output.subarray(0, 4).toString('ascii')).toBe('RIFF');
  expect(output.subarray(8, 12).toString('ascii')).toBe('WEBP');
  expect(await fs.readFile(sourcePath)).toEqual(original);
  await expect(page.locator('.officekit-result-action-status')).toContainText('Download started: dandelion.webp.');

  await page.locator('#format-options button', { hasText: /^png$/i }).click();
  await expect(page.locator('#convert-btn')).toBeVisible();
  await expect(page.locator('#convert-btn')).toBeEnabled();
  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  await expect(page.locator('#convert-btn')).toBeHidden();
  const pngDownloadReady = page.waitForEvent('download');
  await page.locator('#converter-action-controls .officekit-result-actions').getByRole('button', { name: 'Download' }).click();
  const pngDownload = await pngDownloadReady;
  expect(pngDownload.suggestedFilename()).toBe('dandelion.png');
});

test('image converter rasterizes a local SVG and converts it to the selected PNG target', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/image-converter/simple.svg');
  await page.locator('#tool-gallery-search').fill('Image Converter');
  await page.locator('[data-open-tool="image_converter"]').click();
  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles(sourcePath);

  await expect(page.locator('#format-selection')).toBeVisible();
  await expect(page.locator('#converter-image-preview-panel')).toBeVisible();
  await expect(page.locator('#converter-image-preview')).toHaveAttribute('alt', 'Preview of simple.svg');
  await expect.poll(() => page.locator('#converter-image-preview').evaluate(image => image.naturalWidth)).toBe(32);
  await expect(page.locator('#converter-image-preview-caption')).toContainText('simple.svg · 32 × 24 px');
  await expect(page.locator('#svg-conversion-note')).toBeVisible();
  await expect(page.locator('#format-options button')).toHaveCount(7);
  for (const [label, extension, signature] of [
    ['PNG', 'png', Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])],
    ['JPEG', 'jpg', Buffer.from([0xff, 0xd8])],
    ['WEBP', 'webp', Buffer.from('RIFF')],
    ['BMP', 'bmp', Buffer.from('BM')],
    ['ICO', 'ico', Buffer.from([0, 0, 1, 0])],
    ['TIFF', 'tiff', Buffer.from('II*\0')],
    ['PDF', 'pdf', Buffer.from('%PDF-')],
  ]) {
    await page.locator('#format-options button', { hasText: new RegExp(`^${label}$`, 'i') }).click();
    await expect(page.locator('#converter-image-preview-panel')).toBeVisible();
    await expect(page.locator('#format-options button[aria-pressed="true"]')).toHaveText(label);
    await expect(page.locator('#convert-btn')).toHaveText(`Convert to ${label}`);
    await page.locator('#convert-btn').click();
    await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
    const downloadReady = page.waitForEvent('download');
    await page.locator('#converter-action-controls .officekit-result-actions').getByRole('button', { name: 'Download' }).click();
    const download = await downloadReady;
    expect(download.suggestedFilename()).toBe(`simple.${extension}`);
    const output = await fs.readFile(await download.path());
    expect(output.subarray(0, signature.length)).toEqual(signature);
    if (label === 'WEBP') expect(output.subarray(8, 12).toString('ascii')).toBe('WEBP');
    expect(output.length).toBeGreaterThan(signature.length);
  }
});

test('image converter explains alpha loss for JPEG and BMP and hides the note for WebP', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-transparent-convert-'));
  const sourcePath = path.join(root, 'transparent.png');
  await fs.writeFile(sourcePath, Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABSK+kcQAAAABJRU5ErkJggg==',
    'base64',
  ));
  try {
    await page.locator('#tool-gallery-search').fill('Image Converter');
    await page.locator('[data-open-tool="image_converter"]').click();
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#generic-file-select-button').click();
    await (await chooser).setFiles(sourcePath);

    const notice = page.locator('#image-transparency-notice');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('composites them onto white');
    await page.locator('#format-options button', { hasText: /^bmp$/i }).click();
    await expect(notice).toBeVisible();
    await page.locator('#format-options button', { hasText: /^webp$/i }).click();
    await expect(notice).toBeHidden();
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('image converter reports malformed image input and restores the conversion control', async ({ page }) => {
  await page.locator('#tool-gallery-search').fill('Image Converter');
  await page.locator('[data-open-tool="image_converter"]').click();

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles({
    name: 'broken.png',
    mimeType: 'image/png',
    buffer: Buffer.from('not a PNG image'),
  });
  await expect(page.locator('#converter-status')).toContainText('Image ·');
  await page.locator('#format-options button', { hasText: /^webp$/i }).click();
  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText(
    'The file or requested format cannot be converted. Check the input and try again.',
  );
  await expect(page.locator('#convert-btn')).toBeEnabled();
});

test('image converter opens the shared converter screen, which accepts tabular files too', async ({ page }) => {
  await page.locator('#tool-gallery-search').fill('Image Converter');
  await page.locator('[data-open-tool="image_converter"]').click();
  await expect(page.locator('#generic-converter-panel')).toBeVisible();
  const csv = Buffer.from('name,amount\nTea,3\n');
  await page.locator('#generic-file-input').setInputFiles({ name: 'inventory.csv', mimeType: 'text/csv', buffer: csv });
  await expect(page.locator('#format-selection')).toBeVisible();
});

test('image resize sends a selected batch and downloads its ZIP while retaining the input', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/similar-images/cc0/dandelion.jpg');
  const source = await fs.readFile(sourcePath);
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-resize-batch-'));
  const first = path.join(root, 'dandelion.jpg');
  const second = path.join(root, 'dandelion-copy.jpg');
  await fs.copyFile(sourcePath, first);
  await fs.copyFile(sourcePath, second);
  try {
    await page.locator('#tool-gallery-search').fill('Resize Images');
    await page.locator('[data-open-tool="image_resize"]').click();
    await expect(page.locator('#image-resize-panel')).toBeVisible();
    await expect(page.locator('#image-resize-action-dock')).toHaveCSS('position', 'fixed');
    await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
    await expect(page.locator('#image-resize-run')).toHaveCSS('min-height', '44px');
    await page.setViewportSize({ width: 1280, height: 900 });
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#image-resize-input').click();
    // WebKit can transfer in-memory filechooser buffers as zero-byte files; stage fixtures on disk.
    await (await chooser).setFiles([first, second]);
    await expect(page.locator('#image-resize-selection')).toContainText('2 image(s)');
    await page.locator('#image-resize-width').fill('640');
    await page.locator('#image-resize-height').fill('640');
    await page.locator('#image-resize-run').click();
    await expect(page.locator('#image-resize-status')).toHaveText('2 images resized. Download the ZIP before clearing.');
    await expect(page.locator('#image-resize-run')).toBeHidden();
    await expect(page.locator('#image-resize-action-dock .officekit-result-actions')).toBeVisible();

    const downloadReady = page.waitForEvent('download');
    await page.locator('#image-resize-action-dock .officekit-result-actions').getByRole('button', { name: 'Download' }).click();
    const download = await downloadReady;
    expect(download.suggestedFilename()).toBe('resized_images.zip');
    const output = await fs.readFile(await download.path());
    expect(output.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
    expect(output.subarray(-22, -18)).toEqual(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
    expect(await fs.readFile(sourcePath)).toEqual(source);

    await page.locator('#image-resize-clear').click();
    await expect(page.locator('#image-resize-status')).toContainText('Your originals remain unchanged.');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('image resize explains a server batch-work limit and lets the user retry', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/similar-images/cc0/dandelion.jpg');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-resize-limit-'));
  const secondPath = path.join(root, 'dandelion-copy.jpg');
  await fs.copyFile(sourcePath, secondPath);
  const message = 'The image batch requires too much processing; select fewer or smaller images.';
  await page.route('http://127.0.0.1:19874/api/images/resize', route => route.fulfill({
    status: 413,
    contentType: 'application/json',
    body: JSON.stringify({ detail: message }),
  }));
  try {
    await page.locator('#tool-gallery-search').fill('Resize Images');
    await page.locator('[data-open-tool="image_resize"]').click();
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#image-resize-input').click();
    await (await chooser).setFiles([sourcePath, secondPath]);
    await page.locator('#image-resize-run').click();
    await expect(page.locator('#image-resize-status')).toContainText(message);
    await expect(page.locator('#image-resize-status .ok-outcome__recovery')).toHaveText('Check your files and try again.');
    await expect(page.locator('#image-resize-run')).toBeEnabled();
    await expect(page.locator('#image-resize-download')).toBeHidden();
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('single image resize reads output dimensions from the real API and downloads the image', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/similar-images/cc0/dandelion.jpg');
  const source = await fs.readFile(sourcePath);

  await page.locator('#tool-gallery-search').fill('Resize Images');
  await page.locator('[data-open-tool="image_resize"]').click();
  const chooser = page.waitForEvent('filechooser');
  await page.locator('#image-resize-input').click();
  await (await chooser).setFiles(sourcePath);
  await page.locator('#image-resize-width').fill('640');
  await page.locator('#image-resize-height').fill('640');
  await page.locator('#image-resize-run').click();
  await expect(page.locator('#image-resize-status')).toContainText(/dandelion_resized\.jpg · \d+ × \d+ pixels/);
  await expect(page.locator('#image-resize-run')).toBeHidden();

  const downloadReady = page.waitForEvent('download');
  await page.locator('#image-resize-action-dock .officekit-result-actions').getByRole('button', { name: 'Download' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('dandelion_resized.jpg');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff]));
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('EXIF cleanup returns a verified image copy and clears transient state', async ({ page }) => {
  const fixturePath = path.resolve('tests/fixtures/similar-images/cc0/dandelion.jpg');
  const source = addMinimalExifApp1(await fs.readFile(fixturePath));
  const tempDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-exif-ui-'));
  const sourcePath = path.join(tempDirectory, 'dandelion.jpg');
  await fs.writeFile(sourcePath, source);
  try {
    expect(jpegHasExifApp1(source)).toBe(true);
    await page.locator('#tool-gallery-search').fill('Remove Image Metadata');
    await page.locator('[data-open-tool="image_exif_strip"]').click();
    await expect(page.locator('#image-metadata-panel')).toBeVisible();
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#image-metadata-input').click();
    await (await chooser).setFiles(sourcePath);
    await expect(page.locator('#image-metadata-selected')).toContainText('dandelion.jpg');
    await page.locator('#image-metadata-run').click();
    await expect(page.locator('#image-metadata-status')).toContainText('Clean copy ready: dandelion_metadata_removed.jpg');
    await expect(page.locator('#image-metadata-status')).toContainText('Original file remains unchanged.');

    const downloadReady = page.waitForEvent('download');
    await page.locator('#image-metadata-status').locator('xpath=..').locator('.officekit-result-actions').getByRole('button', { name: 'Download' }).click();
    const download = await downloadReady;
    expect(download.suggestedFilename()).toBe('dandelion_metadata_removed.jpg');
    const output = await fs.readFile(await download.path());
    expect(output.length).toBeGreaterThan(3);
    expect(output.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff]));
    expect(jpegHasExifApp1(output)).toBe(false);
    expect(await fs.readFile(sourcePath)).toEqual(source);

    await page.locator('#image-metadata-clear').click();
    await expect(page.locator('#image-metadata-status')).toHaveText('No account or network connection required. Image content is not saved in History.');
    await expect(page.locator('#image-metadata-download')).toBeHidden();
  } finally {
    await fs.rm(tempDirectory, { recursive: true, force: true });
  }
});
