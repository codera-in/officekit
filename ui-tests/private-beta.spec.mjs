import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test.skip(process.env.OFFICEKIT_RELEASE_PROFILE !== 'private-beta', 'Beta-specific scope acceptance');

test('beta exposes supported bank-statement and PDF password tools while blocking held tools', async ({ context, page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`, origin: 'tauri://localhost' },
    });
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).toHaveText('50 tools');
  await expect(page.locator('#release-profile-badge')).toBeVisible();
  await expect(page.locator('#announcement-banner-text')).toContainText('50 tools');
  await expect(page.locator('#announcement-banner-text')).toContainText('5 reminder tools');
  await expect(page.locator('#announcement-banner-text')).toContainText('7 selected-file utilities');
  await expect(page.locator('#announcement-banner-text')).toContainText('1 bank-statement exporter');
  await expect(page.locator('#announcement-banner-text')).toContainText('3 image tools');
  await expect(page.locator('#announcement-banner-text')).toContainText('9 PDF utilities');
  await expect(page.locator('#announcement-banner-text')).toContainText('2 PDF password tools');
  await expect(page.getByRole('button', { name: 'Activate', exact: true })).toHaveCount(0);
  for (const selector of ['button[title="Check for Updates"]', 'button[title="Help & Bug Report"]', '#license-badge-btn']) await expect(page.locator(selector)).toBeHidden();
  await expect(page.getByRole('button', { name: /Statements/ })).toBeVisible();
  await page.locator('#tool-gallery-category').selectOption('System');
  await expect(page.locator('#tool-gallery-category')).toHaveValue('System');
  await expect(page.locator('#tool-gallery-results')).toContainText('System Information');
  await page.locator('#tool-gallery-category').selectOption('Audio & Dictation');
  await expect(page.locator('#tool-gallery-results')).toContainText('Voice Transcription');
  await expect(page.locator('#tool-gallery-results')).toContainText('Meeting Notes');
  await page.locator('#tool-gallery-category').selectOption('');
  for (const query of ['PDF to CSV', 'PDF to XLSX']) {
    await page.locator('#tool-gallery-search').fill(query);
    await expect(page.locator('#tool-gallery-status')).toHaveText('2 tools');
    await expect(page.locator('#tool-gallery-results article')).toHaveCount(2);
    await expect(page.locator('#tool-gallery-results [data-open-tool="pdf_table_extractor"]')).toContainText('Extract PDF Tables');
    await expect(page.locator('#tool-gallery-results [data-open-tool="bank_statement"]')).toContainText('Bank Statement Extractor');
  }
  for (const query of ['similar images']) {
    await page.locator('#tool-gallery-search').fill(query);
    await expect(page.locator('#tool-gallery-status')).toHaveText('0 tools');
    await expect(page.locator('#tool-gallery-results article')).toHaveCount(0);
  }
  await page.locator('#tool-gallery-search').fill('dictation');
  await expect(page.locator('#tool-gallery-status')).toHaveText('2 tools');
  await expect(page.locator('#tool-gallery-results [data-open-tool="voice_transcription"]')).toBeVisible();
  await expect(page.locator('#tool-gallery-results [data-open-tool="meeting_notes"]')).toBeVisible();
  await page.locator('#tool-gallery-search').fill('Voice Transcription');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await page.locator('#tool-gallery-results [data-open-tool="voice_transcription"]').click();
  await expect(page.locator('#audio-tool-title')).toHaveText('Voice Transcription');
  await expect(page.locator('#dictation-hotkey-toggle')).toBeVisible();
  await expect(page.locator('#meeting-record-toggle')).toBeHidden();
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('Meeting Notes');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await page.locator('#tool-gallery-results [data-open-tool="meeting_notes"]').click();
  await expect(page.locator('#audio-tool-title')).toHaveText('Meeting Notes');
  await expect(page.locator('#dictation-hotkey-toggle')).toBeHidden();
  await expect(page.locator('#meeting-record-toggle')).toBeVisible();
  await page.locator('#tool-gallery-category').selectOption('');
  await page.locator('#tool-gallery-search').fill('Image Converter');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await expect(page.locator('#tool-gallery-results [data-open-tool="image_converter"]')).toBeVisible();
  await page.locator('#tool-gallery-search').fill('Resize Images');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await expect(page.locator('#tool-gallery-results [data-open-tool="image_resize"]')).toBeVisible();
  await page.locator('#tool-gallery-search').fill('Remove Image Metadata');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await page.locator('#tool-gallery-results [data-open-tool="image_exif_strip"]').click();
  await expect(page.locator('#image-metadata-panel')).toBeVisible();
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('unlock pdf');
  await expect(page.locator('#tool-gallery-status')).toHaveText('2 tools');
  await expect(page.locator('#tool-gallery-results [data-open-tool="pdf_unlock"]')).toContainText('PDF Password Remover');
  await page.locator('#tool-gallery-results [data-open-tool="pdf_unlock"]').click();
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('#pdf-task-title')).toHaveText('Unlock PDF (known password)');
  await expect(page.locator('[data-pdf-tool="unlock"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="protect"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="merge"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="split"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="compress"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="images"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="metadata"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="tables"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="text"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="delete-pages"]')).toBeVisible();
  await expect(page.locator('[data-pdf-tool="reorder-pages"]')).toBeVisible();
  const allowedPdfTools = await page.evaluate(() => ({ merge: openPdfTool('merge', false), split: openPdfTool('split', false), compress: openPdfTool('compress', false), images: openPdfTool('images', false), metadata: openPdfTool('metadata', false), tables: openPdfTool('tables', false), text: openPdfTool('text', false), deletePages: openPdfTool('delete-pages', false), reorderPages: openPdfTool('reorder-pages', false), unlock: openPdfTool('unlock', false) }));
  expect(allowedPdfTools).toEqual({ merge: true, split: true, compress: true, images: true, metadata: true, tables: true, text: true, deletePages: true, reorderPages: true, unlock: true });
  await page.locator('#pdf-workbench-file-input').setInputFiles({
    name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF document'),
  });
  const unlockResponsePromise = page.waitForResponse(response => response.url().includes('/api/pdf/unlock'));
  await page.getByRole('button', { name: 'Unlock PDF', exact: true }).click();
  const unlockResponse = await unlockResponsePromise;
  expect(unlockResponse.status()).toBe(400);
  await expect(page.locator('#pdf-workbench-status')).toContainText('The PDF could not be processed.');
  await expect(page.locator('#pdf-workbench-download')).toBeHidden();
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('protect pdf');
  await expect(page.locator('#tool-gallery-status')).toHaveText('1 tool');
  await expect(page.locator('#tool-gallery-results article')).toContainText('PDF AES-256 Protector');
  await page.locator('#tool-gallery-results article').click();
  await expect(page.locator('#pdf-task-title')).toHaveText('Protect PDF');
  const source = await fs.readFile(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url));
  await page.locator('#pdf-workbench-file-input').setInputFiles({ name: 'beta-source.pdf', mimeType: 'application/pdf', buffer: source });
  expect(await page.evaluate(() => pdfSelectedFiles.map(file => ({ name: file.name, size: file.size })))).toEqual([{ name: 'beta-source.pdf', size: source.length }]);
  await page.getByLabel('New PDF password', { exact: true }).fill('beta password 123');
  await page.getByLabel('Confirm new PDF password', { exact: true }).fill('beta password 123');
  const protectResponsePromise = page.waitForResponse(response => response.url().includes('/api/pdf/protect'));
  await page.locator('#pdf-workbench-run').click();
  const protectResponse = await protectResponsePromise;
  expect(protectResponse.status()).toBe(200);
  await expect(page.locator('#pdf-workbench-status')).toContainText('Output is ready');
  const protectedDownload = page.waitForEvent('download');
  await page.locator('#pdf-workbench-download').click();
  const protectedFile = await protectedDownload;
  const protectedBytes = await fs.readFile(await protectedFile.path());
  expect(protectedBytes.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  const passwordRoundTrip = await page.request.post('http://127.0.0.1:19873/api/pdf/unlock', {
    headers: { authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    multipart: { password: 'beta password 123', file: { name: 'protected.pdf', mimeType: 'application/pdf', buffer: protectedBytes } },
  });
  expect(passwordRoundTrip.status()).toBe(200);
  expect(Buffer.from(await passwordRoundTrip.body()).subarray(0, 5).toString('ascii')).toBe('%PDF-');
  expect(source.subarray(0, 5).toString('ascii')).toBe('%PDF-');
  const attempts = await page.evaluate(async () => {
    const selected = selectSearchTool('bank_statement');
    const tab = switchTab('dictate') !== false;
    const system = switchTab('system') !== false;
    const pricing = switchTab('pricing');
    return { selected, tab, system, pricing };
  });
  expect(attempts).toEqual({ selected: true, tab: true, system: true, pricing: false });
  await page.evaluate(() => switchTab('statement'));
  await expect(page.locator('#tab-statement')).toBeVisible();
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#tab-dictate')).toBeVisible();
  await page.getByRole('button', { name: 'JSON & text tools', exact: true }).click();
  await expect(page.locator('#developer-tools-panel')).toBeVisible();
  await expect(page.locator('#generic-converter-panel')).toBeHidden();
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('');
  await expect(page.locator('#tool-gallery-status')).toHaveText('50 tools');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: testInfo.outputPath('private-beta-gallery.png'), fullPage: true });
  await page.getByRole('button', { name: 'Dismiss announcement', exact: true }).click();
  await expect(page.locator('#inapp-announcement-banner')).toBeHidden();
  expect(errors).toEqual([]);
});

test('unavailable release scope cannot expose legacy tools or execute shortcuts', async ({ context, page }) => {
  const calls = [];
  await context.route('**/api/**', async route => {
    calls.push(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Unavailable"}' });
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).toContainText('could not verify');
  await expect(page.locator('#legacy-tool-pages')).toBeHidden();
  await expect(page.locator('#tool-gallery-results article')).toHaveCount(0);
  const unavailableRoutes = await page.evaluate(() => ({
    calculator: selectSearchTool('loan_emi'),
    calculatorsTab: switchTab('calculators'),
    heldPdfTool: openPdfTool('merge'),
  }));
  expect(unavailableRoutes).toEqual({ calculator: false, calculatorsTab: false, heldPdfTool: false });
  expect(calls).toEqual(['/api/release']);
});
