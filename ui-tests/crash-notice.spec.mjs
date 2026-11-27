import { expect, test } from '@playwright/test';

// The packaged app asks the shell whether the last run crashed; the browser build gets a stub of it.
async function openApp(page, { notice, fail = false } = {}) {
  await page.addInitScript(({ pending, failSend }) => {
    window.__calls = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.__calls.push({ command, args });
          if (command === 'crash_notice_pending') return pending;
          if (command === 'support_ticket_submit') {
            if (failSend) throw 'Could not reach OfficeKit support. Nothing was sent.';
            return 'OK-e2e-crash';
          }
          if (command === 'support_ticket_updates') return [];
          return null;
        },
      },
    };
  }, { pending: notice ?? null, failSend: fail });
  await page.route('http://127.0.0.1:19874/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  return page.locator('#crash-notice-modal');
}

const NOTICE = { version: '1.0.112', closedAtMs: Date.UTC(2026, 10, 25, 14, 32), macos: '27.2.1', restartEnabled: false };

test('nothing appears when the last run ended normally', async ({ page }) => {
  const dialog = await openApp(page);
  await page.waitForFunction(() => window.__calls.some(call => call.command === 'crash_notice_pending'));
  await expect(dialog).toBeHidden();
});

test('a crash shows the notice with two buttons and the restart switch', async ({ page }) => {
  const dialog = await openApp(page, { notice: NOTICE });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('OfficeKit closed unexpectedly');
  await expect(dialog).toContainText('1.0.112');
  await expect(dialog).toContainText('27.2.1');
  await expect(dialog.getByLabel('Reopen OfficeKit automatically after a crash')).toBeVisible();
  expect(await dialog.locator('button:visible').count()).toBeLessThanOrEqual(3);
  await dialog.getByText('See exactly what is sent').click();
  await expect(dialog).toContainText('Never your files');
});

test('with restart already on the switch is left out', async ({ page }) => {
  const dialog = await openApp(page, { notice: { ...NOTICE, restartEnabled: true } });
  await expect(dialog).toContainText('reopened by itself');
  await expect(dialog.getByLabel('Reopen OfficeKit automatically after a crash')).toBeHidden();
});

test('Send report files a bug and ends on a single Done button', async ({ page }) => {
  const dialog = await openApp(page, { notice: NOTICE });
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog).toContainText('Report sent');
  await expect(dialog).toContainText('OK-e2e-crash');
  expect(await dialog.locator('button:visible').count()).toBe(1);
  const sent = await page.evaluate(() => window.__calls.find(call => call.command === 'support_ticket_submit').args);
  expect(sent.draft.kind).toBe('bug');
  expect(JSON.stringify(sent)).not.toMatch(/\/Users|userAgent/);
  await dialog.getByRole('button', { name: 'Done' }).click();
  await expect(dialog).toBeHidden();
});

test('a failed send offers Try again, and Not now sends nothing', async ({ page }) => {
  const dialog = await openApp(page, { notice: NOTICE, fail: true });
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog.locator('#crash-notice-status')).toContainText('Nothing was sent');
  await expect(dialog.getByRole('button', { name: 'Try again' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Not now' }).click();
  await expect(dialog).toBeHidden();
  const submits = await page.evaluate(() => window.__calls.filter(call => call.command === 'support_ticket_submit').length);
  expect(submits).toBe(1);
});
