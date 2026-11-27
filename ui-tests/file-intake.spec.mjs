import { expect, test } from '@playwright/test';
import path from 'node:path';

const fixtures = [
  path.resolve('tests/fixtures/pdf-protect-source.pdf'),
  path.resolve('tests/fixtures/pdf-page-management-source.pdf'),
];

async function nativeSelection(page, paths) {
  const response = await page.request.post('http://127.0.0.1:19873/api/file-selections', {
    headers: {
      Authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
      'X-OfficeKit-Native-Grant': process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN,
    },
    data: { paths, access: 'read' },
  });
  expect(response.status()).toBe(201);
  return response.json();
}

test.beforeEach(async ({ context }) => {
  await context.addInitScript(({ token, origin }) => {
    window.__TAURI__ = {
      core: { invoke: async (command) => command === 'officekit_api_token' ? token : command === 'officekit_api_origin' ? origin : command === 'file_intake_ack' ? null : null },
      event: { listen: async () => () => {} },
    };
  }, { token: process.env.OFFICEKIT_UI_TEST_TOKEN, origin: 'http://127.0.0.1:19873' });
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`, origin: 'tauri://localhost' },
    });
  });
});

test('file intake matches PDF tools, updates for an explicit subset, and opens the existing destination', async ({ page }) => {
  const intakeAssetResponse = page.waitForResponse('**/assets/file-intake-capabilities.js');
  await page.goto('/');
  expect((await intakeAssetResponse).ok()).toBe(true);
  const selection = await nativeSelection(page, fixtures);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), selection);

  const intake = page.locator('#tab-file-intake');
  await expect(intake).toBeVisible();
  await expect(intake.locator('#file-intake-files label')).toHaveCount(2);
  await expect(intake.locator('input[name="file-intake-tool"][value="pdf_merge"]')).toBeEnabled();
  await expect(intake.locator('input[name="file-intake-tool"][value="file_compare"]')).toBeEnabled();
  await expect(intake.locator('input[name="file-intake-tool"][value="zip_create"]')).toBeEnabled();
  const tiles = intake.locator('.ok-intake-tile');
  expect(await tiles.count()).toBeGreaterThan(4);
  await expect(intake.locator('.ok-intake-tiles').first()).toHaveCSS('display', 'grid');
  await expect(tiles.first().locator('.ok-intake-name')).not.toBeEmpty();
  await expect(tiles.first().locator('.ok-intake-desc')).not.toBeEmpty();
  await expect(tiles.first().locator('.ok-intake-hint')).toBeHidden();
  // Choosing a tool opens it, so there is no Continue button.
  expect(await intake.locator('#file-intake-continue').count()).toBe(0);
  await expect(intake.locator('button:visible')).toHaveCount(0);
  // Search is the first control: full width, labelled for assistive tech, focused on open, with no separate "Filter tools" label.
  const search = intake.getByRole('searchbox', { name: 'Search tools for this file' });
  await expect(search).toBeFocused();
  await expect(intake.getByText('Filter tools', { exact: true })).toHaveCount(0);
  const [searchBox, panelBox] = await Promise.all([search.boundingBox(), intake.locator('#file-intake-files').boundingBox()]);
  expect(Math.abs(searchBox.width - panelBox.width)).toBeLessThan(2);
  await expect(intake.locator('#file-intake-files .ok-intake-file-meta').first()).toContainText('PDF');

  await intake.locator('#file-intake-files input[type="checkbox"]').nth(1).uncheck();
  await expect(intake.locator('input[name="file-intake-tool"][value="pdf_merge"]')).toBeDisabled();
  await expect(intake.locator('input[name="file-intake-tool"][value="pdf_text_extract"]')).toBeEnabled();
  await intake.locator('input[name="file-intake-tool"][value="pdf_text_extract"]').check();

  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('#tab-pdf')).toContainText(`1/${path.basename(fixtures[0])}`);
  await expect(page.locator('#tab-pdf')).toContainText('1 PDF ready');
  // Esc on the opened tool goes back to the tool choice for the same file, keeping the subset (one of two files).
  await expect(page.getByRole('link', { name: /Back to tool choice/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(intake).toBeVisible();
  await expect(intake.locator('#file-intake-files input[type="checkbox"]').nth(0)).toBeChecked();
  await expect(intake.locator('#file-intake-files input[type="checkbox"]').nth(1)).not.toBeChecked();
  await expect(intake.locator('input[name="file-intake-tool"][value="pdf_text_extract"]')).toBeEnabled();
  // Moving on to another page releases the selection.
  await page.evaluate(() => switchTab('home'));
  await expect.poll(async () => {
    const response = await page.request.get(`http://127.0.0.1:19873/api/file-selections/${selection.id}`, {
      headers: { Authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
    return response.status();
  }).toBe(404);
});

test('Backspace and undo on the opened tool also return to the tool choice', async ({ page }) => {
  const intakeAssetResponse = page.waitForResponse('**/assets/file-intake-capabilities.js');
  await page.goto('/');
  expect((await intakeAssetResponse).ok()).toBe(true);
  const selection = await nativeSelection(page, [fixtures[0]]);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), selection);
  const intake = page.locator('#tab-file-intake');
  for (const key of ['Backspace', 'Meta+z']) {
    await intake.locator('input[name="file-intake-tool"][value="pdf_text_extract"]').check();
    await expect(page.locator('#tab-pdf')).toBeVisible();
    await page.keyboard.press(key);
    await expect(intake).toBeVisible();
  }
});

test('a file with no recognised format still offers the tools that work on any file', async ({ page }) => {
  const bare = path.resolve('tests/fixtures/intake-no-extension');
  {
    const intakeAssetResponse = page.waitForResponse('**/assets/file-intake-capabilities.js');
    await page.goto('/');
    expect((await intakeAssetResponse).ok()).toBe(true);
    const selection = await nativeSelection(page, [bare]);
    await page.evaluate((value) => window.OfficeKitFileIntake.open(value), selection);
    const intake = page.locator('#tab-file-intake');
    await expect(intake.locator('#file-intake-files .ok-intake-file-meta')).toHaveText('FILE · 3 bytes');
    await expect(intake.locator('#file-intake-files')).toContainText('intake-no-extension');
    for (const id of ['file_hash', 'file_type', 'zip_create', 'file_info', 'batch_rename', 'file_split_join']) {
      await expect(intake.locator(`input[name="file-intake-tool"][value="${id}"]`)).toBeEnabled();
    }
    await expect(intake.locator('input[name="file-intake-tool"][value="pdf_merge"]')).toHaveCount(0);
    await expect(intake.getByText('No tools in the current release support this file selection.')).toHaveCount(0);
  }
});

test('file intake search filters the tools', async ({ page }) => {
  const intakeAssetResponse = page.waitForResponse('**/assets/file-intake-capabilities.js');
  await page.goto('/');
  expect((await intakeAssetResponse).ok()).toBe(true);
  const selection = await nativeSelection(page, [fixtures[0]]);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), selection);

  const intake = page.locator('#tab-file-intake');
  const radio = intake.locator('input[name="file-intake-tool"][value="pdf_text_extract"]');
  await intake.locator('#file-intake-search').fill('text');
  await expect(radio).toHaveCount(1);
  await intake.locator('#file-intake-search').fill('compress');
  await expect(radio).toHaveCount(0);
  await intake.locator('#file-intake-search').fill('text');
  await expect(radio).toHaveCount(1);
  // Backspace in the search box edits the text; it never leaves the page.
  await intake.locator('#file-intake-search').press('Backspace');
  await expect(intake).toBeVisible();
});

test('opening a second file asks before replacing the one on screen', async ({ page }) => {
  const intakeAssetResponse = page.waitForResponse('**/assets/file-intake-capabilities.js');
  await page.goto('/');
  expect((await intakeAssetResponse).ok()).toBe(true);
  const first = await nativeSelection(page, [fixtures[0]]);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), first);
  const intake = page.locator('#tab-file-intake');
  await expect(intake.locator('#file-intake-files')).toContainText(path.basename(fixtures[0]));
  await intake.locator('#file-intake-search').fill('text');

  const second = await nativeSelection(page, [fixtures[1]]);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), second);
  const dialog = page.getByRole('dialog', { name: 'Replace this file?' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(`You also opened ${path.basename(fixtures[1])}.`);
  await expect(dialog).toContainText(`Replace ${path.basename(fixtures[0])} with it`);
  await expect(dialog.getByRole('button')).toHaveCount(2);

  // Keep current: nothing on screen changes, including what was typed in the search box.
  await dialog.getByRole('button', { name: 'Keep current' }).click();
  await expect(dialog).toBeHidden();
  await expect(intake.locator('#file-intake-files')).toContainText(path.basename(fixtures[0]));
  await expect(intake.locator('#file-intake-search')).toHaveValue('text');

  // Replace: the new file is shown and the old selection is discarded.
  const third = await nativeSelection(page, [fixtures[1]]);
  await page.evaluate((value) => window.OfficeKitFileIntake.open(value), third);
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Replace' }).click();
  await expect(intake.locator('#file-intake-files')).toContainText(path.basename(fixtures[1]));
  await expect(intake.locator('#file-intake-files')).not.toContainText(path.basename(fixtures[0]));
  await expect.poll(async () => (await page.request.get(`http://127.0.0.1:19873/api/file-selections/${first.id}`, {
    headers: { Authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
  })).status()).toBe(404);
});
