import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// The native build embeds this scope and supplies it to its child API process.
// A webview request cannot switch a beta into the development profile.
const result = spawnSync(process.execPath, [path.join(root, 'scripts/build-desktop.mjs'), ...process.argv.slice(2)], {
  cwd: root,
  env: { ...process.env, OFFICEKIT_RELEASE_PROFILE: 'private-beta' },
  stdio: 'inherit',
});
if (result.error) process.stderr.write(`Private beta build failed: ${result.error.message}\n`);
process.exitCode = result.error ? 1 : (result.status ?? 1);
