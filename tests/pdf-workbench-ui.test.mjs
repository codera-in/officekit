import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const client = html.match(/\/\* PDF API CLIENT START \*\/([\s\S]*?)\/\* PDF API CLIENT END \*\//)?.[1];

function loadClient(fetchImpl) {
  assert.ok(client, 'PDF API client is isolated for contract tests');
  const context = {
    Blob,
    FormData,
    TextEncoder,
    TextDecoder,
    atob,
    fetch: fetchImpl,
    officekitApiUrl: (value) => `http://127.0.0.1:8000${value}`,
    officekitReadApiResponse: async (response) => {
      if (response.ok) return response;
      throw new Error(response.message || `request failed (${response.status})`);
    },
  };
  vm.runInNewContext(client, context);
  return context;
}

function pdf(name = 'report.pdf', size = 4) {
  const value = new Blob(['x'.repeat(size)], { type: 'application/pdf' });
  Object.defineProperty(value, 'name', { value: name });
  return value;
}

test('PDF workbench exposes the reviewed table extractor beside bank statement export', () => {
  for (const operation of ['merge', 'split', 'compress', 'images', 'delete-pages', 'reorder-pages', 'statement', 'tables', 'text', 'unlock', 'protect', 'metadata']) {
    assert.match(html, new RegExp(`data-pdf-tool="${operation}"`), `${operation} task is discoverable`);
  }
  assert.match(html, /PDF to CSV\/XLS\/XLSX can export a reviewed selectable table or extract transactions from supported bank statements/);
  assert.match(html, /Scanned PDFs and unruled layouts are outside table extraction/);
  assert.match(html, /Only selectable text tables are listed/);
  assert.match(html, /source cell text is preserved/);
  assert.match(html, /id="pdf-table-export-xls"[^>]*>Download XLS<\/button>/);
  assert.match(html, /Legacy Excel \(XLS\)/);
  assert.match(html, /pdf_table_extractor: \{ tab: 'pdf', pdfTool: 'tables' \}/);
  assert.match(html, /password the user already knows/);
  assert.match(html, /data-pdf-tool="delete-pages"[\s\S]*?Delete pages/);
  assert.match(html, /data-pdf-tool="reorder-pages"[\s\S]*?Reorder pages/);
  assert.match(html, /pdf_text_extract: \{ tab: 'pdf', pdfTool: 'text' \}/);
  assert.match(html, /Extract PDF text/);
  assert.match(html, /Scanned image pages are reported; OCR is not included/);
  assert.match(html, /\[Preview shortened\. Download the full extracted text\.\]/);
  assert.match(html, /not secure redaction/);
  assert.match(html, /Alt \+ ↑ \/ Alt \+ ↓/);
  assert.match(html, /function renderPdfPageManagement\(container\)/);
  assert.match(html, /Showing \$\{first\}–\$\{last\} of \$\{pdfPageCount\} pages/);
  assert.match(html, /pageNumbers\.length > 24/);
  assert.match(html, /at least one page must remain/);
  assert.match(html, /pageRanges = compactPdfPageNumbers\(\[\.\.\.pdfDeletedPages\]/);
  assert.match(html, /pageOrder = \[\.\.\.pdfPageOrder\]/);
});

test('PDF text client sends bounded options and validates text bytes and metadata', async () => {
  const calls = [];
  const text = '## Page 2\n\nCafé résumé';
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      headers: { get: name => ({
        'content-type': 'text/markdown; charset=utf-8',
        'content-length': String(new TextEncoder().encode(text).length),
        'x-officekit-page-count': '3',
        'x-officekit-selected-pages': '2',
        'x-officekit-missing-text-pages': '',
        'x-officekit-extracted-characters': '11',
      })[name.toLowerCase()] },
      blob: async () => new Blob([text], { type: 'text/markdown' }),
    };
  });
  const result = await context.officekitExtractPdfText(pdf(), { pageRanges: '2', format: 'md' });
  assert.equal(result.text, text);
  assert.deepEqual(Array.from(result.selectedPages), [2]);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/text');
  assert.equal(calls[0].init.body.get('page_ranges'), '2');
  assert.equal(calls[0].init.body.get('format'), 'md');
});

test('PDF text client rejects unsafe inputs, malformed metadata and non-text downloads', async () => {
  const context = loadClient(async () => ({
    ok: true,
    headers: { get: name => ({
      'content-type': 'text/plain', 'x-officekit-page-count': '1',
      'x-officekit-selected-pages': '1', 'x-officekit-missing-text-pages': '',
      'x-officekit-extracted-characters': '4',
    })[name.toLowerCase()] },
    blob: async () => new Blob(['text']),
  }));
  await assert.rejects(context.officekitExtractPdfText(pdf(), { pageRanges: 'x'.repeat(4097) }), /4,096/);
  await assert.rejects(context.officekitExtractPdfText(pdf(), { format: 'html' }), /plain text or Markdown/);
  await assert.rejects(context.officekitExtractPdfText({ name: 'large.pdf', size: 67_108_865 }), /64 MiB/);
  const malformed = loadClient(async () => ({ ok: true, headers: { get: name => name.toLowerCase() === 'content-type' ? 'text/plain' : 'bad' }, blob: async () => new Blob(['text']) }));
  await assert.rejects(malformed.officekitExtractPdfText(pdf()), /invalid PDF text details/);
  const wrongMime = loadClient(async () => ({ ok: true, headers: { get: name => name.toLowerCase() === 'content-type' ? 'application/pdf' : '1' }, blob: async () => new Blob(['%PDF']) }));
  await assert.rejects(wrongMime.officekitExtractPdfText(pdf()), /invalid text file/);
});

test('PDF table preview client validates bounded DTOs and sends only the selected file', async () => {
  const calls = [];
  const result = { page_count: 3, tables: [{ page_number: 2, table_number: 1, row_count: 2, column_count: 2, preview_rows: [['Code', 'Amount'], ['000042', '1,250.00']] }] };
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return { ok: true, status: 200, headers: { get: (name) => ({ 'content-type': 'application/json', 'content-length': '128' })[name] }, json: async () => result };
  });
  const response = await context.officekitGetPdfTablePreview(pdf());
  assert.equal(response.page_count, 3);
  assert.deepEqual(response.tables[0].preview_rows[1], ['000042', '1,250.00']);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/tables');
  assert.equal(calls[0].init.body.getAll('file').length, 1);
  assert.equal(calls[0].init.body.getAll('page_number').length, 0);

  const invalid = loadClient(async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => ({ page_count: 3, tables: [{ ...result.tables[0], column_count: 1 }] }) }));
  await assert.rejects(invalid.officekitGetPdfTablePreview(pdf()), /valid table preview/);
});

test('PDF table export client validates CSV/XLS/XLSX bytes and selection before requesting', async () => {
  const calls = [];
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    const format = init.body.get('format');
    const isCsv = format === 'csv';
    return {
      ok: true, status: 200,
      headers: { get: (name) => ({
        'content-type': isCsv ? 'text/csv; charset=utf-8' : format === 'xls' ? 'application/vnd.ms-excel' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })[name] },
      blob: async () => new Blob([isCsv ? '\uFEFFA,B\r\n' : format === 'xls' ? Uint8Array.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, 0x42, 0x49, 0x46, 0x46]) : 'PK\u0003\u0004xlsx']),
    };
  });
  const input = pdf();
  const selection = { page_number: 2, table_number: 1 };
  assert.equal((await context.officekitExportPdfTable(input, selection, 'csv')).contentType, 'text/csv');
  assert.equal((await context.officekitExportPdfTable(input, selection, 'xls')).contentType, 'application/vnd.ms-excel');
  assert.equal((await context.officekitExportPdfTable(input, selection, 'xlsx')).contentType, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/tables/export');
  assert.equal(calls[0].init.body.get('page_number'), '2');
  assert.equal(calls[0].init.body.get('table_number'), '1');
  await assert.rejects(context.officekitExportPdfTable(input, selection, 'json'), /CSV, XLS or XLSX/);

  const bad = loadClient(async () => ({ ok: true, status: 200, headers: { get: () => 'text/csv' }, blob: async () => new Blob(['not a csv response']) }));
  await assert.rejects(bad.officekitExportPdfTable(input, selection, 'csv'), /valid table export/);
  const badLegacyXls = loadClient(async () => ({ ok: true, status: 200, headers: { get: () => 'application/vnd.ms-excel' }, blob: async () => new Blob([Uint8Array.from([0x50, 0x4b, 0x03, 0x04, 0x6e, 0x6f, 0x74, 0x20])]) }));
  await assert.rejects(badLegacyXls.officekitExportPdfTable(input, selection, 'xls'), /valid table export/);
});

test('PDF Password Remover treats a rejected known password as correction guidance, not an app bug', () => {
  const helper = html.match(/function pdfFailureShouldReport\(tool, message\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(helper, 'unlock error classification is isolated for deterministic testing');
  const context = {};
  vm.runInNewContext(`${helper}\nglobalThis.expectedPassword = pdfFailureShouldReport('unlock', 'Incorrect password. Please try again.');\nglobalThis.backendFailure = pdfFailureShouldReport('unlock', 'PDF processing failed.');\nglobalThis.protectorFailure = pdfFailureShouldReport('protect', 'Incorrect password.');`, context);
  assert.equal(context.expectedPassword, false);
  assert.equal(context.backendFailure, true, 'unexpected processing failures remain reportable');
  assert.equal(context.protectorFailure, true, 'the suppression is scoped to unlock password correction');
  assert.match(html, /unlock: \{ id: 'pdf_unlock', title: 'PDF Password Remover'/);
});

test('PDF Password Protector marks password confirmation feedback as local validation and recovers', () => {
  const helper = html.match(/function updatePdfProtectPasswordState\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(helper, 'password confirmation validation is isolated for deterministic testing');
  const makeField = value => ({
    value,
    textContent: '',
    attributes: new Map(),
    setAttribute(name, next) { this.attributes.set(name, next); },
    removeAttribute(name) { this.attributes.delete(name); },
    getAttribute(name) { return this.attributes.get(name) ?? null; },
  });
  const elements = {
    'pdf-new-password': makeField('audit-passphrase-42'),
    'pdf-new-password-confirm': makeField('different-audit-phrase'),
    'pdf-protect-confirm-error': makeField(''),
    'pdf-protect-password-count': makeField(''),
  };
  const context = {
    TextEncoder,
    document: { getElementById: id => elements[id] ?? null },
    officekitPdfPasswordValidationMessage: () => '',
  };
  vm.runInNewContext(`${helper}\nglobalThis.validate = updatePdfProtectPasswordState;`, context);

  assert.equal(context.validate(), false);
  assert.equal(elements['pdf-protect-confirm-error'].textContent, 'Passwords do not match.');
  assert.equal(elements['pdf-protect-confirm-error'].getAttribute('data-officekit-no-bug-report'), '');
  assert.equal(elements['pdf-new-password-confirm'].getAttribute('aria-invalid'), 'true');

  elements['pdf-new-password-confirm'].value = 'audit-passphrase-42';
  assert.equal(context.validate(), true);
  assert.equal(elements['pdf-protect-confirm-error'].textContent, '');
  assert.equal(elements['pdf-protect-confirm-error'].getAttribute('data-officekit-no-bug-report'), null);
  assert.equal(elements['pdf-new-password-confirm'].getAttribute('aria-invalid'), 'false');
});

test('PDF password workbench reports the revision-six UTF-8 byte limit', () => {
  assert.match(html, /Confirm new PDF password/);
  assert.match(html, /pdf-protect-confirm-error/);
  assert.match(html, /Passwords do not match/);
  assert.match(html, /Maximum 127 NFKC-normalized UTF-8 bytes/);
  assert.match(html, /pdf-protect-password-count/);
  assert.match(html, /pdf-unlock-password-count/);
  assert.match(html, /PDF passwords must be at most 127 normalized UTF-8 bytes/);
});

test('PDF workbench task output and imported filenames are rendered as text', () => {
  assert.match(html, /id="pdf-workbench-files"/);
  assert.match(html, /id="pdf-workbench-status"[^>]*aria-live="polite"/);
  assert.match(html, /id="pdf-workbench-download"/);
  assert.match(html, /function renderPdfSelection\(\)\s*\{[\s\S]*?container\.replaceChildren\(\)/);
  assert.doesNotMatch(html, /pdfFileList\.innerHTML\s*=/);
  assert.match(html, /function clearPdfWorkbenchOutput\(\)/);
  assert.match(html, /move\.addEventListener\('click', \(\) => \{ clearPdfWorkbenchOutput\(\)/);
  assert.match(html, /remove\.addEventListener\('click', \(\) => \{ clearPdfWorkbenchOutput\(\)/);
});

test('PDF split screen exposes named page groups with accessible limits and a ZIP preview', () => {
  assert.match(html, /pdf-split-group-add/);
  assert.match(html, /pdf-split-group-count/);
  assert.match(html, /pdf-split-group-help/);
  assert.match(html, /pdf-split-preview-list/);
  assert.match(html, /Create \$\{pdfSplitGroups\.length\} PDFs/);
  assert.match(html, /2,000 selected pages/);
  assert.match(html, /Pages cannot appear in more than one group/);
  assert.match(html, /Duplicate or unsafe filenames are rejected/);
  assert.match(html, /Split output will be downloaded together in one ZIP/);
  assert.match(html, /split-pages\.zip/);
  assert.match(html, /function renderPdfSplitGroups\(\)/);
  assert.match(html, /pdf-split-preview-list[\s\S]*?replaceChildren\(\)/);
  assert.match(html, /document\.createElement\('li'\)/);
  assert.match(html, /grid-cols-\[minmax\(0,1fr\)_auto\][\s\S]*?sm:grid-cols-\[minmax\(0,1fr\)_minmax\(0,1fr\)_auto\]/);
  assert.match(html, /remove\.textContent\s*=\s*'×'/);
  assert.match(html, /remove\.setAttribute\('aria-label', `Remove \$\{group\.name \|\| 'page'\} group`\)/);
  assert.match(html, /nameInput\.value\s*=/);
  assert.match(html, /rangeInput\.value\s*=/);
  assert.doesNotMatch(html, /pdf-split-group.*innerHTML\s*=/);
});

test('PDF client maps all supported tasks to declared endpoints and multipart fields', async () => {
  const calls = [];
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return { ok: true, status: 200, headers: { get: (name) => ({ 'content-type': url.endsWith('/images') ? 'application/zip' : 'application/pdf', 'x-officekit-output-input-ratio': '0.8', 'x-officekit-page-count': '2' })[name] }, blob: async () => new Blob([url.endsWith('/images') ? 'PK\u0003\u0004output' : '%PDF-1.7\noutput']) };
  });
  const input = pdf();
  const tasks = [
    ['merge', [pdf('a.pdf'), pdf('b.pdf')], {}, '/api/pdf/merge', 'files'],
    ['split', [input], { pageRanges: '1-2' }, '/api/pdf/split', 'file'],
    ['compress', [input], { preset: 'maximum' }, '/api/pdf/compress', 'file'],
    ['images', [input], { targetFormat: 'jpeg', dpi: 300, quality: 82 }, '/api/pdf/images', 'file'],
    ['metadata', [input], {}, '/api/pdf/metadata', 'file'],
    ['unlock', [input], { password: '' }, '/api/pdf/unlock', 'file'],
    ['protect', [input], { password: 'known-new-password' }, '/api/pdf/protect', 'file'],
  ];

  for (const [task, files, options, endpoint, field] of tasks) {
    const result = await context.officekitRunPdfTask(task, files, options);
    assert.ok(result.blob instanceof Blob);
    if (task === 'compress') assert.equal(result.outputInputRatio, 0.8);
    if (task === 'images') assert.equal(result.pageCount, 2);
    assert.equal(calls.at(-1).url, `http://127.0.0.1:8000${endpoint}`);
    assert.equal(calls.at(-1).init.method, 'POST');
    const form = calls.at(-1).init.body;
    assert.equal(form.getAll(field).length, files.length);
    if (task === 'split') assert.equal(form.get('page_ranges'), '1-2');
    if (task === 'compress') assert.equal(form.get('preset'), 'maximum');
    if (task === 'images') {
      assert.equal(form.get('target_format'), 'jpeg');
      assert.equal(form.get('dpi'), '300');
      assert.equal(form.get('quality'), '82');
    }
    if (task === 'unlock' || task === 'protect') assert.equal(form.get('password'), options.password);
  }
  assert.equal(calls.length, tasks.length);
});

test('PDF grouped split sends one source and named page groups to the ZIP endpoint', async () => {
  const calls = [];
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      headers: { get: (name) => ({ 'content-type': 'application/zip' })[name] || null },
      blob: async () => new Blob(['PK\u0003\u0004named outputs']),
    };
  });
  const groups = [
    { name: 'cover.pdf', page_ranges: '1-3' },
    { name: 'appendix.pdf', page_ranges: '4-6' },
  ];
  const result = await context.officekitRunPdfTask('split-groups', [pdf()], { groups });

  assert.equal(result.contentType, 'application/zip');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/split/groups');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.body.getAll('file').length, 1);
  assert.equal(calls[0].init.body.get('groups'), JSON.stringify(groups));
});

test('PDF grouped split rejects invalid group counts, fields and bounds before network calls', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; throw new Error('unexpected network call'); });
  const group = { name: 'output.pdf', page_ranges: '1' };
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [group] }), /2 and 50 page groups/);
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [...Array(51)].map((_, index) => ({ ...group, name: `part-${index}.pdf` })) }), /2 and 50 page groups/);
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [group, { name: 'other.pdf', page_ranges: ' '.repeat(4_097) }] }), /page ranges/);
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [group, { name: 'two.pdf', page_ranges: '2', extra: true }] }), /page group/);
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [group, { name: 'OUTPUT.pdf', page_ranges: '2' }] }), /unique/);
  await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups: [group, { name: '../unsafe.pdf', page_ranges: '2' }] }), /safe PDF filename/);
  assert.equal(calls, 0);
});

test('PDF grouped split rejects malformed, repeated, overlapping, and oversized page selections locally', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; throw new Error('unexpected network call'); });
  const group = (name, page_ranges) => ({ name, page_ranges });
  const invalidSelections = [
    [[group('first.pdf', '1,,2'), group('second.pdf', '3')], /page range/],
    [[group('first.pdf', '3-1'), group('second.pdf', '4')], /ascending/],
    [[group('first.pdf', '0'), group('second.pdf', '4')], /positive/],
    [[group('first.pdf', '1-3'), group('second.pdf', '3-5')], /overlap/],
    [[group('first.pdf', '1, 1'), group('second.pdf', '4')], /overlap/],
    [[group('first.pdf', '1-2001'), group('second.pdf', '2002')], /2,000 selected pages/],
  ];
  for (const [groups, message] of invalidSelections) {
    await assert.rejects(context.officekitRunPdfTask('split-groups', [pdf()], { groups }), message);
  }
  assert.equal(calls, 0);
});

test('PDF page-management client posts compact page selections and complete reorder permutations', async () => {
  const calls = [];
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      headers: { get: name => name === 'content-type' ? 'application/pdf' : null },
      blob: async () => new Blob(['%PDF-1.7 output']),
    };
  });
  await context.officekitRunPdfTask('delete-pages', [pdf()], { pageCount: 5, pageRanges: '2,4-5' });
  await context.officekitRunPdfTask('reorder-pages', [pdf()], { pageCount: 3, pageOrder: [3, 1, 2] });

  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/pages/delete');
  assert.equal(calls[0].init.body.get('page_ranges'), '2,4-5');
  assert.equal(calls[1].url, 'http://127.0.0.1:8000/api/pdf/pages/reorder');
  assert.equal(calls[1].init.body.get('page_order'), '3,1-2');
});

test('PDF page-management client rejects empty, duplicate, out-of-range and incomplete selections before network calls', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; throw new Error('unexpected network call'); });
  for (const pageRanges of ['', '1-3', '1,1', '0', '4', '3-1', '1,,2']) {
    await assert.rejects(
      context.officekitRunPdfTask('delete-pages', [pdf()], { pageCount: 3, pageRanges }),
    );
  }
  for (const pageOrder of [[1, 2], [1, 2, 2], [0, 1, 2], [1, 2, 4], '3,1,2']) {
    await assert.rejects(
      context.officekitRunPdfTask('reorder-pages', [pdf()], { pageCount: 3, pageOrder }),
    );
  }
  await assert.rejects(context.officekitRunPdfTask('delete-pages', [pdf()], { pageCount: 1, pageRanges: '1' }), /at least one page/);
  assert.equal(calls, 0);
});

test('PDF thumbnail client validates ordered PNG page lists and request bounds', async () => {
  const calls = [];
  const pngBase64 = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 0]).toString('base64');
  const context = loadClient(async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      headers: { get: name => ({ 'content-type': 'application/json', 'content-length': '512' })[name] || null },
      json: async () => ({
        page_count: 3,
        pages: [3, 2].map(page_number => ({ page_number, width_points: 300, height_points: 400, data_base64: pngBase64 })),
      }),
    };
  });
  const result = await context.officekitGetPdfPageThumbnails(pdf(), [3, 2]);
  assert.deepEqual(result.pages.map(page => page.page_number), [3, 2]);
  assert.equal(result.pages[0].data_uri, `data:image/png;base64,${pngBase64}`);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/pdf/page-thumbnails');
  assert.equal(calls[0].init.body.get('page_numbers'), '3,2');

  await assert.rejects(context.officekitGetPdfPageThumbnails(pdf(), [0]), /unique valid pages/);
  await assert.rejects(context.officekitGetPdfPageThumbnails(pdf(), Array.from({ length: 25 }, (_, index) => index + 1)), /between 1 and 24/);
});

test('PDF client rejects wrong task file counts, oversized inputs and invalid options before network calls', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; throw new Error('unexpected network call'); });
  await assert.rejects(context.officekitRunPdfTask('merge', [pdf()], {}), /2 and 20/);
  await assert.rejects(context.officekitRunPdfTask('split', [pdf(), pdf()], { pageRanges: '1' }), /one PDF/);
  await assert.rejects(context.officekitRunPdfTask('split', [pdf()], { pageRanges: ' '.repeat(4_097) }), /page range/);
  await assert.rejects(context.officekitRunPdfTask('compress', [pdf()], { preset: 'lossy' }), /compression preset/);
  await assert.rejects(context.officekitRunPdfTask('images', [pdf()], { targetFormat: 'webp', dpi: 300, quality: 90 }), /PNG or JPEG/);
  await assert.rejects(context.officekitRunPdfTask('images', [pdf()], { targetFormat: 'png', dpi: 301, quality: 90 }), /resolution/);
  await assert.rejects(context.officekitRunPdfTask('protect', [pdf()], { password: '' }), /password/);
  await assert.rejects(context.officekitRunPdfTask('protect', [pdf()], { password: '😀'.repeat(32) }), /127 normalized UTF-8 bytes/);
  await assert.rejects(context.officekitRunPdfTask('protect', [pdf()], { password: 'ﷺ'.repeat(16) }), /127 normalized UTF-8 bytes/);
  await assert.rejects(context.officekitRunPdfTask('protect', [pdf()], { password: '\ud800' }), /valid Unicode/);
  await assert.rejects(context.officekitRunPdfTask('protect', [pdf()], { password: '\udfff' }), /valid Unicode/);
  await assert.rejects(context.officekitRunPdfTask('unlock', [pdf()], { password: 'x'.repeat(128) }), /127 normalized UTF-8 bytes/);
  await assert.rejects(context.officekitRunPdfTask('metadata', [{ name: 'large.pdf', size: 67_108_865 }], {}), /64 MiB/);
  await assert.rejects(context.officekitRunPdfTask('not-a-task', [pdf()], {}), /unsupported PDF task/);
  assert.equal(calls, 0);

  let body;
  const valid = loadClient(async (_url, init) => {
    body = init.body;
    return { ok: true, status: 200, headers: { get: name => name === 'content-type' ? 'application/pdf' : null }, blob: async () => new Blob(['%PDF-1.7']) };
  });
  const boundaryPassword = '😀'.repeat(31) + 'abc';
  assert.equal(new TextEncoder().encode(boundaryPassword).length, 127);
  await valid.officekitRunPdfTask('protect', [pdf()], { password: boundaryPassword });
  assert.equal(body.get('password'), boundaryPassword);
});

test('PDF client reads the shared safe API error envelope and rejects non-binary success', async () => {
  const failing = loadClient(async () => ({ ok: false, status: 422, message: 'Choose valid PDF pages.' }));
  await assert.rejects(failing.officekitRunPdfTask('split', [pdf()], { pageRanges: '0' }), /Choose valid PDF pages/);

  const malformed = loadClient(async () => ({ ok: true, status: 200, headers: { get: () => 'text/html' }, blob: async () => new Blob(['error']) }));
  await assert.rejects(malformed.officekitRunPdfTask('metadata', [pdf()], {}), /valid file/);
});

test('PDF client rejects lookalike MIME types and corrupt file signatures', async () => {
  for (const [contentType, bytes, task] of [
    ['application/pdfx', '%PDF-1.7\nnot actually a PDF', 'metadata'],
    ['application/pdf', 'server error', 'metadata'],
    ['application/zip-malicious', 'PK\u0003\u0004payload', 'images'],
    ['application/zip', 'not actually a ZIP', 'images'],
  ]) {
    const context = loadClient(async () => ({
      ok: true,
      status: 200,
      headers: { get: (name) => ({ 'content-type': contentType, 'x-officekit-page-count': '1' })[name] || null },
      blob: async () => new Blob([bytes]),
    }));
    await assert.rejects(context.officekitRunPdfTask(task, [pdf()], task === 'images' ? { targetFormat: 'png', dpi: 150, quality: 90 } : {}), /valid file/);
  }
});

test('PDF client rejects oversized declared and actual outputs before accepting a download', async () => {
  let blobReads = 0;
  const declaredTooLarge = loadClient(async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => ({ 'content-type': 'application/pdf', 'content-length': '67108865' })[name] },
    blob: async () => { blobReads += 1; return new Blob(['%PDF-1.7']); },
  }));
  await assert.rejects(declaredTooLarge.officekitRunPdfTask('metadata', [pdf()], {}), /oversized PDF output/);
  assert.equal(blobReads, 0);

  const oversizedBlob = new Blob(['%PDF-1.7']);
  Object.defineProperty(oversizedBlob, 'size', { value: 67_108_865 });
  const undeclaredTooLarge = loadClient(async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => name === 'content-type' ? 'application/pdf' : null },
    blob: async () => oversizedBlob,
  }));
  await assert.rejects(undeclaredTooLarge.officekitRunPdfTask('metadata', [pdf()], {}), /oversized PDF output/);
});
