import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getPythonCandidates } from './run-python-tests.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const coverageDir = path.join(root, 'coverage/process-manager');
const pythonTests = [
  'tests/test_process_manager_unittest.py',
  'tests/test_process_manager_api_unittest.py',
  'tests/test_process_quit_eligibility_unittest.py',
];

export function findPythonWithCoverage(candidates, run = spawnSync) {
  for (const python of candidates) {
    const pytest = run(python, ['-m', 'pytest', '--version'], { encoding: 'utf8' });
    const coverage = run(python, ['-m', 'coverage', '--version'], { encoding: 'utf8' });
    if (!pytest.error && pytest.status === 0 && !coverage.error && coverage.status === 0) return python;
  }
  return null;
}

function run(python, args) {
  const result = spawnSync(python, args, { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' } });
  if (result.error || result.status !== 0) throw new Error(`Process manager coverage failed: ${python} ${args.join(' ')}`);
}

export function main() {
  const python = findPythonWithCoverage(getPythonCandidates());
  if (!python) throw new Error('Process manager coverage needs pytest and coverage.py; install the pinned development dependencies from requirements-dev.txt.');
  mkdirSync(coverageDir, { recursive: true });
  const dataFile = path.join(coverageDir, '.coverage');
  run(python, ['-m', 'coverage', 'erase', `--data-file=${dataFile}`]);
  run(python, ['-m', 'coverage', 'run', `--data-file=${dataFile}`, '--branch', '--source=officekit.engines.engine_process_manager', '-m', 'pytest', ...pythonTests, '-q']);
  run(python, ['-m', 'coverage', 'report', `--data-file=${dataFile}`, '--include=officekit/engines/engine_process_manager.py', '--fail-under=100']);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
