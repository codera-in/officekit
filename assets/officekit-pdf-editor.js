/* Local PDF workspace. Secrets are read once from live fields and never enter session state. */
(function (global) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const limit = (value, min, max) => Math.min(max, Math.max(min, Number(value) || min));
  function pointInPage(clientX, clientY, rect, geometry) {
    const u = limit((clientX - rect.left) / rect.width, 0, 1);
    const v = limit((clientY - rect.top) / rect.height, 0, 1);
    const crop=geometry.crop_box||[0,0,geometry.width,geometry.height];
    const w=crop[2]-crop[0],h=crop[3]-crop[1];let point;
    switch ((geometry.rotation || 0) % 360) {
      case 90: point={x:v*w, y:u*h};break;
      case 180: point={x:(1-u)*w, y:v*h};break;
      case 270: point={x:(1-v)*w, y:(1-u)*h};break;
      default: point={x:u*w, y:(1-v)*h};
    }
    return {x:point.x+crop[0],y:point.y+crop[1]};
  }
  function displayPoint(x, y, geometry) {
    const crop=geometry.crop_box||[0,0,geometry.width,geometry.height];
    const w=crop[2]-crop[0],h=crop[3]-crop[1];x-=crop[0];y-=crop[1];
    switch ((geometry.rotation || 0)%360) {
      case 90:return {x:y,y:x};
      case 180:return {x:w-x,y};
      case 270:return {x:h-y,y:w-x};
      default:return {x,y:h-y};
    }
  }
  function annotationChange(obj, rect, overrides={}) {
    const [x,y,right,top]=rect,sx=(right-x)/obj.width,sy=(top-y)/obj.height;
    return {kind:'annotation',action:'replace',object_id:obj.id,page:obj.page,rect,
      annotation_type:obj.annotation_type,text:obj.text||'',color:obj.color||'#000000',
      outer_color:obj.outer_color||'#ffffff',stroke_width:obj.stroke_width??2,outer_width:obj.outer_width??0,
      font:obj.font||'Helvetica',font_size:obj.font_size??12,
      points:(obj.points||[]).map(p=>[x+(p[0]-obj.x)*sx,y+(p[1]-obj.y)*sy]),...overrides};
  }
  function previewDescriptor(tool, points, geometry) {
    const p=points.map(p=>displayPoint(p.x,p.y,geometry));
    const x=Math.min(...p.map(v=>v.x)),y=Math.min(...p.map(v=>v.y)),w=Math.max(...p.map(v=>v.x))-x,h=Math.max(...p.map(v=>v.y))-y;
    if(['rectangle','highlight','certificate'].includes(tool))return {tag:'rect',attrs:{x,y,width:w,height:h,fill:tool==='highlight'?'currentColor':'none','fill-opacity':tool==='highlight'?.3:0}};
    if(tool==='circle')return {tag:'ellipse',attrs:{cx:x+w/2,cy:y+h/2,rx:w/2,ry:h/2,fill:'none'}};
    return {tag:'path',attrs:{d:p.map((v,i)=>`${i?'L':'M'}${v.x} ${v.y}`).join(' '),fill:'none'}};
  }
  function node(tag, text, className) {
    const el=document.createElement(tag); if(text !== undefined)el.textContent=text;
    if(className)el.className=className;return el;
  }
  function mount(root, options={}) {
    if(root.pdfEditor)return root.pdfEditor;
    root.classList.add('ok-pdf-editor');
    const state={document:null,page:1,revision:0,history:[0],cursor:0,tool:'select',mode:'annotate',objects:[],selected:null,zoom:1,previewScale:0,previewUrl:null,previewGeneration:0,busy:false,provider:null,placement:null,artifact:null,urls:new Set(),thumbnailUrls:new Set(),destroyed:false,epoch:0};
    const ui={};
    const button=(label,action,parent,className='')=>{const b=node('button',label,`btn ${className.includes('primary')?'btn-primary':'btn-outline'} ${className}`);b.type='button';b.onclick=()=>run(action);if(parent)parent.append(b);return b;};
    const input=(label,type,value,parent)=>{const wrap=node('label',label);const el=node('input',undefined,type==='checkbox'?'checkbox checkbox-primary':type==='range'?'range range-primary':'input ');el.type=type;if(value!==undefined)el.value=value;wrap.append(el);parent.append(wrap);return el;};
    const select=(label,items,parent)=>{const wrap=node('label',label),el=node('select',undefined,'select ');for(const [value,text]of items){const option=node('option',text);option.value=value;el.append(option);}wrap.append(el);parent.append(wrap);return el;};
    const row=(parent,cls='')=>{const el=node('div',undefined,`ok-pdf-row ${cls}`);parent.append(el);return el;};
    function status(message,error=false){officekitOutcome.show(ui.status,{state:error?'error':'info',text:message});if(error&&options.notify)options.notify(message);}
    async function request(path,body,method='POST') {
      const init={method};if(body instanceof FormData)init.body=body;else if(body!==undefined){init.headers={'Content-Type':'application/json'};init.body=JSON.stringify(body);}
      const response=await (options.apiFetch||global.fetch.bind(global))(path,init);
      if(!response.ok){let data;try{data=await response.json();}catch{}const detail=data?.detail;const message=typeof detail==='string'?detail:(detail?.message||data?.error?.message||'The PDF operation failed. Review the selection and try again.');throw Error(response.status===409?`${message} Reopen the document if its revision changed.`:message);}
      return response;
    }
    async function json(path,body,method){return (await request(path,body,method)).json();}
    async function run(action){if(state.busy||state.destroyed)return;state.busy=true;update();try{await action();}catch(error){status(error.message,true);}finally{state.busy=false;update();}}
    const source=row(root,'ok-pdf-source');
    ui.name=node('strong','Choose a PDF');source.append(ui.name);
    ui.open=button('Choose PDF…',choose,source);
    ui.replace=node('a','Replace PDF…','ok-pdf-file-link');ui.replace.href='#';ui.replace.hidden=true;ui.replace.addEventListener('click',event=>{event.preventDefault();if(!state.busy)void run(choose);});source.append(ui.replace);
    ui.clear=button('Clear',clear,source);ui.clear.hidden=true;
    const toolbar=row(root,'ok-pdf-toolbar');ui.toolbar=toolbar;toolbar.hidden=true;
    ui.mode=select('Mode',[['annotate','Annotate'],['edit','Edit PDF']],toolbar);ui.mode.onchange=()=>{state.mode=ui.mode.value;setTool('select');update();};
    const annotations=row(toolbar,'ok-pdf-group');ui.annotations=annotations;
    ui.tools={};
    const tool=(key,label,parent)=>{const b=button(label,()=>setTool(key),parent);b.dataset.pdfTool=key;b.setAttribute('aria-pressed','false');ui.tools[key]=b;return b;};
    tool('select','↖ Select',annotations);tool('freehand','✎ Freehand',annotations);
    ui.shapes=select('Shapes',[['','Shapes…'],['rectangle','Rectangle'],['circle','Circle'],['line','Line']],annotations);ui.shapes.onchange=()=>{if(ui.shapes.value)setTool(ui.shapes.value);ui.shapes.value='';};
    tool('highlight','▧ Highlight',annotations);tool('text','T Text',annotations);
    ui.callouts=select('Callouts',[['','Callouts…'],['arrow','Arrow'],['callout','Text callout']],annotations);ui.callouts.onchange=()=>{if(ui.callouts.value)setTool(ui.callouts.value);ui.callouts.value='';};tool('eraser','⌫ Eraser',annotations);
    const edits=row(toolbar,'ok-pdf-group');ui.edits=edits;
    for(const [key,label]of [['edit_text','Edit text'],['edit_image','Edit images'],['add_text','Add text'],['add_image','Add image']])tool(key,label,edits);
    tool('ocr','Recognise scanned text',edits);
    const view=row(toolbar,'ok-pdf-group');tool('pan','✋ Pan',view);
    button('−',()=>setZoom(state.zoom-.25),view).setAttribute('aria-label','Zoom out');
    button('+',()=>setZoom(state.zoom+.25),view).setAttribute('aria-label','Zoom in');button('Fit',()=>setZoom(1),view).setAttribute('aria-label','Fit page to view');
    ui.undo=button('↶',()=>history(-1),toolbar);ui.undo.setAttribute('aria-label','Undo');ui.redo=button('↷',()=>history(1),toolbar);ui.redo.setAttribute('aria-label','Redo');
    tool('signature','Signature appearance',toolbar);tool('certificate','Sign with certificate',toolbar);
    const compactControls=node('div',undefined,'ok-pdf-compact-controls');toolbar.append(compactControls);
    const compactMode=select('Mode',[['annotate','Annotate'],['edit','Edit PDF']],compactControls);compactMode.value=state.mode;compactMode.onchange=()=>{state.mode=compactMode.value;setTool('select');update();};
    const compactToolItems=[['select','Select'],['freehand','Freehand'],['rectangle','Rectangle'],['circle','Circle'],['line','Line'],['highlight','Highlight'],['text','Text'],['arrow','Arrow'],['callout','Text callout'],['eraser','Eraser'],['edit_text','Edit text'],['edit_image','Edit images'],['add_text','Add text'],['add_image','Add image'],['ocr','Recognise scanned text'],['signature','Signature appearance'],['certificate','Sign with certificate']];
    const compactTool=select('Tool',compactToolItems,compactControls);compactTool.value=state.tool;compactTool.onchange=()=>{const key=compactTool.value;if((key==='edit_text'||key==='edit_image'||key==='add_text'||key==='add_image'||key==='ocr')&&state.mode!=='edit'){state.mode='edit';compactMode.value='edit';}else if(!['edit_text','edit_image','add_text','add_image','ocr'].includes(key)&&state.mode!=='annotate'){state.mode='annotate';compactMode.value='annotate';}setTool(key);update();};
    const compactView=select('View',[['fit','Fit page'],['in','Zoom in'],['out','Zoom out'],['pan','Pan']],compactControls);compactView.onchange=()=>{if(compactView.value==='in')setZoom(state.zoom+.25);else if(compactView.value==='out')setZoom(state.zoom-.25);else if(compactView.value==='pan')setTool('pan');else setZoom(1);compactView.value='fit';};
    const compactHistory=select('History',[['','Undo or redo'],['undo','Undo'],['redo','Redo']],compactControls);compactHistory.onchange=()=>{if(compactHistory.value)history(compactHistory.value==='undo'?-1:1);compactHistory.value='';};
    const context=row(root,'ok-pdf-context');ui.context=context;context.hidden=true;
    ui.main=input('Main','color','#185c89',context);ui.outer=input('Outer','color','#ffffff',context);ui.stroke=input('Stroke','number',2,context);ui.stroke.min=1;ui.stroke.max=24;ui.outerWidth=input('Outer line','number',0,context);ui.outerWidth.min=0;ui.outerWidth.max=24;
    ui.selected=select('Selection',[['','Select annotation']],context);ui.selected.onchange=()=>{state.selected=state.objects.find(o=>o.id===ui.selected.value)||null;showObject();draw();};
    ui.selected.dataset.pdfSelection='';
    ui.remove=button('Delete selected',remove,context);
    ui.more=button('Load more objects',async()=>{const result=await json(`${base()}/objects?page=${state.page}&revision=${state.revision}&offset=${state.objects.length}&limit=100`,undefined,'GET');state.objects.push(...result.objects);for(const obj of result.objects){const option=node('option',`${obj.kind}: ${(obj.text||obj.id).slice(0,45)}`);option.value=obj.id;ui.selected.append(option);}ui.more.hidden=result.objects.length<100;draw();status(`${state.objects.length} selectable objects loaded.`);},context);ui.more.hidden=true;
    const nav=row(root,'ok-pdf-context');ui.nav=nav;nav.classList.add('ok-pdf-nav');nav.hidden=true;
    ui.previous=button('Previous page',()=>changePage(state.page-1),nav);ui.page=input('Page','number',1,nav);ui.page.min=1;ui.page.onchange=()=>run(()=>changePage(Number(ui.page.value)));ui.count=node('span');nav.append(ui.count);ui.next=button('Next page',()=>changePage(state.page+1),nav);
    const layoutNode=node('div',undefined,'ok-pdf-layout');root.append(layoutNode);
    ui.stage=node('div',undefined,'ok-pdf-stage');layoutNode.append(ui.stage);
    ui.empty=node('div','Open a PDF to edit, annotate or sign. The original remains unchanged.','ok-pdf-empty');ui.stage.append(ui.empty);
    ui.paper=node('div',undefined,'ok-pdf-paper');ui.paper.hidden=true;ui.image=node('img');ui.image.alt='PDF page preview';ui.svg=document.createElementNS(NS,'svg');ui.svg.setAttribute('tabindex','0');ui.svg.setAttribute('role','application');ui.svg.setAttribute('aria-label','PDF editing canvas. Use precise placement controls for keyboard drawing.');ui.paper.append(ui.image,ui.svg);ui.stage.append(ui.paper);
    ui.inspector=node('aside',undefined,'ok-pdf-inspector');ui.inspector.hidden=true;ui.inspector.setAttribute('aria-label','Selected tool settings');layoutNode.append(ui.inspector);
    const dock=row(root,'ok-pdf-dock');ui.status=node('p','Choose a PDF to begin.','ok-pdf-status');ui.status.setAttribute('role','status');ui.status.setAttribute('aria-live','polite');dock.append(ui.status);
    ui.cancel=button('Cancel operation',cancel,dock);ui.cancel.hidden=true;
    ui.export=button('Download PDF',exportPdf,dock,'ok-pdf-primary');ui.verify=button('Verify signatures',verify,dock);
    ui.sign=button('Sign PDF',()=>ui.performSign(),dock,'ok-pdf-primary');ui.sign.hidden=true;
    const file=node('input');file.type='file';file.accept='.pdf,application/pdf';file.hidden=true;root.append(file);file.onchange=()=>{const picked=file.files[0];file.value='';if(picked)run(()=>openFile(picked));};
    function update(){const has=!!state.document;ui.toolbar.hidden=ui.context.hidden=ui.nav.hidden=!has;ui.empty.hidden=has;ui.paper.hidden=!has;ui.clear.hidden=!has;ui.open.hidden=has;ui.open.textContent='Choose PDF…';ui.replace.hidden=!has;ui.replace.setAttribute('aria-disabled',String(state.busy));ui.annotations.hidden=state.mode!=='annotate';ui.edits.hidden=state.mode!=='edit';compactMode.value=state.mode;compactTool.value=state.tool;ui.undo.disabled=state.busy||state.cursor===0;ui.redo.disabled=state.busy||state.cursor===state.history.length-1;compactHistory.querySelector('[value="undo"]').disabled=ui.undo.disabled;compactHistory.querySelector('[value="redo"]').disabled=ui.redo.disabled;ui.export.disabled=ui.verify.disabled=!has||state.busy;ui.remove.disabled=state.busy||!state.selected;ui.open.disabled=ui.clear.disabled=state.busy;ui.page.disabled=state.busy;ui.previous.disabled=state.busy||state.page<=1;ui.next.disabled=state.busy||!has||state.page>=state.document.page_count;ui.page.value=state.page;ui.count.textContent=has?`of ${state.document.page_count} · revision ${state.revision}`:'';
      for(const [key,b]of Object.entries(ui.tools)){b.setAttribute('aria-pressed',String(state.tool===key));b.disabled=state.busy||(key==='certificate'&&state.document?.permissions?.can_sign===false)||(key!=='certificate'&&key!=='pan'&&key!=='select'&&state.document?.permissions?.can_edit===false);}
      const style=['text','add_text','freehand','circle','rectangle','line','highlight','arrow','callout','signature'].includes(state.tool);for(const el of [ui.main,ui.outer,ui.stroke,ui.outerWidth])el.parentElement.hidden=!style;
      ui.sign.hidden=!has||state.tool!=='certificate';ui.sign.disabled=state.busy||!state.provider||state.document?.permissions?.can_sign===false;
      root.setAttribute('aria-busy',String(state.busy));
    }
    async function choose(){if(options.chooseDocument){const selection=await options.chooseDocument();if(!selection)return;const body=new FormData();body.append('selection_id',typeof selection==='string'?selection:selection.selection_id);await load(body,selection.name||'Selected PDF');}else file.click();}
    async function openFile(picked){if(picked.size>64*1024*1024)throw Error('Choose a PDF smaller than 64 MiB.');const body=new FormData();body.append('file',picked);await load(body,picked.name);}
    async function load(body,name){status('Opening PDF…');const doc=await json('/api/pdf-documents',body);await release();state.document=doc;state.revision=doc.revision;state.history=[doc.revision];state.cursor=0;state.page=1;state.zoom=1;state.previewScale=0;state.epoch++;ui.name.textContent=name;await render();status(doc.permissions?.can_edit===false?'This signed document is read-only for editing. Permitted additional signing remains available.':'PDF ready. Choose a tool to begin.');}
    async function release(){state.epoch++;state.previewGeneration++;for(const url of state.urls)URL.revokeObjectURL(url);state.urls.clear();state.thumbnailUrls.clear();state.previewUrl=null;state.previewScale=0;const doc=state.document;state.document=null;state.provider=null;state.selected=null;state.artifact=null;state.placement=null;state.signedVerification=null;state.tool='select';ui.inspector.replaceChildren();ui.inspector.hidden=true;if(doc)try{await request(`/api/pdf-documents/${encodeURIComponent(doc.id)}`,undefined,'DELETE');}catch{}}
    async function clear(){await release();ui.name.textContent='Choose a PDF';ui.svg.replaceChildren();ui.inspector.replaceChildren();ui.inspector.hidden=true;ui.thumbnails.hidden=true;status('Choose a PDF to begin.');}
    function base(){return `/api/pdf-documents/${encodeURIComponent(state.document.id)}`;}
    function geometry(){return state.document.pages.find(p=>p.page===state.page)||state.document.pages[state.page-1];}
    async function render(){const epoch=state.epoch;const objects=await json(`${base()}/objects?page=${state.page}&revision=${state.revision}`,undefined,'GET');if(epoch!==state.epoch)return;state.previewScale=0;if(state.previewUrl){URL.revokeObjectURL(state.previewUrl);state.urls.delete(state.previewUrl);state.previewUrl=null;ui.image.removeAttribute('src');}state.objects=objects.objects||[];state.selected=null;ui.selected.replaceChildren();const placeholder=node('option','Select annotation or content');placeholder.value='';ui.selected.append(placeholder);for(const obj of state.objects){const opt=node('option',`${obj.kind}: ${(obj.text||obj.id).slice(0,45)}`);opt.value=obj.id;ui.selected.append(opt);}ui.more.hidden=state.objects.length<100;layout();draw();update();await refreshPreview(true);await thumbnails();}
    ui.thumbnails=node('nav',undefined,'ok-pdf-thumbnails ok-pdf-row');ui.thumbnails.setAttribute('aria-label','PDF page thumbnails');ui.nav.after(ui.thumbnails);ui.thumbnails.hidden=true;
    async function thumbnails(){for(const url of state.thumbnailUrls){URL.revokeObjectURL(url);state.urls.delete(url);}state.thumbnailUrls.clear();ui.thumbnails.replaceChildren();ui.thumbnails.hidden=!state.document;if(!state.document)return;const current=state.page,epoch=state.epoch;const start=Math.max(1,current-2),end=Math.min(state.document.page_count,current+2);await Promise.all(Array.from({length:end-start+1},async(_,i)=>{const page=start+i,b=button(`Page ${page}`,()=>changePage(page),ui.thumbnails);b.setAttribute('aria-current',page===current?'page':'false');try{const response=await request(`${base()}/previews/${page}?revision=${state.revision}&scale=.15`,undefined,'GET');const blob=await response.blob();if(epoch!==state.epoch)return;const url=URL.createObjectURL(blob);state.urls.add(url);state.thumbnailUrls.add(url);const image=node('img');image.alt='';image.src=url;b.prepend(image);}catch{}}));}
    function pageSize(){const g=geometry(),crop=g.crop_box||[0,0,g.width,g.height],w=crop[2]-crop[0],h=crop[3]-crop[1],rotated=(g.rotation||0)%180!==0;return rotated?{width:h,height:w}:{width:w,height:h};}
    function fitScale(){const size=pageSize(),style=global.getComputedStyle(ui.stage),paddingX=(parseFloat(style.paddingLeft)||0)+(parseFloat(style.paddingRight)||0),paddingY=(parseFloat(style.paddingTop)||0)+(parseFloat(style.paddingBottom)||0);const width=Math.max(1,ui.stage.clientWidth-paddingX),height=Math.max(1,ui.stage.clientHeight-paddingY);return Math.min(width/size.width,height/size.height);}
    function previewResolution(){return Math.min(4,Math.max(1,Math.ceil(fitScale()*state.zoom*(global.devicePixelRatio||1)*4)/4));}
    async function refreshPreview(force=false){if(!state.document)return;const scale=previewResolution();if(!force&&scale===state.previewScale)return;const generation=++state.previewGeneration,epoch=state.epoch;state.previewScale=scale;try{const response=await request(`${base()}/previews/${state.page}?revision=${state.revision}&scale=${scale.toFixed(2)}`,undefined,'GET'),blob=await response.blob();if(epoch!==state.epoch||generation!==state.previewGeneration)return;const url=URL.createObjectURL(blob);if(state.previewUrl){URL.revokeObjectURL(state.previewUrl);state.urls.delete(state.previewUrl);}state.previewUrl=url;state.urls.add(url);ui.image.src=url;}catch(error){if(epoch===state.epoch&&generation===state.previewGeneration){state.previewScale=0;if(!state.previewUrl)status(`Page preview failed: ${error.message}`,true);}}}
    function layout(){if(!state.document)return;const size=pageSize();ui.svg.setAttribute('viewBox',`0 0 ${size.width} ${size.height}`);const scale=fitScale();ui.paper.style.width=`${size.width*scale*state.zoom}px`;}
    function setZoom(value){state.zoom=limit(value,.25,4);layout();void refreshPreview();}
    const resizeObserver=typeof ResizeObserver==='undefined'?null:new ResizeObserver(()=>{layout();void refreshPreview();});resizeObserver?.observe(ui.stage);
    async function changePage(page){if(!Number.isInteger(page)||page<1||page>state.document.page_count)throw Error('Choose a page within this document.');state.page=page;state.zoom=1;await render();if(state.tool==='certificate')setTool('certificate');}
    async function history(direction){const cursor=state.cursor+direction;const restored=await json(`${base()}/revisions`,{base_revision:state.revision,restore_revision:state.history[cursor]});state.cursor=cursor;state.revision=restored.revision;state.artifact=null;state.signedVerification=null;await render();status('Revision restored. New edits and signing use this restored document.');}
    function encodeOperation(op){
      if(op.kind)return op;
      const source=op.annotation||op;
      const rect=[source.x,source.y,source.x+source.width,source.y+source.height];
      const common={kind:op.type==='annotation_add'?'annotation':op.type,page:source.page};
      if(rect.every(Number.isFinite))common.rect=rect;
      for(const key of ['object_id','text','font_size','color','outer_color','outer_width','stroke_width'])if(source[key]!==undefined)common[key]=source[key];
      if(source.image_data)common.image_base64=source.image_data.split(',')[1];
      if(op.annotation?.kind==='image')common.kind='add_image';
      if(op.font_fallback)common.font=op.font_fallback;
      if(op.type==='image_change')common.action=op.delete?'delete':source.image_data?'replace':'move';
      if(op.annotation&&source.kind!=='image'){common.annotation_type=source.kind;common.points=(source.points||[]).map(p=>[p.x,p.y]);if(['arrow','line'].includes(source.kind)&&common.points.length<2)common.points=[[rect[0],rect[1]],[rect[2],rect[3]]];}
      if(op.type==='annotation_delete'){common.kind='annotation';common.action='delete';}
      return common;
    }
    async function mutate(operations){const revision=await json(`${base()}/revisions`,{base_revision:state.revision,operations:operations.map(encodeOperation)});state.revision=revision.revision??revision.id;state.history.splice(state.cursor+1);state.history.push(state.revision);state.cursor=state.history.length-1;state.artifact=null;await render();status('Changes applied. The original PDF is unchanged.');}
    function setTool(tool){state.tool=tool;state.selected=null;ui.inspector.replaceChildren();ui.inspector.hidden=['select','pan','eraser'].includes(tool);if(tool==='certificate')signPanel();else if(tool==='ocr')ocrPanel();else if(tool==='edit_text'||tool==='edit_image'){ui.inspector.append(node('p','Select an object on the page or in the selection list. Unsupported objects show a reason.'));}else if(!ui.inspector.hidden)placementPanel(tool);draw();update();}
    function precise(parent,values={}){const group=row(parent);const g=geometry(),crop=g.crop_box||[0,0,g.width,g.height];const fields={};for(const [key,value]of [['x',crop[0]+Math.min(36,g.width/4)],['y',crop[1]+Math.min(36,g.height/4)],['width',Math.min(160,g.width/2)],['height',Math.min(40,g.height/4)]]){fields[key]=input(key[0].toUpperCase()+key.slice(1),'number',values[key]??value,group);fields[key].min=0;fields[key].max=key==='x'||key==='width'?crop[2]:crop[3];fields[key].step='.5';}const get=()=>Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Number(v.value)]));get.set=value=>{for(const key of Object.keys(fields))fields[key].value=value[key];};get.onchange=callback=>{for(const field of Object.values(fields))field.oninput=callback;};return get;}
    function placementPanel(tool){ui.inspector.append(node('h2',tool==='signature'?'Signature appearance':'Precise placement'),node('p','Draw on the page, or enter a region in PDF points.','ok-pdf-muted'));const get=precise(ui.inspector);ui.text=input('Text','text',tool==='signature'?'':'Note',ui.inspector);ui.text.maxLength=10000;ui.font=input('Text size','number',14,ui.inspector);ui.font.min=6;ui.font.max=120;
      if(tool==='signature'){ui.signatureKind=select('Appearance source',[['draw','Draw signature on page'],['image','Use signature image']],ui.inspector);}
      if(['add_image','signature'].includes(tool)){ui.imageFile=input('Image file','file',undefined,ui.inspector);ui.imageFile.accept='image/png,image/jpeg';if(tool==='signature'){ui.imageFile.parentElement.hidden=true;ui.signatureKind.onchange=()=>{ui.imageFile.parentElement.hidden=ui.signatureKind.value!=='image';};}}
      button('Place on page',()=>place(get()),ui.inspector);if(tool==='signature')ui.inspector.append(node('p','This is a visual signature only. Use Sign with certificate for a cryptographic signature.','ok-pdf-muted'));
    }
    async function imageData(file){if(!file)throw Error('Choose an image file first.');if(file.size>8*1024*1024)throw Error('Choose an image smaller than 8 MiB.');return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('The image could not be read.'));reader.readAsDataURL(file);});}
    async function place(rect,points){const tool=state.tool;let operation;if(tool==='certificate'){state.placement={page:state.page,...rect};ui.signaturePlacement?.set(rect);draw();status('Certificate signature position selected.');return;}const drawnSignature=tool==='signature'&&ui.signatureKind?.value==='draw';if(drawnSignature&&(!points||points.length<2))throw Error('Draw the signature on the page, or choose a signature image.');const common={page:state.page,...rect};if(tool==='add_text')operation={type:'add_text',...common,text:ui.text.value,font_size:Number(ui.font.value),color:ui.main.value};else if(tool==='add_image')operation={type:'add_image',...common,image_data:await imageData(ui.imageFile?.files[0])};else operation={type:'annotation_add',annotation:{...common,kind:drawnSignature?'freehand':tool==='signature'?'image':tool,text:ui.text?.value||'',font_size:Number(ui.font?.value||14),color:ui.main.value,outer_color:ui.outer.value,stroke_width:Number(ui.stroke.value),outer_width:Number(ui.outerWidth.value),...(points?{points}:{}),...(tool==='signature'&&!drawnSignature?{image_data:await imageData(ui.imageFile?.files[0])}:{})}};await mutate([operation]);setTool('select');}
    function draw(){ui.svg.replaceChildren();if(!state.document)return;for(const obj of state.objects){const a=displayPoint(obj.x,obj.y+obj.height,geometry()),b=displayPoint(obj.x+obj.width,obj.y,geometry());const rect=document.createElementNS(NS,'rect');for(const [key,value]of Object.entries({x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(b.x-a.x),height:Math.abs(b.y-a.y),fill:'transparent',stroke:state.selected?.id===obj.id?'var(--ok-accent)':'transparent','stroke-width':2,'vector-effect':'non-scaling-stroke'}))rect.setAttribute(key,value);rect.dataset.objectId=obj.id;ui.svg.append(rect);}if(state.tool==='certificate'&&state.placement?.page===state.page){const p=state.placement,descriptor=previewDescriptor('certificate',[{x:p.x,y:p.y},{x:p.x+p.width,y:p.y+p.height}],geometry());const rect=document.createElementNS(NS,descriptor.tag);for(const [key,value]of Object.entries({...descriptor.attrs,stroke:'var(--ok-accent)','stroke-dasharray':'6 3','stroke-width':2,'pointer-events':'none'}))rect.setAttribute(key,value);rect.dataset.signaturePlacement='';ui.svg.append(rect);}}
    function showObject(){
      ui.inspector.replaceChildren();ui.inspector.hidden=!state.selected;if(!state.selected)return;
      const obj=state.selected;ui.inspector.append(node('h2',`Selected ${obj.kind}`));
      if(state.document.permissions?.can_edit===false){ui.inspector.append(node('p','This signed document is read-only for editing.'));return;}
      if(!obj.editable){ui.inspector.append(node('p',obj.reason||'This object cannot be edited safely.'));return;}
      const get=precise(ui.inspector,obj);
      if(obj.kind==='text'){
        const text=node('textarea');text.value=obj.text||'';text.maxLength=10000;text.setAttribute('aria-label','Text content');ui.inspector.append(text);
        const fallback=select('Replacement font',[['','Choose replacement font…'],['Helvetica','Helvetica'],['Times-Roman','Times Roman'],['Courier','Courier']],ui.inspector);
        const fontSize=input('Text size','number',obj.font_size||12,ui.inspector);
        ui.inspector.append(node('p','Embedded font editing requires an explicit replacement font. Built-in fonts support Latin text. Review the rendered layout after applying.','ok-pdf-muted'));
        button('Apply text edit',()=>{if(!fallback.value)throw Error('Choose a replacement font before editing existing text.');return mutate([{type:'replace_text',object_id:obj.id,page:state.page,...get(),text:text.value,font_size:Number(fontSize.value),font_fallback:fallback.value}]);},ui.inspector);
      }else if(obj.kind==='image'){
        const image=input('Replacement image','file',undefined,ui.inspector);image.accept='image/png,image/jpeg';
        button('Apply image edit',async()=>mutate([{type:'image_change',object_id:obj.id,page:state.page,...get(),...(image.files[0]?{image_data:await imageData(image.files[0])}:{})}]),ui.inspector);
        const rotation=select('Rotate image',[['90','90° clockwise'],['180','180°'],['270','270° clockwise']],ui.inspector);
        button('Apply rotation',()=>{const r=get();return mutate([{kind:'image_change',object_id:obj.id,page:state.page,action:'rotate',rotation_delta:Number(rotation.value),rect:[r.x,r.y,r.x+r.width,r.y+r.height]}]);},ui.inspector);
        const crop=node('details');crop.append(node('summary','Crop image · intrinsic pixels'));ui.inspector.append(crop);
        const fields={};for(const key of ['left','top','right','bottom'])fields[key]=input(key,'number',0,crop);
        button('Apply image crop',()=>{const r=get();return mutate([{kind:'image_change',object_id:obj.id,page:state.page,action:'crop',image_crop:['left','top','right','bottom'].map(k=>Number(fields[k].value)),rect:[r.x,r.y,r.x+r.width,r.y+r.height]}]);},crop);
      }else if(obj.kind==='annotation'){
        const text=input('Annotation text','text',obj.text||'',ui.inspector);text.maxLength=10000;
        const color=input('Main color','color',obj.color||ui.main.value,ui.inspector),outer=input('Outer color','color',obj.outer_color||ui.outer.value,ui.inspector);
        const stroke=input('Stroke width','number',obj.stroke_width||2,ui.inspector),outerWidth=input('Outer width','number',obj.outer_width||0,ui.inspector);
        button('Apply annotation edit',()=>{const r=get();return mutate([annotationChange(obj,[r.x,r.y,r.x+r.width,r.y+r.height],{text:text.value,color:color.value,outer_color:outer.value,stroke_width:Number(stroke.value),outer_width:Number(outerWidth.value)})]);},ui.inspector);
      }
    }
    async function remove(){if(!state.selected)return;if(!['image','annotation'].includes(state.selected.kind))throw Error('Use Edit text to change original text. Eraser removes annotations only.');await mutate([{type:state.selected.kind==='image'?'image_change':'annotation_delete',page:state.page,object_id:state.selected.id,...(state.selected.kind==='image'?{delete:true}:{})}]);setTool('select');}
    let drag=null;
    ui.svg.addEventListener('pointerdown',event=>{if(state.busy||!state.document||event.button!==0)return;const object=event.target.dataset.objectId;if(object&&['select','edit_text','edit_image','eraser'].includes(state.tool)){state.selected=state.objects.find(o=>o.id===object);ui.selected.value=object;if(state.tool==='eraser'){if(state.selected.kind==='annotation')run(remove);else status('Eraser removes annotations only. Original content is unchanged.');}else{showObject();draw();update();}return;}if(['select','edit_text','edit_image','ocr','eraser'].includes(state.tool))return;const p=pointInPage(event.clientX,event.clientY,ui.svg.getBoundingClientRect(),geometry());drag={p,points:[p],clientX:event.clientX,clientY:event.clientY,left:ui.stage.scrollLeft,top:ui.stage.scrollTop};ui.svg.setPointerCapture(event.pointerId);});
    ui.svg.addEventListener('pointermove',event=>{if(!drag)return;if(state.tool==='pan'){ui.stage.scrollLeft=drag.left-(event.clientX-drag.clientX);ui.stage.scrollTop=drag.top-(event.clientY-drag.clientY);}else if((state.tool==='freehand'||state.tool==='signature'&&ui.signatureKind?.value==='draw')&&drag.points.length<1000)drag.points.push(pointInPage(event.clientX,event.clientY,ui.svg.getBoundingClientRect(),geometry()));});
    ui.svg.addEventListener('pointerup',event=>{if(!drag)return;const start=drag;drag=null;if(state.tool==='pan')return;const end=pointInPage(event.clientX,event.clientY,ui.svg.getBoundingClientRect(),geometry());const freehand=state.tool==='freehand'||state.tool==='signature'&&ui.signatureKind?.value==='draw';const points=freehand?[...start.points,end]:[start.p,end];const crop=geometry().crop_box||[0,0,geometry().width,geometry().height];const x=Math.min(...points.map(p=>p.x)),y=Math.min(...points.map(p=>p.y));const rect={x,y,width:Math.min(crop[2]-x,Math.max(1,Math.max(...points.map(p=>p.x))-x)),height:Math.min(crop[3]-y,Math.max(1,Math.max(...points.map(p=>p.y))-y))};if(rect.width<=0||rect.height<=0)return;run(()=>place(rect,points));});
    ui.svg.addEventListener('pointercancel',()=>{drag=null;});
    ui.svg.addEventListener('pointermove',event=>{if(!drag||state.tool==='pan')return;draw();const end=pointInPage(event.clientX,event.clientY,ui.svg.getBoundingClientRect(),geometry());const isInk=state.tool==='freehand'||state.tool==='signature'&&ui.signatureKind?.value==='draw';const descriptor=previewDescriptor(state.tool,isInk?[...drag.points,end]:[drag.p,end],geometry());for(const [color,width]of [[ui.outer.value,Number(ui.stroke.value)+2*Number(ui.outerWidth.value)],[ui.main.value,Number(ui.stroke.value)]]){const shape=document.createElementNS(NS,descriptor.tag);for(const [key,value]of Object.entries({...descriptor.attrs,stroke:color,color,'stroke-width':width,'pointer-events':'none'}))shape.setAttribute(key,value);shape.dataset.dragPreview=state.tool;ui.svg.append(shape);}});
    root.addEventListener('keydown',event=>{if(/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)||event.isComposing)return;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='z'){event.preventDefault();if(!state.busy&&((event.shiftKey&&state.cursor<state.history.length-1)||(!event.shiftKey&&state.cursor>0)))run(()=>history(event.shiftKey?1:-1));}else if(event.key==='Delete'||event.key==='Backspace'){if(state.selected){event.preventDefault();run(remove);}}else if(event.key==='Escape')setTool('select');else if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)&&state.selected&&['image','annotation'].includes(state.selected.kind)){event.preventDefault();const obj=state.selected,step=event.shiftKey?10:1,dx=event.key==='ArrowLeft'?-step:event.key==='ArrowRight'?step:0,dy=event.key==='ArrowDown'?-step:event.key==='ArrowUp'?step:0;const rect=[obj.x+dx,obj.y+dy,obj.x+obj.width+dx,obj.y+obj.height+dy];run(()=>mutate([obj.kind==='annotation'?annotationChange(obj,rect):{kind:'image_change',page:state.page,object_id:obj.id,action:'move',rect}]));}});
    async function poll(job){state.job=job.id;ui.cancel.hidden=false;const activity=window.OfficeKitActivity?.start({id:`pdf-${job.id}`,title:'PDF operation',tool:'PDF editor',tab:'pdf-editor',phase:job.phase||'Queued',unit:'pages',cancel,returnTo:()=>switchTab('pdf-editor')});try{while(!['ready','completed','failed','cancelled'].includes(job.state)){status(job.phase||'Processing PDF…');activity?.update({state:job.state==='queued'?'queued':'running',phase:job.phase||'Processing PDF',percent:null});await new Promise(resolve=>setTimeout(resolve,500));if(state.destroyed)throw Error('Workspace closed.');job=await json(`/api/pdf-workspace-jobs/${encodeURIComponent(job.id)}`,undefined,'GET');}if(job.state==='failed')throw Error(typeof job.error==='string'?job.error:'The operation failed. Review the document and try again.');if(job.state==='cancelled'){activity?.finish({state:'cancelled',phase:'Cancelled',summary:'The PDF operation was cancelled.'});throw Error('Operation cancelled.');}activity?.finish({state:'complete',phase:'Complete',summary:'The PDF result is ready in the editor.'});return job;}catch(error){if(job.state!=='cancelled')activity?.finish({state:'failed',phase:'Could not complete',summary:error?.message||'PDF operation failed.'});throw error;}finally{state.job=null;ui.cancel.hidden=true;}}
    async function cancel(){if(!state.job)return;await json(`/api/pdf-workspace-jobs/${encodeURIComponent(state.job)}/cancellations`,{});status('Cancellation requested.');}
    ui.cancel.onclick=()=>cancel().catch(error=>status(error.message,true));
    async function download(ref){const response=await request(`/api/pdf-workspace-artifacts/${encodeURIComponent(ref)}`,undefined,'GET');const blob=await response.blob();if(options.saveArtifact){const saved=await options.saveArtifact(blob,'edited.pdf');status(!saved?'Save cancelled.':'PDF saved.');return;}const url=URL.createObjectURL(blob);state.urls.add(url);const link=node('a');link.href=url;link.download='edited.pdf';root.append(link);link.click();link.remove();status('Download started.');}
    async function exportPdf(){if(state.artifact){await download(state.artifact);return;}status('Preparing PDF…');const job=await poll(await json(`${base()}/exports`,{revision:state.revision}));if(!job.result_ref)throw Error('No completed PDF was returned.');state.artifact=job.result_ref;state.signedVerification=null;await download(job.result_ref);}
    function signPanel(){ui.inspector.append(node('h2','Sign with certificate'));const kind=select('Certificate source',[['pkcs12','Certificate file (.p12 / .pfx)'],['pkcs11','USB DSC token']],ui.inspector);const certificateFile=input('Certificate file','file',undefined,ui.inspector);certificateFile.accept='.p12,.pfx';let certificateSelection=null;const certificateButton=button('Choose certificate…',async()=>{certificateSelection=await options.chooseCertificate();if(certificateSelection)certificateButton.textContent=certificateSelection.name||'Certificate selected';},ui.inspector);certificateButton.hidden=!options.chooseCertificate;certificateFile.parentElement.hidden=!!options.chooseCertificate;const secret=input('Certificate password / token PIN','password','',ui.inspector);secret.autocomplete='off';secret.maxLength=1024;const certs=select('Certificate',[['','Choose a provider first']],ui.inspector);const detail=node('p',undefined,'ok-pdf-muted');ui.inspector.append(detail);
      kind.onchange=()=>{certificateFile.parentElement.hidden=kind.value==='pkcs11'||!!options.chooseCertificate;certificateButton.hidden=kind.value==='pkcs11'||!options.chooseCertificate;state.provider=null;secret.value='';detail.textContent=kind.value==='pkcs11'?'Select installed compatible token middleware through the native picker. Your private key stays on the token.':'';};
      button('Read certificates',async()=>{state.provider=null;let provider;if(kind.value==='pkcs11'){secret.value='';if(!options.chooseProvider)throw Error('USB token signing requires the desktop app and compatible installed middleware.');provider=await options.chooseProvider();if(!provider)return;}else{if(!certificateSelection&&!certificateFile.files[0])throw Error('Choose a .p12 or .pfx certificate.');const body=new FormData();body.append('kind','pkcs12');if(certificateSelection)body.append('selection_id',certificateSelection.selection_id);else{if(certificateFile.files[0].size>2*1024*1024)throw Error('Choose a certificate smaller than 2 MiB.');body.append('file',certificateFile.files[0]);}body.append('password',secret.value);secret.value='';provider=await json('/api/pdf-signing-providers',body);}state.provider=provider;certs.replaceChildren();for(const cert of provider.certificates||[]){const option=node('option',cert.subject||cert.id);option.value=cert.id;certs.append(option);}detail.textContent=(provider.certificates||[]).map(c=>`${c.subject||''} · Issuer: ${c.issuer||'Unavailable'} · Valid: ${c.valid_from||'Unavailable'} — ${c.valid_until||'Unavailable'}`).join('\n');status('Review the certificate, then enter the password or PIN again to sign.');},ui.inspector);
      const get=precise(ui.inspector,state.placement?.page===state.page?state.placement:{});ui.signaturePlacement=get;const visible=input('Visible signature placement','checkbox',undefined,ui.inspector);visible.checked=true;const sync=()=>{state.placement=visible.checked?{page:state.page,...get()}:null;draw();};get.onchange(sync);visible.onchange=sync;sync();const reason=input('Reason (optional)','text','',ui.inspector);reason.maxLength=200;
      ui.inspector.append(node('p','Signing checks integrity locally. Trust, revocation and timestamp results are reported separately. No online checks are requested.','ok-pdf-muted'));
      ui.performSign=async()=>{if(!state.provider||!certs.value)throw Error('Read and choose a certificate first.');const body={revision:state.revision,provider_id:state.provider.id,certificate_id:certs.value,secret:secret.value,placement:visible.checked?{page:state.page,...get()}:null,reason:reason.value};secret.value='';status('Signing PDF. A token PIN is attempted once for this action.');let initial;try{initial=await json(`${base()}/signatures`,body);}finally{body.secret='';}const job=await poll(initial);if(!job.result_ref)throw Error('Signing returned no verified PDF.');state.artifact=job.result_ref;state.signedVerification=job.result;verificationPanel(job.result);status('Signed PDF is ready. Download preserves this verified signature.');};
    }
    function verificationPanel(summary){if(!summary)return;const section=node('section');section.append(node('h2','Signature verification'));const checks=Array.isArray(summary)?summary:[summary];if(!checks.length)section.append(node('p','No digital signatures found.'));for(const [index,check]of checks.entries()){section.append(node('h3',`Signature ${index+1}`));for(const key of ['integrity','trust','revocation','timestamp','modification_permissions'])section.append(node('p',`${key.replaceAll('_',' ')}: ${typeof check[key]==='string'?check[key]:JSON.stringify(check[key]??'Not checked')}`));}ui.inspector.append(section);ui.inspector.hidden=false;}
    async function verify(){if(state.artifact&&state.signedVerification){ui.inspector.replaceChildren();verificationPanel(state.signedVerification);status('Verification of the completed signed PDF. Offline checks do not establish current revocation status.');return;}status('Checking signatures locally…');const job=await poll(await json(`${base()}/verifications`,{revision:state.revision,network_consent:false}));ui.inspector.replaceChildren();verificationPanel(job.result);status('Signature check completed. Offline checks do not establish current revocation status.');}
    function ocrPanel(){
      ui.inspector.append(node('h2','Recognise scanned text'));
      const language=input('Installed OCR language','text','eng',ui.inspector);language.maxLength=40;
      const mode=select('Output',[['reconstruction','Editable reconstruction'],['searchable','Searchable text layer']],ui.inspector);
      ui.inspector.append(node('p','Reconstruction turns the rest of the affected page into an image and replaces reviewed regions with editable text. Fonts and layout may differ. Only unrotated pages with an unshifted crop box support reconstruction. Original scans remain in the source PDF.','ok-pdf-muted'));
      button('Recognise this page',async()=>{
        const selectedMode=mode.value;
        const initial=await json(`${base()}/ocr-reviews`,{base_revision:state.revision,pages:[state.page],language:language.value,mode:selectedMode});
        const job=await poll(initial),review=job.result||job,container=node('div'),regions=review.regions||[];
        for(const region of regions){
          const group=node('div',undefined,'ok-pdf-ocr-region'),text=node('textarea');text.value=region.text||'';text.maxLength=10000;
          await ui.image.decode();const g=geometry(),a=displayPoint(region.rect[0],region.rect[3],g),b=displayPoint(region.rect[2],region.rect[1],g),crop=g.crop_box||[0,0,g.width,g.height];
          const canvas=document.createElement('canvas'),width=Math.abs(b.x-a.x),height=Math.abs(b.y-a.y),ratio=Math.min(1,800/Math.max(width,height));canvas.width=Math.max(1,Math.ceil(width*ratio));canvas.height=Math.max(1,Math.ceil(height*ratio));
          canvas.getContext('2d').drawImage(ui.image,Math.min(a.x,b.x)*ui.image.naturalWidth/(crop[2]-crop[0]),Math.min(a.y,b.y)*ui.image.naturalHeight/(crop[3]-crop[1]),width*ui.image.naturalWidth/(crop[2]-crop[0]),height*ui.image.naturalHeight/(crop[3]-crop[1]),0,0,canvas.width,canvas.height);
          const original=node('img');original.src=canvas.toDataURL('image/png');original.alt=`Original scan region on page ${region.page}, ${region.rect.join(', ')} PDF points`;original.style.maxWidth='100%';group.append(node('p','Original scan region'),original);
          text.setAttribute('aria-label',`Recognised region ${region.id||region.region_id}`);
          group.append(node('p',`Region ${region.id||region.region_id}${Number.isFinite(region.confidence)?` · Confidence ${region.confidence}`:''}`),text);container.append(group);region.correctedText=text;
        }
        ui.inspector.append(container);if(!regions.length){status('No text regions were recognised.');return;}
        const consent=input(selectedMode==='reconstruction'?'I reviewed the text and accept page rasterisation and font/layout changes':'I reviewed the recognised text','checkbox',undefined,container);
        button('Apply reviewed text',()=>{if(!consent.checked)throw Error('Review the recognised text and acknowledge the output changes first.');return mutate(regions.map(r=>({kind:'apply_ocr',page:r.page,rect:r.rect,review_id:review.review_id||initial.id,region_id:r.id||r.region_id,text:r.correctedText.value,ocr_mode:selectedMode})));},container);
        status('Review every recognised region before applying.');
      },ui.inspector);
    }
    const api={openFile: picked=>run(()=>openFile(picked)),clear:()=>run(clear),state,async destroy(){state.destroyed=true;resizeObserver?.disconnect();await release();root.replaceChildren();delete root.pdfEditor;}};root.pdfEditor=api;update();return api;
  }
  global.OfficeKitPdfEditor={mount,pointInPage,displayPoint,annotationChange,previewDescriptor};
})(typeof window==='undefined'?globalThis:window);
