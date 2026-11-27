import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const catalogSource = fs.readFileSync('officekit/engines/engine_comms.py', 'utf8');
const lockBlock = html.match(/\/\/ ---- license lock: begin ----\n([\s\S]*?)\/\/ ---- license lock: end ----/)?.[1];
const functionSource = (name, prefix = '') => html.match(new RegExp(`${prefix}function ${name}\\([\\s\\S]*?\\n        \\}`))?.[0];
const destinations = html.match(/const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{[\s\S]*?\n        \}\);/)?.[0];
const registry = [...catalogSource.matchAll(/\{"id": "([a-z][a-z0-9_]+)", "name": "([^"]+)", "category": "([^"]+)"/g)]
  .map(([, id, name, category]) => ({ id, name, category }));
const FREE_CATEGORIES = ['Calculators', 'Unit Converters', 'Developer & Data'];
// Sit in a free category but are paid by id: Clipboard & Snippets Studio (owner decision 2026-10-22) and
// Global Launcher, whose native commands are all Paid.
const PAID_BY_ID = ['clipboard_manager', 'global_launcher'];

class FakeElement {
  constructor(id, log) {
    this.id = id;
    this.log = log;
    this.attrs = {};
    this.dataset = {};
    this.classes = new Set();
    this.innerHTML = '';
    this.textContent = '';
    this.className = '';
    this.value = '';
    this.chips = [];
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      contains: name => this.classes.has(name),
      toggle: (name, force) => {
        const on = force ?? !this.classes.has(name);
        if (on) this.classes.add(name); else this.classes.delete(name);
        return on;
      },
    };
  }
  get hidden() { return this.classes.has('hidden'); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  removeAttribute(name) { delete this.attrs[name]; }
  insertAdjacentHTML(_position, markup) { this.chips.push(markup); }
  querySelector(selector) { return selector === '[data-license-chip]' && this.chips.length ? { remove: () => { this.chips = []; } } : null; }
  focus() { this.log.focused.push(this.id); }
}

// Loads the real license-lock block (and, when asked, real handlers) into a vm with a small fake page.
function loadLockApp({ invoke, catalog = registry, loaded = true, extra = '', now = () => 0, timers } = {}) {
  assert.ok(lockBlock, 'the license-lock block exists between its markers');
  const log = { focused: [], native: [], fetched: [], updateChecks: 0, galleryRenders: 0 };
  const elements = new Map();
  const element = id => { if (!elements.has(id)) elements.set(id, new FakeElement(id, log)); return elements.get(id); };
  ['license-lock-notice', 'inapp-announcement-banner', 'announcement-banner-content', 'license-status-text', 'license-badge-btn',
    'update-check-button', 'update-badge-dot', 'license-modal', 'license-activation-status', 'license-email', 'license-key', 'search-modal',
    'license-details-modal', 'license-details-edition', 'license-details-devices', 'license-details-verified', 'license-details-offline',
    'license-details-activation', 'license-details-status', 'license-details-close'].forEach(element);
  element('license-modal').classes.add('hidden');
  element('license-details-modal').classes.add('hidden');
  element('search-modal').classes.add('hidden');
  const sidebar = ['home', 'tools', 'calculators', 'pdf', 'screenshot', 'dictate', 'workspace', 'quick-stats', 'clipboard', 'settings'].map(tab => {
    const button = new FakeElement(`sidebar-${tab}`, log);
    button.dataset.sidebarTab = tab;
    return button;
  });
  const homeButtons = ['screenshot_editor', 'loan_emi'].map(tool => {
    const button = new FakeElement(`home-${tool}`, log);
    button.dataset.licenseTool = tool;
    return button;
  });
  const listeners = {};
  const context = {
    // A Date whose clock is the test's `now`, so "Today" in the details dialog is deterministic.
    Object, Date: class extends Date { static now() { return now(); } },
    allToolsCache: loaded ? catalog.map(tool => ({ ...tool })) : [],
    allToolsLoaded: loaded,
    fetchToolSearchResults: async () => catalog.map(tool => ({ ...tool })),
    renderToolGallery: () => { log.galleryRenders += 1; },
    renderPersonalToolList: () => {},
    filterGlobalTools: async () => {},
    checkAppUpdates: async () => { log.updateChecks += 1; },
    document: {
      activeElement: null,
      visibilityState: 'visible',
      getElementById: id => elements.get(id) || null,
      querySelectorAll: selector => selector === '[data-sidebar-tab]' ? sidebar : selector === '[data-license-tool]' ? homeButtons : [],
    },
    window: {
      __TAURI__: invoke ? { core: { invoke: async (...args) => { log.native.push(args[0]); return invoke(...args); } } } : undefined,
      setTimeout: timers || ((callback) => { callback(); return 0; }),
      setInterval: (callback, ms) => { listeners.interval = { callback, ms }; return 1; },
      addEventListener: (name, handler) => { listeners[name] = handler; },
      fetch: async (...args) => { log.fetched.push(args[0]); return context.__response; },
    },
    Promise, JSON, Array,
    navigator: {},
    officekitExtensionShellTabs: new Set(),
    // Release-profile client (kept from main): the development profile allows every tool and tab, so these
    // tests exercise the licence guard alone.
    officekitReleaseProfile: { profile: 'development', tool_ids: [] },
    officekitReleaseAllowsTool: () => true,
    officekitReleaseAllowsTab: () => true,
    officekitIsPrivateBeta: () => false,
    officekitQueueStartupNavigation: () => false,
    officekitToolDestination: id => vm.runInContext('OFFICEKIT_TOOL_DESTINATIONS', context)[id],
  };
  context.window.fetch.bind = () => context.window.fetch;
  vm.createContext(context);
  vm.runInContext([
    functionSource('openLicenseModal'), functionSource('closeLicenseModal'), functionSource('clearLicenseEmailInvalid'), 'let officekitLicenseReturnFocus = null;',    lockBlock, extra,
  ].filter(Boolean).join('\n'), context);
  const state = () => vm.runInContext('officekitLicenseState', context);
  return { context, log, element, sidebar, homeButtons, listeners, state };
}

const COPY = {
  checking: ['Checking your license', '', ''],
  locked: ['Activate OfficeKit to use your tools', 'Calculators, Converters and Developer tools are free. Activate to unlock the rest.', 'Use the Activate button with the email you purchased with and the license key we sent you. Support stays available.'],
  expired: ['OfficeKit could not confirm your license', '', 'Calculators, Converters and Developer tools stay free. Support stays available.'],
  revoked: ['This license is no longer active', 'It was refunded or revoked. If that looks wrong, contact us with the Help button and we will sort it out.', 'Calculators, Converters and Developer tools stay free. Support stays available.'],
};

test('every lock state maps to its approved banner copy, tone and header badge word', () => {
  const words = { checking: 'Checking', locked: 'Activate', expired: 'Reactivate', revoked: 'Activate' };
  const tones = { checking: '', locked: '', expired: 'ok-lock-notice--warn', revoked: 'ok-lock-notice--err' };
  for (const state of Object.keys(COPY)) {
    const app = loadLockApp();
    app.context.officekitSetLicenseState(state);
    const slot = app.element('license-lock-notice').innerHTML;
    const [title, text, keep] = COPY[state];
    assert.ok(slot.includes(`>${title}</strong>`), `${state} title`);
    // Approved copy only: checking and expired carry no extra sentence (owner decision 2026-10-22).
    if (text) assert.ok(slot.includes(`>${text}</span>`), `${state} text`);
    else assert.ok(!slot.includes('ok-lock-notice__text'), `${state} has no extra sentence`);
    assert.ok(!slot.includes('works offline') && !slot.includes('Connect to the internet'), `${state} has no unapproved sentence`);
    assert.equal(slot.includes('ok-lock-notice__keep'), keep !== '', `${state} support line presence`);
    if (keep) assert.ok(slot.includes(`>${keep}</span>`), `${state} support line`);
    assert.ok(slot.includes(`class="ok-lock-notice ${tones[state]}"`), `${state} tone`);
    assert.equal(slot.includes('fa-spin'), state === 'checking', 'only the checking banner spins');
    assert.doesNotMatch(slot, /<button/, 'the banner has no button and no dismiss');
    assert.equal(app.element('license-status-text').textContent, words[state]);
    assert.equal(app.element('license-badge-btn').dataset.licenseState, state);
    assert.equal(app.element('update-check-button').hidden, true, `${state}: update button hidden`);
    assert.equal(app.element('update-badge-dot').hidden, true, `${state}: update dot hidden`);
    assert.equal(app.element('announcement-banner-content').hidden, true);
    assert.equal(app.element('inapp-announcement-banner').hidden, false);
  }
});

test('active restores the announcement, the update button and the Paid badge; a dismissed announcement stays dismissed', () => {
  const app = loadLockApp({ invoke: async command => command === 'license_status' ? { device_slots_used: 1, device_slots_allowed: 3 } : null });
  app.element('inapp-announcement-banner').classes.add('hidden');
  app.context.officekitSetLicenseState('revoked');
  assert.equal(app.element('inapp-announcement-banner').hidden, false, 'the notice shows even after a dismissal');
  app.context.officekitSetLicenseState('active');
  assert.equal(app.element('license-lock-notice').innerHTML, '');
  assert.equal(app.element('announcement-banner-content').hidden, false);
  assert.equal(app.element('inapp-announcement-banner').hidden, true, 'the owner dismissal is restored');
  assert.equal(app.element('update-check-button').hidden, false);
  assert.equal(app.element('license-status-text').textContent, 'Activated');
  assert.equal(app.element('license-badge-btn').attrs['aria-label'], 'OfficeKit activated. View license details.');
  assert.match(app.element('license-badge-btn').className, /emerald/);
});

const ACTIVE_STATUS = {
  activation_id: 'dGWuTkBfdEVWjS4Qh39fJA', edition: 'paid', features: [], device_slots_used: 1, device_slots_allowed: 3,
  last_checked_epoch: 1_795_171_937, offline_capable: true,
};
// 2026-11-20 11:12 UTC as the test clock, so the verified time is "Today" in any timezone near it.
const DETAILS_NOW = 1_795_172_000_000;

test('the activated chip never shows device counts; the details dialog does, read fresh on open', async () => {
  const app = loadLockApp({ now: () => DETAILS_NOW, invoke: async command => command === 'license_state' ? 'active' : ACTIVE_STATUS });
  await app.context.checkLicenseStatus();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.element('license-status-text').textContent, 'Activated');
  assert.ok(!app.log.native.includes('license_status'), 'the chip does not read the device counts');
  await app.context.openLicenseBadge();
  assert.ok(app.log.native.includes('license_status'));
  assert.equal(app.element('license-details-modal').hidden, false);
  assert.equal(app.element('license-modal').hidden, true, 'the activation form stays closed');
  assert.equal(app.element('license-details-edition').textContent, 'Paid');
  assert.equal(app.element('license-details-devices').textContent, '1 of 3 used');
  assert.match(app.element('license-details-verified').textContent, /^Today, /);
  assert.equal(app.element('license-details-offline').textContent, 'Yes');
  assert.equal(app.element('license-details-activation').textContent, 'dGWuTk…9fJA');
  assert.equal(app.element('license-details-status').textContent, '');
  assert.equal(app.log.focused.at(-1), 'license-details-close');
});

test('the header chip opens the activation form in every state except active', async () => {
  for (const state of ['checking', 'locked', 'expired', 'revoked']) {
    const app = loadLockApp({ invoke: async () => null });
    app.context.officekitSetLicenseState(state);
    await app.context.openLicenseBadge();
    assert.equal(app.element('license-modal').hidden, false, `${state} opens the activation form`);
    assert.equal(app.element('license-details-modal').hidden, true, `${state} does not open the details`);
  }
});

test('an earlier verification shows its date, and a stale or missing value never throws', () => {
  const app = loadLockApp({ now: () => DETAILS_NOW });
  const format = app.context.officekitFormatVerifiedTime;
  assert.match(format(1_795_171_937 - 3 * 86400), /2026/);
  assert.doesNotMatch(format(1_795_171_937 - 3 * 86400), /^Today/);
  for (const bad of [0, -5, 'x', null, undefined, 1.5]) assert.equal(format(bad), 'Not yet', String(bad));
});

test('details that cannot be read say so, show dashes and copy nothing', async () => {
  for (const invoke of [undefined, async () => { throw new Error('native failed'); }, async () => null]) {
    const app = loadLockApp({ invoke });
    app.context.officekitSetLicenseState('active');
    await app.context.openLicenseDetails();
    assert.equal(app.element('license-details-modal').hidden, false);
    assert.equal(app.element('license-details-devices').textContent, '—');
    assert.equal(app.element('license-details-status').textContent, 'License details are unavailable right now.');
    let copied = null;
    app.context.navigator = { clipboard: { writeText: async text => { copied = text; } } };
    await app.context.copyLicenseDetails();
    assert.equal(copied, null);
    assert.equal(app.element('license-details-status').textContent, 'Could not copy the license details.');
  }
});

test('Copy details copies every row with the full activation id, never an email or key; a blocked clipboard is reported', async () => {
  const app = loadLockApp({ now: () => DETAILS_NOW, invoke: async () => ACTIVE_STATUS });
  app.context.officekitSetLicenseState('active');
  await app.context.openLicenseDetails();
  let copied = '';
  app.context.navigator = { clipboard: { writeText: async text => { copied = text; } } };
  await app.context.copyLicenseDetails();
  assert.equal(app.element('license-details-status').textContent, 'License details copied.');
  const lines = copied.split('\n');
  assert.deepEqual(lines.slice(0, 4), ['OfficeKit license', 'Status: Activated', 'Edition: Paid', 'Devices: 1 of 3 used']);
  assert.ok(lines.includes('Works offline: Yes'));
  assert.ok(lines.includes('Activation ID: dGWuTkBfdEVWjS4Qh39fJA'));
  assert.ok(!/@|OK1\./.test(copied));
  app.context.navigator = { clipboard: { writeText: async () => { throw new Error('denied'); } } };
  await app.context.copyLicenseDetails();
  assert.equal(app.element('license-details-status').textContent, 'Could not copy the license details.');
  app.context.navigator = {};
  await app.context.copyLicenseDetails();
  assert.equal(app.element('license-details-status').textContent, 'Could not copy the license details.');
});

test('closing the details hides them, clears the message and returns focus to the chip', async () => {
  const app = loadLockApp({ invoke: async () => ACTIVE_STATUS });
  app.context.officekitSetLicenseState('active');
  const chip = app.element('license-badge-btn');
  app.context.document.activeElement = chip;
  await app.context.openLicenseDetails();
  app.element('license-details-status').textContent = 'License details copied.';
  app.context.closeLicenseDetails();
  assert.equal(app.element('license-details-modal').hidden, true);
  assert.equal(app.element('license-details-status').textContent, '');
  assert.equal(app.log.focused.at(-1), 'license-badge-btn');
  app.context.closeLicenseDetails();
  assert.equal(app.log.focused.filter(id => id === 'license-badge-btn').length, 1, 'closing twice does not steal focus again');
});

test('the details dialog stays within the three-button limit and the chip is wired to the state-aware opener', () => {
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const modal = html.slice(html.indexOf('id="license-details-modal"'), html.indexOf('<!-- Global Search Palette Modal'));
  const buttons = modal.match(/<button\b[^>]*>/g) || [];
  const counted = buttons.filter(tag => !/aria-label="Close"/.test(tag) && !/ok-text-link/.test(tag));
  assert.equal(counted.length, 2, 'Close and Copy details; the corner × is an icon control, Deactivate this Mac is a text link');
  assert.ok(counted.length <= 3);
  assert.match(modal, /id="license-deactivate-link"[^>]*data-officekit-click="openLicenseDeactivate\(\)"/);
  // The confirm step: Deactivate and Cancel, plus the corner ×. Same limit.
  const confirm = html.slice(html.indexOf('id="license-deactivate-modal"'), html.indexOf('id="license-details-modal"'));
  const confirmButtons = (confirm.match(/<button\b[^>]*>/g) || []).filter(tag => !/aria-label="Close"/.test(tag));
  assert.equal(confirmButtons.length, 2, 'Deactivate and Cancel');
  assert.match(confirm, /role="alertdialog"/);
  for (const action of ['openLicenseDeactivate', 'closeLicenseDeactivate', 'submitLicenseDeactivate']) {
    assert.ok(html.includes(`'${action}'`), `${action} is in the delegated allowlist`);
    assert.match(html, new RegExp(`function ${action}\\(`));
  }
  assert.match(html, /invoke\('license_deactivate', \{ email, licenseKey: key \}\)/);
  assert.match(html, /data-officekit-click="openLicenseBadge\(\)" id="license-badge-btn"/);
  assert.ok(!html.includes('devices last reported'), 'the chip no longer carries device counts');
});

test('free versus locked follows the catalog category names, for every tool id in the catalog', () => {
  const app = loadLockApp();
  const categories = new Set(registry.map(tool => tool.category));
  for (const category of FREE_CATEGORIES) assert.ok(categories.has(category), `the catalog still has the free category ${category}`);
  assert.deepEqual([...vm.runInContext('OFFICEKIT_FREE_TOOL_CATEGORIES', app.context)].sort(), [...FREE_CATEGORIES].sort());
  assert.ok(!categories.has('Developer Tools'), 'the gallery pill name "Developer Tools" is not a catalog category');
  assert.ok(registry.length > 40, 'catalog parsed');
  app.context.officekitSetLicenseState('locked');
  for (const tool of registry) {
    // Clipboard & Snippets Studio sits in a free category but is paid by owner decision (2026-10-22).
    const expected = FREE_CATEGORIES.includes(tool.category) && !PAID_BY_ID.includes(tool.id) ?'allow' : 'deny';
    assert.equal(app.context.officekitLicenseDecision({ toolId: tool.id }), expected, `${tool.id} (${tool.category})`);
  }
  assert.equal(app.context.officekitLicenseDecision({ toolId: 'loan_emi' }), 'allow');
  assert.equal(app.context.officekitLicenseDecision({ toolId: 'pdf_merge' }), 'deny');
});

test('no free tool lives on a tab the guard treats as paid, except the mixed converter tab', () => {
  assert.ok(destinations);
  const destination = vm.runInNewContext(`${destinations}; OFFICEKIT_TOOL_DESTINATIONS`, { Object });
  const app = loadLockApp();
  const paidTabs = vm.runInContext('OFFICEKIT_PAID_TABS', app.context);
  const freeTabs = new Set();
  for (const tool of registry.filter(item => FREE_CATEGORIES.includes(item.category) && !PAID_BY_ID.includes(item.id))) {
    const tab = destination[tool.id]?.tab;
    if (!tab) continue;
    freeTabs.add(tab);
    if (tab === 'converter') continue;
    assert.ok(!paidTabs.includes(tab), `${tool.id} opens on ${tab}, which would be locked`);
  }
  assert.deepEqual([...freeTabs].sort(), ['calculators', 'color', 'converter']);
  for (const tab of ['home', 'tools', 'favorites', 'recents', 'activity', 'history', 'calculators', 'color', 'pricing']) {
    assert.ok(!paidTabs.includes(tab), `${tab} stays open`);
  }
  for (const tab of ['clipboard', 'settings', 'pdf', 'screenshot', 'dictate', 'workspace', 'quick-stats', 'pii', 'password', 'network', 'system', 'statement']) {
    assert.ok(paidTabs.includes(tab), `${tab} is locked`);
  }
});

test('the guard allows when unlocked, opens the modal with the exact status line when locked, and names tabs and tools', () => {
  for (const state of ['active', 'none']) {
    const app = loadLockApp();
    app.context.officekitSetLicenseState(state);
    assert.equal(app.context.requireLicensedTool({ toolId: 'pdf_merge' }), true);
    assert.equal(app.context.requireLicensedTool({ tab: 'settings' }), true);
    assert.equal(app.element('license-modal').hidden, true);
  }
  for (const state of ['locked', 'expired', 'revoked']) {
    const app = loadLockApp();
    app.context.officekitSetLicenseState(state);
    assert.equal(app.context.requireLicensedTool({ toolId: 'pdf_merge' }), false);
    assert.equal(app.element('license-modal').hidden, false);
    assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Merge PDFs.');
    assert.deepEqual(app.log.focused, ['license-email']);
    assert.equal(app.context.requireLicensedTool({ tab: 'settings' }), false);
    assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Settings.');
    assert.equal(app.context.requireLicensedTool({ toolId: 'loan_emi' }), true);
    assert.equal(app.context.requireLicensedTool({ tab: 'calculators' }), true);
    assert.equal(app.context.requireLicensedTool({ tab: 'tools' }), true);
  }
});

test('opening the modal with a message fills the existing status line and closing returns focus once', () => {
  const app = loadLockApp();
  const opener = new FakeElement('opener', app.log);
  app.context.document.activeElement = opener;
  app.context.openLicenseModal('Activate OfficeKit to use Settings.');
  assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Settings.');
  app.context.closeLicenseModal();
  assert.deepEqual(app.log.focused, ['license-email', 'opener']);
  app.context.closeLicenseModal();
  assert.deepEqual(app.log.focused, ['license-email', 'opener'], 'a second close (Escape on a closed modal) does not steal focus');
  app.context.openLicenseModal();
  assert.equal(app.element('license-activation-status').textContent, '', 'no message leaves the line empty');
});

test('a tap while checking waits for the native result, then proceeds when active', async () => {
  const answers = ['checking', 'checking', 'active'];
  const app = loadLockApp({ invoke: async () => answers.shift() ?? 'active' });
  app.context.officekitSetLicenseState('checking');
  let proceeded = 0;
  assert.equal(app.context.requireLicensedTool({ toolId: 'pdf_merge' }, () => { proceeded += 1; }), false);
  assert.equal(app.element('license-modal').hidden, true, 'no modal while the check runs');
  assert.equal(proceeded, 0);
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(proceeded, 1);
  assert.equal(app.element('license-modal').hidden, true);
  assert.deepEqual(app.log.native.filter(command => command === 'license_state').length, 3);
});

test('a tap while checking opens the modal when the result is locked, and when the check never finishes', async () => {
  const locked = loadLockApp({ invoke: async () => 'locked' });
  locked.context.officekitSetLicenseState('checking');
  let proceeded = 0;
  locked.context.requireLicensedTool({ toolId: 'pdf_merge' }, () => { proceeded += 1; });
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(proceeded, 0);
  assert.equal(locked.element('license-activation-status').textContent, 'Activate OfficeKit to use Merge PDFs.');

  let clock = 0;
  const stuck = loadLockApp({ invoke: async () => 'checking', now: () => clock, timers: callback => { clock += 1_000; callback(); return 0; } });
  stuck.context.officekitSetLicenseState('checking');
  stuck.context.requireLicensedTool({ toolId: 'pdf_merge' }, () => { proceeded += 1; });
  for (let i = 0; i < 12; i += 1) await new Promise(resolve => setImmediate(resolve));
  assert.equal(proceeded, 0);
  assert.equal(stuck.element('license-activation-status').textContent, 'Activate OfficeKit to use Merge PDFs.');
});

test('while checking, free tools and shell tabs open at once and only locked tools wait', () => {
  let clock = 0;
  const app = loadLockApp({ invoke: async () => 'checking', now: () => { clock += 1_000; return clock; } });
  app.context.officekitSetLicenseState('checking');
  assert.equal(app.context.requireLicensedTool({ toolId: 'loan_emi' }), true);
  assert.equal(app.context.requireLicensedTool({ tab: 'tools' }), true);
  assert.equal(app.context.requireLicensedTool({ tab: 'settings' }), false);
});

test('a locked tool whose catalog is not loaded yet loads the catalog, then decides', async () => {
  const app = loadLockApp({ loaded: false, invoke: async () => 'locked' });
  app.context.officekitSetLicenseState('locked');
  let proceeded = 0;
  assert.equal(app.context.requireLicensedTool({ toolId: 'loan_emi' }, () => { proceeded += 1; }), false);
  for (let i = 0; i < 4; i += 1) await new Promise(resolve => setImmediate(resolve));
  assert.equal(proceeded, 1, 'a free tool proceeds once its category is known');
  assert.equal(app.element('license-modal').hidden, true);
  assert.equal(app.context.requireLicensedTool({ toolId: 'pdf_merge' }), false);
  assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Merge PDFs.');
});

test('an unreadable or unrecognised native answer never locks the interface and keeps a known state', async () => {
  for (const answer of [null, undefined, 'bogus', 42, { state: 'locked' }]) {
    const app = loadLockApp({ invoke: async () => answer });
    app.context.officekitSetLicenseState('checking');
    assert.equal(await app.context.officekitReadLicenseState(), 'none');
  }
  const failing = loadLockApp({ invoke: async () => { throw 'boom'; } });
  failing.context.officekitSetLicenseState('locked');
  assert.equal(await failing.context.officekitReadLicenseState(), 'locked', 'a failed read keeps the last known state');
  const web = loadLockApp();
  assert.equal(await web.context.officekitReadLicenseState(), 'none', 'no native bridge: not gated here');
  assert.equal(web.context.requireLicensedTool({ toolId: 'pdf_merge' }), true);
});

test('chips and labels: sidebar studios, Settings and Home buttons lock and unlock, and the free ones never lock', () => {
  const app = loadLockApp();
  app.context.officekitSetLicenseState('locked');
  const bySide = Object.fromEntries(app.sidebar.map(button => [button.dataset.sidebarTab, button]));
  for (const tab of ['pdf', 'screenshot', 'dictate', 'workspace', 'quick-stats', 'clipboard', 'settings']) {
    assert.equal(bySide[tab].chips.length, 1, `${tab} chip`);
    assert.match(bySide[tab].chips[0], /Locked<\/span>/);
    assert.match(bySide[tab].attrs['aria-label'], /, locked: activation needed$/);
  }
  assert.equal(bySide.settings.attrs['aria-label'], 'Settings, locked: activation needed');
  assert.equal(bySide.clipboard.attrs['aria-label'], 'Open Clipboard & Snippets Studio, locked: activation needed');
  for (const tab of ['home', 'tools', 'calculators']) {
    assert.equal(bySide[tab].chips.length, 0, `${tab} has no chip`);
    assert.equal('aria-label' in bySide[tab].attrs, false);
  }
  assert.equal(app.homeButtons[0].chips.length, 1, 'Screenshot Editor quick start is locked');
  assert.equal(app.homeButtons[1].chips.length, 0, 'Loan EMI quick start is free');
  assert.equal(app.log.galleryRenders > 0, true, 'the gallery re-renders when the state changes');
  app.context.officekitSetLicenseState('active');
  for (const button of [...app.sidebar, ...app.homeButtons]) {
    assert.equal(button.chips.length, 0);
    assert.equal('aria-label' in button.attrs, false);
  }
});

test('updates: the silent launch check is skipped while locked and runs once on activation', async () => {
  const states = ['locked', 'locked', 'active'];
  const app = loadLockApp({ invoke: async command => command === 'license_state' ? states.shift() : null });
  await app.context.officekitInitLicenseLock();
  assert.equal(app.log.updateChecks, 0, 'no launch check while locked');
  assert.equal(app.state(), 'locked');
  await app.context.officekitReadLicenseState();
  assert.equal(app.log.updateChecks, 0);
  await app.context.officekitReadLicenseState();
  assert.equal(app.state(), 'active');
  assert.equal(app.log.updateChecks, 1, 'the launch check runs on activation');
  await app.context.officekitReadLicenseState();
  assert.equal(app.log.updateChecks, 1, 'and only once');
});

test('updates: an active launch checks straight away, and a web build with no bridge still checks', async () => {
  const active = loadLockApp({ invoke: async () => 'active' });
  await active.context.officekitInitLicenseLock();
  assert.equal(active.log.updateChecks, 1);
  const web = loadLockApp();
  await web.context.officekitInitLicenseLock();
  assert.equal(web.log.updateChecks, 1);
  assert.equal(web.element('update-check-button').hidden, false);
});

test('checkAppUpdates does nothing while the app is not active and fetches once it is', async () => {
  const source = functionSource('checkAppUpdates', 'async ');
  assert.ok(source);
  const app = loadLockApp({ extra: source });
  const requests = [];
  app.context.officekitApiUrl = path => path;
  // The dialog itself is covered by update-dialog-ui.test.mjs; here only the licence gate and the request matter.
  for (const name of ['officekitUpdateShowChecking', 'officekitUpdateShowUnavailable', 'officekitUpdateShowCurrent', 'officekitUpdateShowAvailable', 'officekitUpdateShowStatus', 'officekitUpdateStartPolling']) app.context[name] = () => {};
  app.context.officekitUpdateInvoke = async () => ({ state: 'idle' });
  app.context.fetch = async path => { requests.push(path); return { ok: true, json: async () => ({ status: 'ok', update_available: false }) }; };
  for (const state of ['checking', 'locked', 'expired', 'revoked']) {
    app.context.officekitSetLicenseState(state);
    await app.context.checkAppUpdates(true);
    await app.context.checkAppUpdates(false);
  }
  assert.deepEqual(requests, [], 'the real function never reaches the network while the app is not active');
  app.context.officekitSetLicenseState('active');
  await app.context.checkAppUpdates(true);
  assert.deepEqual(requests, ['/api/system/check-update']);
});

test('the lock state is re-read on a named timer constant under the native tick, on focus and after activation', async () => {
  const poll = Number(html.match(/const OFFICEKIT_LICENSE_POLL_MS = ([\d_]+);/)?.[1].replaceAll('_', ''));
  assert.ok(poll > 0 && poll < 15 * 60_000, 'faster than the 15-minute native tick');
  const app = loadLockApp({ invoke: async () => 'locked' });
  await app.context.officekitInitLicenseLock();
  assert.equal(app.listeners.interval.ms, poll);
  const before = app.log.native.length;
  app.listeners.interval.callback();
  app.context.document.visibilityState = 'hidden';
  app.listeners.interval.callback();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.log.native.length, before + 1, 'the timer reads once while visible and skips while hidden');
  app.listeners.focus();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.log.native.length, before + 2, 'focus re-reads');
  assert.match(html, /await invoke\('license_activate', \{ email, licenseKey: key \}\);[\s\S]*?await checkLicenseStatus\(\);/);
});

test('license_required rejections and 403 responses are recognised and re-read the state quietly', async () => {
  const app = loadLockApp({ invoke: async () => 'locked' });
  for (const error of ['license_required', new Error('license_required'), { code: 'license_required' }, { error: { code: 'license_required' } }]) {
    assert.equal(app.context.officekitIsLicenseRequiredError(error), true);
  }
  for (const error of ['other', new Error('nope'), null, undefined, 403, { code: 'x' }, {}]) {
    assert.equal(app.context.officekitIsLicenseRequiredError(error), false);
  }
  const originalFetch = app.context.window.fetch;
  app.context.officekitInstallLicenseRequiredHandling();
  let prevented = 0;
  app.listeners.unhandledrejection({ reason: 'license_required', preventDefault: () => { prevented += 1; } });
  app.listeners.unhandledrejection({ reason: new Error('unrelated'), preventDefault: () => { prevented += 10; } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(prevented, 1, 'only the licence rejection is swallowed');
  assert.equal(app.log.native.filter(command => command === 'license_state').length, 1);

  const respond = (status, body) => { app.context.__response = { status, clone: () => ({ json: async () => body }) }; };
  respond(403, { error: { code: 'license_required' } });
  assert.equal((await app.context.window.fetch('/api/x')).status, 403, 'the response is passed through untouched');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.log.native.filter(command => command === 'license_state').length, 2);
  respond(403, { detail: 'forbidden' });
  await app.context.window.fetch('/api/x');
  respond(200, { error: { code: 'license_required' } });
  await app.context.window.fetch('/api/x');
  respond(403, null);
  await app.context.window.fetch('/api/x');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.log.native.filter(command => command === 'license_state').length, 2, 'other 403s and 200s do not re-read');
  assert.ok(originalFetch);
});

test('real entry points call the guard: switchTab, selectSearchTool and openPdfTool hold locked destinations', () => {
  const app = loadLockApp();
  app.context.officekitSetLicenseState('locked');
  const visible = new Set();
  const tabs = ['tools', 'settings', 'calculators', 'pdf', 'screenshot', 'workspace'].map(id => [`tab-${id}`, { classList: { add: () => visible.delete(id), remove: () => visible.add(id) } }]);
  app.context.document.getElementById = id => Object.fromEntries(tabs)[id] || app.element(id);
  app.context.document.querySelectorAll = selector => selector === '[data-sidebar-tab]' ? [] : [];
  app.context.officekitSetSidebarCollapsed = () => {};
  app.context.loadToolGallery = () => {};
  vm.runInContext(functionSource('switchTab'), app.context);
  assert.equal(app.context.switchTab('settings'), false);
  assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Settings.');
  assert.deepEqual([...visible], [], 'the locked tab was not shown');
  assert.equal(app.context.switchTab('pdf'), false);
  assert.equal(app.context.switchTab('screenshot'), false);
  assert.equal(app.context.switchTab('workspace'), false);
  assert.equal(app.context.switchTab('converter'), false);
  assert.notEqual(app.context.switchTab('calculators'), false);
  assert.deepEqual([...visible], ['calculators']);
  assert.notEqual(app.context.switchTab('tools'), false);
  assert.notEqual(app.context.switchTab('converter', true), false, 'a destination already checked per tool is not blocked again');
  assert.equal(app.context.switchTab('converter'), false);

  // selectSearchTool: held (null, not false) for a locked tool, normal for a free one.
  const calls = { tabs: [], recent: [], closes: 0, calculators: [] };
  Object.assign(app.context, {
    closeGlobalSearchModal: () => { calls.closes += 1; },
    officekitRecordStore: { recordRecent: id => { calls.recent.push(id); return { ok: true }; } },
    switchCalc: calc => calls.calculators.push(calc),
    setConverterMode: () => {},
    setAudioToolView: () => {},
  });
  app.context.switchTab = (...args) => calls.tabs.push(args);
  vm.runInContext(`${destinations}\n${functionSource('selectSearchTool')}`, app.context);
  app.element('license-modal').classes.add('hidden');
  assert.equal(app.context.selectSearchTool('pdf_merge'), null);
  assert.equal(app.element('license-activation-status').textContent, 'Activate OfficeKit to use Merge PDFs.');
  assert.deepEqual(calls.tabs, []);
  assert.deepEqual(calls.recent, [], 'a held tool is not recorded as recent');
  assert.equal(calls.closes, 1, 'the search palette closes so the modal is not hidden behind it');
  assert.equal(app.context.selectSearchTool('screenshot'), null, 'the screenshot alias is guarded too');
  assert.equal(app.context.selectSearchTool('unknown_tool'), false, 'unknown stays false so the launcher still says not available');
  assert.equal(app.context.selectSearchTool('loan_emi'), true);
  assert.deepEqual(calls.tabs, [['calculators', true]]);
  assert.deepEqual(calls.recent, ['loan_emi']);
  assert.equal(app.context.selectSearchTool('data_converter'), true);
  assert.deepEqual(calls.tabs.at(-1), ['converter', true]);
  assert.equal(app.context.selectSearchTool('crypto_hashes'), null, 'a paid tool on the mixed converter tab is held');

  // openPdfTool holds before touching any state.
  const pdfCopy = html.match(/const PDF_TOOL_COPY = Object\.freeze\(\{[\s\S]*?\n        \}\);/)?.[0];
  assert.ok(pdfCopy);
  vm.runInContext(`${pdfCopy}\nlet activePdfTool = 'none';\n${functionSource('openPdfTool')}`, app.context);
  assert.equal(app.context.openPdfTool('merge'), false);
  assert.equal(vm.runInContext('activePdfTool', app.context), 'none');
  app.context.officekitSetLicenseState('active');
  app.context.openPdfTool = () => true;
  assert.equal(app.context.selectSearchTool('pdf_merge'), true, 'unlocked: the same tool opens');
});

test('cards and search results show the chip and the locked label only for locked tools, and a busy flag while checking', () => {
  const card = functionSource('toolCardMarkup');
  const results = html.match(/function renderSearchResults\(tools\) \{[\s\S]*?\n        \}(?=\n\n        let toolGalleryView)/)?.[0];
  assert.ok(card && results && destinations);
  const container = { className: '', innerHTML: '', querySelectorAll: () => [] };
  const app = loadLockApp();
  const base = app.context;
  Object.assign(base, {
    toolGalleryView: 'gallery',
    officekitRecordStore: { read: () => ({ state: { favorites: [] } }) },
    officekitEscapeHtml: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  });
  const lookup = base.document.getElementById;
  base.document.getElementById = id => id === 'search-results-list' ? container : lookup(id);
  vm.runInContext(`${destinations}\n${card}\n${results}`, base);
  const paid = { id: 'pdf_merge', name: 'Merge PDFs', category: 'PDF & Documents', icon: 'fa-file-pdf', desc: 'Combine' };
  const free = { id: 'loan_emi', name: 'Loan EMI', category: 'Calculators', icon: 'fa-calculator', desc: 'Pay' };
  const unavailable = { id: 'not_routed', name: 'Soon', category: 'Images', icon: 'fa-image', desc: '' };

  for (const compact of [false, true]) {
    base.officekitSetLicenseState('locked');
    const lockedCard = base.toolCardMarkup(paid, compact);
    assert.match(lockedCard, /<button[^>]*data-open-tool="pdf_merge"[^>]*aria-label="Open Merge PDFs, locked: activation needed"/);
    assert.doesNotMatch(lockedCard, /<button[^>]*data-open-tool="pdf_merge"[^>]*\sdisabled[\s>]/, 'locked cards stay enabled');
    assert.equal((lockedCard.match(/data-license-chip/g) || []).length, 1);
    assert.match(lockedCard, /class="ok-lock-chip"[^>]*><i class="fa-solid fa-lock" aria-hidden="true"><\/i>Locked<\/span>/);
    const freeCard = base.toolCardMarkup(free, compact);
    assert.doesNotMatch(freeCard, /data-license-chip|locked:/);
    assert.match(freeCard, /aria-label="Open Loan EMI"/);
    assert.doesNotMatch(base.toolCardMarkup(unavailable, compact), /data-license-chip|aria-busy/);
    base.officekitSetLicenseState('checking');
    const busy = base.toolCardMarkup(paid, compact);
    assert.match(busy, /<article aria-busy="true"/);
    assert.doesNotMatch(busy, /data-license-chip|locked:/);
    assert.match(busy, /aria-label="Open Merge PDFs"/);
    assert.doesNotMatch(base.toolCardMarkup(free, compact), /aria-busy/);
    base.officekitSetLicenseState('active');
    assert.doesNotMatch(base.toolCardMarkup(paid, compact), /data-license-chip|aria-busy|locked:/);
  }

  base.officekitSetLicenseState('revoked');
  base.renderSearchResults([paid, free]);
  const rows = container.innerHTML.split('data-tool-id=').slice(1);
  assert.match(rows[0], /aria-label="Open Merge PDFs, locked: activation needed"/);
  assert.match(rows[0], /data-license-chip/);
  assert.match(rows[0], /tabindex="0" aria-disabled="false"/);
  assert.doesNotMatch(rows[1], /data-license-chip|locked:/);
  base.officekitSetLicenseState('checking');
  base.renderSearchResults([paid]);
  assert.match(container.innerHTML, /aria-busy="true"/);
  assert.doesNotMatch(container.innerHTML, /data-license-chip/);
});

// ARCH-7: sub-navigation inside the mixed converter tab goes through the same guard.
function loadConverterApp() {
  const extra = `let converterMode = 'convert'; let selectedGenericFile = null;
    const clearGenericImagePreview = () => {}; const officekitGetConversionPlan = () => ({ kind: 'other' }); const updateGenericImagePreview = async () => {};
    ${functionSource('setConverterMode')}`;
  const app = loadLockApp({ extra });
  // Every element the real function reads, so a field added to setConverterMode later does not need a test edit.
  const ids = new Set([...functionSource('setConverterMode').matchAll(/getElementById\('([^']+)'\)/g)].map(match => match[1]));
  for (const id of [...ids, 'image-resize-input', 'image-metadata-input']) app.element(id);
  return { app, mode: () => vm.runInContext('converterMode', app.context) };
}

test('Open Media Toolkit and the other paid converter modes are guarded; the free modes are not', () => {
  assert.match(html, /id="open-media-toolkit"[^>]*data-officekit-click="setConverterMode\('media_toolkit'\)"/, 'the button still calls setConverterMode, the guarded choke point');
  assert.match(functionSource('setConverterMode'), /requireLicensedTool\(\{ converterMode: mode \}/);
  for (const state of ['locked', 'expired', 'revoked']) {
    const { app, mode } = loadConverterApp();
    app.context.officekitSetLicenseState(state);
    for (const [paidMode, name] of [['media_toolkit', 'Media Toolkit'], ['image_resize', 'Image Resize'], ['image_metadata', 'Image Metadata Stripper']]) {
      app.context.document.getElementById('license-modal').classList.add('hidden');
      assert.equal(app.context.setConverterMode(paidMode), false, `${state}: ${paidMode} is held`);
      assert.equal(mode(), 'convert', `${state}: ${paidMode} did not switch the mode`);
      assert.equal(app.element('license-modal').hidden, false, `${state}: the activation modal opens for ${paidMode}`);
      assert.equal(app.element('license-activation-status').textContent, `Activate OfficeKit to use ${name}.`);
    }
    assert.equal(app.element('media-toolkit-panel').classes.has('hidden'), false, 'no panel was toggled by the held calls');
    for (const freeMode of ['convert', 'url_codec', 'developer_tools']) {
      app.context.setConverterMode(freeMode);
      assert.equal(mode(), freeMode, `${state}: ${freeMode} stays open`);
    }
    assert.equal(app.element('media-toolkit-panel').classes.has('hidden'), true, 'the Media Toolkit panel stays hidden');
  }
  const { app, mode } = loadConverterApp();
  app.context.officekitSetLicenseState('active');
  app.context.setConverterMode('media_toolkit');
  assert.equal(mode(), 'media_toolkit', 'an activated app opens Media Toolkit');
  assert.equal(app.element('media-toolkit-panel').classes.has('hidden'), false);
});

// CR-2 (JS side): the startup native initialisers run again once the state becomes active.
test('window snap, screenshot shortcut and media drop are re-applied once on the move to active', async () => {
  const extra = `var calls = [];
    var applyWindowSnapEdgeSetting = async () => { calls.push('snap'); };
    var officekitReconfigureScreenshotShortcut = async () => { calls.push('shortcut'); };
    var Event = class { constructor(type) { this.type = type; } };
    window.dispatchEvent = event => calls.push(event.type);`;
  const app = loadLockApp({ extra });
  const calls = () => [...vm.runInContext('calls', app.context)];
  app.context.officekitSetLicenseState('checking');
  app.context.officekitSetLicenseState('locked');
  assert.deepEqual(calls(), [], 'nothing runs while checking or locked');
  app.context.officekitSetLicenseState('active');
  assert.deepEqual(calls(), ['snap', 'shortcut', 'officekit-license-active']);
  app.context.officekitSetLicenseState('active');
  assert.equal(calls().length, 3, 'a repeated active read does not run them again');
  app.context.officekitSetLicenseState('expired');
  app.context.officekitSetLicenseState('active');
  assert.equal(calls().length, 6, 'a later re-activation runs them once more');
  assert.match(fs.readFileSync('assets/officekit-media.js', 'utf8'), /addEventListener\('officekit-license-active', \(\) => \{ syncMediaDrop\(\); \}\)/, 'the media drop target listens for it');
});

test('license-state-changed moves the state; a shell without the event is tolerated', async () => {
  const handlers = {};
  const app = loadLockApp({ invoke: async () => 'checking' });
  app.context.window.__TAURI__.event = { listen: async (name, handler) => { handlers[name] = handler; } };
  await app.context.officekitInitLicenseLock();
  assert.equal(typeof handlers['license-state-changed'], 'function');
  handlers['license-state-changed']({ payload: 'locked' });
  assert.equal(app.state(), 'locked');
  handlers['license-state-changed']({ payload: 'active' });
  assert.equal(app.state(), 'active');
  handlers['license-state-changed']({ payload: 'bogus' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(OFFICEKIT_STATES_OK(app.state()), true, 'an unknown payload falls back to a re-read');
  for (const event of [undefined, { listen: 'nope' }, { listen: async () => { throw new Error('unknown event'); } }]) {
    const tolerant = loadLockApp({ invoke: async () => 'locked' });
    tolerant.context.window.__TAURI__.event = event;
    await assert.doesNotReject(() => tolerant.context.officekitInitLicenseLock());
    assert.equal(tolerant.state(), 'locked');
  }
});
const OFFICEKIT_STATES_OK = state => ['checking', 'locked', 'active', 'expired', 'revoked'].includes(state);

test('a licence rejection never reaches the window-snap or screenshot status text', () => {
  const snap = functionSource('setWindowSnapEdgeEnabled', 'async ');
  assert.match(snap, /officekitIsLicenseRequiredError\(error\)/);
  assert.match(snap, /Edge snapping turns on once OfficeKit is activated\./);
  const shortcut = html.match(/officekitReconfigureScreenshotShortcut = configure;/);
  assert.ok(shortcut);
  assert.match(html, /if \(officekitIsLicenseRequiredError\(error\)\) \{ void officekitReadLicenseState\(\); return; \}\n\s+officekitScreenshotStatus/);
});

// UX-1 / owner decision: the first-run tour keeps every step while locked but never calls the guarded switchTab for a paid tab.
function loadTour(decide) {
  const store = new Map();
  const element = () => {
    const children = new Map();
    const el = {
      style: {}, className: '', textContent: '', innerHTML: '', hidden: false, checked: false, disabled: false, dataset: {},
      classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
      setAttribute() {}, addEventListener() {}, scrollIntoView() {}, append() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 20, right: 100, bottom: 20 }),
      querySelector: selector => { if (!children.has(selector)) children.set(selector, element()); return children.get(selector); },
      querySelectorAll: () => [],
    };
    return el;
  };
  const switched = [];
  const context = {
    window: { innerWidth: 1280, innerHeight: 900, addEventListener() {}, switchTab: tab => { switched.push(tab); }, officekitLicenseDecision: decide },
    document: { body: { append() {} }, createElement: element, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, readyState: 'loading' },
    localStorage: { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    setTimeout: () => 0,
  };
  context.globalThis = context.window;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('assets/officekit-tour.js', 'utf8'), context);
  return { tour: context.window.OfficeKitTour, switched };
}

test('App Tour while locked keeps all seven steps and never switches to a paid tab (no modal over the tour)', () => {
  const PAID_STEP_TABS = ['dictate', 'clipboard', 'workspace'];
  const locked = loadTour(({ tab }) => PAID_STEP_TABS.includes(tab) ? 'deny' : 'allow');
  assert.equal(locked.tour.getSteps().length, 7, 'no step is dropped');
  assert.deepEqual([...locked.tour.getSteps()].filter(step => step.tab && PAID_STEP_TABS.includes(step.tab)).map(step => step.tab), PAID_STEP_TABS);
  for (let index = 0; index < 7; index += 1) locked.tour.start(index);
  locked.tour.close();
  for (const tab of PAID_STEP_TABS) assert.ok(!locked.switched.includes(tab), `${tab} was not switched to`);
  assert.ok(locked.switched.includes('tools') && locked.switched.includes('activity'), 'free steps still switch tabs');
  // The state is still being checked: a paid tab is 'pending', which also must not switch.
  const checking = loadTour(({ tab }) => PAID_STEP_TABS.includes(tab) ? 'pending' : 'allow');
  for (let index = 0; index < 7; index += 1) checking.tour.start(index);
  assert.deepEqual(checking.switched.filter(tab => PAID_STEP_TABS.includes(tab)), []);
  // Unlocked, or a build without the guard: every step switches as before.
  for (const decide of [() => 'allow', undefined]) {
    const open = loadTour(decide);
    for (let index = 0; index < 7; index += 1) open.tour.start(index);
    for (const tab of PAID_STEP_TABS) assert.ok(open.switched.includes(tab), `${tab} is switched to when unlocked`);
  }
});

test('the markup carries the live region, the update button id and no new controls in the banner slot', () => {
  const slot = html.match(/<div id="license-lock-notice"[^>]*><\/div>/)?.[0];
  assert.ok(slot, 'the notice slot exists, empty');
  assert.match(slot, /role="status"/);
  assert.match(slot, /aria-live="polite"/);
  assert.ok(html.indexOf('id="license-lock-notice"') > html.indexOf('id="inapp-announcement-banner"'), 'the notice lives inside the announcement slot');
  assert.ok(html.indexOf('id="license-lock-notice"') < html.indexOf('id="announcement-banner-content"'));
  assert.match(html, /<button id="update-check-button" data-officekit-click="checkAppUpdates\(true\)"/);
  assert.match(html, /id="update-badge-dot"/);
  assert.equal((html.match(/data-license-tool="/g) || []).length, 4, 'the four static Home quick-start buttons are marked');
  assert.match(html, /void officekitInitLicenseLock\(\);/);
  assert.doesNotMatch(html, /\n\s+checkAppUpdates\(false\);/, 'startup no longer runs the update check unconditionally');
  const css = fs.readFileSync('assets/officekit.input.css', 'utf8');
  for (const selector of ['.ok-lock-chip', '.ok-lock-notice__glyph', '.ok-lock-notice--warn', '.ok-lock-notice--err', '#license-badge-btn[data-license-state="checking"]']) {
    assert.ok(css.includes(selector), `${selector} is styled`);
  }
  assert.match(css, /prefers-reduced-motion: reduce\) \{\s*\.ok-lock-notice \.fa-spin \{ animation: none; \}/);
  assert.match(css, /#app-sidebar\.ok-collapsed \.ok-lock-chip \{ display: none; \}/);
});
