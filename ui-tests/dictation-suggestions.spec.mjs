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

async function dictate(page, text) {
  await page.evaluate(async spoken => {
    window.__TAURI__ = {
      core: {
        invoke: async command => {
          if (command === 'dictation_cleanup_and_paste') return { text: spoken, delivery_status: 'paste-requested-clipboard-retained' };
          return null;
        },
      },
    };
    await handleNativeDictationTranscript({ payload: { text: spoken, audio_duration_seconds: 2, capture_generation: 1 } });
  }, text);
  await expect(page.locator('#dictate-transcript')).toHaveValue(text);
}

async function edit(page, text) {
  await page.locator('#dictate-transcript').fill(text);
  await page.locator('#dictate-transcript').blur();
}

test('editing a dictated name offers a dictionary suggestion that can be added', async ({ page }) => {
  await openDictation(page);
  await expect(page.locator('#dictation-suggestions')).toBeHidden();

  await dictate(page, 'Please email sedu about the report.');
  await edit(page, 'Please email Sedhu about the report.');

  const panel = page.locator('#dictation-suggestions');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('heading', { name: 'Suggested from your edits' })).toBeVisible();
  await expect(panel.locator('li')).toHaveCount(1);
  await expect(panel.locator('li').first()).toContainText('sedu → Sedhu');

  await panel.getByRole('button', { name: /Add sedu to Sedhu/ }).click();
  await expect(panel).toBeHidden();
  await expect(page.locator('#dictation-dictionary-list')).toContainText('sedu → Sedhu');
  await expect(page.locator('#dictation-dictionary-message')).toHaveText('Term saved on this Mac.');
});

test('dismissed suggestions stay dismissed and ordinary rewrites suggest nothing', async ({ page }) => {
  await openDictation(page);
  await dictate(page, 'We use office kit every day.');
  await edit(page, 'We use OfficeKit every day.');
  const panel = page.locator('#dictation-suggestions');
  await expect(panel.locator('li')).toHaveCount(1);
  await panel.getByRole('button', { name: /Dismiss suggestion office kit to OfficeKit/ }).click();
  await expect(panel).toBeHidden();

  await dictate(page, 'We use office kit every day.');
  await edit(page, 'We use OfficeKit every day.');
  await expect(panel).toBeHidden();

  await dictate(page, 'We ship on Friday afternoon.');
  await edit(page, 'We deliver on Monday morning.');
  await expect(panel).toBeHidden();
});

test('suggestions never appear without an edit and survive a reload until handled', async ({ page }) => {
  await openDictation(page);
  await dictate(page, 'Ask sedu to review it.');
  await page.locator('#dictate-transcript').focus();
  await page.locator('#dictate-transcript').blur();
  await expect(page.locator('#dictation-suggestions')).toBeHidden();

  await edit(page, 'Ask Sedhu to review it.');
  await expect(page.locator('#dictation-suggestions li')).toHaveCount(1);
  await page.reload();
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#dictation-suggestions li')).toHaveCount(1);
});

test('the suggestions panel keeps its controls inside the dictionary card', async ({ page }) => {
  await openDictation(page);
  await dictate(page, 'Ask sedu to review it.');
  await edit(page, 'Ask Sedhu to review it.');
  const panel = page.locator('#dictation-suggestions');
  await expect(panel).toBeVisible();
  const escaping = await panel.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return [...element.querySelectorAll('*')].filter(child => child.getBoundingClientRect().right > bounds.right + 1).length;
  });
  expect(escaping).toBe(0);
  const heights = await panel.locator('button').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().height));
  // DESIGN_SYSTEM.md: 44px at compact and touch widths (900px and below), 40px on desktop.
  const floor = page.viewportSize().width <= 900 ? 44 : 40;
  expect(Math.min(...heights)).toBeGreaterThanOrEqual(floor);
});
