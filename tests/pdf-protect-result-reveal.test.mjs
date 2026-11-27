import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('PDF AES-256 Protector reveals the completed result above the shared dock', () => {
  assert.match(html, /if \(\(activePdfTool === 'unlock' \|\| activePdfTool === 'protect'\) && pdfOutputBlob instanceof Blob\) \{\s*revealPdfWorkbenchResult\(document\.getElementById\('pdf-workbench-preview'\), 'end', true\);/);
});
