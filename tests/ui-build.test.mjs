import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { buildUi } from '../scripts/build-ui.mjs';

test('source and packaged inline scripts parse before a desktop build', async () => {
  for (const file of ['index.html', 'dist-ui/index.html']) {
    const html = await fs.readFile(file, 'utf8');
    const inlineScripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)]
      .filter(([, attributes]) => !/\bsrc\s*=/i.test(attributes));
    assert.ok(inlineScripts.length > 0, `${file} contains inline application scripts`);
    inlineScripts.forEach(([, , source], index) => {
      assert.doesNotThrow(
        () => new vm.Script(source, { filename: `${file}:inline-script-${index + 1}` }),
        `${file} inline script ${index + 1} must parse before Tauri packages it`,
      );
    });
  }
});

test('generated font assets preserve the upstream font files and Quick Controls script', async () => {
  const pairs = [
    ['node_modules/@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2', 'dist-ui/assets/fontawesome/webfonts/fa-solid-900.woff2'],
    ['node_modules/@fontsource-variable/plus-jakarta-sans/files/plus-jakarta-sans-latin-wght-normal.woff2', 'dist-ui/assets/fonts/plus-jakarta-sans-latin-wght-normal.woff2'],
    ['node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2', 'dist-ui/assets/fonts/jetbrains-mono-latin-wght-normal.woff2'],
    ['assets/quick-controls.js', 'dist-ui/assets/quick-controls.js'],
  ];
  for (const [source, output] of pairs) {
    assert.deepEqual(await fs.readFile(output), await fs.readFile(source), `${output} must match ${source}`);
  }
});

test('Tauri dev and release builds refresh packaged UI from the authoritative source', async () => {
  const config = JSON.parse(await fs.readFile('src-tauri/tauri.conf.json', 'utf8'));
  const packageJson = JSON.parse(await fs.readFile('package.json', 'utf8'));
  assert.equal(packageJson.scripts['build:ui'], 'node scripts/build-ui-assets.mjs && node scripts/build-ui.mjs');
  assert.match(config.build.beforeDevCommand, /npm run build:ui/);
  assert.match(config.build.beforeBuildCommand, /npm run build:ui/);

  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-ui-build-'));
  try {
    await fs.mkdir(path.join(temp, 'dist-ui'));
    await fs.mkdir(path.join(temp, 'src-tauri'));
    await fs.writeFile(path.join(temp, 'index.html'), '<!doctype html><script>window.officekitReady = true;</script>');
    await fs.writeFile(path.join(temp, 'quick-controls.html'), '<!doctype html><title>quick controls</title>');
    await fs.writeFile(path.join(temp, 'dist-ui', 'index.html'), '<!doctype html><title>stale</title>');
    await fs.writeFile(path.join(temp, 'src-tauri', 'tauri.conf.json'), JSON.stringify({ app: { security: { csp: { 'script-src': "'self' 'sha256-stale'" } } } }));
    await buildUi({ root: temp });
    assert.equal(
      await fs.readFile(path.join(temp, 'dist-ui', 'index.html'), 'utf8'),
      '<!doctype html><script>window.officekitReady = true;</script>',
    );
    assert.equal(
      await fs.readFile(path.join(temp, 'dist-ui', 'quick-controls.html'), 'utf8'),
      '<!doctype html><title>quick controls</title>',
    );
    const config = JSON.parse(await fs.readFile(path.join(temp, 'src-tauri', 'tauri.conf.json'), 'utf8'));
    const scriptHash = createHash('sha256').update('window.officekitReady = true;').digest('base64');
    assert.equal(config.app.security.csp['script-src'], `'self' 'sha256-${scriptHash}'`);
    if (process.platform !== 'win32') {
      const sourceMode = (await fs.stat(path.join(temp, 'index.html'))).mode & 0o777;
      const outputMode = (await fs.stat(path.join(temp, 'dist-ui', 'index.html'))).mode & 0o777;
      assert.equal(outputMode, sourceMode);
    }
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
  }
});

test('the full test command rebuilds the packaged UI before checking source parity', async () => {
  const packageJson = JSON.parse(await fs.readFile('package.json', 'utf8'));
  assert.match(packageJson.scripts.test, /^npm run build:ui && node --test /);
});

test('UI build fails closed when the source is missing and retains the last packaged page', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-ui-build-'));
  try {
    await fs.mkdir(path.join(temp, 'dist-ui'));
    await fs.writeFile(path.join(temp, 'dist-ui', 'index.html'), '<!doctype html><title>known-good</title>');
    await assert.rejects(buildUi({ root: temp }));
    assert.equal(
      await fs.readFile(path.join(temp, 'dist-ui', 'index.html'), 'utf8'),
      '<!doctype html><title>known-good</title>',
    );
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
  }
});

test('UI build rejects a missing Tauri security policy instead of packaging unsynchronized scripts', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-ui-build-'));
  try {
    await fs.mkdir(path.join(temp, 'dist-ui'));
    await fs.mkdir(path.join(temp, 'src-tauri'));
    await fs.writeFile(path.join(temp, 'index.html'), '<script>window.officekitReady = true;</script>');
    await fs.writeFile(path.join(temp, 'quick-controls.html'), '<!doctype html><title>quick controls</title>');
    await fs.writeFile(path.join(temp, 'dist-ui', 'index.html'), '<!doctype html><title>known-good</title>');
    await fs.writeFile(path.join(temp, 'src-tauri', 'tauri.conf.json'), JSON.stringify({ app: {} }));
    await assert.rejects(buildUi({ root: temp }), /Tauri production CSP is missing/);
    assert.equal(
      await fs.readFile(path.join(temp, 'dist-ui', 'index.html'), 'utf8'),
      '<!doctype html><title>known-good</title>',
    );
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
  }
});
