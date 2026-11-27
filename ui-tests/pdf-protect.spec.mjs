import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { inflateRawSync } from 'node:zlib';


async function selectPdfNavTool(page, tool) {
  const wideButton = page.locator(`.pdf-nav-wide [data-pdf-tool="${tool}"]`);
  if (await page.locator('.pdf-nav-wide').isVisible()) {
    const group = wideButton.locator('xpath=ancestor::details[1]');
    if (!(await group.evaluate(element => element.open))) await group.locator('summary').click();
    await wideButton.click();
  } else {
    const compactMenu = page.locator('#pdf-compact-menu');
    if (!(await compactMenu.evaluate(element => element.open))) await compactMenu.locator('summary').click();
    await page.locator(`#pdf-compact-list [data-pdf-tool="${tool}"]`).click();
  }
  const info = test.info();
  const name = info.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const directory = path.resolve('docs/verification/tool-unification/before');
  await fs.mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, `pdf-before-${name}-${info.project.name}.png`), fullPage: true });
}

test.beforeEach(async ({ context, page }) => {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.evaluate(() => openPdfTool('merge', false));
  await selectPdfNavTool(page, 'protect');
  await expect(page.locator('#pdf-task-title')).toHaveText('Protect PDF');
});

async function inspectPdfPageCounts(page, name, bytes) {
  const response = await page.request.post('http://127.0.0.1:19873/api/pdf/page-counts', {
    headers: { authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    multipart: { files: { name, mimeType: 'application/pdf', buffer: bytes } },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

async function clickPdfOutputDownload(page) {
  await page.locator('#pdf-workbench-preview-text').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
}

function readStoredZipEntries(bytes) {
  const signature = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
  const end = bytes.lastIndexOf(signature);
  expect(end).toBeGreaterThanOrEqual(0);
  const count = bytes.readUInt16LE(end + 10);
  let cursor = bytes.readUInt32LE(end + 16);
  const entries = [];
  for (let index = 0; index < count; index += 1) {
    expect(bytes.readUInt32LE(cursor)).toBe(0x02014b50);
    const method = bytes.readUInt16LE(cursor + 10);
    const compressedSize = bytes.readUInt32LE(cursor + 20);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const localOffset = bytes.readUInt32LE(cursor + 42);
    const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString('utf8');
    expect(method).toBe(0);
    expect(bytes.readUInt32LE(localOffset)).toBe(0x04034b50);
    const localNameLength = bytes.readUInt16LE(localOffset + 26);
    const localExtraLength = bytes.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    entries.push({ name, bytes: bytes.subarray(dataOffset, dataOffset + compressedSize) });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function readZipEntries(bytes) {
  const endSignature = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
  const end = bytes.lastIndexOf(endSignature);
  expect(end).toBeGreaterThanOrEqual(0);
  const count = bytes.readUInt16LE(end + 10);
  let cursor = bytes.readUInt32LE(end + 16);
  const entries = [];
  for (let index = 0; index < count; index += 1) {
    expect(bytes.readUInt32LE(cursor)).toBe(0x02014b50);
    const method = bytes.readUInt16LE(cursor + 10);
    const compressedSize = bytes.readUInt32LE(cursor + 20);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const localOffset = bytes.readUInt32LE(cursor + 42);
    const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString('utf8');
    expect(bytes.readUInt32LE(localOffset)).toBe(0x04034b50);
    const localNameLength = bytes.readUInt16LE(localOffset + 26);
    const localExtraLength = bytes.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataOffset, dataOffset + compressedSize);
    const contents = method === 8 ? inflateRawSync(compressed) : compressed;
    entries.push({ name, contents });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

test('PDF password flow uses the real API, produces an encrypted copy, and verifies unlock output', async ({ page }, testInfo) => {
  const source = await fs.readFile(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url));
  expect(await inspectPdfPageCounts(page, 'source.pdf', source)).toMatchObject({
    files: [{ index: 0, page_count: 1, status: 'ready' }],
    total_pages: 1,
    ready_count: 1,
    unreadable_count: 0,
  });
  const protectRequests = [];
  page.on('request', request => {
    if (request.url().includes('/api/pdf/protect')) {
      protectRequests.push(request);
    }
  });

  await page.locator('#pdf-workbench-file-input').setInputFiles({ name: 'source.pdf', mimeType: 'application/pdf', buffer: source });
  expect(await page.evaluate(() => pdfSelectedFiles.map(file => ({ name: file.name, size: file.size })))).toEqual([{ name: 'source.pdf', size: source.length }]);
  expect(await page.evaluate(async () => new TextDecoder().decode(await pdfSelectedFiles[0].slice(0, 5).arrayBuffer()))).toBe('%PDF-');
  const password = page.getByLabel('New PDF password', { exact: true });
  const confirmation = page.getByLabel('Confirm new PDF password', { exact: true });
  const run = page.locator('#pdf-workbench-run');
  await password.fill('ﷺ'.repeat(16));
  await confirmation.fill('ﷺ'.repeat(16));
  await expect(page.locator('#pdf-protect-password-count')).toHaveText(/\d+ entered · \d{3,} normalized \/ 127 bytes/);
  await expect(page.locator('#pdf-protect-confirm-error')).toContainText('127 normalized UTF-8 bytes');
  await expect(run).toBeDisabled();

  await password.fill('😀'.repeat(32));
  await confirmation.fill('😀'.repeat(32));
  await expect(page.locator('#pdf-protect-password-count')).toHaveText('128 entered · 128 normalized / 127 bytes');
  await expect(password).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#pdf-protect-confirm-error')).toContainText('127 normalized UTF-8 bytes');
  await expect(run).toBeDisabled();
  expect(protectRequests).toHaveLength(0);

  await confirmation.fill('');
  await password.fill('correct horse battery');
  await expect(page.locator('#pdf-protect-confirm-error')).toContainText('Enter the password again to confirm');
  await expect(run).toBeDisabled();
  await confirmation.fill('correct horse battery staple');
  await expect(confirmation).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#pdf-protect-confirm-error')).toContainText('Passwords do not match');
  await expect(run).toBeDisabled();
  expect(protectRequests).toHaveLength(0);

  await confirmation.fill('correct horse battery');
  await expect(confirmation).not.toHaveAttribute('aria-invalid', 'true');
  await expect(run).toBeEnabled();
  await run.click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
  await expect.poll(async () => {
    const protectedPreview = await page.locator('#pdf-workbench-preview').boundingBox();
    const protectDock = await page.locator('#officekit-tool-actions').boundingBox();
    return protectedPreview && protectDock && protectedPreview.y + protectedPreview.height <= protectDock.y;
  }).toBe(true);
  const protectedDownload = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const protectedFile = await protectedDownload;
  expect(protectedFile.suggestedFilename()).toBe('source_protected.pdf');
  const encrypted = await fs.readFile(await protectedFile.path());
  expect(encrypted.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await inspectPdfPageCounts(page, 'source_protected.pdf', encrypted)).toMatchObject({
    files: [{ index: 0, page_count: null, status: 'unreadable' }],
    total_pages: 0,
    ready_count: 0,
    unreadable_count: 1,
  });
  expect(source.subarray(0, 5).toString('ascii')).toBe('%PDF-');

  await selectPdfNavTool(page, 'unlock');
  await page.locator('#pdf-workbench-file-input').setInputFiles({ name: 'source_protected.pdf', mimeType: 'application/pdf', buffer: encrypted });
  await page.getByLabel('Known PDF password', { exact: true }).fill('😀'.repeat(32));
  await expect(page.locator('#pdf-unlock-password-count')).toContainText('128 entered · 128 normalized / 127 bytes');
  await expect(page.locator('#pdf-workbench-run')).toBeDisabled();

  await page.getByLabel('Known PDF password', { exact: true }).fill('incorrect password');
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Incorrect password');
  await expect(page.locator('#pdf-workbench-download')).toBeHidden();
  await expect(page.getByRole('button', { name: /Report bug for:/ })).toHaveCount(0);
  await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
  await expect(page.getByRole('button', { name: 'Copy summary' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Download' })).toBeHidden();
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/pdf_unlock-wrong-password-${testInfo.project.name}.png`), fullPage: true });

  await page.getByLabel('Known PDF password', { exact: true }).fill('correct horse battery');
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
  await expect.poll(async () => {
    const unlockedPreview = await page.locator('#pdf-workbench-preview').boundingBox();
    const unlockDock = await page.locator('#officekit-tool-actions').boundingBox();
    return unlockedPreview && unlockDock && unlockedPreview.y + unlockedPreview.height <= unlockDock.y;
  }).toBe(true);
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/pdf_unlock-recovered-${testInfo.project.name}.png`), fullPage: true });
  const unlockedDownload = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const unlockedFile = await unlockedDownload;
  expect(unlockedFile.suggestedFilename()).toBe('source_unlocked.pdf');
  const unlocked = await fs.readFile(await unlockedFile.path());
  expect(unlocked.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await inspectPdfPageCounts(page, 'source_unlocked.pdf', unlocked)).toMatchObject({
    files: [{ index: 0, page_count: 1, status: 'ready' }],
    total_pages: 1,
    ready_count: 1,
    unreadable_count: 0,
  });
  expect(source.equals(await fs.readFile(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url)))).toBe(true);
  expect(protectRequests).toHaveLength(1);
});

test('PDF merge creates a real combined download from the selected files and preserves both inputs', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('[data-pdf-tool="merge"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles([
    { name: 'first.pdf', mimeType: 'application/pdf', buffer: source },
    { name: 'second.pdf', mimeType: 'application/pdf', buffer: source },
  ]);
  await expect(page.locator('#pdf-workbench-files')).toContainText('first.pdf');
  await expect(page.locator('#pdf-workbench-files')).toContainText('second.pdf');
  expect(await page.evaluate(() => pdfSelectedFiles.map(file => file.name))).toEqual(['first.pdf', 'second.pdf']);
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();

  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('KiB');
  await expect(page.locator('#pdf-workbench-preview-text')).not.toContainText('0.00 MiB');
  await expect.poll(async () => {
    const mergedPreview = await page.locator('#pdf-workbench-preview').boundingBox();
    const mergeDock = await page.locator('#officekit-tool-actions').boundingBox();
    return mergedPreview && mergeDock && mergedPreview.y + mergedPreview.height <= mergeDock.y;
  }).toBe(true);
  const mergeCopy = page.locator('#pdf-workbench-preview .officekit-result-actions button').first();
  await mergeCopy.click();
  await expect(page.locator('.officekit-result-action-status[data-officekit-action-for="pdf_merge"]')).toContainText('Copied to clipboard');
  await expect.poll(async () => {
    const mergedPreview = await page.locator('#pdf-workbench-preview').boundingBox();
    const mergeDock = await page.locator('#officekit-tool-actions').boundingBox();
    return mergedPreview && mergeDock && mergedPreview.y + mergedPreview.height <= mergeDock.y;
  }).toBe(true);
  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('first_merged.pdf');
  const merged = await fs.readFile(await download.path());
  expect(merged.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await inspectPdfPageCounts(page, 'merged.pdf', merged)).toMatchObject({
    files: [{ index: 0, page_count: 2, status: 'ready' }],
    total_pages: 2,
    ready_count: 1,
    unreadable_count: 0,
  });
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('PDF compression downloads a readable copy and reports the measured size change', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('[data-pdf-tool="compress"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'statement.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  await expect(page.locator('#pdf-compression-preset')).toHaveValue('fast');

  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('source unchanged');
  await expect.poll(async () => {
    const preview = await page.locator('#pdf-workbench-preview').boundingBox();
    const dock = await page.locator('#officekit-tool-actions').boundingBox();
    return preview && dock && preview.y + preview.height <= dock.y;
  }).toBe(true);
  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('statement_compressed.pdf');
  const compressed = await fs.readFile(await download.path());
  expect(compressed.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(await inspectPdfPageCounts(page, 'compressed.pdf', compressed)).toMatchObject({
    files: [{ index: 0, page_count: 1, status: 'ready' }],
    total_pages: 1,
    ready_count: 1,
    unreadable_count: 0,
  });

  const displayedRatio = (compressed.length / source.length * 100).toFixed(1);
  const comparisonLabel = compressed.length > source.length ? 'output is larger' : 'size change';
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText(`${comparisonLabel}: ${displayedRatio}% of source`);
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('PDF metadata removal downloads a readable copy without the source title', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('[data-pdf-tool="metadata"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'private.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('metadata');

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('private_metadata-removed.pdf');
  const cleaned = await fs.readFile(await download.path());
  expect(cleaned.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(cleaned.toString('latin1')).not.toContain('OfficeKit PDF test fixture');
  expect(await inspectPdfPageCounts(page, 'metadata-cleaned.pdf', cleaned)).toMatchObject({
    files: [{ index: 0, page_count: 1, status: 'ready' }],
    total_pages: 1,
    ready_count: 1,
    unreadable_count: 0,
  });
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('PDF pages-to-images reads the real page-count header and downloads ordered images', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  await page.locator('[data-pdf-tool="images"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'statement.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();

  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('1 pages');
  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('statement_pages.zip');
  const archive = await fs.readFile(await download.path());
  expect(archive.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(archive.indexOf(Buffer.from('page-001.png'))).toBeGreaterThanOrEqual(0);
  expect(archive.subarray(-22, -18)).toEqual(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('PDF pages-to-JPEG passes selected DPI and quality into a readable ZIP download', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const source = await fs.readFile(sourcePath);
  const requests = [];
  page.on('request', request => {
    if (request.url().includes('/api/pdf/images')) requests.push(request);
  });

  await page.locator('[data-pdf-tool="images"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'statement.pdf', mimeType: 'application/pdf', buffer: source,
  });
  await page.locator('#pdf-image-format').selectOption('jpeg');
  await page.locator('#pdf-image-dpi').selectOption('300');
  await page.locator('#pdf-image-quality').fill('82');
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('1 pages');

  expect(requests).toHaveLength(1);
  const body = requests[0].postData();
  expect(body).toContain('name="target_format"\r\n\r\njpeg');
  expect(body).toContain('name="dpi"\r\n\r\n300');
  expect(body).toContain('name="quality"\r\n\r\n82');

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('statement_pages.zip');
  const entries = readZipEntries(await fs.readFile(await download.path()));
  expect(entries.map(entry => entry.name)).toEqual(['page-001.jpg']);
  expect(entries[0].contents.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff]));
  expect(await fs.readFile(sourcePath)).toEqual(source);
});

test('PDF grouped split downloads a ZIP with the named page groups and valid PDFs', async ({ page }) => {
  const sourcePath = new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url);
  const original = await fs.readFile(sourcePath);
  await page.locator('[data-pdf-tool="merge"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles([
    { name: 'first-page.pdf', mimeType: 'application/pdf', buffer: original },
    { name: 'second-page.pdf', mimeType: 'application/pdf', buffer: original },
  ]);
  await page.locator('#pdf-workbench-run').click();
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  const mergedDownloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const mergedDownload = await mergedDownloadReady;
  const twoPages = await fs.readFile(await mergedDownload.path());
  expect(await inspectPdfPageCounts(page, 'two-pages.pdf', twoPages)).toMatchObject({ total_pages: 2, ready_count: 1 });

  const splitRequests = [];
  page.on('request', request => {
    if (request.url().includes('/api/pdf/split/groups')) splitRequests.push(request);
  });
  await page.locator('[data-pdf-tool="split"]').click();
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'two-pages.pdf', mimeType: 'application/pdf', buffer: twoPages,
  });
  await expect(page.locator('#pdf-split-group-ranges-1')).toHaveValue('');
  await expect(page.locator('#pdf-split-group-ranges-2')).toHaveValue('');
  await expect(page.locator('#pdf-workbench-run')).toBeDisabled();
  expect(splitRequests).toHaveLength(0);
  await page.locator('#pdf-split-group-name-1').fill('front.pdf');
  await page.locator('#pdf-split-group-ranges-1').fill('1');
  await page.locator('#pdf-split-group-name-2').fill('back.pdf');
  await page.locator('#pdf-split-group-ranges-2').fill('1');
  await expect(page.locator('#pdf-split-preview-list')).toContainText('front.pdf — pages 1');
  const splitState = await page.evaluate(() => ({
    activePdfTool,
    disabled: document.getElementById('pdf-workbench-run').disabled,
    groups: pdfSplitGroups.map(group => ({ name: group.name, pageRanges: group.pageRanges })),
  }));
  expect(splitState).toEqual({
    activePdfTool: 'split',
    disabled: false,
    groups: [{ name: 'front.pdf', pageRanges: '1' }, { name: 'back.pdf', pageRanges: '1' }],
  });
  await page.locator('#pdf-workbench-run').focus();
  await page.locator('#pdf-workbench-run').press('Enter');
  await expect(page.locator('#pdf-workbench-status')).toContainText('A page cannot be repeated');
  expect(splitRequests).toHaveLength(0);

  await page.locator('#pdf-split-group-ranges-2').fill('2');
  await expect(page.locator('#pdf-workbench-run')).toBeEnabled();
  await expect(page.locator('#pdf-split-group-add')).toBeVisible();
  expect(await page.evaluate(() => pdfSplitGroups.map(group => group.pageRanges))).toEqual(['1', '2']);
  const splitResponse = page.waitForResponse(response => response.url().includes('/api/pdf/split/groups'));
  await page.locator('#pdf-workbench-run').click();
  await splitResponse;
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  await expect(page.locator('#pdf-split-group-add')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Copy summary' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download' }).last()).toBeVisible();
  await expect(page.locator('#pdf-workbench-preview-text')).toContainText('KiB');
  await expect.poll(async () => {
    const splitPreview = await page.locator('#pdf-workbench-preview').boundingBox();
    const splitDock = await page.locator('#officekit-tool-actions').boundingBox();
    return splitPreview && splitDock && splitPreview.y + splitPreview.height <= splitDock.y;
  }).toBe(true);
  expect(splitRequests).toHaveLength(1);

  const downloadReady = page.waitForEvent('download');
  await clickPdfOutputDownload(page);
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('two-pages_split-pages.zip');
  const archive = await fs.readFile(await download.path());
  expect(archive.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  const entries = readStoredZipEntries(archive);
  expect(entries.map(entry => entry.name)).toEqual(['front.pdf', 'back.pdf']);
  for (const entry of entries) {
    expect(entry.bytes.subarray(0, 5).toString('ascii')).toBe('%PDF-');
    expect(await inspectPdfPageCounts(page, entry.name, entry.bytes)).toMatchObject({
      files: [{ index: 0, page_count: 1, status: 'ready' }],
      total_pages: 1,
      ready_count: 1,
      unreadable_count: 0,
    });
  }
  expect(await fs.readFile(sourcePath)).toEqual(original);
  await page.locator('#pdf-split-group-ranges-2').fill('3');
  await expect(page.locator('#pdf-split-group-add')).toBeVisible();
});
