import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function getPythonCandidates({
  root = repositoryRoot,
  platform = process.platform,
  env = process.env,
  exists = existsSync,
} = {}) {
  const pathApi = platform === 'win32' ? path.win32 : path.posix;
  const virtualenvPython = platform === 'win32'
    ? pathApi.join(root, '.venv', 'Scripts', 'python.exe')
    : pathApi.join(root, '.venv', 'bin', 'python');
  const candidates = [];
  if (typeof env.PYTHON === 'string' && env.PYTHON.trim()) {
    candidates.push(env.PYTHON.trim());
  }
  if (exists(virtualenvPython)) candidates.push(virtualenvPython);
  candidates.push(platform === 'win32' ? 'python' : 'python3', 'python');
  return [...new Set(candidates)];
}

export function findPythonWithPytest(candidates, run = spawnSync) {
  for (const python of candidates) {
    const result = run(python, ['-m', 'pytest', '--version'], { encoding: 'utf8' });
    if (!result.error && result.status === 0) return python;
  }
  return null;
}

export function main({ run = spawnSync, env = process.env, platform = process.platform } = {}) {
  const candidates = getPythonCandidates({ env, platform });
  const python = findPythonWithPytest(candidates, run);
  if (!python) {
    console.error('Python tests need pytest. Install the pinned development dependencies from requirements.txt.');
    return 1;
  }

  const result = run(python, ['-m', 'pytest', 'tests/', '-v'], {
    stdio: 'inherit',
    env: { ...env, PYTHONUTF8: '1' },
  });
  return result.error ? 1 : (result.status ?? 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
