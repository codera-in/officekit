import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: {
        ...route.request().headers(),
        authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`
      }
    });
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

test('Clipboard & Snippets Studio supports deleting history clips and removing snippets', async ({ page }) => {
  // Navigate to Clipboard & Snippets studio
  await page.evaluate(() => switchTab('clipboard'));
  await expect(page.locator('#tab-clipboard')).toBeVisible();

  // Seed a test clip via API
  const addClipResp = await page.request.post('http://127.0.0.1:19873/api/clipboard/clips', {
    headers: {
      authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
      'content-type': 'application/json'
    },
    data: {
      text_content: 'Confidential Test Token XYZ123',
      source_app: 'Playwright Test'
    }
  });
  expect(addClipResp.ok()).toBeTruthy();

  // Reload clips in UI
  await page.evaluate(() => window.officekitClipboard.loadClips());

  // Clip should appear in the container
  const clipsContainer = page.locator('#clipboard-clips-container');
  await expect(clipsContainer).toContainText('Confidential Test Token XYZ123');

  // Select clip to inspect
  const clipCard = clipsContainer.locator('div.group', { hasText: 'Confidential Test Token XYZ123' });
  await clipCard.click();

  // Inspector should be open and display Delete button
  const inspector = page.locator('#clipboard-inspector-content');
  await expect(inspector).toBeVisible();
  const deleteBtn = inspector.locator('#clipboard-action-delete');
  await expect(deleteBtn).toBeVisible();
  await expect(deleteBtn).toContainText('Delete');

  // Delete via inspector
  await deleteBtn.click();
  await expect(page.locator('#app-feedback-toast')).toContainText('Clip deleted');

  // Inspector returns to empty state and clip is gone
  await expect(page.locator('#clipboard-inspector-empty')).toBeVisible();
  await expect(clipsContainer).not.toContainText('Confidential Test Token XYZ123');

  // Test Snippets: Switch to Snippets tab
  await page.locator('#clipboard-mode-snippets-btn').click();
  const snippetsContainer = page.locator('#clipboard-snippets-container');
  await expect(snippetsContainer).toBeVisible();

  // Seed a snippet via API
  const addSnippetResp = await page.request.post('http://127.0.0.1:19873/api/clipboard/snippets', {
    headers: {
      authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
      'content-type': 'application/json'
    },
    data: {
      title: 'Temporary Customer Signature',
      content: 'Best regards,\nSupport Team',
      trigger_key: ':temp_sig'
    }
  });
  expect(addSnippetResp.ok()).toBeTruthy();
  const snippetData = await addSnippetResp.json();
  const snippetId = snippetData.snippet.id;

  // Reload snippets in UI
  await page.evaluate(() => window.officekitClipboard.loadSnippets());
  await expect(snippetsContainer).toContainText('Temporary Customer Signature');

  // Open Edit Snippet modal
  const snipCard = snippetsContainer.locator('div.group', { hasText: 'Temporary Customer Signature' });
  await snipCard.locator('button[data-edit-id]').click();

  const editModal = page.locator('#officekit-snippet-form-modal');
  await expect(editModal).toBeVisible();

  // Remove Snippet button must be visible in edit modal
  const modalRemoveBtn = editModal.locator('#snippet-modal-delete');
  await expect(modalRemoveBtn).toBeVisible();
  await expect(modalRemoveBtn).toContainText('Remove Snippet');

  // Confirm dialogue override for clean automated execution
  page.on('dialog', async dialog => dialog.accept());

  // Click Remove Snippet inside the edit modal
  await modalRemoveBtn.click();
  await expect(page.locator('#app-feedback-toast')).toContainText('Snippet removed');
  await expect(editModal).toBeHidden();

  // Snippet is gone from container
  await expect(snippetsContainer).not.toContainText('Temporary Customer Signature');
});

test('the Dictation tab lists saved transcripts, searches them and keeps them read-only', async ({ page }) => {
  await page.evaluate(() => { dictationHistoryStore.clear(); dictationHistoryStore.add('Hey I used a service called Biswok', 'push-to-talk'); dictationHistoryStore.add('This should be a compact view', 'push-to-talk'); switchTab('clipboard'); });
  await page.locator('#clipboard-mode-dictation-btn').click();
  const list = page.locator('#clipboard-dictation-container');
  await expect(list).toContainText('Biswok');
  await expect(list).toContainText('compact view');
  await expect(page.locator('#clipboard-clips-container')).toBeHidden();
  await list.getByText('Biswok').click();
  await expect(page.locator('#clipboard-preview-textarea')).toHaveValue('Hey I used a service called Biswok');
  await expect(page.locator('#clipboard-preview-textarea')).toHaveJSProperty('readOnly', true);
  for (const id of ['clipboard-action-delete', 'clipboard-action-save-as-snippet', 'clipboard-inspector-transforms']) await expect(page.locator('#' + id)).toBeHidden();
  await page.locator('#clipboard-search-input').fill('compact');
  await expect(list).not.toContainText('Biswok');
  await page.locator('#clipboard-mode-clips-btn').click();
  await expect(page.locator('#clipboard-dictation-container')).toBeHidden();
});
