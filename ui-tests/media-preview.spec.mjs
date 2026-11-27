import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const selectionId = '53535353-5353-4353-8353-535353535353';
const id = digit => `${digit}${digit}${digit}${digit}${digit}${digit}${digit}${digit}-${digit}${digit}${digit}${digit}-4${digit}${digit}${digit}-8${digit}${digit}${digit}-${String(digit).repeat(12)}`;
const ids = { heic: id(4), png: id(5), jxl: id(6), mp4: id(7), m4a: id(8), pdf: id(9), locked: id(1), notes: id(2) };
const capability = (operationId, formats) => ({ id: operationId, label: operationId, available: true, formats, reason: null });
// A 1x1 transparent PNG.
const pixel = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

async function openToolkit(page, files, previewRoute) {
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__TAURI__ = { core: { invoke: async (command) => (command === 'file_selection_open' ? { id: selectionId } : null) }, event: { listen: async () => () => {} } };
  }, { selectionId });
  await page.route('**/api/media-capabilities', route => route.fulfill({ json: { version: 1, maxInputBytes: 67108864, maxBatchItems: 30, media: [
    { id: 'image', label: 'Images', operations: [capability('image-optimize', ['jpeg', 'webp'])] },
    { id: 'video', label: 'Video', operations: [capability('video-optimize', ['mp4'])] },
    { id: 'pdf', label: 'PDF', operations: [capability('pdf-lossless-compress', ['pdf'])] },
    { id: 'audio', label: 'Audio', operations: [capability('audio-optimize', ['m4a'])] },
  ] } }));
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: { id: selectionId, access: 'read', hasMore: false, files } }));
  await page.route('**/api/media-previews/**', previewRoute);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [] }));
  await page.route('**/api/media-operation-defaults', route => route.fulfill({ json: {} }));
  await page.route('**/api/media-folder-watches', route => route.fulfill({ json: [] }));
  await page.goto('/'); await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-select').click();
}

const fileEntries = [
  { id: ids.heic, name: 'IMG_7469.HEIC', size_bytes: 2400000 },
  { id: ids.png, name: 'beach.png', size_bytes: 830000 },
  { id: ids.jxl, name: 'scan.jxl', size_bytes: 1100000 },
];

test('selected images show a thumbnail, pixel size and a larger preview; unsupported ones show a type tile', async ({ page }) => {
  const requested = [];
  await openToolkit(page, fileEntries, route => {
    const url = new URL(route.request().url());
    const fileId = url.pathname.split('/').pop();
    requested.push(`${fileId}?${url.searchParams.get('size')}`);
    if (fileId === ids.jxl) return route.fulfill({ status: 415, json: { detail: 'No preview is available for this file type.' } });
    const [width, height] = fileId === ids.heic ? [4032, 3024] : [1920, 1080];
    return route.fulfill({ json: { kind: 'image', width, height, contentType: 'image/png', dataBase64: pixel } });
  });

  const list = page.locator('#media-toolkit-file-list');
  await expect(list).toContainText('2.29 MiB · 4032 × 3024 px');
  await expect(list).toContainText('0.79 MiB · 1920 × 1080 px');
  await expect(list).toContainText('1.05 MiB · preview unavailable');
  await expect(list.locator('[data-preview-kind="image"][data-preview-status="none"]')).toContainText('JXL');
  await expect(list.locator('img')).toHaveCount(2);

  const preview = page.locator('#media-toolkit-preview');
  await expect(preview).toBeVisible();
  await expect(preview).toContainText('IMG_7469.HEIC · 4032 × 3024 px');
  await expect(preview).toContainText('Preview only; the original is not changed');
  await expect(preview.getByRole('img', { name: 'Preview of IMG_7469.HEIC' })).toBeVisible();

  await page.getByRole('button', { name: 'Settings for beach.png', exact: true }).click();
  await expect(preview).toContainText('beach.png · 1920 × 1080 px');

  // A file without a preview hides the large panel; the file stays selected and can still be prepared.
  await page.getByRole('button', { name: 'Settings for scan.jxl', exact: true }).click();
  await expect(preview).toBeHidden();
  await expect(page.getByLabel('Prepare scan.jxl')).toBeChecked();

  // Thumbnails (128) and the large preview (512) are each fetched once, never on every redraw.
  expect(requested.filter(entry => entry === `${ids.heic}?128`)).toHaveLength(1);
  expect(requested.filter(entry => entry === `${ids.heic}?512`)).toHaveLength(1);
  expect(requested.every(entry => /\?(128|512)$/.test(entry))).toBe(true);
});

test('video, audio and PDF rows get previews, locked and unknown files get a type tile', async ({ page }) => {
  const requested = [];
  await openToolkit(page, [
    { id: ids.mp4, name: 'holiday.mp4', size_bytes: 50500000 },
    { id: ids.m4a, name: 'interview.m4a', size_bytes: 6700000 },
    { id: ids.pdf, name: 'invoice.pdf', size_bytes: 1150000 },
    { id: ids.locked, name: 'secret.pdf', size_bytes: 90000 },
    { id: ids.notes, name: 'notes.xyz', size_bytes: 1000 },
  ], route => {
    const url = new URL(route.request().url());
    const fileId = url.pathname.split('/').pop();
    requested.push(`${fileId}?${url.searchParams.toString()}`);
    if (fileId === ids.locked) return route.fulfill({ json: { kind: 'pdf', locked: true } });
    if (fileId === ids.mp4) return route.fulfill({ json: { kind: 'video', width: 1920, height: 1080, durationSeconds: 84.4, contentType: 'image/png', dataBase64: pixel } });
    if (fileId === ids.m4a) return route.fulfill({ json: { kind: 'audio', durationSeconds: 728.2, peaks: [10, 60, 100, 40, 80, 20] } });
    return route.fulfill({ json: { kind: 'pdf', width: 595, height: 842, contentType: 'image/png', dataBase64: pixel, pageCount: 3, page: Number(url.searchParams.get('page')) } });
  });

  const list = page.locator('#media-toolkit-file-list');
  await expect(list).toContainText('48.16 MiB · 1920 × 1080 · 1:24');
  await expect(list).toContainText('6.39 MiB · 12:08');
  await expect(list).toContainText('1.10 MiB · 3 pages');
  await expect(list).toContainText('0.09 MiB · password protected');
  await expect(list.locator('[data-preview-kind="video"] img')).toHaveCount(1);
  await expect(list.locator('[data-preview-kind="audio"] i')).toHaveCount(6);
  await expect(list.locator('[data-preview-kind="pdf"][data-preview-status="locked"]')).toContainText('LOCKED');
  await expect(list.locator('[data-preview-kind="other"]')).toContainText('XYZ');
  // A file of an unknown type never asks the sidecar for a picture.
  expect(requested.some(entry => entry.startsWith(ids.notes))).toBe(false);

  const preview = page.locator('#media-toolkit-preview');
  await expect(preview).toContainText('holiday.mp4 · 1920 × 1080 · 1:24');
  await page.getByRole('button', { name: 'Settings for invoice.pdf', exact: true }).click();
  await expect(preview).toContainText('invoice.pdf · 3 pages');
  await expect(preview).toContainText('1 / 3');
  await preview.getByRole('button', { name: 'Next page' }).click();
  await expect(preview).toContainText('2 / 3');
  expect(requested.some(entry => entry.startsWith(ids.pdf) && entry.includes('page=2') && entry.includes('size=512'))).toBe(true);
  await page.getByRole('button', { name: 'Settings for interview.m4a', exact: true }).click();
  await expect(preview).toContainText('interview.m4a · 12:08');
});

test('the expanded viewer zooms, steps through files, pages a PDF and closes with Escape', async ({ page }) => {
  const requested = [];
  await openToolkit(page, [
    { id: ids.png, name: 'beach.png', size_bytes: 830000 },
    { id: ids.pdf, name: 'invoice.pdf', size_bytes: 1150000 },
    { id: ids.mp4, name: 'holiday.mp4', size_bytes: 50500000 },
  ], route => {
    const url = new URL(route.request().url());
    const fileId = url.pathname.split('/').pop();
    requested.push(`${fileId}?${url.searchParams.toString()}`);
    if (fileId === ids.mp4) return route.fulfill({ json: { kind: 'video', width: 1920, height: 1080, durationSeconds: 84.4, contentType: 'image/png', dataBase64: pixel } });
    if (fileId === ids.pdf) return route.fulfill({ json: { kind: 'pdf', width: 595, height: 842, contentType: 'image/png', dataBase64: pixel, pageCount: 3, page: Number(url.searchParams.get('page')) } });
    return route.fulfill({ json: { kind: 'image', width: 4032, height: 3024, contentType: 'image/png', dataBase64: pixel } });
  });

  await expect(page.locator('#media-toolkit-preview')).toBeVisible();
  // WebKit does not focus a button on click, so focus it first to check that focus comes back after closing.
  await page.getByRole('button', { name: 'Expand preview of beach.png' }).focus();
  await page.keyboard.press('Enter');
  const viewer = page.getByRole('dialog', { name: 'Preview viewer' });
  await expect(viewer).toBeVisible();
  await expect(viewer).toContainText('beach.png');
  await expect(viewer).toContainText('4032 × 3024 px · 1 of 3');
  expect(requested.some(entry => entry.startsWith(ids.png) && entry.includes('size=2048'))).toBe(true);
  await expect(viewer.getByText('Reduced copy of the original')).toBeVisible();

  // Zoom: 100% is the actual pixels of the copy, + and − change it, Fit returns.
  await viewer.getByRole('button', { name: 'Actual size (100%)' }).click();
  await expect(viewer).toContainText('100%');
  await viewer.getByRole('button', { name: 'Zoom in' }).click();
  await expect(viewer).toContainText('125%');
  await page.keyboard.press('-');
  await expect(viewer).toContainText('100%');
  await page.keyboard.press('0');
  await expect(viewer).not.toContainText('125%');

  // Files: arrows step through, wrapping round; a PDF shows page controls and no frame slider.
  await page.keyboard.press('ArrowRight');
  await expect(viewer).toContainText('invoice.pdf');
  await expect(viewer).toContainText('3 pages · 2 of 3');
  await viewer.getByRole('button', { name: 'Next page' }).click();
  await expect(viewer.getByText('2 / 3')).toBeVisible();
  await page.keyboard.press('PageDown');
  await expect(viewer.getByText('3 / 3')).toBeVisible();
  expect(requested.some(entry => entry.startsWith(ids.pdf) && entry.includes('page=3') && entry.includes('size=2048'))).toBe(true);
  await expect(viewer.getByRole('button', { name: 'Zoom in' })).toBeVisible();

  // A video has a frame slider instead of zoom, and asks for the chosen position.
  await page.keyboard.press('ArrowRight');
  await expect(viewer).toContainText('holiday.mp4');
  await expect(viewer.getByRole('button', { name: 'Zoom in' })).toBeHidden();
  await viewer.getByLabel('Frame position').fill('60');
  await expect.poll(() => requested.some(entry => entry.startsWith(ids.mp4) && entry.includes('position=60') && entry.includes('size=2048'))).toBe(true);
  await page.keyboard.press('ArrowLeft');
  await expect(viewer).toContainText('invoice.pdf');

  // Full screen falls back to a window-filling layout and Escape leaves it before closing the viewer.
  await viewer.getByRole('button', { name: 'Full screen' }).click();
  await expect(viewer.getByRole('button', { name: 'Exit full screen' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(viewer.getByRole('button', { name: 'Full screen' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(viewer).toBeHidden();
  await expect(page.getByRole('button', { name: 'Expand preview of beach.png' })).toBeFocused();
});

test('double-clicking a thumbnail opens the viewer, and clicking outside closes it', async ({ page }) => {
  await openToolkit(page, fileEntries.slice(0, 2), route => route.fulfill({ json: { kind: 'image', width: 800, height: 600, contentType: 'image/png', dataBase64: pixel } }));
  await expect(page.locator('#media-toolkit-file-list img')).toHaveCount(2);
  await page.locator('#media-toolkit-file-list [data-preview-kind="image"]').nth(1).dblclick();
  const viewer = page.getByRole('dialog', { name: 'Preview viewer' });
  await expect(viewer).toContainText('beach.png');
  await page.mouse.click(4, 4);
  await expect(viewer).toBeHidden();
});
