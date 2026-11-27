import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

async function clickPdfOutputDownload(page) {
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
}

test('exposes lossless PDF compression and creates a measurable local output', async ({ context, page }) => {
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
  await page.locator('#tool-gallery-search').fill('Compress PDF');
  await expect(page.locator('#tool-gallery-results')).toContainText('Compress PDF');
  await page.locator('#tool-gallery-results [data-open-tool="pdf_compress"]').click();
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="compress"]')).toBeVisible();

  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'sample-source.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await expect(page.locator('#pdf-compression-preset')).toHaveValue('fast');
  const responseReady = page.waitForResponse(response => response.url().includes('/api/pdf/compress'));
  await page.locator('#pdf-workbench-run').click();
  const response = await responseReady;
  expect(response.status()).toBe(200);
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('sample-source_compressed.pdf');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  const ratio = Number(response.headers()['x-officekit-output-input-ratio']);
  expect(Number.isFinite(ratio) && ratio > 0 && ratio <= 1000).toBe(true);
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText(`${(ratio * 100).toFixed(1)}% of source`);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});
