import { expect, test } from '@playwright/test';

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

// The Tools-page field is visually hidden (the header search drives it), so set it the way the header does.
const search = (page, query) => page.evaluate(value => { const input = document.getElementById('tool-gallery-search'); input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); }, query);

test('searching zip or compress finds the archive tools and image compression', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => switchTab('tools'));
  await search(page, 'zip');
  await expect(page.locator('#tool-gallery-results [data-open-tool="archive_manager"]').first()).toBeVisible();
  await search(page, 'compress image');
  await expect(page.locator('#tool-gallery-results [data-open-tool="image_compress"]').first()).toBeVisible();
});

test('Compress & Extract ZIP opens the Archive tools screen and Compress Images opens image optimisation', async ({ page }) => {
  await openApp(page);
  expect(await page.evaluate(() => selectSearchTool('archive_manager'))).toBe(true);
  await expect(page.locator('#direct-file-title')).toHaveText('Archive tools');
  expect(await page.evaluate(() => selectSearchTool('image_compress'))).toBe(true);
  await expect(page.locator('#media-toolkit-panel')).toBeVisible();
  await expect(page.locator('#media-toolkit-operation')).toHaveValue('image-optimize');
});
