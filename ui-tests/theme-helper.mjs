/** Drives the header theme icon button: 'light' or 'dark' toggles to it, 'system' uses the context menu. */
export async function setTheme(page, theme) {
  if (theme === 'system') {
    await page.locator('#officekit-theme-toggle').click({ button: 'right' });
    await page.locator('#officekit-theme-system').click();
    return;
  }
  const html = page.locator('html');
  if ((await html.getAttribute('data-theme')) !== theme) {
    await page.locator('#officekit-theme-toggle').click();
  }
  await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
}
