import assert from 'node:assert/strict';
import test from 'node:test';
import { entitlementPushBody, installSmokeEntitlement } from '../scripts/smoke-backend-sidecar.mjs';

test('the smoke entitlement is pushed as the native shell does: PUT with the API token and the native grant', async () => {
  const calls = [];
  await installSmokeEntitlement({
    origin: 'http://127.0.0.1:9', token: 'api', grantToken: 'grant',
    fetchImpl: async (url, init) => { calls.push({ url, init }); return { status: 204 }; },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:9/api/license/entitlement');
  assert.equal(calls[0].init.method, 'PUT');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer api');
  assert.equal(calls[0].init.headers['X-OfficeKit-Native-Grant'], 'grant');
  assert.equal(calls[0].init.body, entitlementPushBody());
});

test('a sidecar that rejects the smoke entitlement fails the smoke with the status, never silently', async () => {
  for (const status of [401, 403, 422, 500]) {
    await assert.rejects(
      installSmokeEntitlement({ origin: 'http://x', token: 't', grantToken: 'g', fetchImpl: async () => ({ status }) }),
      new RegExp(`HTTP ${status}`),
    );
  }
});

test('the pushed body is a valid paid entitlement summary with no features and a bounded lifetime', () => {
  const body = JSON.parse(entitlementPushBody());
  assert.equal(body.edition, 'paid');
  assert.deepEqual(body.features, []);
  assert.ok(Number.isInteger(body.valid_for_seconds) && body.valid_for_seconds > 0 && body.valid_for_seconds <= 86_400);
});
