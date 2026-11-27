import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [html, desktop, rust, panel, swift] = await Promise.all([
  readFile(new URL('../index.html', import.meta.url), 'utf8'),
  readFile(new URL('../assets/officekit-global-desktop.js', import.meta.url), 'utf8'),
  readFile(new URL('../src-tauri/src/global_desktop.rs', import.meta.url), 'utf8'),
  readFile(new URL('../src-tauri/src/global_clipboard.rs', import.meta.url), 'utf8'),
  readFile(new URL('../src-tauri/macos-global-logic.swift', import.meta.url), 'utf8'),
]);

test('Global Launcher exposes and saves password length and symbol options', () => {
  assert.match(html, /id="global-launcher-password-length"[^>]*type="number"[^>]*min="8"[^>]*max="128"/);
  assert.match(html, /id="global-launcher-password-symbols"[^>]*maxlength="32"/);
  assert.match(desktop, /saveDesktop\(\{ quickPasswordLength: length \}, 'launcher'\)/);
  assert.match(desktop, /saveDesktop\(\{ quickPasswordSymbols: symbols \}, 'launcher'\)/);
  assert.match(rust, /quick_password_length: u8/);
  assert.match(rust, /quick_password_symbols: String/);
  assert.match(panel, /"passwordLength": options\.password_length/);
  assert.match(panel, /"passwordSymbols": options\.password_symbols/);
  assert.match(swift, /symbols: switches\.passwordSymbols/);
  assert.match(swift, /words\.count > 1 \? Int\(words\[1\]\) \?\? 0 : switches\.passwordLength/);
});
