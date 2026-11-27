import { spawn, spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { Buffer } from 'node:buffer';
import { deflateRawSync, deflateSync, inflateRawSync } from 'node:zlib';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { findPythonWithPytest, getPythonCandidates } from './run-python-tests.mjs';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..');
const STATEMENT_SMOKE_TIMEOUT_MS = 120_000;
export const SIDECAR_FIRST_LAUNCH_TIMEOUT_MS = 120_000;
const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
let smokePortValue = process.env.OFFICEKIT_API_PORT || '8000';
if (!/^[0-9]{1,5}$/.test(smokePortValue) || Number(smokePortValue) < 1 || Number(smokePortValue) > 65535) {
  throw new Error('OFFICEKIT_API_PORT must be a decimal TCP port between 1 and 65535.');
}
let API_ORIGIN = `http://127.0.0.1:${smokePortValue}`;
let HEALTH_URL = `${API_ORIGIN}/api/health`;
const fetch = (input, init) => globalThis.fetch(
  typeof input === 'string' ? input.replaceAll(DEFAULT_API_ORIGIN, API_ORIGIN) : input,
  init,
);
const EXPECTED_APP_VERSION = JSON.parse(
  fs.readFileSync(path.join(REPO_ROOT, 'src-tauri', 'tauri.conf.json'), 'utf8'),
).version;

export function resolveSmokeBinary({
  root = REPO_ROOT,
  platform = process.platform,
  targetTriple,
  exists = fs.existsSync,
} = {}) {
  if (typeof targetTriple !== 'string' || !targetTriple || /[\\/\s]/.test(targetTriple)) {
    throw new Error('A valid Rust target triple is required to locate the OfficeKit sidecar.');
  }
  const pathApi = platform === 'win32' ? path.win32 : path.posix;
  const extension = platform === 'win32' ? '.exe' : '';
  if (platform === 'darwin') {
    const appBundleBackend = pathApi.join(
      root, '.build', 'backend-sidecar', 'dist', 'officekit-backend', 'officekit-backend',
    );
    if (exists(appBundleBackend)) return appBundleBackend;
  }
  return pathApi.join(root, 'src-tauri', 'binaries', `officekit-backend-${targetTriple}${extension}`);
}

export function isOfficeKitHealthResponse(status, payload, expectedVersion) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.status === 'ok' && payload.service === 'officekit-api' &&
    typeof expectedVersion === 'string' && expectedVersion.length > 0 &&
    payload.version === expectedVersion;
}

export function createSidecarSmokeFetch(fetchImpl) {
  if (typeof fetchImpl !== 'function') throw new Error('A sidecar smoke fetch function is required.');
  return async (input, init) => {
    const requestUrl = typeof input === 'string' ? input : input?.url;
    let pathname = 'unknown route';
    try { pathname = new URL(requestUrl).pathname; } catch (_) { /* Keep diagnostic details bounded. */ }
    try {
      return await fetchImpl(input, init);
    } catch (error) {
      throw new Error(`Sidecar smoke request ${(init?.method || 'GET').toUpperCase()} ${pathname} failed: ${error.message}`, { cause: error });
    }
  };
}

export function isPassphraseGeneratorResponse(status, payload, wordCount, separator = ' ') {
  if (status !== 200 || !payload || typeof payload !== 'object' ||
      !Number.isInteger(wordCount) || wordCount < 6 || wordCount > 12 ||
      ![' ', '.', '_'].includes(separator) || payload.word_count !== wordCount ||
      payload.separator !== separator || typeof payload.passphrase !== 'string' ||
      payload.passphrase.length > 512 || !Number.isFinite(payload.theoretical_search_space_bits)) return false;
  const words = payload.passphrase.split(separator);
  return words.length === wordCount && words.every(word => /^[a-z]+(?:-[a-z]+)?$/.test(word)) &&
    Math.abs(payload.theoretical_search_space_bits - wordCount * Math.log2(7776)) < 1e-12;
}

export function isRelatedPdfSearchResponse(status, payload) {
  if (status !== 200 || !payload || typeof payload !== 'object' ||
      !Array.isArray(payload.tools) || payload.tools.length > 100) return false;
  const records = new Map();
  for (const tool of payload.tools) {
    if (!tool || typeof tool !== 'object' || typeof tool.id !== 'string' ||
        typeof tool.name !== 'string' || typeof tool.desc !== 'string' || records.has(tool.id)) return false;
    records.set(tool.id, tool);
  }
  const statement = records.get('bank_statement');
  const pageImages = records.get('pdf_to_images');
  if (!statement || !pageImages) return false;
  const statementCopy = `${statement.name} ${statement.desc}`;
  const imageCopy = `${pageImages.name} ${pageImages.desc}`;
  return /supported.*(?:statement|bank)|(?:statement|bank).*supported/i.test(statement.desc) &&
    /\bcsv\b/i.test(statementCopy) &&
    /\bxls\b/i.test(statementCopy) && /\bxlsx\b/i.test(statementCopy) &&
    /\bpng\b/i.test(imageCopy) && /\b(?:jpeg|jpg)\b/i.test(imageCopy);
}

export function isLockedLicenseStatusResponse(status, payload) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.activated === false && payload.edition === null &&
    Array.isArray(payload.features) && payload.features.length === 0 &&
    payload.valid_until_epoch === null;
}

export function isLicenseRequiredResponse(status, payload) {
  return status === 403 && payload?.error?.code === 'license_required';
}

export function entitlementPushBody() {
  return JSON.stringify({
    activation_id: 'sidecarSmokeActivation',
    edition: 'paid',
    features: [],
    valid_for_seconds: 3600,
  });
}

// The packaged sidecar starts locked, so every paid route answers 403 license_required. Smokes that exercise
// paid routes install an entitlement the way the native shell does (PUT with the native grant); there is
// deliberately no off switch in the binary.
export async function installSmokeEntitlement({ origin, token, grantToken, fetchImpl = fetch }) {
  const response = await fetchImpl(`${origin}/api/license/entitlement`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-OfficeKit-Native-Grant': grantToken },
    body: entitlementPushBody(),
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status !== 204) {
    throw new Error(`The packaged sidecar rejected the smoke entitlement push (HTTP ${response.status}).`);
  }
}

export function isLicenseActivationUnavailableResponse(status, payload) {
  return status === 501 && payload !== null && typeof payload === 'object' &&
    payload.detail === 'Online activation is not available in this build.';
}

export function isCsvJsonConversionResponse(status, rows) {
  return status === 200 && Array.isArray(rows) && rows.length === 1 &&
    rows[0]?.name === 'Ada' && rows[0]?.amount === 3.5;
}

export function isYamlToJsonResponse(status, payload) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    !Array.isArray(payload) && Object.keys(payload).length === 1 &&
    payload.result === '{\n  "active": true,\n  "count": 2,\n  "name": "OfficeKit"\n}';
}

export function isJsonDecimalFidelityResponse(status, payload) {
  if (status !== 200 || !payload || Object.keys(payload).length !== 1 || typeof payload.result !== 'string') {
    return false;
  }
  return payload.result.includes('0.12345678901234567890123456789') &&
    payload.result.includes('1E+999') && payload.result.includes('1E-9999');
}

export function isDelimitedDataFidelityResponse(status, contentType, contentDisposition, bytes) {
  if (status !== 200 || typeof contentType !== 'string' ||
      contentType.toLowerCase().split(';', 1)[0].trim() !== 'application/json' ||
      typeof contentDisposition !== 'string' ||
      !/^attachment;\s*filename="accounts\.json";\s*filename\*=UTF-8''accounts\.json$/i.test(contentDisposition) ||
      !Buffer.isBuffer(bytes) || bytes.length > 1_048_576) return false;
  try {
    const rows = JSON.parse(bytes.toString('utf8'));
    return Array.isArray(rows) && rows.length === 2 &&
      Object.keys(rows[0]).sort().join(',') === 'amount,date,max_safe,precise,reference' &&
      Object.keys(rows[1]).sort().join(',') === 'amount,date,max_safe,precise,reference' &&
      rows[0].reference === '00001' && rows[0].amount === 0.125 &&
      rows[0].max_safe === 999999999999999 && rows[0].precise === '1234567890123456789' &&
      rows[0].date === '2026-10-07' && rows[1].reference === '00002' &&
      rows[1].amount === 0 && rows[1].max_safe === 999999999999998 &&
      rows[1].precise === '1234567890123456790' && rows[1].date === '01/02/2026';
  } catch (_) {
    return false;
  }
}

export function isXlsxDisplayFormatCsvResponse(status, csv) {
  const normalized = typeof csv === 'string' ? csv.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trimEnd() : '';
  const expected = [
    'currency,percentage,negative,zero,rounded',
    ['"$1,234.50"', '12.5%', '"(1,234.50)"', '-', '1.13'].join(','),
  ].join('\n');
  return status === 200 && normalized === expected;
}

export function isColorConversionResponse(status, payload) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.value === 'rgb(255, 0, 0)' && payload.source_format === 'hex' &&
    payload.target_format === 'rgb';
}

export function isPasswordGeneratorResponse(status, payload, expectedLength, includeSymbols) {
  if (status !== 200 || payload === null || typeof payload !== 'object' || Array.isArray(payload) ||
      Object.keys(payload).sort().join(',') !== 'password,theoretical_search_space_bits' ||
      typeof payload.password !== 'string' || payload.password.length !== expectedLength ||
      !Number.isFinite(payload.theoretical_search_space_bits) ||
      payload.theoretical_search_space_bits <= 0 || payload.theoretical_search_space_bits > 2048) return false;
  if (!/[a-z]/.test(payload.password) || !/[A-Z]/.test(payload.password) || !/[0-9]/.test(payload.password)) return false;
  if (includeSymbols) return /[!@#$%^&*()\-_=+\[\]{}<>?]/.test(payload.password);
  return /^[A-Za-z0-9]+$/.test(payload.password);
}

export function isMathEvaluationResponse(status, payload, expected) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.expression === expected?.expression && payload.angle_mode === expected?.angleMode &&
    Number.isFinite(payload.result) && Math.abs(payload.result - expected?.result) <= 1e-12;
}

function hasExactKeys(value, keys) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(','));
}

export function isMarginMarkupResponse(status, payload, expected = {
  cost: 80, revenue: 100, profit: 20, gross_margin_percent: 20, markup_percent: 25,
}) {
  if (status !== 200 || !hasExactKeys(payload, ['profit', 'gross_margin_percent', 'markup_percent', 'cost', 'revenue', 'assumptions']) ||
      payload.cost !== expected.cost || payload.revenue !== expected.revenue || payload.profit !== expected.profit ||
      payload.gross_margin_percent !== expected.gross_margin_percent || payload.markup_percent !== expected.markup_percent ||
      !hasExactKeys(payload.assumptions, ['margin_denominator', 'markup_denominator']) ||
      payload.assumptions.margin_denominator !== 'revenue' || payload.assumptions.markup_denominator !== 'cost') return false;
  return true;
}

export function isBreakEvenResponse(status, payload) {
  return status === 200 && hasExactKeys(payload, ['break_even_units', 'break_even_revenue', 'contribution_margin']) &&
    payload.break_even_units === 34 && payload.break_even_revenue === 1700 && payload.contribution_margin === 30 &&
    payload.break_even_units * payload.contribution_margin >= 1000 &&
    (payload.break_even_units - 1) * payload.contribution_margin < 1000;
}

export function isSimpleInterestResponse(status, payload) {
  if (status !== 200 || !hasExactKeys(payload, ['principal', 'annual_rate_percent', 'time_value', 'time_unit', 'time_in_years', 'interest_amount', 'total_amount', 'assumptions']) ||
      payload.principal !== 1000 || payload.annual_rate_percent !== 10 || payload.time_value !== 18 || payload.time_unit !== 'months' ||
      payload.time_in_years !== 1.5 || payload.interest_amount !== 150 || payload.total_amount !== 1150 ||
      !hasExactKeys(payload.assumptions, ['method', 'rate_basis', 'currency_precision', 'rounding', 'compounding'])) return false;
  return payload.assumptions.method === 'simple_interest' && payload.assumptions.rate_basis === 'nominal_annual' &&
    payload.assumptions.currency_precision === '0.01' && payload.assumptions.rounding === 'half_up' && payload.assumptions.compounding === 'none';
}

export function isDepreciationResponse(status, payload) {
  if (status !== 200 || !hasExactKeys(payload, ['annual_depreciation', 'total_depreciable', 'schedule', 'assumptions']) ||
      payload.annual_depreciation !== 3000 || payload.total_depreciable !== 9000 || !Array.isArray(payload.schedule) || payload.schedule.length !== 3 ||
      !hasExactKeys(payload.assumptions, ['method', 'currency_precision', 'rounding', 'final_period']) ||
      payload.assumptions.method !== 'straight_line' || payload.assumptions.currency_precision !== '0.01' ||
      payload.assumptions.rounding !== 'half_up' || payload.assumptions.final_period !== 'adjusted_to_salvage_value') return false;
  let expectedBookValue = 10_000;
  for (let index = 0; index < payload.schedule.length; index += 1) {
    const row = payload.schedule[index];
    if (!hasExactKeys(row, ['year', 'depreciation', 'book_value']) || row.year !== index + 1 ||
        !Number.isFinite(row.depreciation) || row.depreciation < 0 || !Number.isFinite(row.book_value)) return false;
    expectedBookValue = Math.round((expectedBookValue - row.depreciation) * 100) / 100;
    if (Math.abs(row.book_value - expectedBookValue) > 0.01) return false;
  }
  return Math.abs(payload.schedule.reduce((sum, row) => sum + row.depreciation, 0) - payload.total_depreciable) < 0.01 &&
    payload.schedule.at(-1).book_value === 1000;
}

function hasPercentageAssumptions(value) {
  return hasExactKeys(value, ['rounding', 'precision', 'currency', 'taxes']) && value.rounding === 'half_up' &&
    value.precision === '0.01' && value.currency === 'not_inferred' && value.taxes === 'excluded';
}

function halfUpToTwo(value) {
  return Math.sign(value) * Math.round((Math.abs(value) + Number.EPSILON * Math.max(1, Math.abs(value))) * 100) / 100;
}

export function isPercentOfResponse(status, payload, expected = { percent: 15, value: 240, result: 36 }) {
  return status === 200 && hasExactKeys(payload, ['percent', 'value', 'result', 'assumptions']) &&
    payload.percent === expected.percent && payload.value === expected.value && Number.isFinite(payload.result) &&
    payload.result === expected.result && hasPercentageAssumptions(payload.assumptions);
}

export function isPercentageChangeResponse(status, payload, expected = { original_value: 80, new_value: 100 }) {
  if (status !== 200 || !hasExactKeys(payload, ['original_value', 'new_value', 'change_value', 'change_percent', 'direction', 'assumptions']) ||
      payload.original_value !== expected.original_value || payload.new_value !== expected.new_value ||
      !Number.isFinite(payload.change_value) || !Number.isFinite(payload.change_percent) || !hasPercentageAssumptions(payload.assumptions)) return false;
  const difference = expected.new_value - expected.original_value;
  const expectedDirection = difference > 0 ? 'increase' : difference < 0 ? 'decrease' : 'no_change';
  return expected.original_value > 0 && payload.change_value === halfUpToTwo(difference) &&
    payload.change_percent === halfUpToTwo(difference * 100 / expected.original_value) && payload.direction === expectedDirection;
}

export function isDiscountResponse(status, payload, expected = { price: 100, discount_percent: 20 }) {
  if (status !== 200 || !hasExactKeys(payload, ['price', 'discount_percent', 'savings', 'discounted_price', 'assumptions']) ||
      payload.price !== expected.price || payload.discount_percent !== expected.discount_percent ||
      !Number.isFinite(payload.savings) || !Number.isFinite(payload.discounted_price) || !hasPercentageAssumptions(payload.assumptions)) return false;
  const savings = halfUpToTwo(expected.price * expected.discount_percent / 100);
  return expected.price >= 0 && expected.discount_percent >= 0 && expected.discount_percent <= 100 &&
    payload.savings === savings && payload.discounted_price === halfUpToTwo(expected.price - savings);
}

export function isLoanEmiResponse(status, payload) {
  const schedule = payload?.schedule;
  if (status !== 200 || payload?.tenure_months !== 60 || payload?.monthly_emi !== 2124.7 ||
      !Array.isArray(schedule) || schedule.length !== 60) return false;
  let previousBalance = 100_000;
  for (let index = 0; index < schedule.length; index += 1) {
    const row = schedule[index];
    if (row?.month !== index + 1 || !Number.isFinite(row?.payment) ||
        !Number.isFinite(row?.principal_paid) || !Number.isFinite(row?.interest_paid) ||
        !Number.isFinite(row?.remaining_balance)) return false;
    const cents = value => Math.round(value * 100);
    const expectedBalance = Math.max(0, cents(previousBalance) - cents(row.principal_paid));
    if (Math.abs(cents(row.payment) - cents(row.principal_paid) - cents(row.interest_paid)) > 1 ||
        Math.abs(cents(row.remaining_balance) - expectedBalance) > 1 ||
        (index < schedule.length - 1 && Math.abs(row.payment - payload.monthly_emi) > 0.01)) return false;
    previousBalance = row.remaining_balance;
  }
  const principalPaid = schedule.reduce((sum, row) => sum + row.principal_paid, 0);
  const payments = schedule.reduce((sum, row) => sum + row.payment, 0);
  const interest = schedule.reduce((sum, row) => sum + row.interest_paid, 0);
  return previousBalance === 0 && Math.round(principalPaid * 100) === 10_000_000 &&
    Math.round(payments * 100) === Math.round(payload.total_payment * 100) &&
    Math.round(interest * 100) === Math.round(payload.total_interest * 100);
}

export function isPdfAttachmentResponse(status, contentType, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'application/pdf' &&
    Buffer.isBuffer(bytes) && bytes.subarray(0, 5).toString('ascii') === '%PDF-';
}

function verifyPackagedMergeStructure(bytes) {
  const python = findPythonWithPytest(getPythonCandidates());
  if (!python) throw new Error('PDF merge smoke needs the repository Python test environment.');
  const outputPath = path.join(os.tmpdir(), `officekit-merge-structure-${randomUUID()}.pdf`);
  fs.writeFileSync(outputPath, bytes, { mode: 0o600, flag: 'wx' });
  try {
    const result = spawnSync(python, ['scripts/verify_pdf_merge_output.py', outputPath], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      timeout: 15_000,
    });
    if (result.error || result.status !== 0) {
      throw new Error((result.stderr || result.stdout || result.error?.message || 'PDF structure read-back failed').trim());
    }
  } finally {
    fs.rmSync(outputPath, { force: true });
  }
}

export function isPdfSplitAttachmentResponse(status, contentType, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'application/pdf' &&
    Buffer.isBuffer(bytes) && bytes.length > 5 && bytes.length <= 64 * 1024 * 1024 &&
    bytes.subarray(0, 5).toString('ascii') === '%PDF-';
}

export function isPdfSplitGroupsResponse(status, contentType, bytes, expectedNames) {
  if (status !== 200 || typeof contentType !== 'string' ||
      contentType.toLowerCase().split(';', 1)[0].trim() !== 'application/zip' ||
      !Buffer.isBuffer(bytes) || bytes.length < 22 || bytes.length > 64 * 1024 * 1024 ||
      !Array.isArray(expectedNames) || expectedNames.length < 2 || expectedNames.length > 50 ||
      bytes.subarray(0, 4).toString('hex') !== '504b0304') return false;
  try {
    const entries = extractZipEntries(bytes);
    return entries.size === expectedNames.length && expectedNames.every((name, index) => {
      const candidate = [...entries.keys()][index];
      const pdf = entries.get(name);
      return candidate === name && Buffer.isBuffer(pdf) && pdf.subarray(0, 5).toString('ascii') === '%PDF-';
    });
  } catch (_) {
    return false;
  }
}

export function isPdfCompressionResponse(status, contentType, ratioHeader, bytes, originalSize) {
  if (!isPdfSplitAttachmentResponse(status, contentType, bytes) ||
      !Number.isSafeInteger(originalSize) || originalSize < 1 ||
      typeof ratioHeader !== 'string' || !/^(?:0|[1-9][0-9]*)\.[0-9]{8}$/.test(ratioHeader)) return false;
  const reportedRatio = Number(ratioHeader);
  const actualRatio = bytes.length / originalSize;
  return Number.isFinite(reportedRatio) && reportedRatio > 0 &&
    Math.abs(reportedRatio - actualRatio) <= 0.000000005;
}

export function isPdfMetadataRemovedResponse(status, contentType, bytes, markers) {
  if (!isPdfSplitAttachmentResponse(status, contentType, bytes) ||
      !Array.isArray(markers) || markers.length < 1 || markers.length > 8 ||
      markers.some(marker => typeof marker !== 'string' || marker.length < 4 || marker.length > 256)) return false;
  return markers.every(marker => !bytes.includes(Buffer.from(marker, 'utf8')));
}

export function isPdfPageOrderResponse(status, pageCount, archiveBytes, expectedDimensions) {
  if (!Array.isArray(expectedDimensions) || expectedDimensions.length < 1 || expectedDimensions.length > 100 ||
      !isPdfImageArchiveResponse(status, pageCount, archiveBytes, expectedDimensions.length)) return false;
  try {
    const entries = extractZipEntries(archiveBytes);
    if (entries.size !== expectedDimensions.length) return false;
    return expectedDimensions.every(([expectedWidth, expectedHeight], index) => {
      const name = `page-${String(index + 1).padStart(3, '0')}.png`;
      const image = entries.get(name);
      return Buffer.isBuffer(image) && image.length >= 24 &&
        image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) &&
        image.subarray(12, 16).toString('ascii') === 'IHDR' &&
        image.readUInt32BE(16) === expectedWidth && image.readUInt32BE(20) === expectedHeight;
    });
  } catch (_) {
    return false;
  }
}

export function isPdfCompressionFidelityResponse(status, pageCount, archiveBytes, expectedPagePngs, expectedDimensions) {
  if (!Array.isArray(expectedPagePngs) || expectedPagePngs.length !== expectedDimensions?.length ||
      expectedPagePngs.some(image => !Buffer.isBuffer(image)) ||
      !isPdfPageOrderResponse(status, pageCount, archiveBytes, expectedDimensions)) return false;
  try {
    const outputEntries = extractZipEntries(archiveBytes);
    return expectedPagePngs.every((expected, index) => {
      const name = `page-${String(index + 1).padStart(3, '0')}.png`;
      return outputEntries.get(name)?.equals(expected) === true;
    });
  } catch (_) {
    return false;
  }
}

function readPngDimensions(image) {
  if (!Buffer.isBuffer(image) || image.length < 24 ||
      !image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ||
      image.subarray(12, 16).toString('ascii') !== 'IHDR') return null;
  const width = image.readUInt32BE(16);
  const height = image.readUInt32BE(20);
  return width > 0 && height > 0 ? [width, height] : null;
}

export function isPdfPageCountsResponse(status, payload, expectedPageCounts) {
  if (status !== 200 || !payload || typeof payload !== 'object' ||
      !Array.isArray(payload.files) || !Array.isArray(expectedPageCounts) ||
      payload.files.length !== expectedPageCounts.length ||
      Object.keys(payload).length !== 4 ||
      !['files', 'total_pages', 'ready_count', 'unreadable_count'].every(key => Object.hasOwn(payload, key)) ||
      !Number.isSafeInteger(payload.total_pages) || !Number.isSafeInteger(payload.ready_count) ||
      !Number.isSafeInteger(payload.unreadable_count)) return false;
  let totalPages = 0;
  for (let index = 0; index < expectedPageCounts.length; index += 1) {
    const item = payload.files[index];
    const expected = expectedPageCounts[index];
    if (!Number.isSafeInteger(expected) || expected < 1 || item?.index !== index ||
        !item || typeof item !== 'object' || Object.keys(item).length !== 3 ||
        !['index', 'page_count', 'status'].every(key => Object.hasOwn(item, key)) ||
        item.page_count !== expected || item.status !== 'ready') return false;
    totalPages += expected;
  }
  return payload.total_pages === totalPages && payload.ready_count === expectedPageCounts.length &&
    payload.unreadable_count === 0;
}

export function isPdfSplitPageOrderResponse(status, pageCount, archiveBytes, expectedDimensions) {
  return isPdfPageOrderResponse(status, pageCount, archiveBytes, expectedDimensions);
}

export function isPdfImageArchiveResponse(status, pageCount, bytes, expectedPages = 1) {
  return status === 200 && Number.isSafeInteger(expectedPages) && expectedPages >= 1 && expectedPages <= 100 &&
    pageCount === String(expectedPages) && Buffer.isBuffer(bytes) &&
    bytes.length >= 4 && bytes.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
}

export function isImageMetadataAttachmentResponse(status, contentType, disposition, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'image/png' &&
    typeof disposition === 'string' && disposition.includes('smoke_metadata_removed.png') &&
    Buffer.isBuffer(bytes) && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
}

export function isScreenshotEditAttachmentResponse(status, contentType, disposition, bytes, format = 'png') {
  const jpeg = format === 'jpeg';
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === (jpeg ? 'image/jpeg' : 'image/png') &&
    typeof disposition === 'string' && disposition.includes(`screenshot-edited.${jpeg ? 'jpg' : 'png'}`) &&
    Buffer.isBuffer(bytes) && (jpeg
      ? bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff && bytes.at(-2) === 0xff && bytes.at(-1) === 0xd9
      : bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])));
}

export function isResizedImageAttachmentResponse(status, contentType, disposition, width, height, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'image/png' &&
    typeof disposition === 'string' && disposition.includes('resize_smoke_resized.png') &&
    width === '1' && height === '1' && Buffer.isBuffer(bytes) &&
    bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
}

export function isResizedImagesArchiveResponse(status, contentType, disposition, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'application/zip' &&
    typeof disposition === 'string' && disposition.includes('resized_images.zip') &&
    Buffer.isBuffer(bytes) && bytes.length >= 4 &&
    bytes.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
}

export function isSimilarImageReportResponse(status, payload) {
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.complete === true && payload.scanned_images === 2 &&
    Array.isArray(payload.groups) && payload.groups.some(group =>
      Array.isArray(group?.files) && group.files.length === 2 &&
      group.files.includes('burst/a.png') && group.files.includes('burst/b.png'));
}

export function isSimilarImageHeicReportResponse(status, payload) {
  const group = payload?.groups?.find(value =>
    Array.isArray(value?.files) && value.files.length === 2 &&
    value.files.includes('burst/heic-a.heic') && value.files.includes('burst/heic-b.heif'));
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.complete === true && payload.scanned_images === 3 &&
    Array.isArray(payload.skipped_files) && payload.skipped_files.length === 0 &&
    Array.isArray(payload.errors) && payload.errors.length === 0 &&
    Array.isArray(payload.groups) && payload.groups.length === 1 &&
    Boolean(group) && !group.files.includes('burst/heic-unrelated.heic');
}

export function isIncompleteSimilarImageReportResponse(status, payload) {
  const error = payload?.errors?.[0];
  return status === 200 && payload !== null && typeof payload === 'object' &&
    payload.complete === false && payload.scanned_images === 0 &&
    Array.isArray(payload.errors) && payload.errors.length === 1 &&
    error?.name === 'broken/bad.png' && error.message === 'Image could not be decoded';
}

export function isDuplicateWorkspaceReportResponse(status, payload) {
  const group = payload?.groups?.[0];
  return status === 200 && payload?.complete === true && payload.files_scanned === 3 &&
    Array.isArray(payload.groups) && payload.groups.length === 1 && group.size_bytes === 6 &&
    Array.isArray(group.files) && group.files.length === 2 &&
    group.files.includes('samples/sample-a.txt') && group.files.includes('sample-b.txt');
}

export function isStorageWorkspaceReportResponse(status, payload, expectedBytes) {
  const folder = payload?.largest_folders?.[0];
  return status === 200 && payload?.complete === true && payload.total_files === 3 &&
    payload.total_size_bytes === expectedBytes && Number.isSafeInteger(expectedBytes) &&
    Array.isArray(payload.largest_folders) && payload.largest_folders.length === 1 &&
    folder.name === 'samples' && folder.file_count === 1 && folder.size_bytes === 6;
}

export function isRenamePreviewResponse(status, payload) {
  const file = payload?.files?.[0];
  return status === 200 && Array.isArray(payload?.files) && payload.files.length === 1 &&
    file.source === 'rename.txt' && file.target === 'ready_rename.txt' && file.size_bytes === 7;
}

export function isRenameArtifactResponse(status, payload) {
  return status === 201 && typeof payload?.artifact_id === 'string' &&
    /^[a-f0-9]{32}$/.test(payload.artifact_id) && payload.file_count === 1 &&
    payload.total_bytes === 7 && Array.isArray(payload.files) &&
    payload.files.length === 1 && payload.files[0] === 'ready_rename.txt' &&
    payload.download_name === 'renamed-files.zip';
}

export function isZipAttachmentResponse(status, contentType, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'application/zip' &&
    Buffer.isBuffer(bytes) && bytes.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
}

export function isWorkspaceSplitResponse(status, payload, expectedBytes, expectedDigest) {
  if (status !== 201 || payload === null || typeof payload !== 'object' ||
      !/^[a-f0-9]{32}$/.test(payload.artifact_id || '') ||
      !Number.isSafeInteger(payload.total_bytes) || payload.total_bytes !== expectedBytes ||
      !Number.isSafeInteger(payload.chunk_size_bytes) || payload.chunk_size_bytes < 1 ||
      !Number.isSafeInteger(payload.chunk_count) || payload.chunk_count < 1 ||
      payload.chunk_count !== Math.max(1, Math.ceil(expectedBytes / payload.chunk_size_bytes)) ||
      payload.sha256 !== expectedDigest || typeof payload.original_name !== 'string' ||
      typeof payload.download_name !== 'string' || !Array.isArray(payload.parts) ||
      payload.parts.length !== payload.chunk_count) return false;

  let remaining = expectedBytes;
  return payload.parts.every((part, index) => {
    const expectedSize = Math.min(payload.chunk_size_bytes, remaining);
    remaining -= expectedSize;
    return part !== null && typeof part === 'object' && part.index === index + 1 &&
      part.name === `part-${String(index + 1).padStart(5, '0')}.bin` &&
      part.size_bytes === expectedSize && /^[a-f0-9]{64}$/.test(part.sha256 || '');
  }) && remaining === 0;
}

export function isWorkspaceJoinResponse(status, payload, expectedBytes, expectedDigest, expectedParts) {
  return status === 201 && payload !== null && typeof payload === 'object' &&
    /^[a-f0-9]{32}$/.test(payload.artifact_id || '') &&
    typeof payload.output_name === 'string' && payload.output_name.length > 0 &&
    payload.total_bytes === expectedBytes && payload.part_count === expectedParts &&
    payload.sha256 === expectedDigest && typeof payload.download_name === 'string' &&
    payload.download_name === `${payload.output_name}.zip`;
}

function extractZipEntries(bytes) {
  if (!Buffer.isBuffer(bytes)) throw new Error('ZIP data is not a byte buffer.');
  const entries = new Map();
  let totalUncompressedBytes = 0;
  let offset = 0;
  while (offset + 4 <= bytes.length && bytes.readUInt32LE(offset) === 0x04034b50) {
    if (offset + 30 > bytes.length) throw new Error('ZIP local header is truncated.');
    const flags = bytes.readUInt16LE(offset + 6);
    const method = bytes.readUInt16LE(offset + 8);
    const expectedCrc = bytes.readUInt32LE(offset + 14);
    const compressedSize = bytes.readUInt32LE(offset + 18);
    const uncompressedSize = bytes.readUInt32LE(offset + 22);
    const nameLength = bytes.readUInt16LE(offset + 26);
    const extraLength = bytes.readUInt16LE(offset + 28);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const dataEnd = dataStart + compressedSize;
    totalUncompressedBytes += uncompressedSize;
    if ((flags & 0x0008) !== 0 || ![0, 8].includes(method) ||
        totalUncompressedBytes > 64 * 1024 * 1024 ||
        dataEnd > bytes.length) throw new Error('ZIP entry is not a bounded supported file.');
    const name = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(nameStart, nameStart + nameLength));
    if (!name || entries.has(name)) throw new Error('ZIP contains an empty or duplicate file name.');
    const compressed = bytes.subarray(dataStart, dataEnd);
    const contents = method === 8 ? inflateRawSync(compressed, { maxOutputLength: uncompressedSize }) : Buffer.from(compressed);
    if (contents.length !== uncompressedSize || pngCrc32(contents) !== expectedCrc) {
      throw new Error('ZIP entry size or checksum is invalid.');
    }
    entries.set(name, contents);
    offset = dataEnd;
  }
  if (entries.size === 0 || offset + 4 > bytes.length || bytes.readUInt32LE(offset) !== 0x02014b50) {
    throw new Error('ZIP does not contain a valid stored-file directory.');
  }
  return entries;
}

export function isFolderComparisonCsvResponse(status, contentType, disposition, bytes) {
  const csv = Buffer.isBuffer(bytes) ? bytes.toString('utf8') : '';
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'text/csv' &&
    typeof disposition === 'string' && disposition.includes('folder-comparison.csv') &&
    csv.startsWith('entry_type,relative_path,status,folder_a_path,folder_a_size_bytes,folder_a_sha256,folder_b_path,folder_b_size_bytes,folder_b_sha256\r\n') &&
    csv.includes("file,'=SUM(1+1).csv,changed,");
}

export function isResultXlsxAttachmentResponse(status, contentType, disposition, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() ===
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' &&
    typeof disposition === 'string' && disposition.includes('loan_emi-result.xlsx') &&
    Buffer.isBuffer(bytes) && bytes.length >= 4 &&
    bytes.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
}

export function isResultPptxAttachmentResponse(status, contentType, disposition, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() ===
      'application/vnd.openxmlformats-officedocument.presentationml.presentation' &&
    typeof disposition === 'string' && disposition.includes('loan_emi-result.pptx') &&
    Buffer.isBuffer(bytes) && bytes.length >= 4 &&
    bytes.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
}

export function isResultPdfAttachmentResponse(status, contentType, disposition, bytes) {
  return status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === 'application/pdf' &&
    typeof disposition === 'string' && disposition.includes('loan_emi-result.pdf') &&
    Buffer.isBuffer(bytes) && bytes.length >= 5 && bytes.subarray(0, 5).equals(Buffer.from('%PDF-'));
}

export function isResultImageAttachmentResponse(status, contentType, disposition, bytes, format) {
  const expected = format === 'png'
    ? { mime: 'image/png', filename: 'loan_emi-result.png', signature: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) }
    : format === 'jpeg'
      ? { mime: 'image/jpeg', filename: 'loan_emi-result.jpg', signature: Buffer.from([0xff, 0xd8, 0xff]) }
      : null;
  return Boolean(expected) && status === 200 && typeof contentType === 'string' &&
    contentType.toLowerCase().split(';', 1)[0].trim() === expected.mime &&
    typeof disposition === 'string' && disposition.includes(expected.filename) &&
    Buffer.isBuffer(bytes) && bytes.length > expected.signature.length &&
    bytes.subarray(0, expected.signature.length).equals(expected.signature);
}

export function isNetworkPingResponse(status, payload, expectedTarget) {
  if (
    status !== 200 || payload?.target !== expectedTarget || ![
      'reachable', 'partial_loss', 'no_reply', 'permission_denied',
    ].includes(payload?.status)
  ) return false;

  if (payload.status === 'permission_denied') {
    return payload.packets_sent === null && payload.packets_received === null &&
      payload.packet_loss_percent === null && payload.latency_ms === null;
  }
  if (
    !Number.isSafeInteger(payload.packets_sent) || payload.packets_sent < 1 ||
    !Number.isSafeInteger(payload.packets_received) || payload.packets_received < 0 ||
    payload.packets_received > payload.packets_sent || !Number.isFinite(payload.packet_loss_percent) ||
    payload.packet_loss_percent < 0 || payload.packet_loss_percent > 100
  ) return false;
  if (payload.status === 'reachable') {
    const latency = payload.latency_ms;
    return payload.packets_received === payload.packets_sent && payload.packet_loss_percent === 0 &&
      latency && Number.isFinite(latency.min) && Number.isFinite(latency.avg) && Number.isFinite(latency.max) &&
      latency.min <= latency.avg && latency.avg <= latency.max;
  }
  if (payload.status === 'no_reply') {
    return payload.packets_received === 0 && payload.packet_loss_percent === 100 && payload.latency_ms === null;
  }
  return payload.packets_received > 0 && payload.packets_received < payload.packets_sent &&
    payload.packet_loss_percent > 0 && payload.packet_loss_percent < 100;
}

export function isDnsLookupResponse(status, payload, expectedHostname, expectedRecordType) {
  if (
    status !== 200 || payload?.hostname !== expectedHostname ||
    payload?.record_type !== expectedRecordType || !Array.isArray(payload.records) ||
    payload.records.length > 100 || typeof payload.truncated !== 'boolean' ||
    !Number.isSafeInteger(payload.duration_ms) || payload.duration_ms < 0 ||
    !['success', 'nxdomain', 'no_records', 'timed_out', 'resolver_error'].includes(payload.status)
  ) return false;
  if (payload.status === 'success' && payload.records.length === 0) return false;
  if (payload.status !== 'success' && payload.records.length !== 0) return false;
  return payload.records.every(record => {
    if (expectedRecordType === 'MX') {
      return Number.isSafeInteger(record?.preference) && record.preference >= 0 &&
        typeof record.exchange === 'string' && record.exchange.length > 0;
    }
    return typeof record === 'string' && record.length > 0;
  });
}

export function isNetworkInterfacesResponse(status, payload, expectedIncludeAddresses = false) {
  const expectedNotice = expectedIncludeAddresses
    ? 'Contains local IP addresses. Copy or export only the addresses you select.'
    : 'Local IP addresses are hidden. Include addresses only when you want to view them.';
  return status === 200 && payload?.include_addresses === expectedIncludeAddresses &&
    payload?.privacy_notice === expectedNotice &&
    Array.isArray(payload.interfaces) && payload.interfaces.length <= 64 &&
    typeof payload.truncated === 'boolean' && payload.interfaces.every(interfaceInfo =>
      typeof interfaceInfo?.name === 'string' && interfaceInfo.name.length > 0 &&
      (interfaceInfo.is_up === null || typeof interfaceInfo.is_up === 'boolean') &&
      Number.isSafeInteger(interfaceInfo.address_count) && interfaceInfo.address_count >= 0 &&
      interfaceInfo.addresses_hidden === (!expectedIncludeAddresses && interfaceInfo.address_count > 0) &&
      Array.isArray(interfaceInfo.addresses) && interfaceInfo.addresses.length <= 32 &&
      interfaceInfo.addresses.length <= interfaceInfo.address_count &&
      (expectedIncludeAddresses || interfaceInfo.addresses.length === 0) &&
      interfaceInfo.addresses.every(address => {
        const keys = ['address', 'broadcast', 'family', 'netmask'];
        return address && Object.keys(address).length === keys.length && keys.every(key => Object.hasOwn(address, key)) &&
          ['IPv4', 'IPv6'].includes(address.family) && typeof address.address === 'string' &&
          (address.netmask === null || typeof address.netmask === 'string') &&
          (address.broadcast === null || typeof address.broadcast === 'string');
      }));
}

export function isSystemResourceResponse(status, payload) {
  return status === 200 && Number.isSafeInteger(payload?.cpu_count) && payload.cpu_count > 0 &&
    Number.isFinite(payload.cpu_percent) && payload.cpu_percent >= 0 && payload.cpu_percent <= 100 &&
    payload.cpu_sample_interval_seconds === 0.1 && Number.isFinite(payload.total_ram_gb) &&
    payload.total_ram_gb > 0 && Number.isFinite(payload.available_ram_gb) && payload.available_ram_gb >= 0 &&
    Number.isSafeInteger(payload.memory_total_bytes) && payload.memory_total_bytes > 0 &&
    Number.isSafeInteger(payload.memory_available_bytes) && payload.memory_available_bytes >= 0 &&
    payload.memory_available_bytes <= payload.memory_total_bytes &&
    payload.memory_used_estimate_bytes === payload.memory_total_bytes - payload.memory_available_bytes &&
    Number.isFinite(payload.memory_percent) && payload.memory_percent >= 0 && payload.memory_percent <= 100 &&
    Number.isSafeInteger(payload.optimal_workers) && payload.optimal_workers >= 1 && payload.optimal_workers <= 32 &&
    typeof payload.cached === 'boolean' && Number.isSafeInteger(payload.sample_age_ms) && payload.sample_age_ms >= 0;
}

export function isRedactedSystemInfoResponse(status, payload) {
  const keys = [
    'architecture', 'logical_cpu_count', 'memory_total_bytes', 'memory_total_gb',
    'os_name', 'os_version', 'physical_cpu_count', 'privacy_notice', 'report_text',
  ];
  return status === 200 && payload?.os_name === 'macOS' &&
    typeof payload.os_version === 'string' && /^\d{1,3}(?:\.\d{1,3}){0,2}$/.test(payload.os_version) &&
    typeof payload.architecture === 'string' && /^[A-Za-z0-9_.-]{1,32}$/.test(payload.architecture) &&
    Number.isSafeInteger(payload.logical_cpu_count) && payload.logical_cpu_count > 0 &&
    (payload.physical_cpu_count === null ||
      (Number.isSafeInteger(payload.physical_cpu_count) && payload.physical_cpu_count > 0 &&
        payload.physical_cpu_count <= payload.logical_cpu_count)) &&
    Number.isSafeInteger(payload.memory_total_bytes) && payload.memory_total_bytes > 0 &&
    Number.isFinite(payload.memory_total_gb) && payload.memory_total_gb > 0 &&
    typeof payload.privacy_notice === 'string' && payload.privacy_notice.includes('excluded') &&
    typeof payload.report_text === 'string' && payload.report_text.length > 0 &&
    keys.length === Object.keys(payload).length && keys.every(key => Object.hasOwn(payload, key));
}

export function isCompoundInterestResponse(status, payload, expected) {
  if (
    status !== 200 || !payload ||
    !Number.isFinite(payload.future_value) || !Number.isFinite(payload.total_invested) ||
    !Number.isFinite(payload.total_interest_earned) ||
    payload.future_value !== expected.future_value || payload.total_invested !== expected.total_invested ||
    payload.total_interest_earned !== expected.total_interest_earned ||
    !Array.isArray(payload.growth_history) || payload.growth_history.length !== 1
  ) return false;
  const [year] = payload.growth_history;
  return year.year === 1 && year.total_balance === expected.future_value &&
    year.total_invested === expected.total_invested && year.total_interest === expected.total_interest_earned &&
    payload.assumptions?.rate_basis === 'nominal_annual' &&
    payload.assumptions?.monthly_accrual === 'equivalent_effective_monthly_rate' &&
    payload.assumptions?.contribution_timing === 'end_of_month' &&
    payload.assumptions?.fractional_month === 'interest_only';
}

export function isMeetingNotesResponse(status, payload, expected) {
  if (
    status !== 200 || !payload || typeof payload !== 'object' || Array.isArray(payload) ||
    !expected || typeof expected.transcript !== 'string' || typeof expected.summary !== 'string' ||
    !Array.isArray(expected.action_items) || !Array.isArray(expected.decisions) ||
    !Array.isArray(payload.action_items) || payload.action_items.length > 10_000 ||
    !Array.isArray(payload.decisions) || payload.decisions.length > 10_000 ||
    payload.action_items.some(item => typeof item !== 'string' || item.length > 262_144) ||
    payload.decisions.some(item => typeof item !== 'string' || item.length > 262_144) ||
    payload.summary !== expected.summary ||
    JSON.stringify(payload.action_items) !== JSON.stringify(expected.action_items) ||
    JSON.stringify(payload.decisions) !== JSON.stringify(expected.decisions) ||
    payload.word_count !== expected.transcript.split(/\s+/).filter(Boolean).length ||
    !Number.isSafeInteger(payload.word_count) || payload.word_count < 1 ||
    typeof payload.markdown !== 'string' || payload.markdown.length > 2_000_000
  ) return false;
  const longestFence = Math.max(0, ...(expected.transcript.match(/`+/g) || []).map(run => run.length));
  const fence = '`'.repeat(Math.max(3, longestFence + 1));
  return payload.markdown.endsWith(
    `## 🎙️ Full Transcript\n\n${fence}text\n${expected.transcript}\n${fence}`,
  );
}

export function isDictationCleanupResponse(status, payload, expectedText) {
  return status === 200 && payload !== null && typeof payload === 'object' && !Array.isArray(payload) &&
    typeof payload.cleaned_text === 'string' && payload.cleaned_text === expectedText &&
    payload.cleaned_text.length <= 262_146;
}

export function isStatementPdfExtractionResponse(status, payload) {
  const transactions = payload?.transactions;
  return status === 200 && Array.isArray(transactions) && transactions.length === 3 &&
    transactions[1]?.description === 'Client invoice' && transactions[1]?.credit === 500 &&
    transactions[2]?.debit === 50 && payload?.reconciliation?.valid === true;
}

export function isPdfTableDateRowsResponse(status, payload) {
  if (status !== 200 || !Array.isArray(payload?.tables) || payload.tables.length === 0) return false;
  const datePattern = /\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b/g;
  let dateRows = 0;
  for (const table of payload.tables) {
    if (!Array.isArray(table?.preview_rows) || table.preview_rows.length === 0) continue;
    const headers = table.preview_rows[0].map(value =>
      typeof value === 'string' ? value.toLowerCase().replace(/[^a-z]/g, '') : '',
    );
    const dateIndex = headers.findIndex(header =>
      ['date', 'transactiondate', 'txndate', 'transdate', 'postingdate'].includes(header),
    );
    if (dateIndex < 0) continue;
    for (const row of table.preview_rows.slice(1)) {
      if (!Array.isArray(row) || row.some(value => typeof value !== 'string')) return false;
      const dateCell = row[dateIndex] || '';
      const matches = dateCell.match(datePattern) || [];
      if (matches.length > 1) return false;
      dateRows += Number(matches.length === 1);
    }
  }
  return dateRows > 0;
}

export function isUnruledStatementPdfResponse(status, payload) {
  const transactions = payload?.transactions;
  return status === 200 && Array.isArray(transactions) && transactions.length === 3 &&
    transactions[0]?.description === 'Opening balance' && transactions[0]?.status === 'baseline' &&
    transactions[1]?.description === 'Client invoice via international clearing reference TXN123456789 from Accounts Team' &&
    transactions[1]?.credit === 500 && transactions[1]?.balance === 1500 &&
    transactions[2]?.description === 'Monthly service fee' && transactions[2]?.debit === 50 &&
    !transactions.some(transaction => {
      const compact = String(transaction?.description || '').toLowerCase().replace(/[^a-z]/g, '');
      return /statementsummary|(?:opening|closing)?balance(?:dr|cr)?count|(?:debit|credit|dr|cr)count/.test(compact);
    }) &&
    payload?.reconciliation?.status === 'verified' && payload.reconciliation.valid === true;
}

export function isWeakVectorStatementRecoveryResponse(status, payload) {
  const transaction = payload?.transactions?.find(row => row?.description === 'Coffee Shop');
  return status === 200 && Array.isArray(payload?.transactions) && transaction?.debit === 25 &&
    transaction?.balance === 975 && transaction?.status === 'ok' &&
    payload?.reconciliation?.status === 'verified' && payload.reconciliation.valid === true;
}

export function isStatementUnverifiedResponse(status, payload) {
  const reconciliation = payload?.reconciliation;
  return status === 200 && Array.isArray(payload?.transactions) &&
    payload.transactions.length === 2 &&
    payload.transactions[0]?.status === 'baseline' &&
    payload.transactions[1]?.status === 'unverified' &&
    reconciliation?.valid === null && reconciliation.status === 'unverified' &&
    reconciliation.checked_rows === 0 && reconciliation.unverified_rows === 1;
}

export function isAmbiguousStatementUnverifiedResponse(status, payload) {
  const transactions = payload?.transactions;
  return status === 200 && Array.isArray(transactions) && transactions.length === 2 &&
    transactions[0]?.status === 'unverified' && transactions[0]?.balance === null &&
    transactions[1]?.status === 'unverified' && transactions[1]?.credit === null &&
    transactions[1]?.balance === null && payload?.reconciliation?.valid === null &&
    payload.reconciliation.status === 'unverified';
}

export function isLocalizedStatementResponse(status, payload, expected) {
  const transaction = payload?.transactions?.[1];
  return status === 200 && payload?.reconciliation?.valid === true &&
    payload.reconciliation.status === 'verified' && transaction?.credit === expected.credit &&
    transaction?.balance === expected.balance &&
    (expected.date === undefined || transaction?.date === expected.date);
}

export function isInvalidStatementOptionResponse(status, payload) {
  return status === 422 && payload?.detail === 'Request contains invalid or unsupported values.';
}

export function sidecarAuth(token, environment = process.env) {
  if (typeof token !== 'string' || token.length < 32 || token.length > 128 || /\s/.test(token)) {
    throw new Error('A valid OfficeKit sidecar token is required.');
  }
  return {
    environment: { ...environment, OFFICEKIT_API_TOKEN: token },
    headers: { Authorization: `Bearer ${token}` },
  };
}

export function findAvailableLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Unable to reserve a local sidecar smoke port.')));
        return;
      }
      server.close(error => error ? reject(error) : resolve(address.port));
    });
  });
}

export async function resolveSmokePort(environment = process.env) {
  const value = environment.OFFICEKIT_API_PORT || String(await findAvailableLoopbackPort());
  if (!/^[0-9]{1,5}$/.test(value) || Number(value) < 1 || Number(value) > 65535) {
    throw new Error('OFFICEKIT_API_PORT must be a decimal TCP port between 1 and 65535.');
  }
  return Number(value);
}

async function delay(ms) {
  await new Promise(resolve => setTimeout(resolve, ms));
}

async function stopChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, 'exit');
  child.kill('SIGTERM');
  await Promise.race([exited, delay(5000)]);
  if (child.exitCode === null && child.signalCode === null) {
    const killed = once(child, 'exit');
    child.kill('SIGKILL');
    await Promise.race([killed, delay(2000)]);
  }
}

async function smokeCsvToJson(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob(['name,amount\nAda,3.5\n'], { type: 'text/csv' }), 'sample.csv');
  form.set('target_format', 'json');
  const response = await fetchImpl('http://127.0.0.1:8000/api/convert/data', {
    method: 'POST',
    headers,
    body: form,
    signal: AbortSignal.timeout(30_000),
  });
  let rows = null;
  try {
    rows = await response.json();
  } catch (_) {
    // A malformed packaged dependency response is reported by the validator below.
  }
  if (!isCsvJsonConversionResponse(response.status, rows)) {
    throw new Error(`OfficeKit sidecar CSV-to-JSON smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeNestedTabularConversion(fetchImpl, headers) {
  const source = JSON.stringify([{
    account: '001234',
    items: [1, { sku: 'A-1' }],
    metadata: { active: true },
    note: null,
  }]);
  const csvForm = new FormData();
  csvForm.set('file', new Blob([source], { type: 'application/json' }), 'nested.json');
  csvForm.set('target_format', 'csv');
  const csvResponse = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: csvForm, signal: AbortSignal.timeout(30_000),
  });
  const csv = await csvResponse.text();
  if (
    csvResponse.status !== 200
    || !csv.includes('"[1,{""sku"":""A-1""}]"')
    || !csv.includes('"{""active"":true}"')
  ) {
    throw new Error('OfficeKit sidecar nested JSON-to-CSV smoke check failed.');
  }

  const xlsxForm = new FormData();
  xlsxForm.set('file', new Blob([source], { type: 'application/json' }), 'nested.json');
  xlsxForm.set('target_format', 'xlsx');
  const xlsxResponse = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: xlsxForm, signal: AbortSignal.timeout(30_000),
  });
  if (xlsxResponse.status !== 200) {
    throw new Error(`OfficeKit sidecar nested JSON-to-XLSX smoke check failed (HTTP ${xlsxResponse.status}).`);
  }
  const xlsxBytes = await xlsxResponse.arrayBuffer();
  if (xlsxBytes.byteLength < 4 || new Uint8Array(xlsxBytes)[0] !== 0x50 || new Uint8Array(xlsxBytes)[1] !== 0x4b) {
    throw new Error('OfficeKit sidecar nested XLSX output is not a workbook archive.');
  }

  const roundTripForm = new FormData();
  roundTripForm.set(
    'file',
    new Blob([xlsxBytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    'nested.xlsx',
  );
  roundTripForm.set('target_format', 'json');
  const roundTripResponse = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: roundTripForm, signal: AbortSignal.timeout(30_000),
  });
  let rows = null;
  try { rows = await roundTripResponse.json(); } catch (_) { /* malformed output fails below */ }
  let items = null;
  let metadata = null;
  try {
    items = JSON.parse(rows?.[0]?.items);
    metadata = JSON.parse(rows?.[0]?.metadata);
  } catch (_) { /* malformed nested cells fail below */ }
  if (
    roundTripResponse.status !== 200
    || !Array.isArray(rows)
    || rows.length !== 1
    || rows[0]?.account !== '001234'
    || rows[0]?.note !== null
    || JSON.stringify(items) !== JSON.stringify([1, { sku: 'A-1' }])
    || metadata?.active !== true
  ) {
    throw new Error('OfficeKit sidecar nested XLSX round-trip smoke check failed.');
  }
}

async function smokeStrictJsonFileImport(fetchImpl, headers) {
  const invalidSources = [
    ['duplicate-keys.json', '[{"id":"first","id":"second"}]'],
    ['non-finite.json', '[{"amount":NaN}]'],
    ['overflow.json', '[{"amount":1e309}]'],
    ['deep.json', `${'['.repeat(1100)}0${']'.repeat(1100)}`],
  ];
  for (const [filename, contents] of invalidSources) {
    const form = new FormData();
    form.set('file', new Blob([contents], { type: 'application/json' }), filename);
    form.set('target_format', 'csv');
    const response = await fetchImpl('http://127.0.0.1:8000/api/convert/data', {
      method: 'POST',
      headers,
      body: form,
      signal: AbortSignal.timeout(30_000),
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* invalid response fails below */ }
    if (
      response.status !== 422
      || payload?.detail !== 'The file or requested format cannot be converted. Check the input and try again.'
    ) {
      throw new Error(`OfficeKit sidecar rejected JSON import fixture unexpectedly: ${filename}.`);
    }
  }
}

async function smokeStrictYamlFileImport(fetchImpl, headers) {
  const invalidSources = [
    ['duplicate-keys.yaml', 'name: first\nname: second\n'],
    ['alias.yaml', 'defaults: &defaults\n  amount: 1\nrow: *defaults\n'],
    ['non-finite.yaml', 'amount: .nan\n'],
  ];
  for (const [filename, contents] of invalidSources) {
    const form = new FormData();
    form.set('file', new Blob([contents], { type: 'application/yaml' }), filename);
    form.set('target_format', 'json');
    const response = await fetchImpl('http://127.0.0.1:8000/api/convert/data', {
      method: 'POST',
      headers,
      body: form,
      signal: AbortSignal.timeout(30_000),
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* invalid response fails below */ }
    if (
      response.status !== 422
      || payload?.detail !== 'The file or requested format cannot be converted. Check the input and try again.'
    ) {
      throw new Error(`OfficeKit sidecar rejected YAML import fixture unexpectedly: ${filename}.`);
    }
  }

  const exact = new FormData();
  exact.set(
    'file',
    new Blob(['amount: 0.123456789012345678901234567890\nflag: yes\ncode: 0012\n'], { type: 'application/yaml' }),
    'exact.yaml',
  );
  exact.set('target_format', 'json');
  const response = await fetchImpl('http://127.0.0.1:8000/api/convert/data', {
    method: 'POST',
    headers,
    body: exact,
    signal: AbortSignal.timeout(30_000),
  });
  const output = await response.text();
  if (
    response.status !== 200
    || !output.includes('0.123456789012345678901234567890')
    || !output.includes('"flag": "yes"')
    || !output.includes('"code": "0012"')
  ) {
    throw new Error('OfficeKit sidecar YAML-to-JSON fidelity smoke check failed.');
  }
}

async function smokeBoundedXlsxFileImport(fetchImpl, headers) {
  const source = new FormData();
  source.set(
    'file',
    new Blob([fs.readFileSync(path.join(REPO_ROOT, 'tests/fixtures/data-converter/formatted-values.xlsx'))], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    'formatted-values.xlsx',
  );
  source.set('target_format', 'json');
  const response = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: source, signal: AbortSignal.timeout(30_000),
  });
  const output = await response.text();
  let rows = null;
  try { rows = JSON.parse(output); } catch (_) { /* malformed payload fails below */ }
  if (
    response.status !== 200
    || !Array.isArray(rows)
    || rows.length !== 1
    || rows[0]?.account !== '001234'
    || rows[0]?.posted_at !== '2026-10-07T00:00:00'
    || rows[0]?.amount !== 25.5
  ) {
    throw new Error(`OfficeKit sidecar XLSX import fidelity smoke check failed (HTTP ${response.status}): ${output.slice(0, 500)}`);
  }

  const oversized = new FormData();
  oversized.set(
    'file',
    new Blob([fs.readFileSync(path.join(REPO_ROOT, 'tests/fixtures/data-converter/oversized-dimension.xlsx'))], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    'oversized-dimension.xlsx',
  );
  oversized.set('target_format', 'json');
  const rejected = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: oversized, signal: AbortSignal.timeout(30_000),
  });
  let payload = null;
  try { payload = await rejected.json(); } catch (_) { /* invalid response fails below */ }
  if (
    rejected.status !== 422
    || payload?.detail !== 'The file or requested format cannot be converted. Check the input and try again.'
  ) {
    throw new Error('OfficeKit sidecar accepted an oversized XLSX worksheet dimension.');
  }
}

async function smokeXlsxDisplayFormatConversion(fetchImpl, headers) {
  const source = new FormData();
  source.set(
    'file',
    new Blob([fs.readFileSync(path.join(REPO_ROOT, 'tests/fixtures/data-converter/formatted-numeric-displays.xlsx'))], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    'formatted-numeric-displays.xlsx',
  );
  source.set('target_format', 'csv');
  const response = await fetchImpl(`${API_ORIGIN}/api/convert/data`, {
    method: 'POST', headers, body: source, signal: AbortSignal.timeout(30_000),
  });
  const csv = await response.text();
  if (!isXlsxDisplayFormatCsvResponse(response.status, csv)) {
    throw new Error(`OfficeKit sidecar XLSX display-format smoke check failed (HTTP ${response.status}).`);
  }
}

async function smokeYamlToJson(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/devtools/process', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: 'name: OfficeKit\ncount: 2\nactive: true\n',
      operation: 'yaml_to_json',
    }),
    signal: AbortSignal.timeout(5_000),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isYamlToJsonResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar YAML-to-JSON smoke check returned HTTP ${response.status}.`);
  }

  const aliasesResponse = await fetchImpl('http://127.0.0.1:8000/api/devtools/process', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: 'first: &value text\nsecond: *value\n', operation: 'yaml_to_json' }),
    signal: AbortSignal.timeout(5_000),
  });
  if (aliasesResponse.status !== 422) {
    throw new Error(`OfficeKit sidecar YAML alias rejection returned HTTP ${aliasesResponse.status}.`);
  }

  const strictJson = '{"large":1e999,"precise":0.12345678901234567890123456789,"small":1e-9999}';
  const formattedResponse = await fetchImpl('http://127.0.0.1:8000/api/devtools/process', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: strictJson, operation: 'format_json' }),
    signal: AbortSignal.timeout(5_000),
  });
  let formatted = null;
  try { formatted = await formattedResponse.json(); } catch (_) { /* validator fails safely */ }
  if (!isJsonDecimalFidelityResponse(formattedResponse.status, formatted)) {
    throw new Error(`OfficeKit sidecar JSON precision smoke check returned HTTP ${formattedResponse.status}.`);
  }

  for (const operation of ['format_json', 'json_to_yaml']) {
    const duplicateResponse = await fetchImpl('http://127.0.0.1:8000/api/devtools/process', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: '{"value":1,"value":2}', operation }),
      signal: AbortSignal.timeout(5_000),
    });
    if (duplicateResponse.status !== 422) {
      throw new Error(`OfficeKit sidecar duplicate JSON key rejection returned HTTP ${duplicateResponse.status}.`);
    }
  }
}

async function smokeDelimitedDataFidelity(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob([
    'reference,amount,max_safe,precise,date\n' +
    '00001,0.125,999999999999999,1234567890123456789,2026-10-07\n' +
    '00002,0,999999999999998,1234567890123456790,01/02/2026\n',
  ], { type: 'text/csv' }), 'accounts.csv');
  form.set('target_format', 'json');
  const response = await fetchImpl('http://127.0.0.1:8000/api/convert/data', {
    method: 'POST',
    headers,
    body: form,
    signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isDelimitedDataFidelityResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar delimited-data fidelity smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeRelatedPdfSearch(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/tools/search?q=PDF%20to', {
    headers,
    signal: AbortSignal.timeout(5_000),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isRelatedPdfSearchResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar PDF tool-search smoke check returned HTTP ${response.status}.`);
  }
}

// The packaged sidecar starts locked. Prove that, then push an entitlement the way the native shell does.
// The locked probe must be a GATED route and the free probe a FREE one; tests/sidecar-smoke.test.mjs
// parses engine_license_gate.py and fails if either drifts out of its table.
export const LOCKED_PROBE_PATH = '/api/system/info';
export const FREE_PROBE_PATH = '/api/units/catalog';

async function smokeLockedGateAndInstallEntitlement(fetchImpl, headers, grantToken) {
  const lockedResponse = await fetchImpl(`http://127.0.0.1:8000${LOCKED_PROBE_PATH}`, { headers });
  if (!isLicenseRequiredResponse(lockedResponse.status, await lockedResponse.json())) {
    throw new Error('OfficeKit sidecar served a paid route without an entitlement.');
  }
  const freeResponse = await fetchImpl(`http://127.0.0.1:8000${FREE_PROBE_PATH}`, { headers });
  if (freeResponse.status !== 200) {
    throw new Error(`OfficeKit sidecar refused a free route while locked (HTTP ${freeResponse.status}).`);
  }
  const rejected = await fetchImpl('http://127.0.0.1:8000/api/license/entitlement', {
    method: 'PUT',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: entitlementPushBody(),
  });
  if (rejected.status !== 401) {
    throw new Error('OfficeKit sidecar accepted an entitlement without the native grant.');
  }
  const accepted = await fetchImpl('http://127.0.0.1:8000/api/license/entitlement', {
    method: 'PUT',
    headers: { ...headers, 'Content-Type': 'application/json', 'X-OfficeKit-Native-Grant': grantToken },
    body: entitlementPushBody(),
  });
  if (accepted.status !== 204) {
    throw new Error(`OfficeKit sidecar rejected the native entitlement push (HTTP ${accepted.status}).`);
  }
}

async function smokeLicenseStatus(fetchImpl, headers) {
  const statusResponse = await fetchImpl('http://127.0.0.1:8000/api/license/status', { headers });
  const statusPayload = await statusResponse.json();
  if (statusResponse.status !== 200 || statusPayload?.activated !== true || statusPayload.edition !== 'paid') {
    throw new Error('OfficeKit sidecar license status did not reflect the pushed entitlement.');
  }

  const activationResponse = await fetchImpl('http://127.0.0.1:8000/api/license/activate', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'sidecar-smoke@example.invalid', license_key: 'NOT-A-REAL-KEY' }),
  });
  const activationPayload = await activationResponse.json();
  if (!isLicenseActivationUnavailableResponse(activationResponse.status, activationPayload)) {
    throw new Error('OfficeKit sidecar exposed an unexpected local license activation response.');
  }
}

async function smokeMeetingNotes(fetchImpl, headers) {
  const expected = {
    transcript: 'The launch date is Friday. We decided that Sara will send the checklist. We will not publish the draft today.',
    summary: 'The launch date is Friday We will not publish the draft today',
    action_items: ['We decided that Sara will send the checklist'],
    decisions: ['We decided that Sara will send the checklist'],
  };
  const response = await fetchImpl('http://127.0.0.1:8000/api/dictate/format-notes', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ transcript: expected.transcript }),
    signal: AbortSignal.timeout(5_000),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isMeetingNotesResponse(response.status, payload, expected)) {
    const detail = {
      summary_match: payload?.summary === expected.summary,
      action_count: Array.isArray(payload?.action_items) ? payload.action_items.length : null,
      decision_count: Array.isArray(payload?.decisions) ? payload.decisions.length : null,
      word_count: payload?.word_count,
      markdown_type: typeof payload?.markdown,
      markdown_length: typeof payload?.markdown === 'string' ? payload.markdown.length : null,
      expected_word_count: expected.transcript.split(/\s+/).filter(Boolean).length,
    };
    throw new Error(`OfficeKit sidecar meeting-notes smoke check returned HTTP ${response.status} (${JSON.stringify(detail)}).`);
  }

  const regressionCases = [
    {
      transcript: 'There will be a design review next week. There is no need to publish before legal sign-off.',
      summary: 'There will be a design review next week There is no need to publish before legal sign-off',
      action_items: [],
      decisions: [],
    },
    {
      transcript: 'The decision will be made after legal review. A decision was not reached. The decision will remain open until finance signs off.',
      summary: 'The decision will be made after legal review A decision was not reached The decision will remain open until finance signs off',
      action_items: [],
      decisions: [],
    },
    {
      transcript: 'The team may have approved the revised price. The team might have chosen the new supplier. A decision might be announced Monday.',
      summary: 'The team may have approved the revised price The team might have chosen the new supplier A decision might be announced Monday',
      action_items: [],
      decisions: [],
    },
    {
      transcript: 'We will not ship today, but Sarah will publish the docs tomorrow.',
      summary: '',
      action_items: ['Sarah will publish the docs tomorrow'],
      decisions: [],
    },
    {
      transcript: "Sarah won't send the file and she will update the release notes.",
      summary: '',
      action_items: ['she will update the release notes'],
      decisions: [],
    },
    {
      transcript: "Sarah won't send the file, and the team will update the release notes.",
      summary: '',
      action_items: ['the team will update the release notes'],
      decisions: [],
    },
    {
      transcript: 'We have not chosen a launch date, but we approved the privacy approach.',
      summary: '',
      action_items: [],
      decisions: ['we approved the privacy approach'],
    },
    {
      transcript: 'There is no decision on the launch until the review is complete.',
      summary: 'There is no decision on the launch until the review is complete',
      action_items: [],
      decisions: [],
    },
    {
      transcript: 'The decision is still pending. No final decision has been made. No final decision on the launch. The launch decision is not final. We decided the launch date is Friday.',
      summary: 'The decision is still pending No final decision has been made No final decision on the launch',
      action_items: [],
      decisions: ['We decided the launch date is Friday'],
    },
    {
      transcript: 'We need a decision on pricing by Friday. The team must make a decision before launch. Decision is required by Friday. The team reached a decision to retain the current price.',
      summary: 'We need a decision on pricing by Friday Decision is required by Friday',
      action_items: ['The team must make a decision before launch'],
      decisions: ['The team reached a decision to retain the current price'],
    },
    {
      transcript: 'Should we review the proposal? We should consider another vendor. The updated installer will be available next week.',
      summary: 'Should we review the proposal We should consider another vendor The updated installer will be available next week',
      action_items: [],
      decisions: [],
    },
    {
      transcript: "Will the service restart tonight? We don't need to launch the new build. We do not need to merge today. Sarah will update the release notes.",
      summary: "Will the service restart tonight We don't need to launch the new build We do not need to merge today",
      action_items: ['Sarah will update the release notes'],
      decisions: [],
    },
    {
      transcript: 'Sarah will review the proposal by Friday. The team must publish the report.',
      summary: '',
      action_items: ['Sarah will review the proposal by Friday', 'The team must publish the report'],
      decisions: [],
    },
    {
      transcript: 'Sarah will be reviewing the proposal by Friday.',
      summary: '',
      action_items: ['Sarah will be reviewing the proposal by Friday'],
      decisions: [],
    },
    {
      transcript: 'If the client approves the budget, Sarah will sign the order. Only if QA passes will David publish the release. Sarah will send the final draft on Friday.',
      summary: 'If the client approves the budget, Sarah will sign the order Only if QA passes will David publish the release',
      action_items: ['Sarah will send the final draft on Friday'],
      decisions: [],
    },
    {
      transcript: 'Sarah will send the approved draft on Friday. Sarah will present the chosen plan tomorrow. We approved the privacy approach.',
      summary: '',
      action_items: [
        'Sarah will send the approved draft on Friday',
        'Sarah will present the chosen plan tomorrow',
      ],
      decisions: ['We approved the privacy approach'],
    },
    {
      transcript: 'We must be ready before review. Sarah must be available for questions. Sarah must be available and review the agenda. The team will review the agenda. Sarah must be ready, and the team will send the agenda.',
      summary: 'We must be ready before review Sarah must be available for questions',
      action_items: ['Sarah must be available and review the agenda', 'The team will review the agenda', 'Sarah must be ready, and the team will send the agenda'],
      decisions: [],
    },
    {
      transcript: 'Sarah will try to finish the test run. David will probably share the build tomorrow. We will maybe move the launch to Friday. Alex will attempt to reproduce it. Priya will hopefully send the results. Omar will be trying to resolve it. Sarah will review the release checklist.',
      summary: 'Sarah will try to finish the test run David will probably share the build tomorrow We will maybe move the launch to Friday',
      action_items: ['Sarah will review the release checklist'],
      decisions: [],
    },
    {
      transcript: "Let's not publish before legal sign-off. Let's not publish today, but Sarah will publish the docs tomorrow. Let's not forget to send the invoice by Friday.",
      summary: "Let's not publish before legal sign-off",
      action_items: [
        'Sarah will publish the docs tomorrow',
        "Let's not forget to send the invoice by Friday",
      ],
      decisions: [],
    },
  ];
  for (const [index, regression] of regressionCases.entries()) {
    const regressionResponse = await fetchImpl('http://127.0.0.1:8000/api/dictate/format-notes', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript: regression.transcript }),
      signal: AbortSignal.timeout(5_000),
    });
    let regressionPayload = null;
    try { regressionPayload = await regressionResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isMeetingNotesResponse(regressionResponse.status, regressionPayload, regression)) {
      throw new Error(`OfficeKit sidecar meeting-notes regression ${index + 1} failed (${regressionResponse.status}); summary=${regressionPayload?.summary === regression.summary}, actions=${JSON.stringify(regressionPayload?.action_items)}, decisions=${JSON.stringify(regressionPayload?.decisions)}.`);
    }
  }
}

async function smokeDictationCleanup(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/dictate/cleanup', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transcript: 'jason comma send the notes period new paragraph we will ship Friday',
      dictionary: { jason: 'JSON' },
    }),
    signal: AbortSignal.timeout(5_000),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  const expected = 'JSON, send the notes.\n\nWe will ship Friday.';
  if (!isDictationCleanupResponse(response.status, payload, expected)) {
    throw new Error(`OfficeKit sidecar dictation-cleanup smoke check returned HTTP ${response.status}.`);
  }
}

async function smokePasswordGenerator(fetchImpl, headers) {
  for (const [length, includeSymbols] of [[20, true], [32, false]]) {
    const query = new URLSearchParams({ length: String(length), include_symbols: String(includeSymbols) });
    const response = await fetchImpl(`http://127.0.0.1:8000/api/crypto/password?${query}`, {
      method: 'POST',
      headers,
      signal: AbortSignal.timeout(5_000),
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
    if (response.headers.get('cache-control') !== 'no-store' ||
        !isPasswordGeneratorResponse(response.status, payload, length, includeSymbols)) {
      throw new Error(`OfficeKit sidecar password-generator smoke check returned HTTP ${response.status}.`);
    }
  }
}

async function smokePassphraseGenerator(fetchImpl, headers) {
  const wordCount = 6;
  const separator = ' ';
  const response = await fetchImpl('http://127.0.0.1:8000/api/crypto/passphrase', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ word_count: wordCount, separator }),
    signal: AbortSignal.timeout(5_000),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (response.headers.get('cache-control') !== 'no-store' ||
      !isPassphraseGeneratorResponse(response.status, payload, wordCount, separator)) {
    throw new Error(`OfficeKit sidecar passphrase-generator smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeColorConversion(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/colors/convert', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: '#f00', source_format: 'hex', target_format: 'rgb' }),
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isColorConversionResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar color-conversion smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeScientificMath(fetchImpl, headers) {
  const expression = 'sin(90) + asin(1)';
  const angleMode = 'degrees';
  const expected = { expression, result: 91, angleMode };
  const response = await fetchImpl('http://127.0.0.1:8000/api/math/eval', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expression, angle_mode: angleMode }),
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isMathEvaluationResponse(response.status, payload, expected)) {
    throw new Error(`OfficeKit sidecar scientific-math smoke check returned HTTP ${response.status}.`);
  }
}

export function financialCalculatorSmokeChecks() {
  const checks = [
    { path: '/api/calculator/margin-markup', body: { cost: 80, revenue: 100 }, validate: isMarginMarkupResponse, label: 'margin/markup' },
    { path: '/api/calculator/margin-markup', body: { cost: 1.25, revenue: 1.125 }, validate: (status, payload) => isMarginMarkupResponse(status, payload, { cost: 1.25, revenue: 1.125, profit: -0.13, gross_margin_percent: -11.11, markup_percent: -10 }), label: 'margin/markup half-up rounding' },
    { path: '/api/calculator/break-even', body: { fixed_costs: 1000, price_per_unit: 50, cost_per_unit: 20 }, validate: isBreakEvenResponse, label: 'break-even' },
    { path: '/api/calculator/simple-interest', body: { principal: 1000, annual_rate_percent: 10, time_value: 18, time_unit: 'months' }, validate: isSimpleInterestResponse, label: 'simple interest' },
    { path: '/api/calculator/depreciation', body: { asset_cost: 10000, salvage_value: 1000, useful_life_years: 3 }, validate: isDepreciationResponse, label: 'depreciation' },
    { path: '/api/calculator/percent-of', body: { percent: 15, value: 240 }, validate: isPercentOfResponse, label: 'percent-of' },
    { path: '/api/calculator/percentage-change', body: { original_value: 80, new_value: 100 }, validate: isPercentageChangeResponse, label: 'percentage change' },
    { path: '/api/calculator/discount', body: { price: 100, discount_percent: 20 }, validate: isDiscountResponse, label: 'discount' },
  ];
  return checks;
}

async function smokeFinancialUtilityCalculators(fetchImpl, headers) {
  for (const check of financialCalculatorSmokeChecks()) {
    const response = await fetchImpl(`http://127.0.0.1:8000${check.path}`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(check.body),
      signal: AbortSignal.timeout(5000),
    });
    let payload = null;
    try { payload = await response.json(); } catch { /* validator reports invalid response */ }
    if (!check.validate(response.status, payload)) {
      throw new Error(`OfficeKit sidecar ${check.label} smoke check returned HTTP ${response.status}.`);
    }
  }
}

async function smokeUnitCatalog(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/units/catalog', {
    headers,
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The structural checks below report a malformed response.
  }
  const categories = payload?.categories;
  if (response.status !== 200 || !Array.isArray(categories) || categories.length !== 15) {
    throw new Error(`OfficeKit sidecar unit-catalog smoke check returned HTTP ${response.status}.`);
  }
  const categoryIds = categories.map((item) => item?.id);
  if (new Set(categoryIds).size !== categoryIds.length || !categoryIds.includes('temperature')) {
    throw new Error('OfficeKit sidecar unit catalog has invalid category identifiers.');
  }
  const digital = categories.find((item) => item.id === 'digital_storage')?.units;
  const symbols = new Set(Array.isArray(digital) ? digital.map((unit) => unit?.id) : []);
  if (!['bit', 'byte', 'kB', 'kb', 'KiB', 'Kib'].every((unit) => symbols.has(unit))) {
    throw new Error('OfficeKit sidecar unit catalog lost case-sensitive storage units.');
  }
  for (const category of categories) {
    if (typeof category.label !== 'string' || !Array.isArray(category.units) || category.units.length < 2) {
      throw new Error('OfficeKit sidecar unit catalog contains an invalid category.');
    }
    const ids = category.units.map((unit) => unit?.id);
    if (ids.some((id) => typeof id !== 'string' || !id) || new Set(ids).size !== ids.length
      || category.units.some((unit) => typeof unit.label !== 'string' || !unit.label)) {
      throw new Error('OfficeKit sidecar unit catalog contains invalid unit choices.');
    }
  }
}

async function smokeLoanEmi(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/calculator/loan-emi', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ principal: 100_000, annual_interest_rate: 10, tenure_years: 5 }),
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isLoanEmiResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar loan-EMI smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeCompoundInterest(fetchImpl, headers) {
  const input = {
    principal: 1000,
    annual_rate: 12,
    years: 1,
    compound_freq: 1,
    monthly_contribution: 100,
  };
  const monthlyFactor = Math.pow(1 + input.annual_rate / 100 / input.compound_freq, input.compound_freq / 12);
  let futureValue = input.principal;
  for (let month = 0; month < 12; month += 1) futureValue = futureValue * monthlyFactor + input.monthly_contribution;
  futureValue = Math.round(futureValue * 100) / 100;
  const expected = {
    future_value: futureValue,
    total_invested: 2200,
    total_interest_earned: Math.round((futureValue - 2200) * 100) / 100,
  };
  const response = await fetchImpl('http://127.0.0.1:8000/api/calculator/compound-interest', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isCompoundInterestResponse(response.status, payload, expected)) {
    throw new Error(`OfficeKit sidecar compound-interest smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeNetworkPing(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/network/ping', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ target: '127.0.0.1', count: 1, timeout_seconds: 3 }),
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isNetworkPingResponse(response.status, payload, '127.0.0.1')) {
    throw new Error(`OfficeKit sidecar ping smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeNetworkDns(fetchImpl, headers) {
  const hostname = 'example.com';
  const response = await fetchImpl('http://127.0.0.1:8000/api/network/dns', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ hostname, record_type: 'A', timeout_seconds: 5 }),
    signal: AbortSignal.timeout(7000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (payload?.status !== 'success' || !isDnsLookupResponse(response.status, payload, hostname, 'A')) {
    throw new Error(`OfficeKit sidecar DNS smoke check returned HTTP ${response.status} with status ${payload?.status ?? 'unknown'}.`);
  }
}

async function smokeNetworkInterfaces(fetchImpl, headers) {
  for (const includeAddresses of [false, true]) {
    const response = await fetchImpl('http://127.0.0.1:8000/api/network/interfaces', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ include_addresses: includeAddresses }),
      signal: AbortSignal.timeout(5000),
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      // The response validator reports a non-JSON or malformed API response.
    }
    if (!isNetworkInterfacesResponse(response.status, payload, includeAddresses)) {
      throw new Error(`OfficeKit sidecar network-interface smoke check returned HTTP ${response.status} for address visibility ${includeAddresses}.`);
    }
  }
}

async function smokeSystemResources(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/system/resources', {
    headers,
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isSystemResourceResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar system-resource smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeSystemInfo(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/system/info', {
    headers,
    signal: AbortSignal.timeout(5000),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    // The response validator reports a non-JSON or malformed API response.
  }
  if (!isRedactedSystemInfoResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar system-information smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeResultXlsx(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/export/result', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      format: 'xlsx',
      tool_id: 'loan_emi',
      title: 'Loan summary',
      created_at: '2026-10-06T09:30:00+05:30',
      inputs: [{ name: 'Principal', value: 250000, unit: 'INR' }],
      results: [{ name: 'Payment', value: 5135.77, unit: 'INR/month' }],
      assumptions: ['Fees excluded'],
      tables: [{ title: 'Schedule', columns: ['Month', 'Balance'], rows: [[1, 200000]] }],
      include_attribution: true,
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isResultXlsxAttachmentResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar XLSX result-export smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeResultPptx(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/export/result', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      format: 'pptx',
      tool_id: 'loan_emi',
      title: 'Loan summary',
      created_at: '2026-10-06T09:30:00+05:30',
      inputs: [{ name: 'Principal', value: 250000, unit: 'INR' }],
      results: [{ name: 'Payment', value: 5135.77, unit: 'INR/month' }],
      assumptions: ['Fees excluded'],
      tables: [{ title: 'Schedule', columns: ['Month', 'Balance'], rows: [[1, 200000]] }],
      include_attribution: true,
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isResultPptxAttachmentResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar PPTX result-export smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeResultPdf(fetchImpl, headers) {
  const response = await fetchImpl('http://127.0.0.1:8000/api/export/result', {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      format: 'pdf',
      tool_id: 'loan_emi',
      title: 'OfficeKit கணக்கீட்டு முடிவு',
      created_at: '2026-10-06T09:30:00+05:30',
      inputs: [{ name: 'Principal', value: 250000, unit: 'INR' }],
      results: [{ name: 'மாதத் தவணை', value: 5135.77, unit: 'INR/month' }],
      assumptions: ['Fees excluded'],
      tables: [{ title: 'Schedule', columns: ['Month', 'Balance'], rows: [[1, 200000]] }],
      include_attribution: true,
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isResultPdfAttachmentResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar PDF result-export smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeResultImages(fetchImpl, headers) {
  for (const format of ['png', 'jpeg']) {
    const response = await fetchImpl('http://127.0.0.1:8000/api/export/result', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        format,
        tool_id: 'loan_emi',
        title: 'Loan summary',
        created_at: '2026-10-06T09:30:00+05:30',
        inputs: [{ name: 'Principal', value: 250000, unit: 'INR' }],
        results: [{ name: 'Payment', value: 5135.77, unit: 'INR/month' }],
        assumptions: ['Fees excluded'],
        tables: [{ title: 'Schedule', columns: ['Month', 'Balance'], rows: [[1, 200000]] }],
        include_attribution: true,
      }),
      signal: AbortSignal.timeout(30_000),
    });
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!isResultImageAttachmentResponse(
      response.status,
      response.headers.get('content-type'),
      response.headers.get('content-disposition'),
      bytes,
      format,
    )) {
      throw new Error(`OfficeKit sidecar ${format.toUpperCase()} result-export smoke check returned HTTP ${response.status}.`);
    }
  }
}

function createStatementSmokePdf() {
  const rows = [
    ['Date', 'Description', 'Withdrawals', 'Deposits', 'Balance'],
    ['2024-01-01', 'Opening balance', '', '', '1000.00'],
    ['2024-01-05', 'Client invoice', '', '500.00', '1500.00'],
    ['2024-01-10', 'Service fee', '50.00', '', '1450.00'],
  ];
  const left = 40;
  const top = 740;
  const rowHeight = 20;
  const widths = [70, 190, 80, 75, 75];
  const xs = [left];
  for (const width of widths) xs.push(xs.at(-1) + width);
  const operators = [];
  for (let row = 0; row <= rows.length; row += 1) {
    const y = top - row * rowHeight;
    operators.push(`${left} ${y} m ${xs.at(-1)} ${y} l S`);
  }
  for (const x of xs) operators.push(`${x} ${top} m ${x} ${top - rows.length * rowHeight} l S`);
  for (let row = 0; row < rows.length; row += 1) {
    for (let column = 0; column < rows[row].length; column += 1) {
      const value = rows[row][column];
      if (!value) continue;
      const safe = value.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
      operators.push(`BT /F1 8 Tf ${xs[column] + 4} ${top - (row + 1) * rowHeight + 6} Td (${safe}) Tj ET`);
    }
  }
  return encodeStatementSmokePdf(operators);
}

function createUnruledStatementSmokePdf() {
  const items = [
    [40, 740, 'Transaction'], [90, 740, 'Date'], [150, 740, 'Particulars'],
    [350, 740, 'Withdrawals'], [420, 740, 'Deposits'], [490, 740, 'Running'], [532, 740, 'Balance'],
    [40, 720, '2024-01-01'], [150, 720, 'Opening balance'], [490, 720, '1000.00'],
    [40, 700, '2024-01-05'], [150, 700, 'Client invoice via'],
    [150, 680, 'international clearing reference TXN123456789'],
    [150, 660, 'from Accounts Team'],
    [420, 700, '500.00'], [490, 700, '1500.00'],
    [40, 650, '2024-01-10'], [150, 650, 'Monthly service fee'], [350, 650, '50.00'], [490, 650, '1450.00'],
    [40, 600, 'STATEMENT SUMMARY'], [150, 600, 'OpeningBalanceDrCount CrCount Debits Credits ClosingBal'],
    [150, 570, 'For assistance contact Customer Care'],
  ];
  const operators = items.map(([x, y, value]) => {
    const safe = value.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
    return `BT /F1 8 Tf ${x} ${y} Td (${safe}) Tj ET`;
  });
  return encodeStatementSmokePdf(operators);
}

function encodeStatementSmokePdf(operators) {
  const content = `${operators.join('\n')}\n`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(content, 'ascii')} >>\nstream\n${content}endstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  const chunks = [Buffer.from('%PDF-1.4\n', 'ascii')];
  const offsets = [0];
  let length = chunks[0].length;
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(length);
    const chunk = Buffer.from(`${index + 1} 0 obj\n${objects[index]}\nendobj\n`, 'ascii');
    chunks.push(chunk);
    length += chunk.length;
  }
  const xrefOffset = length;
  const entries = offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  chunks.push(Buffer.from(`xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${entries}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`, 'ascii'));
  return Buffer.concat(chunks);
}

async function smokeUnruledStatementPdf(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob([createUnruledStatementSmokePdf()], { type: 'application/pdf' }), 'unruled-statement.pdf');
  const response = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(STATEMENT_SMOKE_TIMEOUT_MS),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isUnruledStatementPdfResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar unruled-statement smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeWeakVectorStatementPdf(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob([
    fs.readFileSync(path.join(REPO_ROOT, 'tests/fixtures/statements/weak-vector-raster-statement.pdf')),
  ], { type: 'application/pdf' }), 'weak-vector-raster-statement.pdf');
  const response = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(STATEMENT_SMOKE_TIMEOUT_MS),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isWeakVectorStatementRecoveryResponse(response.status, payload)) {
    const summary = {
      transactions: Array.isArray(payload?.transactions)
        ? payload.transactions.slice(0, 12).map(({ date, description, debit, credit, balance, status }) => ({
          date, description, debit, credit, balance, status,
        }))
        : null,
      reconciliation: payload?.reconciliation ?? null,
    };
    throw new Error(`OfficeKit sidecar weak-vector statement OCR recovery did not produce the expected rows (HTTP ${response.status}): ${JSON.stringify(summary)}`);
  }
}

async function smokeStatementPdf(fetchImpl, headers) {
  const statementPdf = createStatementSmokePdf();
  const form = new FormData();
  form.set('file', new Blob([statementPdf], { type: 'application/pdf' }), 'statement.pdf');
  const response = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(STATEMENT_SMOKE_TIMEOUT_MS),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* validator fails safely */ }
  if (!isStatementPdfExtractionResponse(response.status, payload)) {
    throw new Error(`OfficeKit sidecar statement-PDF extraction smoke check returned HTTP ${response.status}.`);
  }

  const textForm = new FormData();
  textForm.set('file', new Blob([statementPdf], { type: 'application/pdf' }), 'statement.pdf');
  textForm.set('page_ranges', '1');
  textForm.set('format', 'md');
  const textResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/text', {
    method: 'POST', headers, body: textForm, signal: AbortSignal.timeout(30_000),
  });
  const textBytes = Buffer.from(await textResponse.arrayBuffer());
  const extractedText = textBytes.toString('utf8');
  if (textResponse.status !== 200 ||
      textResponse.headers.get('content-type')?.toLowerCase().split(';', 1)[0].trim() !== 'text/markdown' ||
      !textResponse.headers.get('content-disposition')?.includes('extracted-text.md') ||
      textResponse.headers.get('x-officekit-page-count') !== '1' ||
      textResponse.headers.get('x-officekit-selected-pages') !== '1' ||
      (textResponse.headers.get('x-officekit-missing-text-pages') || '') !== '' ||
      !extractedText.includes('Client invoice') || !extractedText.includes('2024-01-10')) {
    throw new Error(`OfficeKit sidecar PDF text extraction smoke check failed: status=${textResponse.status}, type=${textResponse.headers.get('content-type')}, disposition=${textResponse.headers.get('content-disposition')}, selected pages=${textResponse.headers.get('x-officekit-selected-pages')}.`);
  }

  const reviewPdfPath = process.env.OFFICEKIT_STATEMENT_REVIEW_PDF;
  if (reviewPdfPath) {
    const before = fs.readFileSync(reviewPdfPath);
    if (before.length < 8 || before.length > 67_108_864 || !before.subarray(0, 5).equals(Buffer.from('%PDF-', 'ascii'))) {
      throw new Error('The optional statement review sample must be a readable PDF no larger than 64 MiB.');
    }
    const reviewForm = new FormData();
    reviewForm.set('file', new Blob([before], { type: 'application/pdf' }), path.basename(reviewPdfPath));
    const reviewResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
      method: 'POST', headers, body: reviewForm, signal: AbortSignal.timeout(60_000),
    });
    let reviewPayload = null;
    try { reviewPayload = await reviewResponse.json(); } catch (_) { /* validator fails safely */ }
    const reviewTransactions = reviewPayload?.transactions;
    const expectedDates = ['21/09/26', '25/09/26', '25/09/26', '25/09/26'];
    const expectedAmounts = [
      { debit: null, credit: 1_718_697.4, balance: 1_737_613.76 },
      { debit: 200_000, credit: null, balance: 1_537_613.76 },
      { debit: 200_000, credit: null, balance: 1_337_613.76 },
      { debit: 150_000, credit: null, balance: 1_187_613.76 },
    ];
    if (reviewResponse.status !== 200 || !Array.isArray(reviewTransactions) || reviewTransactions.length !== 4 ||
        reviewTransactions.some((transaction, index) => transaction?.date !== expectedDates[index]) ||
        reviewTransactions.some((transaction, index) => {
          const expected = expectedAmounts[index];
          return transaction?.debit !== expected.debit || transaction?.credit !== expected.credit ||
            !Number.isFinite(transaction?.balance) || Math.abs(transaction.balance - expected.balance) > 0.005;
        }) ||
        reviewTransactions[0]?.status !== 'ok' ||
        reviewTransactions.some(transaction => typeof transaction?.description !== 'string' || transaction.description.trim().length < 10) ||
        !reviewTransactions[0].description.includes('FOREIGN') ||
        !reviewTransactions[1].description.includes('NEFT DR') ||
        !reviewTransactions[2].description.includes('50100000000001') ||
        !reviewTransactions[3].description.includes('50100000000002') ||
        reviewPayload?.reconciliation?.status !== 'verified' ||
        reviewPayload?.reconciliation?.checked_rows !== 4 ||
        reviewPayload?.reconciliation?.unverified_rows !== 0 ||
        reviewTransactions.some(transaction => transaction?.status !== 'ok') ||
        reviewPayload?.reconciliation?.discrepancies_count !== 0) {
      throw new Error(`OfficeKit sidecar local statement review returned HTTP ${reviewResponse.status} or unexpected row/reconciliation shape.`);
    }
    const exportResponse = await fetchImpl('http://127.0.0.1:8000/api/export/csv', {
      method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ transactions: reviewTransactions }), signal: AbortSignal.timeout(30_000),
    });
    const csv = await exportResponse.text();
    if (exportResponse.status !== 200 || csv.trim().split(/\r?\n/).length !== 5 ||
        !csv.includes('21/09/26') || !csv.includes('25/09/26') || /STATEMENT SUMMARY/i.test(csv)) {
      throw new Error(`OfficeKit sidecar local statement CSV review returned HTTP ${exportResponse.status} or unexpected row count.`);
    }
    const workbookResponse = await fetchImpl('http://127.0.0.1:8000/api/export/excel', {
      method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ transactions: reviewTransactions }), signal: AbortSignal.timeout(30_000),
    });
    const workbook = Buffer.from(await workbookResponse.arrayBuffer());
    if (workbookResponse.status !== 200 || workbook.length < 1000 ||
        !workbook.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]))) {
      throw new Error(`OfficeKit sidecar local statement XLSX review returned HTTP ${workbookResponse.status} or an invalid workbook signature.`);
    }
    const legacyWorkbookResponse = await fetchImpl('http://127.0.0.1:8000/api/export/xls', {
      method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ transactions: reviewTransactions }), signal: AbortSignal.timeout(30_000),
    });
    const legacyWorkbook = Buffer.from(await legacyWorkbookResponse.arrayBuffer());
    if (legacyWorkbookResponse.status !== 200 || legacyWorkbook.length < 1000 ||
        !legacyWorkbook.subarray(0, 8).equals(Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]))) {
      throw new Error(`OfficeKit sidecar local statement XLS review returned HTTP ${legacyWorkbookResponse.status} or an invalid workbook signature.`);
    }
    const tablePreviewForm = new FormData();
    tablePreviewForm.set('file', new Blob([before], { type: 'application/pdf' }), path.basename(reviewPdfPath));
    const tablePreviewResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/tables', {
      method: 'POST', headers, body: tablePreviewForm, signal: AbortSignal.timeout(60_000),
    });
    let tablePreviewPayload = null;
    try { tablePreviewPayload = await tablePreviewResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isPdfTableDateRowsResponse(tablePreviewResponse.status, tablePreviewPayload)) {
      throw new Error(`OfficeKit packaged PDF-table preview returned HTTP ${tablePreviewResponse.status} or merged date rows.`);
    }
    if (!fs.readFileSync(reviewPdfPath).equals(before)) {
      throw new Error('OfficeKit changed the optional statement review source PDF.');
    }
  }

  await smokeUnruledStatementPdf(fetchImpl, headers);
  await smokeWeakVectorStatementPdf(fetchImpl, headers);

  const csvForm = new FormData();
  csvForm.set('file', new Blob([
    'Date,Description,Amount,Balance\n2024-01-01,Opening Balance,,100.00\n2024-01-02,Amount not detected,,95.00\n',
  ], { type: 'text/csv' }), 'statement.csv');
  const unverifiedResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: csvForm, signal: AbortSignal.timeout(30_000),
  });
  let unverifiedPayload = null;
  try { unverifiedPayload = await unverifiedResponse.json(); } catch (_) { /* validator fails safely */ }
  if (!isStatementUnverifiedResponse(unverifiedResponse.status, unverifiedPayload)) {
    throw new Error(`OfficeKit sidecar unverified-statement smoke check returned HTTP ${unverifiedResponse.status}.`);
  }

  const ambiguousStatementForm = new FormData();
  ambiguousStatementForm.set('file', new Blob([
    'Date,Description,Credit,Balance\n2024-01-01,Opening balance,,"1,234"\n2024-01-02,Settlement,"1,234","2,468"\n',
  ], { type: 'text/csv' }), 'statement-ambiguous-auto.csv');
  const ambiguousStatementResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: ambiguousStatementForm, signal: AbortSignal.timeout(30_000),
  });
  let ambiguousStatementPayload = null;
  try { ambiguousStatementPayload = await ambiguousStatementResponse.json(); } catch (_) { /* validator fails safely */ }
  if (!isAmbiguousStatementUnverifiedResponse(ambiguousStatementResponse.status, ambiguousStatementPayload)) {
    throw new Error(`OfficeKit sidecar ambiguous-auto statement smoke check returned HTTP ${ambiguousStatementResponse.status}.`);
  }

  const localizedStatements = [
    {
      name: 'statement-eu.csv',
      csv: 'Date,Description,Credit,Balance\n01/02/2024,Opening balance,,"1.000,00"\n02/02/2024,SEPA payment,"12,50","1.012,50"\n',
      expected: { credit: 12.5, balance: 1012.5 },
    },
    {
      name: 'statement-in.csv',
      csv: 'Date,Description,Credit,Balance\n01/04/2024,Opening balance,,"₹ 1,00,000.00"\n02/04/2024,UPI transfer,"₹ 2,500.00","₹ 1,02,500.00"\n',
      expected: { credit: 2500, balance: 102500 },
    },
    {
      name: 'statement-de-ambiguous.csv',
      numberLocale: 'de-DE',
      dateOrder: 'DMY',
      csv: 'Date,Description,Credit,Balance\n01/02/2024,Opening balance,,"0,000"\n02/02/2024,Settlement,"1,234","1,234"\n',
      expected: { credit: 1.234, balance: 1.234, date: '2024-02-02' },
    },
  ];
  for (const fixture of localizedStatements) {
    const localizedForm = new FormData();
    if (fixture.numberLocale) localizedForm.set('number_locale', fixture.numberLocale);
    if (fixture.dateOrder) localizedForm.set('date_order', fixture.dateOrder);
    localizedForm.set('file', new Blob([fixture.csv], { type: 'text/csv' }), fixture.name);
    const localizedResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
      method: 'POST', headers, body: localizedForm, signal: AbortSignal.timeout(30_000),
    });
    let localizedPayload = null;
    try { localizedPayload = await localizedResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isLocalizedStatementResponse(localizedResponse.status, localizedPayload, fixture.expected)) {
      throw new Error(`OfficeKit sidecar ${fixture.name} locale-normalization smoke check returned HTTP ${localizedResponse.status}.`);
    }
  }
  for (const option of [
    { name: 'number_locale', value: 'xx-YY' },
    { name: 'date_order', value: 'YDM' },
  ]) {
    const invalidOptionForm = new FormData();
    invalidOptionForm.set(option.name, option.value);
    invalidOptionForm.set('file', new Blob([
      'Date,Description,Credit,Balance\n2024-01-01,Opening balance,,0.00\n',
    ], { type: 'text/csv' }), 'statement-invalid-option.csv');
    const invalidOptionResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
      method: 'POST', headers, body: invalidOptionForm, signal: AbortSignal.timeout(30_000),
    });
    let invalidOptionPayload = null;
    try { invalidOptionPayload = await invalidOptionResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isInvalidStatementOptionResponse(invalidOptionResponse.status, invalidOptionPayload)) {
      throw new Error(`OfficeKit sidecar invalid ${option.name} smoke check returned HTTP ${invalidOptionResponse.status}.`);
    }
  }
}

function createCompressionSmokePdf() {
  const imageWidth = 32;
  const imageHeight = 32;
  const rawImage = Buffer.alloc(imageWidth * imageHeight * 3);
  for (let y = 0; y < imageHeight; y += 1) {
    for (let x = 0; x < imageWidth; x += 1) {
      const offset = (y * imageWidth + x) * 3;
      rawImage[offset] = (x * 17 + y * 3) % 256;
      rawImage[offset + 1] = (y * 19 + x * 5) % 256;
      rawImage[offset + 2] = (x * 7 + y * 11) % 256;
    }
  }
  const imageStream = deflateSync(rawImage);
  const pageContent = Buffer.from(
    'q 0.16 0.32 0.68 rg 4 4 136 136 re f Q\nq 96 0 0 96 24 24 cm /Im1 Do Q\nBT /F1 11 Tf 1 1 1 rg 8 125 Td (OfficeKit PDF fidelity) Tj ET\n',
    'ascii',
  );
  const objects = [
    Buffer.from('<< /Type /Catalog /Pages 2 0 R >>', 'ascii'),
    Buffer.from('<< /Type /Pages /Kids [3 0 R] /Count 1 >>', 'ascii'),
    Buffer.from('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 144 144] /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>', 'ascii'),
    Buffer.from('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', 'ascii'),
    Buffer.concat([
      Buffer.from(`<< /Length ${pageContent.length} >>\nstream\n`, 'ascii'),
      pageContent,
      Buffer.from('endstream', 'ascii'),
    ]),
    Buffer.concat([
      Buffer.from(`<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length ${imageStream.length} >>\nstream\n`, 'ascii'),
      imageStream,
      Buffer.from('\nendstream', 'ascii'),
    ]),
  ];
  const chunks = [Buffer.from('%PDF-1.4\n', 'ascii')];
  const offsets = [0];
  let length = chunks[0].length;
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(length);
    const prefix = Buffer.from(`${index + 1} 0 obj\n`, 'ascii');
    const suffix = Buffer.from('\nendobj\n', 'ascii');
    chunks.push(prefix, objects[index], suffix);
    length += prefix.length + objects[index].length + suffix.length;
  }
  const xrefOffset = length;
  const entries = offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  chunks.push(Buffer.from(
    `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${entries}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`,
    'ascii',
  ));
  return Buffer.concat(chunks);
}

function createSmokePdf(pageCount = 1, pageSizeOffset = 0, metadataMarker = null, structure = null) {
  if (!Number.isSafeInteger(pageCount) || pageCount < 1 || pageCount > 10 ||
      !Number.isSafeInteger(pageSizeOffset) || pageSizeOffset < 0 || pageSizeOffset > 100 ||
      (metadataMarker !== null && (typeof metadataMarker !== 'string' || metadataMarker.length < 4 || metadataMarker.length > 128 || /[()\\\r\n]/.test(metadataMarker))) ||
      (structure !== null && (!structure || typeof structure !== 'object' ||
        !/^[A-Za-z0-9_-]{4,128}$/.test(structure.outlineTitle ?? '') ||
        !/^[A-Za-z0-9_-]{4,128}$/.test(structure.fieldName ?? '') ||
        !/^[A-Za-z0-9_-]{4,128}$/.test(structure.fieldValue ?? '')))) {
    throw new Error('PDF sidecar smoke fixture page count is invalid.');
  }
  const pageReferences = Array.from({ length: pageCount }, (_, index) => `${index + 3} 0 R`).join(' ');
  const firstExtraObject = pageCount + 3;
  const metadataObject = metadataMarker ? firstExtraObject : null;
  const infoObject = metadataMarker ? firstExtraObject + 1 : null;
  let nextObject = firstExtraObject + (metadataMarker ? 2 : 0);
  const outlineRootObject = structure ? nextObject++ : null;
  const outlineItemObject = structure ? nextObject++ : null;
  const acroFormObject = structure ? nextObject++ : null;
  const fieldObject = structure ? nextObject++ : null;
  const objects = [
    `<< /Type /Catalog /Pages 2 0 R${metadataMarker ? ` /Metadata ${metadataObject} 0 R` : ''}${structure ? ` /Outlines ${outlineRootObject} 0 R /PageMode /UseOutlines /AcroForm ${acroFormObject} 0 R` : ''} >>`,
    `<< /Type /Pages /Kids [${pageReferences}] /Count ${pageCount} >>`,
    ...Array.from({ length: pageCount }, (_, index) => {
      const side = 72 + pageSizeOffset + index;
      const annotations = structure && index === 0 ? ` /Annots [${fieldObject} 0 R]` : '';
      return `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${side} ${side}] /Resources << >>${annotations} >>`;
    }),
  ];
  if (metadataMarker) {
    const xmp = `<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description>${metadataMarker}</rdf:Description></rdf:RDF></x:xmpmeta>`;
    objects.push(`<< /Type /Metadata /Subtype /XML /Length ${Buffer.byteLength(xmp, 'utf8')} >>\nstream\n${xmp}\nendstream`);
    objects.push(`<< /Title (OfficeKit metadata ${metadataMarker}) /Author (OfficeKit) >>`);
  }
  if (structure) {
    objects.push(`<< /Type /Outlines /First ${outlineItemObject} 0 R /Last ${outlineItemObject} 0 R /Count 1 >>`);
    objects.push(`<< /Title (${structure.outlineTitle}) /Parent ${outlineRootObject} 0 R /Dest [3 0 R /Fit] >>`);
    objects.push(`<< /Fields [${fieldObject} 0 R] /DA (/Helv 10 Tf 0 g) >>`);
    objects.push(`<< /Type /Annot /Subtype /Widget /FT /Tx /T (${structure.fieldName}) /V (${structure.fieldValue}) /Rect [10 10 200 30] /F 4 /P 3 0 R >>`);
  }
  const chunks = [Buffer.from('%PDF-1.4\n', 'ascii')];
  const offsets = [0];
  let length = chunks[0].length;
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(length);
    const chunk = Buffer.from(`${index + 1} 0 obj\n${objects[index]}\nendobj\n`, 'ascii');
    chunks.push(chunk);
    length += chunk.length;
  }
  const xrefOffset = length;
  const entries = offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  const infoReference = metadataMarker ? ` /Info ${infoObject} 0 R` : '';
  chunks.push(Buffer.from(`xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${entries}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R${infoReference} >>\nstartxref\n${xrefOffset}\n%%EOF\n`, 'ascii'));
  return Buffer.concat(chunks);
}

function pngCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function createSmokePng(width = 1, height = 1) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const chunk = (type, data) => {
    const typeBytes = Buffer.from(type, 'ascii');
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(pngCrc32(Buffer.concat([typeBytes, data])));
    return Buffer.concat([length, typeBytes, data, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  const rows = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y += 1) {
    const rowOffset = y * (1 + width * 4);
    rows[rowOffset] = 0;
    for (let x = 0; x < width; x += 1) {
      rows.fill(255, rowOffset + 1 + x * 4, rowOffset + 1 + x * 4 + 4);
    }
  }
  return Buffer.concat([
    signature,
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function createBurstSmokePng({ left = 0, top = 0 } = {}) {
  const sourceSize = 32;
  const cropSize = left === 0 && top === 0 ? sourceSize : 24;
  if (!Number.isInteger(left) || !Number.isInteger(top) || left < 0 || top < 0 ||
      left + cropSize > sourceSize || top + cropSize > sourceSize) {
    throw new Error('Burst smoke crop must remain inside the 32x32 source image.');
  }
  const luma = new Uint8Array(sourceSize * sourceSize);
  for (let y = 0; y < sourceSize; y += 1) {
    for (let x = 0; x < sourceSize; x += 1) {
      let value = 35 + Math.floor(x / 2) + Math.floor(y / 3);
      if ((x - 16) ** 2 + (y - 15) ** 2 <= 50) value = 165;
      if ((x - 9) ** 2 + (y - 22) ** 2 <= 8) value = 95;
      luma[y * sourceSize + x] = value;
    }
  }
  const rgba = Buffer.alloc(sourceSize * sourceSize * 4);
  for (let y = 0; y < sourceSize; y += 1) {
    for (let x = 0; x < sourceSize; x += 1) {
      const sourceX = left + Math.floor(x * cropSize / sourceSize);
      const sourceY = top + Math.floor(y * cropSize / sourceSize);
      const gray = luma[sourceY * sourceSize + sourceX];
      const offset = (y * sourceSize + x) * 4;
      rgba[offset] = gray;
      rgba[offset + 1] = gray;
      rgba[offset + 2] = gray;
      rgba[offset + 3] = 255;
    }
  }
  const rows = Buffer.alloc(sourceSize * (1 + sourceSize * 4));
  for (let y = 0; y < sourceSize; y += 1) {
    const rowOffset = y * (1 + sourceSize * 4);
    rows[rowOffset] = 0;
    rgba.copy(rows, rowOffset + 1, y * sourceSize * 4, (y + 1) * sourceSize * 4);
  }
  const chunk = (type, data) => {
    const typeBytes = Buffer.from(type, 'ascii');
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(pngCrc32(Buffer.concat([typeBytes, data])));
    return Buffer.concat([length, typeBytes, data, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(sourceSize, 0);
  header.writeUInt32BE(sourceSize, 4);
  header[8] = 8;
  header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

async function smokePdfProtectionAndRendering(fetchImpl, headers) {
  const firstSource = createSmokePdf(2, 0, null, {
    outlineTitle: 'OfficeKitOriginalOutlineMarker', fieldName: 'OfficeKitSharedField', fieldValue: 'OfficeKitAdaValueMarker',
  });
  const secondSource = createSmokePdf(1, 10, null, {
    outlineTitle: 'OfficeKitSecondOutlineMarker', fieldName: 'OfficeKitSharedField', fieldValue: 'OfficeKitGraceValueMarker',
  });
  const pageCountForm = new FormData();
  pageCountForm.append('files', new Blob([firstSource], { type: 'application/pdf' }), 'first.pdf');
  pageCountForm.append('files', new Blob([secondSource], { type: 'application/pdf' }), 'second.pdf');
  const pageCountsResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/page-counts', {
    method: 'POST', headers, body: pageCountForm, signal: AbortSignal.timeout(30_000),
  });
  const pageCounts = await pageCountsResponse.json();
  if (!isPdfPageCountsResponse(pageCountsResponse.status, pageCounts, [2, 1]) ||
      JSON.stringify(pageCounts).includes('first.pdf') || JSON.stringify(pageCounts).includes('second.pdf')) {
    throw new Error(`OfficeKit sidecar PDF page-count smoke check returned HTTP ${pageCountsResponse.status}.`);
  }

  const mergeForm = new FormData();
  mergeForm.append('files', new Blob([firstSource], { type: 'application/pdf' }), 'first.pdf');
  mergeForm.append('files', new Blob([secondSource], { type: 'application/pdf' }), 'second.pdf');
  const mergeResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/merge', {
    method: 'POST', headers, body: mergeForm, signal: AbortSignal.timeout(30_000),
  });
  const mergedBytes = Buffer.from(await mergeResponse.arrayBuffer());
  if (!isPdfAttachmentResponse(
    mergeResponse.status,
    mergeResponse.headers.get('content-type'),
    mergedBytes,
  )) {
    throw new Error(`OfficeKit sidecar PDF merge smoke check returned HTTP ${mergeResponse.status}.`);
  }
  verifyPackagedMergeStructure(mergedBytes);
  const mergedImageForm = new FormData();
  mergedImageForm.set('file', new Blob([mergedBytes], { type: 'application/pdf' }), 'merged.pdf');
  mergedImageForm.set('target_format', 'png');
  mergedImageForm.set('dpi', '72');
  const mergedImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: mergedImageForm, signal: AbortSignal.timeout(30_000),
  });
  const mergedArchive = Buffer.from(await mergedImagesResponse.arrayBuffer());
  if (!isPdfPageOrderResponse(
    mergedImagesResponse.status,
    mergedImagesResponse.headers.get('x-officekit-page-count'),
    mergedArchive,
    [[72, 72], [73, 73], [82, 82]],
  )) {
    throw new Error(`OfficeKit sidecar PDF merge page-order smoke check returned HTTP ${mergedImagesResponse.status}.`);
  }

  const pageManagementSource = createSmokePdf(3);
  const thumbnailForm = new FormData();
  thumbnailForm.set('file', new Blob([pageManagementSource], { type: 'application/pdf' }), 'thumbnail-preview.pdf');
  thumbnailForm.set('page_numbers', '3,1');
  const thumbnailResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/page-thumbnails', {
    method: 'POST', headers, body: thumbnailForm, signal: AbortSignal.timeout(30_000),
  });
  const thumbnailResult = await thumbnailResponse.json();
  if (thumbnailResponse.status !== 200 || thumbnailResponse.headers.get('content-type')?.split(';', 1)[0] !== 'application/json' ||
      thumbnailResult?.page_count !== 3 || !Array.isArray(thumbnailResult.pages) || thumbnailResult.pages.length !== 2 ||
      thumbnailResult.pages[0]?.page_number !== 3 || thumbnailResult.pages[1]?.page_number !== 1 ||
      thumbnailResult.pages.some(page => !Number.isFinite(page.width_points) || page.width_points <= 0 ||
        !Number.isFinite(page.height_points) || page.height_points <= 0 ||
        !Buffer.from(page.data_base64 || '', 'base64').subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) ||
      Number(thumbnailResponse.headers.get('content-length') || '0') > 17_000_000) {
    throw new Error(`OfficeKit sidecar PDF thumbnail smoke check returned HTTP ${thumbnailResponse.status}.`);
  }

  for (const operation of [
    {
      path: '/api/pdf/pages/delete',
      field: 'page_ranges',
      selection: '2',
      outputName: 'deleted-pages.pdf',
      dimensions: [[72, 72], [74, 74]],
    },
    {
      path: '/api/pdf/pages/reorder',
      field: 'page_order',
      selection: '3,1,2',
      outputName: 'reordered.pdf',
      dimensions: [[74, 74], [72, 72], [73, 73]],
    },
  ]) {
    const pageForm = new FormData();
    pageForm.set('file', new Blob([pageManagementSource], { type: 'application/pdf' }), 'page-management.pdf');
    pageForm.set(operation.field, operation.selection);
    const pageResponse = await fetchImpl(`http://127.0.0.1:8000${operation.path}`, {
      method: 'POST', headers, body: pageForm, signal: AbortSignal.timeout(30_000),
    });
    const pageBytes = Buffer.from(await pageResponse.arrayBuffer());
    if (!isPdfAttachmentResponse(
      pageResponse.status,
      pageResponse.headers.get('content-type'),
      pageBytes,
    ) || !pageResponse.headers.get('content-disposition')?.includes(operation.outputName)) {
      throw new Error(`OfficeKit sidecar ${operation.path} smoke returned HTTP ${pageResponse.status}.`);
    }

    const renderedForm = new FormData();
    renderedForm.set('file', new Blob([pageBytes], { type: 'application/pdf' }), operation.outputName);
    renderedForm.set('target_format', 'png');
    renderedForm.set('dpi', '72');
    const renderedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
      method: 'POST', headers, body: renderedForm, signal: AbortSignal.timeout(30_000),
    });
    const renderedBytes = Buffer.from(await renderedResponse.arrayBuffer());
    if (!isPdfPageOrderResponse(
      renderedResponse.status,
      renderedResponse.headers.get('x-officekit-page-count'),
      renderedBytes,
      operation.dimensions,
    )) {
      throw new Error(`OfficeKit sidecar ${operation.path} rendered-page fidelity smoke failed (HTTP ${renderedResponse.status}).`);
    }
  }

  const reviewPdfPath = process.env.OFFICEKIT_STATEMENT_REVIEW_PDF;
  const compressionSource = reviewPdfPath ? fs.readFileSync(reviewPdfPath) : createCompressionSmokePdf();
  if (compressionSource.length < 8 || compressionSource.length > 67_108_864 ||
      !compressionSource.subarray(0, 5).equals(Buffer.from('%PDF-', 'ascii'))) {
    throw new Error('The optional PDF fidelity sample must be a readable PDF no larger than 64 MiB.');
  }
  const sourceImageForm = new FormData();
  sourceImageForm.set('file', new Blob([compressionSource], { type: 'application/pdf' }), 'compression-source.pdf');
  sourceImageForm.set('target_format', 'png');
  sourceImageForm.set('dpi', '72');
  const sourceImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: sourceImageForm, signal: AbortSignal.timeout(30_000),
  });
  const sourceImagesArchive = Buffer.from(await sourceImagesResponse.arrayBuffer());
  const sourcePageCountHeader = sourceImagesResponse.headers.get('x-officekit-page-count');
  const sourcePageCount = Number(sourcePageCountHeader);
  if (!Number.isSafeInteger(sourcePageCount) || sourcePageCount < 1 || sourcePageCount > 50 ||
      !isPdfImageArchiveResponse(sourceImagesResponse.status, sourcePageCountHeader, sourceImagesArchive, sourcePageCount)) {
    throw new Error(`OfficeKit sidecar PDF compression source rendering failed with HTTP ${sourceImagesResponse.status}.`);
  }
  const sourceEntries = extractZipEntries(sourceImagesArchive);
  const sourcePagePngs = [];
  const sourceDimensions = [];
  for (let index = 0; index < sourcePageCount; index += 1) {
    const name = `page-${String(index + 1).padStart(3, '0')}.png`;
    const image = sourceEntries.get(name);
    const dimensions = readPngDimensions(image);
    if (!dimensions) throw new Error('OfficeKit PDF compression source rendering returned an invalid page image.');
    sourcePagePngs.push(image);
    sourceDimensions.push(dimensions);
  }
  if (sourceEntries.size !== sourcePageCount ||
      !isPdfPageOrderResponse(sourceImagesResponse.status, String(sourcePageCount), sourceImagesArchive, sourceDimensions)) {
    throw new Error(`OfficeKit sidecar PDF compression source rendering failed with HTTP ${sourceImagesResponse.status}.`);
  }
  for (const preset of ['fast', 'balanced', 'maximum']) {
    const compressionForm = new FormData();
    compressionForm.set('file', new Blob([compressionSource], { type: 'application/pdf' }), `compress-${preset}.pdf`);
    compressionForm.set('preset', preset);
    const compressionResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/compress', {
      method: 'POST', headers, body: compressionForm, signal: AbortSignal.timeout(30_000),
    });
    const compressedBytes = Buffer.from(await compressionResponse.arrayBuffer());
    const ratio = compressionResponse.headers.get('x-officekit-output-input-ratio');
    if (!isPdfCompressionResponse(
      compressionResponse.status,
      compressionResponse.headers.get('content-type'),
      ratio,
      compressedBytes,
      compressionSource.length,
    )) {
      throw new Error(`OfficeKit sidecar PDF ${preset} compression smoke check returned HTTP ${compressionResponse.status}.`);
    }
    const compressedImageForm = new FormData();
    compressedImageForm.set('file', new Blob([compressedBytes], { type: 'application/pdf' }), `compressed-${preset}.pdf`);
    compressedImageForm.set('target_format', 'png');
    compressedImageForm.set('dpi', '72');
    const compressedImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
      method: 'POST', headers, body: compressedImageForm, signal: AbortSignal.timeout(30_000),
    });
    const compressedArchive = Buffer.from(await compressedImagesResponse.arrayBuffer());
    if (!isPdfCompressionFidelityResponse(
      compressedImagesResponse.status,
      compressedImagesResponse.headers.get('x-officekit-page-count'),
      compressedArchive,
      sourcePagePngs,
      sourceDimensions,
    )) {
      throw new Error(`OfficeKit sidecar PDF ${preset} compression fidelity smoke check returned HTTP ${compressedImagesResponse.status}.`);
    }
  }

  const metadataMarkers = ['OfficeKitDocInfoMarkerA91', 'OfficeKitXmpMarkerB72'];
  const metadataSource = createSmokePdf(1, 0, metadataMarkers.join('_'));
  if (!metadataMarkers.every(marker => metadataSource.includes(marker))) {
    throw new Error('OfficeKit could not build the PDF metadata-removal smoke fixture.');
  }
  const pdfMetadataForm = new FormData();
  pdfMetadataForm.set('file', new Blob([metadataSource], { type: 'application/pdf' }), 'metadata-source.pdf');
  const pdfMetadataResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/metadata', {
    method: 'POST', headers, body: pdfMetadataForm, signal: AbortSignal.timeout(30_000),
  });
  const pdfMetadataBytes = Buffer.from(await pdfMetadataResponse.arrayBuffer());
  if (!isPdfMetadataRemovedResponse(
    pdfMetadataResponse.status,
    pdfMetadataResponse.headers.get('content-type'),
    pdfMetadataBytes,
    metadataMarkers,
  )) {
    throw new Error(`OfficeKit sidecar PDF metadata-removal smoke check returned HTTP ${pdfMetadataResponse.status}.`);
  }
  const pdfMetadataImageForm = new FormData();
  pdfMetadataImageForm.set('file', new Blob([pdfMetadataBytes], { type: 'application/pdf' }), 'metadata-removed.pdf');
  pdfMetadataImageForm.set('target_format', 'png');
  pdfMetadataImageForm.set('dpi', '72');
  const pdfMetadataImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: pdfMetadataImageForm, signal: AbortSignal.timeout(30_000),
  });
  const pdfMetadataArchive = Buffer.from(await pdfMetadataImagesResponse.arrayBuffer());
  if (!isPdfPageOrderResponse(
    pdfMetadataImagesResponse.status,
    pdfMetadataImagesResponse.headers.get('x-officekit-page-count'),
    pdfMetadataArchive,
    [[72, 72]],
  )) {
    throw new Error(`OfficeKit sidecar PDF metadata-removal fidelity smoke check returned HTTP ${pdfMetadataImagesResponse.status}.`);
  }

  const splitForm = new FormData();
  splitForm.set('file', new Blob([createSmokePdf(3)], { type: 'application/pdf' }), 'split-source.pdf');
  splitForm.set('page_ranges', '3,1');
  const splitResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/split', {
    method: 'POST', headers, body: splitForm, signal: AbortSignal.timeout(30_000),
  });
  const splitBytes = Buffer.from(await splitResponse.arrayBuffer());
  if (!isPdfSplitAttachmentResponse(splitResponse.status, splitResponse.headers.get('content-type'), splitBytes)) {
    throw new Error(`OfficeKit sidecar PDF split smoke check returned HTTP ${splitResponse.status}.`);
  }
  const splitImageForm = new FormData();
  splitImageForm.set('file', new Blob([splitBytes], { type: 'application/pdf' }), 'selected-pages.pdf');
  splitImageForm.set('target_format', 'png');
  splitImageForm.set('dpi', '72');
  const splitImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: splitImageForm, signal: AbortSignal.timeout(30_000),
  });
  const splitImageArchive = Buffer.from(await splitImagesResponse.arrayBuffer());
  if (!isPdfSplitPageOrderResponse(
    splitImagesResponse.status,
    splitImagesResponse.headers.get('x-officekit-page-count'),
    splitImageArchive,
    [[74, 74], [72, 72]],
  )) {
    throw new Error(`OfficeKit sidecar PDF split page-order smoke check returned HTTP ${splitImagesResponse.status}.`);
  }

  const groupSplitForm = new FormData();
  groupSplitForm.set('file', new Blob([createSmokePdf(3)], { type: 'application/pdf' }), 'grouped-source.pdf');
  groupSplitForm.set('groups', JSON.stringify([
    { name: 'middle.pdf', page_ranges: '2' },
    { name: 'outside-order.pdf', page_ranges: '3,1' },
  ]));
  const groupSplitResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/split/groups', {
    method: 'POST', headers, body: groupSplitForm, signal: AbortSignal.timeout(30_000),
  });
  const groupSplitBytes = Buffer.from(await groupSplitResponse.arrayBuffer());
  const groupNames = ['middle.pdf', 'outside-order.pdf'];
  if (!isPdfSplitGroupsResponse(
    groupSplitResponse.status,
    groupSplitResponse.headers.get('content-type'),
    groupSplitBytes,
    groupNames,
  )) {
    throw new Error(`OfficeKit sidecar grouped PDF split smoke check returned HTTP ${groupSplitResponse.status}.`);
  }
  const groupEntries = extractZipEntries(groupSplitBytes);
  for (const [name, expectedDimensions] of [['middle.pdf', [[73, 73]]], ['outside-order.pdf', [[74, 74], [72, 72]]]]) {
    const groupImageForm = new FormData();
    groupImageForm.set('file', new Blob([groupEntries.get(name)], { type: 'application/pdf' }), name);
    groupImageForm.set('target_format', 'png');
    groupImageForm.set('dpi', '72');
    const groupImagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
      method: 'POST', headers, body: groupImageForm, signal: AbortSignal.timeout(30_000),
    });
    const groupImageArchive = Buffer.from(await groupImagesResponse.arrayBuffer());
    if (!isPdfSplitPageOrderResponse(
      groupImagesResponse.status,
      groupImagesResponse.headers.get('x-officekit-page-count'),
      groupImageArchive,
      expectedDimensions,
    )) {
      throw new Error(`OfficeKit sidecar grouped PDF split page-order smoke failed for ${name}.`);
    }
  }

  const original = createSmokePdf();
  const password = `${'😀'.repeat(31)}abc`;
  const protectForm = new FormData();
  protectForm.set('file', new Blob([original], { type: 'application/pdf' }), 'smoke.pdf');
  protectForm.set('password', password);
  const protectedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/protect', {
    method: 'POST', headers, body: protectForm, signal: AbortSignal.timeout(30_000),
  });
  const protectedBytes = Buffer.from(await protectedResponse.arrayBuffer());
  if (!isPdfAttachmentResponse(protectedResponse.status, protectedResponse.headers.get('content-type'), protectedBytes)) {
    throw new Error(`OfficeKit sidecar PDF protection smoke check returned HTTP ${protectedResponse.status}.`);
  }

  const unlockForm = new FormData();
  unlockForm.set('file', new Blob([protectedBytes], { type: 'application/pdf' }), 'smoke_protected.pdf');
  unlockForm.set('password', password);
  const unlockedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/unlock', {
    method: 'POST', headers, body: unlockForm, signal: AbortSignal.timeout(30_000),
  });
  const unlockedBytes = Buffer.from(await unlockedResponse.arrayBuffer());
  if (!isPdfAttachmentResponse(unlockedResponse.status, unlockedResponse.headers.get('content-type'), unlockedBytes)) {
    throw new Error(`OfficeKit sidecar PDF unlock smoke check returned HTTP ${unlockedResponse.status}.`);
  }

  for (const [route, source] of [
    ['protect', original],
    ['unlock', protectedBytes],
  ]) {
    const oversizedForm = new FormData();
    oversizedForm.set('file', new Blob([source], { type: 'application/pdf' }), 'oversized-password.pdf');
    oversizedForm.set('password', '😀'.repeat(32));
    const response = await fetchImpl(`http://127.0.0.1:8000/api/pdf/${route}`, {
      method: 'POST', headers, body: oversizedForm, signal: AbortSignal.timeout(30_000),
    });
    let detail = null;
    try { detail = await response.json(); } catch (_) { /* status check fails safely */ }
    if (response.status !== 422 || detail?.detail !== 'Password must be non-empty and within the supported size limit.') {
      throw new Error(`OfficeKit sidecar PDF ${route} password-byte-limit smoke returned HTTP ${response.status}.`);
    }
  }

  const imageForm = new FormData();
  imageForm.set('file', new Blob([unlockedBytes], { type: 'application/pdf' }), 'smoke_unlocked.pdf');
  imageForm.set('target_format', 'png');
  imageForm.set('dpi', '72');
  const imagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: imageForm, signal: AbortSignal.timeout(30_000),
  });
  const archiveBytes = Buffer.from(await imagesResponse.arrayBuffer());
  if (!isPdfImageArchiveResponse(imagesResponse.status, imagesResponse.headers.get('x-officekit-page-count'), archiveBytes)) {
    throw new Error(`OfficeKit sidecar PDF-to-image smoke check returned HTTP ${imagesResponse.status}.`);
  }

  const metadataForm = new FormData();
  metadataForm.set('file', new Blob([createSmokePng()], { type: 'image/png' }), 'smoke.png');
  const metadataResponse = await fetchImpl('http://127.0.0.1:8000/api/image/metadata', {
    method: 'POST', headers, body: metadataForm, signal: AbortSignal.timeout(30_000),
  });
  const metadataBytes = Buffer.from(await metadataResponse.arrayBuffer());
  if (!isImageMetadataAttachmentResponse(
    metadataResponse.status,
    metadataResponse.headers.get('content-type'),
    metadataResponse.headers.get('content-disposition'),
    metadataBytes,
  )) {
    throw new Error(`OfficeKit sidecar image metadata smoke check returned HTTP ${metadataResponse.status}.`);
  }
}

async function smokeSimilarImageWorkspace(fetchImpl, headers) {
  if (process.platform !== 'darwin') {
    throw new Error('HEIC sidecar smoke requires macOS native image codecs.');
  }
  const workspaceForm = new FormData();
  const burstWidePng = createBurstSmokePng();
  const burstOffCenterCropPng = createBurstSmokePng({ left: 8, top: 0 });
  const malformedPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC',
    'base64',
  );
  const heicFixtureDirectory = path.join(REPO_ROOT, 'tests/fixtures/similar-images/cc0/heic');
  const heicFiles = [
    ['heic-a', fs.readFileSync(path.join(heicFixtureDirectory, 'still-medium.heic')), 'heic'],
    ['heic-b', fs.readFileSync(path.join(heicFixtureDirectory, 'still-medium.heic')), 'heif'],
    ['heic-unrelated', fs.readFileSync(path.join(heicFixtureDirectory, 'still-high-quality.heic')), 'heic'],
  ];
  workspaceForm.append('files', new Blob([burstWidePng], { type: 'image/png' }), 'burst/a.png');
  workspaceForm.append('files', new Blob([burstOffCenterCropPng], { type: 'image/png' }), 'burst/b.png');
  workspaceForm.append('files', new Blob([malformedPng], { type: 'image/png' }), 'broken/bad.png');
  for (const [name, bytes, extension] of heicFiles) {
    workspaceForm.append('files', new Blob([bytes], { type: 'image/heic' }), `burst/${name}.${extension}`);
  }
  const created = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
    method: 'POST', headers, body: workspaceForm, signal: AbortSignal.timeout(30_000),
  });
  if (created.status !== 201) {
    throw new Error(`OfficeKit sidecar similar-image workspace smoke check returned HTTP ${created.status}.`);
  }
  let workspaceId;
  try {
    const workspace = await created.json();
    workspaceId = workspace?.workspace_id;
    if (typeof workspaceId !== 'string' || workspace.files?.length !== 6) {
      throw new Error('OfficeKit sidecar could not create the selected-image smoke workspace.');
    }
    const report = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}/similar-image-reports`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames: ['burst/a.png', 'burst/b.png'], threshold: 8 }),
      signal: AbortSignal.timeout(30_000),
    });
    let payload = null;
    try {
      payload = await report.json();
    } catch (_) {
      // The validator below turns malformed packaged responses into a smoke failure.
    }
    if (!isSimilarImageReportResponse(report.status, payload)) {
      throw new Error(`OfficeKit sidecar similar-image smoke check returned HTTP ${report.status}.`);
    }
    const heicReport = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}/similar-image-reports`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filenames: ['burst/heic-a.heic', 'burst/heic-b.heif', 'burst/heic-unrelated.heic'], threshold: 8,
      }),
      signal: AbortSignal.timeout(30_000),
    });
    let heicPayload = null;
    try {
      heicPayload = await heicReport.json();
    } catch (_) {
      // The validator below turns malformed packaged responses into a smoke failure.
    }
    if (!isSimilarImageHeicReportResponse(heicReport.status, heicPayload)) {
      const summary = {
        complete: heicPayload?.complete,
        scanned_images: heicPayload?.scanned_images,
        groups: heicPayload?.groups,
        skipped_files: heicPayload?.skipped_files,
        errors: heicPayload?.errors,
      };
      throw new Error(`OfficeKit sidecar HEIC burst smoke check returned HTTP ${heicReport.status}: ${JSON.stringify(summary)}`);
    }
    const malformedReport = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}/similar-image-reports`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames: ['broken/bad.png'], threshold: 8 }),
      signal: AbortSignal.timeout(30_000),
    });
    let malformedPayload = null;
    try {
      malformedPayload = await malformedReport.json();
    } catch (_) {
      // The validator below turns malformed packaged responses into a smoke failure.
    }
    if (!isIncompleteSimilarImageReportResponse(malformedReport.status, malformedPayload)) {
      throw new Error(`OfficeKit sidecar corrupt-image smoke check returned HTTP ${malformedReport.status}.`);
    }
  } finally {
    if (typeof workspaceId === 'string') {
      const cleared = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}`, {
        method: 'DELETE', headers, signal: AbortSignal.timeout(30_000),
      });
      if (cleared.status !== 204) {
        throw new Error(`OfficeKit sidecar could not clear its similar-image smoke workspace (HTTP ${cleared.status}).`);
      }
    }
  }
}

async function smokeImageResize(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob([createSmokePng(2, 1)], { type: 'image/png' }), 'resize_smoke.png');
  form.set('max_width', '1');
  form.set('max_height', '1');
  const response = await fetchImpl('http://127.0.0.1:8000/api/image/resize', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isResizedImageAttachmentResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    response.headers.get('x-officekit-image-width'),
    response.headers.get('x-officekit-image-height'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar image resize smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeScreenshotEditor(fetchImpl, headers) {
  const form = new FormData();
  form.set('file', new Blob([createSmokePng(2, 1)], { type: 'image/png' }), 'screenshot_smoke.png');
  form.set('operations', JSON.stringify([
    { type: 'crop', x: 0, y: 0, width: 1, height: 1 },
    { type: 'mask', x: 0, y: 0, width: 1, height: 1, color: '#123456' },
  ]));
  const response = await fetchImpl('http://127.0.0.1:8000/api/screenshot/edit', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isScreenshotEditAttachmentResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar screenshot editor smoke check returned HTTP ${response.status}.`);
  }

  const jpegForm = new FormData();
  jpegForm.set('file', new Blob([createSmokePng(2, 1)], { type: 'image/png' }), 'screenshot_smoke.png');
  jpegForm.set('operations', JSON.stringify([
    { type: 'mask', x: 0, y: 0, width: 1, height: 1, color: '#123456' },
  ]));
  jpegForm.set('format', 'jpeg');
  const jpegResponse = await fetchImpl('http://127.0.0.1:8000/api/screenshot/edit', {
    method: 'POST', headers, body: jpegForm, signal: AbortSignal.timeout(30_000),
  });
  const jpegBytes = Buffer.from(await jpegResponse.arrayBuffer());
  if (!isScreenshotEditAttachmentResponse(
    jpegResponse.status,
    jpegResponse.headers.get('content-type'),
    jpegResponse.headers.get('content-disposition'),
    jpegBytes,
    'jpeg',
  )) {
    throw new Error(`OfficeKit sidecar screenshot JPEG smoke check returned HTTP ${jpegResponse.status}.`);
  }
}

async function smokeBatchImageResize(fetchImpl, headers) {
  const form = new FormData();
  form.append('files', new Blob([createSmokePng(2, 1)], { type: 'image/png' }), 'batch_resize_a.png');
  form.append('files', new Blob([createSmokePng(1, 2)], { type: 'image/png' }), 'batch_resize_b.png');
  form.set('max_width', '1');
  form.set('max_height', '1');
  const response = await fetchImpl('http://127.0.0.1:8000/api/images/resize', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(30_000),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!isResizedImagesArchiveResponse(
    response.status,
    response.headers.get('content-type'),
    response.headers.get('content-disposition'),
    bytes,
  )) {
    throw new Error(`OfficeKit sidecar batch image resize smoke check returned HTTP ${response.status}.`);
  }
}

async function smokeFilesystemWorkspace(fetchImpl, headers) {
  const splitBytes = Buffer.from([0, 1, 2, 3, 128, 129, 254, 255, 65, 0, 66, 67, 68]);
  const splitDigest = createHash('sha256').update(splitBytes).digest('hex');
  const workspaceForm = new FormData();
  workspaceForm.append('files', new Blob(['repeat'], { type: 'text/plain' }), 'samples/sample-a.txt');
  workspaceForm.append('files', new Blob(['repeat'], { type: 'text/plain' }), 'sample-b.txt');
  workspaceForm.append('files', new Blob(['rename!'], { type: 'text/plain' }), 'rename.txt');
  const created = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
    method: 'POST', headers, body: workspaceForm, signal: AbortSignal.timeout(30_000),
  });
  if (created.status !== 201) {
    throw new Error(`OfficeKit sidecar filesystem workspace smoke check returned HTTP ${created.status}.`);
  }
  let workspaceId;
  let splitWorkspaceId;
  let isoMediaWorkspaceId;
  try {
    const workspace = await created.json();
    workspaceId = workspace?.workspace_id;
  if (typeof workspaceId !== 'string' || workspace.files?.length !== 3) {
      throw new Error('OfficeKit sidecar could not create the selected-file smoke workspace.');
    }
    const workspacePath = `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}`;
    const postJson = (route, body) => fetchImpl(`${workspacePath}/${route}`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(30_000),
    });

    const hashResponse = await postJson('hash-reports', { filenames: ['samples/sample-a.txt'], algorithm: 'sha256' });
    let hashPayload = null;
    try { hashPayload = await hashResponse.json(); } catch (_) { /* validator below fails safely */ }
    const expectedTextHash = createHash('sha256').update('repeat').digest('hex');
    if (hashResponse.status !== 200 || hashPayload?.algorithm !== 'sha256' || hashPayload?.total_files !== 1 || hashPayload?.total_bytes !== 6 || hashPayload?.complete !== true || hashPayload?.files?.length !== 1 || hashPayload.files[0]?.name !== 'samples/sample-a.txt' || hashPayload.files[0]?.size_bytes !== 6 || hashPayload.files[0]?.digest !== expectedTextHash) {
      throw new Error(`OfficeKit sidecar workspace hash smoke check returned HTTP ${hashResponse.status}.`);
    }

    const typeResponse = await postJson('file-type-reports', { filenames: ['samples/sample-a.txt'] });
    let typePayload = null;
    try { typePayload = await typeResponse.json(); } catch (_) { /* validator below fails safely */ }
    if (typeResponse.status !== 200 || typePayload?.total_files !== 1 || typePayload?.complete !== true || typePayload?.files?.length !== 1 || typePayload.files[0]?.name !== 'samples/sample-a.txt' || typePayload.files[0]?.detected_type !== 'Text' || typePayload.files[0]?.mime_type !== 'text/plain' || typePayload.files[0]?.extension_matches !== true || typePayload.files[0]?.method !== 'magic-bytes+utf8') {
      throw new Error(`OfficeKit sidecar file-type detection smoke check returned HTTP ${typeResponse.status}.`);
    }

    const isoFtyp = (brand, compatible = []) => {
      const compatibleBytes = Buffer.concat(compatible);
      const size = Buffer.alloc(4);
      size.writeUInt32BE(16 + compatibleBytes.length);
      return Buffer.concat([size, Buffer.from('ftyp'), Buffer.from(brand), Buffer.alloc(4), compatibleBytes]);
    };
    const isoMediaForm = new FormData();
    isoMediaForm.append('files', new Blob([isoFtyp('mif1', [Buffer.from('heic')])]), 'photo.heif');
    isoMediaForm.append('files', new Blob([isoFtyp('avif')]), 'photo.avif');
    isoMediaForm.append('files', new Blob([isoFtyp('qt  ')]), 'clip.mov');
    isoMediaForm.append('files', new Blob([isoFtyp('M4A ')]), 'audio.m4a');
    isoMediaForm.append('files', new Blob([isoFtyp('isom', [Buffer.from('mp42')])]), 'clip.mp4');
    const isoMediaWorkspace = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
      method: 'POST', headers, body: isoMediaForm, signal: AbortSignal.timeout(30_000),
    });
    if (isoMediaWorkspace.status !== 201) {
      throw new Error(`OfficeKit sidecar ISO media workspace import returned HTTP ${isoMediaWorkspace.status}.`);
    }
    const isoMediaWorkspacePayload = await isoMediaWorkspace.json();
    isoMediaWorkspaceId = isoMediaWorkspacePayload?.workspace_id;
    if (typeof isoMediaWorkspaceId !== 'string' || isoMediaWorkspacePayload.files?.length !== 5) {
      throw new Error('OfficeKit sidecar could not import the ISO media brand smoke files.');
    }
    const isoMediaReportResponse = await fetchImpl(
      `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(isoMediaWorkspaceId)}/file-type-reports`,
      {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ filenames: ['photo.heif', 'photo.avif', 'clip.mov', 'audio.m4a', 'clip.mp4'] }),
        signal: AbortSignal.timeout(30_000),
      },
    );
    const isoMediaReport = await isoMediaReportResponse.json();
    const expectedIsoMedia = [
      ['photo.heif', 'HEIC image', 'image/heic'],
      ['photo.avif', 'AVIF image', 'image/avif'],
      ['clip.mov', 'QuickTime video', 'video/quicktime'],
      ['audio.m4a', 'M4A audio', 'audio/mp4'],
      ['clip.mp4', 'MP4 media', 'application/mp4'],
    ];
    if (isoMediaReportResponse.status !== 200 || isoMediaReport?.complete !== true || isoMediaReport?.files?.length !== expectedIsoMedia.length || expectedIsoMedia.some(([name, detectedType, mimeType], index) => {
      const item = isoMediaReport.files[index];
      return item?.name !== name || item?.detected_type !== detectedType || item?.mime_type !== mimeType || item?.extension_matches !== true;
    })) {
      throw new Error(`OfficeKit sidecar ISO media brand smoke check returned HTTP ${isoMediaReportResponse.status}.`);
    }

    const duplicateResponse = await postJson('duplicate-reports', { max_entries: 10_000 });
    let duplicatePayload = null;
    try { duplicatePayload = await duplicateResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isDuplicateWorkspaceReportResponse(duplicateResponse.status, duplicatePayload)) {
      throw new Error(`OfficeKit sidecar duplicate-file smoke check returned HTTP ${duplicateResponse.status}.`);
    }

    const storageResponse = await postJson('storage-reports', { top_n: 10 });
    let storagePayload = null;
    try { storagePayload = await storageResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isStorageWorkspaceReportResponse(storageResponse.status, storagePayload, 19)) {
      throw new Error(`OfficeKit sidecar storage-analysis smoke check returned HTTP ${storageResponse.status}.`);
    }

    const renameRequest = {
      filenames: ['rename.txt'], pattern_type: 'affix', prefix: 'ready_',
    };
    const previewResponse = await postJson('rename-previews', renameRequest);
    let previewPayload = null;
    try { previewPayload = await previewResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isRenamePreviewResponse(previewResponse.status, previewPayload)) {
      throw new Error(`OfficeKit sidecar rename-preview smoke check returned HTTP ${previewResponse.status}.`);
    }

    const artifactResponse = await postJson('renamed-artifacts', renameRequest);
    let artifactPayload = null;
    try { artifactPayload = await artifactResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isRenameArtifactResponse(artifactResponse.status, artifactPayload)) {
      throw new Error(`OfficeKit sidecar rename-artifact smoke check returned HTTP ${artifactResponse.status}.`);
    }
    const download = await fetchImpl(`${workspacePath}/artifacts/${encodeURIComponent(artifactPayload.artifact_id)}`, {
      headers, signal: AbortSignal.timeout(30_000),
    });
    const downloadBytes = Buffer.from(await download.arrayBuffer());
    if (!isZipAttachmentResponse(download.status, download.headers.get('content-type'), downloadBytes)) {
      throw new Error(`OfficeKit sidecar renamed-file download smoke check returned HTTP ${download.status}.`);
    }

    const splitForm = new FormData();
    splitForm.append('files', new Blob([splitBytes], { type: 'application/octet-stream' }), 'smoke.bin');
    const splitWorkspaceResponse = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
      method: 'POST', headers, body: splitForm, signal: AbortSignal.timeout(30_000),
    });
    if (splitWorkspaceResponse.status !== 201) {
      throw new Error(`OfficeKit sidecar split workspace import returned HTTP ${splitWorkspaceResponse.status}.`);
    }
    const splitWorkspace = await splitWorkspaceResponse.json();
    splitWorkspaceId = splitWorkspace?.workspace_id;
    if (typeof splitWorkspaceId !== 'string' || splitWorkspace.files?.length !== 1) {
      throw new Error('OfficeKit sidecar could not import the selected binary for splitting.');
    }
    const splitWorkspacePath = `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(splitWorkspaceId)}`;
    const splitResponse = await fetchImpl(`${splitWorkspacePath}/splits`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: 'smoke.bin', chunk_size_bytes: 5 }),
      signal: AbortSignal.timeout(30_000),
    });
    let splitPayload = null;
    try { splitPayload = await splitResponse.json(); } catch (_) { /* validator fails safely */ }
    if (!isWorkspaceSplitResponse(splitResponse.status, splitPayload, splitBytes.length, splitDigest)) {
      throw new Error(`OfficeKit sidecar file-split smoke check returned HTTP ${splitResponse.status}.`);
    }
    const splitDownload = await fetchImpl(
      `${splitWorkspacePath}/artifacts/${encodeURIComponent(splitPayload.artifact_id)}`,
      { headers, signal: AbortSignal.timeout(30_000) },
    );
    const splitArchiveBytes = Buffer.from(await splitDownload.arrayBuffer());
    if (!isZipAttachmentResponse(splitDownload.status, splitDownload.headers.get('content-type'), splitArchiveBytes)) {
      throw new Error(`OfficeKit sidecar split archive download returned HTTP ${splitDownload.status}.`);
    }
    const splitEntries = extractZipEntries(splitArchiveBytes);
    const manifestBytes = splitEntries.get('split-manifest.json');
    if (!manifestBytes) throw new Error('OfficeKit sidecar split archive omitted its manifest.');
    const manifest = JSON.parse(manifestBytes.toString('utf8'));
    if (manifest.format !== 'officekit-file-split' || manifest.version !== 1 ||
        manifest.file_sha256 !== splitDigest || manifest.total_size_bytes !== splitBytes.length ||
        manifest.parts?.length !== splitPayload.chunk_count) {
      throw new Error('OfficeKit sidecar split manifest does not reconcile with the source file.');
    }
    const rebuiltParts = [];
    for (const part of manifest.parts) {
      const bytes = splitEntries.get(part.name);
      if (!bytes || bytes.length !== part.size_bytes ||
          createHash('sha256').update(bytes).digest('hex') !== part.sha256) {
        throw new Error('OfficeKit sidecar split part does not match its checksum.');
      }
      rebuiltParts.push(bytes);
    }
    if (!Buffer.concat(rebuiltParts).equals(splitBytes)) {
      throw new Error('OfficeKit sidecar split parts do not reproduce the original bytes.');
    }

    const joinForm = new FormData();
    joinForm.append('files', new Blob([splitArchiveBytes], { type: 'application/zip' }), 'smoke.bin.split.zip');
    const joinWorkspaceResponse = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
      method: 'POST', headers, body: joinForm, signal: AbortSignal.timeout(30_000),
    });
    if (joinWorkspaceResponse.status !== 201) {
      throw new Error(`OfficeKit sidecar join workspace import returned HTTP ${joinWorkspaceResponse.status}.`);
    }
    let joinWorkspaceId;
    try {
      const joinWorkspace = await joinWorkspaceResponse.json();
      joinWorkspaceId = joinWorkspace?.workspace_id;
      if (typeof joinWorkspaceId !== 'string' || joinWorkspace.files?.length !== 1) {
        throw new Error('OfficeKit sidecar could not import the split ZIP into a join workspace.');
      }
      const joinResponse = await fetchImpl(
        `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(joinWorkspaceId)}/joins`,
        {
          method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ archive_name: 'smoke.bin.split.zip', output_name: 'smoke-restored.bin' }),
          signal: AbortSignal.timeout(30_000),
        },
      );
      let joinPayload = null;
      try { joinPayload = await joinResponse.json(); } catch (_) { /* validator fails safely */ }
      if (!isWorkspaceJoinResponse(
        joinResponse.status, joinPayload, splitBytes.length, splitDigest, splitPayload.chunk_count,
      )) throw new Error(`OfficeKit sidecar file-join smoke check returned HTTP ${joinResponse.status}.`);

      const joinedDownload = await fetchImpl(
        `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(joinWorkspaceId)}/artifacts/${encodeURIComponent(joinPayload.artifact_id)}`,
        { headers, signal: AbortSignal.timeout(30_000) },
      );
      const joinedArchive = extractZipEntries(Buffer.from(await joinedDownload.arrayBuffer()));
      if (joinedDownload.status !== 200 || !joinedArchive.get('joined/smoke-restored.bin')?.equals(splitBytes)) {
        throw new Error(`OfficeKit sidecar joined-file download did not reproduce source bytes (HTTP ${joinedDownload.status}).`);
      }
    } finally {
      if (typeof joinWorkspaceId === 'string') {
        const cleared = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(joinWorkspaceId)}`, {
          method: 'DELETE', headers, signal: AbortSignal.timeout(30_000),
        });
        if (cleared.status !== 204) throw new Error(`OfficeKit sidecar could not clear its join smoke workspace (HTTP ${cleared.status}).`);
      }
    }
  } finally {
    const cleanupIds = [workspaceId, splitWorkspaceId, isoMediaWorkspaceId].filter(id => typeof id === 'string');
    const cleanupResponses = await Promise.all(cleanupIds.map(id => fetchImpl(
      `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(id)}`,
      { method: 'DELETE', headers, signal: AbortSignal.timeout(30_000) },
    )));
    if (cleanupResponses.some(response => response.status !== 204)) {
      throw new Error('OfficeKit sidecar could not clear a filesystem smoke workspace.');
    }
  }
}

async function smokeFolderComparisonCsv(fetchImpl, headers) {
  const workspaceForm = new FormData();
  workspaceForm.append('files', new Blob(['left'], { type: 'text/plain' }), 'before/=SUM(1+1).csv');
  workspaceForm.append('files', new Blob(['right'], { type: 'text/plain' }), 'after/=SUM(1+1).csv');
  const created = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
    method: 'POST', headers, body: workspaceForm, signal: AbortSignal.timeout(30_000),
  });
  if (created.status !== 201) {
    throw new Error(`OfficeKit sidecar folder-comparison workspace returned HTTP ${created.status}.`);
  }
  let workspaceId;
  try {
    const workspace = await created.json();
    workspaceId = workspace?.workspace_id;
    if (typeof workspaceId !== 'string' || workspace.files?.length !== 2) {
      throw new Error('OfficeKit sidecar could not create its folder-comparison smoke workspace.');
    }
    const response = await fetchImpl(
      `http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}/folder-comparisons?format=csv`,
      {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ left_folder: 'before', right_folder: 'after' }),
        signal: AbortSignal.timeout(30_000),
      },
    );
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!isFolderComparisonCsvResponse(
      response.status,
      response.headers.get('content-type'),
      response.headers.get('content-disposition'),
      bytes,
    )) {
      throw new Error(`OfficeKit sidecar folder-comparison CSV returned HTTP ${response.status}.`);
    }
  } finally {
    if (typeof workspaceId === 'string') {
      const cleared = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${encodeURIComponent(workspaceId)}`, {
        method: 'DELETE', headers, signal: AbortSignal.timeout(30_000),
      });
      if (cleared.status !== 204) {
        throw new Error(`OfficeKit sidecar could not clear its folder-comparison workspace (HTTP ${cleared.status}).`);
      }
    }
  }
}

export async function smokeSidecar({
  binary,
  fetchImpl = fetch,
  // The first launch of a freshly built sidecar is slow on macOS (about 30 s while the system scans it).
  timeoutMs = SIDECAR_FIRST_LAUNCH_TIMEOUT_MS,
  expectedVersion = EXPECTED_APP_VERSION,
  only = null,
} = {}) {
  if (!binary || !fs.existsSync(binary)) throw new Error(`OfficeKit backend sidecar is missing: ${binary || '(path not provided)'}`);
  if (only !== null && !['pdf-text', 'weak-vector-statement', 'similar-images'].includes(only)) {
    throw new Error('The only-supported sidecar smoke filters are pdf-text, weak-vector-statement, and similar-images.');
  }
  fetchImpl = createSidecarSmokeFetch(fetchImpl);
  const token = randomUUID();
  const auth = sidecarAuth(token);
  const grantToken = randomUUID() + randomUUID();
  const child = spawn(binary, [], {
    cwd: REPO_ROOT,
    stdio: 'ignore',
    windowsHide: true,
    // The desktop app tells its sidecar the app version; without it the sidecar reports 1.0.0.
    env: { ...auth.environment, OFFICEKIT_APP_VERSION: expectedVersion, OFFICEKIT_NATIVE_GRANT_TOKEN: grantToken },
  });
  let spawnError = null;
  child.on('error', error => { spawnError = error; });
  const deadline = Date.now() + timeoutMs;
  let healthy = false;
  try {
    while (Date.now() < deadline) {
      if (spawnError) throw new Error(`OfficeKit sidecar could not start: ${spawnError.message}`);
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`OfficeKit sidecar exited before readiness (code ${child.exitCode ?? child.signalCode}).`);
      }
      let response;
      let payload;
      try {
        response = await fetchImpl(HEALTH_URL, {
          headers: auth.headers,
          signal: AbortSignal.timeout(500),
        });
        payload = await response.json();
      } catch (_) {
        // Startup races and transient health errors are expected.
      }
      if (isOfficeKitHealthResponse(response?.status, payload, expectedVersion)) {
        await smokeLockedGateAndInstallEntitlement(fetchImpl, auth.headers, grantToken);
        if (only === 'pdf-text') {
          await smokeStatementPdf(fetchImpl, auth.headers);
          healthy = true;
          return payload;
        }
        if (only === 'weak-vector-statement') {
          await smokeUnruledStatementPdf(fetchImpl, auth.headers);
          await smokeWeakVectorStatementPdf(fetchImpl, auth.headers);
          healthy = true;
          return payload;
        }
        if (only === 'similar-images') {
          await smokeSimilarImageWorkspace(fetchImpl, auth.headers);
          healthy = true;
          return payload;
        }
        await smokeLicenseStatus(fetchImpl, auth.headers);
        await smokeMeetingNotes(fetchImpl, auth.headers);
        await smokeDictationCleanup(fetchImpl, auth.headers);
        await smokePasswordGenerator(fetchImpl, auth.headers);
        await smokePassphraseGenerator(fetchImpl, auth.headers);
        await smokeRelatedPdfSearch(fetchImpl, auth.headers);
        await smokeCsvToJson(fetchImpl, auth.headers);
        await smokeNestedTabularConversion(fetchImpl, auth.headers);
        await smokeStrictJsonFileImport(fetchImpl, auth.headers);
        await smokeStrictYamlFileImport(fetchImpl, auth.headers);
        await smokeBoundedXlsxFileImport(fetchImpl, auth.headers);
        await smokeXlsxDisplayFormatConversion(fetchImpl, auth.headers);
        await smokeYamlToJson(fetchImpl, auth.headers);
        await smokeDelimitedDataFidelity(fetchImpl, auth.headers);
        await smokeColorConversion(fetchImpl, auth.headers);
        await smokeScientificMath(fetchImpl, auth.headers);
        await smokeFinancialUtilityCalculators(fetchImpl, auth.headers);
        await smokeUnitCatalog(fetchImpl, auth.headers);
        await smokeLoanEmi(fetchImpl, auth.headers);
        await smokeCompoundInterest(fetchImpl, auth.headers);
        await smokeNetworkPing(fetchImpl, auth.headers);
        await smokeNetworkDns(fetchImpl, auth.headers);
        await smokeNetworkInterfaces(fetchImpl, auth.headers);
        await smokeSystemResources(fetchImpl, auth.headers);
        await smokeSystemInfo(fetchImpl, auth.headers);
        await smokeResultXlsx(fetchImpl, auth.headers);
        await smokeResultPptx(fetchImpl, auth.headers);
        await smokeResultPdf(fetchImpl, auth.headers);
        await smokeResultImages(fetchImpl, auth.headers);
        await smokeStatementPdf(fetchImpl, auth.headers);
        await smokePdfProtectionAndRendering(fetchImpl, auth.headers);
        await smokeImageResize(fetchImpl, auth.headers);
        await smokeBatchImageResize(fetchImpl, auth.headers);
        await smokeScreenshotEditor(fetchImpl, auth.headers);
        await smokeSimilarImageWorkspace(fetchImpl, auth.headers);
        await smokeFilesystemWorkspace(fetchImpl, auth.headers);
        await smokeFolderComparisonCsv(fetchImpl, auth.headers);
        healthy = true;
        return payload;
      }
      await delay(100);
    }
    throw new Error(`OfficeKit sidecar did not return its health response within ${timeoutMs} ms.`);
  } finally {
    if (child.pid) await stopChild(child);
    if (child.pid && !healthy && child.exitCode === null && child.signalCode === null) {
      throw new Error('OfficeKit sidecar could not be stopped after the smoke check.');
    }
  }
}

async function main() {
  const target = spawnSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' });
  if (target.status !== 0) throw new Error((target.stderr || 'Unable to determine the Rust host target.').trim());
  const smokePort = await resolveSmokePort();
  smokePortValue = String(smokePort);
  process.env.OFFICEKIT_API_PORT = smokePortValue;
  API_ORIGIN = `http://127.0.0.1:${smokePortValue}`;
  HEALTH_URL = `${API_ORIGIN}/api/health`;
  const args = process.argv.slice(2);
  const onlyIndex = args.indexOf('--only-pdf-text');
  const weakVectorIndex = args.indexOf('--only-weak-vector-statement');
  const similarImagesIndex = args.indexOf('--only-similar-images');
  if ([onlyIndex, weakVectorIndex, similarImagesIndex].filter(index => index >= 0).length > 1) {
    throw new Error('Choose only one sidecar smoke filter.');
  }
  const only = onlyIndex >= 0 ? 'pdf-text'
    : weakVectorIndex >= 0 ? 'weak-vector-statement'
      : similarImagesIndex >= 0 ? 'similar-images' : null;
  if (onlyIndex >= 0) args.splice(onlyIndex, 1);
  if (weakVectorIndex >= 0) args.splice(weakVectorIndex, 1);
  if (similarImagesIndex >= 0) args.splice(similarImagesIndex, 1);
  const binary = args[0] || resolveSmokeBinary({ targetTriple: target.stdout.trim() });
  const health = await smokeSidecar({ binary, only });
  process.stdout.write(`OfficeKit backend sidecar is healthy (version ${health.version}).\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => {
    process.stderr.write(`Backend sidecar smoke check failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
