import { expect, test } from '@playwright/test';

async function openApp(page) {
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.addInitScript(() => {
    window.__crashCopyFails = false;
    window.__clipboardText = '';
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async text => {
          if (window.__crashCopyFails) throw new Error('clipboard permission denied');
          window.__clipboardText = text;
        },
      },
    });
  });
  await page.goto('/');
}

test('crash report copy succeeds without sending anything and keeps details collapsed by default', async ({ page }) => {
  const requests = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await openApp(page);
  await page.evaluate(() => showAppleCrashReport({ stack_trace: 'Parser error at /Users/test/private.pdf' }, 'PDF operation failed'));

  const dialog = page.getByRole('dialog', { name: 'This operation didn’t finish' });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('details')).not.toHaveJSProperty('open', true);
  await expect(dialog).toContainText('Nothing is sent automatically');
  await dialog.getByRole('button', { name: 'Copy diagnostic details' }).click();
  await expect(dialog.locator('#crash-report-status')).toHaveText('Copied to clipboard. No report was sent.');
  expect(await page.evaluate(() => window.__clipboardText)).toContain('PDF operation failed');
  expect(await page.evaluate(() => window.__clipboardText)).toContain('/Users/test/private.pdf');
  expect(requests.some(path => path.includes('support') || path.includes('feedback'))).toBe(false);
});

test('crash report clipboard denial gives manual-copy recovery without a false success', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    window.__crashCopyFails = true;
    showAppleCrashReport({ stack_trace: 'Parser error details' }, 'PDF operation failed');
  });

  const dialog = page.getByRole('dialog', { name: 'This operation didn’t finish' });
  await dialog.getByRole('button', { name: 'Copy diagnostic details' }).click();
  await expect(dialog.locator('#crash-report-status')).toContainText('Clipboard unavailable');
  await expect(dialog.locator('#crash-report-status')).toContainText('copy them manually');
  await expect(dialog.locator('#copy-crash-btn')).toBeEnabled();
  await dialog.locator('details summary').click();
  await expect(dialog.locator('#crash-stacktrace-box')).toContainText('Parser error details');
});

test('crash dialog actions remain inside a narrow window', async ({ page }) => {
  await openApp(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => showAppleCrashReport({ stack_trace: 'Parser error details' }, 'PDF operation failed'));

  const bounds = await page.locator('#crash-modal > div').evaluate(element => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width, viewport: window.innerWidth };
  });
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
  await expect(page.getByRole('button', { name: 'Copy diagnostic details' })).toBeVisible();
});
