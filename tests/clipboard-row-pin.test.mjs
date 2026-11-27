import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const panel = readFileSync(new URL('../src-tauri/macos-global.swift', import.meta.url), 'utf8');
const logic = readFileSync(new URL('../src-tauri/macos-global-logic.swift', import.meta.url), 'utf8');

test('only text and link clips can be pinned from the panel', () => {
  assert.match(logic, /func globalPickerCanPin\(kind: String\) -> Bool \{\s*kind == "text" \|\| kind == "link"\s*\}/);
  assert.match(panel, /case "pin": if !readOnlySelected && selectedRowCanPin/);
  assert.match(panel, /globalPickerCanPin\(kind: visible\[table\.selectedRow\]\.kind\)/);
  assert.match(panel, /let canPin = !readOnlySelected && globalPickerCanPin\(kind: item\.kind\)/);
  assert.match(panel, /guard visible\.indices\.contains\(sender\.tag\), globalPickerCanPin/);
});

test('each pinnable row has a pushpin button at its left edge and the star prefix is gone', () => {
  assert.match(panel, /systemSymbolName: item\.pinned \? "pin\.fill" : "pin"/);
  assert.match(panel, /pin\.contentTintColor = item\.pinned \? \.systemOrange : \.labelColor/);
  assert.match(panel, /pin\.leadingAnchor\.constraint\(equalTo: cell\.leadingAnchor/);
  assert.match(panel, /label\.leadingAnchor\.constraint\(equalTo: pin\.trailingAnchor/);
  assert.doesNotMatch(panel, /"★ \\\(item\.title\)"/);
});

test('clicking the pin toggles it and leaves the panel open', () => {
  assert.match(panel, /@objc private func pinRowClicked[\s\S]*deliver\(action: 2, hide: false\)/);
  assert.match(panel, /func tableViewSelectionDidChange/);
});
