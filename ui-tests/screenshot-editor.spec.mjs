import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';


const apiPort = process.env.OFFICEKIT_UI_TEST_API_PORT || '19873';
const uiPort = process.env.OFFICEKIT_UI_TEST_UI_PORT || '19874';

test.beforeEach(async ({ context, page }) => {
  const webOrigin = process.env.OFFICEKIT_UI_TEST_ORIGIN || `http://127.0.0.1:${process.env.OFFICEKIT_UI_TEST_UI_PORT || '19874'}`;
  const apiPort = process.env.OFFICEKIT_UI_TEST_API_PORT || '19873';
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== `http://127.0.0.1:${uiPort}`) {
      await route.abort();
    } else if (url.pathname === '/api/screenshot/edit') {
      const body = route.request().postData() || '';
      const format = body.match(/name="format"\r\n\r\n(\w+)/)?.[1] || 'png';
      if (format === 'jpeg') {
        await route.fulfill({ status: 200, contentType: 'image/jpeg', body: Buffer.from([0xff, 0xd8, 0xff]) });
      } else {
        const dimensions = /"type"\s*:\s*"crop"/.test(body) ? [100, 60] : /"type"\s*:\s*"rotate"/.test(body) ? [80, 120] : [120, 80];
        await route.fulfill({ status: 200, contentType: 'image/png', body: await makeEditedScreenshotPng(page, ...dimensions) });
      }
    } else if (url.pathname === '/api/media-image-stagings' && route.request().method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        stagingId: '55555555-5555-4555-8555-555555555555', filename: 'edited-screenshot.png',
        sizeBytes: 512, mediaType: 'image/png', width: 120, height: 80, expiresInSeconds: 300,
      }) });
    } else if (url.pathname.startsWith('/api/media-image-stagings/') && route.request().method() === 'DELETE') {
      await route.fulfill({ status: 204, body: '' });
    } else if (url.pathname.startsWith('/api/')) {
      const response = await route.fetch({
        url: `http://127.0.0.1:${apiPort}${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
      await route.fulfill({ response });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('screenshot'));
});

test('exported screenshot can be explicitly handed to Media Toolkit as a short-lived staged image', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'handoff.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  await page.locator('#screenshot-rotate').click();
  await page.locator('#screenshot-export-button').click();
  await expect(page.locator('#screenshot-media-toolkit-button')).toBeEnabled();
  await page.locator('#screenshot-more-menu > summary').click();
  await expect(page.locator('#screenshot-more-menu')).toHaveJSProperty('open', true);
  await page.locator('#screenshot-media-toolkit-button').click();
  await expect(page.locator('#media-toolkit-panel')).toBeVisible();
  await expect(page.locator('#media-toolkit-file-list')).toContainText('edited-screenshot.png · edited copy');
  await expect(page.locator('#media-toolkit-run')).toBeEnabled();
  await expect(page.locator('#media-toolkit-status')).toContainText('editor export remains unchanged');
});

async function makeScreenshotPng(page) {
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 120;
    canvas.height = 80;
    const context = canvas.getContext('2d');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, 120, 80);
    context.fillStyle = '#0044cc';
    context.fillRect(25, 20, 45, 35);
    return canvas.toDataURL('image/png');
  });
  return Buffer.from(dataUrl.split(',')[1], 'base64');
}

async function makeEditedScreenshotPng(page, width, height) {
  const dataUrl = await page.evaluate(([imageWidth, imageHeight]) => {
    const canvas = document.createElement('canvas');
    canvas.width = imageWidth;
    canvas.height = imageHeight;
    const context = canvas.getContext('2d');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, imageWidth, imageHeight);
    context.fillStyle = '#ff00ff';
    context.fillRect(10, 10, Math.min(15, imageWidth - 10), Math.min(15, imageHeight - 10));
    return canvas.toDataURL('image/png');
  }, [width, height]);
  return Buffer.from(dataUrl.split(',')[1], 'base64');
}

test('rectangle and text annotations can be applied and exported using keyboard region controls', async ({ page }) => {
  await expect(page.locator('#screenshot-action-dock')).toBeVisible();
  await expect(page.locator('#screenshot-toolbar')).not.toContainText('Copy image');
  await expect(page.locator('#screenshot-action-dock')).toHaveCSS('position', 'fixed');
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'annotation.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  await expect(page.locator('#screenshot-canvas')).toBeVisible();
  await page.locator('#screenshot-advanced-settings summary').click();
  await expect(page.locator('#screenshot-apply-region')).not.toHaveAttribute('data-officekit-docked');
  await page.locator('#screenshot-shape-picker summary').click();
  await page.getByRole('button', { name: 'Rectangle', exact: true }).click();
  for (const [name, value] of Object.entries({ x: 5, y: 5, width: 30, height: 20 })) {
    await page.locator(`#screenshot-region-${name}`).fill(String(value));
  }
  await page.getByRole('button', { name: 'Apply selected tool' }).click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await page.getByRole('button', { name: 'Text', exact: true }).click();
  await page.locator('#screenshot-annotation-text').fill('Review');
  await page.getByRole('button', { name: 'Apply selected tool' }).click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('2 edits');
  await page.locator('#screenshot-export-button').click();
  await expect(page.locator('#screenshot-export-status')).toContainText('Download started');
  await expect(page.locator('#screenshot-copy-button')).toBeEnabled();
});

test('placing text returns to Select so another click moves it instead of duplicating it', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'text-move.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  const canvas = page.locator('#screenshot-canvas');
  const box = await canvas.boundingBox();
  const dimensions = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
  const point = (x, y) => ({ x: x * box.width / dimensions.width, y: y * box.height / dimensions.height });
  await page.locator('#screenshot-tool-text').click();
  await canvas.click({ position: point(12, 12) });
  const editor = page.getByRole('textbox', { name: /Annotation text/ });
  await editor.fill('Move');
  await editor.press('Enter');
  await expect(page.locator('#screenshot-tool-select')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await canvas.click({ position: point(14, 13) });
  const beforeMove = await page.locator('#screenshot-selection').boundingBox();
  await page.mouse.move(box.x + point(14, 13).x, box.y + point(14, 13).y);
  await page.mouse.down();
  await page.mouse.move(box.x + point(30, 24).x, box.y + point(30, 24).y, { steps: 3 });
  await page.mouse.up();
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await expect(page.locator('#screenshot-status')).toContainText('Select to move');
  const afterMove = await page.locator('#screenshot-selection').boundingBox();
  expect(afterMove.x).toBeGreaterThan(beforeMove.x + 10);
  expect(afterMove.y).toBeGreaterThan(beforeMove.y + 10);
});

test('a new text box starts empty, so extra clicks never save a copy of the last text', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'text-empty.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  const canvas = page.locator('#screenshot-canvas');
  const box = await canvas.boundingBox();
  const dimensions = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
  const point = (x, y) => ({ x: x * box.width / dimensions.width, y: y * box.height / dimensions.height });
  const editors = page.getByRole('textbox', { name: /Annotation text/ });
  await page.locator('#screenshot-tool-text').click();
  await canvas.click({ position: point(12, 12) });
  await editors.fill('Fd');
  await editors.press('Enter');
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  // Placing text again opens an empty box; leaving it empty saves nothing.
  await page.locator('#screenshot-tool-text').click();
  await canvas.click({ position: point(100, 60) });
  await expect(editors).toHaveCount(1);
  await expect(editors).toHaveValue('');
  // Clicking elsewhere moves the empty box there; it is still empty and still only one box.
  await canvas.click({ position: point(90, 20) });
  await expect(editors).toHaveCount(1);
  await expect(editors).toHaveValue('');
  await editors.press('Enter');
  await expect(editors).toHaveCount(0);
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
});

test('Freehand draws the pointer path live instead of showing a rectangular region', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'freehand.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  const canvas = page.locator('#screenshot-canvas');
  await page.locator('#screenshot-tool-freehand').click();
  const box = await canvas.boundingBox();
  const dimensions = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
  const point = (x, y) => ({ x: box.x + x * box.width / dimensions.width, y: box.y + y * box.height / dimensions.height });
  const start = point(10, 10);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  for (const [x, y] of [[20, 30], [40, 15], [70, 60]]) {
    const next = point(x, y);
    await page.mouse.move(next.x, next.y);
  }
  const preview = page.locator('#screenshot-canvas-stage svg[aria-hidden="true"] polyline').last();
  await expect(preview).toBeVisible();
  await expect(page.locator('#screenshot-selection')).toBeHidden();
  const previewPoints = await preview.getAttribute('points');
  expect(previewPoints.split(' ')).toHaveLength(4);
  const end = point(70, 60);
  await page.mouse.up(end);
  await expect(page.locator('#screenshot-object-list')).toContainText('Freehand');
  await expect(page.locator('#screenshot-status')).toContainText('Freehand added');
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
});

test('directional stamps, rotation, pixelation and annotation erasing compose through undoable edits', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'expanded-tools.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  const canvas=page.locator('#screenshot-canvas');
  await page.locator('#screenshot-stamp-picker summary').click();
  await page.locator('[data-stamp="check"]').click();
  await expect(page.locator('#screenshot-stamp-picker')).not.toHaveAttribute('open');
  await dragCanvasRegion(page,canvas,12,12,32,24);
  await expect(page.locator('#screenshot-object-list')).toContainText('Stamp');
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await page.locator('#screenshot-rotate').click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('80 × 120');
  await page.locator('#screenshot-tool-pixelate').click();
  await dragCanvasRegion(page,canvas,4,4,20,18);
  await expect(page.locator('#screenshot-dimensions')).toContainText('3 edits');
  await page.locator('#screenshot-tool-eraser').click();
  await dragCanvasRegion(page,canvas,35,40,10,10);
  await expect(page.locator('#screenshot-dimensions')).toContainText('2 edits');
  await expect(page.locator('#screenshot-status')).toContainText('annotation erased');
  await page.locator('#screenshot-undo-button').click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('3 edits');
});

test('zoom scales a large fitted image by one step instead of its backing pixel size', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'large-image.png', mimeType: 'image/png', buffer: await makeEditedScreenshotPng(page, 2400, 1600) });
  const canvas=page.locator('#screenshot-canvas');
  const before=await canvas.evaluate(node=>node.getBoundingClientRect().width);
  await page.locator('#screenshot-zoom-in').click();
  const after=await canvas.evaluate(node=>node.getBoundingClientRect().width);
  expect(after/before).toBeGreaterThan(1.18);
  expect(after/before).toBeLessThan(1.22);
});

test('Copy image shows a success toast and surfaces clipboard failures', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'copy.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  await page.evaluate(() => {
    window.officekitEditScreenshot = async () => ({ blob: new Blob(['png'], { type: 'image/png' }), fileName: 'copy.png' });
    window.officekitWriteScreenshotClipboardImage = async () => {};
  });
  await page.locator('#screenshot-more-menu > summary').click();
  await page.locator('#screenshot-copy-button').click();
  await expect(page.locator('#app-feedback-toast')).toContainText('Edited image copied to the clipboard.');
  await page.evaluate(() => { window.officekitWriteScreenshotClipboardImage = async () => { throw new Error('Clipboard access denied.'); }; });
  await page.locator('#screenshot-copy-button').click();
  await expect(page.locator('#app-feedback-toast')).toContainText('Clipboard access denied.');
  await expect(page.locator('#app-feedback-toast')).toHaveAttribute('role', 'alert');
});

async function dragCanvasRegion(page, canvas, x, y, width, height) {
  const box = await canvas.boundingBox();
  const dimensions = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
  const point = (px, py) => ({
    x: box.x + px * box.width / dimensions.width,
    y: box.y + py * box.height / dimensions.height,
  });
  const start = point(x, y);
  const end = point(x + width, y + height);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 3 });
  await page.mouse.up();
}

test('screenshot editor pastes an image and clears it without calling the processor', async ({ page }) => {
  await expect(page.locator('#screenshot-source-actions')).toBeVisible();
  await expect(page.locator('#screenshot-toolbar')).toBeHidden();
  let processorCalls = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/screenshot/edit') processorCalls += 1;
  });
  const png = await makeScreenshotPng(page);
  const base64 = png.toString('base64');
  await page.evaluate(value => {
    const binary = atob(value);
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], 'pasted-screenshot.png', { type: 'image/png' }));
    document.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: transfer }));
  }, base64);

  await expect(page.locator('#screenshot-canvas')).toBeVisible();
  await expect(page.locator('#screenshot-status')).toContainText('Image ready');
  await expect(page.locator('#screenshot-export-button')).toBeEnabled();
  await expect(page.locator('#screenshot-dimensions')).toContainText('120 × 80');
  await expect(page.locator('#screenshot-file-name')).toHaveText('pasted-screenshot.png');
  await expect(page.locator('#screenshot-source-actions')).toBeHidden();
  await expect(page.locator('#screenshot-filebar')).toBeVisible();
  await expect(page.locator('#screenshot-toolbar')).toBeVisible();
  expect(processorCalls).toBe(0);

  await page.locator('#screenshot-image-menu summary').click();
  await page.getByRole('button', { name: 'Clear editor' }).click();
  await expect(page.locator('#screenshot-canvas')).toBeHidden();
  await expect(page.locator('#screenshot-dimensions')).toHaveText('No image selected');
  await expect(page.locator('#screenshot-source-actions')).toBeVisible();
  await expect(page.locator('#screenshot-filebar')).toBeHidden();
  await expect(page.locator('#screenshot-toolbar')).toBeHidden();
  await expect(page.locator('#screenshot-status')).toContainText('Clipboard contents were not changed');
});

test('screenshot editor reads a clipboard image from the native Tauri bridge on explicit paste', async ({ page }) => {
  await page.evaluate(() => {
    window.__TAURI__ = {
      clipboardManager: {
        readImage: async () => ({
          size: async () => ({ width: 3, height: 2 }),
          rgba: async () => new Uint8Array(3 * 2 * 4).fill(255),
        }),
      },
    };
  });

  await page.getByRole('link', { name: 'Paste from clipboard' }).click();

  await expect(page.locator('#screenshot-canvas')).toBeVisible();
  await expect(page.locator('#screenshot-dimensions')).toContainText('3 × 2');
  await expect(page.locator('#screenshot-status')).toContainText('Image ready');
});

test('annotation toolbar stays reachable while scrolling a maximized editor workspace', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'large-workspace.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  const shell = page.locator('#screenshot-editor-shell');
  await shell.evaluate(node => { node.style.minHeight = '1400px'; });
  const main = page.locator('#app-main');
  const toolbar = page.locator('#screenshot-toolbar');
  await expect(toolbar).toBeVisible();
  await expect(toolbar).toHaveCSS('position', 'sticky');
  await main.evaluate(node => { node.scrollTop = 500; });
  const firstTop = await toolbar.evaluate(node => node.getBoundingClientRect().top);
  await main.evaluate(node => { node.scrollTop = 600; });
  await expect.poll(async () => {
    const secondTop = await toolbar.evaluate(node => node.getBoundingClientRect().top);
    return Math.abs(secondTop - firstTop);
  }).toBeLessThan(3);
});

test('screenshot editor crops, blurs, masks, undoes, redoes and exports an opaque PNG', async ({ page }) => {
  const source = await makeScreenshotPng(page);
  const sourceFile = page.locator('#screenshot-file-input');
  await sourceFile.setInputFiles({ name: 'synthetic-screen.png', mimeType: 'image/png', buffer: source });
  const canvas = page.locator('#screenshot-canvas');
  await expect(canvas).toBeVisible();
  await expect(page.locator('#screenshot-filebar')).toHaveClass(/flex/);
  await expect(page.locator('#screenshot-dimensions')).toContainText('120 × 80');

  await page.getByRole('button', { name: 'Blur selected area' }).click();
  await dragCanvasRegion(page, canvas, 5, 5, 20, 20);
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await expect(page.locator('#screenshot-undo-button')).toBeEnabled();
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('0 edits');
  await page.getByRole('button', { name: 'Redo' }).click();
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');

  await page.getByRole('button', { name: 'Crop image' }).click();
  await dragCanvasRegion(page, canvas, 10, 10, 100, 60);
  await expect(page.locator('#screenshot-dimensions')).toContainText('100 × 60');
  await page.locator('#screenshot-mask-color').evaluate(input => {
    input.value = '#ff00ff';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.getByRole('button', { name: 'Opaque mask' }).click();
  await dragCanvasRegion(page, canvas, 10, 10, 15, 15);

  const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/screenshot/edit');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('image/png');
  await expect(page.getByRole('link', { name: 'Download screenshot-edited.png' })).toBeVisible();
  await expect(page.locator('#screenshot-copy-button')).toBeEnabled();

  const downloadReady = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download screenshot-edited.png' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('screenshot-edited.png');
  const edited = await page.evaluate(async base64 => {
    const binary = atob(base64);
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
    const output = document.createElement('canvas');
    output.width = bitmap.width;
    output.height = bitmap.height;
    const context = output.getContext('2d', { willReadFrequently: true });
    context.drawImage(bitmap, 0, 0);
    const pixel = [...context.getImageData(17, 17, 1, 1).data];
    bitmap.close();
    return { width: output.width, height: output.height, pixel };
  }, (await fs.readFile(await download.path())).toString('base64'));
  expect(edited.width).toBe(100);
  expect(edited.height).toBe(60);
  expect(edited.pixel).toEqual([255, 0, 255, 255]);

  await page.locator('#screenshot-export-format').selectOption('jpeg');
  const jpegResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/screenshot/edit');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const jpegResponse = await jpegResponsePromise;
  expect(jpegResponse.status()).toBe(200);
  expect(jpegResponse.headers()['content-type']).toContain('image/jpeg');
  const jpegDownloadReady = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download screenshot-edited.jpg' }).click();
  const jpegDownload = await jpegDownloadReady;
  const jpeg = await fs.readFile(await jpegDownload.path());
  expect(jpegDownload.suggestedFilename()).toBe('screenshot-edited.jpg');
  expect([...jpeg.subarray(0, 3)]).toEqual([0xff, 0xd8, 0xff]);

  await expect(sourceFile).toHaveValue('');
  await expect(page.locator('#screenshot-export-status')).toContainText('Metadata was removed');
});

test('screenshot toolbar controls share uniform 38px height and vertical center alignment', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'alignment-test.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  await expect(page.locator('#screenshot-toolbar')).toBeVisible();

  const toolbarMetrics = await page.evaluate(() => {
    const annotNav = document.querySelector('#screenshot-toolbar nav[aria-label="Annotation tools"]');
    const privNav = document.querySelector('#screenshot-toolbar nav[aria-label="Privacy tools"]');
    const annotButtons = [...annotNav.querySelectorAll(':scope > button, :scope > details > summary')];
    const privButtons = [...privNav.querySelectorAll(':scope > button')];

    const getMetrics = el => {
      const rect = el.getBoundingClientRect();
      return {
        id: el.id || el.getAttribute('aria-label') || el.title || el.tagName,
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        centerY: Math.round(rect.top + rect.height / 2),
      };
    };

    return {
      annot: annotButtons.map(getMetrics),
      priv: privButtons.map(getMetrics),
    };
  });

  // Check all annotation buttons (including shape and stamp summaries)
  for (const m of toolbarMetrics.annot) {
    expect(m.height).toBe(38);
    expect(m.width).toBe(38);
  }

  // Check privacy buttons (fit-view has text label and icon)
  for (const m of toolbarMetrics.priv) {
    expect(m.height).toBe(38);
    if (m.id !== 'screenshot-fit-view' && m.id !== 'Fit image to view') {
      expect(m.width).toBe(38);
    }
  }

  // All buttons in each nav group should share identical vertical center within 1px
  const annotY = toolbarMetrics.annot.map(m => m.centerY);
  expect(Math.max(...annotY) - Math.min(...annotY)).toBeLessThanOrEqual(1);

  const privY = toolbarMetrics.priv.map(m => m.centerY);
  expect(Math.max(...privY) - Math.min(...privY)).toBeLessThanOrEqual(1);
});

test('options bar controls share uniform height and precise vertical center alignment', async ({ page }) => {
  await page.locator('#screenshot-file-input').setInputFiles({ name: 'options-alignment.png', mimeType: 'image/png', buffer: await makeScreenshotPng(page) });
  await page.locator('#screenshot-shape-picker summary').click();
  await page.locator('#screenshot-tool-rectangle').click();

  await expect(page.locator('#screenshot-stroke-control')).toBeVisible();
  await expect(page.locator('#screenshot-outer-width-control')).toBeVisible();

  const optionsMetrics = await page.evaluate(() => {
    const desc = document.getElementById('screenshot-tool-description');
    const strokeControl = document.getElementById('screenshot-stroke-control');
    const outerControl = document.getElementById('screenshot-outer-width-control');
    const strokeInput = document.getElementById('screenshot-stroke-width');
    const outerInput = document.getElementById('screenshot-outer-width');
    const objList = document.getElementById('screenshot-object-list');
    const deleteBtn = document.getElementById('screenshot-delete-button');

    const getMetrics = el => {
      const rect = el.getBoundingClientRect();
      return {
        id: el.id,
        height: Math.round(rect.height),
        centerY: Math.round(rect.top + rect.height / 2),
      };
    };

    return {
      inputs: [strokeInput, outerInput, deleteBtn].map(getMetrics),
      rowItems: [desc, strokeControl, outerControl, deleteBtn].map(getMetrics),
    };
  });

  // Inputs, selects, and buttons in the sub-toolbar must share 28px height
  for (const item of optionsMetrics.inputs) {
    expect(item.height).toBeGreaterThanOrEqual(27);
    expect(item.height).toBeLessThanOrEqual(29);
  }

  // Controls on the same flex line in the options bar must have aligned vertical centers (within 2px)
  const lines = new Map();
  for (const item of optionsMetrics.rowItems) {
    const lineKey = Math.round(item.centerY / 20) * 20;
    if (!lines.has(lineKey)) lines.set(lineKey, []);
    lines.get(lineKey).push(item.centerY);
  }
  for (const [, ys] of lines) {
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThanOrEqual(2);
  }
});

