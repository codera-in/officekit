// Read-only inventory; it creates evidence scaffolding, never invents acceptance passes.
import { readFile, writeFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { loadToolCatalog, parseSliceDestinations, SLICE_KEYS, sliceAssetPath } from './tool-catalog.mjs';

const root = resolve(import.meta.dirname, '..');
const output = resolve(root, 'docs/ui-research/tool-acceptance-matrix.md');
try {
  const existing = await readFile(output, 'utf8');
  if (!process.argv.includes('--refresh-scaffold')) throw Error('Matrix already exists; use --refresh-scaffold only for an unreviewed scaffold');
  const rows = existing.split('\n').filter(line => /^\| [a-z][a-z0-9_]+ ·/.test(line));
  if (!rows.length || rows.some(line => !line.endsWith('| Pending | Pending / Pending | Pending | Pending | Pending | Pending | Not checked |'))) throw Error('Existing acceptance evidence must be retained; write a separate audit instead');
} catch (error) { if (error.code !== 'ENOENT') throw error; }
let tools;
let inventorySource;
if (process.env.OFFICEKIT_AUDIT_API_URL) {
  const base = new URL(process.env.OFFICEKIT_AUDIT_API_URL);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname) || base.protocol !== 'http:') throw Error('Only a local authenticated API may be audited');
  const response = await fetch(new URL('/api/tools/search', base), {
    headers: process.env.OFFICEKIT_AUDIT_API_TOKEN ? { Authorization: `Bearer ${process.env.OFFICEKIT_AUDIT_API_TOKEN}` } : {},
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw Error(`Registry request failed (${response.status})`);
  tools = (await response.json()).tools;
  inventorySource = 'Authenticated local API registry';
} else {
  tools = loadToolCatalog().tools;
  inventorySource = 'Source registry via python3 -m officekit.tool_catalog (not an installed API verification)';
}
if (!Array.isArray(tools) || !tools.every(tool => typeof tool.id === 'string' && typeof tool.name === 'string' && typeof tool.tab === 'string') || new Set(tools.map(tool => tool.id)).size !== tools.length) throw Error('Invalid registry');
const frontend = await readFile(resolve(root, 'index.html'), 'utf8');
const destinationLiteral = frontend.match(/const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{([\s\S]*?)\n\s*\}\);/)?.[1];
if (!destinationLiteral) throw Error('Frontend destination map changed; inspect real routing before auditing');
const destinations = new Map();
const sliceDestinationLines = await Promise.all(SLICE_KEYS.map(slice => readFile(resolve(root, sliceAssetPath(slice)), 'utf8')))
  .then(sources => sources.flatMap(parseSliceDestinations).map(match => match[0]).join('\n'));
for (const match of `${destinationLiteral}\n${sliceDestinationLines}`.matchAll(/^\s*([a-z][a-z0-9_]*):\s*\{([^{}]+)\},?\s*$/gm)) {
  const fields = [...match[2].matchAll(/([a-zA-Z][a-zA-Z0-9]*):\s*'([^']*)'/g)];
  if (!fields.length || fields[0][1] !== 'tab') throw Error('Unrecognized frontend destination');
  destinations.set(match[1], Object.fromEntries(fields.map(field => [field[1], field[2]])));
}
if (tools.some(tool => !destinations.has(tool.id))) throw Error('A registry tool has no parsed frontend destination; inspect routing');
const routeText = tool => {
  const route = destinations.get(tool.id);
  const fields = Object.entries(route).filter(([name]) => name !== 'accept').map(([name, value]) => `${name}=${value}`).join('; ');
  return `${fields}${route.tab !== tool.tab ? ` (registry tab ${tool.tab} differs)` : ''}`;
};
const revision = execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const dirty = Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim());
const identities = [];
for (const [label, file] of [['Installed native executable', '/Applications/OfficeKit.app/Contents/MacOS/officekit'], ['Installed sidecar', '/Applications/OfficeKit.app/Contents/MacOS/officekit-backend']]) {
  try {
    const bytes = await readFile(file);
    const metadata = await stat(file);
    identities.push(`- ${label}: SHA-256 \`${createHash('sha256').update(bytes).digest('hex')}\`; modified ${metadata.mtime.toISOString()}.`);
  } catch { identities.push(`- ${label}: unavailable; installed acceptance remains pending.`); }
}
const escape = text => String(text).replace(/\|/g, '\\|').replace(/[\r\n]/g, ' ');
const fixture = tool => /PDF|Documents/.test(tool.category) ? 'Disposable document: valid / corrupt / oversized; unchanged original' : /Images/.test(tool.category) ? 'Disposable image: valid / corrupt / boundary dimensions; unchanged original' : /File|Storage/.test(tool.category) ? 'Disposable selected files/folder: normal / empty / changed identity / denied scope' : /Audio/.test(tool.category) ? 'Approved speech fixture: short / long / no speech / denied permission' : 'Known-value normal / invalid / boundary input';
const lines = ['# OfficeKit tool acceptance matrix', '', `Generated ${new Date().toISOString()} by scripts/officekit-tool-audit.mjs. Source ${revision}${dirty ? ' (dirty tree)' : ''}.`, '',
  `Inventory: ${inventorySource}. ${tools.length} tools. Destinations come from the frontend OFFICEKIT_TOOL_DESTINATIONS map, including operation/focus fields; mismatched legacy registry tabs are flagged. Actual navigation, task synonyms and result capabilities still require verification.`, '',
  'This is an acceptance ledger scaffold. **No generated row is a pass.** The presence of implementation or a test filename does not establish installed behavior. Retain completed evidence before regenerating this file.', '',
  '## Installed identity', '', ...identities, '', 'Bundle version alone is insufficient; these hashes identify files read at audit time, not the running process. Native interaction, microphone, clipboard, tray, installed CSP and package equality remain pending.', '',
  '## Per-tool checks', '', '| Tool ID / name | Actual frontend destination | Fixture to run | Search and synonyms | Valid / invalid input | Complete output | Copy | Download | Keyboard / layout | Installed evidence |',
  '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
  ...tools.map(tool => `| ${escape(tool.id)} · ${escape(tool.name)} | ${escape(routeText(tool))} | ${fixture(tool)} | Pending | Pending / Pending | Pending | Pending | Pending | Pending | Not checked |`), '',
  '## Result capability verification', '', 'For each computed result, record the actual full-data adapter and supported formats. Text/number results need complete Copy and Download; table exports preserve all rows and CSV formula safety; binary outputs need relevant file download and an explicitly labelled summary copy or rendered image copy where appropriate. Actions with no computed result require honest success/cancellation instead of artificial exports.', '',
  'For every row verify failure clearing, pending status, clipboard denial, save cancellation, large-copy limits and stale-input separation. A preview-only or truncated copy fails the complete-output check. Use the repository officekit-ux-verification skill for design and installed evidence modes.', ''];
await writeFile(output, lines.join('\n'), { flag: process.argv.includes('--refresh-scaffold') ? 'w' : 'wx' });
console.log(`Wrote ${tools.length} pending tool rows to ${output}`);
