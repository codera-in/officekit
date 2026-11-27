import assert from 'node:assert/strict';
import fs from 'node:fs';

const manifest = JSON.parse(fs.readFileSync(new URL('../release-profile.json', import.meta.url), 'utf8'));

function isPdfGroupArchive(bytes, expectedNames) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 22 || bytes.length > 64 * 1024 * 1024 ||
      bytes.readUInt32LE(0) !== 0x04034b50 || !Array.isArray(expectedNames)) return false;
  const entries = [];
  let offset = 0;
  try {
    while (offset + 30 <= bytes.length && bytes.readUInt32LE(offset) === 0x04034b50) {
      const flags = bytes.readUInt16LE(offset + 6);
      const method = bytes.readUInt16LE(offset + 8);
      const size = bytes.readUInt32LE(offset + 18);
      const nameLength = bytes.readUInt16LE(offset + 26);
      const extraLength = bytes.readUInt16LE(offset + 28);
      const nameStart = offset + 30;
      const dataStart = nameStart + nameLength + extraLength;
      const dataEnd = dataStart + size;
      if (flags !== 0 || method !== 0 || dataEnd > bytes.length) return false;
      const name = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(nameStart, nameStart + nameLength));
      const pdf = bytes.subarray(dataStart, dataEnd);
      if (pdf.subarray(0, 5).toString('ascii') !== '%PDF-') return false;
      entries.push({ name, size });
      offset = dataEnd;
    }
    return entries.length === expectedNames.length &&
      entries.every((entry, index) => entry.name === expectedNames[index] && entry.size > 5) &&
      offset + 4 <= bytes.length && bytes.readUInt32LE(offset) === 0x02014b50;
  } catch (_) {
    return false;
  }
}

function addMinimalExif(jpeg) {
  const payload = Buffer.from('Exif\0\0II*\0\x08\0\0\0\0\0\0\0\0', 'binary');
  const length = Buffer.alloc(2);
  length.writeUInt16BE(payload.length + 2);
  const segment = Buffer.concat([Buffer.from([0xff, 0xe1]), length, payload]);
  return Buffer.concat([jpeg.subarray(0, 2), segment, jpeg.subarray(2)]);
}

function hasExifApp1(jpeg) {
  for (let index = 2; index + 10 <= jpeg.length; index += 1) {
    if (jpeg[index] === 0xff && jpeg[index + 1] === 0xe1 && jpeg.subarray(index + 4, index + 10).equals(Buffer.from('Exif\0\0', 'binary'))) return true;
  }
  return false;
}

function makeSelectableTextPdf() {
  const text = 'OfficeKit packaged PDF text smoke';
  const stream = `BT /F1 12 Tf 1 0 0 1 40 740 Tm (${text}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 450 780] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream, 'ascii')} >>\nstream\n${stream}\nendstream`,
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
  const xref = [`xref\n0 ${objects.length + 1}\n`, '0000000000 65535 f \n'];
  for (const offset of offsets.slice(1)) xref.push(`${String(offset).padStart(10, '0')} 00000 n \n`);
  xref.push(`trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`);
  chunks.push(Buffer.from(xref.join(''), 'ascii'));
  return Buffer.concat(chunks);
}

async function verifyPdfPageDimensions(fetchImpl, headers, pdfBytes, filename, expectedDimensions) {
  const form = new FormData();
  form.set('file', new Blob([pdfBytes], { type: 'application/pdf' }), filename);
  form.set('page_numbers', expectedDimensions.map((_, index) => String(index + 1)).join(','));
  const response = await fetchImpl('http://127.0.0.1:8000/api/pdf/page-thumbnails', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(response.status, 200, `Packaged PDF ${filename} page preview failed`);
  const payload = await response.json();
  assert.deepEqual(payload.pages?.map(page => [page.width_points, page.height_points]), expectedDimensions);
}

export async function verifyPrivateBetaScope(fetchImpl, headers) {
  const get = async path => {
    const response = await fetchImpl(`http://127.0.0.1:8000${path}`, { headers, signal: AbortSignal.timeout(30_000) });
    assert.equal(response.status, 200, 'Private beta scope endpoint failed');
    return response.json();
  };
  const profile = await get('/api/release');
  assert.deepEqual(profile, { profile: 'private-beta', tool_ids: manifest.tool_ids }, 'Private beta startup profile must match the release manifest');
  const dictationSearch = await get('/api/tools/search?q=dictation');
  assert.deepEqual(dictationSearch.tools.map(tool => tool.id), ['voice_transcription'], 'Private beta must make local voice transcription discoverable');
  const meetingNotesSearch = await get('/api/tools/search?q=meeting%20notes');
  assert.deepEqual(meetingNotesSearch.tools.map(tool => tool.id), ['meeting_notes'], 'Private beta must make meeting notes discoverable separately');
  for (const path of ['/api/system/info', '/api/system/resources']) {
    const response = await fetchImpl(`http://127.0.0.1:8000${path}`, { headers, signal: AbortSignal.timeout(30_000) });
    assert.equal(response.status, 200, 'Private beta system utilities must be available');
    assert.equal(typeof await response.json(), 'object');
  }
  const notesResponse = await fetchImpl('http://127.0.0.1:8000/api/dictate/format-notes', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ transcript: 'The launch is Friday.' }), signal: AbortSignal.timeout(30_000),
  });
  assert.equal(notesResponse.status, 200, 'Private beta must format meeting notes locally');
  const notes = await notesResponse.json();
  assert.equal(notes.summary, 'The launch is Friday');
  assert.equal(notes.word_count, 4);
  assert.equal(typeof notes.markdown, 'string');
  const cleanupResponse = await fetchImpl('http://127.0.0.1:8000/api/dictate/cleanup', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ transcript: 'jason comma send the notes period', dictionary: { jason: 'JSON' } }),
    signal: AbortSignal.timeout(30_000),
  });
  assert.equal(cleanupResponse.status, 200, 'Private beta must clean local dictation with the personal dictionary');
  assert.equal((await cleanupResponse.json()).cleaned_text, 'JSON, send the notes.');
  const catalog = await get('/api/tools/search');
  assert.deepEqual(catalog.tools.map(tool => tool.id).sort(), [...manifest.tool_ids].sort(), 'Private beta catalogue must expose exactly the shortlisted tools');
  const protectSearch = await get('/api/tools/search?q=protect%20pdf');
  assert.deepEqual(protectSearch.tools.map(tool => tool.id), ['pdf_protect'], 'Private beta must make PDF protection discoverable');
  const mergeSearch = await get('/api/tools/search?q=merge%20pdf');
  assert.deepEqual(mergeSearch.tools.map(tool => tool.id), ['pdf_merge'], 'Private beta must make PDF merging discoverable');
  const splitSearch = await get('/api/tools/search?q=split%20pdf');
  assert.deepEqual(splitSearch.tools.map(tool => tool.id), ['pdf_split', 'pdf_table_extractor', 'pdf_text_extract'], 'Private beta must make the exact PDF splitter first and include related extraction tools');
  const pdfTableSearch = await get('/api/tools/search?q=pdf%20tables');
  assert.deepEqual(pdfTableSearch.tools.map(tool => tool.id), ['pdf_table_extractor'], 'Private beta must make selectable PDF table extraction discoverable');
  const pdfCsvSearch = await get('/api/tools/search?q=pdf%20to%20csv');
  assert.deepEqual(pdfCsvSearch.tools.map(tool => tool.id), ['pdf_table_extractor', 'bank_statement'], 'PDF-to-CSV search must lead with generic table export while offering transaction extraction');
  const pdfTextSearch = await get('/api/tools/search?q=pdf%20to%20text');
  assert.deepEqual(pdfTextSearch.tools.map(tool => tool.id), ['pdf_text_extract', 'pdf_table_extractor'], 'Private beta must make PDF text extraction primary while showing a related table tool');
  const deletePagesSearch = await get('/api/tools/search?q=delete%20pages%20from%20pdf');
  assert.equal(deletePagesSearch.tools[0]?.id, 'pdf_delete_pages', 'Private beta must make PDF page deletion discoverable');
  const reorderPagesSearch = await get('/api/tools/search?q=reorder%20pdf%20pages');
  assert.equal(reorderPagesSearch.tools[0]?.id, 'pdf_reorder_pages', 'Private beta must make PDF page reordering discoverable');
  const imageSearch = await get('/api/tools/search?q=image%20converter');
  assert.deepEqual(imageSearch.tools.map(tool => tool.id), ['image_converter'], 'Private beta must make the local image converter discoverable');
  const resizeSearch = await get('/api/tools/search?q=resize%20images');
  assert.deepEqual(resizeSearch.tools.map(tool => tool.id), ['image_resize'], 'Private beta must make local image resizing discoverable');
  for (const path of ['/api/convert/data', '/api/network/ping', '/api/license/activate', '/api/support/tickets']) {
    const response = await fetchImpl(`http://127.0.0.1:8000${path}?profile=development`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(30_000),
    });
    assert.equal(response.status, 404, 'Private beta must reject excluded operations');
    assert.deepEqual(await response.json(), { detail: 'This operation is not available in the OfficeKit private beta.' }, 'Private beta scope error must be explicit');
  }

  const imageSource = fs.readFileSync(new URL('../tests/fixtures/similar-images/cc0/dandelion.jpg', import.meta.url));
  const imageForm = new FormData();
  imageForm.set('file', new Blob([imageSource], { type: 'image/jpeg' }), 'dandelion.jpg');
  imageForm.set('target_format', 'webp');
  const imageResponse = await fetchImpl('http://127.0.0.1:8000/api/convert/image', {
    method: 'POST', headers, body: imageForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(imageResponse.status, 200, 'Private beta must convert a selected local image');
  assert.match(imageResponse.headers.get('content-type') || '', /^image\/webp\b/);
  assert.match(imageResponse.headers.get('content-disposition') || '', /dandelion\.webp/);
  const convertedImage = Buffer.from(await imageResponse.arrayBuffer());
  assert.equal(convertedImage.subarray(0, 4).toString('ascii'), 'RIFF');
  assert.equal(convertedImage.subarray(8, 12).toString('ascii'), 'WEBP');

  const resizeSource = fs.readFileSync(new URL('../tests/fixtures/similar-images/cc0/dandelion.jpg', import.meta.url));
  const resizeForm = new FormData();
  resizeForm.set('file', new Blob([resizeSource], { type: 'image/jpeg' }), 'dandelion.jpg');
  resizeForm.set('max_width', '80');
  resizeForm.set('max_height', '80');
  const resizedResponse = await fetchImpl('http://127.0.0.1:8000/api/image/resize', {
    method: 'POST', headers, body: resizeForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(resizedResponse.status, 200, 'Private beta must resize a selected local image');
  assert.match(resizedResponse.headers.get('content-type') || '', /^image\/jpeg\b/);
  assert.match(resizedResponse.headers.get('content-disposition') || '', /dandelion_resized\.jpg/);
  const resizedImage = Buffer.from(await resizedResponse.arrayBuffer());
  assert.deepEqual([...resizedImage.subarray(0, 3)], [0xff, 0xd8, 0xff]);

  const batchForm = new FormData();
  batchForm.append('files', new Blob([resizeSource], { type: 'image/jpeg' }), 'dandelion.jpg');
  batchForm.append('files', new Blob([resizeSource], { type: 'image/jpeg' }), 'dandelion-copy.jpg');
  batchForm.set('max_width', '80');
  batchForm.set('max_height', '80');
  const batchResponse = await fetchImpl('http://127.0.0.1:8000/api/images/resize', {
    method: 'POST', headers, body: batchForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(batchResponse.status, 200, 'Private beta must resize selected image batches');
  assert.match(batchResponse.headers.get('content-type') || '', /^application\/zip\b/);
  const resizedZip = Buffer.from(await batchResponse.arrayBuffer());
  assert.deepEqual([...resizedZip.subarray(0, 4)], [0x50, 0x4b, 0x03, 0x04]);

  const imageMetadataSearch = await get('/api/tools/search?q=remove%20image%20metadata');
  assert.deepEqual(imageMetadataSearch.tools.map(tool => tool.id), ['image_exif_strip'], 'Private beta must make image metadata cleanup discoverable');
  const privateJpeg = addMinimalExif(resizeSource);
  assert.equal(hasExifApp1(privateJpeg), true);
  const imageMetadataForm = new FormData();
  imageMetadataForm.set('file', new Blob([privateJpeg], { type: 'image/jpeg' }), 'private-photo.jpg');
  const imageMetadataResponse = await fetchImpl('http://127.0.0.1:8000/api/image/metadata', {
    method: 'POST', headers, body: imageMetadataForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(imageMetadataResponse.status, 200, 'Private beta must remove image metadata locally');
  assert.match(imageMetadataResponse.headers.get('content-type') || '', /^image\/jpeg\b/);
  assert.match(imageMetadataResponse.headers.get('content-disposition') || '', /private-photo_metadata_removed\.jpg/);
  const cleanedJpeg = Buffer.from(await imageMetadataResponse.arrayBuffer());
  assert.deepEqual([...cleanedJpeg.subarray(0, 3)], [0xff, 0xd8, 0xff]);
  assert.equal(hasExifApp1(cleanedJpeg), false, 'Metadata-cleaned output must not contain the injected EXIF block');

  const invalidTableForm = new FormData();
  invalidTableForm.set('file', new Blob(['not a PDF'], { type: 'application/pdf' }), 'invalid.pdf');
  const invalidTable = await fetchImpl('http://127.0.0.1:8000/api/pdf/tables', {
    method: 'POST', headers, body: invalidTableForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(invalidTable.status, 422, 'Private beta must route PDF table previews to bounded PDF validation');
  const invalidTablePayload = await invalidTable.json();
  assert.equal(typeof invalidTablePayload.detail, 'string');
  assert.doesNotMatch(invalidTablePayload.detail, /traceback|pdfminer|python/i);

  const statementForm = new FormData();
  statementForm.set('file', new Blob([
    'Date,Description,Credit,Balance\n2024-01-01,Opening balance,,100.00\n2024-01-02,Transfer,25.00,125.00\n',
  ], { type: 'text/csv' }), 'statement.csv');
  const statementResponse = await fetchImpl('http://127.0.0.1:8000/api/extract/statement', {
    method: 'POST', headers, body: statementForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(statementResponse.status, 200, 'Private beta must support reviewed bank-statement extraction');
  const statement = await statementResponse.json();
  assert.equal(statement.transactions?.length, 2);
  assert.equal(statement.reconciliation?.status, 'verified');
  const statementCsv = await fetchImpl('http://127.0.0.1:8000/api/export/csv', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(statement), signal: AbortSignal.timeout(30_000),
  });
  assert.equal(statementCsv.status, 200, 'Private beta must export statement transactions to CSV');
  assert.match(await statementCsv.text(), /Transfer/);
  const statementXlsx = await fetchImpl('http://127.0.0.1:8000/api/export/excel', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(statement), signal: AbortSignal.timeout(30_000),
  });
  assert.equal(statementXlsx.status, 200, 'Private beta must export statement transactions to XLSX');
  const workbook = Buffer.from(await statementXlsx.arrayBuffer());
  assert.deepEqual(workbook.subarray(0, 4), Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  assert.ok(workbook.length > 1000);
  const statementXls = await fetchImpl('http://127.0.0.1:8000/api/export/xls', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(statement), signal: AbortSignal.timeout(30_000),
  });
  assert.equal(statementXls.status, 200, 'Private beta must export statement transactions to legacy XLS');
  const legacyWorkbook = Buffer.from(await statementXls.arrayBuffer());
  assert.deepEqual(legacyWorkbook.subarray(0, 8), Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]));
  assert.ok(legacyWorkbook.length > 1000);

  const textForm = new FormData();
  textForm.set('file', new Blob([makeSelectableTextPdf()], { type: 'application/pdf' }), 'scope-text.pdf');
  const textResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/text', {
    method: 'POST', headers, body: textForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(textResponse.status, 200, 'Private beta must extract selectable PDF text with the packaged backend');
  assert.equal(textResponse.headers.get('x-officekit-page-count'), '1');
  assert.match(textResponse.headers.get('content-disposition') || '', /extracted-text\.txt/);
  assert.match(await textResponse.text(), /OfficeKit packaged PDF text smoke/);

  const pageManagementSource = fs.readFileSync(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  for (const operation of [
    { path: '/api/pdf/pages/delete', field: 'page_ranges', selection: '2', filename: 'deleted-pages.pdf', dimensions: [[300, 400], [300, 400]] },
    { path: '/api/pdf/pages/reorder', field: 'page_order', selection: '3,1,2', filename: 'reordered.pdf', dimensions: [[300, 400], [300, 400], [300, 400]] },
  ]) {
    const pageForm = new FormData();
    pageForm.set('file', new Blob([pageManagementSource], { type: 'application/pdf' }), 'page-management.pdf');
    pageForm.set(operation.field, operation.selection);
    const pageResponse = await fetchImpl(`http://127.0.0.1:8000${operation.path}`, {
      method: 'POST', headers, body: pageForm, signal: AbortSignal.timeout(30_000),
    });
    assert.equal(pageResponse.status, 200, `Packaged ${operation.path} failed`);
    assert.equal(pageResponse.headers.get('content-type'), 'application/pdf');
    assert.match(pageResponse.headers.get('content-disposition') || '', new RegExp(operation.filename));
    const pageBytes = Buffer.from(await pageResponse.arrayBuffer());
    assert.equal(pageBytes.subarray(0, 5).toString('ascii'), '%PDF-');
    await verifyPdfPageDimensions(fetchImpl, headers, pageBytes, operation.filename, operation.dimensions);
  }

  const form = new FormData();
  form.set('files', new Blob(['scope smoke fixture'], { type: 'text/plain' }), 'scope-smoke.txt');
  const created = await fetchImpl('http://127.0.0.1:8000/api/workspaces', {
    method: 'POST', headers, body: form, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(created.status, 201, 'Private beta must support selected-file workspaces');
  const workspace = await created.json();
  assert.match(workspace.workspace_id, /^[a-f0-9]{32}$/);
  assert.deepEqual(workspace.files, [{ name: 'scope-smoke.txt', size_bytes: 19 }]);

  const inspected = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${workspace.workspace_id}`, {
    headers, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(inspected.status, 200, 'Private beta must expose the selected workspace inventory');
  assert.deepEqual(await inspected.json(), workspace);

  const hashed = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${workspace.workspace_id}/hash-reports`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ filenames: ['scope-smoke.txt'], algorithm: 'sha256' }),
    signal: AbortSignal.timeout(30_000),
  });
  assert.equal(hashed.status, 200, 'Private beta must execute selected-file hash reports');
  const report = await hashed.json();
  assert.equal(report.complete, true);
  assert.equal(report.files?.[0]?.name, 'scope-smoke.txt');
  assert.equal(report.total_bytes, 19);
  assert.match(report.files[0].digest, /^[a-f0-9]{64}$/);

  const cleared = await fetchImpl(`http://127.0.0.1:8000/api/workspaces/${workspace.workspace_id}`, {
    method: 'DELETE', headers, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(cleared.status, 204, 'Private beta must clear selected temporary files');

  const unlockProbe = await fetchImpl('http://127.0.0.1:8000/api/pdf/unlock', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(30_000),
  });
  assert.equal(unlockProbe.status, 422, 'Private beta must route PDF unlock requests to input validation');

  const sourceBytes = fs.readFileSync(new URL('../tests/fixtures/pdf-protect-source.pdf', import.meta.url));
  const protectForm = new FormData();
  protectForm.set('file', new Blob([sourceBytes], { type: 'application/pdf' }), 'beta-source.pdf');
  protectForm.set('password', 'beta password 123');
  const protectedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/protect', {
    method: 'POST', headers, body: protectForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(protectedResponse.status, 200, 'Private beta must execute PDF password protection');
  assert.match(protectedResponse.headers.get('content-type') || '', /^application\/pdf\b/);
  const protectedBytes = Buffer.from(await protectedResponse.arrayBuffer());
  assert.equal(protectedBytes.subarray(0, 5).toString('ascii'), '%PDF-');

  const unlockForm = new FormData();
  unlockForm.set('file', new Blob([protectedBytes], { type: 'application/pdf' }), 'protected.pdf');
  unlockForm.set('password', 'beta password 123');
  const unlockedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/unlock', {
    method: 'POST', headers, body: unlockForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(unlockedResponse.status, 200, 'The packaged beta must unlock its own protected output');
  assert.match(unlockedResponse.headers.get('content-type') || '', /^application\/pdf\b/);
  assert.equal(Buffer.from(await unlockedResponse.arrayBuffer()).subarray(0, 5).toString('ascii'), '%PDF-');

  const mergeForm = new FormData();
  const mergeSources = [
    ['first.pdf', fs.readFileSync(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url))],
    ['second.pdf', sourceBytes],
  ];
  for (const [name, bytes] of mergeSources) mergeForm.append('files', new Blob([bytes], { type: 'application/pdf' }), name);
  const mergedResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/merge', {
    method: 'POST', headers, body: mergeForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(mergedResponse.status, 200, 'Private beta must merge selected PDFs in the requested order');
  assert.match(mergedResponse.headers.get('content-type') || '', /^application\/pdf\b/);
  const mergedBytes = Buffer.from(await mergedResponse.arrayBuffer());
  assert.equal(mergedBytes.subarray(0, 5).toString('ascii'), '%PDF-');
  assert.ok(mergedBytes.length > 5 && mergedBytes.length <= 64 * 1024 * 1024);

  const splitForm = new FormData();
  const splitSource = fs.readFileSync(new URL('../tests/fixtures/pdf-page-management-source.pdf', import.meta.url));
  splitForm.set('file', new Blob([splitSource], { type: 'application/pdf' }), 'grouped-source.pdf');
  splitForm.set('groups', JSON.stringify([
    { name: 'last-first.pdf', page_ranges: '3,1' },
    { name: 'middle.pdf', page_ranges: '2' },
  ]));
  const splitResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/split/groups', {
    method: 'POST', headers, body: splitForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(splitResponse.status, 200, 'Private beta must return the requested grouped PDF split');
  assert.match(splitResponse.headers.get('content-type') || '', /^application\/zip\b/);
  const splitBytes = Buffer.from(await splitResponse.arrayBuffer());
  assert.equal(isPdfGroupArchive(splitBytes, ['last-first.pdf', 'middle.pdf']), true);

  const imagesSearch = await get('/api/tools/search?q=pdf%20to%20jpeg');
  assert.deepEqual(imagesSearch.tools.map(tool => tool.id), ['pdf_to_images'], 'Private beta must make PDF page image export discoverable');
  const imagesForm = new FormData();
  imagesForm.set('file', new Blob([sourceBytes], { type: 'application/pdf' }), 'beta-pages.pdf');
  imagesForm.set('target_format', 'jpeg');
  imagesForm.set('dpi', '300');
  imagesForm.set('quality', '82');
  const imagesResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/images', {
    method: 'POST', headers, body: imagesForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(imagesResponse.status, 200, 'Private beta must render PDF pages to a local image ZIP');
  assert.match(imagesResponse.headers.get('content-type') || '', /^application\/zip\b/);
  assert.equal(imagesResponse.headers.get('x-officekit-page-count'), '1');
  assert.match(imagesResponse.headers.get('content-disposition') || '', /beta-pages_pages\.zip/);
  const imagesBytes = Buffer.from(await imagesResponse.arrayBuffer());
  assert.equal(imagesBytes.subarray(0, 4).toString('hex'), '504b0304');
  assert.ok(imagesBytes.includes(Buffer.from('page-001.jpg')));

  const metadataSearch = await get('/api/tools/search?q=remove%20pdf%20metadata');
  assert.deepEqual(metadataSearch.tools.map(tool => tool.id), ['pdf_metadata_strip'], 'Private beta must make PDF metadata removal discoverable');
  const metadataForm = new FormData();
  metadataForm.set('file', new Blob([sourceBytes], { type: 'application/pdf' }), 'beta-private.pdf');
  const metadataResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/metadata', {
    method: 'POST', headers, body: metadataForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(metadataResponse.status, 200, 'Private beta must create a clean PDF copy');
  assert.match(metadataResponse.headers.get('content-type') || '', /^application\/pdf\b/);
  const cleanedBytes = Buffer.from(await metadataResponse.arrayBuffer());
  assert.equal(cleanedBytes.subarray(0, 5).toString('ascii'), '%PDF-');
  assert.equal(cleanedBytes.toString('latin1').includes('OfficeKit PDF test fixture'), false);
  const pageCountForm = new FormData();
  pageCountForm.set('files', new Blob([cleanedBytes], { type: 'application/pdf' }), 'cleaned.pdf');
  const pageCountResponse = await fetchImpl('http://127.0.0.1:8000/api/pdf/page-counts', {
    method: 'POST', headers, body: pageCountForm, signal: AbortSignal.timeout(30_000),
  });
  assert.equal(pageCountResponse.status, 200, 'Private beta must confirm cleaned PDF pages remain readable');
  const pageCount = await pageCountResponse.json();
  assert.equal(pageCount.total_pages, 1);
  assert.equal(pageCount.ready_count, 1);
  assert.equal(pageCount.unreadable_count, 0);
}
