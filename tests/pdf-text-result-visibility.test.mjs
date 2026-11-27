import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

test('PDF text extraction reveals its result above the shared action dock', async () => {
  const [source, packaged] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
  ]);

  for (const html of [source, packaged]) {
    const revealTools = html.match(/if \(\[([^\]]+)\]\.includes\(activePdfTool\) && pdfOutputBlob instanceof Blob\)/);
    assert.ok(revealTools, 'completed PDF results should use the shared reveal path');
    assert.match(revealTools[1], /'text'/, 'Extract PDF Text should be included in the reveal path');
    assert.match(html, /preview\?\.style\.setProperty\('scroll-margin-bottom', '12px'\)/);
    assert.match(html, /revealPdfWorkbenchResult\(preview, 'end', true\)/);
    const observerTools = html.match(/!\[([^\]]+)\]\.includes\(activePdfTool\)/);
    assert.ok(observerTools, 'the shared reveal observer should stop when leaving its supported tools');
    assert.match(observerTools[1], /'text'/, 'Extract PDF Text should remain supported by the reveal observer');
    assert.doesNotMatch(html, /requestAnimationFrame\(\(\) => document\.getElementById\('pdf-workbench-preview'\).*scrollIntoView\(\{ block: 'start'/);
  }
});
