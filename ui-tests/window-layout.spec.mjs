import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi } from './authenticated-app.mjs';

test('window layout menu drives fullscreen, monitor movement, and drag snap preferences', async ({ page }) => {
  await page.addInitScript(() => {
    window.officekitWindowCalls = [];
    window.officekitWindowEvents = new Map();
    window.__TAURI__ = {
      core: { invoke: async (command, args) => { window.officekitWindowCalls.push({ command, args }); } },
      event: { listen: async (name, handler) => {
        window.officekitWindowEvents.set(name, handler);
        return () => window.officekitWindowEvents.delete(name);
      } },
    };
  });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');

  await page.locator('#officekit-window-snap summary').click();
  await page.locator('[data-officekit-click="applyWindowSnap(\'toggle-fullscreen\')"]').click();
  await page.locator('#officekit-window-snap summary').click();
  await page.locator('[data-officekit-click="applyWindowSnap(\'move-next-monitor\')"]').click();
  await page.locator('#officekit-window-snap summary').click();
  await page.locator('[data-officekit-click="applyWindowSnap(\'move-previous-monitor\')"]').click();
  await expect.poll(() => page.evaluate(() => window.officekitWindowCalls.map(call => call.args?.action).filter(Boolean))).toEqual([
    'toggle-fullscreen', 'move-next-monitor', 'move-previous-monitor',
  ]);
  await page.keyboard.press('Control+Alt+Shift+ArrowRight');
  await expect.poll(() => page.evaluate(() => window.officekitWindowCalls.map(call => call.args?.action).filter(Boolean))).toEqual([
    'toggle-fullscreen', 'move-next-monitor', 'move-previous-monitor', 'move-next-monitor',
  ]);

  await page.locator('#officekit-window-snap summary').click();
  const edgeToggle = page.getByRole('checkbox', { name: 'Snap while dragging' });
  await expect(edgeToggle).toBeChecked();
  await edgeToggle.uncheck();
  await expect.poll(() => page.evaluate(() => window.officekitWindowCalls.at(-1))).toEqual({
    command: 'window_snap_set_edge_enabled', args: { enabled: false },
  });
  await expect.poll(() => page.evaluate(() => localStorage.getItem('officekit.window-snap-edge-enabled'))).toBe('false');
  await page.reload();
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.locator('#officekit-window-snap summary').click();
  await expect(page.getByRole('checkbox', { name: 'Snap while dragging' })).not.toBeChecked();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Shortcuts…' }).click();
  const triggerBounds = await page.locator('#officekit-window-snap > summary').boundingBox();
  expect(triggerBounds.height).toBeGreaterThanOrEqual(44);
  expect(triggerBounds.width).toBeGreaterThanOrEqual(44);
  const menuBounds = await page.locator('#officekit-window-snap .dropdown-content').boundingBox();
  expect(menuBounds.x).toBeGreaterThanOrEqual(0);
  expect(menuBounds.x + menuBounds.width).toBeLessThanOrEqual(390);
  expect(menuBounds.y + menuBounds.height).toBeLessThanOrEqual(844);
  const compactTargetHeights = await page.locator('#officekit-window-snap .dropdown-content button').evaluateAll(buttons => buttons.filter(button => button.offsetParent !== null).map(button => button.getBoundingClientRect().height));
  expect(compactTargetHeights.length).toBeGreaterThan(10);
  expect(compactTargetHeights.every(height => height >= 44)).toBe(true);
});

test('edge preview reports the layout while the window is dragged near a screen edge', async ({ page }) => {
  await page.addInitScript(() => {
    window.__TAURI__ = {
      core: { invoke: async () => {} },
      event: { listen: async (name, handler) => {
        (window.officekitWindowEvents ||= new Map()).set(name, handler);
        return () => window.officekitWindowEvents.delete(name);
      } },
    };
  });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  const preview = page.locator('#officekit-window-snap-preview');
  await expect.poll(() => page.evaluate(() => typeof window.officekitWindowEvents?.get('window-snap-preview'))).toBe('function');
  await page.evaluate(() => window.officekitWindowEvents.get('window-snap-preview')({ payload: { action: 'left-half' } }));
  await expect(preview).toHaveText('Pause to snap left half');
  await page.evaluate(() => window.officekitWindowEvents.get('window-snap-preview')({ payload: { action: null } }));
  await expect(preview).toBeHidden();
});

test('shortcut editor saves custom keys and resets to Rectangle defaults', async ({ page }) => {
  await page.addInitScript(() => {
    window.__TAURI__ = { core: { invoke: async () => {} } };
    localStorage.removeItem('officekit.window-snap-shortcuts');
  });
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');

  await page.locator('#officekit-window-snap summary').click();
  await page.getByRole('button', { name: 'Shortcuts…' }).click();
  const modifier = await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌃⌥' : 'Ctrl+Alt+');
  await page.locator('#window-snap-shortcut-rows > div').filter({ hasText: 'Left half' }).getByRole('button', { name: 'Change' }).click();
  await page.keyboard.press('Control+Alt+L');
  await expect(page.locator('#window-snap-shortcut-rows')).toContainText(`${modifier}L`);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('officekit.window-snap-shortcuts'))['left-half'])).toBe('l');

  await page.getByRole('button', { name: 'Reset to Rectangle shortcuts' }).click();
  const rectangleDefaults = {
    'Left half': `${modifier}←`,
    'Right half': `${modifier}→`,
    'Top half': `${modifier}↑`,
    'Bottom half': `${modifier}↓`,
    'Top-left': `${modifier}U`,
    'Top-right': `${modifier}I`,
    'Bottom-left': `${modifier}J`,
    'Bottom-right': `${modifier}K`,
    Center: `${modifier}C`,
    Maximize: `${modifier}↩`,
    Restore: `${modifier}⌫`,
    Fullscreen: `${modifier}F`,
    'Previous screen': `${modifier}⇧←`,
    'Next screen': `${modifier}⇧→`,
  };
  for (const [label, shortcut] of Object.entries(rectangleDefaults)) {
    await expect(page.locator('#window-snap-shortcut-rows > div').filter({ hasText: label }).locator('kbd')).toHaveText(shortcut);
  }
  await expect.poll(() => page.evaluate(() => localStorage.getItem('officekit.window-snap-shortcuts'))).toBeNull();
});
