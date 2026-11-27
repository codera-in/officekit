import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../design/mocks/image-metadata-workbench.html', import.meta.url), 'utf8');

test('image metadata mock compares the current converter with the proposed gallery destination', () => {
  for (const content of [
    'Before · current image converter',
    'After · exact EXIF-removal destination',
    'Remove image metadata',
    'Remove EXIF metadata',
    'Your original stays unchanged',
    'Download clean copy',
    'Processed locally',
    'GPS coordinates',
    'Animated GIF/WebP frames and TIFF pages stay intact',
  ]) {
    assert.ok(html.includes(content), `mock must show ${content}`);
  }
  assert.match(html, /390 px wide/);
  assert.match(html, /data-theme="light"/);
  assert.match(html, /Preview dark theme/);
});

test('image metadata mock remains self-contained and performs no file or network action', () => {
  const [, script] = html.match(/<script>([\s\S]*?)<\/script>/) ?? [];
  assert.ok(script, 'mock must contain its local theme toggle');
  assert.doesNotThrow(() => new vm.Script(script));
  assert.doesNotMatch(script, /fetch\s*\(|XMLHttpRequest|FileReader|navigator\.clipboard/);
  assert.doesNotMatch(html, /<script[^>]+src=|<link[^>]+href="https?:/);
});
