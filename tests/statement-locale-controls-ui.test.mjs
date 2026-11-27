import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/statement-locale-controls.html'), 'utf8');
const scopeMock = fs.readFileSync(path.join(root, 'design/mocks/bank-statement-copy-scope.html'), 'utf8');
const client = html.match(/\/\* STATEMENT LOCALE CLIENT START \*\/([\s\S]*?)\/\* STATEMENT LOCALE CLIENT END \*\//)?.[1];

test('statement locale mock shows safe, explicit locale/date choices', () => {
  for (const text of ['Number format', 'Date order', 'Automatic', 'United States', 'India', 'Germany', 'France', '03/04/2026', '1,234']) assert.ok(mock.includes(text), text);
  assert.match(mock, /review the extracted rows/i);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('statement screen exposes all server-supported interpretation choices', () => {
  for (const id of ['statement-number-locale', 'statement-date-order']) assert.match(html, new RegExp(`id="${id}"`));
  for (const value of ['auto', 'en-US', 'en-IN', 'de-DE', 'fr-FR']) assert.match(html, new RegExp(`<option value="${value}"`));
  for (const value of ['auto', 'DMY', 'MDY', 'YMD']) assert.match(html, new RegExp(`<option value="${value}"`));
  assert.match(html, /officekitStatementFormData\([\s\S]*?statement-number-locale[\s\S]*?statement-date-order/);
});

test('statement screen promises only supported bank-statement extraction and qualified checks', () => {
  assert.ok(html.includes('Bank Statement to CSV / Excel'), 'use the supported tool name');
  assert.match(html, /supported bank statement layouts/i);
  assert.match(html, /review extracted values/i);
  assert.doesNotMatch(html, /any PDF bank statement, scan, photo, or invoice/i, 'do not claim invoice extraction');
  assert.doesNotMatch(html, /checking every transaction debit\/credit vs balance/i, 'do not promise every row can be reconciled');
});

test('copy-scope mock records the old and proposed text without external dependencies', () => {
  for (const text of ['Current', 'Proposed', 'invoice', 'supported bank statement layouts', 'Layout coverage varies', 'review every extracted row']) {
    assert.ok(scopeMock.toLowerCase().includes(text.toLowerCase()), text);
  }
  assert.doesNotMatch(scopeMock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('upload request carries the exact locale/date choices and rejects unsupported values', () => {
  assert.ok(client, 'statement locale request helper exists');
  const context = { FormData };
  vm.runInNewContext(client, context);
  const file = new Blob(['statement'], { type: 'text/csv' });
  Object.defineProperty(file, 'name', { value: 'statement.csv' });
  const form = context.officekitStatementFormData(file, 'en-IN', 'DMY');
  assert.equal(form.get('file').size, 9);
  assert.equal(form.get('number_locale'), 'en-IN');
  assert.equal(form.get('date_order'), 'DMY');
  const automatic = context.officekitStatementFormData(file, 'auto', 'auto');
  assert.equal(automatic.get('number_locale'), 'auto');
  assert.equal(automatic.get('date_order'), 'auto');
  assert.throws(() => context.officekitStatementFormData(file, 'xx-YY', 'DMY'), /supported number format/);
  assert.throws(() => context.officekitStatementFormData(file, 'en-US', 'YDM'), /supported date order/);
  assert.throws(() => context.officekitStatementFormData(null, 'auto', 'auto'), /Choose a statement file/);
});
