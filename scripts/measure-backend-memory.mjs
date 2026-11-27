import { spawn, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const durationSeconds = Number(process.env.OFFICEKIT_MEMORY_IDLE_SECONDS ?? 10);
const runs = Number(process.env.OFFICEKIT_MEMORY_RUNS ?? 3);
const python = process.env.PYTHON ?? 'python3';
const backend = process.env.OFFICEKIT_BACKEND_BENCH_EXECUTABLE;

if (!['darwin', 'linux'].includes(process.platform)) {
  throw new Error('The backend memory benchmark requires macOS or Linux ps.');
}
if (!Number.isInteger(durationSeconds) || durationSeconds < 0 || durationSeconds > 300 ||
    !Number.isInteger(runs) || runs < 1 || runs > 10) {
  throw new Error('Set idle seconds to 0–300 and run count to 1–10.');
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8' });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message ?? result.stderr ?? `${command} exited ${result.status}`);
  }
  return result.stdout.trim();
}

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}

function processTreeMemory(rootPid) {
  const rows = run('ps', ['-axo', 'pid=,ppid=,rss='])
    .split('\n').map(line => line.trim().split(/\s+/).map(Number))
    .filter(row => row.length === 3 && row.every(Number.isFinite));
  const childrenByParent = new Map();
  for (const [pid, parent, rss] of rows) {
    if (!childrenByParent.has(parent)) childrenByParent.set(parent, []);
    childrenByParent.get(parent).push({ pid, rss });
  }
  const pending = [rootPid];
  const seen = new Set();
  let totalKb = 0;
  while (pending.length) {
    const pid = pending.pop();
    if (seen.has(pid)) continue;
    seen.add(pid);
    const row = rows.find(candidate => candidate[0] === pid);
    if (row) totalKb += row[2];
    for (const child of childrenByParent.get(pid) ?? []) pending.push(child.pid);
  }
  return { processCount: seen.size, rssMb: Math.round(totalKb / 1024 * 10) / 10 };
}

async function waitForHealth(url, child, token) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Backend exited early (${child.exitCode}).`);
    try {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(1000),
      });
      if (response.ok) return;
    } catch (_) {
      // The backend is still starting.
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('Backend did not become healthy within 120 seconds.');
}

async function exercisePdfRoutes(origin, token) {
  const content = 'BT /F1 12 Tf 72 720 Td (OfficeKit memory benchmark) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
  ];
  const parts = ['%PDF-1.4\n'];
  const offsets = [0];
  let byteLength = Buffer.byteLength(parts[0]);
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(byteLength);
    const part = `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
    parts.push(part);
    byteLength += Buffer.byteLength(part);
  }
  const xrefOffset = byteLength;
  parts.push(`xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`);
  for (const offset of offsets.slice(1)) parts.push(`${String(offset).padStart(10, '0')} 00000 n \n`);
  parts.push(`trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`);
  const source = Buffer.from(parts.join(''), 'ascii');
  const headers = { Authorization: `Bearer ${token}` };
  for (const route of ['/api/pdf/text', '/api/pdf/tables']) {
    const form = new FormData();
    form.set('file', new Blob([source], { type: 'application/pdf' }), 'memory-benchmark.pdf');
    const response = await fetch(`${origin}${route}`, { method: 'POST', headers, body: form });
    if (!response.ok) throw new Error(`${route} returned HTTP ${response.status}: ${await response.text()}`);
    await response.arrayBuffer();
  }
}

async function exerciseStatementRoutes(origin, token) {
  const form = new FormData();
  form.set('file', new Blob([
    'Date,Description,Amount,Balance\n2024-01-01,Opening Balance,,100.00\n2024-01-02,Coffee,-2.50,97.50\n',
  ], { type: 'text/csv' }), 'memory-benchmark.csv');
  const headers = { Authorization: `Bearer ${token}` };
  const response = await fetch(`${origin}/api/extract/statement`, { method: 'POST', headers, body: form });
  if (!response.ok) throw new Error(`/api/extract/statement returned HTTP ${response.status}: ${await response.text()}`);
  const result = await response.json();
  const exported = await fetch(`${origin}/api/export/csv`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(result),
  });
  if (!exported.ok) throw new Error(`/api/export/csv returned HTTP ${exported.status}: ${await exported.text()}`);
  await exported.arrayBuffer();
}

async function measureOnce(runNumber) {
  const port = await freePort();
  const token = randomUUID();
  const child = spawn(backend ?? python, backend ? [] : [path.join(root, 'backend_main.py')], {
    cwd: root,
    stdio: ['ignore', 'ignore', 'pipe'],
    env: {
      ...process.env,
      OFFICEKIT_API_PORT: String(port),
      OFFICEKIT_API_TOKEN: token,
      OFFICEKIT_RELEASE_PROFILE: 'development',
    },
  });
  let stderr = '';
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr = `${stderr}${chunk}`.slice(-4000); });
  try {
    await waitForHealth(`http://127.0.0.1:${port}/api/health`, child, token);
    await new Promise(resolve => setTimeout(resolve, 2000));
    const afterStartup = processTreeMemory(child.pid);
    await new Promise(resolve => setTimeout(resolve, durationSeconds * 1000));
    const afterIdle = processTreeMemory(child.pid);
    await exercisePdfRoutes(`http://127.0.0.1:${port}`, token);
    const afterPdfRoutes = processTreeMemory(child.pid);
    await exerciseStatementRoutes(`http://127.0.0.1:${port}`, token);
    const afterStatementRoutes = processTreeMemory(child.pid);
    return { run: runNumber, afterStartup, afterIdle, afterPdfRoutes, afterStatementRoutes };
  } catch (error) {
    throw new Error(`${error.message}${stderr ? `\n${stderr}` : ''}`);
  } finally {
    child.kill('SIGTERM');
    await Promise.race([
      new Promise(resolve => child.once('exit', resolve)),
      new Promise(resolve => setTimeout(resolve, 5000)),
    ]);
    if (child.exitCode === null) child.kill('SIGKILL');
  }
}

const results = [];
for (let index = 1; index <= runs; index += 1) results.push(await measureOnce(index));
const median = values => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const summary = {
  backend: backend ?? `${python} backend_main.py`,
  idleSeconds: durationSeconds,
  runs,
  samples: results,
  medianStartupRssMb: median(results.map(result => result.afterStartup.rssMb)),
  medianIdleRssMb: median(results.map(result => result.afterIdle.rssMb)),
  medianAfterPdfRoutesRssMb: median(results.map(result => result.afterPdfRoutes.rssMb)),
  medianAfterStatementRoutesRssMb: median(results.map(result => result.afterStatementRoutes.rssMb)),
  medianIdleProcessCount: median(results.map(result => result.afterIdle.processCount)),
};
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
