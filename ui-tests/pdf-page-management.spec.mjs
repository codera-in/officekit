import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
test.beforeEach(async ({ context, page }) => {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.evaluate(() => openPdfTool('delete-pages', false));
});

async function getPageCount(page, name, bytes) {
  const response = await page.request.post('http://127.0.0.1:19873/api/pdf/page-counts', {
    headers: { authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    multipart: { files: { name, mimeType: 'application/pdf', buffer: bytes } },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).total_pages;
}

test('delete pages selects thumbnails, keeps one page, exports a new PDF and preserves the source', async ({ page }) => {
  const sourcePath = fileURLToPath(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  const source = await fs.readFile(sourcePath);
  const requests = [];
  page.on('request', request => {
    if (request.url().includes('/api/pdf/pages/delete')) requests.push(request);
  });

  await page.locator('[data-pdf-tool="delete-pages"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
  const thumbnails = page.locator('ol[aria-label="PDF page thumbnails"] > li');
  await expect(thumbnails).toHaveCount(3);
  await expect(page.locator('section[aria-label="Select PDF pages to delete"] [role="alert"]')).toHaveCount(0);
  await expect(page.getByText(/not secure redaction/i)).toBeVisible();
  const deleteButtons = page.getByRole('button', { name: 'Delete this page' });
  await deleteButtons.nth(1).click();
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('1 page selected for removal');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('2 will remain');

  const requestReady = page.waitForRequest(request => request.url().includes('/api/pdf/pages/delete'));
  await page.locator('#pdf-workbench-run').click();
  const request = await requestReady;
  expect(request.postData()).toContain('name="page_ranges"\r\n\r\n2');
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
  await expect.poll(() => page.evaluate(() => {
    const preview = document.getElementById('pdf-workbench-preview');
    const dock = document.getElementById('officekit-tool-actions');
    return dock.getBoundingClientRect().top - preview.getBoundingClientRect().bottom;
  })).toBeGreaterThanOrEqual(8);
  expect(requests).toHaveLength(1);

  const downloadReady = page.waitForEvent('download');
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('pdf-page-management-source_pages-removed.pdf');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await getPageCount(page, 'removed-page.pdf', output)).toBe(2);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('reorder controls submit a complete keyboard-operable order and download a readable copy', async ({ page }) => {
  const sourcePath = fileURLToPath(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  const source = await fs.readFile(sourcePath);
  const requests = [];
  page.on('request', request => {
    if (request.url().includes('/api/pdf/pages/reorder')) requests.push(request);
  });

  await page.locator('[data-pdf-tool="reorder-pages"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
  const thumbnails = page.locator('ol[aria-label="PDF page thumbnails"] > li');
  await expect(thumbnails).toHaveCount(3);
  await expect(thumbnails.nth(2)).toHaveAttribute('aria-label', /Alt plus arrow keys to reorder/);
  await page.getByRole('button', { name: 'Move page up: page 3' }).click();
  await expect(thumbnails.nth(1)).toHaveAttribute('data-page-number', '3');
  await expect(thumbnails.nth(2)).toHaveAttribute('data-page-number', '2');

  const requestReady = page.waitForRequest(request => request.url().includes('/api/pdf/pages/reorder'));
  await page.locator('#pdf-workbench-run').click();
  const request = await requestReady;
  expect(request.postData()).toContain('name="page_order"\r\n\r\n1,3,2');
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect.poll(() => page.evaluate(() => {
    const preview = document.getElementById('pdf-workbench-preview');
    const dock = document.getElementById('officekit-tool-actions');
    return dock.getBoundingClientRect().top - preview.getBoundingClientRect().bottom;
  })).toBeGreaterThanOrEqual(8);
  expect(requests).toHaveLength(1);

  const downloadReady = page.waitForEvent('download');
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('pdf-page-management-source_reordered.pdf');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await getPageCount(page, 'reordered.pdf', output)).toBe(3);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});
