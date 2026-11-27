import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { inflateRawSync } from 'node:zlib';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');

function unzipEntries(buffer) {
  const entries = new Map();
  let offset = 0;
  while (offset + 30 <= buffer.length && buffer.readUInt32LE(offset) === 0x04034b50) {
    const method = buffer.readUInt16LE(offset + 8);
    const compressedSize = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const dataStart = offset + 30;
    const name = buffer.toString('utf8', dataStart, dataStart + nameLength);
    const payloadStart = dataStart + nameLength + extraLength;
    const compressed = buffer.subarray(payloadStart, payloadStart + compressedSize);
    entries.set(name, method === 8 ? inflateRawSync(compressed) : compressed);
    offset = payloadStart + compressedSize;
  }
  return entries;
}

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
});

test('Contact Sheet paginates four images and validates PDF and PNG ZIP exports', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_contact_sheet"]').click();
  const previewAction = page.locator('#tab-image-tools [data-action=preview]');
  const saveAction = page.locator('#tab-image-tools [data-action=save]');
  await expect(previewAction).toBeDisabled();
  await expect(saveAction).toBeDisabled();
  await page.screenshot({ path: path.join(evidence, `image_contact_sheet-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });

  const colors = ['#ffaa00', '#0055cc', '#008844', '#993366'];
  const encoded = await page.evaluate(palette => palette.map(color => {
    const canvas = document.createElement('canvas');
    canvas.width = 8;
    canvas.height = 8;
    const context = canvas.getContext('2d');
    context.fillStyle = color;
    context.fillRect(0, 0, 8, 8);
    return canvas.toDataURL('image/png').split(',')[1];
  }), colors);
  await page.locator('#tab-image-tools input[type=file][data-slot=files]').setInputFiles(encoded.map((data, index) => ({
    name: `sheet-${index + 1}.png`, mimeType: 'image/png', buffer: Buffer.from(data, 'base64'),
  })));
  await page.locator('#tab-image-tools [data-param=page]').selectOption('letter');
  await page.locator('#tab-image-tools [data-param=orientation]').selectOption('landscape');
  await page.locator('#tab-image-tools [data-param=columns]').fill('2');
  await page.locator('#tab-image-tools [data-param=rows]').fill('1');
  await expect(page.locator('#tab-image-tools [data-role=canvas-size]')).toHaveText('2 pages · 2 per page');
  await expect(previewAction).toBeEnabled();
  await expect(saveAction).toBeEnabled();
  await page.screenshot({ path: path.join(evidence, `image_contact_sheet-current-source-ready-${testInfo.project.name}-20261103.png`), fullPage: true });

  const previewResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/contact-sheets');
  await previewAction.click();
  const preview = await previewResponse;
  expect(preview.status()).toBe(200);
  expect(preview.headers()['x-officekit-page-count']).toBe('2');
  const image = page.locator('#tab-image-tools [data-role=ordered-img]');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate(node => node.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Preview updated.');
  await page.screenshot({ path: path.join(evidence, `image_contact_sheet-current-source-preview-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.evaluate(() => {
    window.officekitDownloadResultBlob = async (blob, name) => {
      window.__contactSheetResult = { blob, name };
      return { state: 'saved' };
    };
  });
  const pdfResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/contact-sheets');
  await saveAction.click();
  expect((await pdfResponse).status()).toBe(200);
  const pdf = await page.evaluate(async () => ({
    name: window.__contactSheetResult.name,
    type: window.__contactSheetResult.blob.type,
    bytes: [...new Uint8Array(await window.__contactSheetResult.blob.arrayBuffer())],
  }));
  const pdfBytes = Buffer.from(pdf.bytes);
  expect(pdf.name).toBe('contact-sheet.pdf');
  expect(pdf.type).toBe('application/pdf');
  expect(pdfBytes.subarray(0, 5).toString()).toBe('%PDF-');
  expect((pdfBytes.toString('latin1').match(/\/Type\s*\/Page\b/g) || []).length).toBe(2);
  await expect(page.locator('#tab-image-tools .ok-action-dock__status')).toHaveText('Saved. Your originals are unchanged.');
  await page.screenshot({ path: path.join(evidence, `image_contact_sheet-current-source-pdf-${testInfo.project.name}-20261103.png`), fullPage: true });

  await page.locator('#tab-image-tools [data-param=format]').selectOption('png-zip');
  await expect(saveAction).toHaveText('Save ZIP');
  const zipResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/contact-sheets');
  await saveAction.click();
  expect((await zipResponse).status()).toBe(200);
  const zip = await page.evaluate(async () => ({
    name: window.__contactSheetResult.name,
    type: window.__contactSheetResult.blob.type,
    bytes: [...new Uint8Array(await window.__contactSheetResult.blob.arrayBuffer())],
  }));
  expect(zip.name).toBe('contact-sheet.zip');
  expect(zip.type).toBe('application/zip');
  const entries = unzipEntries(Buffer.from(zip.bytes));
  expect([...entries.keys()].sort()).toEqual(['contact-sheet-001.png', 'contact-sheet-002.png']);
  for (const png of entries.values()) expect(png.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link,.image-tools__moves button')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_contact_sheet-current-source-zip-${testInfo.project.name}-20261103.png`), fullPage: true });
});
