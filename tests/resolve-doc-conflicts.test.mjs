import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { bumpLike, renumberHistoryRow, renumberVersionLine, resolveRepo, resolveText } from '../scripts/resolve-doc-conflicts.mjs';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'resolve-doc-conflicts.mjs');
const hunk = (main, branch, base) => `<<<<<<< HEAD\n${main}${base === undefined ? '' : `||||||| base\n${base}`}=======\n${branch}>>>>>>> abc123 (feat: branch)\n`;

test('bumpLike repeats the kind of bump the branch made on top of main', () => {
  assert.deepEqual(bumpLike([1, 90, 9], [1, 90, 4], [1, 90, 5]), [1, 90, 10]);
  assert.deepEqual(bumpLike([1, 14, 1], [1, 13, 0], [1, 14, 0]), [1, 15, 0]);
  assert.deepEqual(bumpLike([2, 3, 4], [1, 0, 0], [2, 0, 0]), [3, 0, 0]);
  assert.deepEqual(bumpLike([1, 0, 9], [1, 0, 8], [1, 0, 8]), [1, 0, 10]);
});

test('a version line is renumbered after main and chains main as the first Earlier entry', () => {
  const main = 'Version: 1.0.209 · 2026-10-23 · Add S06. Earlier: 1.0.208 · Add F11.';
  const branch = 'Version: 1.0.209 · 2026-10-23 · Add D99. Earlier: 1.0.208 · Add F11.';
  const result = renumberVersionLine(main, branch);
  assert.equal(result.line, 'Version: 1.0.210 · 2026-10-23 · Add D99. Earlier: 1.0.209 · 2026-10-23 · Add S06. Earlier: 1.0.208 · Add F11.');
  assert.deepEqual(result.mapping, { from: '1.0.209', to: '1.0.210', main: '1.0.209' });
});

test('the bold contract version prefix is kept', () => {
  const result = renumberVersionLine('**Version:** 1.90.9 · Main. Earlier: 1.90.8 · Old.', '**Version:** 1.91.0 · Branch. Earlier: 1.90.8 · Old.');
  assert.equal(result.line, '**Version:** 1.91.0 · Branch. Earlier: 1.90.9 · Main. Earlier: 1.90.8 · Old.');
});

test('a version line is left unless the branch made one bump from an entry main also has', () => {
  assert.equal(renumberVersionLine('Version: 1.2.3 · Main.', 'Version: 1.2.3 · Branch.'), null);
  const main = 'Version: 1.90.4 · Sibling. Earlier: 1.90.3 · Base.';
  assert.equal(renumberVersionLine(main, 'Version: 1.90.5 · Second. Earlier: 1.90.4 · First. Earlier: 1.90.3 · Base.'), null);
  assert.equal(renumberVersionLine(main, 'Version: 1.90.4 · Only. Earlier: 1.90.3 · Base.').line, 'Version: 1.90.5 · Only. Earlier: 1.90.4 · Sibling. Earlier: 1.90.3 · Base.');
});

test('lines that are not version lines are not renumbered', () => {
  assert.equal(renumberVersionLine('Total: 111 entries', 'Version: 1.0.0 · x.'), null);
  assert.equal(renumberVersionLine('Version: 1.0.0 · x.', 'Total: 112 entries'), null);
});

test('history rows take the renumbered pair only for the file and version that moved', () => {
  const mappings = new Map([['API-CONTRACT.md', { from: '1.90.10', to: '1.90.11', main: '1.90.10' }]]);
  const row = '| 2026-10-24 | docs/TOOL-GUIDE.md, API-CONTRACT.md | 1.198.143 → 1.198.144 / 1.90.9 → 1.90.10 | D99. |';
  assert.equal(renumberHistoryRow(row, mappings), '| 2026-10-24 | docs/TOOL-GUIDE.md, API-CONTRACT.md | 1.198.143 → 1.198.144 / 1.90.10 → 1.90.11 | D99. |');
  assert.equal(renumberHistoryRow('| 2026-10-24 | API-CONTRACT.md | 1.90.8 → 1.90.9 | old. |', mappings), '| 2026-10-24 | API-CONTRACT.md | 1.90.8 → 1.90.9 | old. |');
  assert.equal(renumberHistoryRow('| a | b |', mappings), '| a | b |');
  assert.equal(renumberHistoryRow('| d | API-CONTRACT.md, x.md | 1.90.9 → 1.90.10 | r |', mappings), '| d | API-CONTRACT.md, x.md | 1.90.9 → 1.90.10 | r |');
  assert.equal(renumberHistoryRow('| d | API-CONTRACT.md | new | r |', mappings), '| d | API-CONTRACT.md | new | r |');
});

test('table-row hunks keep both sides, main first outside the history file', () => {
  const text = `# Guide\n${hunk('| s06 | main |\n', '| d99 | branch |\n')}end\n`;
  const result = resolveText(text, 'docs/TOOL-GUIDE.md');
  assert.equal(result.text, '# Guide\n| s06 | main |\n| d99 | branch |\nend\n');
  assert.deepEqual([result.resolved, result.left], [1, 0]);
});

test('history hunks put the branch rows on top, renumbered from versions resolved earlier', () => {
  const mappings = new Map();
  resolveText(hunk('Version: 1.90.10 · Main. Earlier: 1.90.9 · Old.\n', 'Version: 1.90.10 · Branch. Earlier: 1.90.9 · Old.\n'), 'API-CONTRACT.md', mappings);
  const history = `# Version history\n\n${hunk('| 2026-10-23 | API-CONTRACT.md | 1.90.9 → 1.90.10 | main. |\n', '| 2026-10-24 | API-CONTRACT.md | 1.90.9 → 1.90.10 | branch. |\n', '')}| older |\n`;
  const result = resolveText(history, 'docs/VERSION-HISTORY.md', mappings);
  assert.equal(result.text, '# Version history\n\n| 2026-10-24 | API-CONTRACT.md | 1.90.10 → 1.90.11 | branch. |\n| 2026-10-23 | API-CONTRACT.md | 1.90.9 → 1.90.10 | main. |\n| older |\n');
});

test('a version line left for a person also leaves the history rows that name its file', () => {
  const mappings = new Map();
  const squash = resolveText(hunk('Version: 1.90.4 · Sibling. Earlier: 1.90.3 · Base.\n', 'Version: 1.90.5 · Second. Earlier: 1.90.4 · First. Earlier: 1.90.3 · Base.\n'), 'API-CONTRACT.md', mappings);
  assert.deepEqual([squash.resolved, squash.left], [0, 1]);
  const rows = hunk('| d | API-CONTRACT.md | 1.90.3 → 1.90.4 | sibling. |\n', '| d | docs/X.md, API-CONTRACT.md | 1.0.0 → 1.0.1 / 1.90.4 → 1.90.5 | second. |\n');
  assert.equal(resolveText(rows, 'docs/VERSION-HISTORY.md', mappings).text, rows);
  assert.equal(renumberHistoryRow('| d | API-CONTRACT.md | 1.90.4 → 1.90.5 | r |', mappings), '| d | API-CONTRACT.md | 1.90.4 → 1.90.5 | r |');
  const other = hunk('| d | docs/Y.md | 1.0.0 → 1.0.1 | main. |\n', '| d | docs/Z.md | 2.0.0 → 2.0.1 | branch. |\n');
  assert.equal(resolveText(other, 'docs/VERSION-HISTORY.md', mappings).text, '| d | docs/Z.md | 2.0.0 → 2.0.1 | branch. |\n| d | docs/Y.md | 1.0.0 → 1.0.1 | main. |\n');
  assert.equal(resolveText(hunk('| a |\n', '| b | c |\n'), 'docs/VERSION-HISTORY.md', mappings).text, '| b | c |\n| a |\n');
});

test('pitfall entries with different IDs are both kept, and colliding IDs are left', () => {
  const main = '### P-254 — main pitfall\n\nBody.\n';
  const branch = '### P-255 — branch pitfall\n\nBody.\n';
  assert.equal(resolveText(hunk(main, branch), 'docs/PITFALLS.md').text, `${main}\n${branch}`);
  assert.equal(resolveText(hunk(`${main}\n`, branch), 'docs/PITFALLS.md').text, `${main}\n${branch}`);
  const clash = resolveText(hunk(main, '### P-254 — other\n'), 'docs/PITFALLS.md');
  assert.deepEqual([clash.resolved, clash.left], [0, 1]);
});

test('a hunk holding a version line and rows is resolved region by region, or not at all', () => {
  const mappings = new Map();
  const result = resolveText(hunk('Version: 1.0.1 · a. Earlier: 1.0.0 · s.\n\n| h |\n| main |\n', 'Version: 1.0.1 · b. Earlier: 1.0.0 · s.\n\n| h |\n| branch |\n'), 'docs/TOOL-GUIDE.md', mappings);
  assert.equal(result.text, 'Version: 1.0.2 · b. Earlier: 1.0.1 · a. Earlier: 1.0.0 · s.\n\n| h |\n| main |\n| branch |\n');
  assert.deepEqual(mappings.get('docs/TOOL-GUIDE.md'), { from: '1.0.1', to: '1.0.2', main: '1.0.1' });
  const untouched = new Map();
  resolveText(hunk('Version: 1.0.1 · a.\nMain prose.\n', 'Version: 1.0.1 · b.\nBranch prose.\n'), 'docs/TOOL-GUIDE.md', untouched);
  assert.equal(untouched.size, 0);
});

test('rows on one side only are kept when the base shows they were added, and left otherwise', () => {
  const added = resolveText(hunk('| a |\n', '| a |\n| new |\n', '| a |\n'), 'docs/TOOL-GUIDE.md');
  assert.equal(added.text, '| a |\n| new |\n');
  const mainAdded = resolveText(hunk('| a |\n| main |\n', '| a |\n', '| a |\n'), 'docs/TOOL-GUIDE.md');
  assert.equal(mainAdded.text, '| a |\n| main |\n');
  const deletedOnMain = hunk('| a |\n', '| a |\n| gone |\n', '| a |\n| gone |\n');
  assert.equal(resolveText(deletedOnMain, 'docs/TOOL-GUIDE.md').text, deletedOnMain);
});

test('prose, generated counts and mixed hunks keep their markers', () => {
  for (const [main, branch] of [
    ['Total: 111 search entries\n', 'Total: 112 search entries\n'],
    ['| row |\nSome prose.\n', '| row |\n'],
    ['', '| row |\n'],
    ['Version: 1.0.1 · a.\nMain prose.\n', 'Version: 1.0.1 · b.\nBranch prose.\n'],
  ]) {
    const text = hunk(main, branch);
    const result = resolveText(text, 'docs/TOOL-GUIDE.md');
    assert.equal(result.text, text);
    assert.deepEqual([result.resolved, result.left], [0, 1]);
  }
});

function repoWithConflict() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ok-doc-conflicts-'));
  const run = (...args) => execFileSync('git', args, { cwd: dir, encoding: 'utf8' });
  const write = (file, text) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), text);
  };
  run('init', '-q', '-b', 'main');
  run('config', 'user.email', 'test@example.com');
  run('config', 'user.name', 'Test');
  const guide = (version, summary, rows) => `# Guide\n\nVersion: ${version} · ${summary} Earlier: 1.0.0 · Start.\n\n| id | state |\n${rows}`;
  const history = (rows) => `# Version history\n\n| Date | File | Version | Reason |\n|---|---|---|---|\n${rows}| 2026-10-01 | docs/GUIDE.md | 0.9.0 → 1.0.0 | Start. |\n`;
  write('docs/GUIDE.md', guide('1.0.0', 'Start.', '').replace(' Earlier: 1.0.0 · Start.', ''));
  write('docs/VERSION-HISTORY.md', history(''));
  write('app.js', 'main\n');
  run('add', '.');
  run('commit', '-q', '-m', 'base');
  run('checkout', '-q', '-b', 'feature');
  write('docs/GUIDE.md', guide('1.0.1', 'Add D99.', '| d99 | branch |\n'));
  write('docs/VERSION-HISTORY.md', history('| 2026-10-24 | docs/GUIDE.md | 1.0.0 → 1.0.1 | D99 row. |\n'));
  run('commit', '-q', '-am', 'feat: d99');
  run('checkout', '-q', 'main');
  write('docs/GUIDE.md', guide('1.0.1', 'Add S06.', '| s06 | main |\n'));
  write('docs/VERSION-HISTORY.md', history('| 2026-10-23 | docs/GUIDE.md | 1.0.0 → 1.0.1 | S06 row. |\n'));
  run('commit', '-q', '-am', 'feat: s06');
  run('checkout', '-q', 'feature');
  return { dir, run, write };
}

test('a real rebase conflict on a version line, rows and history is resolved and staged', () => {
  const { dir, run } = repoWithConflict();
  assert.notEqual(spawnSync('git', ['rebase', 'main'], { cwd: dir, encoding: 'utf8' }).status, 0);
  const { report, mappings } = resolveRepo(dir);
  assert.deepEqual(report.map(({ file, status }) => [file, status]), [['docs/GUIDE.md', 'resolved'], ['docs/VERSION-HISTORY.md', 'resolved']]);
  assert.deepEqual(mappings.get('docs/GUIDE.md'), { from: '1.0.1', to: '1.0.2', main: '1.0.1' });
  assert.equal(run('diff', '--name-only', '--diff-filter=U'), '');
  const guide = fs.readFileSync(path.join(dir, 'docs/GUIDE.md'), 'utf8');
  assert.match(guide, /^Version: 1\.0\.2 · Add D99\. Earlier: 1\.0\.1 · Add S06\. Earlier: 1\.0\.0 · Start\.$/m);
  assert.match(guide, /\| s06 \| main \|\n\| d99 \| branch \|/);
  const history = fs.readFileSync(path.join(dir, 'docs/VERSION-HISTORY.md'), 'utf8');
  assert.match(history, /\| 2026-10-24 \| docs\/GUIDE\.md \| 1\.0\.1 → 1\.0\.2 \| D99 row\. \|\n\| 2026-10-23 \| docs\/GUIDE\.md \| 1\.0\.0 → 1\.0\.1 \| S06 row\. \|/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('the command leaves code conflicts and unresolvable doc hunks, and exits 1', () => {
  const { dir, run, write } = repoWithConflict();
  write('app.js', 'branch\n');
  write('docs/NOTES.md', 'Total: 2\n');
  write('docs/GUIDE.md', fs.readFileSync(path.join(dir, 'docs/GUIDE.md'), 'utf8').replace('Version: 1.0.1 · Add D99. Earlier: 1.0.0 · Start.', 'Version: 1.0.2 · Add D100. Earlier: 1.0.1 · Add D99. Earlier: 1.0.0 · Start.'));
  run('add', '.');
  run('commit', '-q', '-m', 'feat: branch code');
  run('checkout', '-q', 'main');
  write('app.js', 'main 2\n');
  write('docs/NOTES.md', 'Total: 3\n');
  run('add', '.');
  run('commit', '-q', '-m', 'feat: main code');
  run('checkout', '-q', 'feature');
  spawnSync('git', ['rebase', 'main'], { cwd: dir, encoding: 'utf8' });
  spawnSync(process.execPath, [script], { cwd: dir, encoding: 'utf8' });
  run('add', 'docs/GUIDE.md', 'docs/VERSION-HISTORY.md');
  spawnSync('git', ['-c', 'core.editor=true', 'rebase', '--continue'], { cwd: dir, encoding: 'utf8' });
  const second = spawnSync(process.execPath, [script], { cwd: dir, encoding: 'utf8' });
  assert.equal(second.status, 1);
  assert.match(second.stdout, /^LEFT app\.js: not a Markdown doc$/m);
  assert.match(second.stdout, /^LEFT docs\/NOTES\.md: 0 hunk\(s\) resolved, 1 left$/m);
  assert.match(second.stdout, /Resolve the files marked LEFT by hand/);
  assert.match(second.stdout, /docs\/GUIDE\.md: version line left \(several bumps, or no shared Earlier entry\)/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('the command reports a clean tree and a fully resolved rebase', () => {
  const { dir } = repoWithConflict();
  const clean = spawnSync(process.execPath, [script], { cwd: dir, encoding: 'utf8' });
  assert.equal(clean.status, 0);
  assert.equal(clean.stdout, 'no conflicted files\n');
  spawnSync('git', ['rebase', 'main'], { cwd: dir, encoding: 'utf8' });
  const resolved = spawnSync(process.execPath, [script], { cwd: dir, encoding: 'utf8' });
  assert.equal(resolved.status, 0);
  assert.match(resolved.stdout, /^ok {3}docs\/GUIDE\.md: 2 hunk\(s\) resolved, 0 left$/m);
  assert.match(resolved.stdout, /docs\/GUIDE\.md: renumbered to 1\.0\.2 after main's 1\.0\.1/);
  assert.match(resolved.stdout, /git rebase --continue/);
  fs.rmSync(dir, { recursive: true, force: true });
});
