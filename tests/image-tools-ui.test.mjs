import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { loadToolCatalog, parseSliceDestinations } from '../scripts/tool-catalog.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const indexHtml = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');
const hook = indexHtml.match(/\/\/ officekit-extensions:start[\s\S]*?\/\/ officekit-extensions:end/)?.[0];
const sliceSource = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-image.js'), 'utf8');
const sliceStyles = fs.readFileSync(path.join(repoRoot, 'assets/officekit-slice-image.css'), 'utf8');

const IMAGE_IDS = [
  'image_rotate_flip', 'image_exif_view', 'image_dpi', 'image_grayscale', 'image_adjust', 'image_border',
  'image_palette', 'image_data_uri', 'image_icon_pack', 'image_collage', 'image_contact_sheet', 'image_compare',
];
const SLUGS = {
  image_rotate_flip: 'rotate-flip', image_exif_view: 'exif', image_dpi: 'dpi', image_grayscale: 'grayscale',
  image_adjust: 'adjust', image_border: 'border', image_palette: 'palette', image_data_uri: 'data-uri',
  image_icon_pack: 'icon-pack', image_collage: 'collage', image_contact_sheet: 'contact-sheet', image_compare: 'compare',
};

function loadSlice() {
  assert.ok(hook, 'shell extension hook exists in index.html');
  const window = { addEventListener() {}, location: { hash: '' } };
  const context = { window, OFFICEKIT_TOOL_DESTINATIONS: {}, FormData, Blob, URL, TextEncoder, atob, console };
  vm.createContext(context);
  vm.runInContext(`${hook}\n${sliceSource}`, context);
  return { context, api: window.OfficeKitImageTools, extensions: window.OfficeKitExtensions };
}

const { context, api } = loadSlice();
const file = (name = 'photo.png', type = 'image/png') => Object.assign(new Blob(['x'], { type }), { name });
// vm arrays and objects come from another realm, so compare plain JSON copies.
const plain = value => JSON.parse(JSON.stringify(value));
const throwsWith = (fn, pattern) => assert.throws(fn, error => error.name === 'ImageToolError' && pattern.test(error.message));

test('the register call is the first statement and lists one destination per line', () => {
  const firstStatement = sliceSource.replace(/^(\/\/[^\n]*\n)+/, '');
  assert.ok(firstStatement.startsWith('window.OfficeKitExtensions.register({'), 'register is the first statement after comments');
  const destinations = parseSliceDestinations(sliceSource);
  assert.deepEqual(destinations.map(match => match[1]).sort(), [...IMAGE_IDS].sort());
});

test('each of the twelve image tool IDs routes to the image-tools tab and its view', () => {
  for (const id of IMAGE_IDS) {
    const destination = context.officekitToolDestination(id);
    assert.ok(destination, `${id} is a destination`);
    assert.equal(destination.tab, 'image-tools');
    assert.equal(destination.sliceView, SLUGS[id]);
    assert.equal(destination.slice, 'image');
  }
});

test('the destinations match the image catalogue records one for one', () => {
  const catalogue = loadToolCatalog().tools.filter(tool => tool.tab === 'image-tools').map(tool => tool.id).sort();
  assert.deepEqual(catalogue, [...IMAGE_IDS].sort());
  for (const id of IMAGE_IDS) assert.equal(api.viewForSlug(SLUGS[id])?.tool, id);
});

test('core destination IDs are not overridden and a second registration is refused', () => {
  const hookWindow = { addEventListener() {}, location: { hash: '' } };
  const hookContext = { window: hookWindow, OFFICEKIT_TOOL_DESTINATIONS: { bank_statement: { tab: 'statement' } } };
  vm.createContext(hookContext);
  vm.runInContext(hook, hookContext);
  assert.throws(() => hookWindow.OfficeKitExtensions.register({ slice: 'image', destinations: { bank_statement: { tab: 'x' } } }), /Duplicate tool destination: bank_statement/);
  hookWindow.OfficeKitExtensions.register({ slice: 'image', destinations: { image_demo: { tab: 'image-tools', sliceView: 'grayscale' } } });
  assert.throws(() => hookWindow.OfficeKitExtensions.register({ slice: 'image' }), /already registered: image/);
});

test('view slugs are unique and the groups match the approved rail', () => {
  const slugs = api.VIEWS.map(view => view.slug);
  assert.equal(new Set(slugs).size, 12);
  assert.deepEqual(plain(api.GROUPS), ['Adjust', 'Inspect', 'Combine', 'Export']);
  assert.equal(api.VIEWS.filter(view => view.group === 'Adjust').length, 5);
  assert.equal(api.VIEWS.filter(view => view.group === 'Inspect').length, 3);
});

// AGENTS.md "Button Limit": count what a user sees as a button. Tabs, in-text links and row actions are not counted.
function visibleButtons(markup) {
  const tags = String(markup).match(/<(button|label)\b[^>]*>/g) || [];
  return tags.filter(tag => {
    if (/role="tab"/.test(tag)) return false;
    if (/class="[^"]*\blink\b/.test(tag)) return false;
    if (/data-move=|data-remove/.test(tag)) return false;
    if (tag.startsWith('<label')) return /class="[^"]*\bbtn\b/.test(tag);
    return true;
  });
}
const loaded = {
  file: file('photo.jpg', 'image/jpeg'), a: file('a.png'), b: file('b.png'),
  files: [file('one.png'), file('two.png'), file('three.png'), file('four.png')],
};

test('every view mounts in both the empty and the loaded state and shows at most three buttons (UX-7, QA-1)', () => {
  for (const view of api.VIEWS) {
    for (const files of [{}, loaded]) {
      const markup = api.viewMarkup(view.slug, files).toString();
      assert.ok(markup.length > 0, `${view.slug} renders`);
      const count = visibleButtons(markup).length;
      assert.ok(count <= 3, `${view.slug} shows ${count} buttons`);
    }
  }
});

test('the compare result states stay within three buttons in every compare mode (UX-4, UX-7)', () => {
  const result = { comparable: true, changed_pixels: 3, changed_ratio: 0.1, threshold: 8, a: { w: 2, h: 2 }, b: { w: 2, h: 2 }, difference_png: 'data:image/png;base64,AAAA' };
  for (const mode of ['side', 'overlay', 'diff']) {
    const markup = api.comparisonMarkup(result, { mode, overlayOpacity: 50, threshold: 8, files: loaded }).toString();
    assert.ok(visibleButtons(markup).length <= 3, `${mode} shows ${visibleButtons(markup).length} buttons`);
  }
  const mismatch = api.comparisonMarkup({ ...result, comparable: false, reason: 'size_mismatch' }, { mode: 'side', files: loaded }).toString();
  assert.ok(visibleButtons(mismatch).length <= 3);
});

test('the dock refuses a fourth button (QA-2)', () => {
  const four = ['a', 'b', 'c', 'd'].map(action => ({ action, label: action }));
  assert.throws(() => api.dock('status', four), /at most three buttons/);
  assert.doesNotThrow(() => api.dock('status', four.slice(0, 3)));
});

test('approved controls from the mock are present in their views (UX-5, UX-8, UX-10, UX-2)', () => {
  const adjust = api.viewMarkup('adjust', loaded).toString();
  assert.match(adjust, /data-action="copy-image"/, 'Copy image is in the adjust dock');
  const rotate = api.viewMarkup('rotate-flip', loaded).toString();
  assert.equal((rotate.match(/data-turn="(0|90|180|270)"/g) || []).length, 4, 'four turn chips');
  assert.match(rotate, /Flip horizontal/);
  assert.match(rotate, /Flip vertical/);
  assert.doesNotMatch(rotate, /<select data-param="turn"/, 'no turn select');
  assert.match(adjust, /data-action="change-file"/, 'a single-image view can change its image');
  assert.match(api.viewMarkup('collage', loaded).toString(), /data-action="preview"/);
  assert.match(api.viewMarkup('contact-sheet', loaded).toString(), /Preview page 1/);
  const overlay = api.comparisonMarkup({ comparable: true, changed_pixels: 0, threshold: 8, a: { w: 1, h: 1 }, b: { w: 1, h: 1 } }, { mode: 'overlay', overlayOpacity: 50, files: loaded }).toString();
  assert.match(overlay, /data-param="overlay-opacity"/);
  assert.match(api.viewMarkup('compare', loaded).toString(), /data-param="threshold"/);
});

test('the single-image views and the EXIF and icon views do not repeat Media Toolkit in an "Also here" row (UX-3)', () => {
  for (const slug of ['exif', 'icon-pack']) assert.doesNotMatch(api.viewMarkup(slug, loaded).toString(), /Also here/);
});

test('the Compare pickers are shown only for a missing image (UX-4)', () => {
  const picked = api.viewMarkup('compare', loaded).toString();
  assert.doesNotMatch(picked, /Choose image A/);
  assert.match(picked, /Change A/);
  assert.match(picked, /Change B/);
  const empty = api.viewMarkup('compare', {}).toString();
  assert.match(empty, /Choose image A/);
  assert.match(empty, /Choose image B/);
});

test('status text is empty on load and the collage and contact-sheet actions sit in the sticky dock (UX-11, UX-1)', () => {
  assert.doesNotMatch(api.viewMarkup('rotate-flip', loaded).toString(), /Preview updates after each change/);
  assert.match(sliceStyles, /\.image-tools__ordered > \.ok-action-dock \{[^}]*position: sticky;[^}]*bottom: 0;/);
});

test('the standalone page heading is gone and the section is labelled for assistive tech (UX-15)', () => {
  assert.doesNotMatch(sliceSource, /image-tools__head/);
  assert.match(sliceSource, /aria-label', 'Image tools'/);
});

test('the data URI result is a block element, so the action dock is not nested in a paragraph (UX-12)', () => {
  assert.doesNotMatch(sliceSource, /<p class="muted" data-role="uri-result">/);
});

test('rendition operations match the server union and keep identity changes out of the request', () => {
  assert.deepEqual(plain(api.renditionOperations('rotate-flip', { turn: '90', flip_h: true })), [
    { type: 'rotate', degrees_cw: 90 }, { type: 'flip', axis: 'horizontal' },
  ]);
  assert.deepEqual(plain(api.renditionOperations('rotate-flip', { turn: '0' })), []);
  throwsWith(() => api.renditionOperations('rotate-flip', { turn: '45' }), /Turn/);
  assert.deepEqual(plain(api.renditionOperations('adjust', { brightness: '0', contrast: '0', saturation: '0' })), []);
  assert.deepEqual(plain(api.renditionOperations('adjust', { brightness: '-100', contrast: '0', saturation: '50' })), [
    { type: 'adjust', brightness: -100, contrast: 0, saturation: 50 },
  ]);
  throwsWith(() => api.renditionOperations('adjust', { brightness: '101' }), /Brightness must be/);
  throwsWith(() => api.renditionOperations('adjust', { contrast: '' }), /Contrast must be/);
  assert.deepEqual(plain(api.renditionOperations('border', { width: '24', fill: '#abcdef', fill_opacity: '100', corner_radius: '0' })), [
    { type: 'border', width: 24, corner_radius: 0, fill: '#ABCDEF', fill_opacity: 100 },
  ]);
  throwsWith(() => api.renditionOperations('border', { width: '2001', fill: '#FFFFFF' }), /Border width/);
  throwsWith(() => api.renditionOperations('border', { width: '', fill: '#FFFFFF' }), /Border width/);
  throwsWith(() => api.renditionOperations('border', { width: '4', fill: 'red' }), /colour as #RRGGBB/);
  assert.deepEqual(plain(api.renditionOperations('dpi', { x: '300', y: '300', unit: 'cm' })), [
    { type: 'density', x: 300, y: 300, unit: 'cm' },
  ]);
  throwsWith(() => api.renditionOperations('dpi', { x: '0', y: '300' }), /Horizontal density/);
  throwsWith(() => api.renditionOperations('dpi', { x: '2401', y: '300' }), /Horizontal density/);
});

test('rendition form carries the operations, format and optional quality and preview size', () => {
  const operations = [{ type: 'grayscale' }];
  const jpeg = api.buildRenditionForm({ file: file(), operations, format: 'jpeg', quality: '85', previewMaxEdge: 1024 });
  assert.equal(jpeg.get('operations'), JSON.stringify({ operations }));
  assert.equal(jpeg.get('format'), 'jpeg');
  assert.equal(jpeg.get('quality'), '85');
  assert.equal(jpeg.get('preview_max_edge'), '1024');
  const png = api.buildRenditionForm({ file: file(), operations, format: 'png', quality: '85' });
  assert.equal(png.get('quality'), null, 'quality is not sent for PNG');
  throwsWith(() => api.buildRenditionForm({ file: file(), operations: [] }), /at least one change/);
  throwsWith(() => api.buildRenditionForm({ file: file(), operations: Array(9).fill({ type: 'grayscale' }) }), /at least one change/);
  throwsWith(() => api.buildRenditionForm({ file: file(), operations, format: 'jpeg', quality: '101' }), /Quality/);
});

test('metadata requests keep location withheld unless asked', () => {
  assert.equal(api.buildMetadataForm(file(), false).get('include_location'), 'false');
  assert.equal(api.buildMetadataForm(file(), true).get('include_location'), 'true');
});

test('collage canvas uses the server formula and refuses oversize layouts before upload', () => {
  const layout = { columns: '2', cell_width: '1200', cell_height: '800', gap: '20', padding: '40', fit: 'contain', background: '#FFFFFF', format: 'png' };
  const canvas = api.collageCanvas(layout, 4);
  assert.equal(canvas.width, 2500);
  assert.equal(canvas.height, 1700);
  assert.equal(canvas.overflow, false);
  const huge = api.collageCanvas({ ...layout, columns: '10', cell_width: '4000', cell_height: '4000' }, 50);
  assert.equal(huge.overflow, true);
  assert.match(huge.reason, /Keep each side/);
  assert.throws(() => api.buildCollageForm([file(), file()], { ...layout, columns: '10', cell_width: '4000', cell_height: '4000' }), /Keep each side/);
  assert.equal(api.collageCanvas({ ...layout, background: 'transparent' }, 2).layout.background, 'transparent');
  throwsWith(() => api.collageCanvas({ ...layout, background: 'red' }, 2), /colour as #RRGGBB/);
  throwsWith(() => api.buildCollageForm([file()], layout), /Choose 2 to 50 images/);
  throwsWith(() => api.buildCollageForm(Array.from({ length: 51 }, () => file()), layout), /Choose 2 to 50 images/);
});

test('contact sheet pages and form follow the bounds', () => {
  assert.equal(api.contactSheetPages(180, 4, 6), 8);
  assert.equal(api.contactSheetPages(5, 4, 6), 1);
  const form = api.buildContactSheetForm([file()], { page: 'letter', orientation: 'landscape', columns: '4', rows: '6', show_names: true, format: 'png-zip' });
  assert.deepEqual(JSON.parse(form.get('sheet')), { page: 'letter', orientation: 'landscape', columns: 4, rows: 6, show_names: true, format: 'png-zip' });
  throwsWith(() => api.buildContactSheetForm([file()], { columns: '0', rows: '6' }), /Columns/);
  throwsWith(() => api.buildContactSheetForm([], { columns: '4', rows: '6' }), /Choose 1 to 200/);
});

test('comparison, palette and icon pack requests are bounded', () => {
  const comparison = api.buildComparisonForm(file('a.png'), file('b.png'), { alignment: 'bogus', threshold: '8' });
  assert.equal(comparison.get('alignment'), 'none');
  assert.equal(comparison.get('threshold'), '8');
  throwsWith(() => api.buildComparisonForm(file(), file(), { threshold: 256 }), /Threshold/);
  throwsWith(() => api.buildPaletteForm(file(), '13', '128'), /Colours/);
  throwsWith(() => api.buildPaletteForm(file(), '6', '0'), /Alpha threshold/);
  assert.equal(api.buildIconPackForm(file(), { web: true, windows: true, macos: true }, 'bogus').get('platforms'), 'web,windows,macos');
  assert.equal(api.buildIconPackForm(file(), { web: true }, 'bogus').get('fit'), 'pad');
  throwsWith(() => api.buildIconPackForm(file(), {}, 'pad'), /at least one platform/);
});

test('data URI text is checked against the grammar and size before any request', () => {
  assert.equal(api.validateDataUriText('data:image/svg+xml;base64,PHN2Zz4=').ok, true);
  assert.equal(api.validateDataUriText('data:text/html;base64,PHNjcmlwdD4=').ok, false);
  assert.equal(api.validateDataUriText('data:image/png,AAAA').ok, false);
  assert.equal(api.validateDataUriText('').ok, false);
  const oversize = `data:image/png;base64,${'A'.repeat(api.LIMITS.dataUriChars)}`;
  assert.match(api.validateDataUriText(oversize).reason, /too large/);
});

test('metadata reports are validated and location is only shown when present', () => {
  const report = {
    format: 'JPEG', width: 4032, height: 3024, frames: 1, has_icc: true, has_xmp: false, has_iptc: false,
    groups: [{ group: 'camera', tag: 'Model', label: 'Camera', value: 'Apple iPhone 15 Pro', status: 'present' }],
    location: { present: true, withheld: true },
  };
  const parsed = api.parseMetadataReport(report);
  assert.equal(parsed.groups[0].label, 'Camera');
  assert.equal(parsed.location.latitude, null);
  assert.equal(api.metadataText(parsed, { includeLocation: false }).includes('Location:'), false);
  throwsWith(() => api.parseMetadataReport({ ...report, groups: [{ ...report.groups[0], group: 'gps' }] }), /unexpected response/);
  throwsWith(() => api.parseMetadataReport({ ...report, groups: [{ ...report.groups[0], status: 'unknown' }] }), /unexpected response/);
  throwsWith(() => api.parseMetadataReport({ ...report, location: undefined }), /unexpected response/);
  throwsWith(() => api.parseMetadataReport(['not', 'an', 'object']), /unexpected response/);
  throwsWith(() => api.parseMetadataReport({ ...report, groups: Array(257).fill(report.groups[0]) }), /unexpected response/);
});

test('palette, comparison and data URI responses are validated', () => {
  const palette = api.parsePalette({ colors: [{ hex: '#2f5d7c', rgb: [47, 93, 124], share: 0.5, pixels: 10 }], sampled_pixels: 20, excluded_transparent_pixels: 0 });
  assert.equal(palette.colors[0].hex, '#2F5D7C');
  throwsWith(() => api.parsePalette({ colors: [{ hex: 'blue', rgb: [0, 0, 0], share: 1, pixels: 1 }], sampled_pixels: 1 }), /unexpected response/);
  throwsWith(() => api.parseComparison({ a: { w: 1, h: 1 }, b: { w: 1, h: 1 }, comparable: 'yes', threshold: 0 }), /unexpected response/);
  throwsWith(() => api.parseComparison({ a: { w: 1, h: 1 }, b: { w: 1, h: 1 }, comparable: true, threshold: 0, difference_png: 5 }), /unexpected response/);
  throwsWith(() => api.parseDataUri({ data_uri: 'data:image/png;base64,AA', byte_length: 1 }), /unexpected response/);
  const uri = api.parseDataUri({ mime: 'image/png', byte_length: 3, data_uri: 'data:image/png;base64,AAAA' });
  assert.equal(uri.data_uri_length, 'data:image/png;base64,AAAA'.length);
});

test('comparison wording never claims the images are identical', () => {
  const same = api.comparisonSummary({ comparable: true, changed_pixels: 0, threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 } });
  assert.match(same, /No pixel differed by more than 8 at 2000 × 1500/);
  assert.doesNotMatch(same, /identical/i);
  assert.doesNotMatch(api.comparisonSummary({ comparable: false, threshold: 0, a: { w: 2, h: 2 }, b: { w: 1, h: 1 } }), /identical/i);
  // A changed result must not claim that nothing differed (CR-16).
  const changedSummary = api.comparisonSummary({ comparable: true, changed_pixels: 12288, changed_ratio: 0.004096, threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 } });
  assert.doesNotMatch(changedSummary, /No pixel differed/);
  assert.equal(changedSummary, '');
});

test('error states use the server detail text or a fixed message, never raw bodies', () => {
  assert.equal(api.errorMessageFromResponse(413, '{"detail":"The image exceeds the supported 64 MiB input limit."}'), 'The image exceeds the supported 64 MiB input limit.');
  assert.match(api.errorMessageFromResponse(422, 'not json at all'), /could not be processed/);
  assert.match(api.errorMessageFromResponse(415, ''), /supported image file/);
  assert.match(api.errorMessageFromResponse(500, ''), /could not be completed/);
  assert.match(api.errorMessageFromResponse(500, '{"detail":42}'), /could not be completed/);
});

test('dynamic values are escaped in every template path (P-011)', () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const rendered = api.html`<p title="${hostile}">${hostile}</p>`.toString();
  assert.equal(rendered.includes('<img'), false);
  assert.ok(rendered.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
  assert.equal(api.html`${[api.html`<i>${'<x>'}</i>`]}`.toString(), '<i>&lt;x&gt;</i>');
  assert.equal(api.html`${api.raw('<b>ok</b>')}`.toString(), '<b>ok</b>');
  assert.equal(api.escapeHtml(`a'b"c&d`), 'a&#39;b&quot;c&amp;d');
  assert.equal(api.html`${undefined}`.toString(), '');
});

test('a saved difference image is decoded from its data URI without fetch, so the packaged CSP is not loosened (DEVOPS-1)', async () => {
  const bytes = api.dataUriToBlob('data:image/png;base64,iVBORw==');
  assert.equal(bytes.type, 'image/png');
  assert.deepEqual([...new Uint8Array(await bytes.arrayBuffer())], [0x89, 0x50, 0x4e, 0x47]);
  assert.throws(() => api.dataUriToBlob('https://example.com/a.png'), /not an image data URI/);
  assert.doesNotMatch(sliceSource, /fetch\(result\.difference_png\)/);
});

test('the print size and palette CSV helpers produce exact text', () => {
  assert.equal(api.printSize(600, 300, 'inch'), '2.00 in');
  // CR-3: 600 px at 300 px per cm is 2.0 cm; the density is already a length per cm.
  assert.equal(api.printSize(600, 300, 'cm'), '2.0 cm');
  assert.equal(api.printSize(600, 300, 'inch'), '2.00 in');
  assert.equal(api.printSize(600, 0, 'inch'), '');
  assert.equal(api.paletteCsv({ colors: [{ hex: '#2F5D7C', rgb: [47, 93, 124], share: 0.382 }] }), 'hex,r,g,b,share\n#2F5D7C,47,93,124,38.2%');
});

test('every image tool is an ordinary gallery card from the shared tool-card component, not a special family card', () => {
  // One component renders every tool, so the image tools share the layout, icon, favourite star and Open Tool link.
  assert.doesNotMatch(indexHtml, /imageToolsCardMarkup|data-image-tools-card|data-image-tool-link/, 'the family card is gone');
  const gallery = indexHtml.match(/const cardsFor = items => [^\n]*/)?.[0] || '';
  assert.match(gallery, /items\.map\(item => toolCardMarkup\(item\)\)\.join\(''\)/, 'every item goes through toolCardMarkup');
  assert.doesNotMatch(gallery, /filter|image-tools/, 'no tool is pulled out of the grid');
  for (const id of IMAGE_IDS) {
    const destination = context.officekitToolDestination(id);
    assert.equal(destination.tab, 'image-tools', `${id} opens the image-tools tab`);
    assert.equal(destination.sliceView, SLUGS[id], `${id} opens its own view`);
  }
  // Each card opens its tool through the shared handlers.
  assert.match(indexHtml, /querySelectorAll\('\[data-open-tool\]'\)[\s\S]{0,160}selectSearchTool\(button\.dataset\.openTool\)/);
  assert.match(indexHtml, /querySelectorAll\('\[data-card-tool\]'\)[\s\S]{0,200}selectSearchTool\(card\.dataset\.cardTool\)/);
});

test('palette refresh and failure keep the shared dock while clearing stale exports', () => {
  const load = sliceSource.match(/async function loadPalette\(root\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(load, 'palette loader exists');
  assert.match(load, /state\.palette = null;\s*target\.innerHTML = dock\('Sampling colours…', \[\]\);/);
  assert.match(load, /catch \(error\) \{\s*target\.innerHTML = dock\(error\.message, \[\], '', 'alert', 'ok-image-error'\);\s*\/\/ A 422 from palette sampling[\s\S]*?if \(error\.status === 422\) target\.querySelector\('\[role="alert"\]'\)\?\.setAttribute\('data-officekit-no-bug-report', ''\);/);
  assert.match(sliceSource, /function dock\(status, buttons, control = '', statusRole = 'status', statusClass = ''\)[\s\S]*?role="\$\{statusRole\}"/);
});

test('EXIF refresh and failure keep the shared dock and clear stale private report state', () => {
  const load = sliceSource.match(/async function loadMetadata\(root, includeLocation\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(load, 'metadata loader exists');
  assert.match(load, /state\.metadata = null;\s*state\.includeLocation = includeLocation;\s*target\.innerHTML = dock\('Reading image metadata…', \[\]\);/);
  assert.match(load, /catch \(error\) \{\s*target\.innerHTML = dock\(error\.message, \[\], '', 'alert', 'ok-image-error'\);\s*if \(\[400, 413, 415, 422\]\.includes\(Number\(error\?\.status\)\)\) \{\s*target\.querySelector\('\[role="alert"\]'\)\?\.setAttribute\('data-officekit-no-bug-report', ''\);/);
});

test('file-to-URI encoding keeps the shared dock and clears stale copy/save data', () => {
  const encode = sliceSource.match(/async function encodeUri\(root\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(encode, 'data URI encoder exists');
  assert.match(encode, /state\.dataUri = null;\s*target\.innerHTML = dock\('Encoding image as text…', \[\]\);/);
  assert.match(encode, /catch \(error\) \{\s*target\.innerHTML = dock\(error\.message, \[\], '', 'alert', 'ok-image-error'\);/);
});

test('decode failures stay editable and use the shared action status', () => {
  const decode = sliceSource.match(/async function decodeUri\(root\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(decode, 'URI decoder exists');
  assert.match(decode, /catch \(error\) \{\s*const input = root\.querySelector\('\[data-param="data_uri"\]'\);[\s\S]*?input\?\.setAttribute\('aria-invalid', 'true'\);[\s\S]*?setStatus\(error\.message, \{ error: true \}\);/);
  const bind = sliceSource.match(/function bindDataUri\(root\) \{[\s\S]*?\n  \}/)?.[0];
  assert.match(bind, /if \(save\) save\.disabled = !check\.ok;/);
  assert.match(bind, /if \(check\.ok\) event\.target\.removeAttribute\('aria-invalid'\);/);
  assert.match(bind, /Paste a base64 image data URI to save it\./);
});

test('a changed Difference result shows the three stat tiles from the approved mock', () => {
  const result = { comparable: true, changed_pixels: 12288, changed_ratio: 0.004096, threshold: 8, max_channel_delta: 214, a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 }, difference_png: 'data:image/png;base64,AAAA' };
  const markup = api.comparisonMarkup(result, { mode: 'diff' }).toString();
  assert.equal((markup.match(/class="image-tools__stat"/g) || []).length, 3, 'three stat tiles');
  assert.match(markup, /<b>0\.41%<\/b>pixels changed &gt; 8/);
  assert.match(markup, /<b>12 288<\/b>of 3 000 000/);
  assert.match(markup, /<b>214<\/b>max channel delta/);
  assert.doesNotMatch(markup, /pixels differ by more than/, 'the single sentence is replaced');
  assert.ok(visibleButtons(markup).length <= 3);
});

test('a zero-change result keeps the approved sentence and shows no stat tiles', () => {
  const markup = api.comparisonMarkup({ comparable: true, changed_pixels: 0, changed_ratio: 0, threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 } }, { mode: 'diff' }).toString();
  assert.match(markup, /No pixel differed by more than 8 at 2000 × 1500\./);
  assert.doesNotMatch(markup, /image-tools__stat/);
});

// Lets a test wait for the promise that bind() starts (runComparison) to settle.
const settle = () => new Promise(resolve => setImmediate(resolve));

// A stub compare root with the elements bind() and renderComparison() use, and a way to press a mode tab.
test('difference maps scale to the available width while preserving their pixel grid', () => {
  assert.match(sliceStyles, /\.image-tools__compare-visual img\s*\{[^}]*width:\s*min\(100%,\s*640px\)[^}]*max-height:\s*45vh[^}]*object-fit:\s*contain[^}]*image-rendering:\s*pixelated/);
  const start = sliceSource.indexOf('function renderComparison');
  const end = sliceSource.indexOf('async function runComparison', start);
  const renderRoutine = sliceSource.slice(start, end);
  assert.match(renderRoutine, /img\[alt="Difference map"\]/);
  assert.match(renderRoutine, /differenceMap\.scrollIntoView\(\{ block: 'nearest' \}\)/);
});

function compareRoot() {
  const control = { hidden: false };
  const output = { textContent: '' };
  const visual = { innerHTML: '', textContent: '', querySelector() { return null; } };
  const summary = { innerHTML: '', textContent: '' };
  const buttons = ['side', 'overlay', 'diff'].map(mode => ({ dataset: { mode }, setAttribute() {}, addEventListener(type, handler) { this.onClick = handler; } }));
  const elements = {
    '[data-role="threshold-control"]': control,
    '[data-role="threshold-output"]': output,
    '[data-role="compare-visual"]': visual,
    '[data-role="compare-result"]': summary,
  };
  const root = {
    listeners: {},
    querySelector: selector => elements[selector],
    querySelectorAll: selector => (selector === '[data-mode]' ? buttons : []),
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
  };
  return { root, control, visual, summary, press: mode => buttons.find(button => button.dataset.mode === mode).onClick() };
}

test('the changed region is written as inclusive pixel ranges under the stat tiles', () => {
  const result = { comparable: true, changed_pixels: 12288, changed_ratio: 0.004096, threshold: 8, max_channel_delta: 214, changed_bbox: [1180, 420, 1321, 561], a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 } };
  const markup = api.comparisonMarkup(result, { mode: 'diff' }).toString();
  assert.match(markup, /Changes are in the region x 1180–1320, y 420–560\./);
  assert.notEqual(markup.indexOf('image-tools__stats'), -1, 'the stat tiles are present');
  assert.ok(markup.indexOf('image-tools__stats') < markup.indexOf('Changes are in the region'), 'the region line follows the tiles');
  // The region sentence and the note share one muted paragraph (UX-22).
  assert.match(markup, /<p class="muted">Changes are in the region x 1180–1320, y 420–560\. Results describe pixels/);
  const none = api.comparisonMarkup({ ...result, changed_bbox: null }, { mode: 'diff' }).toString();
  assert.doesNotMatch(none, /Changes are in the region/);
});

test('a size mismatch shows the approved dock with Save disabled, within three buttons', () => {
  const mismatch = { comparable: false, reason: 'size_mismatch', threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 1000, h: 750 } };
  const markup = api.comparisonMarkup(mismatch, { mode: 'diff' }).toString();
  assert.match(markup, /ok-action-dock__status[^>]*>Waiting for a choice\.</);
  assert.match(markup, /data-action="save-diff" disabled/);
  assert.ok(visibleButtons(markup).length <= 3, `${visibleButtons(markup).length} buttons`);
});

test('the threshold slider sits outside the compare result, so a re-render cannot drop its focus', () => {
  const result = { comparable: true, changed_pixels: 3, changed_ratio: 0.1, threshold: 8, a: { w: 2, h: 2 }, b: { w: 2, h: 2 }, difference_png: 'data:image/png;base64,AAAA' };
  // renderComparison replaces the result element, so a slider inside that markup would be destroyed on every change.
  assert.doesNotMatch(api.comparisonMarkup(result, { mode: 'diff' }).toString(), /data-param="threshold"/);
  const view = api.viewMarkup('compare', loaded).toString();
  assert.equal(view.split('data-param="threshold"').length - 1, 1, 'one threshold slider in the view');
  // Approved order: the difference image, then the threshold, then the stats and note.
  const visual = view.indexOf('data-role="compare-visual"');
  const slider = view.indexOf('data-param="threshold"');
  const summary = view.indexOf('data-role="compare-result"');
  assert.ok(visual > -1 && visual < slider && slider < summary, 'order: visual, threshold, summary');
});

// Fires the listeners that bind() attached to a stub root, with the given event target.
function dispatch(root, type, target) {
  for (const handler of root.listeners[type] || []) handler({ target, preventDefault() {}, stopPropagation() {} });
}

test('the compare view binds its threshold readout and shows the slider only in Difference mode', () => {
  const thresholdControl = { hidden: false };
  const output = { textContent: '' };
  const result = { textContent: '', innerHTML: '' };
  const modeButton = mode => ({ dataset: { mode }, setAttribute() {}, addEventListener(type, handler) { this.onClick = handler; } });
  const buttons = ['side', 'overlay', 'diff'].map(modeButton);
  const slider = { dataset: { param: 'threshold' }, value: '8' };
  const root = {
    listeners: {},
    querySelector: selector => ({
      '[data-role="threshold-control"]': thresholdControl,
      '[data-role="threshold-output"]': output,
      '[data-role="compare-result"]': result,
    })[selector],
    querySelectorAll: selector => (selector === '[data-mode]' ? buttons : []),
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
  };
  api.bindView('compare', root);
  // Checked before any click: the mount-time line is the only thing that hides the slider on first open.
  assert.equal(thresholdControl.hidden, true, 'hidden on mount in the default Side by side');
  const press = mode => buttons.find(button => button.dataset.mode === mode).onClick();

  press('side');
  assert.equal(thresholdControl.hidden, true, 'hidden in Side by side');
  press('overlay');
  assert.equal(thresholdControl.hidden, true, 'hidden in Overlay');
  press('diff');
  assert.equal(thresholdControl.hidden, false, 'shown in Difference');

  slider.value = '42';
  dispatch(root, 'input', slider);
  assert.equal(output.textContent, '42', 'readout follows the slider while it moves (input)');
  slider.value = '60';
  dispatch(root, 'change', slider);
  assert.equal(output.textContent, '60', 'readout follows the released value (change)');
});

// These two change the shared view state (a mismatch result, a Difference mode), so they run after the bind test above.
test('a size mismatch keeps the threshold slider hidden even in Difference mode', async () => {
  const mismatch = { comparable: false, reason: 'size_mismatch', threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 1000, h: 750 } };
  context.fetch = async () => ({ ok: true, json: async () => mismatch });
  try {
    const view = compareRoot();
    api.bindView('compare', view.root, { a: file('a.png'), b: file('b.png') });
    await settle();
    view.press('diff');
    assert.equal(view.control.hidden, true, 'hidden for a mismatch in Difference mode');
    assert.match(String(view.visual.innerHTML), /The images are different sizes/);
    const dockMarkup = String(view.summary.innerHTML);
    assert.match(dockMarkup, /Waiting for a choice\./, 'the approved mismatch dock status');
    assert.match(dockMarkup, /data-action="save-diff" disabled/, 'Save is disabled for a mismatch');
  } finally {
    delete context.fetch;
  }
});

test('a mismatch that arrives after a comparable result hides the slider without a click (QA-13)', async () => {
  const comparable = { comparable: true, changed_pixels: 12288, changed_ratio: 0.004096, threshold: 8, max_channel_delta: 214, a: { w: 2000, h: 1500 }, b: { w: 2000, h: 1500 }, difference_png: 'data:image/png;base64,AAAA' };
  const mismatch = { comparable: false, reason: 'size_mismatch', threshold: 8, a: { w: 2000, h: 1500 }, b: { w: 1000, h: 750 } };
  let next = comparable;
  context.fetch = async () => ({ ok: true, json: async () => next });
  try {
    const first = compareRoot();
    api.bindView('compare', first.root, { a: file('a.png'), b: file('b.png') });
    await settle();
    first.press('diff');
    assert.equal(first.control.hidden, false, 'shown for a comparable Difference result');

    next = mismatch;
    const second = compareRoot();
    api.bindView('compare', second.root, { a: file('a.png'), b: file('b.png') });
    await settle();
    // No press: the hide comes from renderComparison when the mismatch result arrives.
    assert.equal(second.control.hidden, true, 'hidden once the mismatch result renders, with no click');
  } finally {
    delete context.fetch;
  }
});

test('a failed comparison clears stale output and keeps an accessible dock with saving disabled', async () => {
  const message = 'Images could not be compared. Check the files and try again.';
  context.fetch = async () => { throw new Error(message); };
  try {
    const view = compareRoot();
    view.visual.textContent = 'stale image';
    api.bindView('compare', view.root, { a: file('a.png'), b: file('b.png') });
    await settle();
    const dock = view.summary.innerHTML.toString();
    assert.match(dock, /ok-action-dock/);
    assert.match(dock, /role="alert"/);
    assert.match(dock, /Images could not be compared/);
    assert.match(dock, /data-action="save-diff" disabled/);
    assert.equal(view.visual.textContent, '', 'the stale visual is cleared');
  } finally {
    delete context.fetch;
  }
});

test('the workbench stylesheet hides the rail below 761 px and shows the menu', () => {
  assert.match(sliceStyles, /@media \(max-width: 760px\)/);
  // The field is display:grid, which beats the user-agent [hidden] rule, so the hidden attribute needs its own rule.
  assert.match(sliceStyles, /\.image-tools__field\[hidden\] \{ display: none; \}/);
  assert.match(sliceStyles, /\.image-tools__rail \{ display: none; \}/);
});
