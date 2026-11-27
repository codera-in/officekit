/* Editable screenshot objects; original image and undo snapshots stay immutable. */
(() => {
  const root = globalThis;
  const styled = ['rectangle', 'rounded_rectangle', 'circle', 'line', 'highlight', 'text', 'arrow', 'freehand', 'stamp'];
  const element = id => document.getElementById(id);
  let selected = -1;
  let selectedRef = null;
  let drag = null;
  let textEditor = null;
  let pathPreview = null;

  function frame(operations, index, initialWidth, initialHeight) {
    let width = initialWidth, height = initialHeight;
    for (let i = 0; i < index; i++) {
      if (operations[i].type === 'crop') { width = operations[i].width; height = operations[i].height; }
      else if (operations[i].type === 'rotate') [width,height]=[height,width];
    }
    return { width, height };
  }

  function objectBounds(operations, index, initialWidth, initialHeight) {
    const op = operations[index];
    if (!op || op.type === 'crop') return null;
    let { x, y, width, height } = op;
    const dimensions = frame(operations, index, initialWidth, initialHeight);
    let right = Math.min(dimensions.width, x + width), bottom = Math.min(dimensions.height, y + height), frameWidth=dimensions.width, frameHeight=dimensions.height;
    for (let i = index + 1; i < operations.length; i++) {
      const crop = operations[i];
      if(crop.type==='rotate') { const oldX=x,oldY=y,oldRight=right,oldBottom=bottom; x=frameHeight-oldBottom; y=oldX; right=frameHeight-oldY; bottom=oldRight; [frameWidth,frameHeight]=[frameHeight,frameWidth]; continue; }
      if (crop.type !== 'crop') continue;
      x -= crop.x; y -= crop.y; right -= crop.x; bottom -= crop.y;
      x = Math.max(0, x); y = Math.max(0, y);
      right = Math.min(crop.width, right); bottom = Math.min(crop.height, bottom);
      if (right <= x || bottom <= y) return null;
      frameWidth=crop.width; frameHeight=crop.height;
    }
    return { x, y, width: right - x, height: bottom - y };
  }

  function eraserRemovals(operations, swept, width, height) {
    const removed = new Set();
    for (let i=0;i<operations.length;i++) {
      if (!styled.includes(operations[i].type)) continue;
      const bounds = objectBounds(operations,i,width,height); if (!bounds) continue;
      if (swept.some(p => p.x >= bounds.x-8 && p.x <= bounds.x+bounds.width+8 && p.y >= bounds.y-8 && p.y <= bounds.y+bounds.height+8)) removed.add(i);
    }
    return removed;
  }

  function distToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1;
    const l2 = dx * dx + dy * dy;
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function getCornerHandle(clientX, clientY, bounds, canvas, state, op) {
    if (!bounds || !canvas || !state || !state.width || !state.height) return null;
    if (op && !['rectangle', 'rounded_rectangle', 'circle', 'line', 'arrow', 'freehand', 'stamp'].includes(op.type)) return null;
    const canvasRect = canvas.getBoundingClientRect();
    const sx = canvasRect.width / state.width;
    const sy = canvasRect.height / state.height;
    const threshold = Math.min(10, Math.max(4, Math.min(bounds.width * sx, bounds.height * sy) / 3));
    const corners = {
      tl: { x: canvasRect.left + bounds.x * sx, y: canvasRect.top + bounds.y * sy },
      tr: { x: canvasRect.left + (bounds.x + bounds.width) * sx, y: canvasRect.top + bounds.y * sy },
      bl: { x: canvasRect.left + bounds.x * sx, y: canvasRect.top + (bounds.y + bounds.height) * sy },
      br: { x: canvasRect.left + (bounds.x + bounds.width) * sx, y: canvasRect.top + (bounds.y + bounds.height) * sy }
    };
    for (const [key, pt] of Object.entries(corners)) {
      if (Math.hypot(clientX - pt.x, clientY - pt.y) <= threshold) return key;
    }
    return null;
  }

  function hitObject(operations, x, y, initialWidth, initialHeight, preferSelection = -1, tool = 'select') {
    // Pass 1: Direct stroke/text/border hits (so strokes inside hollow rectangles are selected first)
    for (let i = operations.length - 1; i >= 0; i--) {
      const op = operations[i];
      if (!op || op.type === 'crop') continue;
      const box = objectBounds(operations, i, initialWidth, initialHeight);
      if (!box) continue;
      const margin = 14;
      if (x < box.x - margin || y < box.y - margin || x > box.x + box.width + margin || y > box.y + box.height + margin) continue;

      if (['arrow', 'freehand', 'line', 'stamp'].includes(op.type) && Array.isArray(op.points) && op.points.length >= 2) {
        const offX = box.x - op.x, offY = box.y - op.y;
        const pts = op.points;
        const threshold = Math.max(14, ((op.stroke_width || 3) + (op.outer_width || 2) * 2) / 2 + 8);
        let hit = false;
        if (op.type === 'stamp' && Math.hypot(x - (pts[0][0] + offX), y - (pts[0][1] + offY)) <= 16) hit = true;
        if (!hit) {
          for (let j = 0; j < pts.length - 1; j++) {
            if (distToSegment(x, y, pts[j][0] + offX, pts[j][1] + offY, pts[j + 1][0] + offX, pts[j + 1][1] + offY) <= threshold) {
              hit = true; break;
            }
          }
        }
        if (hit) return i;
      } else if (op.type === 'text' || ['mask', 'highlight', 'blur', 'pixelate'].includes(op.type)) {
        if (x >= box.x && y >= box.y && x < box.x + box.width && y < box.y + box.height) return i;
      } else if (['rectangle', 'rounded_rectangle'].includes(op.type)) {
        const dBorder = Math.min(Math.abs(x - box.x), Math.abs(x - (box.x + box.width)), Math.abs(y - box.y), Math.abs(y - (box.y + box.height)));
        if (dBorder <= 14 && x >= box.x - 8 && x <= box.x + box.width + 8 && y >= box.y - 8 && y <= box.y + box.height + 8) return i;
      } else if (op.type === 'circle') {
        const rx = box.width / 2, ry = box.height / 2;
        if (rx > 0 && ry > 0) {
          const cx = box.x + rx, cy = box.y + ry;
          const normDist = Math.hypot((x - cx) / rx, (y - cy) / ry);
          if (Math.abs(normDist - 1) * Math.min(rx, ry) <= 14) return i;
        }
      }
    }
    // Pass 2: Interior hit for filled shapes or when tool is select or when clicking inside the already-selected item
    for (let i = operations.length - 1; i >= 0; i--) {
      const op = operations[i];
      if (!op || op.type === 'crop') continue;
      const box = objectBounds(operations, i, initialWidth, initialHeight);
      if (!box || x < box.x || y < box.y || x >= box.x + box.width || y >= box.y + box.height) continue;
      if (['mask', 'highlight', 'blur', 'pixelate', 'text'].includes(op.type)) return i;
      if (tool === 'select' || i === preferSelection) return i;
    }
    return -1;
  }

  function moveObject(operations, index, dx, dy, initialWidth, initialHeight) {
    const op = operations[index];
    if (!op || op.type === 'crop' || !Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error('Select an annotation to move.');
    const dimensions = frame(operations, index, initialWidth, initialHeight);
    for(let i=index+1;i<operations.length;i++)if(operations[i].type==='rotate')[dx,dy]=[dy,-dx];
    const x = Math.max(0, Math.min(dimensions.width - op.width, op.x + Math.round(dx)));
    const y = Math.max(0, Math.min(dimensions.height - op.height, op.y + Math.round(dy)));
    const moved = { ...op, x, y };
    if (op.points) moved.points = op.points.map(([px, py]) => [px + x - op.x, py + y - op.y]);
    return moved;
  }

  function resizeObject(operations, index, handle, dx, dy, initialWidth, initialHeight) {
    const op = operations[index];
    if (!op || op.type === 'crop' || !Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error('Select an annotation to resize.');
    const dimensions = frame(operations, index, initialWidth, initialHeight);
    for (let i = index + 1; i < operations.length; i++) if (operations[i].type === 'rotate') [dx, dy] = [dy, -dx];
    dx = Math.round(dx); dy = Math.round(dy);
    let x = op.x, y = op.y, width = op.width, height = op.height;
    const minW = 8, minH = 8;
    if (handle === 'br') {
      width = Math.max(minW, Math.min(dimensions.width - x, op.width + dx));
      height = Math.max(minH, Math.min(dimensions.height - y, op.height + dy));
    } else if (handle === 'tl') {
      const newX = Math.max(0, Math.min(op.x + op.width - minW, op.x + dx));
      const newY = Math.max(0, Math.min(op.y + op.height - minH, op.y + dy));
      width = op.width - (newX - op.x);
      height = op.height - (newY - op.y);
      x = newX; y = newY;
    } else if (handle === 'tr') {
      const newY = Math.max(0, Math.min(op.y + op.height - minH, op.y + dy));
      width = Math.max(minW, Math.min(dimensions.width - op.x, op.width + dx));
      height = op.height - (newY - op.y);
      y = newY;
    } else if (handle === 'bl') {
      const newX = Math.max(0, Math.min(op.x + op.width - minW, op.x + dx));
      width = op.width - (newX - op.x);
      height = Math.max(minH, Math.min(dimensions.height - op.y, op.height + dy));
      x = newX;
    }
    const resized = { ...op, x, y, width, height };
    if (op.points && op.points.length >= 2) {
      // The box is the points plus padding (room for arrow heads and callout markers). Scale the points' own
      // extent between the same padding, so the marker follows the dragged corner and is not skewed by the padding.
      const xs = op.points.map(p => p[0]), ys = op.points.map(p => p[1]);
      const fromX = Math.min(...xs), fromY = Math.min(...ys);
      const fromW = Math.max(...xs) - fromX, fromH = Math.max(...ys) - fromY;
      const padLeft = fromX - op.x, padTop = fromY - op.y;
      const padRight = Math.max(0, op.x + op.width - 1 - Math.max(...xs)), padBottom = Math.max(0, op.y + op.height - 1 - Math.max(...ys));
      const toX = x + padLeft, toY = y + padTop;
      const toW = Math.max(0, width - 1 - padLeft - padRight), toH = Math.max(0, height - 1 - padTop - padBottom);
      const sx = fromW > 0 ? toW / fromW : 1;
      const sy = fromH > 0 ? toH / fromH : 1;
      resized.points = op.points.map(([px, py]) => [
        Math.max(x, Math.min(x + width - 1, Math.round(toX + (px - fromX) * sx))),
        Math.max(y, Math.min(y + height - 1, Math.round(toY + (py - fromY) * sy)))
      ]);
    }
    return resized;
  }

  function pathOperation(type, points, width, height, style) {
    if (!['arrow', 'freehand', 'line', 'stamp'].includes(type) || !Array.isArray(points) || points.length < 2) throw new Error('Draw at least two distinct points.');
    if (points.length > (type === 'arrow' || type === 'line' || type === 'stamp' ? 2 : 512)) throw new Error('A freehand annotation supports at most 512 points. Draw a shorter path.');
    const normalized = points.map(point => {
      if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isInteger)) throw new Error('Path coordinates are invalid.');
      return [Math.max(0, Math.min(width - 1, point[0])), Math.max(0, Math.min(height - 1, point[1]))];
    });
    if (normalized.every(p => p[0] === normalized[0][0] && p[1] === normalized[0][1])) throw new Error('Draw at least two distinct points.');
    const padding = (style.stroke_width || 3) + (style.outer_width || 2) * 2 + (['arrow','stamp'].includes(type) ? 16 : 0);
    const xs = normalized.map(p => p[0]), ys = normalized.map(p => p[1]);
    const x = Math.max(0, Math.min(...xs) - padding), y = Math.max(0, Math.min(...ys) - padding);
    const right = Math.min(width, Math.max(...xs) + padding + 1), bottom = Math.min(height, Math.max(...ys) + padding + 1);
    return { type, x, y, width: right - x, height: bottom - y, ...style, points: normalized };
  }

  function updatePathPreview(points, type) {
    const state = officekitScreenshot, canvas = element('screenshot-canvas'), stage = element('screenshot-canvas-stage');
    if (!state.bitmap || !canvas || !stage || typeof document.createElementNS !== 'function') return;
    if (!pathPreview) {
      pathPreview = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      pathPreview.setAttribute('aria-hidden', 'true');
      Object.assign(pathPreview.style, { position: 'absolute', pointerEvents: 'none', overflow: 'visible' });
      stage.append(pathPreview);
    }
    const canvasRect = canvas.getBoundingClientRect(), stageRect = stage.getBoundingClientRect();
    pathPreview.setAttribute('viewBox', `0 0 ${state.width} ${state.height}`);
    pathPreview.setAttribute('preserveAspectRatio', 'none');
    Object.assign(pathPreview.style, { left: `${canvasRect.left - stageRect.left}px`, top: `${canvasRect.top - stageRect.top}px`, width: `${canvasRect.width}px`, height: `${canvasRect.height}px` });
    pathPreview.replaceChildren();
    const style = inspectorStyle(type), value = points.map(point => point.join(',')).join(' ');
    if (style.outer_width > 0) {
      const outline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      outline.setAttribute('points', value); outline.setAttribute('fill', 'none'); outline.setAttribute('stroke', style.outer_color);
      outline.setAttribute('stroke-width', String(style.stroke_width + 2 * style.outer_width)); outline.setAttribute('stroke-linecap', 'round'); outline.setAttribute('stroke-linejoin', 'round');
      pathPreview.append(outline);
    }
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', value); line.setAttribute('fill', 'none'); line.setAttribute('stroke', style.color);
    line.setAttribute('stroke-width', String(style.stroke_width)); line.setAttribute('stroke-linecap', 'round'); line.setAttribute('stroke-linejoin', 'round');
    pathPreview.append(line);
    const stamp = officekitScreenshot.stamp;
    if (type === 'stamp' && points.length > 1) {
      const marker = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      marker.setAttribute('cx', points[0][0]); marker.setAttribute('cy', points[0][1]); marker.setAttribute('r', '10');
      marker.setAttribute('fill', '#fff'); marker.setAttribute('stroke', style.color); marker.setAttribute('stroke-width', '3'); pathPreview.append(marker);
      const glyph = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      glyph.setAttribute('x', points[0][0]); glyph.setAttribute('y', points[0][1] + 4); glyph.setAttribute('text-anchor', 'middle');
      glyph.setAttribute('fill', style.color); glyph.textContent = ({check:'✓',question:'?',x:'×',alert:'!',heart:'♥'})[stamp] || '✓'; pathPreview.append(glyph);
    }
  }

  function clearPathPreview() { pathPreview?.remove(); pathPreview = null; }

  function inspectorStyle(type) {
    const style = { color: element('screenshot-mask-color')?.value?.toUpperCase() || '#185C89' };
    if (styled.includes(type)) Object.assign(style, {
      outer_color: element('screenshot-outer-color')?.value?.toUpperCase() || '#FFFFFF',
      stroke_width: Number(element('screenshot-stroke-width')?.value || 3),
      outer_width: Number(element('screenshot-outer-width')?.value || 2),
    });
    if (type === 'text') style.font_size = Number(element('screenshot-font-size')?.value || 24);
    return style;
  }

  function fitText(text, fontSize, outerWidth, canvasWidth, canvasHeight, x, y) {
    let size = Math.max(8, Math.min(120, Math.round(Number(fontSize) || 24)));
    const pad = Math.max(0, Math.round(Number(outerWidth) || 0)) * 2;
    let width = Math.ceil(text.length * size * 0.8 + pad);
    let height = Math.ceil(size * 1.6 + pad);
    if (width > canvasWidth && text.length > 0) {
      size = Math.max(8, Math.floor((canvasWidth - pad) / Math.max(1, text.length * 0.8)));
      width = Math.ceil(text.length * size * 0.8 + pad);
    }
    if (height > canvasHeight) {
      size = Math.max(8, Math.floor((canvasHeight - pad) / 1.6));
      height = Math.ceil(size * 1.6 + pad);
      width = Math.ceil(text.length * size * 0.8 + pad);
    }
    width = Math.max(1, Math.min(canvasWidth, Math.round(width)));
    height = Math.max(1, Math.min(canvasHeight, Math.round(height)));
    const safeX = Math.max(0, Math.min(canvasWidth - width, Math.round(Number(x) || 0)));
    const safeY = Math.max(0, Math.min(canvasHeight - height, Math.round(Number(y) || 0)));
    return { font_size: size, width, height, x: safeX, y: safeY };
  }

  function select(index) {
    selected = index;
    selectedRef = officekitScreenshot.operations[index] || null;
    if (selectedRef) {
      const values = {
        'screenshot-mask-color': selectedRef.color,
        'screenshot-outer-color': selectedRef.outer_color,
        'screenshot-stroke-width': selectedRef.stroke_width,
        'screenshot-outer-width': selectedRef.outer_width,
        'screenshot-font-size': selectedRef.font_size,
        'screenshot-annotation-text': selectedRef.text,
        'screenshot-region-x': selectedRef.x,
        'screenshot-region-y': selectedRef.y,
        'screenshot-region-width': selectedRef.width,
        'screenshot-region-height': selectedRef.height
      };
      Object.entries(values).forEach(([id, value]) => { if (value != null && element(id)) element(id).value = value; });
      if (selectedRef.type === 'pixelate' && selectedRef.block_size != null && element('screenshot-pixel-block-size')) {
        element('screenshot-pixel-block-size').value = selectedRef.block_size;
      }
      if (selectedRef.type === 'blur' && selectedRef.radius != null && element('screenshot-blur-radius')) {
        element('screenshot-blur-radius').value = selectedRef.radius;
        if (element('screenshot-blur-value')) element('screenshot-blur-value').textContent = selectedRef.radius;
      }
    }
    refreshSelection();
  }

  function updateSelectionBox(bounds) {
    const selection = element('screenshot-selection');
    const canvas = element('screenshot-canvas');
    const stage = element('screenshot-canvas-stage');
    const state = officekitScreenshot;
    if (!selection || !canvas || !stage || !bounds || !state.width || !state.height) return;
    const canvasRect = canvas.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    Object.assign(selection.style, {
      left: `${canvasRect.left - stageRect.left + bounds.x * canvasRect.width / state.width}px`,
      top: `${canvasRect.top - stageRect.top + bounds.y * canvasRect.height / state.height}px`,
      width: `${bounds.width * canvasRect.width / state.width}px`,
      height: `${bounds.height * canvasRect.height / state.height}px`
    });
    selection.classList.remove('hidden');
  }

  function refreshSelection() {
    const state = officekitScreenshot;
    if (!state.bitmap || (drag && drag.bitmap !== state.bitmap)) { drag = null; state.drawing = null; }
    if (selectedRef !== state.operations[selected] || !state.bitmap) { selected = -1; selectedRef = null; }
    const selection = element('screenshot-selection');
    const remove = element('screenshot-delete-button');
    if (remove) remove.disabled = selected < 0;

    const hasSelection = selected >= 0 && selectedRef != null;
    const type = selectedRef?.type || state.tool;
    const isShape = ['rectangle', 'rounded_rectangle', 'circle', 'line', 'arrow', 'freehand'].includes(type);
    const showStroke = isShape;
    const showOuterWidth = isShape;
    const showOuterColor = isShape || type === 'text';
    const showMainColor = isShape || ['mask', 'highlight', 'text'].includes(type);

    // Toolbar contextual controls visibility
    const mainColorCtrl = element('screenshot-main-color-control');
    const outerColorCtrl = element('screenshot-outer-color-control');
    const strokeCtrl = element('screenshot-stroke-control');
    const outerWidthCtrl = element('screenshot-outer-width-control');

    if (mainColorCtrl) mainColorCtrl.classList.toggle('hidden', !showMainColor);
    if (outerColorCtrl) outerColorCtrl.classList.toggle('hidden', !showOuterColor);
    if (strokeCtrl) strokeCtrl.classList.toggle('hidden', !showStroke);
    if (outerWidthCtrl) outerWidthCtrl.classList.toggle('hidden', !showOuterWidth);

    // Toolbar status description
    const desc = element('screenshot-tool-description');
    if (desc) {
      if (hasSelection) {
        const typeNames = {
          rectangle: 'Square',
          rounded_rectangle: 'Rounded rectangle',
          circle: 'Circle',
          line: 'Line',
          arrow: 'Arrow',
          highlight: 'Highlight',
          text: 'Text',
          freehand: 'Freehand',
          stamp: 'Callout',
          mask: 'Mask',
          blur: 'Blur',
          pixelate: 'Pixelate'
        };
        const name = typeNames[selectedRef.type] || (selectedRef.type[0].toUpperCase() + selectedRef.type.slice(1));
        const action = selectedRef.type === 'text' ? 'drag to move or double-click to edit' : 'drag to move or resize';
        desc.textContent = `${name} selected · ${action}`;
      } else {
        const titles = { select: 'Click annotation to select · drag to move or resize', crop: 'Crop selected · drag a rectangle', blur: 'Blur selected · drag over sensitive detail', mask: 'Opaque mask selected · drag over sensitive detail', pixelate: 'Pixelate selected · drag over an area', rectangle: 'Square selected · drag over an area', rounded_rectangle: 'Rounded rectangle selected · drag over an area', circle: 'Circle selected · drag over an area', line: 'Line selected · drag from start to end', highlight: 'Highlight selected · drag over an area', text: 'Text selected · click where the text should go', arrow: 'Arrow selected · drag from tail to tip', freehand: 'Freehand selected · draw on the image', stamp: `${officekitScreenshot.stamp || 'Check'} callout selected · drag from marker to target`, eraser: 'Annotation eraser · drag across marks to remove them', pan: 'Pan view · drag to move the image' };
        desc.textContent = titles[state.tool] || 'Click annotation to select · drag to move or resize';
      }
    }

    // Advanced settings panel: never keep it empty!
    const inspector = element('screenshot-contextual-settings');
    if (inspector) {
      inspector.dataset.annotationType = type;
      inspector.classList.remove('hidden');
      inspector.querySelectorAll('[data-annotation-settings]').forEach(group => {
        const allowed = group.dataset.annotationSettings.split(' ');
        group.classList.toggle('hidden', !allowed.includes(type));
      });
      const hint = element('screenshot-advanced-help-hint');
      if (hint) {
        hint.textContent = hasSelection
          ? `Editing selected ${selectedRef.type} (#${selected + 1}). Coordinates and styles apply live.`
          : 'Choose a tool above to draw, or click any annotation on the canvas to inspect and edit.';
      }
      const applyBtn = element('screenshot-apply-region');
      if (applyBtn) {
        applyBtn.textContent = 'Apply selected tool';
      }
    }

    const objectList = element('screenshot-object-list');
    if (objectList?.replaceChildren) {
      const empty = document.createElement('option'); empty.value = '-1'; empty.textContent = 'Select an annotation';
      const options = state.operations.flatMap((op,index) => {
        if (op.type === 'crop') return [];
        const option = document.createElement('option'); option.value = String(index);
        option.textContent = `${index + 1}. ${op.type === 'circle' ? 'Circle' : op.type[0].toUpperCase() + op.type.slice(1)}${op.type === 'text' ? ` · ${op.text.slice(0,32)}` : ''}`;
        return [option];
      });
      objectList.replaceChildren(empty,...options);
      objectList.value = String(selected); objectList.disabled = options.length === 0;
    }
    if (!selection || drag) return;
    const bounds = state.bitmap && objectBounds(state.operations, selected, state.bitmap.width, state.bitmap.height);
    if (!bounds) { selection.classList.add('hidden'); return; }
    updateSelectionBox(bounds);
  }

  async function commit(next, selectedIndex = -1) {
    const state = officekitScreenshot;
    try {
      if (next.length) officekitValidateScreenshotOperations(next, state.bitmap.width, state.bitmap.height);
      if (new TextEncoder().encode(JSON.stringify(next)).length > 32768) throw new Error('Annotations exceed the 32 KiB limit. Remove an annotation or shorten a path.');
      if (state.undo.length >= 20) state.undo.shift();
      state.undo.push(state.operations);
      state.redo = [];
      state.operations = next;
      state.lastExport = null;
      const mediaHandoff = element('screenshot-media-toolkit-button');
      if (mediaHandoff) mediaHandoff.disabled = true;
      if (state.exportUrl) { URL.revokeObjectURL(state.exportUrl); state.exportUrl = null; }
      const download = element('screenshot-download-link');
      if (download) { download.removeAttribute('href'); download.classList.add('hidden'); }
      select(selectedIndex);
      await officekitRenderScreenshotPreview();
      refreshSelection();
      return true;
    } catch (error) {
      officekitScreenshotStatus(error?.message || 'That annotation could not be changed.');
      return false;
    }
  }

  async function removeSelected() {
    if (selected < 0 || !selectedRef) return;
    const next = officekitScreenshot.operations.filter((_, index) => index !== selected);
    if (await commit(next)) officekitScreenshotStatus('Annotation removed. Undo restores it.');
  }

  function openTextEditor(point, index = -1) {
    // A click while a text box is open only saves that box; it never opens a second one on top of it.
    if (textEditor) { textEditor.blur(); return; }
    const state = officekitScreenshot;
    const imageBitmap = state.bitmap;
    const old = state.operations[index];
    const bounds = old ? objectBounds(state.operations, index, state.bitmap.width, state.bitmap.height) : point;
    if (!bounds) return;
    const input = document.createElement('input');
    input.type = 'text'; input.maxLength = 200; input.setAttribute('aria-label', 'Annotation text. Enter to save, Escape to cancel.');
    input.className = 'input  officekit-field';
    // A new text box starts empty. Prefilling the last text made every extra click save a duplicate of it.
    input.value = old?.text || '';
    input.placeholder = 'Type text';
    const canvas = element('screenshot-canvas').getBoundingClientRect(), stage = element('screenshot-canvas-stage').getBoundingClientRect();
    Object.assign(input.style, { position: 'absolute', left: `${canvas.left - stage.left + bounds.x * canvas.width / state.width}px`,
      top: `${canvas.top - stage.top + bounds.y * canvas.height / state.height}px`, zIndex: '4', width: 'min(320px, 90%)' });
    element('screenshot-canvas-stage').append(input);
    textEditor = input;
    let finished = false;
    const finish = async cancelled => {
      if (finished) return;
      finished = true; textEditor = null;
      const text = input.value.trim(); input.remove();
      if (cancelled || !text || state.bitmap !== imageBitmap) return;
      const style = inspectorStyle('text');
      const startX = old ? old.x : Math.min(point.x, state.width - 1);
      const startY = old ? old.y : Math.min(point.y, state.height - 1);
      const fitted = fitText(text, style.font_size, style.outer_width, state.width, state.height, startX, startY);
      const op = {
        type: 'text',
        text,
        color: style.color,
        outer_color: style.outer_color,
        stroke_width: style.stroke_width,
        outer_width: style.outer_width,
        font_size: fitted.font_size,
        x: fitted.x,
        y: fitted.y,
        width: fitted.width,
        height: fitted.height,
      };
      if (element('screenshot-annotation-text')) element('screenshot-annotation-text').value = text;
      if (element('screenshot-font-size')) element('screenshot-font-size').value = fitted.font_size;
      const next = [...state.operations];
      if (old) next[index] = op; else next.push(op);
      if (await commit(next, old ? index : next.length - 1)) {
        officekitScreenshotSetTool('select');
        officekitScreenshotStatus('Text saved. Select to move; double-click to edit.');
      }
    };
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void finish(event.key === 'Escape'); }
    });
    input.addEventListener('blur', () => void finish(false));
    input.focus(); input.select();
  }

  function bindObjects() {
    const canvas = element('screenshot-canvas');
    if (!canvas || canvas.dataset.objectsBound) return;
    canvas.dataset.objectsBound = 'true';
    canvas.tabIndex = 0;
    canvas.addEventListener('pointerdown', event => {
      const state = officekitScreenshot;
      if (!state.bitmap || event.button > 0) return;
      event.preventDefault(); canvas.focus();
      const point = officekitScreenshotCoordinates(event);
      if (state.tool === 'rotate') return;

      // 1. Check corner resize handles on the currently selected object
      const selectedBounds = selected >= 0 ? objectBounds(state.operations, selected, state.bitmap.width, state.bitmap.height) : null;
      if (selectedBounds) {
        const handle = getCornerHandle(event.clientX, event.clientY, selectedBounds, canvas, state, selectedRef);
        if (handle) {
          drag = { kind: 'resize', handle, start: point, initial: state.operations, index: selected, bitmap: state.bitmap };
          canvas.setPointerCapture(event.pointerId);
          return;
        }
      }

      // 2. Pan and eraser modes
      if (state.tool === 'pan') {
        drag = { kind: 'pan', start: point, clientX: event.clientX, clientY: event.clientY, bitmap: state.bitmap };
        canvas.setPointerCapture(event.pointerId);
        return;
      }
      if (state.tool === 'eraser') {
        select(-1);
        drag = { kind: 'eraser', start: point, bitmap: state.bitmap, points: [point] };
        canvas.setPointerCapture(event.pointerId);
        return;
      }

      // 3. Hit-test existing objects (Pass 1 strokes/paths/borders, Pass 2 interior)
      const hit = hitObject(state.operations, point.x, point.y, state.bitmap.width, state.bitmap.height, selected, state.tool);
      if (hit >= 0 && state.tool !== 'crop') {
        if (state.tool === 'text' && state.operations[hit]?.type === 'text') {
          select(hit);
          openTextEditor(point, hit);
          return;
        }
        if (state.tool !== 'select') officekitScreenshotSetTool('select');
        select(hit);
        drag = { kind: 'move', start: point, initial: state.operations, index: hit, bitmap: state.bitmap, moved: false };
        try { canvas.setPointerCapture(event.pointerId); } catch (_) {}
        return;
      }

      // 4. Text tool on blank space
      if (state.tool === 'text') { openTextEditor(point); return; }

      // 5. Select tool on blank space: deselect
      if (state.tool === 'select') { select(-1); return; }

      // 6. Drawing tools on blank space
      select(-1);
      drag = { kind: state.tool, start: point, bitmap: state.bitmap, points: [[Math.min(state.width - 1, point.x), Math.min(state.height - 1, point.y)]], exceeded: false };
      state.drawing = point;
      if (['freehand','stamp','line','arrow'].includes(state.tool)) updatePathPreview(drag.points, state.tool);
      else officekitUpdateScreenshotSelection(point);
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
      const state = officekitScreenshot;
      if (!drag) {
        if (!state.bitmap) return;
        const point = officekitScreenshotCoordinates(event);
        const selectedBounds = selected >= 0 ? objectBounds(state.operations, selected, state.bitmap.width, state.bitmap.height) : null;
        if (selectedBounds) {
          const handle = getCornerHandle(event.clientX, event.clientY, selectedBounds, canvas, state, selectedRef);
          if (handle) {
            canvas.style.cursor = (handle === 'tl' || handle === 'br') ? 'nwse-resize' : 'nesw-resize';
            return;
          }
        }
        const hit = hitObject(state.operations, point.x, point.y, state.bitmap.width, state.bitmap.height, selected, state.tool);
        if (hit >= 0 && !['eraser', 'pan', 'crop'].includes(state.tool)) {
          canvas.style.cursor = hit === selected ? 'move' : 'pointer';
          return;
        }
        if (state.tool === 'pan') canvas.style.cursor = 'grab';
        else if (state.tool === 'select') canvas.style.cursor = 'default';
        else if (state.tool === 'text') canvas.style.cursor = 'text';
        else canvas.style.cursor = 'crosshair';
        return;
      }
      const point = officekitScreenshotCoordinates(event);
      if (drag.kind === 'pan') {
        const dx = event.clientX - drag.clientX, dy = event.clientY - drag.clientY;
        const stage = element('screenshot-canvas-stage'); stage.scrollLeft -= dx; stage.scrollTop -= dy;
        drag.clientX = event.clientX; drag.clientY = event.clientY;
      } else if (drag.kind === 'resize') {
        const resized = resizeObject(drag.initial, drag.index, drag.handle, point.x - drag.start.x, point.y - drag.start.y, state.bitmap.width, state.bitmap.height);
        const next = [...drag.initial]; next[drag.index] = resized;
        const bounds = objectBounds(next, drag.index, state.bitmap.width, state.bitmap.height);
        if (bounds) updateSelectionBox(bounds);
      } else if (drag.kind === 'move') {
        drag.moved = true;
        const moved = moveObject(drag.initial, drag.index, point.x - drag.start.x, point.y - drag.start.y, state.bitmap.width, state.bitmap.height);
        const next = [...drag.initial]; next[drag.index] = moved;
        const bounds = objectBounds(next, drag.index, state.bitmap.width, state.bitmap.height);
        if (bounds) updateSelectionBox(bounds);
      } else if (drag.kind === 'eraser') {
        drag.points.push(point); updatePathPreview(drag.points.map(p => [p.x,p.y]), 'freehand');
      } else if (['freehand','stamp','line','arrow'].includes(drag.kind)) {
        const coalesced = event.getCoalescedEvents?.();
        const samples = coalesced?.length ? coalesced : [event];
        for (const sample of samples) {
          const sampled = officekitScreenshotCoordinates(sample);
          const p = [Math.min(state.width - 1, sampled.x), Math.min(state.height - 1, sampled.y)];
          const previous = drag.points.at(-1);
          if (p[0] !== previous[0] || p[1] !== previous[1]) {
            if (drag.points.length < 512) drag.points.push(p); else drag.exceeded = true;
          }
        }
        updatePathPreview(drag.points, drag.kind);
      } else {
        officekitUpdateScreenshotSelection(point);
      }
    });
    canvas.addEventListener('pointerup', async event => {
      if (!drag) return;
      const gesture = drag, state = officekitScreenshot, end = officekitScreenshotCoordinates(event);
      drag = null; state.drawing = null;
      clearPathPreview();
      if (!state.bitmap || state.bitmap !== gesture.bitmap) { refreshSelection(); return; }
      if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      element('screenshot-selection')?.classList.add('hidden');
      if (gesture.kind === 'resize') {
        const next = [...gesture.initial];
        next[gesture.index] = resizeObject(next, gesture.index, gesture.handle, end.x - gesture.start.x, end.y - gesture.start.y, state.bitmap.width, state.bitmap.height);
        if (next[gesture.index].width !== gesture.initial[gesture.index].width || next[gesture.index].height !== gesture.initial[gesture.index].height || next[gesture.index].x !== gesture.initial[gesture.index].x || next[gesture.index].y !== gesture.initial[gesture.index].y) {
          await commit(next, gesture.index);
        } else {
          refreshSelection();
        }
      } else if (gesture.kind === 'move') {
        const next = [...gesture.initial];
        next[gesture.index] = moveObject(next, gesture.index, end.x - gesture.start.x, end.y - gesture.start.y, state.bitmap.width, state.bitmap.height);
        if (next[gesture.index].x !== gesture.initial[gesture.index].x || next[gesture.index].y !== gesture.initial[gesture.index].y) {
          await commit(next, gesture.index);
        } else {
          select(gesture.index);
        }
      } else if (gesture.kind === 'pan') {
        refreshSelection();
      } else if (gesture.kind === 'eraser') {
        clearPathPreview();
        const swept = gesture.points, state = officekitScreenshot;
        const removed = eraserRemovals(state.operations,swept,state.bitmap.width,state.bitmap.height);
        if (removed.size) { const next=state.operations.filter((_,i)=>!removed.has(i)); if(await commit(next)) officekitScreenshotStatus(`${removed.size} annotation${removed.size===1?'':'s'} erased. Undo restores ${removed.size===1?'it':'them'}.`); }
        else officekitScreenshotStatus('No annotation crossed. Original image pixels are unchanged.');
      } else if (['arrow', 'freehand','line','stamp'].includes(gesture.kind)) {
        if (Math.hypot(end.x - gesture.start.x, end.y - gesture.start.y) < 3) {
          select(-1);
          return;
        }
        try {
          if (gesture.exceeded) throw new Error('This path exceeds 512 points. Draw a shorter path; no points were silently removed.');
          const endpoint = [Math.min(state.width-1,end.x),Math.min(state.height-1,end.y)];
          const points = ['arrow','line','stamp'].includes(gesture.kind) ? [gesture.points[0], endpoint] : [...gesture.points];
          if (gesture.kind === 'freehand' && points.at(-1).some((value,index)=>value!==endpoint[index])) points.push(endpoint);
          const op = pathOperation(gesture.kind, points, state.width, state.height, inspectorStyle(gesture.kind));
          if(gesture.kind==='stamp'){op.stamp=state.stamp;delete op.color;delete op.outer_color;delete op.stroke_width;delete op.outer_width;}
          const next = [...state.operations, op];
          if (await commit(next, next.length - 1)) {
            const label = gesture.kind === 'stamp' ? 'Directional callout' : gesture.kind[0].toUpperCase() + gesture.kind.slice(1);
            officekitScreenshotSetTool('select');
            select(next.length - 1);
            officekitScreenshotStatus(`${label} added. Click to select, drag to move.`);
          }
        } catch(error) { officekitScreenshotStatus(error.message); }
      } else {
        if (Math.abs(end.x - gesture.start.x) >= 2 || Math.abs(end.y - gesture.start.y) >= 2) {
          await officekitApplyScreenshotRegion(Math.min(gesture.start.x,end.x),Math.min(gesture.start.y,end.y),Math.max(1,Math.abs(end.x-gesture.start.x)),Math.max(1,Math.abs(end.y-gesture.start.y)));
          if (['rectangle', 'rounded_rectangle', 'circle', 'line', 'highlight'].includes(gesture.kind)) {
            officekitScreenshotSetTool('select');
          }
          select(state.operations.length - 1);
        } else {
          select(-1);
        }
      }
    });
    canvas.addEventListener('pointercancel', () => { drag = null; officekitScreenshot.drawing = null; clearPathPreview(); refreshSelection(); });
    canvas.addEventListener('dblclick', event => {
      if (!officekitScreenshot.bitmap) return;
      const point = officekitScreenshotCoordinates(event), state = officekitScreenshot;
      const index = hitObject(state.operations,point.x,point.y,state.bitmap.width,state.bitmap.height,selected,state.tool);
      if (index >= 0 && state.operations[index]?.type === 'text') { select(index); openTextEditor(point,index); }
    });
    element('screenshot-delete-button')?.addEventListener('click', () => void removeSelected());
    element('screenshot-object-list')?.addEventListener('change', event => {
      const index = Number(event.target.value);
      select(Number.isInteger(index) && index >= 0 && officekitScreenshot.operations[index]?.type !== 'crop' ? index : -1);
    });

    const updateSelectedFromInputs = async () => {
      if (!selectedRef || selected < 0) return;
      const state = officekitScreenshot;
      const next = [...state.operations];
      const op = { ...selectedRef };
      if (!styled.includes(op.type) && op.type !== 'mask' && op.type !== 'blur' && op.type !== 'pixelate') return;
      Object.assign(op, inspectorStyle(op.type));
      if (op.type === 'blur' && element('screenshot-blur-radius')) {
        op.radius = Math.max(1, Math.min(100, Number(element('screenshot-blur-radius').value) || 24));
      }
      if (op.type === 'pixelate' && element('screenshot-pixel-block-size')) {
        op.block_size = Math.max(2, Math.min(64, Number(element('screenshot-pixel-block-size').value) || 12));
      }
      if (op.type === 'text') {
        const text = element('screenshot-annotation-text')?.value?.trim() || op.text || 'Note';
        const fontSize = Number(element('screenshot-font-size')?.value) || op.font_size || 24;
        const outerWidth = Number(element('screenshot-outer-width')?.value) || op.outer_width || 2;
        const fitted = fitText(text, fontSize, outerWidth, state.width, state.height, op.x, op.y);
        Object.assign(op, fitted, { text });
      }
      if (['arrow','line','freehand','stamp'].includes(op.type) && Array.isArray(op.points)) {
        const padding = (op.stroke_width || 3) + (op.outer_width || 2) * 2 + (['arrow','stamp'].includes(op.type) ? 16 : 0);
        const xs = op.points.map(p => p[0]), ys = op.points.map(p => p[1]);
        const minX = Math.min(...xs), minY = Math.min(...ys), maxX = Math.max(...xs), maxY = Math.max(...ys);
        op.x = Math.max(0, minX - padding);
        op.y = Math.max(0, minY - padding);
        op.width = Math.min(state.width - op.x, Math.max(1, maxX - op.x + padding + 1));
        op.height = Math.min(state.height - op.y, Math.max(1, maxY - op.y + padding + 1));
      }
      next[selected] = op;
      await commit(next, selected);
    };

    for (const id of ['screenshot-mask-color','screenshot-outer-color','screenshot-stroke-width','screenshot-outer-width','screenshot-font-size','screenshot-annotation-text','screenshot-blur-radius','screenshot-pixel-block-size']) {
      const el = element(id);
      if (el) {
        el.addEventListener('input', updateSelectedFromInputs);
        el.addEventListener('change', updateSelectedFromInputs);
      }
    }

    const updateSelectedCoordinates = async () => {
      if (!selectedRef || selected < 0) return;
      const state = officekitScreenshot;
      const newX = Number(element('screenshot-region-x')?.value ?? selectedRef.x);
      const newY = Number(element('screenshot-region-y')?.value ?? selectedRef.y);
      const newW = Number(element('screenshot-region-width')?.value ?? selectedRef.width);
      const newH = Number(element('screenshot-region-height')?.value ?? selectedRef.height);
      const dx = newX - selectedRef.x;
      const dy = newY - selectedRef.y;
      const dw = newW - selectedRef.width;
      const dh = newH - selectedRef.height;
      if (dx === 0 && dy === 0 && dw === 0 && dh === 0) return;

      let nextOp = { ...selectedRef };
      if (dw !== 0 || dh !== 0) {
        nextOp = resizeObject(state.operations, selected, 'br', dw, dh, state.bitmap.width, state.bitmap.height);
      }
      if (dx !== 0 || dy !== 0) {
        const curOps = [...state.operations]; curOps[selected] = nextOp;
        nextOp = moveObject(curOps, selected, dx, dy, state.bitmap.width, state.bitmap.height);
      }
      const next = [...state.operations];
      next[selected] = nextOp;
      await commit(next, selected);
    };

    for (const id of ['screenshot-region-x', 'screenshot-region-y', 'screenshot-region-width', 'screenshot-region-height']) {
      element(id)?.addEventListener('change', updateSelectedCoordinates);
    }
    document.querySelectorAll('[data-screenshot-tool]').forEach(button => button.addEventListener('click', () => { select(-1); button.closest('details')?.removeAttribute('open'); }));
    document.querySelectorAll('[data-stamp]').forEach(button => button.addEventListener('click', () => { officekitScreenshot.stamp=button.dataset.stamp; officekitScreenshotSetTool('stamp'); button.closest('details')?.removeAttribute('open'); }));
    element('screenshot-rotate')?.addEventListener('click', async () => {
      const next=[...officekitScreenshot.operations,{type:'rotate'}]; if(await commit(next)) officekitScreenshotStatus('Image rotated 90° clockwise. Undo restores the previous orientation.');
    });
    const canvasNode=canvas;
    const applyZoom = zoom => {
      canvasNode.style.width=''; canvasNode.style.height=''; canvasNode.style.maxWidth=''; canvasNode.style.maxHeight='';canvasNode.style.flex='';
      const fit=canvasNode.getBoundingClientRect(); officekitScreenshot.zoom=zoom;
      if(zoom===1)return;
      canvasNode.style.width=`${fit.width*zoom}px`;canvasNode.style.height=`${fit.height*zoom}px`;
      canvasNode.style.maxWidth='none';canvasNode.style.maxHeight='none';canvasNode.style.flex='none';
    };
    for(const [id,factor] of [['screenshot-zoom-in',1.2],['screenshot-zoom-out',1/1.2]]) element(id)?.addEventListener('click',()=>applyZoom(Math.max(.25,Math.min(4,officekitScreenshot.zoom*factor))));
    element('screenshot-fit-view')?.addEventListener('click',()=>{applyZoom(1);element('screenshot-canvas-stage').scrollTo(0,0);});
    document.addEventListener('keydown', async event => {
      if (!officekitScreenshotVisible() || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement;
      if (active?.isContentEditable || ['INPUT','TEXTAREA','SELECT'].includes(active?.tagName)) return;
      if (event.key === 'Escape') { select(-1); return; }
      if(officekitScreenshot.tool==='pan' && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();const d={ArrowLeft:[-60,0],ArrowRight:[60,0],ArrowUp:[0,-60],ArrowDown:[0,60]}[event.key];element('screenshot-canvas-stage').scrollBy(...d);return;}
      if (['Delete','Backspace'].includes(event.key) && selected >= 0) { event.preventDefault(); await removeSelected(); return; }
      const directions = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
      if (directions[event.key] && selected >= 0) {
        event.preventDefault(); const [dx,dy] = directions[event.key], state = officekitScreenshot, next = [...state.operations], step = event.shiftKey ? 10 : 1;
        next[selected] = moveObject(next,selected,dx*step,dy*step,state.bitmap.width,state.bitmap.height);
        await commit(next,selected);
        return;
      }
      if(event.code==='Space' && officekitScreenshot.bitmap){event.preventDefault();officekitScreenshotSetTool('pan');return;}
      if(event.key==='+'||event.key==='='){element('screenshot-zoom-in')?.click();return;}
      if(event.key==='-'){element('screenshot-zoom-out')?.click();return;}
      if(event.key==='0'){element('screenshot-fit-view')?.click();return;}
      const shortcuts = {v:'select',c:'crop',b:'blur',m:'mask',h:'highlight',t:'text',a:'arrow',p:'freehand',o:'circle',r:'rectangle',g:'pan'};
      const tool = shortcuts[event.key.toLowerCase()];
      if (tool && !event.repeat) { event.preventDefault(); officekitScreenshotSetTool(tool); select(-1); }
    });
    refreshSelection();
  }

  Object.assign(root, { officekitBindScreenshotObjects: bindObjects, officekitRefreshScreenshotObjectSelection: refreshSelection,
    officekitSelectScreenshotObject: select,
    officekitScreenshotObjectBounds: objectBounds, officekitScreenshotEraserRemovals: eraserRemovals, officekitHitScreenshotObject: hitObject,
    officekitMoveScreenshotObject: moveObject, officekitResizeScreenshotObject: resizeObject, officekitScreenshotPathOperation: pathOperation });
})();
