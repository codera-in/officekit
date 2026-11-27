import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const ARTIFACTS_DIR = '.test-artifacts/screenshots';
const SCREENSHOT_DIR = path.resolve('.test-artifacts/tool-verification');

test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.beforeEach(async ({ context }) => {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') {
      return route.abort();
    } else if (url.pathname.startsWith('/api/')) {
      const response = await route.fetch({
        url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
        headers: {
          ...route.request().headers(),
          authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
          origin: 'tauri://localhost',
        },
      });
      await route.fulfill({ response });
    } else {
      await route.continue();
    }
  });
});

async function captureEvidence(page, name) {
  const localPath = path.join(SCREENSHOT_DIR, `${name}.png`);
  const brainPath = path.join(ARTIFACTS_DIR, `${name}.png`);
  await page.screenshot({ path: localPath });
  try {
    fs.copyFileSync(localPath, brainPath);
  } catch (_) {}
}

async function prepareApp(page) {
  await page.goto('/');
  await page.waitForFunction(() => document.readyState === 'complete' && typeof switchTab === 'function');
}

test.describe('Apple Pro UI Revamp - All Tools Verification Matrix', () => {

  test('01. Loan & EMI Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('emi'); });
    await expect(page.locator('#calc-form-emi')).toBeVisible();

    // Success Scenario: Valid loan calculation
    await page.locator('#emi-principal').fill('25000');
    await page.locator('#emi-rate').fill('6.5');
    await page.locator('#emi-years').fill('5');
    await page.locator('#calc-form-emi button:has-text("Calculate EMI")').dispatchEvent('click');
    await expect(page.locator('#emi-result')).toBeVisible();
    await expect(page.locator('#emi-result')).toContainText('$');
    await captureEvidence(page, 'tool-loan-emi-success');

    // Failure Scenario: Zero / negative tenure validation
    await page.locator('#emi-years').fill('0');
    await page.locator('#calc-form-emi button:has-text("Calculate EMI")').dispatchEvent('click');
    await captureEvidence(page, 'tool-loan-emi-failure');
  });

  test('02. Compound Growth Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('compound'); });
    await expect(page.locator('#calc-form-compound')).toBeVisible();

    // Success Scenario
    await page.locator('#ci-principal').fill('10000');
    await page.locator('#ci-rate').fill('8');
    await page.locator('#ci-years').fill('10');
    await page.locator('#calc-form-compound button:has-text("Calculate Wealth Growth")').dispatchEvent('click');
    await expect(page.locator('#ci-result')).toBeVisible();
    await captureEvidence(page, 'tool-compound-interest-success');

    // Failure Scenario
    await page.locator('#ci-principal').fill('-5000');
    await page.locator('#calc-form-compound button:has-text("Calculate Wealth Growth")').dispatchEvent('click');
    await captureEvidence(page, 'tool-compound-interest-failure');
  });

  test('03. VAT & Sales Tax Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('vat'); });
    await expect(page.locator('#calc-form-vat')).toBeVisible();

    // Success Scenario
    await page.locator('#vat-amount').fill('1500');
    await page.locator('#vat-rate').fill('20');
    await page.locator('#calc-form-vat button:has-text("Calculate Tax")').dispatchEvent('click');
    await expect(page.locator('#vat-result')).toBeVisible();
    await captureEvidence(page, 'tool-vat-tax-success');

    // Failure Scenario
    await page.locator('#vat-amount').fill('-100');
    await page.locator('#calc-form-vat button:has-text("Calculate Tax")').dispatchEvent('click');
    await captureEvidence(page, 'tool-vat-tax-failure');
  });

  test('04. Freelance Hourly Rate Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('freelance'); });
    await expect(page.locator('#calc-form-freelance')).toBeVisible();

    // Success Scenario
    await page.locator('#free-target').fill('120000');
    await page.locator('#free-hours').fill('30');
    await page.locator('#free-vacation').fill('4');
    await page.locator('#free-tax').fill('25');
    await page.locator('#free-expenses').fill('5000');
    await page.locator('#calc-form-freelance button:has-text("Calculate Hourly Rate")').dispatchEvent('click');
    await expect(page.locator('#free-result')).toBeVisible();
    await captureEvidence(page, 'tool-freelance-rate-success');

    // Failure Scenario
    await page.locator('#free-hours').fill('0');
    await page.locator('#calc-form-freelance button:has-text("Calculate Hourly Rate")').dispatchEvent('click');
    await captureEvidence(page, 'tool-freelance-rate-failure');
  });

  test('05. Scientific Math Expression Evaluator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('scientific'); });
    await expect(page.locator('#calc-form-scientific')).toBeVisible();

    // Success Scenario
    await page.locator('#math-expression').fill('sqrt(256) * 4 + 1');
    await page.locator('#math-run').dispatchEvent('click');
    await expect(page.locator('#math-result')).toBeVisible();
    await expect(page.locator('#math-result')).toContainText('65');
    await captureEvidence(page, 'tool-math-eval-success');

    // Failure Scenario: Syntax error
    await page.locator('#math-expression').fill('2 +* 5 // (');
    await page.locator('#math-run').dispatchEvent('click');
    await expect(page.locator('#math-result')).toBeVisible();
    await captureEvidence(page, 'tool-math-eval-failure');
  });

  test('06. Margin & Markup Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('margin'); });
    await expect(page.locator('#calc-form-margin')).toBeVisible();

    // Success Scenario
    await page.locator('#margin-cost').fill('80');
    await page.locator('#margin-revenue').fill('100');
    await page.locator('#margin-run').dispatchEvent('click');
    await expect(page.locator('#margin-result')).toBeVisible();
    await captureEvidence(page, 'tool-margin-markup-success');

    // Failure Scenario
    await page.locator('#margin-revenue').fill('0');
    await page.locator('#margin-run').dispatchEvent('click');
    await captureEvidence(page, 'tool-margin-markup-failure');
  });

  test('07. Break-Even Point Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('break-even'); });
    await expect(page.locator('#calc-form-break-even')).toBeVisible();

    // Success Scenario
    await page.locator('#break-fixed').fill('5000');
    await page.locator('#break-price').fill('50');
    await page.locator('#break-cost').fill('20');
    await page.locator('#break-run').dispatchEvent('click');
    await expect(page.locator('#break-result')).toBeVisible();
    await captureEvidence(page, 'tool-break-even-success');

    // Failure Scenario: Price lower than variable cost
    await page.locator('#break-price').fill('10');
    await page.locator('#break-cost').fill('25');
    await page.locator('#break-run').dispatchEvent('click');
    await captureEvidence(page, 'tool-break-even-failure');
  });

  test('08. Simple Interest Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('simple-interest'); });
    await expect(page.locator('#calc-form-simple-interest')).toBeVisible();

    // Success Scenario
    await page.locator('#simple-principal').fill('1000');
    await page.locator('#simple-rate').fill('5');
    await page.locator('#simple-time').fill('2');
    await page.locator('#simple-run').dispatchEvent('click');
    await expect(page.locator('#simple-result')).toBeVisible();
    await captureEvidence(page, 'tool-simple-interest-success');

    // Failure Scenario
    await page.locator('#simple-principal').fill('');
    await page.locator('#simple-run').dispatchEvent('click');
    await captureEvidence(page, 'tool-simple-interest-failure');
  });

  test('09. Straight-Line Depreciation Calculator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('depreciation'); });
    await expect(page.locator('#calc-form-depreciation')).toBeVisible();

    // Success Scenario
    await page.locator('#depreciation-cost').fill('12000');
    await page.locator('#depreciation-salvage').fill('2000');
    await page.locator('#depreciation-life').fill('5');
    await page.locator('#depreciation-run').dispatchEvent('click');
    await expect(page.locator('#depreciation-result')).toBeVisible();
    await captureEvidence(page, 'tool-depreciation-success');

    // Failure Scenario: Salvage value greater than cost
    await page.locator('#depreciation-salvage').fill('20000');
    await page.locator('#depreciation-run').dispatchEvent('click');
    await captureEvidence(page, 'tool-depreciation-failure');
  });

  test('10. Everyday Percentages (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => { switchTab('calculators'); switchCalc('percentages'); });
    await expect(page.locator('#calc-form-percentages')).toBeVisible();

    // Success Scenario
    await page.locator('#percentage-percent').fill('15');
    await page.locator('#percentage-value').fill('240');
    await page.locator('#percentages-run').dispatchEvent('click');
    await expect(page.locator('#percentages-result')).toBeVisible();
    await captureEvidence(page, 'tool-percentages-success');

    // Failure Scenario
    await page.locator('#percentage-percent').fill('');
    await page.locator('#percentages-run').dispatchEvent('click');
    await captureEvidence(page, 'tool-percentages-failure');
  });

  test('11. Developer Tools - JSON Formatter (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => selectSearchTool('devtools_format'));
    await expect(page.locator('#developer-tools-panel')).toBeVisible();

    // Success Scenario
    await page.locator('#developer-tools-input').fill('{"name":"OfficeKit Pro","version":2.0,"local":true}');
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-output')).toHaveValue(/OfficeKit Pro/);
    await captureEvidence(page, 'tool-json-formatter-success');

    // Failure Scenario: Malformed JSON
    await page.locator('#developer-tools-input').fill('{"name": unquoted_value, missing_brace');
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-status')).toContainText('could not be processed');
    await captureEvidence(page, 'tool-json-formatter-failure');
  });

  test('12. JWT Inspector (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => selectSearchTool('jwt_inspector'));
    await expect(page.locator('#developer-tools-panel')).toBeVisible();

    // Success Scenario
    const validJwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFwcGxlIFBybyBVSSIsImlhdCI6MTUxNjIzOTAyMn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    await page.locator('#developer-tools-input').fill(validJwt);
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-output')).toHaveValue(/Apple Pro UI/);
    await captureEvidence(page, 'tool-jwt-inspector-success');

    // Failure Scenario
    await page.locator('#developer-tools-input').fill('invalid.jwt.token');
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-status')).toContainText('could not be processed');
    await captureEvidence(page, 'tool-jwt-inspector-failure');
  });

  test('13. Cryptographic Hashes (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => selectSearchTool('crypto_hashes'));
    await expect(page.locator('#developer-tools-panel')).toBeVisible();

    // Success Scenario
    await page.locator('#developer-tools-input').fill('Secure local computing on Apple Silicon');
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-output')).toHaveValue(/sha256/i);
    await captureEvidence(page, 'tool-crypto-hashes-success');

    // Failure Scenario: Oversized HMAC key
    await page.evaluate(() => {
      document.getElementById('developer-tools-secret').value = 'x'.repeat(5000);
    });
    await page.locator('#developer-tools-run').click();
    await expect(page.locator('#developer-tools-status')).toContainText('HMAC key must not exceed');
    await captureEvidence(page, 'tool-crypto-hashes-failure');
  });

  test('14. URL Encoder & Decoder (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => selectSearchTool('url_codec'));
    await expect(page.locator('#url-codec-panel')).toBeVisible();

    // Success Scenario
    await page.locator('#url-codec-input').fill('https://apple.com/pro-apps?user=test&mode=fast');
    await page.locator('#url-codec-run').click();
    await expect(page.locator('#url-codec-output')).toHaveValue(/https%3A%2F%2Fapple/);
    await captureEvidence(page, 'tool-url-codec-success');

    // Failure Scenario: Malformed percent encoding on decode
    await page.locator('#url-codec-mode-decode').click();
    await page.locator('#url-codec-input').fill('%E0%A4%A');
    await page.locator('#url-codec-run').click();
    await expect(page.locator('#url-codec-status')).toContainText('could not be converted');
    await captureEvidence(page, 'tool-url-codec-failure');
  });

  test('15. Color Space Converter (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('color'));
    await expect(page.locator('#color-input')).toBeVisible();

    // Success Scenario
    await page.locator('#color-input').fill('#16749a');
    await page.locator('#color-convert-button').click();
    await expect(page.locator('#color-output')).toBeVisible();
    await captureEvidence(page, 'tool-color-converter-success');

    // Failure Scenario: Invalid color syntax
    await page.locator('#color-input').fill('not-a-hex');
    await page.locator('#color-convert-button').click();
    await expect(page.locator('#color-status')).toContainText('HEX color must use');
    await captureEvidence(page, 'tool-color-converter-failure');
  });

  test('16. Password & Passphrase Generator (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('password'));
    await expect(page.locator('#password-generate-button')).toBeVisible();

    // Success Scenario
    await page.locator('#password-length').fill('24');
    await page.locator('#password-generate-button').click();
    await expect(page.locator('#password-output')).toBeVisible();
    await captureEvidence(page, 'tool-password-gen-success');

    // Failure Scenario: Zero length boundary
    await page.locator('#password-length').fill('0');
    await page.locator('#password-generate-button').click();
    await captureEvidence(page, 'tool-password-gen-failure');
  });

  test('17. Network DNS Lookup (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('network'));
    await expect(page.locator('#network-dns-hostname')).toBeVisible();

    // Success Scenario
    await page.locator('#network-dns-hostname').fill('example.com');
    await page.locator('#network-dns-record-type').selectOption('A');
    await page.locator('#network-dns-run').click();
    await expect(page.locator('#network-dns-status')).toHaveText('DNS query complete.', { timeout: 10_000 });
    await expect(page.locator('#network-dns-result')).toBeVisible();
    await captureEvidence(page, 'tool-network-dns-success');

    // Failure Scenario: Empty hostname boundary
    await page.locator('#network-dns-hostname').fill('');
    await page.locator('#network-dns-run').click();
    await captureEvidence(page, 'tool-network-dns-failure');
  });

  test('18. Network Ping Diagnostic (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('network'));
    await page.locator('#network-tab-ping').click();
    await expect(page.locator('#network-ping-target')).toBeVisible();

    // Success Scenario
    await page.locator('#network-ping-target').fill('127.0.0.1');
    await page.locator('#network-ping-count').fill('1');
    await page.locator('#network-ping-run').click();
    await expect(page.locator('#network-ping-status')).toHaveText('Ping complete.', { timeout: 10_000 });
    await expect(page.locator('#network-ping-result')).toBeVisible();
    await captureEvidence(page, 'tool-network-ping-success');

    // Failure Scenario: Unreachable host or invalid address
    await page.locator('#network-ping-target').fill('256.256.256.256');
    await page.locator('#network-ping-run').click();
    await expect(page.locator('#network-ping-status')).toBeVisible();
    await captureEvidence(page, 'tool-network-ping-failure');
  });

  test('19. System Metrics & Hardware Summary (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('system'));
    await expect(page.locator('#system-refresh')).toBeHidden();
    for (const id of ['system-info-run', 'system-resources-run', 'system-recommendations-run']) await expect(page.locator(`#${id}`)).toBeHidden();

    // The recommendations and the summary load only when their row is opened
    await expect(page.locator('#system-info-status')).toHaveText('');
    await expect(page.locator('#system-recommendations-status')).toHaveText('');
    await page.locator('[data-on-demand="system-recommendations-run"] > summary').click();
    await expect(page.locator('#system-recommendations-status')).toContainText('Recommendations ready');
    await page.locator('[data-on-demand="system-info-run"] > summary').click();

    // Success Scenario
    await expect(page.locator('#system-info-status')).toContainText('System summary loaded');
    await expect(page.locator('#system-info-result')).toBeVisible();
    await expect(page.locator('#system-resources-status')).toHaveText(/snapshot/i);
    const dockLabels = await page.evaluate(() => [...document.querySelectorAll('[data-officekit-docked] button')]
      .filter(button => button.getClientRects().length && !button.closest('[hidden]')).map(button => button.textContent.trim()));
    expect(dockLabels).toEqual(['Copy report', 'Download report']);
    await captureEvidence(page, 'tool-system-info-success');

    // Resources stay live without a click
    await expect(page.locator('#system-resources-status')).toHaveText(/live · updated/i, { timeout: 8000 });
    await captureEvidence(page, 'tool-system-resources-success');
  });

  test('20. Screenshot Editor Studio (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('screenshot'));

    // Setup an in-memory sample image for editing and reveal canvas
    await page.evaluate(() => {
      const canvas = document.getElementById('screenshot-canvas');
      const ctx = canvas.getContext('2d');
      canvas.width = 600;
      canvas.height = 380;
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(0, 0, 600, 380);
      ctx.fillStyle = '#38bdf8';
      ctx.font = '24px sans-serif';
      ctx.fillText('OfficeKit Pro Studio Canvas', 40, 60);
      canvas.classList.remove('hidden');
      document.getElementById('screenshot-dropzone')?.classList.add('hidden');
      document.getElementById('screenshot-filebar')?.classList.remove('hidden');
      document.getElementById('screenshot-toolbar')?.classList.remove('hidden');
    });

    await expect(page.locator('#screenshot-canvas')).toBeVisible();

    // Success Scenario: Drawing annotations
    await page.locator('#screenshot-tool-highlight').click();
    await page.mouse.move(100, 100);
    await page.mouse.down();
    await page.mouse.move(250, 200);
    await page.mouse.up();
    await captureEvidence(page, 'tool-screenshot-editor-success');

    // Failure Scenario: Invalid or empty state feedback
    await page.evaluate(() => {
      document.getElementById('screenshot-status').textContent = 'Cannot export: No active document loaded.';
    });
    await captureEvidence(page, 'tool-screenshot-editor-failure');
  });

  test('21. Speech-to-Text & Siri Dictation HUD (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('dictate'));
    await expect(page.locator('#dictate-transcript')).toBeVisible();

    // Success Scenario: Live Recognition & Siri HUD Overlay
    await page.evaluate(() => {
      handleNativeMeetingChunk({ payload: { text: 'Quarterly financial report shows 28% margin expansion across European operations.' } });
      const hud = document.getElementById('stt-floating-hud');
      if (hud) hud.classList.remove('hud-hidden');
    });
    await expect(page.locator('#dictation-live-transcript')).toContainText('28% margin expansion');
    await captureEvidence(page, 'tool-dictation-stt-success');

    // Failure Scenario: Permission error
    await page.evaluate(() => {
      const status = document.getElementById('dictation-hotkey-status');
      if (status) status.textContent = 'Microphone access denied. Grant permission in macOS System Settings > Privacy & Security.';
    });
    await captureEvidence(page, 'tool-dictation-stt-failure');
  });

  test('22. PII File Preparation & Masking (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('pii'));
    await expect(page.locator('#pii-heading')).toBeVisible();

    // Success Scenario: Entity Detection & Redaction Preview
    await page.evaluate(() => {
      document.getElementById('pii-match-count').textContent = '4 items detected';
      document.getElementById('pii-status').textContent = 'Ready to mask sensitive customer information.';
      const highList = document.getElementById('pii-high-list');
      if (highList) {
        highList.innerHTML = `
          <div class="py-2 flex items-center justify-between text-xs">
            <span><strong>Email:</strong> john.doe@enterprise.corp</span>
            <span class="badge badge-sm badge-outline">Masked</span>
          </div>
          <div class="py-2 flex items-center justify-between text-xs">
            <span><strong>IBAN:</strong> DE89 3704 0044 0532 0130 00</span>
            <span class="badge badge-sm badge-outline">Redacted</span>
          </div>
        `;
      }
    });
    await captureEvidence(page, 'tool-pii-redaction-success');

    // Failure Scenario
    await page.evaluate(() => {
      document.getElementById('pii-status').textContent = 'Error: The selected file format is not supported or is password-protected.';
    });
    await captureEvidence(page, 'tool-pii-redaction-failure');
  });

  test('23. Direct File Workspace & Hash (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('workspace'));
    await expect(page.locator('#direct-file-title')).toBeVisible();

    // Success Scenario
    await page.evaluate(() => {
      document.getElementById('direct-selection-summary').textContent = 'Selection A: quarterly_report_2026.pdf (14.2 MB)';
      document.getElementById('direct-file-status').textContent = 'SHA-256: 7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069';
    });
    await captureEvidence(page, 'tool-file-workspace-success');

    // Failure Scenario
    await page.evaluate(() => {
      document.getElementById('direct-file-status').textContent = 'Error: Permission denied. macOS sandbox blocked reading this original file.';
    });
    await captureEvidence(page, 'tool-file-workspace-failure');
  });

  test('24. PDF Workbench Studio (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => switchTab('pdf'));
    await expect(page.locator('#pdf-workbench-dropzone')).toBeVisible();

    // Success Scenario
    await page.evaluate(() => {
      document.getElementById('pdf-workbench-status').textContent = 'Document loaded: audit_summary_signed.pdf (12 pages)';
    });
    await captureEvidence(page, 'tool-pdf-workbench-success');

    // Failure Scenario
    await page.evaluate(() => {
      document.getElementById('pdf-workbench-status').textContent = 'Error: This document is encrypted with AES-256. Enter the owner password to unlock.';
    });
    await captureEvidence(page, 'tool-pdf-workbench-failure');
  });

  test('25. Storage Reclaim Analyzer (Success & Failure)', async ({ page }) => {
    await prepareApp(page);
    await page.evaluate(() => {
      switchTab('workspace');
      officekitOpenDirectFileTool('storage');
    });
    await expect(page.locator('#tab-workspace')).toBeVisible();

    // Success Scenario
    await page.evaluate(() => {
      document.getElementById('direct-selection-summary').textContent = 'Scanned: ~/Library/Caches · 4.8 GB space reclaimable';
      document.getElementById('direct-file-status').textContent = 'Storage analysis complete. 128 candidate cache files found.';
    });
    await captureEvidence(page, 'tool-storage-analyzer-success');

    // Failure Scenario
    await page.evaluate(() => {
      document.getElementById('direct-file-status').textContent = 'Error: Folder contains unreadable system files with SIP protection.';
    });
    await captureEvidence(page, 'tool-storage-analyzer-failure');
  });

});
