(() => {
  'use strict';

  const MODIFIER_GLYPHS = [[1, '⌃'], [2, '⌥'], [4, '⇧'], [8, '⌘']];
  const ACTIONS = ['clipboard.history', 'snippets.panel', 'launcher.open'];
  const FILTER_PREFIX = 'launcher.filter.';
  const FILTERS = ['all', 'app', 'tool', 'snippet'];
  const MAX_SKIP_APPS = 64;
  const BUNDLE_ID = /^[A-Za-z0-9][A-Za-z0-9.-]{0,199}$/;
  // Clipboard panel choice for "Panel opens on", and the Python setting value that each radio saves.
  const PANEL_CHOICES = ['all', 'text', 'images', 'links', 'pinned'];
  const PAUSE_CHOICES = ['off', '15m', '1h', 'until_resume'];

  const state = { desktop: null, settings: null, capturing: null, available: false };

  const byId = id => document.getElementById(id);
  const invoke = () => window.__TAURI__?.core?.invoke;

  function keyName(keyCode) {
    const codes = typeof macDictationKeyCodes === 'undefined' ? {} : macDictationKeyCodes;
    const code = Object.keys(codes).find(name => codes[name] === keyCode);
    if (!code) return `Key ${keyCode}`;
    if (code.startsWith('Key')) return code.slice(3);
    if (code.startsWith('Digit')) return code.slice(5);
    const glyphs = {
      ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓', Enter: '↩', Backspace: '⌫', Escape: '⎋',
      Tab: '⇥', Space: 'Space', Equal: '=', Minus: '-', Comma: ',', Period: '.', Slash: '/', Backslash: '\\',
      BracketLeft: '[', BracketRight: ']', Semicolon: ';', Quote: "'", Backquote: '`',
    };
    return glyphs[code] || code;
  }

  function shortcutLabel(shortcut) {
    const glyphs = MODIFIER_GLYPHS.filter(([bit]) => (shortcut.modifierMask & bit) !== 0).map(([, glyph]) => glyph);
    return `${glyphs.join('')}${keyName(shortcut.keyCode)}`;
  }

  function parseSkipList(text) {
    const seen = new Set();
    const ids = [];
    for (const line of String(text).split(/[\n,]+/)) {
      const id = line.trim();
      if (!id) continue;
      if (!BUNDLE_ID.test(id)) return { error: `"${id.slice(0, 40)}" is not a valid app id (like com.apple.keychainaccess).` };
      if (!seen.has(id.toLowerCase())) { seen.add(id.toLowerCase()); ids.push(id); }
    }
    if (ids.length > MAX_SKIP_APPS) return { error: `Skip at most ${MAX_SKIP_APPS} apps.` };
    return { ids };
  }

  function parseRetention(clips, days) {
    const keepClips = Number(clips);
    const keepDays = Number(days);
    if (!Number.isInteger(keepClips) || keepClips < 50 || keepClips > 5000) return { error: 'Keep between 50 and 5000 clips.' };
    if (!Number.isInteger(keepDays) || keepDays < 1 || keepDays > 365) return { error: 'Keep history for 1 to 365 days.' };
    return { clips: keepClips, days: keepDays };
  }

  // The banner text while capture is paused: a timed pause shows its end time, "until I resume" says so.
  function pauseBannerText(settings) {
    if (settings.capture_pause === 'until_resume') return 'Capture paused until you resume';
    const until = new Date(Number(settings.capture_paused_until) * 1000);
    if (Number.isNaN(until.getTime())) return 'Capture paused';
    return `Capture paused until ${until.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  }

  const SCOPE_NODES = { desktop: 'global-desktop-status', windows: 'global-windows-status', launcher: 'global-launcher-status' };

  function scopeOf(action) {
    if (String(action).startsWith('window.')) return 'windows';
    if (action === 'launcher.open' || String(action).startsWith(FILTER_PREFIX)) return 'launcher';
    return 'desktop';
  }

  function say(message, scope = 'desktop') {
    const node = byId(SCOPE_NODES[scope] || SCOPE_NODES.desktop);
    if (node) officekitOutcome.show(node, { state: 'info', text: message || '' });
  }

  function toast(message, kind) {
    if (typeof showAppFeedbackToast === 'function') showAppFeedbackToast(message, kind);
  }

  async function fetchSettings(options) {
    const url = typeof officekitApiUrl === 'function' ? officekitApiUrl('/api/clipboard/global-settings') : '/api/clipboard/global-settings';
    const response = await fetch(url, Object.assign({}, options, { headers: { 'Content-Type': 'application/json' } }));
    if (!response.ok) throw new Error('The local clipboard store rejected that setting.');
    return (await response.json()).settings;
  }

  const WINDOW_LAYOUTS = [
    ['left-half', 'Left half'], ['right-half', 'Right half'], ['top-half', 'Top half'], ['bottom-half', 'Bottom half'],
    ['top-left', 'Top left'], ['top-right', 'Top right'], ['bottom-left', 'Bottom left'], ['bottom-right', 'Bottom right'],
    ['maximize', 'Maximize'], ['center', 'Center'], ['first-third', 'First third'], ['center-third', 'Center third'],
    ['last-third', 'Last third'], ['first-two-thirds', 'First two thirds'], ['last-two-thirds', 'Last two thirds'],
    ['center-half', 'Center half'], ['almost-maximize', 'Almost maximize'], ['maximize-height', 'Maximize height'],
    ['larger', 'Larger'], ['smaller', 'Smaller'], ['move-left', 'Move left'], ['move-right', 'Move right'],
    ['move-up', 'Move up'], ['move-down', 'Move down'], ['restore', 'Restore'],
    ['next-display', 'Next display'], ['previous-display', 'Previous display'],
  ];
  const LOCAL_EDGE_KEY = 'officekit.window-snap-edge-enabled';

  function renderWindowShortcutRows() {
    const rows = byId('global-windows-shortcut-rows');
    if (!rows || state.capturing?.startsWith('window.')) return;
    rows.replaceChildren();
    for (const [layout, label] of WINDOW_LAYOUTS) {
      const action = `window.${layout}`;
      const shortcut = state.desktop.settings.shortcuts[action];
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between gap-2 rounded-lg px-2 py-1';
      const name = document.createElement('span');
      name.className = 'min-w-0 truncate text-xs';
      name.textContent = label;
      const controls = document.createElement('div');
      controls.className = 'flex shrink-0 items-center gap-1';
      const record = document.createElement('button');
      record.type = 'button';
      record.className = `btn btn-xs btn-outline font-mono${state.desktop.registrationFailures.includes(action) ? ' btn-error' : ''}`;
      record.dataset.globalAction = action;
      record.textContent = shortcut ? shortcutLabel(shortcut) : 'Not set';
      record.setAttribute('aria-label', `${label} shortcut, press to change`);
      record.addEventListener('click', () => beginCapture(action));
      controls.append(record);
      if (shortcut) {
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'btn btn-ghost btn-xs';
        clear.textContent = '✕';
        clear.setAttribute('aria-label', `Clear ${label} shortcut`);
        clear.addEventListener('click', event => {
          // The rows are rebuilt after saving; without this the menu's outside-click handler sees a
          // detached target and closes the menu.
          event.stopPropagation();
          const shortcuts = Object.assign({}, state.desktop.settings.shortcuts);
          delete shortcuts[action];
          saveDesktop({ shortcuts }, 'windows');
        });
        controls.append(clear);
      }
      row.append(name, controls);
      rows.append(row);
    }
  }

  function syncLocalEdgeSnap(edgeDragOn) {
    const toggle = byId('window-snap-edge-toggle');
    if (!toggle) return;
    let preferred = true;
    try {
      const saved = window.localStorage.getItem(LOCAL_EDGE_KEY);
      if (saved === 'true' || saved === 'false') preferred = saved === 'true';
    } catch (_) {}
    toggle.disabled = edgeDragOn;
    toggle.checked = edgeDragOn ? false : preferred;
    invoke()?.('window_snap_set_edge_enabled', { enabled: edgeDragOn ? false : preferred }).catch(() => {});
  }

  function renderWindows() {
    const section = byId('global-windows-section');
    if (!section) return;
    const { desktop, available } = state;
    byId('global-windows-unavailable').classList.toggle('hidden', available);
    for (const control of section.querySelectorAll('input, button, textarea')) {
      if (control.id !== 'global-windows-open-accessibility') control.disabled = !available;
    }
    if (!available || !desktop) return;
    const settings = desktop.settings;
    byId('global-windows-enabled').checked = settings.windowsEnabled;
    byId('global-windows-edge-drag').checked = settings.edgeDrag;
    byId('global-windows-edge-drag').disabled = !settings.windowsEnabled;
    if (document.activeElement !== byId('global-windows-gap')) byId('global-windows-gap').value = settings.windowGap;
    byId('global-windows-accessibility').classList.toggle('hidden', desktop.accessibility === 'trusted' || !settings.windowsEnabled);
    const skipped = settings.windowSkipApps;
    byId('global-windows-skip-summary').textContent = skipped.length
      ? `${skipped.length} app${skipped.length === 1 ? '' : 's'}: ${skipped.slice(0, 2).join(', ')}${skipped.length > 2 ? '…' : ''}`
      : 'No apps skipped';
    renderWindowShortcutRows();
    syncLocalEdgeSnap(settings.windowsEnabled && settings.edgeDrag);
  }

  function togglePanel(panelId, buttonId, open) {
    byId(panelId).classList.toggle('hidden', !open);
    byId(buttonId).setAttribute('aria-expanded', String(open));
  }

  async function saveGap() {
    const value = Number(byId('global-windows-gap').value);
    if (!Number.isInteger(value) || value < 0 || value > 64) {
      say('The gap must be a whole number from 0 to 64 pixels.', 'windows');
      return;
    }
    await saveDesktop({ windowGap: value }, 'windows');
  }

  async function saveWindowSkip() {
    const skip = parseSkipList(byId('global-windows-skip').value);
    if (skip.error) { say(skip.error, 'windows'); return; }
    if (await saveDesktop({ windowSkipApps: skip.ids }, 'windows')) togglePanel('global-windows-skip-panel', 'global-windows-skip-edit', false);
  }

  async function resetWindowShortcuts() {
    try {
      const defaults = await invoke()('global_desktop_default_shortcuts');
      const shortcuts = Object.assign({}, state.desktop.settings.shortcuts);
      for (const action of Object.keys(shortcuts)) if (action.startsWith('window.')) delete shortcuts[action];
      for (const [action, shortcut] of Object.entries(defaults)) if (action.startsWith('window.')) shortcuts[action] = shortcut;
      await saveDesktop({ shortcuts }, 'windows');
    } catch (error) {
      say('The default shortcuts could not be restored.', 'windows');
    }
  }

  function bindWindows() {
    if (!byId('global-windows-section')) return;
    byId('global-windows-enabled').addEventListener('change', event => saveDesktop({ windowsEnabled: event.target.checked }, 'windows'));
    byId('global-windows-edge-drag').addEventListener('change', event => saveDesktop({ edgeDrag: event.target.checked }, 'windows'));
    byId('global-windows-gap').addEventListener('change', saveGap);
    byId('global-windows-skip-edit').addEventListener('click', () => {
      const open = byId('global-windows-skip-panel').classList.contains('hidden');
      if (open) byId('global-windows-skip').value = state.desktop.settings.windowSkipApps.join('\n');
      togglePanel('global-windows-skip-panel', 'global-windows-skip-edit', open);
    });
    byId('global-windows-skip-cancel').addEventListener('click', () => togglePanel('global-windows-skip-panel', 'global-windows-skip-edit', false));
    byId('global-windows-skip-save').addEventListener('click', saveWindowSkip);
    byId('global-windows-shortcuts-edit').addEventListener('click', () => {
      togglePanel('global-windows-shortcuts-panel', 'global-windows-shortcuts-edit', byId('global-windows-shortcuts-panel').classList.contains('hidden'));
    });
    byId('global-windows-shortcuts-reset').addEventListener('click', resetWindowShortcuts);
    byId('global-windows-open-accessibility').addEventListener('click', () => {
      invoke()?.('dictation_open_permission_settings', { kind: 'accessibility' }).catch(() => say('System Settings could not be opened.', 'windows'));
    });
  }

  // Each switch or radio group is bound to one field: desktop settings (Rust) or clipboard settings (store).
  function setChecked(id, value) {
    const node = byId(id);
    if (node) node.checked = Boolean(value);
  }

  function renderClipboardPause(settings) {
    const paused = Boolean(settings.capture_paused);
    byId('global-clipboard-paused').classList.toggle('hidden', !paused);
    byId('global-clipboard-paused-text').textContent = paused ? pauseBannerText(settings) : '';
    const pause = PAUSE_CHOICES.includes(settings.capture_pause) ? settings.capture_pause : 'off';
    const radio = { off: 'global-clipboard-pause-off', '15m': 'global-clipboard-pause-15m', '1h': 'global-clipboard-pause-1h', until_resume: 'global-clipboard-pause-until' }[pause];
    setChecked(radio, true);
  }

  function renderPanelChoice(settings) {
    const choice = PANEL_CHOICES.includes(settings.panel_default_filter) ? settings.panel_default_filter : 'text';
    setChecked(`global-clipboard-panel-${choice}`, true);
  }

  function renderShortcutButtons(desktop) {
    for (const action of ACTIONS) {
      const button = document.querySelector(`[data-global-action="${action}"]`);
      const shortcut = desktop.settings.shortcuts[action];
      if (button && shortcut && state.capturing !== action) {
        button.textContent = shortcutLabel(shortcut);
        button.classList.toggle('btn-error', desktop.registrationFailures.includes(action));
      }
    }
  }

  function renderLauncher(desktop) {
    const card = byId('global-launcher-card');
    if (!card) return;
    const { available } = state;
    byId('global-launcher-unavailable').classList.toggle('hidden', available);
    for (const control of card.querySelectorAll('input, button, select')) control.disabled = !available;
    if (!available || !desktop) return;
    const settings = desktop.settings;
    setChecked('global-launcher-enabled', settings.launcherEnabled);
    setChecked('global-launcher-show-apps', settings.launcherShowApps);
    setChecked('global-launcher-show-tools', settings.launcherShowTools);
    setChecked('global-launcher-show-snippets', settings.launcherShowSnippets);
    setChecked('global-launcher-quick-calculator', settings.quickCalculator);
    setChecked('global-launcher-quick-uuid', settings.quickUuid);
    setChecked('global-launcher-quick-password', settings.quickPassword);
    byId('global-launcher-password-length').value = String(settings.quickPasswordLength ?? 20);
    byId('global-launcher-password-symbols').value = settings.quickPasswordSymbols ?? '!@#$%&*?-_+=';
    for (const filter of FILTERS) {
      const key = byId(`global-launcher-filter-${filter}`);
      const shortcut = (settings.launcherFilters || {})[filter];
      if (key && shortcut && state.capturing !== `${FILTER_PREFIX}${filter}`) key.textContent = shortcutLabel(shortcut);
    }
    const shortcutButton = byId('global-desktop-shortcut-launcher');
    if (shortcutButton && settings.shortcuts['launcher.open'] && state.capturing !== 'launcher.open') {
      shortcutButton.textContent = shortcutLabel(settings.shortcuts['launcher.open']);
      shortcutButton.classList.toggle('btn-error', desktop.registrationFailures.includes('launcher.open'));
    }
  }

  function renderSkipSummary(settings) {
    const skipped = settings.skip_bundle_ids;
    byId('global-desktop-skip-summary').textContent = skipped.length
      ? `${skipped.length} app${skipped.length === 1 ? '' : 's'}: ${skipped.slice(0, 2).join(', ')}${skipped.length > 2 ? '…' : ''}`
      : 'No apps skipped';
    byId('global-desktop-retention-summary').textContent = `${settings.retention_clips} clips · ${settings.retention_days} days`;
  }

  function render() {
    renderWindows();
    renderLauncher(state.desktop);
    const card = byId('global-desktop-card');
    if (!card) return;
    const { desktop, settings, available } = state;
    byId('global-desktop-unavailable').classList.toggle('hidden', available);
    for (const control of card.querySelectorAll('input, button, textarea')) control.disabled = !available;
    if (!available || !desktop || !settings) return;
    setChecked('global-desktop-enabled', desktop.settings.enabled);
    setChecked('global-desktop-login', desktop.settings.openAtLogin);
    setChecked('global-desktop-snippets-enabled', desktop.settings.snippetsEnabled);
    setChecked('global-desktop-capture', settings.capture_enabled);
    setChecked('global-desktop-expansion', settings.expansion_enabled);
    byId('global-desktop-accessibility').classList.toggle('hidden', desktop.accessibility === 'trusted');
    byId('global-desktop-login-note').textContent = desktop.loginItem === 'needs-approval'
      ? 'Approve OfficeKit in System Settings → General → Login Items.'
      : 'Needed so history has no gaps';
    renderShortcutButtons(desktop);
    renderClipboardPause(settings);
    renderPanelChoice(settings);
    renderSkipSummary(settings);
    if (byId('global-desktop-edit-panel')?.open) renderSkipApps();
    if (desktop.registrationFailures.length) say('macOS refused a shortcut. Pick a different combination.', desktop.registrationFailures.some(action => scopeOf(action) === 'launcher') ? 'launcher' : 'desktop');
  }

  async function load() {
    if (typeof invoke() !== 'function') { state.available = false; render(); return; }
    try {
      state.desktop = await invoke()('global_desktop_status');
      state.available = state.desktop.available;
      state.settings = await fetchSettings({ method: 'GET' });
    } catch (error) {
      state.available = false;
      say('Global clipboard settings could not be loaded.');
    }
    render();
  }

  async function saveDesktop(change, scope = 'desktop') {
    const previous = state.desktop.settings;
    const next = Object.assign({}, previous, change);
    let saved = false;
    try {
      state.desktop = await invoke()('global_desktop_configure', { settings: next });
      saved = true;
      say('', scope);
    } catch (error) {
      say(typeof error === 'string' ? error : error?.message || 'That setting could not be saved.', scope);
    }
    render();
    return saved;
  }

  async function savePython(change) {
    let saved = false;
    try {
      state.settings = await fetchSettings({ method: 'POST', body: JSON.stringify(change) });
      saved = true;
      say('');
      await invoke()('global_desktop_refresh');
    } catch (error) {
      say(error?.message || 'That setting could not be saved.');
    }
    render();
    return saved;
  }

  // A shortcut button, or a launcher filter key shown in the Global Launcher page.
  function captureTarget(action) {
    if (action.startsWith(FILTER_PREFIX)) return byId(`global-launcher-filter-${action.slice(FILTER_PREFIX.length)}`);
    return document.querySelector(`[data-global-action="${action}"]`);
  }

  function beginCapture(action) {
    state.capturing = action;
    const target = captureTarget(action);
    if (target) target.textContent = 'Press shortcut… (Esc cancels)';
    say('Press the combination to use. It needs a modifier key.', scopeOf(action));
  }

  function endCapture(message) {
    const scope = scopeOf(state.capturing);
    state.capturing = null;
    say(message || '', scope);
    render();
  }

  async function onCaptureKey(event) {
    if (!state.capturing) return;
    event.preventDefault();
    event.stopPropagation();
    if (['Meta', 'Control', 'Alt', 'Shift'].includes(event.key)) return;
    if (event.code === 'Escape') { endCapture('Shortcut unchanged.'); return; }
    const codes = typeof macDictationKeyCodes === 'undefined' ? {} : macDictationKeyCodes;
    const keyCode = codes[event.code];
    if (!Number.isInteger(keyCode)) { endCapture('That key is not supported. Try a letter, number or F-key.'); return; }
    const modifierMask = (event.ctrlKey ? 1 : 0) | (event.altKey ? 2 : 0) | (event.shiftKey ? 4 : 0) | (event.metaKey ? 8 : 0);
    const action = state.capturing;
    state.capturing = null;
    if (action.startsWith(FILTER_PREFIX)) {
      const launcherFilters = Object.assign({}, state.desktop.settings.launcherFilters, { [action.slice(FILTER_PREFIX.length)]: { keyCode, modifierMask } });
      await saveDesktop({ launcherFilters }, scopeOf(action));
      return;
    }
    const shortcuts = Object.assign({}, state.desktop.settings.shortcuts, { [action]: { keyCode, modifierMask } });
    await saveDesktop({ shortcuts }, scopeOf(action));
  }

  // The checkbox list edits the same bundle-id textarea that the saved list is read from, so both ways of choosing agree.
  async function loadInstalledApps() {
    if (state.installedApps) return state.installedApps;
    try {
      const apps = await invoke()('list_installed_apps');
      state.installedApps = Array.isArray(apps) ? apps.filter(app => app && typeof app.name === 'string' && BUNDLE_ID.test(app.bundleId || '')) : [];
    } catch { state.installedApps = []; }
    return state.installedApps;
  }

  function currentSkipIds() {
    const parsed = parseSkipList(byId('global-desktop-skip').value);
    return parsed.error ? [] : parsed.ids;
  }

  function renderSkipApps() {
    const list = byId('global-desktop-skip-apps');
    const note = byId('global-desktop-skip-apps-note');
    const apps = state.installedApps || [];
    const chosen = new Set(currentSkipIds().map(id => id.toLowerCase()));
    const query = byId('global-desktop-skip-search').value.trim().toLowerCase();
    const rows = apps
      .filter(app => !query || app.name.toLowerCase().includes(query) || app.bundleId.toLowerCase().includes(query))
      .sort((a, b) => (chosen.has(b.bundleId.toLowerCase()) - chosen.has(a.bundleId.toLowerCase())) || a.name.localeCompare(b.name));
    list.replaceChildren(...rows.map(app => {
      const item = document.createElement('li');
      const label = document.createElement('label');
      label.className = 'flex cursor-pointer items-center gap-3 border-t border-slate-200 px-3 py-2 first:border-t-0 dark:border-white/10';
      const text = document.createElement('span');
      text.className = 'min-w-0 flex-1';
      const name = document.createElement('span');
      name.className = 'block truncate';
      name.textContent = app.name;
      const id = document.createElement('small');
      id.className = 'block truncate text-xs text-slate-500';
      id.textContent = app.bundleId;
      text.append(name, id);
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'checkbox checkbox-sm';
      box.checked = chosen.has(app.bundleId.toLowerCase());
      box.dataset.bundleId = app.bundleId;
      box.setAttribute('aria-label', `Skip ${app.name}`);
      label.append(text, box);
      item.append(label);
      return item;
    }));
    note.classList.toggle('hidden', rows.length > 0);
    note.textContent = apps.length ? 'No installed app matches.' : 'Installed apps could not be listed. Use "Add an app by bundle id" below.';
  }

  // Skipped apps save as soon as they change; the bundle-id box and the checkboxes stay in step.
  async function saveSkipIds(ids) {
    const skip = parseSkipList(ids.join('\n'));
    if (skip.error) { say(skip.error); return false; }
    return savePython({ skip_bundle_ids: skip.ids });
  }

  function toggleSkipApp(bundleId, skip) {
    const ids = currentSkipIds().filter(id => id.toLowerCase() !== bundleId.toLowerCase());
    if (skip) ids.push(bundleId);
    byId('global-desktop-skip').value = ids.join('\n');
    renderSkipApps();
    void saveSkipIds(ids);
  }

  function openSkipPanel(open) {
    if (!open) return;
    byId('global-desktop-skip').value = state.settings.skip_bundle_ids.join('\n');
    byId('global-desktop-retention-clips').value = state.settings.retention_clips;
    byId('global-desktop-retention-days').value = state.settings.retention_days;
    byId('global-desktop-skip-search').value = '';
    renderSkipApps();
    void loadInstalledApps().then(renderSkipApps);
  }

  async function saveRetention() {
    const retention = parseRetention(byId('global-desktop-retention-clips').value, byId('global-desktop-retention-days').value);
    if (retention.error) { say(retention.error); return; }
    await savePython({ retention_clips: retention.clips, retention_days: retention.days });
  }

  async function saveSkipTextarea() {
    const skip = parseSkipList(byId('global-desktop-skip').value);
    if (skip.error) { say(skip.error); return; }
    await saveSkipIds(skip.ids);
  }

  function bindClipboard() {
    byId('global-desktop-enabled').addEventListener('change', event => saveDesktop({ enabled: event.target.checked }));
    byId('global-desktop-login').addEventListener('change', event => saveDesktop({ openAtLogin: event.target.checked }));
    byId('global-desktop-capture').addEventListener('change', event => savePython({ capture_enabled: event.target.checked }));
    byId('global-desktop-expansion').addEventListener('change', event => savePython({ expansion_enabled: event.target.checked }));
    byId('global-desktop-snippets-enabled').addEventListener('change', event => saveDesktop({ snippetsEnabled: event.target.checked }, 'desktop'));
    for (const choice of PAUSE_CHOICES) {
      const radio = { off: 'global-clipboard-pause-off', '15m': 'global-clipboard-pause-15m', '1h': 'global-clipboard-pause-1h', until_resume: 'global-clipboard-pause-until' }[choice];
      byId(radio).addEventListener('change', () => savePython({ capture_pause: choice }));
    }
    byId('global-clipboard-resume').addEventListener('click', () => savePython({ capture_pause: 'off' }));
    for (const choice of PANEL_CHOICES) {
      byId(`global-clipboard-panel-${choice}`).addEventListener('change', () => savePython({ panel_default_filter: choice }));
    }
    byId('global-desktop-skip-search').addEventListener('input', renderSkipApps);
    byId('global-desktop-skip').addEventListener('change', saveSkipTextarea);
    byId('global-desktop-skip-apps').addEventListener('change', event => {
      const box = event.target;
      if (box instanceof HTMLInputElement && box.dataset.bundleId) toggleSkipApp(box.dataset.bundleId, box.checked);
    });
    byId('global-desktop-retention-clips').addEventListener('change', saveRetention);
    byId('global-desktop-retention-days').addEventListener('change', saveRetention);
    byId('global-desktop-edit-panel').addEventListener('toggle', event => openSkipPanel(event.currentTarget.open));
    byId('global-desktop-open-accessibility').addEventListener('click', event => {
      event.preventDefault();
      invoke()?.('dictation_open_permission_settings', { kind: 'accessibility' }).catch(() => say('System Settings could not be opened.'));
    });
  }

  function bindLauncher() {
    if (!byId('global-launcher-card')) return;
    byId('global-launcher-enabled').addEventListener('change', event => saveDesktop({ launcherEnabled: event.target.checked }, 'launcher'));
    byId('global-launcher-show-apps').addEventListener('change', event => saveDesktop({ launcherShowApps: event.target.checked }, 'launcher'));
    byId('global-launcher-show-tools').addEventListener('change', event => saveDesktop({ launcherShowTools: event.target.checked }, 'launcher'));
    byId('global-launcher-show-snippets').addEventListener('change', event => saveDesktop({ launcherShowSnippets: event.target.checked }, 'launcher'));
    byId('global-launcher-quick-calculator').addEventListener('change', event => saveDesktop({ quickCalculator: event.target.checked }, 'launcher'));
    byId('global-launcher-quick-uuid').addEventListener('change', event => saveDesktop({ quickUuid: event.target.checked }, 'launcher'));
    byId('global-launcher-quick-password').addEventListener('change', event => saveDesktop({ quickPassword: event.target.checked }, 'launcher'));
    byId('global-launcher-password-length').addEventListener('change', event => {
      const length = event.target.valueAsNumber;
      if (!Number.isInteger(length) || length < 8 || length > 128) {
        say('Choose a whole number from 8 to 128 characters.', 'launcher');
        return;
      }
      saveDesktop({ quickPasswordLength: length }, 'launcher');
    });
    byId('global-launcher-password-symbols').addEventListener('change', event => {
      const symbols = event.target.value;
      const punctuation = [...symbols].every(character => {
        const code = character.codePointAt(0);
        return (code >= 33 && code <= 47) || (code >= 58 && code <= 64)
          || (code >= 91 && code <= 96) || (code >= 123 && code <= 126);
      });
      if (symbols.length > 32 || !punctuation || new Set(symbols).size !== symbols.length) {
        say('Use up to 32 unique ASCII punctuation characters.', 'launcher');
        return;
      }
      saveDesktop({ quickPasswordSymbols: symbols }, 'launcher');
    });
    byId('global-launcher-filter-change').addEventListener('click', () => beginCapture(`${FILTER_PREFIX}${byId('global-launcher-filter-name').value}`));
    // An empty map makes the app restore every filter's default key.
    byId('global-desktop-filters-reset').addEventListener('click', () => saveDesktop({ launcherFilters: {} }, 'launcher'));
  }

  function bind() {
    bindWindows();
    bindLauncher();
    if (!byId('global-desktop-card')) return;
    bindClipboard();
    for (const button of document.querySelectorAll('[data-global-action]')) {
      button.addEventListener('click', () => beginCapture(button.dataset.globalAction));
    }
    document.addEventListener('keydown', onCaptureKey, true);
    window.addEventListener('focus', () => { if (state.available) load(); });
    window.__TAURI__?.event?.listen?.('launcher-open-tool', event => {
      const toolId = event.payload?.toolId;
      if (typeof toolId !== 'string' || !/^[a-z0-9_-]{1,128}$/i.test(toolId) || typeof selectSearchTool !== 'function') return;
      if (selectSearchTool(toolId) === false) toast('That tool is not available in this build.', 'error');
    });
    window.__TAURI__?.event?.listen?.('global-desktop-notice', event => toast(event.payload?.message || 'OfficeKit could not finish that.', 'error'));
    load();
  }

  window.officekitGlobalDesktop = { shortcutLabel, parseSkipList, parseRetention, pauseBannerText, reload: load };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
