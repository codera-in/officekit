import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const bundled = fs.readFileSync(path.join(root, 'dist-ui/index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const actionSource = fs.readFileSync(path.join(root, 'assets/officekit-tool-actions.js'), 'utf8');
const functionSource = source.match(/function officekitBuildStatementCorrectionCsv\([\s\S]*?\n        }/)?.[0];
const bundledFunctionSource = bundled.match(/function officekitBuildStatementCorrectionCsv\([\s\S]*?\n        }/)?.[0];
const buildCsv = functionSource ? vm.runInNewContext(`(${functionSource})`, { TextEncoder }) : null;

const sourceResult = {
  raw_rows: [
    ['Date', 'Description', 'Debit', 'Credit', 'Balance'],
    ['2026-01-01 2026-01-02', 'Merged "transfer", reference', '', '50.00', '1050.00'],
  ],
  column_mapping: { date: 0, desc: 1, debit: 2, credit: 3, balance: 4 },
  excluded_rows: [{ row_index: 1, reason: 'multiple_dates' }],
};

test('Bank Statement shared action title matches the catalog title', () => {
  assert.match(registry, /"id": "bank_statement", "name": "Bank Statement Extractor"/);
  assert.match(source, /toolId:'bank_statement',title:'Bank Statement Extractor'/);
  assert.match(bundled, /toolId:'bank_statement',title:'Bank Statement Extractor'/);
});

test('statement replacement link sits beside the result count and leaves three shared actions', () => {
  const results = source.match(/<div id="statement-results"[\s\S]*?<div id="statement-output-display">/)?.[0] ?? '';
  assert.match(results, /id="statement-result-summary"[\s\S]*?id="statement-action-count"[\s\S]*?id="statement-choose-link"[^>]*class="link link-primary/);
  assert.ok(results.indexOf('id="statement-result-summary"') < results.indexOf('id="statement-output-display"'));
  assert.doesNotMatch(results, /Choose another statement[\s\S]*?ok-action-dock/);
  assert.match(source, /statement-choose-link'\)\.addEventListener\('click'[\s\S]*?stDropzone\.click\(\)/);
  assert.match(actionSource, /statementHasResult[\s\S]*?statementChooseAction\.remove\(\)/);
  assert.match(source, /row\.prepend\(window\.officekitStatementActionNodes\.review\)/);
  assert.doesNotMatch(source.match(/<div class="ok-action-dock" aria-label="Statement export actions">[\s\S]*?<\/div>/)?.[0] ?? '', /Choose another statement/);
  assert.match(bundled, /id="statement-result-summary"[\s\S]*?id="statement-choose-link"/);
  assert.match(bundled, /Choose another statement[\s\S]*statement-results/);
});

test('statement correction replaces stale export actions and gives column re-read honest working feedback', () => {
  assert.match(source, /id="statement-correction-actions" class="officekit-result-actions[^\"]*" data-officekit-action-for="bank_statement"/);
  const begin = source.match(/function beginStatementCorrection\(\)[\s\S]*?\n        \}/)?.[0] ?? '';
  assert.match(begin, /statement-output-display'\)\.classList\.add\('hidden'\)/);
  assert.match(begin, /statement-results > \.officekit-result-actions/);
  assert.match(source, /const row=mountedActions;document\.getElementById\('statement-results'\)\.append\(row\)/);
  const mapping = source.match(/async function applyStatementColumnMapping\(\)[\s\S]*?\n        \}/)?.[0] ?? '';
  assert.match(mapping, /state: 'working', text: 'Re-reading the selected file/);
  assert.match(mapping, /officekitOutcome\.clear\(status\)/, 'success does not leave a stale working/error message');
  assert.match(source, /id="statement-correction-result-status"[^>]*role="status"/);
  const applyCorrection = source.match(/async function applyStatementCorrection\(\)[\s\S]*?\n        \}/)?.[0] ?? '';
  assert.match(applyCorrection, /Corrections applied\. Review the recalculated balance checks below\./);
  assert.match(applyCorrection, /officekitOutcome\.clear\(status\)/, 'success clears the hidden editor working state');
  assert.match(mapping, /data-officekit-no-bug-report/, 'correctable mapping errors are excluded from bug reporting');
  assert.match(source, /statement-column-mapping-details'\)\.addEventListener\('toggle'[\s\S]*?statement-correction-add-actions[\s\S]*?OfficeKitToolActions\?\.refresh\(\)/);
  assert.match(source, /ok-row-action row-act min-h-9/, 'transaction row actions are classified as row actions');
  assert.match(bundled, /statement-correction-actions[\s\S]*Corrections applied\. Review the recalculated balance checks below\./);
});

test('unreadable statement files stay editable and clear stale result actions without a bug report', () => {
  const helper = source.match(/function officekitStatementInputErrorMessage\(status, detail, fileName\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(helper, 'statement upload validation is isolated for deterministic testing');
  const context = {};
  vm.runInNewContext(`${helper}\nglobalThis.invalidPdf = officekitStatementInputErrorMessage(422, 'The PDF could not be read. If it is password-protected, unlock it first.', 'broken.pdf');\nglobalThis.noRows = officekitStatementInputErrorMessage(422, 'No extractable text or tables found in document.', 'blank.pdf');\nglobalThis.tooLarge = officekitStatementInputErrorMessage(413, '', 'large.csv');\nglobalThis.unsupported = officekitStatementInputErrorMessage(400, '', 'notes.txt');\nglobalThis.unexpected = officekitStatementInputErrorMessage(500, 'Internal server error', 'statement.pdf');`, context);
  assert.equal(context.invalidPdf, 'Couldn’t read broken.pdf. Choose a readable PDF. If it is password-protected, unlock it first.');
  assert.match(context.noRows, /Couldn’t find transaction rows in blank\.pdf/);
  assert.match(context.tooLarge, /64 MiB limit/);
  assert.match(context.unsupported, /file type is not supported/);
  assert.equal(context.unexpected, null, 'unexpected service failures remain reportable');
  assert.match(source, /id="statement-file-error"[^>]*role="alert"[^>]*data-officekit-no-bug-report/);
  const upload = source.match(/async function uploadStatement\(file\) \{[\s\S]*?\n        \}/)?.[0] ?? '';
  assert.match(upload, /currentExtractedData = null/);
  assert.match(upload, /officekitStatementInputErrorMessage\(res\.status, data\.detail, file\.name\)/);
  assert.match(upload, /officekitOutcome\.show\(fileError, \{ state: 'error', text: inputError \}\)/);
  assert.match(upload, /showAppleCrashReport\(data\.diagnostic/);
  assert.match(actionSource, /statement-file-error:not\(\.hidden\)[\s\S]*Choose another statement/);
  assert.match(bundled, /function officekitStatementInputErrorMessage\([\s\S]*?data-officekit-no-bug-report/);
  assert.match(bundled, /officekitOutcome\.show\(fileError, \{ state: 'error', text: inputError \}\)/);
});

test('statement correction serializes bounded edited rows and escapes CSV cells', () => {
  assert.ok(buildCsv, 'correction serializer exists');
  const csv = buildCsv(sourceResult, [{
    date: '2026-01-03', description: 'Cafe, "North"', debit: '12.50', credit: '', balance: '1037.50', sourceRowIndex: null,
  }], new Set());
  assert.equal(csv, 'Date,Description,Debit,Credit,Balance\r\n2026-01-03,"Cafe, ""North""",12.50,,1037.50\r\n2026-01-01 2026-01-02,"Merged ""transfer"", reference",,50.00,1050.00\r\n');
  assert.equal(functionSource, bundledFunctionSource, 'Tauri bundle matches the tested CSV correction serializer');
});

test('statement correction keeps unresolved source rows and omits only explicitly reviewed exclusions', () => {
  assert.ok(buildCsv, 'correction serializer exists');
  const draft = [{ date: '2026-01-02', description: 'Corrected transfer', debit: '', credit: '50', balance: '1050', sourceRowIndex: 1 }];
  const unresolved = buildCsv(sourceResult, [], new Set());
  assert.match(unresolved, /2026-01-01 2026-01-02,"Merged ""transfer"", reference",,50\.00,1050\.00/);
  const resolved = buildCsv(sourceResult, draft, new Set([1]));
  assert.doesNotMatch(resolved, /Merged/);
  assert.match(resolved, /2026-01-02,Corrected transfer,,50,1050/);
});

test('statement correction rejects malformed rows, amounts, resolution indexes and oversized exports', () => {
  assert.ok(buildCsv, 'correction serializer exists');
  const valid = [{ date: '2026-01-03', description: 'Cafe', debit: '10.00', credit: '', balance: '990.00', sourceRowIndex: null }];
  assert.throws(() => buildCsv({}, valid, new Set()), /source rows/);
  assert.throws(() => buildCsv(sourceResult, [{ ...valid[0], debit: 'NaN' }], new Set()), /amount/);
  assert.throws(() => buildCsv(sourceResult, [{ ...valid[0], debit: '-1' }], new Set()), /amount/);
  assert.throws(() => buildCsv(sourceResult, [{ ...valid[0], debit: '1', credit: '1' }], new Set()), /debit or a credit/);
  assert.throws(() => buildCsv(sourceResult, [{ ...valid[0], sourceRowIndex: 99 }], new Set()), /source row/);
  assert.throws(() => buildCsv(sourceResult, valid, new Set([99])), /source row/);
  assert.throws(() => buildCsv(sourceResult, [{ ...valid[0], description: 'x'.repeat(10_001) }], new Set()), /description/);
  assert.throws(() => buildCsv(sourceResult, Array.from({ length: 10_001 }, () => valid[0]), new Set()), /source rows/);
  assert.throws(() => buildCsv(sourceResult, Array.from({ length: 800 }, () => ({ ...valid[0], description: 'x'.repeat(10_000) })), new Set()), /7 MiB/);
});
