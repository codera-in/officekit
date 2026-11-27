import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/financial-utilities-workbench.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/async function officekitCalculateFinancialUtility\([\s\S]*?\n        \}\n/)?.[0];
const exact = html.match(/function officekitExactKeys\(value, keys\) \{[\s\S]*?\n        \}/)?.[0];
const reader = html.match(/async function officekitReadTypedJson\(response, fallback, \{ inputError = false \} = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
const freelanceValidator = html.match(/function officekitValidateFreelanceRateResult\(data, inputs\) \{[\s\S]*?\n        \}/)?.[0];

function loadClient(fetch) {
  assert.ok(apiUrlHelper && client && exact && reader, 'strict finance API client dependencies exist');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${apiUrlHelper}\n${exact}\n${reader}\n${client}\nglobalThis.calculate = officekitCalculateFinancialUtility;`, context);
  return context;
}

const responses = {
  margin_markup: {
    profit: 20, gross_margin_percent: 20, markup_percent: 25, cost: 80, revenue: 100,
    assumptions: { margin_denominator: 'revenue', markup_denominator: 'cost' },
  },
  break_even: { break_even_units: 34, break_even_revenue: 1700, contribution_margin: 30 },
  simple_interest: {
    principal: 1000, annual_rate_percent: 10, time_value: 2, time_unit: 'years', time_in_years: 2,
    interest_amount: 200, total_amount: 1200,
    assumptions: { method: 'simple_interest', rate_basis: 'nominal_annual', currency_precision: '0.01', rounding: 'half_up', compounding: 'none' },
  },
  depreciation: {
    annual_depreciation: 3000, total_depreciable: 9000,
    schedule: [
      { year: 1, depreciation: 3000, book_value: 7000 },
      { year: 2, depreciation: 3000, book_value: 4000 },
      { year: 3, depreciation: 3000, book_value: 1000 },
    ],
    assumptions: { method: 'straight_line', currency_precision: '0.01', rounding: 'half_up', final_period: 'adjusted_to_salvage_value' },
  },
};
const inputs = {
  margin_markup: { cost: 80, revenue: 100 },
  break_even: { fixed_costs: 1000, price_per_unit: 50, cost_per_unit: 20 },
  simple_interest: { principal: 1000, annual_rate_percent: 10, time_value: 2, time_unit: 'years' },
  depreciation: { asset_cost: 10000, salvage_value: 1000, useful_life_years: 3 },
};

test('financial utilities mock shows all four API-only tools as simple calculator tasks', () => {
  for (const text of ['Margin &amp; markup', 'Break-even point', 'Simple interest', 'Straight-line depreciation', 'denominator is zero', 'rounds half-up to cents', 'percentages use entered values', 'whole units', 'no compounding', 'final year adjusts']) assert.match(mock, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest|https?:\/\//);
});

test('all four calculators have searchable routes, forms and explicit assumptions', () => {
  const routes = {
    margin_markup: "margin_markup: { tab: 'calculators', calculator: 'margin' }",
    break_even: "break_even: { tab: 'calculators', calculator: 'break-even' }",
    simple_interest: "simple_interest: { tab: 'calculators', calculator: 'simple-interest' }",
    depreciation: "depreciation: { tab: 'calculators', calculator: 'depreciation' }",
  };
  const forms = ['margin','break-even','simple-interest','depreciation'];
  for (const [id, route] of Object.entries(routes)) {
    assert.ok(registry.includes(`"id": "${id}"`));
    assert.ok(html.includes(route));
  }
  for (const form of forms) assert.match(html, new RegExp(`id="calc-form-${form}"`));
  for (const text of ['revenue as its denominator', 'rounded up to the next whole unit', 'Money rounds half-up to cents; percentages use entered values.', 'no compounding', 'final period adjusts for cent rounding']) assert.match(html, new RegExp(text, 'i'));
});

test('typed calculator requests return reconciled results for margin, break-even, simple interest and depreciation', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    const body = JSON.parse(options.body);
    calls.push({ url, options, body });
    const pathname = new URL(url).pathname;
    const id = Object.entries({
      '/api/calculator/margin-markup': 'margin_markup',
      '/api/calculator/break-even': 'break_even',
      '/api/calculator/simple-interest': 'simple_interest',
      '/api/calculator/depreciation': 'depreciation',
    }).find(([path]) => path === pathname)?.[1];
    return { ok: true, json: async () => responses[id] };
  });
  for (const id of Object.keys(inputs)) {
    const result = await context.calculate(id, inputs[id]);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), responses[id]);
  }
  assert.equal(calls.length, 4);
  assert.deepEqual(calls.map(call => call.options.method), Array(4).fill('POST'));
  assert.deepEqual(calls.map(call => call.body), Object.values(inputs));
});

test('financial calculator client rejects invalid inputs and inconsistent or malformed responses', async () => {
  let calls = 0;
  const valid = loadClient(async () => { calls += 1; return { ok: true, json: async () => responses.margin_markup }; });
  await assert.rejects(valid.calculate('unknown', {}), /supported calculator/);
  await assert.rejects(valid.calculate('margin_markup', { cost: true, revenue: 10 }), /valid cost/);
  await assert.rejects(valid.calculate('break_even', { fixed_costs: 0, price_per_unit: 10, cost_per_unit: 10 }), /greater than variable cost/);
  await assert.rejects(valid.calculate('simple_interest', { principal: 10, annual_rate_percent: 3, time_value: 0, time_unit: 'years' }), /valid time value/);
  await assert.rejects(valid.calculate('depreciation', { asset_cost: 100, salvage_value: 110, useful_life_years: 2 }), /cannot exceed asset cost/);
  assert.equal(calls, 0);

  const mismatched = loadClient(async () => ({ ok: true, json: async () => ({ ...responses.margin_markup, gross_margin_percent: 99 }) }));
  await assert.rejects(mismatched.calculate('margin_markup', inputs.margin_markup), /inconsistent margin/);
  const changedSchedule = loadClient(async () => ({ ok: true, json: async () => ({ ...responses.depreciation, schedule: responses.depreciation.schedule.map((item, i) => i === 2 ? { ...item, book_value: 1010 } : item) }) }));
  await assert.rejects(changedSchedule.calculate('depreciation', inputs.depreciation), /inconsistent depreciation/);
  const extraKey = loadClient(async () => ({ ok: true, json: async () => ({ ...responses.break_even, extra: 1 }) }));
  await assert.rejects(extraKey.calculate('break_even', inputs.break_even), /inconsistent break-even/);
});

test('margin and markup keeps zero-denominator percentages explicitly undefined', async () => {
  const zero = loadClient(async () => ({ ok: true, json: async () => ({
    profit: 0, gross_margin_percent: null, markup_percent: null, cost: 0, revenue: 0,
    assumptions: { margin_denominator: 'revenue', markup_denominator: 'cost' },
  }) }));
  const result = await zero.calculate('margin_markup', { cost: 0, revenue: 0 });
  assert.equal(result.gross_margin_percent, null);
  assert.equal(result.markup_percent, null);
});

test('margin and markup client validates half-up currency results for negative half-cent ties', async () => {
  const response = {
    profit: -0.13, gross_margin_percent: -11.11, markup_percent: -10,
    cost: 1.25, revenue: 1.125,
    assumptions: { margin_denominator: 'revenue', markup_denominator: 'cost' },
  };
  const client = loadClient(async () => ({ ok: true, json: async () => response }));

  const result = await client.calculate('margin_markup', { cost: 1.25, revenue: 1.125 });

  assert.deepEqual(JSON.parse(JSON.stringify(result)), response);
});

test('freelance-rate calculator exposes and preserves every rate assumption', () => {
  const mock = fs.readFileSync(path.join(root, 'design/mocks/freelance-rate-assumptions.html'), 'utf8');
  assert.match(mock, /Business expenses \/ year/);
  assert.match(mock, /aria-label="Result actions"[\s\S]*?Export…[\s\S]*?Save result/);
  assert.match(html, /id="free-expenses"[^>]*value="5000"/);
  assert.match(html, /business_expenses_annual:\s*parseFloat\(document\.getElementById\('free-expenses'\)\.value\)/);
  assert.match(html, /calculator\.freelance-rate': \{ key: 'freelance', fields: \{[^}]*business_expenses_annual: 'free-expenses'/);
  assert.match(html, /'business_expenses_annual', 'gross_annual_revenue_needed'/);
  assert.match(html, /data-freelance-assumptions/);
});

test('freelance-rate response is reconciled to the requested inputs and exact assumptions', () => {
  assert.ok(exact && freelanceValidator, 'freelance response validator and strict-key helper exist');
  const context = {};
  vm.runInNewContext(`${exact}\n${freelanceValidator}\nglobalThis.validate = officekitValidateFreelanceRateResult;`, context);
  const values = { target_annual_take_home: 80000, billable_hours_per_week: 25, vacation_weeks: 4, business_expenses_annual: 5000, tax_rate_percent: 25 };
  const valid = {
    recommended_hourly_rate: 93.06,
    recommended_day_rate: 465.28,
    gross_annual_revenue_needed: 111666.67,
    total_annual_billable_hours: 1200,
    assumptions: { tax_treatment: 'gross_up_target_then_add_expenses', working_days_per_week: 5, jurisdiction: 'not_specified' },
  };
  assert.deepEqual(JSON.parse(JSON.stringify(context.validate(valid, values))), valid);
  assert.throws(() => context.validate({ ...valid, recommended_hourly_rate: 1 }, values), /inconsistent freelance-rate/);
  assert.throws(() => context.validate({ ...valid, assumptions: { ...valid.assumptions, jurisdiction: 'US' } }, values), /inconsistent freelance-rate/);
  assert.throws(() => context.validate({ ...valid, unexpected: true }, values), /inconsistent freelance-rate/);
  assert.throws(() => context.validate(valid, { ...values, vacation_weeks: 52 }), /valid freelance-rate inputs/);
  assert.throws(() => context.validate(valid, { ...values, tax_rate_percent: 100 }), /valid freelance-rate inputs/);
});

test('editing financial calculator fields clears the previous on-screen result', () => {
  assert.match(html, /addEventListener\('input', \(\) => \{[\s\S]*?clearFinancialUtilityResult\(toolId\);\n            \}\);/);
  const clear = html.match(/function clearFinancialUtilityResult\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(clear);
  const result = { replaceChildren() { this.childrenRemoved = true; }, classList: { add(value) { this.hiddenClass = value; } } };
  const context = { document: { getElementById: id => id === 'margin-result' ? result : null } };
  vm.runInNewContext(`${clear}\nclearFinancialUtilityResult('margin_markup');`, context);
  assert.equal(result.childrenRemoved, true);
  assert.equal(result.classList.hiddenClass, 'hidden');
});

test('shared financial field error component associates guidance and clears field state', () => {
  const show = html.match(/function officekitShowFinancialFieldError\([\s\S]*?\n        \}/)?.[0];
  const clear = html.match(/function officekitClearFinancialFieldError\([\s\S]*?\n        \}/)?.[0];
  assert.ok(show && clear);
  const attrs = new Map();
  const input = { setAttribute: (name, value) => attrs.set(name, value), removeAttribute: name => attrs.delete(name) };
  const classes = new Set(['hidden']);
  const feedback = { textContent: '', classList: { remove: name => classes.delete(name), add: name => classes.add(name) } };
  const runClasses = new Set(['hidden']);
  const runButton = { classList: { remove: name => runClasses.delete(name), add: name => runClasses.add(name) } };
  const form = { attrs: new Map(), querySelector: selector => selector === '[data-calc-run]' ? runButton : null, setAttribute(name, value) { this.attrs.set(name, value); }, removeAttribute(name) { this.attrs.delete(name); } };
  const container = {
    actionsRemoved: false, children: [],
    querySelector: () => ({ remove() { container.actionsRemoved = true; } }),
    classList: { remove() {} }, setAttribute(name, value) { this[name] = value; },
    closest: () => form, replaceChildren(...children) { this.children = children; },
  };
  const context = { document: { createElement: () => ({ className: '', textContent: '' }) } };
  vm.runInNewContext(`${show}\n${clear}\nglobalThis.showError = officekitShowFinancialFieldError; globalThis.clearError = officekitClearFinancialFieldError;`, context);
  context.showError(container, input, feedback, 'Fix this field.', 'Update the value.');
  assert.equal(attrs.get('aria-invalid'), 'true');
  assert.equal(feedback.textContent, 'Fix this field.');
  assert.equal(classes.has('hidden'), false);
  assert.equal(container.role, 'alert');
  assert.equal(form.attrs.has('data-officekit-no-bug-report'), true);
  assert.equal(runClasses.has('hidden'), false);
  assert.equal(container.actionsRemoved, true);
  assert.equal(container.children[0].textContent, 'Update the value.');
  context.showError(container, input, feedback, 'Fix this field.', 'Update the value.', 'Your other inputs are preserved.');
  assert.equal(container.children[1].textContent, 'Your other inputs are preserved.');
  context.clearError(form, input, feedback);
  assert.equal(attrs.has('aria-invalid'), false);
  assert.equal(feedback.textContent, '');
  assert.equal(classes.has('hidden'), true);
  assert.equal(form.attrs.has('data-officekit-no-bug-report'), false);
});

test('break-even correction stays on the price field, suppresses bug reporting, and restores the dock action', () => {
  for (const [inputId, errorId] of [['break-fixed', 'break-fixed-error'], ['break-price', 'break-price-error'], ['break-cost', 'break-cost-error']]) {
    assert.match(html, new RegExp(`id="${inputId}"[^>]*aria-describedby="${errorId}"`));
    assert.match(html, new RegExp(`id="${errorId}"[^>]*role="alert"`));
  }
  const run = html.match(/async function runFinancialUtility\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run);
  assert.match(run, /officekitBreakEvenInputError\(inputs\)[\s\S]*?officekitShowFinancialFieldError\(container, input, feedback/);
  assert.match(run, /officekitClearFinancialFieldError\(form, document\.getElementById\(inputId\), document\.getElementById\(errorId\)\)/);
  const validator = html.match(/function officekitBreakEvenInputError\(inputs\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(validator);
  const context = {};
  vm.runInNewContext(`${validator}\nglobalThis.validate = officekitBreakEvenInputError;`, context);
  assert.equal(context.validate({ fixed_costs: 900, price_per_unit: 50, cost_per_unit: 20 }), null);
  const invalid = context.validate({ fixed_costs: 900, price_per_unit: 10, cost_per_unit: 20 });
  assert.equal(invalid.inputId, 'break-price');
  assert.equal(invalid.errorId, 'break-price-error');
  assert.match(invalid.message, /greater than the variable cost per unit/);
  assert.match(invalid.prompt, /Update the price per unit/);
  assert.ok(invalid.explanation.includes('fixed costs'));
  assert.equal(context.validate({ fixed_costs: -1, price_per_unit: 50, cost_per_unit: 20 }).inputId, 'break-fixed');
  assert.equal(context.validate({ fixed_costs: 900, price_per_unit: 50, cost_per_unit: 1e12 + 1 }).inputId, 'break-cost');
  const handlers = html.match(/for \(const \[toolId, ids\] of Object\.entries\([\s\S]*?for \(const id of ids\) document\.getElementById\(id\)\.addEventListener\('input', \(\) => \{[\s\S]*?\n            \}\n        \}\)/)?.[0] ?? '';
  assert.match(handlers, /if \(toolId === 'break_even'\)[\s\S]*?officekitClearFinancialFieldError\(form, document\.getElementById\(inputId\), document\.getElementById\(errorId\)\)/);
  assert.match(html, /function officekitShowFinancialFieldError[\s\S]*?data-officekit-no-bug-report/);
  assert.match(html, /if \(toolId === 'break_even'\)[\s\S]*?officekitBreakEvenInputError\(inputs\)[\s\S]*?officekitShowFinancialFieldError\(container, input, feedback,[\s\S]*?return;/);
});

test('simple interest invalid principal stays a local field error and recovers cleanly', () => {
  assert.match(html, /id="simple-principal"[^>]*aria-describedby="simple-principal-error"/);
  assert.match(html, /id="simple-principal-error"/);
  const run = html.match(/async function runFinancialUtility\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run);
  assert.match(run, /value < 0 \|\| value > 1e12/);
  assert.match(run, /officekitShowFinancialFieldError\(container, principal, principalError/);
  assert.match(run, /Update the principal to continue\./);
  assert.match(run, /return;/);
  assert.match(run, /officekitClearFinancialFieldError\(container\.closest\('\[data-calc-form\]'\), principal, principalError\)/);
  assert.match(run, /if \(toolId === 'simple_interest'\) document\.getElementById\('simple-run'\)\.classList\.add\('hidden'\)/);
  assert.match(html, /if \(toolId === 'simple_interest'\) document\.getElementById\('simple-run'\)\.classList\.remove\('hidden'\)/);
  assert.match(html, /id === 'simple-principal'[\s\S]*?officekitClearFinancialFieldError/);
});

test('depreciation salvage above cost gets linked guidance and clears on either correction', () => {
  assert.match(html, /id="depreciation-salvage"[^>]*aria-describedby="depreciation-salvage-error"/);
  assert.match(html, /id="depreciation-salvage-error"/);
  const run = html.match(/async function runFinancialUtility\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run);
  assert.match(run, /inputs\.salvage_value > inputs\.asset_cost/);
  assert.match(run, /officekitShowFinancialFieldError\(container, salvage, salvageError/);
  assert.match(run, /Salvage value must be less than or equal to asset cost/);
  assert.match(run, /Update the salvage value to continue\./);
  assert.match(run, /officekitClearFinancialFieldError\(container\.closest\('\[data-calc-form\]'\), salvage, salvageError\)/);
  assert.match(html, /\['depreciation-cost', 'depreciation-salvage'\][\s\S]*?officekitClearFinancialFieldError/);
});

test('percentage change zero origin stays a local field error and clears on correction or mode switch', () => {
  assert.match(html, /id="percentage-original"[^>]*aria-describedby="percentage-original-error"/);
  assert.match(html, /id="percentage-original-error"/);
  const run = html.match(/async function runFinancialUtility\(toolId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run);
  assert.match(run, /toolId === 'percentage_change'[\s\S]*?inputs\.original_value === 0/);
  assert.match(run, /officekitShowFinancialFieldError\(container, original, originalError/);
  assert.match(run, /Update the original value to continue\./);
  assert.match(run, /officekitClearFinancialFieldError\(container\.closest\('\[data-calc-form\]'\), original, originalError\)/);
  assert.match(html, /id === 'percentage-original'[\s\S]*?officekitClearFinancialFieldError/);
  assert.match(html, /percentage-mode'\)\.addEventListener\('change',[\s\S]*?officekitClearFinancialFieldError/);
});
