import { expect, test } from '@playwright/test';

for (const banner of ['hidden', 'shown']) {
  test(`the footer stays one slim line at the bottom with the announcement banner ${banner}`, async ({ page }) => {
    await page.setViewportSize({ width: 1244, height: 830 });
    await page.goto('/');
    await page.evaluate((mode) => {
      document.getElementById('inapp-announcement-banner').classList.toggle('hidden', mode === 'hidden');
    }, banner);
    const layout = await page.evaluate(() => {
      const box = (selector) => { const rect = document.querySelector(selector).getBoundingClientRect(); return { top: Math.round(rect.top), bottom: Math.round(rect.bottom), height: Math.round(rect.height) }; };
      return { shell: box('#app-shell'), footer: box('footer[role="contentinfo"]'), viewport: window.innerHeight };
    });
    expect(layout.footer.height).toBeLessThanOrEqual(40);
    expect(layout.footer.bottom).toBe(layout.viewport);
    expect(layout.shell.bottom).toBe(layout.footer.top);
    expect(layout.shell.height).toBeGreaterThan(500);
  });
}
