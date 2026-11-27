import { test, expect } from '@playwright/test';
import { expectGalleryMatchesCatalog } from './gallery-count.mjs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const fixture = relative => path.resolve('tests/fixtures/similar-images', relative);
let externalRequests;
let pageErrors;


test.beforeEach(async ({ context, page }) => {
  externalRequests = [];
  pageErrors = [];
  await context.addInitScript(() => {
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'file_selection_open') return window.__officekitTestSelection;
      throw new Error(`Unexpected native test command: ${command}`);
    } } };
  });
  page.on('pageerror', error => pageErrors.push(error.message));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const request = route.request();
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...request.headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
          origin: 'tauri://localhost',
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expectGalleryMatchesCatalog(page, expect);
});

test.afterEach(() => {
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('direct-file similar-image flow groups photo copies and leaves unrelated scenes separate', async ({ page }) => {
  const portrait = await fs.readFile(fixture('cc0/dog-portrait.jpg'));
  const road = await fs.readFile(fixture('cc0/dog-on-road.jpg'));
  const dandelion = await fs.readFile(fixture('cc0/dandelion.jpg'));
  const staged = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-similar-images-'));
  try {
    const stagedFiles = [
      ['burst-frame-01.jpg', portrait],
      ['burst-frame-02.jpg', portrait],
      ['different-dog-scene.jpg', road],
      ['unrelated-flower.jpg', dandelion],
    ];
    for (const [name, bytes] of stagedFiles) await fs.writeFile(path.join(staged, name), bytes);

    const canonicalPath = await fs.realpath(staged);
    const selectionResponse = await page.request.post('http://127.0.0.1:19873/api/file-selections', {
      headers: {
        authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        'X-OfficeKit-Native-Grant': process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN,
        origin: 'tauri://localhost',
      },
      data: { paths: [canonicalPath], access: 'read' },
    });
    expect(selectionResponse.status()).toBe(201);
    await page.evaluate(selection => { window.__officekitTestSelection = selection; }, await selectionResponse.json());
    await page.evaluate(() => selectSearchTool('similar_images'));
    await page.getByRole('button', { name: 'Choose folder…', exact: true }).click();
    await expect(page.locator('#direct-selection-summary')).toContainText(path.basename(staged));
    await page.locator('#direct-file-run').click();

    const results = page.locator('#direct-file-results');
    await expect(results).toBeVisible({ timeout: 30_000 });
    await expect(results).toContainText('burst-frame-01.jpg');
    await expect(results).toContainText('burst-frame-02.jpg');
    await expect(results).not.toContainText('unrelated-flower.jpg');
    await expect(page.locator('#direct-file-status')).toContainText('Result ready.');
    await expect(results.locator('.officekit-result-actions')).toBeVisible();
    expect(await fs.readdir(staged)).toEqual(stagedFiles.map(([name]) => name));
  } finally {
    await fs.rm(staged, { recursive: true, force: true });
  }
});
