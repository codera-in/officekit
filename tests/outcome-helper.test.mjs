import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../assets/officekit-outcome.js', import.meta.url), 'utf8');

function slotFactory() {
  const classes = new Set(['ok-action-dock__status']);
  const slot = {
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
    },
    textContent: '',
    dataset: {},
    attrs: {},
    ownerDocument: {
      createElement: () => ({ className: '', textContent: '' }),
    },
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    append(child) { this.children = [...(this.children || []), child]; },
  };
  return slot;
}

function load() {
  const context = { window: {}, globalThis: {} };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.officekitOutcome;
}

test('success, working and error states set the state, role and words', () => {
  const outcome = load();
  const slot = slotFactory();
  outcome.show(slot, { state: 'success', text: 'Settings saved.' });
  assert.equal(slot.dataset.state, 'success');
  assert.equal(slot.attrs.role, 'status');
  assert.equal(slot.textContent, 'Settings saved.');
  assert.equal(slot.classList.contains('ok-outcome'), true);
  assert.equal(slot.classList.contains('ok-action-dock__status'), true, 'keeps the layout class');

  outcome.show(slot, { state: 'working', text: 'Saving…' });
  assert.equal(slot.dataset.state, 'working');

  outcome.show(slot, { state: 'error', text: 'Could not save.' });
  assert.equal(slot.dataset.state, 'error');
  assert.equal(slot.attrs.role, 'alert');
});

test('an unknown or missing state falls back to the neutral info state', () => {
  const outcome = load();
  const slot = slotFactory();
  outcome.show(slot, { text: 'Unsaved changes' });
  assert.equal(slot.dataset.state, 'info');
  outcome.show(slot, { state: 'celebrate', text: 'Hi' });
  assert.equal(slot.dataset.state, 'info');
});

test('recovery text is added as its own line, not merged into the words', () => {
  const outcome = load();
  const slot = slotFactory();
  outcome.show(slot, { state: 'error', text: 'Could not save.', recovery: 'Try again.' });
  assert.equal(slot.textContent, 'Could not save.');
  assert.equal(slot.children.length, 1);
  assert.equal(slot.children[0].className, 'ok-outcome__recovery');
  assert.equal(slot.children[0].textContent, 'Try again.');
});

test('clear resets the slot to the plain status class', () => {
  const outcome = load();
  const slot = slotFactory();
  outcome.show(slot, { state: 'success', text: 'Done' });
  outcome.clear(slot);
  assert.equal(slot.classList.contains('ok-outcome'), false);
  assert.equal(slot.classList.contains('ok-action-dock__status'), true);
  assert.equal(slot.textContent, '');
  assert.equal('state' in slot.dataset, false);
});

test('a missing slot is ignored rather than throwing', () => {
  const outcome = load();
  assert.doesNotThrow(() => outcome.show(null, { state: 'error', text: 'x' }));
  assert.doesNotThrow(() => outcome.clear(undefined));
});

test('a license_required rejection never becomes text, a toast or a popup', () => {
  const outcome = load();
  const slot = slotFactory();
  slot.ownerDocument.body = { append() { throw new Error('nothing may be drawn'); } };
  slot.closest = () => true;
  slot.textContent = 'old';
  outcome.show(slot, { state: 'error', text: 'license_required' });
  assert.equal(slot.textContent, '');
  assert.equal('state' in slot.dataset, false);
  assert.equal(outcome.isLicenseRequired('license_required'), true);
  assert.equal(outcome.isLicenseRequired(new Error('license_required')), true);
  assert.equal(outcome.isLicenseRequired({ error: { code: 'license_required' } }), true);
  assert.equal(outcome.isLicenseRequired(new Error('disk full')), false);
  assert.equal(outcome.isLicenseRequired(null), false);
});

test('the reminders tool stays quiet when a locked app rejects its native commands', () => {
  const ergonomics = readFileSync(new URL('../assets/officekit-ergonomics.js', import.meta.url), 'utf8');
  assert.match(ergonomics, /isLicenseRequired\?\.\(error\)\) message\('Could not complete that action\.'/);
  assert.match(ergonomics, /isLicenseRequired\?\.\(error\)\) message\('Could not connect to desktop reminders/);
});

test('Media toolkit run and cancel report through the outcome slot with a state, not bare text', () => {
  const media = readFileSync(new URL('../assets/officekit-media.js', import.meta.url), 'utf8');
  assert.match(media, /officekitOutcome\.show\(\$\('status'\)/);
  assert.match(media, /status\('Submitting local media job…', 'working'\)/);
  assert.match(media, /status\('Results are ready\. Save each one below\.', 'success'\)/);
  assert.match(media, /status\(error\.message \|\| 'The media job could not be completed\.', 'error'\)/);
  assert.doesNotMatch(media, /status\('Select at least one file to prepare\.'\)/);
});
