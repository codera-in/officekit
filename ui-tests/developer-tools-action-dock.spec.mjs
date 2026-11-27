import { test, expect } from '@playwright/test';
import { routeAuthenticatedApi } from './authenticated-app.mjs';

test('developer utility actions and result controls share the bottom dock', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => {
    switchTab('converter');
    document.querySelector('#developer-tools-panel').hidden = false;
  });

  const dock = page.locator('#developer-tools-action-dock');
  await expect(dock).toHaveCSS('position', 'fixed');
  await expect(page.locator('#developer-tools-run').locator('xpath=..')).toHaveAttribute('id', 'developer-tools-action-controls');
  await expect(page.locator('#developer-tools-status').locator('xpath=..')).toHaveAttribute('id', 'developer-tools-action-dock');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    dock: document.getElementById('developer-tools-action-dock').getBoundingClientRect().width,
    run: document.getElementById('developer-tools-run').getBoundingClientRect(),
  }));
  expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.dock).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.run.width).toBeGreaterThanOrEqual(44);
  expect(dimensions.run.height).toBeGreaterThanOrEqual(44);
  expect(dimensions.run.right).toBeLessThanOrEqual(dimensions.viewport);

  await page.evaluate(() => officekitPublishTextResult(document.getElementById('developer-tools-action-controls'), '{"ok": true}', 'Developer result', 'devtools_format', 'json'));
  await expect(page.locator('#developer-tools-action-controls .officekit-result-actions')).toBeVisible();
  await expect(page.locator('#developer-tools-action-controls .officekit-result-actions')).toHaveCSS('position', 'static');
  await expect(page.locator('#developer-tools-action-controls .officekit-result-actions').getByRole('button', { name: 'Download', exact: true })).toBeVisible();
  await expect(page.locator('#developer-tools-action-controls .officekit-result-actions').getByRole('button', { name: 'Copy text', exact: true })).toBeVisible();
  await page.evaluate(() => document.querySelector('#developer-tools-action-controls .officekit-result-actions').remove());
  await expect(page.locator('#developer-tools-action-controls .officekit-result-actions')).toHaveCount(0);
});
