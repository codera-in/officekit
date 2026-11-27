import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { loadToolCatalog, parseSliceDestinations, SLICE_KEYS, sliceAssetPath } from '../scripts/tool-catalog.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');
const destinations = html.match(/const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{[\s\S]*?\n        \}\);/)?.[0];
const extensionHook = html.match(/\/\/ officekit-extensions:start[\s\S]*?\/\/ officekit-extensions:end/)?.[0];
const sliceSources = SLICE_KEYS.map(slice => fs.readFileSync(path.join(repoRoot, sliceAssetPath(slice)), 'utf8'));
const sliceRegistrations = sliceSources.map(source => source.match(/^window\.OfficeKitExtensions\.register\(\{[\s\S]*?^\}\);$/m)?.[0]);
const selector = html.match(/function selectSearchTool\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
const searchFetcher = html.match(/async function fetchToolSearchResults\(query = ''\) \{[\s\S]*?\n        \}/)?.[0];
const searchPrompt = html.match(/function renderSearchPrompt\(\) \{[\s\S]*?\n        \}/)?.[0];
const registryToolIds = loadToolCatalog().tools.map(tool => tool.id);
const destinationRecords = [
  ...(destinations || '').matchAll(/^\s+([a-z][a-z0-9_]*): \{ tab: '([^']+)'([^}]*)\},?$/gm),
  ...sliceSources.flatMap(parseSliceDestinations),
];

function loadSelector() {
  assert.ok(destinations, 'exact stable-ID destination map exists');
  assert.ok(selector, 'search selection handler exists');
  const calls = { tabs: [], calculators: [], focused: [], accepted: null, converterModes: [], developerOperations: [], developerUpdates: 0, pdfTools: [], fileTools: [], audioViews: [], mediaOperations: [], ergonomicsKinds: [], invoiceViews: [], closes: 0 };
  const context = {
    Object,
    officekitReleaseProfile: { profile: 'development', tool_ids: [] }, // Unit tests exercise routed tools after startup verification.
    officekitReleaseAllowsTool: () => true, // Full development profile; beta is tested separately.
    officekitIsPrivateBeta: () => false,
    window: { __TAURI__: { core: { invoke: () => {} } }, officekitMediaToolkit: { setOperation: operation => calls.mediaOperations.push(operation) }, OfficeKitErgonomics: { open: kind => calls.ergonomicsKinds.push(kind) }, OfficeKitInvoices: { open: view => calls.invoiceViews.push(view) } },
    OFFICEKIT_TOOL_DESTINATIONS: undefined,
    closeGlobalSearchModal: () => { calls.closes += 1; },
    switchTab: (tab) => calls.tabs.push(tab),
    switchCalc: (calc) => calls.calculators.push(calc),
    setConverterMode: (mode) => calls.converterModes.push(mode),
    setAudioToolView: view => calls.audioViews.push(view),
    updateDeveloperToolsMode: () => { calls.developerUpdates += 1; },
    openPdfTool: (tool, focus) => calls.pdfTools.push({ tool, focus }),
    openFilesystemTool: tool => calls.fileTools.push(tool),
    document: {
      getElementById(id) {
        return {
          focus: () => calls.focused.push(id),
          set accept(value) { calls.accepted = value; },
          set value(value) { calls.developerOperations.push(value); },
        };
      },
    },
  };
  assert.ok(extensionHook, 'slice extension hook exists');
  sliceRegistrations.forEach((registration, index) => assert.ok(registration, `${SLICE_KEYS[index]} registers first in its asset`));
  vm.runInNewContext(`${destinations}\n${extensionHook}\n${sliceRegistrations.join('\n')}\n${selector}`, context);
  return { context, calls };
}

test('slice extensions reject unknown slices, duplicate registrations and core ID overrides', () => {
  const { context } = loadSelector();
  const register = context.window.OfficeKitExtensions.register;
  assert.throws(() => register({ slice: 'unknown' }), /Unknown OfficeKit slice/);
  assert.throws(() => register({ slice: 'calculators' }), /already registered/);
  const fresh = { Object, window: {} };
  vm.runInNewContext(`${destinations}\n${extensionHook}`, fresh);
  assert.throws(() => fresh.window.OfficeKitExtensions.register({ slice: 'image', destinations: { bank_statement: { tab: 'x' } } }), /Duplicate tool destination: bank_statement/);
  assert.throws(() => fresh.window.OfficeKitExtensions.register({ slice: 'image', openView: 'nope' }), /openView must be a function/);
});

test('slice destinations open their registered view after switching tab', () => {
  const opened = [];
  const calls = { tabs: [], closes: 0 };
  const context = {
    Object,
    officekitReleaseProfile: { profile: 'development', tool_ids: [] },
    officekitReleaseAllowsTool: () => true,
    officekitIsPrivateBeta: () => false,
    window: { __TAURI__: { core: { invoke: () => {} } } },
    closeGlobalSearchModal: () => { calls.closes += 1; },
    switchTab: tab => calls.tabs.push(tab),
    setConverterMode: () => {},
    document: { getElementById: () => null },
  };
  vm.runInNewContext(`${destinations}\n${extensionHook}\n${selector}`, context);
  context.window.OfficeKitExtensions.register({ slice: 'image', tabs: ['image-tools'], destinations: { image_demo: { tab: 'image-tools', sliceView: 'rotate' } }, openView: view => opened.push(view) });
  assert.equal(context.selectSearchTool('image_demo'), true);
  assert.deepEqual(calls.tabs, ['image-tools']);
  assert.deepEqual(opened, ['rotate']);
});

test('calculator search opens the matching calculator instead of the default tab', () => {
  for (const [toolId, calculator] of [
    ['loan_emi', 'emi'],
    ['compound_interest', 'compound'],
    ['vat_salestax', 'vat'],
    ['freelance_rate', 'freelance'],
  ]) {
    const { context, calls } = loadSelector();
    assert.equal(context.selectSearchTool(toolId), true);
    assert.deepEqual(calls.tabs, ['calculators']);
    assert.deepEqual(calls.calculators, [calculator]);
    assert.equal(calls.closes, 1);
  }
});

test('scientific and unit converter searches open their exact calculator panels', () => {
  for (const [toolId, calculator] of [['math_eval', 'scientific'], ['units_convert', 'units']]) {
    const { context, calls } = loadSelector();
    assert.equal(context.selectSearchTool(toolId), true);
    assert.deepEqual(calls.tabs, ['calculators']);
    assert.deepEqual(calls.calculators, [calculator]);
  }
});

test('URL encode and decode searches open the local URI-component workbench', () => {
  assert.match(html, /url_codec: \{ tab: 'converter', converterMode: 'url_codec', focusId: 'url-codec-input' \}/);
  assert.match(html, /setConverterMode\(destination\.converterMode\)/);
});

test('each developer catalogue destination selects its actual operation', () => {
  for (const [id, operation] of [['devtools_format', 'format_json'], ['jwt_inspector', 'decode_jwt'], ['crypto_hashes', 'hashes']]) {
    const { context, calls } = loadSelector();
    assert.equal(context.selectSearchTool(id), true);
    assert.deepEqual(calls.developerOperations, [operation]);
    assert.equal(calls.developerUpdates, 1);
  }
});

test('voice transcription and meeting notes searches open their separate audio views', () => {
  for (const [toolId, view] of [['voice_transcription', 'voice'], ['meeting_notes', 'meeting'], ['speech_coach', 'voice']]) {
    const { context, calls } = loadSelector();
    assert.equal(context.selectSearchTool(toolId), true);
    assert.deepEqual(calls.tabs, ['dictate']);
    assert.deepEqual(calls.audioViews, [view]);
  }
});

test('business calculator searches open their exact calculator forms', () => {
  for (const [id, form] of [['margin_markup', 'margin'], ['break_even', 'break-even'], ['simple_interest', 'simple-interest'], ['depreciation', 'depreciation'], ['everyday_percentages', 'percentages']]) {
    assert.match(html, new RegExp(`${id}: \\{ tab: 'calculators', calculator: '${form}' \\}`));
    assert.match(html, new RegExp(`id="calc-form-${form}"`));
  }
});

test('converter search selects the relevant accepted file formats and focuses file selection', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('data_converter'), true);
  assert.deepEqual(calls.tabs, ['converter']);
  assert.deepEqual(calls.focused, ['generic-file-select-button']);
  assert.match(calls.accepted, /\.csv/);
  assert.match(calls.accepted, /\.xlsx/);
  assert.doesNotMatch(calls.accepted, /\.jpg/);
});

test('image metadata search opens the shared media cleanup operation', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('image_exif_strip'), true);
  assert.deepEqual(calls.tabs, ['converter']);
  assert.deepEqual(calls.converterModes, ['media_toolkit']);
  assert.deepEqual(calls.mediaOperations, ['image-strip-metadata']);
});

test('image resize search opens the shared media resize operation', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('image_resize'), true);
  assert.deepEqual(calls.tabs, ['converter']);
  assert.deepEqual(calls.converterModes, ['media_toolkit']);
  assert.deepEqual(calls.mediaOperations, ['image-resize']);
});

test('private beta keeps existing image and PDF destinations on their currently released routes', () => {
  const { context, calls } = loadSelector();
  context.officekitIsPrivateBeta = () => true;
  for (const [toolId, mode] of [['image_converter', 'convert'], ['image_resize', 'image_resize'], ['image_exif_strip', 'image_metadata']]) {
    assert.equal(context.selectSearchTool(toolId), true);
    assert.equal(calls.converterModes.at(-1), mode);
    assert.deepEqual(calls.mediaOperations, []);
  }
  assert.equal(context.selectSearchTool('pdf_compress'), true);
  assert.equal(calls.tabs.at(-1), 'pdf');
  assert.equal(calls.pdfTools.at(-1).tool, 'compress');
});

test('browser sessions keep existing upload-based tools while the native Media Toolkit requires Tauri authority', () => {
  const { context, calls } = loadSelector();
  delete context.window.__TAURI__;
  assert.equal(context.selectSearchTool('image_converter'), true);
  assert.deepEqual(calls.converterModes, ['convert']);
  assert.deepEqual(calls.mediaOperations, []);
  assert.equal(context.selectSearchTool('media_toolkit'), true);
  assert.deepEqual(calls.converterModes.at(-1), 'media_toolkit');
});

test('unsupported search results do not open an unrelated tool tab', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('not-yet-implemented'), false);
  assert.deepEqual(calls.tabs, []);
  assert.equal(calls.closes, 0);
});

test('search destinations are stable IDs, not registry-provided tab values', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('bank_statement'), true);
  assert.deepEqual(calls.tabs, ['statement']);
});

test('every tool in the searchable registry opens its mapped screen and operation', () => {
  const destinationsById = new Map(destinationRecords.map(([, id, tab, attributes]) => {
    const options = Object.fromEntries([...attributes.matchAll(/([a-zA-Z]+): '([^']+)'/g)].map(([, key, value]) => [key, value]));
    return [id, { tab, options }];
  }));

  assert.ok(registryToolIds.length >= 60, 'the live catalogue keeps every shipped tool');
  assert.equal(new Set(registryToolIds).size, registryToolIds.length, 'registry tool IDs must be unique');
  assert.deepEqual([...destinationsById.keys()].sort(), [...registryToolIds].sort(), 'every searchable tool must have a unique UI destination');

  for (const [toolId, { tab, options }] of destinationsById) {
    const { context, calls } = loadSelector();
    assert.equal(context.selectSearchTool(toolId), true, toolId);
    assert.deepEqual(calls.tabs, [tab], toolId);
    assert.equal(calls.closes, 1, toolId);
    if (options.calculator) assert.deepEqual(calls.calculators, [options.calculator], toolId);
    if (options.converterMode) assert.deepEqual(calls.converterModes, [options.converterMode], toolId);
    if (options.pdfTool) assert.deepEqual(calls.pdfTools, [{ tool: options.pdfTool, focus: false }], toolId);
    if (options.fileTool) assert.deepEqual(calls.fileTools, [options.fileTool], toolId);
    if (options.ergonomicsKind) assert.deepEqual(calls.ergonomicsKinds, [options.ergonomicsKind], toolId);
    if (options.focusId) assert.deepEqual(calls.focused, [options.focusId], toolId);
  }
});

test('PDF workbench operations keep their existing destinations, including compression', () => {
  const { context, calls } = loadSelector();
  context.openPdfTool = tool => calls.pdfTools.push(tool);
  calls.pdfTools = [];
  for (const [id, operation] of [
    ['pdf_merge', 'merge'], ['pdf_split', 'split'],
    ['pdf_metadata_strip', 'metadata'], ['pdf_to_images', 'images'],
    ['pdf_table_extractor', 'tables'], ['pdf_text_extract', 'text'],
    ['pdf_delete_pages', 'delete-pages'], ['pdf_reorder_pages', 'reorder-pages'],
    ['pdf_unlock', 'unlock'], ['pdf_protect', 'protect'],
  ]) {
    assert.equal(context.selectSearchTool(id), true, id);
    assert.equal(calls.tabs.at(-1), 'pdf', id);
    assert.equal(calls.pdfTools.at(-1), operation, id);
  }
  assert.equal(context.selectSearchTool('pdf_compress'), true);
  assert.equal(calls.tabs.at(-1), 'pdf');
  assert.equal(calls.pdfTools.at(-1), 'compress');
  assert.deepEqual(calls.mediaOperations, []);
});

test('PDF to CSV and XLSX search results offer statement extraction and general table preview', () => {
  const { context, calls } = loadSelector();
  assert.equal(context.selectSearchTool('bank_statement'), true);
  assert.deepEqual(calls.tabs, ['statement']);
  context.openPdfTool = tool => calls.pdfTools.push(tool);
  calls.pdfTools = [];
  assert.equal(context.selectSearchTool('pdf_table_extractor'), true);
  assert.deepEqual(calls.tabs, ['statement', 'pdf']);
  assert.deepEqual(calls.pdfTools, ['tables']);
});

test('global search renders every PDF-to destination returned by the shared catalogue', () => {
  const renderResults = html.match(/function renderSearchResults\(tools\) \{[\s\S]*?\n        \}(?=\n\n        let toolGalleryView)/)?.[0];
  assert.ok(renderResults, 'the shared search-result renderer exists');
  const container = {
    className: '',
    innerHTML: '',
    querySelectorAll: () => [],
  };
  const context = {
    Object,
    OFFICEKIT_TOOL_DESTINATIONS: undefined,
    document: { getElementById: () => container },
    officekitEscapeHtml: value => String(value ?? ''),
  };
  const ids = [
    'bank_statement', 'pdf_unlock', 'pdf_protect', 'pdf_merge', 'pdf_split',
    'pdf_compress', 'pdf_metadata_strip', 'pdf_to_images',
    'pdf_delete_pages', 'pdf_reorder_pages',
  ];
  const tools = ids.map(id => ({ id, name: id, category: 'PDF & Documents', icon: 'fa-file-pdf', desc: id }));
  vm.runInNewContext(`${destinations}\nfunction officekitToolDestination(id) { return OFFICEKIT_TOOL_DESTINATIONS[id]; }\n${renderResults}`, context);
  context.renderSearchResults(tools);
  for (const id of ids) {
    assert.match(container.innerHTML, new RegExp(`data-tool-id="${id}"`));
    assert.match(container.innerHTML, new RegExp(`<span[^>]*>${id}</span>`));
  }
  assert.equal((container.innerHTML.match(/aria-disabled="false"/g) ?? []).length, ids.length);
});

test('search requests use the shared backend index and discard stale responses', async () => {
  const filterSource = html.match(/async function filterGlobalTools\(\) \{[\s\S]*?\n        \}(?=\n\n        function renderSearchUnavailable)/)?.[0];
  assert.ok(filterSource, 'query filtering calls the authoritative search index');
  const input = { value: 'PDF to' };
  const rendered = [];
  const requests = [];
  let resolveFirst;
  const context = {
    document: { getElementById: () => input },
    globalSearchRequestSequence: 0,
    allToolsCache: [{ id: 'cached' }],
    encodeURIComponent,
    renderSearchResults: results => rendered.push(results),
    renderSearchUnavailable: () => rendered.push('unavailable'),
    officekitStartupFetch(url) {
      requests.push(url);
      if (requests.length === 1) return new Promise(resolve => { resolveFirst = resolve; });
      return Promise.resolve({ ok: true, json: async () => ({ tools: [{ id: 'pdf_merge' }] }) });
    },
  };
  vm.runInNewContext(`${searchFetcher}\n${filterSource}`, context);
  const staleRequest = context.filterGlobalTools();
  input.value = 'PDF';
  const currentRequest = context.filterGlobalTools();
  await currentRequest;
  resolveFirst({ ok: true, json: async () => ({ tools: [{ id: 'bank_statement' }] }) });
  await staleRequest;

  assert.deepEqual(requests, ['/api/tools/search?q=PDF%20to', '/api/tools/search?q=PDF']);
  assert.equal(rendered.length, 1);
  assert.deepEqual(rendered[0].map(tool => tool.id), ['pdf_merge']);
});

test('empty search clears palette results without loading the full catalogue', async () => {
  const filterSource = html.match(/async function filterGlobalTools\(\) \{[\s\S]*?\n        \}(?=\n\n        function renderSearchUnavailable)/)?.[0];
  const input = { value: '   ' };
  let requests = 0;
  let prompted = false;
  const context = {
    document: { getElementById: () => input },
    globalSearchRequestSequence: 0,
    renderSearchPrompt: () => { prompted = true; },
    officekitStartupFetch: async () => { requests += 1; throw new Error('Should not search empty query'); },
  };
  vm.runInNewContext(`${searchFetcher}\n${filterSource}`, context);
  await context.filterGlobalTools();
  assert.equal(requests, 0);
  assert.equal(prompted, true);
});

test('opening an empty palette does not load the catalogue and typing searches the shared index', async () => {
  const openSource = html.match(/async function openGlobalSearchModal\(\) \{[\s\S]*?\n        \}/)?.[0];
  const filterSource = html.match(/async function filterGlobalTools\(\) \{[\s\S]*?\n        \}(?=\n\n        function renderSearchUnavailable)/)?.[0];
  assert.ok(openSource, 'the title-bar search opener exists');
  assert.ok(filterSource, 'title-bar search filtering exists');

  const input = { value: '', focus() {} };
  const renders = [];
  const requests = [];
  const context = {
    document: { getElementById: id => id === 'global-search-input' ? input : { classList: { remove() {} } } },
    allToolsCache: [],
    allToolsLoaded: false,
    globalSearchRequestSequence: 0,
    renderSearchResults: tools => renders.push(tools.map(tool => tool.id)),
    renderSearchPrompt() { renders.push('prompt'); },
    renderSearchUnavailable: () => renders.push('unavailable'),
    officekitStartupFetch(url) {
      requests.push(url);
      return Promise.resolve({ ok: true, json: async () => ({ tools: [{ id: 'pdf_to_images' }] }) });
    },
  };
  vm.runInNewContext(`${searchFetcher}\n${filterSource}\n${openSource}`, context);

  await context.openGlobalSearchModal();
  assert.deepEqual(requests, []);
  input.value = 'PDF to';
  await context.filterGlobalTools();

  assert.deepEqual(renders.at(-1), ['pdf_to_images']);
  assert.deepEqual(requests, ['/api/tools/search?q=PDF%20to']);
});

test('reopening title-bar search reapplies the query already in its input', async () => {
  const openSource = html.match(/async function openGlobalSearchModal\(\) \{[\s\S]*?\n        \}/)?.[0];
  const filterSource = html.match(/async function filterGlobalTools\(\) \{[\s\S]*?\n        \}(?=\n\n        function renderSearchUnavailable)/)?.[0];
  const input = { value: 'PDF to', focus() {} };
  const requests = [];
  const renders = [];
  const context = {
    document: { getElementById: id => id === 'global-search-input' ? input : { classList: { remove() {} } } },
    allToolsCache: [{ id: 'pdf_merge' }, { id: 'pdf_to_images' }],
    allToolsLoaded: true,
    globalSearchRequestSequence: 0,
    renderSearchResults: tools => renders.push(tools.map(tool => tool.id)),
    renderSearchUnavailable() {},
    officekitStartupFetch: async url => {
      requests.push(url);
      return { ok: true, json: async () => ({ tools: [{ id: 'pdf_to_images' }] }) };
    },
  };
  vm.runInNewContext(`${searchFetcher}\n${searchPrompt}\n${filterSource}\n${openSource}`, context);
  await context.openGlobalSearchModal();

  assert.deepEqual(requests, ['/api/tools/search?q=PDF%20to']);
  assert.deepEqual(renders.at(-1), ['pdf_to_images']);
});

test('global search exposes retry after catalog failures and recovers with normal result styling', async () => {
  const openModal = html.match(/async function openGlobalSearchModal\(\) \{[\s\S]*?\n        \}/)?.[0];
  const unavailable = html.match(/function renderSearchUnavailable\(retrySearch = \(\) => openGlobalSearchModal\(\)\) \{[\s\S]*?\n        \}/)?.[0];
  const renderResults = html.match(/function renderSearchResults\(tools\) \{[\s\S]*?\n        \}(?=\n\n        let toolGalleryView)/)?.[0];
  const filterSource = html.match(/async function filterGlobalTools\(\) \{[\s\S]*?\n        \}(?=\n\n        function renderSearchUnavailable)/)?.[0];
  assert.ok(openModal, 'global search modal loader exists');
  assert.ok(unavailable, 'the shared unavailable state exists');
  assert.ok(renderResults, 'search results renderer exists');

  const elements = new Map();
  let retryHandler;
  const document = {
    getElementById(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          className: '',
          classList: { remove() {} },
          focus() {},
          value: '',
          querySelectorAll: () => [],
          querySelector: selector => selector === '#search-retry-button' ? { addEventListener: (event, handler) => { if (event === 'click') retryHandler = handler; } } : null,
          innerHTML: '',
          textContent: '',
        });
      }
      return elements.get(id);
    },
  };
  elements.set('global-search-input', { value: 'PDF', focus() {} });
  const context = {
    document,
    Object,
    OFFICEKIT_TOOL_DESTINATIONS: { pdf_merge: { tab: 'pdf' } },
    allToolsCache: [],
    allToolsLoaded: false,
    globalSearchRequestSequence: 0,
    officekitEscapeHtml: value => String(value ?? ''),
    officekitStartupFetch: async () => { throw new Error('sidecar unavailable'); },
    renderSearchResults: undefined,
    renderSearchUnavailable: undefined,
    selectSearchTool() {},
    closeGlobalSearchModal() {},
  };
  vm.runInNewContext(`${searchFetcher}\n${unavailable}\nfunction officekitToolDestination(id) { return OFFICEKIT_TOOL_DESTINATIONS[id]; }\n${renderResults}\n${filterSource}\n${openModal}`, context);
  await context.openGlobalSearchModal();
  const container = elements.get('search-results-list');
  assert.match(container.innerHTML, /Tool search is unavailable/);
  assert.match(container.innerHTML, /Retry search/);
  assert.equal(context.allToolsLoaded, false);

  context.officekitStartupFetch = async () => ({ ok: false, json: async () => ({ tools: [] }) });
  await context.openGlobalSearchModal();
  assert.match(container.innerHTML, /Tool search is unavailable/);
  assert.equal(context.allToolsLoaded, false);

  context.officekitStartupFetch = async () => ({ ok: true, json: async () => ({ tools: [{ id: 'pdf_merge', name: 'Merge PDFs', category: 'PDF & Documents', icon: 'fa-object-group', desc: 'Merge selected PDFs' }] }) });
  await retryHandler();
  assert.equal(context.allToolsLoaded, false);
  assert.match(container.innerHTML, /Merge PDFs/);
  assert.match(container.className, /max-h-96 overflow-y-auto/);
});

test('network diagnostic searches open the shared workbench and focus the exact task', () => {
  const { context, calls } = loadSelector();
  for (const [id, focusId] of [
    ['network_dns', 'network-dns-hostname'],
    ['network_ping', 'network-ping-target'],
    ['network_interfaces', 'network-interfaces-run'],
  ]) {
    assert.equal(context.selectSearchTool(id), true);
    assert.equal(calls.tabs.at(-1), 'network');
    assert.equal(calls.focused.at(-1), focusId);
  }
});

test('system summary and resource searches open their exact manual actions', () => {
  const { context, calls } = loadSelector();
  for (const [id, focusId] of [
    ['system_info', 'system-refresh'],
    ['system_resources', 'system-refresh'],
  ]) {
    assert.equal(context.selectSearchTool(id), true);
    assert.equal(calls.tabs.at(-1), 'system');
    assert.equal(calls.focused.at(-1), focusId);
  }
});

test('title-bar Quick Search and query input have direct listeners independent of delegated CSP actions', async () => {
  const binder = html.match(/function bindGlobalSearch\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(binder, 'title-bar search wires its own click and input handlers');
  assert.match(html, /window\.addEventListener\('DOMContentLoaded', async \(\) => \{\s*\/\/ Keep the title-bar search usable even if profile discovery fails\.\s*bindGlobalSearch\(\);\s*try \{ await initializeReleaseProfile\(\); \}/);
  assert.doesNotMatch(html.match(/<button id="global-search-trigger"[^>]*>/)?.[0] ?? '', /data-officekit-click/);
  assert.doesNotMatch(html.match(/<input type="text" id="global-search-input"[^>]*>/)?.[0] ?? '', /data-officekit-input/);

  const listeners = { click: null, input: null };
  const calls = { open: 0, filter: 0 };
  const elements = {
    'global-search-trigger': { addEventListener: (name, handler) => { listeners[name] = handler; } },
    'global-search-input': { addEventListener: (name, handler) => { listeners[name] = handler; } },
  };
  const context = {
    document: { getElementById: id => elements[id] },
    openGlobalSearchModal: async () => { calls.open += 1; },
    filterGlobalTools: async () => { calls.filter += 1; },
  };
  vm.runInNewContext(`${binder}`, context);
  context.bindGlobalSearch();
  await listeners.click();
  await listeners.input();
  assert.deepEqual(calls, { open: 1, filter: 1 });
});

test('zero-result Quick Search opens a prefilled local feature request draft', () => {
  const renderResults = html.match(/function renderSearchResults\(tools\) \{[\s\S]*?\n        \}(?=\n\n        let toolGalleryView)/)?.[0];
  const openSupport = html.match(/function openSupportModal\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(renderResults);
  assert.ok(openSupport);
  const listeners = {};
  const values = {
    'global-search-input': { value: 'invoice reminder' },
    'support-modal': { classList: { remove: value => { listeners.modalClass = value; } } },
    'ticket-type': { value: 'bug' },
    'ticket-title': { value: '' },
    'ticket-desc': { value: '', focus: () => { listeners.descriptionFocused = true; } },
  };
  const container = {
    innerHTML: '',
    className: '',
    querySelector: selector => selector === '#search-request-tool-button'
      ? { addEventListener: (event, handler) => { if (event === 'click') listeners.request = handler; } }
      : null,
  };
  const context = {
    Object,
    document: { getElementById: id => id === 'search-results-list' ? container : values[id] },
    updateSupportFeedbackFields() {},
    setSupportStatus(message) { listeners.status = message; },
    closeGlobalSearchModal() { listeners.searchClosed = true; },
  };
  vm.runInNewContext(`${renderResults}\n${openSupport}`, context);
  context.renderSearchResults([]);
  assert.match(container.innerHTML, /Request this tool/);
  assert.equal((container.innerHTML.match(/<button\b/g) || []).length, 1);
  listeners.request();
  assert.equal(listeners.searchClosed, true);
  assert.equal(listeners.modalClass, 'hidden');
  assert.equal(values['ticket-type'].value, 'feature');
  assert.equal(values['ticket-title'].value, 'Request tool: invoice reminder');
  assert.match(values['ticket-desc'].value, /invoice reminder/);
  assert.equal(listeners.descriptionFocused, true);

  values['global-search-input'].value = 'x'.repeat(256);
  context.renderSearchResults([]);
  listeners.request();
  assert.equal(values['ticket-title'].value.length, 160);
  assert.match(openSupport, /\.trim\(\)\.slice\(0, 146\)/);
  assert.match(html, /Send a report to OfficeKit support\. We tell you here when a fix ships\./);
});
