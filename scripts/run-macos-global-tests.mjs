import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

if (process.platform !== 'darwin') {
  process.stdout.write('Skipping native global desktop tests; macOS is required.\n');
  process.exit(0);
}

const root = process.cwd();
const outputDirectory = path.join(root, '.build', 'tests');
const output = path.join(outputDirectory, 'macos-global-logic-tests');
mkdirSync(outputDirectory, { recursive: true });

const compilation = spawnSync('swiftc', [
  '-parse-as-library',
  path.join(root, 'src-tauri', 'macos-global-logic.swift'),
  path.join(root, 'tests', 'macos-global-logic-tests.swift'),
  '-o', output,
], { cwd: root, stdio: 'inherit' });

if (compilation.error) {
  process.stderr.write(`Could not start Swift compiler: ${compilation.error.message}\n`);
  process.exitCode = 1;
} else if (compilation.status !== 0) {
  process.exitCode = compilation.status ?? 1;
} else {
  const tests = spawnSync(output, [], { cwd: root, stdio: 'inherit' });
  if (tests.error) process.stderr.write(`Could not start native test binary: ${tests.error.message}\n`);
  process.exitCode = tests.error ? 1 : (tests.status ?? 1);
}

if (process.exitCode === undefined || process.exitCode === 0) {
  const hardwareOutput = path.join(outputDirectory, 'macos-hardware-tests');
  const hardwareCompilation = spawnSync('swiftc', [
    '-parse-as-library',
    path.join(root, 'src-tauri', 'macos-hardware.swift'),
    path.join(root, 'tests', 'macos-hardware-tests.swift'),
    '-o', hardwareOutput,
  ], { cwd: root, stdio: 'inherit' });
  if (hardwareCompilation.error || hardwareCompilation.status !== 0) {
    process.exitCode = hardwareCompilation.status ?? 1;
  } else {
    const hardwareTests = spawnSync(hardwareOutput, [], { cwd: root, stdio: 'inherit' });
    process.exitCode = hardwareTests.error ? 1 : (hardwareTests.status ?? 1);
  }
}

if (process.exitCode === undefined || process.exitCode === 0) {
  const sensorOutput = path.join(outputDirectory, 'macos-sensor-tests');
  const sensorCompilation = spawnSync('swiftc', [
    '-parse-as-library',
    path.join(root, 'src-tauri', 'macos-sensors.swift'),
    path.join(root, 'tests', 'macos-sensors-tests.swift'),
    '-o', sensorOutput,
  ], { cwd: root, stdio: 'inherit' });
  if (sensorCompilation.error) {
    process.stderr.write(`Could not start Swift sensor compiler: ${sensorCompilation.error.message}\n`);
    process.exitCode = 1;
  } else if (sensorCompilation.status !== 0) {
    process.exitCode = sensorCompilation.status ?? 1;
  } else {
    const sensorTests = spawnSync(sensorOutput, [], { cwd: root, stdio: 'inherit' });
    if (sensorTests.error) process.stderr.write(`Could not start native sensor test binary: ${sensorTests.error.message}\n`);
    process.exitCode = sensorTests.error ? 1 : (sensorTests.status ?? 1);
  }
}
