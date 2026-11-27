import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workflows = [
  '.github/workflows/ci.yml',
];

test('clean CI runners install application and sidecar Python dependencies before tests/builds', () => {
  for (const workflowPath of workflows) {
    const workflow = readFileSync(new URL(`../${workflowPath}`, import.meta.url), 'utf8');
    const installIndex = workflow.indexOf('python -m pip install -r requirements.txt -r requirements-build.txt');
    assert.notEqual(installIndex, -1, `${workflowPath} must install both dependency manifests`);
    const testIndex = workflow.indexOf('npm test');
    assert.notEqual(testIndex, -1, `${workflowPath} must keep the npm test gate`);
    assert.ok(installIndex < testIndex, `${workflowPath} must install dependencies before npm test`);
  }
});

test('clean macOS CI builds the real packaged media launcher before Rust tests resolve Tauri resources', () => {
  const workflow = readFileSync(new URL('../.github/workflows/ci.yml', import.meta.url), 'utf8');
  const resources = JSON.parse(readFileSync(new URL('../src-tauri/tauri.macos.conf.json', import.meta.url), 'utf8')).bundle.resources;
  assert.ok(resources.includes('binaries/officekit-media'));
  const createDirectory = workflow.indexOf('mkdir -p src-tauri/binaries');
  const compileLauncher = workflow.indexOf('rustc --edition=2021 src-tauri/media-cli-launcher.rs -o src-tauri/binaries/officekit-media');
  const rustTests = workflow.indexOf('cargo test --manifest-path src-tauri/Cargo.toml --locked');
  assert.notEqual(createDirectory, -1, 'fresh checkouts must create the ignored binaries directory');
  assert.notEqual(compileLauncher, -1, 'CI must compile the real launcher required by the macOS resource manifest');
  assert.notEqual(rustTests, -1, 'keep the Rust test gate');
  assert.ok(createDirectory < compileLauncher && compileLauncher < rustTests, 'build the media resource before cargo resolves it');
});
