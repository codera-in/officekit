import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const drawers = fs.readFileSync(path.join(root, 'src-tauri/macos-drawers.swift'), 'utf8');

test('an in-place refresh that changes the height resizes the host and the content together', () => {
  // Resizing only the content and then letting the popover resize the host moved the top-pinned content up by the
  // growth twice: the rings were clipped at the top and a blank band was left at the bottom (Network, after a check).
  const update = drawers.match(/func update\(with next: NSView, in popover: NSPopover\?\) -> Bool \{[\s\S]*?\n    \}\n/)?.[0] || '';
  assert.match(update, /fit\(shown, to: size, in: popover\)/, 'the refresh sizes through fit');
  assert.doesNotMatch(update, /shown\.setFrameSize/, 'the content is never resized on its own');
  const fit = drawers.match(/private func fit\(_ shown: NSView, to size: NSSize, in popover: NSPopover\?\) \{[\s\S]*?\n    \}\n/)?.[0] || '';
  assert.match(fit, /view\.setFrameSize\(size\)/, 'the host takes the new size first');
  assert.match(fit, /shown\.frame = NSRect\(origin: \.zero, size: size\)/, 'the content fills the host from its origin');
  assert.ok(fit.indexOf('view.setFrameSize') < fit.indexOf('shown.frame ='), 'host first, then content');
  assert.match(fit, /popover\?\.contentSize = size/, 'the popover follows');
});

test('the drawer footer is as wide as the rows, so its buttons and link line up with them', () => {
  assert.match(drawers, /footer\.widthAnchor\.constraint\(equalToConstant: drawerContentWidth\)\.isActive = true/);
});

test('the two footer buttons are pinned edge to edge at equal width and the link is centred under them', () => {
  // A nested fill-equally stack measured 262 wide and sat against the right edge; the pair is explicit now.
  assert.doesNotMatch(drawers, /pair\.distribution = \.fillEqually/, 'no nested fill-equally stack');
  assert.match(drawers, /primary\.leadingAnchor\.constraint\(equalTo: pair\.leadingAnchor\)\.isActive = true/, 'Run again on the left edge');
  assert.match(drawers, /settings\.trailingAnchor\.constraint\(equalTo: pair\.trailingAnchor\)\.isActive = true/, 'Network settings on the right edge');
  assert.match(drawers, /settings\.leadingAnchor\.constraint\(equalTo: primary\.trailingAnchor, constant: 8\)\.isActive = true/, 'eight points between them');
  assert.match(drawers, /primary\.widthAnchor\.constraint\(equalTo: settings\.widthAnchor\)\.isActive = true/, 'equal widths');
  assert.match(drawers, /pair\.widthAnchor\.constraint\(equalToConstant: drawerContentWidth\)\.isActive = true/, 'as wide as the rows');
  assert.match(drawers, /speedTest\.alignment = \.center\s*speedTest\.widthAnchor\.constraint\(equalToConstant: drawerContentWidth\)\.isActive = true/, 'the link is centred across the row width');
});
