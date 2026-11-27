import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const dialog = html.match(/<div id="crash-notice-modal"([\s\S]*?)<div id="support-modal"/)?.[1] ?? '';

function element() {
  const classes = new Set(['hidden']);
  return {
    textContent: '', checked: false, disabled: false, className: '', children: [],
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle: (name, force) => (force ?? !classes.has(name)) ? classes.add(name) : classes.delete(name),
      contains: name => classes.has(name),
    },
    replaceChildren() { this.children = []; },
    append(...nodes) { this.children.push(...nodes); },
  };
}

function makeContext(invoke) {
  const ids = ['crash-notice-modal', 'crash-notice-lead', 'crash-notice-facts', 'crash-notice-restart-row', 'crash-notice-status',
    'crash-notice-title', 'crash-notice-body', 'crash-notice-later', 'crash-notice-send', 'crash-notice-send-label'];
  const nodes = Object.fromEntries(ids.map(id => [id, element()]));
  nodes['crash-notice-send-label'].textContent = 'Send report';
  const start = html.indexOf('        let crashNoticeState = null;');
  const end = html.indexOf('        /* RELEASE PROFILE CLIENT START */', start);
  assert.ok(start >= 0 && end > start, 'the crash notice handlers exist');
  const context = {
    document: { getElementById: id => nodes[id] ?? null, createElement: () => element() },
    window: invoke ? { __TAURI__: { core: { invoke } } } : {},
  };
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context);
  return { context, nodes };
}

const NOTICE = { version: '1.0.112', closedAtMs: Date.UTC(2026, 10, 25, 14, 32), macos: '27.2.1', restartEnabled: false };

function shell(overrides = {}) {
  const calls = [];
  const invoke = async (command, args) => {
    calls.push({ command, args: args ? JSON.parse(JSON.stringify(args)) : undefined });
    if (command in overrides) {
      const value = overrides[command];
      if (value instanceof Error) throw value;
      return value;
    }
    return null;
  };
  return { calls, invoke };
}

test('the notice dialog shows no more than three buttons and states what is sent', () => {
  assert.ok(dialog.length > 0);
  assert.ok((dialog.match(/<button\b/g) ?? []).length <= 3);
  assert.match(dialog, /Send report/);
  assert.match(dialog, /Not now/);
  assert.match(dialog, /Never your files/);
  assert.match(dialog, /See exactly what is sent/);
});

test('nothing is shown when the last run ended normally, offline or in the browser build', async () => {
  for (const invoke of [async () => null, async () => 'x', async () => { throw new Error('no shell'); }, null]) {
    const { context, nodes } = makeContext(invoke);
    await context.checkCrashNotice();
    assert.ok(nodes['crash-notice-modal'].classList.contains('hidden'));
  }
});

test('a crash opens the notice with the facts and the restart switch when it is off', async () => {
  const { invoke } = shell({ crash_notice_pending: NOTICE });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  assert.ok(!nodes['crash-notice-modal'].classList.contains('hidden'));
  assert.match(nodes['crash-notice-lead'].textContent, /^It quit on .+\. Your files were not changed\.$/);
  assert.doesNotMatch(nodes['crash-notice-lead'].textContent, /reopened by itself/);
  assert.deepEqual(nodes['crash-notice-facts'].children.map(row => row.children[0].textContent), ['OfficeKit', 'macOS', 'Closed']);
  assert.ok(!nodes['crash-notice-restart-row'].classList.contains('hidden'));
});

test('with the restart switch already on the checkbox is left out and the text says so', async () => {
  const { invoke } = shell({ crash_notice_pending: { ...NOTICE, restartEnabled: true, macos: null, version: null } });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  assert.match(nodes['crash-notice-lead'].textContent, /and reopened by itself/);
  assert.ok(nodes['crash-notice-restart-row'].classList.contains('hidden'));
  assert.deepEqual(nodes['crash-notice-facts'].children.map(row => row.children[0].textContent), ['Closed']);
});

test('a notice without a time still reads cleanly', async () => {
  const { invoke } = shell({ crash_notice_pending: { version: '1.0.112', closedAtMs: null, macos: null, restartEnabled: false } });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  assert.equal(nodes['crash-notice-lead'].textContent, 'It quit. Your files were not changed.');
});

test('Send report files one bug with only the version, macOS and time, then offers Done', async () => {
  const { invoke, calls } = shell({ crash_notice_pending: NOTICE, support_ticket_submit: 'OK-7QX2M' });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  await context.crashNoticeSend();

  const sent = calls.find(call => call.command === 'support_ticket_submit').args.draft;
  assert.equal(sent.kind, 'bug');
  assert.equal(sent.title, 'OfficeKit closed unexpectedly');
  assert.equal(sent.publicationConsent, false);
  assert.match(sent.description, /^OfficeKit 1\.0\.112 closed unexpectedly on .+\.\nmacOS 27\.2\.1\.\nSent from the closed-unexpectedly notice\.$/);
  assert.ok(calls.some(call => call.command === 'crash_notice_dismiss'));
  assert.equal(nodes['crash-notice-title'].textContent, 'Thank you. Report sent');
  assert.match(nodes['crash-notice-lead'].textContent, /OK-7QX2M/);
  assert.equal(nodes['crash-notice-send-label'].textContent, 'Done');
  assert.ok(nodes['crash-notice-later'].classList.contains('hidden'));
  assert.equal(nodes['crash-notice-send'].disabled, false);

  await context.crashNoticeSend();
  assert.ok(nodes['crash-notice-modal'].classList.contains('hidden'), 'Done closes it');
});

test('a failed send keeps the notice open and offers Try again; nothing is marked sent', async () => {
  const { invoke, calls } = shell({ crash_notice_pending: NOTICE, support_ticket_submit: new Error('offline') });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  await context.crashNoticeSend();
  assert.match(nodes['crash-notice-status'].textContent, /offline/);
  assert.equal(nodes['crash-notice-send-label'].textContent, 'Try again');
  assert.ok(!nodes['crash-notice-modal'].classList.contains('hidden'));
  assert.ok(!calls.some(call => call.command === 'crash_notice_dismiss'));
});

test('Not now closes the notice and tells the shell not to ask again', async () => {
  const { invoke, calls } = shell({ crash_notice_pending: NOTICE });
  const { context, nodes } = makeContext(invoke);
  await context.checkCrashNotice();
  await context.crashNoticeDismiss();
  assert.ok(nodes['crash-notice-modal'].classList.contains('hidden'));
  assert.ok(calls.some(call => call.command === 'crash_notice_dismiss'));
  assert.ok(!calls.some(call => call.command === 'support_ticket_submit'), 'nothing is sent');
});

test('the restart checkbox turns the existing setting on and undoes itself on failure', async () => {
  const ok = shell({ crash_restart_set: true });
  const first = makeContext(ok.invoke);
  const box = { checked: true };
  await first.context.crashNoticeSetRestart({ target: box });
  assert.deepEqual(ok.calls, [{ command: 'crash_restart_set', args: { enabled: true } }]);
  assert.equal(box.checked, true);

  const failing = makeContext(async () => { throw 'macOS would not load the restart agent. Nothing was changed.'; });
  const other = { checked: true };
  await failing.context.crashNoticeSetRestart({ target: other });
  assert.equal(other.checked, false);
  assert.match(failing.nodes['crash-notice-status'].textContent, /would not load/);
});

test('the notice is asked for once the profile is ready, after the fixed-ticket check', () => {
  assert.match(html, /void checkSupportTicketUpdates\(\);\s*void checkCrashNotice\(\);/);
});
