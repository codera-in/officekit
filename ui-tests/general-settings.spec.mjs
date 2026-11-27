import { expect, test } from '@playwright/test';

// Same native mock as the setup spec, with the saved file and the three permissions the card reads.
async function mockNative(page, overrides = {}) {
  await page.addInitScript(overrides => {
    const state = {
      microphone: 'granted', accessibility: 'denied', screen: 'denied', calendar: 'undetermined',
      model: 'ready', modelId: 'parakeet_v3', hotkey: 'disabled',
      saved: { setupDone: true, setupVersion: 1, setupCompletedAt: '2026-10-23', modelId: 'parakeet_v3' },
      desktop: { enabled: true, openAtLogin: false, windowsEnabled: false },
      ...overrides,
    };
    window.__calls = [];
    window.__state = state;
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      window.__calls.push({ command, args });
      switch (command) {
        case 'officekit_api_token': return 'test-token-with-32-characters-min';
        case 'dictation_microphone_permission': return { permission: state.microphone };
        case 'dictation_accessibility_permission': return { permission: state.accessibility };
        case 'dictation_screen_recording_permission': return { permission: state.screen };
        case 'dictation_request_microphone_permission': if (state.microphone === 'undetermined') state.microphone = 'granted'; return { permission: state.microphone };
        case 'dictation_request_accessibility_permission': state.accessibility = 'granted'; return { permission: 'granted' };
        case 'dictation_request_screen_recording_permission': return { permission: state.screen };
        case 'dictation_open_permission_settings': return null;
        case 'calendar_permission_status': return { permission: state.calendar };
        case 'calendar_permission_request': state.calendar = 'granted'; return { permission: 'granted' };
        case 'dictation_model_status': return { model_id: state.modelId, state: state.model, message: '' };
        case 'dictation_model_select':
          // Like the native side: no switching while the speech to text shortcut is on.
          if (state.modelId !== args.modelId && state.hotkey !== 'disabled') throw 'Disable the Fn shortcut, stop recording, and wait for setup before switching models';
          if (state.modelId !== args.modelId) state.model = state.cached?.includes(args.modelId) ? 'ready' : 'not_installed';
          state.modelId = args.modelId; return { model_id: state.modelId, state: state.model, message: '' };
        case 'dictation_prepare_model':
          if (state.slowDownload) { state.model = 'preparing'; return new Promise(() => {}); }
          state.model = 'ready'; return { model_id: state.modelId, state: 'ready', message: 'Ready' };
        case 'app_settings_status': return state.saved;
        case 'app_settings_save':
          state.saved = { ...state.saved, ...Object.fromEntries(Object.entries(args.update).filter(([, value]) => value !== null && value !== undefined)) };
          if (state.saved.setupDone) state.saved.setupVersion = 1;
          return state.saved;
        case 'dictation_hotkey_status': return { state: state.hotkey };
        case 'dictation_hotkey_enable': state.hotkey = 'ready'; return { state: 'ready' };
        case 'dictation_hotkey_disable': state.hotkey = 'disabled'; return { state: 'disabled' };
        case 'global_desktop_status': return { available: true, settings: state.desktop };
        case 'global_desktop_configure': {
          // The native side refuses unknown fields (deny_unknown_fields), so the mock does too.
          const known = new Set(['enabled', 'openAtLogin', 'windowsEnabled', 'edgeDrag', 'windowGap', 'windowSkipApps']);
          const unknown = Object.keys(args.settings).filter(key => !known.has(key));
          if (unknown.length) throw `unknown field ${unknown[0]}`;
          state.desktop = args.settings; return { available: true, settings: args.settings };
        }
        case 'finder_open_in_status': return state.finder ?? false;
        case 'finder_open_in_set': state.finder = args.enabled; return args.enabled;
        case 'crash_restart_status': return state.crashRestart ?? false;
        case 'crash_restart_set':
          if (state.crashRestartFails) throw 'Could not turn this on: ~/Library/LaunchAgents is not writable. Nothing was changed.';
          state.crashRestart = args.enabled; return args.enabled;
        default: return null;
      }
    } } };
  }, overrides);
}

async function openSettings(page) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await page.evaluate(() => switchTab('settings'));
  await expect(page.locator('#general-settings')).toContainText('General');
}

test('General shows the saved setup state, the model, the tools and each permission', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const card = page.locator('#general-settings');
  await expect(card).toContainText('Setup done · 23 Oct 2026');
  await expect(card.locator('[data-gs-model]')).toHaveValue('parakeet_v3');
  await expect(card).toContainText('Downloaded');
  await expect(card.locator('input[data-gs-tool="desktop"]')).toBeChecked();
  await expect(card.locator('input[data-gs-tool="windows"]')).not.toBeChecked();
  await expect(card.locator('[data-gs-permission="microphone"]')).toContainText('Allowed');
  await expect(card.locator('[data-gs-permission="microphone"] button')).toHaveCount(0);
  await expect(card.locator('[data-gs-permission="accessibility"]')).toContainText('Not allowed');
  await expect(card.locator('[data-gs-permission="screen"]')).toContainText('Not allowed');
  await expect(card.locator('[data-gs-permission="calendar"]')).toContainText('Not asked yet');
  // The card adds no counted buttons: its only buttons are row actions.
  await expect(card.locator('button:not(.ok-row-action)')).toHaveCount(0);
});

test('Finder: Open in OfficeKit is a background-tool switch that installs and removes the Quick Action', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const card = page.locator('#general-settings');
  const finder = card.locator('input[data-gs-tool="finder"]');
  await expect(card).toContainText('Finder: Open in OfficeKit');
  await expect(finder).not.toBeChecked();
  await finder.check();
  await expect(finder).toBeChecked();
  await finder.uncheck();
  await expect(finder).not.toBeChecked();
  const calls = (await page.evaluate(() => window.__calls)).filter(call => call.command === 'finder_open_in_set');
  expect(calls.map(call => call.args)).toEqual([{ enabled: true }, { enabled: false }]);
  await expect(card.locator('button:not(.ok-row-action)')).toHaveCount(0);
});

test('Restart after a crash is an off-by-default switch under Open at login and adds no button', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const card = page.locator('#general-settings');
  const restart = card.locator('input[data-gs-tool="crash_restart"]');
  await expect(card).toContainText('Restart after a crash');
  await expect(card).toContainText('Quitting normally does not restart it.');
  await expect(restart).not.toBeChecked();
  await restart.check();
  await expect(restart).toBeChecked();
  await restart.uncheck();
  await expect(restart).not.toBeChecked();
  const calls = (await page.evaluate(() => window.__calls)).filter(call => call.command === 'crash_restart_set');
  expect(calls.map(call => call.args)).toEqual([{ enabled: true }, { enabled: false }]);
  await expect(card.locator('button:not(.ok-row-action)')).toHaveCount(0);
});

test('a failed Restart after a crash change stays off and says why on its own row', async ({ page }) => {
  await mockNative(page, { crashRestartFails: true });
  await openSettings(page);
  const card = page.locator('#general-settings');
  const restart = card.locator('input[data-gs-tool="crash_restart"]');
  await restart.check();
  await expect(card).toContainText('Could not turn this on: ~/Library/LaunchAgents is not writable. Nothing was changed.');
  await expect(restart).not.toBeChecked();
});

test('Allow asks macOS and the row turns into Allowed', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const row = page.locator('[data-gs-permission="accessibility"]');
  await row.getByRole('button', { name: 'Allow' }).click();
  await expect(row).toContainText('Allowed');
  await expect(row.getByRole('button')).toHaveCount(0);
  expect((await page.evaluate(() => window.__calls)).some(call => call.command === 'dictation_request_accessibility_permission')).toBe(true);
});

test('Calendar reads its real status and Allow asks macOS', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const row = page.locator('[data-gs-permission="calendar"]');
  await row.getByRole('button', { name: 'Allow' }).click();
  await expect(row).toContainText('Allowed');
  await expect(row.getByRole('button')).toHaveCount(0);
});

test('a Calendar permission already allowed shows Allowed with no button', async ({ page }) => {
  await mockNative(page, { calendar: 'granted' });
  await openSettings(page);
  const row = page.locator('[data-gs-permission="calendar"]');
  await expect(row).toContainText('Allowed');
  await expect(row.getByRole('button')).toHaveCount(0);
});

test('a denied microphone offers Open System Settings instead of Allow', async ({ page }) => {
  await mockNative(page, { microphone: 'denied' });
  await openSettings(page);
  const row = page.locator('[data-gs-permission="microphone"]');
  await expect(row).toContainText('Denied in System Settings');
  await row.getByRole('button', { name: 'Open System Settings' }).click();
  expect(await page.evaluate(() => window.__calls)).toContainEqual({ command: 'dictation_open_permission_settings', args: { kind: 'microphone' } });
});

test('tool switches are saved at once and blocked until their access is allowed', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted' });
  await openSettings(page);
  const windows = page.locator('input[data-gs-tool="windows"]');
  await windows.check();
  await expect(windows).toBeChecked();
  expect(await page.evaluate(() => window.__state.desktop.windowsEnabled)).toBe(true);
  await page.locator('input[data-gs-tool="dictation"]').check();
  expect(await page.evaluate(() => window.__state.hotkey)).toBe('ready');
  const login = page.locator('input[data-gs-tool="login"]');
  await login.check();
  await expect(login).toBeChecked();
  expect(await page.evaluate(() => window.__state.desktop)).toMatchObject({ windowsEnabled: true, openAtLogin: true });
  await expect(page.locator('#general-settings .ok-setup-status')).toHaveText('');
});

test('the shortcut keys shown are the saved ones, the same as the Launcher page', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted', desktop: {
    enabled: true, openAtLogin: false, windowsEnabled: true,
    shortcuts: { 'launcher.open': { keyCode: 49, modifierMask: 8 }, 'clipboard.history': { keyCode: 9, modifierMask: 10 }, 'window.left-half': { keyCode: 123, modifierMask: 3 } },
  } });
  await openSettings(page);
  const row = page.locator('.ok-gs-row', { has: page.locator('input[data-gs-tool="desktop"]') });
  await expect(row.locator('.ok-setup-key')).toHaveText('⌘Space · ⌥⌘V');
  await expect(page.locator('.ok-gs-row', { has: page.locator('input[data-gs-tool="windows"]') }).locator('.ok-setup-key')).toHaveText('⌃⌥←');
});

test('a Mac with Window layouts already on shows the switch on', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted', desktop: { enabled: true, openAtLogin: true, windowsEnabled: true } });
  await openSettings(page);
  await expect(page.locator('input[data-gs-tool="windows"]')).toBeChecked();
  await expect(page.locator('input[data-gs-tool="login"]')).toBeChecked();
});

test('Configure links go to where each tool is set up', async ({ page }) => {
  await mockNative(page, { accessibility: 'granted' });
  await openSettings(page);
  await expect(page.locator('[data-gs-configure]')).toHaveCount(3);
  await page.locator('[data-gs-configure="windows"]').click();
  await expect(page.locator('#officekit-window-snap')).toHaveAttribute('open', '');
  await page.locator('[data-gs-configure="dictation"]').click();
  await expect(page.locator('#tab-dictate, [data-tab-panel="dictate"]').first()).toBeVisible();
});

test('a switch whose access is missing is disabled and says what it needs', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  const windows = page.locator('input[data-gs-tool="windows"]');
  await expect(windows).toBeDisabled();
  await expect(page.locator('#general-settings')).toContainText('Needs Accessibility · allow it below');
});

test('changing the model downloads it in the background and keeps the choice', async ({ page }) => {
  await mockNative(page);
  await openSettings(page);
  await page.locator('[data-gs-model]').selectOption('whisper_small');
  await expect.poll(() => page.evaluate(() => window.__state.modelId)).toBe('whisper_small');
  expect(await page.evaluate(() => window.__state.saved.modelId)).toBe('whisper_small');
  expect((await page.evaluate(() => window.__calls)).some(call => call.command === 'dictation_prepare_model')).toBe(true);
  await expect(page.locator('[data-gs-model-status]')).toContainText('Whisper Small is ready.');
  await expect(page.locator('#general-settings')).toContainText('Downloaded');
});

test('a model already on this Mac switches with no download', async ({ page }) => {
  await mockNative(page, { cached: ['whisper_small'] });
  await openSettings(page);
  await page.locator('[data-gs-model]').selectOption('whisper_small');
  await expect(page.locator('[data-gs-model-status]')).toContainText('Switched to Whisper Small.');
  expect((await page.evaluate(() => window.__calls)).some(call => call.command === 'dictation_prepare_model')).toBe(false);
});

test('switching the model turns the shortcut off for the change and back on after', async ({ page }) => {
  await mockNative(page, { hotkey: 'ready' });
  await openSettings(page);
  await page.locator('[data-gs-model]').selectOption('whisper_small');
  await expect(page.locator('[data-gs-model-status]')).toContainText('Whisper Small is ready.');
  expect(await page.evaluate(() => window.__state.modelId)).toBe('whisper_small');
  expect(await page.evaluate(() => window.__state.hotkey)).toBe('ready');
});

test('a slow download shows its progress in the model row and can be left running', async ({ page }) => {
  await mockNative(page, { slowDownload: true });
  await openSettings(page);
  await page.locator('[data-gs-model]').selectOption('whisper_small');
  await expect(page.locator('#general-settings')).toContainText('Downloading');
  await expect(page.locator('[data-gs-model]')).toBeDisabled();
});

test('a model that is not on this Mac offers Download', async ({ page }) => {
  await mockNative(page, { model: 'not_installed' });
  await openSettings(page);
  await page.locator('[data-gs-download]').click();
  await expect(page.locator('[data-gs-model-status]')).toContainText('is ready.');
  await expect(page.locator('[data-gs-download]')).toHaveCount(0);
});

test('a Mac that has not run setup says so and offers to run it', async ({ page }) => {
  await mockNative(page, { saved: { setupDone: false, setupVersion: 0 }, model: 'not_installed' });
  await openSettings(page);
  const card = page.locator('#general-settings');
  await expect(card).toContainText('Setup not done');
  await expect(card).toContainText('This Mac is not set up yet');
  await expect(card).toContainText('Not downloaded');
  await card.getByRole('link', { name: 'Run setup' }).click();
  await expect(page.locator('#officekit-setup')).toBeVisible();
});

test('first time is decided from the saved file, and an earlier install carries over once', async ({ page }) => {
  await mockNative(page, { saved: { setupDone: false, setupVersion: 0 } });
  await page.goto('/');
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(false);
  await page.evaluate(() => window.localStorage.setItem('officekit.setup.done_v1', 'true'));
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(true);
  expect(await page.evaluate(() => window.__state.saved.setupDone)).toBe(true);
  await page.evaluate(() => window.localStorage.removeItem('officekit.setup.done_v1'));
  expect(await page.evaluate(() => window.officekitSetup.isDone())).toBe(true);
});
