import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  codesignArguments,
  collectSignable,
  isDeveloperIdentity,
  isMachO,
  signMacosHelpers,
  signingOrder,
} from '../scripts/sign-macos-helpers.mjs';

const MACHO_64 = Buffer.from([0xcf, 0xfa, 0xed, 0xfe, 0x0c, 0x00, 0x00, 0x01]);
const FAT = Buffer.from([0xca, 0xfe, 0xba, 0xbe, 0x00, 0x00, 0x00, 0x02]);
const JAVA_CLASS = Buffer.from([0xca, 0xfe, 0xba, 0xbe, 0x00, 0x00, 0x00, 0x34]);

function tree() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-sign-'));
  const write = (relative, bytes) => {
    const full = path.join(root, relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, bytes);
  };
  write('officekit-backend', MACHO_64);
  write('_internal/libfoo.dylib', MACHO_64);
  write('_internal/pandas/_libs/x.so', FAT);
  write('_internal/data.txt', Buffer.from('hello world'));
  write('_internal/Tool.class', JAVA_CLASS);
  write('_internal/tiny', Buffer.from([1, 2]));
  write('_internal/Python.framework/Versions/3.14/Python', MACHO_64);
  fs.symlinkSync('3.14', path.join(root, '_internal/Python.framework/Versions/Current'));
  fs.symlinkSync('libfoo.dylib', path.join(root, '_internal/libfoo.1.dylib'));
  return root;
}

test('Mach-O and fat binaries are recognized; text, Java classes and short files are not', () => {
  assert.equal(isMachO(MACHO_64), true);
  assert.equal(isMachO(FAT), true);
  assert.equal(isMachO(JAVA_CLASS), false);
  assert.equal(isMachO(Buffer.from('#!/bin/sh\n')), false);
  assert.equal(isMachO(Buffer.from([0xcf, 0xfa])), false);
  assert.equal(isMachO(null), false);
});

test('only a Developer ID Application identity triggers signing', () => {
  assert.equal(isDeveloperIdentity('Developer ID Application: Codera (ABCDE12345)'), true);
  for (const value of ['Apple Development: me@example.com', '-', '', undefined, null, 'developer id application: x']) {
    assert.equal(isDeveloperIdentity(value), false, String(value));
  }
});

test('collection finds Mach-O files and framework folders and never follows symbolic links', () => {
  const root = tree();
  const { files, bundles } = collectSignable(root);
  const relative = files.map(file => path.relative(root, file)).sort();
  assert.deepEqual(relative, [
    '_internal/Python.framework/Versions/3.14/Python',
    '_internal/libfoo.dylib',
    '_internal/pandas/_libs/x.so',
    'officekit-backend',
  ]);
  assert.deepEqual(bundles.map(bundle => path.relative(root, bundle)), ['_internal/Python.framework']);
  fs.rmSync(root, { recursive: true, force: true });
});

test('files are signed before framework bundles, and nested bundles before their parents', () => {
  const order = signingOrder({
    files: ['/a/lib.dylib', '/a/b/x.so'],
    bundles: ['/a/Outer.framework', '/a/Outer.framework/Versions/3/Inner.framework'],
  });
  assert.deepEqual(order.map(item => item.kind), ['file', 'file', 'bundle', 'bundle']);
  assert.equal(order[2].target, '/a/Outer.framework/Versions/3/Inner.framework');
  assert.equal(order[3].target, '/a/Outer.framework');
});

test('codesign uses the hardened runtime and a secure timestamp, never --deep or an unset identity', () => {
  const args = codesignArguments({ identity: 'Developer ID Application: X (T)', entitlements: '/e.plist', target: '/t/file' });
  assert.deepEqual(args, ['--force', '--options', 'runtime', '--timestamp', '--sign', 'Developer ID Application: X (T)', '--entitlements', '/e.plist', '/t/file']);
  assert.ok(!args.includes('--deep'));
  assert.ok(codesignArguments({ identity: '-', target: '/t', timestamp: false }).includes('--timestamp=none'));
  assert.throws(() => codesignArguments({ identity: '', target: '/t' }), /identity is required/);
});

test('signing signs every file, then the bundle, then verifies each one, and reports the count', async () => {
  const root = tree();
  const calls = [];
  const messages = [];
  const count = await signMacosHelpers({
    identity: 'Developer ID Application: X (T)',
    entitlements: '/e.plist',
    roots: [root],
    concurrency: 2,
    exec: async (command, args) => { calls.push([command, ...args]); return ''; },
    log: message => messages.push(message),
  });
  assert.equal(count, 5);
  const signs = calls.filter(call => call.includes('--sign'));
  const verifies = calls.filter(call => call.includes('--verify'));
  assert.equal(signs.length, 5);
  assert.equal(verifies.length, 5);
  assert.ok(signs.at(-1).at(-1).endsWith('Python.framework'), 'the framework bundle is signed last');
  assert.ok(verifies.every(call => call.includes('--strict')));
  assert.match(messages[0], /Signed 4 native files and 1 framework bundles/);
  fs.rmSync(root, { recursive: true, force: true });
});

test('a failing codesign stops the run with the path and no signature is reported', async () => {
  const root = tree();
  await assert.rejects(
    signMacosHelpers({
      identity: 'Developer ID Application: X (T)',
      roots: [root],
      concurrency: 1,
      exec: async () => { throw new Error('unsigned'); },
      log: () => assert.fail('must not report success'),
    }),
    /unsigned/,
  );
  await assert.rejects(signMacosHelpers({ identity: 'Developer ID Application: X (T)', roots: ['/no/such/path'], exec: async () => '' }), /missing path/);
  fs.rmSync(root, { recursive: true, force: true });
});

test('a framework whose links were followed is signed file by file, never as a bundle', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-flat-'));
  const write = (relative, bytes) => {
    const full = path.join(root, relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, bytes);
  };
  write('Python.framework/Python', MACHO_64);
  write('Python.framework/Versions/Current/Python', MACHO_64);
  const { files, bundles } = collectSignable(root);
  assert.equal(files.length, 2);
  assert.deepEqual(bundles, [], 'real folders instead of a Current link: not a signable bundle');
  fs.rmSync(root, { recursive: true, force: true });
});

test('the sidecar build copies with links followed, drops the framework copy and signs the helpers', () => {
  const build = fs.readFileSync(new URL('../scripts/build-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(build, /spawnSync\('cp', \['-RL', plan\.resourceDir, plan\.bundleResourceDir\]/, 'links are followed, as the Tauri bundler does');
  assert.doesNotMatch(build, /verbatimSymlinks/);
  assert.match(build, /_internal', 'Python\.framework'/, 'the framework copy is removed');
  assert.match(build, /sign-macos-helpers\.mjs/);
  assert.ok(build.indexOf('sign-macos-helpers.mjs') > build.indexOf('fs.chmodSync(plan.mediaCliOutput'), 'signing runs after the helpers are built');
});
