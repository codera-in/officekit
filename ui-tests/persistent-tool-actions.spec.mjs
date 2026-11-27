import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {setTheme} from './theme-helper.mjs';

test.beforeEach(async ({page})=>{
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    return route.continue({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`}});
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

test('file result actions remain above the app footer while the workspace scrolls',async({page},testInfo)=>{
  await page.evaluate(()=>{
    selectSearchTool('dup_finder');
    officekitDirectFilesState.selections=[{id:crypto.randomUUID(),displayNames:['Downloads'],mode:'folder',access:'read'}];
    document.getElementById('direct-duplicate-mode').value='folders';
    officekitDirectUpdateSelection();
    officekitRenderDirectReport({match_kind:'folders',complete:false,skipped_links:3,skipped_entries:3,
      groups:Array.from({length:30},(_,index)=>({size_bytes:1024,entries:[0,1].map(copy=>({id:crypto.randomUUID(),
        name:`Project-${index}${copy?' backup':''}`,full_path:`/fixture/Downloads/Project-${index}${copy?' backup':''}`,
        modified_at:'2026-10-16T10:00:00Z',file_count:2}))}))},crypto.randomUUID());
  });
  const bar=page.locator('#officekit-tool-actions');
  await expect(bar).toBeVisible();
  await expect(page.getByRole('button',{name:'Download',exact:true})).toBeVisible();
  const measure=()=>page.getByRole('button',{name:'Download',exact:true}).boundingBox();
  const before=await measure();
  await page.locator('#app-main').evaluate(main=>{main.scrollTop=main.scrollHeight;});
  const after=await measure();
  expect(after.y).toBe(before.y);
  const footer=await page.locator('footer[role=contentinfo]').boundingBox();
  expect(after.y+after.height).toBeLessThanOrEqual(footer.y);
  await expect(page.locator('#duplicate-report-details')).toContainText('3');
  await page.screenshot({path:testInfo.outputPath('duplicate-folder-persistent-actions.png')});
  for(const theme of ['light','dark']){
    await setTheme(page,theme);
    await page.locator('#app-main').evaluate(main=>{main.scrollTop=0;});
    await page.screenshot({path:testInfo.outputPath(`duplicate-folder-${theme}-top.png`)});
  }
});

test('Activity monitors background work and combines recent results with saved history',async({page})=>{
  await page.evaluate(()=>window.OfficeKitActivity.start({id:'activity-fixture',title:'Find duplicates',tool:'File utilities',tab:'workspace',phase:'Comparing file contents',progress:547,total:2381,unit:'files',insights:[{label:'Extra copies',value:'18'},{label:'Potential recovery',value:'2.4 GB',detail:'empty Trash to reclaim disk space'}],cancel:()=>{window.__activityCancelled=true;},returnTo:()=>switchTab('workspace')}));
  await expect(page.locator('[data-officekit-activity-count]').first()).toHaveText('1');
  await page.locator('#officekit-activity-mini').getByRole('button',{name:'Continue in background'}).click();
  await expect(page.locator('#tab-home')).toBeVisible();
  await page.locator('[data-sidebar-tab="activity"]').click();
  await expect(page.locator('#tab-activity')).toBeVisible();
  await expect(page.locator('#officekit-activity-content')).toContainText('547 of 2,381 files');
  await expect(page.locator('#officekit-activity-content')).toContainText('Potential recovery');
  await expect(page.locator('#officekit-activity-history')).toContainText('Saved results');
  await expect(page.locator('#officekit-activity-history')).toContainText('Recent tools');
  await page.locator('#officekit-activity-content').getByRole('button',{name:'Cancel'}).click();
  await expect.poll(()=>page.evaluate(()=>window.__activityCancelled)).toBe(true);
});

test('entering a tool auto-collapses the sidebar even after it was expanded',async({page})=>{
  await page.evaluate(()=>{window.officekitSidebarPreference=false;localStorage.setItem('officekit.sidebar.collapsed','false');});
  await page.evaluate(()=>selectSearchTool('dup_finder'));
  await expect(page.locator('#app-sidebar')).toHaveClass(/ok-collapsed/);
  await expect(page.locator('#sidebar-toggle')).toHaveAttribute('aria-expanded','false');
});

test('all allowed tool routes have persistent actions and browsing screens have no empty bar',async({page},testInfo)=>{
  test.setTimeout(180000);
  const tools=await page.evaluate(async()=>{await loadToolGallery();return allToolsCache.filter(tool=>OFFICEKIT_TOOL_DESTINATIONS[tool.id]).map(tool=>tool.id);});
  const matrix=[];
  const initialViewport=page.viewportSize();
  for(const viewport of [initialViewport,{width:390,height:844}]){
  await page.setViewportSize(viewport);
  for(const theme of ['light','dark']){
    await setTheme(page,theme);
    for(const id of tools){
      await page.evaluate(async id=>{selectSearchTool(id);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));window.OfficeKitToolActions?.refresh();},id);
      const geometry=await page.evaluate(()=>{
        const bar=document.querySelector('#officekit-tool-actions').getBoundingClientRect();
        const main=document.querySelector('#app-main').getBoundingClientRect();
        const sources=[...document.querySelectorAll('[data-officekit-docked]')];
        const controls=sources.flatMap(source=>[source,...source.querySelectorAll('button,select')]).filter(element=>element.getClientRects().length&&!element.closest('[hidden],.hidden'));
        return {count:sources.length,visible:bar.height>0,mainBottom:main.bottom,barTop:bar.top,
          bounds:controls.map(source=>({id:source.id,label:source.textContent.trim().slice(0,50),top:source.getBoundingClientRect().top,bottom:source.getBoundingClientRect().bottom,left:source.getBoundingClientRect().left,right:source.getBoundingClientRect().right,barBottom:bar.bottom,barRight:bar.right})),
          fits:controls.every(source=>{const r=source.getBoundingClientRect();return r.top>=bar.top&&r.bottom<=bar.bottom+1&&r.left>=bar.left&&r.right<=bar.right+1;})};
      });
      matrix.push({id,theme,viewport:viewport.width,...geometry});
    }
  }
  }
  for(const tab of ['home','tools','recents','favorites','history','pricing']){
    await page.evaluate(tab=>{switchTab(tab);window.OfficeKitToolActions?.refresh();},tab);
    // Browsing pages show no bottom bar at all: there is no task to put in it.
    await expect(page.locator('#officekit-tool-actions'),tab).toBeHidden();
  }
  const evidence = JSON.stringify({project:testInfo.project.name,matrix},null,2);
  await writeFile(testInfo.outputPath('tool-action-matrix.json'),evidence);
  await testInfo.attach('tool-action-matrix',{body:evidence,contentType:'application/json'});
  // The bar appears exactly when a tool has task actions; a tool with none shows no bar.
  expect(matrix.filter(row=>row.visible!==(row.count>0)||(row.count>0&&(!row.fits||row.mainBottom>row.barTop+1)))).toEqual([]);
});
