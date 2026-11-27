import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { startUiTestApiServer } from '../scripts/ui-test-api-server.mjs';

function harness(t) {
  const events = new EventEmitter();
  events.stderr = { write() {} };
  const child = new EventEmitter();
  const signals = [];
  child.kill = signal => signals.push(signal);
  const server = startUiTestApiServer({
    environment: {},
    processEvents: events,
    spawnChild: () => child,
    python: 'python3',
  });
  t.after(() => {
    server.cleanup();
    events.removeAllListeners();
  });
  return { child, events, server, signals };
}

test('isolated UI API data is removed after graceful server shutdown', t => {
  const { child, events, server, signals } = harness(t);
  assert.equal(existsSync(server.dataDirectory), true);
  events.emit('SIGTERM');
  assert.deepEqual(signals, ['SIGTERM']);
  child.emit('close', 0, null);
  assert.equal(existsSync(server.dataDirectory), false);
  assert.equal(events.exitCode, 0);
});

test('isolated UI API data is removed when the parent process exits', t => {
  const { events, server } = harness(t);
  assert.equal(existsSync(server.dataDirectory), true);
  events.emit('exit', 0);
  assert.equal(existsSync(server.dataDirectory), false);
});

test('isolated UI API data is removed when the child fails to start', t => {
  const events = new EventEmitter();
  events.stderr = { write() {} };
  const child = new EventEmitter();
  const directory = mkdtempSync(path.join(tmpdir(), 'officekit-ui-test-data-'));
  const server = startUiTestApiServer({
    environment: {},
    processEvents: events,
    spawnChild: () => child,
    python: 'python3',
    createDataDirectory: () => directory,
  });
  child.emit('error', new Error('spawn failure'));
  assert.equal(existsSync(directory), false);
  assert.equal(events.exitCode, 1);
  server.cleanup();
});

test('isolated UI API data is removed when spawning the child throws synchronously', () => {
  const events = new EventEmitter();
  let errorOutput = '';
  events.stderr = { write: value => { errorOutput += value; } };
  const directory = mkdtempSync(path.join(tmpdir(), 'officekit-ui-test-data-'));
  const server = startUiTestApiServer({
    environment: {},
    processEvents: events,
    spawnChild: () => { throw new Error('synchronous spawn failure'); },
    python: 'python3',
    createDataDirectory: () => directory,
  });
  assert.equal(server.child, null);
  assert.equal(existsSync(directory), false);
  assert.equal(events.exitCode, 1);
  assert.match(errorOutput, /synchronous spawn failure/);
});
