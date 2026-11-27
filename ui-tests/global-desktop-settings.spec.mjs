import { test, expect } from '@playwright/test';

const API = `http://127.0.0.1:${process.env.OFFICEKIT_UI_TEST_API_PORT || '19873'}`;
const authorization = () => `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`;

// The screen budget: no page shows more than three buttons at once (AGENTS.md "Button Limit").
const BUTTON_LIMIT = 3;

async function openCard(page, { desktop, tab = 'clipboard' }) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `${API}${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: authorization() },
    });
  });
  if (desktop) {
    await page.addInitScript(() => {
      window.__nativeCalls = [];
      const defaults = {
        'clipboard.history': { keyCode: 9, modifierMask: 10 },
        'snippets.panel': { keyCode: 1, modifierMask: 10 },
        'launcher.open': { keyCode: 49, modifierMask: 3 },
        'window.left-half': { keyCode: 123, modifierMask: 3 },
        'window.right-half': { keyCode: 124, modifierMask: 3 },
        'window.maximize': { keyCode: 36, modifierMask: 3 },
        'window.next-display': { keyCode: 124, modifierMask: 11 },
      };
      const filterDefaults = {
        all: { keyCode: 18, modifierMask: 1 },
        app: { keyCode: 19, modifierMask: 1 },
        tool: { keyCode: 20, modifierMask: 1 },
        snippet: { keyCode: 21, modifierMask: 1 },
      };
      const settings = {
        enabled: false,
        openAtLogin: false,
        windowsEnabled: false,
        edgeDrag: false,
        windowGap: 0,
        windowSkipApps: [],
        shortcuts: { ...defaults },
        launcherFilters: { ...filterDefaults },
        launcherEnabled: true,
        snippetsEnabled: true,
        launcherShowApps: true,
        launcherShowTools: true,
        launcherShowSnippets: true,
        quickCalculator: true,
        quickUuid: true,
        quickPassword: true,
      };
      let current = settings;
      const seen = shortcuts => {
        const keys = Object.values(shortcuts).map(s => `${s.keyCode}:${s.modifierMask}`);
        return new Set(keys).size !== keys.length;
      };
      window.__TAURI__ = {
        core: {
          invoke: async (command, args) => {
            window.__nativeCalls.push([command, args]);
            if (command === 'global_desktop_status') {
              return { available: true, accessibility: 'needs-access', loginItem: 'off', settings: current, registrationFailures: [] };
            }
            if (command === 'global_desktop_configure') {
              if (seen(args.settings.shortcuts)) throw 'Two actions cannot share the same shortcut.';
              if (args.settings.windowGap > 64) throw 'The window gap must be between 0 and 64 pixels.';
              // Like the app: missing filters get their defaults, and two filters cannot share a key.
              args.settings.launcherFilters = { ...filterDefaults, ...args.settings.launcherFilters };
              const filterKeys = Object.values(args.settings.launcherFilters).map(s => `${s.keyCode}:${s.modifierMask}`);
              if (new Set(filterKeys).size !== filterKeys.length) throw 'Two launcher filters cannot share the same shortcut.';
              current = args.settings;
              return { available: true, accessibility: 'needs-access', loginItem: 'off', settings: current, registrationFailures: [] };
            }
            if (command === 'list_installed_apps') {
              return [
                { name: 'Safari', bundleId: 'com.apple.Safari' },
                { name: 'Terminal', bundleId: 'com.apple.Terminal' },
                { name: '1Password', bundleId: 'com.1password.1password' },
                { name: 'Broken', bundleId: 'has space' },
              ];
            }
            if (command === 'global_desktop_default_shortcuts') return defaults;
            if (command === 'global_desktop_refresh' || command === 'dictation_open_permission_settings' || command === 'window_snap_set_edge_enabled') return null;
            throw new Error(`Unexpected native command ${command}`);
          },
        },
      };
    });
  }
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(tabName => switchTab(tabName), tab);
  await expect(page.locator(tab === 'global-launcher' ? '#global-launcher-card' : '#global-desktop-card')).toBeVisible();
}

// The test sidecar uses the real local clipboard store, so put its settings back after each test.
let savedSettings = null;
test.beforeEach(async ({ request }) => {
  const response = await request.get(`${API}/api/clipboard/global-settings`, { headers: { authorization: authorization() } });
  savedSettings = (await response.json()).settings;
  // Start every test from the default pause and panel filter, so an earlier test cannot leak state into it.
  await request.post(`${API}/api/clipboard/global-settings`, {
    headers: { authorization: authorization(), 'content-type': 'application/json' },
    data: { capture_pause: 'off', panel_default_filter: 'text' },
  });
});
test.afterEach(async ({ request }) => {
  if (!savedSettings) return;
  await request.post(`${API}/api/clipboard/global-settings`, {
    headers: { authorization: authorization(), 'content-type': 'application/json' },
    data: savedSettings,
  });
});

const settingsApi = (page, data) =>
  page.request.post(`${API}/api/clipboard/global-settings`, {
    headers: { authorization: authorization(), 'content-type': 'application/json' },
    data,
  });

const storedSettings = async page => (await (await page.request.get(`${API}/api/clipboard/global-settings`, { headers: { authorization: authorization() } })).json()).settings;

const lastConfigure = page => page.evaluate(() => window.__nativeCalls.filter(([c]) => c === 'global_desktop_configure').at(-1)[1].settings);

test('browser mode explains the card is desktop only and disables its controls', async ({ page }) => {
  await openCard(page, { desktop: false });
  await expect(page.locator('#global-desktop-unavailable')).toBeVisible();
  await expect(page.locator('#global-desktop-capture')).toBeDisabled();
  await expect(page.locator('#global-desktop-shortcut-clipboard-history')).toBeDisabled();
  await expect(page.locator('#global-clipboard-pause-15m')).toBeDisabled();
  await expect(page.locator('#global-desktop-snippets-enabled')).toBeDisabled();
});

test('desktop card shows defaults, saves toggles and guides Accessibility', async ({ page }) => {
  await openCard(page, { desktop: true });
  await settingsApi(page, { capture_enabled: false, expansion_enabled: false, skip_bundle_ids: ['com.1password.1password'], retention_clips: 500, retention_days: 30 });
  await page.evaluate(() => window.officekitGlobalDesktop.reload());

  await expect(page.locator('#global-desktop-shortcut-clipboard-history')).toHaveText('⌥⌘V');
  await expect(page.locator('#global-desktop-shortcut-snippets-panel')).toHaveText('⌥⌘S');
  await expect(page.locator('#global-desktop-skip-summary')).toContainText('1 app');
  await expect(page.locator('#global-desktop-retention-summary')).toHaveText('500 clips · 30 days');
  await expect(page.locator('#global-desktop-accessibility')).toBeVisible();

  await page.locator('#global-desktop-enabled').check();
  await expect.poll(() => page.evaluate(() => window.__nativeCalls.filter(([c]) => c === 'global_desktop_configure').length)).toBe(1);
  await page.locator('#global-desktop-capture').check();
  await expect.poll(async () => (await storedSettings(page)).capture_enabled).toBe(true);
  await expect.poll(() => page.evaluate(() => window.__nativeCalls.some(([c]) => c === 'global_desktop_refresh'))).toBe(true);

  await page.locator('#global-desktop-open-accessibility').click();
  await expect.poll(() => page.evaluate(() => window.__nativeCalls.some(([c, a]) => c === 'dictation_open_permission_settings' && a.kind === 'accessibility'))).toBe(true);
});

test('the clipboard and snippets block shows at most three buttons, also while paused and with the skip list open', async ({ page }) => {
  await openCard(page, { desktop: true });
  // Resume is in the DOM but hidden until a pause starts, so only visible buttons count.
  await expect(page.locator('#global-desktop-card button:visible')).toHaveCount(2);
  await page.locator('#global-clipboard-pause-1h').check();
  await expect(page.locator('#global-clipboard-paused')).toBeVisible();
  await page.locator('#global-desktop-edit-panel > summary').click();
  await expect(page.locator('#global-desktop-skip-search')).toBeVisible();
  const buttons = await page.locator('#global-desktop-card button:visible').count();
  expect(buttons).toBeLessThanOrEqual(BUTTON_LIMIT);
  expect(buttons).toBe(3);
});

test('the pause banner shows the end time, resumes early and keeps the saved clips', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-clipboard-pause-1h').check();
  await expect(page.locator('#global-clipboard-paused')).toBeVisible();
  await expect(page.locator('#global-clipboard-paused-text')).toContainText(/Capture paused until \d{1,2}:\d{2}/);
  const paused = await storedSettings(page);
  expect(paused.capture_pause).toBe('1h');
  expect(paused.capture_paused).toBe(true);
  expect(paused.capture_paused_until).toBeGreaterThan(Date.now() / 1000 + 3000);
  await expect.poll(() => page.evaluate(() => window.__nativeCalls.some(([c]) => c === 'global_desktop_refresh'))).toBe(true);

  await page.locator('#global-clipboard-resume').click();
  await expect(page.locator('#global-clipboard-paused')).toBeHidden();
  await expect(page.locator('#global-clipboard-pause-off')).toBeChecked();
  expect((await storedSettings(page)).capture_paused).toBe(false);
});

test('until I resume pauses without an end time and says so', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-clipboard-pause-until').check();
  await expect(page.locator('#global-clipboard-paused-text')).toHaveText('Capture paused until you resume');
  expect((await storedSettings(page)).capture_paused_until).toBeNull();
});

test('the panel opens on a chosen filter and defaults to Text', async ({ page }) => {
  await openCard(page, { desktop: true });
  await expect(page.locator('#global-clipboard-panel-text')).toBeChecked();
  await page.locator('#global-clipboard-panel-links').check();
  await expect.poll(async () => (await storedSettings(page)).panel_default_filter).toBe('links');
  await page.reload();
  await page.evaluate(() => switchTab('clipboard'));
  await expect(page.locator('#global-clipboard-panel-links')).toBeChecked();
});

test('snippets panel switch releases its shortcut through the native command', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-desktop-snippets-enabled').uncheck();
  await expect.poll(async () => (await lastConfigure(page)).snippetsEnabled).toBe(false);
  await expect(page.locator('#global-desktop-snippets-enabled')).not.toBeChecked();
  await page.locator('#global-desktop-snippets-enabled').check();
  await expect.poll(async () => (await lastConfigure(page)).snippetsEnabled).toBe(true);
});

test('recording a shortcut saves it and a duplicate is rejected with a message', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-desktop-shortcut-snippets-panel').click();
  await expect(page.locator('#global-desktop-shortcut-snippets-panel')).toContainText('Press shortcut');
  await page.keyboard.press('Control+Alt+KeyK');
  await expect(page.locator('#global-desktop-shortcut-snippets-panel')).toHaveText('⌃⌥K');

  await page.locator('#global-desktop-shortcut-snippets-panel').click();
  await page.keyboard.press('Alt+Meta+KeyV');
  await expect(page.locator('#global-desktop-status')).toContainText('cannot share');

  await page.locator('#global-desktop-shortcut-snippets-panel').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#global-desktop-status')).toContainText('unchanged');
});

test('the global launcher is its own page with a launcher switch and a shortcut that can be recorded', async ({ page }) => {
  await openCard(page, { desktop: true, tab: 'global-launcher' });
  await expect(page.locator('#global-launcher-enabled')).toBeChecked();
  await page.locator('#global-launcher-enabled').uncheck();
  await expect.poll(async () => (await lastConfigure(page)).launcherEnabled).toBe(false);

  await page.locator('#global-desktop-shortcut-launcher').click();
  await page.keyboard.press('Control+Alt+KeyL');
  await expect(page.locator('#global-desktop-shortcut-launcher')).toHaveText('⌃⌥L');
  expect((await lastConfigure(page)).shortcuts['launcher.open']).toEqual({ keyCode: 37, modifierMask: 3 });
});

test('show in results and the quick-result switches save separately', async ({ page }) => {
  await openCard(page, { desktop: true, tab: 'global-launcher' });
  await expect(page.locator('#global-launcher-show-apps')).toBeChecked();
  await page.locator('#global-launcher-show-tools').uncheck();
  await expect.poll(async () => (await lastConfigure(page)).launcherShowTools).toBe(false);
  await expect(page.locator('#global-launcher-show-snippets')).toBeChecked();
  await page.locator('#global-launcher-quick-calculator').uncheck();
  await expect.poll(async () => (await lastConfigure(page)).quickCalculator).toBe(false);
  await page.locator('#global-launcher-quick-password').check();
  await expect.poll(async () => (await lastConfigure(page)).quickPassword).toBe(true);
  expect((await lastConfigure(page)).quickUuid).toBe(true);
});

test('the launcher page shows at most three buttons (shortcut, change key, reset)', async ({ page }) => {
  await openCard(page, { desktop: true, tab: 'global-launcher' });
  await expect(page.locator('#tab-global-launcher button')).toHaveCount(3);
  await expect(page.locator('#tab-global-launcher button:visible')).toHaveCount(3);
  expect(await page.locator('#tab-global-launcher button:visible').count()).toBeLessThanOrEqual(BUTTON_LIMIT);
});

test('launcher filter keys: pick a filter, record a key, refuse a clash and reset', async ({ page }) => {
  await openCard(page, { desktop: true, tab: 'global-launcher' });
  await expect(page.locator('#global-launcher-filter-all')).toHaveText('⌃1');
  await expect(page.locator('#global-launcher-filter-app')).toHaveText('⌃2');
  await expect(page.locator('#global-launcher-filter-snippet')).toHaveText('⌃4');

  await page.locator('#global-launcher-filter-name').selectOption('app');
  await page.locator('#global-launcher-filter-change').click();
  await expect(page.locator('#global-launcher-filter-app')).toContainText('Press shortcut');
  await page.keyboard.press('Control+Alt+Digit7');
  await expect(page.locator('#global-launcher-filter-app')).toHaveText('⌃⌥7');
  const saved = (await lastConfigure(page)).launcherFilters.app;
  expect(saved).toEqual({ keyCode: 26, modifierMask: 3 });

  await page.locator('#global-launcher-filter-change').click();
  await page.keyboard.press('Control+Digit1');
  await expect(page.locator('#global-launcher-status')).toContainText('cannot share');
  await expect(page.locator('#global-launcher-filter-app')).toHaveText('⌃⌥7');

  await page.locator('#global-desktop-filters-reset').click();
  await expect(page.locator('#global-launcher-filter-app')).toHaveText('⌃2');
});

test('skipped apps save as they are chosen and the bundle-id box stays in step', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-desktop-edit-panel > summary').click();
  const rows = page.locator('#global-desktop-skip-apps li');
  await expect(rows).toHaveCount(3); // the app with an invalid bundle id is not offered
  await expect(page.locator('#global-desktop-skip-apps')).not.toContainText('Broken');

  await page.getByRole('checkbox', { name: 'Skip Terminal' }).check();
  await expect.poll(async () => (await storedSettings(page)).skip_bundle_ids).toContain('com.apple.Terminal');
  await page.getByRole('checkbox', { name: 'Skip Safari' }).check();
  // Chosen apps float to the top (1Password is skipped by default), then the rest by name.
  await expect(rows.nth(0)).toContainText('1Password');
  await expect(rows.nth(1)).toContainText('Safari');
  await expect(rows.nth(2)).toContainText('Terminal');

  await page.locator('#global-desktop-skip-search').fill('term');
  await expect(rows).toHaveCount(1);
  await page.locator('#global-desktop-skip-search').fill('zzz');
  await expect(page.locator('#global-desktop-skip-apps-note')).toHaveText('No installed app matches.');
  await page.locator('#global-desktop-skip-search').fill('');

  await page.locator('#global-desktop-edit-panel details > summary').click();
  await expect(page.locator('#global-desktop-skip')).toHaveValue(/com\.apple\.Terminal/);
  await page.locator('#global-desktop-skip').fill('com.apple.Terminal');
  await page.locator('#global-desktop-skip').dispatchEvent('change');
  await expect(page.getByRole('checkbox', { name: 'Skip Safari' })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Skip Terminal' })).toBeChecked();

  await page.getByRole('checkbox', { name: 'Skip Terminal' }).uncheck();
  await expect(page.locator('#global-desktop-skip')).toHaveValue('');
});

test('skipped apps and retention validate before saving and autosave when valid', async ({ page }) => {
  await openCard(page, { desktop: true });
  await page.locator('#global-desktop-edit-panel > summary').click();
  await page.locator('#global-desktop-edit-panel details > summary').click();

  await page.locator('#global-desktop-skip').fill('not a bundle id');
  await page.locator('#global-desktop-skip').dispatchEvent('change');
  await expect(page.locator('#global-desktop-status')).toContainText('not a valid app id');

  await page.locator('#global-desktop-retention-clips').fill('10');
  await page.locator('#global-desktop-retention-clips').dispatchEvent('change');
  await expect(page.locator('#global-desktop-status')).toContainText('50 and 5000');

  await page.locator('#global-desktop-skip').fill('com.apple.keychainaccess\ncom.bitwarden.desktop');
  await page.locator('#global-desktop-skip').dispatchEvent('change');
  await page.locator('#global-desktop-retention-clips').fill('800');
  await page.locator('#global-desktop-retention-days').fill('14');
  await page.locator('#global-desktop-retention-days').dispatchEvent('change');
  await expect(page.locator('#global-desktop-retention-summary')).toHaveText('800 clips · 14 days');
  await expect(page.locator('#global-desktop-skip-summary')).toContainText('2 apps');
});

async function openWindowMenu(page) {
  await page.locator('#officekit-window-snap > summary').click();
  await expect(page.locator('#global-windows-section')).toBeVisible();
}

test('window manager section is disabled in the browser', async ({ page }) => {
  await openCard(page, { desktop: false });
  await openWindowMenu(page);
  await expect(page.locator('#global-windows-unavailable')).toBeVisible();
  await expect(page.locator('#global-windows-enabled')).toBeDisabled();
});

test('window manager toggles, gap and skipped apps save through the native command', async ({ page }) => {
  await openCard(page, { desktop: true });
  await openWindowMenu(page);
  await expect(page.locator('#global-windows-edge-drag')).toBeDisabled();
  await page.locator('#global-windows-enabled').check();
  await expect(page.locator('#global-windows-edge-drag')).toBeEnabled();
  await expect(page.locator('#global-windows-accessibility')).toBeVisible();
  await page.locator('#global-windows-edge-drag').check();
  await expect(page.locator('#window-snap-edge-toggle')).toBeDisabled();
  await expect(page.locator('#window-snap-edge-toggle')).not.toBeChecked();

  await page.locator('#global-windows-gap').fill('12');
  await page.locator('#global-windows-gap').press('Tab');
  await expect.poll(() => page.evaluate(() => window.__nativeCalls.filter(([c, a]) => c === 'global_desktop_configure' && a.settings.windowGap === 12).length)).toBe(1);

  await page.locator('#global-windows-gap').fill('99');
  await page.locator('#global-windows-gap').press('Tab');
  await expect(page.locator('#global-windows-status')).toContainText('0 to 64');

  await page.locator('#global-windows-skip-edit').click();
  await page.locator('#global-windows-skip').fill('com.apple.finder\nbad id');
  await page.locator('#global-windows-skip-save').click();
  await expect(page.locator('#global-windows-status')).toContainText('not a valid app id');
  await page.locator('#global-windows-skip').fill('com.apple.finder\ncom.apple.Safari');
  await page.locator('#global-windows-skip-save').click();
  await expect(page.locator('#global-windows-skip-summary')).toContainText('2 apps');

  await page.locator('#global-windows-edge-drag').uncheck();
  await expect(page.locator('#window-snap-edge-toggle')).toBeEnabled();
});

test('window shortcuts can be recorded, cleared, conflict-checked and reset', async ({ page }) => {
  await openCard(page, { desktop: true });
  await openWindowMenu(page);
  await page.locator('#global-windows-shortcuts-edit').click();
  const leftHalf = page.locator('[data-global-action="window.left-half"]');
  await expect(leftHalf).toHaveText('⌃⌥←');

  await leftHalf.click();
  await page.keyboard.press('Control+Alt+KeyH');
  await expect(leftHalf).toHaveText('⌃⌥H');

  await leftHalf.click();
  await page.keyboard.press('Control+Alt+ArrowRight');
  await expect(page.locator('#global-windows-status')).toContainText('cannot share');

  await page.getByRole('button', { name: 'Clear Right half shortcut' }).click();
  await expect(page.locator('[data-global-action="window.right-half"]')).toHaveText('Not set');

  await page.locator('#global-windows-shortcuts-reset').click();
  await expect(leftHalf).toHaveText('⌃⌥←');
  await expect(page.locator('[data-global-action="window.right-half"]')).toHaveText('⌃⌥→');
});

test('the clipboard page and the launcher page have no horizontal overflow at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  for (const tab of ['clipboard', 'global-launcher']) {
    await openCard(page, { desktop: true, tab });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  }
});
