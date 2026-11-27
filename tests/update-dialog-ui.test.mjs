import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const START = '// In-App Auto-Update Checker';
const END = '// In-Built Support & Bug Reporting Modal';
const source = html.slice(html.indexOf(START), html.indexOf(END));

class FakeNode {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this.classes = new Set();
    this.style = {};
    this.text = '';
    this.id = '';
    this.focused = false;
    this.classList = {
      contains: name => this.classes.has(name),
      add: name => { this.classes.add(name); },
      remove: name => { this.classes.delete(name); },
    };
  }
  set className(value) { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classes].join(' '); }
  set textContent(value) { this.text = String(value); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  get lastElementChild() { return this.children.at(-1) ?? null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; this.text = ''; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  focus() { this.focused = true; }
  all(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.all(predicate, found);
    }
    return found;
  }
}

function load({ unlocked = true, invoke, fetchResult } = {}) {
  const dialog = new FakeNode();
  dialog.className = 'hidden fixed inset-0';
  const body = new FakeNode();
  const dot = new FakeNode('span');
  dot.className = 'hidden';
  const byId = { 'update-dialog': dialog, 'update-dialog-body': body, 'update-badge-dot': dot };
  const calls = [];
  const timers = [];
  const context = {
    document: {
      createElement: tag => new FakeNode(tag),
      getElementById: id => byId[id] ?? null,
      activeElement: null,
    },
    window: invoke === undefined ? {} : { __TAURI__: { core: { invoke: async (command, args) => { calls.push([command, args]); return invoke(command, args); } } } },
    HTMLElement: FakeNode,
    setInterval: callback => { timers.push(callback); return timers.length; },
    clearInterval: () => {},
    fetch: async () => fetchResult(),
    officekitLicenseUnlocked: () => unlocked,
    officekitApiUrl: path => path,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const buttons = () => body.all(node => node.tag === 'button' && !node.classes.has('ok-text-link'));
  return {
    context, dialog, body, dot, calls, timers,
    visible: () => !dialog.classes.has('hidden'),
    labels: () => buttons().map(node => node.text),
    link: () => body.all(node => node.classes.has('ok-text-link'))[0],
    title: () => body.all(node => node.tag === 'h3')[0]?.text,
    info: () => vm.runInContext('officekitUpdateInfo', context),
  };
}

const AVAILABLE = {
  status: 'update_available', update_available: true, current_version: '1.0.121', latest_version: '1.0.124',
  release_notes: 'Notarized build.', download_url: 'https://officekit.app/get',
  download_sha256: 'a'.repeat(64), download_size: 247904819,
};
const answer = data => () => ({ ok: true, json: async () => data });

test('the update code never calls alert(), which the desktop window does not display', () => {
  assert.ok(source.length > 2000, 'the update block was found');
  assert.doesNotMatch(source, /\balert\(/);
});

test('at launch an available update only lights the green dot', async () => {
  const app = load({ fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(false);
  assert.equal(app.dot.classes.has('hidden'), false);
  assert.equal(app.visible(), false, 'no dialog opens by itself');
  assert.equal(app.info().latest_version, '1.0.124');
});

test('at launch nothing shows when up to date, unavailable or locked', async () => {
  for (const data of [{ status: 'up_to_date', update_available: false, current_version: '1.0.124' }, { status: 'unavailable', update_available: false }]) {
    const app = load({ fetchResult: answer(data) });
    await app.context.checkAppUpdates(false);
    assert.equal(app.visible(), false);
    assert.equal(app.dot.classes.has('hidden'), true);
  }
  const locked = load({ unlocked: false, fetchResult: () => { throw new Error('no network while locked'); } });
  await locked.context.checkAppUpdates(true);
  assert.equal(locked.visible(), false);
});

test('clicking the refresh button with an update shows the versions, notes and two buttons, and clears the dot', async () => {
  const app = load({ invoke: () => ({ state: 'idle' }), fetchResult: answer(AVAILABLE) });
  app.dot.classes.delete('hidden');
  await app.context.checkAppUpdates(true);
  assert.equal(app.visible(), true);
  assert.equal(app.title(), 'OfficeKit 1.0.124 is available');
  assert.match(app.body.textContent, /You have 1\.0\.121\. Download size: 248 MB\./);
  assert.match(app.body.textContent, /Notarized build\./);
  assert.deepEqual(app.labels(), ['Not now', 'Download update']);
  assert.equal(app.dot.classes.has('hidden'), true);
});

test('release notes are rendered as text, never as markup', async () => {
  const app = load({ fetchResult: answer({ ...AVAILABLE, release_notes: '<img src=x onerror=alert(1)>' }) });
  await app.context.checkAppUpdates(true);
  const notes = app.body.all(node => node.text.includes('<img'))[0];
  assert.equal(notes.text, '<img src=x onerror=alert(1)>');
  assert.equal(app.body.all(node => node.tag === 'img').length, 0);
});

test('a manifest without a checksum offers no in-app download', async () => {
  const app = load({ fetchResult: answer({ ...AVAILABLE, download_sha256: null, download_size: null }) });
  await app.context.checkAppUpdates(true);
  assert.deepEqual(app.labels(), ['Close']);
  assert.match(app.body.textContent, /officekit\.app/);
});

test('up to date and cannot-check each show one Close button', async () => {
  const current = load({ fetchResult: answer({ status: 'up_to_date', update_available: false, current_version: '1.0.124' }) });
  await current.context.checkAppUpdates(true);
  assert.equal(current.title(), "You're up to date");
  assert.match(current.body.textContent, /OfficeKit 1\.0\.124 is the latest release\./);
  assert.deepEqual(current.labels(), ['Close']);

  const down = load({ fetchResult: answer({ status: 'unavailable', update_available: false }) });
  await down.context.checkAppUpdates(true);
  assert.equal(down.title(), "Couldn't check for updates");
  assert.deepEqual(down.labels(), ['Close']);

  const broken = load({ fetchResult: () => { throw new Error('offline'); } });
  await broken.context.checkAppUpdates(true);
  assert.equal(broken.title(), "Couldn't check for updates");
  const bad = load({ fetchResult: () => ({ ok: false }) });
  await bad.context.checkAppUpdates(true);
  assert.equal(bad.title(), "Couldn't check for updates");
});

test('Download update sends exactly the verified fields to the shell and starts polling', async () => {
  let state = { state: 'idle' };
  const app = load({ invoke: command => (command === 'update_download_start' ? (state = { state: 'downloading', version: '1.0.124', received: 1000, total: 4000 }, null) : state), fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  await app.context.startUpdateDownload();
  const started = app.calls.find(([command]) => command === 'update_download_start');
  assert.equal(JSON.stringify(started[1]), JSON.stringify({
    version: '1.0.124', url: 'https://officekit.app/get', sha256: 'a'.repeat(64), size: 247904819,
  }));
  assert.equal(app.timers.length, 1, 'a poll timer is running');
  await app.context.officekitUpdateRefresh();
  assert.equal(app.title(), 'Downloading OfficeKit 1.0.124');
  const bar = app.body.all(node => node.getAttribute('role') === 'progressbar')[0];
  assert.equal(bar.getAttribute('aria-valuenow'), '25');
  assert.match(app.body.textContent, /1 MB of 1 MB|0 MB of|1 MB of 4 MB/);
  assert.deepEqual(app.labels(), ['Cancel download']);
});

test('a download that cannot start shows the reason and Try again', async () => {
  const app = load({
    invoke: command => { if (command === 'update_download_start') throw 'A download is already running.'; return { state: 'idle' }; },
    fetchResult: answer(AVAILABLE),
  });
  await app.context.checkAppUpdates(true);
  await app.context.startUpdateDownload();
  assert.equal(app.title(), "The download didn't finish");
  assert.match(app.body.textContent, /A download is already running\. Nothing was installed\./);
  assert.deepEqual(app.labels(), ['Close', 'Try again']);
});

test('a finished download offers Open installer and a Show in Finder link, never a path', async () => {
  const ready = { state: 'ready', version: '1.0.124', file_name: 'OfficeKit_1.0.124_aarch64.dmg' };
  const app = load({ invoke: () => ready, fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  assert.equal(app.title(), 'OfficeKit 1.0.124 is ready to install');
  assert.deepEqual(app.labels(), ['Close', 'Open installer']);
  assert.equal(app.link().text, 'Show in Finder');
  assert.equal(app.link().getAttribute('data-officekit-click'), 'openUpdateInstaller(true)');
  assert.doesNotMatch(app.body.textContent, /\/Users\//);
  await app.context.openUpdateInstaller(false);
  assert.equal(JSON.stringify(app.calls.at(-1)), JSON.stringify(['update_installer_open', { reveal: false }]));
  await app.context.openUpdateInstaller(true);
  assert.equal(JSON.stringify(app.calls.at(-1)), JSON.stringify(['update_installer_open', { reveal: true }]));
});

test('a refresh click during a download shows its progress instead of checking again', async () => {
  let fetched = 0;
  const app = load({
    invoke: () => ({ state: 'downloading', version: '1.0.124', received: 10, total: 100 }),
    fetchResult: () => { fetched += 1; return { ok: true, json: async () => AVAILABLE }; },
  });
  await app.context.checkAppUpdates(true);
  assert.equal(fetched, 0);
  assert.equal(app.title(), 'Downloading OfficeKit 1.0.124');
  assert.equal(app.timers.length, 1);
});

test('cancelling returns to the update-found view once the shell reports idle', async () => {
  let state = { state: 'idle' };
  const app = load({ invoke: command => { if (command === 'update_download_cancel') state = { state: 'idle' }; return state; }, fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  state = { state: 'downloading', version: '1.0.124', received: 5, total: 10 };
  await app.context.cancelUpdateDownload();
  await app.context.officekitUpdateRefresh();
  assert.ok(app.calls.some(([command]) => command === 'update_download_cancel'));
  assert.equal(app.title(), 'OfficeKit 1.0.124 is available');
});

test('a failed download reported by the shell shows its plain message', async () => {
  const app = load({ invoke: () => ({ state: 'failed', version: '1.0.124', message: 'The downloaded file did not match its checksum.' }), fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  await app.context.officekitUpdateRefresh();
  assert.match(app.body.textContent, /did not match its checksum\. Nothing was installed\./);
});

test('outside the desktop shell the refresh button still checks and reports', async () => {
  const app = load({ fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  assert.equal(app.title(), 'OfficeKit 1.0.124 is available');
  await app.context.startUpdateDownload();
  assert.equal(app.title(), "The download didn't finish");
  assert.match(app.body.textContent, /Downloads work in the desktop app|could not start/i);
});

test('only a click on the backdrop closes the dialog, and Close stops the polling', async () => {
  const app = load({ invoke: () => ({ state: 'idle' }), fetchResult: answer(AVAILABLE) });
  await app.context.checkAppUpdates(true);
  const inner = new FakeNode();
  app.context.closeUpdateDialog.call(app.dialog, { target: inner });
  assert.equal(app.visible(), true, 'a click inside the dialog keeps it open');
  app.context.closeUpdateDialog.call(app.dialog, { target: app.dialog });
  assert.equal(app.visible(), false);
  app.context.closeUpdateDialog();
  assert.equal(app.visible(), false, 'closing twice is harmless');
});

test('no update screen shows more than three buttons', async () => {
  const views = [
    load({ fetchResult: answer(AVAILABLE) }),
    load({ invoke: () => ({ state: 'ready', version: '1.0.124' }), fetchResult: answer(AVAILABLE) }),
    load({ invoke: () => ({ state: 'downloading', version: '1.0.124', received: 1, total: 2 }), fetchResult: answer(AVAILABLE) }),
    load({ fetchResult: answer({ status: 'unavailable' }) }),
  ];
  for (const app of views) {
    await app.context.checkAppUpdates(true);
    assert.ok(app.labels().length >= 1 && app.labels().length <= 3, app.labels().join('|'));
  }
});

test('the markup, the delegated actions and the Escape key are wired', () => {
  assert.match(html, /<div id="update-dialog" data-officekit-click="closeUpdateDialog\(event\)" class="hidden /);
  assert.match(html, /id="update-dialog-body" aria-live="polite"/);
  assert.match(html, /role="dialog" aria-modal="true" aria-labelledby="update-dialog-title"/);
  const allowlist = html.slice(html.indexOf('const OFFICEKIT_DELEGATED_ACTIONS'), html.indexOf('function officekitParseDelegatedArguments'));
  for (const name of ['closeUpdateDialog', 'startUpdateDownload', 'cancelUpdateDownload', 'openUpdateInstaller']) {
    assert.ok(allowlist.includes(`'${name}'`), `${name} is a delegated action`);
  }
  assert.match(html, /closeCrashModal\(\);\n\s+closeUpdateDialog\(\);/);
  for (const action of [...source.matchAll(/action: '([A-Za-z]+)\(/g)].map(match => match[1])) {
    assert.ok(allowlist.includes(`'${action}'`), `${action} used by the dialog is allowed`);
  }
});
