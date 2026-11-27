import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

test('Reorder PDF Pages reveals the new order and PDF above the shared dock', async () => {
  const [source, packaged] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
  ]);

  for (const html of [source, packaged]) {
    assert.match(html, /if \(\['merge', 'split', 'compress', 'images', 'text', 'metadata', 'delete-pages', 'reorder-pages'\]\.includes\(activePdfTool\) && pdfOutputBlob instanceof Blob\)/);
    assert.match(html, /preview\?\.style\.setProperty\('scroll-margin-bottom', '12px'\)/);
    assert.match(html, /revealPdfWorkbenchResult\(preview, 'end', true\)/);
    assert.match(html, /!\['merge', 'split', 'compress', 'images', 'text', 'metadata', 'delete-pages', 'reorder-pages'\]\.includes\(activePdfTool\)/);
  }
});
