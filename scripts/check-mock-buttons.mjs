import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// AGENTS.md "Button Limit": no screen shows more than 3 buttons. In a mock, each
// screen is a `frame` or `v2-frame` div (desktop, compact and phone variants); a
// button is any `btn`-class element. Text links (`link`, `ok-text-link`), list-row
// actions (`row-act`, unclassed icon buttons such as a row's ×), tabs
// (`role="tab"`), segmented toggles (`aria-pressed`, owner 2026-10-23: "Not
// counted") and tool-list entries (`tl`) are not counted. A frame holding a
// `native` dialog is outside the page and is skipped, as is a `data-clone` frame
// copied from another at load time. Every frame states its count
// as "Buttons: N" (or "N/3"); a Before frame showing today's screen over the limit
// says "Buttons: N (over)" and is exempt from the limit, not from the count.
export const BUTTON_LIMIT = 3;

const FRAME_START = /<div class="(?:v2-)?frame(?:\s[^"]*)?"/g;
const OPEN_TAG = /<([a-z][a-z0-9]*)\b([^>]*)>/g;
// The same exclusions as the UI tests' UNCOUNTED_BUTTON_CLASSES, plus the mock-only names.
const NOT_COUNTED = new Set(['ok-text-link', 'ok-segment', 'ok-row-action', 'link', 'row-act', 'tl']);

function classes(attributes) {
  return (/\bclass="([^"]*)"/.exec(attributes)?.[1] ?? '').split(/\s+/).filter(Boolean);
}

export function countButtons(frame) {
  let count = 0;
  for (const [, tag, attributes] of frame.matchAll(OPEN_TAG)) {
    const list = classes(attributes);
    if (!list.includes('btn')) continue;
    if (list.some((name) => NOT_COUNTED.has(name)) || /\b(?:role="tab"|aria-pressed=)/.test(attributes)) continue;
    count += 1;
  }
  return count;
}
const COUNT_NOTE = /class="count"/;
const DECLARED = /Buttons:\s*(\d+)(?:\s*\/\s*(\d+))?([^<]*)/;
const LABEL = /class="(?:mock-label|cap|v2-cap)[^"]*"[^>]*>([^<]*)</;
const HEADING = /<h1[^>]*>([^<]*)</;

export function frames(html) {
  const starts = [...html.matchAll(FRAME_START)].map((match) => match.index);
  return starts.map((start, index) => html.slice(start, starts[index + 1] ?? html.length));
}

function frameName(frame, index) {
  const label = LABEL.exec(frame)?.[1]?.trim();
  const heading = HEADING.exec(frame)?.[1]?.trim();
  return [`frame ${index + 1}`, label, heading].filter(Boolean).join(' · ');
}

export function checkMock(html, limit = BUTTON_LIMIT) {
  const problems = [];
  const all = frames(html);
  if (all.length === 0) problems.push('no <div class="frame"> screens found');
  all.forEach((frame, index) => {
    if (frame.includes('class="native"')) return;
    // A compact frame filled at load time from a desktop frame repeats that frame's count.
    if (/^<div class="[^"]*"\s+data-clone=/.test(frame)) return;
    const name = frameName(frame, index);
    const counted = countButtons(frame);
    const declared = DECLARED.exec(frame);
    if (!declared) {
      if (!COUNT_NOTE.test(frame)) problems.push(`${name}: no "Buttons: N/${limit}" count line`);
      else if (counted > 0) problems.push(`${name}: ${counted} buttons but the count line gives no number`);
      if (counted > limit) problems.push(`${name}: ${counted} buttons, limit ${limit}`);
      return;
    }
    const [, stated, statedLimit, note] = declared;
    if (Number(stated) !== counted) problems.push(`${name}: count line says ${stated}, mock has ${counted}`);
    if (statedLimit !== undefined && Number(statedLimit) !== limit) problems.push(`${name}: count line uses limit ${statedLimit}, limit is ${limit}`);
    if (counted > limit && !/\(over\)/.test(note)) problems.push(`${name}: ${counted} buttons, limit ${limit}`);
  });
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const files = process.argv.slice(2);
  if (files.length === 0) {
    process.stderr.write('usage: node scripts/check-mock-buttons.mjs <mock.html> [...]\n');
    process.exit(2);
  }
  for (const file of files) {
    const problems = checkMock(fs.readFileSync(file, 'utf8'));
    process.stdout.write(problems.length ? `FAIL ${file}\n${problems.map((p) => `  ${p}\n`).join('')}` : `ok   ${file}\n`);
    if (problems.length) process.exitCode = 1;
  }
}
