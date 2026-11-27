import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

async function clickPdfOutputDownload(page) {
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
}

test.beforeEach(async ({ context, page }) => {
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`, origin: 'tauri://localhost' },
    });
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
});

test('search opens PDF merge and downloads a new PDF from selected files', async ({ page }) => {
  const first = await fs.readFile(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  const second = await fs.readFile(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url));
  await page.locator('#tool-gallery-search').fill('merge pdf');
  await expect(page.locator('#tool-gallery-results [data-open-tool="pdf_merge"]')).toBeVisible();
  await page.locator('#tool-gallery-results [data-open-tool="pdf_merge"]').click();
  await expect(page.locator('#pdf-task-title')).toHaveText('Merge PDFs');
  await page.locator('#pdf-workbench-file-input').setInputFiles([
    { name: 'first.pdf', mimeType: 'application/pdf', buffer: first },
    { name: 'second.pdf', mimeType: 'application/pdf', buffer: second },
  ]);
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  const responsePromise = page.waitForResponse(response => response.url().includes('/api/pdf/merge'));
  await page.locator('#pdf-workbench-run').click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/pdf');
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  const downloadPromise = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('first_merged.pdf');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await fs.readFile(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url))).toEqual(first);
  expect(await fs.readFile(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url))).toEqual(second);
});

test('search opens grouped PDF split and downloads validated named copies in a ZIP', async ({ page }) => {
  const source = await fs.readFile(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  await page.locator('#tool-gallery-search').fill('split pdf');
  await expect(page.locator('#tool-gallery-results [data-open-tool="pdf_split"]')).toBeVisible();
  await page.locator('#tool-gallery-results [data-open-tool="pdf_split"]').click();
  await expect(page.locator('#pdf-task-title')).toHaveText('Split by pages');
  await page.locator('#pdf-workbench-file-input').setInputFiles({ name: 'source.pdf', mimeType: 'application/pdf', buffer: source });
  await page.locator('#pdf-split-group-name-1').fill('last-first.pdf');
  await page.locator('#pdf-split-group-ranges-1').fill('3,1');
  await page.locator('#pdf-split-group-name-2').fill('middle.pdf');
  await page.locator('#pdf-split-group-ranges-2').fill('2');
  await expect(page.locator('#pdf-split-preview-list')).toContainText('last-first.pdf — pages 3,1');
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  expect(await page.evaluate(() => ({
    activePdfTool,
    selectedCount: pdfSelectedFiles.length,
    groups: pdfSplitGroups.map(({ name, pageRanges }) => ({ name, pageRanges })),
    disabled: document.getElementById('pdf-workbench-run').disabled,
  }))).toEqual({
    activePdfTool: 'split',
    selectedCount: 1,
    groups: [{ name: 'last-first.pdf', pageRanges: '3,1' }, { name: 'middle.pdf', pageRanges: '2' }],
    disabled: false,
  });
  const responsePromise = page.waitForResponse(response => response.url().includes('/api/pdf/split/groups'));
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).not.toHaveText('1 PDF ready. Originals remain unchanged.');
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/zip');
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  const downloadPromise = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('source_split-pages.zip');
  const output = await fs.readFile(await download.path());
  expect(output.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(output.includes(Buffer.from('last-first.pdf'))).toBe(true);
  expect(output.includes(Buffer.from('middle.pdf'))).toBe(true);
  expect(output.includes(Buffer.from('%PDF-'))).toBe(true);
  expect(await fs.readFile(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url))).toEqual(source);
});
