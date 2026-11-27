import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const context = vm.createContext({ Intl });
vm.runInContext(source.split('/* CURRENCY DISPLAY START */')[1].split('/* CURRENCY DISPLAY END */')[0], context);

test('USD display preserves cents and uses explicit locale grouping', () => {
  assert.equal(context.officekitFormatUsd(100, 'en-US'), '$100.00');
  assert.equal(context.officekitFormatUsd(1200, 'en-US'), '$1,200.00');
  assert.equal(context.officekitFormatUsd(0, 'en-US'), '$0.00');
  assert.equal(context.officekitFormatUsd(-12.5, 'en-US'), '-$12.50');
  assert.equal(context.officekitFormatUsd(1200, 'de-DE'), '1.200,00\u00a0$');
  assert.equal(typeof context.officekitFormatUsd(100), 'string');
});

test('monetary display rejects malformed values rather than rendering NaN or undefined', () => {
  for (const value of [null, undefined, '100', NaN, Infinity, -Infinity, {}, []]) {
    assert.throws(() => context.officekitFormatUsd(value), /invalid monetary result/);
  }
});
