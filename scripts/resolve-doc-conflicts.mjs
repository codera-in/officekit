import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Resolves the doc conflicts parallel feature branches hit when rebasing onto main
// (VERSION-HISTORY rows, TOOL-GUIDE and contract rows, `Version:` lines, pitfalls).
// Run it while a rebase is stopped on a conflict. Only Markdown files are touched,
// and only three hunk shapes are resolved; every other hunk keeps its markers:
// - one `Version:` line per side: main's version is bumped the way the branch
//   bumped its own, and main's line becomes the first `Earlier:` entry;
// - table rows on both sides: both kept (branch rows first in VERSION-HISTORY,
//   which is newest first; after main's rows elsewhere), with the branch's history
//   pairs renumbered to the versions given above;
// - whole `### ` pitfall entries on both sides with different IDs: both kept.
// In a rebase, the HEAD side of a hunk is main and the other side is the branch.

const HUNK = /^<<<<<<< [^\n]*\n([\s\S]*?)(?:^\|\|\|\|\|\|\| [^\n]*\n([\s\S]*?))?^=======\n([\s\S]*?)^>>>>>>> [^\n]*\n/gm;
const VERSION_LINE = /^(\*\*Version:\*\*|Version:) (\d+)\.(\d+)\.(\d+) · (.*)$/;
const EARLIER = / Earlier: (\d+)\.(\d+)\.(\d+)\b/;
const HISTORY_FILE = 'docs/VERSION-HISTORY.md';

const lines = (side) => side.split('\n').slice(0, -1);
const isTableSide = (side) => lines(side).length > 0 && lines(side).every((line) => line.trim() === '' || line.startsWith('|'));
const pitfallIds = (side) => [...side.matchAll(/^### (P-\d+)\b/gm)].map((match) => match[1]);
const isPitfallSide = (side) => /^### P-\d+\b/.test(side) && pitfallIds(side).length > 0;

export function bumpLike(main, branchOld, branchNew) {
  const [major, minor, patch] = main;
  if (branchNew[0] !== branchOld[0]) return [major + 1, 0, 0];
  if (branchNew[1] !== branchOld[1]) return [major, minor + 1, 0];
  return [major, minor, patch + 1];
}

export function renumberVersionLine(mainLine, branchLine) {
  const main = VERSION_LINE.exec(mainLine);
  const branch = VERSION_LINE.exec(branchLine);
  if (!main || !branch) return null;
  const mainVersion = main.slice(2, 5).map(Number);
  const branchVersion = branch.slice(2, 5).map(Number);
  const branchRest = branch[5];
  const earlier = EARLIER.exec(branchRest);
  if (!earlier) return null;
  // The branch's previous entry, text and all, must be in main's line: then the branch
  // made exactly one bump from a version main also has. A squash of several bumps, or
  // a branch entry that only shares a number with main's, is left for a person.
  const afterEarlier = branchRest.slice(earlier.index + ' Earlier: '.length);
  const nextEarlier = afterEarlier.indexOf(' Earlier: ');
  const previousEntry = nextEarlier === -1 ? afterEarlier : afterEarlier.slice(0, nextEarlier);
  if (!mainLine.includes(previousEntry)) return null;
  const next = bumpLike(mainVersion, earlier.slice(1, 4).map(Number), branchVersion);
  const summary = branchRest.slice(0, earlier.index);
  const from = branchVersion.join('.');
  const to = next.join('.');
  return {
    line: `${main[1]} ${to} · ${summary} Earlier: ${mainVersion.join('.')} · ${main[5]}`,
    mapping: { from, to, main: mainVersion.join('.') },
  };
}

const PENDING = Symbol('left for a person');

function rowFiles(row) {
  const cells = row.split('|');
  return cells.length < 5 ? [] : cells[2].trim().split(/\s*[,/]\s*/);
}

export function renumberHistoryRow(row, mappings) {
  const cells = row.split('|');
  if (cells.length < 5) return row;
  const files = cells[2].trim().split(/,\s*/);
  const pairs = cells[3].trim().split(/\s*\/\s*/);
  if (files.length !== pairs.length) return row;
  let changed = false;
  const renumbered = pairs.map((pair, index) => {
    const mapping = mappings.get(files[index]);
    const match = /^(\S+) → (\S+)$/.exec(pair);
    if (!mapping || mapping === PENDING || !match || match[2] !== mapping.from) return pair;
    changed = true;
    return `${mapping.main} → ${mapping.to}`;
  });
  if (!changed) return row;
  cells[3] = ` ${renumbered.join(' / ')} `;
  return cells.join('|');
}

const joined = (list) => list.map((line) => `${line}\n`).join('');

// One changed region of a hunk: the lines main and the branch hold in place of each
// other. Rows on one side only are kept only when the base shows they were added;
// without a base they may be rows the other side deleted.
function resolveRegion(main, branch, file, mappings, base) {
  if (main.length === 1 && branch.length === 1 && VERSION_LINE.test(main[0]) && VERSION_LINE.test(branch[0])) {
    const renumbered = renumberVersionLine(main[0], branch[0]);
    // A version line left for a person also leaves that file's history rows to them.
    mappings.set(file, renumbered ? renumbered.mapping : PENDING);
    return renumbered ? `${renumbered.line}\n` : null;
  }
  const mainText = joined(main);
  const branchText = joined(branch);
  const added = (side) => base !== undefined && side.every((line) => !base.has(line));
  const bothTables = isTableSide(mainText) && isTableSide(branchText);
  const oneSided = (mainText === '' && isTableSide(branchText) && added(branch)) || (branchText === '' && isTableSide(mainText) && added(main));
  if (!bothTables && !oneSided) return null;
  if (file !== HISTORY_FILE) return mainText + branchText;
  const pending = [...mappings].filter(([, mapping]) => mapping === PENDING).map(([name]) => name);
  if (branch.some((row) => rowFiles(row).some((name) => pending.includes(name)))) return null;
  return branch.map((row) => `${renumberHistoryRow(row, mappings)}\n`).join('') + mainText;
}

function keepBothPitfalls(main, branch) {
  if (!isPitfallSide(main) || !isPitfallSide(branch)) return null;
  if (pitfallIds(branch).some((id) => pitfallIds(main).includes(id))) return null;
  return main.endsWith('\n\n') || branch.startsWith('\n') ? main + branch : `${main}\n${branch}`;
}

// Splits two sides into shared lines and changed regions (longest common subsequence).
export function regions(main, branch) {
  const table = Array.from({ length: main.length + 1 }, () => new Array(branch.length + 1).fill(0));
  for (let i = main.length - 1; i >= 0; i -= 1) {
    for (let j = branch.length - 1; j >= 0; j -= 1) {
      table[i][j] = main[i] === branch[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const parts = [];
  let change = null;
  const flush = () => { if (change) parts.push(change); change = null; };
  let i = 0;
  let j = 0;
  while (i < main.length || j < branch.length) {
    if (i < main.length && j < branch.length && main[i] === branch[j]) {
      flush();
      parts.push({ same: main[i] });
      i += 1;
      j += 1;
    } else {
      change ??= { main: [], branch: [] };
      if (j >= branch.length || (i < main.length && table[i + 1][j] >= table[i][j + 1])) change.main.push(main[i++]);
      else change.branch.push(branch[j++]);
    }
  }
  flush();
  return parts;
}

export function resolveText(text, file, mappings = new Map()) {
  let resolved = 0;
  let left = 0;
  const out = text.replace(HUNK, (hunk, main, baseText, branch) => {
    const pitfalls = keepBothPitfalls(main, branch);
    if (pitfalls !== null) {
      resolved += 1;
      return pitfalls;
    }
    const base = baseText === undefined ? undefined : new Set(lines(baseText));
    const trial = new Map(mappings);
    let body = '';
    for (const part of regions(lines(main), lines(branch))) {
      const piece = 'same' in part ? `${part.same}\n` : resolveRegion(part.main, part.branch, file, trial, base);
      if (piece === null) {
        for (const [key, value] of trial) if (value === PENDING) mappings.set(key, PENDING);
        left += 1;
        return hunk;
      }
      body += piece;
    }
    for (const [key, value] of trial) mappings.set(key, value);
    resolved += 1;
    return body;
  });
  return { text: out, resolved, left };
}

function git(cwd, args) {
  return execFileSync('git', args, { cwd, encoding: 'utf8' });
}

export function resolveRepo(cwd) {
  const conflicted = git(cwd, ['diff', '--name-only', '--diff-filter=U', '-z']).split('\0').filter(Boolean);
  // The history file is last, so its rows see every version renumbered in this pass.
  conflicted.sort((a, b) => Number(a === HISTORY_FILE) - Number(b === HISTORY_FILE));
  const mappings = new Map();
  const report = [];
  for (const file of conflicted) {
    if (path.extname(file) !== '.md') {
      report.push({ file, status: 'left', detail: 'not a Markdown doc' });
      continue;
    }
    // Rewrite the markers with the base section, so one-sided rows can be told apart.
    git(cwd, ['checkout', '--conflict=diff3', '--', file]);
    const full = path.join(cwd, file);
    const result = resolveText(fs.readFileSync(full, 'utf8'), file, mappings);
    fs.writeFileSync(full, result.text);
    if (result.left === 0) git(cwd, ['add', '--', file]);
    report.push({ file, status: result.left === 0 ? 'resolved' : 'left', detail: `${result.resolved} hunk(s) resolved, ${result.left} left` });
  }
  return { report, mappings };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const cwd = git(process.cwd(), ['rev-parse', '--show-toplevel']).trim();
  const { report, mappings } = resolveRepo(cwd);
  if (report.length === 0) process.stdout.write('no conflicted files\n');
  for (const { file, status, detail } of report) process.stdout.write(`${status === 'resolved' ? 'ok  ' : 'LEFT'} ${file}: ${detail}\n`);
  for (const [file, mapping] of mappings) {
    process.stdout.write(mapping === PENDING
      ? `     ${file}: version line left (several bumps, or no shared Earlier entry); renumber it and its history rows by hand\n`
      : `     ${file}: renumbered to ${mapping.to} after main's ${mapping.main}\n`);
  }
  if (report.some(({ status }) => status === 'left')) {
    process.stdout.write('Resolve the files marked LEFT by hand, then git add them.\n');
    process.exitCode = 1;
  } else if (report.length) {
    process.stdout.write('All conflicts resolved and staged. Review with git diff --cached, then git rebase --continue.\n');
  }
}
