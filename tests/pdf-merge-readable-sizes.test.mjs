import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);

test('Merge PDFs keeps tiny selected and output sizes readable in source and packaged UI', async () => {
  const [source, packaged, formatter] = await Promise.all([
    readFile(new URL('index.html', root), 'utf8'),
    readFile(new URL('dist-ui/index.html', root), 'utf8'),
    readFile(new URL('assets/officekit-formatters.js', root), 'utf8'),
  ]);
  for (const html of [source, packaged]) {
    assert.match(html, /function renderPdfSelection\(\) \{[\s\S]*?size\.textContent = window\.OfficeKitFormatters\.fileSize\(file\.size\)/);
    const outputTools = html.match(/const outputSize = \[([^\]]+)\]\.includes\(activePdfTool\) \? window\.OfficeKitFormatters\.fileSize\(pdfOutputBlob\.size\)/);
    assert.ok(outputTools, 'PDF output sizes should use the shared readable-size formatter');
    assert.match(outputTools[1], /'merge'/, 'Merge PDFs should use the shared output-size formatter');
    assert.match(html, /officekit-formatters\.js/);
  }
  const context = { window: {}, Number };
  vm.runInNewContext(formatter, context);
  assert.equal(context.window.OfficeKitFormatters.fileSize(626), '626 bytes');
  assert.equal(context.window.OfficeKitFormatters.fileSize(1234), '1.2 KiB');
});
