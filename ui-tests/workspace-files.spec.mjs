import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { setTheme } from './theme-helper.mjs';
import os from 'node:os';
import path from 'node:path';

test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(() => {
    window.__TAURI__ = { event: { listen: async () => () => {} }, core: { invoke: async (command, args) => {
      if (command === 'file_selection_open') return window.__officekitTestSelection;
      if (command === 'file_job_reveal') { window.__officekitRevealedItem = args; return; }
      if (command === 'result_copy_text') { window.__officekitCopiedText = args.text; return; }
      if (command === 'result_save') { window.__officekitSavedFile = args; return { state: 'saved', name: args.suggestedName }; }
      throw new Error(`Unexpected native test command: ${command}`);
    } } };
  });
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`, origin: 'tauri://localhost' },
    });
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
});

async function authorizeSelection(page, selectedPath, access = 'read') {
  const canonicalPath = await fs.realpath(selectedPath);
  const response = await page.request.post('http://127.0.0.1:19873/api/file-selections', {
    headers: {
      authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
      'X-OfficeKit-Native-Grant': process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN,
      origin: 'tauri://localhost',
    },
    data: { paths: [canonicalPath], access },
  });
  expect(response.status()).toBe(201);
  await page.evaluate(selection => { window.__officekitTestSelection = selection; }, await response.json());
}

test('file checksum uses the selected original and exposes complete Copy and Download actions', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-direct-hash-'));
  const original = path.join(root, 'original.txt');
  await fs.writeFile(original, 'OfficeKit original fixture\n');
  try {
    await authorizeSelection(page, original);
    await page.evaluate(() => selectSearchTool('file_hash'));
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-results')).toBeVisible();
    await expect(page.locator('#direct-file-results')).toContainText('original.txt');
    await expect(page.locator('#direct-file-results')).toContainText('1fd11533');
    const actions = page.locator('#direct-file-results .officekit-result-actions');
    await actions.getByRole('button', { name: 'Copy report' }).click();
    await expect(actions).toContainText('Copied to clipboard.');
    expect(await page.evaluate(() => window.__officekitCopiedText)).toContain('1fd11533');
    await actions.getByRole('button', { name: 'Download' }).click();
    await expect(actions).toContainText('Saved file-result.json.');
    const saved = await page.evaluate(() => window.__officekitSavedFile);
    expect(saved.suggestedName).toBe('file-result.json');
    expect(JSON.parse(Buffer.from(saved.base64Data, 'base64').toString('utf8')).files[0].name).toBe('original.txt');
    expect(await fs.readdir(root)).toEqual(['original.txt']);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('rename preview becomes stale after edits and applies only the refreshed mapping to originals', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-direct-rename-'));
  const original = path.join(root, 'quarterly.txt');
  await fs.writeFile(original, 'unchanged bytes');
  try {
    await authorizeSelection(page, root, 'read-write');
    await page.evaluate(() => selectSearchTool('batch_rename'));
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    await page.locator('#direct-rename-pattern').selectOption('affix');
    await page.locator('#direct-rename-prefix').fill('reviewed-');
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-run')).toHaveText('Apply rename');
    await page.locator('#direct-rename-suffix').fill('-final');
    await expect(page.locator('#direct-file-run')).toHaveText('Preview rename');
    await expect(page.locator('#direct-file-results')).toBeHidden();
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-run')).toHaveText('Apply rename');
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-status')).toContainText('Result ready.');
    expect(await fs.readFile(path.join(root, 'reviewed-quarterly-final.txt'), 'utf8')).toBe('unchanged bytes');
    expect(await fs.readdir(root)).toEqual(['reviewed-quarterly-final.txt']);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('duplicate finder exposes a clear action and renders file names in a readable table', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-direct-duplicates-'));
  const first = path.join(root, 'first long filename.txt');
  const second = path.join(root, 'second long filename.txt');
  await fs.writeFile(first, 'same fixture bytes');
  await fs.copyFile(first, second);
  try {
    await authorizeSelection(page, root);
    await page.evaluate(() => selectSearchTool('dup_finder'));
    await expect(page.locator('#direct-file-run')).toHaveText('Find duplicates');
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    await expect(page.locator('#direct-file-run')).toHaveText('Find duplicates');
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-results .ok-file-report-table')).toBeVisible();
    await expect(page.locator('#direct-file-results')).toContainText('first long filename.txt');
    await expect(page.locator('#direct-file-results')).toContainText('second long filename.txt');
    await expect(page.locator('#direct-file-results .ok-file-report-scroll')).toHaveCSS('overflow-x', 'auto');
    await expect(page.locator('#direct-file-title')).toHaveCSS('font-size', '28px');
    const actions = page.locator('#direct-file-results .officekit-result-actions');
    await expect(actions).toHaveCSS('position', 'fixed');
    expect(await actions.evaluate(element => element.getBoundingClientRect().top >= document.getElementById('officekit-tool-actions').getBoundingClientRect().top)).toBe(true);
    await page.getByRole('button', { name: 'Select all duplicates', exact: true }).click();
    await expect(page.locator('#duplicate-selection-status')).toContainText('1 copy selected');
    await expect(page.getByRole('checkbox', { name: 'Keep first long filename.txt', exact: true })).toBeDisabled();
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('duplicate cleanup requires explicit confirmation and uses selected copy IDs only', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-duplicate-confirm-'));
  await fs.writeFile(path.join(root, 'a.txt'), 'same fixture');
  await fs.writeFile(path.join(root, 'b.txt'), 'same fixture');
  let cleanupRequests = 0;
  try {
    await authorizeSelection(page, root, 'read-write');
    await page.evaluate(() => selectSearchTool('dup_finder'));
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    await page.locator('#direct-file-run').click();
    await expect(page.getByRole('button', { name: 'Select all duplicates', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Select all duplicates', exact: true }).click();
    await page.route('**/api/file-jobs', async route => {
      const body = route.request().postDataJSON();
      if (body.kind !== 'duplicate-trash') return route.fallback();
      cleanupRequests += 1;
      expect(body.options.fileIds).toHaveLength(1);
      expect(Object.keys(body.options).sort()).toEqual(['fileIds', 'sourceJobId']);
      return route.fulfill({status:422,json:{detail:'Fixture cleanup rejected; originals unchanged.'}});
    });
    const trash = page.locator('#duplicate-trash');
    await trash.click();
    const dialog = page.getByRole('dialog', { name: 'Move selected copies to Trash?' });
    await expect(dialog).toBeVisible();
    expect(cleanupRequests).toBe(0);
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(cleanupRequests).toBe(0);
    await trash.click();
    await dialog.getByRole('button', { name: 'Move to Trash', exact: true }).click();
    await expect(page.locator('#direct-file-status')).toContainText('Fixture cleanup rejected');
    expect(cleanupRequests).toBe(1);
    expect((await fs.readdir(root)).sort()).toEqual(['a.txt', 'b.txt']);
  } finally { await fs.rm(root, { recursive:true,force:true }); }
});

test('duplicate scope, sorting and group pagination preserve selection across all pages', async ({ page }, testInfo) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-duplicate-pages-'));
  const subfolder = path.join(root, 'nested');
  await fs.mkdir(subfolder);
  for (let index = 0; index < 24; index++) {
    const name = `group-${String(index).padStart(2, '0')}`;
    const bytes = String(index).padStart(2, '0') + 'x'.repeat(index);
    for (const suffix of ['a', 'b']) {
      const file = path.join(root, `${name}-${suffix}.txt`);
      await fs.writeFile(file, bytes);
      // Dates run in the opposite order to name/size to verify the actual sort key.
      await fs.utimes(file, 1700000000 + (24 - index) * 86400, 1700000000 + (24 - index) * 86400);
    }
  }
  await fs.writeFile(path.join(subfolder, 'nested-a.txt'), 'nested fixture');
  await fs.writeFile(path.join(subfolder, 'nested-b.txt'), 'nested fixture');
  try {
    await authorizeSelection(page, root, 'read-write');
    await page.evaluate(() => selectSearchTool('dup_finder'));
    await page.getByRole('button', {name:'Choose folder…', exact:true}).click();
    await expect(page.locator('#direct-file-options')).toContainText('Includes all subfolders');
    await page.locator('#direct-file-run').click();
    const result = page.locator('#direct-file-results');
    const rows = result.locator('tbody tr');
    await expect(result.locator('h2')).toHaveText('25 duplicate groups');
    await expect(rows).toHaveCount(20);
    await expect(rows.first()).toContainText('group-00-a.txt');
    await expect(rows.first()).toContainText(path.basename(root) + '/');
    await expect(rows.first()).not.toContainText('Unavailable');
    await page.getByRole('button', {name:'Select all duplicates', exact:true}).click();
    await expect(page.locator('#duplicate-selection-status')).toHaveText('25 copies selected');
    await page.getByRole('button', {name:'Next', exact:true}).click();
    await expect(page.locator('#duplicate-page-status')).toContainText('Page 2 of 3');
    await expect(result.locator('tbody input:checked')).toHaveCount(10);
    await page.getByRole('button', {name:'Sort by Date modified', exact:true}).click();
    await expect(result.locator('th[aria-sort="ascending"]')).toContainText('Date modified');
    await expect(rows.first()).toContainText('group-23-a.txt');
    await expect(page.locator('#duplicate-page-status')).toContainText('Page 1 of 3');
    await page.getByRole('button', {name:'Sort by Size', exact:true}).click();
    await expect(rows.first()).toContainText('group-00-a.txt');
    await page.getByRole('button', {name:'Sort by Size', exact:true}).click();
    await expect(result.locator('th[aria-sort="descending"]')).toContainText('Size');
    await expect(rows.first()).toContainText('group-23-a.txt');
    await expect(result.locator('tbody input:disabled:checked')).toHaveCount(0);
    await expect(result.locator('tbody input:checked')).toHaveCount(10);
    await page.getByLabel('Groups per page', {exact:true}).selectOption('25');
    await expect(rows).toHaveCount(50);
    await expect(page.getByRole('button', {name:'Next', exact:true})).toBeDisabled();
    for (const size of ['50', '100', '10']) {
      await page.getByLabel('Groups per page', {exact:true}).selectOption(size);
      await expect(rows).toHaveCount(size === '10' ? 20 : 50);
    }
    await page.getByRole('button', {name:'Clear selection', exact:true}).click();
    await expect(result.locator('tbody input:checked')).toHaveCount(0);
    await expect(page.locator('#duplicate-selection-status')).toHaveText('No copies selected');
    const geometry = await result.evaluate(element => {
      const list = element.querySelector('.ok-duplicate-list');
      const actions = element.querySelector('.officekit-result-actions');
      const bar = document.getElementById('officekit-tool-actions').getBoundingClientRect();
      return {height:list.clientHeight, scrollHeight:list.scrollHeight, actionsInBar:actions.getBoundingClientRect().top >= bar.top && actions.getBoundingClientRect().bottom <= bar.bottom};
    });
    expect(geometry.scrollHeight).toBe(geometry.height);
    expect(geometry.actionsInBar).toBe(true);
    await page.getByLabel('Groups per page', {exact:true}).selectOption('100');
    await expect(result).toContainText(path.basename(root) + '/nested/');
    await page.getByRole('button', {name:'Select all duplicates', exact:true}).click();
    await expect(page.locator('#duplicate-selection-status')).toHaveText('25 copies selected');
    const fullPath = await rows.first().locator('strong').getAttribute('title');
    expect(path.isAbsolute(fullPath)).toBe(true);
    await expect(rows.first().locator('.ok-duplicate-path')).toHaveAttribute('title', fullPath);
    await rows.first().getByRole('button', {name:'Show in Finder', exact:true}).click();
    const reveal = await page.evaluate(() => window.__officekitRevealedItem);
    expect(Object.keys(reveal).sort()).toEqual(['itemId', 'jobId']);
    expect(reveal.itemId).toMatch(/^[a-f0-9-]{36}$/);
    for (const theme of ['light', 'dark']) {
      await setTheme(page, theme);
      await result.scrollIntoViewIfNeeded();
      await page.screenshot({path:testInfo.outputPath(`duplicate-pagination-${theme}.png`)});
    }
    expect((await fs.readdir(root)).length).toBe(49);
  } finally { await fs.rm(root, {recursive:true, force:true}); }
});

test('identical folder mode shows exact structure matches with Finder actions and no cleanup', async ({page}, testInfo) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-folder-matches-'));
  for (const name of ['Project', 'Project backup', 'Different']) {
    await fs.mkdir(path.join(root, name, 'empty'), {recursive:true});
    await fs.writeFile(path.join(root, name, 'file.txt'), name === 'Different' ? 'different bytes' : 'identical bytes');
  }
  try {
    await authorizeSelection(page, root);
    await page.evaluate(() => selectSearchTool('dup_finder'));
    await page.getByRole('button', {name:'Choose folder…', exact:true}).click();
    await page.locator('#direct-file-run').click();
    await expect(page.locator('#direct-file-results')).toBeVisible();
    await page.getByLabel('Find', {exact:true}).selectOption('folders');
    await expect(page.locator('#direct-file-results')).toBeHidden();
    await page.locator('#direct-file-run').click();
    const result = page.locator('#direct-file-results');
    await expect(result.locator('h2')).toHaveText('2 identical folder groups');
    await expect(result).toContainText('Folder matches are for inspection');
    await expect(result.locator('tbody tr')).toHaveCount(5);
    await expect(result.locator('input[type=checkbox]')).toHaveCount(0);
    await expect(result.locator('#duplicate-trash')).toHaveCount(0);
    await expect(result.getByRole('button', {name:'Select all duplicates', exact:true})).toHaveCount(0);
    await result.getByRole('button', {name:'Show in Finder', exact:true}).first().click();
    await expect(page.locator('#direct-file-status')).toHaveText('Revealed in Finder.');
    for (const theme of ['light', 'dark']) {
      await setTheme(page, theme);
      await result.scrollIntoViewIfNeeded();
      await page.screenshot({path:testInfo.outputPath(`identical-folders-${theme}.png`)});
    }
    expect((await fs.readdir(root)).sort()).toEqual(['Different', 'Project', 'Project backup']);
  } finally { await fs.rm(root, {recursive:true, force:true}); }
});

test('browser-only file selection explains that direct access requires the desktop app', async ({ page }) => {
  await page.evaluate(() => { delete window.__TAURI__; selectSearchTool('file_type'); });
  await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
  await expect(page.locator('#direct-file-status')).toContainText('No files have been copied');
  await expect(page.locator('#direct-file-run')).toBeDisabled();
});

test('adding an unsupported archive explains the limitation and disables extraction', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-unsupported-archive-'));
  const archive = path.join(root, 'legacy.sitx');
  await fs.writeFile(archive, 'unsupported archive fixture');
  try {
    await authorizeSelection(page, archive);
    await page.evaluate(() => { switchTab('workspace'); officekitOpenDirectFileTool('archive'); });
    await expect(page.locator('#direct-file-options details summary')).toContainText('Format support (42)');
    // The reference table stays closed behind its disclosure until the user opens it.
    await expect(page.locator('#direct-file-options details table')).toBeHidden();
    await page.locator('#direct-file-options details summary').click();
    await expect(page.locator('#direct-file-options details table')).toBeVisible();
    await page.locator('#direct-file-options details summary').click();
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    const results = page.locator('#direct-file-results');
    await expect(results).toContainText('SITX files aren’t supported yet.');
    await expect(results).toContainText('can’t open or extract this format');
    await expect(page.locator('#direct-file-run')).toBeDisabled();
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('the subfolders checkbox keeps its own size and sits beside its label', async ({ page }) => {
  await page.evaluate(() => { switchTab('workspace'); officekitOpenDirectFileTool('symlink_inspector'); });
  const box = page.locator('#direct-include-subfolders');
  await expect(box).toBeVisible();
  const shape = await box.evaluate(node => {
    const input = node.getBoundingClientRect();
    const label = node.parentElement.getBoundingClientRect();
    return { square: Math.abs(input.width - input.height) <= 2, small: input.height <= 24, beside: label.height < input.height + 40, level: Math.abs((input.top + input.height / 2) - (label.top + label.height / 2)) <= 2 };
  });
  expect(shape).toEqual({ square: true, small: true, beside: true, level: true });
});

test('file type detector reports content signatures and extension mismatches', async ({ page }, testInfo) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-direct-file-type-'));
  const mislabeled = path.join(root, 'photo.png');
  await fs.copyFile(path.resolve('tests/fixtures/similar-images/cc0/dog-on-road.jpg'), mislabeled);
  try {
    await authorizeSelection(page, mislabeled);
    await page.evaluate(() => selectSearchTool('file_type'));
    await fs.mkdir(path.resolve('docs/verification/tool-unification/before'), { recursive: true });
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/before/file_type-initial-${testInfo.project.name}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Choose files…', exact: true }).click();
    await page.locator('#direct-file-run').click();
    const results = page.locator('#direct-file-results');
    await expect(results).toContainText('photo.png');
    await expect(results).toContainText('JPEG');
    await expect(results).toContainText('image/jpeg');
    await expect(results).toContainText('No');
    const actions = results.locator('.officekit-result-actions');
    await expect(actions).toHaveAttribute('data-officekit-docked', 'true');
    await expect(page.locator('#officekit-tool-actions')).toBeVisible();
    await fs.mkdir(path.resolve('docs/verification/tool-unification/after'), { recursive: true });
    await actions.getByRole('button', { name: 'Copy report' }).click();
    await expect(actions).toContainText('Copied to clipboard.');
    const copied = JSON.parse(await page.evaluate(() => window.__officekitCopiedText));
    expect(copied).toMatchObject({ total_files: 1, complete: true });
    expect(copied.files).toHaveLength(1);
    expect(copied.files[0]).toMatchObject({ name: 'photo.png', detected_type: 'JPEG', mime_type: 'image/jpeg', extension_matches: false });
    await actions.getByRole('button', { name: 'Download' }).click();
    await expect(actions).toContainText('Saved file-result.json.');
    const saved = await page.evaluate(() => window.__officekitSavedFile);
    expect(saved.suggestedName).toBe('file-result.json');
    expect(JSON.parse(Buffer.from(saved.base64Data, 'base64').toString('utf8'))).toEqual(copied);
    expect(await page.locator('#officekit-tool-actions button:visible').count()).toBeLessThanOrEqual(3);
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/file_type-result-${testInfo.project.name}.png`), fullPage: true });
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('file comparison finds the first byte difference and preserves both originals', async ({ page }, testInfo) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-direct-file-compare-'));
  const first = path.join(root, 'first.txt');
  const second = path.join(root, 'second.txt');
  await fs.writeFile(first, 'alpha\n');
  await fs.writeFile(second, 'alphi\n');
  try {
    const selectionA = await authorizeSelection(page, first);
    const selectionB = await authorizeSelection(page, second);
    await page.evaluate(() => selectSearchTool('file_compare'));
    await expect(page.locator('#direct-file-title')).toHaveText('Compare two files');
    await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
    await page.evaluate(([a, b]) => { window.__officekitTestSelectionQueue = [a, b]; }, [selectionA, selectionB]);
    await fs.mkdir(path.resolve('docs/verification/tool-unification/before'), { recursive: true });
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/before/file_compare-initial-${testInfo.project.name}.png`), fullPage: true });
    await page.locator('#direct-choose-files').click();
    await page.locator('#direct-folder-b').click();
    await page.locator('#direct-file-run').click();
    const results = page.locator('#direct-file-results');
    await expect(results).toContainText('Files differ');
    await expect(results).toContainText('first difference at byte 4');
    await expect(results).toContainText('File A');
    await expect(results).toContainText('File B');
    await expect(page.locator('#officekit-tool-actions')).toBeVisible();
    const actions = results.locator('.officekit-result-actions');
    await expect(actions).toHaveAttribute('data-officekit-docked', 'true');
    await actions.getByRole('button', { name: 'Copy report' }).click();
    await expect(actions).toContainText('Copied to clipboard.');
    const copied = JSON.parse(await page.evaluate(() => window.__officekitCopiedText));
    expect(copied).toMatchObject({ equal: false, first_difference_offset: 4, size_a: 6, size_b: 6 });
    expect(copied.sha256_a).not.toBe(copied.sha256_b);
    expect(JSON.stringify(copied)).not.toContain('private fixture data');
    await actions.getByRole('button', { name: 'Download' }).click();
    await expect(actions).toContainText('Saved file-result.json.');
    const saved = await page.evaluate(() => window.__officekitSavedFile);
    expect(saved.suggestedName).toBe('file-result.json');
    expect(JSON.parse(Buffer.from(saved.base64Data, 'base64').toString('utf8'))).toEqual(copied);
    expect(await page.locator('#officekit-tool-actions button:visible').count()).toBeLessThanOrEqual(3);
    await fs.mkdir(path.resolve('docs/verification/tool-unification/after'), { recursive: true });
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/file_compare-result-${testInfo.project.name}.png`), fullPage: true });
    expect(await fs.readFile(first, 'utf8')).toBe('alpha\n');
    expect(await fs.readFile(second, 'utf8')).toBe('alphi\n');
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
