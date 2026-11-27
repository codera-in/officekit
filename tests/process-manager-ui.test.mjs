import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const workspaceJs = fs.readFileSync(path.join(root, 'assets/officekit-workspace.js'), 'utf8');

test('quick-stats markup includes active processes table and controls', () => {
  assert.ok(html.includes('id="tab-quick-stats"'));
  assert.ok(html.includes('id="quick-processes-heading"'));
  assert.ok(html.includes('id="quick-processes-sort"'));
  assert.ok(html.includes('id="quick-processes-refresh-btn"'));
  assert.ok(html.includes('id="quick-processes-filter"'));
  assert.ok(html.includes('id="quick-processes-status"'));
  assert.ok(html.includes('id="quick-processes-table"'));
  assert.ok(html.includes('id="quick-processes-tbody"'));
});

test('officekit-workspace.js contains process management functions', () => {
  assert.ok(workspaceJs.includes('async function officekitFetchProcesses'));
  assert.ok(workspaceJs.includes('function officekitRenderProcessList'));
  assert.ok(workspaceJs.includes('async function officekitConfirmAndKillProcess'));
  assert.ok(workspaceJs.includes('/api/system/processes'));
  assert.ok(workspaceJs.includes('/api/system/processes/terminate'));
});

test('process killer formats process rows safely with protection badges', () => {
  assert.ok(workspaceJs.includes('data-kill-pid'));
  assert.ok(workspaceJs.includes('End Process'));
  assert.ok(workspaceJs.includes('Protected'));
});
