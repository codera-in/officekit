import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workspace = fs.readFileSync(path.join(root, 'assets/officekit-workspace.js'), 'utf8');
const drawers = fs.readFileSync(path.join(root, 'src-tauri/macos-drawers.swift'), 'utf8');
const native = fs.readFileSync(path.join(root, 'src-tauri/src/workspace_native.rs'), 'utf8');
const refresh = workspace.match(/async function officekitRefreshMenuDrawersAfterQuit\(\)[\s\S]*?\n}/)?.[0];

test('CPU and RAM have an Applications tab and a History and details tab', () => {
  assert.match(drawers, /let collapsibleStats = model\.id == "cpu" \|\| model\.id == "ram"/);
  assert.match(drawers, /labels: \["Applications", "History and details"\], trackingMode: \.selectOne/);
  assert.match(drawers, /showHistoryTab = statsHistoryTab\.contains\(model\.id\)\s*if showHistoryTab \{\s*appendUsageHistoryAndDetails\(model, to: stack\)/);
  assert.ok(drawers.indexOf('if collapsibleStats {') < drawers.indexOf('for row in (showHistoryTab ? [] : model.rows)'));
  assert.match(drawers, /private func selectStatsTab\(_ sender: NSSegmentedControl\)[\s\S]*?refreshOpenPopover\(animated: true\)/);
  assert.match(drawers, /NSWorkspace\.shared\.accessibilityDisplayShouldReduceMotion/);
  assert.match(drawers, /popover\.contentViewController = DrawerHostController\(content:/, 'one host controller keeps the popover in place');
  assert.match(drawers, /let eased = 1 - pow\(1 - progress, 4\)[\s\S]*?popover\?\.contentSize = NSSize/, 'the height is stepped every frame on an ease-out curve');
  assert.match(drawers, /hasPrefix\("drawer-tabs-"\)[\s\S]*?newBody\.forEach \{ \$0\.alphaValue = 0 \}/, 'only the body under the tab bar fades; the header, rings and tabs never blink');
  assert.match(drawers, /if !animated, focusIdentifier == nil, pendingQuitPid == nil, host\.update\(with: content, in: popover\) \{\s*return/, 'routine refreshes update the shown views in place');
  for (const view of ['DrawerRingView', 'DrawerHistoryView', 'DrawerCoresView', 'DrawerSegmentBar']) {
    assert.match(drawers, new RegExp(`private final class ${view}: NSView, DrawerAdoptable`), `${view} takes new values in place`);
  }
  assert.match(drawers, /if model\.networkCheckAction \|\| pane != nil \{[\s\S]*?let primary = PointerButton\(/, 'the bottom primary button exists only for a network check or a settings pane');
  assert.doesNotMatch(drawers, /"Open Activity Monitor"/, 'Activity Monitor has its header link; no duplicate button at the bottom');
  assert.match(drawers, /if activeQuitRow == nil, !footerButtons\.isEmpty \{/, 'a drawer with no footer buttons has no empty footer');
  assert.equal(drawers.match(/layerContentsRedrawPolicy = \.onSetNeedsDisplay/g)?.length, 4, 'every drawn view is layer-backed so a refresh never flashes');
  assert.match(drawers, /next\.fractions\.count == grown\.count \+ 1 && Array\(next\.fractions\.dropLast\(\)\) == grown/, 'a new sample slides the bars instead of repainting the chart');
  assert.match(drawers, /was\.tag == now\.tag, was\.action == now\.action, was\.target === now\.target/, 'a Quit button is only kept for the same process');
  assert.match(drawers, /if !animated, focusIdentifier == nil, host\.isAnimating \{ return \}/, 'data refreshes do not cut a transition short');
  assert.match(drawers, /NSEvent\.pressedMouseButtons != 0 \{ return \}/, 'a refresh never rebuilds buttons mid-press');
  assert.match(drawers, /private func resetDrawerState\(\)[\s\S]*?statsHistoryTab\.removeAll\(\)/);
  assert.match(drawers, /private func closePopover\(\)[\s\S]*?resetDrawerState\(\)/);
  assert.match(drawers, /func popoverDidClose\([\s\S]*?resetDrawerState\(\)/);
  assert.match(drawers, /func popoverDidClose\([\s\S]*?closed !== current \{ return \}[\s\S]*?resetDrawerState\(\)/, 'a late close of the old drawer must not clear the newly opened one');
  assert.match(drawers, /private func quitRow\(_ sender: NSButton\)[\s\S]*?pendingQuitPid = pid[\s\S]*?refreshOpenPopover\(focusIdentifier: "drawer-quit-cancel"\)/);
  assert.doesNotMatch(drawers.match(/@objc private func quitRow\(_ sender: NSButton\)[\s\S]*?\n    }/)?.[0] || '', /closePopover\(/);
  assert.match(drawers, /quit\.refusesFirstResponder = false[\s\S]*?quit\.focusRingType = \.default/);
  assert.match(drawers, /window\.makeFirstResponder\(target\)/);
  assert.match(drawers, /NSAccessibility\.post\(element: content, notification: \.announcementRequested/);
  assert.match(drawers, /if lastQuitAnnouncement != announcement \{[\s\S]*?lastQuitAnnouncement = announcement/);
  assert.match(drawers, /card\.setAccessibilityRole\(\.group\)[\s\S]*?card\.setAccessibilityLabel\("Quit confirmation for/);
  assert.match(drawers, /private final class DrawerFocusableStackView: NSStackView \{\s*override var acceptsFirstResponder: Bool \{ true \}/);
  const prompt = drawers.match(/private func processQuitPrompt\(for row: MenuDrawerRow\) -> NSView \{[\s\S]*?\n    }/)?.[0] || '';
  assert.match(prompt, /let card = DrawerFocusableStackView\(\)/);
  assert.match(prompt, /card\.identifier = NSUserInterfaceItemIdentifier\("drawer-quit-status"\)[\s\S]*?card\.focusRingType = \.default/);
  assert.match(drawers, /quitInProgress = true[\s\S]*?refreshOpenPopover\(focusIdentifier: "drawer-quit-status"\)/);
  const update = drawers.match(/func update\(_ newModels: \[MenuDrawerModel\]\)[\s\S]*?\n    }/)?.[0] || '';
  assert.match(update, /refreshOpenPopover\(\)/);
  assert.doesNotMatch(update, /contentViewController = makeViewController/);
});

test('Quit requires the in-drawer confirmation and a successful response refreshes rows', async () => {
  const handler = workspace.match(/async function officekitRunMenuDrawerQuit\(pid\)[\s\S]*?\n}/)?.[0];
  assert.ok(handler, 'drawer quit handler exists');
  let requests = 0;
  let refreshes = 0;
  let postedBody;
  const context = {
    Number, Map, Error, fetch: async (_url, options) => {
      requests += 1;
      postedBody = JSON.parse(options.body);
      return { ok: true, json: async () => ({ success: true }) };
    },
    officekitApiUrl: value => value,
    officekitDrawerNames: new Map([[812, 'Editor']]),
    officekitLatestMetrics: { cpu_percent: 5 },
    officekitUpdateDrawers: async () => { refreshes += 1; },
    officekitRefreshQuickStats: async () => { refreshes += 1; },
  };
  const sandbox = vm.createContext(context);
  vm.runInContext(`let officekitMenuQuitFeedback = null; let officekitMenuQuitBusy = false; ${refresh}\n${handler}\nglobalThis.run = officekitRunMenuDrawerQuit; globalThis.state = () => officekitMenuQuitFeedback;`, sandbox);
  assert.equal(requests, 0, 'loading the handler does not terminate a process');
  await sandbox.run(812);
  assert.equal(requests, 1);
  assert.deepEqual(postedBody, { pid: 812, force: false });
  assert.equal(refreshes, 2, 'drawer rows refresh before and after the request');
  assert.equal(context.state(), null, 'success clears inline quit feedback');
});

test('Quit failures stay bounded in the drawer and never show/focus the app window', async () => {
  const handler = workspace.match(/async function officekitRunMenuDrawerQuit\(pid\)[\s\S]*?\n}/)?.[0];
  let feedback;
  const context = {
    Number, Map, Error, fetch: async () => ({ ok: false, json: async () => ({ detail: 'Permission denied'.repeat(20) }) }),
    officekitApiUrl: value => value,
    officekitDrawerNames: new Map([[812, 'Editor']]),
    officekitLatestMetrics: { cpu_percent: 5 },
    officekitUpdateDrawers: async () => { feedback = context.state(); },
    officekitRefreshQuickStats: async () => {},
  };
  const sandbox = vm.createContext(context);
  vm.runInContext(`let officekitMenuQuitFeedback = null; let officekitMenuQuitBusy = false; ${refresh}\n${handler}\nglobalThis.run = officekitRunMenuDrawerQuit; globalThis.state = () => officekitMenuQuitFeedback;`, sandbox);
  await sandbox.run(812);
  assert.equal(sandbox.state().state, 'error');
  assert.ok(sandbox.state().message.length <= 120);
  assert.match(native.match(/extern "C" fn on_menu_drawer_quit\(pid: i32\)[\s\S]*?\n}/)?.[0] || '', /app\.emit\("quick-access"/);
  assert.doesNotMatch(native.match(/extern "C" fn on_menu_drawer_quit\(pid: i32\)[\s\S]*?\n}/)?.[0] || '', /window\.show\(\)|set_focus\(/);
  assert.ok(feedback, 'error feedback is published into the native drawer model');
});

test('Cancel clears the inline prompt without terminating the app or closing OfficeKit', async () => {
  const cancelHandler = workspace.match(/async function officekitCancelMenuDrawerQuit\(pid\)[\s\S]*?\n}/)?.[0];
  assert.ok(cancelHandler, 'drawer quit cancel handler exists');
  let requests = 0;
  let refreshes = 0;
  const context = {
    Number, Map, Error, fetch: async () => { requests += 1; return { ok: true, json: async () => ({ success: true }) }; },
    officekitApiUrl: value => value,
    officekitDrawerNames: new Map(),
    officekitLatestMetrics: { cpu_percent: 5 },
    officekitUpdateDrawers: async () => { refreshes += 1; },
    officekitRefreshQuickStats: async () => { refreshes += 1; },
  };
  const sandbox = vm.createContext(context);
  vm.runInContext(`let officekitMenuQuitFeedback = {pid: 812, state: 'error', message: 'Permission denied'}; let officekitMenuQuitBusy = false; ${refresh}\n${cancelHandler}\nglobalThis.cancel = officekitCancelMenuDrawerQuit; globalThis.state = () => officekitMenuQuitFeedback;`, sandbox);
  await sandbox.cancel(812);
  assert.equal(requests, 0, 'cancelling sends no process termination request');
  assert.equal(refreshes, 1, 'cancellation refreshes the drawer in place');
  assert.equal(sandbox.state(), null, 'cancellation clears inline feedback');

  const cancelAction = drawers.match(/@objc private func cancelQuit\(_ sender: NSButton\)[\s\S]*?\n    }/)?.[0] || '';
  assert.match(cancelAction, /clearPendingQuit\(\)/);
  assert.match(cancelAction, /refreshOpenPopover\(focusIdentifier: pid\.map/);
  assert.match(cancelAction, /quitCancelCallback\?\(pid\)/);
  assert.doesNotMatch(cancelAction, /quitCallback\?\(/);
});
