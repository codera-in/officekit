import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const profileClient = html.match(/\/\* RELEASE PROFILE CLIENT START \*\/([\s\S]*?)\/\* RELEASE PROFILE CLIENT END \*\//)?.[1];
const manifest = JSON.parse(fs.readFileSync('release-profile.json', 'utf8'));

function load() {
  assert.ok(profileClient, 'startup profile client exists');
  const context = {};
  vm.runInNewContext(profileClient, context);
  return context;
}

test('release UI fails closed until startup profile is loaded and rejects malformed profiles', () => {
  const client = load();
  assert.equal(client.officekitReleaseAllowsTool('loan_emi'), false);
  assert.equal(client.officekitReleaseAllowsTab('statement'), false);
  for (const payload of [null, {}, { profile: 'paid', tool_ids: [] }, { profile: 'private-beta', tool_ids: ['loan_emi', 'loan_emi'] }, { profile: 'private-beta', tool_ids: [] }, { profile: 'private-beta', tool_ids: [42] }, { profile: 'development', tool_ids: ['loan_emi'] }]) {
    assert.throws(() => client.officekitSetReleaseProfile(payload), /Invalid/);
  }
});

test('beta allows exactly its returned IDs and safe shared screens; development remains full', () => {
  const client = load();
  client.officekitSetReleaseProfile({ profile: 'private-beta', tool_ids: manifest.tool_ids });
  for (const id of manifest.tool_ids) assert.equal(client.officekitReleaseAllowsTool(id), true, id);
  assert.equal(client.officekitReleaseAllowsTool('bank_statement'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_unlock'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_protect'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_merge'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_split'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_compress'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_to_images'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_metadata_strip'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_table_extractor'), true);
  assert.equal(client.officekitReleaseAllowsTool('pdf_text_extract'), true);
  for (const id of ['voice_transcription', 'meeting_notes', 'system_info', 'system_resources']) assert.equal(client.officekitReleaseAllowsTool(id), true);
  assert.equal(client.officekitReleaseAllowsTool('similar_images'), false);
  for (const tab of ['tools', 'favorites', 'history', 'converter', 'calculators', 'password', 'color', 'workspace']) assert.equal(client.officekitReleaseAllowsTab(tab), true, tab);
  assert.equal(client.officekitReleaseAllowsTab('statement'), true);
  assert.equal(client.officekitReleaseAllowsTab('pdf'), true);
  for (const tab of ['pricing', 'unlocker', 'network', 'screenshot']) assert.equal(client.officekitReleaseAllowsTab(tab), false, tab);
  assert.equal(client.officekitReleaseAllowsTab('dictate'), true);
  assert.equal(client.officekitReleaseAllowsTab('system'), true);
  client.officekitSetReleaseProfile({ profile: 'development', tool_ids: [] });
  assert.equal(client.officekitReleaseAllowsTool('pdf_unlock'), true);
  assert.equal(client.officekitReleaseAllowsTab('pdf'), true);
});

test('allowed statement tool navigation records history and opens its screen', () => {
  const client = load();
  client.officekitSetReleaseProfile({ profile: 'private-beta', tool_ids: manifest.tool_ids });
  let effects = 0;
  client.OFFICEKIT_TOOL_DESTINATIONS = { bank_statement: { tab: 'statement' } };
  client.officekitToolDestination = id => client.OFFICEKIT_TOOL_DESTINATIONS[id];
  client.officekitRecordStore = { recordRecent: () => effects++ };
  client.closeGlobalSearchModal = () => {};
  client.document = { getElementById: () => null };
  client.window = {};
  client.switchTab = () => effects++;
  vm.runInNewContext(html.match(/function selectSearchTool\(toolId\) \{[\s\S]*?\n        \}/)[0], client);
  assert.equal(client.selectSearchTool('bank_statement'), true);
  assert.equal(effects, 2);
});

test('beta packaging contains scope manifest and native profile is not webview-controlled', () => {
  const sidecar = fs.readFileSync('scripts/build-backend-sidecar.mjs', 'utf8');
  const native = fs.readFileSync('src-tauri/src/lib.rs', 'utf8');
  const build = fs.readFileSync('src-tauri/build.rs', 'utf8');
  assert.match(sidecar, /release-profile\.json/);
  assert.match(native, /\.env\(\s*"OFFICEKIT_RELEASE_PROFILE",\s*env!\("OFFICEKIT_RELEASE_PROFILE"\),?\s*\)/);
  assert.match(native, /if dictation_commands_enabled\(env!\("OFFICEKIT_RELEASE_PROFILE"\)\)/);
  assert.match(build, /cargo:rerun-if-env-changed=OFFICEKIT_RELEASE_PROFILE/);
});
