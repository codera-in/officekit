import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { pinnedKeyMarkers, verifyBinaryLicenseConfig, verifyBuiltApp } from '../scripts/verify-built-license-config.mjs';

const BODY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxYz3k2QpLmN8vTbR1uHsDfGhJkLq';
const KEYS = JSON.stringify({ 'officekit-license-v1': `-----BEGIN PUBLIC KEY-----\n${BODY}\n-----END PUBLIC KEY-----\n` });
const ENV = { OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: KEYS, OFFICEKIT_LICENSE_API_BASE_URL: 'https://api.officekit.app' };

// What rustc-env embeds: the JSON text as one line, with the newlines still escaped.
const withKeys = Buffer.from(`xx${KEYS.replaceAll('\n', '\\n')}xx https://api.officekit.app xx`);
// What build.rs embeds when the variable is missing.
const withoutKeys = Buffer.from('xx{}xx https://api.officekit.app xx called `Result::unwrap()`');

test('a binary built with the pinned keys passes', () => {
  assert.deepEqual(verifyBinaryLicenseConfig(withKeys, ENV), []);
});

test('a binary built with an empty keyring is rejected (the v1.0.108 failure)', () => {
  const errors = verifyBinaryLicenseConfig(withoutKeys, ENV);
  assert.equal(errors.length, 2, 'both the key id and the key body are missing');
  assert.match(errors[0], /could never activate/);
});

test('a binary without the API base URL is rejected', () => {
  const errors = verifyBinaryLicenseConfig(Buffer.from(KEYS.replaceAll('\n', '\\n')), ENV);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /API base URL/);
});

test('missing or malformed key config cannot be verified, so it fails', () => {
  assert.equal(verifyBinaryLicenseConfig(withKeys, {}).length, 1);
  assert.equal(verifyBinaryLicenseConfig(withKeys, { OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: '{}' }).length, 1);
  assert.equal(verifyBinaryLicenseConfig(withKeys, { OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: '[1]' }).length, 1);
  assert.deepEqual(pinnedKeyMarkers('not json'), []);
});

test('verifyBuiltApp reads Contents/MacOS/officekit and reports a missing binary', () => {
  const app = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-verify-'));
  assert.match(verifyBuiltApp(app, ENV)[0], /binary is missing/);
  fs.mkdirSync(path.join(app, 'Contents', 'MacOS'), { recursive: true });
  fs.writeFileSync(path.join(app, 'Contents', 'MacOS', 'officekit'), withoutKeys);
  assert.ok(verifyBuiltApp(app, ENV).length > 0);
  fs.writeFileSync(path.join(app, 'Contents', 'MacOS', 'officekit'), withKeys);
  assert.deepEqual(verifyBuiltApp(app, ENV), []);
});

test('CI runs the locked-app UI tests so a first-launch error dialog blocks the merge', () => {
  const ci = fs.readFileSync(new URL('../.github/workflows/ci.yml', import.meta.url), 'utf8');
  assert.match(ci, /npx playwright test ui-tests\/locked-app\.spec\.mjs/);
  assert.ok(ci.indexOf('locked-app.spec.mjs') > ci.indexOf('run: npm test'));
  const spec = fs.readFileSync(new URL('../ui-tests/locked-app.spec.mjs', import.meta.url), 'utf8');
  assert.match(spec, /license_required 403 are handled quietly/);
});

test('staging an app for Apple runs this check before the app is staged', () => {
  const notarize = fs.readFileSync(new URL('../scripts/macos-notarize.mjs', import.meta.url), 'utf8');
  assert.match(notarize, /verifyBuiltApp\(appPath, environment\)/);
  assert.ok(notarize.indexOf('verifyBuiltApp(appPath') < notarize.indexOf('state = stage({ tag, appPath'), 'checked before staging');
});
