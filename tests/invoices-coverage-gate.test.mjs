import assert from 'node:assert/strict';
import test from 'node:test';
import { assessInvoiceCoverage } from '../scripts/check-invoice-coverage.mjs';

const inventory = {python:['officekit/invoices/domain.py'], javascript:['assets/officekit-slice-invoices.js'], native:['src-tauri/src/invoice_native.rs']};
function reports() {
  return {
    python: {files: {'officekit/invoices/domain.py': {summary: {missing_lines:0,missing_branches:0,excluded_lines:0}, functions: {'':{summary:{num_statements:1,covered_lines:1}},calculate:{summary:{num_statements:2,covered_lines:2}}}}}},
    javascript: {'/repo/assets/officekit-slice-invoices.js': {s:{0:1}, f:{0:1}, b:{0:[1,1]}}},
    native: {data:[{files:[{filename:'/repo/src-tauri/src/invoice_native.rs',summary:{lines:{count:2,covered:2},functions:{count:1,covered:1},branches:{count:2,covered:2}}}]}]},
  };
}
test('module coverage gate accepts measured complete source inventory', () => {
  assert.deepEqual(assessInvoiceCoverage(reports(), inventory), []);
});
test('module coverage gate fails missing/unimported source and exclusions', () => {
  const report = reports();
  report.python.files['officekit/invoices/domain.py'].summary.excluded_lines = 1;
  assert.match(assessInvoiceCoverage(report, inventory).join('\n'), /excluded/);
  assert.equal(assessInvoiceCoverage(reports(), {...inventory, python:['officekit/invoices/new.py']}).length, 1);
  assert.equal(assessInvoiceCoverage(reports(), {...inventory, javascript:['assets/new.js']}).length, 1);
  assert.equal(assessInvoiceCoverage(reports(), {...inventory, native:['src-tauri/src/new.rs']}).length, 1);
});
test('module coverage gate fails zero function/branch execution in every language', () => {
  const report = reports();
  report.python.files['officekit/invoices/domain.py'].functions.calculate.summary.covered_lines = 0;
  report.javascript['/repo/assets/officekit-slice-invoices.js'].b[0][1] = 0;
  report.native.data[0].files[0].summary.branches.covered = 1;
  const errors = assessInvoiceCoverage(report, inventory);
  assert.equal(errors.length, 3);
  assert.match(errors[0], /uncalled function calculate/);
  assert.match(errors[1], /statement\/function\/branch/);
  assert.match(errors[2], /branches/);
});
test('module coverage gate refuses reports without function counters', () => {
  const report = reports();
  delete report.python.files['officekit/invoices/domain.py'].functions;
  delete report.javascript['/repo/assets/officekit-slice-invoices.js'].f;
  delete report.native.data[0].files[0].summary.functions;
  assert.equal(assessInvoiceCoverage(report, inventory).length, 3);
});
