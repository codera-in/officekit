import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from './helpers/vm.mjs';

const html = fs.readFileSync('index.html', 'utf8');
const functionSource = name => html.match(new RegExp(`async function ${name}\\([\\s\\S]*?\\n        }`))?.[0];
const plainFunctionSource = name => html.match(new RegExp(`(?<!async )function ${name}\\([\\s\\S]*?\\n        }`))?.[0];

function makeClient(invoke, { email = '  buyer@example.com  ', key = '  OK1.key.secret  ' } = {}) {
  const focused = [];
  const attrs = {};
  const emailInput = {
    value: email,
    attrs,
    focus() { focused.push('email'); },
    setAttribute(name, value) { attrs[name] = value; },
    removeAttribute(name) { delete attrs[name]; },
  };
  const keyInput = { value: key, focus() { focused.push('key'); } };
  const status = { textContent: '' };
  const button = { disabled: false };
  let closed = false;
  const context = {
    window: { __TAURI__: { core: { invoke } } },
    document: { getElementById: id => ({
      'license-email': emailInput,
      'license-key': keyInput,
      'license-activation-status': status,
      'license-activate-submit': button,
      'license-status-text': status,
      'license-badge-btn': { className: '' },
      'license-modal': { classList: { add: name => { if (name === 'hidden') closed = true; }, remove: name => { if (name === 'hidden') closed = false; } } },
    })[id] },
    checkLicenseStatus: async () => {},
  };
  vm.runInNewContext(functionSource('submitLicenseActivation'), context);
  vm.runInNewContext(plainFunctionSource('clearLicenseEmailInvalid'), context);
  vm.runInNewContext(plainFunctionSource('closeLicenseModal'), context);
  vm.runInNewContext(plainFunctionSource('openLicenseModal'), context);
  return { context, emailInput, keyInput, status, button, focused, isClosed: () => closed };
}

test('desktop activation sends the trimmed email and key through the native command and clears both on success', async () => {
  const calls = [];
  const client = makeClient(async (...args) => {
    calls.push(args);
    return { device_slots_used: 1, device_slots_allowed: 3 };
  });
  await client.context.submitLicenseActivation();
  assert.equal(JSON.stringify(calls), JSON.stringify([['license_activate', { email: 'buyer@example.com', licenseKey: 'OK1.key.secret' }]]));
  assert.equal(client.emailInput.value, '');
  assert.equal(client.keyInput.value, '');
  assert.match(client.status.textContent, /1 of 3 device slots/);
  assert.equal(client.isClosed(), true);
  assert.equal(client.button.disabled, false);
  assert.deepEqual(client.focused, []);
});

test('activation errors remain visible and neither the email nor the key is cleared', async () => {
  const calls = [];
  const client = makeClient(async (...args) => {
    calls.push(args);
    throw 'The email or license key is not valid. Check both and try again.';
  });
  await client.context.submitLicenseActivation();
  assert.equal(calls.length, 1);
  assert.equal(client.emailInput.value, '  buyer@example.com  ');
  assert.equal(client.keyInput.value, '  OK1.key.secret  ');
  assert.equal(client.status.textContent, 'The email or license key is not valid. Check both and try again.');
  assert.equal(client.isClosed(), false);
  assert.equal(client.button.disabled, false);
});

test('an Error object from the native command is shown and other failures use the fallback text', async () => {
  const withError = makeClient(async () => { throw new Error('The licensing service is unavailable. Try again when you are online.'); });
  await withError.context.submitLicenseActivation();
  assert.equal(withError.status.textContent, 'The licensing service is unavailable. Try again when you are online.');
  const withNothing = makeClient(async () => { throw {}; });
  await withNothing.context.submitLicenseActivation();
  assert.equal(withNothing.status.textContent, 'Activation could not be completed. Try again.');
});

test('an empty or malformed email blocks submit, focuses the email field and never calls the native command', async () => {
  for (const email of ['', '   ', 'buyer', 'buyer@', '@example.com', 'buyer@example', 'bu yer@example.com', 'a@b@example.com', `${'a'.repeat(250)}@example.com`]) {
    const calls = [];
    const client = makeClient(async (...args) => { calls.push(args); return {}; }, { email });
    await client.context.submitLicenseActivation();
    assert.equal(calls.length, 0, `invoked for ${JSON.stringify(email)}`);
    assert.deepEqual(client.focused, ['email']);
    assert.equal(client.status.textContent, 'Enter the email you purchased with to continue.');
    assert.equal(client.keyInput.value, '  OK1.key.secret  ');
    assert.equal(client.isClosed(), false);
  }
});

test('an empty key blocks submit and focuses the key field once the email is valid', async () => {
  const calls = [];
  const client = makeClient(async (...args) => { calls.push(args); return {}; }, { key: '   ' });
  await client.context.submitLicenseActivation();
  assert.equal(calls.length, 0);
  assert.deepEqual(client.focused, ['key']);
  assert.equal(client.status.textContent, 'Enter your license key to continue.');
});

test('outside the desktop app activation explains that it needs the OfficeKit app', async () => {
  const client = makeClient(undefined);
  client.context.window.__TAURI__ = undefined;
  await client.context.submitLicenseActivation();
  assert.equal(client.status.textContent, 'License activation is available in the OfficeKit desktop app.');
});

test('activation form asks for the purchase email above the key and does not claim a local HTTP activation endpoint', () => {
  assert.match(html, /id="license-modal-title"[^>]*>Activate OfficeKit/);
  const email = html.match(/<input[^>]*id="license-email"[^>]*>/)?.[0];
  assert.ok(email, 'license email input is present');
  assert.match(email, /type="email"/);
  assert.match(email, /autocomplete="email"/);
  assert.match(email, /maxlength="254"/);
  assert.match(html, /<label for="license-email"[^>]*>Purchase email<\/label>/);
  assert.ok(html.indexOf('id="license-email"') < html.indexOf('id="license-key"'), 'email comes before the key');
  assert.match(html, /<input type="password" id="license-key"/);
  assert.match(html, /invoke\('license_activate', \{ email, licenseKey: key \}\)/);
  assert.doesNotMatch(html, /fetch\([^)]*\/api\/license\/activate/);
});

const emailOfLength = length => `${'a'.repeat(length - '@example.com'.length)}@example.com`;

test('the email length limit is exactly 254: 254 is sent, 255 is blocked', async () => {
  const calls = [];
  const ok = makeClient(async (...args) => { calls.push(args); return { device_slots_used: 1, device_slots_allowed: 1 }; }, { email: emailOfLength(254) });
  await ok.context.submitLicenseActivation();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].email.length, 254);
  const tooLong = makeClient(async (...args) => { calls.push(args); return {}; }, { email: emailOfLength(255) });
  await tooLong.context.submitLicenseActivation();
  assert.equal(calls.length, 1, '255 characters must not reach the native command');
  assert.deepEqual(tooLong.focused, ['email']);
});

test('an invalid email sets aria-invalid, and typing or the next submit clears it', async () => {
  const client = makeClient(async () => ({ device_slots_used: 1, device_slots_allowed: 1 }), { email: 'nope' });
  await client.context.submitLicenseActivation();
  assert.equal(client.emailInput.attrs['aria-invalid'], 'true');
  client.context.clearLicenseEmailInvalid();
  assert.equal('aria-invalid' in client.emailInput.attrs, false);
  await client.context.submitLicenseActivation();
  assert.equal(client.emailInput.attrs['aria-invalid'], 'true');
  client.emailInput.value = 'buyer@example.com';
  await client.context.submitLicenseActivation();
  assert.equal('aria-invalid' in client.emailInput.attrs, false);
});

test('the email field is wired to the status line and clears its invalid flag on input', () => {
  const email = html.match(/<input[^>]*id="license-email"[^>]*>/)?.[0];
  assert.match(email, /aria-describedby="license-activation-status"/);
  assert.match(email, /data-officekit-input="clearLicenseEmailInvalid\(\)"/);
  assert.match(html, /'clearLicenseEmailInvalid',/);
});

test('closing the modal resets both fields, the status line and the invalid flag', async () => {
  const client = makeClient(async () => { throw 'The email or license key is not valid. Check both and try again.'; });
  await client.context.submitLicenseActivation();
  client.emailInput.setAttribute('aria-invalid', 'true');
  client.context.closeLicenseModal();
  assert.equal(client.emailInput.value, '');
  assert.equal(client.keyInput.value, '');
  assert.equal(client.status.textContent, '');
  assert.equal('aria-invalid' in client.emailInput.attrs, false);
  assert.equal(client.isClosed(), true);
  client.status.textContent = 'stale';
  client.context.openLicenseModal();
  assert.equal(client.status.textContent, '');
  assert.equal(client.isClosed(), false);
});

test('progress copy names both the email and the key', async () => {
  let during;
  const client = makeClient(async () => { during = client.status.textContent; return { device_slots_used: 1, device_slots_allowed: 1 }; });
  await client.context.submitLicenseActivation();
  assert.equal(during, 'Verifying your email and key, and binding this device securely…');
});
