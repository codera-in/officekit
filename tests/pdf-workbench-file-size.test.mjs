import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const formatters = fs.readFileSync(path.join(root, 'assets/officekit-formatters.js'), 'utf8');

test('PDF workbench uses readable shared units for every selected file', () => {
  const context = { window: {} };
  vm.runInNewContext(formatters, context);
  const formatSize = context.window.OfficeKitFormatters.fileSize;

  assert.equal(formatSize(0), '0 bytes');
  assert.equal(formatSize(1), '1 byte');
  assert.equal(formatSize(626), '626 bytes');
  assert.equal(formatSize(1024), '1.0 KiB');
  assert.equal(formatSize(1024 * 1024), '1.00 MiB');

  const selection = html.match(/function renderPdfSelection\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(selection, 'PDF selected-file list is rendered by the workbench');
  assert.match(selection, /size\.textContent = window\.OfficeKitFormatters\.fileSize\(file\.size\)/);
  assert.doesNotMatch(selection, /file\.size\s*\/\s*\(1024\s*\*\s*1024\)/);
});
