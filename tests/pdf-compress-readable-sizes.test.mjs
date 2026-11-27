import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);

test('Compress PDF formats its source, output and comparison sizes in source and packaged UI', async () => {
  const [source, packaged, formatter] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
    readFile(new URL('assets/officekit-formatters.js', root), 'utf8'),
  ]);
  for (const html of [source, packaged]) {
    assert.match(html, /function renderPdfSelection\(\) \{[\s\S]*?size\.textContent = window\.OfficeKitFormatters\.fileSize\(file\.size\)/);
    const outputTools = html.match(/const outputSize = \[([^\]]+)\]\.includes\(activePdfTool\) \? window\.OfficeKitFormatters\.fileSize\(pdfOutputBlob\.size\)/);
    assert.ok(outputTools, 'PDF output sizes should use the shared readable-size formatter');
    assert.match(outputTools[1], /'compress'/, 'Compress PDF should use the shared output-size formatter');
    assert.match(html, /const sourceSize = window\.OfficeKitFormatters\.fileSize\(pdfSelectedFiles\.reduce\(\(sum, file\) => sum \+ file\.size, 0\)\)/);
    assert.match(html, /officekit-formatters\.js/);
  }
  const context = { window: {}, Number };
  vm.runInNewContext(formatter, context);
  assert.equal(context.window.OfficeKitFormatters.fileSize(3_174), '3.1 KiB');
  assert.equal(context.window.OfficeKitFormatters.fileSize(2_969), '2.9 KiB');
});
