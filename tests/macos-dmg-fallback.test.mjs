import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createMacDmgFallback, shouldCreateMacDmgFallback } from '../scripts/macos-dmg-fallback.mjs';

test('DMG fallback is limited to a fresh signed Mac app after a requested DMG build failed', () => {
  const common = {
    platform: 'darwin',
    tauriExitCode: 1,
    dmgRequested: true,
    appBundleFresh: true,
    appSignatureVerified: true,
  };
  assert.equal(shouldCreateMacDmgFallback(common), true);
  assert.equal(shouldCreateMacDmgFallback({ ...common, platform: 'linux' }), false);
  assert.equal(shouldCreateMacDmgFallback({ ...common, tauriExitCode: 0 }), false);
  assert.equal(shouldCreateMacDmgFallback({ ...common, dmgRequested: false }), false);
  assert.equal(shouldCreateMacDmgFallback({ ...common, appBundleFresh: false }), false);
  assert.equal(shouldCreateMacDmgFallback({ ...common, appSignatureVerified: false }), false);
});

test('DMG fallback preserves the signed app and creates a verified drag-to-Applications image', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-fallback-test-'));
  const appBundle = path.join(root, 'OfficeKit.app');
  const executable = path.join(appBundle, 'Contents', 'MacOS', 'officekit');
  const outputPath = path.join(root, 'bundle', 'dmg', 'OfficeKit_1.0.0_aarch64.dmg');
  const calls = [];
  let applicationsLink;
  try {
    fs.mkdirSync(path.dirname(executable), { recursive: true });
    fs.writeFileSync(executable, 'signed test app');
    const run = (command, args) => {
      calls.push([command, args]);
      if (command === 'ditto') {
        fs.cpSync(args[0], args[1], { recursive: true });
      } else if (command === 'hdiutil' && args[0] === 'create') {
        const sourceFolder = args[args.indexOf('-srcfolder') + 1];
        applicationsLink = fs.readlinkSync(path.join(sourceFolder, 'Applications'));
        fs.mkdirSync(path.dirname(args.at(-1)), { recursive: true });
        fs.writeFileSync(args.at(-1), 'verified test image');
      }
      return { status: 0 };
    };

    const result = createMacDmgFallback({ appBundle, outputPath, run, tempRoot: root });

    assert.equal(result, outputPath);
    assert.equal(fs.readFileSync(path.join(outputPath), 'utf8'), 'verified test image');
    assert.equal(fs.readFileSync(path.join(root, 'OfficeKit.app', 'Contents', 'MacOS', 'officekit'), 'utf8'), 'signed test app');
    assert.ok(applicationsLink === '/Applications' || applicationsLink.endsWith('\\Applications'));
    assert.deepEqual(calls.map(([command, args]) => [command, args[0]]), [
      ['codesign', '--verify'],
      ['ditto', appBundle],
      ['codesign', '--verify'],
      ['hdiutil', 'create'],
      ['hdiutil', 'verify'],
    ]);
    assert.ok(calls.find(([command, args]) => command === 'hdiutil' && args[0] === 'create')[1].includes('-format'));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('DMG fallback removes staging files and refuses to publish when the image verification fails', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-fallback-failure-'));
  const appBundle = path.join(root, 'OfficeKit.app');
  const executable = path.join(appBundle, 'Contents', 'MacOS', 'officekit');
  const outputPath = path.join(root, 'bundle', 'dmg', 'OfficeKit_1.0.0_aarch64.dmg');
  try {
    fs.mkdirSync(path.dirname(executable), { recursive: true });
    fs.writeFileSync(executable, 'signed test app');
    assert.throws(() => createMacDmgFallback({
      appBundle,
      outputPath,
      tempRoot: root,
      run(command, args) {
        if (command === 'ditto') fs.cpSync(args[0], args[1], { recursive: true });
        if (command === 'hdiutil' && args[0] === 'create') fs.writeFileSync(args.at(-1), 'bad image');
        const failed = command === 'hdiutil' && args[0] === 'verify';
        return { status: failed ? 1 : 0, stderr: failed ? 'image checksum is invalid' : '' };
      },
    }), /image checksum is invalid/);
    assert.deepEqual(fs.readdirSync(root).sort(), ['OfficeKit.app', 'bundle'].sort());
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('DMG fallback creates HFS+ directly when macOS cannot configure a disk device', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-device-failure-'));
  const appBundle = path.join(root, 'OfficeKit.app');
  const outputPath = path.join(root, 'bundle', 'OfficeKit.dmg');
  const calls = [];
  try {
    fs.mkdirSync(appBundle);
    fs.writeFileSync(path.join(appBundle, 'original'), 'signed app');
    const result = createMacDmgFallback({
      appBundle, outputPath, tempRoot: root,
      run(command, args) {
        calls.push([command, args]);
        if (command === 'ditto') fs.cpSync(args[0], args[1], { recursive: true });
        if (command === 'hdiutil' && args[0] === 'create') return { status: 1, stderr: 'hdiutil: create failed - Device not configured' };
        if (command === 'hdiutil' && args[0] === 'makehybrid') {
          const source = args.at(-1);
          assert.equal(fs.readFileSync(path.join(source, 'OfficeKit.app', 'original'), 'utf8'), 'signed app');
          assert.equal(fs.readlinkSync(path.join(source, 'Applications')), '/Applications');
          fs.writeFileSync(args[args.indexOf('-o') + 1], 'HFS+ image');
        }
        if (command === 'hdiutil' && args[0] === 'convert') {
          assert.equal(fs.readFileSync(args.at(-1), 'utf8'), 'HFS+ image');
          assert.ok(args.includes('UDZO'));
          fs.writeFileSync(args[args.indexOf('-o') + 1], 'compressed image');
        }
        return { status: 0 };
      },
    });
    assert.equal(result, outputPath);
    assert.equal(fs.readFileSync(outputPath, 'utf8'), 'compressed image');
    assert.deepEqual(calls.filter(([command]) => command === 'hdiutil').map(([, args]) => args[0]), ['create', 'makehybrid', 'convert', 'verify']);
    assert.deepEqual(fs.readdirSync(root).sort(), ['OfficeKit.app', 'bundle'].sort());
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

for (const failure of ['permission', 'conversion', 'checksum']) {
  test(`DMG fallback preserves the previous installer after ${failure} failure`, () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-atomic-'));
    const appBundle = path.join(root, 'OfficeKit.app');
    const outputPath = path.join(root, 'bundle', 'OfficeKit.dmg');
    const calls = [];
    try {
      fs.mkdirSync(appBundle);
      fs.mkdirSync(path.dirname(outputPath));
      fs.writeFileSync(outputPath, 'previous verified installer');
      assert.throws(() => createMacDmgFallback({
        appBundle, outputPath, tempRoot: root,
        run(command, args) {
          calls.push([command, args[0]]);
          if (command === 'ditto') fs.cpSync(args[0], args[1], { recursive: true });
          if (command === 'hdiutil' && args[0] === 'create') {
            if (failure === 'permission') return { status: 1, stderr: 'Permission denied' };
            return { status: 1, stderr: 'Device not configured' };
          }
          if (command === 'hdiutil' && args[0] === 'makehybrid') fs.writeFileSync(args[args.indexOf('-o') + 1], 'HFS+ image');
          if (command === 'hdiutil' && args[0] === 'convert') {
            if (failure === 'conversion') return { status: 1, stderr: 'Conversion failed' };
            fs.writeFileSync(args[args.indexOf('-o') + 1], 'unverified image');
          }
          if (command === 'hdiutil' && args[0] === 'verify') return { status: 1, stderr: 'Checksum failed' };
          return { status: 0 };
        },
      }), /Permission denied|Conversion failed|Checksum failed/);
      assert.equal(fs.readFileSync(outputPath, 'utf8'), 'previous verified installer');
      assert.deepEqual(fs.readdirSync(root).sort(), ['OfficeKit.app', 'bundle'].sort());
      if (failure === 'permission') assert.equal(calls.some(([, operation]) => operation === 'makehybrid'), false);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}
