import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

function pdf(){
  const stream='BT /F1 16 Tf 40 700 Td (Original document text) Tj ET';
  const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 450 780] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let source='%PDF-1.4\n';const offsets=[0];for(const [index,obj]of objects.entries()){offsets.push(Buffer.byteLength(source));source+=`${index+1} 0 obj\n${obj}\nendobj\n`;}
  const start=Buffer.byteLength(source);source+=`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(n=>`${String(n).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n${start}\n%%EOF\n`;return source;
}

test('real PDF API opens original, edits annotation, exports native PDF and preserves source',async({context,page})=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'officekit-pdf-editor-')),original=path.join(directory,'original.pdf');await fs.writeFile(original,pdf());
  try{
    await context.addInitScript(()=>{window.__TAURI__={core:{invoke:async(command,args)=>{if(command==='file_selection_open')return window.selectedPdf;if(command==='result_save'){window.savedPdf=args;return {state:'saved'};}throw Error(`Unexpected native command ${command}`);}}};});
    await context.route('**/api/**',route=>{const url=new URL(route.request().url());return route.continue({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,origin:'tauri://localhost'}});});
    await page.goto('/');
    const granted=await page.request.post('http://127.0.0.1:19873/api/file-selections',{headers:{authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,'X-OfficeKit-Native-Grant':process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN,origin:'tauri://localhost'},data:{paths:[await fs.realpath(original)],access:'read'}});expect(granted.status()).toBe(201);
    await page.evaluate(selection=>{window.selectedPdf=selection;selectSearchTool('pdf_editor');},await granted.json());
    const editor=page.locator('#pdf-editor-workspace');await editor.getByRole('button',{name:'Choose PDF…'}).click();
    await expect(editor.getByRole('status')).toContainText('PDF ready');
    await page.evaluate(()=>dismissAppFeedbackToast());
    await page.screenshot({path:`.test-artifacts/pdf-editor-${test.info().project.name}-light.png`,fullPage:true});
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.screenshot({path:`.test-artifacts/pdf-editor-${test.info().project.name}-dark.png`,fullPage:true});
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    // Exercise the loaded inspector inside the real shell: empty-route checks
    // cannot catch toolbar overflow, clipped selects or a dock over the page.
    await editor.getByRole('button',{name:'Sign with certificate',exact:true}).click();
    for(const width of [1440,900,390]){
      await page.setViewportSize({width,height:900});
      for(const theme of ['light','dark']){
        await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
        await editor.getByRole('button',{name:'Fit page to view'}).click();
        const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(element=>element.getBoundingClientRect().right>innerWidth+1).map(element=>({tag:element.tagName,id:element.id,class:element.className,right:element.getBoundingClientRect().right})).slice(0,12));
        expect(await page.evaluate(()=>document.documentElement.scrollWidth),JSON.stringify(overflow)).toBeLessThanOrEqual(width);
        const geometry=await editor.evaluate(root=>{
          const stage=root.querySelector('.ok-pdf-stage').getBoundingClientRect();
          const paper=root.querySelector('.ok-pdf-paper').getBoundingClientRect();
          const dock=root.querySelector('.ok-pdf-dock').getBoundingClientRect();
          const bar=document.getElementById('officekit-tool-actions').getBoundingClientRect();
          const main=document.getElementById('app-main').getBoundingClientRect();
          const select=root.querySelector('select[data-signing-source]')||[...root.querySelectorAll('select')].find(element=>element.closest('.ok-pdf-inspector'));
          return {stage:{width:stage.width,height:stage.height},paper:{width:paper.width,height:paper.height},dockTop:dock.top,dockBottom:dock.bottom,barTop:bar.top,barBottom:bar.bottom,mainBottom:main.bottom,arrow:getComputedStyle(select).backgroundImage};
        });
        expect(geometry.paper.width).toBeLessThanOrEqual(geometry.stage.width);
        expect(geometry.paper.height).toBeLessThanOrEqual(geometry.stage.height);
        expect(geometry.dockTop).toBeGreaterThanOrEqual(geometry.barTop);
        expect(geometry.dockBottom).toBeLessThanOrEqual(geometry.barBottom);
        expect(geometry.mainBottom).toBeLessThanOrEqual(geometry.barTop);
        expect(geometry.arrow).not.toBe('none');
        await page.screenshot({path:`.test-artifacts/pdf-editor-certificate-${width}-${theme}.png`,fullPage:true});
      }
    }
    await page.setViewportSize(test.info().project.use.viewport);
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    await editor.getByRole('button',{name:'T Text',exact:true}).click();await editor.getByLabel('Text',{exact:true}).fill('Reviewed annotation');await editor.getByRole('button',{name:'Place on page'}).click();
    await expect(editor.getByRole('status')).toContainText('Changes applied');
    const selection=editor.locator('select[data-pdf-selection]'),annotationOption=selection.locator('option').filter({hasText:'annotation: Reviewed annotation'});await expect(annotationOption).toHaveCount(1);
    await selection.selectOption(await annotationOption.getAttribute('value'),{force:true});await editor.getByLabel('Annotation text',{exact:true}).fill('Edited annotation');
    await expect(editor.getByRole('button',{name:'Apply annotation edit'})).not.toHaveAttribute('data-officekit-docked');
    await editor.getByRole('button',{name:'Apply annotation edit'}).click();
    await expect(editor.getByRole('status')).toContainText('Changes applied');await editor.getByRole('button',{name:'Download PDF',exact:true}).click();
    await expect(editor.getByRole('status')).toHaveText('PDF saved.');
    const saved=await page.evaluate(()=>window.savedPdf);expect(saved.suggestedName).toBe('edited.pdf');expect(Buffer.from(saved.base64Data,'base64').subarray(0,5).toString()).toBe('%PDF-');expect(await fs.readFile(original,'utf8')).toBe(pdf());
  }finally{await fs.rm(directory,{recursive:true,force:true});}
});
