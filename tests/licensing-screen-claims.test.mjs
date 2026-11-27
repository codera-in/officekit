import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const html = fs.readFileSync('index.html', 'utf8');
const screen = html.match(/<section id="tab-pricing"[\s\S]*?<\/section>/)?.[0];

test('licensing screen describes available activation without inventing checkout or product claims', () => {
  assert.ok(screen, 'licensing screen exists');
  assert.match(screen, /Your OfficeKit license/);
  assert.match(screen, /This build does not offer purchases or checkout/);
  assert.match(screen, /If you already have a license key, activate it here/);
  assert.match(screen, /data-officekit-click="openLicenseModal\(\)"/);
  assert.doesNotMatch(screen, /mockCheckout|\$19|\$199|\$299|QBO|OFX|Turbo Server|Unlimited Bank Statement|OCR priority|Save 75%/i);
  assert.doesNotMatch(html, /function mockCheckout\s*\(/);
});
