import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function inlineScripts(html) {
  return [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)]
    .filter(([, attributes]) => !/\bsrc=/.test(attributes) && !/type="(?!text\/javascript|module)/.test(attributes))
    .map(([, , body], index) => ({ body, index: index + 1 }));
}

test('every inline script in index.html parses, so one bad edit cannot disable every button', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const scripts = inlineScripts(html);
  assert.ok(scripts.length >= 3, 'index.html should still carry its inline scripts');
  for (const { body, index } of scripts) {
    assert.doesNotThrow(() => new vm.Script(body, { filename: `index.html inline script ${index}` }), `inline script ${index} must be valid JavaScript`);
  }
});

test('every local script and stylesheet index.html loads is published to dist-ui', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const references = [...html.matchAll(/(?:src|href)="\.\/(assets\/[^"?#]+)"/g)].map(match => match[1]);
  assert.ok(references.length > 20);
  const missing = references.filter(reference => !fs.existsSync(path.join(root, 'dist-ui', reference)));
  assert.deepEqual(missing, []);
});
