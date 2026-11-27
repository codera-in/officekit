import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = readFileSync(path.join(root, 'assets/officekit.input.css'), 'utf8');
const backend = readFileSync(path.join(root, 'officekit/engines/engine_file_converter.py'), 'utf8');
const mock = readFileSync(path.join(root, 'design/mocks/file-converter-format-matrix.html'), 'utf8');
const transparencyMock = readFileSync(path.join(root, 'design/mocks/image-transparency-conversion.html'), 'utf8');
const planSource = html.match(/function officekitGetConversionPlan\([\s\S]*?\n        \}/)?.[0];
const selectionSource = html.match(/function handleGenericFileSelect\(file\) \{[\s\S]*?\n        \}/)?.[0];
const transparencyNoticeSource = html.match(/function updateImageTransparencyNotice\(\) \{[\s\S]*?\n        \}/)?.[0];
const executeSource = html.match(/async function executeGenericConversion\(\) \{[\s\S]*?\n        \}/)?.[0];

function getPlan(name) {
  assert.ok(planSource, 'file converter exposes a pure supported-format plan');
  const context = {};
  vm.runInNewContext(`${planSource}\nglobalThis.getPlan = officekitGetConversionPlan;`, context);
  return JSON.parse(JSON.stringify(context.getPlan(name)));
}

test('format-matrix mock explains valid targets and unsupported-file feedback', () => {
  assert.match(mock, /Before/);
  assert.match(mock, /After/);
  assert.match(mock, /YAML/);
  assert.match(mock, /SQL/);
  assert.match(mock, /unsupported-format/);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('image transparency mock makes target-specific alpha loss clear', () => {
  assert.match(transparencyMock, /Transparency will be flattened/);
  assert.match(transparencyMock, /composites them onto white/);
  assert.match(transparencyMock, /Choose PNG or WebP to keep transparency/);
  assert.doesNotMatch(transparencyMock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('data file targets mirror backend source and output support without unrelated fallbacks', () => {
  const expected = ['csv', 'tsv', 'xlsx', 'json', 'yaml', 'html', 'sql'];
  const aliases = { tab: 'tsv', yml: 'yaml' };
  for (const source of ['csv', 'txt', 'tsv', 'tab', 'xlsx', 'xls', 'json', 'yaml', 'yml']) {
    const plan = getPlan(`report.${source}`);
    assert.equal(plan.kind, 'data');
    assert.deepEqual(plan.targets, expected.filter(format => format !== (aliases[source] || source)));
  }
  assert.deepEqual(getPlan('archive.zip'), { kind: 'archive', targets: [] });
  assert.deepEqual(getPlan('unknown.dat'), { kind: 'unsupported', targets: [] });
  assert.deepEqual(getPlan('no-extension'), { kind: 'unsupported', targets: [] });
});

test('image file targets cover supported inputs and exclude the same output format', () => {
  const expected = ['jpg', 'png', 'webp', 'bmp', 'ico', 'tiff', 'pdf'];
  const sameFormat = { jpg: ['jpg'], jpeg: ['jpg'], png: ['png'], webp: ['webp'], bmp: ['bmp'], ico: ['ico'], tif: ['tiff'], tiff: ['tiff'] };
  for (const source of ['svg', 'jpg', 'jpeg', 'png', 'webp', 'bmp', 'ico', 'tif', 'tiff', 'gif']) {
    const plan = getPlan(`picture.${source}`);
    assert.equal(plan.kind, 'image');
    assert.deepEqual(plan.targets, expected.filter(format => !sameFormat[source]?.includes(format)));
  }
  assert.deepEqual(getPlan('photo.avif'), { kind: 'unsupported', targets: [] });
  assert.deepEqual(getPlan('logo.svg').targets, expected, 'SVG exposes every supported image output');
});

test('UI capability labels stay aligned with the actual converter engines', () => {
  assert.match(backend, /elif target_ext == 'sql'/);
  assert.match(html, /<h1[^>]*>\s*Convert a file\s*<\/h1>/);
  assert.match(html, /id="converter-status"/);
  assert.match(html, /async function officekitRasterizeSvg\(file\)/);
  assert.match(html, /allowedElements = new Set\(\['svg'/);
  assert.match(html, /Convert to \$\{selectedTargetFormat/);
  assert.match(html, /svg-conversion-note/);
  assert.match(html, /<div id="format-selection"[\s\S]*?<\/div>[\s\S]*?id="converter-action-dock"[\s\S]*?id="converter-status"/, 'conversion status and actions must stay visible in the shared dock outside hidden format options');
  assert.match(html, /id="converter-action-controls"[\s\S]*?id="convert-btn"/);
  assert.match(html, /const panel=document\.getElementById\('converter-action-controls'\);[\s\S]*?officekitPublish(?:Text|Binary)Result\(panel/);
  assert.match(html, /officekitGetConversionPlan\(file\.name\)/);
  assert.match(html, /function executeGenericConversion\([\s\S]*?officekitGetConversionPlan\(/);
  assert.match(html, /generic-file-input"[^>]*accept="[^"]*\.yaml/);
  assert.match(html, /id="xlsx-sheet-panel"[\s\S]*?id="converter-xlsx-sheet"/);
  assert.match(html, /function loadXlsxSheetNames\(file\)[\s\S]*?option\.textContent = name/);
  assert.match(html, /formData\.append\('sheet_name', selectedXlsxSheetName\)/);
  assert.match(html, /id="converter-null-token-panel"[\s\S]*?id="converter-null-token-enabled"/);
  assert.match(html, /formData\.append\('null_token', nullMarker\)/);
  assert.match(html, /id="converter-image-preview-panel"[\s\S]*?id="converter-image-preview"/);
  assert.match(styles, /\.ok-image-converter-preview__stage[\s\S]*?conic-gradient/);
  assert.match(html, /function clearGenericImagePreview\([\s\S]*?URL\.revokeObjectURL\(genericImagePreviewUrl\)/);
  assert.match(html, /function updateGenericImagePreview\(file\)[\s\S]*?officekitRasterizeSvg\(file\)/);
});

test('selection renders only valid targets and rejects unknown extensions before enabling conversion', () => {
  assert.ok(planSource && selectionSource && transparencyNoticeSource, 'file selection and format plan are available');
  const children = [];
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      id, textContent: '', innerHTML: '', className: '', hidden: false, setAttribute() {}, classList: {
        add() {}, remove() {}, toggle() {},
      },
      replaceChildren() {}, querySelector() { return null; },
    });
    return elements.get(id);
  };
  const context = {
    document: {
      getElementById: element,
      createElement: tag => ({ tag, className: '', textContent: '', type: '', onclick: null, setAttribute() {} }),
    },
  };
  const setup = `let selectedGenericFile = null; let selectedTargetFormat = null; let genericConversionRequestSequence = 0; let selectedXlsxSheetName = null; let selectedXlsxSheetNames = []; let xlsxSheetRequestSequence = 0; let zipWorkspaceId = null; let zipArchiveName = null; let zipArtifactId = null; const xlsxSheetPanel = document.getElementById('xlsx-sheet-panel'); const xlsxSheetSelect = document.getElementById('converter-xlsx-sheet'); const xlsxSheetRetry = document.getElementById('xlsx-sheet-retry'); const converterNullTokenEnabled = document.getElementById('converter-null-token-enabled'); const converterNullTokenInput = document.getElementById('converter-null-token'); function clearGenericImagePreview() {} function updateGenericImagePreview() {} function resetGenericConversionActionState() {} function officekitIsPrivateBeta() { return false; } function officekitReleaseAllowsTool() { return false; } ${planSource} function setGenericConverterStatus(message, isError = false) { const status = document.getElementById('converter-status'); status.textContent = message; status.className = isError ? 'error' : 'ok'; } ${transparencyNoticeSource} ${selectionSource} const container = document.getElementById('format-options'); container.appendChild = child => ${'children'}.push(child);`;
  const csvRun = { ...context, children };
  vm.runInNewContext(`${setup} handleGenericFileSelect({ name: 'ledger.csv', size: 1024 }); globalThis.selectedFile = selectedGenericFile; globalThis.target = selectedTargetFormat;`, csvRun);
  assert.equal(children.map(button => button.textContent).join(','), 'TSV,XLSX,JSON,YAML,HTML,SQL');
  assert.equal(csvRun.target, 'xlsx', 'CSV should default to the spreadsheet output shown in the mock');
  assert.equal(element('image-transparency-notice').hidden, true, 'tabular conversion must not show image format guidance');
  assert.equal(element('converter-null-token-panel').hidden, false, 'tabular inputs should expose the optional null marker');
  assert.equal(element('converter-status').textContent, 'Tabular data · 6 supported output formats.');

  const svgChildren = [];
  vm.runInNewContext(`${setup} handleGenericFileSelect({ name: 'logo.svg', size: 1024 }); globalThis.target = selectedTargetFormat; globalThis.label = document.getElementById('convert-btn').textContent; globalThis.noteHidden = document.getElementById('svg-conversion-note').hidden;`, { ...context, children: svgChildren });
  assert.equal(svgChildren.map(button => button.textContent).join(','), 'JPEG,PNG,WEBP,BMP,ICO,TIFF,PDF');
  assert.equal(element('convert-btn').textContent, 'Convert to PNG');
  assert.equal(element('svg-conversion-note').hidden, false);
  assert.equal(element('converter-status').textContent, 'Image · 7 supported output formats.');

  vm.runInNewContext(`${setup} handleGenericFileSelect({ name: 'ledger.unknown', size: 1024 }); globalThis.selectedFile = selectedGenericFile; globalThis.target = selectedTargetFormat;`, { ...context, children: [] });
  assert.equal(element('converter-status').textContent, 'This file type is not supported. Choose an image or tabular file, or a ZIP archive.');
  assert.equal(element('converter-null-token-panel').hidden, true, 'unsupported inputs should hide data-only options');
});

test('transparency guidance follows the selected target and hides for data sources', () => {
  assert.ok(planSource && transparencyNoticeSource, 'the visibility guard and format plan are available');
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { hidden: false, classList: { toggle() {} } });
    return elements.get(id);
  };
  const context = { document: { getElementById: element } };
  vm.runInNewContext(`let selectedGenericFile = { name: 'photo.png' }; let selectedTargetFormat = 'jpg'; ${planSource} ${transparencyNoticeSource} updateImageTransparencyNotice();`, context);
  assert.equal(element('image-transparency-notice').hidden, false);
  vm.runInNewContext(`selectedTargetFormat = 'webp'; updateImageTransparencyNotice();`, context);
  assert.equal(element('image-transparency-notice').hidden, true);
  vm.runInNewContext(`selectedGenericFile = { name: 'records.csv' }; selectedTargetFormat = 'jpg'; updateImageTransparencyNotice();`, context);
  assert.equal(element('image-transparency-notice').hidden, true);
});

test('execution refuses a stale or forged target before making an API request', async () => {
  assert.ok(planSource && executeSource, 'the format guard and conversion handler are available');
  let requestCount = 0;
  const status = { textContent: '', className: '' };
  const context = {
    fetch: async () => { requestCount += 1; throw new Error('must not call API'); },
    FormData: class { append() {} },
    document: { getElementById: () => status },
  };
  vm.runInNewContext(`let selectedGenericFile = { name: 'ledger.csv' }; let selectedTargetFormat = 'pdf'; let genericConversionRequestSequence = 0; ${planSource} function setGenericConverterStatus(message, isError) { document.getElementById('converter-status').textContent = message; } ${executeSource} globalThis.convert = executeGenericConversion;`, context);
  await context.convert();
  assert.equal(requestCount, 0);
  assert.match(status.textContent, /not available for this file/i);
});
