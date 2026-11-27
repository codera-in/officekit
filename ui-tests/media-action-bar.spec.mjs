import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const selectionId = '53535353-5353-4353-8353-535353535353';
const imageId = '54545454-5454-4454-8454-545454545454';
const capability = (id, formats) => ({ id, label: id, available: true, formats, reason: null });

test('the bottom action bar carries the media Run button instead of floating empty over the form', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__TAURI__ = { core: { invoke: async (command) => (command === 'file_selection_open' ? { id: selectionId } : null) }, event: { listen: async () => () => {} } };
  }, { selectionId });
  await page.route('**/api/media-capabilities', route => route.fulfill({ json: { version: 1, maxInputBytes: 67108864, maxBatchItems: 30, media: [
    { id: 'image', label: 'Images', operations: [capability('image-optimize', ['jpeg', 'webp'])] },
  ] } }));
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: { id: selectionId, access: 'read', hasMore: false, files: [{ id: imageId, name: 'IMG_7469.HEIC', size_bytes: 2400000 }] } }));
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [] }));
  await page.route('**/api/media-operation-defaults', route => route.fulfill({ json: {} }));
  await page.route('**/api/media-folder-watches', route => route.fulfill({ json: [] }));
  await page.goto('/'); await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  // Nothing selected: the strip is on step 1, the Next panel asks for files and Select files is a text link.
  await expect(page.locator('#media-toolkit-next')).toHaveAttribute('data-state', 'empty');
  await expect(page.locator('#media-toolkit-next-title')).toHaveText('Next: choose files');
  await expect(page.locator('#media-toolkit-next-action')).toBeDisabled();
  await expect(page.locator('#media-toolkit-steps li[data-step="1"]')).toHaveAttribute('data-status', 'current');
  await expect(page.locator('#media-toolkit-select')).toHaveText('Select files');
  await page.locator('#media-toolkit-select').click();
  await expect(page.locator('#media-toolkit-file-list')).toContainText('IMG_7469.HEIC');
  // The type comes from the file, so the operation list shows image operations without a manual type pick.
  await expect(page.locator('#media-toolkit-kind')).toHaveValue('image');
  await expect(page.locator('#media-toolkit-operation option[value="image-optimize"]')).toBeEnabled();
  // One file ready: steps 1 and 2 are done and the Next panel names the file count and the operation.
  await expect(page.locator('#media-toolkit-next')).toHaveAttribute('data-state', 'ready');
  await expect(page.locator('#media-toolkit-next-title')).toContainText('Ready: 1 file →');
  await expect(page.locator('#media-toolkit-next-action')).toBeEnabled();
  await expect(page.locator('#media-toolkit-steps li[data-step="1"]')).toHaveAttribute('data-status', 'done');
  await expect(page.locator('#media-toolkit-steps li[data-step="3"]')).toHaveAttribute('data-status', 'current');
  // Link import, results and coverage start collapsed.
  expect(await page.locator('#media-toolkit-url-panel').evaluate(node => node.open)).toBe(false);
  expect(await page.locator('#media-toolkit-results-panel').evaluate(node => node.open)).toBe(false);

  const bar = page.locator('#officekit-tool-actions');
  await expect(bar).toBeVisible();
  const run = page.locator('#media-toolkit-run');
  await expect(run).toBeVisible();
  await expect.poll(async () => {
    const [barBox, runBox] = [await bar.boundingBox(), await run.boundingBox()];
    return Boolean(barBox && runBox && runBox.y >= barBox.y - 1 && runBox.y + runBox.height <= barBox.y + barBox.height + 1);
  }).toBe(true);
  // A switch sits clear of its label instead of touching it.
  const caption = page.locator('#media-toolkit-settings-fields label', { hasText: 'Keep metadata' }).locator('span').first();
  const toggle = page.locator('#media-toolkit-settings-fields [data-option-key="preserveMetadata"]');
  const [captionBox, toggleBox] = [await caption.boundingBox(), await toggle.boundingBox()];
  expect(toggleBox.x - (captionBox.x + captionBox.width)).toBeGreaterThanOrEqual(8);
  // The converter's own empty action bar stays hidden instead of showing as a stray band above this one.
  expect(await page.locator('#converter-action-dock').evaluate(node => getComputedStyle(node).display)).toBe('none');
  // At most three buttons at once: Select files is a text link, so ready shows only the named action; Cancel, Save and Start over appear only when they apply.
  const shown = () => page.evaluate(() => [...document.querySelectorAll('#media-toolkit-action-dock button')].filter(button => button.getClientRects().length).map(button => button.textContent.trim()));
  const ready = await shown();
  expect(ready).toHaveLength(1);
  expect(ready[0]).toMatch(/\b1\b/);
  expect(ready[0]).not.toMatch(/copies/i);
  expect(await page.locator('#media-toolkit-select').evaluate(node => node.tagName)).toBe('A');
  await expect(page.locator('#media-toolkit-cancel')).toBeHidden();
  await expect(page.locator('#media-toolkit-reset')).toBeHidden();
  await expect(page.locator('#media-toolkit-save')).toBeHidden();
  await expect(page.locator('#media-toolkit-next-action')).toBeHidden();
});
