import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/everyday-percentages.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const client = html.match(/async function officekitCalculateFinancialUtility\([\s\S]*?\n        \}\n/)?.[0];
const exact = html.match(/function officekitExactKeys\(value, keys\) \{[\s\S]*?\n        \}/)?.[0];
const reader = html.match(/async function officekitReadTypedJson\(response, fallback, \{ inputError = false \} = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
const assumptions = { rounding: 'half_up', precision: '0.01', currency: 'not_inferred', taxes: 'excluded' };
const vectors = {
  percent_of: {
    inputs: { percent: 15, value: 240 },
    response: { percent: 15, value: 240, result: 36, assumptions },
  },
  percentage_change: {
    inputs: { original_value: 80, new_value: 100 },
    response: { original_value: 80, new_value: 100, change_value: 20, change_percent: 25, direction: 'increase', assumptions },
  },
  discount: {
    inputs: { price: 100, discount_percent: 20 },
    response: { price: 100, discount_percent: 20, savings: 20, discounted_price: 80, assumptions },
  },
};
const routes = {
  percent_of: '/api/calculator/percent-of',
  percentage_change: '/api/calculator/percentage-change',
  discount: '/api/calculator/discount',
};

function loadClient(fetch) {
  assert.ok(apiUrlHelper && client && exact && reader, 'strict local calculator client dependencies exist');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${apiUrlHelper}\n${exact}\n${reader}\n${client}\nglobalThis.calculate = officekitCalculateFinancialUtility;`, context);
  return context;
}

test('everyday percentages mock and registered calculator expose all three common operations', () => {
  for (const phrase of ['Percent of', 'Percentage change', 'Discount', 'half-up', 'currency', 'tax']) assert.match(mock, new RegExp(phrase, 'i'));
  assert.match(registry, /"id": "everyday_percentages"/);
  for (const term of ['percentage of', 'percentage change', 'percent increase', 'discount calculator']) assert.ok(registry.includes(term));
  assert.match(html, /id="calc-form-percentages"/);
  assert.match(html, /calculatorScreens = \{[\s\S]*percentages: \['Everyday percentages'/);
  assert.match(html, /everyday_percentages: \{ tab: 'calculators', calculator: 'percentages' \}/);
});

test('strict client posts exact local DTOs and validates all three independent result vectors', async () => {
  const calls = [];
  const context = loadClient(async (url, options) => {
    const toolId = Object.entries(routes).find(([, route]) => new URL(url).pathname === route)?.[0];
    calls.push({ url, options, toolId });
    return { ok: true, json: async () => vectors[toolId].response };
  });
  for (const [toolId, vector] of Object.entries(vectors)) {
    const result = await context.calculate(toolId, vector.inputs);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), vector.response);
  }
  assert.equal(calls.length, 3);
  for (const call of calls) {
    assert.equal(call.options.method, 'POST');
    assert.equal(call.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(call.options.body), vectors[call.toolId].inputs);
  }
});

test('client rejects invalid inputs before requests and refuses inconsistent, extra-key or wrong-assumption responses', async () => {
  let calls = 0;
  const valid = loadClient(async () => { calls += 1; return { ok: true, json: async () => vectors.percent_of.response }; });
  await assert.rejects(valid.calculate('percent_of', { percent: true, value: 240 }), /valid percent/);
  await assert.rejects(valid.calculate('percent_of', { percent: 15, value: 240, currency: 'USD' }), /supported calculator/);
  await assert.rejects(valid.calculate('percentage_change', { original_value: 0, new_value: 1 }), /greater than zero/);
  await assert.rejects(valid.calculate('discount', { price: 100, discount_percent: 100.1 }), /valid discount percent/);
  assert.equal(calls, 0);

  const mismatch = loadClient(async () => ({ ok: true, json: async () => ({ ...vectors.percent_of.response, result: 37 }) }));
  await assert.rejects(mismatch.calculate('percent_of', vectors.percent_of.inputs), /inconsistent percentage/);
  const extra = loadClient(async () => ({ ok: true, json: async () => ({ ...vectors.discount.response, note: 'unexpected' }) }));
  await assert.rejects(extra.calculate('discount', vectors.discount.inputs), /inconsistent percentage/);
  const wrongAssumption = loadClient(async () => ({ ok: true, json: async () => ({ ...vectors.percentage_change.response, assumptions: { ...assumptions, taxes: 'included' } }) }));
  await assert.rejects(wrongAssumption.calculate('percentage_change', vectors.percentage_change.inputs), /inconsistent percentage/);
});

test('calculator screen wires mode changes, stale-result clearing, save, export, and input reuse', () => {
  for (const marker of ['percentage-mode', 'percentage-fields-percent-of', 'percentage-fields-change', 'percentage-fields-discount', 'percentages-run', 'percentages-result']) assert.match(html, new RegExp(`id="${marker}"`));
  assert.match(html, /addEventListener\('input', \(\) => \{[\s\S]*?clearFinancialUtilityResult\(toolId\);\n            \}\);/);
  assert.match(html, /toolId: isPercentage \? 'everyday_percentages' : toolId/);
  assert.match(html, /everyday_percentages' && snapshot\.inputs/);
  assert.match(html, /switchCalc\('percentages'\)/);
  assert.match(html, /officekitRenderCalculationActions\(container, \{/);
});
