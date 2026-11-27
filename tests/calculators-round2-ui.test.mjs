// Round-2 guards for the calculators slice: the Statistics radios show visible focus (UX-14), and no coded engine
// message reaches visible text, with the nonexistent local time shown at its field (UX-15).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sliceSource = readFileSync(path.join(root, 'assets', 'officekit-slice-calculators.js'), 'utf8');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const css = readFileSync(path.join(root, 'assets', 'officekit.input.css'), 'utf8');

// Runs the slice in a VM with a stub document, so the time-zone error path is exercised as the browser runs it.
function loadSliceWithDocument() {
  const nodes = new Map();
  const document = { activeElement: null, getElementById: id => node(id) };
  const node = id => {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, {
        id,
        value: '',
        textContent: '',
        attributes: {},
        classList: { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name) },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        removeAttribute(name) { delete this.attributes[name]; },
        focus() { document.activeElement = this; },
      });
    }
    return nodes.get(id);
  };
  const context = { window: {}, document, fetch: () => { throw new Error('no network in tests'); } };
  context.window.OfficeKitExtensions = { register() {} };
  context.window.document = context.document;
  vm.runInNewContext(sliceSource, context);
  return { slice: context.window.OfficeKitCalcSlice, node, document };
}

test('the Statistics Sample and Whole population pills keep the approved look and show keyboard focus on the pill', () => {
  const radios = [...html.matchAll(/<input type="radio" name="calc-statistics-kind"[^>]*>/g)].map(match => match[0]);
  assert.equal(radios.length, 2);
  for (const radio of radios) assert.match(radio, /class="sr-only"/, `${radio} hides the native dot, as the mock draws it`);
  assert.match(html, /<div role="radiogroup" aria-label="Data is" class="ok-calc-seg /);
  assert.match(css, /\.ok-app \.ok-calc-seg > label:has\(input:focus-visible\) \{ outline: 3px solid var\(--ok-focus\)/);
});

test('the invalid-field border rule is in the stylesheet, skips focused fields and only reaches calculator forms', () => {
  assert.match(css, /\.ok-app \[data-calc-form\] :is\(input, select, textarea\)\[aria-invalid="true"\]:not\(:focus\) \{ border-color: var\(--ok-error\) !important; \}/);
  // Other screens set aria-invalid too (PDF protect passwords), so no unscoped rule may recolour them.
  assert.doesNotMatch(css, /^\.ok-app :is\(input, select, textarea\)\[aria-invalid/m);
});

test('a nonexistent local time shows the approved sentence at the time field and never the engine code', () => {
  const { slice, node, document } = loadSliceWithDocument();
  node('calc-time-zones-date').value = '2026-03-08';
  node('calc-time-zones-time').value = '02:30';
  const handled = slice.specs['time-zones'].onError(new Error('NONEXISTENT_TIME: this local time does not exist in the source zone'));
  assert.equal(handled, true);
  const field = node('calc-time-zones-time-error');
  assert.equal(field.textContent, '02:30 does not exist on this date in this zone because clocks go forward. Choose another time.');
  assert.equal(field.classList.contains('hidden'), false);
  assert.doesNotMatch(field.textContent, /NONEXISTENT_TIME|AMBIGUOUS_TIME/);
  assert.equal(node('calc-time-zones-time').attributes['aria-invalid'], 'true');
  assert.equal(node('calc-time-zones-time').attributes['aria-describedby'], 'calc-time-zones-time-error');
  assert.equal(document.activeElement, node('calc-time-zones-time'), 'focus moves to the invalid time field');
  assert.match(html, /<p id="calc-time-zones-time-error" role="alert" /, 'the message is announced when it appears');
});

test('a repeated local time still opens the earlier-or-later choice and does not use the field error', () => {
  const { slice, node } = loadSliceWithDocument();
  node('calc-time-zones-date').value = '2026-11-01';
  node('calc-time-zones-time').value = '01:30';
  const handled = slice.specs['time-zones'].onError(new Error('AMBIGUOUS_TIME: choose the earlier or later occurrence'));
  assert.equal(handled, true);
  assert.equal(node('calc-time-zones-choice').classList.contains('hidden'), false);
  assert.match(node('calc-time-zones-choice-note').textContent, /01:30 happens twice on 2026-11-01/);
  assert.equal(node('calc-time-zones-time').attributes['aria-invalid'], undefined);
});

test('the error function never shows a coded engine message as visible text', () => {
  const errorFn = html.match(/function officekitShowCalculatorError\(container, error, options = \{\}\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(errorFn, 'error function exists');
  assert.match(errorFn, /codedMessage = \/\^\[A-Z\]\[A-Z_\]\+: \/\.test\(error\?\.message \?\? ''\)/);
  assert.match(errorFn, /codedMessage \? 'Check the inputs and try again\.' : \(options\.message \?\? error\.message\)/);
});
