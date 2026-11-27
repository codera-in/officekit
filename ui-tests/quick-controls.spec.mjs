import { test, expect } from '@playwright/test';

test('Quick Controls shows the approved tools, tooltips and a single Disable all action', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 860 });
  await page.goto('/quick-controls.html');

  await expect(page.getByRole('heading', { name: 'Quick controls' })).toBeVisible();
  for (const name of ['Speech Coach', 'Listen In', 'Speech to text', 'Window Manager', 'Ergonomics', 'Meeting Recorder']) {
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(page.locator('.quick-control-row input[type="checkbox"]')).toHaveCount(15);
  await expect(page.getByRole('heading', { name: 'Menu bar stats' })).toBeVisible();
  const groups = await page.locator('.quick-group').evaluateAll(sections => sections.map(section => ({
    heading: section.querySelector('h2').textContent,
    tools: [...section.querySelectorAll('[data-tool]')].map(row => row.dataset.tool),
  })));
  expect(groups).toEqual([
    { heading: 'Speech', tools: ['speechCoach', 'listenIn', 'speechToText', 'meetingRecorder'] },
    { heading: 'Desktop', tools: ['windowManager', 'clipboardHistory', 'ergonomics'] },
    { heading: 'Menu bar stats', tools: ['menuCpu', 'menuGpu', 'menuTemperature', 'menuRam', 'menuStorage', 'menuNetwork', 'menuBattery', 'menuBluetooth'] },
  ]);
  for (const name of ['CPU', 'GPU', 'Temperature', 'RAM', 'Storage', 'Network', 'Battery', 'Bluetooth']) {
    await expect(page.getByRole('checkbox', { name: `Show ${name} in the menu bar` })).toBeVisible();
  }
  await expect(page.locator('[data-tool="listenIn"]')).toHaveAttribute('title', /free-form speaking practice/);
  await expect(page.locator('[data-tool="speechCoach"]')).toHaveAttribute('title', /private Live Workspace that is hidden from screen sharing/);
  await expect(page.getByRole('button')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Disable all' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'HUD position' })).toBeVisible();
  for (const row of await page.locator('.quick-control-row').all()) {
    await expect(row).toHaveAttribute('title', /.+/);
    const checkbox = row.locator('input[type="checkbox"]');
    const descriptionId = await checkbox.getAttribute('aria-describedby');
    expect(descriptionId).toBeTruthy();
    await expect(page.locator(`#${descriptionId}`)).toHaveText(/.+/);
    await expect(row.locator('.quick-control-icon :is(.fa-solid, svg)')).toHaveCount(1);
  }
  // Disable all is the first thing under the title, and the stats are four-across icon-only tiles.
  const order = await page.locator('#quick-controls .card-body > *').evaluateAll(nodes => nodes.map(node => node.id || node.tagName.toLowerCase()));
  expect(order.slice(0, 2)).toEqual(['header', 'quick-controls-disable-all']);
  const tiles = await page.locator('.quick-stat-tile').evaluateAll(nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return { x: Math.round(box.x), height: Math.round(box.height) }; }));
  expect(new Set(tiles.map(tile => tile.x)).size).toBe(4);
  expect(tiles.every(tile => tile.height <= 52)).toBe(true);
  // The names are not drawn (they stay for tooltips and screen readers).
  const drawnLabelWidths = await page.locator('.quick-stat-tile .quick-control-copy').evaluateAll(nodes => nodes.map(node => Math.round(node.getBoundingClientRect().width)));
  expect(drawnLabelWidths.every(width => width <= 1)).toBe(true);
  const popupHeight = await page.locator('#quick-controls').evaluate(element => Math.ceil(element.getBoundingClientRect().height));
  expect(popupHeight).toBeLessThanOrEqual(836);
});

test('Menu bar stats switch one at a time through the app', async ({ page }) => {
  await page.addInitScript(() => {
    const state = {
      speechCoach: false, listenIn: false, speechToText: false, windowManager: false, ergonomics: false,
      meetingRecorder: false, menuCpu: false, menuRam: true, menuStorage: false, menuNetwork: false,
      hudPosition: 'top_center'
    };
    window.__quickControlCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      if (command === 'quick_controls_status') return { ...state };
      if (command === 'quick_controls_set_tool') {
        window.__quickControlCalls.push(args);
        state[args.tool] = args.enabled;
        return { ...state };
      }
      throw new Error(`Unexpected command: ${command}`);
    } } };
  });
  await page.goto('/quick-controls.html');
  const cpu = page.getByRole('checkbox', { name: 'Show CPU in the menu bar' });
  const ram = page.getByRole('checkbox', { name: 'Show RAM in the menu bar' });
  await expect(ram).toBeChecked();
  await expect(cpu).not.toBeChecked();
  await expect(page.locator('[data-tool="menuRam"] [data-state]')).toHaveText('In menu bar');
  await expect(page.locator('[data-tool="menuCpu"] [data-state]')).toHaveText('Off');
  await cpu.check();
  await expect(cpu).toBeChecked();
  await expect(page.getByText('CPU in the menu bar is on.')).toBeVisible();
  await ram.uncheck();
  await expect(ram).not.toBeChecked();
  expect(await page.evaluate(() => window.__quickControlCalls)).toEqual([
    { tool: 'menuCpu', enabled: true },
    { tool: 'menuRam', enabled: false }
  ]);
  await expect(page.getByRole('button')).toHaveCount(1);
});

test('GPU, Temperature, Battery and Bluetooth each have their own menu bar switch', async ({ page }) => {
  await page.addInitScript(() => {
    const state = { menuCpu: true, menuGpu: false, menuTemperature: false, menuBattery: false, menuBluetooth: true, hudPosition: 'top_center' };
    window.__quickControlCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      if (command === 'quick_controls_status') return { ...state };
      if (command === 'quick_controls_set_tool') { window.__quickControlCalls.push(args); state[args.tool] = args.enabled; return { ...state }; }
      throw new Error(`Unexpected command: ${command}`);
    } } };
  });
  await page.goto('/quick-controls.html');
  const bluetooth = page.getByRole('checkbox', { name: 'Show Bluetooth in the menu bar' });
  await expect(bluetooth).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Show GPU in the menu bar' })).not.toBeChecked();
  await expect(page.locator('[data-tool="menuTemperature"] [data-state]')).toHaveText('Off');
  await bluetooth.uncheck();
  await page.getByRole('checkbox', { name: 'Show Temperature in the menu bar' }).check();
  expect(await page.evaluate(() => window.__quickControlCalls)).toEqual([
    { tool: 'menuBluetooth', enabled: false },
    { tool: 'menuTemperature', enabled: true },
  ]);
  await expect(page.getByRole('button')).toHaveCount(1);
});

for (const [label, hasBattery, shown] of [['a desktop Mac', false, false], ['a laptop', true, true], ['an unknown answer', undefined, true]]) {
  test(`the Battery menu bar switch is ${shown ? 'offered' : 'left out'} on ${label}`, async ({ page }) => {
    await page.addInitScript((value) => {
      window.__TAURI__ = { core: { invoke: async (command) => {
        if (command === 'quick_controls_status') return { menuCpu: true, menuBattery: false, hasBattery: value, hudPosition: 'top_center' };
        throw new Error(`Unexpected command: ${command}`);
      } } };
    }, hasBattery);
    await page.goto('/quick-controls.html');
    await expect(page.getByRole('checkbox', { name: 'Show CPU in the menu bar' })).toBeChecked();
    await expect(page.getByRole('checkbox', { name: 'Show Battery in the menu bar' })).toHaveCount(shown ? 1 : 0);
    await expect(page.locator('[data-tool="menuBattery"]')).toBeVisible({ visible: shown });
    await expect(page.getByRole('button')).toHaveCount(1);
  });
}

test('Clipboard history switch pauses and resumes saving through the app', async ({ page }) => {
  await page.addInitScript(() => {
    const state = { clipboardHistory: true, hudPosition: 'top_center' };
    window.__quickControlCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      if (command === 'quick_controls_status') return { ...state };
      if (command === 'quick_controls_set_tool') {
        window.__quickControlCalls.push(args);
        state[args.tool] = args.enabled;
        return { ...state };
      }
      throw new Error(`Unexpected command: ${command}`);
    } } };
  });
  await page.goto('/quick-controls.html');
  const history = page.getByRole('checkbox', { name: 'Enable Clipboard history' });
  await expect(history).toBeChecked();
  await expect(page.locator('[data-tool="clipboardHistory"] [data-state]')).toHaveText('Enabled');
  await history.uncheck();
  await expect(history).not.toBeChecked();
  await expect(page.locator('[data-tool="clipboardHistory"] [data-state]')).toHaveText('Disabled');
  expect(await page.evaluate(() => window.__quickControlCalls)).toEqual([{ tool: 'clipboardHistory', enabled: false }]);
});

test('a switch whose access is missing says what it needs and asks for it when turned on', async ({ page }) => {
  await page.addInitScript(() => {
    const state = { windowManager: false, speechToText: false, hudPosition: 'top_center' };
    window.__accessCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      window.__accessCalls.push(command);
      if (command === 'quick_controls_status') return { ...state };
      if (command === 'dictation_accessibility_permission') return { permission: 'denied' };
      if (command === 'dictation_microphone_permission') return { permission: 'granted' };
      if (command === 'dictation_request_accessibility_permission') return { permission: 'denied' };
      if (command === 'quick_controls_set_tool') { state[args.tool] = args.enabled; return { ...state }; }
      throw new Error(`Unexpected command: ${command}`);
    } } };
  });
  await page.goto('/quick-controls.html');
  await expect(page.locator('[data-tool="windowManager"] [data-state]')).toHaveText('Needs Accessibility · tap to allow');
  await expect(page.locator('[data-tool="speechToText"] [data-state]')).toHaveText('Disabled');
  await page.getByRole('checkbox', { name: 'Enable Window Manager' }).check();
  expect(await page.evaluate(() => window.__accessCalls)).toContain('dictation_request_accessibility_permission');
});

test('Listen In starts solo practice and stays synced with Speech Coach', async ({ page }) => {
  const calls = [];
  await page.addInitScript(() => {
    const state = {
      speechCoach: false,
      listenIn: false,
      speechToText: false,
      windowManager: false,
      ergonomics: false,
      meetingRecorder: false,
      hudPosition: 'top_center'
    };
    window.__TAURI__ = {
      core: {
        invoke: async (command, args = {}) => {
          if (command === 'quick_controls_status') return { ...state };
          if (command === 'quick_controls_set_tool') {
            window.__quickControlCalls.push({ command, args });
            if (args.tool === 'listenIn') {
              state.listenIn = args.enabled;
              state.speechCoach = args.enabled;
            }
            return { ...state };
          }
          throw new Error(`Unexpected command: ${command}`);
        }
      }
    };
    window.__quickControlCalls = [];
  });
  await page.goto('/quick-controls.html');
  const listenIn = page.getByRole('checkbox', { name: 'Start or stop Listen In solo practice' });
  await expect(listenIn).toBeVisible();
  await listenIn.check();
  await expect(listenIn).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Enable Speech Coach' })).toBeChecked();
  await expect(page.getByText('Listen In is on. Speak naturally; coaching stays on this Mac.')).toBeVisible();
  await listenIn.uncheck();
  await expect(listenIn).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Enable Speech Coach' })).not.toBeChecked();
  calls.push(...await page.evaluate(() => window.__quickControlCalls));
  expect(calls).toEqual([
    { command: 'quick_controls_set_tool', args: { tool: 'listenIn', enabled: true } },
    { command: 'quick_controls_set_tool', args: { tool: 'listenIn', enabled: false } }
  ]);
});
