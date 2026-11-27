import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { access, copyFile, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';

const execFileAsync = promisify(execFile);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..');

async function ensureExists(filePath, description) {
  try {
    await access(filePath);
  } catch {
    throw new Error(`${description} is missing: ${filePath}`);
  }
}

export async function buildUiAssets({ root = REPO_ROOT } = {}) {
  const resolvedRoot = path.resolve(root);
  const nodeModules = path.join(resolvedRoot, 'node_modules');
  const outputParent = path.join(resolvedRoot, 'dist-ui');
  const output = path.join(outputParent, 'assets');
  const stage = path.join(outputParent, `.assets-${process.pid}-${randomUUID()}`);
  const backup = path.join(outputParent, `.assets-old-${process.pid}-${randomUUID()}`);
  const fontAwesome = path.join(nodeModules, '@fortawesome', 'fontawesome-free');
  const jakartaFont = path.join(nodeModules, '@fontsource-variable', 'plus-jakarta-sans');
  const jetbrainsFont = path.join(nodeModules, '@fontsource-variable', 'jetbrains-mono');
  const tailwindCli = path.join(nodeModules, '@tailwindcss', 'cli', 'dist', 'index.mjs');
  const inputs = [
    [path.join(resolvedRoot, 'assets', 'officekit.input.css'), 'Tailwind input stylesheet'],
    [path.join(resolvedRoot, 'index.html'), 'OfficeKit UI source'],
    [path.join(resolvedRoot, 'quick-controls.html'), 'OfficeKit Quick Controls source'],
    [tailwindCli, 'Tailwind compiler'],
    [path.join(fontAwesome, 'css', 'fontawesome.min.css'), 'Font Awesome base stylesheet'],
    [path.join(fontAwesome, 'css', 'solid.min.css'), 'Font Awesome solid icon stylesheet'],
    [path.join(fontAwesome, 'webfonts', 'fa-solid-900.woff2'), 'Font Awesome solid icon font'],
    [path.join(jakartaFont, 'files', 'plus-jakarta-sans-latin-wght-normal.woff2'), 'Plus Jakarta Sans font'],
    [path.join(jetbrainsFont, 'files', 'jetbrains-mono-latin-wght-normal.woff2'), 'JetBrains Mono font'],
  ];

  for (const [filePath, description] of inputs) await ensureExists(filePath, description);
  await mkdir(outputParent, { recursive: true });
  await rm(stage, { recursive: true, force: true });
  await mkdir(path.join(stage, 'fonts'), { recursive: true });
  await mkdir(path.join(stage, 'fontawesome', 'css'), { recursive: true });
  await mkdir(path.join(stage, 'fontawesome', 'webfonts'), { recursive: true });
  await mkdir(path.join(stage, 'licenses'), { recursive: true });
  await mkdir(path.join(stage, 'ergonomics'), { recursive: true });

  try {
    const cssPath = path.join(stage, 'officekit.css');
    await execFileAsync(process.execPath, [
      tailwindCli,
      '-i', path.join(resolvedRoot, 'assets', 'officekit.input.css'),
      '-o', cssPath,
      '--minify',
    ], { cwd: resolvedRoot, maxBuffer: 4 * 1024 * 1024 });

    await Promise.all([
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-action-icons.js'), path.join(stage, 'officekit-action-icons.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-tool-actions.js'), path.join(stage, 'officekit-tool-actions.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-activity.js'), path.join(stage, 'officekit-activity.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-workspace.js'), path.join(stage, 'officekit-workspace.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-results.js'), path.join(stage, 'officekit-results.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-formatters.js'), path.join(stage, 'officekit-formatters.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-files.js'), path.join(stage, 'officekit-files.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'file-intake-capabilities.js'), path.join(stage, 'file-intake-capabilities.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-media-preview.js'), path.join(stage, 'officekit-media-preview.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-media.js'), path.join(stage, 'officekit-media.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-storage.js'), path.join(stage, 'officekit-storage.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-screenshot.js'), path.join(stage, 'officekit-screenshot.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-pdf-editor.js'), path.join(stage, 'officekit-pdf-editor.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-pdf-editor.css'), path.join(stage, 'officekit-pdf-editor.css')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-tour.js'), path.join(stage, 'officekit-tour.js')),
      ...['officekit-setup.js', 'officekit-setup.css', 'officekit-general-settings.js'].map(name => copyFile(path.join(resolvedRoot, 'assets', name), path.join(stage, name))),
      copyFile(path.join(resolvedRoot, 'assets', 'quick-controls.js'), path.join(stage, 'quick-controls.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-agents.js'), path.join(stage, 'officekit-agents.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-clipboard.js'), path.join(stage, 'officekit-clipboard.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-global-desktop.js'), path.join(stage, 'officekit-global-desktop.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-outcome.js'), path.join(stage, 'officekit-outcome.js')),
      copyFile(path.join(resolvedRoot, 'assets', 'officekit-section-nav.js'), path.join(stage, 'officekit-section-nav.js')),
      ...['officekit-date-picker.js', 'officekit-date-picker.css'].map(name => copyFile(path.join(resolvedRoot, 'assets', name), path.join(stage, name))),
      ...['calculators', 'developer', 'files', 'image', 'pdf-tools', 'invoices'].flatMap(slice => ['js', 'css'].map(extension => copyFile(path.join(resolvedRoot, 'assets', `officekit-slice-${slice}.${extension}`), path.join(stage, `officekit-slice-${slice}.${extension}`)))),
      ...['coach-workspace.html', 'coach-workspace.js', 'coach-workspace.css'].map(name => copyFile(path.join(resolvedRoot, 'assets', name), path.join(stage, name))),
      ...['officekit-ergonomics.js', 'ergonomics-companion.html', 'ergonomics-companion.js', 'ergonomics.css'].map(name => copyFile(path.join(resolvedRoot, 'assets', name), path.join(stage, name))),
      ...['water', 'stretch', 'eyes', 'meeting'].map(name => copyFile(path.join(resolvedRoot, 'assets', 'ergonomics', `${name}.png`), path.join(stage, 'ergonomics', `${name}.png`))),
      copyFile(inputs[6][0], path.join(stage, 'fontawesome', 'webfonts', 'fa-solid-900.woff2')),
      copyFile(inputs[7][0], path.join(stage, 'fonts', 'plus-jakarta-sans-latin-wght-normal.woff2')),
      copyFile(inputs[8][0], path.join(stage, 'fonts', 'jetbrains-mono-latin-wght-normal.woff2')),
      copyFile(path.join(fontAwesome, 'css', 'fontawesome.min.css'), path.join(stage, 'fontawesome', 'css', 'fontawesome.min.css')),
      copyFile(path.join(fontAwesome, 'css', 'solid.min.css'), path.join(stage, 'fontawesome', 'css', 'solid.min.css')),
      copyFile(path.join(fontAwesome, 'LICENSE.txt'), path.join(stage, 'licenses', 'fontawesome.txt')),
      copyFile(path.join(nodeModules, 'tailwindcss', 'LICENSE'), path.join(stage, 'licenses', 'tailwindcss.txt')),
      copyFile(path.join(nodeModules, 'daisyui', 'LICENSE'), path.join(stage, 'licenses', 'daisyui.txt')),
      copyFile(path.join(jakartaFont, 'LICENSE'), path.join(stage, 'licenses', 'plus-jakarta-sans.txt')),
      copyFile(path.join(jetbrainsFont, 'LICENSE'), path.join(stage, 'licenses', 'jetbrains-mono.txt')),
    ]);

    let hadPrevious = false;
    try {
      await rename(output, backup);
      hadPrevious = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    try {
      await rename(stage, output);
    } catch (error) {
      if (hadPrevious) await rename(backup, output).catch(() => {});
      throw error;
    }
    if (hadPrevious) await rm(backup, { recursive: true, force: true });
    const css = await readFile(path.join(output, 'officekit.css'));
    if (!css.length) throw new Error('Generated OfficeKit CSS is empty');
    return { output, cssBytes: css.length };
  } catch (error) {
    await rm(stage, { recursive: true, force: true });
    await rm(backup, { recursive: true, force: true });
    throw error;
  }
}

async function main() {
  const result = await buildUiAssets();
  process.stdout.write(`Prepared local OfficeKit UI assets: ${result.output} (${result.cssBytes} CSS bytes)\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => {
    process.stderr.write(`UI asset build failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
