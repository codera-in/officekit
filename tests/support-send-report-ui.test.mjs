import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const modal = html.match(/<!-- Support reports -->([\s\S]*?)<!-- Apple Pro Siri/)?.[1] ?? '';

function makeContext(invoke) {
  const values = {
    'ticket-email': { value: '' },
    'ticket-type': { value: 'bug' },
    'ticket-title': { value: 'A bug' },
    'ticket-desc': { value: 'Expected one thing.' },
    'ticket-display-name': { value: '' },
    'ticket-publication-consent': { checked: false },
    'ticket-reference': { value: '' },
    'support-send': { disabled: false },
    'support-send-label': { textContent: 'Send report' },
    'ticket-display-name-field': { classList: { toggle() {} } },
    'ticket-publication-consent-field': { classList: { toggle() {} } },
    'support-status': {
      textContent: '',
      attributes: {},
      dataset: {},
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute(name, value) { this.attributes[name] = value; },
    },
  };
  const toasts = [];
  const sourceStart = html.indexOf('        function openSupportModal() {');
  const sourceEnd = html.indexOf("        window.addEventListener('DOMContentLoaded', async () => {", sourceStart);
  assert.ok(sourceStart >= 0 && sourceEnd > sourceStart, 'support handlers exist in the expected script section');
  const context = {
    document: { getElementById: id => values[id] ?? null },
    window: invoke ? { __TAURI__: { core: { invoke } } } : {},
    showAppFeedbackToast: (message, state) => toasts.push({ message, state }),
    officekitApiUrl: value => value,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'assets', 'officekit-outcome.js'), 'utf8'), context);
  vm.runInContext(html.slice(sourceStart, sourceEnd), context);
  return { context, values, toasts };
}

test('the dialog sends reports, says what is sent and no longer offers local drafts', () => {
  assert.match(modal, /Send report/);
  assert.match(modal, /See exactly what is sent/);
  assert.match(modal, /Never your files/);
  assert.match(modal, /You get a reference to quote in replies/);
  assert.doesNotMatch(modal, /Save local draft|Reopen a saved draft|Open draft|Nothing is sent automatically/);
  assert.doesNotMatch(html, /lookupTicketStatus/);
});

test('the dialog stays within the three-button limit', () => {
  const buttons = modal.match(/<button\b/g) ?? [];
  assert.ok(buttons.length <= 3, `support dialog shows ${buttons.length} buttons`);
});

test('a report is sent through the native command with only the typed text', async () => {
  const calls = [];
  const { context, values } = makeContext(async (command, args) => { calls.push({ command, args }); return 'OK-12'; });
  values['ticket-email'].value = ' person@example.com ';
  await context.submitSupportTicket();

  assert.equal(calls[0].command, 'support_ticket_submit');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].args)), {
    draft: { kind: 'bug', title: 'A bug', description: 'Expected one thing.', email: 'person@example.com', publicationConsent: false },
  });
  assert.match(values['support-status'].textContent, /Sent\. Your reference is OK-12/);
  assert.match(values['support-status'].textContent, /email you/);
  assert.equal(values['support-status'].attributes.role, 'status');
  assert.equal(values['ticket-reference'].value, 'OK-12');
  assert.equal(values['ticket-title'].value, '');
  assert.equal(values['support-send'].disabled, false);
});

test('a testimonial carries its display name and explicit permission', async () => {
  let args;
  const { context, values } = makeContext(async (_command, value) => { args = value; return 'OK-13'; });
  values['ticket-type'].value = 'testimonial';
  values['ticket-title'].value = 'Helpful';
  values['ticket-desc'].value = 'It saved me time.';
  values['ticket-display-name'].value = 'Sam';
  values['ticket-publication-consent'].checked = true;
  await context.submitSupportTicket();
  assert.deepEqual(JSON.parse(JSON.stringify(args.draft)), {
    kind: 'testimonial', title: 'Helpful', description: 'It saved me time.', displayName: 'Sam', publicationConsent: true,
  });
  assert.doesNotMatch(values['support-status'].textContent, /email you/);
});

test('a failed send keeps the text and turns the button into Try again', async () => {
  const { context, values } = makeContext(async () => { throw 'Could not reach OfficeKit support. Nothing was sent and your text is kept here.'; });
  await context.submitSupportTicket();
  assert.match(values['support-status'].textContent, /Nothing was sent/);
  assert.equal(values['support-status'].attributes.role, 'alert');
  assert.equal(values['ticket-title'].value, 'A bug');
  assert.equal(values['support-send-label'].textContent, 'Try again');
  assert.equal(values['support-send'].disabled, false);
});

test('missing text and the browser build are refused before anything is sent', async () => {
  const calls = [];
  const { context, values } = makeContext(async (...args) => { calls.push(args); return 'x'; });
  values['ticket-title'].value = '';
  await context.submitSupportTicket();
  assert.match(values['support-status'].textContent, /Add a short title/);
  values['ticket-title'].value = 'T';
  values['ticket-type'].value = 'testimonial';
  values['ticket-publication-consent'].checked = true;
  await context.submitSupportTicket();
  assert.match(values['support-status'].textContent, /Add a display name/);
  assert.equal(calls.length, 0);

  const browser = makeContext(null);
  await browser.context.submitSupportTicket();
  assert.match(browser.values['support-status'].textContent, /desktop app/);
});

test('a fix is announced in the app with its version', async () => {
  const fixed = makeContext(async () => [{ ticketId: 'OK-12', fixedIn: '1.0.116' }, { ticketId: 'OK-9', fixedIn: '1.0.116' }]);
  await fixed.context.checkSupportTicketUpdates();
  assert.deepEqual(fixed.toasts, [{ message: 'Your report OK-12 is fixed in OfficeKit 1.0.116 (and 1 more).', state: 'success' }]);

  const single = makeContext(async () => [{ ticketId: 'OK-12', fixedIn: '1.0.116' }]);
  await single.context.checkSupportTicketUpdates();
  assert.match(single.toasts[0].message, /^Your report OK-12 is fixed in OfficeKit 1\.0\.116\.$/);

  for (const invoke of [async () => [], async () => null, async () => { throw new Error('offline'); }, null]) {
    const quiet = makeContext(invoke);
    await quiet.context.checkSupportTicketUpdates();
    assert.deepEqual(quiet.toasts, []);
  }
});
