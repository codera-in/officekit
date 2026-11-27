import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../assets/officekit.input.css', import.meta.url), 'utf8');
const navSource = readFileSync(new URL('../assets/officekit-section-nav.js', import.meta.url), 'utf8');

function voiceNav() {
  const start = html.indexOf('<nav class="officekit-section-nav"');
  assert.notEqual(start, -1, 'the Voice transcription section list exists');
  return html.slice(start, html.indexOf('</nav>', start) + '</nav>'.length);
}

test('the Voice transcription section list has one link per section, in screen order', () => {
  const nav = voiceNav();
  const targets = [...nav.matchAll(/href="#([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(targets, [
    'dictation-ready-heading',
    'dictation-smart-heading',
    'speech-coach-notes-heading',
    'transcript-heading',
    'dictation-history-heading',
  ]);
});

test('every section link points at an element that exists on the page', () => {
  const nav = voiceNav();
  for (const [, id] of nav.matchAll(/href="#([^"]+)"/g)) {
    assert.match(html, new RegExp(`id="${id}"`), `#${id} exists`);
  }
});

test('the section list is limited to the Voice view and is marked for the scroll-spy script', () => {
  const nav = voiceNav();
  assert.match(nav, /data-section-nav/);
  assert.match(nav, /data-audio-view="voice"/);
  assert.match(nav, /aria-current="true"/);
});

test('the section list is a left column on wide screens and a row on phones', () => {
  assert.match(css, /\.officekit-section-layout \{ display: grid;/);
  assert.match(css, /@media \(min-width: 1024px\) \{[\s\S]*?grid-template-columns: 13rem/);
  assert.match(css, /\.officekit-section-nav \{ display: flex; flex-direction: row; flex-wrap: wrap;/);
});

test('the section list script moves focus to the target heading and marks the current section', () => {
  assert.match(navSource, /event\.preventDefault\(\)/);
  assert.match(navSource, /aria-current/);
  assert.match(navSource, /matches\('h1, h2, h3'\)/);
});

test('the outcome helper is loaded before the Ergonomics module that uses it', () => {
  const outcomeAt = html.indexOf('officekit-outcome.js');
  const ergonomicsAt = html.indexOf('officekit-ergonomics.js');
  assert.notEqual(outcomeAt, -1);
  assert.ok(outcomeAt < ergonomicsAt, 'outcome helper loads first');
});
