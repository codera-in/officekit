import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { loadToolCatalog } from '../scripts/tool-catalog.mjs';
import { applyCountRows, main as toolCounts, renderCountRows } from '../scripts/tool-counts.mjs';

const root = new URL('../', import.meta.url);
const toolGuide = readFileSync(new URL('docs/TOOL-GUIDE.md', root), 'utf8');
const releasePlan = readFileSync(new URL('docs/RELEASE-123-TOOLS.md', root), 'utf8');

test('tool guide exposure totals match its numbered family rows and release audit', () => {
  const familyRows = [...toolGuide.matchAll(/^\|\s*(\d+)\s*\|([^\n]+)$/gm)];
  const familyIds = familyRows.map((match) => Number(match[1])).sort((left, right) => left - right);

  assert.equal(familyRows.length, 53);
  assert.deepEqual(familyIds, Array.from({ length: 53 }, (_, index) => index + 1));

  const exposure = familyRows.map((match) => {
    const cells = match[2].split('|').map((cell) => cell.trim());
    const [api, ui] = cells[1].split('/').map((value) => value.trim());
    return { api, ui, depth: cells[2] };
  });
  const hasApi = ({ api }) => api === 'Yes';
  const hasUi = ({ ui }) => ui === 'Yes';
  const apiCount = exposure.filter(hasApi).length;
  const uiCount = exposure.filter(hasUi).length;
  const engineOnly = exposure.filter((row) => !hasApi(row) && !hasUi(row)).length;
  const apiWithoutUi = exposure.filter((row) => hasApi(row) && !hasUi(row)).length;
  const uiOnly = exposure.filter((row) => !hasApi(row) && hasUi(row)).length;
  const d2Count = exposure.filter(({ depth }) => depth === 'D2').length;
  const d1Count = exposure.filter(({ depth }) => depth === 'D1').length;

  assert.deepEqual(
    { apiCount, uiCount, engineOnly, apiWithoutUi, uiOnly, d2Count, d1Count },
    { apiCount: 53, uiCount: 53, engineOnly: 0, apiWithoutUi: 0, uiOnly: 0, d2Count: 51, d1Count: 2 },
  );
  assert.match(toolGuide, /\| Distinct tool families found in code \| \*\*58\*\*/);
  assert.match(toolGuide, /\| Families with backend or native wiring \| \*\*58\*\*/);
  assert.match(toolGuide, /\| Families with UI interaction wiring \| \*\*58\*\*/);
  assert.match(toolGuide, /\| API-wired families without UI \| \*\*0\*\*/);
  assert.equal(applyCountRows(toolGuide, loadToolCatalog()), toolGuide, 'run node scripts/tool-counts.mjs to refresh generated counts');
  assert.match(releasePlan, /53 tool families in code, 49 catalogue entries, 53 API-wired families and 53 UI-wired families/);
  assert.ok(toolGuide.includes('| 35 | Resource overview (`system_resources`, release matrix N02) | Yes / Yes | D2 |'));
  assert.ok(toolGuide.includes('| 47 | System information (`system_info`, release matrix N01) | Yes / Yes | D2 |'));
  assert.ok(toolGuide.includes('| 52 | PDF selectable-text extraction (`pdf_text_extract`) | Yes / Yes | D2 |'));
  assert.match(toolGuide, /^\| 11 \| Resize image \(`image_resize`\) \| Yes \/ Yes \| D2 \|/m);
  assert.match(toolGuide, /^\| 12 \| Remove EXIF\/GPS \(`image_exif_strip`\) \| Yes \/ Yes \| D2 \|/m);
  assert.match(toolGuide, /^\| 21 \| Scientific expression evaluator \(`math_eval`\) \| Yes \/ Yes \| D2 \|/m);
  assert.match(toolGuide, /^\| 22 \| Unit converter \(`units_convert`\) \| Yes \/ Yes \| D2 \|/m);
  assert.match(toolGuide, /^\| 29 \| URL encode\/decode \(`url_codec`\) \| Yes \/ Yes \| D2 \|/m);
  for (const id of ['margin_markup', 'break_even', 'depreciation', 'simple_interest', 'everyday_percentages']) {
    const row = toolGuide.split('\n').find(line => line.includes(`\`${id}\``));
    assert.ok(row, `${id} has an audit row`);
    assert.match(row, /Yes \/ Yes/);
  }
  for (const row of ['Delete PDF pages (`pdf_delete_pages`)', 'Reorder PDF pages (`pdf_reorder_pages`)', 'File split/join (`file_split_join`,', 'Folder comparison (`folder_compare`,', 'Password & passphrase generator (`password_generator`)', 'Similar image finder (`similar_images`)', 'Color conversion (`color_converter`,']) {
    assert.ok(toolGuide.includes(row), `tool guide includes ${row}`);
  }
  assert.match(toolGuide, /^\| 51 \| PDF selectable-table export \(`pdf_table_extractor`\) \| Yes \/ Yes \| D2 \|/m);
});

test('the grouped PDF split audit matches the implemented named ZIP workbench', () => {
  const splitRow = toolGuide.split('\n').find((line) => line.startsWith('| 5 | Split/extract PDF'));
  assert.ok(splitRow);
  assert.match(splitRow, /PDF workbench validates group counts\/names\/ranges/);
  assert.match(splitRow, /downloads verified PDFs in a ZIP/);
  assert.doesNotMatch(splitRow, /screen currently exposes only one selected-page output/);
});

test('generated tool counts follow the live catalogue and detect stale rows', () => {
  const catalogue = { tools: [{ id: 'a' }, { id: 'b' }, { id: 'c' }], slices: { calculators: ['b'], image: ['c'] } };
  const [catalogueRow, pendingRow] = renderCountRows(catalogue);
  assert.match(catalogueRow, /^\| Search catalogue entries \| \*\*3\*\* \|/);
  assert.match(pendingRow, /^\| Pending-tool slice entries \| \*\*2\*\* \| Development-only; calculators 1, developer 0, files 0, image 1, pdf tools 0, invoices 0;/);

  const withoutPendingRow = '| Measure | Count |\n| Search catalogue entries | **1** | old |\n| Other | **0** |';
  const refreshed = applyCountRows(withoutPendingRow, catalogue);
  assert.equal(refreshed, ['| Measure | Count |', catalogueRow, pendingRow, '| Other | **0** |'].join('\n'));
  assert.equal(applyCountRows(refreshed, catalogue), refreshed);
  assert.throws(() => applyCountRows('| Other | **0** |', catalogue), /missing the "Search catalogue entries" row/);

  const writes = [];
  const errors = [];
  const io = { catalogue, read: () => withoutPendingRow, write: (_, text) => writes.push(text), log: { error: message => errors.push(message) } };
  assert.equal(toolCounts(['--check'], io), 1);
  assert.match(errors[0], /stale/);
  assert.equal(writes.length, 0);
  assert.equal(toolCounts([], io), 0);
  assert.deepEqual(writes, [refreshed]);
  assert.equal(toolCounts(['--check'], { ...io, read: () => refreshed }), 0);
  assert.equal(toolCounts([], { ...io, read: () => refreshed }), 0);
  assert.equal(writes.length, 1);
});
