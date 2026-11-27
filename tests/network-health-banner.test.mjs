import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const drawers = fs.readFileSync(path.join(root, 'src-tauri/macos-drawers.swift'), 'utf8');
const workspace = fs.readFileSync(path.join(root, 'assets/officekit-workspace.js'), 'utf8');

test('the network check result is a left-aligned tinted banner, not a centred block', () => {
  const view = drawers.match(/private func networkHealthView\(_ health: MenuDrawerHealth\?\) -> NSView \{[\s\S]*?\n    \}\n/)?.[0] || '';
  assert.match(view, /card\.alignment = \.leading/, 'the card no longer centres its children');
  assert.match(view, /DrawerBannerView\(\s*tint: drawerColor\(health\?\.tone\)/, 'the result is one banner tinted by its tone');
  assert.match(view, /time: health\?\.checked \?\? ""/, 'the check time is passed to the banner');
  assert.doesNotMatch(view, /"Checked \\\(health\.checked\)"/, 'no separate centred "Checked" line');
});

test('the banner spans the row width with a rounded tinted fill, the time beside the headline, and updates in place', () => {
  const banner = drawers.match(/private final class DrawerBannerView: NSStackView, DrawerAdoptable \{[\s\S]*?\n\}\n/)?.[0] || '';
  assert.ok(banner, 'DrawerBannerView exists');
  assert.match(banner, /widthAnchor\.constraint\(equalToConstant: drawerContentWidth\)/, 'as wide as the rows');
  assert.match(banner, /alignment = \.leading/);
  assert.match(banner, /NSStackView\(views: \[dot, headline, time\]\)/, 'dot, headline and time share one line');
  assert.match(banner, /withAlphaComponent\(0\.12\)\.setFill\(\)/, 'soft tint fill');
  assert.match(banner, /withAlphaComponent\(0\.35\)\.setStroke\(\)/, 'matching soft outline');
  assert.match(banner, /func adopt\(_ other: NSView\) -> Bool \{\s*guard let next = other as\? DrawerBannerView/, 'a routine refresh updates it in place');
});

test('the check time is hours and minutes', () => {
  assert.match(workspace, /checked: new Date\(result\.checked_at\)\.toLocaleTimeString\(\[\], \{ hour: 'numeric', minute: '2-digit' \}\)/);
});
