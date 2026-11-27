import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('function applyPdfDock(');
assert.notEqual(start, -1, 'applyPdfDock is declared in index.html');
let depth = 0;
let end = -1;
for (let index = html.indexOf('{', start); index < html.length; index += 1) {
  if (html[index] === '{') depth += 1;
  else if (html[index] === '}' && --depth === 0) { end = index + 1; break; }
}
assert.notEqual(end, -1, 'applyPdfDock has a closing brace');

class Element {
  constructor() { this.classes = new Set(); this.className = ''; this.textContent = ''; }
  classList = { toggle: (name, force) => force ? this.classes.add(name) : this.classes.delete(name) };
}

function dockForOutput(output) {
  const elements = Object.fromEntries(['pdf-workbench-run', 'pdf-workbench-download', 'pdf-slice-copy', 'pdf-workbench-preview']
    .map(id => [id, new Element()]));
  const context = {
    Blob,
    activePdfTool: 'metadata',
    pdfPhase: output ? 'complete' : 'idle',
    pdfOutputBlob: output,
    pdfTablePreview: null,
    PDF_DOWNLOAD_PRIMARY: 'primary',
    PDF_DOWNLOAD_SECONDARY: 'secondary',
    document: { getElementById: id => elements[id] },
    window: { OfficeKitPdfSlice: { isOperation: () => false, dockFor: () => [], workbenchPreviewVisible: () => false } },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context);
  context.applyPdfDock();
  return elements;
}

test('PDF metadata result hides the create action so the shared dock can show result actions', () => {
  const ready = dockForOutput(new Blob(['valid PDF bytes'], { type: 'application/pdf' }));
  assert.equal(ready['pdf-workbench-run'].classes.has('hidden'), true);
  const idle = dockForOutput(null);
  assert.equal(idle['pdf-workbench-run'].classes.has('hidden'), false);
});
