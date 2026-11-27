import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function macosBetaSmokeEnvironment(sourceEnvironment) {
  return { ...sourceEnvironment, OFFICEKIT_RELEASE_PROFILE: 'private-beta' };
}

function run() {
  const result = spawnSync(
    process.execPath,
    [path.join(root, 'scripts', 'smoke-macos-dmg.mjs'), ...process.argv.slice(2)],
    {
      cwd: root,
      env: macosBetaSmokeEnvironment(process.env),
      stdio: 'inherit',
    },
  );
  if (result.error) process.stderr.write(`Could not start private-beta installer smoke: ${result.error.message}\n`);
  process.exitCode = result.error ? 1 : (result.status ?? 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) run();
