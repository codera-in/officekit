import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);

test('Remove PDF Metadata formats tiny input and output sizes in source and packaged UI', async () => {
  const [source, packaged, formatter] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
    readFile(new URL('assets/officekit-formatters.js', root), 'utf8'),
  ]);
  for (const html of [source, packaged]) {
    assert.match(html, /size\.textContent = window\.OfficeKitFormatters\.fileSize\(file\.size\)/);
    assert.match(html, /const outputSize = \[[^\]]*'metadata'[^\]]*\]\.includes\(activePdfTool\) \? window\.OfficeKitFormatters\.fileSize\(pdfOutputBlob\.size\)/);
    assert.match(html, /officekit-formatters\.js/);
  }
  const context = { window: {}, Number };
  vm.runInNewContext(formatter, context);
  assert.equal(context.window.OfficeKitFormatters.fileSize(626), '626 bytes');
  assert.equal(context.window.OfficeKitFormatters.fileSize(1234), '1.2 KiB');
});
