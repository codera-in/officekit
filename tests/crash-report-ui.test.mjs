import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const crashMarkup = html.match(/<!-- Apple-style Diagnostic Crash Reporter Modal Dialog -->([\s\S]*?)<!-- License Activation Modal Dialog -->/)?.[1] ?? '';

function makeContext(writeText) {
  const elements = {
    'crash-summary-msg': { textContent: 'PDF operation failed' },
    'crash-stacktrace-box': { textContent: 'PDF parser failed at /Users/test/Documents/private.pdf' },
    'crash-report-status': { textContent: '', classList: { add() {}, remove() {} } },
    'copy-crash-btn': { disabled: false },
  };
  const start = html.indexOf('        function showAppleCrashReport(diagnostic, userErrorMsg) {');
  const end = html.indexOf('        // ==========================================\n        // Global Search Palette', start);
  assert.ok(start >= 0 && end > start, 'crash-report functions exist in the expected script section');
  const source = html.slice(start, end);
  const context = {
    document: { getElementById: id => elements[id] },
    navigator: { clipboard: { writeText } },
    currentCrashDiagnostic: null,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, elements };
}

test('crash screen offers one honest copy path and keeps technical details collapsed', () => {
  assert.match(crashMarkup, /<details/);
  assert.match(crashMarkup, /Copy diagnostic details/);
  assert.match(crashMarkup, /Nothing is sent automatically/);
  assert.match(crashMarkup, /local file paths/);
  assert.doesNotMatch(crashMarkup, /Send to Developers|email it directly|rapid fix/i);
  const actions = html.match(/const OFFICEKIT_DELEGATED_ACTIONS = new Set\(\[([\s\S]*?)\]\);/)?.[1] ?? '';
  assert.match(actions, /'copyCrashLog'/);
  assert.doesNotMatch(actions, /'emailCrashReport'/);
});

test('copy action includes the summary and trace and reports successful clipboard copy', async () => {
  let copied = '';
  const { context, elements } = makeContext(async value => { copied = value; });
  await context.copyCrashLog();
  assert.match(copied, /PDF operation failed/);
  assert.match(copied, /private\.pdf/);
  assert.match(elements['crash-report-status'].textContent, /Copied.*report was sent/i);
  assert.equal(elements['copy-crash-btn'].disabled, false);
});

test('copy action reports clipboard denial and leaves details available for manual copy', async () => {
  const { context, elements } = makeContext(async () => { throw new Error('permission denied'); });
  await context.copyCrashLog();
  assert.match(elements['crash-report-status'].textContent, /clipboard.*select.*copy them manually/i);
  assert.equal(elements['copy-crash-btn'].disabled, false);
});
