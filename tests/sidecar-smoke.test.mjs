import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import test from 'node:test';
import { deflateRawSync } from 'node:zlib';
import {
  isCsvJsonConversionResponse,
  isYamlToJsonResponse,
  isJsonDecimalFidelityResponse,
  isDelimitedDataFidelityResponse,
  isXlsxDisplayFormatCsvResponse,
  isMathEvaluationResponse,
  isMarginMarkupResponse,
  isBreakEvenResponse,
  isSimpleInterestResponse,
  isDepreciationResponse,
  isPercentOfResponse,
  isPercentageChangeResponse,
  isDiscountResponse,
  isPasswordGeneratorResponse,
  isPassphraseGeneratorResponse,
  isColorConversionResponse,
  isLoanEmiResponse,
  isNetworkPingResponse,
  isDnsLookupResponse,
  isNetworkInterfacesResponse,
  isSystemResourceResponse,
  isRedactedSystemInfoResponse,
  isCompoundInterestResponse,
  isMeetingNotesResponse,
  isDictationCleanupResponse,
  isDuplicateWorkspaceReportResponse,
  isOfficeKitHealthResponse,
  isRelatedPdfSearchResponse,
  isLockedLicenseStatusResponse,
  isLicenseRequiredResponse,
  entitlementPushBody,
  isLicenseActivationUnavailableResponse,
  isPdfAttachmentResponse,
  isPdfSplitAttachmentResponse,
  isPdfSplitGroupsResponse,
  isPdfCompressionResponse,
  isPdfCompressionFidelityResponse,
  isPdfMetadataRemovedResponse,
  isPdfPageCountsResponse,
  isPdfPageOrderResponse,
  isPdfSplitPageOrderResponse,
  isPdfImageArchiveResponse,
  isIncompleteSimilarImageReportResponse,
  isImageMetadataAttachmentResponse,
  isScreenshotEditAttachmentResponse,
  isResizedImageAttachmentResponse,
  isResizedImagesArchiveResponse,
  isRenameArtifactResponse,
  isRenamePreviewResponse,
  isResultPptxAttachmentResponse,
  isResultPdfAttachmentResponse,
  isResultImageAttachmentResponse,
  isStatementPdfExtractionResponse,
  isPdfTableDateRowsResponse,
  isUnruledStatementPdfResponse,
  isWeakVectorStatementRecoveryResponse,
  isStatementUnverifiedResponse,
  isAmbiguousStatementUnverifiedResponse,
  isLocalizedStatementResponse,
  isInvalidStatementOptionResponse,
  isResultXlsxAttachmentResponse,
  isSimilarImageReportResponse,
  isSimilarImageHeicReportResponse,
  isFolderComparisonCsvResponse,
  isStorageWorkspaceReportResponse,
  isZipAttachmentResponse,
  isWorkspaceSplitResponse,
  isWorkspaceJoinResponse,
  createSidecarSmokeFetch,
  resolveSmokeBinary,
  findAvailableLoopbackPort,
  resolveSmokePort,
  sidecarAuth,
  SIDECAR_FIRST_LAUNCH_TIMEOUT_MS,
  smokeSidecar,
  LOCKED_PROBE_PATH,
  FREE_PROBE_PATH,
} from '../scripts/smoke-backend-sidecar.mjs';

// Parse a route table (a Python frozenset or dict literal) out of engine_license_gate.py.
function readGateTable(name) {
  const source = fs.readFileSync('officekit/engines/engine_license_gate.py', 'utf8');
  const start = source.indexOf(`\n${name}`);
  assert.notEqual(start, -1, `${name} not found in engine_license_gate.py`);
  const end = source.indexOf('\n}', start);
  return [...source.slice(start, end).matchAll(/\("([A-Z]+)", "([^"]+)"\)/g)]
    .map(([, method, template]) => ({ method, template }));
}

function tableHas(table, method, requestPath) {
  return table.some((route) => route.method === method
    && new RegExp(`^${route.template.replace(/\{[^/]+\}/g, '[^/]+')}$`).test(requestPath));
}

test('the locked-gate smoke probes a gated route and a free route, never an exempt or free one as "locked"', () => {
  const free = readGateTable('FREE_ROUTES');
  const exempt = readGateTable('GATE_EXEMPT_ROUTES');
  const gated = readGateTable('ROUTE_FEATURES');
  assert.ok(free.length > 10 && exempt.length === 10 && gated.length > 100, 'tables must parse');
  assert.equal(tableHas(free, 'GET', LOCKED_PROBE_PATH), false, 'locked probe is a free route');
  assert.equal(tableHas(exempt, 'GET', LOCKED_PROBE_PATH), false, 'locked probe is an exempt route');
  assert.equal(tableHas(gated, 'GET', LOCKED_PROBE_PATH), true, 'locked probe is not a gated route');
  assert.equal(tableHas(free, 'GET', FREE_PROBE_PATH), true, 'free probe is not a free route');
  assert.equal(tableHas(gated, 'GET', FREE_PROBE_PATH), false);
  // The retired probe (QA-1) must be detected as free, proving the check can fail.
  assert.equal(tableHas(free, 'GET', '/api/units/catalog'), true);
  assert.equal(tableHas(free, 'GET', '/api/clipboard/history'), false);
});

test('sidecar readiness requires an HTTP success and the exact versioned OfficeKit identity', () => {
  const expected = JSON.parse(fs.readFileSync('src-tauri/tauri.conf.json', 'utf8')).version;
  assert.equal(isOfficeKitHealthResponse(200, { status: 'ok', service: 'officekit-api', version: expected }, expected), true);
  assert.equal(isOfficeKitHealthResponse(503, { status: 'ok', service: 'officekit-api', version: expected }, expected), false);
  assert.equal(isOfficeKitHealthResponse(200, { status: 'ok', service: 'another-api', version: expected }, expected), false);
  assert.equal(isOfficeKitHealthResponse(200, { status: 'ok', service: 'officekit-api' }, expected), false);
  assert.equal(isOfficeKitHealthResponse(200, { status: 'ok', service: 'officekit-api', version: '0.9.0' }, expected), false);
  assert.equal(isOfficeKitHealthResponse(200, { status: 'ok', service: 'officekit-api', version: expected }), false);
});

test('sidecar smoke request failures identify only the method and local API route', async () => {
  const request = createSidecarSmokeFetch(async () => { throw new Error('The operation was aborted due to timeout'); });
  await assert.rejects(
    request('http://127.0.0.1:8000/api/system/metrics', { method: 'post' }),
    /Sidecar smoke request POST \/api\/system\/metrics failed: The operation was aborted due to timeout/,
  );
  assert.throws(() => createSidecarSmokeFetch(null), /fetch function is required/);
});

test('packaged search includes spreadsheet and image destinations for PDF to queries', () => {
  const tools = [
    { id: 'bank_statement', name: 'Bank statement PDF to CSV / XLS / XLSX', category: 'PDF & Documents', desc: 'Extract supported bank statements to CSV, XLS or XLSX.' },
    { id: 'pdf_to_images', name: 'PDF pages to PNG / JPEG', category: 'PDF & Documents', desc: 'Render PDF pages to PNG or JPEG.' },
    { id: 'pdf_merge', name: 'Merge PDFs', category: 'PDF & Documents', desc: 'Combine PDFs.' },
    { id: 'pdf_split', name: 'Split PDF pages', category: 'PDF & Documents', desc: 'Extract pages.' },
    { id: 'pdf_compress', name: 'Compress PDF', category: 'PDF & Documents', desc: 'Recompress PDF.' },
    { id: 'pdf_unlock', name: 'Unlock PDF', category: 'PDF & Documents', desc: 'Unlock a known-password PDF.' },
    { id: 'pdf_protect', name: 'Protect PDF', category: 'PDF & Documents', desc: 'Protect a PDF.' },
    { id: 'pdf_metadata_strip', name: 'Remove PDF metadata', category: 'PDF & Documents', desc: 'Remove metadata.' },
  ];
  assert.equal(isRelatedPdfSearchResponse(200, { tools }), true);
  assert.match(tools[0].desc, /CSV, XLS or XLSX/);
  assert.equal(isRelatedPdfSearchResponse(503, { tools }), false);
  assert.equal(isRelatedPdfSearchResponse(200, { tools: tools.slice(1) }), false);
  assert.equal(isRelatedPdfSearchResponse(200, { tools: tools.filter(tool => tool.id !== 'pdf_to_images') }), false);
  assert.equal(isRelatedPdfSearchResponse(200, { tools: tools.map(tool => tool.id === 'bank_statement' ? { ...tool, desc: 'Convert every PDF table into a spreadsheet.' } : tool) }), false);
});

test('sidecar smoke requires a locked licence status and a license_required gate before an entitlement is pushed', () => {
  const status = { activated: false, edition: null, features: [], valid_until_epoch: null };
  assert.equal(isLockedLicenseStatusResponse(200, status), true);
  assert.equal(isLockedLicenseStatusResponse(200, { ...status, activated: true }), false);
  assert.equal(isLockedLicenseStatusResponse(200, { ...status, edition: 'paid' }), false);
  assert.equal(isLockedLicenseStatusResponse(200, { ...status, features: ['a'] }), false);
  assert.equal(isLockedLicenseStatusResponse(200, { ...status, valid_until_epoch: 5 }), false);
  assert.equal(isLockedLicenseStatusResponse(401, status), false);
  assert.equal(isLicenseRequiredResponse(403, { error: { code: 'license_required' } }), true);
  assert.equal(isLicenseRequiredResponse(403, { error: { code: 'feature_not_licensed' } }), false);
  assert.equal(isLicenseRequiredResponse(200, { error: { code: 'license_required' } }), false);
  assert.deepEqual(JSON.parse(entitlementPushBody()), {
    activation_id: 'sidecarSmokeActivation',
    edition: 'paid',
    features: [],
    valid_for_seconds: 3600,
  });
  assert.equal(JSON.parse(entitlementPushBody()).activation_id.length, 22);
  assert.equal(isLicenseActivationUnavailableResponse(501, {
    detail: 'Online activation is not available in this build.',
  }), true);
  assert.equal(isLicenseActivationUnavailableResponse(200, { valid: true }), false);
  assert.equal(isLicenseActivationUnavailableResponse(501, { detail: 'failed' }), false);
});

test('packaged PDF table acceptance requires separate date rows and rejects collapsed transaction dates', () => {
  const preview = {
    page_count: 1,
    tables: [{
      page_number: 1,
      table_number: 1,
      row_count: 3,
      column_count: 2,
      preview_rows: [
        ['Date', 'Description'],
        ['21/09/26', 'Opening balance'],
        ['25/09/26', 'NEFT payment'],
      ],
    }],
  };
  assert.equal(isPdfTableDateRowsResponse(200, preview), true);
  assert.equal(isPdfTableDateRowsResponse(422, preview), false);
  assert.equal(isPdfTableDateRowsResponse(200, { ...preview, tables: [] }), false);
  assert.equal(isPdfTableDateRowsResponse(200, {
    ...preview,
    tables: [{ ...preview.tables[0], preview_rows: [
      ['Date', 'Description'],
      ['21/09/26 25/09/26', 'Merged rows'],
    ] }],
  }), false);
  assert.equal(isPdfTableDateRowsResponse(200, {
    ...preview,
    tables: [{ ...preview.tables[0], preview_rows: [['Description'], ['No date column']] }],
  }), false);
});

test('sidecar smoke check verifies a real CSV-to-JSON tool result', () => {
  assert.equal(isCsvJsonConversionResponse(200, [{ name: 'Ada', amount: 3.5 }]), true);
  assert.equal(isCsvJsonConversionResponse(422, [{ name: 'Ada', amount: 3.5 }]), false);
  assert.equal(isCsvJsonConversionResponse(200, []), false);
  assert.equal(isCsvJsonConversionResponse(200, [{ name: 'Ada', amount: '3.5' }]), false);
});

test('packaged data-converter smoke round-trips nested JSON through CSV and XLSX', () => {
  const smokeScript = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeScript, /async function smokeNestedTabularConversion\(fetchImpl, headers\)/);
  assert.match(smokeScript, /items: \[1, \{ sku: 'A-1' \}\]/);
  assert.match(smokeScript, /await smokeNestedTabularConversion\(fetchImpl, auth\.headers\)/);
  assert.match(smokeScript, /metadata\?\.active !== true/);
});

test('packaged YAML conversion requires typed JSON output', () => {
  const result = '{\n  "active": true,\n  "count": 2,\n  "name": "OfficeKit"\n}';
  assert.equal(isYamlToJsonResponse(200, { result }), true);
  assert.equal(isYamlToJsonResponse(422, { result }), false);
  assert.equal(isYamlToJsonResponse(200, { result: result.replace('true', '"true"') }), false);
  assert.equal(isYamlToJsonResponse(200, { result, extra: true }), false);
  assert.equal(isYamlToJsonResponse(200, null), false);
});

test('packaged tabular YAML smoke rejects ambiguous input and checks exact JSON decimals', () => {
  const smokeScript = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeScript, /async function smokeStrictYamlFileImport\(fetchImpl, headers\)/);
  assert.match(smokeScript, /duplicate-keys\.yaml/);
  assert.match(smokeScript, /alias\.yaml/);
  assert.match(smokeScript, /non-finite\.yaml/);
  assert.match(smokeScript, /0\.123456789012345678901234567890/);
  assert.match(smokeScript, /await smokeStrictYamlFileImport\(fetchImpl, auth\.headers\)/);
});

test('packaged XLSX import smoke checks displayed identifiers, ISO dates and worksheet bounds', () => {
  const smokeScript = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeScript, /async function smokeBoundedXlsxFileImport\(fetchImpl, headers\)/);
  assert.match(smokeScript, /formatted-values\.xlsx/);
  assert.match(smokeScript, /oversized-dimension\.xlsx/);
  assert.match(smokeScript, /account !== '001234'/);
  assert.match(smokeScript, /posted_at !== '2026-10-07T00:00:00'/);
  assert.match(smokeScript, /await smokeBoundedXlsxFileImport\(fetchImpl, auth\.headers\)/);
});

test('packaged JSON formatter smoke requires exact decimal and exponent text', () => {
  const result = '{\n  "large": 1E+999,\n  "precise": 0.12345678901234567890123456789,\n  "small": 1E-9999\n}';
  assert.equal(isJsonDecimalFidelityResponse(200, { result }), true);
  assert.equal(isJsonDecimalFidelityResponse(422, { result }), false);
  assert.equal(isJsonDecimalFidelityResponse(200, { result: result.replace('1E+999', 'Infinity') }), false);
  assert.equal(isJsonDecimalFidelityResponse(200, { result, extra: true }), false);
  assert.equal(isJsonDecimalFidelityResponse(200, null), false);
});

test('packaged CSV conversion preserves identifiers, exact numeric limits and date-like strings', () => {
  const payload = [
    { reference: '00001', amount: 0.125, max_safe: 999999999999999, precise: '1234567890123456789', date: '2026-10-07' },
    { reference: '00002', amount: 0, max_safe: 999999999999998, precise: '1234567890123456790', date: '01/02/2026' },
  ];
  const body = Buffer.from(JSON.stringify(payload));
  const disposition = "attachment; filename=\"accounts.json\"; filename*=UTF-8''accounts.json";
  assert.equal(isDelimitedDataFidelityResponse(200, 'application/json', disposition, body), true);
  assert.equal(isDelimitedDataFidelityResponse(422, 'application/json', disposition, body), false);
  assert.equal(isDelimitedDataFidelityResponse(200, 'application/json', 'attachment; filename="other.json"', body), false);
  assert.equal(isDelimitedDataFidelityResponse(200, 'application/json', disposition, Buffer.from('[]')), false);
});

test('sidecar smoke check verifies a typed color-conversion result', () => {
  const result = { value: 'rgb(255, 0, 0)', source_format: 'hex', target_format: 'rgb' };
  assert.equal(isColorConversionResponse(200, result), true);
  assert.equal(isColorConversionResponse(422, result), false);
  assert.equal(isColorConversionResponse(200, { ...result, value: '#ff0000' }), false);
  assert.equal(isColorConversionResponse(200, null), false);
});

test('password generation smoke validates bounded response shape and class constraints', () => {
  const withSymbols = { password: 'Ab3!Cd4@Ef5#Gh6$Ij7&', theoretical_search_space_bits: 121.5 };
  assert.equal(isPasswordGeneratorResponse(200, withSymbols, 20, true), true);
  assert.equal(isPasswordGeneratorResponse(200, {
    ...withSymbols, password: 'Ab3Cd4Ef5Gh6Ij7Kl8Mn',
  }, 20, false), true);
  assert.equal(isPasswordGeneratorResponse(200, { ...withSymbols, password: 'ab3!cd4@ef5#gh6$ij7&' }, 20, true), false);
  assert.equal(isPasswordGeneratorResponse(200, { ...withSymbols, password: 'Ab3!Cd4@Ef5#Gh6$Ij7&extra' }, 20, true), false);
  assert.equal(isPasswordGeneratorResponse(200, { ...withSymbols, theoretical_search_space_bits: Infinity }, 20, true), false);
  assert.equal(isPasswordGeneratorResponse(200, { ...withSymbols, extra: 'secret' }, 20, true), false);
  assert.equal(isPasswordGeneratorResponse(500, withSymbols, 20, true), false);
  assert.equal(isPasswordGeneratorResponse(200, null, 20, true), false);
});

test('packaged workspace smoke distinguishes ISO media brands and cleans its temporary fixture workspace', () => {
  const smokeScript = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeScript, /const isoFtyp = \(brand, compatible = \[\]\) =>/);
  for (const value of ['photo.heif', 'photo.avif', 'clip.mov', 'audio.m4a', 'clip.mp4']) {
    assert.ok(smokeScript.includes(value), `expected packaged media-type fixture ${value}`);
  }
  for (const value of ['HEIC image', 'AVIF image', 'QuickTime video', 'M4A audio', 'MP4 media']) {
    assert.ok(smokeScript.includes(value), `expected packaged media type ${value}`);
  }
  assert.match(smokeScript, /\[workspaceId, splitWorkspaceId, isoMediaWorkspaceId\]/);
});

test('sidecar smoke check verifies the loan EMI and reconciled cent schedule', () => {
  let balance = 100000;
  let totalInterest = 0;
  let totalPayment = 0;
  const schedule = Array.from({ length: 60 }, (_, index) => {
    const interestPaid = Math.round(balance * 0.10 / 12 * 100) / 100;
    const principalPaid = index === 59 ? balance : Math.min(2124.7 - interestPaid, balance);
    const payment = Math.round((principalPaid + interestPaid) * 100) / 100;
    balance = Math.round((balance - principalPaid) * 100) / 100;
    totalInterest = Math.round((totalInterest + interestPaid) * 100) / 100;
    totalPayment = Math.round((totalPayment + payment) * 100) / 100;
    return {
      month: index + 1,
      payment,
      principal_paid: principalPaid,
      interest_paid: interestPaid,
      remaining_balance: balance,
    };
  });
  const result = {
    tenure_months: 60,
    monthly_emi: 2124.7,
    total_payment: totalPayment,
    total_interest: totalInterest,
    schedule,
  };
  assert.equal(isLoanEmiResponse(200, result), true);
  assert.equal(isLoanEmiResponse(422, result), false);
  assert.equal(isLoanEmiResponse(200, { ...result, schedule: schedule.slice(0, 59) }), false);
  assert.equal(isLoanEmiResponse(200, {
    ...result,
    schedule: schedule.map((row, index) => index === 10 ? { ...row, month: 99 } : row),
  }), false);
  assert.equal(isLoanEmiResponse(200, { ...result, total_payment: 1 }), false);
});

test('sidecar smoke check validates PDF attachments and rendered image archives', () => {
  assert.equal(isPdfAttachmentResponse(200, 'application/pdf', Buffer.from('%PDF-1.7')), true);
  assert.equal(isPdfAttachmentResponse(422, 'application/pdf', Buffer.from('%PDF-1.7')), false);
  assert.equal(isPdfAttachmentResponse(200, 'text/plain', Buffer.from('%PDF-1.7')), false);
  assert.equal(isPdfAttachmentResponse(200, 'application/pdf', Buffer.from('not a PDF')), false);
  assert.equal(isPdfImageArchiveResponse(200, '1', Buffer.from('PK\x03\x04')), true);
  assert.equal(isPdfImageArchiveResponse(200, '2', Buffer.from('PK\x03\x04'), 2), true);
  assert.equal(isPdfImageArchiveResponse(200, '1', Buffer.from('PK\x03\x04'), 2), false);
  assert.equal(isPdfImageArchiveResponse(200, '2', Buffer.from('PK\x03\x04')), false);
  assert.equal(isPdfImageArchiveResponse(422, '1', Buffer.from('PK\x03\x04')), false);
  assert.equal(isPdfImageArchiveResponse(200, '1', Buffer.from('not a ZIP')), false);
});

test('sidecar smoke requires a bounded successful PDF split attachment', () => {
  const valid = Buffer.concat([Buffer.from('%PDF-1.7\n'), Buffer.alloc(256)]);
  assert.equal(isPdfSplitAttachmentResponse(200, 'application/pdf', valid), true);
  assert.equal(isPdfSplitAttachmentResponse(200, 'text/html', valid), false);
  assert.equal(isPdfSplitAttachmentResponse(422, 'application/pdf', valid), false);
  assert.equal(isPdfSplitAttachmentResponse(200, 'application/pdf', Buffer.from('%PDF-')), false);
});

test('packaged grouped-PDF smoke requires exactly the named valid PDF entries in order', () => {
  const names = ['cover.pdf', 'appendix.pdf'];
  const archive = makeDeflatedZip([
    ['cover.pdf', Buffer.from('%PDF-1.7\ncover')],
    ['appendix.pdf', Buffer.from('%PDF-1.7\nappendix')],
  ]);
  assert.equal(isPdfSplitGroupsResponse(200, 'application/zip', archive, names), true);
  assert.equal(isPdfSplitGroupsResponse(200, 'application/zip', archive, [...names].reverse()), false);
  assert.equal(isPdfSplitGroupsResponse(200, 'application/zip', archive, [...names, 'extra.pdf']), false);
  assert.equal(isPdfSplitGroupsResponse(200, 'application/pdf', archive, names), false);
  const wrongEntry = makeDeflatedZip([
    ['cover.pdf', Buffer.from('%PDF-1.7\ncover')],
    ['appendix.pdf', Buffer.from('not a PDF')],
  ]);
  assert.equal(isPdfSplitGroupsResponse(200, 'application/zip', wrongEntry, names), false);
});

test('packaged PDF compression validation requires its exact measured ratio and a valid output', () => {
  const bytes = Buffer.from('%PDF-1.7');
  assert.equal(isPdfCompressionResponse(200, 'application/pdf', '0.80000000', bytes, 10), true);
  assert.equal(isPdfCompressionResponse(200, 'application/pdf', '1.25000000', bytes, 10), false);
  assert.equal(isPdfCompressionResponse(200, 'application/pdf', '0.8', bytes, 10), false);
  assert.equal(isPdfCompressionResponse(200, 'application/pdf', '0.80000000', Buffer.from('bad'), 10), false);
  assert.equal(isPdfCompressionResponse(413, 'application/pdf', '0.80000000', bytes, 10), false);
  assert.equal(isPdfCompressionResponse(200, 'text/plain', '0.80000000', bytes, 10), false);
});

test('packaged PDF compression fidelity rejects changed rendered pixels despite matching dimensions', () => {
  const sourcePng = makePngDimensionsFixture(144, 144);
  const sourceArchive = makeDeflatedZip([['page-001.png', sourcePng]]);
  const changedPng = Buffer.concat([sourcePng, Buffer.from([1])]);
  const changedArchive = makeDeflatedZip([['page-001.png', changedPng]]);
  const dimensions = [[144, 144]];

  assert.equal(isPdfCompressionFidelityResponse(200, '1', sourceArchive, [sourcePng], dimensions), true);
  assert.equal(isPdfCompressionFidelityResponse(200, '1', changedArchive, [sourcePng], dimensions), false);
  assert.equal(isPdfCompressionFidelityResponse(500, '1', sourceArchive, [sourcePng], dimensions), false);
  assert.equal(isPdfCompressionFidelityResponse(200, '2', sourceArchive, [sourcePng], dimensions), false);
});

test('packaged PDF metadata-removal validation rejects retained info and XMP markers', () => {
  const cleanPdf = Buffer.from('%PDF-1.7\nclean copy');
  const markedPdf = Buffer.from('%PDF-1.7\nOfficeKitInfoMarker OfficeKitXmpMarker');
  const markers = ['OfficeKitInfoMarker', 'OfficeKitXmpMarker'];
  assert.equal(isPdfMetadataRemovedResponse(200, 'application/pdf', cleanPdf, markers), true);
  assert.equal(isPdfMetadataRemovedResponse(200, 'application/pdf', markedPdf, markers), false);
  assert.equal(isPdfMetadataRemovedResponse(422, 'application/pdf', cleanPdf, markers), false);
  assert.equal(isPdfMetadataRemovedResponse(200, 'text/plain', cleanPdf, markers), false);
  assert.equal(isPdfMetadataRemovedResponse(200, 'application/pdf', cleanPdf, []), false);
});

function zipCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function makePngDimensionsFixture(width, height) {
  const bytes = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes, 0);
  bytes.write('IHDR', 12, 'ascii');
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return bytes;
}

function makeDeflatedZip(files) {
  const localRecords = [];
  const centralRecords = [];
  let localOffset = 0;
  for (const [name, contents] of files) {
    const nameBytes = Buffer.from(name, 'utf8');
    const compressed = deflateRawSync(contents);
    const crc = zipCrc32(contents);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(8, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(contents.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    localRecords.push(local, nameBytes, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(8, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(contents.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(localOffset, 42);
    centralRecords.push(central, nameBytes);
    localOffset += local.length + nameBytes.length + compressed.length;
  }
  const centralBytes = Buffer.concat(centralRecords);
  const ending = Buffer.alloc(22);
  ending.writeUInt32LE(0x06054b50, 0);
  ending.writeUInt16LE(files.length, 8);
  ending.writeUInt16LE(files.length, 10);
  ending.writeUInt32LE(centralBytes.length, 12);
  ending.writeUInt32LE(localOffset, 16);
  return Buffer.concat([...localRecords, centralBytes, ending]);
}

test('packaged split verification checks requested page order from rendered page dimensions', () => {
  const archive = makeDeflatedZip([
    ['page-001.png', makePngDimensionsFixture(74, 74)],
    ['page-002.png', makePngDimensionsFixture(72, 72)],
  ]);
  assert.equal(isPdfSplitPageOrderResponse(200, '2', archive, [[74, 74], [72, 72]]), true);
  assert.equal(isPdfSplitPageOrderResponse(200, '2', archive, [[72, 72], [74, 74]]), false);
  assert.equal(isPdfSplitPageOrderResponse(200, '1', archive, [[74, 74], [72, 72]]), false);
  assert.equal(isPdfSplitPageOrderResponse(200, '2', Buffer.from('invalid'), [[74, 74], [72, 72]]), false);
});

test('packaged merge verification checks page count and source order from rendered dimensions', () => {
  const archive = makeDeflatedZip([
    ['page-001.png', makePngDimensionsFixture(72, 72)],
    ['page-002.png', makePngDimensionsFixture(73, 73)],
    ['page-003.png', makePngDimensionsFixture(82, 82)],
  ]);
  assert.equal(isPdfPageOrderResponse(200, '3', archive, [[72, 72], [73, 73], [82, 82]]), true);
  assert.equal(isPdfPageOrderResponse(200, '2', archive, [[72, 72], [73, 73], [82, 82]]), false);
  assert.equal(isPdfPageOrderResponse(200, '3', archive, [[82, 82], [72, 72], [73, 73]]), false);
  assert.equal(isPdfPageOrderResponse(500, '3', archive, [[72, 72], [73, 73], [82, 82]]), false);
});

test('packaged PDF page-management smoke verifies deleted and reordered pages by rendering', () => {
  const smokeSource = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeSource, /path: '\/api\/pdf\/pages\/delete'[\s\S]*?field: 'page_ranges'[\s\S]*?selection: '2'[\s\S]*?dimensions: \[\[72, 72\], \[74, 74\]\]/);
  assert.match(smokeSource, /path: '\/api\/pdf\/pages\/reorder'[\s\S]*?field: 'page_order'[\s\S]*?selection: '3,1,2'[\s\S]*?dimensions: \[\[74, 74\], \[72, 72\], \[73, 73\]\]/);
  assert.match(smokeSource, /OfficeKit sidecar \$\{operation\.path\} rendered-page fidelity smoke failed/);
});

test('packaged PDF page-count validation requires ordered counts, totals, and a path-free DTO', () => {
  const valid = {
    files: [
      { index: 0, page_count: 2, status: 'ready' },
      { index: 1, page_count: 1, status: 'ready' },
    ],
    total_pages: 3,
    ready_count: 2,
    unreadable_count: 0,
  };
  assert.equal(isPdfPageCountsResponse(200, valid, [2, 1]), true);
  assert.equal(isPdfPageCountsResponse(200, { ...valid, total_pages: 4 }, [2, 1]), false);
  assert.equal(isPdfPageCountsResponse(200, { ...valid, files: [...valid.files].reverse() }, [2, 1]), false);
  assert.equal(isPdfPageCountsResponse(200, {
    ...valid,
    files: [{ ...valid.files[0], filename: '/Users/secret.pdf' }, valid.files[1]],
  }, [2, 1]), false);
  assert.equal(isPdfPageCountsResponse(200, { ...valid, debug: 'parser details' }, [2, 1]), false);
  assert.equal(isPdfPageCountsResponse(422, valid, [2, 1]), false);
});

test('sidecar smoke check validates the image metadata-removal attachment contract', () => {
  const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 0]);
  assert.equal(isImageMetadataAttachmentResponse(
    200, 'image/png', 'attachment; filename="smoke_metadata_removed.png"', png,
  ), true);
  assert.equal(isImageMetadataAttachmentResponse(
    422, 'image/png', 'attachment; filename="smoke_metadata_removed.png"', png,
  ), false);
  assert.equal(isImageMetadataAttachmentResponse(
    200, 'text/plain', 'attachment; filename="smoke_metadata_removed.png"', png,
  ), false);
  assert.equal(isImageMetadataAttachmentResponse(
    200, 'image/png', 'attachment; filename="smoke_metadata_removed.png"', Buffer.from('not png'),
  ), false);
});

test('sidecar smoke check validates bounded image-resize attachment dimensions and bytes', () => {
  const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 0]);
  assert.equal(isResizedImageAttachmentResponse(
    200, 'image/png', 'attachment; filename="resize_smoke_resized.png"', '1', '1', png,
  ), true);
  assert.equal(isResizedImageAttachmentResponse(
    413, 'image/png', 'attachment; filename="resize_smoke_resized.png"', '1', '1', png,
  ), false);
  assert.equal(isResizedImageAttachmentResponse(
    200, 'image/jpeg', 'attachment; filename="resize_smoke_resized.png"', '1', '1', png,
  ), false);
  assert.equal(isResizedImageAttachmentResponse(
    200, 'image/png', 'attachment; filename="wrong.png"', '1', '1', png,
  ), false);
  assert.equal(isResizedImageAttachmentResponse(
    200, 'image/png', 'attachment; filename="resize_smoke_resized.png"', '2', '1', png,
  ), false);
});

test('sidecar smoke check validates screenshot editor PNG and JPEG attachment metadata and bytes', () => {
  const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 0]);
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0x00, 0xff, 0xd9]);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/png', 'attachment; filename="screenshot-edited.png"', png,
  ), true);
  assert.equal(isScreenshotEditAttachmentResponse(
    413, 'image/png', 'attachment; filename="screenshot-edited.png"', png,
  ), false);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/jpeg', 'attachment; filename="screenshot-edited.png"', png,
  ), false);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/png', 'attachment; filename="other.png"', png,
  ), false);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/png', 'attachment; filename="screenshot-edited.png"', Buffer.from('bad'),
  ), false);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/jpeg', 'attachment; filename="screenshot-edited.jpg"', jpeg, 'jpeg',
  ), true);
  assert.equal(isScreenshotEditAttachmentResponse(
    200, 'image/jpeg', 'attachment; filename="screenshot-edited.jpg"', png, 'jpeg',
  ), false);
});

test('sidecar smoke check validates bounded batch image ZIP metadata and bytes', () => {
  const zip = Buffer.from([0x50, 0x4b, 0x03, 0x04, 0]);
  assert.equal(isResizedImagesArchiveResponse(
    200, 'application/zip', 'attachment; filename="resized_images.zip"', zip,
  ), true);
  assert.equal(isResizedImagesArchiveResponse(
    413, 'application/zip', 'attachment; filename="resized_images.zip"', zip,
  ), false);
  assert.equal(isResizedImagesArchiveResponse(
    200, 'application/json', 'attachment; filename="resized_images.zip"', zip,
  ), false);
  assert.equal(isResizedImagesArchiveResponse(
    200, 'application/zip', 'attachment; filename="wrong.zip"', zip,
  ), false);
  assert.equal(isResizedImagesArchiveResponse(
    200, 'application/zip', 'attachment; filename="resized_images.zip"', Buffer.from('bad'),
  ), false);
});

test('sidecar smoke check validates structured result XLSX attachment metadata and bytes', () => {
  const mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  const bytes = Buffer.from('PK\x03\x04');
  assert.equal(isResultXlsxAttachmentResponse(200, mime, 'attachment; filename="loan_emi-result.xlsx"', bytes), true);
  assert.equal(isResultXlsxAttachmentResponse(422, mime, 'attachment; filename="loan_emi-result.xlsx"', bytes), false);
  assert.equal(isResultXlsxAttachmentResponse(200, 'application/zip', 'attachment; filename="loan_emi-result.xlsx"', bytes), false);
  assert.equal(isResultXlsxAttachmentResponse(200, mime, 'attachment; filename="other.xlsx"', bytes), false);
  assert.equal(isResultXlsxAttachmentResponse(200, mime, 'attachment; filename="loan_emi-result.xlsx"', Buffer.from('bad')), false);
});

test('sidecar smoke check validates structured result PPTX attachment metadata and bytes', () => {
  const mime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
  const bytes = Buffer.from('PK\x03\x04');
  assert.equal(isResultPptxAttachmentResponse(200, mime, 'attachment; filename="loan_emi-result.pptx"', bytes), true);
  assert.equal(isResultPptxAttachmentResponse(422, mime, 'attachment; filename="loan_emi-result.pptx"', bytes), false);
  assert.equal(isResultPptxAttachmentResponse(200, 'application/zip', 'attachment; filename="loan_emi-result.pptx"', bytes), false);
  assert.equal(isResultPptxAttachmentResponse(200, mime, 'attachment; filename="other.pptx"', bytes), false);
  assert.equal(isResultPptxAttachmentResponse(200, mime, 'attachment; filename="loan_emi-result.pptx"', Buffer.from('bad')), false);
});

test('sidecar smoke check validates structured result PDF attachment metadata and bytes', () => {
  const bytes = Buffer.from('%PDF-1.7\n');
  assert.equal(isResultPdfAttachmentResponse(200, 'application/pdf', 'attachment; filename="loan_emi-result.pdf"', bytes), true);
  assert.equal(isResultPdfAttachmentResponse(422, 'application/pdf', 'attachment; filename="loan_emi-result.pdf"', bytes), false);
  assert.equal(isResultPdfAttachmentResponse(200, 'application/octet-stream', 'attachment; filename="loan_emi-result.pdf"', bytes), false);
  assert.equal(isResultPdfAttachmentResponse(200, 'application/pdf', 'attachment; filename="other.pdf"', bytes), false);
  assert.equal(isResultPdfAttachmentResponse(200, 'application/pdf', 'attachment; filename="loan_emi-result.pdf"', Buffer.from('bad')), false);
});

test('sidecar smoke check validates calculator result PNG and JPEG attachment metadata and signatures', () => {
  assert.equal(isResultImageAttachmentResponse(
    200, 'image/png', 'attachment; filename="loan_emi-result.png"',
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]), 'png',
  ), true);
  assert.equal(isResultImageAttachmentResponse(
    200, 'image/jpeg', 'attachment; filename="loan_emi-result.jpg"', Buffer.from([0xff, 0xd8, 0xff, 0x00]), 'jpeg',
  ), true);
  assert.equal(isResultImageAttachmentResponse(
    200, 'image/png', 'attachment; filename="loan_emi-result.png"', Buffer.from('bad'), 'png',
  ), false);
  assert.equal(isResultImageAttachmentResponse(
    200, 'image/gif', 'attachment; filename="loan_emi-result.gif"', Buffer.from('GIF89a'), 'gif',
  ), false);
});

test('sidecar smoke check validates scientific math values and their angle mode', () => {
  const expression = "sin(90) + asin(1)";
  const payload = { expression, result: 91, angle_mode: 'degrees' };
  assert.equal(isMathEvaluationResponse(200, payload, { expression, result: 91, angleMode: 'degrees' }), true);
  assert.equal(isMathEvaluationResponse(200, { ...payload, result: 90 }, { expression, result: 91, angleMode: 'degrees' }), false);
  assert.equal(isMathEvaluationResponse(200, { ...payload, angle_mode: 'radians' }, { expression, result: 91, angleMode: 'degrees' }), false);
  assert.equal(isMathEvaluationResponse(200, { ...payload, expression: 'sin(1)' }, { expression, result: 91, angleMode: 'degrees' }), false);
  assert.equal(isMathEvaluationResponse(422, payload, { expression, result: 91, angleMode: 'degrees' }), false);
});

test('packaged sidecar financial utility smokes require valid reconciled response DTOs', () => {
  const margin = { profit: 20, gross_margin_percent: 20, markup_percent: 25, cost: 80, revenue: 100, assumptions: { margin_denominator: 'revenue', markup_denominator: 'cost' } };
  assert.equal(isMarginMarkupResponse(200, margin), true);
  assert.equal(isMarginMarkupResponse(200, { ...margin, markup_percent: 24 }), false);
  assert.equal(isMarginMarkupResponse(200, { ...margin, assumptions: { margin_denominator: 'cost', markup_denominator: 'revenue' } }), false);
  const negativeHalfCentMargin = { ...margin, profit: -0.13, gross_margin_percent: -11.11, markup_percent: -10, cost: 1.25, revenue: 1.125 };
  assert.equal(isMarginMarkupResponse(200, negativeHalfCentMargin, {
    cost: 1.25, revenue: 1.125, profit: -0.13, gross_margin_percent: -11.11, markup_percent: -10,
  }), true);
  assert.equal(isMarginMarkupResponse(200, { ...negativeHalfCentMargin, profit: -0.12 }, {
    cost: 1.25, revenue: 1.125, profit: -0.13, gross_margin_percent: -11.11, markup_percent: -10,
  }), false);
  const breakEven = { break_even_units: 34, break_even_revenue: 1700, contribution_margin: 30 };
  assert.equal(isBreakEvenResponse(200, breakEven), true);
  assert.equal(isBreakEvenResponse(200, { ...breakEven, break_even_units: 33 }), false);
  assert.equal(isBreakEvenResponse(200, { ...breakEven, extra: true }), false);
  const interest = { principal: 1000, annual_rate_percent: 10, time_value: 18, time_unit: 'months', time_in_years: 1.5, interest_amount: 150, total_amount: 1150, assumptions: { method: 'simple_interest', rate_basis: 'nominal_annual', currency_precision: '0.01', rounding: 'half_up', compounding: 'none' } };
  assert.equal(isSimpleInterestResponse(200, interest), true);
  assert.equal(isSimpleInterestResponse(200, { ...interest, time_in_years: 18 }), false);
  assert.equal(isSimpleInterestResponse(200, { ...interest, assumptions: { ...interest.assumptions, compounding: 'monthly' } }), false);
  const depreciation = { annual_depreciation: 3000, total_depreciable: 9000, schedule: [{ year: 1, depreciation: 3000, book_value: 7000 }, { year: 2, depreciation: 3000, book_value: 4000 }, { year: 3, depreciation: 3000, book_value: 1000 }], assumptions: { method: 'straight_line', currency_precision: '0.01', rounding: 'half_up', final_period: 'adjusted_to_salvage_value' } };
  assert.equal(isDepreciationResponse(200, depreciation), true);
  assert.equal(isDepreciationResponse(200, { ...depreciation, schedule: depreciation.schedule.slice(0, 2) }), false);
  assert.equal(isDepreciationResponse(200, { ...depreciation, schedule: depreciation.schedule.map((row, index) => index === 2 ? { ...row, book_value: 1010 } : row) }), false);
  assert.equal(isDepreciationResponse(422, depreciation), false);
});

test('packaged sidecar percentage smokes validate exact outputs and declared assumptions', () => {
  const assumptions = { rounding: 'half_up', precision: '0.01', currency: 'not_inferred', taxes: 'excluded' };
  const percent = { percent: 15, value: 240, result: 36, assumptions };
  assert.equal(isPercentOfResponse(200, percent), true);
  assert.equal(isPercentOfResponse(200, { ...percent, result: 37 }), false);
  assert.equal(isPercentOfResponse(200, { ...percent, extra: true }), false);

  const change = { original_value: 80, new_value: 100, change_value: 20, change_percent: 25, direction: 'increase', assumptions };
  assert.equal(isPercentageChangeResponse(200, change), true);
  assert.equal(isPercentageChangeResponse(200, { ...change, direction: 'decrease' }), false);
  assert.equal(isPercentageChangeResponse(200, { ...change, assumptions: { ...assumptions, currency: 'USD' } }), false);
  assert.equal(isPercentageChangeResponse(200, change, { original_value: 0, new_value: 1 }), false);

  const discount = { price: 100, discount_percent: 20, savings: 20, discounted_price: 80, assumptions };
  assert.equal(isDiscountResponse(200, discount), true);
  assert.equal(isDiscountResponse(200, { ...discount, discounted_price: 79 }), false);
  assert.equal(isDiscountResponse(422, discount), false);
});

test('sidecar smoke check validates actual network ping measurements and explicit permission denial', () => {
  const reachable = {
    target: '127.0.0.1', status: 'reachable', packets_sent: 1,
    packets_received: 1, packet_loss_percent: 0,
    latency_ms: { min: 0.1, avg: 0.2, max: 0.3 },
  };
  assert.equal(isNetworkPingResponse(200, reachable, '127.0.0.1'), true);
  assert.equal(isNetworkPingResponse(200, {
    target: '127.0.0.1', status: 'permission_denied', packets_sent: null,
    packets_received: null, packet_loss_percent: null, latency_ms: null,
  }, '127.0.0.1'), true);
  assert.equal(isNetworkPingResponse(200, { ...reachable, status: 'incomplete' }, '127.0.0.1'), false);
  assert.equal(isNetworkPingResponse(200, { ...reachable, target: 'example.com' }, '127.0.0.1'), false);
  assert.equal(isNetworkPingResponse(500, reachable, '127.0.0.1'), false);
});

test('sidecar smoke check validates typed DNS A and MX answers and rejects malformed results', () => {
  const address = {
    hostname: 'example.com', record_type: 'A', status: 'success', records: ['192.0.2.10'],
    truncated: false, nameserver: null, duration_ms: 4,
  };
  assert.equal(isDnsLookupResponse(200, address, 'example.com', 'A'), true);
  assert.equal(isDnsLookupResponse(200, {
    ...address, record_type: 'MX', records: [{ preference: 10, exchange: 'mail.example.com' }],
  }, 'example.com', 'MX'), true);
  assert.equal(isDnsLookupResponse(200, { ...address, records: [] }, 'example.com', 'A'), false);
  assert.equal(isDnsLookupResponse(200, { ...address, records: Array(101).fill('192.0.2.10') }, 'example.com', 'A'), false);
  assert.equal(isDnsLookupResponse(503, address, 'example.com', 'A'), false);
});

test('sidecar smoke check requires the default network-interface response to hide IP addresses', () => {
  const payload = {
    include_addresses: false,
    privacy_notice: 'Local IP addresses are hidden. Include addresses only when you want to view them.',
    interfaces: [{
      name: 'en0', is_up: true, address_count: 2, addresses_hidden: true, addresses: [],
    }],
    truncated: false,
  };
  assert.equal(isNetworkInterfacesResponse(200, payload), true);
  const addressOptIn = {
    include_addresses: true,
    privacy_notice: 'Contains local IP addresses. Copy or export only the addresses you select.',
    interfaces: [{
      name: 'en0', is_up: true, address_count: 1, addresses_hidden: false,
      addresses: [{ family: 'IPv4', address: '192.168.1.2', netmask: '255.255.255.0', broadcast: '192.168.1.255' }],
    }],
    truncated: false,
  };
  assert.equal(isNetworkInterfacesResponse(200, addressOptIn, true), true);
  assert.equal(isNetworkInterfacesResponse(200, { ...addressOptIn, interfaces: [{ ...addressOptIn.interfaces[0], addresses: [{ ...addressOptIn.interfaces[0].addresses[0], mac: '00:11:22:33:44:55' }] }] }, true), false);
  assert.equal(isNetworkInterfacesResponse(200, {
    ...payload, interfaces: [{ ...payload.interfaces[0], addresses: [{ address: '192.168.1.2' }] }],
  }), false);
  assert.equal(isNetworkInterfacesResponse(500, payload), false);
});

test('sidecar smoke check validates measured and reconciled CPU/memory metrics', () => {
  const payload = {
    cpu_count: 8, cpu_percent: 12.5, cpu_sample_interval_seconds: 0.1,
    total_ram_gb: 8, available_ram_gb: 3,
    memory_total_bytes: 8 * 1024 ** 3, memory_available_bytes: 3 * 1024 ** 3,
    memory_used_estimate_bytes: 5 * 1024 ** 3, memory_percent: 62.5,
    optimal_workers: 6, cached: false, sample_age_ms: 0,
  };
  assert.equal(isSystemResourceResponse(200, payload), true);
  assert.equal(isSystemResourceResponse(200, { ...payload, cpu_percent: 101 }), false);
  assert.equal(isSystemResourceResponse(200, { ...payload, memory_used_estimate_bytes: 1 }), false);
  assert.equal(isSystemResourceResponse(503, payload), false);
});

test('sidecar smoke check validates the redacted macOS system-information report', () => {
  const payload = {
    os_name: 'macOS', os_version: '15.5.1', architecture: 'arm64',
    logical_cpu_count: 8, physical_cpu_count: 4, memory_total_bytes: 16 * 1024 ** 3,
    memory_total_gb: 16, privacy_notice: 'Device identifiers and host/account names are excluded.',
    report_text: 'Operating system: macOS 15.5.1\nArchitecture: arm64\nCPU cores: 4 physical, 8 logical\nMemory: 16 GB',
  };
  assert.equal(isRedactedSystemInfoResponse(200, payload), true);
  assert.equal(isRedactedSystemInfoResponse(200, { ...payload, hostname: 'private-host' }), false);
  assert.equal(isRedactedSystemInfoResponse(200, { ...payload, physical_cpu_count: 9 }), false);
  assert.equal(isRedactedSystemInfoResponse(501, payload), false);
});

test('sidecar smoke check validates compound interest schedule totals and assumptions', () => {
  const result = {
    future_value: 2384.99,
    total_invested: 2200,
    total_interest_earned: 184.99,
    growth_history: [{ year: 1, total_balance: 2384.99, total_invested: 2200, total_interest: 184.99 }],
    assumptions: {
      rate_basis: 'nominal_annual',
      monthly_accrual: 'equivalent_effective_monthly_rate',
      contribution_timing: 'end_of_month',
      fractional_month: 'interest_only',
    },
  };
  const expected = {
    future_value: 2384.99,
    total_invested: 2200,
    total_interest_earned: 184.99,
  };
  assert.equal(isCompoundInterestResponse(200, result, expected), true);
  assert.equal(isCompoundInterestResponse(200, { ...result, total_invested: 2100 }, expected), false);
  assert.equal(isCompoundInterestResponse(200, result, { ...expected, future_value: 2390 }), false);
  assert.equal(isCompoundInterestResponse(500, result, expected), false);
});

test('packaged meeting-notes result must preserve the expected heuristic classification and fenced input', () => {
  const expected = {
    transcript: 'The launch date is Friday. We decided that Sara will send the checklist. We will not publish the draft today.',
    summary: 'The launch date is Friday We will not publish the draft today',
    action_items: ['We decided that Sara will send the checklist'],
    decisions: ['We decided that Sara will send the checklist'],
  };
  const fence = '```';
  const result = {
    ...expected,
    word_count: expected.transcript.split(/\s+/).length,
    markdown: `# Meeting Notes\n\n## 🎙️ Full Transcript\n\n${fence}text\n${expected.transcript}\n${fence}`,
  };

  assert.equal(isMeetingNotesResponse(200, result, expected), true);
  assert.equal(isMeetingNotesResponse(200, { ...result, action_items: [] }, expected), false);
  assert.equal(isMeetingNotesResponse(200, { ...result, decisions: [] }, expected), false);
  assert.equal(isMeetingNotesResponse(200, { ...result, markdown: `${result.markdown} altered` }, expected), false);
  assert.equal(isMeetingNotesResponse(500, result, expected), false);
});

test('mounted sidecar smoke invokes the meeting-notes route through authenticated requests', () => {
  const source = fs.readFileSync(new URL('../scripts/smoke-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /api\/dictate\/format-notes/);
  assert.match(source, /await smokeMeetingNotes\(fetchImpl, auth\.headers\)/);
  assert.match(source, /There will be a design review next week\. There is no need to publish before legal sign-off/);
  assert.match(source, /The decision will be made after legal review\. A decision was not reached/);
  assert.match(source, /The team may have approved the revised price\. The team might have chosen the new supplier/);
  assert.match(source, /We will not ship today, but Sarah will publish the docs tomorrow/);
  assert.match(source, /We have not chosen a launch date, but we approved the privacy approach/);
  assert.match(source, /There is no decision on the launch until the review is complete/);
  assert.match(source, /The decision is still pending\. No final decision has been made\. No final decision on the launch/);
  assert.match(source, /Let's not publish before legal sign-off\. Let's not publish today, but Sarah will publish the docs tomorrow/);
  assert.match(source, /Let's not forget to send the invoice by Friday/);
  assert.match(source, /We need a decision on pricing by Friday\. The team must make a decision before launch\. Decision is required by Friday/);
  assert.match(source, /We decided the launch date is Friday/);
  assert.match(source, /Should we review the proposal\? We should consider another vendor/);
  assert.match(source, /Will the service restart tonight\? We don't need to launch the new build/);
  assert.match(source, /We do not need to merge today\. Sarah will update the release notes/);
  assert.match(source, /Sarah will review the proposal by Friday\. The team must publish the report/);
  assert.match(source, /Sarah will be reviewing the proposal by Friday/);
  assert.match(source, /If the client approves the budget, Sarah will sign the order/);
  assert.match(source, /Sarah will present the chosen plan tomorrow/);
  assert.match(source, /We must be ready before review\. Sarah must be available for questions\. Sarah must be available and review/);
});

test('packaged dictation cleanup smoke requires the exact local cleanup output', () => {
  const expected = 'JSON, send the notes.\n\nWe will ship Friday.';
  assert.equal(isDictationCleanupResponse(200, { cleaned_text: expected }, expected), true);
  assert.equal(isDictationCleanupResponse(200, { cleaned_text: `${expected} altered` }, expected), false);
  assert.equal(isDictationCleanupResponse(500, { cleaned_text: expected }, expected), false);
  const source = fs.readFileSync(new URL('../scripts/smoke-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /api\/dictate\/cleanup/);
  assert.match(source, /await smokeDictationCleanup\(fetchImpl, auth\.headers\)/);
});

test('mounted sidecar smoke validates password output without logging the secret', () => {
  const source = fs.readFileSync(new URL('../scripts/smoke-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /await smokePasswordGenerator\(fetchImpl, auth\.headers\)/);
  assert.match(source, /\/api\/crypto\/password\?\$\{query\}/);
  assert.match(source, /password-generator smoke check returned HTTP/);
});

test('mounted PDF protect and unlock smoke covers the normalized UTF-8 password boundary', () => {
  const source = fs.readFileSync(new URL('../scripts/smoke-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /const password = `\$\{'😀'\.repeat\(31\)\}abc`/);
  assert.match(source, /\['protect', original\]/);
  assert.match(source, /\['unlock', protectedBytes\]/);
  assert.match(source, /'😀'\.repeat\(32\)/);
  assert.match(source, /response\.status !== 422/);
});

test('mounted sidecar smoke validates bundled passphrase output without logging the secret', () => {
  const valid = {
    passphrase: 'abacus drop-down yo-yo secreted tripod velvet',
    word_count: 6,
    separator: ' ',
    theoretical_search_space_bits: 6 * Math.log2(7776),
  };
  assert.equal(isPassphraseGeneratorResponse(200, valid, 6), true);
  assert.equal(isPassphraseGeneratorResponse(200, { ...valid, word_count: 5 }, 6), false);
  assert.equal(isPassphraseGeneratorResponse(200, { ...valid, theoretical_search_space_bits: 1 }, 6), false);
  assert.equal(isPassphraseGeneratorResponse(500, valid, 6), false);
  const source = fs.readFileSync(new URL('../scripts/smoke-backend-sidecar.mjs', import.meta.url), 'utf8');
  assert.match(source, /await smokePassphraseGenerator\(fetchImpl, auth\.headers\)/);
  assert.match(source, /api\/crypto\/passphrase/);
});

test('sidecar smoke check requires a correctly parsed and reconciled bank-statement PDF', () => {
  const payload = {
    transactions: [
      { description: 'Opening balance' },
      { description: 'Client invoice', credit: 500 },
      { description: 'Service fee', debit: 50 },
    ],
    reconciliation: { valid: true },
  };
  assert.equal(isStatementPdfExtractionResponse(200, payload), true);
  assert.equal(isStatementPdfExtractionResponse(200, { ...payload, transactions: payload.transactions.slice(1) }), false);
  assert.equal(isStatementPdfExtractionResponse(200, { ...payload, reconciliation: { valid: false } }), false);
  assert.equal(isStatementPdfExtractionResponse(422, payload), false);
});

test('sidecar smoke check verifies unruled statement columns, wrapped descriptions and summary filtering', () => {
  const payload = {
    transactions: [
      { description: 'Opening balance', status: 'baseline' },
      { description: 'Client invoice via international clearing reference TXN123456789 from Accounts Team', credit: 500, balance: 1500 },
      { description: 'Monthly service fee', debit: 50 },
    ],
    reconciliation: { status: 'verified', valid: true },
  };
  assert.equal(isUnruledStatementPdfResponse(200, payload), true);
  assert.equal(isUnruledStatementPdfResponse(200, {
    ...payload,
    transactions: [...payload.transactions, { description: 'STATEMENT SUMMARY' }],
  }), false);
  assert.equal(isUnruledStatementPdfResponse(422, payload), false);
});

test('PDF statement smoke requests allow bounded OCR initialization time', () => {
  const source = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(source, /const STATEMENT_SMOKE_TIMEOUT_MS = 120_000/);
  for (const helper of ['smokeUnruledStatementPdf', 'smokeWeakVectorStatementPdf', 'smokeStatementPdf']) {
    const start = source.indexOf(`async function ${helper}`);
    const end = source.indexOf('\nasync function ', start + 1);
    assert.ok(start >= 0 && end > start, `${helper} should be a named bounded smoke stage`);
    assert.match(source.slice(start, end), /AbortSignal\.timeout\(STATEMENT_SMOKE_TIMEOUT_MS\)/);
  }
});

test('sidecar smoke check requires weak-vector statement recovery and mounted Vision fixture coverage', () => {
  const payload = {
    transactions: [
      { description: 'Opening balance', status: 'baseline', balance: 1000 },
      { description: 'Coffee Shop', status: 'ok', debit: 25, balance: 975 },
    ],
    reconciliation: { status: 'verified', valid: true },
  };
  assert.equal(isWeakVectorStatementRecoveryResponse(200, payload), true);
  assert.equal(isWeakVectorStatementRecoveryResponse(200, {
    ...payload,
    transactions: payload.transactions.map(row => row.description === 'Coffee Shop' ? { ...row, debit: null } : row),
  }), false);
  assert.equal(isWeakVectorStatementRecoveryResponse(503, payload), false);
  const smokeScript = fs.readFileSync('scripts/smoke-backend-sidecar.mjs', 'utf8');
  assert.match(smokeScript, /weak-vector-raster-statement\.pdf/);
  assert.match(smokeScript, /isWeakVectorStatementRecoveryResponse\(response\.status/);
  assert.match(smokeScript, /await smokeUnruledStatementPdf\(fetchImpl, auth\.headers\);\s+await smokeWeakVectorStatementPdf\(fetchImpl, auth\.headers\);/);
  assert.match(smokeScript, /--only-weak-vector-statement/);
  assert.match(smokeScript, /--only-similar-images/);
});

test('sidecar smoke check rejects a false reconciliation pass when no equation was checked', () => {
  const payload = {
    transactions: [{ status: 'baseline' }, { status: 'unverified' }],
    reconciliation: {
      valid: null,
      status: 'unverified',
      checked_rows: 0,
      unverified_rows: 1,
    },
  };
  assert.equal(isStatementUnverifiedResponse(200, payload), true);
  assert.equal(isStatementUnverifiedResponse(200, {
    ...payload,
    reconciliation: { ...payload.reconciliation, valid: true },
  }), false);
  assert.equal(isStatementUnverifiedResponse(200, {
    ...payload,
    reconciliation: { ...payload.reconciliation, checked_rows: 1 },
  }), false);
  assert.equal(isStatementUnverifiedResponse(500, payload), false);
});

test('sidecar smoke requires ambiguous automatic amounts to remain unverified instead of guessed', () => {
  const payload = {
    transactions: [
      { status: 'unverified', balance: null },
      { status: 'unverified', credit: null, balance: null },
    ],
    reconciliation: { valid: null, status: 'unverified' },
  };
  assert.equal(isAmbiguousStatementUnverifiedResponse(200, payload), true);
  assert.equal(isAmbiguousStatementUnverifiedResponse(200, {
    ...payload,
    transactions: [{ ...payload.transactions[0], status: 'baseline', balance: 1234 }, payload.transactions[1]],
  }), false);
  assert.equal(isAmbiguousStatementUnverifiedResponse(200, {
    ...payload,
    reconciliation: { ...payload.reconciliation, valid: true },
  }), false);
  assert.equal(isAmbiguousStatementUnverifiedResponse(500, payload), false);
});

test('sidecar smoke validates explicit statement locale/date normalization and safe option errors', () => {
  const result = {
    transactions: [{ description: 'Opening balance' }, {
      credit: 1.234, balance: 1.234, date: '2024-02-02',
    }],
    reconciliation: { valid: true, status: 'verified' },
  };
  assert.equal(isLocalizedStatementResponse(200, result, {
    credit: 1.234, balance: 1.234, date: '2024-02-02',
  }), true);
  assert.equal(isLocalizedStatementResponse(200, result, { credit: 1234, balance: 1234 }), false);
  assert.equal(isLocalizedStatementResponse(422, result, { credit: 1.234, balance: 1.234 }), false);
  assert.equal(isInvalidStatementOptionResponse(422, {
    detail: 'Request contains invalid or unsupported values.',
  }), true);
  assert.equal(isInvalidStatementOptionResponse(422, { detail: 'secret value' }), false);
  assert.equal(isInvalidStatementOptionResponse(200, result), false);
});

test('sidecar smoke check validates a real selected-workspace similar-image report', () => {
  assert.equal(isSimilarImageReportResponse(200, {
    complete: true,
    scanned_images: 2,
    groups: [{ files: ['burst/a.png', 'burst/b.png'] }],
  }), true);
  assert.equal(isSimilarImageReportResponse(422, {
    complete: true,
    scanned_images: 2,
    groups: [{ files: ['burst/a.png', 'burst/b.png'] }],
  }), false);
  assert.equal(isSimilarImageReportResponse(200, {
    complete: true,
    scanned_images: 2,
    groups: [],
  }), false);
  assert.equal(isIncompleteSimilarImageReportResponse(200, {
    complete: false,
    scanned_images: 0,
    errors: [{ name: 'broken/bad.png', message: 'Image could not be decoded' }],
  }), true);
  assert.equal(isIncompleteSimilarImageReportResponse(500, {
    complete: false,
    scanned_images: 0,
    errors: [{ name: 'broken/bad.png', message: 'Image could not be decoded' }],
  }), false);
});

test('sidecar smoke check groups a HEIC and HEIF duplicate without including an unrelated scene', () => {
  const report = {
    complete: true,
    scanned_images: 3,
    skipped_files: [],
    errors: [],
    groups: [{ files: ['burst/heic-a.heic', 'burst/heic-b.heif'] }],
  };
  assert.equal(isSimilarImageHeicReportResponse(200, report), true);
  assert.equal(isSimilarImageHeicReportResponse(200, {
    ...report, groups: [{ files: ['burst/heic-a.heic', 'burst/heic-b.heif', 'burst/heic-unrelated.heic'] }],
  }), false);
  assert.equal(isSimilarImageHeicReportResponse(200, { ...report, scanned_images: 2 }), false);
  assert.equal(isSimilarImageHeicReportResponse(200, { ...report, skipped_files: ['burst/heic-a.heic'] }), false);
  assert.equal(isSimilarImageHeicReportResponse(200, { ...report, complete: false }), false);
  assert.equal(isSimilarImageHeicReportResponse(503, report), false);
});

test('sidecar smoke check validates selected-copy filesystem reports and renamed ZIP artifacts', () => {
  assert.equal(isDuplicateWorkspaceReportResponse(200, {
    complete: true,
    files_scanned: 3,
    groups: [{ files: ['samples/sample-a.txt', 'sample-b.txt'], size_bytes: 6 }],
  }), true);
  assert.equal(isDuplicateWorkspaceReportResponse(200, {
    complete: false,
    files_scanned: 3,
    groups: [],
  }), false);
  assert.equal(isStorageWorkspaceReportResponse(200, {
    complete: true,
    total_files: 3,
    total_size_bytes: 19,
    largest_folders: [{ name: 'samples', file_count: 1, size_bytes: 6 }],
  }, 19), true);
  assert.equal(isStorageWorkspaceReportResponse(200, {
    complete: true,
    total_files: 3,
    total_size_bytes: 19,
    largest_folders: [],
  }, 19), false);
  assert.equal(isRenamePreviewResponse(200, {
    files: [{ source: 'rename.txt', target: 'ready_rename.txt', size_bytes: 7 }],
  }), true);
  assert.equal(isRenameArtifactResponse(201, {
    artifact_id: 'a'.repeat(32),
    file_count: 1,
    total_bytes: 7,
    files: ['ready_rename.txt'],
    download_name: 'renamed-files.zip',
  }), true);
  assert.equal(isZipAttachmentResponse(200, 'application/zip', Buffer.from('PK\x03\x04')), true);
  assert.equal(isZipAttachmentResponse(200, 'text/plain', Buffer.from('PK\x03\x04')), false);
});

test('sidecar smoke check validates split manifests and joined-file digest reconciliation', () => {
  const digest = 'a'.repeat(64);
  const split = {
    artifact_id: 'b'.repeat(32),
    original_name: 'archive.bin',
    total_bytes: 25,
    chunk_size_bytes: 10,
    chunk_count: 3,
    sha256: digest,
    parts: [
      { index: 1, name: 'part-00001.bin', size_bytes: 10, sha256: digest },
      { index: 2, name: 'part-00002.bin', size_bytes: 10, sha256: digest },
      { index: 3, name: 'part-00003.bin', size_bytes: 5, sha256: digest },
    ],
    download_name: 'archive.bin.split.zip',
  };
  assert.equal(isWorkspaceSplitResponse(201, split, 25, digest), true);
  assert.equal(isWorkspaceSplitResponse(422, split, 25, digest), false);
  assert.equal(isWorkspaceSplitResponse(201, { ...split, parts: split.parts.slice(1) }, 25, digest), false);
  assert.equal(isWorkspaceSplitResponse(201, { ...split, sha256: 'not-a-digest' }, 25, digest), false);

  const joined = {
    artifact_id: 'c'.repeat(32),
    output_name: 'archive-restored.bin',
    total_bytes: 25,
    part_count: 3,
    sha256: digest,
    download_name: 'archive-restored.bin.zip',
  };
  assert.equal(isWorkspaceJoinResponse(201, joined, 25, digest, 3), true);
  assert.equal(isWorkspaceJoinResponse(201, { ...joined, total_bytes: 24 }, 25, digest, 3), false);
  assert.equal(isWorkspaceJoinResponse(201, { ...joined, part_count: 4 }, 25, digest, 3), false);
  assert.equal(isWorkspaceJoinResponse(201, { ...joined, artifact_id: '../artifact' }, 25, digest, 3), false);
});

test('sidecar smoke check validates formula-safe folder-comparison CSV attachment', () => {
  const csv = Buffer.from(
    "entry_type,relative_path,status,folder_a_path,folder_a_size_bytes,folder_a_sha256,folder_b_path,folder_b_size_bytes,folder_b_sha256\r\nfile,'=SUM(1+1).csv,changed,before/=SUM(1+1).csv,4," + 'a'.repeat(64) + ',after/=SUM(1+1).csv,5,' + 'b'.repeat(64) + '\r\n',
  );
  assert.equal(isFolderComparisonCsvResponse(
    200,
    'text/csv; charset=utf-8',
    'attachment; filename="folder-comparison.csv"',
    csv,
  ), true);
  assert.equal(isFolderComparisonCsvResponse(200, 'application/json', 'folder-comparison.csv', csv), false);
  assert.equal(isFolderComparisonCsvResponse(500, 'text/csv', 'folder-comparison.csv', csv), false);
});

test('sidecar smoke check validates Excel display formatting in CSV output', () => {
  const csv = [
    'currency,percentage,negative,zero,rounded',
    ['"$1,234.50"', '12.5%', '"(1,234.50)"', '-', '1.13'].join(','),
  ].join('\r\n');
  assert.equal(isXlsxDisplayFormatCsvResponse(200, csv), true);
  const changedPercentage = csv.replace('12.5%', '12.4%');
  assert.equal(isXlsxDisplayFormatCsvResponse(200, changedPercentage), false);
  assert.equal(isXlsxDisplayFormatCsvResponse(422, csv), false);
});

test('sidecar smoke check waits longer than the first-launch scan of a fresh macOS build (about 31 s)', () => {
  assert.ok(SIDECAR_FIRST_LAUNCH_TIMEOUT_MS >= 90_000);
});

test('sidecar smoke check fails clearly when the packaged executable is missing', async () => {
  await assert.rejects(smokeSidecar({ binary: '/officekit/sidecar-that-does-not-exist' }), /sidecar is missing/);
});

test('sidecar smoke check starts the sidecar with the app version, as the desktop app does', async () => {
  const os = await import('node:os');
  const path = await import('node:path');
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-smoke-'));
  const record = path.join(folder, 'version.txt');
  const binary = path.join(folder, 'fake-sidecar');
  fs.writeFileSync(binary, `#!/bin/sh\nprintf '%s' "$OFFICEKIT_APP_VERSION" > '${record}'\nexec sleep 30\n`, { mode: 0o755 });
  const expected = JSON.parse(fs.readFileSync('src-tauri/tauri.conf.json', 'utf8')).version;
  const fetchImpl = async url => {
    if (!String(url).endsWith('/api/health')) throw new Error('health reached');
    const version = fs.existsSync(record) ? fs.readFileSync(record, 'utf8') : '';
    if (!version) throw new Error('not started yet');
    return { status: 200, json: async () => ({ status: 'ok', service: 'officekit-api', version }) };
  };
  try {
    // A sidecar that is never told the app version reports 1.0.0 and the smoke check would wait out its timeout.
    await assert.rejects(smokeSidecar({ binary, fetchImpl, timeoutMs: 5000 }), /health reached/);
    assert.equal(fs.readFileSync(record, 'utf8'), expected);
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('default smoke binary uses the built macOS sidecar from the source tree', () => {
  const root = '/work/officekit';
  const bundled = `${root}/.build/backend-sidecar/dist/officekit-backend/officekit-backend`;
  const launcher = `${root}/src-tauri/binaries/officekit-backend-aarch64-apple-darwin`;
  assert.equal(resolveSmokeBinary({
    root, platform: 'darwin', targetTriple: 'aarch64-apple-darwin', exists: candidate => candidate === bundled,
  }), bundled);
  assert.equal(resolveSmokeBinary({
    root, platform: 'darwin', targetTriple: 'aarch64-apple-darwin', exists: () => false,
  }), launcher);
  assert.equal(resolveSmokeBinary({
    root, platform: 'linux', targetTriple: 'aarch64-unknown-linux-gnu', exists: () => true,
  }), `${root}/src-tauri/binaries/officekit-backend-aarch64-unknown-linux-gnu`);
  assert.equal(resolveSmokeBinary({
    root: 'C:\\officekit', platform: 'win32', targetTriple: 'x86_64-pc-windows-msvc', exists: () => true,
  }), 'C:\\officekit\\src-tauri\\binaries\\officekit-backend-x86_64-pc-windows-msvc.exe');
});

test('sidecar smoke selects a free loopback port without binding the app default', async () => {
  const port = await findAvailableLoopbackPort();
  assert.equal(Number.isInteger(port) && port >= 1 && port <= 65535, true);
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
});

test('sidecar smoke resolves explicit and automatic ports for the child environment', async () => {
  assert.equal(await resolveSmokePort({ OFFICEKIT_API_PORT: '49183' }), 49183);
  const automaticPort = await resolveSmokePort({});
  assert.equal(Number.isInteger(automaticPort) && automaticPort >= 1 && automaticPort <= 65535, true);
  assert.equal(sidecarAuth('0123456789abcdef0123456789abcdef', {
    OFFICEKIT_API_PORT: String(automaticPort),
  }).environment.OFFICEKIT_API_PORT, String(automaticPort));
  await assert.rejects(resolveSmokePort({ OFFICEKIT_API_PORT: '0' }), /decimal TCP port/);
});

test('financial calculator sidecar smoke covers every utility calculator without a release profile', async () => {
  const { financialCalculatorSmokeChecks } = await import('../scripts/smoke-backend-sidecar.mjs');
  const previous = process.env.OFFICEKIT_RELEASE_PROFILE;
  process.env.OFFICEKIT_RELEASE_PROFILE = 'private-beta';
  try {
    const paths = financialCalculatorSmokeChecks().map(check => check.path);
    for (const path of [
      '/api/calculator/percent-of', '/api/calculator/percentage-change', '/api/calculator/discount',
      '/api/calculator/margin-markup', '/api/calculator/break-even', '/api/calculator/simple-interest', '/api/calculator/depreciation',
    ]) {
      assert.ok(paths.includes(path), `${path} is covered by the sidecar smoke`);
    }
  } finally {
    if (previous === undefined) delete process.env.OFFICEKIT_RELEASE_PROFILE;
    else process.env.OFFICEKIT_RELEASE_PROFILE = previous;
  }
});

test('sidecar smoke launch and health probe share a bounded bearer token', () => {
  const token = '0123456789abcdef0123456789abcdef';
  assert.deepEqual(sidecarAuth(token, { PATH: '/test' }), {
    environment: { PATH: '/test', OFFICEKIT_API_TOKEN: token },
    headers: { Authorization: `Bearer ${token}` },
  });
  assert.throws(() => sidecarAuth('short'), /valid OfficeKit sidecar token/);
});
