import { test, expect } from '@playwright/test';

test.beforeEach(async({page,context})=>{
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!=='http://127.0.0.1:19874')return route.abort();
    if(url.pathname.startsWith('/api/'))return route.continue({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`}});
    return route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#tab-home')).toBeVisible();
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
});

test('Home shows at most five deduplicated recents and retains explicit sidebar preference',async({page})=>{
  await page.evaluate(async()=>{await loadToolGallery();const ids=allToolsCache.filter(tool=>OFFICEKIT_TOOL_DESTINATIONS[tool.id]).slice(0,7).map(tool=>tool.id);ids.forEach(selectSearchTool);selectSearchTool(ids[0]);switchTab('home');});
  await expect(page.locator('#tool-gallery-recent [data-open-tool]')).toHaveCount(5);
  await page.evaluate(()=>officekitSetSidebarCollapsed(false,true));
  await page.locator('#sidebar-toggle').click();
  await expect(page.locator('#sidebar-toggle')).toHaveAttribute('aria-expanded','false');
  await page.evaluate(()=>switchTab('tools'));
  await expect(page.locator('#sidebar-toggle')).toHaveAttribute('aria-expanded','false');
  await page.locator('#sidebar-toggle').click();
  await expect(page.locator('#sidebar-toggle')).toHaveAttribute('aria-expanded','true');
});

test('every allowed registry tool opens its exact workspace and reordered unlock phrases match',async({page})=>{
  const routes=await page.evaluate(async()=>{await loadToolGallery();return allToolsCache.map(tool=>({id:tool.id,destination:OFFICEKIT_TOOL_DESTINATIONS[tool.id]?.tab}));});
  expect(routes.length).toBeGreaterThan(0);
  for(const route of routes){expect(route.destination,route.id).toBeTruthy();expect(await page.evaluate(id=>selectSearchTool(id),route.id),route.id).toBe(true);await expect(page.locator(`#tab-${route.destination}`),route.id).toBeVisible();}
  for(const query of ['PDF unlock','unlock PDF','unlock PDFs','unlock unlock pdf']){
    const ids=await page.evaluate(async q=>(await(await fetch(officekitApiUrl(`/api/tools/search?q=${encodeURIComponent(q)}`))).json()).tools.map(tool=>tool.id),query);
    expect(ids,query).toContain('pdf_unlock');
  }
});

test('Home search clears a previously selected category before searching all tools',async({page})=>{
  await page.evaluate(()=>switchTab('tools'));
  await page.locator('#tool-gallery-category').selectOption('Audio & Dictation');
  await page.evaluate(()=>switchTab('home'));
  await page.evaluate(()=>switchTab('tools'));
  await page.locator('#tool-gallery-search').fill('unlock unlock pdf');
  await expect(page.locator('#tool-gallery-category')).toHaveValue('');
  await expect(page.locator('#tool-gallery-search')).toHaveValue('unlock unlock pdf');
  await expect(page.locator('[data-open-tool="pdf_unlock"]')).toBeVisible();
});

test('scalar results share Copy and Download while preserving computed inputs',async({page})=>{
  await page.evaluate(()=>selectSearchTool('loan_emi'));
  await page.locator('#emi-principal').fill('25000');
  await page.locator('#emi-rate').fill('7.5');
  await page.locator('#emi-years').fill('5');
  await page.evaluate(()=>runEmiCalc());
  await expect(page.locator('#emi-result [data-copy-calculation]')).toBeVisible();
  await expect(page.locator('#emi-result [data-export-calculation]')).toHaveText('Download…');
  const text=await page.evaluate(()=>officekitResultSnapshotText(officekitCurrentCalculationSnapshot));
  expect(text).toContain('25000');expect(text).toContain('7.5');
});

test('screenshot objects retain independent colors and can move, delete and undo',async({page})=>{
  await page.evaluate(()=>switchTab('screenshot'));
  const rendered=page.waitForResponse(response=>response.url().includes('/api/screenshot/edit'));
  await page.evaluate(async()=>{const canvas=document.createElement('canvas');canvas.width=200;canvas.height=140;canvas.getContext('2d').fillStyle='#fff';canvas.getContext('2d').fillRect(0,0,200,140);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));await officekitLoadScreenshot(new File([blob],'sample.png',{type:'image/png'}));officekitScreenshotSetTool('rectangle');document.getElementById('screenshot-mask-color').value='#d94b2d';document.getElementById('screenshot-outer-color').value='#ffffff';await officekitApplyScreenshotRegion(10,10,80,50);});
  const renderResponse=await rendered;
  expect(renderResponse.status(),`${await renderResponse.text()}\n${renderResponse.request().postData()}`).toBe(200);
  await expect(page.locator('#screenshot-status')).toContainText('added');
  await expect(page.locator('#screenshot-dimensions')).toContainText('1 edit');
  await page.locator('#screenshot-tool-select').click();
  await page.locator('#screenshot-canvas').click({ position: { x: 50, y: 35 } });
  await page.locator('#screenshot-canvas').focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(()=>page.evaluate(()=>officekitScreenshot.operations[0]?.x)).toBe(11);
  await page.keyboard.press('Delete');
  await expect.poll(()=>page.evaluate(()=>officekitScreenshot.operations.length)).toBe(0);
  await page.locator('#screenshot-undo-button').click();
  await expect.poll(()=>page.evaluate(()=>officekitScreenshot.operations.length)).toBe(1);
  expect(await page.evaluate(()=>officekitScreenshot.operations[0].outer_color)).toBe('#ffffff');
});

test('filesystem selection never falls back to copying inputs in a browser',async({page})=>{
  await page.evaluate(()=>selectSearchTool('file_hash'));
  await page.getByRole('button',{name:'Choose files…',exact:true}).click();
  await expect(page.locator('#direct-file-status')).toContainText('No files have been copied');
  await expect(page.locator('#direct-file-run')).toBeDisabled();
});
