import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

async function clickPdfOutputDownload(page) {
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
}

test('removes standard PDF metadata while retaining readable pages and the untouched source', async ({ context, page }) => {
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
  await page.locator('#tool-gallery-search').fill('Remove PDF metadata');
  await expect(page.locator('#tool-gallery-results')).toContainText('Remove PDF Metadata');
  await page.locator('#tool-gallery-results [data-open-tool="pdf_metadata_strip"]').click();
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="metadata"]')).toBeVisible();
  await expect(page.locator('#pdf-workbench-options')).toContainText('some embedded identifiers may remain');

  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'sample-private.pdf', mimeType: 'application/pdf', buffer: source,
  });
  const responseReady = page.waitForResponse(response => response.url().includes('/api/pdf/metadata'));
  await page.locator('#pdf-workbench-run').click();
  const response = await responseReady;
  expect(response.status()).toBe(200);
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect.poll(() => page.evaluate(() => {
    const preview = document.getElementById('pdf-workbench-preview');
    const dock = document.getElementById('officekit-tool-actions');
    return dock.getBoundingClientRect().top - preview.getBoundingClientRect().bottom;
  })).toBeGreaterThanOrEqual(8);

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('sample-private_metadata-removed.pdf');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(output.toString('latin1')).not.toContain('OfficeKit PDF test fixture');
  const countResponse = await page.request.post('http://127.0.0.1:19873/api/pdf/page-counts', {
    headers: { authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    multipart: { files: { name: download.suggestedFilename(), mimeType: 'application/pdf', buffer: output } },
  });
  expect(countResponse.status()).toBe(200);
  expect(await countResponse.json()).toMatchObject({ total_pages: 1, ready_count: 1, unreadable_count: 0 });
  expect(await fs.readFile(sourcePath)).toEqual(source);
});
