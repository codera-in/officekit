import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

function runRequired(run, command, args) {
  const result = run(command, args, { encoding: 'utf8' });
  if (result.error || result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed: ${result.stderr || result.error?.message || result.stdout || 'unknown error'}`);
  }
}

export function shouldCreateMacDmgFallback({
  platform,
  tauriExitCode,
  dmgRequested,
  appBundleFresh,
  appSignatureVerified,
}) {
  return platform === 'darwin' && tauriExitCode !== 0 && dmgRequested === true &&
    appBundleFresh === true && appSignatureVerified === true;
}

export function createMacDmgFallback({
  appBundle,
  outputPath,
  run = spawnSync,
  fileSystem = fs,
  tempRoot = os.tmpdir(),
}) {
  if (typeof appBundle !== 'string' || typeof outputPath !== 'string' ||
      !fileSystem.statSync(appBundle).isDirectory()) {
    throw new Error('A completed OfficeKit app bundle is required to create the macOS installer.');
  }
  const staging = fileSystem.mkdtempSync(path.join(tempRoot, 'officekit-dmg-'));
  let publication;
  try {
    runRequired(run, 'codesign', ['--verify', '--deep', '--strict', appBundle]);
    const source = path.join(staging, 'source');
    fileSystem.mkdirSync(source);
    const stagedApp = path.join(source, path.basename(appBundle));
    runRequired(run, 'ditto', [appBundle, stagedApp]);
    fileSystem.symlinkSync('/Applications', path.join(source, 'Applications'), 'dir');
    runRequired(run, 'codesign', ['--verify', '--deep', '--strict', stagedApp]);
    fileSystem.mkdirSync(path.dirname(outputPath), { recursive: true });
    const image = path.join(staging, 'OfficeKit.dmg');
    try {
      runRequired(run, 'hdiutil', [
        'create', '-volname', 'OfficeKit', '-srcfolder', source,
        '-ov', '-format', 'UDZO', image,
      ]);
    } catch (error) {
      if (!/Device not configured|DiskManagement|DiskArbitration/i.test(error.message)) throw error;
      // makehybrid writes the HFS+ filesystem without attaching a temporary
      // disk device. Conversion then compresses that file into a normal UDZO.
      fileSystem.rmSync(image, { force: true });
      const hybrid = path.join(staging, 'OfficeKit-hybrid.dmg');
      runRequired(run, 'hdiutil', ['makehybrid', '-hfs', '-hfs-volume-name', 'OfficeKit', '-o', hybrid, source]);
      runRequired(run, 'hdiutil', ['convert', '-format', 'UDZO', '-o', image, hybrid]);
    }
    runRequired(run, 'hdiutil', ['verify', image]);
    // Keep any previous installer intact until the replacement is verified.
    // Publish from the destination filesystem so rename remains atomic.
    publication = fileSystem.mkdtempSync(path.join(path.dirname(outputPath), '.officekit-dmg-'));
    const verifiedImage = path.join(publication, path.basename(outputPath));
    fileSystem.copyFileSync(image, verifiedImage);
    fileSystem.renameSync(verifiedImage, outputPath);
    return outputPath;
  } finally {
    if (publication) fileSystem.rmSync(publication, { recursive: true, force: true });
    fileSystem.rmSync(staging, { recursive: true, force: true });
  }
}
