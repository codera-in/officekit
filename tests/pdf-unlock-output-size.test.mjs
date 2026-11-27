import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const formatters = await readFile(new URL('../assets/officekit-formatters.js', import.meta.url), 'utf8');

test('PDF Password Remover formats a small unlocked output in readable units', () => {
  const expression = html.match(/const outputSize = ([^\n]+);/)?.[1];
  assert.ok(expression, 'the PDF workbench derives the visible output size');
  assert.match(expression, /'unlock'/, 'Password Remover uses the shared readable-size formatter');

  const context = { window: {}, activePdfTool: 'unlock', pdfOutputBlob: { size: 692 } };
  vm.runInNewContext(`${formatters}\nglobalThis.outputSize = (${expression});`, context);
  assert.equal(context.outputSize, '692 bytes');
});
