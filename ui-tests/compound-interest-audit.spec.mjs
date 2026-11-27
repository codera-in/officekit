import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

let calls;

test.beforeEach(async ({ context, page }) => {
  calls = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      if (url.pathname === '/api/calculator/compound-interest') calls.push(route.request().postDataJSON());
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
  await page.locator('[data-sidebar-tab="tools"]').click();
  const card = page.locator('#tool-gallery-results article').filter({
    has: page.locator('[data-open-tool="compound_interest"]'),
  });
  await card.locator('[data-open-tool]').click();
});

test('compound growth exposes the selected frequency, assumptions and fractional history', async ({ page }, testInfo) => {
  await page.locator('#ci-principal').fill('1000');
  await page.locator('#ci-rate').fill('12');
  await page.locator('#ci-years').fill('1.1');
  await page.locator('#ci-monthly').fill('100');
  await page.locator('#ci-frequency').selectOption('4');
  await page.locator('#calc-form-compound [data-calc-run]').dispatchEvent('click');

  // Results are live, so filling the fields one by one can send earlier requests; the last one carries every input.
  await expect.poll(() => calls.at(-1)?.compound_freq).toBe(4);
  expect(calls.at(-1)).toEqual({
    principal: 1000,
    annual_rate: 12,
    years: 1.1,
    monthly_contribution: 100,
    compound_freq: 4,
  });
  await expect(page.locator('#ci-result')).toContainText('$2,521.72');
  await expect(page.locator('#ci-result')).toContainText('$2,300.00');
  await expect(page.locator('#ci-result')).toContainText('$221.72');
  await expect(page.locator('#ci-result [data-compound-assumptions]')).toContainText('Quarterly');
  await expect(page.locator('#ci-result [data-compound-assumptions]')).toContainText('month-end');
  await expect(page.locator('#ci-result [data-compound-assumptions]')).toContainText('interest only');
  await page.locator('#ci-result details summary').click();
  await expect(page.locator('#ci-result [data-growth-history] tbody tr')).toHaveCount(2);
  await expect(page.locator('#ci-result [data-growth-history] tbody tr').last()).toContainText('1.1');
  await expect(page.locator('#ci-result [data-growth-history] tbody tr').last()).toContainText('$2,521.72');
  const historyTable = page.locator('#ci-result [data-growth-history]');
  expect(await historyTable.evaluate(table => table.scrollWidth <= table.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('compound-growth-result.png'), fullPage: true });
});

test('compound growth enforces visible API bounds and saves frequency with the exact result', async ({ page }) => {
  await expect(page.locator('#ci-principal')).toHaveAttribute('max', '1000000000000');
  await expect(page.locator('#ci-rate')).toHaveAttribute('min', '-100');
  await expect(page.locator('#ci-rate')).toHaveAttribute('max', '1000');
  await expect(page.locator('#ci-years')).toHaveAttribute('max', '100');
  await expect(page.locator('#ci-monthly')).toHaveAttribute('max', '1000000000000');

  await page.locator('#ci-principal').fill('1000');
  await page.locator('#ci-rate').fill('-100');
  await page.locator('#ci-years').fill('1.1');
  await page.locator('#ci-monthly').fill('100');
  await page.locator('#ci-frequency').selectOption('4');
  // Let the live runs for the earlier edits finish, then check the out-of-range rate is refused before any request.
  await page.waitForTimeout(800);
  calls.length = 0;
  await page.locator('#calc-form-compound [data-calc-run]').dispatchEvent('click');
  expect(calls).toHaveLength(0);
  await expect(page.locator('#ci-rate')).toBeFocused();

  await page.locator('#ci-rate').fill('12');
  await expect.poll(() => calls.at(-1)?.annual_rate).toBe(12);
  await page.locator('#ci-result').getByRole('button', { name: 'Save result', exact: true }).click();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults[0]);
  expect(saved.inputs.compound_freq).toBe(4);
  expect(saved.result.growth_history.at(-1).year).toBe(1.1);
  expect(saved.result.assumptions.fractional_month).toBe('interest_only');

  const exportRequests = [];
  page.on('request', request => {
    if (request.url().includes('/api/export/result')) exportRequests.push(request.postDataJSON());
  });
  await page.locator('#ci-result [data-export-calculation]').click();
  await page.locator('#result-export-format').selectOption('json');
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download export', exact: true }).click();
  const download = await downloadReady;
  const report = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  expect(exportRequests).toHaveLength(1);
  for (const [name, value] of Object.entries(calls[0])) {
    expect(exportRequests[0].inputs.find(item => item.name === name).value).toBe(value);
  }
  expect(report.inputs.find(item => item.name === 'compound_freq').value).toBe(4);
  const history = report.tables.find(item => item.title === 'growth_history');
  expect(history.rows.at(-1)[history.columns.indexOf('year')]).toBe(1.1);
  expect(report.assumptions).toContain('fractional_month: interest_only');
});
