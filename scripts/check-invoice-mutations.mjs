import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-invoice-mutations-'));
const checkout = path.join(tempRoot, 'checkout');
const cases = [
  {
    name: 'domain monetary rounding', file: 'officekit/invoices/domain.py',
    find: 'Decimal(value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)',
    replace: 'Decimal(value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_DOWN)',
    command: '.venv/bin/python', args: ['-m', 'pytest', '-q', 'tests/test_invoices_domain.py'],
    expectRed: 'FAILED tests/test_invoices_domain.py::test_totals_use_decimal',
  },
  {
    name: 'storage external-edit conflict detection', file: 'officekit/invoices/storage.py',
    find: 'if expected_data is not None and _read_file(directory, name, MAX_DATABASE_BYTES) != expected_data:',
    replace: 'if False and expected_data is not None and _read_file(directory, name, MAX_DATABASE_BYTES) != expected_data:',
    command: '.venv/bin/python', args: ['-m', 'pytest', '-q', 'tests/test_invoices_storage.py'],
    expectRed: 'Failed: DID NOT RAISE InvoiceStorageError',
  },
  {
    name: 'route validation error mapping', file: 'officekit/invoices/routes.py',
    find: 'return JSONResponse({"error": {"code": "INVALID_INVOICE_INPUT", "message": "Invoice input is invalid or exceeds supported limits.", "details": []}}, status_code=422)',
    replace: 'return JSONResponse({"error": {"code": "INVALID_INVOICE_INPUT", "message": "Invoice input is invalid or exceeds supported limits.", "details": []}}, status_code=400)',
    command: '.venv/bin/python', args: ['-m', 'pytest', '-q', 'tests/test_invoices_routes.py'],
    expectRed: 'assert 400 == 422',
  },
  {
    name: 'invoice PDF download action', file: 'assets/officekit-slice-invoices.js',
    find: "await download(blob, 'invoice.pdf');", replace: "await download(blob, 'broken.pdf');",
    command: 'node', args: ['--test', 'tests/invoices-ui.test.mjs'],
    expectRed: "expected: 'invoice.pdf'",
  },
];

let failed = false;
try {
  execFileSync('git', ['worktree', 'add', '--detach', checkout, 'HEAD'], { cwd: root, stdio: 'ignore' });
  for (const dependency of ['node_modules', '.venv']) {
    const original = path.join(root, dependency);
    if (fs.existsSync(original)) fs.symlinkSync(original, path.join(checkout, dependency), 'dir');
  }
  for (const item of cases) {
    const filename = path.join(checkout, item.file);
    const original = fs.readFileSync(filename, 'utf8');
    const occurrences = original.split(item.find).length - 1;
    if (occurrences !== 1) throw new Error(`${item.name}: expected one mutation anchor, found ${occurrences}`);
    try {
      fs.writeFileSync(filename, original.replace(item.find, item.replace));
      const result = spawnSync(item.command, item.args, { cwd: checkout, encoding: 'utf8' });
      const output = `${result.stdout || ''}${result.stderr || ''}`;
      if (result.error) throw result.error;
      if (result.status === 0 || !output.includes(item.expectRed)) {
        failed = true;
        process.stdout.write(`FAIL: ${item.name} did not produce its expected regression assertion\n`);
      } else {
        process.stdout.write(`GUARD PROVEN: ${item.name} (exit ${result.status}; matched ${item.expectRed})\n`);
      }
      process.stdout.write(output.trim().split('\n').slice(-14).join('\n') + '\n');
    } finally {
      fs.writeFileSync(filename, original);
    }
  }
} finally {
  try { execFileSync('git', ['worktree', 'remove', '--force', checkout], { cwd: root, stdio: 'ignore' }); } catch {}
  fs.rmSync(tempRoot, { recursive: true, force: true });
}
if (failed) process.exitCode = 1;
