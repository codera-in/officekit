import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, lstatSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
if (process.platform !== 'darwin' || process.arch !== 'arm64') {
  throw new Error('Qwen3-ASR runtime verification requires macOS on Apple silicon.');
}
const version = spawnSync('/usr/bin/sw_vers', ['-productVersion'], { encoding: 'utf8' });
if (version.status !== 0 || Number.parseInt(version.stdout.split('.')[0], 10) < 15) {
  throw new Error('Qwen3-ASR runtime verification requires macOS 15 or later.');
}

const modelRoot = path.join(
  os.homedir(), 'Library', 'Application Support', 'FluidAudio', 'Models',
  'qwen3-asr-0.6b', 'f32',
);
if (process.env.OFFICEKIT_QWEN3_ALLOW_DOWNLOAD !== '1') {
  const directories = ['qwen3_asr_audio_encoder_v2.mlmodelc', 'qwen3_asr_decoder_stateful.mlmodelc'];
  const files = ['qwen3_asr_embeddings.bin', 'vocab.json'];
  for (const name of directories) {
    const info = lstatSync(path.join(modelRoot, name));
    if (info.isSymbolicLink() || !info.isDirectory()) throw new Error(`Qwen3 cache artifact is not a regular model directory: ${name}`);
  }
  for (const name of files) {
    const info = lstatSync(path.join(modelRoot, name));
    if (info.isSymbolicLink() || !info.isFile()) throw new Error(`Qwen3 cache artifact is not a regular file: ${name}`);
  }
}

const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'officekit-qwen3-runtime-'));
const sentence = 'Local dictation is working today.';
const phrase = Array.from({ length: 16 }, () => sentence).join(' ');
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
    'test', '--manifest-path', 'src-tauri/Cargo.toml', '--test', 'qwen3_runtime',
    '--', '--ignored', '--exact', 'local_qwen3_transcribes_capture_shaped_samples', '--nocapture',
  ], {
    ...process.env,
    OFFICEKIT_QWEN3_FIXTURE: wav,
    OFFICEKIT_QWEN3_EXPECTED: sentence.replace(/\.$/, ''),
  });
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
