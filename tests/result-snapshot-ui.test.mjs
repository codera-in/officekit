import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const client = html.match(/\/\* RESULT SNAPSHOT CLIENT START \*\/([\s\S]*?)\/\* RESULT SNAPSHOT CLIENT END \*\//)?.[1];

function loadClient(fetch) {
  assert.ok(client, 'result snapshot and export helpers exist');
  const context = {
    fetch,
    officekitApiUrl: path => `http://127.0.0.1:8000${path}`,
    Date,
    JSON,
    Object,
    Array,
    Number,
    String,
    RegExp,
    Blob,
    TextEncoder,
  };
  vm.runInNewContext(client, context);
  return context;
}

test('calculator result screen exposes bookmark and export actions, and History exposes saved snapshots', () => {
  for (const id of ['emi-result', 'ci-result', 'vat-result', 'free-result']) {
    const match = html.match(new RegExp(`<div id="${id}"[^>]*>`));
    assert.ok(match, `${id} exists`);
  }
  assert.match(html, /id="saved-result-list"/);
  assert.match(html, /id="result-export-dialog"/);
  // The visible "Download…" is the accessible name: no aria-label may hide it (UX-1).
  assert.doesNotMatch(html, /aria-label="Download result"/);
  assert.match(html, /data-export-calculation[^>]*>Download…</);
  assert.match(html, /Save result/);
  assert.match(html, /Export/);
  assert.match(html, /Reopening never recalculates or regenerates the saved result/i);
});

test('completed calculations make Export primary and Save result secondary', () => {
  const render = html.match(/function officekitRenderCalculationActions\(container, calculation\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(render);
  const exportPosition = render.indexOf('data-export-calculation');
  const savePosition = render.indexOf('data-save-calculation');
  // Approved order (mock sections 3 and 6, live results mock): Save result, then the primary Download… at the right.
  assert.ok(exportPosition >= 0 && savePosition >= 0 && savePosition < exportPosition, 'Save comes before the primary Export');
  assert.match(render, /data-export-calculation[^>]*class="[^"]*bg-indigo-600/);
  assert.match(render, /data-save-calculation[^>]*class="[^"]*border[^\"]*bg-white/);
});

test('result export request preserves immutable scalar inputs, result fields and complete schedule rows', async () => {
  let request;
  const context = loadClient(async (url, options) => {
    request = { url, options };
    return { ok: true, status: 200, headers: { get: () => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, blob: async () => new Blob(['report']) };
  });
  const snapshot = {
    id: '00000000-0000-4000-8000-000000000001',
    toolId: 'calculator.loan-emi',
    title: 'April home loan',
    savedAt: '2026-10-06T12:00:00.000Z',
    inputs: { principal: 50000, annual_interest_rate: 7.5, tenure_years: 5 },
    result: {
      monthly_emi: 1001.9,
      total_interest: 10113.9,
      assumptions: { rounding: 'half_up', term_months: 60 },
      preview_schedule: [{ month: 1, payment: 1001.9, remaining_balance: 49310.6 }],
      schedule: [{ month: 1, payment: 1001.9, remaining_balance: 49310.6 }, { month: 2, payment: 1001.9, remaining_balance: 48554.79 }],
    },
  };

  const result = await context.officekitExportSavedResult(snapshot, 'xlsx', true);

  assert.equal(result.blob.size, 6);
  assert.equal(request.url, 'http://127.0.0.1:8000/api/export/result');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), {
    format: 'xlsx', tool_id: snapshot.toolId, title: snapshot.title,
    created_at: snapshot.savedAt, include_attribution: true,
    inputs: [
      { name: 'principal', value: 50000, unit: '$' },
      { name: 'annual_interest_rate', value: 7.5, unit: '%' },
      { name: 'tenure_years', value: 5, unit: 'years' },
    ],
    results: [
      { name: 'monthly_emi', value: 1001.9, unit: '$' },
      { name: 'total_interest', value: 10113.9, unit: '$' },
    ],
    assumptions: ['rounding: half_up', 'term_months: 60'],
    tables: [{
      title: 'schedule', columns: ['month', 'payment', 'remaining_balance'],
      rows: [[1, 1001.9, 49310.6], [2, 1001.9, 48554.79]],
    }],
  });
});

test('result export rejects unsupported formats, corrupt snapshots, oversized schedules and API failures', async () => {
  let calls = 0;
  const context = loadClient(async () => { calls += 1; return { ok: false, status: 422, json: async () => ({ detail: 'Invalid snapshot' }) }; });
  const valid = {
    id: '00000000-0000-4000-8000-000000000001', toolId: 'calculator.x', title: 'Result',
    savedAt: '2026-10-06T12:00:00.000Z', inputs: { amount: 12 }, result: { total: 13 },
  };

  await assert.rejects(context.officekitExportSavedResult(valid, 'exe', false), /format/i);
  await assert.rejects(context.officekitExportSavedResult({ ...valid, title: '' }, 'pdf', false), /invalid or incomplete/i);
  await assert.rejects(context.officekitExportSavedResult({
    ...valid, result: { schedule: Array.from({ length: 10_001 }, () => ({ month: 1 })) },
  }, 'pdf', false), /row or column limit/i);
  await assert.rejects(context.officekitExportSavedResult(valid, 'pdf', false), /Invalid snapshot/);
  assert.equal(calls, 1);
});

test('download names use standard Markdown and image extensions', async () => {
  const snapshot = {
    toolId: 'calculator.loan-emi', title: 'Loan', savedAt: '2026-10-06T12:00:00.000Z',
    inputs: { principal: 1200 }, result: { monthly_emi: 100 },
  };
  for (const [format, extension, mime] of [
    ['markdown', 'md', 'text/markdown'], ['jpeg', 'jpg', 'image/jpeg'],
    ['png', 'png', 'image/png'], ['pdf', 'pdf', 'application/pdf'],
  ]) {
    const context = loadClient(async () => ({
      ok: true, headers: { get: () => mime }, blob: async () => new Blob(['report']),
    }));
    const result = await context.officekitExportSavedResult(snapshot, format, true);
    assert.equal(result.fileName, `calculator.loan-emi-result.${extension}`);
  }
});

test('result export rejects wrong MIME and empty files and caps serialized request bytes before fetch', async () => {
  let calls = 0;
  const context = loadClient(async () => {
    calls += 1;
    return { ok: true, headers: { get: () => 'application/json' }, blob: async () => new Blob(['unexpected']) };
  });
  const valid = {
    id: '00000000-0000-4000-8000-000000000001', toolId: 'calculator.x', title: 'Result',
    savedAt: '2026-10-06T12:00:00.000Z', inputs: { amount: 12 }, result: { total: 13 },
  };
  await assert.rejects(context.officekitExportSavedResult(valid, 'pdf', false), /unexpected format/i);
  const emptyContext = loadClient(async () => ({ ok: true, headers: { get: () => 'application/pdf' }, blob: async () => new Blob([]) }));
  await assert.rejects(emptyContext.officekitExportSavedResult(valid, 'pdf', false), /empty/i);

  const oversized = { ...valid, result: Object.fromEntries(Array.from({ length: 220 }, (_, index) => [`field-${index}`, 'x'.repeat(10_000)])) };
  await assert.rejects(context.officekitExportSavedResult(oversized, 'pdf', false), /2 MiB/i);
  assert.equal(calls, 1, 'oversized result data is rejected before making another request');
});

test('calculator render and History wiring keep reopen read-only and expose save/export actions', () => {
  assert.match(html, /function officekitRenderCalculationActions/);
  assert.match(html, /function renderSavedResults/);
  assert.match(html, /function openSavedResult/);
  assert.match(html, /function reuseSavedResultInputs/);
  assert.match(html, /officekitRecordStore\.saveResultSnapshot/);
  assert.match(html, /officekitRecordStore\.deleteSavedResult/);
  assert.match(html, /Saved calculator snapshots and meeting notes stay only in this device's local storage/);
  assert.match(html, /Save to History/);
  assert.match(html, /officekitDownloadSavedMeetingNotes/);
  assert.match(html, /no separate transcript field/);
  assert.match(html, /officekitResultExportReturnFocus\?\.focus/);
  assert.match(html, /document\.activeElement === first/);
  assert.match(html, /closeResultExport\(\);/);
  for (const toolId of [
    'calculator.loan-emi', 'calculator.compound-interest',
    'calculator.vat-sales-tax', 'calculator.freelance-rate',
  ]) assert.ok(html.includes(`toolId: '${toolId}'`), `${toolId} result is wired to the common snapshot flow`);
  for (const label of ['Open result', 'Export original', 'Reuse inputs', 'Delete saved result']) {
    assert.ok(html.includes(label), `${label} is available from History`);
  }
});
