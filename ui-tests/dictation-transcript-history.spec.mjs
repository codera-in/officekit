import { expect, test } from '@playwright/test';

test('recognized meeting segments appear in the live view and remain in local transcript history', async ({ page }) => {
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('dictate'));

  await page.evaluate(() => handleNativeMeetingChunk({ payload: { text: 'The exact words returned by the local model.' } }));
  await expect(page.locator('#dictation-live-transcript')).toHaveText('The exact words returned by the local model.');
  await expect(page.locator('#dictate-transcript')).toHaveValue('The exact words returned by the local model.');

  await page.evaluate(() => handleNativeMeetingStopped());
  const historyRow = page.locator('#dictation-history-list li').first();
  await expect(historyRow).toContainText('The exact words returned by the local model.');
  await expect(historyRow).toContainText('Meeting recording');

  await page.locator('#dictate-transcript').fill('A later transcript replaced the editor.');
  await expect(historyRow.getByRole('button', { name: 'Open' })).toHaveCount(0);
  await expect(historyRow.getByRole('button')).toHaveCount(3);
  await historyRow.locator('.dictation-history-text').click();
  await expect(page.locator('#dictate-transcript')).toHaveValue('The exact words returned by the local model.');
  await historyRow.getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#dictation-history-list li')).toHaveCount(0);
  await expect(page.locator('#dictation-history-empty')).toBeVisible();

  await page.evaluate(async () => {
    window.__TAURI__ = {
      core: {
        invoke: async command => {
          if (command !== 'dictation_cleanup_and_paste') throw new Error('Unexpected native command.');
          return { text: 'Cleaned words returned after push-to-talk.' };
        },
      },
    };
    await handleNativeDictationTranscript({
      payload: { text: 'Raw words returned by on-device recognition.', audio_duration_seconds: 1.5, capture_generation: 7 },
    });
  });
  await expect(page.locator('#dictation-live-transcript')).toHaveText('Cleaned words returned after push-to-talk.');
  await expect(page.locator('#dictate-transcript')).toHaveValue('Cleaned words returned after push-to-talk.');
  await expect(page.locator('#dictation-history-list li').first()).toContainText('Cleaned words returned after push-to-talk.');
  await expect(page.locator('#dictation-history-list li').first()).toContainText('Push-to-talk');
});

test('transcript retention expires old entries, lets users change the period, and persists the preference', async ({ page }) => {
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
    if (localStorage.getItem('officekit.dictation.history.retention.v1') !== null) return;
    const now = Date.now();
    localStorage.setItem('officekit.dictation.history.v1', JSON.stringify([
      { id: 'expired', text: 'Transcript older than the retention period.', source: 'meeting', createdAt: new Date(now - 31 * 86400000).toISOString() },
      { id: 'recent', text: 'Recent transcript stays available.', source: 'push-to-talk', createdAt: new Date(now - 10 * 86400000).toISOString() },
    ]));
    localStorage.setItem('officekit.dictation.history.retention.v1', JSON.stringify({ enabled: true, days: 30 }));
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('dictate'));

  const rows = page.locator('#dictation-history-list li');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('Recent transcript stays available.');
  await expect(rows.first()).not.toContainText('Transcript older than the retention period.');
  await expect(page.locator('#dictation-history-auto-clear')).toBeChecked();
  await expect(page.locator('#dictation-history-retention-days')).toHaveValue('30');
  await expect(rows.first()).toContainText(/Auto-clears in \d+ days/);
  await page.setViewportSize({ width: 390, height: 844 });
  const compactTargets = await page.locator('#dictation-history-toggle-hitarea, #dictation-history-retention-days, #dictation-history-list button').evaluateAll(elements => elements.map(element => ({
    name: element.getAttribute('aria-label') || element.id || element.textContent.trim(),
    height: element.getBoundingClientRect().height,
  })));
  expect(compactTargets.length).toBeGreaterThan(4);
  expect(compactTargets.every(target => target.height >= 44), JSON.stringify(compactTargets)).toBe(true);

  await page.locator('#dictation-history-retention-days').selectOption('7');
  await expect(rows).toHaveCount(0);
  await expect(page.locator('#dictation-history-status')).toContainText('older than 7 days');
  await page.reload();
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#dictation-history-auto-clear')).toBeChecked();
  await expect(page.locator('#dictation-history-retention-days')).toHaveValue('7');
});
