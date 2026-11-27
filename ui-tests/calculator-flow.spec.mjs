import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { expectGalleryMatchesCatalog } from './gallery-count.mjs';

let externalRequests;
let errors;

test.beforeEach(async ({ context, page }) => {
  // Starter favorites are added once per profile; these tests start from an empty list.
  await page.addInitScript(() => localStorage.setItem('officekit.favorites.seeded.v1', '1'));
  externalRequests = [];
  errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      // Real backend, matching the desktop's bearer and trusted origin policy.
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
  await expectGalleryMatchesCatalog(page, expect);
  expect(externalRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test.afterEach(() => {
  expect(externalRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test('find, calculate, save, export and reopen an immutable result', async ({ page }, testInfo) => {
  const calculationRequests = [];
  page.on('request', request => {
    if (request.url().includes('/api/calculator/loan-emi')) calculationRequests.push(request.postDataJSON());
  });
  await page.locator('#tool-gallery-search').fill('loan emi');
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  await expect(card).toHaveCount(1);
  await card.locator('[data-open-tool]').click();
  await page.getByLabel('Loan Amount ($)', { exact: true }).fill('1200');
  await page.getByLabel('Interest Rate (%)', { exact: true }).fill('0');
  await page.getByLabel('Tenure (Years)', { exact: true }).fill('1');
  await page.locator('#calc-form-emi [data-calc-run]').dispatchEvent('click');
  await expect(page.locator('#emi-result')).toContainText('$100.00');
  const resultActions = page.locator('#emi-result .officekit-result-actions');
  expect(await resultActions.evaluate(element => element.parentElement.lastElementChild === element)).toBe(true);
  // Result actions sit in the card under the result, not in a docked bar (decision 20, option A).
  await expect(resultActions).toHaveCSS('position', 'static');
  expect(await resultActions.evaluate(element => element.closest('.calc-card') !== null)).toBe(true);
  await expect(page.locator('#officekit-tool-actions')).toBeHidden();
  expect(calculationRequests.at(-1)).toEqual({ principal: 1200, annual_interest_rate: 0, tenure_years: 1 });
  await page.getByRole('button', { name: 'Save result', exact: true }).click();
  await expect(page.locator('[data-calculation-action-status]')).toContainText('Saved');

  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('[data-saved-result]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Open result', exact: true }).click();
  await expect(page.locator('#saved-result-detail-content [data-result-field="monthly_emi"]')).toHaveText('$100.00');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults[0].result.monthly_emi)).toBe(100);
  // One request for the default values when the form opened, one for the values typed.
  expect(calculationRequests).toHaveLength(2);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: testInfo.outputPath('saved-result.png'), fullPage: true });

  await page.locator('#saved-result-detail-content .officekit-result-actions').getByRole('button', { name: 'Download', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Export result', exact: true })).toBeVisible();
  await page.locator('#result-export-format').selectOption('markdown');
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download export', exact: true }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  const markdown = await fs.readFile(await download.path(), 'utf8');
  expect(markdown).toContain('Loan EMI calculation');
  expect(markdown).toContain('100');
  expect(markdown).toContain('officekit.app');
  await page.getByRole('button', { name: 'Close export dialog', exact: true }).click();

  await page.reload();
  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('[data-saved-result]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Open result', exact: true }).click();
  await expect(page.locator('#saved-result-detail-content [data-result-field="monthly_emi"]')).toHaveText('$100.00');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults[0].result.monthly_emi)).toBe(100);
  // One request for the default values when the form opened, one for the values typed.
  expect(calculationRequests).toHaveLength(2);
});

test('freelance rate calculation exposes expenses and preserves them with disclosed assumptions', async ({ page }, testInfo) => {
  const requests = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/calculator/freelance-rate')) requests.push(request.postDataJSON());
  });
  await page.locator('#tool-gallery-search').fill('freelance rate');
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="freelance_rate"]') });
  await expect(card).toHaveCount(1);
  await card.locator('[data-open-tool]').click();
  await page.getByLabel('Business Expenses / Year ($)', { exact: true }).fill('5000');
  await page.locator('#calc-form-freelance [data-calc-run]').dispatchEvent('click');

  const result = page.locator('#free-result');
  await expect(result).toContainText('$93.06 / hr');
  await expect(result).toContainText('$465.28 / day');
  await expect(result).toContainText('$111,666.67');
  await expect(result.locator('[data-freelance-assumptions]')).toContainText('$5,000.00 annual business expenses');
  await expect(result.locator('[data-freelance-assumptions]')).toContainText('48 working weeks');
  const exportButton = result.locator('[data-export-calculation]');
  const saveButton = result.locator('[data-save-calculation]');
  await expect(exportButton).toHaveClass(/bg-indigo-600/);
  await expect(saveButton).toHaveClass(/bg-white/);
  expect(await saveButton.evaluate(element => element.nextElementSibling?.matches('[data-export-calculation]'))).toBe(true);
  await result.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('freelance-rate-result.png') });
  // Results are live, so earlier edits may also have been calculated; the last request carries the final inputs.
  expect(requests.at(-1)).toEqual({ target_annual_take_home: 80000, billable_hours_per_week: 25, vacation_weeks: 4, business_expenses_annual: 5000, tax_rate_percent: 25 });

  await result.getByRole('button', { name: 'Save result', exact: true }).click();
  await page.locator('#free-expenses').fill('1');
  await page.locator('[data-sidebar-tab="activity"]').click();
  await page.getByRole('button', { name: 'Reuse inputs', exact: true }).click();
  await expect(page.locator('#free-expenses')).toHaveValue('5000');
  expect(requests.at(-1).business_expenses_annual).toBe(5000);
});

test('everyday percentage modes use local APIs and saved results retain their operation', async ({ page }) => {
  const requests = [];
  page.on('request', request => {
    if (['/api/calculator/percent-of', '/api/calculator/percentage-change', '/api/calculator/discount'].some(path => request.url().includes(path))) requests.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
  });
  await page.locator('#tool-gallery-search').fill('percentage change');
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="everyday_percentages"]') });
  await expect(card).toHaveCount(1);
  await card.locator('[data-open-tool]').click();
  await expect(page.locator('#calc-form-percentages')).toBeVisible();
  await page.locator('#percentage-percent').fill('15');
  await page.locator('#percentage-value').fill('240');
  await page.locator('#percentages-run').dispatchEvent('click');
  await expect(page.locator('#percentages-result')).toContainText('36.00');
  await page.getByRole('button', { name: 'Save result', exact: true }).click();
  await expect(page.locator('[data-calculation-action-status]')).toContainText('Saved');

  await page.locator('#percentage-mode').selectOption('percentage_change');
  await page.locator('#percentage-original').fill('80');
  await page.locator('#percentage-new').fill('100');
  await page.locator('#percentages-run').dispatchEvent('click');
  await expect(page.locator('#percentages-result')).toContainText('+25.00%');
  await page.locator('#percentage-mode').selectOption('discount');
  await page.locator('#percentage-price').fill('100');
  await page.locator('#percentage-discount').fill('20');
  await page.locator('#percentages-run').dispatchEvent('click');
  await expect(page.locator('#percentages-result')).toContainText('20.00');
  await expect(page.locator('#percentages-result')).toContainText('80.00');
  // Results are live, so typing several fields can send more than one request per mode; the last one per mode is what the user sees.
  const lastPerPath = Object.fromEntries(requests.map(request => [request.path, request.body]));
  expect(lastPerPath).toEqual({
    '/api/calculator/percent-of': { percent: 15, value: 240 },
    '/api/calculator/percentage-change': { original_value: 80, new_value: 100 },
    '/api/calculator/discount': { price: 100, discount_percent: 20 },
  });

  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('[data-saved-result]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Open result', exact: true }).click();
  await expect(page.locator('#saved-result-detail-content')).toContainText('36');
  await page.locator('#saved-result-detail-reuse').click();
  await expect(page.locator('#percentage-mode')).toHaveValue('percent_of');
  await expect(page.locator('#percentage-percent')).toHaveValue('15');
  await expect(page.locator('#percentage-value')).toHaveValue('240');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults[0].inputs.operation)).toBe('percent_of');
  expect(requests.length).toBeGreaterThanOrEqual(3);
});

test('loan EMI schedule pages on compact screens and saved JSON retains every month', async ({ page }) => {
  const calculationRequests = [];
  page.on('request', request => {
    if (request.url().includes('/api/calculator/loan-emi')) calculationRequests.push(request.postDataJSON());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#sidebar-toggle').click();
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  await card.locator('[data-open-tool]').click();
  await page.getByLabel('Loan Amount ($)', { exact: true }).fill('2400');
  await page.getByLabel('Interest Rate (%)', { exact: true }).fill('12');
  await page.getByLabel('Tenure (Years)', { exact: true }).fill('2');
  await page.locator('#calc-form-emi [data-calc-run]').dispatchEvent('click');

  const schedule = page.locator('[data-loan-schedule]');
  await expect(schedule.locator('tbody tr')).toHaveCount(12);
  await expect(page.locator('#loan-schedule-range')).toHaveText('Months 1–12 of 24');
  await expect(schedule.locator('tbody tr').first()).toContainText('1');
  await page.getByRole('button', { name: 'Next 12 months', exact: true }).click();
  await expect(page.locator('#loan-schedule-range')).toHaveText('Months 13–24 of 24');
  await expect(schedule.locator('tbody tr')).toHaveCount(12);
  await expect(schedule.locator('tbody tr').last()).toContainText('24');
  await expect(page.getByRole('button', { name: 'Next 12 months', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Previous 12 months', exact: true }).click();
  await expect(page.locator('#loan-schedule-range')).toHaveText('Months 1–12 of 24');

  const pageMetrics = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, width: innerWidth }));
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(node => node.getBoundingClientRect().right > innerWidth + 2).map(node => ({tag:node.tagName,id:node.id,classes:String(node.className).slice(0,100),left:Math.round(node.getBoundingClientRect().left),right:Math.round(node.getBoundingClientRect().right),width:node.clientWidth})).slice(0,20));
  expect(pageMetrics.scrollWidth,JSON.stringify(overflow)).toBeLessThanOrEqual(pageMetrics.width);
  await page.getByRole('button', { name: 'Save result', exact: true }).click();
  await expect(page.locator('[data-calculation-action-status]')).toContainText('Saved');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults[0].result.schedule.length)).toBe(24);
  expect(calculationRequests.at(-1)).toEqual({ principal: 2400, annual_interest_rate: 12, tenure_years: 2 });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('[data-sidebar-tab="activity"]').click();
  await page.getByRole('button', { name: 'Open result', exact: true }).click();
  await page.locator('#saved-result-detail-content .officekit-result-actions').getByRole('button', { name: 'Download', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Export result', exact: true })).toBeVisible();
  await page.locator('#result-export-format').selectOption('json');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download export', exact: true }).click();
  const download = await downloadPromise;
  const exported = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  expect(exported.tables).toHaveLength(1);
  expect(exported.tables[0].rows).toHaveLength(24);
  expect(exported.tables[0].rows.at(-1)[4]).toBe(0);
  // One request for the default values when the form opened, one for the values typed.
  expect(calculationRequests).toHaveLength(2);
});

test('gallery remains readable at supported desktop widths', async ({ page }, testInfo) => {
  await expect(page.locator('#officekit-brand-mark')).toBeVisible();
  const sizes = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
  expect(sizes.scroll).toBeLessThanOrEqual(sizes.width);
  await page.screenshot({ path: testInfo.outputPath('tool-gallery.png'), fullPage: true });
});

const reuseCases = [
  { tool: 'loan_emi', form: 'emi', runName: 'Calculate EMI', result: 'emi-result', fields: { 'emi-principal': '2400', 'emi-rate': '0', 'emi-years': '2' } },
  { tool: 'compound_interest', form: 'compound', runName: 'Calculate Wealth Growth', result: 'ci-result', fields: { 'ci-principal': '1400', 'ci-rate': '8', 'ci-years': '3', 'ci-monthly': '25' } },
  { tool: 'vat_salestax', form: 'vat', runName: 'Calculate Tax', result: 'vat-result', fields: { 'vat-amount': '150', 'vat-rate': '12' } },
  { tool: 'freelance_rate', form: 'freelance', runName: 'Calculate Hourly Rate', result: 'free-result', fields: { 'free-target': '55000', 'free-hours': '25', 'free-vacation': '5', 'free-tax': '15', 'free-expenses': '12000' } },
  { tool: 'math_eval', form: 'scientific', run: 'math-run', result: 'math-result', fields: { 'math-expression': '6 * 7', 'math-angle-mode': 'degrees' } },
  { tool: 'units_convert', form: 'units', run: 'unit-run', result: 'unit-result', fields: { 'unit-value': '2.5', 'unit-category': 'length', 'unit-from': 'meter', 'unit-to': 'centimeter' } },
  { tool: 'margin_markup', form: 'margin', run: 'margin-run', result: 'margin-result', fields: { 'margin-cost': '73', 'margin-revenue': '101' } },
  { tool: 'break_even', form: 'break-even', run: 'break-run', result: 'break-result', fields: { 'break-fixed': '1234', 'break-price': '55', 'break-cost': '21' } },
  { tool: 'simple_interest', form: 'simple-interest', run: 'simple-run', result: 'simple-result', fields: { 'simple-principal': '1400', 'simple-rate': '8', 'simple-time': '18', 'simple-unit': 'months' } },
  { tool: 'depreciation', form: 'depreciation', run: 'depreciation-run', result: 'depreciation-result', fields: { 'depreciation-cost': '15000', 'depreciation-salvage': '1500', 'depreciation-life': '5' } },
  // The 13 pending calculators (C06-C07, C15-C25): each form restores from its saved result without recalculating.
  { tool: 'roi', form: 'roi', run: 'calc-roi-run', result: 'calc-roi-result', fields: { 'calc-roi-invested': '1000', 'calc-roi-returned': '1250', 'calc-roi-fees': '25' } },
  { tool: 'cagr', form: 'cagr', run: 'calc-cagr-run', result: 'calc-cagr-result', fields: { 'calc-cagr-start': '10000', 'calc-cagr-end': '16000', 'calc-cagr-years': '5' } },
  { tool: 'weighted_average', form: 'average', run: 'calc-average-run', result: 'calc-average-result', fields: { 'calc-average-values': '12, 15, 9' }, restored: { 'calc-average-values': '12\n15\n9' } },
  { tool: 'fractions_ratios', form: 'fractions', run: 'calc-fractions-run', result: 'calc-fractions-result', fields: { 'calc-fractions-left-num': '1', 'calc-fractions-left-den': '3', 'calc-fractions-right-num': '1', 'calc-fractions-right-den': '6' } },
  { tool: 'gcd_lcm', form: 'gcd-lcm', run: 'calc-gcd-lcm-run', result: 'calc-gcd-lcm-result', fields: { 'calc-gcd-lcm-integers': '48, 180, 36' }, restored: { 'calc-gcd-lcm-integers': '48\n180\n36' } },
  { tool: 'descriptive_statistics', form: 'statistics', run: 'calc-statistics-run', result: 'calc-statistics-result', fields: { 'calc-statistics-values': '2, 4, 4, 4, 5, 5, 7, 9' }, restored: { 'calc-statistics-values': '2\n4\n4\n4\n5\n5\n7\n9' } },
  { tool: 'date_difference', form: 'date-difference', run: 'calc-date-difference-run', result: 'calc-date-difference-result', fields: { 'calc-date-difference-start': '2024-01-31', 'calc-date-difference-end': '2025-03-01' } },
  { tool: 'age_calculator', form: 'age', run: 'calc-age-run', result: 'calc-age-result', fields: { 'calc-age-birth': '1990-06-15', 'calc-age-as-of': '2026-10-22' } },
  { tool: 'business_days', form: 'business-days', run: 'calc-business-days-run', result: 'calc-business-days-result', fields: { 'calc-business-days-start': '2026-12-21', 'calc-business-days-end': '2027-01-08' } },
  { tool: 'work_hours', form: 'work-hours', run: 'calc-work-hours-run', result: 'calc-work-hours-result', fields: { 'calc-work-hours-rows': '2026-03-02 09:00 17:30 30' } },
  { tool: 'time_zone_converter', form: 'time-zones', run: 'calc-time-zones-run', result: 'calc-time-zones-result', fields: { 'calc-time-zones-date': '2026-03-08', 'calc-time-zones-time': '12:00', 'calc-time-zones-from': 'America/New_York', 'calc-time-zones-to': 'Europe/London' } },
  { tool: 'quadratic_solver', form: 'quadratic', run: 'calc-quadratic-run', result: 'calc-quadratic-result', fields: { 'calc-quadratic-a': '1', 'calc-quadratic-b': '-3', 'calc-quadratic-c': '2' } },
  { tool: 'geometry', form: 'geometry', run: 'calc-geometry-run', result: 'calc-geometry-result', fields: { 'calc-geometry-shape': 'circle', 'calc-geometry-dim-1': '2' } },
];

for (const entry of reuseCases) {
  test(`saved ${entry.tool} inputs restore without recalculation`, async ({ page }) => {
    let calculations = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && /\/api\/(math\/eval|units\/convert|calculator\/)/.test(request.url())) calculations += 1;
    });
    const card = page.locator('#tool-gallery-results article').filter({ has: page.locator(`[data-open-tool="${entry.tool}"]`) });
    await card.locator('[data-open-tool]').click();
    for (const [id, value] of Object.entries(entry.fields)) {
      const input = page.locator(`#${id}`);
      await expect(input).toBeEnabled();
      if (await input.evaluate(element => element.tagName === 'SELECT')) await input.selectOption(value);
      else await input.fill(value);
    }
    if (entry.run) await page.locator(`#${entry.run}`).dispatchEvent('click');
    else await page.locator(`#calc-form-${entry.form} [data-calc-run]`).dispatchEvent('click');
    await page.locator(`#${entry.result}`).getByRole('button', { name: 'Save result', exact: true }).click();
    // Alter live form state so merely navigating back cannot satisfy restoration.
    const firstId = Object.keys(entry.fields)[0];
    const first = page.locator(`#${firstId}`);
    const kind = await first.evaluate(element => (element.tagName === 'SELECT' ? 'select' : element.type || 'text'));
    if (kind === 'select') await first.selectOption({ index: 1 });
    else await first.fill(kind === 'date' ? '2000-01-01' : kind === 'time' ? '01:00' : '1');
    await page.locator('[data-sidebar-tab="activity"]').click();
    await page.getByRole('button', { name: 'Reuse inputs', exact: true }).click();
    await expect(page.locator(`#calc-form-${entry.form}`)).toBeVisible();
    // List fields restore one value per line, the form the app writes; `restored` names that form when it differs from the typed text.
    for (const [id, value] of Object.entries(entry.fields)) await expect(page.locator(`#${id}`)).toHaveValue(entry.restored?.[id] ?? value);
    // Results are live: reopening the form may recalculate the restored inputs.
    expect(calculations).toBeGreaterThanOrEqual(1);
  });
}

test('margin and markup displays negative half-cent money with half-up rounding', async ({ page }) => {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="margin_markup"]') });
  await card.locator('[data-open-tool]').click();
  await page.locator('#margin-cost').fill('1.25');
  await page.locator('#margin-revenue').fill('1.125');
  await page.locator('#margin-run').dispatchEvent('click');

  const result = page.locator('#margin-result');
  await expect(result).toContainText('Profit');
  await expect(result).toContainText('-0.13');
  await expect(result).toContainText('-11.11%');
  await expect(result).toContainText('-10%');
});

test('VAT results disclose user-supplied rate and rounding assumptions and reject malformed responses', async ({ page }) => {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="vat_salestax"]') });
  await card.locator('[data-open-tool]').click();
  await expect(page.getByLabel('Amount (currency units)', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Tax Rate (%) · supplied by you', { exact: true })).toBeVisible();
  await page.locator('#vat-amount').fill('19.99');
  await page.locator('#vat-rate').fill('7.5');
  await page.locator('#calc-form-vat [data-calc-run]').dispatchEvent('click');
  const result = page.locator('#vat-result');
  await expect(result).toContainText('19.99');
  await expect(result).toContainText('1.50');
  await expect(result).toContainText('21.49');
  await expect(result.locator('[data-vat-assumptions]')).toContainText('Rate supplied by you');
  await expect(result.locator('[data-vat-assumptions]')).toContainText('Jurisdiction not specified');
  await expect(result.locator('[data-vat-assumptions]')).toContainText('half-up to 2 decimal places');
  await expect(result.getByRole('button', { name: 'Save result', exact: true })).toBeVisible();

  await page.locator('#vat-inclusive').check();
  await page.locator('#vat-amount').fill('21.49');
  await page.locator('#calc-form-vat [data-calc-run]').dispatchEvent('click');
  await expect(result).toContainText('Net Amount');
  await expect(result).toContainText('19.99');
  await expect(result).toContainText('Gross Amount');
  await expect(result).toContainText('21.49');

  await page.locator('#vat-inclusive').uncheck();
  await page.locator('#vat-amount').fill('19.99');
  await page.locator('#vat-rate').fill('0');
  await page.locator('#calc-form-vat [data-calc-run]').dispatchEvent('click');
  await expect(result).toContainText('Tax (0%)');
  await expect(result).toContainText('0.00');
  await expect(result).toContainText('19.99');

  await page.locator('#vat-amount').fill('1');
  await page.locator('#vat-rate').fill('1000');
  await page.locator('#calc-form-vat [data-calc-run]').dispatchEvent('click');
  await expect(result).toContainText('Tax (1000%)');
  await expect(result).toContainText('10.00');
  await expect(result).toContainText('11.00');

  await page.route('**/api/calculator/vat-sales-tax', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ net_amount: 19.99, tax_amount: 1.5, gross_amount: 21.49, tax_rate_percent: 7.5, is_inclusive: true, assumptions: {} }),
  }));
  await page.locator('#calc-form-vat [data-calc-run]').dispatchEvent('click');
  await expect(result).toContainText('OfficeKit returned an invalid tax calculation result');
  await expect(result.getByRole('button', { name: 'Save result', exact: true })).toHaveCount(0);
});

test('all nine share formats download real files with optional attribution', async ({ page }) => {
  const requests = [];
  page.on('request', request => {
    if (request.url().includes('/api/export/result')) requests.push(request.postDataJSON());
  });
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  await card.locator('[data-open-tool]').click();
  await page.locator('#emi-principal').fill('1200');
  await page.locator('#emi-rate').fill('0');
  await page.locator('#emi-years').fill('1');
  await page.locator('#calc-form-emi [data-calc-run]').dispatchEvent('click');
  await page.locator('#emi-result .officekit-result-actions').getByRole('button', { name: 'Download…', exact: true }).click();
  for (const [format, extension, signature] of [
    ['markdown', 'md'], ['html', 'html'], ['json', 'json'], ['csv', 'csv'],
    ['xlsx', 'xlsx', '504b0304'], ['pptx', 'pptx', '504b0304'],
    ['pdf', 'pdf', '255044462d'], ['png', 'png', '89504e470d0a1a0a'], ['jpeg', 'jpg', 'ffd8'],
  ]) {
    await page.locator('#result-export-format').selectOption(format);
    await page.locator('#result-export-attribution').setChecked(format !== 'json');
    const waiting = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download export', exact: true }).click();
    const download = await waiting;
    expect(download.suggestedFilename()).toBe(`calculator.loan-emi-result.${extension}`);
    const bytes = await fs.readFile(await download.path());
    expect(bytes.length).toBeGreaterThan(0);
    if (signature) expect(bytes.subarray(0, signature.length / 2).toString('hex')).toBe(signature);
    else if (format === 'json') {
      const report = JSON.parse(bytes.toString('utf8'));
      expect(report.schema_version).toBe('officekit.result.v1');
      expect(report.results.find(field => field.name === 'monthly_emi').value).toBe(100);
      expect(bytes.toString('utf8')).not.toContain('Generated with OfficeKit');
    } else expect(bytes.toString('utf8')).toContain('officekit.app');
    expect(requests.at(-1).include_attribution).toBe(format !== 'json');
    expect(requests.at(-1).tables[0].rows).toHaveLength(12);
  }
  expect(requests).toHaveLength(9);
});

test('favorite tools and recent destinations survive reload', async ({ page }) => {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  await card.locator('[data-favorite-tool="loan_emi"]').click();
  await page.locator('[data-sidebar-tab="favorites"]').click();
  await expect(page.locator('#favorite-tool-results [data-open-tool="loan_emi"]')).toHaveCount(1);
  await page.locator('#favorite-tool-results [data-open-tool="loan_emi"]').click();
  await expect(page.locator('#calc-form-emi')).toBeVisible();
  await page.reload();
  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('#recent-tool-results [data-open-tool="loan_emi"]')).toHaveCount(1);
  await page.locator('[data-sidebar-tab="favorites"]').click();
  await expect(page.locator('#favorite-tool-results [data-open-tool="loan_emi"]')).toHaveCount(1);
  await page.locator('#favorite-tool-results [data-favorite-tool="loan_emi"]').click();
  await expect(page.locator('#favorite-tool-results [data-open-tool="loan_emi"]')).toHaveCount(0);
});

test('unit reuse waits for the catalogue and reports an unavailable catalogue honestly', async ({ page }) => {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="units_convert"]') });
  await card.locator('[data-open-tool]').click();
  await expect(page.locator('#unit-run')).toBeEnabled();
  await page.locator('#unit-value').fill('2.5');
  await page.locator('#unit-from').selectOption('meter');
  await page.locator('#unit-to').selectOption('centimeter');
  await page.locator('#unit-run').dispatchEvent('click');
  await page.locator('#unit-result').getByRole('button', { name: 'Save result', exact: true }).click();
  await page.reload();
  // Reload clears the in-memory catalogue while retaining the saved snapshot.
  await page.route('**/api/units/catalog', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Catalogue unavailable"}' }));
  await page.locator('[data-sidebar-tab="activity"]').click();
  await page.getByRole('button', { name: 'Reuse inputs', exact: true }).click();
  await expect(page.locator('#unit-catalog-status')).toContainText('Saved unit choices could not be restored');
  await expect(page.locator('#unit-run')).toBeDisabled();
  await expect(page.locator('#unit-value')).toHaveValue('5.6');
  await expect(page.locator('#record-store-notice-text')).not.toContainText('Saved inputs loaded');
});

test('saved results show original labeled metrics, inputs and one complete schedule', async ({ page }) => {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  await card.locator('[data-open-tool]').click();
  await page.locator('#emi-principal').fill('1200');
  await page.locator('#emi-rate').fill('0');
  await page.locator('#emi-years').fill('1');
  await page.locator('#calc-form-emi [data-calc-run]').dispatchEvent('click');
  await page.getByRole('button', { name: 'Save result', exact: true }).click();
  await page.locator('[data-sidebar-tab="activity"]').click();
  await page.getByRole('button', { name: 'Open result', exact: true }).click();
  const detail = page.locator('#saved-result-detail-content');
  await expect(detail.locator('[data-result-field="monthly_emi"]')).toHaveText('$100.00');
  await expect(detail.locator('[data-input-field="principal"]')).toHaveText('$1,200.00');
  await expect(detail.getByRole('heading', { name: 'Inputs used', exact: true })).toBeVisible();
  await expect(detail.getByRole('table')).toHaveCount(1);
  await expect(detail.getByRole('table').locator('tbody tr')).toHaveCount(12);
  await expect(detail.locator('pre')).toHaveCount(0);
});

test('list, favorite and recent controls have separate targets and live favorite state', async ({ page }) => {
  await page.locator('[data-gallery-view="list"]').click();
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator('[data-open-tool="loan_emi"]') });
  async function expectSeparate(row) {
    const open = await row.locator('[data-open-tool="loan_emi"]').boundingBox();
    const star = await row.locator('[data-favorite-tool="loan_emi"]').boundingBox();
    expect(open).not.toBeNull();
    expect(star).not.toBeNull();
    const overlap = Math.min(open.x + open.width, star.x + star.width) - Math.max(open.x, star.x);
    expect(overlap).toBeLessThanOrEqual(0);
  }
  await expectSeparate(card);
  await card.locator('[data-favorite-tool="loan_emi"]').click();
  await page.locator('[data-sidebar-tab="favorites"]').click();
  const favorite = page.locator('#favorite-tool-results article');
  await expectSeparate(favorite);
  await favorite.locator('[data-open-tool="loan_emi"]').click();
  await page.locator('[data-sidebar-tab="activity"]').click();
  const recent = page.locator('#recent-tool-results article');
  await expectSeparate(recent);
  await recent.locator('[data-favorite-tool="loan_emi"]').click();
  await expect(recent.locator('[data-favorite-tool="loan_emi"]')).toHaveAttribute('aria-pressed', 'false');
});

async function openGalleryTool(page, toolId) {
  const card = page.locator('#tool-gallery-results article').filter({ has: page.locator(`[data-open-tool="${toolId}"]`) });
  await card.locator('[data-open-tool]').click();
}

test('release candidate JSON/YAML formatter downloads exact data and recovers from duplicate keys', async ({ page }) => {
  await openGalleryTool(page, 'devtools_format');
  await expect(page.locator('#developer-tools-operation')).toHaveValue('format_json');
  await page.locator('#developer-tools-input').fill('{"id":"001","count":2}');
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue(/"001"/);
  await expect(page.locator('#developer-tools-download')).toBeEnabled();
  const waiting = page.waitForEvent('download');
  await page.locator('#developer-tools-download').click();
  const download = await waiting;
  expect(JSON.parse(await fs.readFile(await download.path(), 'utf8'))).toEqual({ id: '001', count: 2 });
  await page.locator('#developer-tools-operation').selectOption('json_to_yaml');
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue(/count: 2/);
  const yaml = await page.locator('#developer-tools-output').inputValue();
  await page.locator('#developer-tools-operation').selectOption('yaml_to_json');
  await page.locator('#developer-tools-input').fill(yaml);
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue(/"001"/);
  await page.locator('#developer-tools-operation').selectOption('format_json');
  await page.locator('#developer-tools-input').fill('{"id":1}');
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-download')).toBeEnabled();
  await page.locator('#developer-tools-input').fill('{"id":1,"id":2}');
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-status')).not.toHaveText('Processing on this computer…');
  await expect(page.locator('#developer-tools-output')).toHaveValue('');
  await expect(page.locator('#developer-tools-download')).toBeDisabled();
});

test('release candidate JWT opens inspection mode and never retains token content', async ({ page }) => {
  await openGalleryTool(page, 'jwt_inspector');
  await expect(page.locator('#developer-tools-operation')).toHaveValue('decode_jwt');
  await expect(page.locator('#developer-tools-secret-label')).toBeHidden();
  const token = `${Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url')}.${Buffer.from('{"sub":"test-subject-9281"}').toString('base64url')}.eA`;
  await page.locator('#developer-tools-input').fill(token);
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue(/test-subject-9281/);
  await expect(page.locator('#developer-tools-status')).toContainText('Signature not verified');
  const storage = await page.evaluate(() => JSON.stringify(localStorage));
  expect(storage).not.toContain(token);
  expect(storage).not.toContain('test-subject-9281');
  await page.locator('#developer-tools-clear').click();
  await expect(page.locator('#developer-tools-input')).toHaveValue('');
});

test('release candidate hashes opens hash mode and matches independent SHA-256', async ({ page }) => {
  await openGalleryTool(page, 'crypto_hashes');
  await expect(page.locator('#developer-tools-operation')).toHaveValue('hashes');
  const input = 'OfficeKit\nதமிழ்';
  await page.locator('#developer-tools-input').fill(input);
  await page.locator('#developer-tools-run').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue(new RegExp(createHash('sha256').update(input).digest('hex')));
  await page.locator('#developer-tools-clear').click();
  await expect(page.locator('#developer-tools-output')).toHaveValue('');
});

test('release candidate URL codec preserves Unicode and rejects malformed escapes', async ({ page }) => {
  await openGalleryTool(page, 'url_codec');
  await page.locator('#url-codec-input').fill('café / தமிழ் & +');
  await page.locator('#url-codec-run').click();
  await expect(page.locator('#url-codec-output')).toHaveValue(encodeURIComponent('café / தமிழ் & +'));
  const encoded = await page.locator('#url-codec-output').inputValue();
  await page.locator('#url-codec-mode-decode').click();
  await page.locator('#url-codec-input').fill(encoded);
  await page.locator('#url-codec-run').click();
  await expect(page.locator('#url-codec-output')).toHaveValue('café / தமிழ் & +');
  await page.locator('#url-codec-input').fill('%GG');
  await page.locator('#url-codec-run').click();
  await expect(page.locator('#url-codec-output')).toHaveValue('');
  await expect(page.locator('#url-codec-status')).toContainText('Check percent escapes');
});

test('release candidate color conversion handles alpha and clears an invalid result', async ({ page }) => {
  await openGalleryTool(page, 'color_converter');
  await page.locator('#color-input').fill('#ff000080');
  await page.locator('#color-convert-button').click();
  await expect(page.locator('#color-output')).toHaveText(/rgba\(255, 0, 0, 0\.502\)/);
  await page.locator('#color-input').fill('not a color');
  await page.locator('#color-convert-button').click();
  await expect(page.locator('#color-copy-button')).toBeDisabled();
});

test('unit converter exposes every engine category and preserves bit/byte meaning at boundaries', async ({ page }) => {
  await openGalleryTool(page, 'units_convert');
  const category = page.locator('#unit-category');
  await expect(category).toBeEnabled();
  const categoryValues = await category.locator('option').evaluateAll(options => options.map(option => option.value));
  expect(categoryValues).toHaveLength(15);
  expect(categoryValues).toEqual(expect.arrayContaining([
    'length', 'area', 'volume', 'mass', 'speed', 'time', 'energy', 'power', 'pressure',
    'force', 'frequency', 'angle', 'digital_storage', 'temperature', 'typography',
  ]));

  await category.selectOption('digital_storage');
  const from = page.locator('#unit-from');
  const to = page.locator('#unit-to');
  await expect(from.locator('option[value="MB"]')).toHaveText('MB');
  await expect(from.locator('option[value="Mb"]')).toHaveText('Mb');
  await expect(from.locator('option[value="byte"]')).toHaveText('byte');
  await expect(from.locator('option[value="bit"]')).toHaveText('bit');
  await page.locator('#unit-value').fill('8');
  await from.selectOption('bit');
  await to.selectOption('byte');
  await page.locator('#unit-run').dispatchEvent('click');
  await expect(page.locator('#unit-result')).toContainText('8 bit = 1 byte');

  await category.selectOption('temperature');
  await page.locator('#unit-value').fill('-0.001');
  await from.selectOption('kelvin');
  await to.selectOption('kelvin');
  await page.locator('#unit-run').dispatchEvent('click');
  await expect(page.locator('#unit-result')).toContainText('absolute zero');
  await page.locator('#unit-value').fill('0');
  await page.locator('#unit-run').dispatchEvent('click');
  await expect(page.locator('#unit-result')).toContainText('0 Kelvin (K) = 0 Kelvin (K)');
});

test('release candidate password and passphrase generation keeps secrets transient', async ({ page }) => {
  await openGalleryTool(page, 'password_generator');
  await page.locator('#password-length').fill('24');
  await page.locator('#password-symbols').uncheck();
  await page.locator('#password-generate-button').click();
  await expect(page.locator('#password-output')).toHaveText(/^[A-Za-z0-9]{24}$/);
  const password = await page.locator('#password-output').textContent();
  expect(password).toMatch(/[a-z]/);
  expect(password).toMatch(/[A-Z]/);
  expect(password).toMatch(/[0-9]/);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(password);
  await page.locator('#passphrase-mode-button').click();
  await page.locator('#passphrase-word-count').selectOption('6');
  await page.locator('#passphrase-separator').selectOption('_');
  await page.locator('#passphrase-generate-button').click();
  await expect(page.locator('#passphrase-output')).toHaveText(/^[a-z]+(?:-[a-z]+)?(?:_[a-z]+(?:-[a-z]+)?){5}$/);
  const passphrase = await page.locator('#passphrase-output').textContent();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(passphrase);
  await page.locator('#passphrase-clear-button').click();
  await expect(page.locator('#passphrase-copy-button')).toBeDisabled();
});

test('clicking a star favorites the tool at once, in gallery and list view', async ({ page }) => {
  for (const view of ['gallery', 'list']) {
    await page.locator(`[data-gallery-view="${view}"]`).click();
    for (const toolId of ['media_toolkit', 'pdf_compress']) {
      const star = page.locator(`#tool-gallery-results [data-favorite-tool="${toolId}"]`);
      const wasPressed = await star.getAttribute('aria-pressed');
      await star.click();
      await expect(star).toHaveAttribute('aria-pressed', wasPressed === 'true' ? 'false' : 'true');
      const color = await star.evaluate(el => getComputedStyle(el).color);
      expect(color === 'rgb(245, 158, 11)').toBe(wasPressed !== 'true');
    }
  }
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).favorites);
  expect(stored).toEqual([]);
});

test('starring a recent tool on Home updates the Favorites list at once', async ({ page }) => {
  await page.evaluate(() => officekitRecordStore.recordRecent('loan_emi'));
  await page.locator('[data-sidebar-tab="home"]').click();
  const recent = page.locator('#tool-gallery-recent [data-favorite-tool="loan_emi"]');
  await recent.click();
  await expect(page.locator('#tool-gallery-favorites [data-open-tool="loan_emi"]')).toHaveCount(1);
  await expect(page.locator('#tool-gallery-recent [data-favorite-tool="loan_emi"]')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#tool-gallery-favorites [data-favorite-tool="loan_emi"]').click();
  await expect(page.locator('#tool-gallery-favorites [data-open-tool="loan_emi"]')).toHaveCount(0);
  await expect(page.locator('#tool-gallery-recent [data-favorite-tool="loan_emi"]')).toHaveAttribute('aria-pressed', 'false');
});

test('the category drop-down keeps its label clear of the arrow, and an on switch is filled', async ({ page }) => {
  for (const theme of ['light', 'dark']) {
    await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    const select = await page.locator('#tool-gallery-category').evaluate(el => {
      const style = getComputedStyle(el);
      return { right: parseFloat(style.paddingRight), width: el.getBoundingClientRect().width };
    });
    expect(select.right).toBeGreaterThanOrEqual(40);
    expect(select.width).toBeGreaterThanOrEqual(224);
    const colors = await page.evaluate(() => {
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'toggle toggle-primary toggle-sm';
      document.querySelector('#app-main').append(box);
      const off = getComputedStyle(box).backgroundColor;
      box.checked = true;
      const on = getComputedStyle(box).backgroundColor;
      const primary = getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim();
      box.remove();
      return { off, on, primary };
    });
    expect(colors.on).not.toBe(colors.off);
    expect(colors.on).not.toBe('rgba(0, 0, 0, 0)');
  }
});

test('every tool count on screen matches the catalogue this build offers', async ({ page }) => {
  const total = await page.evaluate(() => allToolsCache.length);
  await expect(page.locator('#catalog-capability-count')).toHaveText(String(total));
  await expect(page.locator('[data-tool-count="all"]')).toHaveText(String(total));
  await expect(page.locator('#tool-gallery-category option').first()).toHaveText(`All categories (${total})`);
  await expect(page.locator('#all-capabilities-count')).toHaveText(`Showing ${total} of ${total} tools`);
  await expect(page.locator('#tab-tools, #app-sidebar').first()).not.toContainText('124');
});

test('the catalog header has one category control that shows tool counts', async ({ page }) => {
  await expect(page.locator('#apple-category-pills')).toHaveCount(0);
  const options = await page.locator('#tool-gallery-category option').allTextContents();
  expect(options[0]).toMatch(/^All categories \(\d+\)$/);
  expect(options.slice(1).every(text => /\(\d+\)$/.test(text))).toBe(true);
  const total = Number(options[0].match(/\((\d+)\)/)[1]);
  const sum = options.slice(1).reduce((n, text) => n + Number(text.match(/\((\d+)\)$/)[1]), 0);
  expect(sum).toBe(total);
  await page.locator('#tool-gallery-category').selectOption({ index: 1 });
  await expect(page.locator('#tool-gallery-category')).not.toHaveValue('');
});
