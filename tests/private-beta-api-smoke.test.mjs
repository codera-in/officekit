import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { verifyPrivateBetaScope } from '../scripts/private-beta-api-smoke.mjs';

const manifest = JSON.parse(fs.readFileSync('release-profile.json', 'utf8'));
function fakeStoredPdfZip(entries) {
  const locals = entries.map(([name, text]) => {
    const nameBytes = Buffer.from(name);
    const pdf = Buffer.from(text);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt32LE(pdf.length, 18);
    local.writeUInt32LE(pdf.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    return Buffer.concat([local, nameBytes, pdf]);
  });
  return Buffer.concat([...locals, Buffer.from([0x50, 0x4b, 0x01, 0x02])]);
}

function fake({ profile = 'private-beta', ids = manifest.tool_ids, status = 404 } = {}) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    const path = new URL(url).pathname;
    if (path === '/api/release') return { status: 200, json: async () => ({ profile, tool_ids: ids }) };
    if (path === '/api/tools/search') {
      const q = new URL(url).searchParams.get('q');
      const tools = q === 'dictation' ? [{ id: 'voice_transcription' }]
        : q === 'meeting notes' ? [{ id: 'meeting_notes' }]
        : q === 'pdf tables' ? [{ id: 'pdf_table_extractor' }]
        : q === 'pdf to csv' ? [{ id: 'pdf_table_extractor' }, { id: 'bank_statement' }]
        : q === 'pdf to text' ? [{ id: 'pdf_text_extract' }, { id: 'pdf_table_extractor' }]
        : q === 'delete pages from pdf' ? [{ id: 'pdf_delete_pages' }]
        : q === 'reorder pdf pages' ? [{ id: 'pdf_reorder_pages' }]
        : q === 'image converter' ? [{ id: 'image_converter' }]
        : q === 'resize images' ? [{ id: 'image_resize' }]
        : q === 'remove image metadata' ? [{ id: 'image_exif_strip' }]
        : q === 'protect pdf' ? [{ id: 'pdf_protect' }]
        : q === 'merge pdf' ? [{ id: 'pdf_merge' }]
        : q === 'split pdf' ? [{ id: 'pdf_split' }, { id: 'pdf_table_extractor' }, { id: 'pdf_text_extract' }]
            : q === 'pdf to jpeg' ? [{ id: 'pdf_to_images' }]
              : q === 'remove pdf metadata' ? [{ id: 'pdf_metadata_strip' }]
            : ids.map(id => ({ id }));
      return { status: 200, json: async () => ({ tools }) };
    }
    if (['/api/system/info', '/api/system/resources'].includes(path)) return { status: 200, json: async () => ({}) };
    if (path === '/api/dictate/format-notes' && init.method === 'POST') return {
      status: 200, json: async () => ({ summary: 'The launch is Friday', word_count: 4, markdown: '## Meeting notes' }),
    };
    if (path === '/api/dictate/cleanup' && init.method === 'POST') return {
      status: 200, json: async () => ({ cleaned_text: 'JSON, send the notes.' }),
    };
    if (path === '/api/convert/image' && init.method === 'POST') return {
      status: 200,
      headers: { get: name => ({ 'content-type': 'image/webp', 'content-disposition': 'attachment; filename="dandelion.webp"' }[name.toLowerCase()] || null) },
      arrayBuffer: async () => Buffer.from('RIFF0000WEBP-image'),
    };
    if (path === '/api/image/resize' && init.method === 'POST') return {
      status: 200,
      headers: { get: name => ({ 'content-type': 'image/jpeg', 'content-disposition': 'attachment; filename="dandelion_resized.jpg"' }[name.toLowerCase()] || null) },
      arrayBuffer: async () => Buffer.from([0xff, 0xd8, 0xff, 0x00]),
    };
    if (path === '/api/images/resize' && init.method === 'POST') return {
      status: 200,
      headers: { get: name => name.toLowerCase() === 'content-type' ? 'application/zip' : null },
      arrayBuffer: async () => Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x50, 0x4b, 0x05, 0x06]),
    };
    if (path === '/api/image/metadata' && init.method === 'POST') return {
      status: 200,
      headers: { get: name => ({ 'content-type': 'image/jpeg', 'content-disposition': 'attachment; filename="private-photo_metadata_removed.jpg"' }[name.toLowerCase()] || null) },
      arrayBuffer: async () => Buffer.from([0xff, 0xd8, 0xff, 0xda, 0x00, 0x02]),
    };
    if (path === '/api/pdf/unlock' && init.method === 'POST') {
      if (init.body instanceof FormData) return { status: 200, headers: { get: () => 'application/pdf' }, arrayBuffer: async () => Buffer.from('%PDF-unlocked') };
      return { status: 422, json: async () => ({ detail: 'Field required' }) };
    }
    if (path === '/api/pdf/protect' && init.method === 'POST') return { status: 200, headers: { get: () => 'application/pdf' }, arrayBuffer: async () => Buffer.from('%PDF-protected') };
    if (path === '/api/pdf/merge' && init.method === 'POST') return { status: 200, headers: { get: () => 'application/pdf' }, arrayBuffer: async () => Buffer.from('%PDF-merged') };
    if (path === '/api/pdf/split/groups' && init.method === 'POST') return { status: 200, headers: { get: () => 'application/zip' }, arrayBuffer: async () => fakeStoredPdfZip([['last-first.pdf', '%PDF-first'], ['middle.pdf', '%PDF-middle']]) };
    if (path === '/api/pdf/images' && init.method === 'POST') return { status: 200, headers: { get: name => ({ 'content-type': 'application/zip', 'content-disposition': 'attachment; filename="beta-pages_pages.zip"', 'x-officekit-page-count': '1' }[name.toLowerCase()] || null) }, arrayBuffer: async () => Buffer.from([0x50,0x4b,0x03,0x04,...Buffer.from('page-001.jpg'),0x50,0x4b,0x05,0x06]) };
    if (path === '/api/pdf/metadata' && init.method === 'POST') return { status: 200, headers: { get: name => name.toLowerCase() === 'content-type' ? 'application/pdf' : null }, arrayBuffer: async () => Buffer.from('%PDF-cleaned') };
    if (path === '/api/pdf/page-counts' && init.method === 'POST') return { status: 200, json: async () => ({ files: [{ index: 0, page_count: 1, status: 'ready' }], total_pages: 1, ready_count: 1, unreadable_count: 0 }) };
    if (path === '/api/pdf/tables' && init.method === 'POST') return { status: 422, json: async () => ({ detail: 'The PDF could not be read.' }) };
    if (path === '/api/pdf/text' && init.method === 'POST') return {
      status: 200,
      headers: { get: name => ({ 'x-officekit-page-count': '1', 'content-disposition': 'attachment; filename="extracted-text.txt"' }[name.toLowerCase()] || null) },
      text: async () => '--- Page 1 ---\n\nOfficeKit packaged PDF text smoke\n',
    };
    if (['/api/pdf/pages/delete', '/api/pdf/pages/reorder'].includes(path) && init.method === 'POST') {
      const deleted = path.endsWith('/delete');
      return {
        status: 200,
        headers: { get: name => ({
          'content-type': 'application/pdf',
          'content-disposition': `attachment; filename="${deleted ? 'deleted-pages.pdf' : 'reordered.pdf'}"`,
        }[name.toLowerCase()] || null) },
        arrayBuffer: async () => Buffer.from(deleted ? '%PDF-deleted' : '%PDF-reordered'),
      };
    }
    if (path === '/api/pdf/page-thumbnails' && init.method === 'POST') {
      const name = init.body.get('file')?.name;
      const pages = name === 'deleted-pages.pdf'
        ? [[300, 400], [300, 400]]
        : [[300, 400], [300, 400], [300, 400]];
      return { status: 200, json: async () => ({ pages: pages.map(([width_points, height_points], index) => ({
        page_number: index + 1, width_points, height_points, data_base64: 'iVBORw0KGgo=',
      })) }) };
    }
    if (path === '/api/extract/statement' && init.method === 'POST') return { status: 200, json: async () => ({ transactions: [{ date: '2024-01-01' }, { date: '2024-01-02' }], reconciliation: { status: 'verified' } }) };
    if (path === '/api/export/csv' && init.method === 'POST') return { status: 200, text: async () => 'Date,Description\n2024-01-02,Transfer' };
    if (path === '/api/export/excel' && init.method === 'POST') return { status: 200, arrayBuffer: async () => Uint8Array.from([0x50, 0x4b, 0x03, 0x04, ...Array(1000).fill(0)]).buffer };
    if (path === '/api/export/xls' && init.method === 'POST') return { status: 200, arrayBuffer: async () => Uint8Array.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, ...Array(1000).fill(0)]).buffer };
    if (path === '/api/workspaces' && init.method === 'POST') return { status: 201, json: async () => ({ workspace_id: 'a'.repeat(32), files: [{ name: 'scope-smoke.txt', size_bytes: 19 }] }) };
    if (path === `/api/workspaces/${'a'.repeat(32)}` && !init.method) return { status: 200, json: async () => ({ workspace_id: 'a'.repeat(32), files: [{ name: 'scope-smoke.txt', size_bytes: 19 }] }) };
    if (path.endsWith('/hash-reports')) return { status: 200, json: async () => ({ algorithm: 'sha256', total_files: 1, total_bytes: 19, complete: true, files: [{ name: 'scope-smoke.txt', size_bytes: 19, digest: 'b'.repeat(64) }] }) };
    if (path === `/api/workspaces/${'a'.repeat(32)}` && init.method === 'DELETE') return { status: 204, json: async () => null };
    return { status, json: async () => ({ detail: 'This operation is not available in the OfficeKit private beta.' }) };
  };
  return { fetch, calls };
}

test('packaged beta check requires the exact shortlist and exercises image and PDF workbenches', async () => {
  const { fetch, calls } = fake();
  await verifyPrivateBetaScope(fetch, { Authorization: 'Bearer fixture' });
  assert.equal(calls.length, 51);
  for (const call of calls) assert.equal(call.init.headers.Authorization, 'Bearer fixture');
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/release');
  const urls = calls.map(call => call.url);
  for (const query of ['dictation', 'meeting%20notes', 'protect%20pdf', 'merge%20pdf', 'split%20pdf', 'pdf%20tables', 'pdf%20to%20csv', 'pdf%20to%20text', 'delete%20pages%20from%20pdf', 'reorder%20pdf%20pages', 'image%20converter', 'resize%20images']) {
    assert.ok(urls.includes(`http://127.0.0.1:8000/api/tools/search?q=${query}`), `expected search query ${query}`);
  }
  assert.ok(urls.includes('http://127.0.0.1:8000/api/convert/image'));
  assert.ok(calls.find(call => call.url.endsWith('/api/convert/image')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/image/resize')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/images/resize')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/image/metadata')).init.body instanceof FormData);
  assert.ok(urls.includes('http://127.0.0.1:8000/api/tools/search?q=pdf%20tables'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/pdf/tables'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/pdf/text'));
  assert.ok(calls.find(call => call.url.endsWith('/api/pdf/text')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/pdf/pages/delete')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/pdf/pages/reorder')).init.body instanceof FormData);
  assert.equal(calls.filter(call => call.url.endsWith('/api/pdf/page-thumbnails')).length, 2);
  assert.ok(calls.find(call => call.url.endsWith('/api/pdf/tables')).init.body instanceof FormData);
  assert.ok(calls.find(call => call.url.endsWith('/api/pdf/tables')).init.headers.Authorization === 'Bearer fixture');
  assert.ok(urls.includes('http://127.0.0.1:8000/api/extract/statement'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/export/csv'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/export/excel'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/export/xls'));
  assert.ok(urls.includes('http://127.0.0.1:8000/api/workspaces'));
});

test('package scope does not accept a full catalogue, missing tool, duplicate or disabled-route success', async () => {
  for (const options of [{ profile: 'development' }, { ids: [...manifest.tool_ids, 'pdf_protect'] }, { ids: manifest.tool_ids.slice(1) }, { ids: [...manifest.tool_ids.slice(1), manifest.tool_ids[1]] }, { status: 200 }]) {
    const { fetch } = fake(options);
    await assert.rejects(verifyPrivateBetaScope(fetch, {}), /private beta/i);
  }
});
