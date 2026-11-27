import { test, expect } from '@playwright/test';


test('statement screen makes supported-layout and review limits clear at desktop and phone widths', async ({ context, page }) => {
  const externalRequests = [];
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
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
  expect(await page.evaluate(() => {
    switchTab('statement');
    return !document.getElementById('tab-statement').classList.contains('hidden');
  })).toBe(true);
  const statement = page.locator('#tab-statement');
  await expect(statement).toBeVisible();
  await expect(statement.getByRole('heading', { name: 'Bank Statement to CSV / Excel' })).toBeVisible();
  await expect(statement).toContainText('supported bank statement layouts');
  await expect(statement).toContainText('balance movements could be checked');
  await expect(statement).toContainText('Layout coverage varies');
  await expect(statement).not.toContainText('invoice');
  await expect(statement).not.toContainText('checking every transaction');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(statement.getByRole('heading', { name: 'Bank Statement to CSV / Excel' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});
