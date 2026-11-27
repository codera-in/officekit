// Round-1 guards for the calculators slice: approved-mock conformance (UX-1..UX-13), the Button Limit (UX-5, QA-3)
// and the source guard for innerHTML writes (QA-6). Markup-level: the slice runs in the browser, so these read the
// shipped source and the Calculators section of index.html.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sliceSource = readFileSync(path.join(root, 'assets', 'officekit-slice-calculators.js'), 'utf8');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');

const calcStart = html.indexOf('<section id="tab-calculators"');
const calcSection = html.slice(calcStart, html.indexOf('</section>', calcStart));
const calcForms = calcSection.split(/(?=<div id="calc-form-)/).slice(1);
// A button counts toward the Button Limit unless it is an in-text link or the inline Copy link.
const countsAsButton = tag => !/\bclass="[^"]*\blink\b/.test(tag) && !/data-inline-action/.test(tag);
const resultActionsTemplate = html.match(/actions\.innerHTML = '([^']*data-export-calculation[^']*)';/)?.[1];

test('every calculator form keeps at most three buttons: before a result, after a result and after an input change', () => {
  assert.equal(calcForms.length, 24);
  for (const form of calcForms) {
    const id = form.match(/id="calc-form-([a-z-]+)"/)[1];
    const buttons = [...form.matchAll(/<button\b[^>]*>/g)].map(match => match[0]).filter(countsAsButton);
    const others = buttons.filter(tag => !/data-calc-run/.test(tag));
    assert.ok(buttons.some(tag => /data-calc-run/.test(tag)), `${id} has a run button`);
    // Before a result the form shows only Calculate. After a result or an input change the three-button result group
    // replaces it, so no body button may remain alongside that group.
    assert.equal(buttons.length, 1, `${id} shows ${buttons.length} buttons before a result`);
    assert.equal(others.length, 0, `${id} has ${others.length} body buttons besides the result group`);
  }
});

test('result actions are built in the approved order, with no aria-label that hides the visible text', () => {
  assert.ok(resultActionsTemplate, 'result actions template exists');
  const buttons = [...resultActionsTemplate.matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
  assert.equal(buttons.length, 2);
  assert.doesNotMatch(resultActionsTemplate, /aria-label=/);
  assert.doesNotMatch(resultActionsTemplate, /data-calc-again/);
  const order = ['data-save-calculation', 'data-export-calculation'];
  assert.deepEqual(order.map(attribute => buttons.findIndex(tag => tag.includes(attribute))), [0, 1]);
  assert.doesNotMatch(html, /aria-label="Save calculator result"/);
  assert.doesNotMatch(html, /aria-label="Download result"/);
});

test('calculators recalculate live after the last key, only once every required field has a value', () => {
  assert.match(sliceSource, /const LIVE_DELAY_MS = 300;/);
  const run = sliceSource.match(/function runLive\(form\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(run, 'runLive exists');
  assert.match(run, /requiredFieldEmpty\(form\)\) \{[^}]*showFillHint\(form\)/);
  assert.match(run, /shownInputs\.get\(form\) === inputSignature\(form\)\) return;/);
  assert.match(run, /\[data-calc-run\]'\)\?\.click\(\)/);
  assert.match(sliceSource, /Fill in every field to see the result\./);
  assert.doesNotMatch(sliceSource, /Inputs changed — calculate to update\./);
  assert.doesNotMatch(sliceSource, /function markStale/);
});

test('warning text does not use a raw Tailwind colour', () => {
  assert.doesNotMatch(sliceSource, /text-amber-700/);
});

test('the unit converter Swap is an in-text link, so it adds no body button after a result', () => {
  assert.match(html, /<button type="button" id="unit-swap" class="link"/);
});

test('innerHTML and outerHTML writes are caught by the source guard, including compound assignment', () => {
  const guard = /(?:inner|outer)HTML['"`\]\s]*(?:\+|\|\||\?\?|&&)?=(?!=)|insertAdjacentHTML\s*\(|document\.write(?:ln)?\(/;
  assert.match('x.innerHTML &&= y', guard);
  assert.match('document.writeln(y)', guard);
  assert.doesNotMatch(sliceSource, guard);
  assert.match("x[ 'innerHTML' ] = y", guard);
  assert.match('x[`innerHTML`] = y', guard);
  assert.match("x.insertAdjacentHTML('beforeend', y)", guard);
  assert.match('x.innerHTML += y', guard);
  assert.match('x.outerHTML = y', guard);
  assert.match('document.write(y)', guard);
  assert.match("x['innerHTML'] = y", guard);
  assert.match('x["outerHTML"] ??= y', guard);
  assert.doesNotMatch('x.innerHTML == y', guard);
});

test('the error state is an assertive alert with the approved heading and body', () => {
  const errorFn = html.match(/function officekitShowCalculatorError\(container, error, options = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(errorFn, 'error function exists');
  assert.match(errorFn, /setAttribute\('role', options\.role \|\| 'alert'\)/);
  assert.match(errorFn, /This calculation could not be completed\./);
  assert.match(errorFn, /Your inputs are kept\. Check that OfficeKit is running and try again\./);
});

test('approved copy: screen titles for statistics and time zones, date difference description', () => {
  assert.match(html, /<h1 id="calc-screen-title"/);
  assert.match(html, /statistics: \['Statistics'/);
  assert.match(html, /'time-zones': \['Time zones'/);
  assert.match(html, /Calendar dates only; no time of day or time zone\./);
});

test('date difference and business days wire their approved inclusive checkboxes', () => {
  assert.match(html, /<input id="calc-date-difference-inclusive" type="checkbox"(?! checked)/);
  assert.match(html, /<input id="calc-business-days-inclusive" type="checkbox" checked/);
  assert.match(sliceSource, /inclusive: el\('calc-date-difference-inclusive'\)\.checked/);
  assert.match(sliceSource, /inclusive: el\('calc-business-days-inclusive'\)\.checked/);
});

test('statistics data set is a Sample / Whole population segmented control, not a select', () => {
  assert.match(html, /<input type="radio" name="calc-statistics-kind" value="sample" checked/);
  assert.match(html, /<input type="radio" name="calc-statistics-kind" value="population"/);
  assert.doesNotMatch(html, /id="calc-statistics-kind" class="[^"]*select/);
});

test('the time zone repeated-hour choice stays hidden until the time is ambiguous; business-day holidays sit in Weekend and holidays', () => {
  assert.match(html, /<fieldset id="calc-time-zones-choice" class="[^"]*\bhidden\b/);
  assert.match(html, /<details[^>]*>\s*<summary[^>]*>Weekend and holidays<\/summary>/);
  const businessDays = calcSection.slice(calcSection.indexOf('id="calc-form-business-days"'));
  assert.ok(businessDays.indexOf('<details') < businessDays.indexOf('calc-business-days-holidays'));
});

test('the result label row carries the Copy result link on the same line as the label', () => {
  assert.match(html, /data-calc-copy-head/);
  assert.match(html, /copyHead\.className = 'mb-2 flex items-center justify-between gap-3'/);
});
