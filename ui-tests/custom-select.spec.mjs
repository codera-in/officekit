import { expect, test } from '@playwright/test';
import { setTheme } from './theme-helper.mjs';

async function authorizeApi(page) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
}

test('native select controls use daisyUI styles and retain normal selection behavior', async ({ page }) => {
  await authorizeApi(page);
  await page.goto('/');
  await page.evaluate(() => selectSearchTool('dup_finder'));
  const select = page.locator('#direct-duplicate-mode');
  await expect(select).toBeVisible();
  await expect(select).toHaveClass(/\bselect\b/);
  await select.selectOption('folders');
  await expect(select).toHaveValue('folders');
  await select.selectOption('files');
  await expect(select).toHaveValue('files');
});

test('native select styling follows the active dark theme', async ({ page }) => {
  await authorizeApi(page);
  await page.goto('/');
  await setTheme(page, 'dark');
  await page.evaluate(() => selectSearchTool('dup_finder'));
  const select = page.locator('#direct-duplicate-mode');
  await expect(select).toBeVisible();
  await expect(select).toHaveClass(/\bselect\b/);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});
