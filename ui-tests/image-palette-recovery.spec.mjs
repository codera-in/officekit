import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

const evidence = path.resolve('docs/verification/tool-unification/after');

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
});

test('Dominant Colors clears stale actions on transparent-only input and recovers with exact CSV', async ({ page }, testInfo) => {
  await page.locator('[data-image-tool-link="image_palette"]').click();
  await page.screenshot({ path: path.join(evidence, `image_palette-current-source-empty-${testInfo.project.name}-20261103.png`), fullPage: true });
  const file = page.locator('#tab-image-tools input[type=file][data-slot=file]');
  const transparent = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 8;
    canvas.height = 8;
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await file.setInputFiles({ name: 'transparent-only.png', mimeType: 'image/png', buffer: Buffer.from(transparent, 'base64') });
  const result = page.locator('#tab-image-tools [data-role=palette]');
  await expect(result).toContainText('no opaque pixels');
  await expect(result.locator('[role=alert]')).toHaveAttribute('data-officekit-no-bug-report', '');
  await expect(result.getByRole('button', { name: 'Report bug' })).toHaveCount(0);
  await expect(result.locator('[data-officekit-docked="true"] button')).toHaveCount(0);
  await page.screenshot({ path: path.join(evidence, `image_palette-current-source-transparent-error-${testInfo.project.name}-20261103.png`), fullPage: true });

  const twoColor = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 8;
    canvas.height = 8;
    const context = canvas.getContext('2d');
    context.fillStyle = '#ff0000';
    context.fillRect(0, 0, 4, 8);
    context.fillStyle = '#0000ff';
    context.fillRect(4, 0, 4, 8);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await file.setInputFiles({ name: 'red-blue.png', mimeType: 'image/png', buffer: Buffer.from(twoColor, 'base64') });
  await expect(result).toContainText('#0000FF');
  await expect(result).toContainText('#FF0000');
  await page.evaluate(() => {
    window.__paletteClipboard = '';
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => { window.__paletteClipboard = value; } } });
  });
  await result.locator('[data-action=copy-csv]').click();
  await expect.poll(() => page.evaluate(() => window.__paletteClipboard)).toBe('hex,r,g,b,share\n#0000FF,0,0,255,50.0%\n#FF0000,255,0,0,50.0%');
  const actionButtonCount = await page.locator('#tab-image-tools .image-tools__body button:visible').evaluateAll(buttons =>
    buttons.filter(button => !button.matches('[role=tab],.link')).length,
  );
  expect(actionButtonCount).toBeLessThanOrEqual(3);
  await page.screenshot({ path: path.join(evidence, `image_palette-current-source-recovered-${testInfo.project.name}-20261103.png`), fullPage: true });
});

test('Dominant Colors keeps twelve per-swatch links outside the shared dock', async ({ page }) => {
  await page.locator('[data-image-tool-link="image_palette"]').click();
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 12;
    canvas.height = 1;
    const context = canvas.getContext('2d');
    const colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff', '#800000', '#008000', '#000080', '#808000', '#800080', '#008080'];
    colors.forEach((color, index) => { context.fillStyle = color; context.fillRect(index, 0, 1, 1); });
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.locator('#tab-image-tools input[type=file][data-slot=file]').setInputFiles({ name: 'twelve-colors.png', mimeType: 'image/png', buffer: Buffer.from(base64, 'base64') });
  await page.locator('#tab-image-tools [data-param=count]').fill('12');
  await page.locator('#tab-image-tools [data-param=count]').dispatchEvent('change');
  await expect(page.locator('#tab-image-tools .image-tools__swatch')).toHaveCount(12);
  const links = page.locator('#tab-image-tools .image-tools__swatch button[data-open-tab="color"]');
  await expect(links).toHaveCount(12);
  await expect(links.first()).not.toHaveAttribute('data-officekit-docked', 'true');
  const dockButtonCount = await page.evaluate(() => {
    const sources = [...document.querySelectorAll('#tab-image-tools [data-officekit-docked="true"]')];
    return new Set(sources.flatMap(source => [...(source.matches('button') ? [source] : []), ...source.querySelectorAll('button')])).size;
  });
  expect(dockButtonCount).toBe(1);
});
