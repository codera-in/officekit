import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {
  PRODUCTION_LICENSE_API_BASE_URL,
  main,
  validateReleaseLicenseConfig,
} from '../scripts/check-release-license-config.mjs';

const PEM = '-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n-----END PUBLIC KEY-----\n';
const valid = () => ({
  OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: JSON.stringify({ 'kms-2026-10': PEM }),
  OFFICEKIT_LICENSE_API_BASE_URL: PRODUCTION_LICENSE_API_BASE_URL,
});
const errorsFor = (overrides) => validateReleaseLicenseConfig({ ...valid(), ...overrides });

test('a complete release configuration passes', () => {
  assert.deepEqual(validateReleaseLicenseConfig(valid()), []);
  assert.deepEqual(errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: JSON.stringify({ a: PEM, b: PEM }) }), []);
});

test('a multi-line keyring fails the release build (cargo would cut it after the first line)', () => {
  const pretty = JSON.stringify({ 'kms-2026-10': PEM }, null, 2);
  const errors = errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: pretty });
  assert.equal(errors.length, 1);
  assert.match(errors[0], /one line of compact JSON/);
  // A single trailing newline (a value saved from a file) is harmless: only a newline inside the JSON breaks it.
  assert.deepEqual(errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: `${JSON.stringify({ 'kms-2026-10': PEM })}\n` }), []);
});

test('an unset, blank or empty keyring fails the release build', () => {
  for (const value of [undefined, '', '   ', '{}', ' {} ']) {
    const errors = errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: value });
    assert.equal(errors.length, 1, String(value));
    assert.match(errors[0], /OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON is empty/);
  }
});

test('a malformed keyring fails the release build', () => {
  const tooMany = Object.fromEntries(Array.from({ length: 9 }, (_, index) => [`k${index}`, PEM]));
  for (const value of [
    'not json', '[]', 'null', '"text"', '5',
    JSON.stringify({ a: 'not a pem' }),
    JSON.stringify({ a: 5 }),
    JSON.stringify({ '': PEM }),
    JSON.stringify({ ['k'.repeat(65)]: PEM }),
    JSON.stringify({ 'é': PEM }),
    JSON.stringify({ a: `${PEM}${'x'.repeat(4096)}` }),
    JSON.stringify(tooMany),
    JSON.stringify({ a: PEM, pad: 'x'.repeat(33 * 1024) }),
  ]) {
    assert.equal(errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: value }).length, 1, value.slice(0, 40));
  }
  assert.match(errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: 'x'.repeat(33 * 1024) })[0], /32 KiB/);
});

test('the API base URL must be set and be the production URL', () => {
  assert.match(errorsFor({ OFFICEKIT_LICENSE_API_BASE_URL: undefined })[0], /OFFICEKIT_LICENSE_API_BASE_URL is empty/);
  assert.match(errorsFor({ OFFICEKIT_LICENSE_API_BASE_URL: '' })[0], /is empty/);
  assert.match(errorsFor({ OFFICEKIT_LICENSE_API_BASE_URL: 'http://127.0.0.1:9000' })[0], /must be https:\/\/api\.officekit\.app/);
  assert.match(errorsFor({ OFFICEKIT_LICENSE_API_BASE_URL: 'https://api.officekit.app/' })[0], /must be/);
});

test('both problems are reported together', () => {
  assert.equal(validateReleaseLicenseConfig({}).length, 2);
});

test('main exits 0 with a message when valid and 1 with annotations when not', () => {
  const logs = [];
  const log = { log: (message) => logs.push(['log', message]), error: (message) => logs.push(['error', message]) };
  assert.equal(main(valid(), log), 0);
  assert.deepEqual(logs, [['log', 'Release licence configuration is present.']]);
  logs.length = 0;
  assert.equal(main({}, log), 1);
  assert.equal(logs.length, 2);
  assert.ok(logs.every(([kind, message]) => kind === 'error' && message.startsWith('::error::')));
});

test('the error output never prints the keyring value', () => {
  const secret = 'SUPER-SECRET-NOT-A-KEY';
  const errors = errorsFor({ OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON: JSON.stringify({ a: secret }) });
  assert.equal(errors.join('\n').includes(secret), false);
});
