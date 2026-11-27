import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sliceSource = readFileSync(path.join(root, 'assets', 'officekit-slice-calculators.js'), 'utf8');

function loadTimeZoneSpec() {
  const elements = new Map();
  const makeElement = (value = '') => ({
    value,
    textContent: '',
    attributes: {},
    classList: { add() {}, remove() {} },
    setAttribute(name, attributeValue) { this.attributes[name] = attributeValue; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() {},
  });
  for (const [id, value] of [
    ['calc-form-time-zones', ''],
    ['calc-time-zones-time', '02:30'],
    ['calc-time-zones-date', '2026-03-08'],
    ['calc-time-zones-time-error', ''],
    ['calc-time-zones-choice-note', ''],
    ['calc-time-zones-choice', ''],
  ]) elements.set(id, makeElement(value));

  const window = { OfficeKitExtensions: { register() {} } };
  const document = { getElementById: id => elements.get(id) || null };
  window.document = document;
  vm.runInNewContext(sliceSource, { window, document, fetch() { throw new Error('unexpected request'); } });
  return { spec: window.OfficeKitCalcSlice.specs['time-zones'], elements };
}

test('Time Zone Converter labels stale output and keeps DST corrections local', () => {
  const { spec, elements } = loadTimeZoneSpec();
  const previous = { date: '2026-01-15', time: '12:00', from_zone: 'America/New_York' };

  assert.equal(
    spec.staleResult(previous),
    'This conversion is for 2026-01-15 at 12:00 in America/New_York. Current inputs have not been converted.'
  );

  assert.equal(spec.onError(new Error('NONEXISTENT_TIME: spring-forward gap')), true);
  assert.equal(elements.get('calc-form-time-zones').attributes['data-officekit-no-bug-report'], '');
  assert.match(elements.get('calc-time-zones-time-error').textContent, /does not exist on this date/);

  elements.get('calc-form-time-zones').removeAttribute('data-officekit-no-bug-report');
  assert.equal(spec.onError(new Error('AMBIGUOUS_TIME: repeated local time')), true);
  assert.equal(elements.get('calc-form-time-zones').attributes['data-officekit-no-bug-report'], '');
  assert.match(elements.get('calc-time-zones-choice-note').textContent, /happens twice/);
});
