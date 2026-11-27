import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const artifacts = [
  ['source', fs.readFileSync(path.join(root, 'index.html'), 'utf8')],
  ['Tauri bundle', fs.readFileSync(path.join(root, 'dist-ui/index.html'), 'utf8')],
];

test('PDF Password Remover suppresses bug reporting for a rejected password in source and bundle', () => {
  for (const [label, html] of artifacts) {
    const helper = html.match(/function pdfFailureShouldReport\(tool, message\) \{[\s\S]*?\n        \}/)?.[0];
    assert.ok(helper, `${label} includes unlock-specific error classification`);
    const context = {};
    vm.runInNewContext(`${helper}\nglobalThis.wrongPassword = pdfFailureShouldReport('unlock', 'Incorrect password. Please try again.');\nglobalThis.serverFailure = pdfFailureShouldReport('unlock', 'PDF processing failed.');\nglobalThis.protectFailure = pdfFailureShouldReport('protect', 'Incorrect password.');`, context);
    assert.equal(context.wrongPassword, false, `${label} keeps a correctable password error local`);
    assert.equal(context.serverFailure, true, `${label} still reports unexpected unlock failures`);
    assert.equal(context.protectFailure, true, `${label} does not change protector failures`);
    assert.match(html, /setPdfWorkbenchStatus\(message, true, pdfFailureShouldReport\(activePdfTool, message\)\)/);
    assert.match(html, /if \(isError && !reportBug\) status\.setAttribute\('data-officekit-no-bug-report', ''\)/);
  }
});
