import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { macDmgRequested, parseLocalAppleDevelopmentIdentity, parseLocalSigningIdentity, tauriBuildEnvironment } from '../scripts/build-desktop.mjs';
import { macosBetaSmokeEnvironment } from '../scripts/smoke-macos-dmg-beta.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('macOS desktop build routes through the wrapper that skips Finder automation', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.equal(packageJson.scripts.build, 'node scripts/build-desktop.mjs');
});

test('macOS build forces Tauri create-dmg into headless mode', () => {
  assert.deepEqual(
    tauriBuildEnvironment('darwin', { CI: 'false', TAURI_BUNDLER_DMG_IGNORE_CI: 'true', PATH: '/bin' }, '-'),
    { CI: 'true', TAURI_BUNDLER_DMG_IGNORE_CI: 'false', PATH: '/bin', APPLE_SIGNING_IDENTITY: '-' },
  );
});

test('local macOS builds use an available Apple Development identity, falling back to ad hoc', () => {
  assert.equal(
    tauriBuildEnvironment('darwin', { PATH: '/bin' }, 'Apple Development: Local (TEAM123)').APPLE_SIGNING_IDENTITY,
    'Apple Development: Local (TEAM123)',
  );
  assert.equal(
    tauriBuildEnvironment('darwin', { PATH: '/bin' }, '-').APPLE_SIGNING_IDENTITY,
    '-',
  );
  assert.equal(
    tauriBuildEnvironment('darwin', { PATH: '/bin', APPLE_SIGNING_IDENTITY: 'Developer ID Application: OfficeKit' })
      .APPLE_SIGNING_IDENTITY,
    'Developer ID Application: OfficeKit',
  );
});

test('local signing identity parser selects only a valid Apple Development identity', () => {
  assert.equal(
    parseLocalAppleDevelopmentIdentity('1 valid identity found\n  1) 1188DC138909252C4BB23ACBFF5C94439F0B3E76 "Apple Development: Example Developer (ABCDE12345)"'),
    'Apple Development: Example Developer (ABCDE12345)',
  );
  assert.equal(parseLocalAppleDevelopmentIdentity('0 valid identities found'), '-');
});

test('local signing prefers one Developer ID identity and refuses to guess between several', () => {
  const dev = '  1) 1188DC138909252C4BB23ACBFF5C94439F0B3E76 "Apple Development: a@b.c (AAAAAAAAAA)"';
  const idA = '  2) 2288DC138909252C4BB23ACBFF5C94439F0B3E76 "Developer ID Application: One LLC (TEAM000001)"';
  const idB = '  3) 3388DC138909252C4BB23ACBFF5C94439F0B3E76 "Developer ID Application: Two Inc (TEAM000002)"';
  assert.equal(parseLocalSigningIdentity(`${dev}\n${idA}`), 'Developer ID Application: One LLC (TEAM000001)');
  assert.equal(parseLocalSigningIdentity(dev), 'Apple Development: a@b.c (AAAAAAAAAA)');
  assert.equal(parseLocalSigningIdentity('0 valid identities found'), '-');
  assert.throws(() => parseLocalSigningIdentity(`${dev}\n${idA}\n${idB}`), /Set APPLE_SIGNING_IDENTITY/);
});

test('macOS entitlements allow the bundled Python sidecar to load under Hardened Runtime', () => {
  const entitlements = fs.readFileSync(path.join(root, 'src-tauri', 'Entitlements.plist'), 'utf8');
  for (const key of ['disable-library-validation', 'allow-unsigned-executable-memory']) {
    assert.match(entitlements, new RegExp(`<key>com\\.apple\\.security\\.cs\\.${key}</key>\\s*<true\\s*/>`));
  }
});

test('other platform builds preserve their environment', () => {
  const original = { CI: 'true', TAURI_BUNDLER_DMG_IGNORE_CI: 'true', PATH: '/bin' };
  assert.deepEqual(tauriBuildEnvironment('win32', original), original);
  assert.deepEqual(tauriBuildEnvironment('linux', original), original);
});

test('Mac DMG fallback honors explicit bundle targets and only runs when DMG output is requested', () => {
  assert.equal(macDmgRequested([]), true);
  assert.equal(macDmgRequested(['--bundles', 'all']), true);
  assert.equal(macDmgRequested(['--bundles=dmg']), true);
  assert.equal(macDmgRequested(['--bundles', 'app,dmg']), true);
  assert.equal(macDmgRequested(['--bundles', 'app']), false);
  assert.equal(macDmgRequested(['--bundles=appimage']), false);
  const build = fs.readFileSync(path.join(root, 'scripts', 'build-desktop.mjs'), 'utf8');
  assert.match(build, /shouldCreateMacDmgFallback/);
  assert.match(build, /createMacDmgFallback/);
});

test('macOS packaging grants microphone access under Hardened Runtime', () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'src-tauri', 'tauri.conf.json'), 'utf8'));
  assert.equal(config.bundle.macOS.entitlements, 'Entitlements.plist');
  const entitlements = fs.readFileSync(path.join(root, 'src-tauri', config.bundle.macOS.entitlements), 'utf8');
  assert.match(entitlements, /<key>com\.apple\.security\.device\.audio-input<\/key>\s*<true\s*\/>/);
  assert.doesNotMatch(entitlements, /com\.apple\.security\.app-sandbox/);
  const smoke = fs.readFileSync(path.join(root, 'scripts', 'smoke-macos-dmg.mjs'), 'utf8');
  assert.match(smoke, /entitlements\['com\.apple\.security\.device\.audio-input'\] !== true/);
});
