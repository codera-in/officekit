import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const outcome=readFileSync(new URL('../assets/officekit-outcome.js',import.meta.url),'utf8');
const script=outcome+'\n'+readFileSync(new URL('../assets/officekit-pdf-editor.js',import.meta.url),'utf8');
const css=readFileSync(new URL('../assets/officekit-pdf-editor.css',import.meta.url),'utf8');
const tokens=readFileSync(new URL('../design/officekit-tokens.css',import.meta.url),'utf8');
const appCss=readFileSync(new URL('../dist-ui/assets/officekit.css',import.meta.url),'utf8');
test('PDF workspace applies placement, restores revision, and recovers from stale revision',async({page})=>{
  await page.setContent('<main id="editor"></main>');await page.addStyleTag({content:tokens+css});await page.addScriptTag({content:script});
  await page.evaluate(()=>{
    window.calls=[];window.failRevision=false;
    const doc={id:'document',revision:0,page_count:1,pages:[{page:1,width:400,height:600,rotation:0,crop_box:[0,0,400,600]}],permissions:{can_edit:true,can_sign:true}};
    window.OfficeKitPdfEditor.mount(document.querySelector('#editor'),{apiFetch:async(path,init)=>{
      window.calls.push({path,body:typeof init.body==='string'?JSON.parse(init.body):null});
      if(path.endsWith('/api/pdf-documents'))return new Response(JSON.stringify(doc));
      if(path.includes('/previews/'))return new Response(new Uint8Array(),{headers:{'Content-Type':'image/png'}});
      if(path.includes('/objects?'))return new Response(JSON.stringify({objects:[]}));
      if(path.endsWith('/revisions'))return new Response(JSON.stringify(window.failRevision?{detail:'Document changed'}:{revision:JSON.parse(init.body).restore_revision===0?2:1}),{status:window.failRevision?409:201});
      return new Response('{}');
    }}).openFile(new File(['%PDF-1.7'],'example.pdf',{type:'application/pdf'}));
  });
  await expect(page.getByText('PDF ready. Choose a tool to begin.')).toBeVisible();
  await page.getByRole('button',{name:'T Text',exact:true}).click();
  await page.getByLabel('Text',{exact:true}).fill('Approved note');
  await page.getByRole('button',{name:'Place on page'}).click();
  await expect(page.getByText('of 1 · revision 1')).toBeVisible();
  expect(await page.evaluate(()=>window.calls.find(c=>c.path.endsWith('/revisions')).body.operations[0])).toMatchObject({kind:'annotation',annotation_type:'text',page:1,text:'Approved note',rect:[36,36,196,76]});
  await expect(page.getByRole('button',{name:'↖ Select',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'Undo',exact:true}).click();await expect(page.getByText('of 1 · revision 2')).toBeVisible();
  expect(await page.evaluate(()=>window.calls.filter(c=>c.path.endsWith('/revisions')).at(-1).body)).toEqual({base_revision:1,restore_revision:0});
  await page.evaluate(()=>{window.failRevision=true;});await page.getByRole('button',{name:'T Text',exact:true}).click();await page.getByRole('button',{name:'Place on page'}).click();
  await expect(page.getByRole('alert')).toContainText('Document changed');await expect(page.getByText('of 1 · revision 2')).toBeVisible();
});
test('compact loaded PDF editor keeps page selection while showing only three task buttons',async({page})=>{
  await page.setViewportSize({width:390,height:800});
  await page.setContent('<main id="editor"></main>');await page.addStyleTag({content:tokens+css});await page.addScriptTag({content:script});
  await page.evaluate(()=>{
    const doc={id:'compact-document',revision:0,page_count:2,pages:[{page:1,width:400,height:600,rotation:0,crop_box:[0,0,400,600]},{page:2,width:400,height:600,rotation:0,crop_box:[0,0,400,600]}],permissions:{can_edit:true,can_sign:true}};
    window.OfficeKitPdfEditor.mount(document.querySelector('#editor'),{apiFetch:async path=>{
      if(path==='/api/pdf-documents')return new Response(JSON.stringify(doc),{status:201});
      if(path.includes('/objects?'))return new Response(JSON.stringify({objects:[]}));
      if(path.includes('/previews/'))return new Response(new Uint8Array(),{headers:{'Content-Type':'image/png'}});
      return new Response('{}');
    }}).openFile(new File(['%PDF-1.7'],'original.pdf',{type:'application/pdf'}));
  });
  await expect(page.getByRole('status')).toContainText('PDF ready');
  await expect(page.getByRole('link',{name:'Replace PDF…'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Choose PDF…'})).toBeHidden();
  await expect(page.getByRole('button',{name:'Previous page'})).toBeHidden();
  await expect(page.getByRole('button',{name:'Next page'})).toBeHidden();
  await expect(page.getByRole('spinbutton',{name:'Page'})).toHaveValue('1');
  await expect(page.getByRole('combobox',{name:'Mode'})).toBeVisible();
  await expect(page.getByRole('combobox',{name:'Tool'})).toBeVisible();
  const taskButtons=await page.locator('.ok-pdf-editor button:visible').evaluateAll(buttons=>buttons.filter(button=>!button.closest('.ok-pdf-thumbnails')).map(button=>button.textContent.trim()));
  expect(taskButtons).toEqual(['Clear','Download PDF','Verify signatures']);
});
test('certificate credentials are cleared after provider failure',async({page})=>{
  await page.setContent('<main id="editor"></main>');await page.addScriptTag({content:script});
  await page.evaluate(()=>window.OfficeKitPdfEditor.mount(document.querySelector('#editor'),{apiFetch:async(path)=>{
    if(path==='/api/pdf-documents')return new Response(JSON.stringify({id:'d',revision:0,page_count:1,pages:[{page:1,width:400,height:600}],permissions:{can_edit:true}}));
    if(path.includes('/objects?'))return new Response('{"objects":[]}');if(path.includes('/previews/'))return new Response('');return new Response('{"detail":"Incorrect certificate password"}',{status:422});
  }}).openFile(new File(['pdf'],'doc.pdf')));
  await expect(page.getByRole('button',{name:'Sign with certificate'})).toBeVisible();await page.getByRole('button',{name:'Sign with certificate'}).click();
  await page.getByLabel('Certificate file',{exact:true}).setInputFiles({name:'certificate.p12',mimeType:'application/x-pkcs12',buffer:Buffer.from('certificate')});
  await page.getByLabel('Certificate password / token PIN').fill('wrong-secret');await page.getByRole('button',{name:'Read certificates'}).click();
  await expect(page.getByLabel('Certificate password / token PIN')).toHaveValue('');await expect(page.getByRole('alert')).toContainText('Incorrect certificate password');
});

test('Fit uses the visible page area, zoom requests sharper previews, and PDF controls remain clear',async({page})=>{
  await page.setViewportSize({width:1280,height:900});await page.setContent('<main id="editor" class="ok-app"></main>');await page.addStyleTag({content:appCss+tokens+css});await page.addScriptTag({content:script});
  await page.evaluate(()=>{
    window.previewScales=[];
    const doc={id:'fit-document',revision:0,page_count:1,pages:[{page:1,width:450,height:780,rotation:0,crop_box:[0,0,450,780]}],permissions:{can_edit:true,can_sign:true}};
    window.OfficeKitPdfEditor.mount(document.querySelector('#editor'),{apiFetch:async(path)=>{
      if(path==='/api/pdf-documents')return new Response(JSON.stringify(doc));
      if(path.includes('/previews/')){window.previewScales.push(Number(new URLSearchParams(path.split('?')[1]).get('scale')));return new Response(new Uint8Array([1]),{headers:{'Content-Type':'image/png'}});}
      if(path.includes('/objects?'))return new Response(JSON.stringify({objects:[]}));
      return new Response('{}');
    }}).openFile(new File(['%PDF-1.7'],'fit.pdf',{type:'application/pdf'}));
  });
  const editor=page.locator('#editor');await expect(editor.getByRole('status')).toContainText('PDF ready');
  const paper=editor.locator('.ok-pdf-paper'),stage=editor.locator('.ok-pdf-stage');
  const fittedWidth=await paper.evaluate(element=>element.getBoundingClientRect().width);
  const expectedWidth=await paper.evaluate(element=>{const stage=element.parentElement,style=getComputedStyle(stage),size={width:450,height:780};const x=stage.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),y=stage.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);return size.width*Math.min(x/size.width,y/size.height);});
  expect(fittedWidth).toBeCloseTo(expectedWidth,0);
  await editor.getByRole('button',{name:'Zoom in'}).click();
  expect(await page.evaluate(()=>document.querySelector('#editor').pdfEditor.state.zoom)).toBe(1.25);
  await editor.getByRole('button',{name:'Fit page to view'}).click();
  expect(await page.evaluate(()=>document.querySelector('#editor').pdfEditor.state.zoom)).toBe(1);
  expect(await paper.evaluate(element=>element.getBoundingClientRect().width)).toBeCloseTo(fittedWidth,0);
  for(let i=0;i<12;i++)await editor.getByRole('button',{name:'Zoom in'}).click();
  await expect.poll(()=>page.evaluate(()=>Math.max(...window.previewScales))).toBeGreaterThan(1);
  await editor.getByRole('button',{name:'Sign with certificate',exact:true}).click();
  const source=editor.getByLabel('Certificate source');
  const arrow=await source.evaluate(element=>getComputedStyle(element).backgroundImage);
  expect(arrow).not.toBe('none');
  expect(await editor.locator('.ok-pdf-dock').evaluate(element=>getComputedStyle(element).position)).toBe('static');
  expect(await stage.evaluate(element=>element.scrollHeight)).toBeGreaterThanOrEqual(await stage.evaluate(element=>element.clientHeight));
});

test('styled movement, certificate placement and reviewed OCR retain their visible context',async({page})=>{
  await page.setContent('<main id="editor"></main>');await page.addStyleTag({content:tokens+css});await page.addScriptTag({content:script});
  await page.evaluate(async()=>{
    const canvas=document.createElement('canvas');canvas.width=400;canvas.height=600;const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,400,600);ctx.fillStyle='black';ctx.fillText('Scanned text',30,60);const png=await new Promise(r=>canvas.toBlob(r));
    window.pdfCalls=[];let revision=0;
    const object={id:'ink',kind:'annotation',page:1,x:20,y:30,width:50,height:40,editable:true,annotation_type:'freehand',text:'',color:'#123456',outer_color:'#abcdef',stroke_width:5,outer_width:3,font:'Courier',font_size:24,points:[[20,30],[70,70]]};
    window.OfficeKitPdfEditor.mount(document.querySelector('#editor'),{apiFetch:async(path,init)=>{
      const body=typeof init.body==='string'?JSON.parse(init.body):null;window.pdfCalls.push({path,body});
      if(path==='/api/pdf-documents')return new Response(JSON.stringify({id:'d',revision:0,page_count:1,pages:[{page:1,width:400,height:600,rotation:0,crop_box:[0,0,400,600]}],permissions:{can_edit:true,can_sign:true}}));
      if(path.includes('/previews/'))return new Response(png);
      if(path.includes('/objects?'))return new Response(JSON.stringify({objects:[object]}));
      if(path.endsWith('/revisions'))return new Response(JSON.stringify({revision:++revision}));
      if(path.endsWith('/ocr-reviews'))return new Response(JSON.stringify({id:'ocr',state:'ready',result:{review_id:'review',regions:[{id:'r1',page:1,rect:[20,520,120,560],text:'Scanned text'}]}}));
      if(path==='/api/pdf-signing-providers')return new Response(JSON.stringify({id:'provider',certificates:[{id:'cert',subject:'Test signer',issuer:'Test issuer',valid_from:'2026-01-01',valid_until:'2027-01-01'}]}));
      return new Response('{}');
    }}).openFile(new File(['%PDF'],'test.pdf'));
  });
  await expect(page.getByRole('status')).toContainText('PDF ready');
  await page.locator('[data-pdf-selection]').selectOption('ink');
  await page.locator('svg').focus();await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('status')).toContainText('Changes applied');
  const move=await page.evaluate(()=>window.pdfCalls.find(c=>c.path.endsWith('/revisions')).body.operations[0]);
  expect(move).toMatchObject({color:'#123456',outer_color:'#abcdef',stroke_width:5,outer_width:3,font:'Courier',font_size:24,points:[[21,30],[71,70]]});
  await page.getByRole('button',{name:'Sign with certificate',exact:true}).click();
  await expect(page.locator('.ok-pdf-dock').getByRole('button',{name:'Sign PDF',exact:true})).toBeVisible();
  await expect(page.locator('.ok-pdf-inspector').getByRole('button',{name:'Sign PDF',exact:true})).toHaveCount(0);
  await page.getByLabel('X',{exact:true}).fill('65');
  await expect(page.locator('[data-signature-placement]')).toHaveAttribute('x','65');
  await page.getByLabel('Certificate file',{exact:true}).setInputFiles({name:'a.p12',mimeType:'application/x-pkcs12',buffer:Buffer.from('certificate')});
  await page.getByRole('button',{name:'Read certificates',exact:true}).click();
  await expect(page.getByText(/Valid: 2026-01-01 — 2027-01-01/)).toBeVisible();
  await page.getByRole('combobox',{name:'Mode',exact:true}).selectOption('edit');
  await page.getByRole('button',{name:'Recognise scanned text',exact:true}).click();
  await page.getByRole('button',{name:'Recognise this page',exact:true}).click();
  await expect(page.getByRole('img',{name:/Original scan region on page 1/})).toBeVisible();
  await page.getByLabel('Recognised region r1').fill('Corrected scan');
  await page.getByLabel('I reviewed the text and accept page rasterisation and font/layout changes').check();
  await page.getByRole('button',{name:'Apply reviewed text',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Changes applied');
  await expect(page.getByRole('img',{name:/Original scan region on page 1/})).toBeVisible();
  const apply=await page.evaluate(()=>window.pdfCalls.filter(c=>c.path.endsWith('/revisions')).at(-1).body.operations[0]);
  expect(apply).toMatchObject({kind:'apply_ocr',region_id:'r1',review_id:'review',text:'Corrected scan',rect:[20,520,120,560]});
});
