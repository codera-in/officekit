import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

async function downloadStatementExport(page, format = 'csv') {
  const actions = page.locator('#statement-results .officekit-result-actions');
  await actions.getByRole('button', { name: 'Download' }).click();
  await page.locator('.officekit-download-dialog select').selectOption(format);
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Continue' }).click();
  return downloadReady;
}

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
});

test('statement PDF extraction reviews ambiguous rows and exports only recovered transactions', async ({ page }) => {
  const sourcePath = path.resolve('tests/fixtures/statements/weak-vector-raster-statement.pdf');
  const source = await fs.readFile(sourcePath);
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-file-input').setInputFiles(sourcePath);

  const results = page.locator('#statement-results');
  await expect(results).toBeVisible({ timeout: 20_000 });
  const transactions = page.locator('#transactions-tbody');
  await expect(transactions).toContainText('Coffee Shop');
  await expect(transactions).toContainText('25.00');
  await expect(transactions).toContainText('975.00');
  await expect(page.locator('#reconciliation-banner')).toContainText('All balance movements matched');

  const download = await downloadStatementExport(page);
  expect(download.suggestedFilename()).toBe('statement_export.csv');
  const csv = await fs.readFile(await download.path(), 'utf8');
  expect(csv).toContain('Coffee Shop');
  expect(csv).toMatch(/Coffee Shop,25(?:\.0+)?/);
  expect(csv).toMatch(/Coffee Shop,25,Unavailable,975,ok/);
  expect(csv).not.toContain('Opening balance Coffee Shop');
  expect(csv).not.toMatch(/2026-01-02\s+2026-01-03/);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('provided local statement keeps transaction dates separate and exports four extracted rows', async ({ page }) => {
  test.skip(!process.env.OFFICEKIT_STATEMENT_REVIEW_PDF, 'Local statement acceptance sample was not provided');
  const sourcePath = path.resolve(process.env.OFFICEKIT_STATEMENT_REVIEW_PDF);
  const source = await fs.readFile(sourcePath);
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-file-input').setInputFiles(sourcePath);

  const results = page.locator('#statement-results');
  await expect(results).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('#trans-count')).toHaveText('4');
  const rows = page.locator('#transactions-tbody tr');
  await expect(rows).toHaveCount(4);
  const dates = await rows.locator('td:nth-child(2)').allTextContents();
  expect(dates.map(value => value.replace(/\s+/g, ' ').trim())).toEqual([
    '21/09/26', '25/09/26', '25/09/26', '25/09/26',
  ]);
  const normalizedCell = async (row, column) => (await rows.nth(row).locator(`td:nth-child(${column})`).innerText())
    .replace(/\s+/g, ' ').trim();
  const firstNarration = await normalizedCell(0, 3);
  expect(firstNarration).toContain('FOREIGN INR PACB INW-TXN000000R0-ORBITX NETWORK GROUP PTE LTD-SKYDO');
  expect(await normalizedCell(0, 5)).toBe('1718697.40');
  expect(await normalizedCell(0, 6)).toBe('1737613.76');
  expect(await normalizedCell(0, 7)).toBe('Balance matched');
  expect(await normalizedCell(1, 3)).toContain('NEFT DR-UTIB0004034-JENNIFER ANDERSSON');
  expect(await normalizedCell(1, 4)).toBe('200000.00');
  expect(await normalizedCell(1, 6)).toBe('1537613.76');
  expect(await normalizedCell(2, 3)).toContain('50100000000001-TPT-HDFCAAAA00000001-MARY JANE SMITH');
  expect(await normalizedCell(2, 4)).toBe('200000.00');
  expect(await normalizedCell(2, 6)).toBe('1337613.76');
  expect(await normalizedCell(3, 3)).toContain('50100000000002-TPT-HDFCBBBB00000002-JOHN PAUL DAWSON');
  expect(await normalizedCell(3, 4)).toBe('150000.00');
  expect(await normalizedCell(3, 6)).toBe('1187613.76');
  await expect(page.locator('#reconciliation-banner')).toContainText('4 balance movements checked');
  await expect(page.locator('#reconciliation-banner')).not.toContainText('row could not be checked');

  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => {
      const region = document.querySelector('#statement-results [aria-label="Extracted transaction rows"]');
      const table = region?.querySelector('table');
      const rowHeights = Array.from(document.querySelectorAll('#transactions-tbody tr'), row => row.getBoundingClientRect().height);
      const firstRowCells = Array.from(document.querySelectorAll('#transactions-tbody tr:first-child td'), cell => {
        const rect = cell.getBoundingClientRect();
        return { left: rect.left, right: rect.right };
      });
      return {
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        regionWidth: region?.clientWidth ?? 0,
        tableWidth: table?.scrollWidth ?? 0,
        rowHeights,
        cells: firstRowCells,
        actionBounds: Array.from(document.querySelectorAll('#statement-output-display button'), button => {
          const rect = button.getBoundingClientRect();
          return { left: rect.left, right: rect.right };
        }),
      };
    });
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tableWidth).toBeGreaterThan(layout.regionWidth);
    expect(layout.rowHeights.every(height => height < 150)).toBe(true);
    expect(layout.cells).toHaveLength(7);
    expect(layout.cells.every((cell, index) => index === 0 || layout.cells[index - 1].right <= cell.left)).toBe(true);
    expect(layout.actionBounds.every(action => action.left >= 0 && action.right <= layout.viewportWidth)).toBe(true);
  }

  const download = await downloadStatementExport(page);
  const csv = await fs.readFile(await download.path(), 'utf8');
  expect(download.suggestedFilename()).toBe('statement_export.csv');
  expect(csv.trim().split(/\r?\n/)).toHaveLength(5);
  expect(csv).toContain('FOREIGN INR PACB INW-TXN000000R0-ORBITX NETWORK GROUP PTE LTD-SKYDO');
  expect(csv).toMatch(/,1718697(?:\.4)?,1737613\.76,ok/);
  expect(csv).toContain('50100000000002-TPT-HDFCBBBB00000002-JOHN PAUL DAWSON');
  expect(csv).toMatch(/,150000(?:\.0)?,,1187613\.76,ok/);
  expect(await fs.readFile(sourcePath)).toEqual(source);

  const workbookDownload = await downloadStatementExport(page, 'xlsx');
  expect(workbookDownload.suggestedFilename()).toBe('statement_export.xlsx');
  const workbook = await fs.readFile(await workbookDownload.path());
  expect(workbook.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(workbook.length).toBeGreaterThan(1000);
  expect(await fs.readFile(sourcePath)).toEqual(source);

  const legacyDownload = await downloadStatementExport(page, 'xls');
  expect(legacyDownload.suggestedFilename()).toBe('statement_export.xls');
  const legacyWorkbook = await fs.readFile(await legacyDownload.path());
  expect(legacyWorkbook.subarray(0, 8)).toEqual(Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]));
  expect(legacyWorkbook.length).toBeGreaterThan(1000);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('ambiguous multi-date row keeps real extraction and CSV reconciliation partial', async ({ page }) => {
  const csv = [
    'Date,Description,Debit,Credit,Balance',
    '20/09/26,Opening balance,,,1000.00',
    '"21/09/26 25/09/26 25/09/26 25/09/26","FOREIGN INWARD REMITTANCE TXN000000RO",,,',
    '26/09/26,Monthly service fee,10.00,,990.00',
  ].join('\n');
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-file-input').setInputFiles({
    name: 'merged-dates.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv),
  });

  const results = page.locator('#statement-results');
  await expect(results).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked');
  await expect(page.locator('#reconciliation-banner')).toContainText('1 row could not be checked');
  const excluded = page.locator('#statement-excluded-warning');
  await expect(excluded).toContainText('1 source row was left out of the transaction list');
  await excluded.getByText('Review excluded rows', { exact: true }).click();
  await expect(excluded.locator('li')).toContainText('FOREIGN INWARD REMITTANCE TXN000000RO');

  const transactions = page.locator('#transactions-tbody');
  await expect(page.locator('#trans-count')).toHaveText('2');
  await expect(transactions).toContainText('Opening balance');
  await expect(transactions).toContainText('Monthly service fee');
  await expect(transactions).not.toContainText('FOREIGN INWARD REMITTANCE');

  const download = await downloadStatementExport(page);
  const exportedCsv = await fs.readFile(await download.path(), 'utf8');
  expect(exportedCsv).toContain('Monthly service fee');
  expect(exportedCsv).not.toContain('FOREIGN INWARD REMITTANCE');
});

test('statement correction rechecks edited rows and resolved source rows before export', async ({ page }) => {
  const csv = [
    'Date,Description,Debit,Credit,Balance',
    '20/09/26,Opening balance,,,1000.00',
    '"21/09/26 25/09/26 25/09/26 25/09/26","FOREIGN INWARD REMITTANCE TXN000000RO",,,',
    '26/09/26,Monthly service fee,10.00,,990.00',
  ].join('\n');
  const sourceBytes = Buffer.from(csv);
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-date-order').selectOption('DMY');
  await page.locator('#statement-file-input').setInputFiles({
    name: 'statement-correction.csv', mimeType: 'text/csv', buffer: sourceBytes,
  });
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked', { timeout: 20_000 });
  await page.getByRole('button', { name: 'Review & correct' }).click();

  const editor = page.locator('#statement-correction-panel');
  await expect(editor).toBeVisible();
  await editor.getByRole('button', { name: 'Add corrected transaction' }).click();
  const transactionFields = editor.locator('#statement-correction-transactions');
  await transactionFields.getByLabel('Date', { exact: true }).nth(2).fill('22/09/26');
  await transactionFields.getByLabel('Description', { exact: true }).nth(2).fill('Corrected remittance');
  await transactionFields.getByLabel('Debit', { exact: true }).nth(1).fill('5');
  await transactionFields.getByLabel('Debit', { exact: true }).nth(2).fill('5');
  await transactionFields.getByLabel('Balance', { exact: true }).nth(2).fill('995');

  const correctionResponse = page.waitForResponse(response => response.url().includes('/api/extract/statement') && response.request().method() === 'POST');
  await editor.getByRole('button', { name: 'Recheck and apply' }).click();
  const correctedResult = await (await correctionResponse).json();
  expect(correctedResult.transactions.map(row => row.description)).toEqual([
    'Opening balance', 'Corrected remittance', 'Monthly service fee',
  ]);
  expect(correctedResult.reconciliation).toMatchObject({ status: 'verified', checked_rows: 2 });
  await expect(page.locator('#reconciliation-banner')).toContainText('All balance movements matched', { timeout: 20_000 });
  await expect(page.locator('#statement-excluded-warning')).toBeHidden();
  await expect(page.locator('#transactions-tbody')).toContainText('Corrected remittance');
  await expect(page.locator('#transactions-tbody')).toContainText('Monthly service fee');

  const download = await downloadStatementExport(page);
  const exportedCsv = await fs.readFile(await download.path(), 'utf8');
  expect(exportedCsv).toContain('Corrected remittance');
  expect(exportedCsv).toContain('Monthly service fee');
  expect(exportedCsv).not.toContain('FOREIGN INWARD REMITTANCE');
  expect(Buffer.from(await page.locator('#statement-file-input').evaluate(async input => Array.from(new Uint8Array(await input.files[0].arrayBuffer()))))).toEqual(sourceBytes);
});

test('unresolved excluded source rows stay excluded after correction recheck', async ({ page }) => {
  const csv = [
    'Date,Description,Debit,Credit,Balance',
    '20/09/26,Opening balance,,,1000.00',
    '"21/09/26 25/09/26","Possible combined activity",,,',
    '26/09/26,Monthly service fee,10.00,,990.00',
  ].join('\n');
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-file-input').setInputFiles({
    name: 'unresolved-correction.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked', { timeout: 20_000 });
  await page.getByRole('button', { name: 'Review & correct' }).click();
  await page.locator('#statement-correction-apply').click();
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked', { timeout: 20_000 });
  await expect(page.locator('#statement-excluded-warning')).toContainText('Possible combined activity');
  await expect(page.locator('#transactions-tbody')).not.toContainText('Possible combined activity');
});

test('statement column mapping rereads the original file and exports recalculated columns', async ({ page }) => {
  const source = [
    'Value Date,Transaction Date,Narration,Reference,Debit,Credit,Closing Balance',
    '26/09/26,25/09/26,Coffee shop,REF-1,10.00,,990.00',
    '27/09/26,26/09/26,Salary,REF-2,,20.00,1010.00',
  ].join('\n');
  const sourceBytes = Buffer.from(source);
  await page.evaluate(() => switchTab('statement'));
  await page.locator('#statement-file-input').setInputFiles({
    name: 'ambiguous-date-columns.csv', mimeType: 'text/csv', buffer: sourceBytes,
  });

  const rows = page.locator('#transactions-tbody tr');
  await expect(rows).toHaveCount(2, { timeout: 20_000 });
  await expect(rows.nth(0).locator('td').nth(1)).toHaveText('26/09/26');
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked');

  await page.getByRole('button', { name: 'Review & correct' }).click();
  const editor = page.locator('#statement-correction-panel');
  await editor.locator('#statement-column-mapping-details summary').click();
  await editor.locator('#statement-column-map-date').selectOption('1');
  await editor.locator('#statement-column-mapping-apply').click();

  await expect(page.locator('#statement-mapping-result-status')).toContainText('Column mapping updated.', { timeout: 20_000 });
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator('td').nth(1)).toHaveText('25/09/26');
  await expect(rows.nth(0).locator('td').nth(2)).toContainText('Coffee shop');
  await expect(rows.nth(0).locator('td').nth(3)).toHaveText('10.00');
  await expect(rows.nth(1).locator('td').nth(1)).toHaveText('26/09/26');
  await expect(page.locator('#reconciliation-banner')).toContainText('Some balance rows could not be checked');

  const download = await downloadStatementExport(page);
  const exportedCsv = await fs.readFile(await download.path(), 'utf8');
  expect(exportedCsv).toContain('25/09/26,Coffee shop,10,Unavailable,990,unverified');
  expect(exportedCsv).toContain('26/09/26,Salary,Unavailable,20,1010,ok');
  const uploadedBytes = await page.locator('#statement-file-input').evaluate(async input => Array.from(new Uint8Array(await input.files[0].arrayBuffer())));
  expect(Buffer.from(uploadedBytes)).toEqual(sourceBytes);
});

test('visible locale controls govern one real extraction and automatic mode preserves ambiguity', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-statement-locale-'));
  const sourcePath = path.join(root, 'locale-check.csv');
  const source = [
    'Date,Description,Debit,Credit,Balance',
    '02/04/2026,Opening balance,,,10000.00',
    '03/04/2026,Regional purchase,"1,234",,8766.00',
  ].join('\n');
  await fs.writeFile(sourcePath, source, 'utf8');
  try {
    await page.evaluate(() => switchTab('statement'));
    await expect(page.locator('#statement-number-locale')).toBeVisible();
    await expect(page.locator('#statement-date-order')).toBeVisible();
    await page.locator('#statement-number-locale').selectOption('en-US');
    await page.locator('#statement-date-order').selectOption('DMY');
    await page.locator('#statement-file-input').setInputFiles(sourcePath);

    const results = page.locator('#statement-results');
    await expect(results).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('#reconciliation-banner')).toContainText('All balance movements matched');
    await expect(page.locator('#transactions-tbody')).toContainText('2026-04-03');
    await expect(page.locator('#transactions-tbody')).toContainText('1234.00');

    await page.locator('#statement-number-locale').selectOption('auto');
    await page.locator('#statement-date-order').selectOption('auto');
    await page.locator('#statement-file-input').evaluate(input => { input.value = ''; });
    await page.locator('#statement-file-input').setInputFiles(sourcePath);
    await expect(page.locator('#reconciliation-banner')).toContainText('Balance math could not be verified');
    await expect(page.locator('#transactions-tbody')).toContainText('03/04/2026');
    await expect(page.locator('#transactions-tbody')).toContainText('Amount not detected');
    expect(await fs.readFile(sourcePath, 'utf8')).toBe(source);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
