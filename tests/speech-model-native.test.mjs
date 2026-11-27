import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

test('native speech model lifecycle preserves lazy loading, single initialization and retained failures', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'officekit-speech-model-'));
  try {
    const binary = path.join(directory, process.platform === 'win32' ? 'speech-model.exe' : 'speech-model');
    const compile = spawnSync('rustc', ['--edition=2021', '--test', 'src-tauri/src/speech_model.rs', '-o', binary], { encoding: 'utf8' });
    assert.equal(compile.status, 0, compile.stderr);
    const result = spawnSync(binary, [], { encoding: 'utf8', timeout: 30_000 });
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
