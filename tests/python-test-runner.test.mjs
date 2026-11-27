import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { findPythonWithPytest, getPythonCandidates } from '../scripts/run-python-tests.mjs';

test('npm test runs the Python suite through the project-aware runner', async () => {
  const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.match(packageJson.scripts.test, /run-python-tests\.mjs/);
});

test('Python discovery prefers an explicit interpreter and then the project virtualenv', () => {
  const candidates = getPythonCandidates({
    root: '/officekit',
    platform: 'darwin',
    env: { PYTHON: '/custom/python' },
    exists: (candidate) => candidate === '/officekit/.venv/bin/python',
  });
  assert.deepEqual(candidates, [
    '/custom/python',
    '/officekit/.venv/bin/python',
    'python3',
    'python',
  ]);
});

test('Python discovery selects the Windows virtualenv executable when present', () => {
  const candidates = getPythonCandidates({
    root: 'C:\\officekit',
    platform: 'win32',
    env: {},
    exists: (candidate) => candidate === 'C:\\officekit\\.venv\\Scripts\\python.exe',
  });
  assert.deepEqual(candidates, [
    'C:\\officekit\\.venv\\Scripts\\python.exe',
    'python',
  ]);
});

test('pytest discovery skips interpreters without pytest and selects the first usable one', () => {
  const probed = [];
  const python = findPythonWithPytest(['python3', 'project-python', 'python'], (command, args) => {
    probed.push([command, args]);
    return command === 'project-python'
      ? { status: 0 }
      : { status: 1, error: undefined };
  });
  assert.equal(python, 'project-python');
  assert.deepEqual(probed.map(([command]) => command), ['python3', 'project-python']);
});
