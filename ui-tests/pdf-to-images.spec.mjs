import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

async function clickPdfOutputDownload(page) {
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
}

test('converts selected PDF pages to JPEG and recovers safely from invalid PDFs', async ({ context, page }) => {
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: {
        ...route.request().headers(),
        authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        origin: 'tauri://localhost',
      },
    });
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('PDF to JPEG');
  await expect(page.locator('#tool-gallery-results')).toContainText('PDF Pages to PNG / JPEG');
  await page.locator('#tool-gallery-results [data-open-tool="pdf_to_images"]').click();
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="images"]')).toBeVisible();

  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'sample-pages.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await page.locator('#pdf-image-format').selectOption('jpeg');
  await page.locator('#pdf-image-dpi').selectOption('300');
  await page.locator('#pdf-image-quality').fill('82');
  const responseReady = page.waitForResponse(response => response.url().includes('/api/pdf/images'));
  await page.locator('#pdf-workbench-run').click();
  const response = await responseReady;
  expect(response.status()).toBe(200);
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('1 pages');
  await expect.poll(() => page.evaluate(() => {
    const preview = document.getElementById('pdf-workbench-preview');
    const dock = document.getElementById('officekit-tool-actions');
    return dock.getBoundingClientRect().top - preview.getBoundingClientRect().bottom;
  })).toBeGreaterThanOrEqual(8);

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('sample-pages_pages.zip');
  const archive = await fs.readFile(await download.path());
  expect(archive.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(archive.includes(Buffer.from('page-001.jpg'))).toBe(true);
  expect(await fs.readFile(sourcePath)).toEqual(source);

  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('PDF to JPEG');
  await page.locator('#tool-gallery-results [data-open-tool="pdf_to_images"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF document'),
  });
  const failedResponseReady = page.waitForResponse(response => response.url().includes('/api/pdf/images'));
  await page.locator('#pdf-workbench-run').click();
  const failedResponse = await failedResponseReady;
  expect(failedResponse.status()).toBe(422);
  await expect(page.locator('#pdf-workbench-status')).toContainText('The PDF file is invalid or the requested operation is unsupported.');
  await expect(page.locator('#pdf-workbench-download')).toBeHidden();
});
