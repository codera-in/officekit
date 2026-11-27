import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const mock = fs.readFileSync('design/mocks/saved-result-export-flow.html', 'utf8');

test('saved-result export review mock compares the current result screen with the proposal', () => {
  assert.match(mock, /Before · current calculator result/);
  assert.match(mock, /After · export, bookmark, reopen/);
  assert.match(mock, /width:390px/);
  assert.match(mock, /role="status"/);
  assert.match(mock, /aria-label="Saved result reopened from History"/);
});

test('proposed result actions preserve and export the original visible snapshot', () => {
  assert.match(mock, /Save result/);
  assert.match(mock, /Export…/);
  assert.match(mock, /Original calculation, unchanged/);
  assert.match(mock, /Original inputs and all 60 rows are included/);
  assert.match(mock, /Reuse inputs/);
  assert.match(mock, /No calculation inputs or results are uploaded/);
});

test('export mock uses local assets and only the implemented result attachment formats', () => {
  assert.match(mock, /Markdown \(\.md\)/);
  assert.match(mock, /HTML \(\.html\)/);
  assert.match(mock, /JSON \(\.json\)/);
  assert.match(mock, /CSV \(\.csv\)/);
  assert.match(mock, /Excel workbook \(\.xlsx\)/);
  assert.match(mock, /PowerPoint \(\.pptx\)/);
  assert.match(mock, /PDF report \(\.pdf\)/);
  assert.match(mock, /JPEG summary \(\.jpg\)/);
  assert.match(mock, /PNG summary \(\.png\)/);
  assert.match(mock, /one-page summary image, not the full repayment table/);
  assert.match(mock, /PDF report preview/);
  assert.match(mock, /Download PDF/);
  assert.match(mock, /Generated with OfficeKit · officekit\.app/);
  assert.doesNotMatch(mock, /<script\b|https?:\/\//i);
});
