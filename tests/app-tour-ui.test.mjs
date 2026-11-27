import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const distHtml = fs.readFileSync(path.join(root, 'dist-ui/index.html'), 'utf8');
const tourJs = fs.readFileSync(path.join(root, 'assets/officekit-tour.js'), 'utf8');

test('title bar has microphone and activity buttons removed and app tour button added', () => {
  // Title bar action area should have #officekit-tour-trigger
  assert.match(html, /id="officekit-tour-trigger"/);
  assert.match(html, /fa-compass/);
  assert.match(html, /data-officekit-click="startAppTour\(\)"/);

  // Microphone and Activity buttons are removed from title bar header actions
  const headerActionsMatch = html.match(/class="ok-header-actions[\s\S]*?<!-- Tab Switching Nav -->/);
  assert.ok(headerActionsMatch, 'header actions area must exist');
  const headerActions = headerActionsMatch[0];

  assert.doesNotMatch(headerActions, /switchTab\('dictate'\)/, 'Microphone shortcut must not be in title bar');
  assert.doesNotMatch(headerActions, /id="officekit-activity-trigger"/, 'Activity trigger must not be in title bar');

  // Sidebar navigation keeps Activity; Speech-to-Text is a starter favorite
  assert.doesNotMatch(html, /data-sidebar-tab="dictate"/);
  assert.match(html, /data-sidebar-tab="activity"/);
  assert.match(html, /<span data-officekit-activity-count/);
});

test('dist-ui/index.html stays in sync with title bar cleanup and tour script', () => {
  assert.match(distHtml, /id="officekit-tour-trigger"/);
  assert.match(distHtml, /assets\/officekit-tour\.js/);
});

test('assets/officekit-tour.js parses and defines window.OfficeKitTour with 7 steps', () => {
  const context = {
    window: {},
    document: {
      addEventListener: () => {},
      body: { append: () => {} },
      createElement: () => ({
        setAttribute: () => {},
        querySelector: () => ({ addEventListener: () => {} }),
        querySelectorAll: () => [],
      }),
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    localStorage: { getItem: () => null, setItem: () => {} },
  };
  context.globalThis = context.window;
  vm.createContext(context);
  assert.doesNotThrow(() => vm.runInContext(tourJs, context));
  assert.ok(context.window.OfficeKitTour, 'window.OfficeKitTour must be defined');
  assert.equal(typeof context.window.OfficeKitTour.start, 'function');
  assert.equal(typeof context.window.OfficeKitTour.close, 'function');
  assert.equal(context.window.OfficeKitTour.getSteps().length, 7);
  assert.equal(typeof context.window.startAppTour, 'function');
});
