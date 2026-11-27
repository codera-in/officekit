import fs from 'node:fs';
import path from 'node:path';

// build.rs bakes the pinned licence keys into the compiled binary. If the build step did not receive
// them, the keyring is empty and every activation fails with "License verification is not configured
// in this build." (v1.0.108 shipped like that). The env check cannot see this because it runs in its
// own step, so this reads the finished binary itself.
const PEM_BODY_LENGTH = 48;

export function pinnedKeyMarkers(keysJson) {
  let keys;
  try {
    keys = JSON.parse(keysJson);
  } catch {
    return [];
  }
  if (!keys || typeof keys !== 'object' || Array.isArray(keys)) return [];
  return Object.entries(keys).flatMap(([id, pem]) => {
    const body = String(pem).replace(/-----[A-Z ]+-----/g, '').replace(/\\n|\s/g, '');
    return [id, body.slice(0, PEM_BODY_LENGTH)];
  }).filter(Boolean);
}

export function verifyBinaryLicenseConfig(binary, env) {
  const markers = pinnedKeyMarkers(env.OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON ?? '');
  if (markers.length === 0) return ['OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON is missing or is not a JSON object of key id to PEM, so nothing can be checked in the binary.'];
  const errors = [];
  for (const marker of markers) {
    if (!binary.includes(marker)) errors.push(`The built binary does not embed the pinned licence key marker "${marker.slice(0, 12)}…". It was built without OFFICEKIT_LICENSE_PUBLIC_KEYS_JSON and could never activate.`);
  }
  const baseUrl = env.OFFICEKIT_LICENSE_API_BASE_URL;
  if (baseUrl && !binary.includes(baseUrl)) errors.push(`The built binary does not embed the licence API base URL ${baseUrl}.`);
  return errors;
}

export function verifyBuiltApp(appPath, env, binaryName = 'officekit') {
  const binaryPath = path.join(appPath, 'Contents', 'MacOS', binaryName);
  if (!fs.existsSync(binaryPath)) return [`The app binary is missing: ${binaryPath}`];
  return verifyBinaryLicenseConfig(fs.readFileSync(binaryPath), env);
}
