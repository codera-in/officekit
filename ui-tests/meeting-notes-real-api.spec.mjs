import { expect, test } from '@playwright/test';

test('meeting notes keep unresolved decisions out of Key Decisions and show them as discussion/actions', async ({ page }) => {
  await page.route('http://127.0.0.1:19874/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('dictate'));
  await page.evaluate(() => setAudioToolView('meeting'));

  const transcript = [
    'We need a decision on pricing by Friday.',
    'The team must make a decision before launch.',
    'Decision is required by Friday.',
    'The team reached a decision to retain the current price.',
  ].join(' ');
  await page.locator('#dictate-transcript').fill(transcript);
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();

  const notes = page.locator('#notes-markdown-output');
  await expect(page.locator('#notes-result')).toBeVisible();
  const markdown = await notes.inputValue();
  expect(markdown).toContain('- We need a decision on pricing by Friday');
  expect(markdown).toContain('- [ ] The team must make a decision before launch');
  expect(markdown).toContain('- Decision is required by Friday');
  expect(markdown).toContain('- **Decision:** The team reached a decision to retain the current price');
  expect(markdown).not.toContain('- **Decision:** We need a decision');
  expect(markdown).not.toContain('- **Decision:** The team must make a decision');
  expect(markdown).not.toContain('- **Decision:** Decision is required');

  await page.getByRole('button', { name: 'Clear transcript and notes' }).click();
  await expect(page.locator('#dictate-transcript')).toHaveValue('');
  await expect(page.locator('#notes-result')).toBeHidden();
});

test('clicking audio tool tabs switches between Voice Transcription and Meeting Notes', async ({ page }) => {
  await page.route('http://127.0.0.1:19874/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('dictate'));

  // 1. Initial view is Voice Transcription
  const voiceTab = page.locator('button[data-audio-tool-tab="voice"]');
  const meetingTab = page.locator('button[data-audio-tool-tab="meeting"]');
  const title = page.locator('#audio-tool-title');

  await expect(title).toHaveText('Voice Transcription');
  await expect(voiceTab).toHaveAttribute('aria-selected', 'true');
  await expect(meetingTab).toHaveAttribute('aria-selected', 'false');
  await expect(page.locator('[data-audio-view="voice"]').first()).toBeVisible();
  await expect(page.locator('#meeting-notes-generate')).toBeHidden();

  // 2. Click Meeting Notes tab
  await meetingTab.click();
  await expect(title).toHaveText('Meeting Notes');
  await expect(meetingTab).toHaveAttribute('aria-selected', 'true');
  await expect(voiceTab).toHaveAttribute('aria-selected', 'false');
  await expect(page.locator('[data-audio-view="voice"]').first()).toBeHidden();
  await expect(page.locator('#meeting-notes-generate')).toBeVisible();

  // 3. Click Voice Transcription tab
  await voiceTab.click();
  await expect(title).toHaveText('Voice Transcription');
  await expect(voiceTab).toHaveAttribute('aria-selected', 'true');
  await expect(meetingTab).toHaveAttribute('aria-selected', 'false');
  await expect(page.locator('[data-audio-view="voice"]').first()).toBeVisible();
  await expect(page.locator('#meeting-notes-generate')).toBeHidden();
});

