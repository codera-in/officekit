import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, lstatSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
if (process.platform !== 'darwin' || process.arch !== 'arm64') {
  throw new Error('Parakeet runtime verification requires macOS on Apple silicon.');
}

const modelVersion = process.env.OFFICEKIT_PARAKEET_VERSION ?? '3';
if (!['2', '3'].includes(modelVersion)) throw new Error('OFFICEKIT_PARAKEET_VERSION must be 2 or 3.');
const modelSlug = `parakeet-tdt-0.6b-v${modelVersion}`;
const modelRoot = path.join(os.homedir(), 'Library', 'Application Support', 'FluidAudio', 'Models', modelSlug);
if (process.env.OFFICEKIT_PARAKEET_ALLOW_DOWNLOAD !== '1') {
  const requiredDirectories = ['Preprocessor.mlmodelc', 'Encoder.mlmodelc', 'Decoder.mlmodelc', modelVersion === '2' ? 'JointDecision.mlmodelc' : 'JointDecisionv3.mlmodelc'];
  for (const name of requiredDirectories) {
    const info = lstatSync(path.join(modelRoot, name));
    if (info.isSymbolicLink() || !info.isDirectory()) throw new Error(`Parakeet cache artifact is not a regular model directory: ${name}`);
  }
  const info = lstatSync(path.join(modelRoot, 'parakeet_vocab.json'));
  if (info.isSymbolicLink() || !info.isFile()) throw new Error('Parakeet vocabulary is not a regular file.');
  JSON.parse(readFileSync(path.join(modelRoot, 'parakeet_vocab.json'), 'utf8'));
}

const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'officekit-parakeet-runtime-'));
const phrase = 'Local dictation is working today';
const aiff = path.join(temporaryDirectory, 'fixture.aiff');
const wav = path.join(temporaryDirectory, 'fixture.wav');

function run(command, args, env = process.env) {
  const result = spawnSync(command, args, { cwd: root, env, encoding: 'utf8' });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed with exit ${result.status}`);
}

try {
  run('/usr/bin/say', ['-v', 'Samantha', '-r', '175', '-o', aiff, phrase]);
  run('/usr/bin/afconvert', ['-f', 'WAVE', '-d', 'LEF32@16000', aiff, wav]);
  run('cargo', [
    'test', '--manifest-path', 'src-tauri/Cargo.toml', '--test', 'parakeet_runtime',
    '--', '--ignored', '--exact', 'local_parakeet_transcribes_file_and_repeated_sample_buffers', '--nocapture',
  ], {
    ...process.env,
    OFFICEKIT_PARAKEET_FIXTURE: wav,
    OFFICEKIT_PARAKEET_EXPECTED: phrase,
    OFFICEKIT_PARAKEET_VERSION: modelVersion,
  });
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
