import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const STABLE_VERSION = /^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,5})$/;

export function bumpPatch(version) {
  const match = STABLE_VERSION.exec(version);
  if (!match) throw new Error(`Not a major.minor.patch version: "${version}"`);
  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`;
}

function readText(root, file) {
  return fs.readFileSync(path.join(root, file), 'utf8');
}

function writeText(root, file, text) {
  fs.writeFileSync(path.join(root, file), text);
}

function jsonVersion(root, file) {
  return JSON.parse(readText(root, file)).version;
}

const CARGO_PACKAGE_VERSION = /(\[package\][^\[]*?\nversion = ")([^"]+)(")/;
const CARGO_LOCK_ENTRY = /(\[\[package\]\]\nname = "officekit"\nversion = ")([^"]+)(")/;
const FOOTER_VERSION = /(id="app-build-version"[^>]*>Version )(\d+\.\d+\.\d+)(<)/;

function currentVersions(root) {
  return {
    'package.json': jsonVersion(root, 'package.json'),
    'package-lock.json': jsonVersion(root, 'package-lock.json'),
    'src-tauri/tauri.conf.json': jsonVersion(root, 'src-tauri/tauri.conf.json'),
    'src-tauri/Cargo.toml': CARGO_PACKAGE_VERSION.exec(readText(root, 'src-tauri/Cargo.toml'))?.[2],
    'src-tauri/Cargo.lock': CARGO_LOCK_ENTRY.exec(readText(root, 'src-tauri/Cargo.lock'))?.[2],
    'index.html': FOOTER_VERSION.exec(readText(root, 'index.html'))?.[2],
  };
}

/** Raises the patch version everywhere it is recorded and returns the new version. */
export function bumpProject(root) {
  const versions = currentVersions(root);
  const distribution = fs.existsSync(path.join(root, 'dist-ui', 'index.html'));
  if (Object.values(versions).some(value => !value) || new Set(Object.values(versions)).size !== 1) {
    throw new Error(`Version files disagree or are missing: ${JSON.stringify(versions)}`);
  }
  const next = bumpPatch(versions['package.json']);
  for (const file of ['package.json', 'src-tauri/tauri.conf.json']) {
    const data = JSON.parse(readText(root, file));
    data.version = next;
    writeText(root, file, `${JSON.stringify(data, null, 2)}\n`);
  }
  const lock = JSON.parse(readText(root, 'package-lock.json'));
  lock.version = next;
  if (lock.packages?.['']) lock.packages[''].version = next;
  writeText(root, 'package-lock.json', `${JSON.stringify(lock, null, 2)}\n`);
  writeText(root, 'src-tauri/Cargo.toml', readText(root, 'src-tauri/Cargo.toml').replace(CARGO_PACKAGE_VERSION, `$1${next}$3`));
  writeText(root, 'src-tauri/Cargo.lock', readText(root, 'src-tauri/Cargo.lock').replace(CARGO_LOCK_ENTRY, `$1${next}$3`));
  for (const file of distribution ? ['index.html', 'dist-ui/index.html'] : ['index.html']) {
    writeText(root, file, readText(root, file).replace(FOOTER_VERSION, `$1${next}$3`));
  }
  return next;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  process.stdout.write(`${bumpProject(root)}\n`);
}
