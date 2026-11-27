import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

function makePdf(content) {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 450 780] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
  ];
  const chunks = [Buffer.from('%PDF-1.4\n', 'ascii')];
  const offsets = [0];
  let length = chunks[0].length;
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(length);
    const chunk = Buffer.from(`${index + 1} 0 obj\n${objects[index]}\nendobj\n`, 'ascii');
    chunks.push(chunk);
    length += chunk.length;
  }
  const xrefOffset = length;
  const xref = [`xref\n0 ${objects.length + 1}\n`, '0000000000 65535 f \n'];
  for (const offset of offsets.slice(1)) xref.push(`${String(offset).padStart(10, '0')} 00000 n \n`);
  xref.push(`trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`);
  chunks.push(Buffer.from(xref.join(''), 'ascii'));
  return Buffer.concat(chunks);
}

function makeGridTablePdf() {
  const lines = ['0.6 w', '50 630 m 400 630 l S', '50 660 m 400 660 l S', '50 690 m 400 690 l S', '50 720 m 400 720 l S', '50 630 m 50 720 l S', '170 630 m 170 720 l S', '290 630 m 290 720 l S', '400 630 m 400 720 l S'];
  const text = [
    [60, 702, 'Reference'], [180, 702, 'Description'], [300, 702, 'Amount'],
    [60, 672, '000042'], [180, 672, 'Tea'], [300, 672, '12.50'],
    [60, 642, 'A-07'], [180, 642, '=1+1'], [300, 642, '2.00'],
  ];
  for (const [x, y, value] of text) lines.push(`BT /F1 10 Tf 1 0 0 1 ${x} ${y} Tm (${value}) Tj ET`);
  return makePdf(lines.join('\n'));
}

async function downloadSelectedTable(page, format) {
  const ready = page.waitForEvent('download');
  await page.locator('#pdf-workbench-options .officekit-result-actions button').nth(1).click();
  await page.locator('.officekit-download-dialog select').selectOption(format);
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  return ready;
}

test.beforeEach(async ({ context, page }) => {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
});

test('selectable PDF tables preview and export to safe CSV, XLS and XLSX without changing the source', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-pdf-table-'));
  try {
    const sourcePath = path.join(root, 'inventory.pdf');
    const source = makeGridTablePdf();
    await fs.writeFile(sourcePath, source);
    await page.evaluate(() => openPdfTool('tables', false));
    await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
    await page.getByRole('button', { name: 'Find tables' }).click();

    const preview = page.getByLabel('Selected PDF table preview');
    await expect(preview).toBeVisible();
    await expect(preview).toContainText('000042');
    await expect(preview).toContainText('=1+1');
    await expect(page.locator('#pdf-workbench-status')).toContainText('Found 1 selectable table');

    const csvDownload = await downloadSelectedTable(page, 'csv');
    expect(csvDownload.suggestedFilename()).toBe('inventory_page_01_table_01.csv');
    const csv = await fs.readFile(await csvDownload.path(), 'utf8');
    expect(csv).toContain('Reference,Description,Amount');
    expect(csv).toContain('000042,Tea,12.50');
    expect(csv).toContain("A-07,'=1+1,2.00");

    const xlsDownload = await downloadSelectedTable(page, 'xls');
    expect(xlsDownload.suggestedFilename()).toBe('inventory_page_01_table_01.xls');
    const xls = await fs.readFile(await xlsDownload.path());
    expect(xls.subarray(0, 8)).toEqual(Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]));
    expect(xls.length).toBeGreaterThan(1000);

    const xlsxDownload = await downloadSelectedTable(page, 'xlsx');
    expect(xlsxDownload.suggestedFilename()).toBe('inventory_page_01_table_01.xlsx');
    const xlsx = await fs.readFile(await xlsxDownload.path());
    expect(xlsx.subarray(0, 4).toString('hex')).toBe('504b0304');
    expect(xlsx.length).toBeGreaterThan(1000);
    expect(await fs.readFile(sourcePath)).toEqual(source);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('supplied bank statement renders four separate transaction rows in the PDF table preview', async ({ page }) => {
  test.skip(!process.env.OFFICEKIT_STATEMENT_REVIEW_PDF, 'Set OFFICEKIT_STATEMENT_REVIEW_PDF for private-source UI acceptance');
  const sourcePath = path.resolve(process.env.OFFICEKIT_STATEMENT_REVIEW_PDF);
  const sourceBytes = await fs.readFile(sourcePath);
  await page.evaluate(() => openPdfTool('tables', false));
  await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
  await page.getByRole('button', { name: 'Find tables' }).click();

  const preview = page.getByLabel('Selected PDF table preview');
  await expect(preview).toBeVisible();
  const rows = preview.locator('tbody tr');
  await expect(rows).toHaveCount(5);
  const header = rows.nth(0).locator('th');
  await expect(header).toHaveCount(7);
  await expect(header.nth(0)).toHaveText('Date');
  await expect(header.nth(1)).toHaveText('Narration');
  await expect(header.nth(6)).toHaveText('ClosingBalance');

  const dates = ['21/09/26', '25/09/26', '25/09/26', '25/09/26'];
  for (let index = 0; index < dates.length; index += 1) {
    const cells = rows.nth(index + 1).locator('td');
    await expect(cells).toHaveCount(7);
    await expect(cells.nth(0)).toHaveText(dates[index]);
    await expect(cells.nth(3)).toHaveText(dates[index]);
    await expect(cells.nth(1)).not.toBeEmpty();
    await expect(cells.nth(2)).not.toBeEmpty();
    await expect(cells.nth(6)).not.toBeEmpty();
  }
  await expect(rows.nth(1).locator('td').nth(4)).toBeEmpty();
  for (const index of [2, 3, 4]) await expect(rows.nth(index).locator('td').nth(4)).not.toBeEmpty();
  await expect(rows.nth(1).locator('td').nth(5)).not.toBeEmpty();
  for (const index of [2, 3, 4]) await expect(rows.nth(index).locator('td').nth(5)).toBeEmpty();

  const download = await downloadSelectedTable(page, 'csv');
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
  const csv = await fs.readFile(await download.path(), 'utf8');
  expect(csv).toContain('Date,Narration,Chq./Ref.No.,ValueDt,WithdrawalAmt.,DepositAmt.,ClosingBalance');
  for (const date of dates) {
    const rowDate = new RegExp(`(?:^|\\r?\\n)\\"?${date}\\"?,`, 'g');
    expect([...csv.matchAll(rowDate)]).toHaveLength(dates.filter(value => value === date).length);
  }
  expect(await fs.readFile(sourcePath)).toEqual(sourceBytes);
});

test('PDF table extraction reports no-table PDFs without enabling exports', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-pdf-no-table-'));
  try {
    const sourcePath = path.join(root, 'blank.pdf');
    await fs.writeFile(sourcePath, makePdf('q Q'));
    await page.evaluate(() => openPdfTool('tables', false));
    await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
    await page.getByRole('button', { name: 'Find tables' }).click();
    await expect(page.locator('#pdf-workbench-status')).toContainText('No selectable PDF tables were found');
    await expect(page.getByText('No selectable tables were found.', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download CSV' })).toBeHidden();
    await expect(page.getByRole('button', { name: 'Download XLS', exact: true })).toBeHidden();
    await expect(page.getByRole('button', { name: 'Download XLSX' })).toBeHidden();
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
