import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const editorCss=readFileSync(new URL('../assets/officekit-pdf-editor.css',import.meta.url),'utf8');
const context=vm.createContext({});
vm.runInContext(readFileSync(new URL('../assets/officekit-pdf-editor.js',import.meta.url),'utf8'),context);
const {pointInPage,displayPoint}=context.OfficeKitPdfEditor;

function mediaRule(css, rule) {
  const start=css.indexOf(rule);
  assert.notEqual(start,-1,`missing ${rule}`);
  const open=css.indexOf('{',start);
  let depth=0;
  for(let index=open;index<css.length;index++){
    if(css[index]==='{')depth++;
    else if(css[index]==='}'&&--depth===0)return css.slice(open+1,index);
  }
  assert.fail(`unclosed ${rule}`);
}

test('approved compact PDF layout switches at 760 px and keeps selectors, inspector and dock in flow',()=>{
  const compact=mediaRule(editorCss,'@media(max-width:760px)');
  for(const rule of [
    '.ok-pdf-editor { display:flex; flex-direction:column; }',
    '.ok-pdf-source { order:1; }',
    '.ok-pdf-toolbar { order:2; }',
    '.ok-pdf-layout { order:4; }',
    '.ok-pdf-context:not(.ok-pdf-nav) { order:5; }',
    '.ok-pdf-dock { order:6; }',
    '.ok-pdf-layout:has(.ok-pdf-inspector:not([hidden])) { grid-template-columns:minmax(0,1fr); }',
    '.ok-pdf-toolbar .ok-pdf-compact-controls { display:grid;',
    '.ok-pdf-toolbar > .ok-pdf-group,.ok-pdf-toolbar > button,.ok-pdf-toolbar > label { display:none; }',
  ])assert.ok(compact.includes(rule),`compact rule must include ${rule}`);
  assert.match(editorCss,/\.ok-pdf-compact-controls\s*\{\s*display:none;\s*\}/);
  assert.match(editorCss,/\.ok-pdf-dock\s*\{\s*position:static;/);
});

test('PDF pointer coordinates round-trip across cropped rotated pages',()=>{
  for(const rotation of [0,90,180,270]){
    const geometry={width:400,height:600,crop_box:[20,30,420,630],rotation};
    const rect={left:100,top:50,width:rotation%180?600:400,height:rotation%180?400:600};
    for(const [u,v]of [[0,0],[1,1],[.2,.7],[.9,.1]]){
      const point=pointInPage(rect.left+u*rect.width,rect.top+v*rect.height,rect,geometry);
      assert.ok(point.x>=20&&point.x<=420&&point.y>=30&&point.y<=630);
      const display=displayPoint(point.x,point.y,geometry);
      assert.ok(Math.abs(display.x-u*rect.width)<1e-8);
      assert.ok(Math.abs(display.y-v*rect.height)<1e-8);
    }
  }
});
test('pointer outside page is clamped to crop bounds',()=>{
  const p=pointInPage(-20,800,{left:0,top:0,width:100,height:200},{width:100,height:200,crop_box:[10,20,110,220]});
  assert.equal(p.x,10);assert.equal(p.y,20);
});

test('moving and resizing ink preserves appearance and transforms every point',()=>{
  const original={id:'ink',kind:'annotation',page:1,x:10,y:20,width:20,height:40,
    annotation_type:'freehand',text:'',color:'#123456',outer_color:'#abcdef',stroke_width:5,outer_width:3,font:'Courier',font_size:24,points:[[10,20],[30,60]]};
  const moved=context.OfficeKitPdfEditor.annotationChange(original,[20,40,60,120]);
  assert.deepEqual(JSON.parse(JSON.stringify(moved)),{kind:'annotation',action:'replace',object_id:'ink',page:1,rect:[20,40,60,120],annotation_type:'freehand',text:'',color:'#123456',outer_color:'#abcdef',stroke_width:5,outer_width:3,font:'Courier',font_size:24,points:[[20,40],[60,120]]});
});

test('drag preview uses actual rectangle circle and translucent highlight geometry',()=>{
  const g={width:100,height:200,crop_box:[0,0,100,200]};
  const points=[{x:10,y:20},{x:40,y:60}];
  const rectangle=context.OfficeKitPdfEditor.previewDescriptor('rectangle',points,g);
  assert.equal(rectangle.tag,'rect');assert.equal(rectangle.attrs.width,30);assert.equal(rectangle.attrs.height,40);
  const circle=context.OfficeKitPdfEditor.previewDescriptor('circle',points,g);
  assert.equal(circle.tag,'ellipse');assert.equal(circle.attrs.rx,15);assert.equal(circle.attrs.ry,20);
  assert.equal(context.OfficeKitPdfEditor.previewDescriptor('highlight',points,g).attrs['fill-opacity'],.3);
});

test('compact PDF editor keeps page number entry and hides paging action buttons',()=>{
  const compact=mediaRule(editorCss,'@media(max-width:760px)');
  assert.match(compact,/\.ok-pdf-nav > button\s*\{\s*display:none;\s*\}/);
  assert.match(editorCss,/\.ok-pdf-file-link\s*\{[^}]*text-decoration:underline/);
});
