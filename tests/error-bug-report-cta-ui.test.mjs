import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

test('markup contains Report bug CTA in toast popup and failure crash dialog', () => {
  // Toast popup CTA
  assert.match(html, /id="app-feedback-report-bug"[^>]*data-officekit-click="reportToastBug\(\)"/);
  assert.match(html, /<button id="app-feedback-report-bug"[^>]*>[\s\S]*?Report bug[\s\S]*?<\/button>/);

  // Crash failure modal CTA
  assert.match(html, /id="crash-report-bug-btn"[^>]*data-officekit-click="reportCrashBug\(\)"/);
  assert.match(html, /<button id="crash-report-bug-btn"[^>]*>[\s\S]*?Report bug[\s\S]*?<\/button>/);

  // Delegated actions include both bug report CTAs
  const actionsBlock = html.match(/const OFFICEKIT_DELEGATED_ACTIONS = new Set\(\[([\s\S]*?)\]\);/)?.[1] ?? '';
  assert.match(actionsBlock, /'reportToastBug'/);
  assert.match(actionsBlock, /'reportCrashBug'/);
});

test('toast popup toggles Report bug CTA visibility based on error state and reportToastBug opens pre-filled dialog', () => {
  const toastClasses = new Set(['hidden']);
  const reportBtnClasses = new Set(['hidden']);
  const elements = {
    'app-feedback-toast': {
      classList: {
        add: cls => toastClasses.add(cls),
        remove: cls => toastClasses.delete(cls),
        contains: cls => toastClasses.has(cls),
      },
      setAttribute() {},
    },
    'app-feedback-icon': { className: '' },
    'app-feedback-progress': { className: '' },
    'app-feedback-text': { textContent: '' },
    'app-feedback-report-bug': {
      classList: {
        add: cls => reportBtnClasses.add(cls),
        remove: cls => reportBtnClasses.delete(cls),
        contains: cls => reportBtnClasses.has(cls),
      },
    },
  };

  const supportModalClasses = new Set(['hidden']);
  const values = {
    'support-modal': {
      classList: {
        add: cls => supportModalClasses.add(cls),
        remove: cls => supportModalClasses.delete(cls),
        contains: cls => supportModalClasses.has(cls),
      },
    },
    'ticket-type': { value: '' },
    'ticket-title': { value: '' },
    'ticket-desc': { value: '', focus() {} },
    'ticket-display-name-field': { classList: { toggle() {} } },
    'ticket-publication-consent-field': { classList: { toggle() {} } },
    'support-status': { textContent: '', dataset: {}, classList: { toggle() {}, add() {}, remove() {} }, setAttribute() {} },
  };

  // Extract functions from index.html
  const toastStart = html.indexOf('        function dismissAppFeedbackToast() {');
  const toastEnd = html.indexOf('        function setDictationStatus(', toastStart);
  assert.ok(toastStart > 0 && toastEnd > toastStart);

  const supportStart = html.indexOf('        function openSupportModal() {');
  const supportEnd = html.indexOf("        window.addEventListener('DOMContentLoaded', async () => {", supportStart);
  assert.ok(supportStart > 0 && supportEnd > supportStart);

  const context = {
    document: {
      getElementById: id => elements[id] || values[id] || null,
    },
    window: {
      clearTimeout() {},
      setTimeout() {},
    },
    appFeedbackToastTimer: null,
    officekitIsLicenseRequiredError: value => /license_required/.test(String(value)),
    officekitReadLicenseState() {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'assets', 'officekit-outcome.js'), 'utf8'), context);
  vm.runInContext(html.slice(supportStart, supportEnd), context);
  vm.runInContext(html.slice(toastStart, toastEnd), context);

  // Non-error state keeps report bug CTA hidden
  context.showAppFeedbackToast('Processing files…', 'working');
  assert.equal(reportBtnClasses.has('hidden'), true);

  // Error state shows report bug CTA
  context.showAppFeedbackToast('Conversion failed: invalid input format', 'error');
  assert.equal(reportBtnClasses.has('hidden'), false);
  assert.equal(reportBtnClasses.has('inline-flex'), true);
  assert.equal(elements['app-feedback-text'].textContent, 'Conversion failed: invalid input format');

  // Triggering reportToastBug dismisses toast and opens bug report dialog pre-filled with context
  context.reportToastBug();
  assert.equal(toastClasses.has('hidden'), true);
  assert.equal(supportModalClasses.has('hidden'), false);
  assert.equal(values['ticket-type'].value, 'bug');
  assert.match(values['ticket-title'].value, /Bug report.*Conversion failed/);
  assert.match(values['ticket-desc'].value, /Error message:\s*Conversion failed: invalid input format/);
  assert.match(values['ticket-desc'].value, /Tool context:/);
  assert.match(values['ticket-desc'].value, /What happened \/ steps taken:/);
});

test('failure dialog (crash modal) Report bug action opens pre-filled support modal with diagnostic stack trace', () => {
  const crashModalClasses = new Set();
  const supportModalClasses = new Set(['hidden']);

  const elements = {
    'crash-modal': {
      classList: {
        add: cls => crashModalClasses.add(cls),
        remove: cls => crashModalClasses.delete(cls),
        contains: cls => crashModalClasses.has(cls),
      },
    },
    'crash-summary-msg': { textContent: 'PDF Protection Failed: Buffer overflow in stream' },
    'crash-stacktrace-box': { textContent: 'Stack trace at officekit/engines/pdf.py:42 in encrypt_stream' },
    'crash-report-status': { textContent: '', classList: { add() {}, remove() {} } },
    'copy-crash-btn': { disabled: false },
    'support-modal': {
      classList: {
        add: cls => supportModalClasses.add(cls),
        remove: cls => supportModalClasses.delete(cls),
        contains: cls => supportModalClasses.has(cls),
      },
    },
    'ticket-type': { value: '' },
    'ticket-title': { value: '' },
    'ticket-desc': { value: '', focus() {} },
    'ticket-display-name-field': { classList: { toggle() {} } },
    'ticket-publication-consent-field': { classList: { toggle() {} } },
    'support-status': { textContent: '', dataset: {}, classList: { toggle() {}, add() {}, remove() {} }, setAttribute() {} },
  };

  const crashStart = html.indexOf('        function showAppleCrashReport(diagnostic, userErrorMsg) {');
  const crashEnd = html.indexOf('        // ==========================================\n        // Global Search Palette', crashStart);
  assert.ok(crashStart > 0 && crashEnd > crashStart);

  const supportStart = html.indexOf('        function openSupportModal() {');
  const supportEnd = html.indexOf("        window.addEventListener('DOMContentLoaded', async () => {", supportStart);
  assert.ok(supportStart > 0 && supportEnd > supportStart);

  const context = {
    document: { getElementById: id => elements[id] || null },
    navigator: { clipboard: { writeText: async () => {} } },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'assets', 'officekit-outcome.js'), 'utf8'), context);
  vm.runInContext(html.slice(supportStart, supportEnd), context);
  vm.runInContext(html.slice(crashStart, crashEnd), context);

  // Trigger reportCrashBug
  context.reportCrashBug();

  // Crash modal closed and support modal opened
  assert.equal(crashModalClasses.has('hidden'), true);
  assert.equal(supportModalClasses.has('hidden'), false);

  // Bug report dialog is pre-filled with context and stack trace, ready to submit
  assert.equal(elements['ticket-type'].value, 'bug');
  assert.match(elements['ticket-title'].value, /Bug report.*Buffer overflow/);
  assert.match(elements['ticket-desc'].value, /PDF Protection Failed: Buffer overflow in stream/);
  assert.match(elements['ticket-desc'].value, /Technical details:\s*Stack trace at officekit\/engines\/pdf\.py:42/);
  assert.ok(elements['ticket-title'].value.length <= 160);
  assert.ok(elements['ticket-desc'].value.length <= 20000);
});

test('status helpers attach Report bug CTA when reporting an error and clicking it opens pre-filled dialog', () => {
  function makeMockElement() {
    const children = [];
    return {
      children,
      textContent: '',
      className: '',
      dataset: {},
      setAttribute() {},
      classList: {
        toggle(cls, val) { if (val) this.add(cls); else this.remove(cls); },
        add(cls) { this[cls] = true; },
        remove(cls) { delete this[cls]; },
        remove(cls) { delete this[cls]; },
        contains(cls) { return Boolean(this[cls]); },
      },
      appendChild(child) { children.push(child); return child; },
      querySelector(sel) { return children.find(c => c.className?.includes(sel.replace('.', ''))) || null; },
      setAttribute(k, v) { this[k] = v; },
      removeAttribute(k) { delete this[k]; },
    };
  }

  const pdfStatus = makeMockElement();
  const workspaceStatus = makeMockElement();
  const converterStatus = makeMockElement();
  const zipStatus = makeMockElement();
  const piiStatus = makeMockElement();

  const supportModalClasses = new Set(['hidden']);
  const supportElements = {
    'support-modal': {
      classList: {
        add: cls => supportModalClasses.add(cls),
        remove: cls => supportModalClasses.delete(cls),
        contains: cls => supportModalClasses.has(cls),
      },
    },
    'ticket-type': { value: '' },
    'ticket-title': { value: '' },
    'ticket-desc': { value: '', focus() {} },
    'ticket-display-name-field': { classList: { toggle() {} } },
    'ticket-publication-consent-field': { classList: { toggle() {} } },
    'support-status': { textContent: '', dataset: {}, classList: { toggle() {}, add() {}, remove() {} }, setAttribute() {} },
    'pdf-workbench-status': pdfStatus,
    'workspace-status': workspaceStatus,
    'converter-status': converterStatus,
    'zip-workspace-status': zipStatus,
    'pii-status': piiStatus,
  };

  const supportStart = html.indexOf('        function openSupportModal() {');
  const supportEnd = html.indexOf("        window.addEventListener('DOMContentLoaded', async () => {", supportStart);
  assert.ok(supportStart > 0 && supportEnd > supportStart);

  const context = {
    document: {
      getElementById: id => supportElements[id] || null,
      createElement: tag => ({
        tag,
        className: '',
        innerHTML: '',
        setAttribute(k, v) { this[k] = v; },
      }),
    },
    activePdfTool: 'protect',
    PDF_TOOL_COPY: {
      protect: { id: 'pdf_protect', title: 'Protect PDF' },
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'assets', 'officekit-outcome.js'), 'utf8'), context);
  vm.runInContext(html.slice(supportStart, supportEnd), context);

  // Helper function to test status updates
  const setPdfWorkbenchStatusSrc = html.match(/function setPdfWorkbenchStatus\([\s\S]*?\n        \}/)?.[0];
  const setWorkspaceStatusSrc = html.match(/function setWorkspaceStatus\([\s\S]*?\n        \}/)?.[0];
  const setGenericConverterStatusSrc = html.match(/function setGenericConverterStatus\([\s\S]*?\n        \}/)?.[0];
  const setZipWorkspaceStatusSrc = html.match(/function setZipWorkspaceStatus\([\s\S]*?\n        \}/)?.[0];
  const officekitPiiStatusSrc = html.match(/function officekitPiiStatus\([\s\S]*?\n        \}/)?.[0];

  assert.ok(setPdfWorkbenchStatusSrc);
  assert.ok(setWorkspaceStatusSrc);
  assert.ok(setGenericConverterStatusSrc);
  assert.ok(setZipWorkspaceStatusSrc);
  assert.ok(officekitPiiStatusSrc);

  vm.runInContext(fs.readFileSync(path.join(root, 'assets', 'officekit-outcome.js'), 'utf8'), context);
  vm.runInContext(setPdfWorkbenchStatusSrc, context);
  vm.runInContext(setWorkspaceStatusSrc, context);
  vm.runInContext(setGenericConverterStatusSrc, context);
  vm.runInContext(setZipWorkspaceStatusSrc, context);
  vm.runInContext(officekitPiiStatusSrc, context);

  // Normal messages do not attach CTA
  context.setPdfWorkbenchStatus('Ready to protect');
  assert.equal(pdfStatus.children.length, 0);

  // Error messages attach CTA button
  context.setPdfWorkbenchStatus('Password must be at least 6 characters', true);
  assert.equal(pdfStatus.children.length, 1);
  const pdfCta = pdfStatus.children[0];
  assert.match(pdfCta.className, /officekit-bug-report-cta/);
  assert.match(pdfCta.innerHTML, /Report bug/);

  // Clicking the CTA opens the bug report modal with tool context and metadata
  pdfCta.onclick({ preventDefault() {}, stopPropagation() {} });
  assert.equal(supportModalClasses.has('hidden'), false);
  assert.equal(supportElements['ticket-type'].value, 'bug');
  assert.match(supportElements['ticket-title'].value, /Protect PDF.*Password must be at least 6 characters/);
  assert.match(supportElements['ticket-desc'].value, /Tool: Protect PDF/);

  // Test other status helpers attach CTA on error
  context.setWorkspaceStatus('Failed to scan workspace duplicates', true);
  assert.equal(workspaceStatus.children.length, 1);
  assert.match(workspaceStatus.children[0].className, /officekit-bug-report-cta/);

  context.setGenericConverterStatus('Image conversion error', true);
  assert.equal(converterStatus.children.length, 1);
  assert.match(converterStatus.children[0].className, /officekit-bug-report-cta/);

  context.setZipWorkspaceStatus('Corrupted archive', true);
  assert.equal(zipStatus.children.length, 1);
  assert.match(zipStatus.children[0].className, /officekit-bug-report-cta/);

  context.officekitPiiStatus('PII detection backend unavailable', true);
  assert.equal(piiStatus.children.length, 1);
  assert.match(piiStatus.children[0].className, /officekit-bug-report-cta/);
});

test('Report bug is for failures only: ready and preparing model messages are not errors, and red buttons are skipped', () => {
  const helper = html.match(/function dictationModelOutcomeState\(modelState\) \{([\s\S]*?)\n        \}/)?.[1] ?? '';
  assert.match(helper, /'failed'\) return 'error'/);
  assert.match(helper, /'ready'\) return 'success'/);
  assert.match(helper, /'preparing'\) return 'working'/);
  assert.doesNotMatch(html, /officekitOutcome\.show\([^;]*dictation-model-status[^;]*state: 'error', text: status\.message/);
  assert.doesNotMatch(html, /officekitOutcome\.show\(statusElement, \{ state: 'error', text: status\.message \}\);\s+renderDictationModelProgress/);
  assert.match(html, /el\?\.closest\?\.\('button, a, summary'\)\) continue;/);
});
