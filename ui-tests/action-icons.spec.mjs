import {test, expect} from '@playwright/test';

// Also used by the Superset Chromium acceptance pass when native WebKit cannot launch.
export async function verifyActionIconUpdates() {
  const host=document.createElement('div');document.body.append(host);
  const button=document.createElement('button');button.className='btn btn-outline';
  button.textContent='Download PDF';host.append(button);
  const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
  await settle();
  const results=[];
  const check=(name,condition)=>results.push({name,pass:Boolean(condition)});
  check('initial label unchanged',button.textContent==='Download PDF');
  check('one decorative download icon',button.querySelectorAll('[data-officekit-action-icon="download"][aria-hidden="true"]').length===1);
  button.textContent='Working…';await settle();
  check('pending update retains icon and label',button.textContent==='Working…' && button.querySelector('[data-officekit-action-icon="download"]'));
  button.textContent='Copy report';await settle();
  check('new action replaces icon',button.querySelectorAll('i').length===1 && button.querySelector('[data-officekit-action-icon="copy"]'));
  button.textContent='Reset selection';await settle();
  check('reset is quiet and text only',!button.querySelector('i') && button.classList.contains('btn-ghost') && !button.classList.contains('btn-outline'));
  const existing=document.createElement('button');existing.innerHTML='<i class="fa-solid fa-copy mr-2"></i>Copy';host.append(existing);await settle();
  check('existing icon not duplicated',existing.querySelectorAll('i').length===1 && existing.querySelector('i').getAttribute('aria-hidden')==='true');
  const tab=document.createElement('button');tab.setAttribute('role','tab');tab.textContent='Copy';host.append(tab);await settle();
  check('tabs excluded',!tab.querySelector('i'));
  const picker=document.createElement('button');picker.textContent='Choose files…';host.append(picker);await settle();picker.textContent='invoice.pdf';await settle();
  check('file selection retains affordance',picker.textContent==='invoice.pdf' && picker.querySelector('[data-officekit-action-icon="file-arrow-up"]'));
  for(const [kind,publish] of [
    ['computed',c=>officekitPublishComputedResult(c,{total:42},'Icon fixture','icon-fixture')],
    ['text',c=>officekitPublishTextResult(c,'Fixture output','Icon fixture','icon-text')],
    ['binary',c=>officekitPublishBinaryResult(c,new Blob(['fixture']),'fixture.txt','Icon fixture')],
  ]){
    const result=document.createElement('section');host.append(result);publish(result);await settle();
    const actions=[...result.querySelectorAll('.officekit-result-actions button')];
    check(`${kind} result action icons`,actions.length>0 && actions.every(b=>b.querySelector('[aria-hidden="true"].ok-button-icon')));
  }
  host.remove();return results;
}

test('dynamic action icons preserve labels, updates and quiet actions',async({page})=>{
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.OfficeKitActionIcons))).toBe(true);
  for(const result of await page.evaluate(verifyActionIconUpdates))expect(result.pass,result.name).toBe(true);
});

test('registered tool actions share icon geometry in both themes',async({page})=>{
  test.setTimeout(180_000);
  await page.route('**/api/**',route=>route.continue({
    url:route.request().url().replace('127.0.0.1:19874','127.0.0.1:19873'),
    headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`},
  }));
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  const ids=await page.evaluate(async()=>{await loadToolGallery();return allToolsCache.filter(t=>OFFICEKIT_TOOL_DESTINATIONS[t.id]).map(t=>t.id);});
  expect(ids.length).toBeGreaterThan(0);
  for(const width of [1440,900,390])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:1000});
    for(const id of ids){
      const problems=await page.evaluate(async({id,theme})=>{
        document.documentElement.dataset.theme=theme;selectSearchTool(id);
        await new Promise(resolve=>setTimeout(resolve,0));
        const section=document.getElementById('tab-'+OFFICEKIT_TOOL_DESTINATIONS[id].tab);
        const failures=[];
        for(const button of section.querySelectorAll('button')){
          if(!button.getBoundingClientRect().width)continue;
          const icons=[...button.querySelectorAll('[data-officekit-action-icon]')];
          if(icons.length>1)failures.push('Duplicate icon: '+button.textContent);
          for(const icon of icons){
            if(icon.getAttribute('aria-hidden')!=='true'||getComputedStyle(icon).width!=='16px'||getComputedStyle(button).gap!=='8px')failures.push('Icon geometry/accessibility: '+button.textContent);
          }
        }
        if(document.documentElement.scrollWidth>innerWidth)failures.push('Horizontal overflow');
        return failures;
      },{id,theme});
      expect(problems,`${id}, ${width}px, ${theme}`).toEqual([]);
    }
  }
});
