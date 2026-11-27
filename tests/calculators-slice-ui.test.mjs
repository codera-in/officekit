import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sliceSource = readFileSync(path.join(root, 'assets', 'officekit-slice-calculators.js'), 'utf8');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const css = readFileSync(path.join(root, 'assets', 'officekit.input.css'), 'utf8');

// Values built inside the vm context have another realm's Array prototype; copy them before deep comparison.
const plain = value => JSON.parse(JSON.stringify(value));

function loadSlice(document = {}) {
  const registrations = [];
  const context = { window: { OfficeKitExtensions: { register: value => registrations.push(value) } }, document, fetch: () => { throw new Error('no network in tests'); } };
  context.window.document = context.document;
  vm.runInNewContext(sliceSource, context);
  return { window: context.window, registrations, slice: context.window.OfficeKitCalcSlice };
}

test('slice registers every new calculator destination once and keeps register() first', () => {
  const { registrations } = loadSlice();
  assert.equal(registrations.length, 1);
  assert.equal(registrations[0].slice, 'calculators');
  assert.deepEqual(Object.keys(registrations[0].destinations).sort(), [
    'age_calculator', 'business_days', 'cagr', 'date_difference', 'descriptive_statistics', 'fractions_ratios',
    'gcd_lcm', 'geometry', 'quadratic_solver', 'roi', 'time_zone_converter', 'weighted_average', 'work_hours',
  ]);
  assert.match(sliceSource.trimStart(), /^\/\/ Calculators slice/);
  assert.equal(registrations[0].destinations.roi.calculator, 'roi');
  assert.equal(registrations[0].destinations.gcd_lcm.calculator, 'gcd-lcm');
});

test('number and list parsing rejects text, blanks and fractional whole numbers', () => {
  const { slice } = loadSlice();
  const { readNumber, readList, readDateLines, readWorkRows, readDate } = slice.parse;
  assert.equal(readNumber(' 12.5 '), 12.5);
  assert.throws(() => readNumber('12 apples', 'Amount'), /Amount must be a number/);
  assert.throws(() => readNumber('0x10', 'Amount'), /must be a number/);
  assert.throws(() => readNumber('1e400', 'Amount'), /must be a number/);
  assert.deepEqual(plain(readList('1, 2\n3', 'Values')), [1, 2, 3]);
  assert.deepEqual(plain(readList('5\n\n7', 'Values', { allowBlank: true })), [5, null, 7]);
  assert.throws(() => readList('5\n\n7', 'Values'), /item 2 is blank/);
  assert.throws(() => readList('   ', 'Values'), /at least one value/);
  assert.throws(() => readList('2.5', 'Whole numbers', { integer: true }), /whole numbers/);
  assert.deepEqual(plain(readDateLines('2026-01-01\n\n2026-12-25', 'Holiday')), ['2026-01-01', '2026-12-25']);
  assert.throws(() => readDateLines('01/01/2026', 'Holiday'), /YYYY-MM-DD/);
  assert.equal(readDate('2026-10-22', 'Date'), '2026-10-22');
  assert.throws(() => readDate('2026-2-1', 'Date'), /calendar date/);
});

test('work-hour lines accept an optional date and break and reject malformed times', () => {
  const { slice } = loadSlice();
  assert.deepEqual(plain(slice.parse.readWorkRows('2026-03-02 09:00 17:30 30\n22:00 06:00')), [
    { date: '2026-03-02', start: '09:00', end: '17:30', break_minutes: 30 },
    { date: null, start: '22:00', end: '06:00', break_minutes: 0 },
  ]);
  assert.throws(() => slice.parse.readWorkRows('09:00'), /needs a start time/);
  assert.throws(() => slice.parse.readWorkRows('9:00 17:00'), /HH:MM/);
  assert.throws(() => slice.parse.readWorkRows('09:00 17:00 1.5'), /whole minutes/);
  assert.throws(() => slice.parse.readWorkRows(' \n '), /at least one shift/);
});

test('responses must contain every documented key with the documented type', () => {
  const { slice } = loadSlice();
  const roi = slice.specs.roi;
  assert.deepEqual(slice.assertResponse(roi, { net_gain: 250, roi_percent: 25, total_cost: 1025 }), { net_gain: 250, roi_percent: 25, total_cost: 1025 });
  assert.throws(() => slice.assertResponse(roi, { net_gain: 250, roi_percent: 25 }), /invalid calculator result/);
  assert.throws(() => slice.assertResponse(roi, { net_gain: '250', roi_percent: 25, total_cost: 1025 }), /invalid calculator result/);
  assert.throws(() => slice.assertResponse(roi, { net_gain: Number.NaN, roi_percent: 25, total_cost: 1025 }), /invalid calculator result/);
  assert.throws(() => slice.assertResponse(roi, ['not', 'an', 'object']), /invalid calculator result/);
  assert.throws(() => slice.assertResponse(slice.specs.statistics, { count: 1 }), /invalid calculator result/);
});

test('quadratic rows hide the discriminant when the kind has none (linear, degenerate)', () => {
  const { slice } = loadSlice();
  const linear = slice.specs.quadratic.rows({ kind: 'linear', discriminant: null, roots: [{ real: 2, imaginary: 0 }], max_residual: 0 });
  assert.equal(plain(linear).some(([label]) => label === 'Discriminant'), false);
  const quadratic = slice.specs.quadratic.rows({ kind: 'two_real', discriminant: 1, roots: [], max_residual: 0 });
  assert.equal(plain(quadratic).some(([label]) => label === 'Discriminant'), true);
  assert.equal(slice.assertResponse(slice.specs.quadratic, { kind: 'linear', discriminant: null, roots: [], max_residual: 0 }).discriminant, null);
  assert.throws(() => slice.assertResponse(slice.specs.quadratic, { kind: 'linear', discriminant: 'x', roots: [], max_residual: 0 }));
});

test('statistics and quadratic presentation covers null variance and complex roots', () => {
  const { slice } = loadSlice();
  const stats = slice.specs.statistics.rows({
    count: 1, sum: 4, mean: 4, median: 4, modes: [], modes_truncated: false, no_mode: true, minimum: 4, maximum: 4, range: 0,
    variance: null, std_dev: null, variance_unavailable_reason: 'need two or more values',
  });
  assert.deepEqual(plain(stats.find(([label]) => label === 'Mode')), ['Mode', 'No mode']);
  assert.match(stats.find(([label]) => label === 'Variance')[1], /need two or more values/);
  assert.equal(slice.formatRoot({ real: 1, imaginary: -2 }), '1 - 2i');
  assert.equal(slice.formatRoot({ real: 3, imaginary: 0 }), '3');
  assert.equal(slice.formatMixed({ whole: '1', numerator: '1', denominator: '2' }), '1 1/2');
  assert.equal(slice.formatMixed({ whole: '2', numerator: '0', denominator: '1' }), '2');
  assert.equal(slice.formatMixed({ whole: '0', numerator: '-1', denominator: '2' }), '-1/2');
  assert.equal(slice.formatMixed({ whole: '0', numerator: '1', denominator: '2' }), '1/2');
  assert.equal(slice.formatMixed({ whole: '-3', numerator: '1', denominator: '2' }), '-3 1/2');
});

test('result text is built with DOM text nodes, never HTML strings', () => {
  // Any innerHTML or outerHTML write, plain or compound (+=, ||=, ??=), and document.write are banned in the slice.
  assert.doesNotMatch(sliceSource, /(?:inner|outer)HTML\s*(?:\+|\|\||\?\?)?=(?!=)|document\.write\(/);
  assert.match('x.innerHTML += y', /(?:inner|outer)HTML\s*(?:\+|\|\||\?\?)?=(?!=)/);
  assert.doesNotMatch(sliceSource, /insertAdjacentHTML/);
  assert.match(sliceSource, /textContent = value/);
});

test('field units map the new result fields and stay out of the way for other tools', () => {
  const { window } = loadSlice();
  const unit = window.OfficeKitCalculatorFieldUnit;
  assert.equal(unit({ toolId: 'roi' }, 'roi_percent', 'results'), '%');
  assert.equal(unit({ toolId: 'cagr', inputs: {} }, 'years', 'inputs'), 'years');
  assert.equal(unit({ toolId: 'work_hours' }, 'total_hours', 'results'), 'hours');
  assert.equal(unit({ toolId: 'geometry', inputs: { unit: 'ft' } }, 'radius', 'inputs'), 'ft');
  assert.equal(unit({ toolId: 'units_convert' }, 'value', 'inputs'), undefined);
  assert.equal(unit({ toolId: 'calculator.loan-emi' }, 'principal', 'inputs'), undefined);
});

test('restore plans route saved results to their calculator and reject unknown tools', () => {
  const { slice } = loadSlice();
  assert.equal(slice.restorePlan({ toolId: 'roi', inputs: { invested: 1, returned: 2, fees: 0 } }).key, 'roi');
  assert.equal(slice.restorePlan({ toolId: 'weighted_average', inputs: { values: [1] } }).key, 'average');
  assert.equal(slice.restorePlan({ toolId: 'roi', inputs: null }), null);
  assert.equal(slice.restorePlan({ toolId: 'calculator.loan-emi', inputs: {} }), null);
});

test('calculator markup opens one calculator per screen with the 13 new forms and the shared run whitelist', () => {
  assert.doesNotMatch(html, /id="calc-pill-/);
  assert.doesNotMatch(html, /<select id="calc-select"/);
  for (const key of ['roi', 'cagr', 'average', 'fractions', 'gcd-lcm', 'statistics', 'date-difference', 'age', 'business-days', 'work-hours', 'time-zones', 'quadratic', 'geometry']) {
    assert.match(html, new RegExp(`<div id="calc-form-${key}" data-calc-form`), key);
    assert.match(html, new RegExp(`id="calc-${key}-run" data-calc-run data-officekit-click="runNewCalculator\\('${key}'\\)"`), key);
    assert.match(html, new RegExp(`id="calc-${key}-result"`), key);
  }
  assert.match(html, /'updateSupportFeedbackFields', 'runNewCalculator'/);
  assert.match(html, /<h1 id="calc-screen-title"/);
  assert.match(html, /data-officekit-click="switchTab\('tools'\)">All tools<\/button>/);
});

test('result actions expose Download and Save with Copy as an inline link, and no Calculate again', () => {
  assert.match(html, /data-calc-copy-head/);
  assert.match(html, /data-inline-action/);
  assert.match(html, /data-copy-calculation/);
  assert.doesNotMatch(html, /data-calc-again/);
  assert.match(sliceSource, /Fill in every field to see the result\./);
  assert.match(html, /globalThis\.officekitCalcMarkFresh\?\.\(container\)/);
});

test('VAT result stays within the card and invalid rates clear stale result actions', () => {
  const vat = html.slice(html.indexOf('id="calc-form-vat"'), html.indexOf('id="calc-form-freelance"'));
  assert.match(vat, /id="vat-amount"[^>]*min="0"[^>]*max="1000000000000"[^>]*aria-describedby="vat-amount-validation"/);
  assert.match(vat, /id="vat-amount-validation" role="alert"/);
  assert.match(vat, /id="vat-rate"[^>]*min="0"[^>]*max="1000"[^>]*aria-describedby="vat-rate-validation"/);
  assert.match(vat, /id="vat-rate-validation" role="alert"/);
  assert.match(html, /document\.getElementById\('vat-amount'\)\.addEventListener\('input', clearVatValidation\)/);
  assert.match(html, /document\.getElementById\('vat-rate'\)\.addEventListener\('input', clearVatValidation\)/);
  const run = html.slice(html.indexOf('async function runVatCalc'), html.indexOf('function officekitValidateFreelanceRateResult'));
  assert.match(run, /!Number\.isFinite\(inputs\.amount\).*inputs\.amount < 0.*inputs\.amount > 1e12/);
  assert.match(run, /!Number\.isFinite\(inputs\.tax_rate_percent\).*inputs\.tax_rate_percent < 0.*inputs\.tax_rate_percent > 1000/);
  assert.match(run, /'Enter an amount from 0 to 1,000,000,000,000\.'/);
  assert.match(run, /officekitShowFinancialFieldError\(div, rate, feedback, 'Enter a rate from 0% to 1,000%\.'/);
  assert.ok(run.indexOf('officekitShowFinancialFieldError') < run.indexOf('fetch('), 'invalid rates are rejected before the API call');
  assert.match(run, /delete div\.dataset\.vatValidation/);
  assert.match(css, /#tab-calculators:has\(#calc-form-vat:not\(\.hidden\)\) #calc-screen-subtitle,/);
  assert.match(css, /#tab-calculators:has\(#calc-form-vat:not\(\.hidden\)\) > \.calc-card \{ flex: none; min-height: auto; padding-block: 1rem; \}/);
});

test('Freelance Rate recovers zero hours locally and presents the latest result before editable inputs', () => {
  const freelance = html.slice(html.indexOf('id="calc-form-freelance"'), html.indexOf('id="calc-form-scientific"'));
  assert.ok(freelance.indexOf('id="free-result"') < freelance.indexOf('class="grid grid-cols-1 sm:grid-cols-2 gap-4"'));
  assert.match(css, /#tab-calculators:has\(#calc-form-freelance:not\(\.hidden\)\) #calc-card-title \{ display: none; \}/);
  assert.match(css, /#tab-calculators:has\(#calc-form-freelance:not\(\.hidden\)\) > \.calc-card \{ flex: none; min-height: auto; padding-block: 1rem; \}/);
  const run = html.slice(html.indexOf('async function runFreelanceCalc'), html.indexOf('/* RESULT SNAPSHOT CLIENT START */'));
  assert.match(run, /officekitShowFinancialFieldError\(div, hoursInput, hoursError, 'Enter at least 1 billable hour per week\.'/);
  assert.match(run, /officekitClearFinancialFieldError\(document\.getElementById\('calc-form-freelance'\), hoursInput, hoursError\)/);
  assert.match(run, /div\.removeAttribute\('role'\)/);
  assert.doesNotMatch(run, /A rate cannot be estimated without billable time/);
});

test('Average & Weighted Average presents its latest result before the long input form', async () => {
  const formStart = html.indexOf('<div id="calc-form-average"');
  const formEnd = html.indexOf('<div id="calc-form-fractions"', formStart);
  const markup = html.slice(formStart, formEnd);
  assert.ok(markup.indexOf('id="calc-average-result"') < markup.indexOf('id="calc-average-values"'));
  assert.equal(loadSlice().slice.specs.average.resultHeading, 'Latest result');

  const makeNode = tagName => ({ tagName, className: '', textContent: '', children: [], append(...nodes) { this.children.push(...nodes); } });
  const fields = new Map([
    ['calc-average-values', { id: 'calc-average-values', value: '10\n20\n30', type: 'textarea' }],
    ['calc-average-weights', { id: 'calc-average-weights', value: '1\n2\n3', type: 'textarea' }],
    ['calc-average-missing', { id: 'calc-average-missing', value: 'reject', type: 'select-one' }],
  ]);
  const form = { querySelectorAll: () => [], querySelector: () => null, removeAttribute() {} };
  const container = {
    classList: { remove() {} },
    attributes: {}, children: [],
    closest: () => form,
    setAttribute(name, value) { this.attributes[name] = value; },
    replaceChildren(...nodes) { this.children = nodes; },
  };
  const document = {
    getElementById: id => id === 'calc-average-result' ? container : fields.get(id) || null,
    createElement: makeNode,
  };
  const result = { mean: 23.3333333333, count_used: 3, count_skipped: 0, weight_total: 6, weighted: true };
  const window = {
    OfficeKitExtensions: { register() {} },
    officekitApiUrl: path => path,
    officekitReadCalculatorResponse: async () => result,
    officekitRenderCalculationActions() {},
    officekitCalcMarkFresh() {},
  };
  const context = { window, document, fetch: async () => ({ ok: true }) };
  context.globalThis = context;
  vm.runInNewContext(sliceSource, context);
  await window.runNewCalculator('average');
  assert.equal(container.children[0].tagName, 'h3');
  assert.equal(container.children[0].textContent, 'Latest result');
  assert.equal(container.children[1].tagName, 'dl');
});

test('mismatched average weights get linked field guidance and recover without a generic error', async () => {
  const form = {
    attributes: {},
    querySelectorAll: () => [values, input, missing],
    querySelector: () => null,
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
  };
  const input = {
    id: 'calc-average-weights', value: '1\n2', attributes: {}, focused: false,
    closest: () => null,
    insertAdjacentElement(position, node) { this.validationNode = node; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() { this.focused = true; },
  };
  const values = { id: 'calc-average-values', value: '10\n20\n30' };
  const missing = { id: 'calc-average-missing', value: 'reject' };
  const actionDock = { removed: false, remove() { this.removed = true; } };
  const container = {
    attributes: {}, children: [],
    classList: { remove() {} },
    closest: () => form,
    querySelector: selector => selector === '.officekit-result-actions' ? actionDock : null,
    setAttribute(name, value) { this.attributes[name] = value; },
    replaceChildren(...nodes) { this.children = nodes; },
  };
  const document = {
    getElementById: id => ({
      'calc-average-values': values,
      'calc-average-weights': input,
      'calc-average-missing': missing,
      'calc-average-result': container,
      'calc-average-weights-validation': input.validationNode,
    })[id] || null,
    createElement: tagName => ({ tagName, attributes: {}, children: [], setAttribute(name, value) { this.attributes[name] = value; }, append(...nodes) { this.children.push(...nodes); }, remove() { this.removed = true; } }),
  };
  const window = {
    OfficeKitExtensions: { register() {} },
    officekitApiUrl: path => path,
    officekitReadCalculatorResponse: async () => ({ mean: 20, count_used: 3, count_skipped: 0, weight_total: 6, weighted: true }),
    officekitRenderCalculationActions() {},
    officekitDisableCalculationActions() {},
    officekitCalcMarkFresh() {},
  };
  const context = { window, document, fetch: async () => ({ ok: true }) };
  context.globalThis = context;
  vm.runInNewContext(sliceSource, context);

  await context.window.runNewCalculator('average');
  assert.equal(input.attributes['aria-invalid'], 'true');
  assert.equal(input.attributes['aria-describedby'], 'calc-average-weights-validation');
  assert.equal(input.focused, true);
  assert.equal(input.validationNode.textContent, 'Add one weight for each value, or clear Weights to use a simple average.');
  assert.equal(form.attributes['data-officekit-no-bug-report'], '');
  assert.equal(actionDock.removed, true);
  assert.equal(container.attributes.role, 'alert');
  assert.equal(container.children[0].textContent, 'Your values are kept. Correct the weight count to continue.');
  assert.doesNotMatch(container.children[0].textContent, /calculation could not be completed/i);

  input.value = '1\n2\n3';
  await context.window.runNewCalculator('average');
  assert.equal(input.attributes['aria-invalid'], undefined);
  assert.equal(input.attributes['aria-describedby'], undefined);
  assert.equal(form.attributes['data-officekit-no-bug-report'], undefined);
  assert.equal(container.children[0].textContent, 'Latest result');
});

test('Average & Weighted Average card grows around its complete multiline form', () => {
  assert.match(css, /#tab-calculators:has\(#calc-form-average:not\(\.hidden\)\) > \.calc-card \{ flex: none; min-height: auto; padding-block: 1rem; \}/);
  assert.match(css, /#tab-calculators:has\(#calc-form-average:not\(\.hidden\)\) > \.calc-card > #calc-form-average:not\(\.hidden\) \{ flex: none; min-height: auto; \}/);
  const average = html.slice(html.indexOf('id="calc-form-average"'), html.indexOf('id="calc-form-fractions"'));
  assert.ok(average.indexOf('id="calc-average-result"') < average.indexOf('id="calc-average-values"'));
  assert.ok(average.indexOf('id="calc-average-weights"') < average.indexOf('id="calc-average-missing"'));
});

test('ROI requires a positive investment and links the correction to that field', () => {
  const { slice } = loadSlice();
  const spec = slice.specs.roi;
  assert.equal(spec.validationField, 'calc-roi-invested');
  assert.equal(spec.preventBugReportOnValidation, true);
  assert.equal(spec.hideActionsOnValidation, true);
  assert.deepEqual(plain(spec.validate({ invested: 0, returned: 1250, fees: 0 })), {
    field: 'calc-roi-invested',
    message: 'Initial investment must be greater than $0.',
    explanation: 'ROI compares gain with the initial investment. Enter a positive starting amount to continue.',
  });
  assert.equal(spec.validate({ invested: 1, returned: 1250, fees: 0 }), undefined);
});

test('CAGR requires a positive duration and links the correction to Years', () => {
  const { slice } = loadSlice();
  const spec = slice.specs.cagr;
  assert.equal(spec.validationField, 'calc-cagr-years');
  assert.equal(spec.preventBugReportOnValidation, true);
  assert.equal(spec.hideActionsOnValidation, true);
  assert.deepEqual(plain(spec.validate({ start_value: 100, end_value: 200, years: 0 })), {
    field: 'calc-cagr-years',
    message: 'Enter a number of years greater than zero.',
    explanation: 'CAGR needs a positive time period. Update Number of years to continue.',
  });
  assert.deepEqual(plain(spec.validate({ start_value: 100, end_value: 200, years: -1 })), {
    field: 'calc-cagr-years',
    message: 'Enter a number of years greater than zero.',
    explanation: 'CAGR needs a positive time period. Update Number of years to continue.',
  });
  assert.equal(spec.validate({ start_value: 100, end_value: 200, years: 1 }), undefined);
});

test('Business Days holiday validation opens details, marks the list and restores normal results after correction', () => {
  const elements = new Map();
  const makeElement = () => ({
    attributes: {}, className: '', textContent: '', removed: false,
    classList: { remove() {}, add() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    insertAdjacentElement(_position, element) { elements.set(element.id, element); },
    remove() { this.removed = true; elements.delete(this.id); },
    focus() { this.focused = true; },
    replaceChildren(...children) { this.children = children; },
  });
  const values = {
    'calc-business-days-start': { value: '2024-01-01' },
    'calc-business-days-end': { value: '2024-01-07' },
    'calc-business-days-inclusive': { checked: true },
    'calc-business-days-weekend': { value: 'sat-sun' },
    'calc-business-days-holidays': Object.assign(makeElement(), { value: '2024-02-30' }),
  };
  for (const [id, element] of Object.entries(values)) { element.id = id; elements.set(id, element); }
  const details = { open: false };
  values['calc-business-days-holidays'].closest = selector => selector === 'details' ? details : null;
  const form = makeElement();
  const actions = Object.assign(makeElement(), { remove() { this.removed = true; } });
  const container = makeElement();
  container.closest = selector => selector === '[data-calc-form]' ? form : null;
  container.querySelector = selector => selector === '.officekit-result-actions' ? actions : null;
  const document = { getElementById: id => elements.get(id) || null, createElement: () => makeElement() };
  const { slice, window } = loadSlice(document);
  let disableCalls = 0;
  window.officekitDisableCalculationActions = () => { disableCalls += 1; };
  const spec = slice.specs['business-days'];
  assert.equal(spec.preventBugReportOnValidation, true);
  assert.equal(spec.hideActionsOnValidation, true);
  let issue;
  assert.throws(() => spec.read(), error => {
    issue = error.fieldValidation;
    assert.equal(issue.field, 'calc-business-days-holidays');
    assert.equal(issue.message, 'Enter real dates as YYYY-MM-DD between 1600-01-01 and 2400-12-31.');
    return true;
  });

  slice.showValidationIssue(spec, issue, container);
  const input = values['calc-business-days-holidays'];
  const fieldMessage = elements.get('calc-business-days-holidays-validation');
  assert.equal(details.open, true);
  assert.equal(input.attributes['aria-invalid'], 'true');
  assert.equal(input.attributes['aria-describedby'], fieldMessage.id);
  assert.equal(input.focused, true);
  assert.equal(fieldMessage.textContent, issue.message);
  assert.equal(form.attributes['data-officekit-no-bug-report'], '');
  assert.equal(actions.removed, true);
  assert.equal(disableCalls, 1);
  assert.equal(container.children[0].textContent, 'Result appears here after you correct the holiday dates. Your other inputs are kept.');

  slice.clearValidationIssue(spec, container);
  assert.equal(input.attributes['aria-invalid'], undefined);
  assert.equal(input.attributes['aria-describedby'], undefined);
  assert.equal(fieldMessage.removed, true);
  assert.equal(form.attributes['data-officekit-no-bug-report'], undefined);
  input.value = '2024-02-29';
  assert.deepEqual(plain(spec.read().holidays), ['2024-02-29']);
});

test('Work Hours successful calculation brings the complete result above the fixed action dock', () => {
  assert.match(sliceSource, /if \(key === 'work-hours'\) container\.scrollIntoView\(\{ block: 'start' \}\);/);
  const workHours = html.slice(html.indexOf('id="calc-form-work-hours"'), html.indexOf('id="calc-form-time-zones"'));
  assert.ok(workHours.indexOf('id="calc-work-hours-result"') < workHours.indexOf('id="calc-work-hours-rows"'));
  assert.match(html, /id="calc-work-hours-run" data-calc-run/);
  assert.match(css, /#tab-calculators:has\(#calc-form-work-hours:not\(\.hidden\)\) > \.calc-card \{ flex: none; min-height: auto; \}/);
  assert.match(css, /#tab-calculators:has\(#calc-form-work-hours:not\(\.hidden\)\) > \.calc-card > #calc-form-work-hours:not\(\.hidden\) \{ flex: none; min-height: auto; \}/);
  assert.match(css, /#calc-work-hours-rows\[aria-invalid="true"\] \{ border-color: var\(--ok-error\) !important; \}/);
});

test('Work Hours local row errors stay editable and link guidance to the shift list', () => {
  const inputs = new Map([
    ['calc-work-hours-rows', { value: '2024-01-01 9:00 17:30 30\n2024-01-02 22:00 06:00 0' }],
    ['calc-work-hours-zone', { value: '' }],
  ]);
  const { slice } = loadSlice({ getElementById: id => inputs.get(id) || null });
  const spec = slice.specs['work-hours'];
  assert.equal(spec.preventBugReportOnValidation, true);
  assert.equal(spec.hideActionsOnValidation, true);
  assert.equal(spec.validationField, 'calc-work-hours-rows');
  assert.throws(() => spec.read(), error => {
    assert.equal(error.fieldValidation.field, 'calc-work-hours-rows');
    assert.equal(error.fieldValidation.message, 'Shift 1 times use the form HH:MM.');
    assert.equal(error.fieldValidation.statusMessage, 'Fix the marked shift row. Your entries are kept.');
    return true;
  });
  assert.deepEqual(plain(spec.validationFromError({ message: 'row 1: break must be shorter than the shift' })), {
    field: 'calc-work-hours-rows',
    message: 'Shift 1: Break must be shorter than the shift',
    statusMessage: 'Fix the marked shift row. Your entries are kept.',
  });
  inputs.get('calc-work-hours-rows').value = '2024-01-01 09:00 17:30 30';
  assert.deepEqual(plain(spec.read().rows), [{ date: '2024-01-01', start: '09:00', end: '17:30', break_minutes: 30 }]);
});

test('Time Zone Converter card contains daylight-saving field guidance above the fixed dock', () => {
  assert.match(css, /#tab-calculators:has\(#calc-form-time-zones:not\(\.hidden\)\) > \.calc-card \{ flex: none; min-height: auto; padding-block: 1rem; \}/);
  assert.match(css, /#tab-calculators:has\(#calc-form-time-zones:not\(\.hidden\)\) > \.calc-card > #calc-form-time-zones:not\(\.hidden\) \{ flex: none; min-height: auto; \}/);
  const start = html.indexOf('id="calc-form-time-zones"');
  const end = html.indexOf('id="calc-form-quadratic"', start);
  const timeZones = html.slice(start, end);
  assert.ok(timeZones.indexOf('id="calc-time-zones-time-error"') > timeZones.indexOf('id="calc-time-zones-time"'));
  assert.match(timeZones, /id="calc-time-zones-time-error" role="alert"/);
  assert.match(html, /id="calc-time-zones-result" role="status"/);
});
