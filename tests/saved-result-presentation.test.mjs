import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const blocks = ['CURRENCY DISPLAY', 'RESULT SNAPSHOT CLIENT', 'SAVED RESULT PRESENTATION'];
const source = blocks.map(name => html.match(new RegExp(`/\\* ${name} START \\*/([\\s\\S]*?)/\\* ${name} END \\*/`))?.[1]).join('\n');
const context = {
  officekitEscapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;'),
  Intl: { NumberFormat: function(locale, options) { return new Intl.NumberFormat(locale || 'en-US', options); } },
};
vm.runInNewContext(source, context);
const loan = {
  toolId: 'calculator.loan-emi', inputs: { principal: 1200, annual_interest_rate: 0, tenure_years: 1 },
  result: { monthly_emi: 100, total_interest: 0, total_payment: 1200, tenure_months: 12 },
};

test('saved summary uses meaningful labels and explicit units without changing numbers', () => {
  const original = JSON.stringify(loan);
  assert.equal(context.officekitSavedResultSummary(loan), 'Monthly payment: $100.00 · Total interest: $0.00 · Total paid: $1,200.00');
  assert.match(context.officekitSavedResultMarkup(loan), /Loan amount<\/dt><dd data-input-field="principal">\$1,200\.00/);
  assert.equal(JSON.stringify(loan), original);
});

test('saved tables show a bounded preview, explicit counts and no duplicate schedule preview', () => {
  const schedule = Array.from({ length: 120 }, (_, month) => ({ month: month + 1, payment: 100, remaining_balance: 12000 - (month + 1) * 100 }));
  const snapshot = { ...loan, result: { ...loan.result, schedule, preview_schedule: schedule.slice(0, 12) } };
  const markup = context.officekitSavedResultMarkup(snapshot);
  assert.equal((markup.match(/<table>/g) || []).length, 1);
  assert.equal((markup.match(/<tr>/g) || []).length, 51);
  assert.match(markup, /Showing 50 of 120 rows/);
  assert.match(markup, /Full-document exports retain every row/);
  assert.equal(snapshot.result.schedule.length, 120);
});

test('saved strings, column names and assumptions cannot inject markup', () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const snapshot = { toolId: 'unknown-tool', inputs: { [hostile]: hostile }, result: { result: hostile, schedule: [{ [hostile]: hostile }], assumptions: { [hostile]: hostile } } };
  const markup = context.officekitSavedResultMarkup(snapshot);
  assert.ok(!markup.includes('<img'));
  assert.ok(markup.includes('&lt;img'));
  assert.ok(markup.includes('&quot;alert(1)&quot;'));
});

test('zero, negative, tiny, large, boolean and undefined results remain meaningful', () => {
  const snapshot = { toolId: 'math_eval' };
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', 0), '0');
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', -12.5), '-12.5');
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', 1e-15), '1E-15');
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', 1e100), '1E100');
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', false), 'No');
  assert.equal(context.officekitResultDisplayValue(snapshot, 'result', null), 'Undefined');
  assert.equal(context.officekitResultDisplayValue({ toolId: 'units_convert', inputs: { from_unit: 'meter', to_unit: 'centimeter' } }, 'result', 250), '250 centimeters');
  assert.equal(context.officekitResultDisplayValue(loan, 'tenure_years', 1, 'inputs'), '1 year');
  assert.equal(context.officekitResultDisplayValue(loan, 'month', 1, 'table'), '1');
  assert.equal(context.officekitResultDisplayValue({ toolId: 'units_convert', inputs: { from_unit: 'custom-unit', to_unit: 'custom-unit' } }, 'result', 12), '12 custom-unit');
});
