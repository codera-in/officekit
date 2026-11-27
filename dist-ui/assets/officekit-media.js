/* Shared local media workbench: native file authority, typed jobs, private artifacts. */
(() => {
  'use strict';
  const kinds = ['image', 'video', 'pdf', 'audio'];
  const mediaTypeForName = name => {
    const extension = String(name || '').split('.').pop()?.toLowerCase();
    if (['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tif', 'tiff', 'heic', 'heif', 'avif', 'jxl', 'ico'].includes(extension)) return 'image/unknown';
    if (['mov', 'mp4', 'm4v', 'mkv', 'webm', 'avi'].includes(extension)) return 'video/unknown';
    if (extension === 'pdf') return 'application/pdf';
    if (['wav', 'mp3', 'm4a', 'aif', 'aiff', 'flac', 'caf'].includes(extension)) return 'audio/unknown';
    return '';
  };
  const mediaTypeMatchesKind = (kind, type) => kind === 'image' ? type?.startsWith('image/')
    : kind === 'video' ? type?.startsWith('video/') : kind === 'audio' ? type?.startsWith('audio/') : type === 'application/pdf';
  const defaults = {
    'image-optimize': { quality: 82, preserveMetadata: false },
    'image-fit-size': { targetBytes: 2097152, targetFormat: 'webp', minQuality: 30, maxQuality: 90 },
    'image-convert': { targetFormat: 'webp', quality: 90 },
    'image-resize': { maxWidth: 1600, maxHeight: 1600 },
    'image-crop': { x: 0, y: 0, width: 1000, height: 1000 },
    'image-strip-metadata': {},
    'image-watermark': { text: 'OfficeKit', opacity: 70, position: 'bottom-right' },
    'image-watermark-overlay': { placement: 'bottom-right', marginPercent: 4, sizePercent: 18, opacityPercent: 72 },
    'video-watermark-overlay': { placement: 'bottom-right', marginPercent: 4, sizePercent: 18, opacityPercent: 72 },
    'video-optimize': { targetFormat: 'm4v', quality: 'balanced' },
    'video-hevc-convert': {},
    'video-fit-size': { targetFormat: 'm4v', targetBytes: 20971520, quality: 'balanced' },
    'video-crop': { x: 0, y: 0, width: 1280, height: 720 },
    'video-resize': { maxWidth: 1280, maxHeight: 720 },
    'video-speed': { factorPercent: 100 }, 'video-mute': {},
    'video-to-gif': { fps: 15, maxWidth: 720, maxDurationSeconds: 30 },
    'pdf-lossless-compress': { profile: 'balanced' },
    'pdf-visual-optimize': { quality: 75, dpi: 150 },
    'pdf-fit-size': { targetBytes: 10485760, quality: 75, dpi: 150 },
    'pdf-crop': { pageSize: 'a4' },
    'audio-optimize': { targetFormat: 'm4a', bitrateKbps: 192 },
    'audio-convert': { targetFormat: 'm4a', bitrateKbps: 192 },
    'audio-fit-size': { targetBytes: 10485760, targetFormat: 'm4a', bitrateKbps: 192 },
    'audio-normalize': { targetLufs: -14 }, 'audio-artwork': { maxEdge: 1024 },
  };
  const settingLabels = {
    quality: 'Quality', preserveMetadata: 'Keep metadata', targetBytes: 'Target size (MiB)', targetFormat: 'Output format',
    minQuality: 'Minimum quality', maxQuality: 'Maximum quality', maxWidth: 'Maximum width (px)', maxHeight: 'Maximum height (px)',
    x: 'Left (px)', y: 'Top (px)', width: 'Width (px)', height: 'Height (px)', text: 'Watermark text', opacity: 'Opacity (%)',
    position: 'Position', bitrateKbps: 'Audio bitrate (kbps)', factorPercent: 'Speed (%)', fps: 'Frames per second',
    maxDurationSeconds: 'Maximum duration (seconds)', profile: 'Compression profile', dpi: 'Resolution (DPI)', pageSize: 'Page size',
    targetLufs: 'Loudness (LUFS)', maxEdge: 'Maximum artwork edge (px)', placement: 'Placement', marginPercent: 'Margin (%)', sizePercent: 'Logo size (%)', opacityPercent: 'Opacity (%)',
  };
  const choicesFor = (key, operationId) => {
    if (key === 'targetFormat') {
      if (operationId.startsWith('image-')) {
        const advertised = operationById(operationId)?.formats;
        if (Array.isArray(advertised)) {
          const normalized = advertised.map(format => ({ jpg: 'jpeg', tif: 'tiff' })[format] || format);
          const allowed = operationId === 'image-fit-size' ? ['jpeg', 'webp', 'png', 'avif', 'jxl'] : ['png', 'jpeg', 'webp', 'bmp', 'tiff', 'ico', 'pdf', 'avif', 'jxl'];
          return [...new Set(normalized.filter(format => allowed.includes(format)))];
        }
        return operationId === 'image-fit-size' ? ['jpeg', 'webp', 'png'] : ['png', 'jpeg', 'webp', 'bmp', 'tiff', 'ico', 'pdf'];
      }
      return operationById(operationId)?.formats || [];
    }
    if (key === 'quality' && typeof defaults[operationId]?.quality === 'string') return ['smaller', 'balanced', 'higher'];
    if (key === 'position') return ['top-left', 'top-right', 'center', 'bottom-left', 'bottom-right'];
    if (key === 'placement') return ['top-left', 'top-right', 'center', 'bottom-left', 'bottom-right', 'tile'];
    if (key === 'profile') return ['fast', 'balanced', 'maximum'];
    if (key === 'pageSize') return ['a4', 'letter', 'mobile', 'tablet'];
    return null;
  };
  const boundsFor = (key, operationId) => {
    const bounds = {
      quality: [1, 100, 1], minQuality: [1, 100, 1], maxQuality: [1, 100, 1], opacity: [1, 100, 1],
      maxWidth: [1, 10000, 1], maxHeight: [1, 10000, 1], x: [0, 40000, 1], y: [0, 40000, 1],
      width: [1, 40000, 1], height: [1, 40000, 1], factorPercent: [25, 400, 1], fps: [1, 60, 1],
      maxDurationSeconds: [1, 60, 1], bitrateKbps: [32, 640, 1], dpi: [72, 300, 1],
      targetLufs: [-24, -5, 0.1], maxEdge: [64, 4096, 1], targetBytes: [1 / 1048576, 32768, 'any'],
      marginPercent: [0, 20, 1], sizePercent: [5, 60, 1], opacityPercent: [10, 100, 1],
    };
    if (key === 'maxWidth' && operationId === 'video-to-gif') return [16, 1920, 1];
    if (key === 'maxHeight') return [1, 10000, 1];
    return bounds[key] || null;
  };
  const $ = id => document.getElementById(`media-toolkit-${id}`);
  const state = { capabilities: null, selection: null, selections: [], files: [], importPreview: null, stagedImage: null, jobId: null, running: false, pipelines: [], draftSteps: [], activePipeline: null, localDefaults: {}, folderWatches: [], presetZones: [] };
  state.kindDrafts = {};
  state.editingKind = 'image';
  state.watermark = null;
  state.previewFileId = null;
  state.handoffs = null;
  state.lastItems = [];
  state.retainedItems = [];
  state.saveOutcomes = new Map();
  const kindForFile = file => kinds.find(kind => mediaTypeMatchesKind(kind, file.media_type));
  function rememberSettings() {
    if (state.activePipeline) return;
    state.kindDrafts[state.editingKind] = { operationId: $('operation').value, options: readOptions() };
  }
  function operationsForFile(file) {
    if (state.activePipeline) return state.activePipeline.operations;
    const kind = kindForFile(file);
    const draft = state.kindDrafts[kind];
    if (draft) return [draft];
    const fallback = state.capabilities?.media.find(media => media.id === kind)?.operations.find(operation => operation.available);
    if (!fallback) throw Error(`No local operation is available for ${file.name}.`);
    return [{ operationId: fallback.id, options: state.localDefaults[fallback.id] || defaults[fallback.id] || {} }];
  }
  let initPromise = null;
  let mediaDropQueue = Promise.resolve();
  let syncMediaDrop = () => {};
  const apiFetch = (path, options) => window.officekitDirectFetch(path, options);
  let clipboardLoop = null;
  let clipboardRevision = null;
  let bypassClipboardOnce = false;
  let clipboardProcessing = false;
  const status = (message, state = 'info', recovery = '') => { officekitOutcome.show($('status'), { state, text: message, recovery }); syncNext(); };
  // The step strip and the highlighted "Next" panel always say what to do now.
  function syncNext() {
    const panel = $('next'), action = $('next-action');
    if (!panel || !action) return;
    const hasInput = state.files.some(file => file.checked !== false) || Boolean(state.importPreview || state.stagedImage);
    const finished = !state.running && state.finished && state.lastItems?.length > 0;
    const set = (mode, title, detail, label, disabled) => {
      panel.dataset.state = mode; action.dataset.mode = mode;
      $('next-title').textContent = title; $('next-detail').textContent = detail;
      action.textContent = label; action.disabled = disabled;
    };
    const total = state.files.filter(file => file.checked !== false).length + (state.importPreview ? 1 : 0) + (state.stagedImage ? 1 : 0);
    const missingArtifact = finished ? state.lastItems.find(item => item.state === 'ready' && item.artifactId && state.saveOutcomes.get(item.artifactId)?.state === 'missing' && state.files.some(file => file.id === item.fileId)) : null;
    if (state.running) set('running', 'Running…', $('status').textContent, 'Cancel', false);
    else if (finished) {
      const ready = state.lastItems.filter(item => item.state === 'ready').length;
      set('done', missingArtifact ? `${missingArtifact.name} needs a new copy` : ready ? `${ready} ${ready === 1 ? 'result' : 'results'} ready` : 'Nothing was prepared', missingArtifact ? 'Its prepared copy is unavailable. Run this file again to create a fresh copy.' : ready ? 'Save puts each result where you choose. Originals are unchanged.' : 'Review each file result under Recent results.', 'Show results', false);
    } else if (!hasInput) set('empty', 'Next: choose files', 'Drop them anywhere on this screen, or use Choose files below.', 'Run', true);
    else set('ready', `Ready: ${total} ${total === 1 ? 'file' : 'files'} → ${activeOperation()?.label || 'choose an operation'}`, `Press ${runLabel(total)} below. Your original stays as it is; the result is a new file.`, 'Run', $('run').disabled);
    const current = state.running || finished ? '3' : hasInput ? '3' : '1';
    for (const item of $('steps').children) {
      const step = item.dataset.step;
      item.dataset.status = step === current ? 'current' : step < current ? 'done' : 'todo';
      if (item.dataset.status === 'done') item.firstElementChild.textContent = '✓';
      else item.firstElementChild.textContent = step;
    }
    // The bar never shows more than three buttons: what it offers depends on where the job is.
    const readyCount = finished ? state.lastItems.filter(item => item.state === 'ready' && item.artifactId && !['saved', 'download-started', 'missing'].includes(state.saveOutcomes.get(item.artifactId)?.state)).length : 0;
    const retryName = missingArtifact ? (state.files.find(file => file.id === missingArtifact.fileId)?.name || missingArtifact.name) : '';
    $('run').textContent = finished ? missingArtifact ? `Retry ${retryName}` : `${runLabel(total)} again` : runLabel(total);
    $('select').hidden = finished;
    $('select').setAttribute('aria-disabled', String(state.running));
    $('run').hidden = state.running;
    $('cancel').hidden = !state.running;
    $('reset').hidden = !finished;
    $('save').hidden = !finished || !readyCount;
    $('save').textContent = readyCount > 1 ? 'Save all' : 'Save';
  }
  // The main button names what will happen to what: "Optimize 1 image", not "Prepare copies".
  function runLabel(total) {
    const label = activeOperation()?.label || '';
    const count = Math.max(total, 1);
    const match = label.match(/^(\S+)\s+(image|video|audio|PDF|file|document)s?$/i);
    if (match) return `${match[1]} ${count} ${match[2]}${count === 1 ? '' : 's'}`;
    return label ? `${label} · ${count} ${count === 1 ? 'file' : 'files'}` : 'Run';
  }
  async function saveReady() {
    const ready = (state.lastItems || []).filter(item => item.state === 'ready' && item.artifactId && !['saved', 'download-started', 'missing'].includes(state.saveOutcomes.get(item.artifactId)?.state));
    for (const item of ready) {
      try {
        const blob = await fetchArtifactBlob(item.artifactId, 'The result could not be saved.');
        const outcome = await window.officekitDownloadResultBlob(blob, item.outputName);
        if (outcome?.state === 'cancelled') { status(`Save cancelled for ${item.outputName}. No copy was saved.`, 'info'); return; }
        if (!['saved', 'download-started'].includes(outcome?.state)) { status('The result was not saved. Choose a destination and try again.', 'error'); return; }
        state.saveOutcomes.set(item.artifactId, { state: outcome.state });
        renderResults(state.lastItems);
        status(`${outcome.state === 'saved' ? 'Saved' : 'Download started for'} ${item.outputName}.`, 'success');
      } catch (error) {
        if (error?.code === 'MEDIA_ARTIFACT_UNAVAILABLE') {
          state.saveOutcomes.set(item.artifactId, { state: 'missing' });
          renderResults(state.lastItems);
          const complete = state.lastItems.filter(row => ['saved', 'download-started'].includes(state.saveOutcomes.get(row.artifactId)?.state)).length;
          const total = state.lastItems.filter(row => row.state === 'ready' && row.artifactId).length;
          status(`${complete} of ${total} copies saved. ${item.outputName} is no longer available.`, 'error');
        } else status(error.message || 'The result could not be saved.', 'error');
        return;
      }
    }
  }
  async function saveOne(item) {
    try {
      const blob = await fetchArtifactBlob(item.artifactId, 'The prepared copy could not be saved.');
      const outcome = await window.officekitDownloadResultBlob(blob, item.outputName);
      if (outcome?.state === 'cancelled') { status(`Save cancelled for ${item.outputName}. No copy was saved.`, 'info'); return; }
      if (!['saved', 'download-started'].includes(outcome?.state)) { status('The result was not saved. Choose a destination and try again.', 'error'); return; }
      state.saveOutcomes.set(item.artifactId, { state: outcome.state });
      renderResults(state.lastItems);
      status(`${outcome.state === 'saved' ? 'Saved' : 'Download started for'} ${item.outputName}.`, 'success');
    } catch (error) {
      if (error?.code === 'MEDIA_ARTIFACT_UNAVAILABLE') {
        state.saveOutcomes.set(item.artifactId, { state: 'missing' });
        renderResults(state.lastItems);
        status(`${item.outputName} is no longer available. Run this file again to create a fresh copy.`, 'error');
      } else status(error.message || 'The prepared copy could not be saved.', 'error');
    }
  }
  async function fetchArtifactBlob(artifactId, failureMessage) {
    const response = await apiFetch(`/api/media-artifacts/${artifactId}`);
    if (!response.ok) {
      const error = Error(failureMessage);
      if ([404, 410].includes(response.status)) error.code = 'MEDIA_ARTIFACT_UNAVAILABLE';
      throw error;
    }
    return response.blob();
  }
  function activeOperation() {
    return state.capabilities?.media.flatMap(media => media.operations).find(operation => operation.id === $('operation').value) || null;
  }
  function operationById(id) {
    return state.capabilities?.media.flatMap(media => media.operations).find(operation => operation.id === id) || null;
  }
  function selectedOperations() {
    if (state.activePipeline) return state.activePipeline.operations;
    return [{ operationId: activeOperation()?.id, options: JSON.parse($('options').value || '{}') }];
  }
  function validLocalDefault(operationId, options) {
    const template = defaults[operationId];
    if (!template || !options || Array.isArray(options) || typeof options !== 'object') return false;
    if (Object.keys(options).some(key => !Object.hasOwn(template, key))) return false;
    return Object.entries(options).every(([key, value]) => {
      const expected = template[key];
      if (typeof value !== typeof expected) return false;
      const choices = choicesFor(key, operationId);
      if (choices && !choices.includes(value)) return false;
      const bounds = boundsFor(key, operationId);
      if (typeof value === 'number' && !Number.isFinite(value)) return false;
      if (typeof value === 'number' && bounds && key !== 'targetBytes' && (value < Number(bounds[0]) || value > Number(bounds[1]) || (Number(bounds[2]) === 1 && !Number.isInteger(value)))) return false;
      if (key === 'targetBytes' && (!Number.isSafeInteger(value) || value < 1 || value > 34359738368)) return false;
      if (key === 'text' && (value.length < 1 || value.length > 256)) return false;
      return true;
    });
  }
  async function loadLocalDefaults() {
    const response = await apiFetch('/api/media-operation-defaults');
    if (!response.ok) throw Error('Saved operation defaults could not be loaded.');
    const saved = await response.json();
    if (!saved || Array.isArray(saved) || typeof saved !== 'object') throw Error('Saved operation defaults are invalid.');
    state.localDefaults = Object.fromEntries(Object.entries(saved).filter(([id, options]) => validLocalDefault(id, options)));
  }
  function renderLocalDefaults() {
    const root = $('local-default-list');
    if (!root || !state.capabilities) return;
    const query = $('local-default-search').value.trim().toLocaleLowerCase();
    root.replaceChildren();
    const operations = state.capabilities.media.flatMap(media => media.operations.map(operation => ({ media, operation })))
      .filter(({ media, operation }) => `${media.label} ${operation.label} ${operation.id}`.toLocaleLowerCase().includes(query));
    if (!operations.length) {
      const empty = document.createElement('li'); empty.className = 'text-sm text-base-content/60'; empty.textContent = 'No matching operation settings.'; root.append(empty); return;
    }
    for (const { media, operation } of operations) {
      const item = document.createElement('li'); item.className = 'flex flex-wrap items-center justify-between gap-2 rounded-lg border border-base-300 p-3';
      const description = document.createElement('div');
      const title = document.createElement('strong'); title.className = 'block text-sm'; title.textContent = `${media.label} · ${operation.label}`;
      const detail = document.createElement('span'); detail.className = 'block text-xs text-base-content/60';
      detail.textContent = state.localDefaults[operation.id] ? `Saved local default · ${Object.keys(state.localDefaults[operation.id]).length} settings` : 'Built-in defaults';
      description.append(title, detail);
      const use = document.createElement('button'); use.type = 'button'; use.className = 'btn btn-outline btn-sm'; use.textContent = 'Use settings'; use.disabled = !operation.available;
      use.addEventListener('click', async () => {
        await window.officekitMediaToolkit.setOperation(operation.id);
        $('tab-prepare').click();
      });
      item.append(description, use); root.append(item);
    }
  }
  async function storeCurrentLocalDefault() {
    const operation = activeOperation();
    if (!operation?.available || state.activePipeline || !syncSettingsFromForm()) return;
    const options = readOptions();
    if (!validLocalDefault(operation.id, options)) { officekitOutcome.show($('local-default-status'), { state: 'error', text: 'These settings do not match the operation’s typed fields.' }); return; }
    try {
      const response = await apiFetch(`/api/media-operation-defaults/${encodeURIComponent(operation.id)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ options }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(payload.detail || 'The operation default could not be saved.');
      state.localDefaults[operation.id] = payload.options;
      officekitOutcome.show($('local-default-status'), { state: 'success', text: `Saved a local default for ${operation.label}. No files or media are stored.` });
      renderLocalDefaults();
    } catch (error) {
      officekitOutcome.show($('local-default-status'), { state: 'error', text: error.message || 'The operation default could not be saved.' });
    }
  }
  async function clearLocalDefaults() {
    try {
      const response = await apiFetch('/api/media-operation-defaults', { method: 'DELETE' });
      if (!response.ok) throw Error('Saved operation defaults could not be cleared.');
      state.localDefaults = {};
      officekitOutcome.show($('local-default-status'), { state: 'success', text: 'Saved operation defaults cleared.' });
      renderLocalDefaults();
    } catch (error) { officekitOutcome.show($('local-default-status'), { state: 'error', text: error.message || 'Saved operation defaults could not be cleared.' }); }
  }
  function readOptions() {
    const options = JSON.parse($('options').value || '{}');
    if (!options || Array.isArray(options) || typeof options !== 'object') throw Error('Invalid operation settings');
    return options;
  }
  function resultFormatTarget() {
    if (state.activePipeline) {
      for (let index = state.activePipeline.operations.length - 1; index >= 0; index -= 1) {
        const step = state.activePipeline.operations[index];
        if (typeof step.options?.targetFormat === 'string' && choicesFor('targetFormat', step.operationId)) return { step, operationId: step.operationId };
      }
      return null;
    }
    const operationId = activeOperation()?.id || '';
    let options;
    try { options = readOptions(); } catch { return null; }
    return typeof options.targetFormat === 'string' && choicesFor('targetFormat', operationId)
      ? { options, operationId }
      : null;
  }
  function renderFormatBar() {
    const bar = $('format-bar');
    const select = $('result-format');
    if (!bar || !select) return;
    const target = resultFormatTarget();
    if (!target) { bar.classList.add('hidden'); return; }
    const choices = choicesFor('targetFormat', target.operationId);
    // A JPEG batch does not offer JPEG as a convert target: converting JPEG to JPEG is not a conversion.
    const inputExtensions = new Set(state.files.map(file => String(file.name || '').split('.').pop()?.toLowerCase()));
    const allJpeg = inputExtensions.size > 0 && [...inputExtensions].every(extension => extension === 'jpg' || extension === 'jpeg');
    const offered = choices?.filter(format => !(allJpeg && format === 'jpeg')) ?? [];
    if (!offered.length) { bar.classList.add('hidden'); return; }
    select.replaceChildren();
    for (const format of offered) {
      const option = document.createElement('option'); option.value = format; option.textContent = format.toUpperCase(); select.append(option);
    }
    const selected = target.step?.options.targetFormat ?? target.options.targetFormat;
    select.value = offered.includes(selected) ? selected : offered[0];
    bar.classList.remove('hidden');
    bar.classList.add('flex');
  }
  function setResultFormat(format) {
    if (!state.activePipeline && !syncSettingsFromForm()) return;
    const target = resultFormatTarget();
    if (!target || !choicesFor('targetFormat', target.operationId).includes(format)) return;
    if (target.step) target.step.options.targetFormat = format;
    else {
      target.options.targetFormat = format;
      $('options').value = JSON.stringify(target.options, null, 2);
    }
    renderSettings();
  }
  function renderSettings() {
    const root = $('settings-fields');
    if (!root) return;
    let values;
    try { values = readOptions(); } catch { root.replaceChildren(); renderFormatBar(); return; }
    const operationId = activeOperation()?.id || '';
    $('watermark-controls').hidden = !operationId.endsWith('watermark-overlay');
    root.replaceChildren();
    for (const [key, raw] of Object.entries(values)) {
      if (key === 'targetFormat') continue;
      const label = document.createElement('label'); label.className = 'form-control w-full gap-1';
      const caption = document.createElement('span'); caption.className = 'label-text text-xs font-semibold'; caption.textContent = settingLabels[key] || key;
      let input;
      if (typeof raw === 'boolean') { input = document.createElement('input'); input.type = 'checkbox'; input.className = 'toggle toggle-primary'; input.checked = raw; label.classList.add('flex', 'items-center', 'justify-between', 'gap-3'); }
      else if (choicesFor(key, operationId) && typeof raw === 'string') {
        input = document.createElement('select'); input.className = 'select select-bordered select-sm w-full';
        for (const choice of choicesFor(key, operationId)) { const option = document.createElement('option'); option.value = choice; option.textContent = choice.toUpperCase(); input.append(option); }
        input.value = String(raw);
      } else {
        input = document.createElement('input'); input.className = 'input input-bordered input-sm w-full'; input.type = typeof raw === 'number' ? 'number' : 'text';
        const bounds = boundsFor(key, operationId);
        if (key === 'targetBytes') input.value = String(raw / 1048576);
        else input.value = String(raw);
        if (bounds) [input.min, input.max, input.step] = bounds.map(String);
        if (key === 'text') { input.required = true; input.maxLength = 256; }
      }
      input.dataset.optionKey = key; label.append(caption, input); root.append(label);
    }
    renderFormatBar();
  }
  function syncSettingsFromForm() {
    const values = readOptions();
    for (const input of $('settings-fields').querySelectorAll('[data-option-key]')) {
      const key = input.dataset.optionKey;
      values[key] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
      if (key === 'targetBytes') values[key] = Math.max(1, Math.round(Number(input.value) * 1048576));
    }
    const minQuality = $('settings-fields').querySelector('[data-option-key="minQuality"]');
    const maxQuality = $('settings-fields').querySelector('[data-option-key="maxQuality"]');
    const invalidOrder = minQuality && maxQuality && Number(minQuality.value) > Number(maxQuality.value);
    if (minQuality) minQuality.setCustomValidity(invalidOrder ? 'Minimum quality cannot exceed maximum quality.' : '');
    if (maxQuality) maxQuality.setCustomValidity(invalidOrder ? 'Maximum quality must be at least the minimum quality.' : '');
    const invalidField = [...$('settings-fields').querySelectorAll('input')].find(input => !input.checkValidity());
    const error = $('settings-error');
    error.hidden = !invalidField;
    error.textContent = invalidField ? invalidField.validationMessage : '';
    $('options').value = JSON.stringify(values, null, 2);
    return !invalidField;
  }
  function selectedOperationsAvailable() {
    try { return selectedOperations().every(step => operationById(step.operationId)?.available === true); }
    catch { return false; }
  }
  function renderPipelineDraft() {
    const list = $('pipeline-draft'); list.replaceChildren();
    state.draftSteps.forEach((step, index) => {
      const item = document.createElement('li'); item.className = 'flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 p-2';
      const label = document.createElement('span'); label.textContent = `${index + 1}. ${operationById(step.operationId)?.label || step.operationId}`;
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-ghost btn-xs'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove step ${index + 1}`);
      remove.addEventListener('click', () => { state.draftSteps.splice(index, 1); renderPipelineDraft(); });
      item.append(label, remove); list.append(item);
    });
    $('pipeline-save').disabled = !state.draftSteps.length || !state.capabilities || state.draftSteps.some(step => !operationById(step.operationId)?.available);
  }
  function renderPipelines() {
    const list = $('pipeline-list'); if (!list) return; list.replaceChildren();
    for (const pipeline of state.pipelines) {
      const item = document.createElement('li'); item.className = 'flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-3';
      const details = document.createElement('div'); details.className = 'min-w-0 flex-1';
      const title = document.createElement('strong'); title.className = 'block text-sm'; title.textContent = pipeline.name;
      const summary = document.createElement('span'); summary.className = 'block text-xs text-slate-500';
      const naming = pipeline.outputNameTemplate ? ` · ${pipeline.outputNameTemplate}` : ' · numbered copy';
      summary.textContent = `${pipeline.media.toUpperCase()} · ${pipeline.operations.map(step => operationById(step.operationId)?.label || step.operationId).join(' → ')}${naming}`;
      details.append(title, summary);
      const actions = document.createElement('div'); actions.className = 'flex gap-2';
      const use = document.createElement('button'); use.type = 'button'; use.className = 'btn btn-outline btn-sm'; use.textContent = state.activePipeline?.id === pipeline.id ? 'Selected' : 'Use pipeline';
      const available = pipeline.operations.every(step => operationById(step.operationId)?.available === true);
      use.disabled = !available || state.running;
      use.addEventListener('click', () => {
        state.activePipeline = JSON.parse(JSON.stringify(pipeline));
        $('kind').value = pipeline.media;
        renderOperations();
        $('operation').value = pipeline.operations[0].operationId;
        $('options').value = JSON.stringify(pipeline.operations[0].options, null, 2);
        officekitOutcome.show($('pipeline-status'), { state: 'info', text: `“${pipeline.name}” selected. It runs locally and remains paused for automatic triggers.` });
        renderPipelines(); renderFiles();
      });
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-ghost btn-sm'; remove.textContent = 'Delete';
      remove.addEventListener('click', () => { void deletePipeline(pipeline.id); });
      actions.append(use, remove); item.append(details, actions);
      const stateTag = document.createElement('span'); stateTag.className = 'badge badge-ghost badge-sm'; stateTag.textContent = 'Paused'; details.append(stateTag);
      list.append(item);
    }
  }
  async function loadPipelines() {
    try { state.pipelines = await (await apiFetch('/api/media-pipelines')).json(); renderPipelines(); renderFolderWatches(); }
    catch (error) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: error.message || 'Saved pipelines could not be loaded.' }); }
    renderPresetZones();
  }
  function renderPresetZones() {
    const select = $('zone-pipeline'), add = $('zone-create'), list = $('zone-list');
    if (!select || !add || !list) return;
    const previous = select.value;
    select.replaceChildren(new Option('Choose a saved pipeline', ''));
    const ready = state.pipelines.filter(pipeline => pipeline.operations.every(step => operationById(step.operationId)?.available === true));
    for (const pipeline of ready) select.add(new Option(`${pipeline.name} · ${pipeline.media.toUpperCase()}`, pipeline.id));
    if (ready.some(pipeline => pipeline.id === previous)) select.value = previous;
    add.disabled = !select.value || !window.officekitDirectFetch;
    list.replaceChildren();
    for (const zone of state.presetZones) {
      const pipeline = state.pipelines.find(item => item.id === zone.pipelineId);
      const item = document.createElement('li'); item.className = 'rounded-lg border border-base-300 bg-base-100 p-3';
      const heading = document.createElement('div'); heading.className = 'flex flex-wrap items-center justify-between gap-2';
      const title = document.createElement('strong'); title.className = 'text-sm'; title.textContent = zone.name;
      const badge = document.createElement('span'); badge.className = `badge badge-sm ${zone.enabled ? 'badge-success badge-outline' : 'badge-ghost'}`; badge.textContent = zone.enabled ? 'Enabled · this session' : 'Off';
      heading.append(title, badge);
      const description = document.createElement('p'); description.className = 'mt-1 text-xs text-base-content/70'; description.textContent = pipeline ? `${pipeline.name} · ${pipeline.media.toUpperCase()}` : 'Saved pipeline is unavailable.';
      const dropTarget = document.createElement('div'); dropTarget.dataset.zoneId = zone.id; dropTarget.className = `mt-2 rounded-md border border-dashed px-3 py-2 text-xs ${zone.enabled && pipeline ? 'border-primary bg-primary/5 text-base-content' : 'border-base-300 text-base-content/50'}`; dropTarget.textContent = zone.enabled && pipeline ? 'Drop supported files here to prepare copies automatically' : 'Enable this zone to accept files';
      const actions = document.createElement('div'); actions.className = 'mt-2 flex flex-wrap gap-2';
      const loadPipeline = () => { state.activePipeline = JSON.parse(JSON.stringify(pipeline)); $('kind').value = pipeline.media; renderOperations(); $('operation').value = pipeline.operations[0].operationId; $('options').value = JSON.stringify(pipeline.operations[0].options, null, 2); renderPipelines(); renderFiles(); };
      const use = document.createElement('button'); use.type = 'button'; use.className = 'btn btn-xs'; use.textContent = 'Use preset'; use.disabled = !pipeline || state.running;
      use.addEventListener('click', () => { if (!pipeline) return; loadPipeline(); officekitOutcome.show($('pipeline-status'), { state: 'info', text: `“${pipeline.name}” loaded from preset “${zone.name}”. Choose files and prepare copies.` }); $('tab-prepare').click(); });
      const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'btn btn-xs btn-outline'; toggle.textContent = zone.enabled ? 'Turn off' : 'Enable for session';
      toggle.disabled = !pipeline || !pipeline.operations.every(step => operationById(step.operationId)?.available === true) || state.running;
      toggle.addEventListener('click', () => { void updatePresetZone(zone.id, !zone.enabled); });
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-xs btn-ghost'; remove.textContent = 'Remove'; remove.addEventListener('click', () => { void deletePresetZone(zone.id); });
      actions.append(use, toggle, remove); item.append(heading, description, dropTarget, actions); list.append(item);
    }
    if (!state.presetZones.length) { const empty = document.createElement('li'); empty.className = 'text-xs text-base-content/60'; empty.textContent = 'No preset zones yet.'; list.append(empty); }
    syncMediaDrop();
  }
  async function refreshPresetZones() {
    try { const response = await apiFetch('/api/media-preset-zones'); if (!response.ok) throw Error('Preset zones are unavailable.'); state.presetZones = await response.json(); renderPresetZones(); }
    catch (error) { officekitOutcome.show($('zone-status'), { state: 'error', text: error.message || 'Preset zones could not be loaded.' }); }
  }
  async function createPresetZone() {
    const name = $('zone-name').value.trim(), pipelineId = $('zone-pipeline').value;
    if (!name || !pipelineId) { officekitOutcome.show($('zone-status'), { state: 'error', text: 'Enter a zone name and choose a saved pipeline.' }); return; }
    $('zone-create').disabled = true;
    try { const response = await apiFetch('/api/media-preset-zones', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, pipelineId }) }); const payload = await response.json().catch(() => ({})); if (!response.ok) throw Error(payload.detail || 'The preset zone could not be saved.'); state.presetZones.push(payload); $('zone-name').value = ''; officekitOutcome.show($('zone-status'), { state: 'error', text: `“${payload.name}” saved disabled. Enable it for this session when ready.` }); renderPresetZones(); }
    catch (error) { officekitOutcome.show($('zone-status'), { state: 'error', text: error.message || 'The preset zone could not be saved.' }); }
    finally { renderPresetZones(); }
  }
  async function updatePresetZone(id, enabled) {
    try { const response = await apiFetch(`/api/media-preset-zones/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }); const payload = await response.json().catch(() => ({})); if (!response.ok) throw Error(payload.detail || 'The preset zone could not be updated.'); state.presetZones = state.presetZones.map(zone => zone.id === id ? payload : zone); officekitOutcome.show($('zone-status'), { state: 'error', text: enabled ? 'Preset zone enabled for this session.' : 'Preset zone turned off.' }); renderPresetZones(); }
    catch (error) { officekitOutcome.show($('zone-status'), { state: 'error', text: error.message || 'The preset zone could not be updated.' }); }
  }
  async function deletePresetZone(id) {
    try { const response = await apiFetch(`/api/media-preset-zones/${id}`, { method: 'DELETE' }); if (!response.ok) throw Error('The preset zone could not be removed.'); state.presetZones = state.presetZones.filter(zone => zone.id !== id); officekitOutcome.show($('zone-status'), { state: 'error', text: 'Preset zone removed. Its pipeline and files are unchanged.' }); renderPresetZones(); }
    catch (error) { officekitOutcome.show($('zone-status'), { state: 'error', text: error.message || 'The preset zone could not be removed.' }); }
  }
  async function addPipelineStep() {
    if (state.activePipeline) { state.activePipeline = null; renderPipelines(); }
    const operation = activeOperation();
    if (!operation?.available) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: 'Choose an available operation before adding a step.' }); return; }
    if (state.draftSteps.length >= 8) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: 'A pipeline can contain up to eight steps.' }); return; }
    let options;
    try { options = JSON.parse($('options').value); if (!options || Array.isArray(options) || typeof options !== 'object') throw Error(); }
    catch { officekitOutcome.show($('pipeline-status'), { state: 'error', text: 'Enter operation settings as a JSON object before adding this step.' }); return; }
    const media = $('kind').value;
    if (state.draftSteps.some(step => step.media !== media)) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: 'All pipeline steps must use the same media type.' }); return; }
    state.draftSteps.push({ media, operationId: operation.id, options });
    officekitOutcome.show($('pipeline-status'), { state: 'error', text: `${operation.label} added to the draft.` });
    renderPipelineDraft();
  }
  async function savePipeline() {
    const name = $('pipeline-name').value.trim();
    if (!name || !state.draftSteps.length) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: 'Enter a name and add at least one step.' }); return; }
    const button = $('pipeline-save'); button.disabled = true;
    try {
      const outputNameTemplate = $('pipeline-output-template').value.trim() || null;
      const response = await apiFetch('/api/media-pipelines', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, media: state.draftSteps[0].media, operations: state.draftSteps.map(({ operationId, options }) => ({ operationId, options })), outputNameTemplate }) });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The pipeline could not be saved.'); }
      const pipeline = await response.json(); state.pipelines.push(pipeline); state.draftSteps = []; $('pipeline-name').value = ''; state.activePipeline = JSON.parse(JSON.stringify(pipeline));
      $('kind').value = pipeline.media;
      renderOperations();
      $('operation').value = pipeline.operations[0].operationId;
      $('options').value = JSON.stringify(pipeline.operations[0].options, null, 2);
      officekitOutcome.show($('pipeline-status'), { state: 'success', text: `“${pipeline.name}” saved paused. Choose files and run it when ready.` });
      renderPipelineDraft(); renderPipelines(); renderOperations(); renderFiles();
    } catch (error) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: error.message || 'The pipeline could not be saved.' }); button.disabled = false; }
  }
  async function deletePipeline(id) {
    try {
      const response = await apiFetch(`/api/media-pipelines/${id}`, { method: 'DELETE' });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The pipeline could not be deleted.'); }
      state.pipelines = state.pipelines.filter(pipeline => pipeline.id !== id);
      if (state.activePipeline?.id === id) state.activePipeline = null;
      renderPipelines(); renderFiles(); officekitOutcome.show($('pipeline-status'), { state: 'success', text: 'Pipeline deleted. Files and previous results are unchanged.' });
    } catch (error) { officekitOutcome.show($('pipeline-status'), { state: 'error', text: error.message || 'The pipeline could not be deleted.' }); }
  }
  function renderFolderWatches() {
    const select = $('folder-pipeline');
    const add = $('folder-add');
    const list = $('folder-list');
    if (!select || !add || !list) return;
    const previous = select.value;
    select.replaceChildren(new Option('Choose an available pipeline', ''));
    const ready = state.pipelines.filter(pipeline => pipeline.operations.every(step => operationById(step.operationId)?.available === true));
    for (const pipeline of ready) select.add(new Option(`${pipeline.name} · ${pipeline.media.toUpperCase()}`, pipeline.id));
    if (ready.some(pipeline => pipeline.id === previous)) select.value = previous;
    add.disabled = !select.value || !window.__TAURI__?.core?.invoke;
    list.replaceChildren();
    for (const watch of state.folderWatches) {
      const item = document.createElement('li'); item.className = 'rounded-lg border border-base-300 p-3';
      const heading = document.createElement('div'); heading.className = 'flex flex-wrap items-center justify-between gap-2';
      const title = document.createElement('strong'); title.className = 'text-sm'; title.textContent = watch.folderName;
      const badge = document.createElement('span'); badge.className = `badge badge-sm ${watch.state === 'watching' ? 'badge-success badge-outline' : 'badge-ghost'}`; badge.textContent = watch.state === 'watching' ? 'Watching' : 'Paused';
      heading.append(title, badge);
      const recipe = document.createElement('p'); recipe.className = 'mt-1 text-xs text-base-content/70'; recipe.textContent = `${watch.pipelineName} · ${watch.processedCount} prepared`;
      const actions = document.createElement('div'); actions.className = 'mt-2 flex flex-wrap gap-2';
      const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'btn btn-xs btn-outline'; toggle.textContent = watch.state === 'watching' ? 'Pause' : 'Resume';
      toggle.addEventListener('click', () => { void setFolderWatchPaused(watch.id, watch.state === 'watching'); });
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-xs btn-ghost'; remove.textContent = 'Remove grant';
      remove.addEventListener('click', () => { void removeFolderWatch(watch.id); });
      actions.append(toggle, remove); item.append(heading, recipe, actions);
      for (const result of (watch.recentOutcomes || []).slice(-3).reverse()) {
        const outcome = document.createElement('p'); outcome.className = 'mt-2 text-xs text-base-content/70';
        outcome.textContent = `${result.filename || 'Latest file'}: ${result.message}`; item.append(outcome);
      }
      list.append(item);
    }
    if (!state.folderWatches.length) { const empty = document.createElement('li'); empty.className = 'text-xs text-base-content/60'; empty.textContent = 'No folders are granted.'; list.append(empty); }
  }
  async function refreshFolderWatches() {
    try {
      const response = await apiFetch('/api/media-folder-watches');
      if (!response.ok) throw Error('Watched folders are unavailable.');
      state.folderWatches = await response.json(); renderFolderWatches();
    } catch (error) { officekitOutcome.show($('folder-status'), { state: 'error', text: error.message || 'Watched-folder status is unavailable.' }); }
  }
  async function addFolderWatch() {
    const pipelineId = $('folder-pipeline').value;
    if (!pipelineId) return;
    const button = $('folder-add'); button.disabled = true;
    try {
      const watch = await window.__TAURI__.core.invoke('media_folder_watch_open', { pipelineId });
      if (!watch) { officekitOutcome.show($('folder-status'), { state: 'info', text: 'Folder selection cancelled. No folder access was granted.' }); return; }
      state.folderWatches.push(watch); renderFolderWatches();
      officekitOutcome.show($('folder-status'), { state: 'info', text: `Watching ${watch.folderName} with ${watch.pipelineName}. You can pause or remove this grant at any time.` });
    } catch (error) { officekitOutcome.show($('folder-status'), { state: 'error', text: error?.message || 'The folder grant could not be created.' }); }
    finally { renderFolderWatches(); }
  }
  async function setFolderWatchPaused(id, paused) {
    try {
      const response = await apiFetch(`/api/media-folder-watches/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paused }) });
      if (!response.ok) throw Error('The folder watching state could not be changed.');
      const updated = await response.json(); state.folderWatches = state.folderWatches.map(item => item.id === id ? updated : item); renderFolderWatches();
    } catch (error) { officekitOutcome.show($('folder-status'), { state: 'error', text: error.message || 'The folder watching state could not be changed.' }); }
  }
  async function removeFolderWatch(id) {
    try {
      const response = await apiFetch(`/api/media-folder-watches/${id}`, { method: 'DELETE' });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The folder grant could not be removed.'); }
      state.folderWatches = state.folderWatches.filter(item => item.id !== id); renderFolderWatches();
      officekitOutcome.show($('folder-status'), { state: 'success', text: 'Folder grant removed. No more files will be watched.' });
    } catch (error) { officekitOutcome.show($('folder-status'), { state: 'error', text: error.message || 'The folder grant could not be removed.' }); }
  }
  const kindLabels = { image: 'Images', video: 'Video', pdf: 'PDF', audio: 'Audio' };
  // Kinds present in the batch, in catalogue order. A mixed batch lists one group per kind.
  function batchKinds() {
    if (state.activePipeline) return [];
    return kinds.filter(kind => state.files.some(file => kindForFile(file) === kind));
  }
  function operationKind(operationId) {
    return state.capabilities?.media.find(entry => entry.operations.some(operation => operation.id === operationId))?.id || null;
  }
  function renderOperations() {
    if (!state.capabilities) return;
    let kind = $('kind').value;
    const select = $('operation');
    const previousOperation = select.value;
    const groups = batchKinds();
    const grouped = groups.length > 1;
    select.replaceChildren();
    for (const groupKind of grouped ? groups : [kind]) {
      const groupMedia = state.capabilities.media.find(entry => entry.id === groupKind);
      const parent = grouped ? document.createElement('optgroup') : select;
      if (grouped) {
        const count = state.files.filter(file => kindForFile(file) === groupKind).length;
        parent.label = `${kindLabels[groupKind]} (${count} ${count === 1 ? 'file' : 'files'})`;
        select.append(parent);
      }
      for (const operation of groupMedia?.operations || []) {
        const option = document.createElement('option');
        option.value = operation.id;
        option.textContent = operation.label + (operation.available ? '' : ' · unavailable');
        option.disabled = !operation.available;
        parent.append(option);
      }
    }
    const allOperations = state.capabilities.media.filter(entry => (grouped ? groups : [kind]).includes(entry.id)).flatMap(entry => entry.operations);
    // "Settings for <file>" asks for that file's type: its saved operation, or its first available one.
    const preferred = grouped ? state.preferredKind : null;
    state.preferredKind = null;
    const preferredMedia = preferred && groups.includes(preferred) ? state.capabilities.media.find(entry => entry.id === preferred) : null;
    if (preferredMedia) {
      const saved = state.kindDrafts[preferred]?.operationId;
      const choice = preferredMedia.operations.find(operation => operation.id === saved && operation.available) || preferredMedia.operations.find(operation => operation.available);
      if (choice) select.value = choice.id;
    } else {
      const selectedOperation = allOperations.find(operation => operation.id === previousOperation && operation.available);
      const firstAvailable = allOperations.find(operation => operation.available);
      if (selectedOperation || firstAvailable) select.value = (selectedOperation || firstAvailable).id;
    }
    // In a mixed batch the chosen operation decides the type, so the type picker follows the list.
    if (grouped && operationKind(select.value)) { kind = operationKind(select.value); $('kind').value = kind; }
    const media = state.capabilities.media.find(entry => entry.id === kind);
    const draft = state.kindDrafts[kind];
    if (draft && media?.operations.some(entry => entry.id === draft.operationId && entry.available) && state.editingKind !== kind) select.value = draft.operationId;
    state.editingKind = kind;
    state.renderedOperationId = select.value;
    const current = activeOperation();
    const operation = current;
    $('options').value = JSON.stringify(draft?.operationId === current?.id ? draft.options : state.localDefaults[current?.id] || defaults[current?.id] || {}, null, 2);
    renderSettings();
    $('save-local-default').disabled = !operation?.available || Boolean(state.activePipeline);
    $('options-help').textContent = operation?.id === 'image-optimize' ? 'Metadata is removed by default. Turning this on preserves EXIF and color profile data, which may include camera or location details.' : operation?.id === 'pdf-crop' ? 'Pages are centered to the selected aspect and content outside the new page boundary is hidden. The original remains unchanged.' : operation?.id?.endsWith('-crop') ? 'Crop coordinates are in pixels; the rectangle must fit inside each selected file.' : 'Settings are validated locally. Choose an operation to see its defaults.';
    const warning = $('fidelity-warning');
    const visualPdf = ['pdf-visual-optimize', 'pdf-fit-size'].includes(operation?.id);
    warning.hidden = !visualPdf && operation?.id !== 'pdf-crop';
    warning.textContent = visualPdf
      ? 'Visual PDF preparation rasterizes each page. Searchable text, links, forms, accessibility structure, and digital signatures are not preserved; annotation appearances may become part of the page image. Review the saved copy before sharing. Your original is unchanged.'
      : operation?.id === 'pdf-crop'
        ? 'This changes each page boundary to the selected size and hides content outside it. Check every page before sharing. Your original is unchanged.'
        : '';
    warning.className = visualPdf
      ? 'rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm leading-6 text-amber-950'
      : 'rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700';
    $('capability').textContent = operation?.available ? `Available for ${operation.formats.join(', ')}. Processing runs locally and creates a separate output.` : (operation?.reason || 'No local adapter is available.');
    $('run').disabled = (!state.files.length && !state.importPreview && !state.stagedImage) || !selectedOperationsAvailable() || state.running || Boolean(state.activePipeline && state.importPreview);
    syncNext();
  }
  // Previews (thumbnails, larger preview, expanded viewer) live in officekit-media-preview.js.
  const previews = window.officekitMediaPreview.create({ apiFetch, getFiles: () => state.files, onChange: () => renderFiles() });
  const renderPreviewPanel = () => previews.renderPanel($('preview'), state.previewFileId);
  function renderFiles() {
    // The type comes from the files: one type selects that type's operations, so a JPEG gets image operations.
    const batchKey = batchKinds().join(',');
    if (batchKey !== state.batchKey) {
      state.batchKey = batchKey;
      const only = batchKinds();
      if (only.length === 1 && $('kind').value !== only[0]) $('kind').value = only[0];
      renderOperations();
    }
    const list = $('file-list');
    list.replaceChildren();
    if (!state.files.length) { previews.close(); previews.clear(); }
    if (!state.files.length && !state.importPreview && !state.stagedImage) {
      const item = document.createElement('li'); item.className = 'rounded-lg bg-slate-50 p-3 text-slate-500'; item.textContent = 'No files selected.'; list.append(item);
    } else for (const file of state.files) {
      // Rows wrap in a narrow column: the Settings button drops under the name rather than squeezing it.
      const item = document.createElement('li'); item.className = 'flex flex-wrap items-center gap-2 rounded-lg bg-base-200 p-3';
      const thumb = previews.thumb(file);
      thumb.tile.addEventListener('dblclick', () => previews.openViewer(file.id));
      const name = document.createElement('span'); name.className = 'block min-w-0 break-all'; name.textContent = file.name;
      const size = document.createElement('span'); size.className = 'block text-xs text-base-content/70';
      size.textContent = previews.describe(file, thumb.entry, window.OfficeKitFormatters.fileSize(file.size_bytes));
      const text = document.createElement('span'); text.className = 'min-w-[5rem] flex-1'; text.append(name, size);
      const check = document.createElement('input'); check.type = 'checkbox'; check.className = 'checkbox checkbox-sm'; check.checked = file.checked !== false; check.disabled = state.running;
      check.setAttribute('aria-label', `Prepare ${file.name}`);
      check.addEventListener('change', () => { file.checked = check.checked; renderFiles(); });
      const edit = text; const editable = !state.running && Boolean(kindForFile(file));
      edit.setAttribute('role', 'button'); edit.tabIndex = editable ? 0 : -1; edit.setAttribute('aria-disabled', String(!editable)); edit.classList.toggle('cursor-pointer', editable);
      edit.setAttribute('aria-label', `Settings for ${file.name}`); edit.title = 'Click to edit the settings for this file’s type';
      edit.addEventListener('keydown', event => { if (editable && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); edit.click(); } });
      edit.addEventListener('click', () => { if (!editable) return; if (!syncSettingsFromForm()) return; rememberSettings(); state.activePipeline = null; state.previewFileId = file.id; $('kind').value = kindForFile(file); state.preferredKind = kindForFile(file); renderPipelines(); renderOperations(); renderPreviewPanel(); $('operation').focus(); });
      item.append(check, thumb.tile, text); list.append(item);
    }
    if (state.importPreview) {
      const item = document.createElement('li'); item.className = 'flex items-center justify-between gap-2 rounded-lg bg-emerald-50 p-3';
      const name = document.createElement('span'); name.textContent = state.importPreview.filename;
      const size = document.createElement('span'); size.className = 'shrink-0 text-xs text-emerald-800'; size.textContent = state.importPreview.sizeBytes == null ? 'size unknown' : window.OfficeKitFormatters.fileSize(state.importPreview.sizeBytes);
      item.append(name, size); list.append(item);
    }
    if (state.stagedImage) {
      const item = document.createElement('li'); item.className = 'flex items-center justify-between gap-2 rounded-lg bg-indigo-50 p-3';
      const name = document.createElement('span'); name.textContent = `${state.stagedImage.filename} · edited copy`;
      const size = document.createElement('span'); size.className = 'shrink-0 text-xs text-indigo-800'; size.textContent = `${window.OfficeKitFormatters.fileSize(state.stagedImage.sizeBytes)} · expires in ${state.stagedImage.expiresInSeconds} seconds`;
      item.append(name, size); list.append(item);
    }
    renderPreviewPanel();
    $('run').disabled = (!state.files.some(file => file.checked !== false) && !state.importPreview && !state.stagedImage) || !selectedOperationsAvailable() || state.running || Boolean(state.activePipeline && state.importPreview);
    const signature = state.files.map(file => `${file.id}:${file.checked !== false}`).join(',');
    if (!state.running && signature !== state.fileSignature) state.finished = false;
    state.fileSignature = signature;
    syncNext();
  }
  function clearImport() {
    state.importPreview = null;
    $('url').value = '';
    $('import-preview').classList.add('hidden');
    $('import-summary').replaceChildren();
    officekitOutcome.show($('import-status'), { state: 'success', text: 'Link cleared. Other selected files remain.' });
    renderFiles();
  }
  async function clearStagedImage() {
    const staged = state.stagedImage;
    state.stagedImage = null;
    if (staged) {
      try { await apiFetch(`/api/media-image-stagings/${staged.stagingId}`, { method: 'DELETE' }); }
      catch { officekitOutcome.show($('import-status'), { state: 'error', text: 'The edited-image grant could not be cleared immediately; it expires automatically in five minutes.' }); }
    }
    renderFiles();
  }
  async function clearSelections() {
    const selections = state.selections.length ? state.selections : state.selection ? [state.selection] : [];
    state.selections = [];
    state.selection = null;
    for (const selection of selections) {
      try { await apiFetch(`/api/file-selections/${selection.id}`, { method: 'DELETE' }); }
      catch { /* Grants expire automatically when immediate cleanup is unavailable. */ }
    }
  }
  async function readSelectionManifest(selection) {
    const response = await apiFetch(`/api/file-selections/${selection.id}`);
    if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The dropped files could not be opened.'); }
    const manifest = await response.json();
    if (manifest.hasMore || manifest.files.length > 30) throw Error('Select at most 30 files at a time.');
    if (!manifest.files.length) throw Error('No files were selected.');
    return manifest;
  }
  function ensurePipelineMatchesSelection(pipeline, manifest) {
    if (manifest.files.some(file => !mediaTypeMatchesKind(pipeline.media, mediaTypeForName(file.name)))) {
      throw Error('The pinned pipeline does not match every dropped file.');
    }
  }
  async function acceptSelection(selection, { append = false, manifest: suppliedManifest = null } = {}) {
    if (state.running) throw Error('Wait for the current job to finish before adding files.');
    const manifest = suppliedManifest || await readSelectionManifest(selection);
    if (state.running) throw Error('Wait for the current job to finish before adding files.');
    if (append && state.files.length + manifest.files.length > 30) throw Error('A batch can contain up to 30 files. Clear or replace the selection before adding more.');
    if (append) {
      state.selections.push(selection);
      state.files.push(...manifest.files.map(file => ({ ...file, media_type: mediaTypeForName(file.name), selectionId: selection.id })));
    } else {
      await clearSelections();
      state.selections = [selection];
      state.selection = selection;
      state.files = manifest.files.map(file => ({ ...file, media_type: mediaTypeForName(file.name), selectionId: selection.id }));
    }
    renderFiles();
    return manifest.files.length;
  }
  async function pinnedPipelineForTrigger(trigger) {
    const bindingResponse = await apiFetch('/api/media-pipeline-triggers');
    if (!bindingResponse.ok) throw Error('Saved media trigger settings could not be read.');
    const bindings = await bindingResponse.json();
    const pipelineId = bindings?.[trigger];
    if (!pipelineId) return null;
    const pipelinesResponse = await apiFetch('/api/media-pipelines');
    if (!pipelinesResponse.ok) throw Error('The pinned media pipeline could not be loaded.');
    const pipelines = await pipelinesResponse.json();
    const pipeline = Array.isArray(pipelines) ? pipelines.find(item => item.id === pipelineId) : null;
    if (!pipeline || !Array.isArray(pipeline.operations) || !pipeline.operations.length
      || pipeline.operations.some(step => operationById(step.operationId)?.available !== true)) {
      throw Error('The pinned media pipeline is unavailable or has unsupported steps.');
    }
    return pipeline;
  }
  function selectPinnedPipeline(pipeline) {
    state.activePipeline = JSON.parse(JSON.stringify(pipeline));
    $('kind').value = pipeline.media;
    renderOperations();
    $('operation').value = pipeline.operations[0].operationId;
    $('options').value = JSON.stringify(pipeline.operations[0].options, null, 2);
    renderPipelines();
  }
  async function handleDroppedSelection(selection) {
    const target = $('drop-target');
    if (state.running || !$('panel').getClientRects().length || !$('prepare-view').getClientRects().length || !document.getElementById('tab-converter')?.getClientRects().length) {
      try { await apiFetch(`/api/file-selections/${selection.id}`, { method: 'DELETE' }); } catch {}
      if (state.running) status('Wait for the current job to finish before adding files.');
      return;
    }
    try {
      const pipeline = await pinnedPipelineForTrigger('drop-zone');
      if (pipeline) {
        const manifest = await readSelectionManifest(selection);
        ensurePipelineMatchesSelection(pipeline, manifest);
        selectPinnedPipeline(pipeline);
        const count = await acceptSelection(selection, { manifest });
        status(`${count} file${count === 1 ? '' : 's'} dropped on the pinned pipeline. Preparing separate local copies…`);
        await run();
        return;
      }
      const count = await acceptSelection(selection, { append: true });
      status(`${count} dropped file${count === 1 ? '' : 's'} added to the batch. The originals will not be modified.`);
    } catch (error) {
      try { await apiFetch(`/api/file-selections/${selection.id}`, { method: 'DELETE' }); } catch {}
      status(error.message || 'The dropped files could not be added.');
    } finally { target?.classList.remove('border-primary', 'bg-primary/5'); }
  }
  async function handlePresetZoneDrop(selection) {
    const zone = state.presetZones.find(item => item.id === selection.presetZoneId && item.enabled);
    const pipeline = state.pipelines.find(item => item.id === zone?.pipelineId);
    if (!zone || !pipeline || state.running) {
      try { await apiFetch(`/api/file-selections/${selection.id}`, { method: 'DELETE' }); } catch {}
      status('That preset zone is off or unavailable. Enable it and drop the file again.');
      return;
    }
    try {
      const manifest = await readSelectionManifest(selection);
      ensurePipelineMatchesSelection(pipeline, manifest);
      state.activePipeline = JSON.parse(JSON.stringify(pipeline));
      $('kind').value = pipeline.media; renderOperations(); $('operation').value = pipeline.operations[0].operationId;
      $('options').value = JSON.stringify(pipeline.operations[0].options, null, 2); renderPipelines();
      const count = await acceptSelection(selection, { manifest });
      status(`${count} file${count === 1 ? '' : 's'} dropped on “${zone.name}”. Preparing a separate local copy…`);
      await run();
    } catch (error) {
      try { await apiFetch(`/api/file-selections/${selection.id}`, { method: 'DELETE' }); } catch {}
      status(error.message || 'The preset-zone drop could not be prepared.');
    }
  }
  async function enableMediaDrop() {
    const tauri = window.__TAURI__;
    if (!tauri?.event?.listen || !tauri?.core?.invoke || !$('drop-target')) return;
    try {
      await tauri.event.listen('officekit-media-file-drop', event => {
        const selection = event.payload;
        if (!selection?.id) { status('Dropped files could not be authorized.'); return; }
        mediaDropQueue = mediaDropQueue.then(() => selection.presetZoneId ? handlePresetZoneDrop(selection) : handleDroppedSelection(selection));
      });
      await tauri.event.listen('officekit-media-file-drop-error', event => {
        status(event.payload?.message || 'The dropped files could not be authorized.');
      });
    } catch { return; }
    const syncEnabled = () => {
      const prepareEnabled = !state.running
        && $('panel').getClientRects().length > 0
        && $('prepare-view').getClientRects().length > 0
        && (document.getElementById('tab-converter')?.getClientRects().length || 0) > 0;
      const rect = $('drop-target').getBoundingClientRect();
      // macOS AppKit and GTK report logical points; Windows WebView2 uses physical client pixels.
      const platform = `${navigator.platform || ''} ${navigator.userAgent || ''}`;
      const scale = /Win/i.test(platform) ? (window.devicePixelRatio || 1) : 1;
      const automationsEnabled = !state.running && $('panel').getClientRects().length > 0
        && $('automations-view').getClientRects().length > 0 && (document.getElementById('tab-converter')?.getClientRects().length || 0) > 0;
      const targets = automationsEnabled ? [...document.querySelectorAll('#media-toolkit-zone-list [data-zone-id]')]
        .filter(element => state.presetZones.some(zone => zone.id === element.dataset.zoneId && zone.enabled && state.pipelines.find(pipeline => pipeline.id === zone.pipelineId)?.operations.every(step => operationById(step.operationId)?.available === true)))
        .map(element => { const bounds = element.getBoundingClientRect(); return { id: element.dataset.zoneId, x: bounds.left * scale, y: bounds.top * scale, width: bounds.width * scale, height: bounds.height * scale }; }) : [];
      tauri.core.invoke('media_toolkit_drop_set_enabled', {
        enabled: prepareEnabled || targets.length > 0,
        x: prepareEnabled ? rect.left * scale : null,
        y: prepareEnabled ? rect.top * scale : null,
        width: prepareEnabled ? rect.width * scale : null,
        height: prepareEnabled ? rect.height * scale : null,
        targets,
      }).catch(() => {});
      $('drop-target').classList.toggle('border-primary', prepareEnabled);
    };
    const observer = new MutationObserver(syncEnabled);
    syncMediaDrop = syncEnabled;
    observer.observe($('panel'), { attributes: true, attributeFilter: ['class'] });
    observer.observe($('prepare-view'), { attributes: true, attributeFilter: ['class'] });
    observer.observe($('automations-view'), { attributes: true, attributeFilter: ['class'] });
    observer.observe($('zone-list'), { childList: true, subtree: true });
    observer.observe(document.getElementById('tab-converter'), { attributes: true, attributeFilter: ['class'] });
    document.addEventListener('scroll', syncEnabled, true);
    window.addEventListener('resize', syncEnabled);
    syncEnabled();
  }
  async function addStagedImage(staged) {
    if (state.running || !staged || !/^[0-9a-f-]{36}$/i.test(staged.stagingId || '') || typeof staged.filename !== 'string' || !Number.isSafeInteger(staged.sizeBytes)) return false;
    await clearStagedImage();
    state.stagedImage = staged;
    $('kind').value = 'image';
    renderOperations(); renderFiles();
    status(`Edited copy ready. Choose an image operation and prepare a new copy; the editor export remains unchanged.`);
    return true;
  }
  async function prepareClipboardImage(file, { explicitHotkey = false } = {}) {
    let stagingId = null;
    try {
      const pipeline = await pinnedPipelineForTrigger('clipboard');
      const form = new FormData(); form.append('file', file, file.name || 'clipboard-image.png');
      const stagedResponse = await apiFetch('/api/media-image-stagings', { method: 'POST', body: form });
      if (!stagedResponse.ok) throw Error((await stagedResponse.json().catch(() => ({}))).detail || 'Clipboard image staging failed.');
      const staged = await stagedResponse.json(); stagingId = staged.stagingId;
      const operations = pipeline ? pipeline.operations : [{ operationId: 'image-optimize', options: { quality: 82, preserveMetadata: false } }];
      if (pipeline && pipeline.media !== 'image') throw Error('The pinned clipboard pipeline must contain image operations.');
      const jobResponse = await apiFetch('/api/media-jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: [{ source: { kind: 'staged-image', stagingId }, operations,
        ...(pipeline?.outputNameTemplate ? { outputNameTemplate: pipeline.outputNameTemplate } : {}) }] }) });
      if (!jobResponse.ok) throw Error((await jobResponse.json().catch(() => ({}))).detail || 'Clipboard image preparation could not start.');
      stagingId = null;
      const { id } = await jobResponse.json();
      let result;
      for (let attempt = 0; attempt < 300; attempt += 1) {
        const response = await apiFetch(`/api/media-jobs/${id}`);
        if (!response.ok) throw Error('Clipboard preparation status is unavailable.');
        result = await response.json();
        if (['ready', 'partial', 'failed', 'cancelled'].includes(result.state)) break;
        await new Promise(resolve => setTimeout(resolve, 350));
      }
      const item = result?.items?.[0];
      if (result?.state !== 'ready' || item?.state !== 'ready' || !item.artifactId) throw Error(item?.errorCode || 'Clipboard image could not be prepared.');
      const artifact = await apiFetch(`/api/media-artifacts/${item.artifactId}`);
      if (!artifact.ok) throw Error('Prepared clipboard image is unavailable.');
      const blob = await artifact.blob();
      if (!explicitHotkey && localStorage.getItem('officekit.media.clipboardAutomation') !== 'true') throw Error('Monitoring was turned off; the prepared image was not copied to the clipboard.');
      await window.officekitWriteScreenshotClipboardImage(blob);
      return { outputBytes: blob.size, inputBytes: file.size, outputName: item.outputName };
    } catch (error) {
      if (stagingId) { try { await apiFetch(`/api/media-image-stagings/${stagingId}`, { method: 'DELETE' }); } catch {} }
      throw error;
    }
  }
  function initClipboardAutomation() {
    const toggle = $('clipboard-opt-in');
    if (!toggle) return;
    const statusNode = $('clipboard-status');
    const bypass = $('clipboard-bypass');
    const enabledKey = 'officekit.media.clipboardAutomation';
    toggle.checked = localStorage.getItem(enabledKey) === 'true';
    const readRevision = () => window.__TAURI__?.core?.invoke('media_clipboard_revision');
    const check = async () => {
      if (!toggle.checked || document.hidden || clipboardProcessing) return;
      clipboardProcessing = true;
      try {
        const revision = await readRevision();
        if (clipboardRevision === null) { clipboardRevision = revision; return; }
        if (revision === clipboardRevision) return;
        clipboardRevision = revision;
        if (bypassClipboardOnce) { bypassClipboardOnce = false; officekitOutcome.show(statusNode, { state: 'info', text: 'Skipped the next clipboard item.' }); return; }
        const file = await window.officekitReadScreenshotClipboardFile();
        if (!file) return;
        officekitOutcome.show(statusNode, { state: 'working', text: 'Preparing clipboard image locally…' });
        const outcome = await prepareClipboardImage(file);
        clipboardRevision = await readRevision();
        officekitOutcome.show(statusNode, { state: 'info', text: `Prepared ${outcome.outputName || 'clipboard image'} · ${window.OfficeKitFormatters.fileSize(outcome.outputBytes)}. The source image remains unchanged.` });
      } catch (error) {
        if (/clipboard.*image|image.*clipboard|clipboard.*contain/i.test(error?.message || '')) officekitOutcome.show(statusNode, { state: 'error', text: 'Clipboard item is not a readable image; it was ignored.' });
        else officekitOutcome.show(statusNode, { state: 'error', text: error?.message || 'Clipboard image preparation failed.' });
      } finally { clipboardProcessing = false; }
    };
    toggle.addEventListener('change', async () => {
      localStorage.setItem(enabledKey, String(toggle.checked));
      bypassClipboardOnce = false;
      clipboardRevision = toggle.checked ? await readRevision().catch(() => null) : null;
      officekitOutcome.show(statusNode, { state: 'info', text: toggle.checked ? 'Monitoring is on. Only changed clipboard images are read; text is ignored.' : 'Monitoring is off. Clipboard contents are not read.' });
      if (toggle.checked && clipboardRevision === null) { toggle.checked = false; localStorage.setItem(enabledKey, 'false'); officekitOutcome.show(statusNode, { state: 'error', text: 'Clipboard monitoring is unavailable on this device.' }); }
    });
    bypass.addEventListener('click', () => { bypassClipboardOnce = true; officekitOutcome.show(statusNode, { state: 'info', text: 'The next changed clipboard item will be skipped.' }); });
    if (toggle.checked) void readRevision().then(value => { clipboardRevision = value; officekitOutcome.show(statusNode, { state: 'info', text: 'Monitoring is on. Only changed clipboard images are read; text is ignored.' }); }).catch(() => { toggle.checked = false; localStorage.setItem(enabledKey, 'false'); officekitOutcome.show(statusNode, { state: 'error', text: 'Clipboard monitoring is unavailable on this device.' }); });
    clipboardLoop = window.setInterval(() => { void check(); }, 800);
  }
  async function runClipboardHotkey() {
    const statusNode = $('hotkey-status');
    if (clipboardProcessing) { officekitOutcome.show(statusNode, { state: 'info', text: 'Clipboard preparation is already in progress.' }); return; }
    clipboardProcessing = true;
    try {
      const file = await window.officekitReadScreenshotClipboardFile();
      if (!file) { officekitOutcome.show(statusNode, { state: 'info', text: 'The clipboard does not contain a readable image; no content was changed.' }); return; }
      officekitOutcome.show(statusNode, { state: 'working', text: 'Preparing the clipboard image locally…' });
      const result = await prepareClipboardImage(file, { explicitHotkey: true });
      clipboardRevision = await window.__TAURI__?.core?.invoke('media_clipboard_revision').catch(() => null);
      officekitOutcome.show(statusNode, { state: 'info', text: `Prepared ${result.outputName || 'clipboard image'} · ${window.OfficeKitFormatters.fileSize(result.outputBytes)}. The prepared image is on the clipboard; the source file is unchanged.` });
    } catch (error) {
      if (/clipboard.*image|image.*clipboard|clipboard.*contain/i.test(error?.message || '')) officekitOutcome.show(statusNode, { state: 'error', text: 'The clipboard does not contain a readable image; no content was changed.' });
      else officekitOutcome.show(statusNode, { state: 'error', text: error?.message || 'Clipboard image preparation failed.' });
    } finally { clipboardProcessing = false; }
  }
  function initClipboardHotkey() {
    const toggle = $('hotkey-enable'), statusNode = $('hotkey-status');
    if (!toggle || !statusNode) return;
    const preferenceKey = 'officekit.media.clipboardHotkey';
    const invoke = window.__TAURI__?.core?.invoke;
    const listen = window.__TAURI__?.event?.listen;
    if (typeof invoke !== 'function' || typeof listen !== 'function') {
      toggle.disabled = true; officekitOutcome.show(statusNode, { state: 'info', text: 'The clipboard hotkey is available in the OfficeKit desktop app.' }); return;
    }
    toggle.checked = localStorage.getItem(preferenceKey) === 'true';
    const setEnabled = async enabled => {
      toggle.disabled = true;
      try {
        const result = await invoke('media_clipboard_hotkey_set_enabled', { enabled });
        if (result !== enabled) throw Error('The shortcut state could not be confirmed.');
        localStorage.setItem(preferenceKey, String(enabled));
        toggle.checked = enabled;
        officekitOutcome.show(statusNode, { state: 'success', text: enabled ? 'Control+Shift+C is on. Clipboard contents are read only after the shortcut is pressed.' : 'Shortcut is off. Clipboard contents are not read.' });
      } catch (error) {
        toggle.checked = !enabled; localStorage.setItem(preferenceKey, String(!enabled));
        officekitOutcome.show(statusNode, { state: 'error', text: typeof error === 'string' ? error : error?.message || 'The clipboard hotkey could not be changed.' });
      } finally { toggle.disabled = false; }
    };
    toggle.addEventListener('change', () => { void setEnabled(toggle.checked); });
    listen('officekit-media-clipboard-hotkey', () => { void runClipboardHotkey(); }).then(() => {
      if (toggle.checked) void setEnabled(true);
      else officekitOutcome.show(statusNode, { state: 'info', text: 'Shortcut is off. Clipboard contents are not read.' });
    }).catch(() => {
      toggle.checked = false; toggle.disabled = true; localStorage.setItem(preferenceKey, 'false');
      officekitOutcome.show(statusNode, { state: 'error', text: 'The clipboard hotkey event could not be connected.' });
    });
  }
  function initFinderAction() {
    const install = $('finder-install'), remove = $('finder-remove');
    const statusNode = $('finder-status');
    if (!install || !remove || !statusNode) return;
    let busy = true, available = false;
    const updateDisabled = () => {
      install.disabled = busy || !available;
      remove.disabled = busy || !available;
    };
    updateDisabled();
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke !== 'function') {
      busy = false;
      install.disabled = true;
      officekitOutcome.show(statusNode, { state: 'info', text: 'Finder Quick Actions are available in the OfficeKit desktop app on macOS.' });
      return;
    }
    const refresh = async () => {
      try {
        const state = await invoke('media_finder_action_status');
        const installed = state === 'installed';
        available = true;
        install.hidden = installed;
        remove.hidden = !installed;
        officekitOutcome.show(statusNode, { state: 'info', text: installed ? 'Quick Action is installed. Select images in Finder and choose Quick Actions → Optimize Image with OfficeKit.' : 'Quick Action is not installed. Installation is optional.' });
      } catch (error) {
        available = false;
        install.disabled = true;
        remove.hidden = true;
        officekitOutcome.show(statusNode, { state: 'error', text: typeof error === 'string' ? error : error?.message || 'Finder Quick Action status is unavailable.' });
      } finally {
        busy = false;
        updateDisabled();
      }
    };
    const change = async (action, button) => {
      if (busy || !available) return;
      busy = true;
      updateDisabled();
      try {
        await invoke(action);
        await refresh();
      } catch (error) {
        officekitOutcome.show(statusNode, { state: 'error', text: typeof error === 'string' ? error : error?.message || 'Finder Quick Action could not be changed.' });
      } finally {
        busy = false;
        updateDisabled();
        button.disabled = !available;
      }
    };
    install.addEventListener('click', () => { void change('media_finder_action_install', install); });
    remove.addEventListener('click', () => { void change('media_finder_action_remove', remove); });
    void refresh();
  }
  async function addAudioSelection(selection) {
    if (state.running || !selection || !/^[0-9a-f-]{36}$/i.test(selection.id || '')) return false;
    let pendingSelection = selection;
    try {
      const response = await apiFetch(`/api/file-selections/${selection.id}`);
      if (!response.ok) throw Error('The selected audio file is no longer available. Choose it again.');
      const manifest = await response.json();
      if (manifest.access !== 'read') throw Error('Audio optimization requires a read-only file selection.');
      if (manifest.hasMore || !manifest.files?.length || manifest.files.length > 30) throw Error('Select between one and 30 audio files.');
      const supported = new Map([['wav', 'audio/wav'], ['mp3', 'audio/mpeg'], ['m4a', 'audio/mp4'], ['aiff', 'audio/aiff'], ['aif', 'audio/aiff'], ['flac', 'audio/flac'], ['caf', 'audio/x-caf']]);
      const files = manifest.files.map(file => {
        const extension = file.name.split('.').pop()?.toLowerCase();
        const mediaType = supported.get(extension);
        if (!mediaType) throw Error('Choose supported audio files only (WAV, MP3, M4A, AIFF, FLAC, or CAF).');
        if (!Number.isSafeInteger(file.size_bytes) || file.size_bytes < 1 || file.size_bytes > 64 * 1024 * 1024) throw Error('Each audio file must be between 1 byte and 64 MiB.');
        return { ...file, media_type: mediaType, selectionId: selection.id };
      });
      await clearSelections();
      if (state.stagedImage) await clearStagedImage();
      state.selection = selection; state.selections = [selection]; state.files = files; state.importPreview = null;
      $('url').value = ''; $('import-preview').classList.add('hidden'); $('import-summary').replaceChildren();
      pendingSelection = null;
      $('kind').value = 'audio';
      await setOperation('audio-optimize');
      setConverterMode('media_toolkit'); switchTab('converter');
      status(`${files.length} audio file${files.length === 1 ? '' : 's'} ready for optimization. Transcription remains separate; originals are unchanged.`);
      renderFiles();
      return true;
    } catch (error) {
      if (pendingSelection) { try { await apiFetch(`/api/file-selections/${pendingSelection.id}`, { method: 'DELETE' }); } catch {} }
      const statusNode = document.getElementById('dictation-audio-file-status');
      if (statusNode) officekitOutcome.show(statusNode, { state: 'error', text: error.message || 'The selected audio could not be opened in Media Toolkit.' });
      return false;
    }
  }
  async function chooseAudioFromTranscription() {
    const button = document.getElementById('dictation-audio-media-button');
    const statusNode = document.getElementById('dictation-audio-file-status');
    if (typeof window.__TAURI__?.core?.invoke !== 'function') {
      officekitOutcome.show(statusNode, { state: 'info', text: 'Choose audio in the OfficeKit desktop app to grant local file access.' });
      return;
    }
    button.disabled = true;
    officekitOutcome.show(statusNode, { state: 'info', text: 'Choose audio to prepare a separate optimized copy…' });
    try {
      const selection = await window.__TAURI__.core.invoke('file_selection_open', { mode: 'files', access: 'read', filterKind: 'audio' });
      if (!selection) { officekitOutcome.show(statusNode, { state: 'info', text: 'Audio selection canceled.' }); return; }
      if (!await addAudioSelection(selection)) return;
      officekitOutcome.show(statusNode, { state: 'info', text: 'Audio selected in Media Toolkit. Choose settings and prepare a copy; the original remains unchanged.' });
    } catch (error) {
      officekitOutcome.show(statusNode, { state: 'error', text: typeof error === 'string' ? error : (error?.message || 'The audio file could not be selected.') });
    } finally { button.disabled = false; }
  }
  async function previewImport() {
    const url = $('url').value.trim();
    if (!url) { officekitOutcome.show($('import-status'), { state: 'error', text: 'Enter a public HTTPS media link.' }); return; }
    const button = $('preview-url'); button.disabled = true; state.importPreview = null; renderFiles();
    $('import-preview').classList.add('hidden'); officekitOutcome.show($('import-status'), { state: 'working', text: 'Checking public link…' });
    try {
      const response = await apiFetch('/api/media-import-previews', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The link could not be previewed.'); }
      state.importPreview = await response.json();
      const preview = state.importPreview;
      const summary = $('import-summary'); summary.replaceChildren();
      const text = document.createElement('span');
      text.textContent = `${preview.host} · ${preview.contentType} · ${preview.sizeBytes == null ? 'size unknown' : window.OfficeKitFormatters.fileSize(preview.sizeBytes)} · expires in ${preview.expiresInSeconds} seconds`;
      summary.append(text); $('import-preview').classList.remove('hidden'); officekitOutcome.show($('import-status'), { state: 'success', text: 'Link preview ready. The file is not downloaded until you press Run.' });
      const kind = preview.contentType.startsWith('image/') ? 'image' : preview.contentType === 'application/pdf' ? 'pdf' : preview.contentType.startsWith('audio/') ? 'audio' : preview.contentType.startsWith('video/') ? 'video' : null;
      if (kind) { $('kind').value = kind; renderOperations(); }
      renderFiles();
    } catch (error) { officekitOutcome.show($('import-status'), { state: 'error', text: error.message || 'The public media link could not be previewed.' }); }
    finally { button.disabled = false; }
  }
  function renderCoverage() {
    const list = $('operation-list'); list.replaceChildren();
    let available = 0, total = 0;
    for (const media of state.capabilities.media) for (const operation of media.operations) {
      total += 1; if (operation.available) available += 1;
      const item = document.createElement('li'); item.className = 'flex items-start justify-between gap-2 border-b border-slate-200 pb-2';
      const label = document.createElement('span'); label.textContent = `${media.label}: ${operation.label}`;
      const badge = document.createElement('span'); badge.className = `badge badge-xs ${operation.available ? 'badge-success' : 'badge-ghost'}`; badge.textContent = operation.available ? 'Ready' : 'Planned';
      if (operation.reason) item.title = operation.reason;
      item.append(label, badge); list.append(item);
    }
    $('coverage').textContent = `${available} of ${total} operations available in this build.`;
  }
  async function chooseFiles() {
    if (typeof window.__TAURI__?.core?.invoke !== 'function') { status('Choose media from the OfficeKit desktop app to grant direct local access.'); return; }
    let pendingSelection = null;
    try {
      pendingSelection = await window.__TAURI__.core.invoke('file_selection_open', { mode: 'files', access: 'read' });
      if (!pendingSelection) return;
      const count = await acceptSelection(pendingSelection);
      pendingSelection = null;
      status(`${count} file${count === 1 ? '' : 's'} ready. The originals will not be modified.`);
    } catch (error) {
      if (pendingSelection) { try { await apiFetch(`/api/file-selections/${pendingSelection.id}`, { method: 'DELETE' }); } catch {} }
      status(error.message || 'The file selection could not be opened.');
    }
  }
  async function clearWatermark() {
    if (state.running) throw Error('Wait for preparation to finish before clearing the logo.');
    const watermark = state.watermark; state.watermark = null;
    $('watermark-file').value = '';
    if (watermark) {
      const response = await apiFetch(`/api/media-watermark-stagings/${watermark.stagingId}`, { method: 'DELETE' });
      if (!response.ok && response.status !== 404) throw Error('The logo could not be cleared. Its grant expires automatically.');
    }
    officekitOutcome.show($('watermark-status'), { state: 'info', text: 'No logo selected. Choose one before preparing a watermark copy.' });
  }
  async function stageWatermark() {
    const file = $('watermark-file').files?.[0];
    if (!file || state.running) return;
    const input = $('watermark-file'); input.disabled = true;
    try {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size < 1 || file.size > 5 * 1024 * 1024) throw Error('Choose a PNG, JPEG or WebP logo up to 5 MiB.');
      await clearWatermark();
      const body = new FormData(); body.append('file', file);
      const response = await apiFetch('/api/media-watermark-stagings', { method: 'POST', body });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(typeof payload.detail === 'string' ? payload.detail : 'The logo could not be staged. Choose a valid image and try again.');
      state.watermark = payload;
      officekitOutcome.show($('watermark-status'), { state: 'success', text: `${payload.filename} · ready for one job · expires in five minutes` });
    } catch (error) { officekitOutcome.show($('watermark-status'), { state: 'error', text: error.message || 'The logo could not be selected.' }); }
    finally { input.disabled = false; }
  }
  async function loadHandoffs() {
    if (typeof window.__TAURI__?.core?.invoke !== 'function') return;
    try { state.handoffs = await window.__TAURI__.core.invoke('media_handoff_capabilities'); }
    catch { state.handoffs = null; }
  }
  function appendHandoff(row, item) {
    if (!state.handoffs?.available) return;
    const controls = document.createElement('div'); controls.className = 'flex w-full flex-wrap items-center gap-2 border-t border-base-300 pt-2';
    const select = document.createElement('select'); select.className = 'select select-sm max-w-full'; select.setAttribute('aria-label', `Continue with another app for ${item.name}`);
    const choices = [{ value: '', label: 'Continue with another app…' }];
    for (const [value, available] of Object.entries(state.handoffs.apps || {})) if (available) choices.push({ value, label: value === 'dropshare' ? 'Upload with Dropshare…' : `Add to ${value[0].toUpperCase()}${value.slice(1)}` });
    for (const name of state.handoffs.shortcuts || []) choices.push({ value: `shortcut:${name}`, label: `Run Shortcut: ${name}` });
    for (const choice of choices) { const option = document.createElement('option'); option.value = choice.value; option.textContent = choice.label; select.append(option); }
    const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-outline btn-sm'; button.textContent = 'Save and continue…'; button.disabled = true;
    select.addEventListener('change', () => { button.disabled = !select.value; });
    const note = document.createElement('p'); note.className = 'w-full text-xs text-base-content/70'; note.textContent = choices.length > 1 ? 'Choose a save location first. Only the prepared copy is handed off.' : 'Install a supported shelf app, Dropshare, or an Apple Shortcut to enable handoff.';
    button.addEventListener('click', async () => {
      const value = select.value; if (!value) return;
      select.disabled = true; button.disabled = true;
      try {
        const shortcut = value.startsWith('shortcut:');
        const result = await window.__TAURI__.core.invoke('media_handoff_open', { artifactId: item.artifactId, suggestedName: item.outputName, destination: shortcut ? 'shortcut' : value, shortcutName: shortcut ? value.slice(9) : null });
        note.textContent = result.state === 'cancelled' ? 'Save cancelled. No handoff was requested.'
          : result.state === 'handoff-requested' ? 'Copy saved. Handoff requested; check the destination app for completion.'
            : 'Copy saved, but the handoff failed. You can open the saved copy manually.';
      } catch (error) { note.textContent = typeof error === 'string' ? error : error.message || 'The prepared copy could not be handed off.'; }
      finally { select.disabled = false; button.disabled = !select.value; }
    });
    controls.append(select, button, note); row.append(controls);
  }
  function renderResults(items) {
    state.lastItems = items;
    const currentArtifacts = new Set(items.map(item => item.artifactId).filter(Boolean));
    for (const artifactId of state.saveOutcomes.keys()) if (!currentArtifacts.has(artifactId)) state.saveOutcomes.delete(artifactId);
    const root = $('results'); root.replaceChildren();
    if (items.length) $('results-panel').open = true;
    syncNext();
    for (const item of items) {
      const row = document.createElement('div'); row.className = 'flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3';
      const detail = document.createElement('div'); detail.className = 'min-w-0 basis-full break-words';
      const title = document.createElement('p'); title.className = 'font-semibold'; title.textContent = item.name;
      const message = document.createElement('p'); message.className = 'text-xs text-slate-500';
      if (item.state === 'ready') {
        const saveOutcome = item.artifactId ? state.saveOutcomes.get(item.artifactId) : null;
        const attributes = item.attributes || {};
        const delta = Number.isSafeInteger(item.inputBytes) && item.inputBytes > 0 ? item.outputBytes === item.inputBytes ? ' · same size as original' : ` · ${Math.round(Math.abs(1 - item.outputBytes / item.inputBytes) * 100)}% ${item.outputBytes < item.inputBytes ? 'smaller' : 'larger'} than original` : '';
        const comparison = Number.isSafeInteger(item.inputBytes) ? ` · ${window.OfficeKitFormatters.fileSize(item.outputBytes)} from ${window.OfficeKitFormatters.fileSize(item.inputBytes)}${delta}` : ` · ${window.OfficeKitFormatters.fileSize(item.outputBytes)}`;
        const target = Number.isFinite(attributes.output_lufs)
          ? ` · ${attributes.output_lufs.toFixed(1)} LUFS · ${attributes.target_met ? 'loudness target met' : 'loudness target not met'}${Number.isFinite(attributes.true_peak_dbfs) ? ` · ${attributes.true_peak_dbfs.toFixed(2)} dBTP` : Number.isFinite(attributes.sample_peak_dbfs) ? ` · ${attributes.sample_peak_dbfs.toFixed(2)} dBFS sample peak` : ''}`
          : attributes.target_met === false ? ` · target not met (${window.OfficeKitFormatters.fileSize(item.outputBytes)} / ${window.OfficeKitFormatters.fileSize(attributes.target_bytes)})` : attributes.target_met === true ? ' · size target met' : '';
        const fidelity = attributes.visual_only ? ' · visual-only PDF; searchable text and interactive content removed' : '';
        const codec = attributes.codec === 'hevc' ? ' · HEVC video · MOV' : attributes.codec === 'av1' ? ' · AV1 video · MP4' : '';
        officekitOutcome.show(message, { state: 'info', text: `${comparison}${target}${fidelity}${codec} · original preserved` });
      } else officekitOutcome.show(message, { state: 'error', text: item.errorCode || item.state });
      detail.append(title, message); row.append(detail);
      const saveOutcome = item.artifactId ? state.saveOutcomes.get(item.artifactId) : null;
      if (saveOutcome?.state === 'missing') {
        const recovery = document.createElement('p'); recovery.className = 'text-xs font-medium text-error'; recovery.textContent = 'Retry this file to prepare a fresh copy.'; detail.append(recovery);
      }
      if (item.artifactId) {
        const saveOutcome = state.saveOutcomes.get(item.artifactId);
        if (saveOutcome?.state === 'saved' || saveOutcome?.state === 'download-started') {
          const saved = document.createElement('span'); saved.className = 'badge badge-success badge-outline badge-sm'; saved.textContent = saveOutcome.state === 'saved' ? 'Saved' : 'Download started'; row.append(saved);
        } else if (saveOutcome?.state === 'missing') {
          const unavailable = document.createElement('span'); unavailable.className = 'badge badge-error badge-outline badge-sm'; unavailable.textContent = 'Needs a new copy'; row.append(unavailable);
        } else {
          const download = document.createElement('button'); download.type = 'button'; download.className = 'btn btn-outline btn-sm'; download.textContent = 'Save';
          download.addEventListener('click', async () => { download.disabled = true; try { await saveOne(item); } finally { if (download.isConnected) download.disabled = false; } }); row.append(download); appendHandoff(row, item);
        }
      } else if (['failed', 'cancelled'].includes(item.state) && state.files.some(file => file.id === item.fileId)) {
        const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn btn-outline btn-sm'; retry.textContent = 'Retry';
        retry.disabled = state.running;
        retry.addEventListener('click', () => run({ retryFileId: item.fileId })); row.append(retry);
      }
      root.append(row);
    }
  }
  async function run({ retryFileId = null } = {}) {
    const operation = activeOperation();
    if (state.running || !selectedOperationsAvailable() || (!state.files.length && !state.importPreview && !state.stagedImage)) return;
    if (state.activePipeline && state.importPreview) { status('Public link imports are only available in a manual operation, not a saved pipeline.', 'error'); return; }
    if (!state.activePipeline) {
      try { if (!syncSettingsFromForm()) { status('Correct the highlighted operation settings before preparing files.', 'error'); return; } }
      catch { status('Operation settings must be a valid JSON object.', 'error', 'Correct them in Advanced settings.'); return; }
    }
    let options;
    try { options = state.activePipeline ? null : readOptions(); if (!state.activePipeline && (!options || Array.isArray(options) || typeof options !== 'object')) throw Error(); }
    catch { status('Enter operation settings as a JSON object.', 'error'); return; }
    if (state.activePipeline) {
      const kind = state.activePipeline.media;
      if (state.files.filter(file => retryFileId ? file.id === retryFileId : file.checked !== false).some(file => !mediaTypeMatchesKind(kind, file.media_type)) || (!retryFileId && state.stagedImage && kind !== 'image')) {
        status(`The selected files do not all match the ${kind} pipeline.`, 'error'); return;
      }
    }
    const operations = selectedOperations();
    if (!state.activePipeline) rememberSettings();
    const files = state.files.filter(file => retryFileId ? file.id === retryFileId : file.checked !== false);
    let items;
    try {
      items = files.map(file => ({ source: { kind: 'selection', selectionId: file.selectionId, fileId: file.id }, operations: operationsForFile(file),
        ...(state.activePipeline?.outputNameTemplate ? { outputNameTemplate: state.activePipeline.outputNameTemplate } : {}) }));
      if (items.some(item => item.operations.some(step => !operationById(step.operationId)?.available))) throw Error('One selected media type has no available operation. Review its settings.');
    } catch (error) { status(error.message, 'error'); return; }
    if (!retryFileId && state.importPreview) items.push({ source: { kind: 'import', importId: state.importPreview.importId }, operations });
    if (!retryFileId && state.stagedImage) items.push({ source: { kind: 'staged-image', stagingId: state.stagedImage.stagingId }, operations });
    if (!items.length) { status('Select at least one file to prepare.', 'error'); return; }
    const overlay = items.some(item => item.operations.some(step => step.operationId.endsWith('watermark-overlay')));
    if (overlay && !state.watermark) { status('Choose a logo before preparing watermark copies.', 'error', 'Each logo grant is used for one job.'); return; }
    state.retainedItems = retryFileId ? state.lastItems.filter(item => item.fileId !== retryFileId) : [];
    if (retryFileId) {
      const previous = state.lastItems.find(item => item.fileId === retryFileId);
      if (previous?.artifactId) state.saveOutcomes.delete(previous.artifactId);
    } else state.saveOutcomes.clear();
    state.running = true; syncMediaDrop(); state.jobId = null; $('cancel').disabled = false; $('run').disabled = true; $('results').replaceChildren(); status('Submitting local media job…', 'working');
    renderFiles();
    try {
      const response = await apiFetch('/api/media-jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items, ...(overlay ? { watermarkStagingId: state.watermark.stagingId } : {}) }) });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw Error(payload.detail || 'The media job could not be submitted.'); }
      state.jobId = (await response.json()).id;
      if (overlay) { state.watermark = null; officekitOutcome.show($('watermark-status'), { state: 'success', text: 'Logo submitted for this job. Choose it again for another run.' }); }
      if (!retryFileId && state.importPreview) { state.importPreview = null; $('url').value = ''; $('import-preview').classList.add('hidden'); $('import-summary').replaceChildren(); officekitOutcome.show($('import-status'), { state: 'success', text: 'One-use link grant submitted. The file is fetched only for this job.' }); renderFiles(); }
      if (!retryFileId && state.stagedImage) { state.stagedImage = null; renderFiles(); }
      const activity = window.OfficeKitActivity?.start({ id: `media-${state.jobId}`, title: state.activePipeline?.name || operation.label, tool: 'Media Toolkit', tab: 'converter', phase: 'Queued', progress: 0, total: state.files.length, cancel: cancel, returnTo: () => { setConverterMode('media_toolkit'); switchTab('converter'); } });
      while (state.jobId) {
        const result = await (await apiFetch(`/api/media-jobs/${state.jobId}`)).json();
        status(`${result.phase} · ${result.progress} of ${result.total} files`, 'working');
        activity?.update({ state: ['ready', 'partial', 'failed', 'cancelled'].includes(result.state) ? 'complete' : result.state, phase: result.phase, progress: result.progress, total: result.total, percent: result.total ? result.progress / result.total * 100 : null });
        renderResults([...state.retainedItems, ...result.items]);
        if (['ready', 'partial', 'failed', 'cancelled'].includes(result.state)) {
          if (result.state === 'ready') status('Results are ready. Save each one below.', 'success');
          else status(`Job ${result.state}.`, result.state === 'cancelled' ? 'info' : 'error', result.state === 'cancelled' ? '' : 'Review each file result below.');
          const recent = $('recent-summary');
          if (recent) recent.textContent = `${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${state.activePipeline?.name || operation.label} · ${result.progress} of ${result.total} files · ${result.state}. Detailed results are shown in Prepare.`;
          activity?.finish({ state: result.state === 'failed' ? 'failed' : result.state === 'cancelled' ? 'cancelled' : 'complete', phase: result.state, percent: 100, summary: 'Review the per-file results in Media Toolkit.' });
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 350));
      }
    } catch (error) { status(error.message || 'The media job could not be completed.', 'error'); }
    finally { state.running = false; state.finished = Boolean(state.jobId); syncMediaDrop(); $('cancel').disabled = true; renderFiles(); renderResults(state.lastItems); }
  }
  async function cancel() {
    if (!state.jobId) return;
    try { await apiFetch(`/api/media-jobs/${state.jobId}/cancellations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); status('Cancellation requested.', 'working', 'OfficeKit keeps any copies already prepared.'); }
    catch (error) { status(error.message || 'Cancellation could not be requested.', 'error'); }
  }
  async function reset() {
    if (state.running) { status('Finish or cancel the current job before clearing its selection.', 'error'); return; }
    await clearSelections();
    try { await clearWatermark(); } catch (error) { status(error.message); }
    state.lastItems = []; state.retainedItems = []; state.kindDrafts = {}; state.finished = false;
    state.saveOutcomes.clear();
    if (state.stagedImage) { const staged = state.stagedImage; state.stagedImage = null; try { await apiFetch(`/api/media-image-stagings/${staged.stagingId}`, { method: 'DELETE' }); } catch {} }
    state.files = []; state.importPreview = null; state.activePipeline = null; $('url').value = ''; $('import-preview').classList.add('hidden'); $('import-summary').replaceChildren(); officekitOutcome.show($('import-status'), { state: 'error', text: '' }); $('results').replaceChildren(); renderPipelines(); renderFiles(); status('Selection cleared. Original files and prepared copies remain in place.');
  }
  async function init() {
    if (!$('kind')) return;
    if (initPromise) return initPromise;
    $('kind').addEventListener('change', () => { state.finished = false; try { syncSettingsFromForm(); rememberSettings(); } catch {} state.activePipeline = null; renderPipelines(); renderOperations(); renderFiles(); });
    $('operation').addEventListener('change', () => {
      state.finished = false;
      // Save the operation that was on screen before the change: its settings are still in the form.
      if (!state.activePipeline && state.renderedOperationId) { try { state.kindDrafts[state.editingKind] = { operationId: state.renderedOperationId, options: readOptions() }; } catch {} }
      state.activePipeline = null; renderPipelines(); renderOperations(); rememberSettings(); renderFiles();
    });
    $('watermark-file').addEventListener('change', stageWatermark);
    $('watermark-clear').addEventListener('click', () => { void clearWatermark().catch(error => status(error.message)); });
    void loadHandoffs();
    $('settings-fields').addEventListener('input', () => { try { syncSettingsFromForm(); } catch {} });
    $('settings-fields').addEventListener('change', () => { try { syncSettingsFromForm(); } catch {} });
    $('options').addEventListener('input', () => { renderSettings(); });
    $('result-format').addEventListener('change', event => setResultFormat(event.currentTarget.value));
    $('save-local-default').addEventListener('click', storeCurrentLocalDefault);
    $('local-default-search').addEventListener('input', renderLocalDefaults);
    $('clear-local-defaults').addEventListener('click', clearLocalDefaults);
    const showView = view => {
      const automations = view === 'automations';
      $('prepare-view').classList.toggle('hidden', automations);
      $('automations-view').classList.toggle('hidden', !automations);
      $('tab-prepare').classList.toggle('btn-primary', !automations);
      $('tab-prepare').classList.toggle('btn-outline', automations);
      $('tab-automations').classList.toggle('btn-primary', automations);
      $('tab-automations').classList.toggle('btn-outline', !automations);
      $('tab-prepare').setAttribute('aria-pressed', String(!automations));
      $('tab-automations').setAttribute('aria-pressed', String(automations));
    };
    $('tab-prepare').addEventListener('click', () => showView('prepare'));
    $('tab-automations').addEventListener('click', () => showView('automations'));
    $('folder-pipeline').addEventListener('change', renderFolderWatches);
    $('folder-add').addEventListener('click', addFolderWatch);
    $('zone-pipeline').addEventListener('change', renderPresetZones);
    $('zone-create').addEventListener('click', createPresetZone);
    void refreshPresetZones();
    void refreshFolderWatches();
    window.setInterval(() => { if (state.folderWatches.length) void refreshFolderWatches(); }, 2000);
    initClipboardAutomation();
    initClipboardHotkey();
    initFinderAction();
    $('select').addEventListener('click', event => { event.preventDefault(); if (!state.running) chooseFiles(); }); $('preview-url').addEventListener('click', previewImport); $('clear-url').addEventListener('click', clearImport); $('run').addEventListener('click', () => {
      const missing = state.lastItems.find(item => item.state === 'ready' && item.artifactId && state.saveOutcomes.get(item.artifactId)?.state === 'missing' && state.files.some(file => file.id === item.fileId));
      void run(missing ? { retryFileId: missing.fileId } : {});
    }); $('cancel').addEventListener('click', cancel); $('reset').addEventListener('click', reset);
    $('save').addEventListener('click', () => { void saveReady(); });
    $('next-action').addEventListener('click', () => {
      const mode = $('next-action').dataset.mode;
      if (mode === 'running') void cancel();
      else if (mode === 'done') { const panel = $('results-panel'); panel.open = true; panel.scrollIntoView({ block: 'nearest' }); $('results').querySelector('button')?.focus(); }
      else void run();
    });
    $('pipeline-add-step').addEventListener('click', addPipelineStep); $('pipeline-save').addEventListener('click', savePipeline);
    void enableMediaDrop();
    initPromise = (async () => {
      try {
        state.capabilities = await (await apiFetch('/api/media-capabilities')).json();
        try { await loadLocalDefaults(); }
        catch (error) { state.localDefaults = {}; officekitOutcome.show($('local-default-status'), { state: 'error', text: error.message || 'Saved operation defaults could not be loaded.' }); }
        renderCoverage(); renderOperations(); renderLocalDefaults(); renderPipelineDraft(); await loadPipelines();
      }
      catch (error) { $('capability').textContent = error.message || 'Operation availability could not be loaded.'; $('coverage').textContent = 'Availability unavailable.'; }
    })();
    window.officekitMediaReady = initPromise;
    return initPromise;
  }
  async function setOperation(operationId) {
    await init();
    const operation = state.capabilities?.media.flatMap(media => media.operations).find(entry => entry.id === operationId);
    if (!operation) return false;
    state.activePipeline = null; renderPipelines();
    $('kind').value = operation.id.split('-')[0];
    renderOperations(); $('operation').value = operation.id;
    $('options').value = JSON.stringify(state.localDefaults[operation.id] || defaults[operation.id] || {}, null, 2);
    renderOperations();
    return true;
  }
  document.getElementById('dictation-audio-media-button')?.addEventListener('click', chooseAudioFromTranscription);
  window.officekitMediaReady = null;
  // The drop-target registration is a paid native command; it can be rejected while the licence is still
  // being checked at launch. The shell announces the move to active once, so register again then.
  window.addEventListener('officekit-license-active', () => { syncMediaDrop(); });
  window.officekitMediaToolkit = { init, chooseFiles, reset, setOperation, acceptSelection, addStagedImage, addAudioSelection, prepareClipboardImage };
})();
