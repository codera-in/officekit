import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('shared action titles match the catalog names for mapped tool results', () => {
  const titles = [
    ["toolId:'pdf_table_extractor',title:'Extract PDF Tables'", 'pdf tables'],
    ["'Extract PDF Text','pdf_text_extract'", 'PDF text'],
    ["'Color Converter','color_converter'", 'color conversion'],
    ["'CPU & Memory Overview','system_resources'", 'system resources'],
    ["'System Information','system_info'", 'system information'],
    ["'Strip EXIF & GPS Metadata'", 'EXIF and GPS metadata'],
    ["'Resize Images'", 'image resize'],
    ["'URL Encoder & Decoder'", 'URL codec'],
    ["'Spreadsheet & Data Converter','data_converter'", 'data conversion'],
    ["'Universal Image Converter'", 'image conversion'],
    ["toolId:'password_generator',title:'Password & Passphrase Generator'", 'password generation'],
    ["'Find & Mask Personal Information'", 'PII preparation'],
  ];
  for (const [source, label] of titles) assert.ok(html.includes(source), `missing catalog title for ${label}`);
  const workspace = readFileSync(new URL('../assets/officekit-workspace.js', import.meta.url), 'utf8');
  assert.match(workspace, /function officekitPublishBinaryResult\(container,blob,fileName,title,copyImage=false,toolId=fileName\)/);
  assert.ok(html.includes("officekitPublishBinaryResult(panel,blob,outputName,'Universal Image Converter',['png','jpg','jpeg'].includes(submittedTargetFormat),'image_converter')"));
  assert.ok(html.includes("officekitPublishBinaryResult(status.parentElement,output.blob,output.name,'Strip EXIF & GPS Metadata',output.blob.type==='image/png'||output.blob.type==='image/jpeg','image_exif_strip')"));
  assert.ok(html.includes("officekitPublishBinaryResult(document.querySelector('#image-resize-action-dock .ok-action-dock__controls'),result.blob,result.name,'Resize Images',!result.batch&&(result.blob.type==='image/png'||result.blob.type==='image/jpeg'),'image_resize')"));
});

test('tool selection refreshes the shared action title after updating the active tool', () => {
  const start = html.indexOf('function selectSearchTool(toolId)');
  const end = html.indexOf('\n        let voiceToolPanel', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const selection = html.slice(start, end);
  const activeTool = selection.indexOf('globalThis.officekitActiveToolId = canonicalId;');
  const activeTitle = selection.indexOf("globalThis.officekitActiveToolTitle = (typeof allToolsCache !== 'undefined' ? allToolsCache : []).find(tool => tool.id === canonicalId)?.name || '';", activeTool);
  const refresh = selection.lastIndexOf('window.OfficeKitToolActions?.refresh?.();');
  const completed = selection.indexOf('return true;', refresh);
  assert.ok(activeTool >= 0 && activeTitle > activeTool, 'set the active tool title after its ID');
  assert.ok(refresh > activeTitle && completed > refresh, 'refresh the shared bar before selection returns');
});

test('PDF task selection refreshes the shared dock with the selected task title', () => {
  const start = html.indexOf('function openPdfTool(tool, recordRecent = true)');
  const end = html.indexOf('\n        function ', start + 1);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const selection = html.slice(start, end);
  const activeTitle = selection.lastIndexOf('globalThis.officekitActiveToolTitle = allToolsCache.find(item => item.id === copy.id)?.name || copy.title;');
  const refresh = selection.indexOf('window.OfficeKitToolActions?.refresh?.();', activeTitle);
  const status = selection.indexOf("setPdfWorkbenchStatus('Select a PDF to begin.');", refresh);
  assert.ok(activeTitle >= 0, 'set the selected PDF task title');
  assert.ok(refresh > activeTitle, 'refresh the shared action dock after setting the task title');
  assert.ok(status > refresh, 'refresh the title before publishing the new task state');
});

test('developer operation changes update the active tool identity and shared dock title', () => {
  const start = html.indexOf('function updateDeveloperToolsMode()');
  const end = html.indexOf('\n        async function runDeveloperTools()', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const update = html.slice(start, end);
  assert.match(update, /decode_jwt:\s*'jwt_inspector'/);
  assert.match(update, /hashes:\s*'crypto_hashes'/);
  assert.match(update, /text_metrics:\s*'text_metrics'/);
  assert.match(update, /text_case:\s*'text_case'/);
  assert.match(update, /timestamp_convert:\s*'timestamp_converter'/);
  assert.match(update, /globalThis\.officekitActiveToolId = activeToolId;[\s\S]*globalThis\.officekitActiveToolTitle = operation === 'base64_encode' \|\| operation === 'base64_decode'[\s\S]*window\.OfficeKitToolActions\?\.refresh\(\)/);
});

test('catalog completion repairs the shared action title for a tool opened before search finishes', () => {
  const gallery = html.match(/async function loadToolGallery\(\)[\s\S]*?\n        \}/)?.[0] ?? '';
  assert.match(gallery, /allToolsCache = await fetchToolSearchResults\(''\)/);
  assert.match(gallery, /allToolsCache\.find\(tool => tool\.id === globalThis\.officekitActiveToolId\)/);
  assert.match(gallery, /globalThis\.officekitActiveToolTitle = activeTool\.name;[\s\S]*OfficeKitToolActions\?\.refresh\(\)/);
});

test('shared dock action discovery inherits the publishing tool scope', () => {
  const actions = readFileSync(new URL('../assets/officekit-tool-actions.js', import.meta.url), 'utf8');
  assert.match(actions, /element\.closest\('\[data-officekit-action-for\]'\)/);
  assert.match(actions, /if \(!logicalVisible\(button\) \|\| !appliesToActiveTool\(button\)/);
  assert.match(actions, /const directFileResult = active\?\.id === 'tab-workspace' && !!result;/);
  assert.match(actions, /if \(directFileResult && intakeAction\) continue;/);
  assert.match(actions, /\|copy\|paste\|save result/);
});

test('invoice workspace folder actions are docked as one three-action group', () => {
  const actions = readFileSync(new URL('../assets/officekit-tool-actions.js', import.meta.url), 'utf8');
  const invoices = readFileSync(new URL('../assets/officekit-slice-invoices.js', import.meta.url), 'utf8');
  assert.match(actions, /\.ok-invoice-actions,\.ok-invoice-folder-actions,\.ok-trash-dock/);
  assert.match(invoices, /const controls = element\('div', '', 'ok-invoice-folder-actions', screen\);/);
  assert.match(invoices, /state\.library\.status === 'ready' \? 'Choose folder'/);
  assert.match(invoices, /action\('Create backup'/);
  assert.match(invoices, /action\('Restore backup'/);
});

test('approved Image ↔ Data URI malformed-image recovery stays editable and reports in the shared action area', () => {
  const image = readFileSync(new URL('../assets/officekit-slice-image.js', import.meta.url), 'utf8');
  assert.match(image, /input\?\.setAttribute\('aria-invalid', 'true'\)[\s\S]*?setStatus\(error\.message, \{ error: true \}\)/);
  // The browser baseline spec was never committed; its checks run once it exists.
  const specUrl = new URL('../ui-tests/tool-unification-baseline.spec.mjs', import.meta.url);
  if (!existsSync(specUrl)) return;
  const browserSpec = readFileSync(specUrl, 'utf8');
  const recovery = browserSpec.slice(browserSpec.indexOf("test('image data URI encodes"), browserSpec.indexOf("test('", browserSpec.indexOf("test('image data URI encodes") + 6));
  assert.match(recovery, /image_data_uri-malformed-recovery/);
  assert.match(recovery, /\.ok-action-dock__status/);
  assert.match(recovery, /toHaveText\('The file contents do not match its image type\.'\)/);
  assert.match(recovery, /\[data-param=data_uri\][\s\S]*?toHaveAttribute\('aria-invalid', 'true'\)/);
  assert.match(recovery, /\[data-action=save-decode\][\s\S]*?toBeEnabled\(\)/);
});
