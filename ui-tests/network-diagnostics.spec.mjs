import { test, expect } from '@playwright/test';


let externalRequests;
let diagnosticRequests;
let pageErrors;

test.beforeEach(async ({ context, page }) => {
  externalRequests = [];
  diagnosticRequests = [];
  pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/network/')) {
      diagnosticRequests.push({ path, method: request.method(), body: request.postDataJSON() });
    }
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      externalRequests.push(url.href);
      await route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const request = route.request();
      await route.continue({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...request.headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
        },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto('/');
  await page.locator('[data-sidebar-tab="tools"]').click();
});

test.afterEach(() => {
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

async function dockedButtons(page) {
  return page.evaluate(() => {
    window.OfficeKitToolActions?.refresh();
    return [...document.querySelectorAll('button[data-officekit-docked], [data-officekit-docked] button')]
      .filter(button => button.getClientRects().length && !button.closest('[hidden]'))
      .map(button => button.textContent.trim());
  });
}

test('network diagnostics run only on request and keep interface IPs hidden until explicit reveal', async ({ page }) => {
  await page.locator('#tool-gallery-search').fill('DNS Lookup');
  await page.locator('[data-open-tool="network_dns"]').click();
  await expect(page.locator('#network-heading')).toBeVisible();
  await expect(page.locator('#network-interfaces-show-addresses')).not.toBeChecked();
  expect(diagnosticRequests).toEqual([]);

  await page.locator('#network-dns-hostname').fill('example.com');
  await page.locator('#network-dns-record-type').selectOption('A');
  await page.locator('#network-dns-run').click();
  await expect(page.locator('#network-dns-status')).toHaveText('DNS query complete.', { timeout: 10_000 });
  await expect(page.locator('#network-dns-result')).toBeVisible();
  await expect(page.locator('#network-dns-result')).toContainText('A records for example.com');
  expect(diagnosticRequests.at(-1)).toEqual({
    path: '/api/network/dns',
    method: 'POST',
    body: { hostname: 'example.com', record_type: 'A', timeout_seconds: 3 },
  });

  expect(await dockedButtons(page)).toEqual(['Look up records', 'Copy', 'Download']);

  await page.locator('#network-tab-ping').click();
  await page.locator('#network-ping-target').fill('127.0.0.1');
  await page.locator('#network-ping-count').fill('1');
  await page.locator('#network-ping-timeout').fill('3');
  await page.locator('#network-ping-run').click();
  await expect(page.locator('#network-ping-status')).toHaveText('Ping complete.', { timeout: 10_000 });
  await expect(page.locator('#network-ping-result')).toBeVisible();
  const pingText = await page.locator('#network-ping-result').innerText();
  expect(pingText).toMatch(/Reachable|No replies received|Ping timed out|macOS denied ping permission|Check could not be completed/);
  expect(diagnosticRequests.at(-1)).toEqual({
    path: '/api/network/ping',
    method: 'POST',
    body: { target: '127.0.0.1', count: 1, timeout_seconds: 3 },
  });

  expect(await dockedButtons(page)).toEqual(['Run ping', 'Copy', 'Download']);

  // Choosing the Interfaces section is the request: it reads this Mac and sends nothing anywhere.
  await page.locator('#network-tab-interfaces').click();
  await expect(page.locator('#network-interfaces-status')).toHaveText('Interface list updated.');
  await expect(page.locator('#network-interfaces-result')).toBeVisible();
  expect(await dockedButtons(page)).toEqual(['Refresh', 'Copy', 'Download']);
  expect(diagnosticRequests.at(-1)).toEqual({
    path: '/api/network/interfaces',
    method: 'POST',
    body: { include_addresses: false },
  });
  const hiddenText = await page.locator('#network-interfaces-result').innerText();
  expect(hiddenText).toContain('IP address(es) hidden');
  expect(hiddenText).not.toMatch(/\b\d{1,3}(?:\.\d{1,3}){3}\b/);
  expect(hiddenText).not.toMatch(/(?:[0-9a-f]{2}:){5}[0-9a-f]{2}/i);

  await page.locator('#network-interfaces-show-addresses').check();
  await page.locator('#network-interfaces-run').click();
  await expect(page.locator('#network-interfaces-status')).toHaveText('Interface list updated.');
  expect(diagnosticRequests.at(-1)).toEqual({
    path: '/api/network/interfaces',
    method: 'POST',
    body: { include_addresses: true },
  });
  const visibleText = await page.locator('#network-interfaces-result').innerText();
  expect(visibleText).toMatch(/\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[0-9a-f]{0,4}:[0-9a-f:]{2,}\b/i);
  expect(visibleText).not.toMatch(/(?:[0-9a-f]{2}:){5}[0-9a-f]{2}/i);
});
