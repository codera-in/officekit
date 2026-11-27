import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync('index.html', 'utf8');
const client = fs.readFileSync('assets/officekit-media.js', 'utf8');
const script = client;
const builder = fs.readFileSync('scripts/build-ui-assets.mjs', 'utf8');
const tauriWindowManager = fs.readFileSync('src-tauri/vendor/tauri/src/manager/window.rs', 'utf8');
const tauriWebviewManager = fs.readFileSync('src-tauri/vendor/tauri/src/manager/webview.rs', 'utf8');

test('Media Toolkit returns to the converter through a semantic link', () => {
  const start = html.indexOf('<section id="media-toolkit-panel"');
  const end = html.indexOf('<div id="generic-converter-panel"', start);
  const panelMarkup = html.slice(start, end);
  const header = panelMarkup.match(/<header[^>]*>[\s\S]*?<\/header>/)?.[0] ?? '';
  assert.match(header, /<a href="#generic-converter-panel" class="link link-hover text-sm font-semibold" data-officekit-click="setConverterMode\('convert'\)">← Other converter tools<\/a>/);
  assert.doesNotMatch(header, /<button[^>]*>← Other converter tools<\/button>/);
});

test('Media Toolkit picks the operation type from the files and hides JPEG as a target for JPEG-only batches', () => {
  assert.match(client, /function batchKinds\(\) \{/, 'the batch kinds come from the files');
  assert.match(client, /if \(only\.length === 1 && \$\('kind'\)\.value !== only\[0\]\) \$\('kind'\)\.value = only\[0\];/, 'one detected kind selects that kind');
  assert.match(client, /parent\.label = `\$\{kindLabels\[groupKind\]\} \(\$\{count\} \$\{count === 1 \? 'file' : 'files'\}\)`;/, 'a mixed batch lists one labelled group per kind');
  assert.match(client, /kind = operationKind\(select\.value\); \$\('kind'\)\.value = kind;/, 'the chosen operation sets the type in a mixed batch');
  assert.match(client, /const allJpeg = inputExtensions\.size > 0 && \[\.\.\.inputExtensions\]\.every/, 'JPEG-only batches are detected');
  assert.match(client, /!\(allJpeg && format === 'jpeg'\)/, 'JPEG is removed from the convert targets for those batches');
  assert.match(html, /<label class="text-sm font-semibold text-slate-700">What do you want to do\?<select id="media-toolkit-operation"/, 'the operation select has a visible label');
  assert.match(html, /<a href="#" id="media-toolkit-select" class="link link-primary font-semibold">Select files<\/a>/, 'Select files is a text link, not a button');
});

test('Media Toolkit UI contains all Clop-inspired transform operation IDs', () => {
  for (const id of [
    'image-optimize','image-fit-size','image-convert','image-resize','image-crop','image-strip-metadata','image-watermark',
    'video-optimize','video-hevc-convert','video-fit-size','video-crop','video-resize','video-speed','video-mute','video-to-gif',
    'pdf-lossless-compress','pdf-visual-optimize','pdf-fit-size','pdf-crop',
    'audio-optimize','audio-convert','audio-fit-size','audio-normalize','audio-artwork',
  ]) assert.match(client, new RegExp(`['"]${id}['"]`), `operation ${id} is represented`);
});

test('Media Toolkit discovers build capability and never offers unavailable actions to run', () => {
  assert.match(client, /\/api\/media-capabilities/);
  assert.match(client, /operationById\(operationId\)\?\.formats/);
  assert.match(client, /'avif'/);
  assert.match(client, /'jxl'/);
  assert.match(client, /option\.disabled = !operation\.available/);
  assert.match(client, /\/api\/media-jobs/);
  assert.match(client, /\/api\/media-artifacts/);
  assert.match(client, /file_selection_open/);
  assert.match(client, /than original/);
  assert.match(client, /target not met/);
  assert.match(client, /HEVC video · MOV/);
  assert.match(client, /api\/media-pipelines/);
  assert.match(client, /api\/media-pipeline-triggers/);
  assert.match(client, /pinnedPipelineForTrigger/);
  assert.match(html, /Save paused pipeline/);
});

test('Media Toolkit never sends a failed artifact response to the native save bridge', () => {
  const helperStart = client.indexOf('async function fetchArtifactBlob(');
  const helperEnd = client.indexOf('\n  function activeOperation()', helperStart);
  const helper = client.slice(helperStart, helperEnd);
  assert.match(helper, /if \(!response\.ok\) \{[\s\S]*throw error;[\s\S]*\}\s+return response\.blob\(\);/);
  assert.match(client, /fetchArtifactBlob\(item\.artifactId, 'The result could not be saved\.'\)/);
  assert.match(client, /fetchArtifactBlob\(item\.artifactId, 'The prepared copy could not be saved\.'\)/);
  assert.doesNotMatch(client, /apiFetch\(`\/api\/media-artifacts\/\$\{item\.artifactId\}`\)\)\.blob\(\)/);
});

test('image preparation summaries use the shared readable size formatter', () => {
  assert.match(client, /Prepared \$\{outcome\.outputName \|\| 'clipboard image'\} · \$\{window\.OfficeKitFormatters\.fileSize\(outcome\.outputBytes\)\}/);
  assert.match(client, /Prepared \$\{result\.outputName \|\| 'clipboard image'\} · \$\{window\.OfficeKitFormatters\.fileSize\(result\.outputBytes\)\}/);
});

test('Media Toolkit rejects an expired artifact response before reading it as a result file', async () => {
  const helperStart = client.indexOf('async function fetchArtifactBlob(');
  const helperEnd = client.indexOf('\n  function activeOperation()', helperStart);
  const helper = client.slice(helperStart, helperEnd);
  let blobReads = 0;
  const expiredFetch = async () => ({ ok: false, status: 404, blob: async () => { blobReads += 1; return new Blob(['404 page']); } });
  const fetchExpired = vm.runInNewContext(`(() => { ${helper}; return fetchArtifactBlob; })()`, { apiFetch: expiredFetch, Error });
  await assert.rejects(fetchExpired('expired-id', 'The result could not be saved.'), error => {
    assert.match(error.message, /The result could not be saved/);
    assert.equal(error.code, 'MEDIA_ARTIFACT_UNAVAILABLE');
    return true;
  });
  assert.equal(blobReads, 0, 'an HTTP error body must never be passed to the native save bridge');

  const expected = new Blob(['prepared bytes']);
  const fetchReady = vm.runInNewContext(`(() => { ${helper}; return fetchArtifactBlob; })()`, {
    apiFetch: async () => ({ ok: true, status: 200, blob: async () => expected }), Error, expected,
  });
  assert.equal(await fetchReady('ready-id', 'The result could not be saved.'), expected);
});

test('existing image tools route to the shared workbench while PDF compression keeps its PDF workspace', () => {
  for (const [id, operation] of [['image_converter','image-convert'],['image_resize','image-resize'],['image_exif_strip','image-strip-metadata']]) {
    assert.match(html, new RegExp(`${id}: \\{ tab: 'converter', converterMode: 'media_toolkit', mediaKind: '[a-z]+', mediaOperation: '${operation}' \\}`));
  }
  assert.match(html, /pdf_compress: \{ tab: 'pdf', pdfTool: 'compress' \}/);
  assert.match(html, /id="media-toolkit-operation"/);
  assert.match(html, /id="media-toolkit-panel"/);
  assert.match(html, /id="media-toolkit-fidelity-warning"/);
  assert.match(script, /Searchable text, links, forms, accessibility structure, and digital signatures are not preserved/);
  assert.match(builder, /officekit-media\.js/);
});

test('media workbench exposes manual automation controls and honest build availability', () => {
  assert.match(html, /selected originals remain unchanged/);
  assert.match(html, /id="media-toolkit-tab-automations"/);
  assert.match(html, /id="media-toolkit-settings-fields"/);
  assert.match(html, /id="media-toolkit-options"/);
  assert.match(html, /Clipboard monitoring/);
  assert.match(html, /id="media-toolkit-clipboard-opt-in"/);
  assert.match(html, /changed clipboard images are optimized locally/);
  assert.match(html, /Bypass next clipboard item/);
  assert.match(html, /Watched folders/);
  assert.match(html, /Grant folder/);
  assert.match(html, /session only/);
  assert.match(html, /CLI and MCP available/);
  assert.match(html, /Contents\/Resources\/binaries\/officekit-media/);
  assert.match(html, /launch that executable with <code>--mcp-server<\/code>/);
  assert.match(html, /photo_prepared\.webp/);
  assert.match(html, /Latest outcome/);
  assert.match(client, /function renderSettings/);
  assert.match(client, /function syncSettingsFromForm/);
  assert.match(client, /media_clipboard_revision/);
  assert.match(client, /media_folder_watch_open/);
  assert.match(client, /function renderFolderWatches/);
  assert.match(html, /id="media-toolkit-zone-list"/);
  assert.match(html, /id="media-toolkit-zone-create"/);
  assert.match(client, /\/api\/media-preset-zones/);
  assert.match(client, /function renderPresetZones/);
  assert.match(client, /Enable for session/);
  assert.match(client, /Use preset/);
  assert.match(client, /media-folder-watches/);
  assert.match(client, /officekit\.media\.clipboardAutomation/);
  assert.match(client, /prepareClipboardImage/);
  assert.match(client, /preserveMetadata: false/);
  assert.match(html, /id="media-toolkit-hotkey-enable"/);
  assert.match(client, /media_clipboard_hotkey_set_enabled/);
  assert.match(html, /id="media-toolkit-finder-install"/);
  assert.match(html, /id="media-toolkit-finder-remove"/);
  assert.match(client, /media_finder_action_status/);
  assert.match(client, /media_finder_action_install/);
  assert.match(client, /media_finder_action_remove/);
  assert.match(client, /numbered|Quick Action is installed/);
  assert.match(client, /officekit-media-clipboard-hotkey/);
  assert.match(client, /explicitHotkey: true/);
  assert.match(client, /original preserved/);
});

test('Media Toolkit labels non-operation Clop workflows that are not implemented yet', () => {
  assert.match(html, /Image watermark overlay/);
  assert.match(html, /id="media-toolkit-format-bar"/);
  assert.match(client, /function renderFormatBar/);
  assert.match(client, /function setResultFormat/);
  assert.match(client, /function renderLocalDefaults/);
  assert.match(client, /api\/media-operation-defaults/);
  assert.match(html, /shared with MCP; only operation values are stored/);
  assert.doesNotMatch(client, /officekit\.media\.operationDefaults\.v1/);
  assert.match(client, /function validLocalDefault/);
  assert.match(client, /image-watermark/);
  assert.match(html, /Additional capabilities not available yet/);
});

test('Media Toolkit drag and drop imports only native opaque file grants', () => {
  assert.match(html, /id="media-toolkit-drop-target"/);
  assert.match(html, /Drop up to 30 files here/);
  assert.match(client, /media_toolkit_drop_set_enabled/);
  assert.match(client, /data-zone-id/);
  assert.match(client, /handlePresetZoneDrop/);
  assert.match(client, /selection\.presetZoneId \? handlePresetZoneDrop/);
  assert.match(client, /Preparing a separate local copy/);
  assert.match(client, /officekit-media-file-drop/);
  assert.match(client, /api\/file-selections/);
  assert.doesNotMatch(client, /payload\.paths/);
  assert.match(client, /state\.files\.length \+ manifest\.files\.length > 30/);
  assert.match(client, /acceptSelection\(selection, \{ append: true \}\)/);
  assert.match(client, /state\.running \|\| \!\$\('panel'\)\.getClientRects\(\)\.length/);
  assert.match(client, /observer\.observe\(document\.getElementById\('tab-converter'\)/);
  assert.match(client, /\!state\.running/);
  assert.match(client, /devicePixelRatio/);
  assert.match(client, /macOS AppKit and GTK report logical points; Windows WebView2 uses physical client pixels/);
  assert.match(tauriWindowManager, /paths: None,/);
  assert.match(tauriWindowManager, /Do not authorize or serialize them into the webview's drop event/);
  assert.doesNotMatch(tauriWindowManager, /scopes\.allow_file\(path\)/);
  assert.match(tauriWebviewManager, /paths: None,/);
  assert.doesNotMatch(tauriWebviewManager, /scopes\.allow_(file|directory)\(path\)/);
  assert.doesNotMatch(tauriWebviewManager, /paths: Some\(paths\)/);
  assert.match(client, /async function readSelectionManifest\(selection\)/);
  assert.match(client, /ensurePipelineMatchesSelection\(pipeline, manifest\)/);
  assert.match(client, /const manifest = await readSelectionManifest\(selection\);\s+ensurePipelineMatchesSelection\(pipeline, manifest\);\s+selectPinnedPipeline\(pipeline\)/);
});
