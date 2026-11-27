import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

if (process.platform !== 'darwin') {
  process.stdout.write('Skipping native dictation hotkey tests; macOS AppKit is required.\n');
  process.exit(0);
}

const root = process.cwd();
const outputDirectory = path.join(root, '.build', 'tests');
const output = path.join(outputDirectory, 'macos-dictation-hotkey-state-tests');
mkdirSync(outputDirectory, { recursive: true });

const objcObjects = ['src-tauri/macos-audio-tap.m', 'tests/macos-audio-tap-test.m'].map((source, index) => {
  const object = path.join(outputDirectory, `audio-tap-${index}.o`);
  const result = spawnSync('clang', ['-fobjc-arc', '-c', path.join(root, source), '-o', object], { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) process.exit(result.status || 1);
  return object;
});

const compilation = spawnSync('swiftc', [
  '-parse-as-library',
  '-import-objc-header', path.join(root, 'tests/macos-audio-tap-test.h'),
  path.join(root, 'src-tauri', 'macos-dictation.swift'),
  path.join(root, 'src-tauri', 'macos-global.swift'),
  path.join(root, 'src-tauri', 'macos-global-logic.swift'),
  path.join(root, 'src-tauri', 'macos-window.swift'),
  path.join(root, 'tests', 'macos-dictation-hotkey-state.swift'),
  ...objcObjects,
  '-framework', 'Carbon',
  '-framework', 'ServiceManagement',
  '-framework', 'AVFAudio',
  '-framework', 'AVFoundation',
  '-framework', 'ScreenCaptureKit',
  '-framework', 'CoreMedia',
  '-framework', 'CoreAudio',
  '-o', output,
], { cwd: root, stdio: 'inherit' });

function runCompiled(compilationResult, binary) {
  if (compilationResult.error) {
    process.stderr.write(`Could not start Swift compiler: ${compilationResult.error.message}\n`);
    return 1;
  }
  if (compilationResult.status !== 0) return compilationResult.status ?? 1;
  const tests = spawnSync(binary, [], { cwd: root, stdio: 'inherit' });
  if (tests.error) process.stderr.write(`Could not start native test binary: ${tests.error.message}\n`);
  return tests.error ? 1 : (tests.status ?? 1);
}

const contextOutput = path.join(outputDirectory, 'macos-dictation-context-tests');
const contextCompilation = spawnSync('swiftc', [
  '-parse-as-library',
  path.join(root, 'src-tauri', 'macos-dictation-context.swift'),
  path.join(root, 'tests', 'macos-dictation-focus-context-tests.swift'),
  '-o', contextOutput,
], { cwd: root, stdio: 'inherit' });

process.exitCode = runCompiled(compilation, output) || runCompiled(contextCompilation, contextOutput);
