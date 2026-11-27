import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..');

export function sidecarPlan({
  root = REPO_ROOT,
  targetTriple,
  platform = process.platform,
  pythonCommand,
  env = process.env,
  exists = fs.existsSync,
}) {
  if (!targetTriple) throw new Error('A Rust target triple is required');
  const pathApi = platform === 'win32' ? path.win32 : path.posix;
  const workRoot = pathApi.join(root, '.build', 'backend-sidecar');
  const virtualenvPython = platform === 'win32'
    ? pathApi.join(root, '.venv', 'Scripts', 'python.exe')
    : pathApi.join(root, '.venv', 'bin', 'python');
  const configuredPython = env.PYTHON;
  const systemPython = platform === 'win32' ? 'python' : 'python3';
  const pythonCandidates = pythonCommand
    ? [pythonCommand]
    : [...new Set([
      configuredPython?.trim(),
      exists(virtualenvPython) ? virtualenvPython : null,
      systemPython,
      'python',
    ].filter(Boolean))];
  const python = pythonCandidates[0];
  const extension = platform === 'win32' ? '.exe' : '';
  const distRoot = pathApi.join(workRoot, 'dist');
  const resourceDir = platform === 'darwin' ? pathApi.join(distRoot, 'officekit-backend') : null;
  const bundleResourceDir = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'resources', 'officekit-backend') : null;
  const output = pathApi.join(root, 'src-tauri', 'binaries', `officekit-backend-${targetTriple}${extension}`);
  const mediaCliSource = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'media-cli-launcher.rs') : null;
  const mediaCliOutput = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'binaries', 'officekit-media') : null;
  const dataSeparator = platform === 'win32' ? ';' : ':';
  const fontDirectory = pathApi.join(root, 'assets', 'fonts');
  const wordlistPath = pathApi.join(root, 'assets', 'wordlists', 'eff-large-wordlist.txt');
  const wordlistReadmePath = pathApi.join(root, 'assets', 'wordlists', 'README.md');
  const jxlLicensePath = pathApi.join(root, 'assets', 'licenses', 'pylibjxl-BSD-3-Clause.txt');
  const visionSource = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'macos-vision-ocr.swift') : null;
  const visionOutput = platform === 'darwin' ? pathApi.join(resourceDir, 'officekit-vision-ocr') : null;
  const mediaTransformSource = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'macos-media-transform.swift') : null;
  const mediaTransformOutput = platform === 'darwin' ? pathApi.join(resourceDir, 'officekit-media-transform') : null;
  const swiftArch = targetTriple.startsWith('aarch64-') ? 'arm64' : targetTriple.startsWith('x86_64-') ? 'x86_64' : null;
  if (platform === 'darwin' && !swiftArch) throw new Error(`Unsupported macOS Swift helper target: ${targetTriple}`);
  const visionArgs = platform === 'darwin'
    ? [visionSource, '-O', '-target', `${swiftArch}-apple-macosx14.0`, '-framework', 'Vision', '-framework', 'ImageIO', '-framework', 'CoreGraphics', '-o', visionOutput]
    : null;
  const mediaTransformArgs = platform === 'darwin'
    ? ['-parse-as-library', mediaTransformSource, '-O', '-target', `${swiftArch}-apple-macosx14.0`, '-framework', 'AVFoundation', '-framework', 'CoreMedia', '-framework', 'Vision', '-framework', 'ImageIO', '-o', mediaTransformOutput]
    : null;
  const args = [
    '-m', 'PyInstaller', '--noconfirm', '--clean', platform === 'darwin' ? '--onedir' : '--onefile',
    '--name', 'officekit-backend',
    '--hidden-import', 'xlrd',
    '--distpath', distRoot,
    '--workpath', pathApi.join(workRoot, 'work'),
    '--specpath', pathApi.join(workRoot, 'spec'),
    '--add-data', `${pathApi.join(root, 'index.html')}${dataSeparator}.`,
    '--add-data', `${pathApi.join(root, 'release-profile.json')}${dataSeparator}.`,
    '--add-data', `${pathApi.join(fontDirectory, 'NotoSansTamil-Regular.ttf')}${dataSeparator}fonts`,
    '--add-data', `${pathApi.join(fontDirectory, 'OFL-NotoSansTamil.txt')}${dataSeparator}fonts`,
    '--add-data', `${pathApi.join(fontDirectory, 'NotoSans-Regular.ttf')}${dataSeparator}fonts`,
    '--add-data', `${pathApi.join(fontDirectory, 'OFL-NotoSans.txt')}${dataSeparator}fonts`,
    '--add-data', `${wordlistPath}${dataSeparator}wordlists`,
    '--add-data', `${wordlistReadmePath}${dataSeparator}wordlists`,
    '--add-data', `${jxlLicensePath}${dataSeparator}licenses`,
  ];
  const archiveOs = targetTriple.includes('windows') ? 'win' : targetTriple.includes('apple-darwin') ? 'mac' : null;
  const archiveArch = targetTriple.startsWith('aarch64-') || targetTriple.startsWith('arm64-') ? 'arm64'
    : targetTriple.startsWith('x86_64-') ? 'x64' : null;
  const archiveEngineRoot = archiveOs && archiveArch
    ? pathApi.join(root, 'node_modules', '7zip-bin-full', archiveOs, archiveArch)
    : null;
  const archiveEngineFiles = archiveOs === 'win' ? ['7z.exe', '7z.dll'] : archiveOs === 'mac' ? ['7zz'] : [];
  for (const file of archiveEngineFiles) {
    const source = pathApi.join(archiveEngineRoot, file);
    if (!exists(source)) throw new Error(`Pinned 7-Zip engine is missing: ${source}. Run npm ci.`);
    args.push('--add-binary', `${source}${dataSeparator}archive-engines`);
  }
  if (archiveEngineRoot) {
    const license = pathApi.join(archiveEngineRoot, 'License.txt');
    if (!exists(license)) throw new Error(`Pinned 7-Zip license is missing: ${license}. Run npm ci.`);
    args.push('--add-data', `${license}${dataSeparator}archive-engines`);
  }
  if (platform !== 'darwin') {
    for (const dependency of ['fastapi', 'uvicorn', 'starlette', 'pandas', 'openpyxl', 'PIL', 'pypdfium2', 'pikepdf', 'pytesseract', 'psutil']) {
      args.push('--collect-all', dependency);
    }
  }
  // RapidOCR loads its ONNX inference provider by engine type and stores the
  // pinned offline models as package data. Preserve both in every sidecar.
  args.push('--collect-submodules', 'rapidocr', '--collect-data', 'rapidocr');
  args.push('--collect-submodules', 'mcp.server', '--collect-submodules', 'mcp.shared',
    '--collect-submodules', 'mcp.types', '--collect-submodules', 'mcp_types');
  // Certificate parsing, validation and PKCS#11 are loaded lazily by signing workers.
  args.push('--collect-submodules', 'pyhanko', '--collect-data', 'pyhanko',
    '--collect-submodules', 'pyhanko_certvalidator');
  if (platform === 'darwin' || platform === 'win32') {
    args.push('--collect-submodules', 'pkcs11', '--collect-binaries', 'pkcs11');
  }
  args.push(pathApi.join(root, 'backend_main.py'));
  const launcherSource = platform === 'darwin' ? pathApi.join(root, 'src-tauri', 'sidecar-launcher.rs') : null;
  return { python, pythonCandidates, args, output, distRoot, workRoot, extension, resourceDir, bundleResourceDir,
    launcherSource, mediaCliSource, mediaCliOutput, visionSource, visionOutput, visionArgs,
    mediaTransformSource, mediaTransformOutput, mediaTransformArgs, targetTriple, archiveEngineRoot, archiveEngineFiles };
}

export function findPythonWithPyInstaller(candidates, run = spawnSync) {
  for (const python of candidates) {
    const result = run(python, ['-m', 'PyInstaller', '--version'], { encoding: 'utf8' });
    if (!result.error && result.status === 0) return python;
  }
  return null;
}

function commandOutput(command, args) {
  const result = spawnSync(command, args, { cwd: REPO_ROOT, encoding: 'utf8' });
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || `${command} failed`).trim());
  }
  return result.stdout.trim();
}

export function resolveTargetTriple(env = process.env, run = commandOutput) {
  const tauriTarget = env.TAURI_ENV_TARGET_TRIPLE?.trim();
  return tauriTarget || run('rustc', ['--print', 'host-tuple']);
}

function main() {
  const targetTriple = resolveTargetTriple();
  const plan = sidecarPlan({ targetTriple });
  if (process.argv.includes('--dry-run')) {
    process.stdout.write(`${JSON.stringify(plan, null, 2)}\n`);
    return;
  }

  const installedPython = findPythonWithPyInstaller(plan.pythonCandidates);
  if (!installedPython) {
    throw new Error('PyInstaller is not installed. Install the pinned build dependencies with: python -m pip install -r requirements-build.txt');
  }
  plan.python = installedPython;
  fs.mkdirSync(path.dirname(plan.output), { recursive: true });
  fs.mkdirSync(path.join(plan.workRoot, 'spec'), { recursive: true });
  const build = spawnSync(plan.python, plan.args, { cwd: REPO_ROOT, stdio: 'inherit' });
  if (build.status !== 0) throw new Error(`PyInstaller failed with exit code ${build.status}`);

  if (plan.visionSource) {
    const visionBuild = spawnSync('swiftc', plan.visionArgs, { cwd: REPO_ROOT, encoding: 'utf8' });
    if (visionBuild.status !== 0) {
      throw new Error((visionBuild.stderr || visionBuild.stdout || 'Unable to build the macOS Vision OCR helper').trim());
    }
    fs.chmodSync(plan.visionOutput, 0o755);
  }
  if (plan.mediaTransformSource) {
    const mediaTransformBuild = spawnSync('swiftc', plan.mediaTransformArgs, { cwd: REPO_ROOT, encoding: 'utf8' });
    if (mediaTransformBuild.status !== 0) {
      throw new Error((mediaTransformBuild.stderr || mediaTransformBuild.stdout || 'Unable to build the macOS media transform helper').trim());
    }
    fs.chmodSync(plan.mediaTransformOutput, 0o755);
  }

  const builtBinary = path.join(plan.distRoot, `officekit-backend${plan.extension}`);
  if (plan.resourceDir) {
    fs.rmSync(plan.bundleResourceDir, { recursive: true, force: true });
    // The Tauri bundler follows symbolic links when it copies resources, so the app would end up with
    // real copies of the Python binary (_internal/Python, Python.framework/Python). A signature made
    // on the framework's original binary is bound to its Info.plist, so a copy elsewhere is "invalid"
    // to Apple, and a framework root with real files cannot be signed at all. Copy with links
    // followed (fs.cpSync ignores `dereference` here), then drop the framework folder: the backend
    // loads _internal/Python and never the framework copy.
    const copied = spawnSync('cp', ['-RL', plan.resourceDir, plan.bundleResourceDir], { encoding: 'utf8' });
    if (copied.status !== 0) throw new Error((copied.stderr || 'Unable to copy the packaged backend').trim());
    fs.rmSync(path.join(plan.bundleResourceDir, '_internal', 'Python.framework'), { recursive: true, force: true });
    const launcher = spawnSync('rustc', [
      '--edition=2021',
      '--target', plan.targetTriple,
      plan.launcherSource,
      '-o', plan.output,
    ], { cwd: REPO_ROOT, encoding: 'utf8' });
    if (launcher.status !== 0) {
      throw new Error((launcher.stderr || launcher.stdout || 'Unable to build the native macOS sidecar launcher').trim());
    }
    const cliLauncher = spawnSync('rustc', [
      '--edition=2021',
      '--target', plan.targetTriple,
      plan.mediaCliSource,
      '-o', plan.mediaCliOutput,
    ], { cwd: REPO_ROOT, encoding: 'utf8' });
    if (cliLauncher.status !== 0) {
      throw new Error((cliLauncher.stderr || cliLauncher.stdout || 'Unable to build the packaged Media Toolkit CLI launcher').trim());
    }
    fs.chmodSync(plan.mediaCliOutput, 0o755);
    // Release builds only: sign the helpers Tauri does not sign, so notarization accepts the app.
    const signing = spawnSync(process.execPath, [path.join(REPO_ROOT, 'scripts', 'sign-macos-helpers.mjs')], { cwd: REPO_ROOT, stdio: 'inherit' });
    if (signing.status !== 0) throw new Error('Signing the packaged helpers failed');
  } else {
    fs.copyFileSync(builtBinary, plan.output);
    if (process.platform !== 'win32') fs.chmodSync(plan.output, 0o755);
  }
  process.stdout.write(`Built Tauri sidecar: ${plan.output}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`Backend sidecar build failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}
