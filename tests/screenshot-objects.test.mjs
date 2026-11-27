import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function helpers() {
  const context = { console, TextEncoder };
  vm.runInNewContext(fs.readFileSync('assets/officekit-screenshot.js', 'utf8'), context);
  return context;
}

test('selection locates topmost visible annotation after sequential crops', () => {
  const h = helpers();
  const ops = [
    { type: 'text', x: 30, y: 30, width: 60, height: 30 },
    { type: 'crop', x: 20, y: 20, width: 100, height: 80 },
    { type: 'highlight', x: 15, y: 15, width: 20, height: 20 },
    { type: 'crop', x: 5, y: 5, width: 80, height: 60 },
  ];
  assert.equal(h.officekitHitScreenshotObject(ops, 12, 12, 200, 200), 2);
  assert.equal(h.officekitHitScreenshotObject(ops, 7, 7, 200, 200), 0);
  assert.equal(h.officekitHitScreenshotObject(ops, 79, 59, 200, 200), -1);
  assert.deepEqual(JSON.parse(JSON.stringify(h.officekitScreenshotObjectBounds(ops, 0, 200, 200))), { x: 5, y: 5, width: 60, height: 30 });
});

test('movement clamps in the annotation frame and translates every path point without mutating history', () => {
  const h = helpers();
  const ops = [{ type: 'crop', x: 20, y: 20, width: 80, height: 60 },
    { type: 'arrow', x: 10, y: 10, width: 20, height: 10, points: [[10, 10], [29, 19]] }];
  const moved = h.officekitMoveScreenshotObject(ops, 1, 100, -100, 200, 200);
  assert.deepEqual(JSON.parse(JSON.stringify(moved)), { type: 'arrow', x: 60, y: 0, width: 20, height: 10, points: [[60, 0], [79, 9]] });
  assert.equal(ops[1].x, 10);
  assert.equal(ops[1].points[0][0], 10);
});

test('rotated image operations keep existing annotation bounds and movement aligned', () => {
  const h=helpers();
  const ops=[{type:'rectangle',x:10,y:20,width:30,height:15},{type:'rotate'}];
  assert.deepEqual(JSON.parse(JSON.stringify(h.officekitScreenshotObjectBounds(ops,0,100,80))),{x:45,y:10,width:15,height:30});
  const moved=h.officekitMoveScreenshotObject(ops,0,4,3,100,80);
  assert.deepEqual({x:moved.x,y:moved.y},{x:13,y:16});
  assert.deepEqual(JSON.parse(JSON.stringify(h.officekitScreenshotObjectBounds([moved,...ops.slice(1)],0,100,80))),{x:49,y:13,width:15,height:30});
});

test('path geometry contains endpoints, padding and current bounds', () => {
  const h = helpers();
  const op = h.officekitScreenshotPathOperation('arrow', [[99, 79], [0, 0]], 100, 80, {color:'#FF0000',outer_color:'#FFFFFF',stroke_width:3,outer_width:2});
  assert.equal(op.x, 0); assert.equal(op.y, 0); assert.equal(op.width, 100); assert.equal(op.height, 80);
  assert.equal(op.points.length, 2);
  assert.throws(() => h.officekitScreenshotPathOperation('freehand', Array.from({length:513},()=>[1,1]),100,80,{}), /512/);
  assert.throws(() => h.officekitScreenshotPathOperation('arrow', [[1,1],[1,1]],100,80,{}), /two distinct/);
});

function editor() {
  const listeners = new Map(), nodes = new Map();
  function node(id) {
    if (nodes.has(id)) return nodes.get(id);
    const handlers = new Map();
    const classes = new Set();
    const n = { id, handlers, dataset: {}, value: '', disabled: false, style: {}, tagName: 'BUTTON',
      classList: { add:c=>classes.add(c), remove:c=>classes.delete(c), toggle:(c,on)=>on?classes.add(c):classes.delete(c) },
      addEventListener:(type,fn)=> { const old=handlers.get(type)||[]; old.push(fn); handlers.set(type,old); },
      getBoundingClientRect:()=>({left:0,top:0,width:100,height:100}), querySelectorAll:()=>[],
      setAttribute:()=>{}, removeAttribute:()=>{}, setPointerCapture:()=>{}, hasPointerCapture:()=>false,
      focus:()=>{context.document.activeElement=n;}, blur:()=>{},
      fire:async(type,event={})=>{for(const fn of handlers.get(type)||[]) await fn(event);},
    };
    nodes.set(id,n); return n;
  }
  const state = {bitmap:{width:100,height:100},width:100,height:100,tool:'select',undo:[],redo:[],
    operations:[{type:'highlight',x:10,y:10,width:20,height:20,color:'#112233',outer_color:'#FFFFFF',stroke_width:3,outer_width:2}]};
  const context = { TextEncoder, URL:{revokeObjectURL:()=>{}}, officekitScreenshot:state,
    document:{
      getElementById:node, querySelectorAll:()=>[], activeElement:null,
      addEventListener:(type,fn)=>listeners.set(type,fn),
      createElement:tagName=>{
        const el = node('created-' + Math.random());
        el.tagName = tagName.toUpperCase();
        el.remove = ()=>{};
        el.select = ()=>{};
        return el;
      }
    },
    officekitScreenshotVisible:()=>true, officekitScreenshotCoordinates:e=>({x:e.clientX,y:e.clientY,clientX:e.clientX,clientY:e.clientY}),
    officekitUpdateScreenshotSelection:()=>{}, officekitValidateScreenshotOperations:()=>{},
    officekitRenderScreenshotPreview:async()=>{},officekitScreenshotStatus:()=>{},officekitApplyScreenshotRegion:async()=>{},
    officekitScreenshotSetTool:tool=>{state.tool=tool;},
  };
  node('screenshot-canvas-stage').append = ()=>{};
  vm.runInNewContext(fs.readFileSync('assets/officekit-screenshot.js','utf8'),context);
  context.officekitBindScreenshotObjects();
  return {context,state,node,key:async e=>listeners.get('keydown')({preventDefault(){this.defaultPrevented=true;},...e}),
    pointer:async(type,x,y)=>node('screenshot-canvas').fire(type,{clientX:x,clientY:y,button:0,pointerId:1,preventDefault(){}})};
}

test('select, drag, nudge and delete preserve undo history; input keys never mutate annotations', async () => {
  const e = editor();
  e.context.officekitBindScreenshotObjects();
  assert.equal(e.node('screenshot-canvas').handlers.get('pointerdown').length,1);
  await e.pointer('pointerdown',15,15); await e.pointer('pointerup',15,15);
  assert.equal(e.node('screenshot-delete-button').disabled,false);
  await e.key({key:'ArrowRight',shiftKey:true});
  assert.equal(e.state.operations[0].x,20); assert.equal(e.state.undo.length,1);
  e.context.document.activeElement={tagName:'INPUT'};
  await e.key({key:'Delete'}); assert.equal(e.state.operations.length,1);
  await e.key({key:'ArrowLeft'}); assert.equal(e.state.operations[0].x,20);
  e.context.document.activeElement=null;
  await e.pointer('pointerdown',25,15); await e.pointer('pointermove',45,35); await e.pointer('pointerup',45,35);
  assert.equal(e.state.operations[0].x,40); assert.equal(e.state.operations[0].y,30);
  assert.equal(e.state.undo[1][0].x,20);
  await e.node('screenshot-delete-button').fire('click');
  // Click handler intentionally dispatches asynchronously; keyboard delete awaits commit.
  await Promise.resolve(); await Promise.resolve();
  assert.equal(e.state.operations.length,0); assert.equal(e.state.undo.length,3);
  assert.equal(e.state.undo[2][0].x,40);
});

test('eraser removes annotations without removing privacy edits', async () => {
  const h=helpers();
  const operations=[
    {type:'blur',x:10,y:10,width:20,height:20},
    {type:'mask',x:10,y:10,width:20,height:20},
    {type:'pixelate',x:10,y:10,width:20,height:20},
    {type:'highlight',x:10,y:10,width:20,height:20,color:'#112233',outer_color:'#FFFFFF',stroke_width:3,outer_width:2},
  ];
  const removed=h.officekitScreenshotEraserRemovals(operations,[{x:15,y:15},{x:25,y:25}],100,100);
  assert.deepEqual([...removed],[3]);
  assert.deepEqual(operations.filter((_,index)=>!removed.has(index)).map(op=>op.type),['blur','mask','pixelate']);
});

test('cancelled drawing never changes operations; arrow commit preserves both colors and full endpoint direction', async () => {
  const e=editor(); e.state.tool='arrow';
  e.node('screenshot-mask-color').value='#FF0000';e.node('screenshot-outer-color').value='#FFFFFF';
  await e.pointer('pointerdown',60,60); await e.node('screenshot-canvas').fire('pointercancel');
  assert.equal(e.state.operations.length,1); assert.equal(e.state.undo.length,0);
  await e.pointer('pointerdown',60,60); await e.pointer('pointerup',20,10);
  assert.equal(e.state.operations.length,2);
  const op=e.state.operations[1]; assert.equal(op.type,'arrow'); assert.equal(op.color,'#FF0000');assert.equal(op.outer_color,'#FFFFFF');
  assert.deepEqual(JSON.parse(JSON.stringify(op.points)),[[60,60],[20,10]]);
});

test('annotation dropdown provides keyboard selection and editor tool shortcuts respect form focus', async () => {
  const e = editor();
  await e.node('screenshot-object-list').fire('change',{target:{value:'0'}});
  assert.equal(e.node('screenshot-delete-button').disabled,false);
  await e.key({key:'ArrowDown'}); assert.equal(e.state.operations[0].y,11);
  await e.key({key:'p'}); assert.equal(e.state.tool,'freehand');
  e.context.document.activeElement={tagName:'INPUT'};
  await e.key({key:'r'}); assert.equal(e.state.tool,'freehand');
  e.context.document.activeElement=null;
  await e.key({key:'c'}); assert.equal(e.state.tool,'crop');
  await e.key({key:'a',altKey:true}); assert.equal(e.state.tool,'crop');
});

test('hitObject prioritizes inner stroke and path annotations over outer hollow rectangles', () => {
  const h = helpers();
  const ops = [
    { type: 'rectangle', x: 10, y: 10, width: 200, height: 200 },
    { type: 'freehand', x: 40, y: 40, width: 50, height: 50, points: [[50, 50], [80, 80]], stroke_width: 3, outer_width: 2 },
  ];
  // Clicking directly on the freehand scribble inside the rectangle selects the freehand scribble
  assert.equal(h.officekitHitScreenshotObject(ops, 50, 50, 300, 300), 1);
  // Clicking on the rectangle's top border selects the rectangle
  assert.equal(h.officekitHitScreenshotObject(ops, 100, 10, 300, 300), 0);
  // Clicking empty space inside the hollow rectangle falls back to the hollow rectangle
  assert.equal(h.officekitHitScreenshotObject(ops, 150, 150, 300, 300), 0);
  // Clicking outside both returns -1
  assert.equal(h.officekitHitScreenshotObject(ops, 250, 250, 300, 300), -1);
});

test('resizeObject scales bounding box and path coordinates correctly', () => {
  const h = helpers();
  const ops = [
    { type: 'rectangle', x: 20, y: 20, width: 40, height: 40 },
    { type: 'arrow', x: 10, y: 10, width: 30, height: 20, points: [[10, 10], [39, 29]] },
  ];
  // Drag bottom-right corner of rectangle
  const resizedRect = h.officekitResizeScreenshotObject(ops, 0, 'br', 10, 15, 200, 200);
  assert.equal(resizedRect.x, 20);
  assert.equal(resizedRect.y, 20);
  assert.equal(resizedRect.width, 50);
  assert.equal(resizedRect.height, 55);

  // Drag top-left corner of rectangle
  const resizedTl = h.officekitResizeScreenshotObject(ops, 0, 'tl', 5, 5, 200, 200);
  assert.equal(resizedTl.x, 25);
  assert.equal(resizedTl.y, 25);
  assert.equal(resizedTl.width, 35);
  assert.equal(resizedTl.height, 35);

  // Drag bottom-right of arrow scales its points
  const resizedArrow = h.officekitResizeScreenshotObject(ops, 1, 'br', 30, 20, 200, 200);
  assert.equal(resizedArrow.width, 60);
  assert.equal(resizedArrow.height, 40);
  assert.equal(resizedArrow.points[0][0], 10);
  assert.equal(resizedArrow.points[0][1], 10);
});

test('resizing a padded callout moves its tip with the dragged corner and keeps the marker where it is', () => {
  const h = helpers();
  const callout = { type: 'stamp', stamp: 'question', x: 77, y: 77, width: 47, height: 147, points: [[100, 100], [100, 200]] };
  const longer = h.officekitResizeScreenshotObject([callout], 0, 'br', 0, 50, 400, 400);
  assert.deepEqual(JSON.parse(JSON.stringify(longer.points)), [[100, 100], [100, 250]]);
  assert.equal(longer.height, 197);
  const shorter = h.officekitResizeScreenshotObject([callout], 0, 'br', 0, -40, 400, 400);
  assert.deepEqual(JSON.parse(JSON.stringify(shorter.points)), [[100, 100], [100, 160]]);
  // Dragging the top-left corner moves the marker end and leaves the tip where it was.
  const marker = h.officekitResizeScreenshotObject([callout], 0, 'tl', 0, 30, 400, 400);
  assert.deepEqual(JSON.parse(JSON.stringify(marker.points)), [[100, 130], [100, 200]]);
  // A callout that is dragged narrower is not skewed sideways: a vertical callout stays vertical.
  const narrower = h.officekitResizeScreenshotObject([callout], 0, 'br', -10, 0, 400, 400);
  assert.equal(narrower.points[0][0], narrower.points[1][0]);
});

test('clicking an existing annotation selects it even when a drawing tool is active', async () => {
  const e = editor();
  // Active tool is rectangle
  e.state.tool = 'rectangle';
  // Click on the existing highlight annotation at (15, 15)
  await e.pointer('pointerdown', 15, 15);
  await e.pointer('pointerup', 15, 15);
  // Annotation is selected, delete button is enabled
  assert.equal(e.node('screenshot-delete-button').disabled, false);
  // Dragging it moves it
  await e.pointer('pointerdown', 20, 15);
  await e.pointer('pointermove', 40, 35);
  await e.pointer('pointerup', 40, 35);
  assert.equal(e.state.operations[0].x, 30);
  assert.equal(e.state.operations[0].y, 30);
});

test('live editing properties updates selected annotation and undo history', async () => {
  const e = editor();
  // Select annotation 0 at (15, 15)
  await e.pointer('pointerdown', 15, 15);
  await e.pointer('pointerup', 15, 15);
  assert.equal(e.node('screenshot-delete-button').disabled, false);

  // Change color
  e.node('screenshot-mask-color').value = '#FF0000';
  await e.node('screenshot-mask-color').fire('input');
  assert.equal(e.state.operations[0].color, '#FF0000');

  // Change stroke width
  e.node('screenshot-stroke-width').value = '8';
  await e.node('screenshot-stroke-width').fire('input');
  assert.equal(e.state.operations[0].stroke_width, 8);

  // Change outer color and outer width
  e.node('screenshot-outer-color').value = '#00FF00';
  e.node('screenshot-outer-width').value = '4';
  await e.node('screenshot-outer-width').fire('input');
  assert.equal(e.state.operations[0].outer_color, '#00FF00');
  assert.equal(e.state.operations[0].outer_width, 4);
});

test('text auto-fits into small canvas without error and clamps coordinates', async () => {
  const e = editor();
  e.state.width = 77;
  e.state.height = 28;
  e.state.bitmap = { width: 77, height: 28 };
  e.state.tool = 'text';
  // Click on canvas to insert text
  await e.pointer('pointerdown', 10, 5);
  await e.pointer('pointerup', 10, 5);
  assert.ok(e.context.document.activeElement);
  e.context.document.activeElement.value = 'Note';
  await e.context.document.activeElement.fire('blur');
  // Verify an operation was committed and fits in the 77x28 boundaries
  const textOp = e.state.operations.find(op => op.type === 'text');
  assert.ok(textOp);
  assert.ok(textOp.x + textOp.width <= 77);
  assert.ok(textOp.y + textOp.height <= 28);
  assert.ok(textOp.font_size <= 24);
});

test('changing coordinates in advanced region inputs updates selected annotation', async () => {
  const e = editor();
  // Select annotation 0
  await e.pointer('pointerdown', 15, 15);
  await e.pointer('pointerup', 15, 15);

  // Edit X, Y, Width, Height
  e.node('screenshot-region-x').value = '25';
  e.node('screenshot-region-y').value = '35';
  e.node('screenshot-region-width').value = '40';
  e.node('screenshot-region-height').value = '30';
  await e.node('screenshot-region-x').fire('change');

  assert.equal(e.state.operations[0].x, 25);
  assert.equal(e.state.operations[0].y, 35);
  assert.equal(e.state.operations[0].width, 40);
  assert.equal(e.state.operations[0].height, 30);
});
