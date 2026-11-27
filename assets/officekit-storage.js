/* System storage is read through native-authorised scans; cleanup sends opaque IDs only. */
const officekitStorage = { busy: false, scan: null, report: null, selected: new Set(), plan: null, cleanupAllowed:false, activity:null, expireTimer:null };
const officekitStorageCategories = Object.freeze({ applications:'Applications', documents:'Documents', media:'Photos & media', developer:'Developer data', caches:'Caches', system:'System', other:'Other', unclassified:'Unclassified', available:'Available' });
function officekitStorageBytes(value) {
  if (!Number.isSafeInteger(value) || value < 0) return 'Unavailable';
  const units = ['B','KB','MB','GB','TB']; let amount=value, index=0;
  while (amount >= 1000 && index < units.length-1) { amount/=1000; index++; }
  return `${new Intl.NumberFormat(undefined,{maximumFractionDigits:index ? 1 : 0}).format(amount)} ${units[index]}`;
}
function officekitStorageNode(tag, text='', className='') {
  const node=document.createElement(tag); node.textContent=text; if(className)node.className=className; return node;
}
function officekitStorageButton(text, action, primary=false) {
  const button=officekitStorageNode('button',text,`btn ${primary?'btn-primary':'btn-outline'}`); button.type='button';button.onclick=action;return button;
}
function officekitStorageMount() {
  if(document.getElementById('storage-system'))return;
  const root=officekitStorageNode('section','','ok-storage');root.id='storage-system';root.hidden=true;
  const controls=officekitStorageNode('section','','ok-file-panel ok-storage-controls');
  const scopeLabel=officekitStorageNode('label','Scan '); const scope=officekitStorageNode('select','','select ');scope.id='storage-scope';
  for(const [value,name]of [['system','Entire computer · local disks'],['folder','Selected files / folder']]){const option=officekitStorageNode('option',name);option.value=value;scope.append(option);}
  scopeLabel.append(scope);scope.onchange=()=>officekitStorageScope(scope.value);
  const ageLabel=officekitStorageNode('label','Old downloads older than ');const age=officekitStorageNode('input','','input ');age.type='number';age.min='1';age.max='3650';age.value='90';age.id='storage-age';ageLabel.append(age,' days');
  const run=officekitStorageButton('Analyse storage',officekitStorageScan,true);run.id='storage-run';
  const cancel=officekitStorageButton('Cancel scan',officekitStorageCancel);cancel.id='storage-cancel';cancel.hidden=true;
  const status=officekitStorageNode('p','Scan local disks for caches, old downloads and programming leftovers.');status.id='storage-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const overview=officekitStorageNode('section','','ok-storage-overview');overview.id='storage-overview';overview.hidden=true;
  const volumes=officekitStorageNode('section');volumes.id='storage-volumes';volumes.setAttribute('aria-label','Storage by volume');
  const coverage=officekitStorageNode('details','','ok-file-panel');coverage.id='storage-coverage';coverage.append(officekitStorageNode('summary','Scan coverage and permissions'),officekitStorageNode('p','System-wide discovery reads accessible local disks. Network disks are excluded. Protected OS files and other users’ data may be unavailable.'));
  const report=officekitStorageNode('section','','ok-file-panel');report.id='storage-candidates';report.hidden=true;
  const footer=officekitStorageNode('div','','ok-storage-footer');footer.hidden=true;footer.id='storage-footer';
  const selected=officekitStorageNode('strong','0 B selected');selected.id='storage-selected';
  const reanalyse=officekitStorageButton('Analyse again',officekitStorageScan);reanalyse.id='storage-footer-reanalyse';reanalyse.className='btn btn-outline btn-sm';
  const review=officekitStorageButton('Review cleanup',officekitStorageReview,true);review.id='storage-review';review.disabled=true;
  const selectSafe=officekitStorageButton('Select safe',officekitStorageSelectSafe);selectSafe.id='storage-select-safe';
  footer.append(selected,officekitStorageNode('span','Trash where supported · tool cleanup is permanent'),reanalyse,selectSafe,review);
  const outcome=officekitStorageNode('section','','ok-file-panel');outcome.id='storage-outcomes';outcome.hidden=true;
  const dialog=officekitStorageNode('dialog','','modal ok-storage-dialog');dialog.id='storage-confirm';dialog.setAttribute('aria-labelledby','storage-confirm-title');
  const dialogBox=officekitStorageNode('div','','modal-box');
  const title=officekitStorageNode('h2','Review selected cleanup');title.id='storage-confirm-title';
  const detail=officekitStorageNode('div');detail.id='storage-confirm-items';
  const back=officekitStorageButton('Back to results',()=>dialog.close());back.id='storage-confirm-back';const confirm=officekitStorageButton('Confirm cleanup',officekitStorageApply,true);confirm.id='storage-confirm-apply';
  const confirmStatus=officekitStorageNode('div','','ok-storage-confirm-status');confirmStatus.id='storage-confirm-status';confirmStatus.hidden=true;confirmStatus.setAttribute('role','status');confirmStatus.setAttribute('aria-live','polite');
  const dialogActions=officekitStorageNode('div','','modal-action');dialogActions.append(back,confirm);dialogBox.append(title,detail,confirmStatus,dialogActions);dialog.append(dialogBox);
  dialog.addEventListener('close',()=>{if(officekitStorage.expireTimer){clearTimeout(officekitStorage.expireTimer);officekitStorage.expireTimer=null;}document.getElementById('storage-review').focus();});
  controls.append(scopeLabel,ageLabel,run,cancel);root.append(controls,status,overview,volumes,coverage,report,footer,outcome,dialog);
  document.getElementById('tab-workspace').append(root);
}
function officekitStorageOpen(action) {
  officekitStorageMount();const active=action==='storage';
  document.getElementById('storage-system').hidden=!active;
  if(active){document.getElementById('storage-scope').value='system';officekitStorageScope('system');}
  else document.getElementById('direct-selections').hidden=false;
}
function officekitStorageScope(scope) {
  const folder=scope==='folder';document.getElementById('direct-selections').hidden=!folder;
  for(const id of ['storage-status','storage-overview','storage-volumes','storage-coverage','storage-candidates','storage-footer','storage-outcomes']) {
    const node=document.getElementById(id);
    if(folder){node.dataset.storageScopeHidden=String(node.hidden);node.hidden=true;}
    else if(Object.hasOwn(node.dataset,'storageScopeHidden')){node.hidden=node.dataset.storageScopeHidden==='true';delete node.dataset.storageScopeHidden;}
  }
  for(const id of ['storage-age','storage-run'])document.getElementById(id).hidden=folder;
  document.getElementById('storage-age').parentElement.hidden=folder;
  document.getElementById('direct-file-results').hidden=!(folder&&officekitDirectFilesState.report);
  document.getElementById('direct-file-title').textContent='Storage analyser & cleaner';
  document.getElementById('direct-file-description').textContent='Find what takes up space, then review what to remove.';
}
function officekitStorageStatus(text,error=false) {
  const node=document.getElementById('storage-status');
  if(!node)return;
  if (text) officekitOutcome.show(node,{state:error?'error':'info',text});
  else officekitOutcome.clear(node);
  if (text && /permission|access/i.test(text) && typeof window.__TAURI__?.core?.invoke === 'function') {
    const permBtn = document.createElement('button');
    permBtn.type = 'button';
    permBtn.className = 'btn btn-xs btn-outline ml-2 rounded-lg font-semibold';
    permBtn.textContent = 'Open System Settings →';
    permBtn.onclick = async () => {
      try { await officekitStorageNative()('storage_permissions_open'); } catch (_) {}
    };
    node.append(' ', permBtn);
  }
}
function officekitStorageBusy(busy,scanning=false) {
  officekitStorage.busy=busy;officekitDirectFilesState.busy=busy;
  for(const id of ['storage-run','storage-age','storage-scope','storage-review','storage-footer-reanalyse']){
    const el=document.getElementById(id);if(el)el.disabled=busy;
  }
  document.getElementById('storage-review').disabled=busy||!officekitStorage.selected.size;
  document.getElementById('storage-cancel').hidden=!scanning;
  const eligible=new Set(officekitStorage.cleanupAllowed?officekitStorage.report?.candidates.filter(item=>item.eligible).map(item=>item.id)||[]:[]);
  document.querySelectorAll('#storage-candidates input').forEach(input=>{
    if(input.id.startsWith('storage-select-group-')){
      const cat=input.id.replace('storage-select-group-','');
      const hasEligible=officekitStorage.cleanupAllowed&&officekitStorage.report?.candidates.some(c=>c.category===cat&&c.eligible);
      input.disabled=busy||!hasEligible;
    }else{
      input.disabled=busy||!eligible.has(input.id.replace('storage-item-',''));
    }
  });
  document.querySelectorAll('.ok-storage-group-toolbar button').forEach(button=>{
    button.disabled=busy||!officekitStorage.cleanupAllowed;
  });
  document.querySelectorAll('#storage-overview input[data-candidate]').forEach(input=>{input.disabled=busy||!eligible.has(input.dataset.candidate);});
  const selectSafe=document.getElementById('storage-select-safe');
  if(selectSafe)selectSafe.disabled=busy||!officekitStorage.cleanupAllowed||!officekitStorage.report?.candidates.some(item=>officekitStorageIsSafe(item));
}
async function officekitStorageRequest(path,options) {
  const response=await fetch(officekitApiUrl(path),options);
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}
    const messages={401:'The app connection expired. Reopen OfficeKit.',403:'This action requires native permission in the desktop app.',404:'This scan is no longer available. Analyse storage again.',409:'The cleanup plan changed or expired. Review a new plan.',422:'The storage request is invalid. Check your selection.'};
    throw Error(typeof detail==='string'?detail:messages[response.status]||'The storage operation failed. Try again.');}
  return response.json();
}
function officekitStorageNative() {
  if(typeof window.__TAURI__?.core?.invoke!=='function')throw Error('System-wide storage analysis requires the OfficeKit desktop app.');
  return tauriInvoke();
}
function officekitStorageExact(value,keys) { return !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key)); }
function officekitStorageText(value,max=4096) { return typeof value==='string'&&value.length<=max; }
function officekitStorageNumber(value) { return Number.isSafeInteger(value)&&value>=0; }
function officekitStorageId(value) { return typeof value==='string'&&/^[a-zA-Z0-9-]{1,80}$/.test(value); }
function officekitStorageInvalid() { throw Error('OfficeKit returned an inconsistent storage response. Analyse storage again.'); }
function officekitStorageValidateCandidate(item) {
  if(!officekitStorageExact(item,['id','name','path','category','sizeBytes','modifiedAt','createdAt','method','eligible','reason','impact'])||!officekitStorageId(item.id)||!officekitStorageText(item.name,1024)||!officekitStorageText(item.path)||!['downloads',...Object.keys(officekitStorageCategories)].includes(item.category)||!officekitStorageNumber(item.sizeBytes)||!Number.isFinite(item.modifiedAt)||!(item.createdAt===null||Number.isFinite(item.createdAt))||!['trash','unsupported','tool'].includes(item.method)||typeof item.eligible!=='boolean'||!officekitStorageText(item.reason)||!officekitStorageText(item.impact)||item.eligible&&item.method==='unsupported')officekitStorageInvalid();
  return item;
}
function officekitStorageValidateCategories(items) {
  if(!Array.isArray(items)||items.length>9||new Set(items.map(item=>item?.id)).size!==items.length||items.some(item=>!officekitStorageExact(item,['id','sizeBytes'])||!Object.hasOwn(officekitStorageCategories,item.id)||!officekitStorageNumber(item.sizeBytes)))officekitStorageInvalid();return items;
}
function officekitStorageValidateLargest(items,files) {
  if(!Array.isArray(items)||items.length>100)officekitStorageInvalid();
  for(const [index,item]of items.entries()) {
    if(!officekitStorageExact(item,['path','name','sizeBytes','fileCount','modifiedAt','createdAt','partial'])||!officekitStorageText(item.path)||!officekitStorageText(item.name,1024)||!officekitStorageNumber(item.sizeBytes)||!officekitStorageNumber(item.fileCount)||!Number.isFinite(item.modifiedAt)||!(item.createdAt===null||Number.isFinite(item.createdAt))||typeof item.partial!=='boolean'||files&&(item.fileCount!==1||item.partial)||index>0&&items[index-1].sizeBytes<item.sizeBytes)officekitStorageInvalid();
  }
  if(new Set(items.map(item=>item.path)).size!==items.length)officekitStorageInvalid();return items;
}
function officekitStorageValidateTool(tool) {
  if(!officekitStorageExact(tool,['id','available','cleanupSupported','reason','cachePath','impact','usage'])||!['docker','npm','yarn','pnpm','pip','uv'].includes(tool.id)||typeof tool.available!=='boolean'||typeof tool.cleanupSupported!=='boolean'||!officekitStorageText(tool.reason)||!(tool.cachePath===null||officekitStorageText(tool.cachePath))||!(tool.impact===null||officekitStorageText(tool.impact))||!Array.isArray(tool.usage)||tool.usage.length>16||tool.id!=='docker'&&tool.usage.length)officekitStorageInvalid();
  for(const item of tool.usage)if(!officekitStorageExact(item,['id','label','totalCount','activeCount','sizeBytes','reclaimableBytes'])||!['images','containers','volumes','build-cache','other'].includes(item.id)||!officekitStorageText(item.label,128)||!['totalCount','activeCount','sizeBytes','reclaimableBytes'].every(key=>item[key]===null||officekitStorageNumber(item[key])))officekitStorageInvalid();return tool;
}
function officekitStorageValidateReport(report) {
  if(!officekitStorageExact(report,['scope','volumes','categories','logicalBytes','candidates','coverage','complete','entriesScanned','tools','mutationSupported','limitations','largestFiles','largestFolders'])||report.scope!=='system'||!officekitStorageNumber(report.logicalBytes)||!officekitStorageNumber(report.entriesScanned)||typeof report.complete!=='boolean'||typeof report.mutationSupported!=='boolean'||!Array.isArray(report.volumes)||report.volumes.length>256||!Array.isArray(report.candidates)||report.candidates.length>2006||!Array.isArray(report.coverage)||report.coverage.length>256||!Array.isArray(report.tools)||report.tools.length>6||!Array.isArray(report.limitations)||report.limitations.some(item=>!officekitStorageText(item)))officekitStorageInvalid();
  officekitStorageValidateLargest(report.largestFiles,true);officekitStorageValidateLargest(report.largestFolders,false);
  officekitStorageValidateCategories(report.categories);
  if(report.categories.length>7||report.categories.reduce((sum,item)=>sum+item.sizeBytes,0)!==report.logicalBytes)officekitStorageInvalid();
  for(const volume of report.volumes){if(!officekitStorageExact(volume,['path','capacityBytes','usedBytes','availableBytes','logicalBytes','categories','logicalCategories','unclassifiedUsedBytes','categoryBasis'])||!officekitStorageText(volume.path)||!['capacityBytes','usedBytes','availableBytes','logicalBytes','unclassifiedUsedBytes'].every(key=>officekitStorageNumber(volume[key]))||volume.usedBytes+volume.availableBytes!==volume.capacityBytes||volume.unclassifiedUsedBytes>volume.usedBytes||volume.categoryBasis!=='allocated-estimate')officekitStorageInvalid();officekitStorageValidateCategories(volume.categories);officekitStorageValidateCategories(volume.logicalCategories);if(volume.categories.reduce((sum,item)=>sum+item.sizeBytes,0)!==volume.capacityBytes)officekitStorageInvalid();}
  for(const volume of report.volumes)if(volume.logicalCategories.length>7||volume.logicalCategories.reduce((sum,item)=>sum+item.sizeBytes,0)!==volume.logicalBytes||volume.categories.find(item=>item.id==='available')?.sizeBytes!==volume.availableBytes||volume.categories.find(item=>item.id==='unclassified')?.sizeBytes!==volume.unclassifiedUsedBytes)officekitStorageInvalid();
  for(const item of report.candidates)officekitStorageValidateCandidate(item);
  if(new Set(report.candidates.map(item=>item.id)).size!==report.candidates.length)officekitStorageInvalid();
  for(const item of report.coverage)if(!officekitStorageExact(item,['path','state','reason','inaccessibleCount'])||!officekitStorageText(item.path)||!['complete','partial','inaccessible'].includes(item.state)||!officekitStorageText(item.reason)||!(item.inaccessibleCount===null||officekitStorageNumber(item.inaccessibleCount)))officekitStorageInvalid();
  for(const tool of report.tools)officekitStorageValidateTool(tool);
  return report;
}
function officekitStorageValidateScan(scan) {
  if(!officekitStorageExact(scan,['id','state','progress','entriesScanned','candidateCount','candidateBytes','report','error'])||!officekitStorageId(scan.id)||!['queued','running','ready','cancelled','failed'].includes(scan.state)||!officekitStorageNumber(scan.progress)||scan.progress>100||!officekitStorageNumber(scan.entriesScanned)||!officekitStorageNumber(scan.candidateCount)||!officekitStorageNumber(scan.candidateBytes)||!(scan.error===null||officekitStorageText(scan.error)))officekitStorageInvalid();
  if(scan.report!==null)officekitStorageValidateReport(scan.report);if(scan.state==='ready'&&scan.report===null)officekitStorageInvalid();return scan;
}
function officekitStorageValidatePlan(plan,selected) {
  if(!officekitStorageExact(plan,['id','expiresAt','items','estimatedBytes','impact'])||!officekitStorageId(plan.id)||!Number.isFinite(plan.expiresAt)||plan.expiresAt<=Date.now()/1000||!Array.isArray(plan.items)||plan.items.length!==selected.size||!officekitStorageNumber(plan.estimatedBytes)||!officekitStorageText(plan.impact))officekitStorageInvalid();
  for(const item of plan.items){officekitStorageValidateCandidate(item);if(!item.eligible||!selected.has(item.id))officekitStorageInvalid();}
  if(new Set(plan.items.map(item=>item.id)).size!==plan.items.length||plan.items.reduce((sum,item)=>sum+item.sizeBytes,0)!==plan.estimatedBytes)officekitStorageInvalid();return plan;
}
function officekitStorageValidateOutcome(result,plan) {
  if(!officekitStorageExact(result,['id','items','movedBytes','measuredFreeSpaceChangeBytes','trashOccupancyIncreaseBytes','reclaimedBytes'])||result.id!==plan.id||!Array.isArray(result.items)||result.items.length!==plan.items.length||!['movedBytes','trashOccupancyIncreaseBytes','reclaimedBytes'].every(key=>officekitStorageNumber(result[key]))||!Number.isSafeInteger(result.measuredFreeSpaceChangeBytes))officekitStorageInvalid();
  const expected=new Set(plan.items.map(item=>item.id));for(const item of result.items)if(!officekitStorageExact(item,['id','status','sizeBytes','message'])||!expected.delete(item.id)||!['moved','cleaned','skipped','failed'].includes(item.status)||!officekitStorageNumber(item.sizeBytes)||!officekitStorageText(item.message))officekitStorageInvalid();return result;
}
async function officekitStorageScan() {
  if(officekitStorage.busy)return;const age=Number(document.getElementById('storage-age').value);
  if(!Number.isInteger(age)||age<1||age>3650){officekitStorageStatus('Choose an old-download threshold between 1 and 3,650 days.',true);document.getElementById('storage-age').focus();return;}
  officekitStorageBusy(true,true);officekitStorage.selected.clear();officekitStorage.plan=null;officekitStorage.report=null;officekitStorage.scan=null;officekitStorage.cleanupAllowed=false;
  for(const id of ['storage-overview','storage-candidates','storage-footer','storage-outcomes'])document.getElementById(id).hidden=true;
  document.getElementById('storage-volumes').replaceChildren();officekitStorageStatus('Discovering local disks…');
  const activity=window.OfficeKitActivity?.start({title:'Storage scan',tool:'Storage analyzer',tab:'workspace',phase:'Starting local scan',progress:0,total:null,cancel:officekitStorageCancel,returnTo:()=>switchTab('workspace')});officekitStorage.activity=activity||null;
  try{
    let scan=officekitStorageValidateScan(await officekitStorageNative()('storage_scan_start',{olderThanDays:age}));officekitStorage.scan=scan.id;
    while(true){
      officekitStorageStatus(`${scan.state==='queued'?'Waiting to scan':'Scanning local disks'}${scan.progress?` · ${scan.progress.toLocaleString()}%`:''}`);
      const candidateBytes=scan.report?scan.report.candidates.filter(item=>item.eligible).reduce((sum,item)=>sum+item.sizeBytes,0):scan.candidateBytes;
      activity?.update({phase:scan.state==='queued'?'Waiting to scan':'Scanning local disks',progress:scan.entriesScanned,total:null,percent:scan.progress||null,
        insights:[{label:'Entries checked',value:scan.entriesScanned.toLocaleString()},{label:'Cleanup candidates',value:scan.report?scan.report.candidates.filter(item=>item.eligible).length.toLocaleString():scan.candidateCount.toLocaleString()},{label:'Potential recovery',value:officekitStorageBytes(candidateBytes),detail:'logical size estimate'}]});
      if(['ready','cancelled','failed'].includes(scan.state)){
        officekitStorage.cleanupAllowed=scan.state==='ready';
        if(scan.report){officekitStorage.report=scan.report;officekitStorageRender(scan.report);}
        if(scan.state==='failed')throw Error(scan.error||'The storage scan failed. Try again.');
        const summary=scan.state==='cancelled'?'Scan cancelled. Any partial results are inspection only.':scan.report.complete?'Storage analysis complete. Select individual items to review cleanup.':'Partial analysis complete. Review coverage for skipped or inaccessible locations.';
        officekitStorageStatus(summary);activity?.finish({state:scan.state==='cancelled'?'cancelled':'complete',phase:scan.state==='cancelled'?'Cancelled':'Complete',summary,percent:100});break;
      }
      await new Promise(resolve=>setTimeout(resolve,400));scan=officekitStorageValidateScan(await officekitStorageRequest(`/api/storage-scans/${encodeURIComponent(scan.id)}`));
    }
  }catch(error){officekitStorageStatus(error.message||'Storage analysis failed.',true);activity?.finish({state:'failed',phase:'Could not complete',summary:error.message||'Storage analysis failed.'});}finally{officekitStorage.activity=null;officekitStorageBusy(false);}
}
async function officekitStorageCancel() {
  if(!officekitStorage.scan)return;try{const result=await officekitStorageRequest(`/api/storage-scans/${encodeURIComponent(officekitStorage.scan)}`,{method:'DELETE'});if(!officekitStorageExact(result,['id','cancellationRequested'])||result.id!==officekitStorage.scan||result.cancellationRequested!==true)officekitStorageInvalid();officekitStorageStatus('Cancellation requested. Waiting for traversal to stop.');}catch(error){officekitStorageStatus(error.message,true);}
}
function officekitStorageBar(categories,label) {
  const wrap=officekitStorageNode('div');const bar=officekitStorageNode('div','','ok-storage-bar');bar.setAttribute('role','img');bar.setAttribute('aria-label',`${label}: ${categories.map(item=>`${officekitStorageCategories[item.id]} ${officekitStorageBytes(item.sizeBytes)}`).join('; ')}`);
  const legend=officekitStorageNode('ul','','ok-storage-legend');legend.setAttribute('aria-label',label);
  for(const item of categories){const segment=officekitStorageNode('span','','ok-storage-segment');segment.style.setProperty('--storage-color',`var(--ok-storage-${item.id})`);segment.style.flexGrow=String(item.sizeBytes);segment.title=`${officekitStorageCategories[item.id]}: ${officekitStorageBytes(item.sizeBytes)}`;bar.append(segment);
    const row=officekitStorageNode('li');const swatch=officekitStorageNode('span','','ok-storage-swatch');swatch.setAttribute('aria-hidden','true');swatch.style.setProperty('--storage-color',`var(--ok-storage-${item.id})`);row.append(swatch,officekitStorageNode('span',officekitStorageCategories[item.id]),officekitStorageNode('strong',officekitStorageBytes(item.sizeBytes)));legend.append(row);}
  wrap.append(bar,legend);return wrap;
}
function officekitStorageDate(value) { return value===null?'Unavailable':new Date(value*1000).toLocaleString(); }
function officekitStorageItemSize(item) { return item.method==='tool'&&item.sizeBytes===0?'Size not measured':officekitStorageBytes(item.sizeBytes); }
function officekitStorageValidatePermissions(result) { if(!officekitStorageExact(result,['state'])||result.state!=='opened')officekitStorageInvalid();return result; }
async function officekitStoragePermissions() {
  const button=document.getElementById('storage-access');const status=document.getElementById('storage-access-status');button.disabled=true;
  try{officekitStorageValidatePermissions(await officekitStorageNative()('storage_permissions_open'));officekitOutcome.show(status, { state: 'info', text: 'macOS Full Disk Access settings opened. Review OfficeKit’s access there, return to OfficeKit, then analyse again. Permission changes may require reopening the app.' });}
  catch(error){officekitOutcome.show(status, { state: 'error', text: error.message||'Open System Settings → Privacy & Security → Full Disk Access to review OfficeKit permissions.' });}
  finally{button.disabled=false;}
}
function officekitStorageLargest(items,title,files) {
  const details=officekitStorageNode('details','','ok-storage-group');details.append(officekitStorageNode('summary',`${title} · ${items.length} shown`),officekitStorageNode('p','Readable scanned locations only · logical size estimates · inspection only. Cleanup is available only for eligible items in the cleanup list.','ok-storage-muted'));
  if(!items.length){details.append(officekitStorageNode('p','No readable entries were reported.'));return details;}
  const wrap=officekitStorageNode('div','','ok-file-report-scroll');const table=officekitStorageNode('table','',`ok-file-report-table ${files?'ok-storage-largest-files':'ok-storage-largest-folders'}`);const caption=officekitStorageNode('caption',files?'Largest files with modification and creation dates':'Largest folders with recursive scanned file totals');table.append(caption);
  const header=officekitStorageNode('tr');for(const name of ['Location','Logical size',files?'Files':'Scanned files','Modified','Created','Coverage'])header.append(officekitStorageNode('th',name));const thead=officekitStorageNode('thead');thead.append(header);table.append(thead);
  const body=officekitStorageNode('tbody');for(const item of items){const row=officekitStorageNode('tr');for(const value of [item.path,officekitStorageBytes(item.sizeBytes),item.fileCount.toLocaleString(),officekitStorageDate(item.modifiedAt),officekitStorageDate(item.createdAt),item.partial?'Partial scanned descendants':'Readable item'])row.append(officekitStorageNode('td',value));body.append(row);}table.append(body);wrap.append(table);details.append(wrap);return details;
}
/* Safe = rebuilds itself (caches, build output, tool data). Everything else eligible is the owner's own files and needs review. */
const officekitStorageSafeCategories = Object.freeze(['caches','developer']);
/* Assistant session history lives under cache roots but is not rebuildable; it always needs review. */
function officekitStorageIsSafe(item) { return item.eligible&&officekitStorageSafeCategories.includes(item.category)&&!/conversation history/i.test(item.impact); }
function officekitStorageCount(count,noun) { return `${count.toLocaleString()} ${noun}${count===1?'':'s'}`; }
function officekitStorageSum(items) { return items.reduce((sum,item)=>sum+item.sizeBytes,0); }
function officekitStorageToggle(id,checked) {
  if(officekitStorage.busy||!officekitStorage.cleanupAllowed)return;
  if(checked)officekitStorage.selected.add(id);else officekitStorage.selected.delete(id);
  const input=document.getElementById(`storage-item-${id}`);if(input)input.checked=checked;
  officekitStorage.plan=null;officekitStorageSelection();
}
function officekitStorageSelectSafe() {
  if(officekitStorage.busy||!officekitStorage.cleanupAllowed||!officekitStorage.report)return;
  const safe=officekitStorage.report.candidates.filter(officekitStorageIsSafe).sort((a,b)=>b.sizeBytes-a.sizeBytes);
  const others=[...officekitStorage.selected].filter(id=>!safe.some(item=>item.id===id)).length;
  const room=Math.max(0,200-others);
  for(const item of safe)officekitStorage.selected.delete(item.id);
  for(const item of safe.slice(0,room)){officekitStorage.selected.add(item.id);const input=document.getElementById(`storage-item-${item.id}`);if(input)input.checked=true;}
  for(const item of safe.slice(room)){const input=document.getElementById(`storage-item-${item.id}`);if(input)input.checked=false;}
  if(safe.length>room&&typeof showAppFeedbackToast==='function')showAppFeedbackToast(`Selected ${room} safe items (batch limit is 200 items per cleanup).`,'working');
  officekitStorage.plan=null;officekitStorageSelection();
}
function officekitStorageOpenGroup(category) {
  const group=document.getElementById(`storage-group-${category}`);
  if(group){group.open=true;group.scrollIntoView({block:'nearest'});group.querySelector('summary')?.focus();}
}
function officekitStorageTiles(report,candidates) {
  const safe=candidates.filter(officekitStorageIsSafe),review=candidates.filter(item=>item.eligible&&!officekitStorageIsSafe(item));
  const free=report.volumes.reduce((sum,volume)=>sum+volume.availableBytes,0),capacity=report.volumes.reduce((sum,volume)=>sum+volume.capacityBytes,0),used=report.volumes.reduce((sum,volume)=>sum+volume.usedBytes,0);
  const selected=officekitStorageSum(candidates.filter(item=>officekitStorage.selected.has(item.id)));
  const wrap=officekitStorageNode('div','','ok-storage-tiles');wrap.setAttribute('role','group');wrap.setAttribute('aria-label','Scan summary');
  // Each summary tile is a row action (not a bar button) that opens or scrolls to its section.
  const open=(target)=>()=>{const node=typeof target==='function'?target():document.getElementById(target);if(!node)return;if(node.tagName==='DETAILS')node.open=true;node.scrollIntoView({behavior:'smooth',block:'start'});};
  const firstGroup=(items)=>()=>{const first=items.slice().sort((a,b)=>b.sizeBytes-a.sizeBytes)[0];const group=first&&document.getElementById(`storage-group-${first.category}`);if(group)group.open=true;return group;};
  const actions={'storage-tile-free':open('storage-volumes'),'storage-tile-safe':open(firstGroup(safe)),'storage-tile-review':open(firstGroup(review)),'storage-tile-unscanned':open('storage-coverage')};
  const tile=(label,value,sub,color,id,extra='')=>{const node=officekitStorageNode('button','','ok-storage-tile ok-row-action');node.type='button';node.id=id;node.onclick=actions[id];if(color)node.style.setProperty('--c',color);const key=officekitStorageNode('div','','ok-storage-tile-key');if(color)key.append(officekitStorageNode('i'));key.append(label);const val=officekitStorageNode('div',value,'ok-storage-tile-value');if(extra)val.append(officekitStorageNode('small',extra));node.append(key,val,officekitStorageNode('div',sub,'ok-storage-tile-sub'));return node;};
  wrap.append(
    tile('Free after cleanup',officekitStorageBytes(free+selected),`${officekitStorageBytes(free)} free now of ${officekitStorageBytes(capacity)}`,null,'storage-tile-free',selected?`+${officekitStorageBytes(selected)}`:''),
    tile('Safe to remove',officekitStorageBytes(officekitStorageSum(safe)),`${officekitStorageCount(safe.length,'item')} · caches that rebuild themselves`,'var(--ok-success, #1f8a5b)','storage-tile-safe'),
    tile('Needs review',officekitStorageBytes(officekitStorageSum(review)),`${officekitStorageCount(review.length,'item')} · personal files, downloads and assistant history`,'var(--ok-warning)','storage-tile-review'),
    tile('Not scanned',officekitStorageBytes(Math.max(0,used-report.logicalBytes)),'System and apps · see coverage',null,'storage-tile-unscanned'));
  return wrap;
}
function officekitStorageExplorer(report,candidates,mode) {
  const card=officekitStorageNode('section','','ok-file-panel ok-storage-explorer');card.setAttribute('aria-labelledby','storage-explorer-title');
  const head=officekitStorageNode('div','','ok-storage-head');head.append(officekitStorageNode('h3','Explorer'));head.firstChild.id='storage-explorer-title';
  const seg=officekitStorageNode('div','','ok-storage-seg');seg.setAttribute('role','group');seg.setAttribute('aria-label','Explorer view');
  for(const [value,name]of [['category','Category'],['cleanup','Cleanup']]){const button=officekitStorageNode('button',name);button.type='button';button.id=`storage-explorer-${value}`;button.setAttribute('aria-pressed',String(mode===value));button.onclick=()=>{officekitStorage.explorerMode=value;officekitStorageOverview(report);document.getElementById(`storage-explorer-${value}`)?.focus();};seg.append(button);}
  head.append(seg);
  const scanned=report.logicalBytes;card.append(head,officekitStorageNode('p',`${officekitStorageBytes(scanned)} scanned · select a tile to open its items`,'ok-storage-muted'));
  const tiles=new Map();
  for(const item of report.categories)if(item.id!=='available'&&item.sizeBytes>0)tiles.set(item.id,{id:item.id,name:officekitStorageCategories[item.id],size:item.sizeBytes});
  const downloads=candidates.filter(item=>item.category==='downloads');
  if(downloads.length)tiles.set('downloads',{id:'downloads',name:'Old downloads',size:officekitStorageSum(downloads)});
  const map=officekitStorageNode('div','','ok-storage-map');map.id='storage-explorer-map';
  const entries=[...tiles.values()].map(tile=>{const items=candidates.filter(item=>item.category===tile.id&&item.eligible);return{...tile,safe:items.filter(officekitStorageIsSafe),review:items.filter(item=>!officekitStorageIsSafe(item))};}).filter(tile=>mode==='category'||tile.safe.length||tile.review.length).sort((a,b)=>b.size-a.size);
  for(const tile of entries){
    const button=officekitStorageNode('button','',`ok-storage-t${tile.safe.length?' is-removable':''}${tile.review.length?' is-review':''}`);button.type='button';button.id=`storage-tile-${tile.id}`;
    button.style.setProperty('--c',`var(--ok-storage-${tile.id==='downloads'?'media':tile.id})`);button.style.flexGrow=String(Math.max(1,tile.size));
    const removable=tile.safe.length?` · ${tile.safe.length} removable`:tile.review.length?' · review':'';
    button.append(officekitStorageNode('b',tile.name),officekitStorageNode('em',`${officekitStorageBytes(tile.size)}${removable}`));
    button.setAttribute('aria-label',`${tile.name}, ${officekitStorageBytes(tile.size)}${tile.safe.length?`, ${tile.safe.length} safe to remove`:''}${tile.review.length?`, ${tile.review.length} to review`:''}`);
    if(candidates.some(item=>item.category===tile.id))button.onclick=()=>officekitStorageOpenGroup(tile.id);
    else{button.disabled=true;button.title='Nothing to open: no cleanup items in this category';}
    map.append(button);
  }
  if(!entries.length)map.append(officekitStorageNode('p','Nothing to show for this view.','ok-storage-muted'));
  const legend=officekitStorageNode('div','','ok-storage-map-legend');legend.append(officekitStorageNode('span','Hatched: holds items you can remove'),officekitStorageNode('span','Dashed: personal files that need your review'));
  card.append(map,legend);return card;
}
function officekitStorageRecommendations(candidates) {
  const card=officekitStorageNode('aside','','ok-file-panel ok-storage-recs');card.setAttribute('aria-labelledby','storage-recs-title');
  const title=officekitStorageNode('h3','Recommendations');title.id='storage-recs-title';
  card.append(title,officekitStorageNode('p',officekitStorage.cleanupAllowed?'Select items to build a cleanup. Moved to Trash where supported.':'Selection is disabled: this scan was cancelled or is inspection-only.','ok-storage-muted'));
  for(const [heading,items,id]of [['Safe to remove',candidates.filter(officekitStorageIsSafe),'safe'],['Review first',candidates.filter(item=>item.eligible&&!officekitStorageIsSafe(item)),'review']]) {
    const sorted=items.slice().sort((a,b)=>b.sizeBytes-a.sizeBytes);
    const h=officekitStorageNode('h4');h.append(officekitStorageNode('span',heading),officekitStorageNode('b',officekitStorageBytes(officekitStorageSum(items))));card.append(h);
    if(!sorted.length){card.append(officekitStorageNode('p','Nothing found.','ok-storage-muted'));continue;}
    const list=officekitStorageNode('div','','ok-storage-rec-list');list.id=`storage-recs-${id}`;
    for(const item of sorted.slice(0,12)){
      const row=officekitStorageNode('div','','ok-storage-rec');const input=officekitStorageNode('input','','checkbox checkbox-primary checkbox-sm');input.type='checkbox';input.id=`storage-rec-${item.id}`;input.dataset.candidate=item.id;input.disabled=!officekitStorage.cleanupAllowed;input.checked=officekitStorage.selected.has(item.id);input.onchange=()=>officekitStorageToggle(item.id,input.checked);
      const label=officekitStorageNode('label');label.htmlFor=input.id;label.append(officekitStorageNode('span',item.name,'ok-storage-rec-name'),officekitStorageNode('small',item.path));
      row.append(input,label,officekitStorageNode('span',officekitStorageItemSize(item),'ok-storage-size'));list.append(row);
    }
    card.append(list);
    if(sorted.length>12)card.append(officekitStorageNode('p',`${sorted.length-12} more in the full list below.`,'ok-storage-muted'));
  }
  return card;
}
function officekitStorageOverview(report) {
  const root=document.getElementById('storage-overview');if(!root)return;
  const candidates=report.candidates,mode=officekitStorage.explorerMode||'category';
  const work=officekitStorageNode('div','','ok-storage-work');work.append(officekitStorageExplorer(report,candidates,mode),officekitStorageRecommendations(candidates));
  root.replaceChildren(officekitStorageTiles(report,candidates),work);root.hidden=false;
}
const officekitStorageGroupPage=25;
function officekitStorageCandidateRow(item){const row=officekitStorageNode('div','','ok-storage-candidate');const input=officekitStorageNode('input','','checkbox checkbox-primary');input.type='checkbox';input.id=`storage-item-${item.id}`;input.disabled=!item.eligible;input.onchange=()=>{if(input.checked)officekitStorage.selected.add(item.id);else officekitStorage.selected.delete(item.id);officekitStorage.plan=null;officekitStorageSelection();};
      const label=officekitStorageNode('label');label.htmlFor=input.id;label.append(officekitStorageNode('strong',item.name),officekitStorageNode('small',item.path,'ok-storage-muted'),officekitStorageNode('small',`Modified: ${officekitStorageDate(item.modifiedAt)} · Created: ${officekitStorageDate(item.createdAt)}`,'ok-storage-muted'),officekitStorageNode('small',`${item.eligible?item.method==='tool'?'Permanent tool cleanup':'Move to Trash':'Inspection only'} · ${item.reason}`,'ok-storage-warning'),officekitStorageNode('small',item.impact,'ok-storage-muted'));row.append(input,label,officekitStorageNode('strong',officekitStorageItemSize(item),'ok-storage-size'));
  return row;}
function officekitStorageRenderGroupRows(group,all=false){
  const items=group._items;if(!items)return;
  const shown=group._shown||0;if(shown&&!all&&shown>=items.length)return;
  const end=all?items.length:Math.min(items.length,shown+officekitStorageGroupPage);
  const more=group.querySelector(':scope > .ok-storage-more');const fragment=document.createDocumentFragment();
  for(const item of items.slice(shown,end)){const row=officekitStorageCandidateRow(item);const box=row.querySelector('input');if(box){box.checked=officekitStorage.selected.has(item.id);box.disabled=!item.eligible||officekitStorage.busy||!officekitStorage.cleanupAllowed;}fragment.append(row);}
  group._shown=end;if(more)group.insertBefore(fragment,more);else group.append(fragment);
  if(more){if(end>=items.length)more.remove();else more.textContent=`Show ${Math.min(officekitStorageGroupPage,items.length-end)} more of ${(items.length-end).toLocaleString()} remaining`;}
}
function officekitStorageRender(report) {
  officekitStorageOverview(report);
  const volumes=document.getElementById('storage-volumes');volumes.replaceChildren();
  for(const volume of report.volumes){const panel=officekitStorageNode('article','','ok-file-panel ok-storage-volume');const heading=officekitStorageNode('div','','ok-storage-volume-heading');heading.append(officekitStorageNode('strong',volume.path),officekitStorageNode('span',`${officekitStorageBytes(volume.usedBytes)} used / ${officekitStorageBytes(volume.capacityBytes)}`));panel.append(heading,officekitStorageBar(volume.categories,'Storage by type — estimated allocated sizes'),officekitStorageNode('p',`Scanned logical file size: ${officekitStorageBytes(volume.logicalBytes)}. Category allocation is estimated; unclassified includes unreadable and protected locations. The overview reconciles to measured disk capacity.`,'ok-storage-muted'));const logical=officekitStorageNode('details');logical.append(officekitStorageNode('summary','Logical file sizes by type'),officekitStorageBar(volume.logicalCategories,'Logical file size estimates'));panel.append(logical);volumes.append(panel);}
  if(!report.volumes.length)volumes.append(officekitStorageNode('p','No volume metrics were available. Review scan coverage.'));
  const coverage=document.getElementById('storage-coverage');coverage.replaceChildren(officekitStorageNode('summary','Scan coverage and permissions'));
  for(const item of report.coverage)coverage.append(officekitStorageNode('p',`${item.path} · ${item.state}${item.inaccessibleCount?` · ${item.inaccessibleCount} inaccessible entries`:''}. ${item.reason}`,item.state==='complete'?'':'ok-storage-warning'));
  for(const note of report.limitations)coverage.append(officekitStorageNode('p',note,'ok-storage-muted'));
  coverage.append(officekitStorageNode('p','For denied locations, review the operating system’s app permissions and analyse again. This scan never grants access automatically.','ok-storage-muted'));
  if(report.mutationSupported){const access=officekitStorageButton('Review access permissions…',officekitStoragePermissions);access.id='storage-access';const status=officekitStorageNode('p','','ok-storage-muted');status.id='storage-access-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');coverage.append(access,status);}
  const root=document.getElementById('storage-candidates');
  const subtitle=officekitStorage.cleanupAllowed
    ?'Nothing is selected automatically. Review each file and its effect before cleanup.'
    :'Selection is disabled: this scan was cancelled or is inspection-only. Analyse storage again to select and clean items.';
  root.replaceChildren(officekitStorageNode('h2','Review cleanup candidates'),officekitStorageNode('p',subtitle,officekitStorage.cleanupAllowed?'ok-storage-muted':'ok-storage-warning font-semibold'));
  if(!officekitStorage.cleanupAllowed){
    const disabledNotice=officekitStorageNode('div','','alert alert-warning text-sm py-2 px-3 mb-3 flex items-center justify-between');
    const noticeText=officekitStorageNode('span','');
    noticeText.append(officekitStorageNode('i','','fa-solid fa-circle-exclamation mr-2'),document.createTextNode('Selection is disabled because this scan is inspection-only or was cancelled.'));
    // The bottom bar already has Analyse again; a second rescan button here would break the 3-button limit.
    disabledNotice.append(noticeText);
    root.append(disabledNotice);
  }
  root.hidden=false;
  root.append(officekitStorageLargest(report.largestFiles,'Largest files',true),officekitStorageLargest(report.largestFolders,'Largest folders',false));
  const grouped=new Map();for(const candidate of report.candidates){if(!grouped.has(candidate.category))grouped.set(candidate.category,[]);grouped.get(candidate.category).push(candidate);}
  for(const [category,items]of grouped){
    const group=officekitStorageNode('details','','ok-storage-group');group.id=`storage-group-${category}`;
    const total=items.reduce((sum,item)=>sum+item.sizeBytes,0);
    const unknown=items.some(item=>item.method==='tool'&&item.sizeBytes===0);
    group.append(officekitStorageNode('summary',`${category==='downloads'?'Old downloads':officekitStorageCategories[category]} · ${items.length} items · ${total||!unknown?officekitStorageBytes(total):'Size not measured'}${unknown&&total?' + unmeasured cache':''}`));
    const eligibleCount=items.filter(item=>item.eligible).length;
    if(eligibleCount>0){
      const toolbar=officekitStorageNode('div','','ok-storage-group-toolbar');toolbar.id=`storage-group-toolbar-${category}`;
      const selectWrap=officekitStorageNode('div','','ok-storage-group-toolbar-select');
      const groupCheck=officekitStorageNode('input','','checkbox checkbox-primary checkbox-sm');
      groupCheck.type='checkbox';groupCheck.id=`storage-select-group-${category}`;
      groupCheck.onchange=()=>officekitStorageSelectCategory(category,groupCheck.checked);
      const groupLabel=officekitStorageNode('label',`Select all${eligibleCount>200?' (first 200)':''}`);
      groupLabel.htmlFor=groupCheck.id;
      selectWrap.append(groupCheck,groupLabel);
      const selectBtn=officekitStorageButton('Select all',()=>officekitStorageSelectCategory(category,true));
      selectBtn.id=`storage-btn-select-all-${category}`;selectBtn.className='btn btn-xs btn-outline';
      const deselectBtn=officekitStorageButton('Deselect all',()=>officekitStorageSelectCategory(category,false));
      deselectBtn.id=`storage-btn-deselect-all-${category}`;deselectBtn.className='btn btn-xs btn-ghost';
      const statusSpan=officekitStorageNode('span',`0 / ${eligibleCount.toLocaleString()} selected`,'ok-storage-group-status');
      statusSpan.id=`storage-group-status-${category}`;
      toolbar.append(selectWrap,selectBtn,deselectBtn,statusSpan);
      group.append(toolbar);
    }
    group._items=items.slice().sort((a,b)=>b.sizeBytes-a.sizeBytes||a.path.localeCompare(b.path));group._shown=0;
    if(items.length>officekitStorageGroupPage){const more=officekitStorageNode('button','','link ok-text-link ok-storage-more');more.type='button';more.onclick=()=>officekitStorageRenderGroupRows(group);group.append(more);}
    group.addEventListener('toggle',()=>{if(group.open)officekitStorageRenderGroupRows(group);});root.append(group);}
  if(!report.candidates.length)root.append(officekitStorageNode('p','No cleanup candidates were found in the readable locations.'));
  const tools=officekitStorageNode('details','','ok-storage-group');tools.append(officekitStorageNode('summary','Docker and programming caches'));
  for(const tool of report.tools){tools.append(officekitStorageNode('p',`${tool.id} · ${tool.available?'Installed':'Not installed'} · ${tool.cleanupSupported?'Cleanup available':'Inspection only'}. ${tool.reason}`));
    if(tool.usage.length){tools.append(officekitStorageNode('p','Docker-reported logical usage is shown separately from host disk allocation. Images, containers and volumes are inspection only; volume cleanup is excluded.','ok-storage-muted'));const wrap=officekitStorageNode('div','','ok-file-report-scroll');const table=officekitStorageNode('table','','ok-file-report-table');table.id='storage-docker-usage';table.append(officekitStorageNode('caption','Local Docker usage · estimates reported by Docker'));const head=officekitStorageNode('tr');for(const label of ['Storage type','Total','Active','Reported size','Reported reclaimable'])head.append(officekitStorageNode('th',label));const thead=officekitStorageNode('thead');thead.append(head);table.append(thead);const body=officekitStorageNode('tbody');for(const usage of tool.usage){const row=officekitStorageNode('tr');for(const value of [usage.label,usage.totalCount===null?'Unavailable':usage.totalCount.toLocaleString(),usage.activeCount===null?'Unavailable':usage.activeCount.toLocaleString(),officekitStorageBytes(usage.sizeBytes),officekitStorageBytes(usage.reclaimableBytes)])row.append(officekitStorageNode('td',value));body.append(row);}table.append(body);wrap.append(table);tools.append(wrap);}
  }root.append(tools);
  document.getElementById('storage-footer').hidden=false;officekitStorageSelection();
  if(typeof officekitMountResultActions==='function')officekitMountResultActions(root,{toolId:'storage_analyzer',inline:true,copyLabel:'Copy report',copy:()=>officekitCopyResultText(JSON.stringify(report,null,2)),download:()=>officekitDownloadResultBlob(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),'storage-report.json')});
}
function officekitStorageSelectCategory(category,select=true) {
  if(officekitStorage.busy||!officekitStorage.cleanupAllowed)return;
  const items=officekitStorage.report?.candidates.filter(item=>item.category===category&&item.eligible)||[];
  if(!items.length)return;
  if(!select){
    for(const item of items){officekitStorage.selected.delete(item.id);const input=document.getElementById(`storage-item-${item.id}`);if(input)input.checked=false;}
  }else{
    const otherSelectedCount=[...officekitStorage.selected].filter(id=>{const candidate=officekitStorage.report?.candidates.find(c=>c.id===id);return candidate&&candidate.category!==category;}).length;
    const quota=Math.max(0,200-otherSelectedCount);
    if(quota<=0){const msg='Batch limit of 200 items reached. Deselect items in other sections first.';officekitStorageStatus(msg,true);if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(msg,'error');officekitStorageSelection();return;}
    const toSelect=items.slice(0,quota);
    for(const item of toSelect){officekitStorage.selected.add(item.id);const input=document.getElementById(`storage-item-${item.id}`);if(input)input.checked=true;}
    if(items.length>quota){const notice=`Selected ${toSelect.length} items (batch limit is 200 items per cleanup).`;if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(notice,'working');}
    else{const catName=category==='downloads'?'Old downloads':(officekitStorageCategories[category]||category);const notice=`Selected all ${toSelect.length} items in ${catName}.`;if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(notice,'success');}
  }
  officekitStorage.plan=null;officekitStorageSelection();
}
function officekitStorageSelection() {
  const items=officekitStorage.report?.candidates.filter(item=>officekitStorage.selected.has(item.id))||[];
  const unknown=items.filter(item=>item.method==='tool'&&item.sizeBytes===0).length;
  document.getElementById('storage-selected').textContent=`${officekitStorageBytes(items.reduce((sum,item)=>sum+item.sizeBytes,0))} selected · ${items.length} items${unknown?` · ${unknown} unmeasured tool cache`:''}`;
  document.getElementById('storage-review').disabled=officekitStorage.busy||!items.length;
  document.getElementById('storage-select-safe').disabled=officekitStorage.busy||!officekitStorage.cleanupAllowed||!officekitStorage.report?.candidates.some(officekitStorageIsSafe);
  for(const input of document.querySelectorAll('#storage-overview input[data-candidate]'))input.checked=officekitStorage.selected.has(input.dataset.candidate);
  if(officekitStorage.report&&document.getElementById('storage-tile-free')){const report=officekitStorage.report,free=report.volumes.reduce((sum,volume)=>sum+volume.availableBytes,0),selectedBytes=officekitStorageSum(items),value=document.querySelector('#storage-tile-free .ok-storage-tile-value');value.replaceChildren(officekitStorageBytes(free+selectedBytes));if(selectedBytes)value.append(officekitStorageNode('small',`+${officekitStorageBytes(selectedBytes)}`));}
  if(officekitStorage.report?.candidates){
    const grouped=new Map();
    for(const candidate of officekitStorage.report.candidates){if(!grouped.has(candidate.category))grouped.set(candidate.category,[]);grouped.get(candidate.category).push(candidate);}
    for(const [category,catItems]of grouped){
      const eligible=catItems.filter(item=>item.eligible);
      if(!eligible.length)continue;
      const selected=eligible.filter(item=>officekitStorage.selected.has(item.id));
      const groupCheck=document.getElementById(`storage-select-group-${category}`);
      const groupStatus=document.getElementById(`storage-group-status-${category}`);
      const selectBtn=document.getElementById(`storage-btn-select-all-${category}`);
      const deselectBtn=document.getElementById(`storage-btn-deselect-all-${category}`);
      if(groupStatus)officekitOutcome.show(groupStatus, { state: 'info', text: `${selected.length.toLocaleString()} / ${eligible.length.toLocaleString()} selected` });
      if(groupCheck){
        groupCheck.disabled=officekitStorage.busy||!officekitStorage.cleanupAllowed;
        if(selected.length===0){groupCheck.checked=false;groupCheck.indeterminate=false;}
        else if(selected.length===eligible.length||(eligible.length>200&&selected.length>=200)){groupCheck.checked=true;groupCheck.indeterminate=false;}
        else{groupCheck.checked=false;groupCheck.indeterminate=true;}
      }
      if(selectBtn)selectBtn.disabled=officekitStorage.busy||!officekitStorage.cleanupAllowed||selected.length===eligible.length||selected.length>=200;
      if(deselectBtn)deselectBtn.disabled=officekitStorage.busy||!officekitStorage.cleanupAllowed||selected.length===0;
    }
  }
}
async function officekitStorageReview() {
  if(officekitStorage.busy||!officekitStorage.selected.size||!officekitStorage.cleanupAllowed)return;
  if(officekitStorage.selected.size>200){const msg='Review at most 200 items in one cleanup.';officekitStorageStatus(msg,true);if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(msg,'error');return;}
  officekitStorageBusy(true);
  if(typeof showAppFeedbackToast==='function')showAppFeedbackToast('Preparing cleanup review…','working');
  try{const plan=officekitStorageValidatePlan(await officekitStorageRequest('/api/storage-cleanup-plans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scanId:officekitStorage.scan,candidateIds:[...officekitStorage.selected]})}),officekitStorage.selected);officekitStorage.plan=plan;
    const root=document.getElementById('storage-confirm-items');root.replaceChildren(officekitStorageNode('p',`${plan.items.length} individual items · ${officekitStorageBytes(plan.estimatedBytes)} estimated logical size`),officekitStorageNode('p',plan.impact,'ok-storage-warning'));
    // Summary first; the full path list is built only if the person opens it, so Review never renders 200 rows.
    const byCategory=new Map();for(const item of plan.items){const entry=byCategory.get(item.category)||{count:0,bytes:0};entry.count+=1;entry.bytes+=item.sizeBytes;byCategory.set(item.category,entry);}
    const breakdown=[...byCategory].map(([category,entry])=>`${category==='downloads'?'Old downloads':officekitStorageCategories[category]||category} ${entry.count} · ${officekitStorageBytes(entry.bytes)}`).join(', ');
    const personal=plan.items.filter(item=>!officekitStorageIsSafe(item)).length;
    const paths=officekitStorageNode('details','','ok-storage-paths-box');paths.id='storage-confirm-paths';
    paths.append(officekitStorageNode('summary',`Show all ${plan.items.length.toLocaleString()} paths`));
    paths.addEventListener('toggle',()=>{if(!paths.open||paths.querySelector('ul'))return;const list=officekitStorageNode('ul','','ok-storage-paths');for(const item of plan.items)list.append(officekitStorageNode('li',`${item.path} · ${officekitStorageItemSize(item)} · ${item.method==='tool'?'Permanent cleanup — cannot be undone':'Move to Trash'}. ${item.impact}`));paths.append(list);});
    const movesToTrash=plan.items.some(item=>item.method!=='tool');
    const permanent=plan.items.filter(item=>item.method==='tool').length;
    root.append(officekitStorageNode('p',breakdown,'ok-storage-muted'),...(permanent?[officekitStorageNode('p',`${officekitStorageCount(permanent,'tool cache')}: Permanent cleanup — cannot be undone.`,'ok-storage-warning')]:[]),...(personal?[officekitStorageNode('p',`${officekitStorageCount(personal,'personal file')} to review — check the full list before confirming.`,'ok-storage-warning')]:[]),paths,officekitStorageNode('p',`This review expires at ${new Date(plan.expiresAt*1000).toLocaleTimeString()}. Changed or active files will be skipped.`),...(movesToTrash?[officekitTrashDisclosure(true)]:[]));
    const confirmBtn=document.getElementById('storage-confirm-apply');if(confirmBtn){confirmBtn.disabled=false;confirmBtn.textContent='Confirm cleanup';}
    const backBtn=document.getElementById('storage-confirm-back');if(backBtn)backBtn.disabled=false;
    const confirmStatus=document.getElementById('storage-confirm-status');if(confirmStatus){confirmStatus.hidden=true;officekitOutcome.show(confirmStatus, { state: 'info', text: '' });confirmStatus.className='ok-storage-confirm-status';}
    if(officekitStorage.expireTimer){clearTimeout(officekitStorage.expireTimer);officekitStorage.expireTimer=null;}
    const remainingMs=Math.max(0,(plan.expiresAt*1000)-Date.now());
    if(remainingMs>0){
      officekitStorage.expireTimer=setTimeout(()=>{
        if(officekitStorage.plan?.id===plan.id&&document.getElementById('storage-confirm')?.open){
          if(confirmBtn&&!officekitStorage.busy)confirmBtn.disabled=true;
          if(confirmStatus&&!officekitStorage.busy){confirmStatus.hidden=false;confirmStatus.className='ok-storage-confirm-status is-error';officekitOutcome.show(confirmStatus, { state: 'error', text: 'This review plan has expired. Close and review your selection again.' });}
          if(typeof showAppFeedbackToast==='function')showAppFeedbackToast('Review plan expired. Review selection again.','error');
        }
      },remainingMs);
    }
    if(typeof dismissAppFeedbackToast==='function')dismissAppFeedbackToast();
    document.getElementById('storage-confirm').showModal();
  }catch(error){officekitStorage.plan=null;officekitStorageStatus(error.message,true);if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(error.message,'error');}finally{officekitStorageBusy(false);}
}
// Cleanup runs in one native call; this polls its progress and offers a stop that takes effect after the current item.
function officekitStorageWatchCleanup(plan,status,confirmBtn,backBtn) {
  const executionPath=`/api/storage-cleanup-plans/${encodeURIComponent(plan.id)}/execution`;
  const bar=officekitStorageNode('progress','','ok-storage-progress');bar.max=plan.items.length;bar.value=0;bar.setAttribute('aria-label','Cleanup progress');
  const text=officekitStorageNode('p',`0 / ${plan.items.length} items`);
  const stop=officekitStorageButton('Stop after current item',async()=>{stop.disabled=true;text.textContent='Stopping after the current item…';try{await officekitStorageRequest(executionPath,{method:'DELETE'});}catch{}});stop.id='storage-confirm-stop';
  status.replaceChildren(bar,text);confirmBtn.hidden=true;backBtn.hidden=true;confirmBtn.parentNode.append(stop);
  let live=true;
  (async()=>{while(live){await new Promise(resolve=>setTimeout(resolve,500));if(!live)break;
    try{const progress=await officekitStorageRequest(executionPath);if(!live)break;
      if(officekitStorageNumber(progress.done)&&officekitStorageNumber(progress.total)&&officekitStorageNumber(progress.movedBytes)&&progress.total>0&&!stop.disabled){bar.max=progress.total;bar.value=Math.min(progress.done,progress.total);text.textContent=`${progress.done.toLocaleString()} / ${progress.total.toLocaleString()} items · ${officekitStorageBytes(progress.movedBytes)} done`;}
    }catch{/* progress is best effort; the cleanup itself reports its result */}}})();
  return ()=>{live=false;stop.remove();confirmBtn.hidden=false;backBtn.hidden=false;};
}
async function officekitStorageApply() {
  const plan=officekitStorage.plan;if(officekitStorage.busy||!plan)return;
  const confirmBtn=document.getElementById('storage-confirm-apply');const backBtn=document.getElementById('storage-confirm-back');const confirmStatus=document.getElementById('storage-confirm-status');
  if(plan.expiresAt<=Date.now()/1000){
    if(confirmStatus){confirmStatus.hidden=false;confirmStatus.className='ok-storage-confirm-status is-error';officekitOutcome.show(confirmStatus, { state: 'error', text: 'This review plan has expired. Close and review your selection again.' });}
    if(confirmBtn)confirmBtn.disabled=true;
    officekitStorage.plan=null;const expiredMsg='The review expired. Review your selection again.';officekitStorageStatus(expiredMsg,true);if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(expiredMsg,'error');return;
  }
  officekitStorageBusy(true);
  if(confirmBtn){confirmBtn.disabled=true;const spinner=officekitStorageNode('span','','loading loading-spinner loading-xs mr-1.5');confirmBtn.replaceChildren(spinner,document.createTextNode('Cleaning…'));}
  if(backBtn)backBtn.disabled=true;
  if(confirmStatus){confirmStatus.hidden=false;confirmStatus.className='ok-storage-confirm-status is-working';const icon=officekitStorageNode('i','','fa-solid fa-spinner fa-spin mr-1.5');confirmStatus.replaceChildren(icon,document.createTextNode('Cleaning up selected items… Tool caches and files are being processed.'));}
  if(typeof showAppFeedbackToast==='function')showAppFeedbackToast('Cleaning up selected items…','working');
  const stopWatching=confirmBtn&&backBtn&&confirmStatus?officekitStorageWatchCleanup(plan,confirmStatus,confirmBtn,backBtn):()=>{};
  try{
    const result=officekitStorageValidateOutcome(await officekitStorageNative()('storage_cleanup_apply',{planId:plan.id}),plan);
    const root=document.getElementById('storage-outcomes');root.replaceChildren(officekitStorageNode('h2','Cleanup result'),officekitStorageNode('p',`${officekitStorageBytes(result.movedBytes)} moved or cleaned · ${officekitStorageBytes(result.trashOccupancyIncreaseBytes)} added to Trash.`),officekitStorageNode('p',`Measured free-space change: ${result.measuredFreeSpaceChangeBytes<0?'−':''}${officekitStorageBytes(Math.abs(result.measuredFreeSpaceChangeBytes))}. Trash still occupies disk space until emptied.`,`ok-storage-muted`));
    const names=new Map(plan.items.map(item=>[item.id,item.path]));for(const item of result.items)root.append(officekitStorageNode('p',`${names.get(item.id)} · ${item.status==='moved'?'Moved to Trash':item.status==='cleaned'?'Cleaned permanently':item.status}. ${item.message}`,['failed','skipped'].includes(item.status)?'ok-storage-warning':''));
    root.hidden=false;
    document.getElementById('storage-confirm').close();
    root.scrollIntoView({behavior:'smooth',block:'nearest'});
    const cleanedSet=new Set(result.items.filter(item=>['moved','cleaned'].includes(item.status)).map(item=>item.id));
    if(officekitStorage.report?.candidates){
      for(const cand of officekitStorage.report.candidates){
        if(cleanedSet.has(cand.id)){cand.eligible=false;cand.reason='Cleaned in previous batch';}
      }
    }
    for(const id of cleanedSet){
      const input=document.getElementById(`storage-item-${id}`);
      if(input){
        input.checked=false;input.disabled=true;
        const row=input.closest('.ok-storage-candidate');
        if(row){row.classList.add('opacity-50');const statusText=row.querySelector('.ok-storage-warning');if(statusText)officekitOutcome.show(statusText, { state: 'info', text: '✓ Cleaned' });}
      }
    }
    officekitStorage.selected.clear();
    officekitStorageStatus('Cleanup finished. Select remaining items to clean more, or analyse again to refresh.');
    const toastSummary=`${officekitStorageBytes(result.movedBytes)} moved or cleaned · Cleanup finished`;
    if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(toastSummary,'success');
  }catch(error){
    const errMsg=error?.message||'Cleanup failed. Scan again before retrying.';
    document.getElementById('storage-confirm').close();
    officekitStorageStatus(errMsg,true);
    if(typeof showAppFeedbackToast==='function')showAppFeedbackToast(errMsg,'error');
  }finally{
    stopWatching();
    if(officekitStorage.expireTimer){clearTimeout(officekitStorage.expireTimer);officekitStorage.expireTimer=null;}
    officekitStorage.plan=null;
    officekitStorage.selected.clear();
    officekitStorageBusy(false);
    officekitStorageSelection();
    if(confirmBtn){confirmBtn.disabled=false;confirmBtn.textContent='Confirm cleanup';}
    if(backBtn)backBtn.disabled=false;
    if(confirmStatus){confirmStatus.hidden=true;officekitOutcome.show(confirmStatus, { state: 'info', text: '' });}
  }
}
