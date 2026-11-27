import { expect, test } from '@playwright/test';

test('network rates appear in System Stats and are sent to the persistent menu-bar adapter', async ({ page }) => {
  const metrics = {
    cpu_percent: 67.3,
    memory_percent: 78.9,
    storage_percent: 3.4,
    volume_label: 'System volume',
    upload_bytes_per_second: 40 * 1024,
    download_bytes_per_second: 512 * 1024,
    captured_at: '2026-10-14T00:00:00+00:00',
    sample_age_ms: 0,
    reasons: {},
    cpu_cores_percent: [10, 50, 90],
    gpu: { utilization_percent: 12.4, renderer_percent: 9, tiler_percent: 6, model: 'Apple M1 Max', core_count: 24 },
    network: { interface: 'en0', local_address: '192.168.1.20', sent_total_bytes: 2048, received_total_bytes: 4096 },
    battery: { percent: 76, power_source: 'battery', state: 'discharging', time_remaining_seconds: 7200,
      cycle_count: 324, designed_capacity_mah: 5000, full_charge_capacity_mah: 4600,
      health_percent: 92, condition: 'Normal' },
    sensors: [{ name: 'CPU Package', current_c: 58.5, high_c: 100 }],
  };
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/system/metrics') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(metrics) });
    } else {
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
  });
  await page.goto('/');
  await page.evaluate(() => {
    window.__officekitTestNativeCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command === 'officekit_api_token') return 'test-token-with-32-characters-min';
      window.__officekitTestNativeCalls.push({ command, args });
    } } };
    switchTab('quick-stats');
  });

  const card = id => page.locator(`#quick-stat-cards [data-stat-card="${id}"]`);
  await expect(card('net')).toContainText('40K');
  await expect(card('net')).toContainText('512K');
  await expect(card('net')).toContainText('192.168.1.20');
  await expect(card('cpu').locator('.ok-card-cores > i')).toHaveCount(3);
  await expect(card('cpu').locator('.ok-ring').first()).toContainText('59°');
  await expect(card('gpu')).toContainText('12%');
  await expect(card('gpu')).toContainText('Apple M1 Max');
  await expect(card('battery')).toContainText('Health');
  await expect(card('battery')).toContainText('92%');
  await expect(page.locator('#quick-stat-cards .ok-system-card').first()).toBeVisible();
  await page.evaluate(() => { dictationHistoryStore.clear(); dictationHistoryStore.add('Hello  world\nthis is a dictated note that runs well past forty characters', 'push-to-talk'); });
  await page.evaluate(() => officekitApplyMenuStats({ cpu: true, gpu: true, temperature: true, ram: true, storage: true, network: true, battery: true, bluetooth: true }));
  await expect.poll(() => page.evaluate(() => window.__officekitTestNativeCalls.length)).toBeGreaterThan(0);
  expect(await page.evaluate(() => window.__officekitTestNativeCalls)).toContainEqual({
    command: 'tray_stats_update',
    args: { text: '' },
  });
  await expect.poll(() => page.evaluate(() => window.__officekitTestNativeCalls.some(call => call.command === 'menu_drawers_update'))).toBe(true);
  const drawers = JSON.parse((await page.evaluate(() => window.__officekitTestNativeCalls)).find(call => call.command === 'menu_drawers_update').args.payload).drawers;
  expect(drawers.map(drawer => drawer.bar)).toEqual(['CPU 67%', 'GPU 12%', '59°', 'RAM 79%', 'SSD 3.4%', '↑40K ↓512K', 'Battery 76%']);
  expect(drawers.some(drawer => drawer.id === 'mic'), 'dictation is no longer a menu-bar item').toBe(false);
  expect(JSON.stringify(drawers)).not.toContain('dictated note');
  const network = drawers.find(drawer => drawer.id === 'net');
  expect(network.rings.map(ring => ring.label)).toEqual(['512K', '40K']);
  expect(network.details.map(line => line.label ?? line.heading)).toEqual(['Interface', 'Local address', 'Since start-up', 'Received', 'Sent']);
  expect(network.rows).toBeUndefined();
  expect(network.history.length).toBeGreaterThan(0);
  expect(network.history.every(value => value >= 0 && value <= 100)).toBe(true);
  expect(drawers.find(drawer => drawer.id === 'gpu').rings.map(ring => ring.label)).toEqual(['12%', '9%']);
  expect(drawers.find(drawer => drawer.id === 'battery').battery).toBe(true);
  expect(drawers.find(drawer => drawer.id === 'battery').details.map(line => line.label)).toEqual(['Power source', 'Time remaining', 'Cycle count', 'Condition']);
  const ram = drawers.find(drawer => drawer.id === 'ram');
  expect(ram.history.length).toBeGreaterThan(0);
  expect(ram.history.every(value => value === 78.9)).toBe(true);
  expect(ram.rings.map(ring => ring.label)).toEqual(['79%']);
  await page.evaluate(() => officekitApplyMenuStats({ cpu: false, ram: false, storage: false, network: false }));
  await expect.poll(() => page.evaluate(() => window.__officekitTestNativeCalls.some(call => call.command === 'menu_drawers_remove'))).toBe(true);
});

test('only the menu bar stats that are switched on get a drawer', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/system/metrics') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        cpu_percent: 10, memory_percent: 50, storage_percent: 20, volume_label: 'System volume',
        upload_bytes_per_second: 1024, download_bytes_per_second: 2048,
        captured_at: '2026-10-14T00:00:00+00:00', sample_age_ms: 0, reasons: {},
      }) });
    } else {
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
  });
  await page.goto('/');
  await page.evaluate(() => {
    window.__officekitTestNativeCalls = [];
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command === 'officekit_api_token') return 'test-token-with-32-characters-min';
      window.__officekitTestNativeCalls.push({ command, args });
    } } };
    switchTab('quick-stats');
    officekitApplyMenuStats({ cpu: true, ram: false, storage: false, network: true });
  });
  await expect.poll(() => page.evaluate(() => window.__officekitTestNativeCalls.some(call => call.command === 'menu_drawers_update'))).toBe(true);
  const call = (await page.evaluate(() => window.__officekitTestNativeCalls)).find(entry => entry.command === 'menu_drawers_update');
  expect(JSON.parse(call.args.payload).drawers.map(drawer => drawer.id)).toEqual(['cpu', 'net']);
});
