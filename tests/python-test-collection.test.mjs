// Every Python test file under tests/ must match a pytest collection pattern, or `npm test` silently skips it (P-188).
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ini = readFileSync(path.join(root, 'pytest.ini'), 'utf8');

function collectionPatterns() {
  const line = ini.split('\n').find(entry => entry.trim().startsWith('python_files'));
  const value = line ? line.split('=')[1] : 'test_*.py *_test.py';
  return value.trim().split(/\s+/).map(glob => new RegExp(`^${glob.replace(/\./g, '\\.').replace(/\*/g, '.*')}$`));
}

function pythonTestFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : pythonTestFiles(full);
    return entry.name.endsWith('.py') && /test/.test(entry.name) && entry.name !== 'conftest.py' ? [full] : [];
  });
}

test('every Python test file under tests/ matches a pytest collection pattern', () => {
  const patterns = collectionPatterns();
  const skipped = pythonTestFiles(path.join(root, 'tests'))
    .map(file => path.basename(file))
    .filter(name => !patterns.some(pattern => pattern.test(name)));
  assert.deepEqual(skipped, [], 'pytest would not collect these files');
});

test('the *_unittest.py naming used by the repo is collected', () => {
  assert.ok(collectionPatterns().some(pattern => pattern.test('mcp_server_unittest.py')));
});
