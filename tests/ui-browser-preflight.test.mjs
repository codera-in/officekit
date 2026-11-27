import assert from 'node:assert/strict';
import test from 'node:test';
import { preflightBrowser } from '../scripts/ui-browser-preflight.mjs';

test('UI browser preflight closes the browser after a successful launch', async () => {
  let closed = false;
  await preflightBrowser({
    launch: async () => ({ close: async () => { closed = true; } }),
  });
  assert.equal(closed, true);
});

test('UI browser preflight propagates startup failures', async () => {
  const error = new Error('browser could not start');
  await assert.rejects(
    preflightBrowser({ launch: async () => { throw error; } }),
    error,
  );
});

test('UI browser preflight surfaces browser cleanup failures', async () => {
  const error = new Error('browser could not close');
  await assert.rejects(
    preflightBrowser({ launch: async () => ({ close: async () => { throw error; } }) }),
    error,
  );
});
