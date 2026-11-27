#!/usr/bin/env node
// Split macOS notarization: stage a signed app, submit it to Apple without waiting, and finish later.
//
//   stage   --tag vX.Y.Z   copy the signed app to a durable folder on the runner (end of the build job)
//   submit  --tag vX.Y.Z   zip it and send it to Apple with `notarytool submit --no-wait` (manual workflow)
//   status  --tag vX.Y.Z   ask Apple for the verdict; sets the `ready` workflow output (manual workflow)
//   finish  --tag vX.Y.Z   staple and verify the app, build and sign the DMG (manual workflow)
//
// Apple's queue can take hours or days, so nothing here waits on it. State lives in
// ~/officekit-releases/<tag>/state.json, outside the checkout, so a later job cannot wipe it.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyBuiltApp } from './verify-built-license-config.mjs';

export const TAG_PATTERN = /^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$/;
export const SUBMISSION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const APP_NAME = 'OfficeKit.app';
export const DEFAULT_ROOT = path.join(os.homedir(), 'officekit-releases');
const MAX_LOG_ISSUES = 20;

export function releaseDirectory(tag, root = DEFAULT_ROOT) {
  if (typeof tag !== 'string' || !TAG_PATTERN.test(tag)) {
    throw new Error('The release tag must match vMAJOR.MINOR.PATCH.');
  }
  return path.join(root, tag);
}

export function readState(directory) {
  const file = path.join(directory, 'state.json');
  if (!fs.existsSync(file)) return null;
  const state = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!state || typeof state !== 'object' || !['built', 'submitted', 'finished'].includes(state.stage)) {
    throw new Error(`Unreadable release state in ${file}.`);
  }
  return state;
}

export function writeState(directory, state) {
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'state.json'), `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
}

export function parseSubmissionId(output) {
  let parsed;
  try { parsed = JSON.parse(output); } catch { throw new Error('Apple returned a submission that is not JSON.'); }
  const id = typeof parsed?.id === 'string' ? parsed.id.toLowerCase() : '';
  if (!SUBMISSION_ID_PATTERN.test(id)) throw new Error('Apple did not return a valid submission id.');
  return id;
}

export function classifyStatus(output) {
  let parsed;
  try { parsed = JSON.parse(output); } catch { return 'unknown'; }
  switch (String(parsed?.status || '').toLowerCase()) {
    case 'accepted': return 'accepted';
    case 'in progress': return 'in-progress';
    case 'invalid':
    case 'rejected': return 'rejected';
    default: return 'unknown';
  }
}

export function summarizeLog(output) {
  let parsed;
  try { parsed = JSON.parse(output); } catch { return ['The Apple log could not be read.']; }
  const issues = Array.isArray(parsed?.issues) ? parsed.issues : [];
  const lines = issues.slice(0, MAX_LOG_ISSUES).map(issue => `${issue.path || '?'}: ${issue.message || 'no message'}`);
  if (issues.length > MAX_LOG_ISSUES) lines.push(`…and ${issues.length - MAX_LOG_ISSUES} more.`);
  return lines.length ? lines : [`Apple reported ${parsed?.statusSummary || 'a rejection'} with no issue list.`];
}

export function credentials(environment = process.env) {
  const keyId = environment.APPLE_API_KEY;
  const issuer = environment.APPLE_API_ISSUER;
  const keyPath = environment.APPLE_API_KEY_PATH;
  if (!/^[A-Z0-9]{10}$/.test(keyId || '')) throw new Error('APPLE_API_KEY must be the 10-character key id.');
  if (!SUBMISSION_ID_PATTERN.test((issuer || '').toLowerCase())) throw new Error('APPLE_API_ISSUER must be the issuer UUID.');
  if (!keyPath || !fs.existsSync(keyPath)) throw new Error('APPLE_API_KEY_PATH must point to the App Store Connect key file.');
  return { keyId, issuer, keyPath };
}

export function notarytoolArguments(action, { keyId, issuer, keyPath, target }) {
  const auth = ['--key-id', keyId, '--issuer', issuer, '--key', keyPath, '--output-format', 'json'];
  if (action === 'submit') return ['notarytool', 'submit', target, '--no-wait', ...auth];
  if (action === 'info') return ['notarytool', 'info', target, ...auth];
  if (action === 'log') return ['notarytool', 'log', target, ...auth];
  throw new Error(`Unknown notarytool action: ${action}`);
}

export function dmgFileName(version, machine = os.arch()) {
  return `OfficeKit_${version}_${machine === 'arm64' ? 'aarch64' : 'x64'}.dmg`;
}

const defaultRun = (command, args) => execFileSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });

function setOutput(name, value, environment) {
  if (environment.GITHUB_OUTPUT) fs.appendFileSync(environment.GITHUB_OUTPUT, `${name}=${value}\n`);
}

export function stage({ tag, appPath, root = DEFAULT_ROOT, run = defaultRun, force = false, now = () => new Date() }) {
  const directory = releaseDirectory(tag, root);
  if (!fs.existsSync(appPath)) throw new Error(`The signed app is missing: ${appPath}`);
  const existing = readState(directory);
  if (existing && existing.stage !== 'built' && !force) {
    throw new Error(`${tag} is already ${existing.stage}; building it again would orphan the Apple submission. Use a new tag.`);
  }
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(directory, { recursive: true });
  run('ditto', [appPath, path.join(directory, APP_NAME)]);
  run('codesign', ['--verify', '--deep', '--strict', path.join(directory, APP_NAME)]);
  const state = { stage: 'built', tag, stagedAt: now().toISOString() };
  writeState(directory, state);
  return state;
}

export function submit({ tag, root = DEFAULT_ROOT, run = defaultRun, environment = process.env, now = () => new Date() }) {
  const directory = releaseDirectory(tag, root);
  const state = readState(directory);
  if (!state) throw new Error(`${tag} has not been built and staged on this runner. Run the build first.`);
  if (state.stage !== 'built') throw new Error(`${tag} is already ${state.stage}; it is submitted only once.`);
  const keys = credentials(environment);
  const zip = path.join(directory, 'OfficeKit.zip');
  fs.rmSync(zip, { force: true });
  run('ditto', ['-c', '-k', '--keepParent', path.join(directory, APP_NAME), zip]);
  const id = parseSubmissionId(run('xcrun', notarytoolArguments('submit', { ...keys, target: zip })));
  fs.rmSync(zip, { force: true });
  const next = { ...state, stage: 'submitted', submissionId: id, submittedAt: now().toISOString() };
  writeState(directory, next);
  return next;
}

export function status({ tag, root = DEFAULT_ROOT, run = defaultRun, environment = process.env, log = console.log }) {
  const directory = releaseDirectory(tag, root);
  const state = readState(directory);
  if (!state || state.stage !== 'submitted') {
    throw new Error(`${tag} is not waiting on Apple (state: ${state ? state.stage : 'not staged'}).`);
  }
  const keys = credentials(environment);
  const verdict = classifyStatus(run('xcrun', notarytoolArguments('info', { ...keys, target: state.submissionId })));
  if (verdict === 'rejected') {
    let detail;
    try { detail = summarizeLog(run('xcrun', notarytoolArguments('log', { ...keys, target: state.submissionId }))); } catch { detail = ['The Apple log could not be fetched.']; }
    throw new Error(`Apple rejected ${tag}:\n${detail.join('\n')}`);
  }
  if (verdict === 'unknown') throw new Error('Apple returned a status this script does not understand.');
  log(verdict === 'accepted' ? `Apple accepted ${tag}.` : `Apple is still reviewing ${tag}; run this again later. Nothing was lost.`);
  return verdict;
}

export function finish({ tag, version, repoRoot, root = DEFAULT_ROOT, run = defaultRun, environment = process.env, machine = os.arch(), now = () => new Date() }) {
  const directory = releaseDirectory(tag, root);
  const state = readState(directory);
  if (!state || state.stage !== 'submitted') throw new Error(`${tag} has no accepted submission to finish.`);
  if (version !== tag.slice(1).split(/[-+]/)[0]) throw new Error('The checked-out version does not match the release tag.');
  const identity = environment.APPLE_SIGNING_IDENTITY;
  if (!identity || !identity.startsWith('Developer ID Application:')) throw new Error('A Developer ID Application identity is required to sign the DMG.');
  const app = path.join(directory, APP_NAME);
  // A rerun after a later failure (say the DMG smoke) finds the ticket already attached, and stapling a
  // second time can fail on a bundle that was already modified. Staple only when no ticket validates yet.
  let alreadyStapled = true;
  try { run('xcrun', ['stapler', 'validate', app]); } catch { alreadyStapled = false; }
  if (!alreadyStapled) run('xcrun', ['stapler', 'staple', app]);
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', app]);
  run('spctl', ['--assess', '--type', 'execute', '--verbose=4', app]);
  run('xcrun', ['stapler', 'validate', app]);

  // The DMG is built after stapling so the app inside carries its ticket and opens offline.
  const dmgDirectory = path.join(repoRoot, 'src-tauri', 'target', 'release', 'bundle', 'dmg');
  fs.rmSync(dmgDirectory, { recursive: true, force: true });
  fs.mkdirSync(dmgDirectory, { recursive: true });
  const staging = path.join(directory, 'dmg-staging');
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging);
  run('ditto', [app, path.join(staging, APP_NAME)]);
  fs.symlinkSync('/Applications', path.join(staging, 'Applications'));
  const dmg = path.join(dmgDirectory, dmgFileName(version, machine));
  run('hdiutil', ['create', '-volname', 'OfficeKit', '-srcfolder', staging, '-ov', '-format', 'UDZO', dmg]);
  fs.rmSync(staging, { recursive: true, force: true });
  run('codesign', ['--force', '--timestamp', '--sign', identity, dmg]);
  run('codesign', ['--verify', '--strict', '--verbose=2', dmg]);
  run('hdiutil', ['verify', dmg]);
  const next = { ...state, stage: 'finished', dmg, finishedAt: now().toISOString() };
  writeState(directory, next);
  return next;
}

function parseArguments(argv) {
  const [command, ...rest] = argv;
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    if (rest[index] === '--force') options.force = true;
    else if (rest[index].startsWith('--') && rest[index + 1] !== undefined) { options[rest[index].slice(2)] = rest[index + 1]; index += 1; }
  }
  return { command, options };
}

export async function main(argv = process.argv.slice(2), environment = process.env) {
  const { command, options } = parseArguments(argv);
  const tag = options.tag;
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  if (command === 'stage') {
    const appPath = options.app || path.join(repoRoot, 'src-tauri/target/release/bundle/macos', APP_NAME);
    // Never stage (and so never send to Apple) a build that cannot activate.
    const licenceErrors = verifyBuiltApp(appPath, environment);
    if (licenceErrors.length > 0) throw new Error(licenceErrors.join('\n'));
    const state = stage({ tag, appPath, force: options.force === true });
    console.log(`Staged ${tag} (${state.stage}) in ${releaseDirectory(tag)}.`);
  } else if (command === 'submit') {
    const state = submit({ tag, environment });
    console.log(`Submitted ${tag} to Apple. Submission id: ${state.submissionId}. It is not waited on; run "Finish macOS release" later.`);
    if (environment.GITHUB_STEP_SUMMARY) fs.appendFileSync(environment.GITHUB_STEP_SUMMARY, `Submitted \`${tag}\` to Apple. Submission id: \`${state.submissionId}\`.\n`);
  } else if (command === 'status') {
    const verdict = status({ tag, environment });
    setOutput('ready', verdict === 'accepted' ? 'true' : 'false', environment);
  } else if (command === 'finish') {
    const version = JSON.parse(fs.readFileSync(path.join(repoRoot, 'package.json'), 'utf8')).version;
    const state = finish({ tag, version, repoRoot, environment });
    console.log(`Finished ${tag}: ${state.dmg}`);
  } else {
    throw new Error('Usage: macos-notarize.mjs stage|submit|status|finish --tag vX.Y.Z');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    console.error(`::error::${String(error.message || error).split('\n').join('%0A')}`);
    process.exit(1);
  });
}
