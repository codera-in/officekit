import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/bank-statement-column-mapping.html'), 'utf8');
const client = html.match(/\/\* STATEMENT LOCALE CLIENT START \*\/([\s\S]*?)\/\* STATEMENT LOCALE CLIENT END \*\//)?.[1];

test('column mapping mock compares the current guess with the local re-read flow', () => {
  for (const text of ['Current', 'Proposed', 'Value date', 'Transaction Date', 'Re-read &amp; recalculate', 'original local file']) {
    assert.ok(mock.includes(text), text);
  }
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('statement column mapping stays inside Review & correct and has accessible controls', () => {
  assert.match(html, /id="statement-column-mapping-details"[\s\S]*id="statement-correction-transactions"/);
  for (const id of [
    'statement-column-mapping-fields', 'statement-column-mapping-status',
    'statement-column-mapping-apply', 'statement-mapping-result-status',
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /Re-reading replaces this extraction and clears any unsaved row edits/);
  assert.match(html, /Re-read &amp; recalculate/);
  assert.match(html, /officekitStatementFormData\([\s\S]*currentStatementSourceFile[\s\S]*mapping/);
});

test('column mapping request helper serializes valid mapping and rejects unsafe combinations', () => {
  assert.ok(client, 'statement form helper exists');
  const context = { FormData };
  vm.runInNewContext(client, context);
  const file = new Blob(['statement'], { type: 'text/csv' });
  const mapping = { date: 1, desc: 2, debit: 4, credit: 5, amount: null, balance: 6 };
  const form = context.officekitStatementFormData(file, 'en-IN', 'DMY', FormData, mapping);
  assert.deepEqual(JSON.parse(form.get('column_mapping')), mapping);
  assert.equal(form.get('number_locale'), 'en-IN');
  assert.equal(form.get('date_order'), 'DMY');
  assert.equal(context.officekitStatementFormData(file, 'auto', 'auto').has('column_mapping'), false);

  assert.throws(() => context.officekitStatementMappingJson({ ...mapping, desc: 1 }), /only one field/);
  assert.throws(() => context.officekitStatementMappingJson({ ...mapping, date: null }), /Date and Description/);
  assert.throws(() => context.officekitStatementMappingJson({ ...mapping, amount: 3 }), /combined amount or separate/);
  assert.throws(() => context.officekitStatementMappingJson({ ...mapping, credit: -1 }), /valid source columns/);
  assert.throws(() => context.officekitStatementMappingJson({ date: 0, desc: 1 }), /incomplete/);
});

test('column mapping result validation refuses mismatched backend selections', () => {
  const functionSource = html.match(/function officekitStatementMappingMatchesResponse\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'response mapping validator exists');
  const context = {};
  vm.runInNewContext(functionSource, context);
  const mapping = { date: 1, desc: 2, debit: 4, credit: null, amount: null, balance: 6 };
  const valid = { transactions: [], column_mapping: { date: 1, desc: 2, debit: 4, balance: 6 } };
  assert.equal(context.officekitStatementMappingMatchesResponse(valid, mapping), true);
  assert.equal(context.officekitStatementMappingMatchesResponse({ ...valid, column_mapping: { ...valid.column_mapping, date: 0 } }, mapping), false);
  assert.equal(context.officekitStatementMappingMatchesResponse({ transactions: [], column_mapping: {} }, mapping), false);
});
