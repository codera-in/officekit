(() => {
  const invoke = window.__TAURI__?.core?.invoke;
  const statusNode = document.getElementById('quick-control-status');
  const controls = [...document.querySelectorAll('.quick-control-row')];
  const names = {
    speechCoach: 'Speech Coach',
    listenIn: 'Listen In',
    speechToText: 'Speech to text',
    windowManager: 'Window Manager',
    clipboardHistory: 'Clipboard history',
    ergonomics: 'Ergonomics',
    meetingRecorder: 'Meeting Recorder',
    menuCpu: 'CPU in the menu bar',
    menuRam: 'RAM in the menu bar',
    menuStorage: 'Storage in the menu bar',
    menuNetwork: 'Network in the menu bar',
    menuGpu: 'GPU in the menu bar',
    menuTemperature: 'Temperature in the menu bar',
    menuBattery: 'Battery in the menu bar',
    menuBluetooth: 'Bluetooth in the menu bar'
  };
  // The access a switch depends on. A switch whose access is missing says so instead of failing silently.
  const access = {
    windowManager: 'accessibility', clipboardHistory: 'accessibility',
    speechToText: 'microphone', speechCoach: 'microphone', listenIn: 'microphone', meetingRecorder: 'microphone'
  };
  const accessCommands = {
    accessibility: { label: 'Accessibility', status: 'dictation_accessibility_permission', request: 'dictation_request_accessibility_permission' },
    microphone: { label: 'Microphone', status: 'dictation_microphone_permission', request: 'dictation_request_microphone_permission' }
  };
  let snapshot = null;
  let missing = {};

  async function refreshAccess() {
    const next = {};
    for (const [name, command] of Object.entries(accessCommands)) {
      try { next[name] = (await invoke(command.status))?.permission !== 'granted'; }
      catch (_) { next[name] = false; }
    }
    missing = next;
  }

  function render() {
    if (!snapshot) return;
    for (const row of controls) {
      const key = row.dataset.tool;
      // A desktop Mac has no battery, so its switch is not offered.
      row.hidden = key === 'menuBattery' && snapshot.hasBattery === false;
      const enabled = Boolean(snapshot[key]);
      const input = row.querySelector('input');
      input.checked = enabled;
      input.disabled = false;
      row.dataset.enabled = String(enabled);
      row.querySelector('[data-state]').textContent = key.startsWith('menu')
        ? (enabled ? 'In menu bar' : 'Off')
        : key === 'meetingRecorder'
        ? (enabled ? 'Recording' : 'Ready · click to record')
        : key === 'listenIn'
          ? (enabled ? 'Solo practice · listening' : 'Ready · solo practice')
        : (enabled ? 'Enabled' : 'Disabled');
      const needs = access[key];
      const blocked = Boolean(needs && missing[needs] && !enabled);
      if (blocked) row.querySelector('[data-state]').textContent = `Needs ${accessCommands[needs].label} · tap to allow`;
      row.dataset.needsAccess = String(blocked);
    }
    document.getElementById('quick-controls-hud-position').value = snapshot.hudPosition || 'top_center';
  }

  async function refresh() {
    if (!invoke) {
      statusNode.textContent = 'Quick controls require the OfficeKit desktop app.';
      return;
    }
    try {
      snapshot = await invoke('quick_controls_status');
      await refreshAccess();
      render();
    } catch (error) {
      statusNode.textContent = typeof error === 'string' ? error : (error?.message || 'Tool states could not be loaded.');
    }
  }

  for (const row of controls) {
    const input = row.querySelector('input');
    input.addEventListener('change', async () => {
      const key = row.dataset.tool;
      input.disabled = true;
      statusNode.textContent = (input.checked ? 'Enabling ' : 'Disabling ') + names[key] + '…';
      try {
        const needs = access[key];
        if (input.checked && needs && missing[needs]) {
          try { await invoke(accessCommands[needs].request); } catch (_) {}
          await refreshAccess();
        }
        snapshot = await invoke('quick_controls_set_tool', { tool: key, enabled: input.checked });
        render();
        statusNode.textContent = key.startsWith('menu')
          ? names[key] + (input.checked ? ' is on.' : ' is off.')
          : key === 'meetingRecorder' && input.checked
          ? 'Meeting recording has started on this Mac.'
          : key === 'listenIn' && input.checked
            ? 'Listen In is on. Speak naturally; coaching stays on this Mac.'
          : names[key] + (input.checked ? ' enabled.' : ' disabled.');
      } catch (error) {
        input.checked = !input.checked;
        input.disabled = false;
        statusNode.textContent = typeof error === 'string' ? error : (error?.message || names[key] + ' could not be changed.');
        await refresh();
      }
    });
  }

  document.getElementById('quick-controls-disable-all').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    statusNode.textContent = 'Disabling tools and safely finalizing active work…';
    try {
      snapshot = await invoke('quick_controls_disable_all');
      render();
      statusNode.textContent = 'All tools are disabled. Any active transcript or recording was finalized.';
    } catch (error) {
      statusNode.textContent = typeof error === 'string' ? error : (error?.message || 'Some tools could not be disabled. Check each state below.');
      await refresh();
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('quick-controls-hud-position').addEventListener('change', async event => {
    const select = event.currentTarget;
    select.disabled = true;
    try {
      snapshot = await invoke('quick_controls_set_hud_position', { placement: select.value });
      render();
      statusNode.textContent = 'Speech Coach HUD position saved.';
    } catch (error) {
      statusNode.textContent = typeof error === 'string' ? error : (error?.message || 'HUD position could not be saved.');
      await refresh();
    } finally {
      select.disabled = false;
    }
  });

  void refresh();
})();
