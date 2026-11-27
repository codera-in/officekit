import { test, expect } from '@playwright/test';
import { routeAuthenticatedApi } from './authenticated-app.mjs';

test('PDF task controls use the shared bottom action dock at desktop and compact widths', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => {
    switchTab('pdf');
  });

  const dock = page.locator('#pdf-workbench-run').locator('xpath=../..');
  await expect(dock).toHaveClass(/ok-action-dock/);
  await expect(dock).toHaveCSS('position', 'fixed');
  await expect(page.locator('#pdf-workbench-status')).toHaveAttribute('aria-live', 'polite');
  await expect(page.locator('#pdf-workbench-run')).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    dock: document.getElementById('pdf-workbench-run').parentElement.parentElement.getBoundingClientRect().width,
    buttons: [...document.querySelectorAll('#pdf-workbench-run, #pdf-workbench-download')].map(button => {
      const rect = button.getBoundingClientRect();
      return { left: rect.left, right: rect.right, height: rect.height };
    }),
  }));
  expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.dock).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.buttons.every(button => button.left >= 0 && button.right <= dimensions.viewport)).toBe(true);
  expect(dimensions.buttons[0].height).toBeGreaterThanOrEqual(44);
});
