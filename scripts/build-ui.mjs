import { createHash, randomUUID } from 'node:crypto';
import { copyFile, open, mkdir, readFile, rename, stat, unlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..');

export async function buildUi({ root = REPO_ROOT } = {}) {
  const resolvedRoot = path.resolve(root);
  const sourcePath = path.join(resolvedRoot, 'index.html');
  const quickControlsSource = path.join(resolvedRoot, 'quick-controls.html');
  const outputDir = path.join(resolvedRoot, 'dist-ui');
  const outputPath = path.join(outputDir, 'index.html');
  const temporaryPath = path.join(outputDir, `.index.html.${process.pid}.${randomUUID()}.tmp`);
  const source = await readFile(sourcePath);
  const quickControls = await readFile(quickControlsSource);
  if (source.length === 0) throw new Error('The OfficeKit UI source is empty');
  await syncTauriInlineScriptHashes(resolvedRoot, source.toString('utf8'));
  const sourceMode = (await stat(sourcePath)).mode & 0o777;

  await mkdir(outputDir, { recursive: true });
  let file;
  try {
    file = await open(temporaryPath, 'wx', sourceMode);
    await file.writeFile(source);
    await file.sync();
    await file.close();
    file = undefined;
    await rename(temporaryPath, outputPath);
    const packaged = await readFile(outputPath);
    if (!packaged.equals(source)) throw new Error('Packaged UI does not match index.html');
    const quickControlsPath = path.join(outputDir, 'quick-controls.html');
    await copyFile(quickControlsSource, quickControlsPath);
    const packagedQuickControls = await readFile(quickControlsPath);
    if (!packagedQuickControls.equals(quickControls)) throw new Error('Packaged UI does not match quick-controls.html');
    return { sourcePath, outputPath, bytes: source.length };
  } catch (error) {
    if (file) await file.close().catch(() => {});
    await unlink(temporaryPath).catch(() => {});
    throw error;
  }
}

export async function syncTauriInlineScriptHashes(root, html) {
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    .filter(([, attributes, script]) => !/\bsrc\s*=/i.test(attributes) && script.trim())
    .map(([, , script]) => `'sha256-${createHash('sha256').update(script).digest('base64')}'`);
  if (scripts.length === 0) throw new Error('The OfficeKit UI has no inline scripts to authorize');

  const configPath = path.join(root, 'src-tauri', 'tauri.conf.json');
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  const csp = config.app?.security?.csp;
  if (!csp || typeof csp !== 'object' || Array.isArray(csp)) {
    throw new Error('Tauri production CSP is missing from src-tauri/tauri.conf.json');
  }
  csp['script-src'] = ["'self'", ...scripts].join(' ');

  const temporaryConfigPath = `${configPath}.${process.pid}.${randomUUID()}.tmp`;
  const configMode = (await stat(configPath)).mode & 0o777;
  let file;
  try {
    file = await open(temporaryConfigPath, 'wx', configMode);
    await file.writeFile(`${JSON.stringify(config, null, 2)}\n`, 'utf8');
    await file.sync();
    await file.close();
    file = undefined;
    await rename(temporaryConfigPath, configPath);
  } catch (error) {
    if (file) await file.close().catch(() => {});
    await unlink(temporaryConfigPath).catch(() => {});
    throw error;
  }
  return csp['script-src'];
}

async function main() {
  const result = await buildUi();
  process.stdout.write(`Prepared Tauri UI: ${result.outputPath} (${result.bytes} bytes)\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => {
    process.stderr.write(`UI build failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
