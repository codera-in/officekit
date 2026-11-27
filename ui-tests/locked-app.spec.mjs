import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';
import { setNativeLicenseState, stubNativeLicense } from './license-state.mjs';

const COPY = {
  locked: {
    word: 'Activate',
    title: 'Activate OfficeKit to use your tools',
    text: 'Calculators, Converters and Developer tools are free. Activate to unlock the rest.',
    keep: 'Use the Activate button with the email you purchased with and the license key we sent you. Support stays available.',
  },
  expired: {
    word: 'Reactivate',
    title: 'OfficeKit could not confirm your license',
    text: '',
    keep: 'Calculators, Converters and Developer tools stay free. Support stays available.',
  },
  revoked: {
    word: 'Activate',
    title: 'This license is no longer active',
    text: 'It was refunded or revoked. If that looks wrong, contact us with the Help button and we will sort it out.',
    keep: 'Calculators, Converters and Developer tools stay free. Support stays available.',
  },
  checking: { word: 'Checking', title: 'Checking your license', text: '', keep: '' },
};
// Sentences the owner struck on 2026-10-22: approved banner copy only.
const REMOVED_SENTENCES = ['This takes a moment and works offline.', 'Connect to the internet and reopen OfficeKit'];

async function openLockedApp(page, state) {
  const problems = [];
  page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
  page.on('console', message => { if (message.type() === 'error') problems.push(`console: ${message.text()}`); });
  await stubNativeLicense(page, state);
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  return problems;
}

async function openToolsTab(page) {
  await page.evaluate(() => switchTab('tools'));
  await expect(page.locator('#tool-gallery-results article').first()).toBeVisible();
}

const card = (page, id) => page.locator(`#tool-gallery-results [data-card-tool="${id}"]`);

test('locked app: banner, badge, hidden update controls, chips and the guarded entry points', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');

  // The load-time native calls (window snap, global desktop, dictation) are all rejected with
  // license_required by the stub: nothing may surface as a toast or a notice.
  expect(await page.evaluate(() => window.__officekitInvokeLog)).toContain('window_snap_set_edge_enabled');
  await expect(page.locator('#app-feedback-toast')).toBeHidden();
  await expect(page.locator('#record-store-notice')).toBeHidden();
  await expect(page.locator('#license-status-text')).toHaveText('Activate');
  const notice = page.locator('#license-lock-notice');
  await expect(notice).toHaveAttribute('role', 'status');
  await expect(notice).toHaveAttribute('aria-live', 'polite');
  await expect(notice).toContainText(COPY.locked.title);
  await expect(notice).toContainText(COPY.locked.text);
  await expect(notice).toContainText(COPY.locked.keep);
  await expect(page.locator('#announcement-banner-content')).toBeHidden();
  await expect(notice.getByRole('button')).toHaveCount(0);
  await expect(page.locator('#update-check-button')).toBeHidden();
  await expect(page.locator('#update-badge-dot')).toBeHidden();

  await openToolsTab(page);
  const paidName = await page.evaluate(() => allToolsCache.find(tool => tool.id === 'pdf_merge').name);
  const paid = card(page, 'pdf_merge');
  await expect(paid.locator('[data-license-chip]')).toHaveText('Locked');
  const paidButton = paid.locator('[data-open-tool]');
  await expect(paidButton).toBeEnabled();
  await expect(paidButton).toHaveAttribute('aria-label', `Open ${paidName}, locked: activation needed`);
  await expect(card(page, 'loan_emi').locator('[data-license-chip]')).toHaveCount(0);
  await expect(card(page, 'loan_emi').locator('[data-open-tool]')).toHaveAttribute('aria-label', /^Open /);
  expect(await page.locator('#tool-gallery-results article:not(:has([data-license-chip]))').count()).toBeGreaterThan(0);

  // A locked card opens the activation modal with the exact status line and never opens the tool.
  await paidButton.click();
  await expect(page.getByRole('dialog', { name: 'Activate OfficeKit' })).toBeVisible();
  await expect(page.locator('#license-activation-status')).toHaveText(`Activate OfficeKit to use ${paidName}.`);
  await expect(page.locator('#tab-pdf')).toBeHidden();
  await expect(page.locator('#license-email')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('#license-modal')).toBeHidden();

  // Keyboard path: Enter on the focused card button, and Escape returns focus to it.
  await paidButton.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#license-modal')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(paidButton).toBeFocused();

  // A free tool opens as it always did.
  await card(page, 'loan_emi').locator('[data-open-tool]').click();
  await expect(page.locator('#tab-calculators')).toBeVisible();
  await expect(page.locator('#license-modal')).toBeHidden();

  // Settings is locked the same way.
  const settings = page.locator('[data-sidebar-tab="settings"]');
  await expect(settings).toHaveAttribute('aria-label', 'Settings, locked: activation needed');
  await page.evaluate(() => document.querySelector('[data-sidebar-tab="settings"]').click());
  await expect(page.locator('#license-activation-status')).toHaveText('Activate OfficeKit to use Settings.');
  await expect(page.locator('#tab-settings')).toBeHidden();
  await page.keyboard.press('Escape');

  // The Activate badge and Help stay reachable.
  await page.locator('#license-badge-btn').click();
  await expect(page.locator('#license-modal')).toBeVisible();
  await expect(page.locator('#license-activation-status')).toHaveText('');
  await page.keyboard.press('Escape');
  await page.getByTitle('Help & Bug Report').click();
  await expect(page.locator('#support-modal')).toBeVisible();

  expect(problems).toEqual([]);
});

test('locked app: search, deep links and the launcher all end at the activation modal', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');
  const paidName = await page.evaluate(() => allToolsCache.find(tool => tool.id === 'pdf_merge').name);

  await page.evaluate(() => openGlobalSearchModal());
  await page.locator('#global-search-input').fill('merge pdf');
  const row = page.locator('#search-results-list [data-tool-id="pdf_merge"]');
  await expect(row).toBeVisible();
  await expect(row.locator('[data-license-chip]')).toHaveText('Locked');
  await expect(row).toHaveAttribute('aria-label', `Open ${paidName}, locked: activation needed`);
  await row.click();
  await expect(page.locator('#search-modal')).toBeHidden();
  await expect(page.locator('#license-activation-status')).toHaveText(`Activate OfficeKit to use ${paidName}.`);
  await page.keyboard.press('Escape');

  // Deep link and launcher paths call selectSearchTool / openPdfTool / switchTab directly.
  expect(await page.evaluate(() => selectSearchTool('pdf_merge'))).toBeNull();
  expect(await page.evaluate(() => openPdfTool('merge'))).toBe(false);
  expect(await page.evaluate(() => switchTab('screenshot'))).toBe(false);
  await expect(page.locator('#license-modal')).toBeVisible();
  await expect(page.locator('#tab-pdf')).toBeHidden();
  await expect(page.locator('#tab-screenshot')).toBeHidden();
  expect(await page.evaluate(() => selectSearchTool('loan_emi'))).toBe(true);
  expect(problems).toEqual([]);
});

for (const state of ['expired', 'revoked']) {
  test(`${state} app: ${state} copy, badge word, chips stay and free tools stay usable`, async ({ page }) => {
    const problems = await openLockedApp(page, state);
    await expect(page.locator('#license-status-text')).toHaveText(COPY[state].word);
    await expect(page.locator('#license-lock-notice')).toContainText(COPY[state].title);
    await expect(page.locator('#license-lock-notice')).toContainText(COPY[state].text);
    await expect(page.locator('#license-lock-notice')).toContainText(COPY[state].keep);
    for (const sentence of REMOVED_SENTENCES) await expect(page.locator('#license-lock-notice')).not.toContainText(sentence);
    await expect(page.locator('#update-check-button')).toBeHidden();
    await openToolsTab(page);
    await expect(card(page, 'pdf_merge').locator('[data-license-chip]')).toHaveCount(1);
    expect(await page.evaluate(() => selectSearchTool('loan_emi'))).toBe(true);
    await expect(page.locator('#tab-calculators')).toBeVisible();
    expect(problems).toEqual([]);
  });
}

test('locked app: Clipboard & Snippets Studio is a locked studio like the others', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');
  // The studio has no sidebar entry any more; it is reached from the Tools list.
  await openToolsTab(page);
  await expect(card(page, 'clipboard_manager').locator('[data-license-chip]')).toHaveText('Locked');
  await card(page, 'clipboard_manager').locator('[data-open-tool]').click();
  await expect(page.locator('#license-activation-status')).toHaveText('Activate OfficeKit to use Clipboard & Snippets Studio.');
  await expect(page.locator('#tab-clipboard')).toBeHidden();
  expect(problems).toEqual([]);
});

test('locked app: Open Media Toolkit in the free converter opens the activation modal, not the paid panel', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');
  await page.evaluate(() => switchTab('converter', true));
  const open = page.locator('#open-media-toolkit');
  await expect(open).toBeVisible();
  await open.click();
  await expect(page.locator('#license-activation-status')).toHaveText('Activate OfficeKit to use Media Toolkit.');
  await expect(page.locator('#media-toolkit-panel')).toBeHidden();
  await expect(open).toBeVisible();
  await page.keyboard.press('Escape');
  await page.evaluate(() => { setConverterMode('url_codec'); });
  await expect(page.locator('#url-codec-panel')).toBeVisible();
  await expect(page.locator('#license-modal')).toBeHidden();
  expect(problems).toEqual([]);
});

test('locked app: the App Tour keeps every step and never opens the activation modal over itself', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');
  await page.evaluate(() => window.startAppTour());
  const tour = page.getByRole('dialog', { name: 'OfficeKit Tour' });
  await expect(tour).toBeVisible();
  const badges = [];
  for (let step = 0; step < 7; step += 1) {
    badges.push(await page.locator('#officekit-tour-badge').textContent());
    await expect(page.locator('#license-modal')).toBeHidden();
    await expect(tour).toBeVisible();
    if (step < 6) await page.locator('#officekit-tour-next').click();
  }
  expect(badges.map(badge => badge.match(/Step (\d) of 7/)?.[1])).toEqual(['1', '2', '3', '4', '5', '6', '7']);
  await expect(page.locator('#tab-dictate')).toBeHidden();
  await expect(page.locator('#tab-workspace')).toBeHidden();
  await expect(page.locator('#tab-clipboard')).toBeHidden();
  expect(problems).toEqual([]);
});

test('locked app: the Jump Right Back In cards are the same height locked, free or checking', async ({ page }) => {
  const problems = await openLockedApp(page, 'checking');
  const heights = async () => page.evaluate(() => [...document.querySelectorAll('[data-license-tool]')].map(button => Math.round(button.getBoundingClientRect().height)));
  const checking = await heights();
  expect(new Set(checking).size).toBe(1);
  await setNativeLicenseState(page, 'locked');
  await expect(page.locator('[data-license-tool="screenshot_editor"] [data-license-chip]')).toHaveText('Locked');
  const locked = await heights();
  expect(locked).toEqual(checking);
  const sameRow = await page.evaluate(() => {
    const chip = document.querySelector('[data-license-tool="screenshot_editor"] [data-license-chip]').getBoundingClientRect();
    const name = document.querySelector('[data-license-tool="screenshot_editor"] .truncate').getBoundingClientRect();
    return Math.abs((chip.top + chip.bottom) / 2 - (name.top + name.bottom) / 2) < 6;
  });
  expect(sameRow, 'the chip sits on the title row').toBe(true);
  expect(problems).toEqual([]);
});

test('checking: neutral banner and badge, no Locked chips yet, then the result replaces them', async ({ page }) => {
  const problems = await openLockedApp(page, 'checking');
  await expect(page.locator('#license-status-text')).toHaveText(COPY.checking.word);
  await expect(page.locator('#license-lock-notice')).toContainText(COPY.checking.title);
  for (const sentence of REMOVED_SENTENCES) await expect(page.locator('#license-lock-notice')).not.toContainText(sentence);
  await openToolsTab(page);
  await expect(page.locator('#tool-gallery-results [data-license-chip]')).toHaveCount(0);
  await expect(card(page, 'pdf_merge')).toHaveAttribute('aria-busy', 'true');
  await expect(card(page, 'loan_emi')).not.toHaveAttribute('aria-busy', 'true');
  await setNativeLicenseState(page, 'locked');
  await expect(page.locator('#license-lock-notice')).toContainText(COPY.locked.title);
  await expect(card(page, 'pdf_merge').locator('[data-license-chip]')).toHaveCount(1);
  expect(problems).toEqual([]);
});

test('checking: a tap on a locked tool waits for the result, then proceeds or opens the modal', async ({ page }) => {
  await openLockedApp(page, 'checking');
  await openToolsTab(page);
  const paidName = await page.evaluate(() => allToolsCache.find(tool => tool.id === 'pdf_merge').name);
  await card(page, 'pdf_merge').locator('[data-open-tool]').click();
  await expect(page.locator('#license-modal')).toBeHidden();
  await page.evaluate(() => { window.__officekitLicenseState = 'active'; });
  await expect(page.locator('#tab-pdf')).toBeVisible();
  await expect(page.locator('#license-modal')).toBeHidden();

  await page.evaluate(() => { window.__officekitLicenseState = 'checking'; return checkLicenseStatus(); });
  await page.evaluate(() => switchTab('tools'));
  await page.evaluate(() => { window.__officekitLicenseState = 'checking'; });
  await card(page, 'pdf_merge').locator('[data-open-tool]').click();
  await expect(page.locator('#license-modal')).toBeHidden();
  await page.evaluate(() => { window.__officekitLicenseState = 'locked'; });
  await expect(page.locator('#license-activation-status')).toHaveText(`Activate OfficeKit to use ${paidName}.`);
});

test('active app: the chip says Activated and opens the license details, not the activation form', async ({ page }) => {
  await openLockedApp(page, 'active');
  await expect(page.locator('#license-status-text')).toHaveText('Activated');
  await page.locator('#license-badge-btn').click();
  await expect(page.locator('#license-details-modal')).toBeVisible();
  await expect(page.locator('#license-modal')).toBeHidden();
  await expect(page.locator('#license-details-devices')).toHaveText('1 of 3 used');
  // Deactivate this Mac is a text link, which the 3-button limit does not count.
  await expect(page.locator('#license-details-modal button:not(.ok-text-link):visible')).toHaveCount(3);
  await expect(page.locator('#license-deactivate-link')).toBeVisible();
  await page.locator('#license-details-close').click();
  await expect(page.locator('#license-details-modal')).toBeHidden();
});

test('active app: Deactivate this Mac asks for the email and key, tells the service, then locks', async ({ page }) => {
  const problems = await openLockedApp(page, 'active');
  await page.locator('#license-badge-btn').click();
  await page.locator('#license-deactivate-link').click();
  const confirm = page.locator('#license-deactivate-modal');
  await expect(confirm).toBeVisible();
  await expect(page.locator('#license-details-modal')).toBeHidden();
  await expect(confirm.locator('button:not(.ok-text-link):visible')).toHaveCount(3);

  // Nothing is sent until both fields are filled in.
  await page.locator('#license-deactivate-submit').click();
  await expect(page.locator('#license-deactivate-status')).toHaveText('Enter the email you purchased with to continue.');
  await page.locator('#license-deactivate-email').fill('buyer@example.com');
  await page.locator('#license-deactivate-submit').click();
  await expect(page.locator('#license-deactivate-status')).toHaveText('Enter your license key to continue.');
  expect(await page.evaluate(() => window.__officekitDeactivateCalls.length)).toBe(0);

  // Cancel goes back to the details, still activated, and clears what was typed.
  await page.locator('#license-deactivate-cancel').click();
  await expect(confirm).toBeHidden();
  await expect(page.locator('#license-details-modal')).toBeVisible();
  await page.locator('#license-deactivate-link').click();
  await expect(page.locator('#license-deactivate-email')).toHaveValue('');
  expect(await page.evaluate(() => window.__officekitDeactivateCalls.length)).toBe(0);

  await page.locator('#license-deactivate-email').fill('buyer@example.com');
  await page.locator('#license-deactivate-key').fill('OK1.reference.secret');
  await page.locator('#license-deactivate-submit').click();
  await expect(confirm).toBeHidden();
  expect(await page.evaluate(() => window.__officekitDeactivateCalls)).toEqual([{ email: 'buyer@example.com', licenseKey: 'OK1.reference.secret' }]);
  await expect(page.locator('#license-lock-notice')).toContainText(COPY.locked.title);
  await expect(page.locator('#license-status-text')).not.toHaveText('Activated');
  expect(problems.filter(problem => !problem.includes('403'))).toEqual([]);
});

test('active app: a deactivation that fails changes nothing and offers Try again', async ({ page }) => {
  await openLockedApp(page, 'active');
  await page.evaluate(() => { window.__officekitDeactivateError = 'The licensing service is unavailable. Try again when you are online.'; });
  await page.locator('#license-badge-btn').click();
  await page.locator('#license-deactivate-link').click();
  await page.locator('#license-deactivate-email').fill('buyer@example.com');
  await page.locator('#license-deactivate-key').fill('OK1.reference.secret');
  await page.locator('#license-deactivate-submit').click();
  await expect(page.locator('#license-deactivate-status')).toContainText('Nothing was changed and this Mac is still activated');
  await expect(page.locator('#license-deactivate-submit')).toHaveText('Try again');
  await expect(page.locator('#license-deactivate-modal')).toBeVisible();
  await expect(page.locator('#license-lock-notice')).toBeEmpty();

  // A wrong email or key shows the service's own message and keeps the label.
  await page.evaluate(() => { window.__officekitDeactivateError = 'The email or license key is not valid. Check both and try again.'; });
  await page.locator('#license-deactivate-submit').click();
  await expect(page.locator('#license-deactivate-status')).toHaveText('The email or license key is not valid. Check both and try again.');
  await expect(page.locator('#license-deactivate-submit')).toHaveText('Deactivate');

  // Closing returns to the details, still activated.
  await page.locator('#license-deactivate-cancel').click();
  await expect(page.locator('#license-details-modal')).toBeVisible();
  await expect(page.locator('#license-status-text')).toHaveText('Activated');
});

test('active app: announcement banner, update check and Activated badge are unchanged and nothing is locked', async ({ page }) => {
  const problems = await openLockedApp(page, 'active');
  await expect(page.locator('#license-status-text')).toHaveText('Activated');
  await expect(page.locator('#license-lock-notice')).toBeEmpty();
  await expect(page.locator('#announcement-banner-content')).toBeVisible();
  await expect(page.locator('#update-check-button')).toBeVisible();
  await openToolsTab(page);
  await expect(page.locator('[data-license-chip]')).toHaveCount(0);
  await expect(page.locator('[data-sidebar-tab="settings"]')).not.toHaveAttribute('aria-label', /locked/);
  expect(await page.evaluate(() => openPdfTool('merge'))).toBe(true);
  await expect(page.locator('#tab-pdf')).toBeVisible();
  expect(problems).toEqual([]);
});

test('locking and unlocking move the update controls and the banner both ways', async ({ page }) => {
  await openLockedApp(page, 'active');
  await expect(page.locator('#update-check-button')).toBeVisible();
  await setNativeLicenseState(page, 'revoked');
  await expect(page.locator('#update-check-button')).toBeHidden();
  await expect(page.locator('#license-lock-notice')).toContainText(COPY.revoked.title);
  await setNativeLicenseState(page, 'active');
  await expect(page.locator('#update-check-button')).toBeVisible();
  await expect(page.locator('#license-lock-notice')).toBeEmpty();
  await expect(page.locator('#announcement-banner-content')).toBeVisible();
  await expect(page.locator('#license-status-text')).toHaveText('Activated');
});

test('a rejected native command and a license_required 403 are handled quietly and re-read the state', async ({ page }) => {
  const problems = await openLockedApp(page, 'active');
  await page.route('**/api/system/metrics', route => route.fulfill({
    status: 403,
    contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'license_required', message: 'An active OfficeKit licence is required.' } }),
  }));
  const reads = () => page.evaluate(() => window.__officekitInvokeLog.filter(command => command === 'license_state').length);
  const before = await reads();
  await page.evaluate(() => { window.__officekitLicenseState = 'locked'; });
  await page.evaluate(async () => { await fetch('/api/system/metrics'); });
  await expect.poll(reads).toBeGreaterThan(before);
  await expect(page.locator('#license-lock-notice')).toContainText(COPY.locked.title);

  const afterFetch = await reads();
  await page.evaluate(() => { void window.__TAURI__.core.invoke('tray_stats_update', { text: '' }); });
  await expect.poll(reads).toBeGreaterThan(afterFetch);
  expect(problems.filter(problem => !problem.includes('403'))).toEqual([]);
});

test('a license_required rejection never reaches the feedback toast, but other errors still do', async ({ page }) => {
  const problems = await openLockedApp(page, 'locked');
  const toast = page.locator('#app-feedback-toast');
  await page.evaluate(() => {
    showAppFeedbackToast('license_required', 'error');
    showAppFeedbackToast(new Error('license_required'), 'error');
  });
  await expect(toast).toBeHidden();
  await expect(page.locator('.ok-error-dialog[open]')).toHaveCount(0);
  await page.evaluate(() => showAppFeedbackToast('The local store rejected the request', 'error'));
  await expect(toast).toBeVisible();
  await expect(page.locator('#app-feedback-text')).toHaveText('The local store rejected the request');
  expect(problems).toEqual([]);
});

test.describe('phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the locked banner and Locked chips fit without horizontal scroll and keep 44px targets', async ({ page }) => {
    const problems = await openLockedApp(page, 'locked');
    await expect(page.locator('#license-lock-notice')).toContainText(COPY.locked.title);
    await openToolsTab(page);
    await expect(card(page, 'pdf_merge').locator('[data-license-chip]')).toHaveText('Locked');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    for (const locator of [page.locator('#license-badge-btn'), card(page, 'pdf_merge').locator('[data-open-tool]')]) {
      const box = await locator.boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    expect(problems).toEqual([]);
  });
});
