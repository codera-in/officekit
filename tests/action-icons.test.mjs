import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('assets/officekit-action-icons.js', 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);
const { iconForLabel } = context.OfficeKitActionIcons;

test('action icons express the action and preserve quiet exceptions', () => {
  for (const [label, icon] of Object.entries({
    'Choose folder…': 'folder-open', 'Choose files…': 'file-arrow-up',
    'Find duplicates': 'magnifying-glass', 'Select copies': 'check-double',
    'Move selected to Trash': 'trash-can', 'Copy report': 'copy',
    'Download PDF': 'download', 'Calculate': 'calculator',
    'Sign with certificate': 'signature', 'Remove metadata': 'eraser',
    'Verify signatures': 'shield-halved', 'Save image': 'floppy-disk',
  })) assert.equal(iconForLabel(label), icon, label);
  for (const label of ['Cancel', 'Clear selection', 'Reset selection', 'Close', '7', '+', 'Gallery']) {
    assert.equal(iconForLabel(label), null, label);
  }
});

test('every action icon exists in the bundled Font Awesome version', () => {
  const css = fs.readFileSync('node_modules/@fortawesome/fontawesome-free/css/all.css', 'utf8');
  const names = [...source.matchAll(/, '([a-z][a-z-]+)'\]/g)].map(match => match[1]);
  const files = fs.readFileSync('assets/officekit-files.js', 'utf8');
  const mapping = files.match(/dataset.actionIcon\s*=\s*\{([^}]+)\}/)?.[1] || '';
  names.push(...[...mapping.matchAll(/:'([^']+)'/g)].map(match => match[1]));
  // Font Awesome 6 wrote `.fa-name::before`; 7 writes `.fa-name{--fa:...}`, often in a selector list.
  for (const name of new Set(names)) assert.ok(new RegExp(`\\.fa-${name}(?:::before)?\\s*[,{]`).test(css), name);
});

test('desktop UI packaging includes the action icon module', () => {
  assert.match(fs.readFileSync('index.html', 'utf8'), /assets\/officekit-action-icons\.js/);
  assert.match(fs.readFileSync('scripts/build-ui-assets.mjs', 'utf8'), /officekit-action-icons\.js/);
});
