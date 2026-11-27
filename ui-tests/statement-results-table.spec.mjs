import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';


test('statement results keep long extracted text readable and expandable at desktop and compact widths', async ({ context, page }, testInfo) => {
  const pageErrors = [];
  const externalRequests = [];
  const exportRequests = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/export/csv') exportRequests.push(request.postDataJSON());
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const response = await route.fetch({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
          origin: 'tauri://localhost',
        },
      });
      await route.fulfill({ response });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.evaluate(() => {
    switchTab('statement');
    const data = {
      reconciliation: { status: 'unverified', valid: null, checked_rows: 0, unverified_rows: 1, discrepancies_count: 0 },
      transactions: [{
        id: 1,
        date: 'Tuesday, 21 September 2026 (as printed)',
        description: 'FOREIGNINNRPACBINW-TXN000000RO-ORBITX NETWORKGROUPPTELTD-SKYDO NEFTDR-UTIB0004034-JENNIFER ANDERSSON-NETBANK,MUM-HDFC01283153909-BB00N000001 12000000000003 50100000000001-TPT-HDFCAAAA0000001-MARY JANESMITH50100000000002-TPT-HDFCBBBB0000002-JOHNPAULDAWSO',
        debit: 250.5,
        credit: null,
        balance: 12500,
        status: 'unverified',
      }],
    };
    currentExtractedData = data;
    renderStatementResults(data);
  });

  const scrollRegion = page.getByRole('region', { name: 'Extracted transaction rows' });
  const dateDetails = page.locator('#transactions-tbody details').filter({ has: page.getByText('Show full date', { exact: true }) });
  const descriptionDetails = page.locator('#transactions-tbody details').filter({ has: page.getByText('Show full description', { exact: true }) });
  await expect(scrollRegion).toBeVisible();
  await expect(dateDetails).toHaveCount(1);
  await expect(descriptionDetails).toHaveCount(1);
  await expect(page.locator('#transactions-tbody')).toContainText('Not checked');
  await expect(page.locator('#transactions-tbody tr')).toContainText('250.50');
  await expect(page.locator('#transactions-tbody tr')).not.toContainText('$');
  await expect(page.locator('#statement-results')).toContainText('CSV/XLS/XLSX exports keep the complete values');
  await expect(page.locator('#statement-results')).toContainText('source currency is not inferred or converted');
  await expect(page.locator('#statement-results')).toContainText('scroll the table horizontally to see every column');
  await expect(page.locator('#statement-results .officekit-result-actions')).toContainText('Review & correct');
  await page.evaluate(() => renderStatementResults(currentExtractedData));
  await expect(page.locator('#statement-results .officekit-result-actions button')).toHaveCount(3);
  const collapsedHeight = await page.locator('#transactions-tbody tr').first().evaluate(row => row.getBoundingClientRect().height);
  expect(collapsedHeight).toBeLessThan(150);
  await page.screenshot({ path: testInfo.outputPath('statement-results-desktop.png'), fullPage: true });

  await dateDetails.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(dateDetails).toHaveAttribute('open', '');
  await expect(page.getByLabel('Full extracted date')).toBeVisible();
  await page.keyboard.press('Space');
  await expect(dateDetails).not.toHaveAttribute('open', '');
  await page.getByText('Show full description', { exact: true }).click();
  await expect(page.getByLabel('Full extracted description')).toBeVisible();
  await expect(page.getByLabel('Full extracted description')).toContainText('JOHNPAULDAWSO');
  const downloadReady = page.waitForEvent('download');
  await page.evaluate(() => exportStatement('csv'));
  const download = await downloadReady;
  const exportedCsv = await readFile(await download.path(), 'utf8');
  expect(exportRequests).toHaveLength(1);
  expect(exportRequests[0].transactions[0]).toMatchObject({ debit: 250.5, balance: 12500, status: 'unverified' });
  expect(exportedCsv).toContain(',250.5,,12500.0,unverified');
  expect(exportedCsv).not.toContain('$');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
  await expect(scrollRegion).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    tableWidth: document.querySelector('#transactions-tbody').closest('table').scrollWidth,
    scrollRegionWidth: document.querySelector('#statement-results .overflow-x-auto').clientWidth,
    actions: Array.from(document.querySelectorAll('#statement-results .officekit-result-actions button'), button => {
      const rect = button.getBoundingClientRect();
      return { left: rect.left, right: rect.right, height: rect.height };
    }),
    dockPosition: getComputedStyle(document.querySelector('#statement-results .officekit-result-actions')).position,
  }));
  expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect(dimensions.tableWidth).toBeGreaterThan(dimensions.scrollRegionWidth);
  expect(dimensions.actions).toHaveLength(3);
  expect(dimensions.dockPosition).toBe('fixed');
  expect(dimensions.actions.every(action => action.left >= 0 && action.right <= dimensions.viewportWidth)).toBe(true);
  expect(dimensions.actions.every(action => action.height >= 44)).toBe(true);
  await descriptionDetails.locator('summary').focus();
  await page.keyboard.press('Space');
  await expect(descriptionDetails).not.toHaveAttribute('open', '');
  await page.screenshot({ path: testInfo.outputPath('statement-results-compact.png'), fullPage: true });
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('multi-date rows stay out of transactions and exports while remaining reviewable', async ({ context, page }) => {
  const pageErrors = [];
  const externalRequests = [];
  const exportRequests = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/export/csv') exportRequests.push(request.postDataJSON());
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const response = await route.fetch({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
          origin: 'tauri://localhost',
        },
      });
      await route.fulfill({ response });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.evaluate(() => {
    switchTab('statement');
    const data = {
      reconciliation: { status: 'unverified', valid: null, checked_rows: 0, unverified_rows: 1, discrepancies_count: 0 },
      column_mapping: { date: 0, desc: 1 },
      raw_rows: [
        ['Date', 'Description', 'Debit', 'Credit', 'Balance'],
        ['21/09/26 25/09/26 25/09/26 25/09/26', 'FOREIGN INWARD REMITTANCE TXN000000RO', '-', '-', '-'],
        ['24/09/26 25/09/26', 'SECOND AMBIGUOUS ROW', '-', '-', '-'],
        ['26/09/26', 'Monthly service fee', '10.00', '', '990.00'],
      ],
      excluded_rows: [
        { row_index: 1, reason: 'multiple_dates' },
        { row_index: 2, reason: 'multiple_dates' },
        { row_index: 999, reason: 'multiple_dates' },
        { row_index: 2, reason: 'other' },
      ],
      transactions: [{
        id: 1, date: '26/09/26', description: 'Monthly service fee',
        debit: 10, credit: null, balance: 990, status: 'unverified',
      }],
    };
    currentExtractedData = data;
    renderStatementResults(data);
  });

  const warning = page.locator('#statement-excluded-warning');
  await expect(warning).toBeVisible();
  await expect(warning).toContainText('2 source rows were left out of the transaction list');
  await expect(page.locator('#transactions-tbody tr')).toHaveCount(1);
  await expect(page.locator('#transactions-tbody')).not.toContainText('FOREIGN INWARD REMITTANCE');
  await warning.getByText('Review excluded rows', { exact: true }).focus();
  await page.keyboard.press('Enter');
  const omittedItems = warning.locator('li');
  await expect(omittedItems).toHaveCount(2);
  await expect(omittedItems.nth(0)).toContainText('21/09/26 25/09/26 25/09/26 25/09/26');
  await expect(omittedItems.nth(0)).toContainText('FOREIGN INWARD REMITTANCE TXN000000RO');
  await expect(omittedItems.nth(1)).toContainText('SECOND AMBIGUOUS ROW');

  const downloadReady = page.waitForEvent('download');
  await page.evaluate(() => exportStatement('csv'));
  const download = await downloadReady;
  const exportedCsv = await readFile(await download.path(), 'utf8');
  expect(exportRequests).toHaveLength(1);
  expect(exportRequests[0].transactions).toHaveLength(1);
  expect(exportedCsv).toContain('Monthly service fee');
  expect(exportedCsv).not.toContain('FOREIGN INWARD REMITTANCE');
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});
