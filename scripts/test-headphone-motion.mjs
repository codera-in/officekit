import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

// Isolate the pure policy from Tauri, model downloads, and hardware permission prompts.
const directory = mkdtempSync(join(tmpdir(), 'officekit-motion-test-'));
try {
  writeFileSync(join(directory, 'Cargo.toml'), '[package]\nname="officekit-motion-policy-test"\nversion="0.0.0"\nedition="2021"\n[lib]\npath="lib.rs"\n[dependencies]\nserde={version="1.0",features=["derive"]}\n');
  writeFileSync(join(directory, 'lib.rs'), `#[path = ${JSON.stringify(resolve('src-tauri/src/headphone_motion.rs'))}]\nmod headphone_motion;\n`);
  // A developer machine reuses the crates already downloaded; a clean CI runner has none, so it may fetch them.
  const offline = process.env.CI ? [] : ['--offline'];
  const result = spawnSync('cargo', ['test', ...offline, '--manifest-path', join(directory, 'Cargo.toml')], { stdio: 'inherit' });
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(directory, { recursive: true, force: true });
}
