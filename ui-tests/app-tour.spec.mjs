import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: {
        ...route.request().headers(),
        authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`
      }
    });
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

test('Title bar cleanup: mic and activity removed, tour button added', async ({ page }) => {
  const headerActions = page.locator('.ok-header-actions');
  await expect(headerActions).toBeVisible();

  // Microphone button removed from title bar
  await expect(headerActions.locator('button[data-officekit-click*="dictate"]')).toHaveCount(0);
  
  // Activity trigger removed from title bar
  await expect(headerActions.locator('#officekit-activity-trigger')).toHaveCount(0);

  // App Tour button is present on title bar
  const tourBtn = headerActions.locator('#officekit-tour-trigger');
  await expect(tourBtn).toBeVisible();
  await expect(tourBtn).toContainText('Tour');
  await expect(tourBtn.locator('i.fa-compass')).toBeVisible();

  // The sidebar is six rows: Speech-to-Text is a starter favorite, not a menu row.
  await expect(page.locator('[data-sidebar-tab="dictate"]')).toHaveCount(0);

  const sidebarActivity = page.locator('[data-sidebar-tab="activity"]');
  await expect(sidebarActivity).toBeVisible();
  await expect(sidebarActivity).toContainText('Activity');
});

test('Activity tab renders simplified clean empty state', async ({ page }) => {
  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('#tab-activity')).toBeVisible();

  const activityContent = page.locator('#officekit-activity-content');
  await expect(activityContent).toBeVisible();
  
  // Clean unified empty state card
  await expect(activityContent.locator('.ok-activity-empty-card')).toBeVisible();
  await expect(activityContent).toContainText('No active operations');
  await expect(activityContent).toContainText('Background tasks and recent results will appear here as you work.');

  // Verify legacy double empty headings are gone
  await expect(activityContent).not.toContainText('Running · 0');
  await expect(activityContent).not.toContainText('Completed operations stay here while OfficeKit is open.');
});

test('App Tour end-to-end walkthrough covering Privacy, STT, System Rights, Window HUD, Storage, and Activity', async ({ page }) => {
  // Launch tour from title bar
  await page.locator('#officekit-tour-trigger').click();
  const modal = page.locator('#officekit-tour-modal');
  await expect(modal).toBeVisible();

  // Step 1: On-Device Privacy
  const spotlight = modal.locator('#officekit-tour-spotlight');
  await expect(spotlight).toBeVisible();
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 1 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('100% Private & On-Device');
  await expect(modal.locator('#officekit-tour-desc')).toContainText('Mac');

  // Step 2: Spotlight Search (⌘K)
  await modal.locator('#officekit-tour-next').click();
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 2 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Spotlight Quick Search');

  // Step 3: STT & System Rights (Microphone & Accessibility) via keyboard ArrowRight
  await page.keyboard.press('ArrowRight');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 3 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Speech-to-Text & System Rights');
  await expect(modal.locator('#officekit-tour-desc')).toContainText('Accessibility');
  await expect(modal.locator('#officekit-tour-desc')).toContainText('Microphone');
  await expect(page.locator('#tab-dictate h1, #tab-dictate h2').first()).toHaveClass(/ok-tour-highlight/);
  await expect(page.locator('#tab-dictate')).toBeVisible();

  // Step 4: Clipboard History & Snippets Studio
  await page.keyboard.press('ArrowRight');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 4 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Clipboard History & Snippets Studio');
  await expect(modal.locator('#officekit-tour-desc')).toContainText('⌥V');
  await expect(page.locator('#tab-clipboard h1, #tab-clipboard h2').first()).toHaveClass(/ok-tour-highlight/);
  await expect(page.locator('#tab-clipboard')).toBeVisible();

  // Step 5: Window Arrangement & Floating HUD
  await page.keyboard.press('ArrowRight');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 5 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Floating HUD & Menu Bar');

  // Step 6: Storage & Local Cleanup
  await page.keyboard.press('ArrowRight');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 6 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Storage Analyzer & Local Cleanup');
  await expect(page.locator('#tab-workspace h1, #tab-workspace h2').first()).toHaveClass(/ok-tour-highlight/);
  await expect(page.locator('#tab-workspace')).toBeVisible();

  // Step 7: Activity Monitor
  await page.keyboard.press('ArrowRight');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 7 of 7');
  await expect(modal.locator('#officekit-tour-title')).toContainText('Live Activity Monitor');
  await expect(page.locator('[data-sidebar-tab="activity"]')).toHaveClass(/ok-tour-highlight/);
  await expect(page.locator('#tab-activity')).toBeVisible();

  // Step backwards with ArrowLeft
  await page.keyboard.press('ArrowLeft');
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 6 of 7');

  // Step forward to Step 7 and finish with "Get Started"
  await modal.locator('#officekit-tour-next').click();
  await expect(modal.locator('#officekit-tour-next')).toContainText('Get Started');
  
  // Toggle "Don't show on start" checkbox
  await modal.locator('#officekit-tour-dont-show').check();
  const seenPref = await page.evaluate(() => localStorage.getItem('officekit.tour.seen_v1'));
  expect(seenPref).toBe('true');

  // Finish tour
  await modal.locator('#officekit-tour-next').click();
  await expect(modal).toBeHidden();
  await expect(page.locator('.ok-tour-highlight')).toHaveCount(0);

  // Reopening tour and testing Escape key dismiss
  await page.locator('#officekit-tour-trigger').click();
  await expect(modal).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();
  await expect(page.locator('.ok-tour-highlight')).toHaveCount(0);
});

test('Auto-start flow: triggers on fresh install, re-triggers on version update, respects user preference', async ({ page }) => {
  // 1. Fresh install auto-start check
  const freshInstallAutoStart = await page.evaluate(() => {
    localStorage.clear();
    return OfficeKitTour.shouldAutoStart({ allowInTests: true });
  });
  expect(freshInstallAutoStart).toBe(true);

  // Trigger auto-start on fresh install
  await page.evaluate(() => {
    OfficeKitTour.checkAutoStart({ force: true, immediate: true });
  });
  const modal = page.locator('#officekit-tour-modal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#officekit-tour-badge')).toContainText('Step 1 of 7');

  // Dismiss tour
  await modal.locator('#officekit-tour-close').click();
  await expect(modal).toBeHidden();

  // Seen flag and version are recorded on dismiss/completion
  const recordedSeen = await page.evaluate(() => localStorage.getItem('officekit.tour.seen_v1'));
  const recordedVersion = await page.evaluate(() => localStorage.getItem('officekit.tour.version'));
  expect(recordedSeen).toBe('true');
  const footerVersion = await page.locator('#app-build-version').innerText();
  expect(recordedVersion).toBe(footerVersion.replace('Version ', ''));

  // 2. Normal launch on the same version does NOT auto-start
  const sameVersionAutoStart = await page.evaluate(() => {
    return OfficeKitTour.shouldAutoStart({ allowInTests: true });
  });
  expect(sameVersionAutoStart).toBe(false);

  // 3. Version update auto-start check (e.g. upgraded from 0.9.0 to 1.0.0)
  const versionUpdateAutoStart = await page.evaluate(() => {
    localStorage.setItem('officekit.tour.seen_v1', 'true');
    localStorage.setItem('officekit.tour.version', '0.9.0');
    return OfficeKitTour.shouldAutoStart({ allowInTests: true });
  });
  expect(versionUpdateAutoStart).toBe(true);

  // 3b. A patch release (every merge to main) does not re-open the tour
  const patchUpdateAutoStart = await page.evaluate(() => {
    localStorage.setItem('officekit.tour.seen_v1', 'true');
    localStorage.setItem('officekit.tour.dont_show', 'false');
    localStorage.setItem('officekit.tour.version', '1.0.99');
    return OfficeKitTour.shouldAutoStart({ allowInTests: true });
  });
  expect(patchUpdateAutoStart).toBe(false);

  // 4. User preference: "Don't show on start" suppresses auto-start on current version
  const dontShowAutoStart = await page.evaluate(() => {
    localStorage.setItem('officekit.tour.seen_v1', 'true');
    localStorage.setItem('officekit.tour.version', '1.0.0');
    localStorage.setItem('officekit.tour.dont_show', 'true');
    return OfficeKitTour.shouldAutoStart({ allowInTests: true });
  });
  expect(dontShowAutoStart).toBe(false);

  // 5. Manual launch from title bar always opens tour regardless of preferences
  await page.locator('#officekit-tour-trigger').click();
  await expect(modal).toBeVisible();
  await expect(modal.locator('#officekit-tour-dont-show')).toBeChecked();
  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();
});

