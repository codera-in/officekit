import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const mock = readFileSync(path.join(root, 'design/mocks/loan-emi-schedule.html'), 'utf8');
const validatorSource = html.match(/function officekitValidateLoanEmiResult\(data, inputs\) \{[\s\S]*?\n        \}/)?.[0];
const exactKeysSource = html.match(/function officekitExactKeys\(value, keys\) \{[\s\S]*?\n        \}/)?.[0];

const inputs = { principal: 2400, annual_interest_rate: 0, tenure_years: 2 };
const assumptions = {
  rate_basis: 'nominal_annual',
  payment_frequency: 'monthly',
  currency_precision: '0.01',
  fees_and_extra_payments: 'excluded',
  final_payment: 'adjusted_to_zero_balance',
};

function expectedResult() {
  const schedule = Array.from({ length: 24 }, (_, index) => ({
    month: index + 1,
    payment: 100,
    principal_paid: 100,
    interest_paid: 0,
    remaining_balance: 2300 - index * 100,
  }));
  return {
    monthly_emi: 100,
    total_interest: 0,
    total_payment: 2400,
    tenure_months: 24,
    preview_schedule: schedule.slice(0, 12),
    schedule,
    assumptions,
  };
}

function validate(result, request = inputs) {
  assert.ok(validatorSource && exactKeysSource, 'loan response validator exists');
  const context = {};
  vm.runInNewContext(`${exactKeysSource}\n${validatorSource}\nglobalThis.validate = officekitValidateLoanEmiResult;`, context);
  return context.validate(JSON.parse(JSON.stringify(result)), request);
}

test('loan EMI mock preserves the summary and adds paged schedule and explicit assumptions', () => {
  assert.match(mock, /Before · current result/);
  assert.match(mock, /After · schedule reviewed in OfficeKit/);
  assert.match(mock, /Monthly repayment schedule/);
  assert.match(mock, /Months 1–12 of 60/);
  assert.match(mock, /Exports keep all 60 months/);
  assert.match(mock, /card card-border bg-base-100 text-base-content/);
  assert.match(mock, /stats stats-horizontal/);
  assert.match(mock, /table table-xs/);
  assert.match(mock, /select select-sm/);
  for (const value of ['$1,001.90', '$10,113.82', '$60,113.82', '$41,436.82']) assert.ok(mock.includes(value), `${value} matches the verified fixture`);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('loan EMI client accepts a complete cent-reconciled schedule', () => {
  const result = expectedResult();
  assert.deepEqual(JSON.parse(JSON.stringify(validate(result))), result);
});

test('loan EMI client reconciles rounded interest and the adjusted final payment', () => {
  const schedule = [
    [9462, 1200, 110538], [9557, 1105, 100981], [9652, 1010, 91329], [9749, 913, 81580],
    [9846, 816, 71734], [9945, 717, 61789], [10044, 618, 51745], [10145, 517, 41600],
    [10246, 416, 31354], [10348, 314, 21006], [10452, 210, 10554], [10554, 106, 0],
  ].map(([principalCents, interestCents, remainingCents], index) => ({
    month: index + 1,
    payment: (principalCents + interestCents) / 100,
    principal_paid: principalCents / 100,
    interest_paid: interestCents / 100,
    remaining_balance: remainingCents / 100,
  }));
  const result = {
    monthly_emi: 106.62,
    total_interest: 79.42,
    total_payment: 1279.42,
    tenure_months: 12,
    preview_schedule: schedule,
    schedule,
    assumptions,
  };
  const request = { principal: 1200, annual_interest_rate: 12, tenure_years: 1 };
  assert.deepEqual(JSON.parse(JSON.stringify(validate(result, request))), result);
});

test('loan EMI client rejects malformed, incomplete, and financially inconsistent schedules', () => {
  const invalidResults = [];

  const missingMonth = expectedResult();
  missingMonth.schedule.pop();
  invalidResults.push(missingMonth);

  const reorderedMonth = expectedResult();
  reorderedMonth.schedule[1].month = 3;
  invalidResults.push(reorderedMonth);

  const extraRowField = expectedResult();
  extraRowField.schedule[0].debug = 'unexpected';
  invalidResults.push(extraRowField);

  const inconsistentPayment = expectedResult();
  inconsistentPayment.schedule[0].payment = 99;
  invalidResults.push(inconsistentPayment);

  const inconsistentBalance = expectedResult();
  inconsistentBalance.schedule[0].remaining_balance = 2200;
  invalidResults.push(inconsistentBalance);

  const inconsistentTotal = expectedResult();
  inconsistentTotal.total_payment = 2300;
  invalidResults.push(inconsistentTotal);

  const inconsistentPreview = expectedResult();
  inconsistentPreview.preview_schedule[0].remaining_balance = 2200;
  invalidResults.push(inconsistentPreview);

  const incorrectAssumption = expectedResult();
  incorrectAssumption.assumptions.payment_frequency = 'weekly';
  invalidResults.push(incorrectAssumption);

  const fractionalCent = expectedResult();
  fractionalCent.schedule[0].payment = 99.999;
  invalidResults.push(fractionalCent);

  const inconsistentInputPrincipal = expectedResult();
  inconsistentInputPrincipal.schedule[0].remaining_balance = 2299;
  invalidResults.push(inconsistentInputPrincipal);

  for (const result of invalidResults) {
    assert.throws(() => validate(result), /invalid|inconsistent|schedule/i);
  }
});
