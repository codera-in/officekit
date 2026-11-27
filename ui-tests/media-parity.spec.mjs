import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const selectionId = '53535353-5353-4353-8353-535353535353';
const imageId = '54545454-5454-4454-8454-545454545454';
const audioId = '55555555-5555-4555-8555-555555555555';
const artifactId = '56565656-5656-4656-8656-565656565656';
const jobId = '57575757-5757-4757-8757-575757575757';
const logoId = '58585858-5858-4858-8858-585858585858';
const capability = (id, formats) => ({ id, label: id, available: true, formats, reason: null });

async function setup(page, files) {
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.nativeMediaCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, payload) => {
      window.nativeMediaCalls.push({ command, payload });
      if (command === 'file_selection_open') return { id: selectionId };
      if (command === 'media_handoff_capabilities') return { available: true, apps: { yoink: true, dropshare: true }, shortcuts: ['Send to Notes'] };
      if (command === 'media_handoff_open') return { state: 'handoff-requested' };
      return null;
    } }, event: { listen: async () => () => {} } };
  }, { selectionId });
  await page.route('**/api/media-capabilities', route => route.fulfill({ json: { version: 1, maxInputBytes: 67108864, maxBatchItems: 30, media: [
    { id: 'image', label: 'Images', operations: [capability('image-optimize', ['jpeg', 'webp']), capability('image-watermark-overlay', ['png'])] },
    { id: 'audio', label: 'Audio', operations: [capability('audio-optimize', ['m4a', 'wav', 'flac', 'mp3']), capability('audio-normalize', ['m4a'])] },
    { id: 'video', label: 'Video', operations: [capability('video-optimize', ['mov', 'mp4', 'webm', 'x265']), capability('video-watermark-overlay', ['mov'])] },
    { id: 'pdf', label: 'PDF', operations: [capability('pdf-lossless-compress', ['pdf'])] },
  ] } }));
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: { id: selectionId, access: 'read', hasMore: false, files } }));
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [] }));
  await page.route('**/api/media-operation-defaults', route => route.fulfill({ json: {} }));
  await page.route('**/api/media-folder-watches', route => route.fulfill({ json: [] }));
  await page.goto('/'); await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-select').click();
  await expect(page.locator('#media-toolkit-file-list')).toContainText(files[0].name);
}

test('mixed batch retains per-type settings and retries only the failed file', async ({ page }) => {
  const submissions = [];
  await setup(page, [{ id: imageId, name: 'photo.jpg', size_bytes: 1000 }, { id: audioId, name: 'voice.wav', size_bytes: 2000 }]);
  // A mixed batch lists its operations under one labelled group per type present.
  await expect(page.locator('#media-toolkit-operation optgroup')).toHaveCount(2);
  await expect(page.locator('#media-toolkit-operation optgroup[label="Images (1 file)"] option[value="image-optimize"]')).toHaveCount(1);
  await expect(page.locator('#media-toolkit-operation optgroup[label="Audio (1 file)"] option[value="audio-optimize"]')).toHaveCount(1);
  await page.route('**/api/media-jobs', async route => {
    submissions.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: { id: jobId } });
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: submissions.length === 1 ? 'partial' : 'ready', progress: submissions.length === 1 ? 2 : 1, total: submissions.length === 1 ? 2 : 1, phase: 'Complete', items: submissions.length === 1 ? [
    { fileId: imageId, name: 'photo.jpg', state: 'ready', artifactId, outputName: 'photo_prepared.jpg', inputBytes: 1000, outputBytes: 700, attributes: {} },
    { fileId: audioId, name: 'voice.wav', state: 'failed', errorCode: 'conversion_failed' },
  ] : [{ fileId: audioId, name: 'voice.wav', state: 'ready', artifactId, outputName: 'voice_prepared.flac', inputBytes: 2000, outputBytes: 1800, attributes: {} }] } }));
  await page.locator('#media-toolkit-settings-fields [data-option-key="quality"]').fill('65');
  await page.getByRole('button', { name: 'Settings for voice.wav', exact: true }).click();
  await page.locator('#media-toolkit-result-format').selectOption('flac');
  await page.locator('#media-toolkit-settings-fields [data-option-key="bitrateKbps"]').fill('128');
  await page.getByRole('button', { name: 'Settings for photo.jpg', exact: true }).click();
  await expect(page.locator('[data-option-key="quality"]')).toHaveValue('65');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-results').getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
  expect(submissions[0].items.map(item => item.operations[0])).toEqual([
    { operationId: 'image-optimize', options: { quality: 65, preserveMetadata: false } },
    { operationId: 'audio-optimize', options: { targetFormat: 'flac', bitrateKbps: 128 } },
  ]);
  await page.locator('#media-toolkit-results').getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('#media-toolkit-status')).toContainText('Results are ready');
  expect(submissions[1].items).toHaveLength(1);
  expect(submissions[1].items[0].source.fileId).toBe(audioId);
  await expect(page.locator('#media-toolkit-results').getByRole('button', { name: 'Save', exact: true })).toHaveCount(2);
  // Done: the bar offers Start over, Save all and the action again, never more than three buttons.
  const bar = await page.evaluate(() => [...document.querySelectorAll('#media-toolkit-action-dock button')].filter(button => button.getClientRects().length).map(button => button.textContent.trim()));
  expect(bar).toHaveLength(3);
  expect(bar[0]).toBe('Start over');
  expect(bar[1]).toBe('Save all');
  expect(bar[2]).toMatch(/again$/);
});

test('logo is explicitly staged once and unchecked batch items are omitted', async ({ page }) => {
  let submitted;
  await setup(page, [{ id: imageId, name: 'photo.jpg', size_bytes: 1000 }, { id: audioId, name: 'voice.wav', size_bytes: 2000 }]);
  await page.route('**/api/media-watermark-stagings', route => route.fulfill({ json: { stagingId: logoId, filename: 'logo.png', expiresInSeconds: 300 } }));
  await page.route('**/api/media-jobs', route => { submitted = route.request().postDataJSON(); return route.fulfill({ status: 202, json: { id: jobId } }); });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [] } }));
  await page.getByRole('checkbox', { name: 'Prepare voice.wav', exact: true }).uncheck();
  await page.locator('#media-toolkit-operation').selectOption('image-watermark-overlay');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-status')).toContainText('Choose a logo');
  expect(submitted).toBeUndefined();
  await page.locator('#media-toolkit-watermark-file').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from('explicit logo fixture') });
  await expect(page.locator('#media-toolkit-watermark-status')).toContainText('ready for one job');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-watermark-status')).toContainText('Logo submitted');
  expect(submitted.items).toHaveLength(1);
  expect(submitted.items[0].operations[0]).toEqual({ operationId: 'image-watermark-overlay', options: { placement: 'bottom-right', marginPercent: 4, sizePercent: 18, opacityPercent: 72 } });
  expect(submitted.watermarkStagingId).toBe(logoId);
});

test('loudness results use LUFS and handoffs require a separate explicit action', async ({ page }) => {
  await setup(page, [{ id: audioId, name: 'voice.wav', size_bytes: 2000 }]);
  await page.route('**/api/media-jobs', route => route.fulfill({ status: 202, json: { id: jobId } }));
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [
    { fileId: audioId, name: 'voice.wav', state: 'ready', artifactId, outputName: 'voice_prepared.m4a', inputBytes: 2000, outputBytes: 1800, attributes: { target_lufs: -14, output_lufs: -19.5, true_peak_dbfs: -2.28, target_met: false } },
  ] } }));
  await page.getByRole('button', { name: 'Settings for voice.wav', exact: true }).click();
  await page.locator('#media-toolkit-operation').selectOption('audio-normalize');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-results')).toContainText('-19.5 LUFS');
  await expect(page.locator('#media-toolkit-results')).toContainText('-2.28 dBTP');
  await expect(page.locator('#media-toolkit-results')).not.toContainText('NaN');
  expect(await page.evaluate(() => window.nativeMediaCalls.filter(call => call.command === 'media_handoff_open'))).toEqual([]);
  await page.getByLabel('Continue with another app for voice.wav', { exact: true }).selectOption('dropshare');
  await page.getByRole('button', { name: 'Save and continue…', exact: true }).click();
  await expect(page.locator('#media-toolkit-results')).toContainText('check the destination app for completion');
  const calls = await page.evaluate(() => window.nativeMediaCalls.filter(call => call.command === 'media_handoff_open'));
  expect(calls).toEqual([{ command: 'media_handoff_open', payload: { artifactId, suggestedName: 'voice_prepared.m4a', destination: 'dropshare', shortcutName: null } }]);
  const dimensions = await page.locator('#media-toolkit-panel').evaluate(panel => ({ width: panel.scrollWidth, viewport: panel.clientWidth }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  await page.screenshot({ path: test.info().outputPath('media-toolkit-after.png'), fullPage: true });
});
