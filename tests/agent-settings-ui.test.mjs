import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'assets/officekit-agents.js'), 'utf8');
const skill = fs.readFileSync(path.join(root, 'assets/agent-skill/SKILL.md'), 'utf8');

function loadAgents() {
  const window = {};
  vm.runInNewContext(script, { window, document: undefined });
  return window.OfficeKitAgents;
}

test('Settings is a sidebar destination pinned above the disk footprint', () => {
  const settingsAt = html.indexOf('data-sidebar-tab="settings"');
  const footprintAt = html.indexOf('class="ok-sidebar-footprint');
  assert.ok(settingsAt > 0 && settingsAt < footprintAt, 'Settings link sits before the disk-usage pill');
  assert.match(html, /data-officekit-click="switchTab\('settings'\)"/);
  assert.match(html, /fa-gear/);
});

test('switchTab and the release profile know the settings tab', () => {
  assert.match(html, /const shellTabs = \[[^\]]*'activity', 'settings', 'workspace'/, 'settings is a shell tab');
  assert.match(html, /'activity', 'settings'\];/, 'settings keeps its sidebar item selected');
  assert.match(html, /'history', 'activity', 'settings'\]\.includes\(tab\)\) return true;/, 'settings is allowed in every release profile');
  assert.match(html, /if \(tab === 'settings' && typeof officekitMountAgents === 'function'\) officekitMountAgents\(\);/);
  assert.match(html, /<script src="\.\/assets\/officekit-agents\.js"><\/script>/);
});

test('Settings is a browsing destination: no action bar and no automatic rail collapse', () => {
  const actions = fs.readFileSync(path.join(root, 'assets/officekit-tool-actions.js'), 'utf8');
  assert.match(actions, /const browsing = new Set\(\[[^\]]*'tab-settings'/);
  assert.match(html, /\['home','tools','recents','favorites','history','activity','settings'\]\.includes\(tab\)\) officekitSetSidebarCollapsed/);
});

test('the skill panel comes before MCP and the privacy note names what is never shared', () => {
  const section = html.slice(html.indexOf('id="tab-settings"'), html.indexOf('id="tab-activity"'));
  assert.ok(section.indexOf('Agent skill') < section.indexOf('Connect through MCP'));
  assert.match(section, /Recommended/);
  for (const id of ['pdf', 'image', 'calc', 'privacy', 'dev', 'system']) assert.match(section, new RegExp(`data-agent-group="${id}"`));
  assert.match(section, /Clipboard history, snippets, dictation and transcripts are never shared with agents/);
  assert.doesNotMatch(section, /password generator|passphrase/i);
  assert.equal((section.match(/role="tab"/g) || []).length, 4);
  assert.match(section, /role="status" aria-live="polite"/);
});

test('client configs launch the bundled helper with --agent-mcp', () => {
  const agents = loadAgents();
  const helper = '/Applications/OfficeKit.app/Contents/Resources/binaries/officekit-media';
  assert.equal(agents.clientConfig('claude-code', helper).text, `claude mcp add officekit -- '${helper}' --agent-mcp`);
  for (const client of ['claude-desktop', 'cursor']) {
    const config = JSON.parse(agents.clientConfig(client, helper).text);
    assert.deepEqual(config.mcpServers.officekit, { command: helper, args: ['--agent-mcp'] });
  }
  const toml = agents.clientConfig('codex', helper).text;
  assert.match(toml, /^\[mcp_servers\.officekit\]\ncommand = "\/Applications\/OfficeKit\.app\/.*officekit-media"\nargs = \["--agent-mcp"\]$/);
  assert.throws(() => agents.clientConfig('vim', helper), /Unknown agent app/);
});

test('shell quoting survives apostrophes and spaces', () => {
  const agents = loadAgents();
  assert.equal(agents.shellQuote("/Users/o'neil/My Apps/officekit-media"), "'/Users/o'\\''neil/My Apps/officekit-media'");
  assert.match(agents.clientConfig('claude-code', "/a b/o'k").text, /-- '\/a b\/o'\\''k' --agent-mcp$/);
});

test('settings helpers keep unrelated saved values and cap folders', () => {
  const agents = loadAgents();
  assert.deepEqual(Array.from(agents.enabledGroups({ version: 1 })), ['pdf', 'image', 'calc', 'privacy', 'dev', 'system']);
  assert.deepEqual(Array.from(agents.enabledGroups({ version: 1, tools: ['calc', 'clipboard'] })), ['calc']);
  const saved = { version: 1, tools: ['pdf'], allowed_dirs: ['/Users/me/Documents'], output_dir: '/Users/me/Out' };
  assert.deepEqual(JSON.parse(JSON.stringify(agents.withTools(saved, ['system', 'pdf']))),
    { version: 1, tools: ['pdf', 'system'], allowed_dirs: ['/Users/me/Documents'], output_dir: '/Users/me/Out' });
  assert.deepEqual(JSON.parse(JSON.stringify(agents.withTools({ version: 1 }, []))), { version: 1, tools: [] });
  const many = Array.from({ length: 30 }, (_, index) => `/tmp/f${index}`);
  assert.equal(agents.withAllowedDirs(saved, many).allowed_dirs.length, 20);
  assert.deepEqual(Array.from(agents.withAllowedDirs(saved, ['/x']).tools), ['pdf']);
  assert.equal(agents.folderLabel('/Users/me/Downloads/'), 'Downloads');
  assert.equal(agents.folderLabel('C:\\Users\\me\\Desktop'), 'Desktop');
  assert.equal(agents.skillMessage('outdated'), 'Installed, an update is available');
  assert.equal(agents.skillMessage('???'), 'Status unavailable');
});

test('the skill template keeps the placeholder the native installer replaces', () => {
  assert.match(skill, /^---\nname: officekit\n/);
  assert.ok(skill.includes('{{OFFICEKIT_BIN}} call <group> <action>'));
  assert.doesNotMatch(skill, /call dev (password|passphrase)/);
});
