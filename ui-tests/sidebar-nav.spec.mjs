import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const starters = ['loan_emi', 'pdf_editor', 'screenshot_editor', 'voice_transcription', 'storage_analyzer', 'system_resources', 'clipboard_manager'];
const favorites = page => page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1') || '{"favorites":[]}').favorites);

test('the sidebar is six rows with no headings, categories or per-row badges', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/'); await waitForAppReady(page);
  await expect(page.locator('#app-sidebar .ok-sidebar-link')).toHaveCount(6);
  await expect(page.locator('#app-sidebar .ok-sidebar-section-title')).toHaveCount(0);
  await expect(page.locator('#sidebar-categories')).toHaveCount(0);
  const labels = await page.locator('#app-sidebar .ok-sidebar-link .ok-nav-label').allTextContents();
  expect(labels.map(label => label.trim())).toEqual(['Home', 'All Tools', 'Favorites', 'Recent tools', 'Activity', 'Settings']);
  const overflow = await page.evaluate(() => { const side = document.getElementById('app-sidebar'); return side.scrollHeight - side.clientHeight; });
  expect(overflow).toBeLessThanOrEqual(0);
});

test('starter favorites are added once and a removed favorite stays removed', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/'); await waitForAppReady(page);
  expect(await favorites(page)).toEqual(starters);
  await page.evaluate(() => officekitRecordStore.toggleFavorite('loan_emi'));
  await page.reload(); await waitForAppReady(page);
  expect(await favorites(page)).toEqual(starters.filter(id => id !== 'loan_emi'));
});

test('existing favorites are kept and the starters are added after them', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.addInitScript(() => {
    if (!localStorage.getItem('officekit.records.v1')) localStorage.setItem('officekit.records.v1', JSON.stringify({ version: 1, favorites: ['network_dns'], recents: [], savedResults: [] }));
  });
  await page.goto('/'); await waitForAppReady(page);
  expect(await favorites(page)).toEqual(['network_dns', ...starters]);
});
