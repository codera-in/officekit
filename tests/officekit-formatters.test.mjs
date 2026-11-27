import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'assets/officekit-formatters.js'), 'utf8');

test('shared file-size formatter uses readable byte units and rejects invalid sizes', () => {
  const context = { window: {} };
  vm.runInNewContext(source, context);
  const format = context.window.OfficeKitFormatters.fileSize;

  assert.equal(format(0), '0 bytes');
  assert.equal(format(1), '1 byte');
  assert.equal(format(1023), '1,023 bytes');
  assert.equal(format(1024), '1.0 KiB');
  assert.equal(format(1536), '1.5 KiB');
  assert.equal(format(1024 * 1024), '1.00 MiB');
  assert.equal(format(-1), 'Size unavailable');
  assert.equal(format(1.5), 'Size unavailable');
});
