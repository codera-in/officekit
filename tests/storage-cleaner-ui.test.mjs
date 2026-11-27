import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source=fs.readFileSync('assets/officekit-storage.js','utf8');
const context=vm.createContext({Intl,Date,Set,Map,console});
vm.runInContext(source,context);
const candidate={id:'candidate-1',name:'old.zip',path:'/Users/demo/Downloads/old.zip',category:'downloads',sizeBytes:20,modifiedAt:100,createdAt:null,method:'trash',eligible:true,reason:'Old download',impact:'Review personal file.'};
const volume={path:'/',capacityBytes:1000,usedBytes:800,availableBytes:200,logicalBytes:20,categories:[{id:'documents',sizeBytes:20},{id:'unclassified',sizeBytes:780},{id:'available',sizeBytes:200}],logicalCategories:[{id:'documents',sizeBytes:20}],unclassifiedUsedBytes:780,categoryBasis:'allocated-estimate'};
const largestFile={path:candidate.path,name:candidate.name,sizeBytes:20,fileCount:1,modifiedAt:100,createdAt:null,partial:false};
const report={scope:'system',volumes:[volume],categories:[{id:'documents',sizeBytes:20}],logicalBytes:20,candidates:[candidate],coverage:[{path:'/',state:'partial',reason:'Permission denied.',inaccessibleCount:1}],complete:false,entriesScanned:2,tools:[{id:'docker',available:true,cleanupSupported:false,reason:'Remote context excluded.',cachePath:null,impact:null}],mutationSupported:true,limitations:['Category estimates.'],largestFiles:[largestFile],largestFolders:[{...largestFile,path:'/Users/demo/Downloads',name:'Downloads',partial:true}]};
report.tools[0].usage=[];
function clone(value){return structuredClone(value);}

test('storage DTO accepts partial coverage and capacity-reconciling category estimates',()=>{
  assert.equal(context.officekitStorageValidateReport(report),report);
  assert.equal(context.officekitStorageValidateScan({id:'scan-1',state:'ready',progress:100,entriesScanned:report.entriesScanned,candidateCount:report.candidates.length,candidateBytes:report.candidates.reduce((sum,item)=>sum+item.sizeBytes,0),report,error:null}).report,report);
  const linux=clone(report);linux.mutationSupported=false;linux.candidates[0].eligible=false;linux.candidates[0].method='unsupported';assert.equal(context.officekitStorageValidateReport(linux),linux);
});
test('storage rejects corrupt capacity, duplicate IDs and unsafe response additions',()=>{
  const invalid=[];let value=clone(report);value.volumes[0].capacityBytes=999;invalid.push(value);
  value=clone(report);value.volumes[0].categories[0].sizeBytes=21;invalid.push(value);
  value=clone(report);value.volumes[0].categories[1].sizeBytes=779;value.volumes[0].categories[2].sizeBytes=201;invalid.push(value);
  value=clone(report);value.candidates.push({...candidate});invalid.push(value);
  value=clone(report);value.tools[0].command=['rm','-rf'];invalid.push(value);
  value=clone(report);value.candidates[0].sizeBytes=-1;invalid.push(value);
  value=clone(report);value.candidates[0].method='unsupported';invalid.push(value);
  for(const item of invalid)assert.throws(()=>context.officekitStorageValidateReport(item),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateScan({id:'scan-1',state:'ready',progress:100,entriesScanned:0,candidateCount:0,candidateBytes:0,report:null,error:null}),/inconsistent/);
});
test('largest-entry DTO distinguishes files from partial recursive folders and rejects authority fields',()=>{
  assert.equal(context.officekitStorageValidateLargest(report.largestFiles,true),report.largestFiles);
  assert.equal(context.officekitStorageValidateLargest(report.largestFolders,false),report.largestFolders);
  assert.throws(()=>context.officekitStorageValidateLargest([{...largestFile,candidateId:'grant-1'}],true),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateLargest([{...largestFile,fileCount:2}],true),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateLargest([{...largestFile,partial:true}],true),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateLargest([largestFile,{...largestFile,path:'/b',sizeBytes:21}],true),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateLargest(Array.from({length:101},(_,index)=>({...largestFile,path:`/${index}`})),true),/inconsistent/);
});
test('Docker usage is bounded read-only data with unknown metrics distinct from zero',()=>{
  const tool={...report.tools[0],usage:[{id:'volumes',label:'Local Volumes',totalCount:2,activeCount:1,sizeBytes:1000,reclaimableBytes:null}]};assert.equal(context.officekitStorageValidateTool(tool),tool);
  assert.throws(()=>context.officekitStorageValidateTool({...tool,id:'npm'}),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateTool({...tool,usage:[{...tool.usage[0],cleanupId:'grant'}]}),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateTool({...tool,usage:[{...tool.usage[0],reclaimableBytes:-1}]}),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateTool({...tool,usage:Array(17).fill(tool.usage[0])}),/inconsistent/);
});
test('only regenerable, eligible candidates count as safe to remove',()=>{
  assert.equal(context.officekitStorageIsSafe({...candidate,category:'caches'}),true);
  assert.equal(context.officekitStorageIsSafe({...candidate,category:'developer'}),true);
  assert.equal(context.officekitStorageIsSafe({...candidate,category:'caches',eligible:false}),false);
  assert.equal(context.officekitStorageIsSafe({...candidate,category:'caches',impact:'May remove cached project snapshots or conversation history; close the application before cleaning.'}),false);
  for(const category of ['system','applications','unclassified'])assert.equal(context.officekitStorageIsSafe({...candidate,category}),false);
  assert.equal(context.officekitStorageCount(1,'item'),'1 item');assert.equal(context.officekitStorageCount(2,'item'),'2 items');
  for(const category of ['downloads','documents','media','other'])assert.equal(context.officekitStorageIsSafe({...candidate,category}),false);
  assert.equal(context.officekitStorageSum([{sizeBytes:2},{sizeBytes:5}]),7);
});
test('permission bridge only accepts an explicit opened state',()=>{
  assert.equal(context.officekitStorageValidatePermissions({state:'opened'}).state,'opened');assert.throws(()=>context.officekitStorageValidatePermissions({state:'granted'}),/inconsistent/);assert.throws(()=>context.officekitStorageValidatePermissions({state:'opened',permission:true}),/inconsistent/);
});
test('cleanup plan pins exact eligible individual selection and estimate',()=>{
  const plan={id:'plan-1',expiresAt:Date.now()/1000+300,items:[candidate],estimatedBytes:20,impact:'Move to Trash.'};
  assert.equal(context.officekitStorageValidatePlan(plan,new Set(['candidate-1'])),plan);
  assert.throws(()=>context.officekitStorageValidatePlan(plan,new Set(['other'])),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidatePlan({...plan,expiresAt:1},new Set(['candidate-1'])),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidatePlan({...plan,estimatedBytes:21},new Set(['candidate-1'])),/inconsistent/);
  const duplicate={...plan,items:[candidate,candidate],estimatedBytes:40};assert.throws(()=>context.officekitStorageValidatePlan(duplicate,new Set(['candidate-1','other'])),/inconsistent/);
});
test('partial cleanup results account for every selected item and allow negative measured change',()=>{
  const plan={id:'plan-1',items:[candidate]};const result={id:'plan-1',items:[{id:'candidate-1',status:'skipped',sizeBytes:0,message:'Changed.'}],movedBytes:0,measuredFreeSpaceChangeBytes:-100,trashOccupancyIncreaseBytes:0,reclaimedBytes:0};
  assert.equal(context.officekitStorageValidateOutcome(result,plan),result);
  assert.throws(()=>context.officekitStorageValidateOutcome({...result,items:[]},plan),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateOutcome({...result,id:'wrong'},plan),/inconsistent/);
  assert.throws(()=>context.officekitStorageValidateOutcome({...result,items:[{...result.items[0],id:'other'}]},plan),/inconsistent/);
});
test('system storage ships through the existing destination and opaque native actions',()=>{
  assert.match(fs.readFileSync('index.html','utf8'),/assets\/officekit-storage\.js/);
  assert.match(fs.readFileSync('scripts/build-ui-assets.mjs','utf8'),/officekit-storage\.js/);
  assert.match(fs.readFileSync('assets/officekit-files.js','utf8'),/officekitStorageOpen\(action\)/);
  assert.match(source,/storage_scan_start',\{olderThanDays:age\}/);
  assert.match(source,/storage_cleanup_apply',\{planId:plan\.id\}/);
  assert.doesNotMatch(source,/innerHTML|window\.confirm|window\.alert/);
});
test('largest-file metadata remains readable and report actions stay after the rows',()=>{
  const styles=fs.readFileSync('assets/officekit.input.css','utf8');
  assert.match(source,/ok-storage-largest-files/);
  assert.match(styles,/\.ok-storage-largest-files, \.ok-storage-largest-folders \{ min-width: 900px;/);
  assert.match(styles,/\.ok-file-report-table th \{ white-space: nowrap; \}/);
  assert.match(styles,/#storage-candidates > \.officekit-result-actions \{ position: static;/);
  assert.match(styles,/\.ok-storage-confirm-status/);
  assert.match(styles,/\.ok-storage-group-toolbar/);
  assert.match(source,/storage-confirm-status/);
  assert.match(source,/storage-select-group-/);
  assert.match(source,/officekitStorageSelectCategory/);
  assert.match(source,/showAppFeedbackToast/);
});
test('byte labels distinguish missing data from zero',()=>{
  assert.equal(context.officekitStorageBytes(0),'0 B');assert.equal(context.officekitStorageBytes(null),'Unavailable');assert.equal(context.officekitStorageBytes(-1),'Unavailable');assert.match(context.officekitStorageBytes(1234),/1\.2 KB/);
});
test('storage HTTP errors provide recovery for authentication, permissions and expired plans',async()=>{
  const client=vm.createContext({Intl,Date,Set,Map,officekitApiUrl:path=>path});vm.runInContext(source,client);
  for(const [status,message]of [[401,/expired/],[403,/native permission/],[404,/Analyse storage again/],[409,/plan changed or expired/],[422,/invalid/]]){
    client.fetch=async()=>({ok:false,status,json:async()=>({detail:[]})});await assert.rejects(client.officekitStorageRequest('/api/storage-cleanup-plans'),message);
  }
  client.fetch=async()=>({ok:false,status:422,json:async()=>({detail:'Selection changed; scan again.'})});await assert.rejects(client.officekitStorageRequest('/api/storage-cleanup-plans'),/Selection changed/);
});
