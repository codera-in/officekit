import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('Compress PDF keeps its finished size comparison above the shared dock', () => {
  const revealTools = html.match(/if \(\[([^\]]+)\]\.includes\(activePdfTool\) && pdfOutputBlob instanceof Blob\)/);
  assert.ok(revealTools, 'completed PDF results should use the shared reveal path');
  assert.match(revealTools[1], /'compress'/, 'Compress PDF should use the shared reveal path');
  assert.match(html, /preview\?\.style\.setProperty\('scroll-margin-bottom', '12px'\);\s*revealPdfWorkbenchResult\(preview, 'end', true\)/);
  assert.match(html, /observer\.observe\(dock\)/);
});
