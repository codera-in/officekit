import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { sliceAssetPath } from '../scripts/tool-catalog.mjs';

// QA-12, ARCH-5: the live index.html wiring of the slice gates. The handlers below are read out of index.html
// by name and run against a small fake DOM with the real slice module loaded beside them. The unit tests in
// pdf-tools-ui.test.mjs only reach the pure slice functions, so these checks cover the calls made from the shell.
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = relative => fs.readFileSync(path.join(repoRoot, relative), 'utf8');
const html = read('index.html');
const sliceSource = read(sliceAssetPath('pdf_tools'));
const formattersSource = read('assets/officekit-formatters.js');

const SLICE_KEYS = ['rotate', 'images-to-pdf', 'metadata-view', 'watermark', 'page-numbers', 'resize-pages', 'grayscale', 'flatten'];

// Pulls one top-level function out of index.html by brace matching. The handlers under test have no braces
// inside string literals, so the scan is exact for them, and vm parses the result.
function extractFunction(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} is declared in index.html`);
  let depth = 0;
  for (let index = html.indexOf('{', start); index < html.length; index += 1) {
    if (html[index] === '{') depth += 1;
    else if (html[index] === '}') {
      depth -= 1;
      if (depth === 0) return html.slice(start, index + 1);
    }
  }
  throw new Error(`${name} has no closing brace`);
}

class FakeElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.listeners = {};
    this.classes = new Set();
    this.textContent = '';
    this.className = '';
    this.disabled = false;
    this.tabIndex = -1;
    this.attributes = {};
  }
  get classList() {
    const classes = this.classes;
    return {
      toggle: (name, force) => {
        const on = force ?? !classes.has(name);
        if (on) classes.add(name); else classes.delete(name);
        return on;
      },
      contains: name => classes.has(name),
    };
  }
  append(...nodes) { for (const node of nodes) this.children.push(node); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type, event) { for (const listener of this.listeners[type] || []) listener(event); }
}

function file(name, size = 10, type = name.endsWith('.pdf') ? 'application/pdf' : 'image/png') {
  return { name, size, type };
}

// Loads the real slice and the four index.html handlers into one vm context. Everything else the handlers read
// is a stub that records what it was asked to do.
function loadShell({ tool, files = [] }) {
  const elements = {};
  const element = id => (elements[id] ||= new FakeElement('div'));
  const statuses = [];
  const context = {
    console,
    Blob,
    URL: { revokeObjectURL() {} },
    document: { getElementById: element, createElement: tag => new FakeElement(tag) },
    pdfThumbUrls: [],
    pdfSelectedFiles: [...files],
    activePdfTool: tool,
    pdfPhase: 'idle',
    pdfOutputBlob: null,
    pdfTablePreview: null,
    pdfTableSelection: '',
    PDF_DOWNLOAD_PRIMARY: 'primary-download',
    PDF_DOWNLOAD_SECONDARY: 'secondary-download',
    imageThumbnail: () => new FakeElement('img'),
    clearPdfWorkbenchOutput() {},
    setPdfWorkbenchStatus(text, isError) { statuses.push({ text, isError: Boolean(isError) }); },
    renderPdfPreview() {},
    renderPdfOptions() {},
    resetPdfPageManagement() {},
    initializePdfPageManagement() {},
    isPdfPageManagementTool: () => false,
    updatePdfProtectPasswordState: () => true,
    updatePdfUnlockPasswordState: () => true,
    pdfSliceShell: () => ({ tool: context.activePdfTool, files: context.pdfSelectedFiles }),
  };
  context.window = { OfficeKitExtensions: { register() {} } };
  vm.createContext(context);
  vm.runInContext(formattersSource, context, { filename: 'officekit-formatters.js' });
  vm.runInContext(sliceSource, context, { filename: 'officekit-slice-pdf-tools.js' });
  for (const name of ['pdfAcceptsBatch', 'applyPdfDock', 'renderPdfSelection', 'acceptPdfSelection']) {
    vm.runInContext(extractFunction(name), context, { filename: `index.html:${name}` });
  }
  return { context, elements, statuses };
}

function rowNames(context) {
  return Array.from(context.pdfSelectedFiles, entry => entry.name);
}

test('ARCH-5 and QA-12: images rows take Alt+ArrowDown reorder through the live gate, and plain ArrowDown does not', () => {
  const { context, elements } = loadShell({ tool: 'images-to-pdf', files: [file('a.png'), file('b.png'), file('c.png')] });
  context.renderPdfSelection();
  const rows = elements['pdf-workbench-files'].children;
  assert.equal(rows[0].tabIndex, 0, 'image rows are focusable so the keyboard can reorder them');
  let prevented = 0;
  const press = (key, altKey) => ({ key, altKey, preventDefault: () => { prevented += 1; } });
  rows[0].dispatch('keydown', press('ArrowDown', false));
  assert.deepEqual(rowNames(context), ['a.png', 'b.png', 'c.png'], 'plain ArrowDown does not move the row');
  context.renderPdfSelection();
  elements['pdf-workbench-files'].children[0].dispatch('keydown', press('ArrowDown', true));
  assert.deepEqual(rowNames(context), ['b.png', 'a.png', 'c.png'], 'Alt+ArrowDown moves the first row down');
  assert.equal(prevented, 1, 'only the Alt arrow prevents the default scroll');
});

test('QA-12: merge rows take no Alt reorder, because the live gate is closed for every task but images', () => {
  const { context, elements } = loadShell({ tool: 'merge', files: [file('one.pdf'), file('two.pdf'), file('three.pdf')] });
  context.renderPdfSelection();
  const rows = elements['pdf-workbench-files'].children;
  assert.equal(rows[0].tabIndex, -1, 'merge rows are not focusable for reordering');
  assert.deepEqual(rows[0].listeners.keydown, undefined, 'no reorder handler is attached to merge rows');
  rows[0].dispatch('keydown', { key: 'ArrowDown', altKey: true, preventDefault() {} });
  assert.deepEqual(rowNames(context), ['one.pdf', 'two.pdf', 'three.pdf'], 'Alt+ArrowDown leaves merge order unchanged');
});

test('QA-12: the generic output preview is hidden for each slice task and shown for merge', () => {
  for (const key of SLICE_KEYS) {
    const { context, elements } = loadShell({ tool: key });
    context.applyPdfDock();
    assert.equal(elements['pdf-workbench-preview'].classes.has('hidden'), true, `${key} hides the generic preview`);
  }
  const { context, elements } = loadShell({ tool: 'merge' });
  context.applyPdfDock();
  assert.equal(elements['pdf-workbench-preview'].classes.has('hidden'), false, 'merge keeps the generic preview');
});

test('QA-12: image batches are checked by the slice, and PDF tasks by the shell rules that remain', () => {
  const { context, statuses } = loadShell({ tool: 'images-to-pdf' });
  const full = Array.from({ length: 200 }, (_, index) => file(`scan-${index}.png`));
  context.acceptPdfSelection(full);
  assert.equal(context.pdfSelectedFiles.length, 200, 'a 200-image batch is accepted');
  context.acceptPdfSelection([file('extra.png')]);
  assert.equal(context.pdfSelectedFiles.length, 200, 'the 201st image is refused');
  assert.equal(statuses.at(-1).text, 'Images to PDF accepts no more than 200 images.', 'the refusal copy comes from the slice');
  assert.equal(statuses.at(-1).isError, true);

  const merge = loadShell({ tool: 'merge' });
  merge.context.acceptPdfSelection(Array.from({ length: 21 }, (_, index) => file(`part-${index}.pdf`)));
  assert.equal(merge.statuses.at(-1).text, 'Merge accepts no more than 20 PDF files.', 'merge keeps its own shell copy');
});

test('ARCH-5: the images limit line comes from the slice, and index.html keeps no copy of the cap', () => {
  assert.doesNotMatch(html, /Choose 1–200/, 'index.html has no literal images limit');
  assert.match(html, /window\.OfficeKitPdfSlice\?\.limitFor\(activePdfTool\) \?\? copy\.limit/, 'the shell reads the limit from the slice');
});

test('QA-12: the three slice gates are called with these exact arguments in index.html', () => {
  assert.equal(html.split('window.OfficeKitPdfSlice?.reordersRows(activePdfTool)').length - 1, 1, 'one reorder gate');
  assert.equal(html.split('window.OfficeKitPdfSlice.keyboardMove(event, pdfSelectedFiles, index)').length - 1, 1, 'one keyboard move call');
  assert.equal(html.split('!slice?.workbenchPreviewVisible(activePdfTool)').length - 1, 1, 'one preview gate');
  assert.equal(html.split('window.OfficeKitPdfSlice.acceptFiles(activePdfTool, pdfSelectedFiles, incoming)').length - 1, 1, 'one accept delegation');
});
