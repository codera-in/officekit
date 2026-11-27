import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { bumpPatch, bumpProject } from '../scripts/bump-version.mjs';

test('bumpPatch raises only the patch of a strict stable version', () => {
  assert.equal(bumpPatch('1.0.0'), '1.0.1');
  assert.equal(bumpPatch('1.2.9'), '1.2.10');
  assert.equal(bumpPatch('10.20.30'), '10.20.31');
});

test('bumpPatch rejects anything that is not major.minor.patch', () => {
  for (const bad of ['1.0', '1.0.0-beta', 'v1.0.0', '1.0.0.1', '', 'x', '01.0.0', '1.0.99999999999']) {
    assert.throws(() => bumpPatch(bad), /version/i, bad);
  }
});

function fixture(version) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ok-bump-'));
  fs.mkdirSync(path.join(root, 'src-tauri'));
  fs.mkdirSync(path.join(root, 'dist-ui'));
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ name: 'x', version }, null, 2) + '\n');
  fs.writeFileSync(path.join(root, 'package-lock.json'), JSON.stringify({ name: 'x', version, packages: { '': { name: 'x', version }, 'node_modules/y': { version: '9.9.9' } } }, null, 2) + '\n');
  fs.writeFileSync(path.join(root, 'src-tauri', 'tauri.conf.json'), JSON.stringify({ productName: 'OfficeKit', version }, null, 2) + '\n');
  fs.writeFileSync(path.join(root, 'src-tauri', 'Cargo.toml'), `[package]\nname = "officekit"\nversion = "${version}"\n\n[dependencies]\nserde = { version = "1.0.0" }\n`);
  fs.writeFileSync(path.join(root, 'src-tauri', 'Cargo.lock'), `[[package]]\nname = "serde"\nversion = "1.0.0"\n\n[[package]]\nname = "officekit"\nversion = "${version}"\n`);
  const page = `<span id="app-build-version" class="x">Version ${version}</span>`;
  fs.writeFileSync(path.join(root, 'index.html'), page);
  fs.writeFileSync(path.join(root, 'dist-ui', 'index.html'), page);
  return root;
}

test('bumpProject updates every version carrier and nothing else', () => {
  const root = fixture('1.0.0');
  assert.equal(bumpProject(root), '1.0.1');
  const read = file => fs.readFileSync(path.join(root, file), 'utf8');
  assert.equal(JSON.parse(read('package.json')).version, '1.0.1');
  const lock = JSON.parse(read('package-lock.json'));
  assert.equal(lock.version, '1.0.1');
  assert.equal(lock.packages[''].version, '1.0.1');
  assert.equal(lock.packages['node_modules/y'].version, '9.9.9');
  assert.equal(JSON.parse(read('src-tauri/tauri.conf.json')).version, '1.0.1');
  assert.match(read('src-tauri/Cargo.toml'), /name = "officekit"\nversion = "1\.0\.1"/);
  assert.match(read('src-tauri/Cargo.toml'), /serde = \{ version = "1\.0\.0" \}/);
  assert.match(read('src-tauri/Cargo.lock'), /name = "serde"\nversion = "1\.0\.0"/);
  assert.match(read('src-tauri/Cargo.lock'), /name = "officekit"\nversion = "1\.0\.1"/);
  assert.match(read('index.html'), /Version 1\.0\.1</);
  assert.match(read('dist-ui/index.html'), /Version 1\.0\.1</);
});

test('bumpProject refuses to run when the version files disagree', () => {
  const root = fixture('1.0.0');
  fs.writeFileSync(path.join(root, 'src-tauri', 'tauri.conf.json'), JSON.stringify({ version: '1.0.5' }));
  assert.throws(() => bumpProject(root), /disagree/i);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version, '1.0.0');
});
