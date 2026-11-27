import { expect, test } from '@playwright/test';

test('every available screen shares control sizing and primary action color', async ({ page }, testInfo) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  test.setTimeout(180_000);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');

  const screenTabs = await page.evaluate(async () => {
    const shellTabs = ['home', 'recents', 'quick-stats', 'tools', 'favorites', 'activity', 'pii', 'workspace', 'network', 'system', 'pdf', 'color', 'password', 'pdf-editor', 'screenshot', 'statement', 'converter', 'calculators', 'dictate', 'unlocker', 'pricing'];
    const tools = await loadToolGallery().then(() => allToolsCache
      .filter(tool => OFFICEKIT_TOOL_DESTINATIONS[tool.id])
      .map(tool => ({ id: tool.id, tab: OFFICEKIT_TOOL_DESTINATIONS[tool.id].tab })));
    return { shellTabs, tools };
  });
  const visited = new Set();
  const configuredViewport = page.viewportSize();
  const viewportMatrix = [configuredViewport, { width: 390, height: 844 }];
  const screens = [
    ...screenTabs.shellTabs.map(tab => ({ tab, label: `screen ${tab}` })),
    ...screenTabs.tools.map(({ id, tab }) => ({ id, tab, label: `tool ${id}` })),
  ];

  for (const viewport of viewportMatrix) {
    await page.setViewportSize(viewport);
    const targetHeight = viewport.width <= 900 ? 44 : 40;
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
      for (const screen of screens) {
        if (screen.id) {
          expect(await page.evaluate(id => selectSearchTool(id), screen.id), screen.label).toBe(true);
        } else {
          expect(await page.evaluate(tab => switchTab(tab), screen.tab), screen.label).not.toBe(false);
        }
        await expect(page.locator(`#tab-${screen.tab}`), screen.label).toBeVisible();
        const measurements = await page.evaluate(() => {
          const active = [...document.querySelectorAll('main section[id^="tab-"]')].find(section => !section.classList.contains('hidden'));
          const visible = element => {
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
          };
          const lineCount = button => {
            const range = document.createRange();
            const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
            const tops = new Set();
            while (walker.nextNode()) {
              range.selectNodeContents(walker.currentNode);
              for (const rect of range.getClientRects()) if (rect.width > 0 && rect.height > 0) tops.add(Math.round(rect.top));
            }
            return tops.size || 1;
          };
          const computedColor = value => {
            if (!/^#[0-9a-f]{3}(?:[0-9a-f]{3})?$/i.test(value)) return value;
            const hex = value.length === 4 ? [...value.slice(1)].map(channel => `${channel}${channel}`).join('') : value.slice(1);
            return `rgb(${parseInt(hex.slice(0, 2), 16)}, ${parseInt(hex.slice(2, 4), 16)}, ${parseInt(hex.slice(4, 6), 16)})`;
          };
          const content = active || document.querySelector('main');
          const fields = [...content.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="color"]):not([type="file"]):not(#home-search):not(#tool-gallery-search), select')]
            .filter(visible)
            .map(element => ({ id: element.id, height: Math.round(element.getBoundingClientRect().height) }));
          const textareas = [...content.querySelectorAll('textarea')]
            .filter(visible)
            .map(element => ({ id: element.id, height: Math.round(element.getBoundingClientRect().height), minimum: parseFloat(getComputedStyle(element).minHeight) }));
          const searchWrappers = [...document.querySelectorAll('.ok-home-search, label:has(#tool-gallery-search):not(.ok-visually-hidden)')]
            .filter(visible)
            .map(element => ({ className: element.className, height: Math.round(element.getBoundingClientRect().height) }));
          const buttons = [
            ...content.querySelectorAll('button'),
            ...document.querySelectorAll('.ok-app > header button, #app-sidebar button'),
          ]
            .filter(visible)
            .map(element => ({
              id: element.id,
              label: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 64),
              height: Math.round(element.getBoundingClientRect().height),
              minHeight: getComputedStyle(element).minHeight,
              declaredHeight: getComputedStyle(element).height,
              lines: lineCount(element),
              enabled: !element.disabled,
              primary: element.matches('.btn-primary,.bg-indigo-600,.bg-indigo-700,.bg-indigo-800,.bg-blue-700,.bg-sky-700,.bg-emerald-600,.bg-green-600,.bg-green-700'),
              background: getComputedStyle(element).backgroundColor,
              foreground: getComputedStyle(element).color,
            }));
          const rootStyle = getComputedStyle(document.documentElement);
          return {
            headings: [...content.querySelectorAll('h1')].filter(visible).map(element => ({text:element.textContent,fontSize:getComputedStyle(element).fontSize,fontWeight:getComputedStyle(element).fontWeight})),
            fields,
            textareas,
            searchWrappers,
            buttons,
            accent: computedColor(rootStyle.getPropertyValue('--ok-accent').trim()),
            onAccent: computedColor(rootStyle.getPropertyValue('--ok-on-accent').trim()),
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth,
            overflowing: [...document.querySelectorAll('body *')].map(element => ({
              tag: element.tagName,
              id: element.id,
              className: typeof element.className === 'string' ? element.className.slice(0, 100) : '',
              right: Math.round(element.getBoundingClientRect().right),
              width: Math.round(element.getBoundingClientRect().width),
            })).filter(element => element.right > window.innerWidth + 1).slice(0, 8),
          };
        });
        visited.add(`${viewport.width}:${theme}:${screen.label}`);
        if (theme === 'light' && viewport.width === configuredViewport.width && testInfo.project.name === 'desktop-webkit') {
          const filename = `${screen.id || screen.tab}-${screen.id ? screen.tab : 'screen'}.png`;
          await page.screenshot({ path: testInfo.outputPath(`visual-audit-${testInfo.project.name}-${filename}`) });
        }
        expect(measurements.documentWidth, `${screen.label}: document horizontal overflow ${JSON.stringify(measurements.overflowing)}`).toBeLessThanOrEqual(measurements.viewportWidth);
        for (const heading of measurements.headings) {
          expect(heading.fontSize, `${screen.label}: ${heading.text} page title`).toBe('28px');
          expect(Number(heading.fontWeight), `${screen.label}: page title hierarchy`).toBeGreaterThanOrEqual(650);
        }
        for (const field of measurements.fields) {
          expect(field.height, `${screen.label}: ${field.id || 'single-line field'} height`).toBe(targetHeight);
        }
        for (const textarea of measurements.textareas) {
          expect(textarea.minimum, `${screen.label}: ${textarea.id || 'textarea'} minimum height`).toBeGreaterThanOrEqual(160);
          expect(textarea.height, `${screen.label}: ${textarea.id || 'textarea'} rendered height`).toBeGreaterThanOrEqual(160);
        }
        for (const wrapper of measurements.searchWrappers) {
          expect(wrapper.height, `${screen.label}: search control wrapper`).toBe(targetHeight);
        }
        for (const button of measurements.buttons) {
          expect(button.height, `${screen.label}: ${JSON.stringify(button)} minimum height`).toBeGreaterThanOrEqual(targetHeight);
          if (button.lines === 1) expect(button.height, `${screen.label}: ${JSON.stringify(button)} one-line height`).toBe(targetHeight);
          if (button.primary && button.enabled) {
            expect(button.background, `${screen.label}: ${button.label} primary background`).toBe(measurements.accent);
            expect(button.foreground, `${screen.label}: ${button.label} primary text`).toBe(measurements.onAccent);
          }
        }
      }
    }
  }

  expect(visited.size).toBe(screens.length * viewportMatrix.length * 2);
});

test('sidebar rows keep one icon column and consistent heights at desktop, compact and phone widths', async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await expect(page.locator('#app-sidebar .ok-sidebar-link')).toHaveCount(6);
  await expect(page.locator('#app-sidebar .ok-sidebar-section-title')).toHaveCount(0);

  for (const viewport of [{ width: 1440, height: 900 }, { width: 900, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const expectedHeight = viewport.width <= 900 ? 44 : 40;
    const rows = await page.evaluate(() => {
      const elements = [
        ...document.querySelectorAll('#app-sidebar nav .ok-sidebar-link'),
        ...document.querySelectorAll('#app-sidebar .ok-sidebar-toggle'),
      ].filter(element => element.getBoundingClientRect().width > 0);
      return elements.map(element => {
        const button = element.getBoundingClientRect();
        const icon = element.querySelector('.ok-nav-icon')?.getBoundingClientRect();
        const label = element.querySelector('.ok-nav-label')?.getBoundingClientRect();
        return {
          label: element.getAttribute('aria-label') || element.innerText.trim(),
          height: Math.round(button.height),
          x: Math.round(button.x),
          iconCenter: icon ? Math.round(icon.x + icon.width / 2) : null,
          labelTop: label ? Math.round(label.y) : null,
          labelHeight: label ? Math.round(label.height) : null,
        };
      });
    });
    expect(rows.length, `${viewport.width}px sidebar rows rendered`).toBeGreaterThanOrEqual(6);
    for (const row of rows) expect(row.height, `${viewport.width}px ${row.label} row height`).toBe(expectedHeight);
    expect(new Set(rows.map(row => row.x)).size, `${viewport.width}px sidebar row left edges`).toBe(1);
    const iconCenters = rows.filter(row => row.iconCenter !== null).map(row => row.iconCenter);
    expect(new Set(iconCenters).size, `${viewport.width}px shared icon column`).toBe(1);
    for (const row of rows) {
      if (row.labelHeight !== null) expect(row.labelHeight, `${viewport.width}px ${row.label} label stays on one line`).toBeLessThanOrEqual(expectedHeight - 16);
    }
  }
});

test('stt floating hud dismisses via Esc button, Done button, and Escape key', async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');

  const hud = page.locator('#stt-floating-hud');
  await expect(hud).toHaveClass(/hud-hidden/);

  // Show HUD
  await page.evaluate(() => window.toggleSttOverlay());
  await expect(hud).not.toHaveClass(/hud-hidden/);

  // Dismiss via Esc button
  const escBtn = hud.locator('button', { hasText: 'Esc' });
  await escBtn.click();
  await expect(hud).toHaveClass(/hud-hidden/);

  // Show HUD again and dismiss via Done button
  await page.evaluate(() => window.toggleSttOverlay());
  await expect(hud).not.toHaveClass(/hud-hidden/);
  const doneBtn = hud.locator('button', { hasText: 'Done' });
  await doneBtn.click();
  await expect(hud).toHaveClass(/hud-hidden/);

  // Show HUD again and dismiss via physical Escape key
  await page.evaluate(() => window.toggleSttOverlay());
  await expect(hud).not.toHaveClass(/hud-hidden/);
  await page.keyboard.press('Escape');
  await expect(hud).toHaveClass(/hud-hidden/);
});

test('sidebar badges do not wrap to a second line and stay within row height', async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await page.setViewportSize({ width: 1440, height: 900 });

  const badges = await page.evaluate(() => {
    const elements = document.querySelectorAll('#app-sidebar .ok-sidebar-badge');
    return Array.from(elements).map(badge => {
      const button = badge.closest('.ok-sidebar-link');
      const bRect = button.getBoundingClientRect();
      const badgeRect = badge.getBoundingClientRect();
      return {
        text: badge.textContent.trim(),
        buttonTop: bRect.top,
        buttonBottom: bRect.bottom,
        badgeTop: badgeRect.top,
        badgeBottom: badgeRect.bottom,
        isInside: badgeRect.top >= bRect.top - 1 && badgeRect.bottom <= bRect.bottom + 1,
      };
    });
  });

  // Only All Tools and Favorites carry a count.
  expect(badges.length).toBeGreaterThanOrEqual(2);
  for (const b of badges) {
    expect(b.isInside, `badge "${b.text}" is completely contained within its button without wrapping`).toBe(true);
  }
});

test("typing 'pd' in tool gallery search displays pdf tools even if another category was active", async ({ page }, testInfo) => {
  if (testInfo.project.name !== 'desktop-webkit') return;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await page.evaluate(() => window.switchTab('tools'));
  await page.waitForTimeout(400);

  // First select Storage category (as in user screenshot)
  await page.evaluate(() => window.selectCategoryPill('Storage & Cleanup'));
  await page.waitForTimeout(200);
  await expect(page.locator('#tool-gallery-category')).toHaveValue('Storage & Cleanup');

  // Type 'pd' in search input
  const searchInput = page.locator('#tool-gallery-search');
  await searchInput.fill('pd');
  await page.waitForTimeout(400);

  // Verify that PDF tools now appear in the results
  const resultsContainer = page.locator('#tool-gallery-results');
  await expect(resultsContainer).toContainText('PDF Password Remover');
  await expect(resultsContainer).toContainText('Merge PDFs');

  // Capture screenshot of the working pd search
  await page.screenshot({ path: '.test-artifacts/screenshots/fixed-pd-search.png' });
});

test('collapsed sidebar renders cleanly without overflowing badges or broken footprint pill', async ({ page }, testInfo) => {
  if (testInfo.project.name !== 'desktop-webkit') return;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(500);

  // Click collapse button
  await page.locator('#sidebar-toggle').click();
  await page.waitForTimeout(300);

  const sidebar = page.locator('#app-sidebar');
  await expect(sidebar).toHaveClass(/ok-collapsed/);

  // Click Favorites tab in collapsed state
  await page.locator('#app-sidebar [data-sidebar-tab="favorites"]').click();
  await page.waitForTimeout(300);
  await expect(page.locator('#tab-favorites')).toBeVisible();

  // Verify no non-icon element is visible in the sidebar buttons
  const badgeVisible = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('#app-sidebar .ok-sidebar-badge, #app-sidebar .ok-sidebar-catalog, #app-sidebar .ok-sidebar-footprint'))
      .some(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(el).display !== 'none';
      });
  });
  expect(badgeVisible).toBe(false);

  // Take screenshot of collapsed state with favorites active
  await page.screenshot({ path: '.test-artifacts/screenshots/collapsed-sidebar-favorites.png' });

  // Switch to dark mode and take screenshot
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  await page.waitForTimeout(200);
  await page.screenshot({ path: '.test-artifacts/screenshots/collapsed-sidebar-dark.png' });
});

test('studio pages keep All Tools selected in the six-row sidebar and workspace initializes storage', async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');

  const studios = [
    { tab: 'calculators', icon: 'calculators' },
    { tab: 'workspace', icon: 'workspace' },
    { tab: 'pdf', icon: 'pdf' },
    { tab: 'screenshot', icon: 'screenshot' },
    { tab: 'dictate', icon: 'dictate' },
    { tab: 'quick-stats', icon: 'quick-stats' },
  ];

  for (const studio of studios) {
    await page.evaluate(t => switchTab(t), studio.tab);
    await expect(page.locator(`[data-sidebar-tab="${studio.icon}"]`)).toHaveCount(0);
    await expect(page.locator('[data-sidebar-tab="tools"]')).toHaveAttribute('aria-current', 'page');
  }

  // Verify workspace initializes storage tool
  await page.evaluate(() => switchTab('workspace'));
  await expect(page.locator('#direct-file-title')).toHaveText('Storage analyser & cleaner');
  await expect(page.locator('#direct-folder-b')).toBeHidden();
});

test('gallery tool cards and Open Tool CTA buttons open target tool views when clicked', async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') return route.abort();
    if (url.pathname.startsWith('/api/')) {
      return route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
      });
    }
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');

  // Navigate to All Tools gallery
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expect(page.locator('#tab-tools')).toBeVisible();

  // Test 1: Click "Open Tool →" button on "Find & Mask Personal Information" (pii_redaction) card
  const piiCard = page.locator('#tool-gallery-results [data-card-tool="pii_redaction"]');
  await expect(piiCard).toBeVisible();
  const piiOpenBtn = piiCard.locator('button[data-open-tool="pii_redaction"]', { hasText: 'Open Tool' });
  await expect(piiOpenBtn).toBeVisible();
  await piiOpenBtn.click();

  // Verify PII tab opened and is visible
  await expect(page.locator('#tab-pii')).toBeVisible();
  await expect(page.locator('#tab-tools')).toBeHidden();

  // Return to All Tools gallery
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expect(page.locator('#tab-tools')).toBeVisible();
  await expect(page.locator('#tab-pii')).toBeHidden();

  // Test 2: Click card container on Loan & EMI card
  const emiCard = page.locator('#tool-gallery-results [data-card-tool="loan_emi"]');
  await expect(emiCard).toBeVisible();
  await emiCard.click();

  // Verify calculators tab opened and EMI calculator is displayed
  await expect(page.locator('#tab-calculators')).toBeVisible();
  await expect(page.locator('#calc-form-emi')).toBeVisible();

  // Return to All Tools gallery
  await page.locator('[data-sidebar-tab="tools"]').click();
  await expect(page.locator('#tab-tools')).toBeVisible();

  // Test 3: Favorite button click toggles favorite without navigating away from gallery
  const pdfCard = page.locator('#tool-gallery-results [data-card-tool="pdf_merge"]');
  await expect(pdfCard).toBeVisible();
  const favBtn = pdfCard.locator('button[data-favorite-tool="pdf_merge"]');
  await favBtn.click();
  await expect(page.locator('#tab-tools')).toBeVisible();
  await expect(favBtn).toHaveAttribute('aria-pressed', 'true');
});






