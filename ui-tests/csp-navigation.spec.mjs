import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('application scripts and left navigation work under the packaged Tauri CSP', async ({ page }) => {
  const pageErrors = [];
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()); });
  page.on('pageerror', error => pageErrors.push(error.message));
  const html = await readFile('dist-ui/index.html', 'utf8');
  const tauriConfig = JSON.parse(await readFile('src-tauri/tauri.conf.json', 'utf8'));
  const csp = [
    "default-src 'self' customprotocol: asset:",
    "base-uri 'self'",
    'connect-src ipc: http://ipc.localhost http://127.0.0.1:19873 http://127.0.0.1:19874',
    "font-src 'self' asset: data:",
    "img-src 'self' asset: http://asset.localhost blob: data:",
    "object-src 'none'",
    `script-src ${tauriConfig.app.security.csp['script-src']}`,
    "style-src 'self' 'unsafe-inline'",
  ].join('; ');

  await page.route('http://127.0.0.1:19874/', async route => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      headers: { ...response.headers(), 'content-security-policy': csp },
    });
  });
  await page.route('http://127.0.0.1:19874/api/tools/search**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.route('http://127.0.0.1:19874/api/system/check-update', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.addInitScript(() => {
    window.officekitNativeCalls = [];
    let modelState = 'not_installed';
    let modelId = 'parakeet_v3';
    let hotkeyKey = 'left_option';
    let customBinding = null;
    let failDictationErrorListenerOnce = true;
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.officekitNativeCalls.push({ command, args });
          if (command === 'officekit_api_token') return 'officekit-test-token-0123456789abcdef';
          if (command === 'officekit_api_origin') return 'http://127.0.0.1:19874';
          if (command === 'dictation_prepare_model') modelState = 'preparing';
          if (command === 'dictation_model_select') {
            modelId = args.modelId;
            modelState = 'not_installed';
          }
          if (command === 'dictation_model_status' || command === 'dictation_model_select' || command === 'dictation_prepare_model') return {
            model_id: modelId,
            model: modelId === 'qwen3_asr' ? 'Qwen3 ASR 0.6B · Multilingual' : modelId === 'parakeet_v2' ? 'Parakeet v2 · English' : 'Parakeet v3 · Multilingual',
            language_support: modelId === 'qwen3_asr' ? '52 languages · macOS 15+' : modelId === 'parakeet_v2' ? 'English speech' : '25 languages',
            state: modelState,
            message: modelState === 'preparing' ? 'Preparing local speech model…' : modelId === 'qwen3_asr' ? 'Qwen3 model is not downloaded.' : modelId === 'parakeet_v2' ? 'English-only model is not downloaded.' : 'Multilingual model is not downloaded.',
          };
          if (command === 'dictation_microphone_permission') return { permission: 'granted', message: 'Microphone access is enabled.' };
          if (command === 'dictation_accessibility_permission') return { permission: 'granted', message: 'Accessibility access is enabled.' };
          if (command === 'dictation_hotkey_configure') { hotkeyKey = args.key; customBinding = null; return { state: 'disabled', key: hotkeyKey, custom_binding: null }; }
          if (command === 'dictation_hotkey_configure_custom') { hotkeyKey = 'custom'; customBinding = args; return { state: 'disabled', key: hotkeyKey, custom_binding: customBinding }; }
          if (command === 'dictation_hotkey_status') return { state: 'disabled', key: hotkeyKey, custom_binding: customBinding };
          return {};
        },
      },
      event: {
        listen: async (eventName) => {
          if (eventName === 'dictation-error' && failDictationErrorListenerOnce) {
            failDictationErrorListenerOnce = false;
            throw new Error('simulated native event permission race');
          }
          return () => {};
        },
      },
    };
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status'), pageErrors.join('\n')).not.toHaveText('Loading tools…');
  const updateDialogPromise = page.waitForEvent('dialog').then(async dialog => {
    const message = dialog.message();
    await dialog.accept();
    return message;
  });
  await page.locator('button[title="Check for Updates"]').click();
  expect(await updateDialogPromise).toContain('Update information is not available');
  await expect(page.locator('#update-badge-dot')).toBeHidden();

  for (const tab of ['favorites', 'activity', 'tools']) {
    await page.locator(`[data-sidebar-tab="${tab}"]`).click();
    await expect(page.locator(`#tab-${tab}`)).toBeVisible();
    await expect(page.locator(`[data-sidebar-tab="${tab}"]`)).toHaveAttribute('aria-current', 'page');
  }

  await page.getByRole('button', { name: 'File converter' }).click();
  const routeState = await page.evaluate(() => ({
    tab: 'converter',
    action: [...document.querySelectorAll('aside button[data-officekit-click]')].find(button => button.textContent.toLowerCase().includes('converter'))?.dataset.officekitClick,
  }));
  await expect(page.locator(`#tab-${routeState.tab}`), JSON.stringify(routeState)).toBeVisible();

  for (const shortcut of ['Meta+k', 'Control+k']) {
    await page.keyboard.press(shortcut);
    await expect(page.locator('#search-modal')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#search-modal')).toBeHidden();
  }
  await page.locator('#global-search-trigger').click();
  await expect(page.locator('#search-modal')).toBeVisible();
  await page.locator('#global-search-input').fill('PDF to');
  await expect(page.locator('#search-results-list')).toContainText('PDF Pages to PNG / JPEG');
  await page.locator('#search-results-list [data-tool-id="pdf_to_images"]').click();
  await expect(page.locator('#search-modal')).toBeHidden();
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('#pdf-task-title')).toHaveText('PDF pages to PNG / JPEG');

  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#tab-dictate')).toBeVisible();
  await expect(page.locator('#dictation-events-recovery')).toBeVisible();
  await expect(page.locator('#dictation-events-detail')).toContainText('dictation-error');
  await page.locator('#dictation-events-retry').click();
  await expect(page.locator('#dictation-events-recovery')).toBeHidden();
  await expect(page.locator('#dictation-hotkey-toggle')).toBeEnabled();
  await expect(page.locator('#dictation-hotkey-choice')).toHaveValue('left_option');
  expect(await page.evaluate(() => window.officekitNativeCalls)).toContainEqual({ command: 'dictation_hotkey_configure', args: { key: 'left_option' } });
  await page.locator('#dictation-model-trigger').click();
  await expect(page.locator('#dictation-model-options')).toBeVisible();
  await expect(page.locator('[data-dictation-model-option="whisper_medium"]')).toContainText('Speed —');
  await expect(page.locator('[data-dictation-model-option="whisper_medium"]')).toContainText('Accuracy —');
  await expect(page.locator('[data-dictation-model-option="whisper_medium"]')).toHaveAttribute('aria-label', /Speed rating unavailable/);
  await page.locator('#dictation-model-trigger').press('ArrowDown');
  await expect(page.locator('[data-dictation-model-option="parakeet_v3"]')).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('[data-dictation-model-option="parakeet_v2"]')).toBeFocused();
  await page.locator('[data-dictation-model-option="parakeet_v2"]').click();
  await page.locator('#dictation-hotkey-choice').selectOption('left_option');
  await expect(page.locator('#dictation-hotkey-toggle')).toHaveText('Enable Left Option shortcut');
  await expect(page.locator('#dictation-hotkey-status')).toHaveText('Shortcut is off');
  expect(await page.evaluate(() => window.localStorage.getItem('officekit.dictation.hotkey'))).toBe('left_option');
  expect(await page.evaluate(() => window.officekitNativeCalls)).toContainEqual({ command: 'dictation_hotkey_configure', args: { key: 'left_option' } });
  await page.locator('#dictation-model-choice').selectOption('parakeet_v2');
  await expect(page.locator('#dictation-model-status')).toHaveText('English-only model is not downloaded.');
  await expect(page.locator('#dictation-model-support')).toHaveText('English only');
  expect(await page.evaluate(() => window.officekitNativeCalls)).toContainEqual({ command: 'dictation_model_select', args: { modelId: 'parakeet_v2' } });
  await page.reload();
  await expect(page.locator('#dictation-model-choice')).toHaveValue('parakeet_v2');
  await expect(page.locator('#dictation-hotkey-choice')).toHaveValue('left_option');
  await page.evaluate(() => switchTab('dictate'));
  await page.locator('#dictation-model-trigger').click();
  await page.locator('[data-dictation-model-option="whisper_medium"]').click();
  await page.locator('#dictation-output-language').selectOption('en');
  expect(await page.evaluate(() => window.officekitNativeCalls)).toContainEqual({ command: 'dictation_set_translation_mode', args: { enabled: true } });
  await page.locator('#dictation-model-trigger').click();
  await page.locator('[data-dictation-model-option="qwen3_asr"]').click();
  await expect(page.locator('#dictation-model-support')).toHaveText('30 languages + 22 Chinese dialects');
  await expect(page.locator('#dictation-model-status')).toHaveText('Qwen3 model is not downloaded.');
  await expect(page.locator('#dictation-output-language option[value="en"]')).toBeDisabled();
  expect(await page.evaluate(() => window.localStorage.getItem('officekit.dictation.model'))).toBe('qwen3_asr');
  await page.reload();
  await expect(page.locator('#dictation-model-choice')).toHaveValue('qwen3_asr');
  await page.evaluate(() => switchTab('dictate'));
  await page.locator('#dictation-model-download').click();
  await expect(page.locator('#dictation-model-status')).toHaveText('Preparing local speech model…');
  await expect(page.locator('#dictation-model-download')).toBeDisabled();
  expect(await page.evaluate(() => window.officekitNativeCalls.some(call => call.command === 'dictation_prepare_model'))).toBe(true);

  await page.locator('#dictation-hotkey-choice').selectOption('custom');
  await expect(page.locator('#dictation-custom-hotkey-controls')).toBeVisible();
  await page.locator('#dictation-hotkey-record').click();
  await page.keyboard.press('a');
  await expect(page.locator('#dictation-hotkey-capture-status')).toHaveText('Add a modifier key, or use F13–F20 alone to avoid starting dictation while typing.');
  await page.keyboard.press('Meta+q');
  await expect(page.locator('#dictation-hotkey-capture-status')).toHaveText('That combination is reserved by macOS. Choose another key combination.');
  await page.keyboard.press('Control+Shift+D');
  await expect(page.locator('#dictation-hotkey-capture-status')).toHaveText('Current shortcut: Control + Shift + D. Use a modifier with a key, or F13–F20 alone.');
  expect(await page.evaluate(() => window.localStorage.getItem('officekit.dictation.hotkey'))).toBe('custom');
  expect(JSON.parse(await page.evaluate(() => window.localStorage.getItem('officekit.dictation.custom-hotkey')))).toEqual({ keyCode: 2, modifierMask: 5, label: 'Control + Shift + D' });
  expect(await page.evaluate(() => window.officekitNativeCalls)).toContainEqual({
    command: 'dictation_hotkey_configure_custom',
    args: { keyCode: 2, modifierMask: 5, label: 'Control + Shift + D' },
  });
  await page.reload();
  await expect(page.locator('#dictation-hotkey-choice')).toHaveValue('custom');
  await expect(page.locator('#dictation-hotkey-capture-status')).toContainText('Current shortcut: Control + Shift + D');
});

test('title-bar Quick Search remains interactive and reports when the local catalogue API is unreachable', async ({ page }) => {
  const tauriConfig = JSON.parse(await readFile('src-tauri/tauri.conf.json', 'utf8'));
  const csp = [
    "default-src 'self' customprotocol: asset:",
    "base-uri 'self'",
    'connect-src ipc: http://ipc.localhost http://127.0.0.1:19873 http://127.0.0.1:19874',
    "font-src 'self' asset: data:",
    "img-src 'self' asset: http://asset.localhost blob: data:",
    "object-src 'none'",
    `script-src ${tauriConfig.app.security.csp['script-src']}`,
    "style-src 'self' 'unsafe-inline'",
  ].join('; ');
  await page.route('http://127.0.0.1:19874/', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': csp } });
  });
  await page.goto('/');

  await page.locator('#global-search-trigger').click();
  await expect(page.locator('#search-modal')).toBeVisible();
  await page.locator('#global-search-input').fill('PDF to');
  await expect(page.locator('#search-results-list')).toContainText('Tool search is unavailable');
});

test('title-bar Quick Search retries the current catalogue request after the local API starts', async ({ page }) => {
  const html = await readFile('dist-ui/index.html', 'utf8');
  const tauriConfig = JSON.parse(await readFile('src-tauri/tauri.conf.json', 'utf8'));
  const csp = [
    "default-src 'self' customprotocol: asset:",
    "base-uri 'self'",
    'connect-src ipc: http://ipc.localhost http://127.0.0.1:19873 http://127.0.0.1:19874',
    "font-src 'self' asset: data:",
    "img-src 'self' asset: http://asset.localhost blob: data:",
    "object-src 'none'",
    `script-src ${tauriConfig.app.security.csp['script-src']}`,
    "style-src 'self' 'unsafe-inline'",
  ].join('; ');
  let searchAttempts = 0;
  const searchQueries = [];
  await page.route('http://127.0.0.1:19874/', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': csp } });
  });
  await page.route('http://127.0.0.1:19874/api/tools/search**', route => {
    searchAttempts += 1;
    searchQueries.push(new URL(route.request().url()).searchParams.get('q'));
    if (searchAttempts <= 2) return route.fulfill({ status: 503, body: 'Starting' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tools: [{ id: 'pdf_to_images', name: 'PDF Pages to PNG / JPEG', category: 'PDF & Documents', icon: 'fa-file-pdf', desc: 'Export selected PDF pages as images.' }] }),
    });
  });
  await page.goto('/');
  await page.locator('#global-search-trigger').click();
  await expect(page.locator('#search-modal')).toBeVisible();
  await page.locator('#global-search-input').fill('PDF to');
  await expect(page.locator('#search-results-list')).toContainText('Retry search');
  const failedAttempts = searchAttempts;
  await page.locator('#search-retry-button').click();
  await expect(page.locator('#search-results-list')).toContainText('PDF Pages to PNG / JPEG');
  expect(searchAttempts).toBeGreaterThan(failedAttempts);
  expect(searchQueries.slice(-2)).toEqual(['PDF to', 'PDF to']);
});
