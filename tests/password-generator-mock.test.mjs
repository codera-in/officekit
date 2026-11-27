import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const mock = readFileSync(path.join(root, 'design/mocks/password-generator-workbench.html'), 'utf8');

test('password generator mock follows the approved OfficeKit shell and monogram', () => {
  assert.match(mock, /aria-label="OfficeKit navigation"/);
  assert.match(mock, /aria-current="page">Privacy &amp; Security/);
  assert.match(mock, /viewBox="0 0 1024 1024"/);
  assert.match(mock, /data-theme="dark"/);
  assert.doesNotMatch(mock, /linear-gradient/);
});

test('password generator mock explains settings and theoretical output space', () => {
  assert.match(mock, /id="length-number" type="number" min="12" max="256"/);
  assert.match(mock, /id="symbols" type="checkbox" checked/);
  assert.match(mock, /Theoretical search space/);
  assert.match(mock, /does not measure reuse or whether a password has been exposed/);
});

test('password generator mock keeps secrets out of persistent and network features', () => {
  assert.match(mock, /does not save generated passwords to history, favorites, or telemetry/);
  assert.match(mock, /never sent with usage telemetry/);
  assert.match(mock, /Prototype only\. Controls show the proposed flow and do not generate or copy a password/);
  assert.doesNotMatch(mock, /localStorage|fetch\s*\(|XMLHttpRequest/);
});
