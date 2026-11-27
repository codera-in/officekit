import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const mock = fs.readFileSync(path.join(root, 'design/mocks/calculator-api-tools.html'), 'utf8');
const apiUrlHelper = html.match(/function officekitApiUrl\(path, currentLocation = window\.location\) \{[\s\S]*?\n        \}/)?.[0];
const clients = html.match(/\/\* CALCULATOR API TOOLS CLIENT START \*\/([\s\S]*?)\/\* CALCULATOR API TOOLS CLIENT END \*\//)?.[1];

function loadClients(fetch) {
  assert.ok(apiUrlHelper, 'loopback API URL helper exists');
  assert.ok(clients, 'calculator API tool clients exist');
  const context = { window: { location: { protocol: 'tauri:', hostname: 'localhost' } }, fetch };
  vm.runInNewContext(`${apiUrlHelper}\n${clients}`, context);
  return context;
}

function jsonResponse(data, ok = true) { return { ok, json: async () => data }; }

test('calculator tools mock covers scientific and unit workflows on desktop and compact layout', () => {
  for (const text of ['Scientific math and unit conversion already have typed local APIs', 'After: direct, task-specific forms', 'Angle mode', 'Unit converter', 'Category', 'Copy result', 'Swap', 'POST /api/math/eval', 'POST /api/units/convert']) assert.ok(mock.includes(text), text);
  assert.doesNotMatch(mock, /<script[^>]+src=|<link[^>]+href="https?:/);
});

test('calculator workspace exposes searchable scientific and unit screens', () => {
  for (const id of [
    'calc-screen-title', 'calc-form-scientific', 'calc-form-units',
    'math-expression', 'math-angle-mode', 'math-run', 'math-result', 'unit-category',
    'unit-value', 'unit-from', 'unit-to', 'unit-run', 'unit-swap', 'unit-result',
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /math_eval: \{ tab: 'calculators', calculator: 'scientific'/);
  assert.match(html, /units_convert: \{ tab: 'calculators', calculator: 'units'/);
  assert.match(html, /api\/units\/catalog/);
});

test('scientific calculator posts strict expression and angle mode and validates its result', async () => {
  const calls = [];
  const context = loadClients(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ result: 28.284271247461902, expression: 'sqrt(2) * 20', angle_mode: 'radians' });
  });
  const result = await context.officekitEvaluateExpression('sqrt(2) * 20', 'radians');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/math/eval');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { expression: 'sqrt(2) * 20', angle_mode: 'radians' });
  assert.equal(result.result, 28.284271247461902);
});

test('scientific calculator treats correctable 4xx input as field guidance and restores fresh actions', () => {
  const readJson = html.match(/async function officekitReadTypedJson\(response, fallback, \{ inputError = false \} = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
  const evaluate = html.match(/async function officekitEvaluateExpression\([\s\S]*?\n        \}/)?.[0];
  const run = html.match(/async function runScientificCalculator\(\) \{[\s\S]*?\n        \}/)?.[0];
  const errorRenderer = html.match(/function officekitShowCalculatorError\(container, error, options = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
  assert.match(readJson, /response\.status >= 400 && response\.status < 500/);
  assert.match(evaluate, /\{ inputError: true \}/);
  assert.match(run, /input\.setAttribute\('aria-invalid', 'true'\)/);
  assert.match(run, /const input = document\.getElementById\('math-expression'\);/);
  assert.match(run, /error\?\.inputError === true \? \{[\s\S]*?hideActions: true,[\s\S]*?hideHeading: true,[\s\S]*?role: 'status',[\s\S]*?Your expression could not be evaluated/);
  assert.match(errorRenderer, /options\.message \?\?/);
  assert.match(errorRenderer, /options\.hideHeading \? \[\] : \[heading\]/);
  assert.match(run, /container\.setAttribute\('role', 'status'\)/);
  assert.match(run, /officekitCalcMarkFresh\?\.\(container\)/);
  assert.match(run, /removeAttribute\('data-officekit-no-bug-report'\)/);
});

test('scientific calculator rejects invalid requests and inconsistent responses', async () => {
  let calls = 0;
  const context = loadClients(async () => { calls += 1; return jsonResponse({ result: 1, expression: '2', angle_mode: 'degrees' }); });
  await assert.rejects(context.officekitEvaluateExpression('', 'radians'), /enter an expression/i);
  await assert.rejects(context.officekitEvaluateExpression('x'.repeat(513), 'radians'), /512/);
  await assert.rejects(context.officekitEvaluateExpression('2', 'gradians'), /angle mode/i);
  await assert.rejects(context.officekitEvaluateExpression('2', 'radians'), /valid scientific result/i);
  assert.equal(calls, 1);
  const bad = loadClients(async () => jsonResponse({ result: Infinity, expression: '2', angle_mode: 'radians' }));
  await assert.rejects(bad.officekitEvaluateExpression('2', 'radians'), /valid scientific result/i);
});

test('unit catalog is validated and unit conversion checks the response matches the request', async () => {
  const calls = [];
  const categoryIds = ['length', 'area', 'volume', 'mass', 'speed', 'time', 'energy', 'power', 'pressure', 'force', 'frequency', 'angle', 'digital_storage', 'temperature', 'typography'];
  const catalog = { categories: categoryIds.map(id => ({ id, label: id, units: [{ id: 'unit_a', label: 'Unit A' }, { id: 'unit_b', label: 'Unit B' }] })) };
  const context = loadClients(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/catalog')) return jsonResponse(catalog);
    return jsonResponse({ result: 3.48, category: 'length', from_unit: 'km', to_unit: 'mi' });
  });
  assert.equal((await context.officekitLoadUnitCatalog()).length, 15);
  const result = await context.officekitConvertUnit({ value: 5.6, category: 'length', from_unit: 'km', to_unit: 'mi' });
  assert.equal(calls.length, 2);
  assert.equal(result.result, 3.48);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/units/catalog');
  assert.equal(calls[1].url, 'http://127.0.0.1:8000/api/units/convert');
  assert.deepEqual(JSON.parse(calls[1].options.body), { value: 5.6, category: 'length', from_unit: 'km', to_unit: 'mi' });
});

test('unit converter rejects malformed catalog, invalid values and inconsistent conversion responses', async () => {
  const malformedCatalog = loadClients(async () => jsonResponse({ categories: [{ id: 'length', label: 'Length', units: [{ id: 'meter', label: 'Meter' }, { id: 'meter', label: 'Duplicate' }] }] }));
  await assert.rejects(malformedCatalog.officekitLoadUnitCatalog(), /valid unit catalog/i);
  let calls = 0;
  const context = loadClients(async () => { calls += 1; return jsonResponse({ result: 10, category: 'mass', from_unit: 'km', to_unit: 'mi' }); });
  for (const request of [
    { value: NaN, category: 'length', from_unit: 'km', to_unit: 'mi' },
    { value: 1e101, category: 'length', from_unit: 'km', to_unit: 'mi' },
    { value: 1, category: 'unknown', from_unit: 'a', to_unit: 'b' },
    { value: 1, category: 'length', from_unit: '', to_unit: 'm' },
  ]) await assert.rejects(context.officekitConvertUnit(request), /finite value/i);
  await assert.rejects(context.officekitConvertUnit({ value: 1, category: 'length', from_unit: 'km', to_unit: 'mi' }), /valid unit conversion/i);
  assert.equal(calls, 1);
});

test('unit converter maps a client validation response to a correctable input error', async () => {
  const context = loadClients(async () => ({
    ok: false,
    status: 422,
    json: async () => ({ detail: 'Temperature cannot be below absolute zero' }),
  }));
  await assert.rejects(
    context.officekitConvertUnit({ value: -0.001, category: 'temperature', from_unit: 'kelvin', to_unit: 'kelvin' }),
    error => error.inputError === true && /absolute zero/i.test(error.message),
  );
});

test('unit converter connects absolute-zero feedback to its value field and clears it on edits', () => {
  const run = html.match(/async function runUnitCalculator\(\) \{[\s\S]*?\n        \}/)?.[0];
  const validation = html.match(/function clearUnitTemperatureValidation\(\) \{[\s\S]*?\n        \}/)?.[0];
  const show = html.match(/function showUnitTemperatureValidation\(unit, container\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run && validation && show);
  assert.match(run, /error\?\.inputError && \/absolute zero\/i[\s\S]*?showUnitTemperatureValidation/);
  assert.match(show, /aria-invalid', 'true'/);
  assert.match(show, /aria-describedby', message\.id/);
  assert.match(show, /setAttribute\('data-officekit-no-bug-report'/);
  assert.match(show, /Enter 0 K or higher\./);
  assert.match(validation, /removeAttribute\('aria-invalid'\)/);
  assert.match(validation, /removeAttribute\('data-officekit-no-bug-report'\)/);
  assert.match(html, /id="unit-value-validation" role="alert"/);
});

test('unit converter rounds only its visible value and preserves the raw result snapshot', () => {
  const run = html.match(/async function runUnitCalculator\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(run);
  assert.match(run, /toLocaleString\(undefined, \{ maximumSignificantDigits: 7, useGrouping: false \}\)/);
  assert.match(run, /officekitRenderCalculationActions\(container, \{ toolId: 'units_convert',[\s\S]*?result \}\)/);
  assert.doesNotMatch(run, /result\.result\s*=|result\.result\s*=/);
});
