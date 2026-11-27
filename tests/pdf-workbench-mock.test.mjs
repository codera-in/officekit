import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const mock = fs.readFileSync(path.join(root, 'design/mocks/pdf-tools-workbench.html'), 'utf8');
const passwordMock = fs.readFileSync(path.join(root, 'design/mocks/pdf-protect-password-confirmation.html'), 'utf8');
const passwordLimitMock = fs.readFileSync(path.join(root, 'design/mocks/pdf-password-127-byte-limit.html'), 'utf8');
const xlsExportMock = fs.readFileSync(path.join(root, 'design/mocks/pdf-legacy-xls-export.html'), 'utf8');

test('PDF workbench mock covers the API-backed task flows and states conversion limits honestly', () => {
  for (const label of ['Merge PDFs', 'Split by pages', 'Compress PDF', 'PDF pages to PNG / JPEG', 'Remove metadata', 'Bank statement PDF to CSV / XLS / XLSX', 'Extract PDF tables', 'Unlock PDF (known password)', 'Protect PDF']) {
    assert.ok(mock.includes(label), `missing task flow: ${label}`);
  }
  assert.match(mock, /Statement export supports bank transaction layouts/);
  assert.match(mock, /table extractor exports selectable PDF tables after preview/);
  assert.match(mock, /does not reconstruct scans or unruled layouts/);
  assert.match(mock, /does not crack passwords/);
  assert.match(mock, /Every page is exported in order to one ZIP/);
  assert.match(mock, /PDF pages can render to PNG or JPEG in a ZIP/);
  assert.match(mock, /Known PDF password/);
  assert.match(mock, /New password/);
  assert.match(mock, /Original files are never changed/);
  assert.match(mock, /lossless stream recompression/i);
  assert.match(mock, /embedded identifiers may remain/i);
});

test('PDF workbench mock script is syntactically valid and self-contained', () => {
  const script = mock.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  assert.ok(script);
  assert.doesNotMatch(mock, /<script[^>]+src=|https?:\/\//i);
  assert.doesNotThrow(() => new vm.Script(script));
});

test('PDF password confirmation mock shows editable recovery and the 127-byte policy within the button cap', () => {
  assert.match(passwordMock, /Before · local validation is reported as a bug/);
  assert.match(passwordMock, /After · mismatch stays editable/);
  assert.match(passwordMock, /After · corrected result/);
  assert.match(passwordMock, /Confirm new PDF password/);
  assert.match(passwordMock, /Maximum 127 normalized UTF-8 bytes/);
  assert.match(passwordMock, /Passwords do not match\. Update either field to continue\./);
  assert.equal((passwordMock.match(/Buttons: 1\/3/g) || []).length, 2);
  assert.match(passwordMock, /Buttons: 3\/3/);
  assert.match(passwordMock, /@media \(max-width: 900px\)/);
  assert.doesNotMatch(passwordMock, /https?:\/\/|<script[^>]+src=/i);
});

test('PDF password-limit mock shows the prior misleading policy and the byte-count correction', () => {
  assert.match(passwordLimitMock, /<h2>Before<\/h2>/);
  assert.match(passwordLimitMock, /1,024 Unicode characters \(4,096 UTF-8 bytes\)/);
  assert.match(passwordLimitMock, /Maximum 127 NFKC-normalized UTF-8 bytes/);
  assert.match(passwordLimitMock, /131 entered · 131 normalized \/ 127 bytes/);
  assert.match(passwordLimitMock, /disabled>Create protected PDF/);
  assert.doesNotMatch(passwordLimitMock, /https?:\/\/|<script[^>]+src=/i);
});

test('legacy XLS export mock adds an explicit compatible option and bounded format guidance', () => {
  assert.match(xlsExportMock, /<span class="tag">BEFORE<\/span>/);
  assert.match(xlsExportMock, /<span class="tag">AFTER<\/span>/);
  assert.match(xlsExportMock, /Download XLS<\/button>/);
  assert.match(xlsExportMock, /65,536 rows and 256 columns/);
  assert.match(xlsExportMock, /formula-like content is escaped/);
  assert.doesNotMatch(xlsExportMock, /https?:\/\/|<script[^>]+src=/i);
});
