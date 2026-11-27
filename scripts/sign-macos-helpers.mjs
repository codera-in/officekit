// Signs the native helpers that the Tauri bundler does not sign itself: every Mach-O file inside the
// packaged Python backend (`src-tauri/resources/officekit-backend`), its Python.framework bundle and
// the `officekit-media` launcher. Apple notarization rejects the app when any of them lacks a
// Developer ID signature, a secure timestamp or the hardened runtime.
//
// It runs at the end of `build:sidecar`, because `tauri build` regenerates the sidecar and would
// discard an earlier signing step. It only acts for a "Developer ID Application:" identity, so local
// development builds keep their current behavior.

import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const DEVELOPER_ID_PREFIX = 'Developer ID Application:';
const MACHO_MAGICS = new Set([0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe, 0xcafebabe, 0xbebafeca]);
const DEFAULT_CONCURRENCY = 8;

// Mach-O and fat binaries; a Java class also starts with 0xCAFEBABE, so a fat header's architecture count
// (a small number) tells them apart.
export function isMachO(header) {
  if (!Buffer.isBuffer(header) || header.length < 8) return false;
  const magic = header.readUInt32BE(0);
  if (!MACHO_MAGICS.has(magic)) return false;
  if (magic === 0xcafebabe) {
    const architectures = header.readUInt32BE(4);
    return architectures >= 1 && architectures < 20;
  }
  if (magic === 0xbebafeca) {
    const architectures = header.readUInt32LE(4);
    return architectures >= 1 && architectures < 20;
  }
  return true;
}

export function isDeveloperIdentity(identity) {
  return typeof identity === 'string' && identity.startsWith(DEVELOPER_ID_PREFIX);
}

// Every Mach-O file under `root` (symbolic links are never followed or signed) and every .framework folder.
export function collectSignable(root, { readHeader = defaultReadHeader, list = fs.readdirSync, stat = fs.lstatSync } = {}) {
  const files = [];
  const bundles = [];
  const visit = (current) => {
    const info = stat(current);
    if (info.isSymbolicLink()) return;
    if (info.isDirectory()) {
      // Only a framework that still has its versioned layout (Versions/Current is a link) can be
      // signed as a bundle; a copy that followed the links has real folders and is signed file by file.
      if (current.endsWith('.framework') && isVersionedBundle(current, stat)) bundles.push(current);
      for (const name of list(current).sort()) visit(path.join(current, name));
    } else if (info.isFile() && isMachO(readHeader(current))) {
      files.push(current);
    }
  };
  visit(root);
  return { files, bundles };
}

function isVersionedBundle(framework, stat) {
  try {
    return stat(path.join(framework, 'Versions', 'Current')).isSymbolicLink();
  } catch {
    return false;
  }
}

function defaultReadHeader(file) {
  const descriptor = fs.openSync(file, 'r');
  try {
    const header = Buffer.alloc(8);
    const read = fs.readSync(descriptor, header, 0, 8, 0);
    return header.subarray(0, read);
  } finally {
    fs.closeSync(descriptor);
  }
}

// Files first (they can be signed in any order), then framework bundles deepest first, so a bundle's
// seal covers contents that are already signed.
export function signingOrder({ files, bundles }) {
  const depth = (item) => item.split(path.sep).length;
  return [
    ...files.map((target) => ({ kind: 'file', target })),
    ...[...bundles].sort((left, right) => depth(right) - depth(left) || left.localeCompare(right)).map((target) => ({ kind: 'bundle', target })),
  ];
}

export function codesignArguments({ identity, entitlements, target, timestamp = true }) {
  if (!identity) throw new Error('A signing identity is required.');
  const args = ['--force', '--options', 'runtime', timestamp ? '--timestamp' : '--timestamp=none', '--sign', identity];
  if (entitlements) args.push('--entitlements', entitlements);
  args.push(target);
  return args;
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { maxBuffer: 4 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) reject(new Error(`${command} ${args.at(-1)}: ${(stderr || stdout || error.message).trim().split('\n').slice(-2).join(' ')}`));
      else resolve(stdout);
    });
  });
}

async function pool(items, limit, task) {
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      await task(items[index]);
    }
  });
  await Promise.all(workers);
}

// Signs `roots` (folders or single files). Returns how many items were signed. Throws on the first failure.
export async function signMacosHelpers({
  identity,
  entitlements,
  roots,
  timestamp = true,
  concurrency = DEFAULT_CONCURRENCY,
  exec = run,
  log = (message) => process.stdout.write(`${message}\n`),
}) {
  const files = [];
  const bundles = [];
  for (const root of roots) {
    if (!fs.existsSync(root)) throw new Error(`Cannot sign missing path: ${root}`);
    const found = fs.lstatSync(root).isDirectory() ? collectSignable(root) : { files: [root], bundles: [] };
    files.push(...found.files);
    bundles.push(...found.bundles);
  }
  const order = signingOrder({ files, bundles });
  const sign = (item) => exec('codesign', codesignArguments({ identity, entitlements, target: item.target, timestamp }));
  await pool(order.filter((item) => item.kind === 'file'), concurrency, sign);
  for (const item of order.filter((entry) => entry.kind === 'bundle')) await sign(item);
  // Every signature must verify; a bundle verifies its nested code too.
  await pool(order, concurrency, (item) => exec('codesign', ['--verify', '--strict', item.target]));
  log(`Signed ${files.length} native files and ${bundles.length} framework bundles for notarization.`);
  return order.length;
}

async function main() {
  if (process.platform !== 'darwin') return;
  const identity = process.env.APPLE_SIGNING_IDENTITY;
  if (!isDeveloperIdentity(identity)) {
    process.stdout.write('Skipping helper signing: no Developer ID Application identity is set.\n');
    return;
  }
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  await signMacosHelpers({
    identity,
    entitlements: path.join(root, 'src-tauri', 'Entitlements.plist'),
    roots: [
      path.join(root, 'src-tauri', 'resources', 'officekit-backend'),
      path.join(root, 'src-tauri', 'binaries', 'officekit-media'),
    ],
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => {
    process.stderr.write(`Helper signing failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
