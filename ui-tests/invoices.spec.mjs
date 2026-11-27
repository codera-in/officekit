import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const apiOrigin = `http://127.0.0.1:${process.env.OFFICEKIT_UI_TEST_API_PORT || '19873'}`;
const auth = () => ({ authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`, 'X-OfficeKit-Native-Grant': process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN, origin: 'tauri://localhost' });

test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(() => {
    localStorage.setItem('officekit.tour.dont_show', 'true'); localStorage.setItem('officekit.tour.version', '1.0.54'); localStorage.setItem('officekit.setup.done_v1', '1');
    window.__TAURI__ = { event: { listen: async () => () => {} }, core: { invoke: async (command, args) => {
      if (command === 'file_selection_open') return window.__invoiceSelected;
      if (command === 'result_save') { window.__invoiceSaved = args; return { state: 'saved', name: args.suggestedName }; }
      return null;
    } } };
  });
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${apiOrigin}${url.pathname}${url.search}`, headers: { ...route.request().headers(), ...auth() } });
    await route.fulfill({ response });
  });
  await page.goto('/?tour=off');
  await page.locator('[data-sidebar-tab="tools"]').click();
  await page.locator('#tool-gallery-search').fill('invoice');
  await page.locator('[data-open-tool="invoice_manager"]').click();
  await expect(page.locator('#tab-invoices')).toBeVisible();
});

async function selected(page, selectedPath, access = 'read-write') {
  const response = await page.request.post(`${apiOrigin}/api/file-selections`, { headers: auth(), data: { paths: [await fs.realpath(selectedPath)], access } });
  expect(response.status()).toBe(201);
  await page.evaluate(value => { window.__invoiceSelected = value; }, await response.json());
}

async function countedButtons(page) {
  const screen = page.locator('#tab-invoices');
  const counted = await screen.locator('button.btn:visible').allTextContents();
  expect(counted.length, counted.join(', ')).toBeLessThanOrEqual(3);
  const overflow = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth, offenders: [...document.querySelectorAll('body *')].filter(node => { const r = node.getBoundingClientRect(); return r.right > innerWidth + 1 && getComputedStyle(node).position !== 'fixed'; }).slice(0, 8).map(node => ({ tag: node.tagName, id: node.id, className: String(node.className).slice(0, 80), right: Math.round(node.getBoundingClientRect().right) })) }));
  expect(overflow.width, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.viewport);
}

async function profile(page, profileName, currency = 'USD') {
  const screen = page.locator('#tab-invoices');
  const dialog = screen.getByRole('dialog');
  await dialog.getByLabel('Profile name', { exact: true }).fill(profileName);
  await dialog.getByLabel('Business name', { exact: true }).fill('Northstar Studio');
  await dialog.getByLabel('Business address', { exact: true }).fill('Business address');
  await countedButtons(page);
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click();
  const defaults = screen.getByRole('dialog');
  await countedButtons(page);
  await defaults.getByRole('combobox', { name: 'Currency', exact: true }).selectOption(currency);
  await defaults.getByRole('button', { name: 'Finish profile', exact: true }).click();
  await expect(screen.getByRole('status')).toHaveText('Business profile saved.');
  await countedButtons(page);
}

async function clickTab(page, name) {
  const tab = page.locator('#tab-invoices').getByRole('tab', { name, exact: true });
  await tab.click(); await expect(tab).toHaveAttribute('aria-selected', 'true');
}

test('real API: profiles, catalogue-local edits, invoice issue, payment, PDF, history and backup', async ({ page }, testInfo) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-invoice-ui-'));
  try {
    await fs.mkdir(path.resolve('docs/verification/tool-unification/before'), { recursive: true });
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/before/invoice_manager-initial-${testInfo.project.name}.png`), fullPage: true });
    await selected(page, root); await page.locator('#tab-invoices').getByRole('button', { name: 'Choose folder', exact: true }).click();
    await profile(page, 'India', 'INR');
    const screen = page.locator('#tab-invoices');
    await clickTab(page, 'Settings');
    await screen.getByRole('link', { name: 'Edit profile', exact: true }).click();
    const editDialog = screen.getByRole('dialog');
    await expect(editDialog).toHaveClass(/modal/);
    await editDialog.getByRole('button', { name: 'Continue', exact: true }).click();
    const logoPreview = editDialog.locator('.ok-invoice-logo-preview');
    const previewBeforeUpload = await logoPreview.boundingBox();
    await selected(page, path.join(process.cwd(), 'app-icon.png'), 'read');
    await screen.getByRole('dialog').getByRole('button', { name: 'Upload logo', exact: true }).click();
    await expect(screen.getByRole('dialog').getByRole('img', { name: 'Invoice logo preview', exact: true })).toBeVisible();
    const previewAfterUpload = await logoPreview.boundingBox();
    expect(previewAfterUpload.height).toBe(previewBeforeUpload.height);
    await countedButtons(page);
    await screen.getByRole('dialog').getByRole('button', { name: 'Finish profile', exact: true }).click();
    await screen.getByRole('link', { name: 'New profile', exact: true }).click(); await profile(page, 'International', 'USD');
    await expect(screen.getByRole('combobox', { name: 'Business profile', exact: true }).locator('option')).toHaveCount(2);
    await clickTab(page, 'Clients & items');
    await screen.getByRole('combobox', { name: 'Catalogue', exact: true }).selectOption('clients'); await screen.getByRole('button', { name: 'New record', exact: true }).click();
    await screen.getByLabel('Client name', { exact: true }).fill('Acme Design'); await screen.getByLabel('Email', { exact: true }).fill('billing@example.test'); await screen.getByLabel('Address', { exact: true }).fill('Acme address');
    await screen.getByRole('button', { name: 'Save record', exact: true }).click(); await expect(screen.getByRole('button', { name: 'New record', exact: true })).toBeVisible();
    await screen.getByRole('button', { name: 'New record', exact: true }).click();
    await screen.getByLabel('Private item name', { exact: true }).fill('Design sprint'); await screen.getByLabel('Printed description', { exact: true }).fill('Reusable design work'); await screen.getByLabel('Default rate', { exact: true }).fill('100');
    await screen.getByRole('button', { name: 'Save record', exact: true }).click(); await expect(screen.getByRole('button', { name: 'New record', exact: true })).toBeVisible();
    await clickTab(page, 'Documents'); await screen.getByRole('button', { name: 'New document', exact: true }).click();
    await screen.getByRole('combobox', { name: 'Saved item', exact: true }).selectOption({ label: 'Design sprint' });
    await expect(screen.getByLabel('Description & invoice-specific details', { exact: true })).toHaveValue('Reusable design work');
    await screen.getByLabel('Description & invoice-specific details', { exact: true }).fill('Reusable design work\nAdditional project details');
    await screen.getByLabel('Quantity', { exact: true }).fill('2');
    await screen.getByRole('button', { name: 'Save draft', exact: true }).click(); await expect(screen.getByRole('status')).toHaveText('Draft saved.'); await countedButtons(page);
    await screen.getByRole('button', { name: 'Update preview', exact: true }).click(); await expect(screen.locator('iframe')).toHaveAttribute('src', /^blob:/);
    await screen.getByRole('button', { name: 'Issue document', exact: true }).click(); await expect(screen.getByRole('button', { name: 'Record payment', exact: true })).toBeVisible();
    const issuedActions = screen.locator('.ok-invoice-actions[data-officekit-docked="true"]');
    await expect(issuedActions).toBeVisible();
    await expect(issuedActions.locator('button:visible')).toHaveCount(3);
    await expect(issuedActions).toContainText('Draft email');
    await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
    await screen.getByRole('button', { name: 'Download PDF', exact: true }).click();
    await expect.poll(() => page.evaluate(() => Boolean(window.__invoiceSaved))).toBe(true);
    await expect(screen.getByRole('button', { name: 'Download PDF', exact: true })).toBeEnabled();
    const saved = await page.evaluate(() => window.__invoiceSaved); expect(saved.suggestedName).toBe('invoice.pdf'); expect(Buffer.from(saved.base64Data, 'base64').subarray(0, 4).toString()).toBe('%PDF');
    await fs.mkdir(path.resolve('docs/verification/tool-unification/after'), { recursive: true });
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/invoice_manager-issued-${testInfo.project.name}.png`), fullPage: true });
    await screen.getByText('Record or correct a payment', { exact: true }).click(); await screen.getByLabel('Amount', { exact: true }).fill('50');
    await screen.getByRole('button', { name: 'Record payment', exact: true }).click(); await expect(screen).toContainText('Partially paid'); await countedButtons(page);
    await clickTab(page, 'Clients & items'); await screen.getByRole('button', { name: 'Design sprint', exact: true }).click(); await expect(screen.getByLabel('Printed description', { exact: true })).toHaveValue('Reusable design work');
    await clickTab(page, 'Reports'); await expect(screen).toContainText('$200.00'); await countedButtons(page);
    await clickTab(page, 'Data folder'); await countedButtons(page);
    const folderActions = screen.locator('.ok-invoice-folder-actions');
    await expect(folderActions).toHaveAttribute('data-officekit-docked', 'true');
    await expect(folderActions.locator('button:visible')).toHaveCount(3);
    await expect(page.locator('#officekit-tool-actions')).toBeVisible();
    await expect(page.locator('#officekit-tool-action-summary')).toBeHidden();
    await expect(page.locator('#officekit-tool-actions')).toHaveCSS('height', '64px');
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/invoice_manager-folder-actions-docked-${testInfo.project.name}.png`), fullPage: true });
    const secondaryActions = screen.locator('.ok-invoice-folder-secondary');
    await expect(folderActions.locator('.ok-invoice-folder-secondary')).toHaveCount(0);
    await secondaryActions.scrollIntoViewIfNeeded();
    const secondaryBox = await secondaryActions.boundingBox();
    const dockBox = await page.locator('#officekit-tool-actions').boundingBox();
    expect(secondaryBox).not.toBeNull(); expect(dockBox).not.toBeNull();
    expect(secondaryBox.y + secondaryBox.height).toBeLessThanOrEqual(dockBox.y);
    await screen.getByText('More workspace actions', { exact: true }).click(); await screen.getByRole('combobox', { name: 'More workspace actions', exact: true }).selectOption('history'); await expect(screen).toContainText('Workspace history'); await countedButtons(page);
    await screen.getByRole('button', { name: 'Workspace settings', exact: true }).click(); await screen.getByRole('button', { name: 'Create backup', exact: true }).click();
    await expect.poll(() => page.evaluate(() => window.__invoiceSaved?.suggestedName)).toBe('officekit-invoices-backup.zip');
    const backup = await page.evaluate(() => window.__invoiceSaved); expect(backup.suggestedName).toBe('officekit-invoices-backup.zip'); expect(Buffer.from(backup.base64Data, 'base64').subarray(0, 2).toString()).toBe('PK');
    await page.screenshot({ path: path.resolve(`docs/verification/tool-unification/after/invoice_manager-workspace-${testInfo.project.name}.png`), fullPage: true });
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('workspace restore uses separate destination and preserves a complete backup', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-invoice-restore-ui-')); const destination = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-invoice-restore-dest-'));
  try {
    const screen = page.locator('#tab-invoices');
    await selected(page, root); await screen.getByRole('button', { name: 'Choose folder', exact: true }).click(); await profile(page, 'Original');
    await clickTab(page, 'Data folder'); await screen.getByRole('button', { name: 'Create backup', exact: true }).click();
    await expect.poll(() => page.evaluate(() => Boolean(window.__invoiceSaved))).toBe(true);
    const backup = await page.evaluate(() => window.__invoiceSaved); const backupPath = path.join(root, 'backup.zip'); await fs.writeFile(backupPath, Buffer.from(backup.base64Data, 'base64'));
    await screen.getByRole('button', { name: 'Restore backup', exact: true }).click(); await expect(screen.getByRole('button', { name: 'Restore & open workspace', exact: true })).toBeDisabled();
    await selected(page, backupPath, 'read'); await screen.getByRole('button', { name: 'Choose backup file', exact: true }).click();
    await selected(page, destination); await screen.getByRole('button', { name: 'Choose parent folder', exact: true }).click(); await countedButtons(page);
    await screen.getByRole('button', { name: 'Restore & open workspace', exact: true }).click(); await expect(screen).toContainText('Invoice workspace');
    await expect(screen.getByRole('combobox', { name: 'Business profile', exact: true })).toContainText('Original');
    expect((await fs.readdir(root)).includes('backup.zip')).toBe(true);
  } finally { await fs.rm(root, { recursive: true, force: true }); await fs.rm(destination, { recursive: true, force: true }); }
});
