import {test, expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {setTheme} from './theme-helper.mjs';

test.beforeEach(async ({page}) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers:{...route.request().headers(), authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`}});
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

test('search fields focus their single outer border without an inner ring or layout shift', async ({page}, testInfo) => {
  for (const theme of ['light', 'dark']) {
    await setTheme(page, theme);
    for (const [tab, selector] of [['tools', '#tool-gallery-search']]) {
      await page.evaluate(tab => switchTab(tab), tab);
      const field = page.locator(selector);
      const before = await field.boundingBox();
      await field.focus();
      const style = await field.evaluate(input => {
        const outer = input.closest('.ok-composite-field');
        const computed = getComputedStyle(input);
        const sample = document.createElement('span'); sample.style.color = 'var(--ok-focus)'; document.body.append(sample);
        const focus = getComputedStyle(sample).color; sample.remove();
        return {hasOuter:!!outer, outline:computed.outlineStyle, shadow:computed.boxShadow,
          background:computed.backgroundColor, border:outer && getComputedStyle(outer).borderColor,
          outerOutline:outer && getComputedStyle(outer).outlineStyle, focus};
      });
      expect(style.hasOuter).toBe(true);
      expect(style.outline).toBe('none');
      expect(style.outerOutline).toBe('none');
      expect(style.shadow).toBe('none');
      expect(style.background).toBe('rgba(0, 0, 0, 0)');
      expect(style.border).toBe(style.focus);
      const after = await field.boundingBox();
      expect(after.width).toBe(before.width); expect(after.height).toBe(before.height);
      await page.screenshot({path:testInfo.outputPath(`${tab}-focus-${theme}.png`)});
    }
    await page.locator('#global-search-trigger').click();
    const palette = page.locator('#global-search-input');
    await expect(palette).toBeFocused();
    await expect(palette).toHaveCSS('outline-style', 'none');
    await expect(palette).toHaveCSS('box-shadow', 'none');
    await expect(palette.locator('xpath=..')).toHaveClass(/ok-composite-field/);
    await page.screenshot({path:testInfo.outputPath(`palette-focus-${theme}.png`)});
    await page.keyboard.press('Escape');
  }
});

test('buttons, checkboxes and ranges retain visible keyboard focus', async ({page}) => {
  for (const theme of ['light','dark']) {
    await setTheme(page, theme);
    await page.keyboard.press('Tab');
    await page.locator('#global-search-trigger').focus();
    await expect(page.locator('#global-search-trigger')).toHaveCSS('outline-style', 'solid');
    await page.evaluate(() => selectSearchTool('password_generator'));
    for (const selector of ['#password-symbols', '#password-length-range']) {
      const field=page.locator(selector);
      await field.focus();
      await expect(field).toBeFocused();
      await expect(field).toHaveCSS('outline-style', 'solid');
    }
  }
});

test('every allowed registry tool and shell screen uses a visible border-only text-field focus cue', async ({page}, testInfo) => {
  test.setTimeout(180_000);
  const registry = await page.evaluate(async () => {
    await loadToolGallery();
    return {tools:allToolsCache.map(tool => ({id:tool.id, destination:OFFICEKIT_TOOL_DESTINATIONS[tool.id]}))};
  });
  const tools = registry.tools.filter(tool => tool.destination);
  expect(tools.length).toBeGreaterThan(0);
  const shells = ['home','tools','recents','favorites','history','quick-stats','pricing'];
  const matrix = [];
  for (const theme of ['light','dark']) {
    await setTheme(page, theme);
    for (const route of [...shells.map(tab => ({tab})), ...tools]) {
      const opened = await page.evaluate(route => route.id ? selectSearchTool(route.id) : switchTab(route.tab), route);
      if (opened === false) { matrix.push({theme, route:route.id || route.tab, status:'excluded'}); continue; }
      const result = await page.evaluate(() => {
        const visible = field => field.getClientRects().length && !field.disabled && getComputedStyle(field).visibility !== 'hidden';
        const active = [...document.querySelectorAll('#app-main > section[id^="tab-"]')].find(section => section.getClientRects().length);
        const closedDetails = [...(active || document.querySelector('#app-main')).querySelectorAll('details:not([open])')];
        for (const details of closedDetails) details.open = true;
        const selector = 'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="color"]):not([type="file"]), select, textarea';
        const fields = [...(active || document.querySelector('#app-main')).querySelectorAll(selector)].filter(visible);
        const sample = document.createElement('span'); sample.style.color='var(--ok-focus)'; document.body.append(sample);
        const focus = getComputedStyle(sample).color; sample.remove();
        const measurements = fields.map((field, index) => {
          const before = field.getBoundingClientRect();
          field.focus({preventScroll:true});
          const host = field.closest('.ok-composite-field') || field;
          const style = getComputedStyle(host), inner = getComputedStyle(field), after = field.getBoundingClientRect();
          return {id:field.id || `${field.tagName.toLowerCase()}-${index}`, tag:field.tagName,
            focused:document.activeElement === field, border:style.borderColor, focus,
            borderWidth:parseFloat(style.borderTopWidth), outline:inner.outlineStyle,
            hostOutline:style.outlineStyle, shadow:inner.boxShadow,
            shifted:before.width !== after.width || before.height !== after.height};
        });
        for (const details of closedDetails) details.open = false;
        return measurements;
      });
      matrix.push({theme, route:route.id || route.tab, destination:route.destination || route.tab, fields:result,
        status:result.every(field => field.focused && field.border === field.focus && field.borderWidth >= 1 &&
          field.outline === 'none' && field.hostOutline === 'none' && field.shadow === 'none' && !field.shifted) ? 'passed' : 'failed'});
    }
  }
  const evidence=JSON.stringify({registry,matrix},null,2);
  await writeFile(testInfo.outputPath('focus-registry-matrix.json'),evidence);
  await testInfo.attach('focus-registry-matrix', {body:evidence, contentType:'application/json'});
  const failures=matrix.filter(row => row.status === 'failed').map(row => ({route:row.route, theme:row.theme,
    fields:row.fields.filter(field => !field.focused || field.border !== field.focus || field.borderWidth < 1 || field.outline !== 'none' || field.hostOutline !== 'none' || field.shadow !== 'none' || field.shifted)}));
  expect(failures).toEqual([]);
});
