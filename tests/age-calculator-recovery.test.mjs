import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'assets/officekit-slice-calculators.js'), 'utf8');

function loadSlice(document) {
  let fetchCalls = 0;
  const context = {
    window: { OfficeKitExtensions: { register() {} } },
    document,
    fetch() { fetchCalls += 1; throw new Error('Date-order validation must not make a request.'); },
  };
  context.window.document = document;
  vm.runInNewContext(source, context);
  return { slice: context.window.OfficeKitCalcSlice, window: context.window, get fetchCalls() { return fetchCalls; } };
}

test('Age Calculator links date-order guidance, avoids a request, hides stale actions and clears on correction', async () => {
  const elements = new Map();
  const makeElement = () => ({
    attributes: {}, className: '', textContent: '', removed: false,
    classList: { add() {}, remove() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    insertAdjacentElement(_position, element) { elements.set(element.id, element); },
    remove() { this.removed = true; elements.delete(this.id); },
    focus() {},
    replaceChildren(...children) { this.children = children; },
  });
  const form = makeElement();
  form.querySelectorAll = () => [];
  const input = makeElement();
  input.value = '1999-12-31';
  const birth = makeElement();
  birth.value = '2000-02-29';
  const actions = makeElement();
  const result = makeElement();
  elements.set('calc-age-as-of', input);
  elements.set('calc-age-birth', birth);
  elements.set('calc-age-result', result);
  result.closest = selector => selector === '[data-calc-form]' ? form : null;
  result.querySelector = selector => selector === '.officekit-result-actions' ? actions : null;
  const document = {
    getElementById: id => elements.get(id) || null,
    createElement: () => makeElement(),
  };
  const loaded = loadSlice(document);
  const { slice, window } = loaded;
  const spec = slice.specs.age;
  const issue = spec.validate({ birth_date: '2000-02-29', as_of_date: '1999-12-31' });

  assert.equal(issue.field, 'calc-age-as-of');
  assert.equal(issue.message, 'Choose a date on or after the date of birth.');
  assert.equal(spec.validate({ birth_date: '2000-02-29', as_of_date: '2025-02-28' }), undefined);

  assert.equal(await window.runNewCalculator('age'), false);
  assert.equal(loaded.fetchCalls, 0, 'a correctable date-order issue is handled before the API call');
  const guidance = elements.get('calc-age-as-of-validation');
  assert.equal(guidance.textContent, issue.message);
  assert.equal(guidance.attributes.role, 'alert');
  assert.equal(input.attributes['aria-invalid'], 'true');
  assert.equal(input.attributes['aria-describedby'], guidance.id);
  assert.equal(form.attributes['data-officekit-no-bug-report'], '');
  assert.equal(actions.removed, true);
  assert.equal(result.attributes.role, 'status');
  assert.equal(result.children[0].textContent, 'Result appears here after you correct the date. Your dates are kept.');

  slice.clearValidationIssue(spec, result);
  assert.equal(input.attributes['aria-invalid'], undefined);
  assert.equal(input.attributes['aria-describedby'], undefined);
  assert.equal(guidance.removed, true);
  assert.equal(form.attributes['data-officekit-no-bug-report'], undefined);
});
