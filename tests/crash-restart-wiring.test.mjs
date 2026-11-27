import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const read = path => fs.readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const settings = read('assets/officekit-general-settings.js');
const lib = read('src-tauri/src/lib.rs');

test('Restart after a crash is read and changed through the two native commands', () => {
  assert.match(settings, /call\('crash_restart_status'\)/);
  assert.match(settings, /invoke\(\)\('crash_restart_set', \{ enabled \}\)/);
  assert.match(settings, /toolRow\('crash_restart', 'Restart after a crash'/);
});

test('the row sits right after Open at login and hides itself when the native side is missing', () => {
  const login = settings.indexOf("toolRow('login', 'Open at login'");
  const restart = settings.indexOf("toolRow('crash_restart'");
  assert.ok(login > 0 && restart > login, 'the new row follows Open at login');
  assert.match(settings, /state\.crashRestart === null \? \[\]/);
});

test('a failed change is shown on the row itself, not in the shared status line', () => {
  assert.match(settings, /state\.crashRestartError = typeof error === 'string'/);
  assert.match(settings, /Boolean\(state\.crashRestartError\)/);
});

test('the commands are registered in both invoke handler lists and the app marks launch and clean exit', () => {
  assert.equal(lib.split('crash_restart::crash_restart_status,').length - 1, 2);
  assert.equal(lib.split('crash_restart::crash_restart_set,').length - 1, 2);
  assert.match(lib, /crash_restart::startup\(\);/);
  assert.match(lib, /crash_restart::shutdown\(\);/);
});
