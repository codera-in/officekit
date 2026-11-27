import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Release builds bake the pinned licence verification keys and API base URL into the binary
// (src-tauri/build.rs). build.rs defaults the keyring to "{}", which would ship an installer that
// can never be unlocked, so a release build must fail here instead. The limits mirror
// parse_pinned_keyring and configured_license_api_base_url in src-tauri/src/license_client.rs.
export const PRODUCTION_LICENSE_API_BASE_URL = 'https://api.officekit.app';
const MAX_KEYRING_BYTES = 32 * 1024;
const MAX_KEYS = 8;
const MAX_KEY_ID_LENGTH = 64;
const MAX_PEM_LENGTH = 4096;

export function validateReleaseLicenseConfig(env) {
  const errors = [];
  const rawKeys = env.OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON ?? '';
  if (rawKeys.trim() === '' || rawKeys.trim() === '{}') {
    errors.push('OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON is empty: a release build with no pinned keys can never unlock. Set the OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON repository variable.');
  } else if (/[\r\n]/.test(rawKeys.trim())) {
    // build.rs hands the value to cargo as a single-line `cargo:rustc-env=` directive, so a multi-line
    // value is cut after its first line and the app embeds "{" (activation then fails as "invalid response").
    errors.push('OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON must be one line of compact JSON (no newlines); the PEM line breaks stay as \\n escapes.');
  } else if (Buffer.byteLength(rawKeys) > MAX_KEYRING_BYTES) {
    errors.push('OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON is larger than the 32 KiB keyring limit.');
  } else {
    let keys = null;
    try { keys = JSON.parse(rawKeys); } catch { /* reported below */ }
    const entries = keys !== null && typeof keys === 'object' && !Array.isArray(keys) ? Object.entries(keys) : null;
    if (entries === null) {
      errors.push('OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON must be a JSON object of key id to PEM public key.');
    } else if (entries.length === 0 || entries.length > MAX_KEYS) {
      errors.push(`OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON must pin between 1 and ${MAX_KEYS} keys.`);
    } else if (entries.some(([kid, pem]) => kid === '' || kid.length > MAX_KEY_ID_LENGTH || !/^[\x20-\x7e]+$/.test(kid)
      || typeof pem !== 'string' || pem.length > MAX_PEM_LENGTH || !pem.includes('-----BEGIN PUBLIC KEY-----'))) {
      errors.push('OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON has an invalid key id or a value that is not a PEM public key.');
    }
  }
  const baseUrl = env.OFFICEKIT_LICENSE_API_BASE_URL ?? '';
  if (baseUrl === '') {
    errors.push('OFFICEKIT_LICENSE_API_BASE_URL is empty. Set the OFFICEKIT_LICENSE_API_BASE_URL repository variable.');
  } else if (baseUrl !== PRODUCTION_LICENSE_API_BASE_URL) {
    errors.push(`OFFICEKIT_LICENSE_API_BASE_URL must be ${PRODUCTION_LICENSE_API_BASE_URL} in a release build.`);
  }
  return errors;
}

export function main(env = process.env, log = console) {
  const errors = validateReleaseLicenseConfig(env);
  for (const message of errors) log.error(`::error::${message}`);
  if (errors.length === 0) log.log('Release licence configuration is present.');
  return errors.length === 0 ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
