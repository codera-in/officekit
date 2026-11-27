import { expect, test } from '@playwright/test';
import { setTheme } from './theme-helper.mjs';

test('the icon toggle switches light and dark, labels itself, and the menu returns to system', async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  const toggle = page.locator('#officekit-theme-toggle');
  await expect(toggle).toBeVisible();
  await page.emulateMedia({ colorScheme: 'light' });
  await setTheme(page, 'system');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(toggle).toHaveAttribute('aria-label', 'Switch to dark mode');
  await expect(toggle.locator('.ok-theme-icon-moon')).toBeVisible();
  await expect(toggle.locator('.ok-theme-icon-sun')).toBeHidden();

  await toggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(toggle).toHaveAttribute('aria-label', 'Switch to light mode');
  await expect(toggle.locator('.ok-theme-icon-sun')).toBeVisible();
  await expect(toggle.locator('.ok-theme-icon-moon')).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(19, 31, 41)');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ok-accent').trim())).toBe('#86c8eb');
  expect(await page.evaluate(() => localStorage.getItem('officekit.theme'))).toBe('dark');

  await toggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(238, 243, 246)');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ok-accent').trim())).toBe('#16749a');

  await toggle.click({ button: 'right' });
  await expect(page.locator('#officekit-theme-menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#officekit-theme-menu')).toBeHidden();
  await toggle.click({ button: 'right' });
  await page.locator('#officekit-theme-system').click();
  await expect(page.locator('#officekit-theme-system')).toHaveAttribute('aria-checked', 'true');
  expect(await page.evaluate(() => localStorage.getItem('officekit.theme'))).toBeNull();
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await setTheme(page, 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('every registered tool destination opens with the dark app palette', async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => allToolsCache.length)).toBeGreaterThan(40);
  const count = await page.evaluate(() => allToolsCache.length);
  expect(count).toBeGreaterThan(40);
  await setTheme(page, 'dark');

  const failures = await page.evaluate(async () => {
    const results = [];
    for (const tool of allToolsCache) {
      const opened = selectSearchTool(tool.id);
      if (!opened) {
        results.push(`${tool.id}: route did not open`);
        continue;
      }
      const active = [...document.querySelectorAll('#app-main section[id^="tab-"]')]
        .find(section => section.getClientRects().length > 0);
      if (!active) results.push(`${tool.id}: no active app surface`);
    }
    return results;
  });
  expect(failures).toEqual([]);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(19, 31, 41)');
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#app-sidebar')).backdropFilter)).toContain('blur');
  expect(await page.evaluate(() => {
    const surface = document.querySelector('#app-main .bg-white');
    return surface ? getComputedStyle(surface).backgroundColor : null;
  })).not.toBe('rgb(255, 255, 255)');
});
