import { expect, test } from '@playwright/test';

async function openApp(page) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
}

test('Speech Coach has its own card in Audio & Dictation and opens its section', async ({ page }) => {
  await openApp(page);
  await page.locator('#tool-gallery-search').fill('speech coach');
  const card = page.locator('#tool-gallery-results [data-open-tool="speech_coach"]');
  await expect(card).toBeVisible();
  await expect(page.locator('#tool-gallery-results')).toContainText('Speech Coach');
  await expect(page.locator('#tool-gallery-results')).toContainText('Audio & Dictation');
  await card.click();
  await expect(page.locator('#audio-tool-title')).toHaveText('Voice Transcription');
  await expect(page.locator('#speech-coach-notes-heading')).toBeInViewport();
  await expect(page.locator('#speech-coach-enabled')).toBeFocused();
});

test('searching for pace or filler words finds Speech Coach', async ({ page }) => {
  await openApp(page);
  for (const query of ['filler words', 'speaking pace']) {
    await page.locator('#tool-gallery-search').fill(query);
    await expect(page.locator('#tool-gallery-results [data-open-tool="speech_coach"]')).toBeVisible();
  }
});

test('a model status message that is not a failure has no Report bug link, and neither has a red Delete button', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => {
    const status = document.getElementById('dictation-model-status');
    officekitOutcome.show(status, { state: 'success', text: 'Whisper Medium · Multilingual is ready. Speech is processed on this Mac.' });
    const row = document.createElement('div');
    row.innerHTML = '<button type="button" id="zz-delete" class="text-rose-700">Delete</button>';
    document.body.append(row);
  });
  await page.waitForTimeout(300);
  await expect(page.locator('#dictation-model-status .officekit-bug-report-cta')).toHaveCount(0);
  await expect(page.locator('#zz-delete .officekit-bug-report-cta')).toHaveCount(0);
  await page.evaluate(() => officekitOutcome.show(document.getElementById('dictation-model-status'), { state: 'error', text: 'The download failed.' }));
  await expect(page.locator('#dictation-model-status .officekit-bug-report-cta')).toHaveCount(1);
});
