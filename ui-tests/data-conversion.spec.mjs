import { test, expect } from '@playwright/test';
import { expectGalleryMatchesCatalog } from './gallery-count.mjs';
import fs from 'node:fs/promises';


let externalRequests;
let pageErrors;

test.beforeEach(async ({ context, page }) => {
  externalRequests = [];
  pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const request = route.request();
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...request.headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expectGalleryMatchesCatalog(page, expect);
});

test.afterEach(() => {
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

async function openConverter(page) {
  await page.locator('#tool-gallery-search').fill('Tabular file conversion');
  await page.locator('[data-open-tool="data_converter"]').click();
  await expect(page.locator('#tab-converter')).toBeVisible();
}

test('data converter downloads JSON from a real selected CSV and preserves identifier text', async ({ page }) => {
  const source = Buffer.from('account,amount,posted_at,note\n001234,25.50,2026-10-07,coffee\n000045,0,01/02/2026,paid\n');
  await openConverter(page);

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles({ name: 'ledger.csv', mimeType: 'text/csv', buffer: source });
  await expect(page.locator('#converter-status')).toHaveText('Tabular data · 6 supported output formats.');
  await page.locator('#format-options button', { hasText: 'json' }).click();

  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  const downloadReady = page.waitForEvent('download');
  await page.locator('#converter-action-controls .officekit-result-actions button').nth(1).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('ledger.json');
  const output = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  expect(output).toEqual([
    { account: '001234', amount: 25.5, posted_at: '2026-10-07', note: 'coffee' },
    { account: '000045', amount: 0, posted_at: '01/02/2026', note: 'paid' },
  ]);
});

test('data converter preserves null and empty values with an explicit CSV marker', async ({ page }) => {
  const source = Buffer.from(JSON.stringify([{
    null_value: null,
    empty_value: '',
    literal_marker: '\\N',
    literal_escape: '\\starts-with-slash',
  }]));
  await openConverter(page);
  await page.locator('#generic-file-input').setInputFiles({
    name: 'nullable.json', mimeType: 'application/json', buffer: source,
  });
  await expect(page.locator('#converter-null-token-panel')).toBeVisible();
  await page.locator('#converter-null-token-enabled').check();
  await expect(page.locator('#converter-null-token')).toBeEnabled();
  await expect(page.locator('#converter-null-token')).toHaveValue('\\N');

  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  const csvDownloadReady = page.waitForEvent('download');
  await page.locator('#converter-action-controls .officekit-result-actions button').nth(1).click();
  const csvDownload = await csvDownloadReady;
  const csv = await fs.readFile(await csvDownload.path(), 'utf8');
  expect(csv).toContain('null_value,empty_value,literal_marker,literal_escape');
  expect(csv).toContain('\\N,,\\\\N,\\\\starts-with-slash');

  await page.locator('#generic-file-input').setInputFiles({
    name: 'nullable.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  await page.locator('#format-options button', { hasText: 'json' }).click();
  await page.locator('#converter-null-token-enabled').check();
  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  const jsonDownloadReady = page.waitForEvent('download');
  await page.locator('#converter-action-controls .officekit-result-actions button').nth(1).click();
  const jsonDownload = await jsonDownloadReady;
  expect(JSON.parse(await fs.readFile(await jsonDownload.path(), 'utf8'))).toEqual([{
    null_value: null,
    empty_value: '',
    literal_marker: '\\N',
    literal_escape: '\\starts-with-slash',
  }]);
});

test('data converter blocks spreadsheet-formula-shaped null markers before processing', async ({ page }) => {
  let conversionRequests = 0;
  await page.route('**/api/convert/data', async route => {
    conversionRequests += 1;
    await route.continue();
  });
  await openConverter(page);
  await page.locator('#generic-file-input').setInputFiles({
    name: 'nullable.json', mimeType: 'application/json',
    buffer: Buffer.from('[{"value":null}]'),
  });
  await page.locator('#converter-null-token-enabled').check();
  await page.locator('#converter-null-token').fill('  +cmd');
  await page.locator('#convert-btn').click();

  await expect(page.locator('#converter-status')).toHaveText(
    'Choose a null marker that does not begin with =, +, -, or @, even after whitespace.',
  );
  await expect(page.locator('#convert-btn')).toBeEnabled();
  expect(conversionRequests).toBe(0);
});

test('data converter reports malformed CSV and restores the conversion control', async ({ page }) => {
  await openConverter(page);

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles({
    name: 'broken.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('name,amount\n"unterminated,10\n'),
  });
  await page.locator('#format-options button', { hasText: 'json' }).click();
  await page.locator('#convert-btn').click();

  await expect(page.locator('#converter-status')).toHaveText(
    'The file or requested format cannot be converted. Check the input and try again.',
  );
  await expect(page.locator('#convert-btn')).toBeEnabled();
});

test('XLSX exposes worksheet names as text and converts only the selected worksheet', async ({ page }) => {
  let selectedSheetPosted = null;
  await page.route('**/api/convert/data/sheets', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ sheets: ['Transactions', 'Summary', '<img onerror=1>'] }),
  }));
  await page.route('**/api/convert/data', async route => {
    const requestBody = route.request().postData() || '';
    selectedSheetPosted = requestBody.match(/name="sheet_name"\r\n\r\n([^\r\n]+)/)?.[1] || null;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[{"code":"000045"}]' });
  });
  await openConverter(page);

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles({
    name: 'quarterly-ledger.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('mock xlsx payload'),
  });

  const selector = page.locator('#converter-xlsx-sheet');
  await expect(page.locator('#xlsx-sheet-panel')).toBeVisible();
  await expect(selector.locator('option')).toHaveCount(3);
  await expect(selector.locator('option').nth(2)).toHaveText('<img onerror=1>');
  await expect(page.locator('#xlsx-sheet-panel img')).toHaveCount(0);
  await selector.selectOption('Summary');
  await page.locator('#format-options button', { hasText: 'json' }).click();

  await page.locator('#convert-btn').click();
  await expect(page.locator('#converter-status')).toHaveText('Conversion ready. Copy or download the output; your original file is unchanged.');
  const downloadReady = page.waitForEvent('download');
  await page.locator('#converter-action-controls .officekit-result-actions button').nth(1).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('quarterly-ledger.json');
  expect(selectedSheetPosted).toBe('Summary');
});

test('XLSX conversion stays disabled when worksheet lookup fails and retry recovers', async ({ page }) => {
  let lookupCalls = 0;
  await page.route('**/api/convert/data/sheets', route => {
    lookupCalls += 1;
    return route.fulfill({
      status: lookupCalls === 1 ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(lookupCalls === 1 ? { detail: 'unavailable' } : { sheets: ['Transactions'] }),
    });
  });
  await openConverter(page);

  const chooser = page.waitForEvent('filechooser');
  await page.locator('#generic-file-select-button').click();
  await (await chooser).setFiles({
    name: 'ledger.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('mock xlsx payload'),
  });

  await expect(page.locator('#xlsx-sheet-status')).toHaveText('Could not read worksheet names. Retry or select the workbook again.');
  await expect(page.locator('#convert-btn')).toBeDisabled();
  await page.locator('#xlsx-sheet-retry').click();
  await expect(page.locator('#xlsx-sheet-status')).toHaveText('1 worksheet found. The first worksheet is selected by default.');
  await expect(page.locator('#convert-btn')).toBeEnabled();
  expect(lookupCalls).toBe(2);
});
