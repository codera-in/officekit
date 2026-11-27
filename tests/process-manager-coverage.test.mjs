import assert from 'node:assert/strict';
import test from 'node:test';
import { findPythonWithCoverage } from '../scripts/check-process-manager-coverage.mjs';

test('the process-manager coverage runner selects only Python environments with pytest and coverage.py', () => {
  const calls = [];
  const run = (python, args) => {
    calls.push([python, args]);
    if (python === 'without-coverage' && args[1] === 'coverage') return { status: 1 };
    return { status: 0 };
  };

  assert.equal(findPythonWithCoverage(['without-coverage', 'ready'], run), 'ready');
  assert.equal(calls.length, 4);
  assert.equal(findPythonWithCoverage(['without-coverage'], run), null);
});
