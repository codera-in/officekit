import assert from 'node:assert/strict';
import test from 'node:test';
import { ejectSmokeImage } from '../scripts/dmg-eject-retry.mjs';

test('a normal eject succeeds once without waiting', async () => {
  const calls = [];
  await ejectSmokeImage('/tmp/own-image', (command, args) => calls.push([command, args]));
  assert.deepEqual(calls, [['diskutil', ['eject', '/tmp/own-image']]]);
});

test('a busy macOS policy check gets bounded normal eject retries without force or process termination', async () => {
  const calls = [], delays = [];
  await ejectSmokeImage('/tmp/own-image', (command, args) => {
    calls.push([command, args]);
    if (calls.length < 3) throw new Error('Unmount was dissented by syspolicyd');
  }, async ms => delays.push(ms));
  assert.deepEqual(calls, Array.from({ length: 3 }, () => ['diskutil', ['eject', '/tmp/own-image']]));
  assert.deepEqual(delays, [1000, 2000]);
});

test('persistent eject failure returns the original error after five attempts', async () => {
  const error = new Error('busy');
  let attempts = 0;
  const delays = [];
  await assert.rejects(ejectSmokeImage('/tmp/own-image', () => { attempts++; throw error; }, async ms => delays.push(ms)), thrown => thrown === error);
  assert.equal(attempts, 5);
  assert.deepEqual(delays, [1000, 2000, 4000, 8000]);
});
