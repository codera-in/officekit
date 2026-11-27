import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'assets/officekit-workspace.js'), 'utf8');
const swift = fs.readFileSync(path.join(root, 'src-tauri/macos-drawers.swift'), 'utf8');

function extract(source, pattern, label) {
  const match = source.match(pattern);
  assert.ok(match?.[0], `${label} exists`);
  return match[0];
}

const validation = extract(js, /function officekitNetworkHealthResponseIsValid\([\s\S]*?\n}/, 'health response validation');
const presentation = extract(js, /function officekitNetworkHealthPresentation\([\s\S]*?\n}/, 'native menu result presentation');
const check = extract(js, /async function officekitRunMenuNetworkHealthCheck\([\s\S]*?\n}/, 'native menu network check action');
const quickAccess = extract(js, /async function officekitBindQuickAccess\([\s\S]*?\n}/, 'native menu event listener');
const rust = fs.readFileSync(path.join(root, 'src-tauri/src/workspace_native.rs'), 'utf8');

function client(result, ok = true) {
  let calls = 0;
  let publishes = 0;
  let quickAccessHandler = null;
  const context = {
    window: { __TAURI__: { event: { listen: async (eventName, handler) => {
      if (eventName === 'quick-access') quickAccessHandler = handler;
      else assert.equal(eventName, 'quick-access-recording');
    } } } },
    fetch: async (url, options) => {
      calls += 1;
      assert.equal(url, '/api/network/health');
      assert.equal(options.method, 'POST');
      assert.equal(options.cache, 'no-store');
      return { ok, json: async () => result };
    },
    officekitApiUrl: value => value,
    officekitNetworkHealthResponseIsValid: value => context.validate(value),
    officekitNetworkHealthPresentation: value => context.present(value),
    officekitPublishMenuDrawers: async () => { publishes += 1; },
    switchTab() {}, officekitRefreshQuickStats() {},
    Date, Number, Math, Array, Error,
  };
  vm.runInNewContext(`
    let officekitNetworkCheckBusy = false;
    let officekitMenuNetworkHealth = null;
    ${validation}\n${presentation}\n${check}\n${quickAccess}
    const checkRun = officekitRunMenuNetworkHealthCheck;
    officekitRunMenuNetworkHealthCheck = (...args) => { globalThis.checkPromise = checkRun(...args); };
    globalThis.validate = officekitNetworkHealthResponseIsValid;
    globalThis.present = officekitNetworkHealthPresentation;
    globalThis.run = officekitRunMenuNetworkHealthCheck;
    globalThis.bind = officekitBindQuickAccess;
    globalThis.health = () => officekitMenuNetworkHealth;
    globalThis.busy = () => officekitNetworkCheckBusy;
  `, context);
  return { context, dispatch: event => quickAccessHandler(event), calls: () => calls, publishes: () => publishes };
}

const wired = {
  status: 'healthy', headline: 'Connection looks healthy', detail: 'The gateway and internet responded normally.', link_type: 'wired', interface: 'Ethernet 2',
  router_median_ms: 3.2, router_loss_percent: 0, internet_median_ms: 18.5, internet_loss_percent: 0, checked_at: '2026-10-27T10:00:00Z',
};

test('native menu check is opt-in and publishes wired LAN results', async () => {
  const app = client(wired);
  await app.context.bind();
  assert.equal(app.calls(), 0, 'registering the native action sends no diagnostic request');
  await app.dispatch({ payload: { action: 'network-check' } });
  await app.context.checkPromise;
  assert.equal(app.calls(), 1, 'one native event sends exactly one explicit health request');
  assert.equal(app.publishes(), 2, 'the native drawer shows checking and final results');
  assert.equal(app.context.health().connection, 'Wired · Ethernet 2');
  assert.equal(app.context.health().router, 'Fast · 3.2 ms');
  assert.equal(app.context.health().internet, '18.5 ms');
  assert.equal(app.context.busy(), false);
});

test('slow router and ISP diagnoses use distinct tones and retain measurement details', () => {
  const app = client({
    ...wired, status: 'internet_slow', headline: 'Slow: ISP, not Wi-Fi', detail: 'The gateway is quick, while internet responses are slow or missing.',
    link_type: 'wifi', interface: 'en1', router_median_ms: 4, internet_median_ms: 186,
  });
  const health = app.context.present({
    ...wired, status: 'internet_slow', headline: 'Slow: ISP, not Wi-Fi', detail: 'The gateway is quick, while internet responses are slow or missing.',
    link_type: 'wifi', interface: 'en1', router_median_ms: 4, internet_median_ms: 186,
  });
  assert.equal(health.tone, 'orange');
  assert.equal(health.routerTone, 'teal');
  assert.equal(health.internetTone, 'red');
  assert.equal(health.connection, 'Wi-Fi · en1');
  assert.match(health.router, /Fast · 4 ms/);
  assert.match(health.internet, /186 ms/);
});

test('incomplete router readings stay neutral instead of claiming a fast router', () => {
  const app = client({
    ...wired, status: 'incomplete', headline: 'Measurement incomplete', detail: 'Not enough internet replies to compare router and internet timing.',
    router_median_ms: 92, router_loss_percent: 0, internet_median_ms: null,
  });
  const health = app.context.present({
    ...wired, status: 'incomplete', headline: 'Measurement incomplete', detail: 'Not enough internet replies to compare router and internet timing.',
    router_median_ms: 92, router_loss_percent: 0, internet_median_ms: null,
  });
  assert.equal(health.router, '92 ms');
  assert.equal(health.routerTone, 'grey');
});

test('failed checks clear previous readings and show a bounded unavailable state', async () => {
  const app = client({ detail: 'Route unavailable.' }, false);
  app.context.run();
  await app.context.checkPromise;
  assert.equal(app.context.health().headline, 'Network check unavailable');
  assert.equal(app.context.health().router, 'Unavailable');
  assert.equal(app.context.health().internet, 'Unavailable');
  assert.equal(app.context.health().tone, 'red');
  assert.ok(app.context.health().detail.length <= 120);
});

test('malformed successful responses are rejected', async () => {
  const app = client({ ...wired, router_median_ms: 'fast' });
  app.context.run();
  await app.context.checkPromise;
  assert.equal(app.context.health().headline, 'Network check unavailable');
});

test('opening the Network drawer starts the check unless one finished in the last minute', () => {
  assert.match(js, /OFFICEKIT_NETWORK_CHECK_MAX_AGE_MS = 60 \* 1000/);
  assert.match(js, /networkCheckAuto: !officekitNetworkCheckBusy && Date\.now\(\) - officekitNetworkCheckedAt > OFFICEKIT_NETWORK_CHECK_MAX_AGE_MS/);
  assert.match(js, /officekitNetworkCheckedAt = Date\.now\(\)/);
  assert.match(swift, /model\.networkCheckAuto, !model\.networkCheckBusy[\s\S]*?networkCheckCallback\?\(\)/);
  assert.match(swift, /"Run again"/);
});

test('the Network footer lines up Run again and Network settings, with the speed test as a plain link below', () => {
  assert.match(swift, /let pair = NSView\(\)[\s\S]*?for button in \[primary, settings\][\s\S]*?primary\.widthAnchor\.constraint\(equalTo: settings\.widthAnchor\)\.isActive = true/);
  assert.match(swift, /speedTest\.isBordered = false/);
  assert.match(swift, /if let speedTestLink, activeQuitRow == nil \{ footerButtons\.append\(speedTestLink\) \}/);
  assert.match(swift, /settings\.setAccessibilityLabel\(settingsTitle\)/);
});

test('diagnostics live in the native Mac popover, not the app header', () => {
  assert.doesNotMatch(html, /officekit-network-popover|officekit-network-trigger/);
  assert.match(js, /action === 'network-check'/);
  assert.match(js, /networkHealth: officekitMenuNetworkHealth, networkCheck: true/);
  assert.match(swift, /Cloudflare Speed Test/);
  assert.match(swift, /openNetworkCheck|runNetworkCheck/);
  assert.match(swift, /lineChart: model\.id == "net"/);
  const networkButton = extract(swift, /let primary = PointerButton\([\s\S]*?\n            \)/, 'network primary button wiring');
  assert.match(networkButton, /target: self/);
  assert.match(networkButton, /action: model\.networkCheckAction \? #selector\(runNetworkCheck\(_:\)\)/);
  const networkAction = extract(swift, /@objc private func runNetworkCheck\(_ sender: NSButton\) \{[\s\S]*?\n    \}/, 'native check action');
  assert.match(networkAction, /networkCheckCallback\?\(\)/);
  const swiftCallbackSetter = extract(swift, /@_cdecl\("officekit_drawers_set_network_check_callback"\)[\s\S]*?\n\}/, 'native callback setter');
  assert.match(swiftCallbackSetter, /MenuDrawerController\.shared\.networkCheckCallback = callback/);
  assert.match(swift, /primary\.refusesFirstResponder = !model\.networkCheckAction/);
  assert.match(swift, /primary\.focusRingType = model\.networkCheckAction \? \.default : \.none/);
  assert.match(swift, /speedTest\.refusesFirstResponder = false/);
  assert.match(swift, /setAccessibilityLabel\("Open Cloudflare Speed Test in your browser"\)/);
  assert.match(swift, /settings\.refusesFirstResponder = false/);
  assert.match(rust, /fn drawer_network_check_event\(\)[\s\S]*?json!\(\{"action":"network-check"\}\)/);
  assert.match(rust, /fn officekit_drawers_set_network_check_callback\(callback: extern "C" fn\(\)\)/);
  assert.match(swift, /@_cdecl\("officekit_drawers_set_network_check_callback"\)/);
  const registerDrawers = extract(rust, /pub fn menu_drawers_update\([\s\S]*?\n\}/, 'native callback registration');
  assert.match(registerDrawers, /officekit_drawers_set_network_check_callback\(on_menu_drawer_network_check\)/);
  const rustCallback = extract(rust, /extern "C" fn on_menu_drawer_network_check\(\) \{[\s\S]*?\n\}/, 'native event callback');
  assert.match(rustCallback, /app\.emit\("quick-access", drawer_network_check_event\(\)\)/);
});
