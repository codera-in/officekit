import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createMacDmgFallback, shouldCreateMacDmgFallback } from './macos-dmg-fallback.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function parseLocalAppleDevelopmentIdentity(identityList) {
  const identity = identityList.match(/\d+\)\s+[A-F0-9]+\s+"(Apple Development:[^"]+)"/);
  return identity?.[1] || '-';
}

// A Developer ID Application identity is distributable, so it wins over Apple Development.
// Several Apple accounts can share one keychain; guessing between them could sign with the
// wrong team, so more than one Developer ID identity requires an explicit APPLE_SIGNING_IDENTITY.
export function parseLocalSigningIdentity(identityList) {
  const developerIds = [...identityList.matchAll(/\d+\)\s+[A-F0-9]+\s+"(Developer ID Application:[^"]+)"/g)]
    .map(match => match[1]);
  if (developerIds.length > 1) {
    throw new Error(
      `Multiple Developer ID Application identities found (${developerIds.join('; ')}). `
      + 'Set APPLE_SIGNING_IDENTITY to the one this app should use.',
    );
  }
  return developerIds[0] || parseLocalAppleDevelopmentIdentity(identityList);
}

export function findLocalAppleDevelopmentIdentity() {
  const result = spawnSync('security', ['find-identity', '-v', '-p', 'codesigning'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  if (result.status !== 0) return '-';
  return parseLocalSigningIdentity(result.stdout);
}

export function tauriBuildEnvironment(platform, sourceEnvironment, localIdentity = undefined) {
  const environment = { ...sourceEnvironment };
  if (platform === 'darwin') {
    // Tauri's DMG helper opens Finder and waits for Finder to write .DS_Store.
    // That automation hangs on machines where the build has no interactive Finder.
    // CI=true selects create-dmg's supported headless mode; this flag prevents
    // tauri-action's default from overriding that behavior on release builds.
    environment.CI = 'true';
    environment.TAURI_BUNDLER_DMG_IGNORE_CI = 'false';
    // Stable local signing is needed for macOS TCC permissions to identify the
    // app across rebuilds. Release jobs provide their Developer ID identity and
    // must retain it; machines without a local Apple Development cert use ad hoc.
    environment.APPLE_SIGNING_IDENTITY ||= localIdentity || findLocalAppleDevelopmentIdentity();
  }
  return environment;
}

export function macDmgRequested(args) {
  const separateIndex = args.indexOf('--bundles');
  const inlineArgument = args.find(argument => argument.startsWith('--bundles='));
  const value = separateIndex >= 0 ? args[separateIndex + 1] : inlineArgument?.slice('--bundles='.length);
  if (value === undefined) return true;
  return value.split(',').some(bundle => ['all', 'dmg'].includes(bundle.trim().toLowerCase()));
}

function tryMacDmgFallback({ appBundle, buildStartedAtMs, args, tauriExitCode }) {
  const executablePath = path.join(appBundle, 'Contents', 'MacOS', 'officekit');
  const executable = fs.statSync(executablePath, { throwIfNoEntry: false });
  const appBundleFresh = Boolean(executable && executable.mtimeMs >= buildStartedAtMs - 2000);
  const appSignatureVerified = appBundleFresh && spawnSync(
    'codesign', ['--verify', '--deep', '--strict', appBundle], { cwd: root, stdio: 'ignore' },
  ).status === 0;
  if (!shouldCreateMacDmgFallback({
    platform: process.platform,
    tauriExitCode,
    dmgRequested: macDmgRequested(args),
    appBundleFresh,
    appSignatureVerified,
  })) return null;

  const config = JSON.parse(fs.readFileSync(path.join(root, 'src-tauri', 'tauri.conf.json'), 'utf8'));
  const target = spawnSync('rustc', ['--print', 'host-tuple'], { cwd: root, encoding: 'utf8' });
  if (target.status !== 0) throw new Error(target.stderr || 'Unable to determine the Mac installer architecture.');
  const architecture = target.stdout.trim().split('-', 1)[0];
  const bundleDir = path.join(root, 'src-tauri', 'target', 'release', 'bundle');
  const outputPath = path.join(bundleDir, 'dmg', `${config.productName}_${config.version}_${architecture}.dmg`);
  return createMacDmgFallback({ appBundle, outputPath });
}

function build() {
  const cli = path.join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');
  const args = process.argv.slice(2);
  const buildStartedAtMs = Date.now();
  const result = spawnSync(process.execPath, [cli, 'build', ...args], {
    cwd: root,
    env: tauriBuildEnvironment(process.platform, process.env),
    stdio: 'inherit',
  });
  if (result.error) {
    process.stderr.write(`Could not start Tauri build: ${result.error.message}\n`);
    process.exitCode = 1;
  } else {
    const status = result.status ?? 1;
    if (status !== 0 && process.platform === 'darwin') {
      try {
        const appBundle = path.join(root, 'src-tauri', 'target', 'release', 'bundle', 'macos', 'OfficeKit.app');
        const fallback = tryMacDmgFallback({ appBundle, buildStartedAtMs, args, tauriExitCode: result.status });
        if (fallback) {
          process.stdout.write(`Tauri DMG bundling failed after producing a signed app; created and verified fallback installer: ${fallback}\n`);
          process.exitCode = 0;
          return;
        }
      } catch (error) {
        process.stderr.write(`Could not create a verified macOS DMG fallback: ${error.message}\n`);
      }
    }
    process.exitCode = status;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) build();
