import fs from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('meeting notes can be edited and downloaded as Markdown from the real API result', async ({ page }) => {
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
  await page.evaluate(() => { switchTab('dictate'); setAudioToolView('meeting'); });

  await page.locator('#dictate-transcript').fill('Morgan will send the proposal by Friday.');
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();
  await expect(page.locator('#notes-result')).toBeVisible();

  const output = page.locator('#notes-markdown-output');
  await expect(output).toBeVisible();
  await expect(output).not.toHaveValue('');
  const editedNotes = '## Follow-up\n\n- Edited and ready for an AI chat\n';
  await output.fill(editedNotes);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download Markdown' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^officekit-meeting-notes-\d{4}-\d{2}-\d{2}\.md$/);
  expect(await fs.readFile(await download.path(), 'utf8')).toBe(editedNotes);
});

test('editing the transcript invalidates previously generated notes until they are regenerated', async ({ page }) => {
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
  await page.evaluate(() => { switchTab('dictate'); setAudioToolView('meeting'); });
  await page.locator('#dictate-transcript').fill('The launch review starts on Tuesday.');
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();
  await expect(page.locator('#notes-result')).toBeVisible();
  await page.locator('#dictate-transcript').fill('The launch review moved to Wednesday.');
  await expect(page.locator('#notes-result')).toBeHidden();
});

test('a slow notes response cannot replace results after the transcript changes mid-request', async ({ page }) => {
  let noteRequestStarted;
  let allowNoteRequest;
  const started = new Promise(resolve => { noteRequestStarted = resolve; });
  const gate = new Promise(resolve => { allowNoteRequest = resolve; });
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname === '/api/dictate/format-notes') {
      noteRequestStarted();
      await gate;
    }
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => { switchTab('dictate'); setAudioToolView('meeting'); });
  await page.locator('#dictate-transcript').fill('The old meeting date is Tuesday.');
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();
  await started;
  await page.locator('#dictate-transcript').fill('The new meeting date is Wednesday.');
  allowNoteRequest();
  await expect(page.locator('#notes-result')).toBeHidden();
  await expect(page.locator('#dictation-transcript-status')).toContainText('Generate meeting notes again');
});

test('edited meeting notes can be saved locally, reopened after reload, and downloaded unchanged', async ({ page }) => {
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
  await page.evaluate(() => { switchTab('dictate'); setAudioToolView('meeting'); });
  await page.locator('#dictate-transcript').fill('Morgan will send the release checklist by Friday.');
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();
  await expect(page.locator('#notes-result')).toBeVisible();

  const editedNotes = '## Reviewed notes\n\n- Morgan: send the release checklist Friday.\n\n## Full Transcript\nMorgan will send the release checklist by Friday.\n\n<script>must remain plain text</script>\n';
  await page.locator('#notes-markdown-output').fill(editedNotes);
  await page.getByRole('button', { name: 'Save to History' }).click();
  await expect(page.locator('#dictation-transcript-status')).toContainText('saved on this device');
  await page.getByRole('button', { name: 'Save to History' }).click();
  await expect(page.locator('#dictation-transcript-status')).toContainText('already saved in History');

  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')));
  expect(stored.savedResults).toHaveLength(1);
  expect(stored.savedResults[0]).toMatchObject({ kind: 'meeting-notes', toolId: 'dictate_stt', inputs: {}, result: { markdown: editedNotes } });
  expect(stored.savedResults[0].inputs).toEqual({});
  expect(Object.keys(stored.savedResults[0].result)).toEqual(['markdown']);
  expect(Object.keys(stored.savedResults[0])).not.toContain('transcript');
  expect(Object.keys(stored.savedResults[0])).not.toContain('audio');

  await page.reload();
  await page.evaluate(() => switchTab('history'));
  const savedArticle = page.locator('[data-saved-result]');
  await expect(savedArticle).toHaveCount(1);
  await savedArticle.getByRole('button', { name: 'Open notes' }).click();
  await expect(page.locator('#saved-result-detail-content pre')).toHaveText(editedNotes);
  await expect(page.getByRole('button', { name: 'Reuse inputs' })).toBeHidden();

  const downloadPromise = page.waitForEvent('download');
  await page.locator('#saved-result-detail-content .officekit-result-actions button').nth(1).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^officekit-meeting-notes-\d{4}-\d{2}-\d{2}\.md$/);
  expect(await fs.readFile(await download.path(), 'utf8')).toBe(editedNotes);
  await savedArticle.getByRole('button', { name: /Delete saved result Meeting notes/ }).click();
  await expect(page.locator('[data-saved-result]')).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('officekit.records.v1')).savedResults)).toHaveLength(0);
});
