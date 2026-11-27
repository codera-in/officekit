import { expect, test } from '@playwright/test';


test('license screen states checkout availability and opens the existing activation dialog', async ({ page }) => {
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');

  await page.evaluate(() => switchTab('pricing'));
  await expect(page.getByRole('heading', { name: 'Your OfficeKit license' })).toBeVisible();
  await expect(page.getByText('This build does not offer purchases or checkout.')).toBeVisible();
  await expect(page.getByText('If you already have a license key, activate it here.')).toBeVisible();

  await page.getByRole('button', { name: 'Activate a license key' }).click();
  await expect(page.getByRole('dialog', { name: 'Activate OfficeKit' })).toBeVisible();
});
