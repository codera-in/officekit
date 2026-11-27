import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src-tauri/src/ergonomics.rs', import.meta.url), 'utf8');

test('the reminder companion window takes the first click without activating OfficeKit first', () => {
  const builder = source.slice(source.indexOf('tauri::WebviewWindowBuilder::new('), source.indexOf('.map_err(|_| "Cannot create reminder companion")'));
  assert.match(builder, /"ergonomics"/);
  assert.match(builder, /\.accept_first_mouse\(true\)/, 'without it the first click only activates the app and a button needs two clicks');
  assert.match(source, /orderFrontRegardless/, 'the bubble is still shown without stealing focus');
});
