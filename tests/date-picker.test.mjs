import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'assets/officekit-date-picker.js'), 'utf8');
const styles = fs.readFileSync(path.join(root, 'assets/officekit-date-picker.css'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const files = fs.readFileSync(path.join(root, 'assets/officekit-files.js'), 'utf8');
const mockWindow = { document: undefined };
vm.runInNewContext(source, { window: mockWindow, Intl, Date, Array, String, Math });
const picker = mockWindow.OfficeKitDatePicker;

test('date parsing accepts only real ISO calendar dates', () => {
  assert.equal(picker.dateKey(picker.parseDate('2024-02-29')), '2024-02-29');
  for (const value of ['2023-02-29', '2024-02-30', '2024-2-03', '02/29/2024', '']) assert.equal(picker.parseDate(value), null);
});

test('locale calendar grid always covers six complete weeks from the requested week start', () => {
  const mondayStart = picker.monthCells(2024, 1, 1);
  assert.equal(mondayStart.length, 42);
  assert.equal(mondayStart[0].value, '2024-01-29');
  assert.equal(mondayStart[0].inMonth, false);
  assert.equal(mondayStart.find(cell => cell.value === '2024-02-29').inMonth, true);
  const sundayStart = picker.monthCells(2024, 1, 0);
  assert.equal(sundayStart[0].value, '2024-01-28');
});

test('one reusable themed picker serves calculator and dynamically created file date fields', () => {
  const ids = ['calc-date-difference-start', 'calc-date-difference-end', 'calc-age-birth', 'calc-age-as-of', 'calc-business-days-start', 'calc-business-days-end', 'calc-time-zones-date'];
  for (const id of ids) assert.match(html, new RegExp(`<input id="${id}" type="date"`));
  assert.match(html, /officekit-date-picker\.css/);
  assert.match(html, /officekit-date-picker\.js/);
  assert.match(files, /OfficeKitDatePicker\?\.initialize\(options\)/);
  assert.match(source, /dispatchEvent\(new global\.Event\('input'/);
  assert.match(source, /aria-haspopup', 'dialog'/);
  assert.match(source, /aria-keyshortcuts', 'Alt\+ArrowDown'/);
  assert.match(source, /event\.clientX >= bounds\.right - 42/);
  assert.equal([...source.matchAll(/<button\b/g)].length, 2, 'only previous/next month buttons are part of the calendar');
  assert.match(source, /if \(!input\.isConnected\) \{ dispose\(\); mountedInputs\.delete\(input\); \}/);
  assert.match(source, /doc\.removeEventListener\('pointerdown', onPointerDown\)/);
  assert.match(source, /event\.key === 'Escape'/);
  assert.match(source, /input\.dataset\.locale \|\| global\.navigator\?\.language/);
  assert.match(source, /getBoundingClientRect\(\)\.height > 0/);
  assert.match(styles, /background:var\(--ok-surface-opaque\)/);
  assert.match(styles, /:root\[data-theme\] \.ok-app \.ok-date-picker:not\(\[hidden\]\)\{background-color:var\(--ok-surface-opaque\)\}/);
  assert.match(styles, /color:var\(--ok-text\)/);
  assert.match(styles, /\.officekit-date-picker-open #officekit-tool-actions\{visibility:hidden!important\}/);
  assert.match(styles, /body\.officekit-date-picker-open \.officekit-result-actions\{display:none!important\}/);
  assert.doesNotMatch(source, /ok-date-picker-trigger/);
  assert.match(source, /Choose a date · results return after selection/);
});
