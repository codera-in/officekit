(function (global) {
  'use strict';

  // The General card on the Settings page. It reads what the app already owns (desktop settings, the
  // dictation shortcut, macOS permissions) plus the small saved file that setup writes; it copies nothing.
  const ROOT_ID = 'general-settings';
  const POLL_MS = 2000;

  const invoke = () => global.__TAURI__?.core?.invoke;
  const setup = () => global.officekitSetup;
  const escapeText = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

  const state = { finder: null, crashRestart: null, crashRestartError: '', saved: null, desktop: null, model: null, shortcut: 'disabled', message: '', timer: null, modelMessage: '', modelError: false, modelTimer: null, resumeShortcut: false };

  async function call(command, args) {
    if (!invoke()) return null;
    try { return await invoke()(command, args); } catch (_) { return null; }
  }

  async function load() {
    const [saved, tools, model, finder, crashRestart] = await Promise.all([setup().readSaved(), setup().readTools(), call('dictation_model_status'), call('finder_open_in_status'), call('crash_restart_status')]);
    await setup().refreshAccess();
    state.finder = typeof finder === 'boolean' ? finder : null;
    state.crashRestart = typeof crashRestart === 'boolean' ? crashRestart : null;
    state.saved = saved;
    state.tools = tools;
    state.desktop = tools.settings ? { settings: tools.settings } : null;
    state.model = model;
    state.shortcut = tools.hotkeyState;
    render();
  }

  function dateText(iso) {
    const date = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function modelRow() {
    const models = setup().MODELS;
    const id = state.model?.model_id || state.saved?.modelId || 'parakeet_v3';
    const current = models.find(model => model.id === id) || models[0];
    const summary = setup().modelSummary(state.model);
    const failed = state.model?.state === 'failed';
    const title = current.size ? `${current.label} · ${current.size}` : current.label;
    const options = models.map(model => `<option value="${model.id}"${model.id === current.id ? ' selected' : ''}>${escapeText(model.size ? `${model.label} · ${model.size}` : model.label)}</option>`).join('');
    const chip = summary.ready ? '<span class="ok-setup-chip ok">Downloaded</span>'
      : summary.busy ? `<span class="ok-setup-chip warn">Downloading${summary.fraction === null ? '…' : ` ${summary.fraction}%`}</span>`
        : `<span class="ok-setup-chip warn">${failed ? 'Download failed' : 'Not downloaded'}</span>`;
    const download = !summary.ready && !summary.busy ? '<button type="button" class="btn btn-sm ok-row-action" data-gs-download>Download</button>' : '';
    const bar = summary.busy ? `<div class="ok-setup-bar" role="progressbar" aria-label="Speech model download" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${summary.fraction ?? 0}"><b style="width:${summary.fraction ?? 0}%"></b></div>` : '';
    const line = state.modelMessage || (summary.busy ? `${summary.text} It keeps going if you leave this page.` : (failed ? state.model.message : ''));
    return `<div class="ok-gs-row ok-gs-model"><span class="ok-setup-copy"><strong>${escapeText(title)}</strong><small>${escapeText(current.note)}</small></span>
      <select class="select select-sm" data-gs-model aria-label="Speech model"${summary.busy ? ' disabled' : ''}>${options}</select>
      ${chip}${download}</div>${line ? `<p class="ok-setup-status ${failed || state.modelError ? 'warn' : ''}" role="status" aria-live="polite" data-gs-model-status>${escapeText(line)}</p>` : ''}${bar}`;
  }

  // The settings come over the wire in camelCase (windowsEnabled, openAtLogin); anything else is refused by the native side.
  const DESKTOP_KEYS = { desktop: 'enabled', windows: 'windowsEnabled', login: 'openAtLogin' };

  // Each tool links to where its details are set: shortcuts, gap and edge snapping, panels and keys.
  function toolRow(id, label, note, key, checked, needs, configure, failed = false) {
    const blocked = (needs && setup().accessAction(needs) !== null) || failed;
    const warning = blocked && !failed ? `Needs ${setup().PERMISSIONS.find(permission => permission.id === needs).label} · allow it below` : note;
    const link = configure ? `<a href="#" class="ok-gs-link" data-gs-configure="${id}" aria-label="Configure ${escapeText(label)}">Configure</a>` : '';
    return `<div class="ok-gs-row"><label class="ok-gs-tool"><span class="ok-setup-copy"><strong>${escapeText(label)}</strong><small class="${blocked ? 'warn' : ''}">${escapeText(warning)}</small></span>${key ? `<span class="ok-setup-key">${escapeText(key)}</span>` : ''}<input class="toggle" type="checkbox" data-gs-tool="${id}" aria-label="${escapeText(label)}"${checked ? ' checked' : ''}${blocked && !checked ? ' disabled' : ''}></label>${link}</div>`;
  }

  // Switches and shortcut keys come from the same read as setup and the tool pages (setup().readTools),
  // so every place shows the same state and the same keys.
  function toolRows() {
    const tools = state.tools;
    if (!tools?.settings) return '<p class="ok-setup-fine">Tool switches are available in the OfficeKit desktop app.</p>';
    const waiting = tools.pending ? 'Turns on when the speech model is ready' : 'Hold a key to dictate anywhere';
    return [
      toolRow('desktop', 'Launcher, clipboard history and snippets', 'Find apps and tools · save what you copy · expand ;keywords', tools.keys.desktop, tools.on.desktop, 'accessibility', true),
      toolRow('windows', 'Window layouts', 'Halves, corners, maximize', tools.keys.windows, tools.on.windows, 'accessibility', true),
      toolRow('dictation', 'Speech to text shortcut', waiting, tools.keys.dictation, tools.on.dictation, 'microphone', true),
      ...(state.finder === null ? [] : [toolRow('finder', 'Finder: Open in OfficeKit', 'Adds Open in OfficeKit to Finder\'s right-click menu, under Quick Actions and Services', '', state.finder, null, false)]),
      toolRow('login', 'Open at login', 'So these are always ready', '', tools.on.login, null, false),
      ...(state.crashRestart === null ? [] : [toolRow('crash_restart', 'Restart after a crash', state.crashRestartError || 'If OfficeKit closes unexpectedly, open it again. Quitting normally does not restart it.', '', state.crashRestart, null, false, Boolean(state.crashRestartError))]),
    ].join('');
  }

  // Window layouts are configured in the Window layout menu in the header; the others have their own pages.
  function configure(id) {
    if (id === 'windows') {
      const menu = global.document.getElementById('officekit-window-snap');
      // Opened after this click ends: the page closes the menu on any click outside it.
      if (menu) setTimeout(() => { menu.open = true; menu.scrollIntoView?.({ block: 'nearest' }); }, 0);
      return;
    }
    const tab = { desktop: 'global-launcher', dictation: 'dictate' }[id];
    if (tab && typeof global.switchTab === 'function') global.switchTab(tab);
  }

  const STATUS_TEXT = { granted: 'Allowed', undetermined: 'Not allowed', denied: 'Not allowed', unknown: 'Not checked' };

  function permissionRow(permission) {
    const status = setup().accessState()[permission.id] || 'unknown';
    const action = setup().accessAction(permission.id);
    const chipClass = status === 'granted' ? 'ok' : (status === 'unknown' ? '' : 'warn');
    const reportsDenied = permission.id === 'microphone' || permission.id === 'calendar';
    const label = reportsDenied && status === 'denied' ? 'Denied in System Settings'
      : reportsDenied && status === 'undetermined' ? 'Not asked yet' : STATUS_TEXT[status];
    const button = action === 'allow' ? `<button type="button" class="btn btn-sm ok-row-action" data-gs-allow="${permission.id}">Allow</button>`
      : action === 'settings' ? `<button type="button" class="btn btn-sm ok-row-action" data-gs-allow="${permission.id}">Open System Settings</button>` : '';
    const optional = permission.optional ? ' · optional' : '';
    return `<div class="ok-gs-row" data-gs-permission="${permission.id}"><span class="ok-setup-copy"><strong>${permission.label}</strong><small class="${action ? 'warn' : ''}">${escapeText(permission.features.join(', ') + optional)}</small></span><span class="ok-setup-chip ${chipClass}">${label}</span>${button}</div>`;
  }

  function permissionRows() {
    return setup().PERMISSIONS.map(permissionRow).join('');
  }

  function render() {
    const root = global.document.getElementById(ROOT_ID);
    if (!root || !setup()) return;
    // Do not rebuild the card while the model list is open or focused; it would close under the cursor.
    if (root.contains(global.document.activeElement) && global.document.activeElement.tagName === 'SELECT') return;
    const saved = state.saved;
    const done = saved?.setupDone === true;
    const chip = done
      ? `<span class="ok-setup-chip ok">Setup done${saved?.setupCompletedAt ? ` · ${escapeText(dateText(saved.setupCompletedAt))}` : ''}</span>`
      : '<span class="ok-setup-chip warn">Setup not done</span>';
    const notice = done ? `<div class="ok-gs-row"><span class="ok-setup-copy"><strong>First-run setup</strong><small>Model, access and tools. Your choices below are kept.</small></span><a href="#" class="ok-setup-link" data-gs-setup>Run setup again</a></div>`
      : `<div class="ok-access-banner"><span class="ok-setup-copy"><strong>This Mac is not set up yet</strong><small>The launcher, clipboard, window layouts and speech model are off until you run setup.</small></span><a href="#" class="ok-setup-link" data-gs-setup>Run setup</a></div>`;
    root.innerHTML = `<div class="ok-gs-head"><h2 id="general-settings-heading">General</h2>${chip}</div>
      ${notice}
      <div class="ok-gs-sub">Speech model</div>${modelRow()}
      <div class="ok-gs-sub">Tools running in the background</div>${toolRows()}
      <div class="ok-gs-sub">System permissions · read from macOS each time you open Settings</div>${permissionRows()}
      <p class="ok-setup-fine">Allow shows the macOS prompt when macOS still asks. After a refusal macOS never asks again, so the button opens System Settings instead. Files and folders, Finder (Trash) control and AirPods motion are asked the first time you use them and are not listed.</p>
      <p class="ok-setup-status" role="status" aria-live="polite">${escapeText(state.message)}</p>`;
  }

  async function changeTool(id, enabled) {
    state.message = '';
    try {
      if (id === 'dictation') {
        const result = await setup().setDictationShortcut(enabled);
        if (!result) throw new Error('The speech to text shortcut could not be changed.');
        if (result === 'pending') state.message = 'The shortcut will turn on as soon as the speech model is ready and access is allowed.';
      } else if (id === 'finder') {
        await invoke()('finder_open_in_set', { enabled });
      } else if (id === 'crash_restart') {
        state.crashRestartError = '';
        try { await invoke()('crash_restart_set', { enabled }); }
        catch (error) { state.crashRestartError = typeof error === 'string' ? error : (error?.message || 'Could not change this. Nothing was changed.'); }
      } else {
        const status = await invoke()('global_desktop_status');
        const key = DESKTOP_KEYS[id];
        if (!key) return;
        await invoke()('global_desktop_configure', { settings: { ...status.settings, [key]: enabled } });
      }
    } catch (error) {
      state.message = typeof error === 'string' ? error : (error?.message || 'That change could not be saved.');
    }
    await load();
  }

  const errorText = (error, fallback) => (typeof error === 'string' ? error : (error?.message || fallback));
  const modelLabel = id => setup().MODELS.find(model => model.id === id)?.label || 'The speech model';

  // The download runs in the background; this watches it and turns the shortcut back on afterwards.
  function watchDownload(id) {
    clearTimeout(state.modelTimer);
    state.modelTimer = setTimeout(async () => {
      state.model = await setup().readModel();
      const summary = setup().modelSummary(state.model);
      if (summary.busy) { render(); watchDownload(id); return; }
      if (summary.ready) {
        state.modelMessage = `${modelLabel(id)} is ready.`;
        if (state.resumeShortcut) await setup().setDictationShortcut(true);
      } else {
        state.modelError = true;
        state.modelMessage = state.model?.message || 'The download did not finish. Try Download again.';
        if (state.resumeShortcut) await setup().setDictationShortcut(true);
      }
      state.resumeShortcut = false;
      await load();
    }, 1000);
  }

  function startDownload(id) {
    state.modelError = false;
    state.modelMessage = 'Starting the download…';
    state.model = { ...(state.model || {}), model_id: id, state: 'preparing', message: 'Starting the download…', progress: null };
    render();
    invoke()('dictation_prepare_model').catch(error => {
      state.model = { model_id: id, state: 'failed', message: errorText(error, 'The download failed. Try again.') };
      state.modelError = true;
      state.modelMessage = state.model.message;
      render();
    });
    watchDownload(id);
  }

  // Switching needs the speech to text shortcut off; it is turned off here and back on once the model is ready.
  async function changeModel(id) {
    state.message = '';
    state.modelError = false;
    state.modelMessage = '';
    const wasOn = state.shortcut !== 'disabled';
    try {
      if (wasOn) { await setup().setDictationShortcut(false); state.resumeShortcut = true; }
      await invoke()('dictation_model_select', { modelId: id });
      await setup().saveSettings({ modelId: id });
    } catch (error) {
      if (wasOn) await setup().setDictationShortcut(true);
      state.resumeShortcut = false;
      state.modelError = true;
      state.modelMessage = errorText(error, 'The model could not be changed right now.');
      await load();
      return;
    }
    state.model = await setup().readModel();
    if (setup().modelSummary(state.model).ready) {
      state.modelMessage = `Switched to ${modelLabel(id)}.`;
      if (state.resumeShortcut) await setup().setDictationShortcut(true);
      state.resumeShortcut = false;
      await load();
      return;
    }
    startDownload(id);
  }

  function onClick(event) {
    const allow = event.target.closest('[data-gs-allow]');
    if (allow) { setup().requestAccess(allow.dataset.gsAllow).then(load); return; }
    if (event.target.closest('[data-gs-download]')) {
      const id = state.model?.model_id || state.saved?.modelId || 'parakeet_v3';
      startDownload(id);
      return;
    }
    if (event.target.closest('[data-gs-setup]')) { event.preventDefault(); setup().open(); return; }
    const link = event.target.closest('[data-gs-configure]');
    if (link) { event.preventDefault(); configure(link.dataset.gsConfigure); }
  }

  function onChange(event) {
    const tool = event.target.closest('[data-gs-tool]');
    if (tool) { changeTool(tool.dataset.gsTool, tool.checked); return; }
    const model = event.target.closest('[data-gs-model]');
    if (model) { model.blur(); changeModel(model.value); }
  }

  function visible() {
    const root = global.document.getElementById(ROOT_ID);
    return !!root && root.getClientRects().length > 0;
  }

  function start() {
    const root = global.document.getElementById(ROOT_ID);
    if (!root) return;
    root.addEventListener('click', onClick);
    root.addEventListener('change', onChange);
    const refresh = () => { if (visible()) load(); };
    global.document.addEventListener('officekit:tab-shown', refresh);
    global.document.addEventListener('officekit:setup-closed', refresh);
    global.addEventListener('focus', refresh);
    // Coming back from System Settings while this page is open: re-read the permissions.
    state.timer = setInterval(() => { if (visible() && !global.document.hidden) load(); }, POLL_MS);
  }

  global.officekitGeneralSettings = { load, render };
  if (global.document.readyState === 'loading') global.document.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
