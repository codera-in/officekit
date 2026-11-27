import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const source = html.match(/\/\* RESULT SNAPSHOT CLIENT START \*\/([\s\S]*?)\/\* RESULT SNAPSHOT CLIENT END \*\//)[1];
const client = { Date, JSON, Object, Array, Number, String, RegExp, Blob, TextEncoder };
vm.runInNewContext(source, client);
function request(toolId, inputs, result) {
  return client.officekitBuildResultExportRequest({ toolId, title: 'Test', savedAt: '2026-10-07T10:00:00Z', inputs, result }, 'json', false);
}

test('unit conversion export preserves actual source and destination units', () => {
  const report = request('units_convert', { value: 2.5, category: 'length', from_unit: 'meter', to_unit: 'centimeter' }, { result: 250 });
  assert.equal(report.inputs.find(field => field.name === 'value').unit, 'meter');
  assert.equal(report.results[0].unit, 'centimeter');
  assert.equal(report.inputs[0].value, 2.5);
});

test('currency-neutral financial tools do not invent USD or money units for duration', () => {
  const report = request('simple_interest', { principal: 1000, annual_rate_percent: 10, time_value: 18, time_unit: 'months' }, { interest: 150, total_amount: 1150 });
  assert.equal(report.inputs.find(field => field.name === 'principal').unit, null);
  assert.equal(report.inputs.find(field => field.name === 'time_value').unit, 'months');
  assert.equal(report.inputs.find(field => field.name === 'annual_rate_percent').unit, '%');
  assert.equal(report.results[0].unit, null);
  for (const toolId of ['margin_markup', 'break_even', 'depreciation', 'math_eval', 'unknown-tool']) {
    const neutral = request(toolId, { value: 10, cost: 4 }, { profit: 6, book_value: 3 });
    assert.equal(neutral.inputs[0].unit, null, toolId);
    assert.equal(neutral.results[1].unit, null, toolId);
  }
});

test('USD calculators retain explicit monetary, rate and time units', () => {
  const report = request('calculator.loan-emi', { principal: 1200, annual_interest_rate: 0, tenure_years: 1 }, { monthly_emi: 100, tenure_months: 12 });
  assert.deepEqual(Array.from(report.inputs, field => field.unit), ['$', '%', 'years']);
  assert.deepEqual(Array.from(report.results, field => field.unit), ['$', 'months']);
});
