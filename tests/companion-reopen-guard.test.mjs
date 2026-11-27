import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lib = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
const ergonomics = fs.readFileSync(path.join(root, 'src-tauri/src/ergonomics.rs'), 'utf8');

test('focusing the reminder mascot starts the reopen grace period before any action reaches the web layer', () => {
  assert.match(lib, /window\.label\(\) == "ergonomics" && matches!\(event, tauri::WindowEvent::Focused\(true\)\) \{\s*ergonomics::note_companion_press\(\);/);
  assert.match(ergonomics, /pub fn note_companion_press\(\)/);
});

test('every mascot press (close included) is noted, and a reopen after the mascot hid is still ignored for a while', () => {
  assert.match(ergonomics, /authorize\(&window\)\?;\s*note_companion_press\(\);/, 'the action command notes the press');
  assert.match(ergonomics, /const COMPANION_HIDE_REOPEN_GRACE: Duration = Duration::from_secs\(15\)/);
  assert.match(ergonomics, /const COMPANION_PRESS_REOPEN_GRACE: Duration = Duration::from_secs\(30\)/);
  assert.match(lib, /ergonomics::companion_hid_recently\(\)\s*\|\| ergonomics::companion_visible\(app\)/, 'the reopen handler consults both');
});
