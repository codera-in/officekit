import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  classifyStatus,
  credentials,
  dmgFileName,
  finish,
  notarytoolArguments,
  parseSubmissionId,
  readState,
  releaseDirectory,
  stage,
  status,
  submit,
  summarizeLog,
} from '../scripts/macos-notarize.mjs';

const ID = '098ee275-3146-48bb-8e53-a2b1fd507091';
const ISSUER = '69a6de70-0000-47e3-e053-5b8c7c11a4d1';
const TAG = 'v1.0.93';

function sandbox() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-notarize-'));
  const root = path.join(base, 'releases');
  const app = path.join(base, 'OfficeKit.app');
  fs.mkdirSync(path.join(app, 'Contents'), { recursive: true });
  const keyPath = path.join(base, 'AuthKey_ABCDE12345.p8');
  fs.writeFileSync(keyPath, 'key');
  const environment = {
    APPLE_API_KEY: 'ABCDE12345',
    APPLE_API_ISSUER: ISSUER,
    APPLE_API_KEY_PATH: keyPath,
    APPLE_SIGNING_IDENTITY: 'Developer ID Application: Example (TEAM123456)',
  };
  const calls = [];
  const run = outputs => (command, args) => {
    calls.push([command, ...args]);
    for (const [needle, output] of Object.entries(outputs || {})) {
      if ([command, ...args].join(' ').includes(needle)) return output;
    }
    return '';
  };
  return { base, root, app, environment, calls, run, cleanup: () => fs.rmSync(base, { recursive: true, force: true }) };
}

test('release tags are validated and kept inside the releases folder', () => {
  assert.equal(releaseDirectory('v1.0.93', '/r'), path.join('/r', 'v1.0.93'));
  assert.equal(releaseDirectory('v2.1.0-beta.1+build.5', '/r'), path.join('/r', 'v2.1.0-beta.1+build.5'));
  for (const bad of ['', '1.0.93', 'v1.0', '../v1.0.93', 'v1.0.93/../../x', 'v1.0.93 ', null, undefined]) {
    assert.throws(() => releaseDirectory(bad, '/r'), /vMAJOR\.MINOR\.PATCH/, String(bad));
  }
});

test('Apple answers are parsed strictly: a submission id must be a UUID, a status must be known', () => {
  assert.equal(parseSubmissionId(JSON.stringify({ id: ID.toUpperCase(), message: 'ok' })), ID);
  for (const bad of ['', 'not json', '{}', JSON.stringify({ id: 'x' }), JSON.stringify({ id: `${ID}; rm -rf /` })]) {
    assert.throws(() => parseSubmissionId(bad), /submission/, bad);
  }
  assert.equal(classifyStatus('{"status":"Accepted"}'), 'accepted');
  assert.equal(classifyStatus('{"status":"In Progress"}'), 'in-progress');
  assert.equal(classifyStatus('{"status":"Invalid"}'), 'rejected');
  assert.equal(classifyStatus('{"status":"Rejected"}'), 'rejected');
  assert.equal(classifyStatus('{"status":"Weird"}'), 'unknown');
  assert.equal(classifyStatus('garbage'), 'unknown');
});

test('the rejection summary is bounded and names the failing files', () => {
  const issues = Array.from({ length: 30 }, (_, index) => ({ path: `a/${index}`, message: 'The signature of the binary is invalid.' }));
  const lines = summarizeLog(JSON.stringify({ issues }));
  assert.equal(lines.length, 21);
  assert.equal(lines[0], 'a/0: The signature of the binary is invalid.');
  assert.match(lines.at(-1), /10 more/);
  assert.match(summarizeLog('nope')[0], /could not be read/);
  assert.match(summarizeLog('{"issues":[]}')[0], /no issue list/);
});

test('credentials need a 10-character key id, an issuer UUID and an existing key file', () => {
  const box = sandbox();
  assert.deepEqual(Object.keys(credentials(box.environment)).sort(), ['issuer', 'keyId', 'keyPath']);
  assert.throws(() => credentials({ ...box.environment, APPLE_API_KEY: 'short' }), /key id/);
  assert.throws(() => credentials({ ...box.environment, APPLE_API_ISSUER: 'nope' }), /issuer/);
  assert.throws(() => credentials({ ...box.environment, APPLE_API_KEY_PATH: '/no/such/key.p8' }), /key file/);
  box.cleanup();
});

test('notarytool is never asked to wait', () => {
  const keys = { keyId: 'ABCDE12345', issuer: ISSUER, keyPath: '/k.p8' };
  const args = notarytoolArguments('submit', { ...keys, target: '/z.zip' });
  assert.deepEqual(args.slice(0, 4), ['notarytool', 'submit', '/z.zip', '--no-wait']);
  assert.ok(!args.includes('--wait'));
  assert.ok(args.includes('--output-format') && args.includes('json'));
  assert.deepEqual(notarytoolArguments('info', { ...keys, target: ID }).slice(0, 3), ['notarytool', 'info', ID]);
  assert.throws(() => notarytoolArguments('wait', keys), /Unknown/);
});

test('staging copies the signed app outside the checkout and refuses to orphan a submission', () => {
  const box = sandbox();
  const state = stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  assert.equal(state.stage, 'built');
  assert.deepEqual(box.calls.map(call => call[0]), ['ditto', 'codesign']);
  assert.ok(box.calls[1].includes('--strict'));
  assert.equal(readState(path.join(box.root, TAG)).stage, 'built');
  // A second build of a staged tag simply replaces it; once submitted it must not.
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  fs.writeFileSync(path.join(box.root, TAG, 'state.json'), JSON.stringify({ stage: 'submitted' }));
  assert.throws(() => stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() }), /already submitted/);
  assert.equal(stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run(), force: true }).stage, 'built');
  assert.throws(() => stage({ tag: TAG, appPath: '/no/app', root: box.root, run: box.run() }), /missing/);
  box.cleanup();
});

test('submitting zips the staged app, sends it without waiting and records the submission once', () => {
  const box = sandbox();
  assert.throws(() => submit({ tag: TAG, root: box.root, run: box.run(), environment: box.environment }), /not been built/);
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  box.calls.length = 0;
  const state = submit({
    tag: TAG, root: box.root, environment: box.environment, now: () => new Date('2026-11-19T16:00:00Z'),
    run: box.run({ 'notarytool submit': JSON.stringify({ id: ID }) }),
  });
  assert.equal(state.stage, 'submitted');
  assert.equal(state.submissionId, ID);
  assert.equal(state.submittedAt, '2026-11-19T16:00:00.000Z');
  assert.equal(box.calls[0][0], 'ditto');
  assert.ok(box.calls[0].includes('--keepParent'));
  const submitCall = box.calls.find(call => call.includes('submit'));
  assert.ok(submitCall.includes('--no-wait'));
  assert.equal(JSON.stringify(readState(path.join(box.root, TAG))).includes('key'), false, 'no key material in the state file');
  assert.throws(() => submit({ tag: TAG, root: box.root, run: box.run(), environment: box.environment }), /already submitted/);
  box.cleanup();
});

test('a bad answer from Apple leaves the staged build ready to submit again', () => {
  const box = sandbox();
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  assert.throws(() => submit({ tag: TAG, root: box.root, environment: box.environment, run: box.run({ 'notarytool submit': '{"id":"x"}' }) }), /valid submission id/);
  assert.equal(readState(path.join(box.root, TAG)).stage, 'built');
  box.cleanup();
});

test('status reports accepted and in progress without failing, and fails with Apple’s reasons on rejection', () => {
  const box = sandbox();
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  assert.throws(() => status({ tag: TAG, root: box.root, run: box.run(), environment: box.environment }), /not waiting on Apple/);
  submit({ tag: TAG, root: box.root, environment: box.environment, run: box.run({ 'notarytool submit': JSON.stringify({ id: ID }) }) });
  const logs = [];
  const ask = outputs => status({ tag: TAG, root: box.root, environment: box.environment, log: message => logs.push(message), run: box.run(outputs) });
  assert.equal(ask({ 'notarytool info': '{"status":"In Progress"}' }), 'in-progress');
  assert.match(logs.at(-1), /still reviewing/);
  assert.equal(ask({ 'notarytool info': '{"status":"Accepted"}' }), 'accepted');
  assert.throws(
    () => ask({ 'notarytool info': '{"status":"Invalid"}', 'notarytool log': JSON.stringify({ issues: [{ path: 'x/Python', message: 'invalid' }] }) }),
    /x\/Python: invalid/,
  );
  assert.throws(() => ask({ 'notarytool info': '{"status":"???"}' }), /does not understand/);
  box.cleanup();
});

test('finishing staples before the DMG exists, signs the DMG and refuses a mismatched version or identity', () => {
  const box = sandbox();
  const repoRoot = path.join(box.base, 'repo');
  fs.mkdirSync(repoRoot);
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  assert.throws(() => finish({ tag: TAG, version: '1.0.93', repoRoot, root: box.root, run: box.run(), environment: box.environment }), /no accepted submission/);
  submit({ tag: TAG, root: box.root, environment: box.environment, run: box.run({ 'notarytool submit': JSON.stringify({ id: ID }) }) });
  assert.throws(() => finish({ tag: TAG, version: '1.0.92', repoRoot, root: box.root, run: box.run(), environment: box.environment }), /does not match/);
  assert.throws(() => finish({ tag: TAG, version: '1.0.93', repoRoot, root: box.root, run: box.run(), environment: { ...box.environment, APPLE_SIGNING_IDENTITY: 'Apple Development: me' } }), /Developer ID Application/);

  box.calls.length = 0;
  // No ticket yet: the first validate fails, then stapling attaches it and the final validate passes.
  let validations = 0;
  const run = (command, args) => {
    const output = box.run()(command, args);
    if (command === 'xcrun' && args[0] === 'stapler' && args[1] === 'validate' && (validations += 1) === 1) throw new Error('no ticket');
    return output;
  };
  const state = finish({ tag: TAG, version: '1.0.93', repoRoot, root: box.root, run, environment: box.environment, machine: 'arm64', now: () => new Date('2026-11-19T20:00:00Z') });
  const order = box.calls.map(call => call.slice(0, 3).join(' '));
  const stapleAt = order.findIndex(item => item.startsWith('xcrun stapler staple'));
  const createAt = order.findIndex(item => item.startsWith('hdiutil create'));
  const signAt = box.calls.findIndex(call => call[0] === 'codesign' && call.includes('--force'));
  assert.ok(stapleAt >= 0 && stapleAt < createAt, 'the app is stapled before the DMG is built');
  assert.ok(createAt < signAt, 'the DMG is signed after it is built');
  assert.ok(box.calls[signAt].includes('--timestamp'));
  assert.ok(order.some(item => item.startsWith('spctl --assess')) && order.some(item => item.startsWith('xcrun stapler validate')));
  assert.equal(state.stage, 'finished');
  assert.equal(path.basename(state.dmg), 'OfficeKit_1.0.93_aarch64.dmg');
  assert.ok(state.dmg.startsWith(path.join(repoRoot, 'src-tauri/target/release/bundle/dmg')));
  box.cleanup();
});

test('finishing again after a later failure does not staple an app that already carries its ticket', () => {
  const box = sandbox();
  const repoRoot = path.join(box.base, 'repo');
  fs.mkdirSync(repoRoot);
  stage({ tag: TAG, appPath: box.app, root: box.root, run: box.run() });
  submit({ tag: TAG, root: box.root, environment: box.environment, run: box.run({ 'notarytool submit': JSON.stringify({ id: ID }) }) });
  box.calls.length = 0;
  // validate passes (ticket present); a staple call would throw, as it did on the already-stapled v1.0.108 app.
  const run = (command, args) => {
    if (command === 'xcrun' && args[0] === 'stapler' && args[1] === 'staple') throw new Error('stapler staple failed (73)');
    return box.run()(command, args);
  };
  const state = finish({ tag: TAG, version: '1.0.93', repoRoot, root: box.root, run, environment: box.environment, machine: 'arm64' });
  const order = box.calls.map(call => call.slice(0, 3).join(' '));
  assert.ok(!order.some(item => item.startsWith('xcrun stapler staple')));
  assert.ok(order.some(item => item.startsWith('xcrun stapler validate')) && order.some(item => item.startsWith('hdiutil create')));
  assert.equal(state.stage, 'finished');
  box.cleanup();
});

test('the DMG name matches the pattern the smoke test looks for', () => {
  assert.match(dmgFileName('1.0.93', 'arm64'), /^OfficeKit_.*\.dmg$/i);
  assert.equal(dmgFileName('1.0.93', 'arm64'), 'OfficeKit_1.0.93_aarch64.dmg');
  assert.equal(dmgFileName('1.0.93', 'x64'), 'OfficeKit_1.0.93_x64.dmg');
});
