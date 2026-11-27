// Exercise the packaged API with disposable originals; never invoke Trash.
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {installSmokeEntitlement, resolveSmokeBinary} from './smoke-backend-sidecar.mjs';

const target = spawnSync('rustc', ['--print', 'host-tuple'], {encoding:'utf8'});
assert.equal(target.status, 0);
const binary = process.argv[2] || resolveSmokeBinary({targetTriple:target.stdout.trim()});
const listener = net.createServer();
await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = listener.address().port;
await new Promise(resolve => listener.close(resolve));
const token = randomUUID(), native = randomUUID();
const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-packaged-duplicates-'));
const root = await fs.realpath(temp);
for (const name of ['Project', 'Project backup', 'Changed']) {
  await fs.mkdir(path.join(root, name, 'empty'), {recursive:true});
  await fs.writeFile(path.join(root, name, 'file.txt'), name === 'Changed' ? 'different' : 'identical');
}
const child = spawn(binary, [], {stdio:['ignore','ignore','pipe'], env:{...process.env,
  OFFICEKIT_API_PORT:String(port), OFFICEKIT_API_TOKEN:token,
  OFFICEKIT_NATIVE_GRANT_TOKEN:native}});
let spawnError;
let startupDiagnostic='';
child.stderr.on('data', chunk => {startupDiagnostic=(startupDiagnostic+String(chunk)).slice(-1500);});
child.on('error', error => {spawnError=error;});
async function request(route, body, nativeAuthority = false) {
  const response = await fetch(`http://127.0.0.1:${port}/api/${route}`, {
    method:body === undefined ? 'GET' : 'POST',
    headers:{authorization:`Bearer ${token}`, origin:'tauri://localhost', 'Content-Type':'application/json',
      ...(nativeAuthority ? {'X-OfficeKit-Native-Grant':native} : {})},
    body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(5000),
  });
  assert.ok(response.ok, `${route}: HTTP ${response.status}`);
  return response.json();
}
async function scan(selection, matchKind) {
  const job = await request('file-jobs', {kind:'duplicates', selectionIds:[selection], options:{matchKind}});
  for (let attempt=0; attempt<100; attempt++) {
    const status = await request(`file-jobs/${job.id}`);
    if (status.state === 'ready') return {id:job.id, report:await request(`file-jobs/${job.id}/results?format=json`)};
    assert.ok(!['failed','cancelled'].includes(status.state));
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw Error('Packaged duplicate scan timed out');
}
try {
  let ready=false;
  let lastError;
  const startupDeadline=Date.now()+45000;
  while (Date.now()<startupDeadline) {
    if (spawnError) throw spawnError;
    assert.equal(child.exitCode, null, 'Packaged backend exited early');
    try { ready=(await request('health')).status === 'ok'; } catch(error) {lastError=error.message;}
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, `Packaged backend did not start: ${lastError || 'invalid health response'} ${startupDiagnostic}`);
  await installSmokeEntitlement({origin:`http://127.0.0.1:${port}`, token, grantToken:native});
  const selection=await request('file-selections', {paths:[root], access:'read'}, true);
  const files=await scan(selection.id, 'files');
  assert.equal(files.report.include_subfolders, true);
  assert.equal(files.report.files_scanned, 3);
  assert.equal(files.report.groups.length, 1);
  assert.ok(path.isAbsolute(files.report.groups[0].entries[0].full_path));
  const folders=await scan(selection.id, 'folders');
  assert.equal(folders.report.match_kind, 'folders');
  assert.equal(folders.report.trash_supported, false);
  const pair=folders.report.groups.find(group => group.files.includes('Project'));
  assert.deepEqual([...pair.files].sort(), ['Project', 'Project backup']);
  const entry=pair.entries.find(item => item.name === 'Project');
  const revealed=await request(`file-jobs/${folders.id}/reveals`, {itemId:entry.id}, true);
  assert.equal(revealed.path, path.join(root, 'Project'));
  assert.equal(await fs.readFile(path.join(root, 'Project', 'file.txt'), 'utf8'), 'identical');
  process.stdout.write('Packaged duplicate finder: recursive files, exact folders, full paths and native reveal resolution passed.\n');
} finally {
  const exited=new Promise(resolve => child.once('exit', resolve));
  child.kill('SIGTERM');
  let timer;
  await Promise.race([exited, new Promise(resolve => { timer=setTimeout(()=>{child.kill('SIGKILL');resolve();}, 5000); })]);
  clearTimeout(timer);
  await fs.rm(root, {recursive:true, force:true});
}
