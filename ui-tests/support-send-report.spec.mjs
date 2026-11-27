import { expect, test } from '@playwright/test';

// The packaged app sends through a native command; the browser build gets a stub of it here.
async function openFeedback(page, { fail = false } = {}) {
  await page.addInitScript(({ failSend }) => {
    window.__sentReports = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          if (command === 'support_ticket_submit') {
            window.__sentReports.push(args);
            if (window.__failSend) throw 'Could not reach OfficeKit support. Nothing was sent and your text is kept here.';
            return 'OK-e2e-1';
          }
          if (command === 'support_ticket_updates') return [];
          // The home screen asks the shell about other things (licence, updates); none matter here.
          (window.__otherCommands ??= []).push(command);
          return null;
        },
      },
    };
    window.__failSend = failSend;
  }, { failSend: fail });
  await page.route('http://127.0.0.1:19874/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.locator('button[title="Help & Bug Report"]').click();
  return page.locator('#support-modal');
}

test('the dialog explains what is sent and shows no more than three buttons', async ({ page }) => {
  const dialog = await openFeedback(page);
  await expect(dialog).toContainText('We tell you here when a fix ships');
  await expect(dialog.getByText('See exactly what is sent')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Open draft' })).toHaveCount(0);
  expect(await dialog.locator('button:visible').count()).toBeLessThanOrEqual(3);
  await dialog.getByText('See exactly what is sent').click();
  await expect(dialog).toContainText('Never your files');
});

test('testimonial permission is explicit and unchecked by default', async ({ page }) => {
  const dialog = await openFeedback(page);
  await expect(dialog.locator('#ticket-display-name-field')).toBeHidden();
  await dialog.locator('#ticket-type').selectOption('testimonial');
  await expect(dialog.locator('#ticket-display-name-field')).toBeVisible();
  await expect(dialog.getByLabel(/OfficeKit may publish/)).not.toBeChecked();
  await dialog.locator('#ticket-type').selectOption('feature');
  await expect(dialog.locator('#ticket-publication-consent-field')).toBeHidden();
});

test('a report is sent and answered with a reference', async ({ page }) => {
  const dialog = await openFeedback(page);
  await dialog.locator('#ticket-title').fill('Snippets do not expand');
  await dialog.locator('#ticket-desc').fill('I typed the keyword and nothing happened.');
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog.locator('#support-status')).toContainText('Sent. Your reference is OK-e2e-1');
  await expect(dialog.locator('#ticket-title')).toHaveValue('');
  const sent = await page.evaluate(() => window.__sentReports);
  expect(JSON.stringify(sent)).not.toMatch(/userAgent|platform|path/i);
});

test('a failed send keeps the text and offers Try again', async ({ page }) => {
  const dialog = await openFeedback(page, { fail: true });
  await dialog.locator('#ticket-title').fill('Keep my report');
  await dialog.locator('#ticket-desc').fill('The failure should not erase this.');
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(dialog.locator('#support-status')).toContainText('Nothing was sent');
  await expect(dialog.locator('#ticket-title')).toHaveValue('Keep my report');
  await expect(dialog.getByRole('button', { name: 'Try again' })).toBeVisible();

  await page.evaluate(() => { window.__failSend = false; });
  await dialog.getByRole('button', { name: 'Try again' }).click();
  await expect(dialog.locator('#support-status')).toContainText('OK-e2e-1');
  await expect(dialog.locator('#ticket-title')).toHaveValue('');
});
