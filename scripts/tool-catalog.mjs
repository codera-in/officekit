import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getPythonCandidates } from './run-python-tests.mjs';

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let cachedCatalogue = null;

// Reads the live merged catalogue (core registry plus slice modules) instead of
// parsing engine_comms.py source text, so counts never need hand edits.
export function loadToolCatalog({ run = spawnSync, root = repositoryRoot } = {}) {
  if (cachedCatalogue && run === spawnSync && root === repositoryRoot) return cachedCatalogue;
  for (const python of getPythonCandidates({ root })) {
    const result = run(python, ['-m', 'officekit.tool_catalog', '--json'], { cwd: root, encoding: 'utf8' });
    if (result.error || result.status !== 0) continue;
    const catalogue = JSON.parse(result.stdout);
    if (run === spawnSync && root === repositoryRoot) cachedCatalogue = catalogue;
    return catalogue;
  }
  throw new Error('Could not load the tool catalogue; python3 must be able to import officekit.');
}

// Slice assets register UI destinations with one `id: { tab: '…', … },` line each.
export const SLICE_KEYS = Object.freeze(['calculators', 'developer', 'files', 'image', 'pdf_tools', 'invoices']);

export const sliceAssetPath = (slice, extension = 'js') => `assets/officekit-slice-${slice.replace('_', '-')}.${extension}`;

export function parseSliceDestinations(source) {
  const block = source.match(/destinations: \{\n([\s\S]*?)\n\s*\},?\n/)?.[1] || '';
  return [...block.matchAll(/^\s+([a-z][a-z0-9_]*): \{ tab: '([^']+)'([^}]*)\},?$/gm)];
}
