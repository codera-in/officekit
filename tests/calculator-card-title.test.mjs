import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const html = fs.readFileSync('index.html', 'utf8');
const switchCalc = html.match(/function switchCalc\(calc\) \{([\s\S]*?)\n        \}/)?.[1];

test('calculator screens use the shared dock for Calculate and result actions', () => {
  const toolActions = fs.readFileSync('assets/officekit-tool-actions.js', 'utf8');
  assert.match(toolActions, /if \(active && !browsing\.has\(active\.id\)\) \{/, 'the shared dock serves every tool screen');
  assert.doesNotMatch(toolActions, /tab-calculators/, 'the shared dock does not skip the calculators tab');
});

test('calculator card fills the work area on the calculators tab', () => {
  const css = fs.readFileSync('assets/officekit.input.css', 'utf8');
  assert.match(css, /#tab-calculators:not\(\.hidden\) > \.calc-card \{[^}]*flex: 1 1 auto/, 'the card grows to the bottom of the work area');
  assert.match(html, /<div class="calc-card w-full /, 'the card carries the calc-card hook');
});

test('calculator card heading follows the selected calculator instead of staying on Loan & EMI', () => {
  assert.ok(switchCalc, 'switchCalc exists');
  assert.match(html, /<h2 id="calc-card-title"/, 'the card heading has an id');
  assert.match(switchCalc, /document\.getElementById\('calc-card-title'\)\.textContent = title;/, 'switchCalc sets the card heading from the catalogue title');
});
