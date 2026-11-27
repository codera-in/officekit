import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const file={id:'file-1',name:'installer.dmg',path:'/Users/demo/Downloads/installer.dmg',category:'downloads',sizeBytes:4000,modifiedAt:100,createdAt:null,method:'trash',eligible:true,reason:'Not changed in 90 days.',impact:'Review this personal download.'};
const tool={...file,id:'tool-1',name:'Docker build cache',path:'unix:///var/run/docker.sock',category:'developer',method:'tool',sizeBytes:0,reason:'Size not measured.',impact:'Permanent cleanup of unused local build cache older than 7 days. Volumes are excluded.'};
const report={scope:'system',volumes:[{path:'Macintosh HD',capacityBytes:100000,usedBytes:70000,availableBytes:30000,logicalBytes:4000,categories:[{id:'applications',sizeBytes:20000},{id:'developer',sizeBytes:10000},{id:'caches',sizeBytes:4000},{id:'unclassified',sizeBytes:36000},{id:'available',sizeBytes:30000}],logicalCategories:[{id:'documents',sizeBytes:4000}],unclassifiedUsedBytes:36000,categoryBasis:'allocated-estimate'}],categories:[{id:'documents',sizeBytes:4000}],logicalBytes:4000,candidates:[file,tool,{...file,id:'protected-1',name:'Protected cache',eligible:false,method:'unsupported'}],coverage:[{path:'/',state:'partial',reason:'Protected locations excluded.',inaccessibleCount:2}],complete:false,entriesScanned:50,tools:[{id:'docker',available:true,cleanupSupported:true,reason:'Local context validated.',cachePath:tool.path,impact:tool.impact}],mutationSupported:true,limitations:['Network disks are excluded.']};
report.largestFiles=[{path:'/Users/demo/Videos/holiday.mov',name:'holiday.mov',sizeBytes:4000,fileCount:1,modifiedAt:100,createdAt:null,partial:false}];
report.largestFolders=[{path:'/Users/demo/Videos',name:'Videos',sizeBytes:4000,fileCount:1,modifiedAt:100,createdAt:null,partial:true}];
report.tools[0].usage=[{id:'images',label:'Images',totalCount:3,activeCount:1,sizeBytes:8000,reclaimableBytes:4000},{id:'containers',label:'Containers',totalCount:1,activeCount:1,sizeBytes:1000,reclaimableBytes:0},{id:'volumes',label:'Local Volumes',totalCount:2,activeCount:1,sizeBytes:20000,reclaimableBytes:null},{id:'build-cache',label:'Build Cache',totalCount:null,activeCount:null,sizeBytes:5000,reclaimableBytes:4000}];

test.beforeEach(async({context,page})=>{
  await context.route('**/api/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/storage-cleanup-plans'){
      const body=route.request().postDataJSON();expect(body.scanId).toBe('scan-1');expect(Object.keys(body).sort()).toEqual(['candidateIds','scanId']);
      const items=report.candidates.filter(item=>body.candidateIds.includes(item.id));
      await route.fulfill({json:{id:'plan-1',expiresAt:Date.now()/1000+300,items,estimatedBytes:items.reduce((sum,item)=>sum+item.sizeBytes,0),impact:'Files move to Trash; selected tool cleanup is permanent.'}});return;
    }
    const response=await route.fetch({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,origin:'tauri://localhost'}});await route.fulfill({response});
  });
  await page.goto('/');
  await page.evaluate(report=>{
    window.storageInvocations=[];
    window.__TAURI__={core:{invoke:async(command,args)=>{
      window.storageInvocations.push({command,args});
      if(command==='storage_scan_start')return {id:'scan-1',state:'ready',progress:100,entriesScanned:report.entriesScanned,candidateCount:report.candidates.length,candidateBytes:report.candidates.reduce((sum,item)=>sum+item.sizeBytes,0),report,error:null};
      if(command==='storage_permissions_open')return {state:'opened'};
      if(command==='storage_cleanup_apply')return {id:'plan-1',items:[{id:'file-1',status:'moved',sizeBytes:4000,message:'Moved to Trash.'},{id:'tool-1',status:'cleaned',sizeBytes:0,message:'Tool completed; size not measured.'}],movedBytes:4000,measuredFreeSpaceChangeBytes:0,trashOccupancyIncreaseBytes:4000,reclaimedBytes:0};
      throw Error('Unexpected native command.');
    }}};
    switchTab('workspace');officekitOpenDirectFileTool('storage');
  },report);
});

test('system storage shows proportional categories, individual review and partial outcomes',async({page},testInfo)=>{
  await expect(page.locator('#storage-scope')).toHaveValue('system');
  await expect(page.locator('#direct-selections')).toBeHidden();
  await page.getByRole('button',{name:'Analyse storage',exact:true}).click();
  await expect(page.locator('#storage-status')).toContainText('Partial analysis');
  await expect(page.locator('#storage-volumes [role="img"]').first()).toHaveAttribute('aria-label',/Applications 20 KB.*Developer data 10 KB.*Available 30 KB/);
  await expect(page.locator('#storage-volumes .ok-storage-segment').first()).toHaveCSS('flex-grow','20000');
  await expect(page.locator('#storage-review')).toBeDisabled();
  await page.getByText('Largest files · 1 shown',{exact:true}).click();await expect(page.locator('#storage-candidates table').first()).toContainText('holiday.mov');await expect(page.locator('#storage-candidates table').first().locator('input')).toHaveCount(0);
  await page.getByText('Largest folders · 1 shown',{exact:true}).click();await expect(page.locator('#storage-candidates table').nth(1)).toContainText('Partial scanned descendants');
  await page.getByText('Largest files · 1 shown',{exact:true}).click();await page.getByText('Largest folders · 1 shown',{exact:true}).click();
  await page.screenshot({path:testInfo.outputPath('storage-overview.png'),fullPage:true});
  const nonOverlapping=await page.evaluate(()=>document.getElementById('storage-footer').getBoundingClientRect().top>=document.getElementById('storage-candidates').getBoundingClientRect().bottom);expect(nonOverlapping).toBe(true);
  await page.locator('#storage-candidates summary').filter({hasText:'Old downloads'}).click();
  await page.locator('#storage-item-file-1').check();
  await expect(page.locator('#storage-item-protected-1')).toBeDisabled();
  await page.locator('#storage-candidates summary').filter({hasText:'Developer data'}).click();
  await page.locator('#storage-item-tool-1').check();
  await page.locator('#storage-review').click();
  await expect(page.getByRole('dialog',{name:'Review selected cleanup'})).toBeVisible();
  await expect(page.locator('#storage-confirm-items')).toContainText('Permanent cleanup — cannot be undone');
  await page.screenshot({path:testInfo.outputPath('storage-review.png'),fullPage:true});
  await page.locator('#storage-confirm-apply').click();
  await expect(page.locator('#storage-outcomes')).toContainText('Moved to Trash');
  await expect(page.locator('#storage-outcomes')).toContainText('Cleaned permanently');
  await expect(page.locator('#app-feedback-toast')).toBeVisible();
  await expect(page.locator('#app-feedback-toast')).toContainText('Cleanup finished');
  await expect(page.locator('#storage-review')).toBeDisabled();
  expect(await page.evaluate(()=>window.storageInvocations)).toEqual([{command:'storage_scan_start',args:{olderThanDays:90}},{command:'storage_cleanup_apply',args:{planId:'plan-1'}}]);
  await page.screenshot({path:testInfo.outputPath('storage-result.png'),fullPage:true});
});

test('summary tiles, explorer and recommendations drive the same selection as the full list',async({page})=>{
  await page.getByRole('button',{name:'Analyse storage',exact:true}).click();
  await expect(page.locator('#storage-overview')).toBeVisible();
  await expect(page.locator('#storage-tile-safe')).toContainText('Safe to remove');
  await expect(page.locator('#storage-tile-review')).toContainText('Needs review');
  await expect(page.locator('#storage-tile-review')).toContainText('1 item ·');
  await expect(page.locator('#storage-tile-unscanned')).toContainText('Not scanned');
  await expect(page.locator('#storage-tile-free .ok-storage-tile-value small')).toHaveCount(0);
  const downloads=page.locator('#storage-tile-downloads');
  await expect(downloads).toHaveClass(/is-review/);
  await downloads.click();
  await expect(page.locator('#storage-group-downloads')).toHaveJSProperty('open',true);
  // A downloads item is never part of Select safe; it is chosen only by hand.
  await page.locator('#storage-select-safe').click();
  await expect(page.locator('#storage-rec-file-1')).not.toBeChecked();
  await page.locator('#storage-rec-file-1').check();
  await expect(page.locator('#storage-item-file-1')).toBeChecked();
  await expect(page.locator('#storage-review')).toBeEnabled();
  await expect(page.locator('#storage-tile-free .ok-storage-tile-value small')).toContainText('+');
  await page.locator('#storage-explorer-cleanup').click();
  await expect(page.locator('#storage-explorer-cleanup')).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('#storage-explorer-map .ok-storage-t').first()).toBeVisible();
  await page.locator('#storage-item-file-1').uncheck();
  await expect(page.locator('#storage-rec-file-1')).not.toBeChecked();
});
test('overview remains readable in dark theme at narrow width',async({page},testInfo)=>{
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.locator('#storage-run').click();await expect(page.locator('#storage-volumes')).toContainText('Macintosh HD');
  await page.screenshot({path:testInfo.outputPath('storage-dark-overview.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  const overflow=await page.locator('#storage-system').evaluate(node=>node.scrollWidth>node.clientWidth);expect(overflow).toBe(false);
  await page.screenshot({path:testInfo.outputPath('storage-dark-narrow.png'),fullPage:true});
});

test('folder analysis remains available and other file tools restore their controls',async({page})=>{
  await page.locator('#storage-run').click();await expect(page.locator('#storage-volumes')).toContainText('Macintosh HD');
  await page.locator('#storage-scope').selectOption('folder');await expect(page.locator('#direct-selections')).toBeVisible();await expect(page.locator('#storage-run')).toBeHidden();
  for(const id of ['storage-volumes','storage-candidates','storage-footer','storage-coverage','storage-status'])await expect(page.locator(`#${id}`)).toBeHidden();
  await page.locator('#storage-scope').selectOption('system');await expect(page.locator('#storage-volumes')).toBeVisible();await expect(page.locator('#storage-candidates')).toBeVisible();await expect(page.locator('#storage-footer')).toBeVisible();await expect(page.locator('#storage-outcomes')).toBeHidden();
  await page.evaluate(()=>officekitOpenDirectFileTool('file_hash'));await expect(page.locator('#storage-system')).toBeHidden();await expect(page.locator('#direct-selections')).toBeVisible();await expect(page.getByRole('group', { name: 'Algorithm' })).toBeVisible();
});

test('cancelled scans show a terminal cancellation state and never enable cleanup',async({page})=>{
  let cancelled=false;
  await page.route('**/api/storage-scans/scan-cancel',async route=>{
    if(route.request().method()==='DELETE'){cancelled=true;await route.fulfill({json:{id:'scan-cancel',cancellationRequested:true}});}
    else await route.fulfill({json:{id:'scan-cancel',state:cancelled?'cancelled':'running',progress:0,entriesScanned:42,candidateCount:1,candidateBytes:2048,report:cancelled?report:null,error:null}});
  });
  await page.evaluate(()=>{window.__TAURI__.core.invoke=async()=>({id:'scan-cancel',state:'queued',progress:0,entriesScanned:0,candidateCount:0,candidateBytes:0,report:null,error:null});});
  await page.locator('#storage-run').click();await expect(page.locator('#storage-cancel')).toBeVisible();await page.locator('#storage-cancel').click();
  await expect(page.locator('#storage-status')).toContainText('Scan cancelled');await expect(page.locator('#storage-run')).toBeEnabled();await expect(page.locator('#storage-footer')).toBeVisible();await expect(page.locator('#storage-review')).toBeDisabled();
  await page.locator('#storage-candidates summary').filter({hasText:'Old downloads'}).click();await expect(page.locator('#storage-item-file-1')).toBeDisabled();
});

test('shared report actions copy and download the complete inspection report',async({page})=>{
  await page.locator('#storage-run').click();await expect(page.locator('#storage-status')).toContainText('Partial analysis');
  await page.evaluate(()=>{window.officekitCopyResultText=async text=>{window.storageCopiedReport=text;};window.__TAURI__.core.invoke=async(command,args)=>{if(command!=='result_save')throw Error('Unexpected command');window.storageSavedReport=args;return {state:'saved',name:args.suggestedName};};});
  await page.locator('#storage-candidates').getByRole('button',{name:'Copy report',exact:true}).click();
  expect(await page.evaluate(()=>JSON.parse(window.storageCopiedReport).largestFiles[0].path)).toBe(report.largestFiles[0].path);
  await page.locator('#storage-candidates').getByRole('button',{name:'Download',exact:true}).click();await expect(page.locator('#storage-candidates .officekit-result-action-status')).toContainText('Saved');
  const saved=await page.evaluate(()=>window.storageSavedReport);expect(saved.suggestedName).toBe('storage-report.json');
  const exported=JSON.parse(Buffer.from(saved.base64Data,'base64').toString('utf8'));expect(exported.largestFolders).toEqual(report.largestFolders);expect(exported.coverage).toEqual(report.coverage);
  await page.evaluate(()=>{delete window.__TAURI__;});const pending=page.waitForEvent('download');await page.locator('#storage-candidates').getByRole('button',{name:'Download',exact:true}).click();const download=await pending;
  expect(download.suggestedFilename()).toBe('storage-report.json');expect(JSON.parse(await fs.readFile(await download.path(),'utf8')).largestFiles).toEqual(report.largestFiles);
});

test('Docker logical usage is separate and permissions open settings without granting access or scanning',async({page})=>{
  await page.locator('#storage-run').click();await expect(page.locator('#storage-status')).toContainText('Partial analysis');
  await page.getByText('Docker and programming caches',{exact:true}).click();await expect(page.locator('#storage-docker-usage')).toContainText('Local Volumes');await expect(page.locator('#storage-docker-usage')).toContainText('Unavailable');await expect(page.locator('#storage-docker-usage input, #storage-docker-usage button')).toHaveCount(0);await expect(page.locator('#storage-volumes')).not.toContainText('Local Volumes');
  await page.getByText('Scan coverage and permissions',{exact:true}).click();await page.getByRole('button',{name:'Review access permissions…',exact:true}).click();await expect(page.locator('#storage-access-status')).toContainText('Full Disk Access settings opened');
  expect(await page.evaluate(()=>window.storageInvocations)).toEqual([{command:'storage_scan_start',args:{olderThanDays:90}},{command:'storage_permissions_open',args:undefined}]);
});

test('cleanup shows in-flight progress feedback inside dialog and via toast',async({page})=>{
  await page.locator('#storage-run').click();
  await page.locator('#storage-candidates summary').filter({hasText:'Old downloads'}).click();
  await page.locator('#storage-item-file-1').check();
  await page.locator('#storage-review').click();
  await expect(page.getByRole('dialog',{name:'Review selected cleanup'})).toBeVisible();

  await page.evaluate(()=>{
    window.__TAURI__.core.invoke=async(command,args)=>{
      if(command==='storage_cleanup_apply'){
        await new Promise(r=>setTimeout(r,500));
        return {id:'plan-1',items:[{id:'file-1',status:'moved',sizeBytes:4000,message:'Moved to Trash.'}],movedBytes:4000,measuredFreeSpaceChangeBytes:0,trashOccupancyIncreaseBytes:4000,reclaimedBytes:0};
      }
      throw Error('Unexpected command');
    };
  });

  await page.locator('#storage-confirm-apply').click();
  // While cleaning, the dialog shows progress and one Stop button instead of Back and Confirm (2 buttons at most).
  await expect(page.locator('#storage-confirm-apply')).toBeHidden();
  await expect(page.locator('#storage-confirm-back')).toBeHidden();
  await expect(page.locator('#storage-confirm-stop')).toBeVisible();
  await expect(page.locator('#storage-confirm-status progress')).toBeVisible();
  await expect(page.locator('#storage-confirm-status')).toContainText('0 / 1 items');

  await expect(page.locator('#storage-outcomes')).toBeVisible();
  await expect(page.locator('#app-feedback-toast')).toContainText('Cleanup finished');
});

test('summary tiles are actions, the bar stays within 3 buttons and large groups draw 25 rows at a time',async({page})=>{
  await page.evaluate(()=>{
    const many=Array.from({length:60},(_,index)=>({id:`bulk-${index}`,name:`bulk-${index}.zip`,path:`/Users/demo/Downloads/bulk-${index}.zip`,category:'downloads',sizeBytes:1000+index,modifiedAt:100,createdAt:null,method:'trash',eligible:true,reason:'Not changed in 90 days.',impact:'Review this personal download.'}));
    const original=window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke=async(command,args)=>{const result=await original(command,args);if(command==='storage_scan_start'){result.report={...result.report,candidates:[...result.report.candidates,...many]};result.candidateCount=result.report.candidates.length;}return result;};
  });
  await page.locator('#storage-run').click();
  for(const id of ['free','safe','review','unscanned']){const tile=page.locator(`#storage-tile-${id}`);await expect(tile).toBeVisible();expect(await tile.evaluate(node=>node.tagName)).toBe('BUTTON');}
  await page.locator('#storage-tile-review').click();
  await expect(page.locator('#storage-group-downloads')).toHaveJSProperty('open',true);
  await expect(page.locator('#storage-group-downloads .ok-storage-candidate')).toHaveCount(25);
  await page.locator('#storage-group-downloads .ok-storage-more').click();
  await expect(page.locator('#storage-group-downloads .ok-storage-candidate')).toHaveCount(50);
  // Selecting a group selects every item, drawn or not.
  await page.locator('#storage-btn-select-all-downloads').click();
  await expect(page.locator('#storage-selected')).toContainText('items');
  // Bottom bar: at most 3 visible buttons, one rescan, no duplicate in the page body.
  const barButtons=await page.locator('#storage-footer button:visible, #storage-run:visible').count();
  expect(barButtons).toBeLessThanOrEqual(3);
  await expect(page.locator('#storage-outcomes button.btn:visible, #storage-candidates > .alert button:visible')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Analyse storage again'})).toHaveCount(0);
});

test('subsection provides select all and deselect all controls',async({page})=>{
  await page.locator('#storage-run').click();
  await page.locator('#storage-candidates summary').filter({hasText:'Old downloads'}).click();
  await expect(page.locator('#storage-group-toolbar-downloads')).toBeVisible();
  await expect(page.locator('#storage-group-status-downloads')).toContainText('0 / 1 selected');

  // Test select all via button
  await page.locator('#storage-btn-select-all-downloads').click();
  await expect(page.locator('#storage-item-file-1')).toBeChecked();
  await expect(page.locator('#storage-select-group-downloads')).toBeChecked();
  await expect(page.locator('#storage-group-status-downloads')).toContainText('1 / 1 selected');
  await expect(page.locator('#storage-selected')).toContainText('1 items');

  // Test deselect all via button
  await page.locator('#storage-btn-deselect-all-downloads').click();
  await expect(page.locator('#storage-item-file-1')).not.toBeChecked();
  await expect(page.locator('#storage-select-group-downloads')).not.toBeChecked();
  await expect(page.locator('#storage-group-status-downloads')).toContainText('0 / 1 selected');
  await expect(page.locator('#storage-selected')).toContainText('0 items');

  // Test select all via group checkbox
  await page.locator('#storage-select-group-downloads').check();
  await expect(page.locator('#storage-item-file-1')).toBeChecked();
  await expect(page.locator('#storage-group-status-downloads')).toContainText('1 / 1 selected');
  await page.screenshot({path:'.test-artifacts/screenshots/storage-subsection-select-all.png',fullPage:true});
});

test('remaining candidates remain selectable after a cleanup batch completes',async({page})=>{
  await page.locator('#storage-run').click();
  // Open Developer data and select tool-1
  await page.locator('#storage-candidates summary').filter({hasText:'Developer data'}).click();
  await page.locator('#storage-item-tool-1').check();
  await page.locator('#storage-review').click();
  await expect(page.getByRole('dialog',{name:'Review selected cleanup'})).toBeVisible();

  // Apply cleanup for tool-1 only
  await page.evaluate(()=>{
    window.__TAURI__.core.invoke=async(command,args)=>{
      if(command==='storage_cleanup_apply'){
        return {id:'plan-1',items:[{id:'tool-1',status:'cleaned',sizeBytes:0,message:'Tool completed'}],movedBytes:0,measuredFreeSpaceChangeBytes:0,trashOccupancyIncreaseBytes:0,reclaimedBytes:0};
      }
      throw Error('Unexpected command');
    };
  });
  await page.locator('#storage-confirm-apply').click();
  await expect(page.locator('#storage-outcomes')).toContainText('Cleaned permanently');

  // Verify tool-1 is marked cleaned and disabled
  await expect(page.locator('#storage-item-tool-1')).toBeDisabled();

  // Verify Old downloads candidates REMAIN selectable!
  await page.locator('#storage-candidates summary').filter({hasText:'Old downloads'}).click();
  await expect(page.locator('#storage-item-file-1')).toBeEnabled();
  await page.locator('#storage-item-file-1').check();
  await expect(page.locator('#storage-item-file-1')).toBeChecked();
  await expect(page.locator('#storage-review')).toBeEnabled();

  // Verify footer reanalyse button is present and enabled
  await expect(page.locator('#storage-footer-reanalyse')).toBeVisible();
  await expect(page.locator('#storage-footer-reanalyse')).toBeEnabled();
});
