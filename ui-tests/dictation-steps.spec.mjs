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

const nativeResult = {
  text: 'So I think easydp is ready.',
  delivery_status: 'paste-requested-clipboard-retained',
  steps: {
    after_smart: 'so I think easy D P is ready',
    dictionary_changes: [{ from: 'easy D P', to: 'easydp' }],
    rules_text: 'So I think easydp is ready.',
    polished: false,
  },
};

async function dictateWithSteps(page) {
  await page.evaluate(async result => {
    window.__nativeRequests = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          if (command === 'dictation_cleanup_and_paste') { window.__nativeRequests.push(args); return result; }
          return null;
        },
      },
    };
    await handleNativeDictationTranscript({
      payload: {
        text: 'so um I think easy D P is ready', audio_duration_seconds: 4, capture_generation: 3,
        capture: { recorded_seconds: 4.2, speech_seconds: 3.1, had_speech: true, level_db: -31 },
      },
    });
  }, nativeResult);
}

test('plain words are added without a source, split on commas, and shown as Word next to Replace', async ({ page }) => {
  await openDictation(page);
  const word = page.locator('#dictation-dictionary-replacement');
  const source = page.locator('#dictation-dictionary-source');
  await expect(source).not.toHaveAttribute('required', '');
  await word.fill('Kubernetes, easydp');
  await page.locator('#dictation-dictionary-form button[type="submit"]').click();
  await expect(page.locator('#dictation-dictionary-message')).toHaveText('2 words saved on this Mac.');
  const rows = page.locator('#dictation-dictionary-list li');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('Kubernetes');
  await expect(rows.nth(0)).toContainText('Word');
  await expect(rows.nth(0)).not.toContainText('→');

  await source.fill('ecdp');
  await word.fill('easydp');
  await page.locator('#dictation-dictionary-form button[type="submit"]').click();
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(2)).toContainText('ecdp → easydp');
  await expect(rows.nth(2)).toContainText('Replace');
  await expect(page.locator('#dictation-dictionary-count')).toHaveText('3 of 256 terms');

  await word.fill('KUBERNETES');
  await source.fill('');
  await page.locator('#dictation-dictionary-form button[type="submit"]').click();
  await expect(page.locator('#dictation-dictionary-message')).toContainText('already in your dictionary');
});

test('plain words travel to the cleanup separately from fixed replacements', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => {
    dictationDictionaryStore.add('', 'easydp');
    dictationDictionaryStore.add('ecdp', 'EasyDP');
  });
  await dictateWithSteps(page);
  const request = await page.evaluate(() => window.__nativeRequests[0]);
  expect(request.dictionary).toEqual({ ecdp: 'EasyDP' });
  expect(request.words).toEqual(['easydp']);
});

test('a push-to-talk transcript opens a steps view from raw capture to the final text', async ({ page }) => {
  await openDictation(page);
  await dictateWithSteps(page);
  const row = page.locator('#dictation-history-list li').first();
  await expect(row.getByRole('link', { name: /Show how the transcript/ })).toBeVisible();

  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  const detail = page.locator('#dictation-history-detail');
  await expect(detail).toBeVisible();
  await expect(page.locator('#dictation-history-main')).toBeHidden();
  await expect(detail).toContainText('Recorded 4.2 s · speech found 3.1 s');
  await expect(detail).toContainText('loudest level -31 dB');
  await expect(detail).toContainText('so um I think easy D P is ready');
  // Each step highlights what it changed against the step above: Smart cleanup removed "um";
  // Dictionary and tidy replaced "easy D P" and fixed the capital and the full stop.
  await expect(detail.locator('.dictation-step-body del')).toHaveText(['um', 'so', 'easy', 'D', 'P', 'ready']);
  await expect(detail.locator('.dictation-step-body ins')).toHaveText(['So', 'easydp', 'ready.']);
  await expect(detail.locator('.dictation-step-badge--change')).toHaveText(['1 removed', '3 changed']);
  await expect(detail).toContainText('Same as the step above.');
  await expect(detail).toContainText('removed 1 word');
  await expect(detail).toContainText('Dictionary: “easy D P” → easydp');
  await expect(detail).toContainText('Not used.');
  await expect(detail).toContainText('Pasted');
  await expect(detail).toContainText('Smart cleanup on');

  // Button limit: the card shows exactly Copy raw and Copy final; Back is a link.
  await expect(detail.getByRole('button')).toHaveCount(2);
  await expect(detail.getByRole('link', { name: /Back to transcripts/ })).toBeVisible();

  await detail.getByRole('button', { name: 'Copy final' }).click();
  await expect(detail.locator('.dictation-history-feedback')).toContainText(/copied|Clipboard/i);

  await page.keyboard.press('Escape');
  await expect(detail).toBeHidden();
  await expect(page.locator('#dictation-history-main')).toBeVisible();
});

test('a Fix grammar step shows what Harper changed, and an unused one says so', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(async () => {
    window.__TAURI__ = { core: { invoke: async () => ({
      text: 'We bought fruit and an apple was cheap.', delivery_status: 'paste-requested-clipboard-retained',
      steps: {
        after_smart: 'we buyed fruit and a apple was cheap', dictionary_changes: [],
        rules_text: 'We buyed fruit and a apple was cheap.',
        grammar_text: 'We bought fruit and an apple was cheap.',
        grammar_fixes: [{ from: 'buyed', to: 'bought', hint: 'Irregular past tense' }, { from: 'a', to: 'an', hint: 'Use an before a vowel sound' }],
        polished: false,
      },
    }) } };
    await handleNativeDictationTranscript({ payload: { text: 'we buyed fruit and a apple was cheap', audio_duration_seconds: 3, capture_generation: 8 } });
  });
  const row = page.locator('#dictation-history-list li').first();
  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  const detail = page.locator('#dictation-history-detail');
  await expect(detail).toContainText('Fix grammar');
  await expect(detail.locator('.dictation-step-badge--change')).toHaveText(['2 changed', '2 changed']);
  await expect(detail).toContainText('“buyed” → “bought” (Irregular past tense)');
  await expect(detail.locator('.dictation-step-body ins').filter({ hasText: /^bought$/ })).toHaveCount(1);
  await expect(detail.locator('.dictation-step-body ins').filter({ hasText: /^an$/ })).toHaveCount(1);
  await expect(detail.locator('.dictation-step-body del').filter({ hasText: /^buyed$/ })).toHaveCount(1);

  // Entries made with Fix grammar off, or before it existed, say it was not used.
  await page.getByRole('link', { name: /Back to transcripts/ }).click();
  await page.evaluate(async () => {
    window.__TAURI__ = { core: { invoke: async () => ({
      text: 'Hello there.', delivery_status: 'paste-requested-clipboard-retained',
      steps: { after_smart: 'hello there', dictionary_changes: [], rules_text: 'Hello there.', polished: false },
    }) } };
    await handleNativeDictationTranscript({ payload: { text: 'hello there', audio_duration_seconds: 1, capture_generation: 9 } });
  });
  await page.locator('#dictation-history-list li').first().getByRole('link', { name: /Show how the transcript/ }).click();
  await expect(page.locator('#dictation-history-detail')).toContainText('Fix grammar');
  await expect(page.locator('#dictation-history-detail')).toContainText('Not used.');
});

test('steps survive a reload and are removed with the transcript', async ({ page }) => {
  await openDictation(page);
  await dictateWithSteps(page);
  await page.reload();
  await page.evaluate(() => switchTab('dictate'));
  const row = page.locator('#dictation-history-list li').first();
  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  await expect(page.locator('#dictation-history-detail')).toContainText('Dictionary: “easy D P” → easydp');
  await page.getByRole('link', { name: /Back to transcripts/ }).click();
  await row.getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#dictation-history-list li')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('officekit.dictation.history.v1'))).not.toContain('easy D P');
});

test('entries without steps say so and meeting transcripts have no steps chip', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => {
    dictationHistoryStore.add('Older push to talk.', 'push-to-talk');
    dictationHistoryStore.add('Meeting words.', 'meeting');
    renderDictationHistory();
  });
  const rows = page.locator('#dictation-history-list li');
  await expect(rows.nth(0)).toContainText('Meeting');
  await expect(rows.nth(0)).not.toContainText('No steps recorded');
  await expect(rows.nth(0).getByRole('link', { name: /Show how/ })).toHaveCount(0);
  await expect(rows.nth(1)).toContainText('No steps recorded');
});

test('a silent attempt is recorded as a row that says where it broke', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(() => handleNativeDictationAttemptFailed({
    payload: {
      kind: 'no-speech', message: 'No speech heard. Recorded 3.0 s, loudest level -62 dB.',
      capture: { recorded_seconds: 3, speech_seconds: 0, had_speech: false, level_db: -62 }, model: 'small.en',
    },
  }));
  const row = page.locator('#dictation-history-list li').first();
  await expect(row).toContainText('No speech heard');
  await expect(row.getByRole('button', { name: 'Remove' })).toBeVisible();
  await expect(row.getByRole('button', { name: /Copy|Paste/ })).toHaveCount(0);

  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  const detail = page.locator('#dictation-history-detail');
  await expect(detail).toContainText('no speech detected');
  await expect(detail).toContainText('too quiet');
  await expect(detail).toContainText('Skipped, there was no speech.');
  await expect(detail).toContainText('Nothing was pasted.');
  // Button limit: no text to copy, so only Copy raw (disabled) is shown and Back is a link.
  await expect(detail.getByRole('button')).toHaveCount(1);
  await expect(detail.getByRole('button', { name: 'Copy raw' })).toBeDisabled();
});

test('a level that drops many words is flagged on the row and in the steps view', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(async () => {
    window.__TAURI__ = {
      core: {
        invoke: async () => ({
          text: 'one two three', delivery_status: 'paste-requested-clipboard-retained',
          steps: { after_smart: 'one two three', dictionary_changes: [], rules_text: 'One two three.', polished: false },
        }),
      },
    };
    await handleNativeDictationTranscript({
      payload: {
        text: 'one two three four five six seven eight nine ten', audio_duration_seconds: 5, capture_generation: 4,
        model: 'small.en', pieces: ['one two three four five', 'six seven eight nine ten'],
        capture: { recorded_seconds: 5, speech_seconds: 4.5, had_speech: true, level_db: -20 },
      },
    });
  });
  const row = page.locator('#dictation-history-list li').first();
  await expect(row).toContainText('Words lost');
  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  const detail = page.locator('#dictation-history-detail');
  await expect(detail).toContainText('small.en');
  await expect(detail).toContainText('decoded in 2 pieces');
  await expect(detail).toContainText('10 → 3');
  await expect(detail).toContainText('removed 70% of the words');
  await expect(detail.getByRole('button')).toHaveCount(2);
});

test('a failed cleanup keeps the raw text in history and says nothing was pasted', async ({ page }) => {
  await openDictation(page);
  await page.evaluate(async () => {
    window.__TAURI__ = { core: { invoke: async () => { throw new Error('cleanup service unavailable'); } } };
    await handleNativeDictationTranscript({
      payload: {
        text: 'please send the report today', audio_duration_seconds: 3, capture_generation: 5,
        capture: { recorded_seconds: 3, speech_seconds: 2.5, had_speech: true, level_db: -25 },
      },
    });
  });
  const row = page.locator('#dictation-history-list li').first();
  await expect(row).toContainText('please send the report today');
  await expect(row).toContainText('Cleanup failed');
  await row.getByRole('link', { name: /Show how the transcript/ }).click();
  const detail = page.locator('#dictation-history-detail');
  await expect(detail).toContainText('Raw text kept here; nothing was pasted.');
  await expect(detail.getByRole('button', { name: 'Copy final' })).toHaveCount(0);
  await expect(detail.getByRole('button')).toHaveCount(1);
});
