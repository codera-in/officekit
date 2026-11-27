import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);

test('PDF Pages to PNG/JPEG formats small source and ZIP sizes in source and packaged UI', async () => {
  const [source, packaged, formatter] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
    readFile(new URL('assets/officekit-formatters.js', root), 'utf8'),
  ]);
  for (const html of [source, packaged]) {
    assert.match(html, /size\.textContent = window\.OfficeKitFormatters\.fileSize\(file\.size\)/);
    assert.match(html, /const outputSize = \[[^\]]*'images'[^\]]*\]\.includes\(activePdfTool\) \? window\.OfficeKitFormatters\.fileSize\(pdfOutputBlob\.size\)/);
    assert.match(html, /officekit-formatters\.js/);
  }
  const context = { window: {}, Number };
  vm.runInNewContext(formatter, context);
  assert.equal(context.window.OfficeKitFormatters.fileSize(3_174), '3.1 KiB');
  assert.equal(context.window.OfficeKitFormatters.fileSize(14_735), '14.4 KiB');
});
