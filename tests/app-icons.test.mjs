import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { isOfficeKitPackagedMacIcon } from '../scripts/macos-app-icon.mjs';

const root = path.resolve(import.meta.dirname, '..');
const iconDir = path.join(root, 'src-tauri', 'icons');
const read = name => fs.readFileSync(path.join(iconDir, name));

function pngSize(bytes) {
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

test('Tauri bundle points at the refreshed platform icon formats', () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'src-tauri', 'tauri.conf.json'), 'utf8'));
  assert.match(config.build.beforeBuildCommand, /npm run icons:build/);
  const icons = config.bundle.icon.map(relative => path.join(root, 'src-tauri', relative));
  for (const iconPath of icons) assert.ok(fs.existsSync(iconPath), `Missing bundled icon: ${iconPath}`);
  assert.ok(icons.some(iconPath => iconPath.endsWith('icon.icns')));
  assert.ok(icons.some(iconPath => iconPath.endsWith('icon.ico')));
});

test('Tauri PNG variants have the exact square sizes declared by the bundle', () => {
  for (const [name, size] of [['32x32.png', 32], ['128x128.png', 128], ['128x128@2x.png', 256], ['icon.png', 512]]) {
    assert.deepEqual(pngSize(read(name)), [size, size], name);
  }
});

test('the repository-level app icon matches the generated OfficeKit mark', () => {
  const sharedIcon = fs.readFileSync(path.join(root, 'app-icon.png'));
  assert.deepEqual(sharedIcon, read('icon.png'), 'app-icon.png must not retain the legacy briefcase artwork');
});

test('mounted installer validation requires the approved monogram ICNS in the app bundle', () => {
  const expectedIcon = read('icon.icns');
  const bundledImages = [['icon_128x128.png', Buffer.from('same rendered icon')]];
  const expectedImages = [['icon_128x128.png', Buffer.from('same rendered icon')]];
  assert.equal(isOfficeKitPackagedMacIcon('icon.icns', bundledImages, expectedImages), true);
  assert.equal(isOfficeKitPackagedMacIcon('generic.icns', bundledImages, expectedImages), false);
  assert.equal(isOfficeKitPackagedMacIcon('icon.icns', bundledImages, [['icon_128x128.png', Buffer.from('briefcase')]]), false);
  assert.equal(isOfficeKitPackagedMacIcon('icon.icns', bundledImages, [['other.png', Buffer.from('same rendered icon')]]), false);
  assert.equal(isOfficeKitPackagedMacIcon('icon.icns', null, expectedImages), false);
});

test('macOS and Windows icon containers are valid and contain high-resolution artwork', () => {
  const icns = read('icon.icns');
  assert.equal(icns.toString('ascii', 0, 4), 'icns');
  assert.equal(icns.readUInt32BE(4), icns.length);
  assert.ok(icns.includes(Buffer.from('ic09')) && icns.includes(Buffer.from('ic10')));
  const macLargeIconOffset = icns.indexOf(Buffer.from('ic09'));
  const macLargeIconLength = icns.readUInt32BE(macLargeIconOffset + 4);
  assert.deepEqual(pngSize(icns.subarray(macLargeIconOffset + 8, macLargeIconOffset + macLargeIconLength)), [512, 512]);

  const ico = read('icon.ico');
  assert.equal(ico.readUInt16LE(0), 0);
  assert.equal(ico.readUInt16LE(2), 1);
  assert.equal(ico.readUInt16LE(4), 6);
  for (let index = 0; index < 6; index += 1) {
    const entryOffset = 6 + index * 16;
    const size = ico[entryOffset] || 256;
    const imageBytes = ico.readUInt32LE(entryOffset + 8);
    const imageOffset = ico.readUInt32LE(entryOffset + 12);
    assert.deepEqual(pngSize(ico.subarray(imageOffset, imageOffset + imageBytes)), [size, size]);
  }
});

test('macOS ICNS small sizes match Tauri-generated artwork after Apple decoding', { skip: process.platform !== 'darwin' }, () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-icon-test-'));
  const cli = path.join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');
  const generatedDir = path.join(temporary, 'generated');
  const currentDir = path.join(temporary, 'current.iconset');
  const expectedDir = path.join(temporary, 'expected.iconset');
  const currentIcns = path.join(temporary, 'current.icns');
  const expectedIcns = path.join(temporary, 'expected.icns');
  fs.mkdirSync(generatedDir);
  try {
    const tauri = spawnSync(process.execPath, [cli, 'icon', path.join(root, 'app-icon.png'), '--output', generatedDir], { encoding: 'utf8' });
    assert.equal(tauri.status, 0, tauri.stderr || tauri.error);
    fs.writeFileSync(currentIcns, read('icon.icns'));
    fs.copyFileSync(path.join(generatedDir, 'icon.icns'), expectedIcns);
    for (const [source, output] of [[currentIcns, currentDir], [expectedIcns, expectedDir]]) {
      const decoded = spawnSync('iconutil', ['-c', 'iconset', source, '--output', output], { encoding: 'utf8' });
      assert.equal(decoded.status, 0, decoded.stderr || decoded.error);
    }
    for (const name of ['icon_16x16.png', 'icon_16x16@2x.png', 'icon_32x32.png', 'icon_32x32@2x.png', 'icon_128x128.png', 'icon_512x512.png']) {
      assert.deepEqual(
        fs.readFileSync(path.join(currentDir, name)),
        fs.readFileSync(path.join(expectedDir, name)),
        `${name} must remain valid and legible in the macOS icon set`,
      );
    }
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('the icon source and repeatable asset generator are checked in', () => {
  const svg = fs.readFileSync(path.join(iconDir, 'officekit-icon.svg'), 'utf8');
  assert.match(svg, /data-mark="officekit-monogram"/);
  assert.match(svg, /<line x1="(?:[0-9.]+)" y1="(?:[0-9.]+)" x2="(?:[0-9.]+)" y2="(?:[0-9.]+)"/);
  assert.ok(fs.existsSync(path.join(root, 'scripts', 'build-app-icons.mjs')));
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.ok(packageJson.devDependencies['@tauri-apps/cli'], 'the icon generator relies on the pinned Tauri icon encoder');
});
