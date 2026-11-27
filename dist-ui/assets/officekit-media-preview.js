/* Media Toolkit previews: thumbnails, a larger preview and an expanded viewer for images, PDFs, video and audio.
   Everything is drawn by the local sidecar from the granted file, fetched one at a time and kept in memory only;
   the original is never changed or uploaded. */
(() => {
  'use strict';
  const EXTENSIONS = {
    image: ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tif', 'tiff', 'gif', 'ico', 'heic', 'heif', 'avif', 'jxl'],
    pdf: ['pdf'],
    video: ['mp4', 'm4v', 'mov', 'mkv', 'webm', 'avi'],
    audio: ['mp3', 'm4a', 'aac', 'wav', 'aiff', 'aif', 'flac', 'caf', 'ogg', 'opus'],
  };
  const SIZES = { thumb: 128, large: 512, viewer: 2048 };
  const VIEWER_CACHE_LIMIT = 6;
  const DEFAULT_POSITION = 10;
  const MIN_SCALE = 0.05;
  const MAX_SCALE = 8;
  const NOTE = 'Preview only; the original is not changed';

  const extensionOf = name => {
    const text = String(name || '');
    return text.includes('.') ? text.split('.').pop().toLowerCase() : '';
  };
  const kindOf = name => Object.keys(EXTENSIONS).find(kind => EXTENSIONS[kind].includes(extensionOf(name))) || 'other';
  const formatDuration = seconds => {
    const total = Math.max(0, Math.round(seconds));
    const hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), rest = String(total % 60).padStart(2, '0');
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
  };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const icon = path => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'h-5 w-5 fill-none stroke-current'); svg.setAttribute('stroke-width', '1.6'); svg.setAttribute('aria-hidden', 'true');
    const shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    shape.setAttribute('d', path); svg.append(shape);
    return svg;
  };
  const FILE_ICON = 'M6 3h8l4 4v14H6zM14 3v4h4';
  const LOCK_ICON = 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z';

  // The sidecar answers with a typed body; anything that does not match is treated as "no preview".
  function parseBody(body, kind) {
    if (!body || body.kind !== kind) return null;
    const dimension = value => value === undefined || (Number.isInteger(value) && value >= 0 && value <= 40000);
    if (!dimension(body.width) || !dimension(body.height)) return null;
    if (body.durationSeconds !== undefined && !(Number.isFinite(body.durationSeconds) && body.durationSeconds > 0)) return null;
    if (body.pageCount !== undefined && !(Number.isInteger(body.pageCount) && body.pageCount >= 1)) return null;
    if (body.peaks !== undefined && !(Array.isArray(body.peaks) && body.peaks.length <= 256 && body.peaks.every(value => Number.isInteger(value) && value >= 0 && value <= 100))) return null;
    let src = null;
    if (body.dataBase64 !== undefined) {
      if (!['image/jpeg', 'image/png'].includes(body.contentType) || typeof body.dataBase64 !== 'string') return null;
      src = `data:${body.contentType};base64,${body.dataBase64}`;
    }
    if (kind !== 'audio' && !src) return null;
    if (kind === 'audio' && !src && !body.peaks) return null;
    return { kind, width: body.width, height: body.height, durationSeconds: body.durationSeconds, pageCount: body.pageCount, page: body.page, peaks: body.peaks, src };
  }

  function create({ apiFetch, getFiles, onChange }) {
    const entries = new Map();
    const pages = new Map();
    const queues = { background: Promise.resolve(), interactive: Promise.resolve() };
    let changeScheduled = false;
    const fileKey = file => `${file.selectionId}:${file.id}`;
    const entryKey = (file, size, page, position) => `${fileKey(file)}:${size}:${page}:${position}`;

    function scheduleChange() {
      if (changeScheduled) return;
      changeScheduled = true;
      requestAnimationFrame(() => { changeScheduled = false; onChange(); });
    }
    function trimViewerEntries() {
      const viewerKeys = [...entries.keys()].filter(key => key.split(':')[2] === String(SIZES.viewer));
      for (const key of viewerKeys.slice(0, Math.max(0, viewerKeys.length - VIEWER_CACHE_LIMIT))) entries.delete(key);
    }
    function request(file, size, { page = 1, position = DEFAULT_POSITION } = {}) {
      const kind = kindOf(file.name);
      const key = entryKey(file, size, kind === 'pdf' ? page : 1, kind === 'video' ? position : DEFAULT_POSITION);
      if (entries.has(key)) return entries.get(key);
      const entry = { status: 'loading' };
      let finish;
      entry.settled = new Promise(resolve => { finish = resolve; });
      entries.set(key, entry);
      if (size === SIZES.viewer) trimViewerEntries();
      const query = new URLSearchParams({ size: String(size) });
      if (kind === 'pdf') query.set('page', String(page));
      if (kind === 'video') query.set('position', String(position));
      const lane = size <= SIZES.thumb ? 'background' : 'interactive';
      queues[lane] = queues[lane].then(async () => {
        try {
          const response = await apiFetch(`/api/media-previews/${encodeURIComponent(file.selectionId)}/${encodeURIComponent(file.id)}?${query}`);
          const body = await response.json();
          if (body?.kind === 'pdf' && body.locked === true) { entry.status = 'locked'; return; }
          const parsed = parseBody(body, kind);
          if (!parsed) { entry.status = 'none'; return; }
          Object.assign(entry, parsed, { status: 'ready' });
        } catch { entry.status = 'none'; }
        finally { finish(); scheduleChange(); }
      });
      return entry;
    }
    const thumbEntry = file => kindOf(file.name) === 'other' ? { status: 'none' } : request(file, SIZES.thumb);

    function waveform(peaks, className, barClass) {
      const wrap = el('span', className);
      wrap.setAttribute('aria-hidden', 'true');
      for (const peak of peaks) { const bar = el('i', barClass); bar.style.height = `${Math.max(2, peak)}%`; wrap.append(bar); }
      return wrap;
    }
    function badge(text) {
      return el('span', 'absolute bottom-0.5 right-0.5 rounded bg-black/65 px-1 text-[9px] font-semibold leading-tight text-white', text);
    }
    function typeTile(file, entry) {
      const wrap = el('span', 'flex flex-col items-center gap-0.5');
      wrap.append(icon(entry.status === 'locked' ? LOCK_ICON : FILE_ICON), el('span', '', entry.status === 'locked' ? 'LOCKED' : (extensionOf(file.name).slice(0, 4).toUpperCase() || 'FILE')));
      return wrap;
    }
    function thumb(file) {
      const kind = kindOf(file.name);
      const entry = thumbEntry(file);
      const tile = el('span', 'relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-base-300 bg-base-300/40 text-center text-[10px] font-bold leading-tight tracking-wide text-base-content/70');
      tile.dataset.previewKind = kind; tile.dataset.previewStatus = entry.status;
      if (entry.status === 'ready') {
        if (entry.src) {
          const image = el('img', kind === 'pdf' ? 'h-full w-full bg-white object-cover object-top' : 'h-full w-full object-cover');
          image.src = entry.src; image.alt = ''; image.decoding = 'async'; tile.append(image);
        } else tile.append(waveform(entry.peaks, 'flex h-full w-full items-center gap-px px-1', 'block min-w-px flex-1 rounded-sm bg-sky-400'));
        if (kind === 'video') {
          const play = el('span', 'absolute inset-0 m-auto flex h-[18px] w-[18px] items-center justify-center rounded-full bg-black/55 pl-px text-[8px] text-white', '▶');
          play.setAttribute('aria-hidden', 'true'); tile.append(play);
        }
        if (entry.durationSeconds) tile.append(badge(formatDuration(entry.durationSeconds)));
        if (kind === 'pdf' && entry.pageCount) tile.append(badge(`${entry.pageCount} p`));
      } else if (entry.status !== 'loading') tile.append(typeTile(file, entry));
      return { tile, entry };
    }
    // Second line of a file row: size first, then whatever the preview learned about the file.
    function describe(file, entry, sizeText) {
      const kind = kindOf(file.name);
      if (entry.status === 'locked') return `${sizeText} · password protected`;
      if (entry.status === 'none') return kind === 'other' ? sizeText : `${sizeText} · preview unavailable`;
      if (entry.status !== 'ready') return sizeText;
      return [sizeText, detailText(kind, entry)].filter(Boolean).join(' · ');
    }
    function detailText(kind, entry) {
      if (kind === 'image') return `${entry.width} × ${entry.height} px`;
      if (kind === 'video') return `${entry.width} × ${entry.height} · ${formatDuration(entry.durationSeconds)}`;
      if (kind === 'audio') return formatDuration(entry.durationSeconds);
      return `${entry.pageCount} ${entry.pageCount === 1 ? 'page' : 'pages'}`;
    }

    const stageContent = (kind, entry, name, imageClass, waveClass) => {
      if (kind === 'audio' && !entry.src) return waveform(entry.peaks, waveClass, 'block min-w-px flex-1 rounded-sm bg-sky-400');
      const image = el('img', imageClass); image.src = entry.src; image.alt = `Preview of ${name}`; image.decoding = 'async';
      return image;
    };
    function renderPanel(panel, selectedId) {
      if (!panel) return;
      const candidates = getFiles().filter(file => kindOf(file.name) !== 'other');
      const file = candidates.find(item => item.id === selectedId) || candidates[0];
      panel.replaceChildren();
      if (!file) { panel.classList.add('hidden'); return; }
      const kind = kindOf(file.name);
      const page = pages.get(fileKey(file)) || 1;
      const entry = request(file, SIZES.large, { page });
      if (entry.status !== 'ready') { panel.classList.add('hidden'); return; }
      const stage = el('div', 'relative flex min-h-24 items-center justify-center rounded-lg bg-base-300/40 p-2');
      const content = stageContent(kind, entry, file.name, `max-h-56 w-full rounded-lg object-contain${kind === 'pdf' ? ' bg-white' : ''}`, 'flex h-24 w-full items-center gap-0.5 px-2');
      stage.append(content);
      if (kind === 'video') {
        const play = el('span', 'pointer-events-none absolute flex h-11 w-11 items-center justify-center rounded-full bg-black/55 pl-1 text-lg text-white', '▶');
        play.setAttribute('aria-hidden', 'true'); stage.append(play);
      }
      const expand = el('button', 'btn btn-xs absolute right-2 top-2 border-white/25 bg-black/55 text-white hover:bg-black/70', '⤢ Expand');
      expand.type = 'button'; expand.setAttribute('aria-label', `Expand preview of ${file.name}`); expand.dataset.previewExpand = file.id;
      expand.addEventListener('click', () => openViewer(file.id));
      stage.addEventListener('dblclick', () => openViewer(file.id));
      stage.append(expand);
      const caption = el('figcaption', 'mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-base-content/70');
      caption.append(el('span', 'min-w-0 break-all', `${file.name} · ${detailText(kind, entry)}`));
      if (kind === 'pdf' && entry.pageCount > 1) caption.append(pager(entry.pageCount, page, next => { pages.set(fileKey(file), next); onChange(); }, 'btn btn-ghost btn-xs'));
      caption.append(el('span', '', NOTE));
      panel.append(stage, caption); panel.classList.remove('hidden');
    }
    function pager(count, page, go, buttonClass) {
      const wrap = el('span', 'inline-flex items-center gap-1');
      const back = el('button', buttonClass, '‹'), next = el('button', buttonClass, '›');
      back.type = next.type = 'button'; back.setAttribute('aria-label', 'Previous page'); next.setAttribute('aria-label', 'Next page');
      back.disabled = page <= 1; next.disabled = page >= count;
      back.addEventListener('click', () => go(page - 1)); next.addEventListener('click', () => go(page + 1));
      wrap.append(back, el('span', 'tabular-nums', `${page} / ${count}`), next);
      return wrap;
    }

    // ----- Expanded viewer -----
    let closeViewer = null;
    function openViewer(startId) {
      if (closeViewer) closeViewer();
      const navigable = () => getFiles().filter(file => kindOf(file.name) !== 'other' && thumbEntry(file).status === 'ready');
      let list = navigable();
      let index = list.findIndex(file => file.id === startId);
      if (index < 0) return;
      const returnFocus = document.activeElement;
      const state = { page: 1, position: DEFAULT_POSITION, scale: 1, fit: 1, x: 0, y: 0, token: 0, fullscreen: false, image: null };

      const overlay = el('div', 'fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 p-4 sm:p-8');
      overlay.id = 'media-toolkit-viewer';
      const dialog = el('div', 'flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-white/15 bg-slate-950 text-slate-100 shadow-2xl');
      dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); dialog.tabIndex = -1;
      const bar = el('div', 'flex flex-wrap items-center gap-2 border-b border-white/15 bg-slate-900/95 px-3 py-2');
      const title = el('div', 'min-w-0 flex-1 truncate font-semibold');
      const detail = el('span', 'ml-2 text-xs font-normal text-slate-400');
      const group = () => el('div', 'flex items-center gap-0.5 rounded-lg border border-white/15 bg-white/5 p-0.5');
      const button = (label, text, extra = '') => {
        const node = el('button', `h-7 min-w-7 rounded-md bg-transparent px-2 text-xs font-semibold text-slate-100 hover:bg-white/10 disabled:opacity-40 ${extra}`, text);
        node.type = 'button'; node.setAttribute('aria-label', label); return node;
      };
      const zoomGroup = group(), zoomOut = button('Zoom out', '−'), zoomLevel = el('span', 'min-w-12 text-center text-xs text-slate-400'), zoomIn = button('Zoom in', '+'), fitButton = button('Fit to window', 'Fit'), actualButton = button('Actual size (100%)', '100%');
      zoomGroup.append(zoomOut, zoomLevel, zoomIn, fitButton, actualButton);
      const pageGroup = group(), positionGroup = group();
      const positionInput = el('input', 'w-32 accent-sky-400'); positionInput.type = 'range'; positionInput.min = '0'; positionInput.max = '100'; positionInput.step = '5'; positionInput.value = String(state.position); positionInput.setAttribute('aria-label', 'Frame position');
      const positionLabel = el('span', 'w-9 text-right text-xs text-slate-400');
      positionGroup.append(el('span', 'px-1 text-xs text-slate-400', 'Frame'), positionInput, positionLabel);
      const windowGroup = group(), fullButton = button('Full screen', '⤢ Full screen'), closeButton = button('Close preview', '✕');
      windowGroup.append(fullButton, closeButton);
      title.append(el('span', '', ''), detail);
      bar.append(title, zoomGroup, pageGroup, positionGroup, windowGroup);

      const stage = el('div', 'relative min-h-0 flex-1 touch-none select-none overflow-hidden bg-[#05080f]');
      const surface = el('div', 'absolute inset-0 flex items-center justify-center');
      const message = el('div', 'absolute inset-0 flex items-center justify-center text-sm text-slate-400');
      message.setAttribute('aria-live', 'polite');
      const previous = el('button', 'absolute left-3 top-1/2 z-10 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-white/25 bg-black/55 text-white hover:bg-black/70', '‹');
      const following = el('button', 'absolute right-3 top-1/2 z-10 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-white/25 bg-black/55 text-white hover:bg-black/70', '›');
      previous.type = following.type = 'button'; previous.setAttribute('aria-label', 'Previous file'); following.setAttribute('aria-label', 'Next file');
      stage.append(surface, message, previous, following);
      const foot = el('div', 'flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-white/15 bg-slate-900/95 px-3 py-2 text-xs text-slate-400');
      const hint = el('span'), keys = el('span');
      foot.append(hint, keys);
      dialog.append(bar, stage, foot); overlay.append(dialog); document.body.append(overlay);

      const current = () => list[index];
      const zoomable = () => ['image', 'pdf'].includes(kindOf(current().name));
      const apply = () => {
        if (!state.image) return;
        state.image.style.transform = `translate(-50%, -50%) translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
        zoomLevel.textContent = `${Math.round(state.scale * 100)}%`;
      };
      const computeFit = () => {
        const box = stage.getBoundingClientRect();
        const width = state.image?.naturalWidth || 1, height = state.image?.naturalHeight || 1;
        state.fit = Math.min(MAX_SCALE, box.width / width, box.height / height) || 1;
      };
      const fit = () => { computeFit(); state.scale = state.fit; state.x = 0; state.y = 0; apply(); };
      const setScale = (next, cx = 0, cy = 0) => {
        const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
        state.x = cx - (cx - state.x) * (scale / state.scale); state.y = cy - (cy - state.y) * (scale / state.scale);
        state.scale = scale; apply();
      };
      async function load() {
        const token = ++state.token;
        const file = current(), kind = kindOf(file.name);
        detail.textContent = '';
        title.firstChild.textContent = file.name;
        previous.hidden = following.hidden = list.length < 2;
        zoomGroup.hidden = !zoomable(); positionGroup.hidden = kind !== 'video'; pageGroup.hidden = kind !== 'pdf';
        positionLabel.textContent = `${state.position}%`;
        officekitOutcome.show(message, { state: 'working', text: 'Loading…' });
        const entry = request(file, SIZES.viewer, { page: state.page, position: state.position });
        await entry.settled;
        if (token !== state.token) return;
        surface.replaceChildren(); state.image = null;
        if (entry.status !== 'ready') { officekitOutcome.show(message, { state: 'info', text: entry.status === 'locked' ? 'This PDF is password protected.' : 'No preview is available for this file.' }); return; }
        officekitOutcome.show(message, { state: 'info', text: '' });
        state.pageCount = entry.pageCount || 1;
        const count = list.length > 1 ? ` · ${index + 1} of ${list.length}` : '';
        detail.textContent = `${detailText(kind, entry)}${count}`;
        pageGroup.replaceChildren(); if (kind === 'pdf') pageGroup.append(pager(entry.pageCount, state.page, next => { state.page = next; void load(); }, 'h-7 min-w-7 rounded-md px-2 text-xs font-semibold hover:bg-white/10 disabled:opacity-40'));
        if (zoomable()) {
          const image = stageContent(kind, entry, file.name, 'absolute left-1/2 top-1/2 max-w-none cursor-grab select-none', '');
          image.draggable = false; surface.className = 'absolute inset-0'; surface.append(image); state.image = image;
          const ready = () => {
            fit();
            const reduced = entry.width > 0 && image.naturalWidth > 0 && entry.width > image.naturalWidth + 1;
            hint.textContent = (reduced ? `Reduced copy of the original (up to ${SIZES.viewer} px). ` : '') + 'Scroll or pinch to zoom · drag to pan · double-click toggles Fit / 100%';
          };
          if (image.complete && image.naturalWidth) ready(); else image.addEventListener('load', ready, { once: true });
        } else {
          surface.className = 'absolute inset-0 flex flex-col items-center justify-center gap-4 p-4';
          surface.append(stageContent(kind, entry, file.name, 'max-h-full min-h-0 max-w-full rounded-lg object-contain', 'flex h-40 w-4/5 items-center gap-1'));
          if (kind === 'audio' && entry.src && entry.peaks) surface.append(waveform(entry.peaks, 'flex h-24 w-4/5 shrink-0 items-center gap-1', 'block min-w-px flex-1 rounded-sm bg-sky-400'));
          hint.textContent = kind === 'video' ? 'A still frame; drag the slider to choose another. Video is not played.' : 'Waveform of the whole file. Audio is not played.';
        }
        keys.textContent = `← → other files${kind === 'pdf' ? ' · PgUp PgDn pages' : ''}${zoomable() ? ' · + − 0 zoom' : ''} · F full screen · Esc close`;
      }
      const go = step => { if (list.length < 2) return; index = (index + step + list.length) % list.length; state.page = 1; state.position = DEFAULT_POSITION; positionInput.value = String(state.position); void load(); };
      const setFullscreen = async on => {
        state.fullscreen = on;
        overlay.className = `fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 ${on ? 'p-0' : 'p-4 sm:p-8'}`;
        dialog.className = `flex h-full w-full ${on ? '' : 'max-w-6xl rounded-2xl border '}flex-col overflow-hidden border-white/15 bg-slate-950 text-slate-100 shadow-2xl`;
        fullButton.textContent = on ? '⤡ Exit full screen' : '⤢ Full screen'; fullButton.setAttribute('aria-label', on ? 'Exit full screen' : 'Full screen');
        try {
          if (on && overlay.requestFullscreen) { await overlay.requestFullscreen(); state.nativeFullscreen = true; }
          else if (!on && document.fullscreenElement) await document.exitFullscreen();
        } catch { /* the window-filling layout still applies */ }
        if (zoomable() && state.image) fit();
      };
      // The user can leave native full screen with the system's own gesture; keep the layout in step.
      const onFullscreenChange = () => {
        if (state.fullscreen && state.nativeFullscreen && !document.fullscreenElement) { state.nativeFullscreen = false; void setFullscreen(false); }
      };
      const close = () => {
        document.removeEventListener('keydown', onKey, true); document.removeEventListener('fullscreenchange', onFullscreenChange); window.removeEventListener('resize', onResize);
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        overlay.remove(); closeViewer = null;
        // The preview panel redraws while the viewer is open, so look the button up again by file.
        const target = returnFocus?.isConnected ? returnFocus : [...document.querySelectorAll('[data-preview-expand]')].find(node => node.dataset.previewExpand === returnFocus?.dataset?.previewExpand);
        if (target && typeof target.focus === 'function') target.focus();
      };
      const onResize = () => { if (zoomable() && state.image) { const atFit = Math.abs(state.scale - state.fit) < 1e-6; computeFit(); if (atFit) fit(); } };
      function onKey(event) {
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const key = event.key;
        const handled = () => { event.preventDefault(); event.stopPropagation(); };
        if (key === 'Escape') { handled(); if (state.fullscreen) void setFullscreen(false); else close(); }
        else if (key === 'ArrowLeft') { handled(); go(-1); }
        else if (key === 'ArrowRight') { handled(); go(1); }
        else if (key === 'f' || key === 'F') { handled(); void setFullscreen(!state.fullscreen); }
        else if (key === 'PageDown' && !pageGroup.hidden) { handled(); if (state.page < state.pageCount) { state.page += 1; void load(); } }
        else if (key === 'PageUp' && !pageGroup.hidden) { handled(); if (state.page > 1) { state.page -= 1; void load(); } }
        else if (zoomable() && (key === '+' || key === '=')) { handled(); setScale(state.scale * 1.25); }
        else if (zoomable() && (key === '-' || key === '_')) { handled(); setScale(state.scale / 1.25); }
        else if (zoomable() && key === '0') { handled(); fit(); }
        else if (key === 'Tab') {
          const controls = [...dialog.querySelectorAll('button, input')].filter(node => !node.disabled && !node.closest('[hidden]') && node.offsetParent !== null);
          if (!controls.length) { handled(); return; }
          const first = controls[0], last = controls[controls.length - 1];
          if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { handled(); last.focus(); }
          else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { handled(); first.focus(); }
        }
      }
      document.addEventListener('keydown', onKey, true); document.addEventListener('fullscreenchange', onFullscreenChange); window.addEventListener('resize', onResize);
      closeViewer = close;
      closeButton.addEventListener('click', close);
      overlay.addEventListener('mousedown', event => { if (event.target === overlay) close(); });
      fullButton.addEventListener('click', () => void setFullscreen(!state.fullscreen));
      previous.addEventListener('click', () => go(-1)); following.addEventListener('click', () => go(1));
      zoomIn.addEventListener('click', () => setScale(state.scale * 1.25)); zoomOut.addEventListener('click', () => setScale(state.scale / 1.25));
      fitButton.addEventListener('click', fit); actualButton.addEventListener('click', () => { state.x = 0; state.y = 0; setScale(1); });
      positionInput.addEventListener('input', () => { positionLabel.textContent = `${positionInput.value}%`; });
      positionInput.addEventListener('change', () => { state.position = Number(positionInput.value); void load(); });
      stage.addEventListener('wheel', event => {
        if (!zoomable() || !state.image) return;
        event.preventDefault();
        const box = stage.getBoundingClientRect();
        setScale(state.scale * Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015)), event.clientX - box.left - box.width / 2, event.clientY - box.top - box.height / 2);
      }, { passive: false });
      stage.addEventListener('dblclick', event => {
        if (!zoomable() || !state.image) return;
        const box = stage.getBoundingClientRect();
        if (Math.abs(state.scale - state.fit) < 1e-6) setScale(1, event.clientX - box.left - box.width / 2, event.clientY - box.top - box.height / 2); else fit();
      });
      let drag = null;
      stage.addEventListener('pointerdown', event => {
        if (!zoomable() || !state.image || event.button !== 0 || event.target.closest('button')) return;
        drag = { id: event.pointerId, x: event.clientX - state.x, y: event.clientY - state.y }; stage.setPointerCapture(event.pointerId);
      });
      stage.addEventListener('pointermove', event => { if (drag && drag.id === event.pointerId) { state.x = event.clientX - drag.x; state.y = event.clientY - drag.y; apply(); } });
      const endDrag = event => { if (drag && drag.id === event.pointerId) drag = null; };
      stage.addEventListener('pointerup', endDrag); stage.addEventListener('pointercancel', endDrag);
      dialog.setAttribute('aria-label', 'Preview viewer');
      dialog.focus();
      void load();
    }

    return {
      thumb, describe, renderPanel, openViewer,
      clear() { entries.clear(); pages.clear(); },
      close() { if (closeViewer) closeViewer(); },
    };
  }

  window.officekitMediaPreview = { create, kindOf, formatDuration };
})();
