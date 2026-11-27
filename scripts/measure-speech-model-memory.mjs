import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
if (process.platform !== 'darwin' || process.arch !== 'arm64') {
  throw new Error('Speech-model footprint profiling requires macOS on Apple silicon.');
}
const model = path.join(os.homedir(), 'Library/Application Support/OfficeKit/Models/whisper.cpp/medium/ggml-medium.bin');
if (statSync(model, { throwIfNoEntry: false })?.size !== 1_533_763_059) {
  throw new Error('An existing cached Whisper Medium model is required. This benchmark never downloads it.');
}
const directory = mkdtempSync(path.join(os.tmpdir(), 'officekit-speech-memory-'));
function run(command, args, env = process.env) {
  const result = spawnSync(command, args, { cwd: root, env, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}
try {
  const aiff = path.join(directory, 'speech.aiff');
  const wav = path.join(directory, 'speech.wav');
  run('/usr/bin/say', ['-v', 'Samantha', '-r', '175', '-o', aiff, 'Local speech models should load only when needed.']);
  run('/usr/bin/afconvert', ['-f', 'WAVE', '-d', 'LEF32@16000', aiff, wav]);
  const output = run('cargo', ['test', '--manifest-path', 'src-tauri/Cargo.toml', '--lib', 'tests::cached_speech_first_use_memory_profile', '--', '--ignored', '--exact', '--nocapture'], {
    ...process.env,
    GGML_METAL_NO_RESIDENCY: '1',
    OFFICEKIT_SPEECH_MEMORY_FIXTURE: wav,
  });
  const measurement = output.split('\n').find(line => line.startsWith('OFFICEKIT_SPEECH_MEMORY '));
  if (!measurement) throw new Error('The native speech profile produced no measurements.');
  const values = JSON.parse(measurement.slice('OFFICEKIT_SPEECH_MEMORY '.length));
  process.stdout.write(`${JSON.stringify({ ...values, scope: 'native model decode path; excludes desktop UI and backend' }, null, 2)}\n`);
} finally {
  rmSync(directory, { recursive: true, force: true });
}
