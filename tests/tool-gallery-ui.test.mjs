import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const catalog = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const searchFetcher = html.match(/async function fetchToolSearchResults\(query = ''\) \{[\s\S]*?\n        \}/)?.[0];

test('the default app shell provides Tools, Favorites and merged Activity navigation with a real gallery', () => {
  for (const route of ['tools', 'favorites', 'activity']) {
    assert.match(html, new RegExp(`data-sidebar-tab="${route}"`));
    assert.match(html, new RegExp(`id="tab-${route}"`));
  }
  assert.doesNotMatch(html, /data-sidebar-tab="history"/);
  assert.match(html, /id="officekit-activity-history"/);
  assert.match(html, /id="tool-gallery-search"/);
  assert.match(html, /id="tool-gallery-search" autofocus/);
  assert.match(html, /id="tool-gallery-home"/);
  assert.match(html, /id="tool-gallery-recent"/);
  assert.match(html, /id="tool-gallery-favorites"/);
  assert.match(html, /data-sidebar-tab="home"/);
  assert.match(html, /data-sidebar-tab="recents"/);
  assert.match(html, /Recent tools <span[^>]*>· last five/);
  assert.match(html, /renderPersonalToolList\('recents', 'tool-gallery-recent'\)/);
  assert.match(html, /renderPersonalToolList\('favorites', 'tool-gallery-favorites'\)/);
  assert.match(html, /requestAnimationFrame\(\(\) => document\.getElementById\('tool-gallery-search'\)\?\.focus\(\{ preventScroll: true \}\)\)/);
  assert.doesNotMatch(html, /id="sidebar-categories"/);
  assert.match(html, /id="tool-gallery-category"/);
  assert.match(html, /data-gallery-view="gallery"/);
  assert.match(html, /data-gallery-view="list"/);
  assert.match(html, /<section id="tab-tools"[^>]*>/);
  assert.match(html, /id="officekit-brand-mark"[^>]*aria-label="OfficeKit monogram"/);
  const brandLockup = html.slice(html.indexOf('id="officekit-brand-mark"') - 180, html.indexOf('<!-- Search & Actions Bar -->'));
  assert.match(brandLockup, /bg-\[#4f46e5\]/);
  assert.match(brandLockup, /viewBox="0 0 1024 1024"/);
  assert.match(brandLockup, /h-\[38px\] w-\[38px\]/);
  assert.match(brandLockup, /class="h-\[34px\] w-\[34px\] max-sm:h-\[30px\] max-sm:w-\[30px\]"/);
  assert.match(brandLockup, /text-slate-800">OfficeKit<\/span>/);
  assert.doesNotMatch(brandLockup, /bg-gradient|Desktop v1\.0|shadow-/i);
  assert.doesNotMatch(html.slice(0, html.indexOf('<!-- In-App Announcement')), /fa-briefcase/);
  assert.match(html, /<body[^>]*>/);
});

test('category navigation selects the gallery filter; the sidebar no longer lists categories', () => {
  const openSource = html.match(/function openToolCategory\(category\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(openSource, 'category navigation action exists');
  assert.doesNotMatch(html, /renderSidebarCategories/);
  const context = {
    OFFICEKIT_TOOL_DESTINATIONS: { pdf_merge: {}, system_info: {}, network_dns: {} },
    officekitToolDestination: id => context.OFFICEKIT_TOOL_DESTINATIONS[id],
    allToolsCache: [
      { id: 'pdf_merge', category: 'PDF & Documents' },
      { id: 'system_info', category: 'System' },
      { id: 'network_dns', category: 'Network' },
    ],
    officekitReleaseAllowsTool: id => id !== 'network_dns',
  };

  const effects = [];
  const categoryFilter = { value: '' };
  const search = { value: 'old query' };
  context.document = { getElementById: id => id === 'tool-gallery-category' ? categoryFilter : id === 'tool-gallery-search' ? search : null };
  context.switchTab = tab => effects.push(tab);
  context.renderToolGallery = () => effects.push('render');
  vm.runInNewContext(openSource, context);
  assert.equal(context.openToolCategory('System'), true);
  assert.equal(categoryFilter.value, 'System');
  assert.equal(search.value, '');
  assert.deepEqual(effects, ['tools', 'render']);
});

test('developer tools share the Developer & Data category in search and gallery results', () => {
  const developerTools = catalog.split('\n').filter(line => /"id": "(?:data_converter|devtools_format|url_codec|jwt_inspector)"/.test(line));
  assert.equal(developerTools.length, 4);
  assert.ok(developerTools.every(line => /"category": "Developer & Data"/.test(line)));
  assert.doesNotMatch(catalog, /"category": "Developer Tools"/);
});

test('sidebar navigation merges history into Activity without hiding legacy tool destinations', () => {
  const switchSource = html.match(/function switchTab\(tab\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(switchSource, 'shared tab switcher exists');
  const visible = new Set();
  const selected = new Map();
  const ids = ['tools', 'favorites', 'history', 'activity', 'statement', 'converter', 'calculators', 'unlocker', 'dictate', 'pricing'];
  const elements = new Map(ids.map(id => [`tab-${id}`, {
    classList: { add: () => visible.delete(id), remove: () => visible.add(id) },
  }]));
  const buttons = ['tools', 'favorites', 'activity'].map(id => ({
    dataset: { sidebarTab: id },
    setAttribute: (name, value) => selected.set(id, value),
    removeAttribute: name => selected.delete(id),
  }));
  const context = {
    officekitReleaseProfile: { profile: 'development', tool_ids: [] },
    officekitReleaseAllowsTab: () => true,
    officekitSetSidebarCollapsed: () => {},
    officekitExtensionShellTabs: new Set(),
    document: {
      getElementById: id => elements.get(id) || null,
      querySelectorAll: selector => selector === '[data-sidebar-tab]' ? buttons : [],
    },
  };
  vm.runInNewContext(switchSource, context);

  context.switchTab('history');
  assert.deepEqual([...visible], ['activity']);
  assert.equal(selected.get('activity'), 'page');
  context.switchTab('favorites');
  assert.deepEqual([...visible], ['favorites']);
  assert.equal(selected.get('favorites'), 'page');
  context.switchTab('converter');
  assert.deepEqual([...visible], ['converter']);
  assert.equal(selected.get('tools'), 'page');
});

test('gallery records only available tool opens and exposes store failures without blocking navigation', () => {
  const selector = html.match(/function selectSearchTool\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(selector, 'stable-ID tool selector exists');
  const calls = { recent: [], tabs: [], errors: [] };
  const context = {
    officekitReleaseProfile: { profile: 'development', tool_ids: [] },
    OFFICEKIT_TOOL_DESTINATIONS: { loan_emi: { tab: 'calculators', calculator: 'emi' } },
    officekitReleaseAllowsTool: () => true,
    closeGlobalSearchModal: () => {},
    officekitRecordStore: { recordRecent: id => { calls.recent.push(id); return { ok: false, code: 'storage-unavailable' }; } },
    showRecordStoreError: code => calls.errors.push(code),
    switchTab: tab => calls.tabs.push(tab),
    switchCalc: () => {},
    window: {},
    document: { getElementById: () => ({ focus: () => {} }) },
  };
  context.officekitToolDestination = id => context.OFFICEKIT_TOOL_DESTINATIONS[id];
  vm.runInNewContext(selector, context);

  assert.equal(context.selectSearchTool('loan_emi'), true);
  assert.deepEqual(calls.recent, ['loan_emi']);
  assert.deepEqual(calls.tabs, ['calculators']);
  assert.deepEqual(calls.errors, ['storage-unavailable']);
  assert.equal(context.selectSearchTool('unknown_tool'), false);
  assert.deepEqual(calls.recent, ['loan_emi']);
});

test('gallery cards open directly from their content without a redundant Open tool action', () => {
  const cardSource = html.match(/function toolCardMarkup\(tool, compact = false\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(cardSource, 'shared gallery and personal-list card renderer exists');
  const context = {
    Object,
    OFFICEKIT_TOOL_DESTINATIONS: { loan_emi: { tab: 'calculators' } },
    officekitToolDestination: id => context.OFFICEKIT_TOOL_DESTINATIONS[id],
    officekitRecordStore: { read: () => ({ state: { favorites: [] } }) },
    toolGalleryView: 'gallery',
    officekitEscapeHtml: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;'),
  };
  vm.runInNewContext(cardSource, context);
  const markup = context.toolCardMarkup({
    id: 'loan_emi', name: 'Loan & EMI', category: 'Calculators', desc: 'Estimate a payment', icon: 'fa-calculator',
  });

  assert.match(markup, /<button[^>]*data-open-tool="loan_emi"[^>]*aria-label="Open Loan &amp; EMI"/);
  assert.match(markup, /data-card-tool="loan_emi"/);
  assert.match(markup, /<button[^>]*data-open-tool="loan_emi"[^>]*>Open Tool →<\/button>/);
  assert.doesNotMatch(markup, />Open tool</);
  assert.match(markup, /data-favorite-tool="loan_emi"/);
});

test('attachToolCardActions connects Open Tool button and card clicks to selectSearchTool while preserving favorite toggling', () => {
  const attachSource = html.match(/function attachToolCardActions\(container\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(attachSource, 'attachToolCardActions exists');

  const openedTools = [];
  const fakeSelect = id => openedTools.push(id);

  const makeClosest = el => sel => {
    if (sel.includes('favorite') && el === favBtn) return favBtn;
    if (sel.includes('open-tool') && el === openBtn) return openBtn;
    if (sel.includes('button') && (el === openBtn || el === favBtn)) return el;
    return null;
  };

  const openBtn = {
    dataset: { openTool: 'pii_redaction' },
    listeners: {},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    click() {
      let stopped = false;
      const event = { stopPropagation: () => { stopped = true; }, target: this };
      this.listeners['click']?.(event);
      if (!stopped) card.click(this);
    }
  };
  openBtn.closest = makeClosest(openBtn);

  const favBtn = {
    dataset: { favoriteTool: 'pii_redaction' },
    listeners: {},
    attributes: { 'aria-pressed': 'false' },
    classList: { toggle() {} },
    getAttribute(name) { return this.attributes[name] ?? null; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() {},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    click() {
      let stopped = false;
      const event = { stopPropagation: () => { stopped = true; }, target: this };
      this.listeners['click']?.(event);
      if (!stopped) card.click(this);
    }
  };
  favBtn.closest = makeClosest(favBtn);

  const card = {
    dataset: { cardTool: 'pii_redaction' },
    listeners: {},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    click(target = this) {
      const event = {
        target,
        closest: target.closest || makeClosest(target),
      };
      this.listeners['click']?.(event);
    }
  };
  card.closest = makeClosest(card);

  const container = {
    querySelectorAll(selector) {
      if (selector === '[data-open-tool]') return [openBtn];
      if (selector === '[data-card-tool]') return [card];
      if (selector === '[data-favorite-tool]') return [favBtn];
      return [];
    }
  };

  const context = {
    selectSearchTool: fakeSelect,
    officekitRecordStore: {
      toggleFavorite: () => ({ ok: true }),
      read: () => ({ state: { favorites: [] } })
    },
    renderToolGallery: () => {},
    renderPersonalToolList: () => {},
    document: { getElementById: () => null }
  };
  vm.runInNewContext(attachSource, context);
  context.attachToolCardActions(container);

  // 1. Clicking Open Tool button triggers selectSearchTool
  openBtn.click();
  assert.deepEqual(openedTools, ['pii_redaction']);

  // 2. Clicking card container triggers selectSearchTool
  card.click();
  assert.deepEqual(openedTools, ['pii_redaction', 'pii_redaction']);

  // 3. Clicking favorite button does NOT trigger selectSearchTool
  favBtn.click();
  assert.deepEqual(openedTools, ['pii_redaction', 'pii_redaction']);
});

test('gallery search results never replace the full catalogue used by Favorites and History', async () => {
  const loader = html.match(/async function loadToolGallery\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(loader, 'gallery loader exists');
  const search = { value: '' };
  const category = { value: '', innerHTML: '' };
  const status = { textContent: '' };
  const results = { replaceChildren() {} };
  const elements = new Map([
    ['tool-gallery-search', search],
    ['tool-gallery-category', category],
    ['tool-gallery-status', status],
    ['tool-gallery-results', results],
  ]);
  const full = [{ id: 'pdf_merge', category: 'PDF' }, { id: 'loan_emi', category: 'Calculators' }];
  const calls = [];
  const context = {
    allToolsCache: [],
    allToolsLoaded: false,
    galleryToolsCache: [],
    toolGalleryRequest: 0,
    officekitEscapeHtml: value => String(value),
    renderToolGallery: () => {},
    document: { getElementById: id => elements.get(id) },
    officekitStartupFetch: async path => {
      calls.push(path);
      const tools = path.endsWith('q=') ? full : [full[0]];
      return { ok: true, json: async () => ({ tools }) };
    },
  };
  vm.runInNewContext(`${searchFetcher}\n${loader}`, context);

  await context.loadToolGallery();
  search.value = 'pdf';
  await context.loadToolGallery();

  assert.deepEqual(context.allToolsCache.map(tool => tool.id), ['pdf_merge', 'loan_emi']);
  assert.deepEqual(context.galleryToolsCache.map(tool => tool.id), ['pdf_merge']);
  assert.deepEqual(calls, ['/api/tools/search?q=', '/api/tools/search?q=pdf']);
});

test('gallery status uses singular grammar for one search result', async () => {
  const loader = html.match(/async function loadToolGallery\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(loader);
  const status = { textContent: '' };
  const elements = new Map([
    ['tool-gallery-search', { value: 'PDF to CSV' }],
    ['tool-gallery-category', { value: '', innerHTML: '' }],
    ['tool-gallery-status', status],
    ['tool-gallery-results', { replaceChildren() {} }],
  ]);
  const context = {
    allToolsCache: [], allToolsLoaded: false, galleryToolsCache: [], toolGalleryRequest: 0,
    officekitEscapeHtml: value => String(value), renderToolGallery() {}, renderSidebarCategories() {}, renderPersonalToolList() {},
    document: { getElementById: id => elements.get(id) },
    officekitStartupFetch: async () => ({ ok: true, json: async () => ({ tools: [{ id: 'bank_statement' }] }) }),
  };
  vm.runInNewContext(`${searchFetcher}\n${loader}`, context);
  await context.loadToolGallery();
  assert.equal(status.textContent, '1 tool');
});

test('gallery replaces its permanent loading state with the existing recovery message after an API timeout', async () => {
  const loader = html.match(/async function loadToolGallery\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(loader);
  const status = { textContent: '' };
  let cleared = false;
  const elements = new Map([
    ['tool-gallery-search', { value: '' }],
    ['tool-gallery-category', { value: '', innerHTML: '' }],
    ['tool-gallery-status', status],
    ['tool-gallery-results', { replaceChildren: () => { cleared = true; } }],
  ]);
  const context = {
    allToolsCache: [], allToolsLoaded: false, galleryToolsCache: [], toolGalleryRequest: 0,
    officekitStartupFetch: async () => { throw new Error('OfficeKit local API request timed out.'); },
    document: { getElementById: id => elements.get(id) },
  };
  vm.runInNewContext(loader, context);

  await context.loadToolGallery();

  assert.equal(status.textContent, 'The tool catalog could not be loaded. Check that OfficeKit is ready, then try again.');
  assert.equal(cleared, true, 'stale results are cleared when the catalogue cannot load');
});

test('local-record storage failures remain visible on Favorites and Activity screens', () => {
  const noticeSource = html.match(/function showRecordStoreError\(code\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(noticeSource);
  const classes = new Set(['hidden']);
  const notice = { classList: { remove: name => classes.delete(name), add: name => classes.add(name) } };
  const noticeText = { textContent: '' };
  const galleryStatus = { textContent: '' };
  const context = { document: { getElementById: id => id === 'record-store-notice' ? notice : id === 'record-store-notice-text' ? noticeText : id === 'tool-gallery-status' ? galleryStatus : null } };
  vm.runInNewContext(noticeSource, context);
  context.showRecordStoreError('storage-unavailable');
  assert.match(noticeText.textContent, /storage-unavailable/);
  assert.equal(classes.has('hidden'), false);
});

test('file utility search destinations open their selected local workspace task', () => {
  const destinations = html.match(/const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{([\s\S]*?)\n        \}\);/)?.[1];
  assert.ok(destinations);
  for (const [toolId, action] of [['batch_rename', 'rename'], ['dup_finder', 'duplicates'], ['storage_analyzer', 'storage'], ['file_split_join', 'split_join']]) {
    assert.match(destinations, new RegExp(`${toolId}: \\{ tab: 'workspace', fileTool: '${action}' \\}`));
  }
  const selector = html.match(/function selectSearchTool\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(selector);
  const calls = { workspace: [] };
  const context = {
    officekitReleaseProfile: { profile: 'development', tool_ids: [] },
    OFFICEKIT_TOOL_DESTINATIONS: { batch_rename: { tab: 'workspace', fileTool: 'rename' } },
    officekitReleaseAllowsTool: () => true,
    officekitRecordStore: { recordRecent: () => ({ ok: true }) },
    closeGlobalSearchModal: () => {},
    switchTab: tab => calls.workspace.push(tab),
    openFilesystemTool: tool => calls.workspace.push(tool),
    window: {},
    document: { getElementById: () => null },
  };
  context.officekitToolDestination = id => context.OFFICEKIT_TOOL_DESTINATIONS[id];
  vm.runInNewContext(selector, context);
  assert.equal(context.selectSearchTool('batch_rename'), true);
  assert.deepEqual(calls.workspace, ['workspace', 'rename']);
});

test('approved workspace flow provides local-copy, preview/report, download and clear controls', () => {
  assert.match(html, /<section id="tab-workspace"[^>]*>/);
  for (const id of ['workspace-files-input', 'workspace-import-button', 'workspace-tool-title', 'workspace-run-button', 'workspace-download-button', 'workspace-clear-button', 'workspace-status', 'workspace-results']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /webkitdirectory/);
  assert.match(html, /officekitImportFiles\(/);
  assert.match(html, /officekitCreateRenameArtifact\(/);
  assert.match(html, /officekitDuplicateReport\(/);
  assert.match(html, /officekitStorageReport\(/);
  assert.match(html, /officekitClearWorkspace\(/);
  assert.match(html, /Download outputs before clearing temporary storage/i);
});

test('switching file tools keeps a generated rename output available until the workspace is cleared', () => {
  const switcher = html.match(/function openFilesystemTool\(action\) \{[\s\S]*?\n        \}/)?.[0];
  const runner = html.match(/async function runFilesystemTool\(\) \{[\s\S]*?\n        \}/)?.[0];
  const creator = html.match(/async function createWorkspaceArtifact\(\) \{[\s\S]*?\n        \}/)?.[0];
  const clearer = html.match(/async function clearFilesystemWorkspace\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(switcher && runner && creator && clearer);
  assert.match(switcher, /classList\.toggle\('hidden', !fileWorkspaceArtifactId\)/);
  assert.match(runner, /classList\.toggle\('hidden', !fileWorkspaceArtifactId\)/);
  assert.match(creator, /if \(!fileWorkspaceId \|\| !fileWorkspaceRenameRequest \|\| fileWorkspaceArtifactId\) return/);
  assert.match(clearer, /fileWorkspaceArtifactId = null/);
  assert.doesNotMatch(switcher, /fileWorkspaceArtifactId = null/);
});
