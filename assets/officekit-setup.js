(function (global) {
  'use strict';

  const DONE_KEY = 'officekit.setup.done_v1';
  // Matches the saved file's setup version; bump both when setup gains a step existing users should see.
  const SETUP_VERSION = 1;
  const MODEL_POLL_MS = 1000;
  const STATUS_POLL_MS = 1500;

  // Each permission lists the features that stop working without it. The same text feeds the setup
  // dialog and the banners on the feature pages, so the two never disagree.
  const PERMISSIONS = [
    {
      id: 'microphone', label: 'Microphone', status: 'dictation_microphone_permission',
      request: 'dictation_request_microphone_permission', settings: 'microphone',
      features: ['Speech to text', 'Speech Coach', 'Listen In', 'Meeting Recorder'],
      missing: 'Speech to text and Speech Coach cannot hear you without it.',
    },
    {
      id: 'accessibility', label: 'Accessibility', status: 'dictation_accessibility_permission',
      request: 'dictation_request_accessibility_permission', settings: 'accessibility',
      features: ['Launcher paste', 'Clipboard paste', 'Snippet expansion', 'Window layouts', 'Typing dictation into other apps'],
      missing: 'Pasting into other apps, snippet expansion and window layouts need it.',
    },
    {
      id: 'screen', label: 'Screen Recording', status: 'dictation_screen_recording_permission',
      request: 'dictation_request_screen_recording_permission', settings: 'screen',
      features: ['Screenshot capture', 'Meeting Recorder (system audio)'],
      missing: 'Screenshot capture and meeting system audio need it. Choosing a file still works.',
    },
    {
      id: 'calendar', label: 'Calendar', optional: true, status: 'calendar_permission_status',
      request: 'calendar_permission_request', settings: 'calendar', features: ['Meeting reminders'],
      missing: 'Meeting reminders cannot read your calendar without it.',
    },
  ];

  // Tools switched on in step 3. Only the first three need a permission before they work.
  const TOOLS = [
    // One switch in the app: the launcher, clipboard history and snippets share the desktop setting.
    { id: 'desktop', label: 'Launcher, clipboard history and snippets', note: 'Find apps and tools · save what you copy · expand ;keywords', key: '⌃⌥Space · ⌘⌥V', needs: 'accessibility', on: true },
    { id: 'windows', label: 'Window layouts', note: 'Halves, corners, maximize', key: '⌃⌥←', needs: 'accessibility', on: true },
    { id: 'dictation', label: 'Speech to text shortcut', note: 'Hold a key to dictate anywhere', key: 'Left ⌥', needs: 'microphone', on: false },
    { id: 'login', label: 'Open at login', note: 'So these are always ready', key: '', needs: null, on: true },
  ];

  // The same models as the Speech model card. Sizes are the download, not the disk use.
  const MODELS = [
    { id: 'parakeet_v3', label: 'Parakeet v3', size: '460 MB', note: 'Recommended · 25 European languages · fastest to download' },
    { id: 'parakeet_v2', label: 'Parakeet v2', size: '', note: 'English only' },
    { id: 'qwen3_asr', label: 'Qwen3 ASR 0.6B', size: '', note: 'Wider language coverage' },
    { id: 'whisper_base', label: 'Whisper Base', size: '148 MB', note: 'Multilingual · smallest' },
    { id: 'whisper_small', label: 'Whisper Small', size: '488 MB', note: 'Multilingual' },
    { id: 'whisper_medium', label: 'Whisper Medium', size: '1.54 GB', note: 'Multilingual · English translation' },
    { id: 'whisper_large_v3', label: 'Whisper Large v3', size: '3.10 GB', note: 'Multilingual · most accurate · English translation' },
    { id: 'whisper_large_v3_turbo', label: 'Whisper Large v3 Turbo', size: '1.63 GB', note: 'Multilingual · fast' },
  ];
  const DEFAULT_MODEL = 'parakeet_v3';

  const state = { step: 0, modelChoice: DEFAULT_MODEL, access: {}, tools: {}, model: null, busy: false, timer: null, root: null, invoke: null };

  const invoke = () => global.__TAURI__?.core?.invoke;
  const escapeText = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  const permissionById = id => PERMISSIONS.find(permission => permission.id === id);

  function storage() {
    try { return global.localStorage; } catch (_) { return null; }
  }

  function localDone() {
    return storage()?.getItem(DONE_KEY) === 'true';
  }

  // The saved file in the app data folder is the source of truth; local storage is only the fallback
  // when the native side is missing, and the source of a one-time carry-over for earlier installs.
  async function readSaved() {
    if (!invoke()) return null;
    try { return await invoke()('app_settings_status'); } catch (_) { return null; }
  }

  async function saveSettings(update) {
    if (!invoke()) return null;
    try { return await invoke()('app_settings_save', { update }); } catch (_) { return null; }
  }

  async function isDone() {
    const saved = await readSaved();
    if (!saved) return localDone();
    if (!saved.setupDone && localDone()) {
      await saveSettings({ setupDone: true, setupCompletedAt: today() });
      return true;
    }
    return saved.setupDone === true && saved.setupVersion >= SETUP_VERSION;
  }

  const today = () => new Date().toISOString().slice(0, 10);

  async function markDone() {
    try { storage()?.setItem(DONE_KEY, 'true'); } catch (_) {}
    await saveSettings({ setupDone: true, setupCompletedAt: today() });
  }

  // granted · undetermined (macOS has not asked yet) · denied · unknown (no way to read it)
  async function readPermission(permission) {
    if (!permission.status || !invoke()) return 'unknown';
    try {
      const result = await invoke()(permission.status);
      if (result?.permission === 'granted') return 'granted';
      return result?.permission === 'undetermined' ? 'undetermined' : 'denied';
    } catch (_) {
      return 'unknown';
    }
  }

  const isMissing = status => status === 'undetermined' || status === 'denied';

  async function refreshAccess() {
    const next = {};
    await Promise.all(PERMISSIONS.map(async permission => { next[permission.id] = await readPermission(permission); }));
    state.access = next;
    return next;
  }

  async function allow(id) {
    const permission = permissionById(id);
    if (!permission || !invoke()) return;
    try { await invoke()(permission.request); } catch (_) {}
    await refreshAccess();
    render();
    refreshBanners();
  }

  async function openSettings(id) {
    const permission = permissionById(id);
    if (!permission || !invoke()) return;
    try { await invoke()('dictation_open_permission_settings', { kind: permission.settings }); } catch (_) {}
  }

  // Microphone and Calendar report "not asked yet" and "denied", so they can tell when macOS has stopped asking.
  const reportsAskedState = id => id === 'microphone' || id === 'calendar';

  // What a row or banner offers: null (nothing to do), 'allow' (macOS can still ask) or 'settings'.
  // After a refusal only System Settings can change it.
  function accessAction(id) {
    const status = state.access[id];
    if (status === 'granted') return null;
    if (reportsAskedState(id)) return status === 'denied' ? 'settings' : 'allow';
    return isMissing(status) ? 'allow' : null;
  }

  // Accessibility and Screen Recording are decided in System Settings, so after the prompt we open it.
  async function requestAccess(id) {
    if (accessAction(id) === 'settings') { await openSettings(id); return; }
    await allow(id);
    if (!reportsAskedState(id) && isMissing(state.access[id])) await openSettings(id);
  }

  async function readModel() {
    if (!invoke()) return null;
    try { return await invoke()('dictation_model_status'); } catch (_) { return null; }
  }

  function modelSummary(model) {
    if (!model) return { ready: false, busy: false, text: 'Checking the local model…', fraction: null };
    const ready = model.state === 'ready' || model.state === 'installed';
    const busy = model.state === 'preparing';
    const fraction = typeof model.progress?.fraction === 'number' ? Math.round(model.progress.fraction * 100) : null;
    let text = model.message || '';
    if (busy && model.progress?.bytes_total) {
      const mb = value => Math.round(value / 1048576);
      text = `Downloading… ${fraction ?? 0}% · ${mb(model.progress.bytes_downloaded || 0)} of ${mb(model.progress.bytes_total)} MB`;
    } else if (ready) {
      text = 'Model ready. Speech to text works offline.';
    }
    return { ready, busy, text, fraction };
  }

  async function startDownload() {
    if (!invoke()) return;
    state.busy = true;
    try {
      if (state.model?.model_id !== state.modelChoice) await invoke()('dictation_model_select', { modelId: state.modelChoice });
      await saveSettings({ modelId: state.modelChoice });
    } catch (error) {
      state.model = { state: 'failed', message: String(error?.message || error || 'The model could not be chosen. Try again.') };
      state.busy = false;
      render();
      return;
    }
    // The download keeps going in the background: setup moves on at once and shows its progress.
    invoke()('dictation_prepare_model')
      .then(status => { state.model = status; })
      .catch(error => { state.model = { state: 'failed', message: String(error?.message || error || 'Download failed. Try again.') }; })
      .finally(() => { state.busy = false; render(); pollModel(); });
    state.model = { ...(state.model || {}), model_id: state.modelChoice, state: 'preparing', message: 'Starting the download…', progress: null };
    render();
    pollModel();
  }

  function pollModel() {
    clearTimeout(state.timer);
    if (!state.root) return;
    state.timer = setTimeout(async () => {
      state.model = await readModel();
      render();
      if (state.model?.state === 'preparing') pollModel();
    }, MODEL_POLL_MS);
  }

  async function applyTools() {
    if (!invoke()) return;
    const on = id => !!state.tools[id];
    const granted = id => state.access[id] === 'granted';
    // A tool whose permission was skipped stays off; its page offers the Allow button later.
    const allowed = tool => on(tool.id) && (!tool.needs || granted(tool.needs));
    try {
      const status = await invoke()('global_desktop_status');
      const settings = {
        ...status.settings,
        enabled: allowed(TOOLS[0]),
        windowsEnabled: allowed(TOOLS[1]),
        openAtLogin: on('login'),
      };
      await invoke()('global_desktop_configure', { settings });
    } catch (_) {}
    await setDictationShortcut(allowed(TOOLS[2]));
  }

  // Same calls the Speech to text page makes, plus its saved "restore on launch" flag.
  const HOTKEY_WISH_KEY = 'officekit.dictation.hotkey-enabled';

  // "Turn it on" is remembered first: the shortcut needs the model ready, and the Speech to text page
  // turns it on by itself as soon as it is. Returns true, 'pending' (wanted, waiting on the model) or false.
  async function setDictationShortcut(enabled) {
    if (!invoke()) return false;
    if (typeof global.persistDictationHotkeyEnabled === 'function') global.persistDictationHotkeyEnabled(enabled);
    try {
      const status = await invoke()('dictation_hotkey_status');
      if (enabled && status.state === 'disabled') {
        await global.enablePreparedDictationHotkey();
      }
      if (!enabled && status.state !== 'disabled') await invoke()('dictation_hotkey_disable');
      return true;
    } catch (_) {
      return enabled ? 'pending' : false;
    }
  }

  function dictationWished() {
    try { return global.localStorage.getItem(HOTKEY_WISH_KEY) === 'true'; } catch (_) { return false; }
  }

  // What is actually switched on right now, and the real shortcut keys. Setup, Settings and the tool pages
  // all read this, so none of them shows a state the others do not.
  async function readTools() {
    const read = async command => { try { return await invoke()(command); } catch (_) { return null; } };
    const [desktop, hotkey] = invoke() ? await Promise.all([read('global_desktop_status'), read('dictation_hotkey_status')]) : [null, null];
    const settings = desktop?.settings || null;
    const label = global.officekitGlobalDesktop?.shortcutLabel;
    const keysOf = actions => (label && settings ? actions.map(action => settings.shortcuts?.[action]).filter(Boolean).map(label).join(' · ') : '');
    const hotkeyLabel = typeof global.dictationHotkeyLabel === 'function' && hotkey ? global.dictationHotkeyLabel(hotkey.key, hotkey.custom_binding) : '';
    const hotkeyOn = !!hotkey && hotkey.state !== 'disabled';
    return {
      settings,
      hotkeyState: hotkey?.state || 'disabled',
      pending: !hotkeyOn && dictationWished(),
      on: { desktop: !!settings?.enabled, windows: !!settings?.windowsEnabled, login: !!settings?.openAtLogin, dictation: hotkeyOn || dictationWished() },
      keys: { desktop: keysOf(['launcher.open', 'clipboard.history']), windows: keysOf(['window.left-half']), dictation: hotkeyLabel },
    };
  }

  // The switches start from what is on now. A first run also offers the defaults; a re-run shows exactly what is on.
  async function syncTools() {
    const [actual, saved] = await Promise.all([readTools(), readSaved()]);
    state.keys = actual.keys;
    const rerun = saved?.setupDone === true;
    state.tools = Object.fromEntries(TOOLS.map(tool => [tool.id, rerun ? !!actual.on[tool.id] : (tool.on || !!actual.on[tool.id])]));
    if (state.step === 1) render();
  }

  function stepsBar() {
    return `<div class="ok-setup-steps" aria-hidden="true">${[0, 1, 2].map(index => `<i class="${index <= state.step ? 'on' : ''}"></i>`).join('')}</div>`;
  }

  function modelOption(model, locked) {
    const checked = state.modelChoice === model.id;
    const title = model.size ? `${model.label} · ${model.size}` : model.label;
    return `<label class="ok-setup-row ok-setup-model${checked ? ' on' : ''}"><input type="radio" name="ok-setup-model" value="${model.id}" data-model="${model.id}"${checked ? ' checked' : ''}${locked ? ' disabled' : ''}><span class="ok-setup-copy"><strong>${title}</strong><small>${model.note}</small></span></label>`;
  }

  function renderModel() {
    const summary = modelSummary(state.model);
    const locked = summary.busy || state.busy || summary.ready;
    const failed = state.model?.state === 'failed';
    const progress = summary.busy
      ? `<div class="ok-setup-bar" role="progressbar" aria-label="Speech model download" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${summary.fraction ?? 0}"><b style="width:${summary.fraction ?? 0}%"></b></div>`
      : '';
    // The download is the last step because the earlier ones may need the app restarted, which would stop it.
    // A download that is already running never blocks the user: Finish sits where Download was.
    const primary = summary.ready || summary.busy
      ? '<button type="button" class="btn btn-primary" data-setup="finish">Finish</button>'
      : `<button type="button" class="btn btn-primary" data-setup="download"${state.busy ? ' disabled' : ''}>${failed ? 'Retry download' : 'Download'}</button>`;
    const keepsGoing = summary.busy ? ' It keeps going if you close setup.' : '';
    const failure = failed ? `Speech model download failed: ${state.model.message || 'try again from Settings.'}` : `${summary.text}${keepsGoing}`;
    return `
      ${stepsBar()}
      <h2 id="ok-setup-title">Download a speech model</h2>
      <p>Speech to text and Speech Coach run on this Mac. Pick a model once; audio never leaves your device. The download keeps going in the background after you finish.</p>
      <div class="ok-setup-models" role="radiogroup" aria-label="Speech model">${MODELS.map(model => modelOption(model, locked)).join('')}</div>
      ${progress}
      <p class="ok-setup-status" role="status" aria-live="polite" data-download-strip>${escapeText(failure)}</p>
      <div class="ok-setup-actions"><button type="button" class="btn btn-ghost" data-setup="finish">Skip for now</button>${primary}</div>`;
  }

  function accessRow(permission) {
    const status = state.access[permission.id];
    const granted = status === 'granted';
    const chips = permission.features.map(name => `<em>${escapeText(name)}</em>`).join('');
    const label = accessAction(permission.id) === 'settings' ? 'Open System Settings' : 'Allow';
    const action = granted
      ? '<span class="ok-setup-chip ok">Allowed</span>'
      : `<button type="button" class="btn btn-sm${permission.optional ? ' btn-ghost' : ''}" data-setup="allow" data-permission="${permission.id}">${label}</button>`;
    return `<div class="ok-setup-perm" data-permission-row="${permission.id}">
      <div class="ok-setup-prow"><span class="ok-setup-copy"><strong>${permission.label}</strong>${permission.optional ? '<small>Optional</small>' : ''}</span>${action}</div>
      <div class="ok-setup-feats"><span>Needed for</span>${chips}</div></div>`;
  }

  function renderAccess() {
    return `
      ${stepsBar()}
      <h2 id="ok-setup-title">What OfficeKit needs, and why</h2>
      <p>Each item says which features stop working without it. macOS asks once; change any of them later in System Settings.</p>
      ${PERMISSIONS.map(accessRow).join('')}
      <p class="ok-setup-fine">Not asked now: Files and folders (asked when you pick a file), Finder control for Trash commands (first use) and AirPods motion (only if you turn on head-angle reminders).</p>
      <div class="ok-setup-actions"><button type="button" class="btn btn-ghost" data-setup="next">Skip for now</button><button type="button" class="btn btn-primary" data-setup="next">Continue</button></div>`;
  }

  function toolRow(tool) {
    const missing = tool.needs && state.access[tool.needs] !== 'granted';
    const note = missing ? `Needs ${permissionById(tool.needs).label} · allow it in the previous step` : tool.note;
    const checked = !!state.tools[tool.id] && !missing;
    return `<label class="ok-setup-row"><span class="ok-setup-copy"><strong>${tool.label}</strong><small class="${missing ? 'warn' : ''}">${escapeText(note)}</small></span>${state.keys?.[tool.id] ? `<span class="ok-setup-key">${escapeText(state.keys[tool.id])}</span>` : ''}<input class="toggle" type="checkbox" data-tool="${tool.id}" aria-label="${escapeText(tool.label)}"${checked ? ' checked' : ''}${missing ? ' disabled' : ''}></label>`;
  }

  function renderTools() {
    return `
      ${stepsBar()}
      <h2 id="ok-setup-title">Choose what runs in the background</h2>
      <p>These work in every app. You can change them any time in Settings.</p>
      ${TOOLS.map(toolRow).join('')}
      <div class="ok-setup-actions"><button type="button" class="btn btn-primary" data-setup="apply">Continue</button></div>`;
  }

  function render() {
    if (!state.root) return;
    const body = [renderAccess, renderTools, renderModel][state.step]();
    // The download and access polls call this every second: skip identical markup, and keep the scroll
    // position and focus when only the numbers changed, so the page never jumps back or steals focus.
    if (body === state.lastBody && state.lastStep === state.step) return;
    const dialog = state.root.querySelector('.ok-setup-dialog');
    const sameStep = state.lastStep === state.step;
    const list = dialog.querySelector('.ok-setup-models');
    const scroll = sameStep ? { dialog: dialog.scrollTop, list: list?.scrollTop ?? 0 } : null;
    const active = sameStep ? focusSelector(global.document.activeElement, dialog) : null;
    state.lastBody = body;
    state.lastStep = state.step;
    dialog.innerHTML = body;
    if (scroll) {
      dialog.scrollTop = scroll.dialog;
      const next = dialog.querySelector('.ok-setup-models');
      if (next) next.scrollTop = scroll.list;
    }
    if (active) dialog.querySelectorAll(active.selector)[active.index]?.focus({ preventScroll: true });
  }

  // A selector for the focused control, built from the data attributes the dialog gives its controls.
  function focusSelector(element, dialog) {
    if (!element || element === global.document.body || !dialog.contains(element)) return null;
    for (const name of ['data-setup', 'data-tool', 'data-model']) {
      const value = element.getAttribute?.(name);
      if (value === null || value === undefined) continue;
      const permission = element.getAttribute('data-permission');
      const selector = `[${name}="${value}"]${permission ? `[data-permission="${permission}"]` : ''}`;
      // Skip and Finish share a data-setup value, so keep the position among the matches too.
      return { selector, index: [...dialog.querySelectorAll(selector)].indexOf(element) };
    }
    return null;
  }

  function close() {
    clearTimeout(state.timer);
    clearInterval(state.poller);
    state.root?.remove();
    state.root = null;
    global.document.removeEventListener('keydown', onKey, true);
    global.document.dispatchEvent(new CustomEvent('officekit:setup-closed'));
  }

  // Tool choices are applied when that step is left, so they hold even if the app has to be restarted afterwards.
  async function finish() {
    markDone();
    close();
    refreshBanners();
  }

  function onKey(event) {
    if (event.key === 'Escape') { markDone(); close(); }
  }

  async function onClick(event) {
    const target = event.target.closest('[data-setup]');
    if (!target) return;
    event.preventDefault();
    const action = target.dataset.setup;
    if (action === 'next') {
      state.step = Math.min(2, state.step + 1);
      render();
    } else if (action === 'apply') {
      await applyTools();
      state.step = 2;
      render();
    } else if (action === 'download') {
      await startDownload();
    } else if (action === 'allow') {
      await requestAccess(permissionById(target.dataset.permission).id);
    } else if (action === 'finish') {
      await finish();
    }
  }

  function onChange(event) {
    const input = event.target.closest('[data-tool]');
    if (input) state.tools[input.dataset.tool] = input.checked;
    const model = event.target.closest('[data-model]');
    if (model && MODELS.some(entry => entry.id === model.dataset.model)) {
      state.modelChoice = model.dataset.model;
      render();
    }
  }

  async function open(options = {}) {
    if (state.root || !global.document) return;
    state.step = 0;
    state.tools = Object.fromEntries(TOOLS.map(tool => [tool.id, tool.on]));
    const root = global.document.createElement('div');
    root.className = 'ok-setup-backdrop';
    root.id = 'officekit-setup';
    root.innerHTML = '<div class="ok-setup-dialog" role="dialog" aria-modal="true" aria-labelledby="ok-setup-title"></div>';
    root.addEventListener('click', onClick);
    root.addEventListener('change', onChange);
    global.document.body.append(root);
    global.document.addEventListener('keydown', onKey, true);
    state.root = root;
    state.lastBody = null;
    state.lastStep = null;
    render();
    await refreshAccess();
    await syncTools();
    state.model = await readModel();
    // A model already chosen in the app stays chosen.
    if (state.model && MODELS.some(entry => entry.id === state.model.model_id)) state.modelChoice = state.model.model_id;
    render();
    // Coming back from System Settings: re-read access so the Allow buttons turn into "Allowed".
    state.poller = setInterval(async () => { await refreshAccess(); render(); }, STATUS_POLL_MS);
    if (state.model?.state === 'preparing') pollModel();
    if (options.focus !== false) root.querySelector('button')?.focus();
  }

  // Feature pages mark where their banner goes: <div data-access-banner="accessibility" data-access-text="..."></div>
  function bannerHtml(permission, text) {
    const label = `Needs ${permission.label} access`;
    const button = accessAction(permission.id) === 'allow'
      ? `<button type="button" class="btn btn-sm" data-banner-allow="${permission.id}">Allow</button>`
      : `<button type="button" class="btn btn-sm" data-banner-settings="${permission.id}">Open System Settings</button>`;
    return `<div class="ok-access-banner" role="status"><span class="ok-access-icon" aria-hidden="true">!</span><span class="ok-setup-copy"><strong>${label}</strong><small>${escapeText(text)}</small></span>${button}</div>`;
  }

  async function refreshBanners() {
    const nodes = [...global.document.querySelectorAll('[data-access-banner]')];
    if (!nodes.length) return;
    await refreshAccess();
    for (const node of nodes) {
      const permission = permissionById(node.dataset.accessBanner);
      const missing = permission && isMissing(state.access[permission.id]);
      node.hidden = !missing;
      node.innerHTML = missing ? bannerHtml(permission, node.dataset.accessText || permission.missing) : '';
    }
  }

  function onBannerClick(event) {
    const allowButton = event.target.closest('[data-banner-allow]');
    const settingsButton = event.target.closest('[data-banner-settings]');
    if (allowButton) {
      const permission = permissionById(allowButton.dataset.bannerAllow);
      requestAccess(permission.id).then(refreshBanners);
    } else if (settingsButton) {
      openSettings(settingsButton.dataset.bannerSettings);
    }
  }

  async function start() {
    global.document.addEventListener('click', onBannerClick);
    global.addEventListener('focus', refreshBanners);
    global.document.addEventListener('officekit:tab-shown', refreshBanners);
    refreshBanners();
    const forced = new URLSearchParams(global.location.search).get('setup') === 'auto';
    // The tour waits while this is deciding, then starts (or setup opens first).
    state.deciding = true;
    const showSetup = forced || (invoke() && !global.navigator.webdriver && !(await isDone()));
    state.deciding = false;
    if (showSetup) await open();
    else global.document.dispatchEvent(new CustomEvent('officekit:setup-closed'));
  }

  global.officekitSetup = {
    open, close, isOpen: () => !!state.root || state.deciding === true, isDone, markDone, refreshBanners, PERMISSIONS, TOOLS,
    readSaved, saveSettings, refreshAccess, accessAction, requestAccess, readPermission, setDictationShortcut,
    MODELS, today, readModel, modelSummary, readTools,
    accessState: () => ({ ...state.access }),
  };
  global.openFirstRunSetup = () => open();
  if (global.document.readyState === 'loading') global.document.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
