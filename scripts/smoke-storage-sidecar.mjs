import { spawn, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import net from 'node:net';
import { installSmokeEntitlement, resolveSmokeBinary } from './smoke-backend-sidecar.mjs';
const listener = net.createServer();
await new Promise((resolve,reject)=>{listener.on('error',reject);listener.listen(0,'127.0.0.1',resolve);});
const port = listener.address().port;
await new Promise(resolve=>listener.close(resolve));
const target = spawnSync('rustc',['--print','host-tuple'],{encoding:'utf8'});
if(target.status!==0)throw Error('Unable to resolve sidecar target');
const binary = resolveSmokeBinary({targetTriple:target.stdout.trim()});
const token=randomUUID();
const nativeGrant=randomUUID();
const child=spawn(binary,[],{cwd:process.cwd(),stdio:'ignore',env:{...process.env,OFFICEKIT_API_PORT:String(port),OFFICEKIT_API_TOKEN:token,OFFICEKIT_NATIVE_GRANT_TOKEN:nativeGrant}});
const origin=`http://127.0.0.1:${port}`;
const headers={Authorization:`Bearer ${token}`,'Content-Type':'application/json'};
async function request(route,options={}){return fetch(origin+route,{...options,headers,signal:AbortSignal.timeout(10000)});}
try{
  let ready=false;
  for(let attempt=0;attempt<100;attempt++){
    if(child.exitCode!==null)throw Error('Sidecar exited before readiness');
    try{const result=await request('/api/health');if(result.ok){ready=true;break;}}catch{}
    await new Promise(resolve=>setTimeout(resolve,300));
  }
  if(!ready)throw Error('Sidecar failed readiness');
  await installSmokeEntitlement({origin,token,grantToken:nativeGrant});
  const checks=[
    ['/api/storage-scans',{method:'POST',body:'{"olderThanDays":90}'},403],
    ['/api/storage-scans',{method:'POST',body:'{"paths":["/"]}'},422],
    ['/api/storage-scans/missing',{},404],
    ['/api/storage-scans/missing',{method:'DELETE'},404],
    ['/api/storage-cleanup-plans',{method:'POST',body:'{"scanId":"missing","candidateIds":["missing"]}'},404],
    ['/api/storage-cleanup-plans/missing/execution',{method:'POST',body:'{}'},403],
  ];
  for(const [route,options,expected]of checks){const result=await request(route,options);if(result.status!==expected)throw Error(`Storage boundary ${route} returned ${result.status}, expected ${expected}`);}
  const spec=await(await request('/openapi.json')).json();
  for(const [model,field]of [['StorageReport','largestFiles'],['StorageReport','largestFolders'],['StorageTool','usage'],['StorageExecution','items']]){
    if(!spec.components.schemas[model]?.properties[field])throw Error(`Packaged schema lacks ${model}.${field}`);
  }
  console.log('Packaged storage API: 6 boundary checks and final typed schemas passed. No real scan or cleanup ran.');
}finally{
  child.kill('SIGTERM');
  if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill('SIGKILL');resolve();},3000).unref();});
}
