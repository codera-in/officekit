import { expect, test } from '@playwright/test';

async function openDictation(page) {
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
}

test('keeping raw audio is off by default, turns on with a status line, and can be cleared', async ({ page }) => {
  await openDictation(page);
  const oldest = Math.floor(Date.now() / 1000) + 3600;
  await page.evaluate(oldestExpiresAt => {
    window.__nativeCalls = [];
    window.__recordings = 3;
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.__nativeCalls.push([command, args]);
          if (command === 'raw_audio_status') return { count: window.__recordings, bytes: 4_300_000, oldestExpiresAt };
          if (command === 'raw_audio_clear') { const cleared = window.__recordings; window.__recordings = 0; return cleared; }
          return null;
        },
      },
    };
  }, oldest);

  const toggle = page.locator('#dictation-raw-audio');
  const status = page.locator('#dictation-raw-audio-status');
  await expect(toggle).not.toBeChecked();
  await expect(page.locator('#dictation-raw-audio-hint')).toContainText('Never sent anywhere and never included in support or crash reports');
  await expect(page.locator('#dictation-raw-audio-hint')).toContainText('Deleted automatically after 24 hours');

  await toggle.check();
  await expect(status).toBeVisible();
  await expect(page.locator('#dictation-raw-audio-summary')).toContainText('3 recordings · 4.1 MB · the oldest is deleted');
  expect(await page.evaluate(() => window.__nativeCalls.filter(([command]) => command === 'dictation_set_raw_audio').map(([, args]) => args)))
    .toEqual([{ enabled: true }]);
  // Persisted for the next launch.
  expect(await page.evaluate(() => localStorage.getItem('officekit.dictation.raw-audio'))).toBe('1');

  await page.locator('#dictation-raw-audio-show').click();
  expect(await page.evaluate(() => window.__nativeCalls.some(([command]) => command === 'raw_audio_show'))).toBe(true);

  await page.locator('#dictation-raw-audio-clear').click();
  await expect(page.locator('#dictation-raw-audio-summary')).toHaveText('Cleared 3 recordings');

  await toggle.uncheck();
  expect(await page.evaluate(() => window.__nativeCalls.filter(([command]) => command === 'dictation_set_raw_audio').map(([, args]) => args)))
    .toEqual([{ enabled: true }, { enabled: false }]);
  // Nothing is saved any more and the switch is off, so the status line goes away.
  await expect(status).toBeHidden();
});

test('the raw audio switch goes back when the native side refuses it, and no button is added', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => {
    window.__TAURI__ = {
      core: { invoke: async command => { if (command === 'dictation_set_raw_audio') throw new Error('refused'); return null; } },
    };
  });
  await page.locator('#dictation-raw-audio').click();
  await expect(page.locator('#dictation-raw-audio')).not.toBeChecked();
  expect(await page.evaluate(() => localStorage.getItem('officekit.dictation.raw-audio'))).toBe('0');
  // The two actions are text links, so the troubleshooting card adds no button.
  await expect(page.locator('#dictation-troubleshooting button:not(.ok-text-link)')).toHaveCount(0);
});

async function openStepsFor(page, rawAudioExpiresAt) {
  await page.evaluate(async expiresAt => {
    window.__TAURI__ = {
      core: {
        invoke: async command => {
          if (command === 'dictation_cleanup_and_paste') return { text: 'So I think easydp is ready.', delivery_status: 'paste-requested-clipboard-retained', steps: { after_smart: 'so I think easydp is ready', rules_text: 'So I think easydp is ready.', polished: false } };
          return null;
        },
      },
    };
    await handleNativeDictationTranscript({
      payload: {
        text: 'so I think easydp is ready', audio_duration_seconds: 4, capture_generation: 3,
        capture: { recorded_seconds: 39.5, speech_seconds: 37.5, had_speech: true, level_db: -6 },
        raw_audio_expires_at: expiresAt,
      },
    });
  }, rawAudioExpiresAt);
  await page.locator('#dictation-history-list li').first().getByRole('link', { name: /Show how the transcript/ }).click();
  return page.locator('#dictation-history-detail');
}

test('an opened transcript says when its raw audio is deleted, and says nothing for one that was not kept', async ({ page }) => {
  await openDictation(page);
  const detail = await openStepsFor(page, Math.floor(Date.now() / 1000) + 3600);
  await expect(detail).toContainText('Recorded 39.5 s · speech found 37.5 s');
  await expect(detail).toContainText('Raw audio kept until');
  await expect(detail.getByRole('button', { name: 'Show in Finder' })).toBeVisible();
});

test('a transcript saved without raw audio, or with an expired copy, shows no raw audio line', async ({ page }) => {
  await openDictation(page);
  let detail = await openStepsFor(page, undefined);
  await expect(detail).toContainText('Recorded 39.5 s');
  await expect(detail).not.toContainText('Raw audio kept until');
  await page.evaluate(() => { localStorage.clear(); });
  await page.reload();
  await page.evaluate(() => switchTab('dictate'));
  detail = await openStepsFor(page, Math.floor(Date.now() / 1000) - 60);
  await expect(detail).toContainText('Recorded 39.5 s');
  await expect(detail).not.toContainText('Raw audio kept until');
});
