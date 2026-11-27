import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');

function sourceOf(name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const source = html.match(new RegExp(`(?:async\\s+)?function ${escaped}\\([^\\n]*\\) \\{[\\s\\S]*?\\n        \\}`))?.[0];
  assert.ok(source, `${name} exists`);
  return source;
}

test('PII tool has a dedicated file selection and review screen in the privacy category', () => {
  assert.match(registry, /"id": "pii_redaction".*"category": "Privacy & Security".*"tab": "pii"/);
  for (const id of ['pii-file-input', 'pii-scan-button', 'pii-review-panel', 'pii-high-list', 'pii-possible-list', 'pii-create-button', 'pii-select-high', 'pii-select-possible']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /accept="\.txt,\.md,\.csv,\.pdf,\.png,\.jpg,\.jpeg,\.webp,\.tif,\.tiff,\.bmp,\.gif,\.docx,\.xlsx,\.pptx"/);
  assert.match(html, /Supported:<\/strong> TXT, MD, CSV, PDF, PNG, JPG\/JPEG, WebP, TIFF\/TIF, BMP, GIF, DOCX, XLSX and PPTX/);
  assert.match(html, /officekitBindPiiRedaction\(\);/);
});

test('Select all possible values control toggles all possible matches and updates selection counts', () => {
  assert.match(html, /id="pii-select-possible"/);
  assert.match(html, /id="pii-select-possible-label"/);
  assert.match(html, /Select all possible values/);

  const updateSource = sourceOf('officekitPiiUpdateSelection');
  assert.ok(updateSource);

  const highBoxes = [{ checked: true }, { checked: true }];
  const possibleBoxes = [{ checked: false }, { checked: false }, { checked: false }];
  const selectHigh = { checked: false, indeterminate: false, disabled: false };
  const selectPossible = { checked: false, indeterminate: false, disabled: false };
  const highCount = { textContent: '' };
  const possibleCount = { textContent: '' };
  const createBtn = { disabled: true };

  const context = {
    piiScanResult: { matches: [] },
    piiScannedFile: { name: 'doc.txt' },
    document: {
      querySelectorAll: selector => {
        if (selector === '[data-pii-confidence="high"]') return highBoxes;
        if (selector === '[data-pii-confidence="possible"]') return possibleBoxes;
        return [];
      },
      getElementById: id => {
        if (id === 'pii-select-high') return selectHigh;
        if (id === 'pii-select-possible') return selectPossible;
        if (id === 'pii-selected-count') return highCount;
        if (id === 'pii-selected-possible-count') return possibleCount;
        if (id === 'pii-create-button') return createBtn;
        return null;
      }
    }
  };

  vm.runInNewContext(updateSource, context);

  // 1. Initially high are checked, possible are unchecked
  context.officekitPiiUpdateSelection();
  assert.equal(selectHigh.checked, true);
  assert.equal(selectHigh.indeterminate, false);
  assert.equal(selectPossible.checked, false);
  assert.equal(selectPossible.indeterminate, false);
  assert.equal(highCount.textContent, '2 selected');
  assert.equal(possibleCount.textContent, '0 selected');

  // 2. User checks all possible items
  possibleBoxes.forEach(box => { box.checked = true; });
  context.officekitPiiUpdateSelection();
  assert.equal(selectPossible.checked, true);
  assert.equal(selectPossible.indeterminate, false);
  assert.equal(possibleCount.textContent, '3 selected');

  // 3. User unchecks one possible item -> indeterminate
  possibleBoxes[0].checked = false;
  context.officekitPiiUpdateSelection();
  assert.equal(selectPossible.checked, false);
  assert.equal(selectPossible.indeterminate, true);
  assert.equal(possibleCount.textContent, '2 selected');
});

test('PII scan contract validates response shape, safe identifiers, confidence and locations', () => {
  const context = {
    Object,
    Set,
    Error,
    OFFICEKIT_PII_TYPES: new Set(['email', 'ssn', 'card', 'iban', 'phone', 'passport', 'tax_id', 'person', 'organization', 'address', 'dob', 'date', 'username', 'ip_address']),
  };
  vm.runInNewContext(`${sourceOf('officekitPiiExactKeys')}\n${sourceOf('officekitPiiValidateScan')}`, context);
  const file = { name: 'note.txt' };
  const match = { id: 'a'.repeat(24), type: 'email', label: 'Email address', confidence: 'high', value: 'maya@example.com', location: 'Text' };
  const report = { filename: 'note.txt', format: 'TXT', matches: [match], page_count: null };
  assert.equal(context.officekitPiiValidateScan(report, file), report);
  for (const type of ['username', 'ip_address']) {
    const candidate = { ...match, id: type === 'username' ? 'c'.repeat(24) : 'd'.repeat(24), type };
    assert.equal(context.officekitPiiValidateScan({ ...report, matches: [candidate] }, file).matches[0].type, type);
  }
  const organization = { ...match, id: 'b'.repeat(24), type: 'organization', label: 'Organization or institution · Context match', confidence: 'possible', value: 'Acme Systems LLC' };
  assert.equal(context.officekitPiiValidateScan({ ...report, matches: [organization] }, file).matches[0].type, 'organization');
  assert.throws(() => context.officekitPiiValidateScan({ ...report, matches: [{ ...match, id: 'unsafe' }] }, file));
  assert.throws(() => context.officekitPiiValidateScan({ ...report, matches: [match, match] }, file));
  assert.throws(() => context.officekitPiiValidateScan({ ...report, matches: [{ ...match, confidence: 'certain' }] }, file));
  assert.throws(() => context.officekitPiiValidateScan({ ...report, filename: 'other.txt' }, file));
});

test('high-confidence defaults are selected and possible items remain opt-in', () => {
  const row = sourceOf('officekitPiiMatchRow');
  assert.match(row, /checkbox\.checked = match\.confidence === 'high'/);
  assert.match(row, /checkbox\.dataset\.piiMatchId = match\.id/);
  assert.match(html, /High confidence · selected by default/);
  assert.match(html, /Not selected · review before masking/);
  assert.match(html, /Your original file stays unchanged/);
});

test('PDF review renders a local page image instead of relying on the WebView PDF iframe', async () => {
  const file = { name: 'statement.pdf' };
  const preview = { children: [], replaceChildren() { this.children = []; }, append(child) { this.children.push(child); } };
  const metadata = { textContent: '' };
  const context = {
    document: {
      getElementById: id => id === 'pii-preview' ? preview : metadata,
      createElement: tag => ({ tag, className: '', src: '', alt: '', textContent: '' }),
    },
    piiScannedFile: file,
    officekitPiiFileType: selected => selected.name.split('.').pop().toUpperCase(),
    officekitGetPdfPageThumbnails: async (selected, pages) => {
      assert.equal(selected, file);
      assert.equal(Array.from(pages).join(','), '1');
      return { page_count: 2, pages: [{ data_uri: 'data:image/png;base64,cGFnZQ==' }] };
    },
  };
  vm.runInNewContext(sourceOf('officekitPiiRenderPreview'), context);
  await context.officekitPiiRenderPreview(file, { format: 'PDF', page_count: 2 });
  assert.equal(preview.children[0].tag, 'img');
  assert.equal(preview.children[0].src, 'data:image/png;base64,cGFnZQ==');
  assert.equal(preview.children[0].alt, 'Preview of statement.pdf, page 1 of 2');
  assert.doesNotMatch(sourceOf('officekitPiiRenderPreview'), /createElement\('iframe'\)/);
});

test('PDF review explains when local page rendering is unavailable', async () => {
  const file = { name: 'statement.pdf' };
  const preview = { children: [], replaceChildren() { this.children = []; }, append(child) { this.children.push(child); } };
  const context = {
    document: {
      getElementById: id => id === 'pii-preview' ? preview : { textContent: '' },
      createElement: tag => ({ tag, className: '', src: '', alt: '', textContent: '' }),
    },
    piiScannedFile: file,
    officekitPiiFileType: selected => selected.name.split('.').pop().toUpperCase(),
    officekitGetPdfPageThumbnails: async () => { throw new Error('render failed'); },
  };
  vm.runInNewContext(sourceOf('officekitPiiRenderPreview'), context);
  await context.officekitPiiRenderPreview(file, { format: 'PDF', page_count: 2 });
  assert.match(preview.children[0].textContent, /could not be previewed/i);
});

test('contextual possible matches carry a visible source hint without extra API fields', () => {
  const row = sourceOf('officekitPiiMatchRow');
  assert.match(row, /match\.label\.endsWith\(' · Context match'\)/);
  assert.match(row, /badge-warning badge-soft badge-xs/);
  assert.match(row, /Context match · not selected/);
  assert.match(row, /checkbox\.checked = match\.confidence === 'high'/);
});

test('redaction submission uses only checked IDs and downloads a separate copy', () => {
  const createCopy = sourceOf('officekitPiiCreateCopy');
  assert.match(createCopy, /officekitApiUrl\('\/api\/privacy\/pii\/redact'\)/);
  assert.match(createCopy, /JSON\.stringify\(selected\)/);
  assert.match(createCopy, /URL\.createObjectURL\(blob\)/);
  assert.match(createCopy, /officekitPiiOutputFilename\(file, responseName, mode, blob\.type\)/);
  assert.match(createCopy, /officekitPublishBinaryResult\(document\.getElementById\('pii-output-actions'\)/);
  assert.match(createCopy, /source file was not changed/);
  assert.match(createCopy, /body\.append\('mode', mode\)/);
  assert.match(html, /name="pii-mode" value="mask" checked/);
  assert.match(html, /name="pii-mode" value="redact"/);
  assert.match(html, /Mask · keep a little visible/);
  assert.match(html, /Redact · remove completely/);
});

test('PII output keeps its true extension when the response filename is missing or incomplete', () => {
  const context = { officekitPiiFileType: file => file.name.split('.').pop().toUpperCase() };
  vm.runInNewContext(sourceOf('officekitPiiOutputFilename'), context);
  assert.equal(context.officekitPiiOutputFilename({ name: 'records.csv' }, '', 'mask', 'text/csv'), 'records-masked.csv');
  assert.equal(context.officekitPiiOutputFilename({ name: 'badge.jpeg' }, 'badge-masked.jpeg', 'mask', 'image/png'), 'badge-masked.png');
  assert.equal(context.officekitPiiOutputFilename({ name: 'report.pdf' }, 'report-redacted.pdf', 'redact', 'application/pdf'), 'report-redacted.pdf');
});

test('manual editor handoff opens the created image copy and explains non-image limits', () => {
  const handoff = sourceOf('officekitPiiOpenManualEditor');
  assert.match(handoff, /switchTab\('screenshot'\)/);
  assert.match(handoff, /new File\(\[piiOutputBlob\], piiOutputName, \{ type: piiOutputBlob\.type \}\)/);
  assert.match(handoff, /officekitLoadScreenshot/);
  assert.match(html, /Screenshot Editor accepts images/);
  assert.match(html, /id="pii-output-panel"/);
});

test('PII creation and status use the shared bottom action dock', () => {
  const bind = sourceOf('officekitBindPiiRedaction');
  assert.match(html, /<footer id="pii-action-dock" class="ok-action-dock"/);
  assert.match(bind, /pii-action-dock-status'\)\.append\(document\.getElementById\('pii-status'\)\)/);
  assert.match(bind, /pii-action-dock-controls'\)\.append\(document\.getElementById\('pii-create-button'\)\)/);
  assert.match(html, /officekitPublishBinaryResult\(document\.getElementById\('pii-output-actions'\)/);
});

test('screenshot editor exposes the approved image annotation tools', () => {
  for (const tool of ['text', 'highlight', 'circle', 'rectangle']) {
    assert.match(html, new RegExp(`data-screenshot-tool="${tool}"`));
  }
});

test('PII mode switching updates button text and radio styling and allows regenerating copy', () => {
  const updateMode = sourceOf('officekitPiiUpdateMode');
  assert.ok(updateMode, 'officekitPiiUpdateMode exists');

  const button = { textContent: '' };
  const maskLabelClasses = new Set(['border-indigo-200', 'bg-indigo-50']);
  const redactLabelClasses = new Set(['border-slate-200']);

  const maskLabel = {
    classList: {
      toggle(cls, condition) {
        if (condition) maskLabelClasses.add(cls);
        else maskLabelClasses.delete(cls);
      }
    }
  };
  const redactLabel = {
    classList: {
      toggle(cls, condition) {
        if (condition) redactLabelClasses.add(cls);
        else redactLabelClasses.delete(cls);
      }
    }
  };

  const maskRadio = { value: 'mask', checked: true, closest: selector => selector === 'label' ? maskLabel : null };
  const redactRadio = { value: 'redact', checked: false, closest: selector => selector === 'label' ? redactLabel : null };

  const context = {
    piiOutputBlob: null,
    document: {
      querySelector: selector => {
        if (selector === 'input[name="pii-mode"]:checked') {
          return maskRadio.checked ? maskRadio : (redactRadio.checked ? redactRadio : null);
        }
        return null;
      },
      querySelectorAll: selector => {
        if (selector === 'input[name="pii-mode"]') return [maskRadio, redactRadio];
        return [];
      },
      getElementById: id => {
        if (id === 'pii-create-button') return button;
        return null;
      }
    }
  };

  vm.runInNewContext(updateMode, context);

  // Before output creation with mask selected:
  context.officekitPiiUpdateMode();
  assert.equal(button.textContent, 'Create masked copy');
  assert.ok(maskLabelClasses.has('border-indigo-200'));
  assert.ok(redactLabelClasses.has('border-slate-200'));

  // Switch to redact before creation:
  maskRadio.checked = false;
  redactRadio.checked = true;
  context.officekitPiiUpdateMode();
  assert.equal(button.textContent, 'Create redacted copy');
  assert.ok(redactLabelClasses.has('border-indigo-200'));
  assert.ok(maskLabelClasses.has('border-slate-200'));

  // After output creation:
  context.piiOutputBlob = { size: 1024, type: 'text/plain' };
  context.officekitPiiUpdateMode();
  assert.equal(button.textContent, 'Update redacted copy');

  // User changes mind back to mask:
  maskRadio.checked = true;
  redactRadio.checked = false;
  context.officekitPiiUpdateMode();
  assert.equal(button.textContent, 'Update masked copy');

  // Verify officekitPiiCreateCopy retains action dock and does not hide it
  const createCopySource = sourceOf('officekitPiiCreateCopy');
  assert.match(createCopySource, /document\.getElementById\('pii-action-dock'\)\.hidden = false/);
  assert.doesNotMatch(createCopySource, /document\.getElementById\('pii-action-dock'\)\.hidden = true/);
  assert.match(createCopySource, /officekitPiiUpdateMode\(\)/);

  // Verify officekitPiiScan hides import panel
  const scanSource = sourceOf('officekitPiiScan');
  assert.match(scanSource, /document\.getElementById\('pii-import-panel'\)\.hidden = true/);
  assert.match(scanSource, /document\.getElementById\('pii-review-panel'\)\.hidden = false/);
});

