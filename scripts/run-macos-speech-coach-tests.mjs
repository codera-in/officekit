import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Explicit live-model acceptance test; deterministic workspace/validation tests run in cargo test.
if (process.platform !== 'darwin') {
  console.log('SKIP: the on-device speech coaching model requires macOS.');
} else {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const temporary = mkdtempSync(path.join(os.tmpdir(), 'officekit-coach-clarity-'));
  const binary = path.join(temporary, 'coach-clarity');
  try {
    const compile = spawnSync('swiftc', ['-parse-as-library',
      path.join(root, 'src-tauri/macos-dictation-polish.swift'),
      path.join(root, 'tests/macos-speech-coach-clarity.swift'), '-o', binary], { stdio: 'inherit' });
    if (compile.status !== 0) throw new Error('Speech coach acceptance test failed to compile.');
    const run = spawnSync(binary, [path.join(root, 'tests/fixtures/speech-coach/clarity.json')], { stdio: 'inherit' });
    if (run.status !== 0) throw new Error('Speech coach live-model acceptance failed.');
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
}
