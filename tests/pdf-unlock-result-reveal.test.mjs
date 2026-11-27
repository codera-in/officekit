import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('PDF unlock result scrolls above the dock immediately and respects reduced motion', () => {
  const source = html.match(/function revealPdfWorkbenchResult\(target, alignment = 'start', immediate = false\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(source, 'the shared PDF result reveal helper exists');
  assert.match(html, /finally \{\s*renderPdfSelection\(\);\s*if \(\(activePdfTool === 'unlock' \|\| activePdfTool === 'protect'\) && pdfOutputBlob instanceof Blob\) \{\s*revealPdfWorkbenchResult\(document\.getElementById\('pdf-workbench-preview'\), 'end', true\);/);

  const context = { window: { matchMedia: () => ({ matches: true }) } };
  vm.runInNewContext(`${source}\nglobalThis.reveal = revealPdfWorkbenchResult;`, context);
  const calls = [];
  context.reveal({ scrollIntoView: options => calls.push([options.block, options.behavior]) });
  assert.deepEqual(calls, [['start', 'auto']]);

  context.window.matchMedia = () => ({ matches: false });
  context.reveal({ scrollIntoView: options => calls.push([options.block, options.behavior]) }, 'end', true);
  assert.deepEqual(calls, [
    ['start', 'auto'],
    ['end', 'auto'],
  ]);
});
