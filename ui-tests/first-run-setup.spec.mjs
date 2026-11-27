import { expect, test } from '@playwright/test';

async function mockNative(page, { slow = false, calendar = 'undetermined', microphone = 'undetermined', accessibility = 'denied', screen = 'denied', model = 'not_installed' } = {}) {
  await page.addInitScript(({ slow, calendar, microphone, accessibility, screen, model }) => {
    const state = { slow, calendar, microphone, accessibility, screen, model, modelId: 'parakeet_v3', saved: { setupDone: false, setupVersion: 0 }, hotkey: 'disabled', desktop: { enabled: false, openAtLogin: false, windowsEnabled: false } };
    window.__setupCalls = [];
    window.__setupState = state;
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      window.__setupCalls.push({ command, args });
      switch (command) {
        case 'officekit_api_token': return 'test-token-with-32-characters-min';
        case 'dictation_microphone_permission': return { permission: state.microphone };
        case 'dictation_accessibility_permission': return { permission: state.accessibility };
        case 'dictation_screen_recording_permission': return { permission: state.screen };
        case 'dictation_request_microphone_permission': state.microphone = 'granted'; return { permission: 'granted' };
        case 'dictation_request_accessibility_permission': return { permission: state.accessibility };
        case 'dictation_request_screen_recording_permission': return { permission: state.screen };
        case 'dictation_open_permission_settings': return null;
        case 'calendar_permission_status': return { permission: state.calendar };
        case 'calendar_permission_request': state.calendar = 'granted'; return { permission: 'granted' };
        case 'dictation_model_status': return {
          model_id: state.modelId, state: state.model, message: 'Model is not installed.',
          progress: state.model === 'preparing' ? { fraction: 0.4, bytes_downloaded: 184 * 1048576, bytes_total: 460 * 1048576 } : null,
        };
        case 'dictation_model_select': state.modelId = args.modelId; return { model_id: state.modelId, state: state.model, message: '' };
        case 'dictation_prepare_model':
          if (state.slow) { state.model = 'preparing'; return new Promise(() => {}); }
          state.model = 'ready'; return { model_id: state.modelId, state: 'ready', message: 'Ready' };
        case 'app_settings_status': return state.saved;
        case 'app_settings_save':
          state.saved = { ...state.saved, ...Object.fromEntries(Object.entries(args.update).filter(([, value]) => value !== null && value !== undefined)) };
          if (state.saved.setupDone) state.saved.setupVersion = 1;
          return state.saved;
        case 'dictation_hotkey_status': return { state: state.hotkey };
        case 'dictation_hotkey_enable':
          // Like the native side: the shortcut needs the speech model ready.
          if (state.model !== 'ready') throw 'The speech model is not ready yet';
          state.hotkey = 'ready'; return { state: 'ready' };
        case 'dictation_hotkey_disable': state.hotkey = 'disabled'; return { state: 'disabled' };
        case 'global_desktop_status': return { available: true, settings: state.desktop };
        case 'global_desktop_configure': {
          // The native side refuses unknown fields (deny_unknown_fields), so the mock does too.
          const known = new Set(['enabled', 'openAtLogin', 'windowsEnabled', 'edgeDrag', 'windowGap', 'windowSkipApps']);
          const unknown = Object.keys(args.settings).filter(key => !known.has(key));
          if (unknown.length) throw `unknown field ${unknown[0]}`;
          window.__configured = args.settings; state.desktop = args.settings; return { available: true, settings: args.settings };
        }
        default: return null;
      }
    } } };
  }, { slow, calendar, microphone, accessibility, screen, model });
}

async function openApp(page) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
}

async function openSetup(page) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/?setup=auto');
  await expect(page.locator('#officekit-setup')).toBeVisible();
}

// Setup runs access, then tools, then the model download last: the earlier steps may need the app
// restarted, and a restart would stop a download that had already started.
async function toStep(dialog, step) {
  if (step >= 1) await dialog.getByRole('button', { name: 'Continue' }).click();
  if (step >= 2) await dialog.getByRole('button', { name: 'Continue' }).click();
}

test('setup asks for access first and the model download comes last', async ({ page }) => {
  await mockNative(page);
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'What OfficeKit needs, and why' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect(dialog.getByRole('heading', { name: 'Choose what runs in the background' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect(dialog.getByRole('heading', { name: 'Download a speech model' })).toBeVisible();
  await expect(dialog.getByRole('radio')).toHaveCount(8);
  await expect(dialog.getByRole('radio', { name: /Parakeet v3/ })).toBeChecked();
});

test('setup lets the user pick a model and downloads it on the last step', async ({ page }) => {
  await mockNative(page);
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await dialog.getByRole('radio', { name: /Whisper Small/ }).check();
  await expect(dialog.locator('.ok-setup-actions button')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Download' }).click();
  await expect(dialog.locator('[data-download-strip]')).toContainText('Model ready');
  await expect(dialog.getByRole('button', { name: 'Finish' })).toBeVisible();
  const calls = await page.evaluate(() => window.__setupCalls);
  expect(calls).toContainEqual({ command: 'dictation_model_select', args: { modelId: 'whisper_small' } });
  expect(calls.some(call => call.command === 'dictation_prepare_model')).toBe(true);
  expect(await page.evaluate(() => window.__setupState.saved.modelId)).toBe('whisper_small');
});

test('a slow download carries on in the background after setup is finished', async ({ page }) => {
  await mockNative(page, { slow: true });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await dialog.getByRole('button', { name: 'Download' }).click();
  await expect(dialog.locator('[data-download-strip]')).toContainText('Downloading… 40%');
  await expect(dialog.locator('[role="progressbar"]')).toHaveAttribute('aria-valuenow', '40');
  await expect(dialog.locator('[data-download-strip]')).toContainText('keeps going if you close setup');
  await dialog.getByRole('button', { name: 'Finish' }).click();
  await expect(page.locator('#officekit-setup')).toHaveCount(0);
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(true);
});

test('skipping the model finishes setup without a download', async ({ page }) => {
  await mockNative(page);
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await dialog.getByRole('button', { name: 'Skip for now' }).click();
  await expect(page.locator('#officekit-setup')).toHaveCount(0);
  expect((await page.evaluate(() => window.__setupCalls)).some(call => call.command === 'dictation_prepare_model')).toBe(false);
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(true);
});

test('coming back to the model step while it downloads offers Finish, not a second download', async ({ page }) => {
  await mockNative(page, { slow: true });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await dialog.getByRole('button', { name: 'Download' }).click();
  await page.evaluate(() => window.officekitSetup.close());
  await page.evaluate(() => window.officekitSetup.open());
  await toStep(dialog, 2);
  await expect(dialog.getByRole('heading', { name: 'Download a speech model' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Download' })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Finish' })).toBeVisible();
});

test('the model list keeps its scroll position and focus while the download is polled', async ({ page }) => {
  await mockNative(page, { slow: true });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await dialog.getByRole('button', { name: 'Download' }).click();
  const list = dialog.locator('.ok-setup-models');
  await expect(list).toBeVisible();
  await list.evaluate(node => { node.scrollTop = node.scrollHeight; });
  const before = await list.evaluate(node => node.scrollTop);
  expect(before).toBeGreaterThan(0);
  await dialog.getByRole('button', { name: 'Finish' }).focus();
  await page.waitForTimeout(3500);
  expect(await list.evaluate(node => node.scrollTop)).toBe(before);
  await expect(dialog.getByRole('button', { name: 'Finish' })).toBeFocused();
});

test('in a short window the setup buttons stay in view and the list is not cut at its edges', async ({ page }) => {
  await mockNative(page);
  await page.setViewportSize({ width: 520, height: 460 });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 2);
  await expect(dialog.getByRole('button', { name: 'Skip for now' })).toBeInViewport({ ratio: 1 });
  await expect(dialog.getByRole('button', { name: 'Download' })).toBeInViewport({ ratio: 1 });
  const fits = await dialog.locator('.ok-setup-models').evaluate(list => {
    const box = list.getBoundingClientRect();
    const row = list.querySelector('.ok-setup-model.on').getBoundingClientRect();
    return row.left - box.left >= 2 && box.right - row.right >= 2;
  });
  expect(fits).toBe(true);
  // The sticky bar spans the dialog edge to edge and matches its background, so it never looks like a floating box.
  const flush = await page.locator('.ok-setup-dialog').evaluate(node => {
    const bar = node.querySelector('.ok-setup-actions').getBoundingClientRect();
    const box = node.getBoundingClientRect();
    const same = getComputedStyle(node.querySelector('.ok-setup-actions')).backgroundColor === getComputedStyle(node).backgroundColor;
    return { left: Math.abs(bar.left - box.left - 1) <= 1, right: Math.abs(box.right - bar.right - 1) <= 1, bottom: Math.abs(box.bottom - bar.bottom - 1) <= 1, same };
  });
  expect(flush).toEqual({ left: true, right: true, bottom: true, same: true });
});

test('the access step lists what each permission is needed for and allows one by one', async ({ page }) => {
  await mockNative(page);
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  for (const name of ['Microphone', 'Accessibility', 'Screen Recording', 'Calendar']) {
    await expect(dialog.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(dialog.locator('[data-permission-row="accessibility"] em')).toHaveText(['Launcher paste', 'Clipboard paste', 'Snippet expansion', 'Window layouts', 'Typing dictation into other apps']);
  await expect(dialog.locator('[data-permission-row="microphone"] em')).toHaveText(['Speech to text', 'Speech Coach', 'Listen In', 'Meeting Recorder']);
  // 2 page buttons; the per-row Allow buttons are row actions and are not counted.
  await expect(dialog.locator('.ok-setup-actions button')).toHaveCount(2);
  await dialog.locator('[data-permission="microphone"]').click();
  await expect(dialog.locator('[data-permission-row="microphone"]')).toContainText('Allowed');
  // Calendar reads its real status, so a Mac that already allowed it shows Allowed and no button.
  await dialog.locator('[data-permission="calendar"]').click();
  await expect(dialog.locator('[data-permission-row="calendar"]')).toContainText('Allowed');
});

test('a permission macOS already allowed shows Allowed with nothing to click', async ({ page }) => {
  await mockNative(page, { calendar: 'granted', microphone: 'granted' });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('[data-permission-row="calendar"]')).toContainText('Allowed');
  await expect(dialog.locator('[data-permission="calendar"]')).toHaveCount(0);
  await expect(dialog.locator('[data-permission="microphone"]')).toHaveCount(0);
});

test('finishing turns on only the tools whose access was granted, then the tour waits for setup', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted' });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 1);
  await expect(dialog.locator('input[data-tool="desktop"]')).toBeChecked();
  await expect(dialog.locator('input[data-tool="dictation"]')).toBeDisabled();
  await expect(dialog.locator('input[data-tool="dictation"]')).not.toBeChecked();
  await expect(dialog.locator('.ok-setup-actions button')).toHaveCount(1);
  expect(await page.evaluate(() => window.officekitSetup.isOpen())).toBe(true);
  // The choices are applied when the step is left, so they hold even if the app must be restarted next.
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect(dialog.getByRole('heading', { name: 'Download a speech model' })).toBeVisible();
  const configured = await page.evaluate(() => window.__configured);
  expect(configured).toMatchObject({ enabled: true, windowsEnabled: true, openAtLogin: true });
  await dialog.getByRole('button', { name: 'Skip for now' }).click();
  await expect(page.locator('#officekit-setup')).toHaveCount(0);
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(true);
  expect(await page.evaluate(() => window.__setupState.saved)).toMatchObject({ setupDone: true, setupVersion: 1 });
});

test('a speech shortcut chosen in setup before the model is ready shows as on in Settings, waiting for the model', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted', microphone: 'granted' });
  await openSetup(page);
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 1);
  const speech = dialog.locator('input[data-tool="dictation"]');
  await speech.check();
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await dialog.getByRole('button', { name: 'Skip for now' }).click();
  await expect(page.locator('#officekit-setup')).toHaveCount(0);
  await page.evaluate(() => switchTab('settings'));
  const row = page.locator('#general-settings input[data-gs-tool="dictation"]');
  await expect(row).toBeChecked();
  await expect(page.locator('#general-settings')).toContainText('Turns on when the speech model is ready');
  // Setup, run again, shows the same.
  await page.evaluate(() => window.officekitSetup.open());
  const again = page.getByRole('dialog');
  await toStep(again, 1);
  await expect(again.locator('input[data-tool="dictation"]')).toBeChecked();
});

test('setup run again starts from what is on now, with the real shortcut keys', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted', microphone: 'granted' });
  await page.addInitScript(() => {
    window.localStorage.setItem('officekit.setup.done_v1', 'true');
  });
  await openApp(page);
  await page.evaluate(() => {
    window.__setupState.model = 'ready';
    window.__setupState.saved = { setupDone: true, setupVersion: 1 };
    window.__setupState.desktop = { enabled: true, openAtLogin: false, windowsEnabled: false, shortcuts: { 'launcher.open': { keyCode: 49, modifierMask: 8 }, 'window.left-half': { keyCode: 123, modifierMask: 3 } } };
  });
  await page.evaluate(() => window.officekitSetup.open());
  const dialog = page.getByRole('dialog');
  await toStep(dialog, 1);
  await expect(dialog.locator('input[data-tool="desktop"]')).toBeChecked();
  await expect(dialog.locator('input[data-tool="windows"]')).not.toBeChecked();
  await expect(dialog.locator('input[data-tool="login"]')).not.toBeChecked();
  await expect(dialog.locator('.ok-setup-row', { has: page.locator('input[data-tool="desktop"]') }).locator('.ok-setup-key')).toContainText('⌘Space');
});

test('a page whose access is missing shows one banner with the exact feature affected', async ({ page }) => {
  await mockNative(page, { microphone: 'undetermined', screen: 'granted' });
  await openApp(page);
  await page.evaluate(() => switchTab('dictate'));
  const banner = page.locator('[data-access-banner="microphone"]');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('Needs Microphone access');
  await expect(banner).toContainText('Speech to text and Speech Coach cannot hear you');
  await expect(banner.getByRole('button')).toHaveCount(1);
  await banner.getByRole('button', { name: 'Allow' }).click();
  await expect(banner).toBeHidden();
  await expect(page.locator('[data-access-banner="screen"]')).toBeHidden();
});

test('after a refusal the banner opens System Settings instead of asking again', async ({ page }) => {
  await mockNative(page, { microphone: 'denied' });
  await openApp(page);
  await page.evaluate(() => switchTab('dictate'));
  const banner = page.locator('[data-access-banner="microphone"]');
  await banner.getByRole('button', { name: 'Open System Settings' }).click();
  expect(await page.evaluate(() => window.__setupCalls)).toContainEqual({ command: 'dictation_open_permission_settings', args: { kind: 'microphone' } });
});

test('the speech model Download button stays inside its card', async ({ page }) => {
  await mockNative(page);
  await openApp(page);
  await expect(page.locator('#dictation-model-download')).toHaveAttribute('data-inline-action', '');
});
