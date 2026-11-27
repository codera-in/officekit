import { spawnSync } from 'node:child_process';
import { mkdir, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getPythonCandidates, findPythonWithPytest } from './run-python-tests.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const normalized = value => value.replaceAll('\\', '/');
const locate = (entries, filename) => Object.entries(entries).find(([name]) => normalized(name) === filename || normalized(name).endsWith('/' + filename))?.[1];

// Inventory is discovered from shipping source, so an unimported new file fails
// the gate instead of disappearing from an include/exclude list.
export function assessInvoiceCoverage(reports, inventory) {
  const errors = [];
  for (const filename of inventory.python) {
    const file = locate(reports.python.files, filename);
    if (!file) { errors.push(`${filename}: missing Python coverage`); continue; }
    if (file.summary.missing_lines || file.summary.missing_branches || file.summary.excluded_lines) errors.push(`${filename}: incomplete or excluded lines/branches`);
    if (!file.functions) { errors.push(`${filename}: missing function coverage`); continue; }
    for (const [name, fn] of Object.entries(file.functions)) {
      if (name && fn.summary.num_statements > 0 && fn.summary.covered_lines === 0) errors.push(`${filename}: uncalled function ${name}`);
    }
  }
  for (const filename of inventory.javascript) {
    const file = locate(reports.javascript, filename);
    if (!file) { errors.push(`${filename}: missing JavaScript coverage`); continue; }
    if (!file.s || !file.f || !file.b) { errors.push(`${filename}: missing statement/function/branch counters`); continue; }
    if (Object.values(file.s).some(count => count === 0) || Object.values(file.f).some(count => count === 0) || Object.values(file.b).flat().some(count => count === 0)) errors.push(`${filename}: incomplete statement/function/branch coverage`);
  }
  for (const filename of inventory.native) {
    const file = reports.native.data.flatMap(entry => entry.files).find(entry => normalized(entry.filename).endsWith('/' + filename));
    if (!file) { errors.push(`${filename}: missing native coverage`); continue; }
    for (const metric of ['lines', 'functions', 'branches']) {
      const counter = file.summary[metric];
      if (!counter || counter.count !== counter.covered) errors.push(`${filename}: incomplete native ${metric}`);
    }
  }
  return errors;
}

function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', env: { ...process.env, ...extraEnv } });
  if (result.error || result.status !== 0) throw new Error(`Invoice coverage command failed: ${command} ${args.join(' ')}`);
}

export async function main() {
  await mkdir(path.join(root, 'coverage/invoices'), { recursive: true });
  const python = findPythonWithPytest(getPythonCandidates());
  if (!python) throw new Error('Invoice coverage requires Python with pytest and coverage.py.');
  const pythonTests = (await readdir(path.join(root, 'tests'))).filter(name => /^test_invoices_.*\.py$/.test(name)).sort().map(name => 'tests/' + name);
  const jsTests = (await readdir(path.join(root, 'tests'))).filter(name => /^invoices.*\.test\.mjs$/.test(name)).sort().map(name => 'tests/' + name);
  run(python, ['-m', 'coverage', 'run', '--rcfile=scripts/invoice-coverage.ini', '-m', 'pytest', ...pythonTests, '-q']);
  run(python, ['-m', 'coverage', 'json', '--rcfile=scripts/invoice-coverage.ini']);
  run(process.execPath, ['node_modules/c8/bin/c8.js', '--all', '--include=assets/officekit-slice-invoices.js', '--reports-dir=coverage/invoices/javascript', '--temp-directory=coverage/invoices/v8', '--reporter=json', '--reporter=text', '--check-coverage', '--lines=100', '--functions=100', '--branches=100', process.execPath, '--test', ...jsTests]);
  // Rust branch instrumentation is unstable, enabled only for this test process;
  // shipping builds retain the ordinary stable compiler configuration.
  run('cargo', ['llvm-cov', '--manifest-path', 'src-tauri/Cargo.toml', '--branch', '--lib', '--json', '--output-path', 'coverage/invoices/native.json', '--', 'invoice_'], { RUSTC_BOOTSTRAP: '1' });
  const reports = {
    python: JSON.parse(await readFile(path.join(root, 'coverage/invoices/python.json'), 'utf8')),
    javascript: JSON.parse(await readFile(path.join(root, 'coverage/invoices/javascript/coverage-final.json'), 'utf8')),
    native: JSON.parse(await readFile(path.join(root, 'coverage/invoices/native.json'), 'utf8')),
  };
  const inventory = {
    python: (await readdir(path.join(root, 'officekit/invoices'))).filter(name => name.endsWith('.py')).map(name => 'officekit/invoices/' + name),
    javascript: (await readdir(path.join(root, 'assets'))).filter(name => /^officekit.*invoices.*\.js$/.test(name)).map(name => 'assets/' + name),
    native: (await readdir(path.join(root, 'src-tauri/src'))).filter(name => /^invoice.*\.rs$/.test(name) && !name.endsWith('_tests.rs')).map(name => 'src-tauri/src/' + name),
  };
  const errors = assessInvoiceCoverage(reports, inventory);
  if (errors.length) throw new Error(errors.join('\n'));
  process.stdout.write('Invoice module: 100% lines, branches and functions across the complete Python/JavaScript/native source inventory.\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
