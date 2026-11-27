import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('the production workspace pump requests sentence coaching and routes through validated fallback', () => {
  const source = readFileSync(new URL('../src-tauri/src/lib.rs', import.meta.url), 'utf8');
  const start = source.indexOf('fn pump_coach_workspace_checks(');
  const end = source.indexOf('fn run_speech_coach_analyzer(', start);
  assert.ok(start >= 0 && end > start, 'Inspect the actual production workspace pump');
  const pump = source.slice(start, end);
  assert.match(pump, /officekit_dictation_language_suggestion\(\s*sentence\.as_ptr\(\),\s*sentence\.len\(\) as u64,\s*3\s*,/,
    'Live Workspace must request full-sentence coaching, not short HUD grammar/vocabulary');
  assert.match(pump, /coach_grammar::check_workspace_sentence\(&sentence,\s*response\.as_deref\(\)\)/,
    'Model output must pass grounded validation and retain grammar fallback');
});
