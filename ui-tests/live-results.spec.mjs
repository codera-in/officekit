import { expect, test } from '@playwright/test';

async function open(page) {
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
}

test('a calculator recalculates as keys are pressed, with no Calculate or Calculate again button', async ({ page }) => {
  await open(page);
  await page.evaluate(() => { switchTab('calculators'); switchCalc('cagr'); });
  const result = page.locator('#calc-cagr-result');
  await expect(result).toContainText('9.86%');
  await expect(page.locator('#calc-cagr-run')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Calculate again' })).toHaveCount(0);

  await page.locator('#calc-cagr-end').fill('20000');
  await expect(result).toContainText('14.87%');

  await page.locator('#calc-cagr-end').fill('');
  await expect(result).toContainText('Fill in every field to see the result.');
  await expect(page.locator('#calc-cagr-result [data-save-calculation]')).toHaveCount(0);

  await page.locator('#calc-cagr-end').fill('16000');
  await expect(result).toContainText('9.86%');
  await expect(page.locator('#calc-form-cagr [data-save-calculation]')).toBeVisible();
});

test('the System page keeps CPU and memory live without pressing Refresh', async ({ page }) => {
  await open(page);
  await page.evaluate(() => switchTab('system'));
  const status = page.locator('#system-resources-status');
  await expect(status).toContainText(/Live · updated/, { timeout: 8000 });
  const first = await status.textContent();
  await expect.poll(async () => status.textContent(), { timeout: 8000 }).not.toBe(first);
  // The live cards match the menu-bar panels: rings, a history graph and the memory breakdown, with no extra buttons.
  const cards = page.locator('#system-stat-cards');
  await expect(cards.locator('[data-stat-card="cpu"] .ok-ring').first()).toBeVisible({ timeout: 8000 });
  await expect(cards.locator('[data-stat-card="ram"]')).toContainText('Top processes');
  await expect(cards.locator('button')).toHaveCount(0);
});

test('a very large network rate is shown in a short unit', async ({ page }) => {
  await open(page);
  const text = await page.evaluate(() => [officekitFormatRate(9999999, false), officekitFormatRate(512, false), officekitFormatRate(5e10, true), officekitFormatRate(null, false)]);
  expect(text).toEqual(['9.5 MB/s', '512 B/s', '47G', '—']);
});
