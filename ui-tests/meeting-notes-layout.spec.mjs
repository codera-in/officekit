import { expect, test } from '@playwright/test';

async function openMeeting(page) {
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => { switchTab('dictate'); setAudioToolView('meeting'); });
  await expect(page.locator('#dictation-editor-section')).toBeVisible();
}

test('Meeting Notes uses the full width, with the transcript beside the notes', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openMeeting(page);
  const shape = await page.evaluate(() => {
    const rect = id => document.getElementById(id).getBoundingClientRect();
    const section = rect('dictation-editor-section');
    const recorder = rect('meeting-recorder-card');
    const transcript = rect('dictate-transcript');
    const notes = rect('meeting-notes-empty-state');
    return {
      wide: section.width > 800,
      recorderSpans: Math.abs(recorder.width - (section.width - 42)) < 8,
      notesBeside: notes.left >= transcript.right - 1 && notes.width > 200,
      notesLevel: notes.top < transcript.bottom,
    };
  });
  expect(shape).toEqual({ wide: true, recorderSpans: true, notesBeside: true, notesLevel: true });
  await expect(page.locator('#meeting-notes-empty-state')).toContainText('No notes yet');
});

test('Meeting Notes shows at most three buttons, even with notes generated', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openMeeting(page);
  await page.locator('#dictate-transcript').fill('Morgan will send the proposal by Friday.');
  await page.getByRole('button', { name: 'Generate meeting notes' }).click();
  await expect(page.locator('#notes-result')).toBeVisible();
  const count = await page.evaluate(() => {
    const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) && !element.closest('dialog:not([open]), .modal:not(.modal-open)');
    const uncounted = element => element.matches('.ok-text-link, [role="tab"], [aria-pressed], .ok-segment, .ok-row-action');
    return [...document.querySelectorAll('#tab-dictate button.btn, #officekit-tool-actions button')]
      .filter(button => visible(button) && !uncounted(button)).map(button => button.textContent.trim());
  });
  expect(count, count.join(' | ')).toHaveLength(Math.min(count.length, 3));
});
