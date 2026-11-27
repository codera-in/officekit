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

test('smart dictation defaults, persistence and context consent', async ({ page }) => {
  await openDictation(page);
  const cleanup = page.locator('#dictation-smart-cleanup');
  const appContext = page.locator('#dictation-app-context');
  const fieldText = page.locator('#dictation-field-text');

  await expect(cleanup).toBeChecked();
  await expect(appContext).toBeChecked();
  await expect(fieldText).not.toBeChecked();
  await expect(page.locator('#dictation-faster-results')).toBeChecked();
  await expect(page.locator('#dictation-field-text-state')).toHaveText('Off');
  await expect(page.getByText('Password fields are always skipped.')).toBeVisible();

  await fieldText.check();
  await expect(page.locator('#dictation-field-text-state')).toHaveText('On');
  await cleanup.focus();
  await page.keyboard.press('Space');
  await expect(cleanup).not.toBeChecked();

  await page.reload();
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#dictation-field-text')).toBeChecked();
  await expect(page.locator('#dictation-smart-cleanup')).not.toBeChecked();
  await expect(page.locator('#dictation-app-context')).toBeChecked();
});

test('Fix grammar is off by default, persists, and travels with each dictation', async ({ page }) => {
  await openDictation(page);
  const fix = page.locator('#dictation-fix-grammar');
  await expect(fix).not.toBeChecked();
  await expect(page.getByText('Names, jargon, spelling and anything in your dictionary are left alone.')).toBeVisible();
  await page.evaluate(() => {
    window.__cleanups = [];
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command === 'dictation_cleanup_and_paste') { window.__cleanups.push(args); return { text: 'Cleaned.', delivery_status: 'paste-requested-clipboard-retained' }; }
      return null;
    } } };
  });
  const dictate = () => page.evaluate(() => handleNativeDictationTranscript({ payload: { text: 'we was late', audio_duration_seconds: 2, capture_generation: 1 } }));
  await dictate();
  await fix.check();
  await dictate();
  expect(await page.evaluate(() => window.__cleanups.map(args => args.fixGrammar))).toEqual([false, true]);
  await page.reload();
  await expect.poll(() => page.evaluate(() => officekitReleaseProfile !== null)).toBe(true);
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#dictation-fix-grammar')).toBeChecked();
});

test('changing context switches tells the native layer and cleanup mode follows the switch', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => {
    window.__nativeCalls = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.__nativeCalls.push([command, args]);
          if (command === 'dictation_cleanup_and_paste') return { text: 'Cleaned.', delivery_status: 'paste-requested-clipboard-retained' };
          return null;
        },
      },
    };
  });

  await page.locator('#dictation-field-text').check();
  await page.locator('#dictation-app-context').uncheck();
  const contextCalls = await page.evaluate(() => window.__nativeCalls.filter(([command]) => command === 'dictation_set_context_options'));
  expect(contextCalls.map(([, args]) => args)).toEqual([
    { appContext: true, fieldText: true },
    { appContext: false, fieldText: true },
  ]);

  await page.locator('#dictation-faster-results').uncheck();
  await page.locator('#dictation-faster-results').check();
  const speedCalls = await page.evaluate(() => window.__nativeCalls.filter(([command]) => command === 'dictation_set_streaming_commit'));
  expect(speedCalls.map(([, args]) => args)).toEqual([{ enabled: false }, { enabled: true }]);

  const deliver = () => page.evaluate(() => handleNativeDictationTranscript({
    payload: { text: 'um we ship at three no four', audio_duration_seconds: 2, capture_generation: 3 },
  }));
  await deliver();
  await page.locator('#dictation-smart-cleanup').uncheck();
  await deliver();
  const modes = await page.evaluate(() => window.__nativeCalls
    .filter(([command]) => command === 'dictation_cleanup_and_paste')
    .map(([, args]) => args.mode));
  expect(modes).toEqual(['smart', 'rules']);
});

test('a switch goes back to its saved state when the native side rejects the change', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => {
    window.__TAURI__ = {
      core: {
        invoke: async command => {
          if (command === 'dictation_set_context_options') throw new Error('native refused');
          return null;
        },
      },
    };
  });
  const fieldText = page.locator('#dictation-field-text');
  await fieldText.click();
  await expect(fieldText).not.toBeChecked();
  await expect(page.locator('#dictation-field-text-state')).toHaveText('Off');
  await expect(page.locator('#dictation-smart-message')).toContainText('stays as it was');
  const stored = await page.evaluate(() => window.localStorage.getItem('officekit.dictation.field-text'));
  expect(stored).not.toBe('1');
});

test('the smart dictation card keeps every control inside its own box', async ({ page }) => {
  await openDictation(page);
  const card = page.locator('#dictation-smart-card');
  await expect(card).toBeVisible();
  const escaping = await card.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {
      scrollOverflow: element.scrollWidth - element.clientWidth,
      outside: [...element.querySelectorAll('*')].filter(child => child.getBoundingClientRect().right > bounds.right + 1).length,
    };
  });
  expect(escaping).toEqual({ scrollOverflow: 0, outside: 0 });
  const box = await page.locator('#dictation-smart-cleanup').boundingBox();
  const target = await page.locator('#dictation-smart-cleanup').evaluate(element => element.closest('label').getBoundingClientRect().height);
  expect(box).not.toBeNull();
  expect(target).toBeGreaterThanOrEqual(44);
});
