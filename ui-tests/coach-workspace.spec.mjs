import { test, expect } from '@playwright/test';

const empty = { open: true, state: 'listening', checksAvailable: true, wordCount: 0, parts: [], fixes: [], paceWpm: null };
const withFixes = {
  open: true, state: 'checking', checksAvailable: true, wordCount: 21, paceWpm: 142,
  parts: [
    { text: 'We ', fixId: null, suggestion: null },
    { text: 'buyed', fixId: 1, suggestion: 'bought' },
    { text: ' fruit and the ', fixId: null, suggestion: null },
    { text: 'prices is', fixId: 2, suggestion: 'prices are' },
    { text: ' low', fixId: null, suggestion: null }
  ],
  fixes: [
    { id: 1, quote: 'buyed', suggestion: 'bought', hint: 'Irregular past tense', category: 'Grammar', patternId: 'grammar.tense' },
    { id: 2, quote: 'prices is', suggestion: 'prices are', hint: 'Subject–verb agreement', category: 'Grammar', patternId: 'grammar.subject_verb' }
  ]
};
const irregularRule = { id: 'grammar.irregular_past', title: 'Irregular past tense', rule: 'Some common verbs do not add -ed in the past. They change form instead: buy → bought, go → went, eat → ate.', wrong: 'We buyed fruit.', right: 'We bought fruit.' };
const subjectVerbRule = { id: 'grammar.subject_verb', title: 'Subject–verb agreement', rule: 'A plural subject takes a plural verb (are, were, have). Only a singular subject takes is, was or has.', wrong: 'The prices is low.', right: 'The prices are low.' };
const withRules = { ...withFixes, fixes: [{ ...withFixes.fixes[0], rule: irregularRule }, { ...withFixes.fixes[1], rule: subjectVerbRule }, { id: 3, quote: 'teh', suggestion: 'the', hint: 'A wording slip', category: 'Grammar', patternId: 'grammar.harper', rule: null }] };
const unavailable = { open: true, state: 'unavailable', checksAvailable: false, wordCount: 8, paceWpm: null, parts: [{ text: 'We went to the market early today.', fixId: null, suggestion: null }], fixes: [] };

async function openWorkspace(page, snapshot, extra = {}) {
  await page.addInitScript(({ snapshot, extra }) => {
    window.__calls = [];
    window.__snapshot = snapshot;
    window.__clipboard = '';
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { window.__clipboard = text; } }, configurable: true });
    window.__TAURI__ = { core: { invoke: async (command, args = {}) => {
      window.__calls.push({ command, args });
      if (command === 'coach_workspace_snapshot') return window.__snapshot;
      if (command === 'coach_workspace_corrected_text') return 'We bought fruit and the prices are low';
      if (command === 'coach_workspace_dismiss') {
        window.__snapshot = { ...window.__snapshot, fixes: window.__snapshot.fixes.filter(f => f.id !== args.fixId) };
        return window.__snapshot;
      }
      if (command === 'coach_workspace_done') return null;
      if (command === 'coach_workspace_open_apple_intelligence') return null;
      if (command === 'coach_workspace_clear') {
        window.__snapshot = { ...window.__snapshot, state: 'listening', wordCount: 0, parts: [], fixes: [], paceWpm: null };
        return window.__snapshot;
      }
      throw new Error(`unexpected command ${command}`);
    } } };
    if (extra.captureLongTimers) {
      const nativeSetTimeout = window.setTimeout.bind(window);
      const nativeClearTimeout = window.clearTimeout.bind(window);
      const timers = new Map();
      let timerId = 0;
      window.__longTimerAdds = 0;
      window.__longTimerClears = 0;
      window.setTimeout = (callback, delay, ...args) => {
        if (delay >= 60000) {
          const id = ++timerId;
          timers.set(id, () => callback(...args));
          window.__longTimerAdds += 1;
          return id;
        }
        return nativeSetTimeout(callback, delay, ...args);
      };
      window.clearTimeout = id => {
        if (timers.delete(id)) { window.__longTimerClears += 1; return; }
        nativeClearTimeout(id);
      };
      window.__fireLongTimer = async () => {
        const callbacks = [...timers.values()];
        timers.clear();
        for (const callback of callbacks) await callback();
      };
    }
    Object.assign(window, extra);
  }, { snapshot, extra });
  await page.setViewportSize({ width: 420, height: 640 });
  await page.goto('/assets/coach-workspace.html');
}

test('just opened: explains what will happen, nothing to fix, copy disabled, two buttons', async ({ page }) => {
  await openWorkspace(page, empty);
  await expect(page.getByRole('heading', { name: 'Live Workspace' })).toBeVisible();
  await expect(page.locator('#ws-state')).toHaveText('Listening · speak naturally');
  await expect(page.locator('#ws-box')).toContainText('Your words appear here as you speak. Improvements appear below.');
  await expect(page.locator('#ws-count')).toHaveText('0');
  await expect(page.locator('#ws-list')).toContainText('Nothing to fix yet.');
  await expect(page.getByRole('button')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Copy', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Done' })).toBeEnabled();
  await expect(page.getByLabel('Auto-clear')).toHaveValue('0');
  await expect(page.getByText('Stays on this Mac · cleared when you press Clear or close')).toBeVisible();
});

test('each fix shows the rule behind it with an example, and a fix with no rule shows none', async ({ page }) => {
  await openWorkspace(page, withRules);
  const rows = page.locator('#ws-list .row');
  await expect(rows).toHaveCount(3);
  const subjectVerb = rows.nth(1);
  await expect(subjectVerb.locator('.pill')).toHaveText('Grammar');
  await expect(subjectVerb.locator('.rule')).toContainText('A plural subject takes a plural verb (are, were, have). Only a singular subject takes is, was or has.');
  await expect(subjectVerb.locator('.rule .ex i')).toHaveText('The prices is low.');
  await expect(subjectVerb.locator('.rule .ex u')).toHaveText('The prices are low.');
  await expect(rows.nth(0).locator('.rule')).toContainText('buy → bought');
  await expect(rows.nth(2).locator('.rule')).toHaveCount(0);
  await expect(rows.nth(2)).toContainText('A wording slip');
  // Rules make each row taller, so the list must still show two whole fixes and the window must not scroll.
  const layout = await page.evaluate(() => ({ list: document.getElementById('ws-list').clientHeight, doc: document.documentElement.scrollHeight, view: window.innerHeight, second: document.querySelectorAll('#ws-list .row')[1].getBoundingClientRect().bottom, listBottom: document.getElementById('ws-list').getBoundingClientRect().bottom }));
  expect(layout.list).toBeGreaterThanOrEqual(260);
  expect(layout.doc).toBeLessThanOrEqual(layout.view);
  expect(layout.second).toBeLessThanOrEqual(layout.listBottom + 1);
  // Teaching the rule adds no control: the card keeps its Clear, Copy and Done buttons.
  await expect(page.locator('body .btn:not([hidden])')).toHaveCount(3);
  // Dismissing still works from a row that carries a rule.
  await rows.nth(1).getByRole('link', { name: /Not a mistake/ }).click();
  await expect(rows).toHaveCount(2);
});

test('Auto-clear remembers the selected delay and clears only after its timer fires', async ({ page }) => {
  await openWorkspace(page, withFixes, { captureLongTimers: true });
  const autoClear = page.getByLabel('Auto-clear');
  const autoClearBox = await autoClear.boundingBox();
  const clearBox = await page.getByRole('button', { name: 'Clear' }).boundingBox();
  expect(autoClearBox.x).toBeLessThan(clearBox.x);
  expect(await autoClear.evaluate(element => getComputedStyle(element).height)).toBe('44px');
  await page.setViewportSize({ width: 1000, height: 640 });
  expect(await autoClear.evaluate(element => getComputedStyle(element).height)).toBe('40px');
  await page.setViewportSize({ width: 420, height: 640 });
  await autoClear.selectOption('5');
  await page.reload();
  await expect(page.getByLabel('Auto-clear')).toHaveValue('5');
  await expect(page.locator('#ws-note')).toHaveText('Stays on this Mac · cleared by Clear, selected timer or close');
  expect(await page.evaluate(() => window.localStorage.getItem('officekit.speechCoach.liveWorkspace.autoClearMinutes'))).toBe('5');
  const clearsBeforeTimer = await page.evaluate(() => window.__calls.filter(call => call.command === 'coach_workspace_clear').length);
  expect(clearsBeforeTimer).toBe(0);
  await page.evaluate(() => {
    window.__snapshot = { ...window.__snapshot, wordCount: 24, parts: [...window.__snapshot.parts, { text: ' again', fixId: null, suggestion: null }] };
  });
  await expect.poll(() => page.evaluate(() => window.__longTimerAdds)).toBe(2);
  expect(await page.evaluate(() => window.__longTimerClears)).toBe(1);
  await page.evaluate(() => window.__fireLongTimer());
  await expect(page.locator('#ws-count')).toHaveText('0');
  await expect(page.locator('#ws-box')).toContainText('Your words appear here as you speak');
  await expect(page.locator('#ws-state')).toHaveText('Listening · speak naturally');
  const clearsAfterTimer = await page.evaluate(() => window.__calls.filter(call => call.command === 'coach_workspace_clear').length);
  expect(clearsAfterTimer).toBe(1);
});

test('the header says the panel is private and drags the whole window, and Not a mistake is a quiet link', async ({ page }) => {
  await openWorkspace(page, withFixes);
  const header = page.locator('.ws header');
  await expect(header).toHaveAttribute('data-tauri-drag-region', '');
  await expect(header).toHaveAttribute('title', 'Drag to move, including to another display');
  await expect(header.getByText('Private · hidden from screen sharing')).toBeVisible();
  await expect(header.locator('.grip')).toBeVisible();
  const dismiss = page.getByRole('link', { name: /Not a mistake: buyed/ });
  await expect(dismiss).toHaveCSS('text-decoration-line', 'none');
  await expect(dismiss).toHaveCSS('font-weight', '400');
  await expect(page.getByRole('button')).toHaveCount(3);
});

test('each correction appears only in Improvements while the transcript stays a clean record', async ({ page }) => {
  await openWorkspace(page, withFixes);
  for (const width of [1440, 420]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('#ws-state')).toHaveText('Checking the last sentence…');
    await expect(page.locator('#ws-pace')).toHaveText('Pace 142 WPM');
    await expect(page.locator('#ws-box')).toHaveText('We buyed fruit and the prices is low');
    await expect(page.locator('#ws-box mark')).toHaveCount(0);
    await expect(page.locator('#ws-box sup')).toHaveCount(0);
    await expect(page.locator('#ws-count')).toHaveText('2');
    await expect(page.locator('.row .fix').first()).toHaveText('buyed → bought');
    await expect(page.locator('.row .pill').first()).toHaveText('Grammar');
    await expect(page.locator('#ws-summary')).toHaveText('2 fixes');
    await expect(page.getByRole('button')).toHaveCount(3);
    await expect(page.getByRole('link', { name: /Not a mistake/ })).toHaveCount(2);
  }
});

test('Not a mistake removes the fix through the backend', async ({ page }) => {
  await openWorkspace(page, withFixes);
  await page.evaluate(() => { window.__remainingDismiss = document.querySelector('[aria-label="Not a mistake: prices is"]'); });
  await page.getByRole('link', { name: 'Not a mistake: buyed' }).click();
  await expect(page.locator('#ws-count')).toHaveText('1');
  await expect(page.locator('.row')).toHaveCount(1);
  expect(await page.evaluate(() => window.__remainingDismiss === document.querySelector('[aria-label="Not a mistake: prices is"]'))).toBe(true);
  const calls = await page.evaluate(() => window.__calls.filter(c => c.command === 'coach_workspace_dismiss'));
  expect(calls).toEqual([{ command: 'coach_workspace_dismiss', args: { fixId: 1 } }]);
});

test('Copy corrected text puts the corrected text on the clipboard only on press', async ({ page }) => {
  await openWorkspace(page, withFixes);
  expect(await page.evaluate(() => window.__clipboard)).toBe('');
  await page.getByRole('button', { name: 'Copy', exact: true }).click();
  await expect(page.locator('#ws-summary')).toHaveText('Copied');
  expect(await page.evaluate(() => window.__clipboard)).toBe('We bought fruit and the prices are low');
});

test('Done asks the backend to close and stop Listen In', async ({ page }) => {
  await openWorkspace(page, withFixes);
  await page.getByRole('button', { name: 'Done' }).click();
  const done = await page.evaluate(() => window.__calls.filter(c => c.command === 'coach_workspace_done').length);
  expect(done).toBe(1);
});

test('grammar checks unavailable never shows zero mistakes', async ({ page }) => {
  await openWorkspace(page, unavailable);
  await expect(page.locator('#ws-state')).toHaveText('Listening · pace and pitch only');
  await expect(page.locator('#ws-count')).toHaveText('—');
  await expect(page.locator('#ws-list')).toContainText('Not checked.');
  await expect(page.getByRole('button', { name: 'Copy', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Copy', exact: true })).toHaveAttribute('title', 'Copy the text');
  await expect(page.getByRole('button')).toHaveCount(3);
});

for (const [status, text, link] of [
  ['off', /Apple Intelligence is turned off.*Basic grammar checks are on/, true],
  ['preparing', /still getting ready.*Basic grammar checks are on/, false],
  ['unsupported', /can't run Apple Intelligence.*Apple Silicon.*macOS 26.*Basic grammar checks are on/, false],
  ['available', null, false]
]) {
  test(`Apple Intelligence ${status}: the panel says so and still counts fixes`, async ({ page }) => {
    await openWorkspace(page, { ...withFixes, appleStatus: status });
    if (text) await expect(page.locator('#ws-warning')).toContainText(text);
    else await expect(page.locator('#ws-warning')).toBeHidden();
    await expect(page.getByRole('link', { name: 'Turn on Apple Intelligence' })).toBeVisible({ visible: link });
    await expect(page.locator('#ws-count')).toHaveText('2');
    await expect(page.getByRole('button')).toHaveCount(3);
  });
}

test('Turn on Apple Intelligence opens System Settings through the app', async ({ page }) => {
  await openWorkspace(page, { ...withFixes, appleStatus: 'off' });
  await page.getByRole('link', { name: 'Turn on Apple Intelligence' }).click();
  const calls = await page.evaluate(() => window.__calls.filter(c => c.command === 'coach_workspace_open_apple_intelligence').length);
  expect(calls).toBe(1);
});

test('the pad has a fixed height, scrolls, and follows the newest words', async ({ page }) => {
  const long = { ...withFixes, wordCount: 200, parts: [{ text: Array.from({ length: 200 }, (_, i) => `word${i}`).join(' '), fixId: null, suggestion: null }], fixes: [] };
  await openWorkspace(page, long);
  const box = page.locator('#ws-box');
  await expect(box).toHaveCSS('overflow-y', 'auto');
  await expect(box).toContainText('word199');
  await expect.poll(() => box.evaluate(el => el.scrollHeight > el.clientHeight && el.scrollHeight - el.scrollTop - el.clientHeight < 24)).toBe(true);
  expect(await box.evaluate(el => Math.round(el.getBoundingClientRect().height))).toBe(150);
  await box.evaluate(el => { el.scrollTop = 0; });
  await page.waitForTimeout(1200);
  expect(await box.evaluate(el => el.scrollTop)).toBe(0);
});

test('Clear appears with text, empties the pad and keeps the panel open', async ({ page }) => {
  await openWorkspace(page, withFixes);
  const clear = page.getByRole('button', { name: 'Clear' });
  await expect(clear).toBeVisible();
  await expect(page.getByRole('button')).toHaveCount(3);
  await clear.click();
  await expect(page.locator('#ws-box')).toContainText('Your words appear here as you speak');
  await expect(page.locator('#ws-count')).toHaveText('0');
  await expect(clear).toBeHidden();
  const calls = await page.evaluate(() => window.__calls.filter(c => c.command === 'coach_workspace_clear').length);
  expect(calls).toBe(1);
  await expect(page.getByRole('button')).toHaveCount(2);
});

test('spoken text is shown as text, never as markup', async ({ page }) => {
  const hostile = { ...empty, wordCount: 3, parts: [{ text: '<img src=x onerror="window.__pwned=1"> hello there', fixId: null, suggestion: null }] };
  await openWorkspace(page, hostile);
  await expect(page.locator('#ws-box')).toContainText('<img src=x');
  expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
  await expect(page.locator('#ws-box img')).toHaveCount(0);
});
