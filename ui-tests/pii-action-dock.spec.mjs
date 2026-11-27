import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import { routeAuthenticatedApi } from './authenticated-app.mjs';

test('PII status, create and result actions share the bottom dock', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => {
    switchTab('pii');
  });
  const dock = page.locator('#pii-action-dock');
  await expect(dock).toHaveCSS('position', 'fixed');
  await expect(page.locator('#pii-create-button')).toHaveCount(1);
  await expect(page.locator('#pii-create-button').locator('xpath=..')).toHaveAttribute('id', 'pii-action-dock-controls');
  await expect(page.locator('#pii-status').locator('xpath=..')).toHaveAttribute('id', 'pii-action-dock-status');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.OfficeKitToolActions?.refresh());
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    dock: document.getElementById('pii-action-dock').getBoundingClientRect().width,
    button: document.getElementById('pii-create-button').getBoundingClientRect(),
  }));
  expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.dock).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.button.width).toBeGreaterThanOrEqual(44);
  expect(dimensions.button.height).toBeGreaterThanOrEqual(44);
  expect(dimensions.button.right).toBeLessThanOrEqual(dimensions.viewport);
});

test('PII review shows a rendered PDF page in WebKit', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => switchTab('pii'));
  await page.locator('#pii-file-input').setInputFiles({
    name: 'preview.pdf',
    mimeType: 'application/pdf',
    buffer: fs.readFileSync(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url)),
  });
  await page.locator('#pii-scan-button').click();
  const preview = page.locator('#pii-preview img[alt^="Preview of preview.pdf"]');
  await expect(preview).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => preview.evaluate(image => image.naturalWidth)).toBeGreaterThan(0);
  await expect(preview).toHaveAttribute('alt', /page 1 of 3/);
});

test('PII review allows selecting all possible values in addition to detected items', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => switchTab('pii'));

  await page.locator('#pii-file-input').setInputFiles({
    name: 'sample.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Contact: Maya Chen\nEmail: maya@example.com\nPhone: +1 (415) 555-0138\nDate: 2026-10-12\n'),
  });
  await page.locator('#pii-scan-button').click();

  await expect(page.locator('#pii-review-panel')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('#pii-select-high')).toBeVisible();
  await expect(page.locator('#pii-select-possible')).toBeVisible();

  const possibleBoxes = page.locator('#pii-possible-list input[type="checkbox"]');
  const possibleCount = await possibleBoxes.count();
  if (possibleCount > 0) {
    for (let i = 0; i < possibleCount; i++) {
      expect(await possibleBoxes.nth(i).isChecked()).toBe(false);
    }

    await page.locator('#pii-select-possible').click();

    for (let i = 0; i < possibleCount; i++) {
      expect(await possibleBoxes.nth(i).isChecked()).toBe(true);
    }

    await page.screenshot({ path: '.test-artifacts/screenshots/pii-select-possible-review.png' });

    await page.locator('#pii-select-possible').click();
    for (let i = 0; i < possibleCount; i++) {
      expect(await possibleBoxes.nth(i).isChecked()).toBe(false);
    }
  }
});

test('user can change mind between Mask and Redact after copy is created', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(() => switchTab('pii'));

  await page.locator('#pii-file-input').setInputFiles({
    name: 'sample.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Contact: Maya Chen\nEmail: maya@example.com\nPhone: +1 (415) 555-0138\nDate: 2026-10-12\n'),
  });
  await page.locator('#pii-scan-button').click();

  await expect(page.locator('#pii-review-panel')).toBeVisible({ timeout: 15_000 });
  const createButton = page.locator('#pii-create-button');
  await expect(createButton).toBeVisible();
  await expect(createButton).toHaveText('Create masked copy');
  await expect(createButton).toBeEnabled();

  // 1. Create initial masked copy
  await createButton.click();
  await expect(page.locator('#pii-output-panel')).toBeVisible();
  await expect(page.locator('#pii-output-title')).toHaveText('Masked copy created');

  // Verify dock is still visible and button is updated, NOT hidden
  await expect(page.locator('#pii-action-dock')).toBeVisible();
  await expect(createButton).toBeVisible();
  await expect(createButton).toHaveText('Update masked copy');
  await expect(createButton).toBeEnabled();

  // Verify obsolete "Scan for personal information" is NOT docked
  const scanButton = page.locator('#pii-scan-button');
  await expect(scanButton).toBeHidden();

  // 2. User changes their mind: switch to Redact
  const redactRadio = page.locator('input[name="pii-mode"][value="redact"]');
  await redactRadio.click();

  // Button text should dynamically update to "Update redacted copy"
  await expect(createButton).toHaveText('Update redacted copy');
  await expect(createButton).toBeEnabled();

  // 3. User clicks "Update redacted copy"
  await createButton.click();
  await expect(page.locator('#pii-output-title')).toHaveText('Redacted copy created');
  await expect(createButton).toBeVisible();
  await expect(createButton).toHaveText('Update redacted copy');
  await expect(createButton).toBeEnabled();

  // 4. User changes mind back to Mask
  const maskRadio = page.locator('input[name="pii-mode"][value="mask"]');
  await maskRadio.click();
  await expect(createButton).toHaveText('Update masked copy');

  // Take screenshot as visual evidence
  await page.screenshot({ path: '.test-artifacts/screenshots/pii-change-mind-update-copy.png' });
});


