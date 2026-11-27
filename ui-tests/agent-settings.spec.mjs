import { test, expect } from '@playwright/test';

const HELPER = '/Applications/OfficeKit.app/Contents/Resources/binaries/officekit-media';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

// A stateful stand-in for the native commands in src-tauri/src/agent_settings.rs.
async function installFakeDesktop(page, options = {}) {
  await page.evaluate(({ helper, failWrites, codexPresent, codexState }) => {
    const store = {
      settings: { version: 1 }, calls: [], copied: [],
      skills: {
        'claude-code': { label: 'Claude Code', path: '/Users/me/.claude/skills/officekit/SKILL.md', present: true, state: 'not-installed' },
        codex: { label: 'Codex', path: '/Users/me/.agents/skills/officekit/SKILL.md', present: codexPresent, state: codexState },
      },
    };
    const skillStatus = () => ({ targets: Object.entries(store.skills).map(([id, target]) => ({ id, ...target })) });
    window.__agentFake = store;
    navigator.clipboard.writeText = async text => { store.copied.push(text); };
    window.__TAURI__ = {
      core: {
        invoke: async (name, args) => {
          store.calls.push([name, args]);
          if (name === 'agent_helper_status') return { available: true, path: helper };
          if (name === 'agent_settings_read') {
            return { settings: store.settings, defaults: { allowed_dirs: ['/Users/me/Documents', '/Users/me/Downloads', '/Users/me/Desktop'], output_dir: '/Users/me/OfficeKit Output' } };
          }
          if (name === 'agent_settings_write') {
            if (failWrites) throw new Error('Agent settings could not be saved');
            store.settings = args.settings;
            return args.settings;
          }
          if (name === 'agent_skill_status') return skillStatus();
          if (name === 'agent_skill_install') {
            // Like the native side: only agents that are on this Mac, never over a foreign skill.
            const done = args.targets.filter(id => store.skills[id] && store.skills[id].present && store.skills[id].state !== 'foreign');
            if (!done.length) throw new Error('None of the selected agents can be updated on this Mac');
            for (const id of done) store.skills[id].state = 'installed';
            return skillStatus();
          }
          if (name === 'agent_choose_folders') return ['/Users/me/Projects', '/Users/me/Documents'];
          if (name === 'agent_reveal_output') return null;
          throw new Error(`Unexpected native command ${name}`);
        },
      },
    };
  }, { helper: HELPER, failWrites: !!options.failWrites, codexPresent: options.codexPresent !== false, codexState: options.codexState || 'not-installed' });
}

async function openSettings(page) {
  await page.locator('[data-sidebar-tab="settings"]').click();
  await expect(page.locator('#tab-settings')).toBeVisible();
}

test('Settings opens from the sidebar and keeps its item selected', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await expect(page.locator('#settings-heading')).toHaveText('Settings');
  await expect(page.locator('[data-sidebar-tab="settings"]')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('[data-sidebar-tab="tools"]')).not.toHaveAttribute('aria-current', 'page');
  // Settings is a destination, not a tool: the rail stays open and no bottom bar is shown.
  await expect(page.locator('#app-sidebar')).not.toHaveClass(/ok-collapsed/);
  await expect(page.locator('#officekit-tool-actions')).toBeHidden();
  await expect(page.locator('#tab-settings #agents-copy')).toBeVisible();
  const order = await page.locator('#tab-settings h2').allTextContents();
  expect(order.slice(0, 3)).toEqual(['General', 'Agent skill', 'Connect through MCP']);
});

test('the skill installs for every ticked agent and then reports installed', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await expect(page.locator('[data-skill-state="claude-code"]')).toHaveText('Not installed');
  await expect(page.locator('[data-skill-state="codex"]')).toHaveText('Not installed');
  await expect(page.locator('input[data-skill-target="claude-code"]')).toBeChecked();
  await expect(page.locator('input[data-skill-target="codex"]')).toBeChecked();
  await expect(page.locator('#tab-settings')).toContainText('/Users/me/.agents/skills/officekit/SKILL.md');
  await page.locator('#agents-skill-install').click();
  await expect(page.locator('[data-skill-state="claude-code"]')).toHaveText('Installed');
  await expect(page.locator('[data-skill-state="codex"]')).toHaveText('Installed');
  await expect(page.locator('#agents-skill-install')).toBeDisabled();
  await expect(page.locator('#agents-skill-status')).toContainText('Skill installed for Claude Code and Codex');
  const install = await page.evaluate(() => window.__agentFake.calls.find(([name]) => name === 'agent_skill_install'));
  expect(install[1]).toEqual({ targets: ['claude-code', 'codex'] });
});

test('only the ticked agent gets the skill', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await page.locator('input[data-skill-target="claude-code"]').uncheck();
  await page.locator('#agents-skill-install').click();
  await expect(page.locator('[data-skill-state="codex"]')).toHaveText('Installed');
  await expect(page.locator('[data-skill-state="claude-code"]')).toHaveText('Not installed');
  await expect(page.locator('#agents-skill-status')).toContainText('Skill installed for Codex');
});

test('an agent that is not on this Mac is skipped, and a foreign skill is never overwritten', async ({ page }) => {
  await installFakeDesktop(page, { codexPresent: false });
  await openSettings(page);
  await expect(page.locator('[data-skill-state="codex"]')).toHaveText('Not found on this Mac');
  await expect(page.locator('input[data-skill-target="codex"]')).toBeDisabled();
  await expect(page.locator('input[data-skill-target="codex"]')).not.toBeChecked();
  await page.locator('#agents-skill-install').click();
  await expect(page.locator('[data-skill-state="claude-code"]')).toHaveText('Installed');

  await page.reload();
  await installFakeDesktop(page, { codexState: 'foreign' });
  await openSettings(page);
  await expect(page.locator('[data-skill-state="codex"]')).toHaveText('A different skill already uses this name');
  await expect(page.locator('input[data-skill-target="codex"]')).toBeDisabled();
});

test('MCP tabs show a copy-ready config for the bundled helper and copy it', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await expect(page.locator('#agents-helper-badge')).toHaveText('Agent helper found');
  await expect(page.locator('#agents-config')).toHaveText(`claude mcp add officekit -- '${HELPER}' --agent-mcp`);

  await page.locator('[data-agent-client="codex"]').click();
  await expect(page.locator('[data-agent-client="codex"]')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#agents-config')).toContainText('[mcp_servers.officekit]');

  await page.locator('[data-agent-client="codex"]').press('ArrowRight');
  await expect(page.locator('[data-agent-client="claude-code"]')).toHaveAttribute('aria-selected', 'true');

  await page.locator('#agents-copy').click();
  await expect(page.locator('#agents-copy-status')).toHaveText('Copied.');
  expect(await page.evaluate(() => window.__agentFake.copied)).toEqual([`claude mcp add officekit -- '${HELPER}' --agent-mcp`]);
});

test('tool groups save immediately and every group off is a valid choice', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await page.locator('[data-agent-group="pdf"]').uncheck();
  await expect(page.locator('#agents-tools-status')).toContainText('Saved.');
  expect(await page.evaluate(() => window.__agentFake.settings.tools)).toEqual(['image', 'calc', 'privacy', 'dev', 'system']);
  for (const id of ['image', 'calc', 'privacy', 'dev', 'system']) await page.locator(`[data-agent-group="${id}"]`).uncheck();
  expect(await page.evaluate(() => window.__agentFake.settings.tools)).toEqual([]);
});

test('a failed save reverts the switch and explains why', async ({ page }) => {
  await installFakeDesktop(page, { failWrites: true });
  await openSettings(page);
  await page.locator('[data-agent-group="image"]').click(); // uncheck() would fail because the page reverts the change
  // The app's shared error styling also appends its Report bug action, so match on containment.
  await expect(page.locator('#agents-tools-status')).toContainText('Agent settings could not be saved');
  await expect(page.locator('[data-agent-group="image"]')).toBeChecked();
});

test('changing folders saves them and keeps the chosen tool groups', async ({ page }) => {
  await installFakeDesktop(page);
  await openSettings(page);
  await expect(page.locator('#agents-read-folders')).toHaveText('Documents, Downloads, Desktop (default)');
  await expect(page.locator('#agents-output-folder')).toHaveText('/Users/me/OfficeKit Output');
  await page.locator('[data-agent-group="system"]').uncheck();
  await page.locator('#agents-change-folders').click();
  await expect(page.locator('#agents-read-folders')).toHaveText('Projects, Documents');
  expect(await page.evaluate(() => window.__agentFake.settings)).toEqual({
    version: 1, tools: ['pdf', 'image', 'calc', 'privacy', 'dev'], allowed_dirs: ['/Users/me/Projects', '/Users/me/Documents'],
  });
  await page.locator('#agents-reveal-output').click();
  expect(await page.evaluate(() => window.__agentFake.calls.some(([name]) => name === 'agent_reveal_output'))).toBe(true);
});

test('outside the desktop app Settings explains instead of failing silently', async ({ page }) => {
  await openSettings(page);
  await expect(page.locator('#agents-skill-status')).toContainText('available in the OfficeKit desktop app');
  await expect(page.locator('#agents-copy')).toBeDisabled();
  await expect(page.locator('#agents-skill-install')).toBeDisabled();
});
