import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('Extract PDF Pages starts with blank page ranges that fit any source length', () => {
  assert.match(html, /let pdfSplitGroups = \[\s*\{ id: 1, name: 'cover\.pdf', pageRanges: '' \},\s*\{ id: 2, name: 'appendix\.pdf', pageRanges: '' \}\s*\];/);
  assert.match(html, /rangeInput\.placeholder = 'For example: 1-3, 5'/);
  assert.match(html, /const pdfSplitRangeMissing = activePdfTool === 'split' && pdfSplitGroups\.some\(group => !group\.pageRanges\.trim\(\)\)/);
  assert.match(html, /\|\| pdfSplitRangeMissing \|\|/);
});

test('Extract PDF Pages reveals its completed ZIP above the dock', () => {
  const reveal = html.match(/if \(\[([^\]]+)\]\.includes\(activePdfTool\) && pdfOutputBlob instanceof Blob\) \{\s*const preview = document\.getElementById\('pdf-workbench-preview'\);\s*preview\?\.style\.setProperty\('scroll-margin-bottom', '12px'\);\s*revealPdfWorkbenchResult\(preview, 'end', true\);/);
  assert.ok(reveal, 'successful PDF outputs should reveal their preview above the dock');
  assert.match(reveal[1], /'split'/, 'the completed ZIP should use the shared result reveal path');
});

test('Extract PDF Pages keeps its completed result within the three-button limit', () => {
  assert.match(html, /const add = document\.createElement\('button'\); add\.type = 'button'; add\.id = 'pdf-split-group-add';[^\n]*add\.hidden = Boolean\(pdfOutputBlob\)/);
  assert.match(html, /if \(activePdfTool === 'split'\) document\.getElementById\('pdf-split-group-add'\)\?\.setAttribute\('hidden', ''\)/);
  assert.match(html, /if \(activePdfTool === 'split'\) document\.getElementById\('pdf-split-group-add'\)\?\.removeAttribute\('hidden'\)/);
});
