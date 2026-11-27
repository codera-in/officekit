import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { findPythonWithPyInstaller, resolveTargetTriple, sidecarPlan as createSidecarPlan } from '../scripts/build-backend-sidecar.mjs';

function sidecarPlan(options) {
  const fixtureRoot = options.root !== process.cwd();
  return createSidecarPlan({
    ...options,
    exists: (file) => (fixtureRoot && file.includes('7zip-bin-full')) || (options.exists?.(file) ?? fs.existsSync(file)),
  });
}

test('sidecar build uses Tauri’s selected target instead of the runner host', () => {
  const hostTarget = 'aarch64-pc-windows-msvc';
  const x64Target = resolveTargetTriple({ TAURI_ENV_TARGET_TRIPLE: 'x86_64-pc-windows-msvc' }, () => hostTarget);
  const arm64Target = resolveTargetTriple({ TAURI_ENV_TARGET_TRIPLE: 'aarch64-pc-windows-msvc' }, () => hostTarget);
  const fallbackTarget = resolveTargetTriple({}, () => hostTarget);
  const x64Plan = sidecarPlan({ root: 'C:\\work\\officekit', targetTriple: x64Target, platform: 'win32' });
  const arm64Plan = sidecarPlan({ root: 'C:\\work\\officekit', targetTriple: arm64Target, platform: 'win32' });

  assert.equal(x64Target, 'x86_64-pc-windows-msvc');
  assert.equal(arm64Target, 'aarch64-pc-windows-msvc');
  assert.equal(fallbackTarget, hostTarget);
  assert.equal(x64Plan.output, 'C:\\work\\officekit\\src-tauri\\binaries\\officekit-backend-x86_64-pc-windows-msvc.exe');
  assert.equal(arm64Plan.output, 'C:\\work\\officekit\\src-tauri\\binaries\\officekit-backend-aarch64-pc-windows-msvc.exe');
});

test('sidecar build prefers configured and repository Python environments', () => {
  const envPython = sidecarPlan({
    root: '/work/officekit',
    targetTriple: 'aarch64-apple-darwin',
    platform: 'darwin',
    env: { PYTHON: '/opt/officekit-python' },
  });
  const virtualenv = sidecarPlan({
    root: '/work/officekit',
    targetTriple: 'aarch64-apple-darwin',
    platform: 'darwin',
    exists: (file) => file === '/work/officekit/.venv/bin/python',
    env: {},
  });
  const configuredFallback = sidecarPlan({
    root: '/work/officekit',
    targetTriple: 'aarch64-apple-darwin',
    platform: 'darwin',
    exists: (file) => file === '/work/officekit/.venv/bin/python',
    env: { PYTHON: '/opt/broken-python' },
  });
  const windows = sidecarPlan({
    root: 'C:\\work\\officekit',
    targetTriple: 'x86_64-pc-windows-msvc',
    platform: 'win32',
    exists: (file) => file === 'C:\\work\\officekit\\.venv\\Scripts\\python.exe',
    env: {},
  });

  assert.equal(envPython.python, '/opt/officekit-python');
  assert.equal(virtualenv.python, '/work/officekit/.venv/bin/python');
  assert.deepEqual(configuredFallback.pythonCandidates, [
    '/opt/broken-python',
    '/work/officekit/.venv/bin/python',
    'python3',
    'python',
  ]);
  assert.equal(windows.python, 'C:\\work\\officekit\\.venv\\Scripts\\python.exe');
});

test('sidecar selects the first interpreter that can import PyInstaller', () => {
  const checked = [];
  const selected = findPythonWithPyInstaller(['project-python', 'system-python'], (command, args) => {
    checked.push(command);
    return { status: command === 'project-python' ? 1 : 0 };
  });

  assert.equal(selected, 'system-python');
  assert.deepEqual(checked, ['project-python', 'system-python']);
});

test('sidecar build names target-specific macOS and Linux binaries', () => {
  const linux = sidecarPlan({ root: '/work/officekit', targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  const mac = sidecarPlan({ root: '/work/officekit', targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  assert.equal(linux.output, '/work/officekit/src-tauri/binaries/officekit-backend-x86_64-unknown-linux-gnu');
  assert.equal(mac.output, '/work/officekit/src-tauri/binaries/officekit-backend-aarch64-apple-darwin');
  assert.equal(mac.mediaCliOutput, '/work/officekit/src-tauri/binaries/officekit-media');
  assert.equal(mac.mediaCliSource, '/work/officekit/src-tauri/media-cli-launcher.rs');
});

test('Windows sidecar path has an exe suffix', () => {
  const plan = sidecarPlan({ root: 'C:\\officekit', targetTriple: 'x86_64-pc-windows-msvc', platform: 'win32' });
  assert.ok(plan.output.endsWith('officekit-backend-x86_64-pc-windows-msvc.exe'));
});

test('PyInstaller data separator matches the target platform', () => {
  const windows = sidecarPlan({ root: 'C:\\officekit', targetTriple: 'x86_64-pc-windows-msvc', platform: 'win32' });
  const unix = sidecarPlan({ root: '/work/officekit', targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  const windowsData = windows.args[windows.args.indexOf('--add-data') + 1];
  const unixData = unix.args[unix.args.indexOf('--add-data') + 1];

  assert.match(windowsData, /;\.$/);
  assert.match(unixData, /:\.$/);
});

test('macOS sidecar uses an onedir bundle to avoid per-launch extraction', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  assert.ok(plan.args.includes('--onedir'));
  assert.ok(!plan.args.includes('--onefile'));
  assert.equal(plan.resourceDir, '/work/officekit/.build/backend-sidecar/dist/officekit-backend');
  assert.equal(plan.bundleResourceDir, '/work/officekit/src-tauri/resources/officekit-backend');
  assert.equal(plan.launcherSource, '/work/officekit/src-tauri/sidecar-launcher.rs');
  assert.equal(plan.visionSource, '/work/officekit/src-tauri/macos-vision-ocr.swift');
  assert.equal(plan.visionOutput, '/work/officekit/.build/backend-sidecar/dist/officekit-backend/officekit-vision-ocr');
  assert.equal(plan.mediaTransformSource, '/work/officekit/src-tauri/macos-media-transform.swift');
  assert.equal(plan.mediaTransformOutput, '/work/officekit/.build/backend-sidecar/dist/officekit-backend/officekit-media-transform');
  assert.ok(plan.mediaTransformArgs.includes('AVFoundation'));
  assert.equal(plan.visionArgs[plan.visionArgs.indexOf('-target') + 1], 'arm64-apple-macosx14.0');
  assert.ok(plan.visionArgs.includes('Vision'));
  assert.ok(plan.visionArgs.includes('ImageIO'));
  assert.ok(!plan.args.includes('--collect-all'));
});

test('Intel macOS Vision helper uses the supported macOS 14 deployment target', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'x86_64-apple-darwin', platform: 'darwin' });
  assert.equal(plan.visionArgs[plan.visionArgs.indexOf('-target') + 1], 'x86_64-apple-macosx14.0');
  assert.equal(plan.mediaTransformArgs[plan.mediaTransformArgs.indexOf('-target') + 1], 'x86_64-apple-macosx14.0');
});

test('non-macOS sidecar remains a single executable until its packaging is ported', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  assert.ok(plan.args.includes('--onefile'));
  assert.equal(plan.resourceDir, null);
  assert.equal(plan.visionSource, null);
  assert.equal(plan.visionOutput, null);
  assert.equal(plan.mediaTransformSource, null);
  assert.equal(plan.mediaTransformOutput, null);
});

test('macOS app resources include the bundled Vision executable', () => {
  const config = JSON.parse(fs.readFileSync('src-tauri/tauri.macos.conf.json', 'utf8'));
  assert.ok(config.bundle.resources.includes('resources/officekit-backend/**/*'));
  assert.ok(config.bundle.resources.includes('resources/OfficeKit Optimize Image.workflow/**/*'));
  assert.ok(config.bundle.resources.includes('resources/Open in OfficeKit.workflow/**/*'));
  assert.ok(fs.existsSync('src-tauri/macos-vision-ocr.swift'));
});

test('sidecar refuses to plan a packaged archive engine that is missing from the real build tree', () => {
  assert.throws(
    () => createSidecarPlan({
      root: process.cwd(),
      targetTriple: 'aarch64-apple-darwin',
      platform: 'darwin',
      exists: (file) => !file.endsWith('/7zz'),
    }),
    /Pinned 7-Zip engine is missing/,
  );
});

test('sidecar includes server UI data and dynamic dependencies', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  assert.ok(plan.args.includes('--add-data'));
  assert.ok(plan.args.includes('--collect-all'));
  assert.ok(plan.args.includes('/work/officekit/backend_main.py'));
});

test('sidecar bundles the licensed OfficeKit Tamil shaping font and its license', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  const data = plan.args.filter((arg, index) => plan.args[index - 1] === '--add-data');
  assert.ok(data.includes('/work/officekit/assets/fonts/NotoSansTamil-Regular.ttf:fonts'));
  assert.ok(data.includes('/work/officekit/assets/fonts/OFL-NotoSansTamil.txt:fonts'));
  assert.ok(data.includes('/work/officekit/assets/fonts/NotoSans-Regular.ttf:fonts'));
  assert.ok(data.includes('/work/officekit/assets/fonts/OFL-NotoSans.txt:fonts'));
});

test('sidecar bundles the EFF passphrase list in the runtime wordlists directory', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  const data = plan.args.filter((arg, index) => plan.args[index - 1] === '--add-data');
  assert.ok(data.includes('/work/officekit/assets/wordlists/eff-large-wordlist.txt:wordlists'));
  assert.ok(data.includes('/work/officekit/assets/wordlists/README.md:wordlists'));
});

test('sidecar includes the pylibjxl BSD notice with its bundled runtime', () => {
  const plan = sidecarPlan({ root: '/work/officekit', targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  const data = plan.args.filter((arg, index) => plan.args[index - 1] === '--add-data');
  assert.ok(data.includes('/work/officekit/assets/licenses/pylibjxl-BSD-3-Clause.txt:licenses'));
  assert.match(fs.readFileSync('assets/licenses/pylibjxl-BSD-3-Clause.txt', 'utf8'), /BSD 3-Clause License/);
});

test('system resource route dependency is pinned and collected into the sidecar', () => {
  const plan = sidecarPlan({ root: process.cwd(), targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  const collected = plan.args.flatMap((arg, index) => arg === '--collect-all' ? [plan.args[index + 1]] : []);
  const requirements = fs.readFileSync('requirements.txt', 'utf8');

  assert.ok(collected.includes('psutil'));
  assert.match(requirements, /^psutil==7\.2\.2$/m);
});

test('pandas is analyzed through its import hook instead of bundling its test suite', () => {
  const plan = sidecarPlan({ root: process.cwd(), targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });

  assert.ok(!plan.args.includes('--collect-all'));
  assert.match(plan.args.at(-1), /backend_main\.py$/);
});

test('similar-image decoding dependency is pinned and included in the sidecar', () => {
  const plan = sidecarPlan({ root: process.cwd(), targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  const collected = plan.args.flatMap((arg, index) => arg === '--collect-all' ? [plan.args[index + 1]] : []);
  const requirements = fs.readFileSync('requirements.txt', 'utf8');

  assert.ok(collected.includes('PIL'));
  assert.match(requirements, /^pillow==12\.3\.0$/im);
});

test('offline RapidOCR runtime and ONNX models are pinned and collected into each sidecar', () => {
  const mac = sidecarPlan({ root: process.cwd(), targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  const linux = sidecarPlan({ root: process.cwd(), targetTriple: 'x86_64-unknown-linux-gnu', platform: 'linux' });
  const requirements = fs.readFileSync('requirements.txt', 'utf8');

  for (const [name, version] of [
    ['rapidocr', '3.9.2'],
    ['onnxruntime', '1.25.1'],
    ['opencv-python', '4.13.0.90'],
    ['pyclipper', '1.4.0'],
    ['Shapely', '2.1.2'],
  ]) {
    assert.match(requirements, new RegExp(`^${name}==${version}$`, 'm'));
  }
  for (const plan of [mac, linux]) {
    assert.ok(plan.args.includes('--collect-submodules'));
    assert.ok(plan.args.includes('rapidocr'));
    assert.ok(plan.args.includes('--collect-data'));
    assert.equal(plan.args[plan.args.indexOf('--collect-data') + 1], 'rapidocr');
  }
});

test('DNS resolver is pinned for static sidecar import analysis', () => {
  const plan = sidecarPlan({ root: process.cwd(), targetTriple: 'aarch64-apple-darwin', platform: 'darwin' });
  const requirements = fs.readFileSync('requirements.txt', 'utf8');

  assert.match(requirements, /^dnspython==2\.8\.0$/m);
  assert.ok(plan.args.at(-1).endsWith('backend_main.py'));
});

test('PDF signing runtime is pinned and packaged with the platform token adapter', () => {
  const requirements = fs.readFileSync('requirements.txt', 'utf8');
  assert.match(requirements, /^pyHanko==0\.37\.0$/m);
  assert.match(requirements, /^python-pkcs11==0\.10\.0; sys_platform == "darwin" or sys_platform == "win32"$/m);
  for (const [platform, targetTriple] of [['darwin', 'aarch64-apple-darwin'], ['win32', 'x86_64-pc-windows-msvc']]) {
    const { args } = sidecarPlan({
      root: process.cwd(),
      platform,
      targetTriple,
      exists: (file) => file.includes('7zip-bin-full') || fs.existsSync(file),
    });
    assert.ok(args.some((value, index) => value === '--collect-submodules' && args[index + 1] === 'pyhanko'));
    assert.ok(args.some((value, index) => value === '--collect-data' && args[index + 1] === 'pyhanko'));
    assert.ok(args.some((value, index) => value === '--collect-submodules' && args[index + 1] === 'pyhanko_certvalidator'));
    assert.ok(args.some((value, index) => value === '--collect-submodules' && args[index + 1] === 'pkcs11'));
    assert.ok(args.some((value, index) => value === '--collect-binaries' && args[index + 1] === 'pkcs11'));
  }
});

test('stdio MCP server runtime and protocol types are collected into the sidecar', () => {
  const requirements = fs.readFileSync('requirements.txt', 'utf8');
  assert.match(requirements, /^mcp==2\.2\.0$/m);
  assert.match(requirements, /^mcp-types==2\.2\.0$/m);
  const { args } = sidecarPlan({ root: process.cwd(), platform: 'darwin', targetTriple: 'aarch64-apple-darwin' });
  for (const module of ['mcp.server', 'mcp.shared', 'mcp.types', 'mcp_types']) {
    assert.ok(args.some((value, index) => value === '--collect-submodules' && args[index + 1] === module));
  }
});

test('Tauri, Rust and API health versions stay in sync', () => {
  const tauri = JSON.parse(fs.readFileSync('src-tauri/tauri.conf.json', 'utf8'));
  const cargo = fs.readFileSync('src-tauri/Cargo.toml', 'utf8');
  const api = fs.readFileSync('app.py', 'utf8');
  const cargoVersion = cargo.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  assert.ok(cargoVersion, 'Cargo package version is declared');
  assert.equal(tauri.version, cargoVersion);
  // The sidecar reports the version the shell passes it, so a version bump never needs an edit in app.py.
  assert.match(api, /^\s+version\s*=\s*resolve_api_version\(\),/m);
  assert.match(api, /OFFICEKIT_APP_VERSION/);
});
