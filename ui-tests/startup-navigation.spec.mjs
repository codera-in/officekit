import { expect, test } from '@playwright/test';

async function routeApi(context, observed = []) {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      observed.push(url.pathname);
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    } else {
      await route.continue();
    }
  });
}

test('navigation requested right after load opens its tool without waiting on any startup scope check', async ({ context, page }) => {
  await routeApi(context);
  await page.goto('/');
  expect(await page.evaluate(() => openPdfTool('merge'))).toBe(true);
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('#pdf-task-title')).toHaveText('Merge PDFs');
});

test('the merged Activity destination opens from the sidebar', async ({ context, page }) => {
  await routeApi(context);
  await page.goto('/');
  await page.locator('[data-sidebar-tab="favorites"]').click();
  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('#tab-activity')).toBeVisible();
  await expect(page.locator('[data-sidebar-tab="activity"]')).toHaveAttribute('aria-current', 'page');
});

test('startup never requests a release scope and shows no private-beta marker', async ({ context, page }) => {
  const observed = [];
  await routeApi(context, observed);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  expect(observed).not.toContain('/api/release');
  await expect(page.locator('#release-profile-badge')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('Private beta');
  await expect(page.locator('#dictation-audio-media-button')).not.toHaveClass(/\bhidden\b/);
});
