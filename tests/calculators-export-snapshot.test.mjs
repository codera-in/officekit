// QA-11: the Download request for a work-hours result is built by the client builder in index.html, so this runs that
// builder (extracted from the shipped source, no DOM) rather than a Python copy of its output shape.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
const blockStart = html.indexOf('function officekitResultFieldUnit(');
const blockEnd = html.indexOf('async function officekitExportSavedResult(');
assert.ok(blockStart > 0 && blockEnd > blockStart, 'export builder block exists in index.html');
const { officekitBuildResultExportRequest: buildInVm } = vm.runInNewContext(
  `${html.slice(blockStart, blockEnd)}\n({ officekitBuildResultExportRequest });`,
  {},
);
// Objects built inside the vm context have another realm's prototypes; copy them before deep comparison.
const officekitBuildResultExportRequest = (...args) => JSON.parse(JSON.stringify(buildInVm(...args)));

// The saved work-hours result the Results dialog stores: the route response, with the same rows, weeks and assumptions.
function workHoursSnapshot() {
  return {
    toolId: 'work_hours',
    title: 'Work hours',
    createdAt: '2026-10-22T09:00:00+00:00',
    inputs: {},
    result: {
      total_minutes: 1200,
      total_hours: 20,
      rows: [
        { index: 1, worked_minutes: 480, overnight: false, dst_adjusted_minutes: 0 },
        { index: 2, worked_minutes: 480, overnight: true, dst_adjusted_minutes: 0 },
        { index: 3, worked_minutes: 240, overnight: false, dst_adjusted_minutes: 0 },
      ],
      weeks: [
        { iso_week: '2026-W10', total_minutes: 960 },
        { iso_week: '2026-W11', total_minutes: 240 },
      ],
      assumptions: { dst: 'not_applied', overnight: 'end_before_start' },
    },
  };
}

test('a work-hours Download request carries the rows and weeks tables with their columns and values, in order', () => {
  const body = officekitBuildResultExportRequest(workHoursSnapshot(), 'csv', false);
  assert.equal(body.format, 'csv');
  assert.equal(body.tool_id, 'work_hours');
  assert.equal(body.title, 'Work hours');
  assert.deepEqual(body.tables.map(table => table.title), ['rows', 'weeks']);
  assert.deepEqual(body.tables[0].columns, ['index', 'worked_minutes', 'overnight', 'dst_adjusted_minutes']);
  assert.deepEqual(body.tables[0].rows, [[1, 480, false, 0], [2, 480, true, 0], [3, 240, false, 0]]);
  assert.deepEqual(body.tables[1].columns, ['iso_week', 'total_minutes']);
  assert.deepEqual(body.tables[1].rows, [['2026-W10', 960], ['2026-W11', 240]]);
});

test('the totals stay in results and the assumptions stay in assumptions, with no table for them', () => {
  const body = officekitBuildResultExportRequest(workHoursSnapshot(), 'csv', true);
  assert.deepEqual(body.results.map(item => [item.name, item.value]), [['total_minutes', 1200], ['total_hours', 20]]);
  assert.deepEqual(body.assumptions, ['dst: not_applied', 'overnight: end_before_start']);
  assert.equal(body.include_attribution, true);
});

test('an invalid saved result is refused before any request body is built', () => {
  const snapshot = workHoursSnapshot();
  snapshot.title = '   ';
  assert.throws(() => officekitBuildResultExportRequest(snapshot, 'csv', false), /invalid or incomplete/);
  assert.throws(() => officekitBuildResultExportRequest(workHoursSnapshot(), 'exe', false), /supported export format/);
});
