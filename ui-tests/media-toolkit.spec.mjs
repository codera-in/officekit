import { expect, test } from '@playwright/test';
import path from 'node:path';
import { mkdir } from 'node:fs/promises';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

async function getMediaOperationCount(page) {
  const apiPort = process.env.OFFICEKIT_UI_API_PORT || '19873';
  const response = await page.request.get(`http://127.0.0.1:${apiPort}/api/media-capabilities`, {
    headers: { authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
  });
  expect(response.ok()).toBe(true);
  const capabilities = await response.json();
  const operations = capabilities.media.flatMap(media => media.operations);
  expect(operations.map(operation => operation.id)).toContain('pdf-uncrop');
  return operations.length;
}

test('Media Toolkit discovers all operations and gates them by local adapter availability', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await expect(page.locator('#media-toolkit-panel')).toBeVisible();
  const operationCount = await getMediaOperationCount(page);
  await expect(page.locator('#media-toolkit-coverage')).toContainText(`of ${operationCount} operations available`);
  await expect(page.locator('#media-toolkit-operation-list li')).toHaveCount(operationCount);
  await expect(page.locator('#media-toolkit-operation option[value="image-optimize"]')).toBeEnabled();

  await page.locator('#media-toolkit-kind').selectOption('video');
  const videoAvailability = await page.locator('#media-toolkit-operation option[value="video-optimize"]').isEnabled();
  expect(videoAvailability).toBe(process.platform === 'darwin');
  expect(await page.locator('#media-toolkit-operation option[value="video-hevc-convert"]').isEnabled()).toBe(process.platform === 'darwin');
  expect(await page.locator('#media-toolkit-operation option[value="video-mute"]').isEnabled()).toBe(process.platform === 'darwin');
  expect(await page.locator('#media-toolkit-operation option[value="video-resize"]').isEnabled()).toBe(process.platform === 'darwin');

  await page.locator('#media-toolkit-kind').selectOption('pdf');
  await expect(page.locator('#media-toolkit-operation option[value="pdf-lossless-compress"]')).toBeEnabled();
  await page.locator('#media-toolkit-operation').selectOption('pdf-visual-optimize');
  await expect(page.locator('#media-toolkit-fidelity-warning')).toContainText('Searchable text');
  await expect(page.locator('#media-toolkit-operation option[value="pdf-visual-optimize"]')).toBeEnabled();
  const dimensions = await page.locator('#media-toolkit-panel').evaluate(panel => ({ width: panel.scrollWidth, viewport: panel.clientWidth }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(errors).toEqual([]);
});

test('Media Toolkit keeps all expanded preparation disclosures within the visible button limit', async ({ page }, testInfo) => {
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines**', route => route.fulfill({ json: [] }));
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-url-panel > summary').click();
  await page.locator('section[aria-labelledby="media-toolkit-settings-heading"] > details > summary').click();
  await page.locator('#media-toolkit-results-panel > summary').click();
  await page.locator('#media-toolkit-results-panel details > summary').click();
  const visibleButtons = await page.locator('#media-toolkit-panel button.btn').evaluateAll(buttons => buttons.filter(button => {
    const rect = button.getBoundingClientRect();
    return button.getClientRects().length && rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth &&
      !button.matches('[aria-pressed],.link,.ok-text-link,.row-act,.tl') && !button.closest('[hidden],.hidden,dialog:not([open]),details:not([open])');
  }).map(button => button.textContent.trim().replace(/\s+/g, ' ')));
  const actionDock = page.locator('#media-toolkit-action-dock');
  await expect(actionDock).toBeVisible();
  await expect(actionDock.locator('.ok-action-dock__controls > :is(button,a):visible')).toHaveCount(2);
  const converterLink = page.getByRole('link', { name: '← Other converter tools' });
  await expect(converterLink).toHaveAttribute('href', '#generic-converter-panel');
  await expect(converterLink).toBeVisible();
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/media_toolkit-expanded-disclosures-${testInfo.project.name}.png`), fullPage: true });
  expect(visibleButtons.length, visibleButtons.join(' | ')).toBeLessThanOrEqual(3);
  await converterLink.click();
  await expect(page.locator('#media-toolkit-panel')).toBeHidden();
  await expect(page.locator('#generic-converter-panel')).toBeVisible();
});

test('preset zones bind to saved pipelines and enable only for the current session', async ({ page }) => {
  const pipelineId = '77777777-7777-4777-8777-777777777777';
  const zoneId = '99999999-9999-4999-8999-999999999999';
  const pipeline = { id: pipelineId, name: 'Web images', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused' };
  let zone = null;
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-preset-zones**', async route => {
    const method = route.request().method();
    if (method === 'GET') return route.fulfill({ json: zone ? [zone] : [] });
    if (method === 'POST') { zone = { id: zoneId, ...route.request().postDataJSON(), enabled: false }; return route.fulfill({ status: 201, json: zone }); }
    if (method === 'PATCH') { zone = { ...zone, ...route.request().postDataJSON() }; return route.fulfill({ json: zone }); }
    if (method === 'DELETE') { zone = null; return route.fulfill({ status: 204 }); }
    return route.fulfill({ status: 405 });
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-zone-name').fill('Web drop');
  await page.locator('#media-toolkit-zone-pipeline').selectOption(pipelineId);
  await page.locator('#media-toolkit-zone-create').click();
  const zoneRow = page.locator('#media-toolkit-zone-list li');
  await expect(zoneRow).toContainText('Web drop');
  await expect(zoneRow).toContainText('Off');
  await zoneRow.getByRole('button', { name: 'Enable for session' }).click();
  await expect(zoneRow).toContainText('Enabled · this session');
  await zoneRow.getByRole('button', { name: 'Use preset' }).click();
  await expect(page.locator('#media-toolkit-prepare-view')).toBeVisible();
  await expect(page.locator('#media-toolkit-operation')).toHaveValue('image-strip-metadata');
  await page.locator('#media-toolkit-tab-automations').click();
  await zoneRow.getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#media-toolkit-zone-list')).toContainText('No preset zones yet.');
});

test('pinned pipeline runs on explicit drop-zone drops through the ordinary safe job path', async ({ page }) => {
  const pipelineId = '71717171-7171-4717-8717-717171717171';
  const selectionId = '72727272-7272-4727-8727-727272727272';
  const fileId = '73737373-7373-4737-8737-737373737373';
  const jobId = '74747474-7474-4747-8747-747474747474';
  const pipeline = { id: pipelineId, name: 'Strip image metadata', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused' };
  const selection = { id: selectionId, access: 'read', files: [{ id: fileId, name: 'photo.png', size_bytes: 512 }], hasMore: false };
  const bindings = { 'drop-zone': pipelineId };
  let submittedJob = null;
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-pipeline-triggers**', route => route.fulfill({ json: bindings }));
  await page.route(`**/api/file-selections/${selectionId}`, route => route.request().method() === 'GET' ? route.fulfill({ json: selection }) : route.fulfill({ status: 204 }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedJob = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{ fileId, name: 'photo.png', state: 'ready', artifactId: null, outputName: 'photo_prepared.png', outputType: 'image/png', inputBytes: 512, outputBytes: 400, attributes: {}, errorCode: null }] } }));
  await page.addInitScript(() => {
    window.__officekitMediaDropHandlers = {};
    window.__TAURI__ = { event: { listen: async (name, handler) => { window.__officekitMediaDropHandlers[name] = handler; return () => {}; } }, core: { invoke: async () => null } };
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  const operationCount = await getMediaOperationCount(page);
  await expect(page.locator('#media-toolkit-coverage')).toContainText(`of ${operationCount} operations available`);
  await page.evaluate(selectionId => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId } }), selectionId);
  await expect(page.locator('#media-toolkit-status')).toContainText('Results are ready');
  expect(submittedJob.items[0].source).toEqual({ kind: 'selection', selectionId, fileId });
  expect(submittedJob.items[0].operations).toEqual(pipeline.operations);
});

test('a media-mismatched pinned drop preserves the existing batch and releases only the rejected grant', async ({ page }) => {
  const pipelineId = '75757575-7575-4757-8757-757575757575';
  const imageSelectionId = '76767676-7676-4767-8767-767676767676';
  const pdfSelectionId = '78787878-7878-4787-8787-787878787878';
  const pipeline = { id: pipelineId, name: 'Strip image metadata', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused' };
  const selections = {
    [imageSelectionId]: { id: imageSelectionId, access: 'read', files: [{ id: '79797979-7979-4797-8797-797979797979', name: 'existing.png', size_bytes: 512 }], hasMore: false },
    [pdfSelectionId]: { id: pdfSelectionId, access: 'read', files: [{ id: '80808080-8080-4808-8808-808080808080', name: 'wrong.pdf', size_bytes: 1024 }], hasMore: false },
  };
  let bindings = {};
  const deletedSelectionIds = [];
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-pipeline-triggers**', route => route.fulfill({ json: bindings }));
  await page.route('**/api/file-selections/**', async route => {
    const selectionId = new URL(route.request().url()).pathname.split('/').at(-1);
    if (route.request().method() === 'GET') return route.fulfill({ json: selections[selectionId] });
    deletedSelectionIds.push(selectionId);
    return route.fulfill({ status: 204 });
  });
  await page.addInitScript(() => {
    window.__officekitMediaDropHandlers = {};
    window.__TAURI__ = { event: { listen: async (name, handler) => { window.__officekitMediaDropHandlers[name] = handler; return () => {}; } }, core: { invoke: async () => null } };
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.evaluate(selectionId => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId } }), imageSelectionId);
  await expect(page.locator('#media-toolkit-file-list')).toContainText('existing.png');
  bindings = { 'drop-zone': pipelineId };
  await page.evaluate(selectionId => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId } }), pdfSelectionId);
  await expect(page.locator('#media-toolkit-status')).toContainText('does not match every dropped file');
  await expect(page.locator('#media-toolkit-file-list')).toContainText('existing.png');
  await expect(page.locator('#media-toolkit-file-list')).not.toContainText('wrong.pdf');
  await expect.poll(() => deletedSelectionIds).toContain(pdfSelectionId);
  expect(deletedSelectionIds).not.toContain(imageSelectionId);
});

test('a media-mismatched preset-zone drop preserves the existing batch and releases only the rejected grant', async ({ page }) => {
  const pipelineId = '81818181-8181-4818-8818-818181818181';
  const zoneId = '82828282-8282-4828-8828-828282828282';
  const imageSelectionId = '83838383-8383-4838-8838-838383838383';
  const pdfSelectionId = '84848484-8484-4848-8848-848484848484';
  const pipeline = { id: pipelineId, name: 'Strip image metadata', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused' };
  const zone = { id: zoneId, name: 'Image zone', pipelineId, enabled: true };
  const selections = {
    [imageSelectionId]: { id: imageSelectionId, access: 'read', files: [{ id: '85858585-8585-4858-8858-858585858585', name: 'existing.png', size_bytes: 512 }], hasMore: false },
    [pdfSelectionId]: { id: pdfSelectionId, access: 'read', files: [{ id: '86868686-8686-4868-8868-868686868686', name: 'wrong.pdf', size_bytes: 1024 }], hasMore: false },
  };
  const deletedSelectionIds = [];
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-pipeline-triggers**', route => route.fulfill({ json: {} }));
  await page.route('**/api/media-preset-zones**', route => route.fulfill({ json: [zone] }));
  await page.route('**/api/file-selections/**', async route => {
    const selectionId = new URL(route.request().url()).pathname.split('/').at(-1);
    if (route.request().method() === 'GET') return route.fulfill({ json: selections[selectionId] });
    deletedSelectionIds.push(selectionId);
    return route.fulfill({ status: 204 });
  });
  await page.addInitScript(() => {
    window.__officekitMediaDropHandlers = {};
    window.__TAURI__ = { event: { listen: async (name, handler) => { window.__officekitMediaDropHandlers[name] = handler; return () => {}; } }, core: { invoke: async () => null } };
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  await expect(page.locator('#media-toolkit-zone-list')).toContainText('Image zone');
  await page.locator('#media-toolkit-tab-prepare').click();
  await page.evaluate(selectionId => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId } }), imageSelectionId);
  await expect(page.locator('#media-toolkit-file-list')).toContainText('existing.png');
  await page.evaluate(({ selectionId, zoneId: targetZoneId }) => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId, presetZoneId: targetZoneId } }), { selectionId: pdfSelectionId, zoneId });
  await expect(page.locator('#media-toolkit-status')).toContainText('does not match every dropped file');
  await expect(page.locator('#media-toolkit-file-list')).toContainText('existing.png');
  await expect(page.locator('#media-toolkit-file-list')).not.toContainText('wrong.pdf');
  await expect.poll(() => deletedSelectionIds).toContain(pdfSelectionId);
  expect(deletedSelectionIds).not.toContain(imageSelectionId);
});

test('operation defaults persist through the shared private API and can be cleared', async ({ page }) => {
  const defaults = {};
  const requests = [];
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-operation-defaults**', async route => {
    const method = route.request().method();
    requests.push({ method, path: new URL(route.request().url()).pathname });
    if (method === 'GET') return route.fulfill({ json: defaults });
    if (method === 'PUT') {
      const operationId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1));
      defaults[operationId] = route.request().postDataJSON().options;
      return route.fulfill({ json: { operationId, options: defaults[operationId] } });
    }
    if (method === 'DELETE') { for (const key of Object.keys(defaults)) delete defaults[key]; return route.fulfill({ status: 204 }); }
    return route.fulfill({ status: 405 });
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-optimize');
  await page.locator('#media-toolkit-settings-fields [data-option-key="quality"]').fill('71');
  await page.evaluate(() => { document.getElementById('media-toolkit-options').closest('details').open = true; });
  await page.locator('#media-toolkit-save-local-default').click();
  await expect(page.locator('#media-toolkit-local-default-status')).toContainText('Saved a local default');
  expect(defaults['image-optimize']).toEqual({ quality: 71, preserveMetadata: false });
  await page.locator('#media-toolkit-operation').selectOption('image-convert');
  await page.locator('#media-toolkit-operation').selectOption('image-optimize');
  await expect(page.locator('#media-toolkit-settings-fields [data-option-key="quality"]')).toHaveValue('71');
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-local-defaults > summary').click();
  await page.locator('#media-toolkit-clear-local-defaults').click();
  await expect(page.locator('#media-toolkit-local-default-status')).toContainText('cleared');
  expect(defaults).toEqual({});
  expect(requests.map(request => request.method)).toEqual(['GET', 'PUT', 'DELETE']);
});

test('dropping onto an enabled preset zone submits its allowlisted pipeline and preserves the source grant', async ({ page }) => {
  const pipelineId = '77777777-7777-4777-8777-777777777777';
  const zoneId = '99999999-9999-4999-8999-999999999999';
  const selectionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const fileId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const jobId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const pipeline = { id: pipelineId, name: 'Web images', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused' };
  const selection = { id: selectionId, access: 'read', files: [{ id: fileId, name: 'photo.png', size_bytes: 1024, media_type: 'image/png' }], hasMore: false };
  let zone = null;
  let submittedJob = null;
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-preset-zones**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: zone ? [zone] : [] });
    if (route.request().method() === 'POST') { zone = { id: zoneId, ...route.request().postDataJSON(), enabled: false }; return route.fulfill({ status: 201, json: zone }); }
    if (route.request().method() === 'PATCH') { zone = { ...zone, ...route.request().postDataJSON() }; return route.fulfill({ json: zone }); }
    return route.fulfill({ status: 204 });
  });
  await page.route(`**/api/file-selections/${selectionId}`, route => route.request().method() === 'GET' ? route.fulfill({ json: selection }) : route.fulfill({ status: 204 }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedJob = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{ fileId, name: 'photo.png', state: 'ready', artifactId: null, outputName: null, outputType: null, inputBytes: 1024, outputBytes: 700, attributes: {}, errorCode: null }] } }));
  await page.addInitScript(({ zoneId }) => {
    window.__officekitMediaDropHandlers = {};
    window.__officekitDropTargetCalls = [];
    window.__TAURI__ = {
      event: { listen: async (name, handler) => { window.__officekitMediaDropHandlers[name] = handler; return () => {}; } },
      core: { invoke: async (command, args) => { if (command === 'media_toolkit_drop_set_enabled') window.__officekitDropTargetCalls.push(args); return null; } },
    };
  }, { zoneId });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-zone-name').fill('Web drop');
  await page.locator('#media-toolkit-zone-pipeline').selectOption(pipelineId);
  await page.locator('#media-toolkit-zone-create').click();
  const zoneRow = page.locator('#media-toolkit-zone-list li');
  await zoneRow.getByRole('button', { name: 'Enable for session' }).click();
  await expect.poll(async () => page.evaluate(zoneId => window.__officekitDropTargetCalls.some(call => call.targets?.some(target => target.id === zoneId)), zoneId)).toBe(true);
  await expect.poll(async () => page.evaluate(() => typeof window.__officekitMediaDropHandlers['officekit-media-file-drop'] === 'function')).toBe(true);
  await page.evaluate(({ selectionId, zoneId }) => window.__officekitMediaDropHandlers['officekit-media-file-drop']({ payload: { id: selectionId, presetZoneId: zoneId } }), { selectionId, zoneId });
  await expect(page.locator('#media-toolkit-status')).toContainText('Results are ready');
  expect(submittedJob.items[0].source).toEqual({ kind: 'selection', selectionId, fileId });
  expect(submittedJob.items[0].operations).toEqual(pipeline.operations);
  await expect(page.locator('#media-toolkit-recent-summary')).toContainText('1 of 1 files · ready');
});

test('opt-in Control+Shift+C prepares the current clipboard image and ignores non-image clipboard items', async ({ page }) => {
  const stagingId = '12121212-1212-4212-8212-121212121212';
  const artifactId = '13131313-1313-4313-8313-131313131313';
  const jobId = '14141414-1414-4414-8414-141414141414';
  const submittedJobs = [];
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-image-stagings', route => route.fulfill({ status: 200, json: { stagingId, filename: 'clipboard.png', mediaType: 'image/png', width: 2, height: 2, sizeBytes: 64, expiresInSeconds: 300 } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedJobs.push(route.request().postDataJSON());
    return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{ fileId: null, name: 'clipboard.png', state: 'ready', artifactId, outputName: 'clipboard_prepared.png', outputType: 'image/png', inputBytes: 64, outputBytes: 48, attributes: {}, errorCode: null }] } }));
  await page.route(`**/api/media-artifacts/${artifactId}`, route => route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]) }));
  await page.addInitScript(() => {
    window.__officekitHotkeyEvents = {};
    window.__officekitClipboardRevision = 7;
    window.__officekitClipboardWriteCount = 0;
    window.__officekitClipboardFile = new File([new Uint8Array([1, 2, 3, 4])], 'clipboard.png', { type: 'image/png' });
    window.__TAURI__ = {
      event: { listen: async (name, handler) => { window.__officekitHotkeyEvents[name] = handler; return () => {}; } },
      core: { invoke: async (command, args) => command === 'media_clipboard_hotkey_set_enabled' ? args.enabled : command === 'media_clipboard_revision' ? window.__officekitClipboardRevision : null },
    };
  });
  await page.goto('/');
  await waitForAppReady(page);
  await page.evaluate(() => {
    window.officekitReadScreenshotClipboardFile = async () => window.__officekitClipboardFile;
    window.officekitWriteScreenshotClipboardImage = async () => { window.__officekitClipboardWriteCount += 1; window.__officekitClipboardRevision += 1; };
  });
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  expect(await page.evaluate(() => localStorage.getItem('officekit.media.clipboardAutomation'))).not.toBe('true');
  await page.locator('#media-toolkit-hotkey-enable').check();
  await expect(page.locator('#media-toolkit-hotkey-status')).toContainText('Control+Shift+C is on');
  await page.evaluate(() => window.__officekitHotkeyEvents['officekit-media-clipboard-hotkey']());
  await expect(page.locator('#media-toolkit-hotkey-status')).toContainText('The prepared image is on the clipboard');
  expect(submittedJobs).toHaveLength(1);
  expect(submittedJobs[0].items[0].source).toEqual({ kind: 'staged-image', stagingId });
  expect(submittedJobs[0].items[0].operations).toEqual([{ operationId: 'image-optimize', options: { quality: 82, preserveMetadata: false } }]);
  expect(await page.evaluate(() => window.__officekitClipboardWriteCount)).toBe(1);
  await page.evaluate(() => { window.__officekitClipboardFile = null; window.__officekitHotkeyEvents['officekit-media-clipboard-hotkey'](); });
  await expect(page.locator('#media-toolkit-hotkey-status')).toContainText('does not contain a readable image');
  expect(submittedJobs).toHaveLength(1);
  expect(await page.evaluate(() => window.__officekitClipboardWriteCount)).toBe(1);
});

test('clipboard hotkey runs the pipeline pinned through shared local settings', async ({ page }) => {
  const pipelineId = '75757575-7575-4757-8757-757575757575';
  const stagingId = '76767676-7676-4767-8767-767676767676';
  const artifactId = '77777777-7777-4777-8777-777777777777';
  const jobId = '78787878-7878-4787-8787-787878787878';
  const pipeline = { id: pipelineId, name: 'Clipboard WebP', media: 'image', operations: [{ operationId: 'image-convert', options: { targetFormat: 'webp', quality: 88 } }], state: 'paused' };
  const submittedJobs = [];
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [pipeline] }));
  await page.route('**/api/media-pipeline-triggers**', route => route.fulfill({ json: { clipboard: pipelineId } }));
  await page.route('**/api/media-image-stagings', route => route.fulfill({ status: 200, json: { stagingId, filename: 'clipboard.png', mediaType: 'image/png', width: 2, height: 2, sizeBytes: 64, expiresInSeconds: 300 } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedJobs.push(route.request().postDataJSON());
    return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: { id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{ fileId: null, name: 'clipboard.png', state: 'ready', artifactId, outputName: 'clipboard_prepared.webp', outputType: 'image/webp', inputBytes: 64, outputBytes: 48, attributes: {}, errorCode: null }] } }));
  await page.route(`**/api/media-artifacts/${artifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: Buffer.from('RIFF0000WEBP') }));
  await page.addInitScript(() => {
    window.__officekitHotkeyEvents = {};
    window.__officekitClipboardWriteCount = 0;
    window.__officekitClipboardFile = new File([new Uint8Array([1, 2, 3, 4])], 'clipboard.png', { type: 'image/png' });
    window.__TAURI__ = {
      event: { listen: async (name, handler) => { window.__officekitHotkeyEvents[name] = handler; return () => {}; } },
      core: { invoke: async (command, args) => command === 'media_clipboard_hotkey_set_enabled' ? args.enabled : command === 'media_clipboard_revision' ? 1 : null },
    };
  });
  await page.goto('/');
  await waitForAppReady(page);
  await page.evaluate(() => {
    window.officekitReadScreenshotClipboardFile = async () => window.__officekitClipboardFile;
    window.officekitWriteScreenshotClipboardImage = async () => { window.__officekitClipboardWriteCount += 1; };
  });
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-hotkey-enable').check();
  await page.evaluate(() => window.__officekitHotkeyEvents['officekit-media-clipboard-hotkey']());
  await expect(page.locator('#media-toolkit-hotkey-status')).toContainText('The prepared image is on the clipboard');
  expect(submittedJobs[0].items[0].operations).toEqual(pipeline.operations);
  expect(await page.evaluate(() => window.__officekitClipboardWriteCount)).toBe(1);
});

test('Finder image Quick Action installs and removes through explicit native actions', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.addInitScript(() => {
    window.__officekitFinderCommands = [];
    window.__officekitFinderInstalled = false;
    window.__TAURI__ = {
      event: { listen: async () => () => {} },
      core: { invoke: async (command, args) => {
        window.__officekitFinderCommands.push(command);
        if (command === 'media_finder_action_status') return window.__officekitFinderInstalled ? 'installed' : 'not-installed';
        if (command === 'media_finder_action_install') { window.__officekitFinderInstalled = true; return 'installed'; }
        if (command === 'media_finder_action_remove') { window.__officekitFinderInstalled = false; return 'not-installed'; }
        if (command === 'media_clipboard_hotkey_set_enabled') return args.enabled;
        return null;
      } },
    };
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-tab-automations').click();
  const install = page.locator('#media-toolkit-finder-install');
  const remove = page.locator('#media-toolkit-finder-remove');
  await expect(page.locator('#media-toolkit-finder-status')).toContainText('Quick Action is not installed');
  await expect(install).toBeVisible();
  await expect(install).toBeEnabled();
  await expect(remove).toBeHidden();
  await install.click();
  await expect(remove).toBeVisible();
  await expect(page.locator('#media-toolkit-finder-status')).toContainText('Quick Action is installed');
  await remove.click();
  await expect(install).toBeVisible();
  await expect(remove).toBeHidden();
  const calls = await page.evaluate(() => window.__officekitFinderCommands);
  expect(calls).toContain('media_finder_action_install');
  expect(calls).toContain('media_finder_action_remove');
});

test('Media Toolkit settings match validated operation choices and synchronize MiB values', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);

  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-optimize');
  await page.locator('#media-toolkit-settings-fields [data-option-key="preserveMetadata"]').check();
  await expect.poll(async () => JSON.parse(await page.locator('#media-toolkit-options').inputValue()).preserveMetadata).toBe(true);
  await page.locator('#media-toolkit-operation').selectOption('image-fit-size');
  const targetBytes = page.locator('#media-toolkit-settings-fields [data-option-key="targetBytes"]');
  await expect(targetBytes).toHaveAttribute('min', '9.5367431640625e-7');
  await expect(targetBytes).toHaveAttribute('step', 'any');
  await targetBytes.fill('0.00000095367431640625');
  await expect.poll(async () => JSON.parse(await page.locator('#media-toolkit-options').inputValue()).targetBytes).toBe(1);
  await targetBytes.fill('5.25');
  const options = page.locator('#media-toolkit-options');
  await expect.poll(async () => JSON.parse(await options.inputValue()).targetBytes).toBe(5_505_024);

  await page.locator('#media-toolkit-kind').selectOption('pdf');
  await page.locator('#media-toolkit-operation').selectOption('pdf-lossless-compress');
  const profile = page.locator('#media-toolkit-settings-fields [data-option-key="profile"]');
  await expect(profile.locator('option')).toHaveText(['FAST', 'BALANCED', 'MAXIMUM']);
  await page.locator('#media-toolkit-operation').selectOption('pdf-crop');
  const pageSize = page.locator('#media-toolkit-settings-fields [data-option-key="pageSize"]');
  await expect(pageSize.locator('option')).toHaveText(['A4', 'LETTER', 'MOBILE', 'TABLET']);

  await page.locator('#media-toolkit-kind').selectOption('audio');
  await page.locator('#media-toolkit-operation').selectOption('audio-artwork');
  const artworkEdge = page.locator('#media-toolkit-settings-fields [data-option-key="maxEdge"]');
  await expect(artworkEdge).toHaveValue('1024');
  await expect(artworkEdge).toHaveAttribute('min', '64');
  await expect(artworkEdge).toHaveAttribute('max', '4096');
  await page.locator('#media-toolkit-operation').selectOption('audio-optimize');
  const format = page.locator('#media-toolkit-result-format');
  await expect(page.locator('#media-toolkit-format-bar')).toBeVisible();
  const audioFormats = await page.evaluate(async () => {
    const capabilities = await (await window.officekitDirectFetch('/api/media-capabilities')).json();
    return capabilities.media.find(group => group.id === 'audio').operations.find(operation => operation.id === 'audio-optimize').formats.map(value => value.toUpperCase());
  });
  await expect(format.locator('option')).toHaveText(audioFormats);
  await format.selectOption('wav');
  await expect.poll(async () => JSON.parse(await page.locator('#media-toolkit-options').inputValue()).targetFormat).toBe('wav');
  await expect(page.locator('#media-toolkit-settings-fields [data-option-key="bitrateKbps"]')).toHaveAttribute('max', '640');
  await page.evaluate(() => { document.getElementById('media-toolkit-options').closest('details').open = true; });
  await page.locator('#media-toolkit-save-local-default').click();
  await expect(page.locator('#media-toolkit-local-default-status')).toContainText('No files or media are stored');
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-local-defaults summary').click();
  await page.locator('#media-toolkit-local-default-search').fill('audio optimize');
  const savedAudioDefault = page.locator('#media-toolkit-local-default-list li');
  await expect(savedAudioDefault).toHaveCount(1);
  await expect(savedAudioDefault).toContainText('Saved local default');
  await savedAudioDefault.getByRole('button', { name: 'Use settings' }).click();
  await expect(page.locator('#media-toolkit-prepare-view')).toBeVisible();
  await expect.poll(async () => JSON.parse(await page.locator('#media-toolkit-options').inputValue()).targetFormat).toBe('wav');
  await page.locator('#media-toolkit-kind').selectOption('pdf');
  await page.locator('#media-toolkit-operation').selectOption('pdf-lossless-compress');
  await expect(page.locator('#media-toolkit-format-bar')).toBeHidden();
});

test('capability-probed AV1 is available in the video result format bar', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-capabilities', route => route.fulfill({ json: {
    version: 1, maxInputBytes: 67_108_864, maxBatchItems: 30,
    media: [{ id: 'video', label: 'Video', operations: [
      { id: 'video-optimize', label: 'Optimize / convert video', available: true, formats: ['m4v', 'mov', 'av1'], reason: null },
      { id: 'video-fit-size', label: 'Fit video to size', available: true, formats: ['m4v', 'mov', 'av1'], reason: null },
    ] }],
  } }));
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-kind').selectOption('video');
  await page.locator('#media-toolkit-operation').selectOption('video-optimize');
  const format = page.locator('#media-toolkit-result-format');
  await expect(format.locator('option')).toHaveText(['M4V', 'MOV', 'AV1']);
  await format.selectOption('av1');
  await expect.poll(async () => JSON.parse(await page.locator('#media-toolkit-options').inputValue()).targetFormat).toBe('av1');
  await page.locator('#media-toolkit-operation').selectOption('video-fit-size');
  await expect(page.locator('#media-toolkit-result-format option[value="av1"]')).toBeAttached();
});

test('Automation view grants, pauses, resumes and removes a watched folder with an allowlisted pipeline', async ({ page }) => {
  const pipelineId = '77777777-7777-4777-8777-777777777777';
  const watchId = '88888888-8888-4888-8888-888888888888';
  let watch = null;
  let added = false;
  await page.exposeFunction('mockFolderGranted', value => { watch = value; added = true; });
  await page.addInitScript(({ watchId }) => {
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command !== 'media_folder_watch_open') return null;
      const granted = { id: watchId, folderName: 'Incoming', pipelineId: args.pipelineId, pipelineName: 'Web images', state: 'watching', processedCount: 0, lastOutcome: null };
      await window.mockFolderGranted(granted);
      return granted;
    } } };
  }, { watchId });
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', route => route.fulfill({ json: [{
    id: pipelineId, name: 'Web images', media: 'image', operations: [{ operationId: 'image-strip-metadata', options: {} }], state: 'paused',
  }] }));
  await page.route(`**/api/media-folder-watches/${watchId}`, async route => {
    if (route.request().method() === 'PATCH') {
      watch = { ...watch, state: route.request().postDataJSON().paused ? 'paused' : 'watching' };
      return route.fulfill({ json: watch });
    }
    if (route.request().method() === 'DELETE') { watch = null; return route.fulfill({ status: 204 }); }
    return route.continue();
  });
  await page.route('**/api/media-folder-watches', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: added && watch ? [watch] : [] });
    return route.continue();
  });
  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  const automations = page.locator('#media-toolkit-tab-automations');
  await automations.click();
  await expect(automations).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#media-toolkit-automations-view')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Clipboard monitoring' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Bypass next clipboard item' })).toBeEnabled();
  await expect(page.locator('#media-toolkit-clipboard-opt-in')).not.toBeChecked();
  await page.getByRole('button', { name: 'Bypass next clipboard item' }).click();
  await expect(page.locator('#media-toolkit-clipboard-status')).toContainText('next changed clipboard item will be skipped');
  await page.locator('#media-toolkit-folder-pipeline').selectOption(pipelineId);
  await expect(page.locator('#media-toolkit-folder-add')).toBeEnabled();
  await page.locator('#media-toolkit-folder-add').click();
  const folderList = page.locator('#media-toolkit-folder-list');
  await expect(folderList).toContainText('Incoming');
  await folderList.getByRole('button', { name: 'Pause' }).click();
  await expect(folderList).toContainText('Paused');
  await folderList.getByRole('button', { name: 'Resume' }).click();
  await expect(folderList).toContainText('Watching');
  await folderList.getByRole('button', { name: 'Remove grant' }).click();
  await expect(folderList).toContainText('No folders are granted');
  await expect(page.getByRole('heading', { name: 'Saved pipelines' })).toBeVisible();
  await page.locator('#media-toolkit-tab-prepare').click();
  await expect(page.locator('#media-toolkit-prepare-view')).toBeVisible();
});

test('Media Toolkit result compares sizes and reports an unmet target honestly', async ({ page }, testInfo) => {
  const selectionId = '11111111-1111-4111-8111-111111111111';
  const fileId = '22222222-2222-4222-8222-222222222222';
  const jobId = '33333333-3333-4333-8333-333333333333';
  const artifactId = '44444444-4444-4444-8444-444444444444';
  const artifactBytes = Buffer.from('RIFF0000WEBPsynthetic-image-data');
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__officekitMediaSaves = [];
    window.__TAURI__ = { event: { listen: async () => () => {} }, core: { invoke: async (command, args) => {
      if (command === 'file_selection_open') return { id: selectionId };
      if (command === 'result_save') { window.__officekitMediaSaves.push(args); return { state: 'saved', name: args.suggestedName }; }
      return null;
    } } };
  }, { selectionId });
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: {
    id: selectionId, access: 'read', files: [{ id: fileId, name: 'photo.png', size_bytes: 1024, media_type: 'image/png' }], hasMore: false,
  } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
    return route.continue();
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: {
    id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{
      fileId, name: 'photo.png', state: 'ready', artifactId,
      outputName: 'photo_prepared.webp', outputType: 'image/webp', inputBytes: 1024, outputBytes: 700,
      attributes: { target_bytes: 512, target_met: false, quality: 30 }, errorCode: null,
    }],
  } }));
  await page.route(`**/api/media-artifacts/${artifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: artifactBytes }));
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#app-feedback-toast')).toBeHidden();
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await mkdir('docs/verification/tool-unification/before', { recursive: true });
  await mkdir('docs/verification/tool-unification/after', { recursive: true });
  await page.screenshot({ path: `docs/verification/tool-unification/before/media_toolkit-initial-${testInfo.project.name}.png`, fullPage: true });
  await page.locator('#media-toolkit-select').click();
  await expect(page.locator('#media-toolkit-run')).toBeEnabled();
  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-fit-size');
  await page.locator('#media-toolkit-run').click();
  const result = page.locator('#media-toolkit-results');
  await expect(result).toContainText('32% smaller than original');
  await expect(result).toContainText('target not met (0.7 KiB / 0.5 KiB)');
  await page.screenshot({ path: `docs/verification/tool-unification/after/media_toolkit-target-result-${testInfo.project.name}.png`, fullPage: true });
  await expect(page.locator('#media-toolkit-save')).toBeVisible();
  await page.locator('#media-toolkit-save').click();
  await expect.poll(() => page.evaluate(() => window.__officekitMediaSaves.length)).toBe(1);
  const saved = await page.evaluate(() => window.__officekitMediaSaves[0]);
  expect(saved.suggestedName).toBe('photo_prepared.webp');
  expect(Buffer.from(saved.base64Data, 'base64')).toEqual(artifactBytes);
  await page.screenshot({ path: `docs/verification/tool-unification/after/media_toolkit-target-saved-${testInfo.project.name}.png`, fullPage: true });
});

test('Media Toolkit Save all downloads every ready artifact with its own name and bytes', async ({ page }, testInfo) => {
  const selectionId = '12121212-1212-4212-8212-121212121212';
  const firstFileId = '23232323-2323-4232-8232-232323232323';
  const secondFileId = '34343434-3434-4343-8343-343434343434';
  const jobId = '45454545-4545-4454-8454-454545454545';
  const firstArtifactId = '56565656-5656-4565-8565-565656565656';
  const secondArtifactId = '67676767-6767-4676-8676-676767676767';
  const firstBytes = Buffer.from('RIFF0000WEBPfirst-image-bytes');
  const secondBytes = Buffer.from('RIFF0000WEBPsecond-image-bytes');
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__officekitMediaSaves = [];
    window.__TAURI__ = { event: { listen: async () => () => {} }, core: { invoke: async (command, args) => {
      if (command === 'file_selection_open') return { id: selectionId };
      if (command === 'result_save') { window.__officekitMediaSaves.push(args); return { state: 'saved', name: args.suggestedName }; }
      return null;
    } } };
  }, { selectionId });
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: {
    id: selectionId, access: 'read', files: [
      { id: firstFileId, name: 'first.png', size_bytes: 1024, media_type: 'image/png' },
      { id: secondFileId, name: 'second.png', size_bytes: 2048, media_type: 'image/png' },
    ], hasMore: false,
  } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
    return route.continue();
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: {
    id: jobId, state: 'ready', progress: 2, total: 2, phase: 'Complete', items: [
      { fileId: firstFileId, name: 'first.png', state: 'ready', artifactId: firstArtifactId, outputName: 'first_prepared.webp', outputType: 'image/webp', inputBytes: 1024, outputBytes: firstBytes.length, attributes: {}, errorCode: null },
      { fileId: secondFileId, name: 'second.png', state: 'ready', artifactId: secondArtifactId, outputName: 'second_prepared.webp', outputType: 'image/webp', inputBytes: 2048, outputBytes: secondBytes.length, attributes: {}, errorCode: null },
    ],
  } }));
  await page.route(`**/api/media-artifacts/${firstArtifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: firstBytes }));
  await page.route(`**/api/media-artifacts/${secondArtifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: secondBytes }));

  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#app-feedback-toast')).toBeHidden();
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await mkdir('docs/verification/tool-unification/before', { recursive: true });
  await mkdir('docs/verification/tool-unification/after', { recursive: true });
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/before/media_toolkit-save-all-initial-${testInfo.project.name}.png`), fullPage: true });
  await page.locator('#media-toolkit-select').click();
  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-fit-size');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-results')).toContainText('first.png');
  await expect(page.locator('#media-toolkit-results')).toContainText('second.png');
  const saveAll = page.locator('#media-toolkit-save');
  await expect(saveAll).toHaveText('Save all');
  await expect(page.locator('#media-toolkit-action-dock .ok-action-dock__controls > :is(button,a):visible')).toHaveCount(2);
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/media_toolkit-save-all-ready-${testInfo.project.name}.png`), fullPage: true });
  await saveAll.click();
  await expect.poll(() => page.evaluate(() => window.__officekitMediaSaves.length)).toBe(2);
  const saved = await page.evaluate(() => window.__officekitMediaSaves.map(item => ({ name: item.suggestedName, bytes: item.base64Data })));
  expect(saved).toEqual([
    { name: 'first_prepared.webp', bytes: firstBytes.toString('base64') },
    { name: 'second_prepared.webp', bytes: secondBytes.toString('base64') },
  ]);
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/media_toolkit-save-all-complete-${testInfo.project.name}.png`), fullPage: true });
});

test('Media Toolkit Save all identifies an expired copy, retains completed saves and retries only the unavailable file', async ({ page }, testInfo) => {
  const selectionId = '81818181-8181-4181-8181-818181818181';
  const firstFileId = '82828282-8282-4282-8282-828282828282';
  const secondFileId = '83838383-8383-4383-8383-838383838383';
  const firstJobId = '84848484-8484-4484-8484-848484848484';
  const retryJobId = '85858585-8585-4585-8585-858585858585';
  const firstArtifactId = '86868686-8686-4686-8686-868686868686';
  const expiredArtifactId = '87878787-8787-4787-8787-878787878787';
  const freshArtifactId = '88888888-8888-4888-8888-888888888888';
  const firstBytes = Buffer.from('RIFF0000WEBPfirst-image-bytes');
  const freshBytes = Buffer.from('RIFF0000WEBPfresh-second-image-bytes');
  const posts = [];
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__officekitMediaSaves = [];
    window.__TAURI__ = { event: { listen: async () => () => {} }, core: { invoke: async (command, args) => {
      if (command === 'file_selection_open') return { id: selectionId };
      if (command === 'result_save') { window.__officekitMediaSaves.push(args); return { state: 'saved', name: args.suggestedName }; }
      return null;
    } } };
  }, { selectionId });
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: {
    id: selectionId, access: 'read', files: [
      { id: firstFileId, name: 'first.png', size_bytes: 1024, media_type: 'image/png' },
      { id: secondFileId, name: 'second.png', size_bytes: 2048, media_type: 'image/png' },
    ], hasMore: false,
  } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    posts.push(route.request().postDataJSON());
    const id = posts.length === 1 ? firstJobId : retryJobId;
    return route.fulfill({ status: 202, json: { id, state: 'queued' } });
  });
  await page.route(`**/api/media-jobs/${firstJobId}`, route => route.fulfill({ json: {
    id: firstJobId, state: 'ready', progress: 2, total: 2, phase: 'Complete', items: [
      { fileId: firstFileId, name: 'first.png', state: 'ready', artifactId: firstArtifactId, outputName: 'first_prepared.webp', outputType: 'image/webp', inputBytes: 1024, outputBytes: firstBytes.length, attributes: {}, errorCode: null },
      { fileId: secondFileId, name: 'second.png', state: 'ready', artifactId: expiredArtifactId, outputName: 'second_prepared.webp', outputType: 'image/webp', inputBytes: 2048, outputBytes: 900, attributes: {}, errorCode: null },
    ],
  } }));
  await page.route(`**/api/media-jobs/${retryJobId}`, route => route.fulfill({ json: {
    id: retryJobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [
      { fileId: secondFileId, name: 'second.png', state: 'ready', artifactId: freshArtifactId, outputName: 'second_prepared.webp', outputType: 'image/webp', inputBytes: 2048, outputBytes: freshBytes.length, attributes: {}, errorCode: null },
    ],
  } }));
  await page.route(`**/api/media-artifacts/${firstArtifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: firstBytes }));
  await page.route(`**/api/media-artifacts/${expiredArtifactId}`, route => route.fulfill({ status: 404, contentType: 'text/plain', body: 'not an image artifact' }));
  await page.route(`**/api/media-artifacts/${freshArtifactId}`, route => route.fulfill({ status: 200, contentType: 'image/webp', body: freshBytes }));

  await page.goto('/');
  await waitForAppReady(page);
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await mkdir('docs/verification/tool-unification/after', { recursive: true });
  await page.locator('#media-toolkit-select').click();
  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-fit-size');
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-save')).toHaveText('Save all');
  await page.locator('#media-toolkit-save').click();
  await expect.poll(() => page.evaluate(() => window.__officekitMediaSaves.length)).toBe(1);
  await expect(page.locator('#media-toolkit-run')).toHaveText('Retry second.png');
  await expect(page.locator('#media-toolkit-results')).toContainText('first.png');
  await expect(page.locator('#media-toolkit-results')).toContainText('Saved');
  await expect(page.locator('#media-toolkit-results')).toContainText('Needs a new copy');
  await expect(page.locator('#media-toolkit-results')).toContainText('Retry this file to prepare a fresh copy.');
  await expect(page.locator('#media-toolkit-save')).toBeHidden();
  await expect(page.locator('#media-toolkit-action-dock .ok-action-dock__controls > :is(button,a):visible')).toHaveCount(2);
  await expect(page.locator('#media-toolkit-status')).toContainText('1 of 2 copies saved. second_prepared.webp is no longer available.');
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/media_toolkit-expired-artifact-${testInfo.project.name}.png`), fullPage: true });

  await page.locator('#media-toolkit-run').click();
  await expect.poll(() => posts.length).toBe(2);
  expect(posts[1].items).toHaveLength(1);
  expect(posts[1].items[0].source.fileId).toBe(secondFileId);
  await expect(page.locator('#media-toolkit-results')).toContainText('second.png');
  await expect(page.locator('#media-toolkit-results')).not.toContainText('Needs a new copy');
  await expect(page.locator('#media-toolkit-save')).toHaveText('Save');
  await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/media_toolkit-expired-artifact-recovered-${testInfo.project.name}.png`), fullPage: true });
  await page.locator('#media-toolkit-save').click();
  await expect.poll(() => page.evaluate(() => window.__officekitMediaSaves.length)).toBe(2);
  const saved = await page.evaluate(() => window.__officekitMediaSaves.map(item => ({ name: item.suggestedName, bytes: item.base64Data })));
  expect(saved).toEqual([
    { name: 'first_prepared.webp', bytes: firstBytes.toString('base64') },
    { name: 'second_prepared.webp', bytes: freshBytes.toString('base64') },
  ]);
  await expect(page.locator('#media-toolkit-results')).toContainText('Saved');
});

test('Voice Transcription hands a native audio selection to Media Toolkit without copying its path', async ({ page }) => {
  const selectionId = '55555555-5555-4555-8555-555555555555';
  const fileId = '66666666-6666-4666-8666-666666666666';
  await routeAuthenticatedApi(page);
  await page.addInitScript(({ selectionId }) => {
    window.__officekitNativeCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      window.__officekitNativeCalls.push({ command, args });
      return command === 'file_selection_open' ? { id: selectionId } : null;
    } } };
  }, { selectionId });
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: {
    id: selectionId, access: 'read', files: [{ id: fileId, name: 'meeting.m4a', size_bytes: 2048 }], hasMore: false,
  } }));
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  expect(await page.evaluate(() => selectSearchTool('voice_transcription'))).toBe(true);
  await expect(page.locator('#dictation-audio-media-button')).toBeVisible();
  await page.locator('#dictation-audio-media-button').click();
  await expect(page.locator('#media-toolkit-panel')).toBeVisible();
  await expect(page.locator('#media-toolkit-file-list')).toContainText('meeting.m4a');
  await expect(page.locator('#media-toolkit-kind')).toHaveValue('audio');
  await expect(page.locator('#media-toolkit-operation')).toHaveValue('audio-optimize');
  const nativeCalls = await page.evaluate(() => window.__officekitNativeCalls);
  const audioSelectionCalls = nativeCalls.filter(call => call.command === 'file_selection_open');
  expect(audioSelectionCalls).toHaveLength(1);
  expect(audioSelectionCalls[0]).toEqual({ command: 'file_selection_open', args: { mode: 'files', access: 'read', filterKind: 'audio' } });
  expect(await page.locator('#media-toolkit-file-list').innerText()).not.toContain('/');
});

test('saved pipelines persist paused and run through the ordinary typed media job', async ({ page }) => {
  const selectionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const fileId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const jobId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  let savedPipeline;
  let submittedJob;
  await routeAuthenticatedApi(page);
  await page.route('**/api/media-pipelines', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [] });
    savedPipeline = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: { id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', ...savedPipeline, state: 'paused' } });
  });
  await page.route('**/api/file-selections', route => route.fulfill({ status: 201, json: { id: selectionId } }));
  await page.route(`**/api/file-selections/${selectionId}`, route => route.fulfill({ json: {
    id: selectionId, access: 'read', files: [{ id: fileId, name: 'photo.png', size_bytes: 1024, media_type: 'image/png' }], hasMore: false,
  } }));
  await page.route('**/api/media-jobs', async route => {
    if (route.request().method() === 'POST') {
      submittedJob = route.request().postDataJSON();
      return route.fulfill({ status: 202, json: { id: jobId, state: 'queued' } });
    }
    return route.continue();
  });
  await page.route(`**/api/media-jobs/${jobId}`, route => route.fulfill({ json: {
    id: jobId, state: 'ready', progress: 1, total: 1, phase: 'Complete', items: [{
      fileId, name: 'photo.png', state: 'ready', artifactId: null, outputName: null, outputType: null,
      inputBytes: 1024, outputBytes: 700, attributes: {}, errorCode: null,
    }],
  } }));
  await page.addInitScript(({ selectionId }) => {
    window.__TAURI__ = { core: { invoke: async command => command === 'file_selection_open' ? { id: selectionId } : null } };
  }, { selectionId });
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  expect(await page.evaluate(() => selectSearchTool('media_toolkit'))).toBe(true);
  await page.locator('#media-toolkit-kind').selectOption('image');
  await page.locator('#media-toolkit-operation').selectOption('image-resize');
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-pipelines summary').click();
  await expect(page.locator('#media-toolkit-pipeline-save')).toBeDisabled();
  await page.locator('#media-toolkit-pipeline-name').fill('Web images');
  await page.locator('#media-toolkit-pipeline-add-step').click();
  await page.locator('#media-toolkit-tab-prepare').click();
  await page.locator('#media-toolkit-operation').selectOption('image-strip-metadata');
  await page.locator('#media-toolkit-tab-automations').click();
  await page.locator('#media-toolkit-pipeline-add-step').click();
  await page.locator('#media-toolkit-pipeline-save').click();
  await expect(page.locator('#media-toolkit-pipeline-list')).toContainText('Paused');
  expect(savedPipeline.media).toBe('image');
  expect(savedPipeline.operations.map(step => step.operationId)).toEqual(['image-resize', 'image-strip-metadata']);
  await page.locator('#media-toolkit-tab-prepare').click();
  await page.locator('#media-toolkit-select').click();
  await page.locator('#media-toolkit-run').click();
  await expect(page.locator('#media-toolkit-status')).toContainText('Results are ready');
  await page.locator('#media-toolkit-tab-automations').click();
  await expect(page.locator('#media-toolkit-recent-summary')).toContainText('1 of 1 files · ready');
  expect(submittedJob.items[0].operations.map(step => step.operationId)).toEqual(['image-resize', 'image-strip-metadata']);
  expect(submittedJob.items[0].source).toEqual({ kind: 'selection', selectionId, fileId });
});
