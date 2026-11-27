import { expect, test } from '@playwright/test';

// Approved direction (docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md):
// a tool shows only the inputs its chosen rule uses, and no screen shows more than three buttons.

async function openApp(page) {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
}

// In-text links (ok-text-link buttons such as "Choose files…" and "Reset selection") are not counted (AGENTS.md Button Limit).
const visibleButtons = page => page.locator('#tab-workspace button:visible:not(.ok-text-link), #officekit-tool-actions button:visible:not(.ok-text-link)').count();

test('batch renamer asks how to rename and shows only that rule’s fields', async ({ page }) => {
  await openApp(page);
  expect(await page.evaluate(() => selectSearchTool('batch_rename'))).toBe(true);
  const rule = page.locator('#direct-rename-pattern');
  await expect(rule).toBeVisible();
  await expect(page.locator('label:has(#direct-rename-pattern)')).toContainText('How to rename');
  await expect(rule.locator('option')).toHaveText(['Add a number', 'Add prefix or suffix', 'Find and replace', 'Change case']);

  await expect(page.locator('#direct-rename-prefix')).toBeVisible();
  await expect(page.locator('#direct-rename-suffix')).toBeVisible();
  await expect(page.locator('#direct-rename-find')).toBeHidden();
  await expect(page.locator('#direct-rename-replace')).toBeHidden();

  await rule.selectOption('replace');
  await expect(page.locator('#direct-rename-find')).toBeVisible();
  await expect(page.locator('#direct-rename-replace')).toBeVisible();
  await expect(page.locator('#direct-rename-prefix')).toBeHidden();
  await expect(page.locator('#direct-rename-suffix')).toBeHidden();

  await rule.selectOption('casing');
  await expect(page.locator('#direct-rename-prefix')).toBeHidden();
  await expect(page.locator('#direct-rename-find')).toBeHidden();
  expect(await visibleButtons(page)).toBeLessThanOrEqual(3);
});

test('archive screen follows the approved v3 frames: Operation picker, Format shown, Create ZIP', async ({ page }) => {
  await openApp(page);
  expect(await page.evaluate(() => selectSearchTool('archive_manager'))).toBe(true);
  const mode = page.locator('#direct-archive-mode');
  await expect(page.locator('label:has(#direct-archive-mode)')).toContainText('Operation');
  await expect(mode.locator('option')).toHaveText(['Browse / extract archive', 'Create archive']);
  await expect(page.locator('#direct-file-run')).toHaveText('Extract selected or all');

  await mode.selectOption('archive-create');
  await expect(page.locator('#direct-file-run')).toHaveText('Create ZIP');
  await expect(page.locator('#direct-archive-format')).toBeVisible();
  expect(await visibleButtons(page)).toBeLessThanOrEqual(3);
});
