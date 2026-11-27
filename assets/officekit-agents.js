(function (global) {
  'use strict';

  const CLIENTS = Object.freeze(['claude-code', 'claude-desktop', 'cursor', 'codex']);
  const GROUP_IDS = Object.freeze(['pdf', 'image', 'calc', 'privacy', 'dev', 'system']);
  const APPLY_NOTE = 'Saved. Changes apply the next time your agent app starts.';

  function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
  }

  // The helper is the bundled launcher; `--agent-mcp` selects the MCP server.
  function clientConfig(client, helperPath) {
    const path = String(helperPath || '');
    const json = JSON.stringify({ mcpServers: { officekit: { command: path, args: ['--agent-mcp'] } } }, null, 2);
    if (client === 'claude-code') {
      return { kind: 'command', text: `claude mcp add officekit -- ${shellQuote(path)} --agent-mcp`, note: 'Run this once in a terminal, then restart Claude Code.' };
    }
    if (client === 'claude-desktop') {
      return { kind: 'json', text: json, note: 'Merge into claude_desktop_config.json, then restart Claude Desktop.' };
    }
    if (client === 'cursor') {
      return { kind: 'json', text: json, note: 'Add to ~/.cursor/mcp.json, then restart Cursor.' };
    }
    if (client === 'codex') {
      return {
        kind: 'toml',
        text: `[mcp_servers.officekit]\ncommand = ${JSON.stringify(path)}\nargs = ["--agent-mcp"]`,
        note: 'Add to ~/.codex/config.toml, then restart Codex.',
      };
    }
    throw new Error('Unknown agent app.');
  }

  function enabledGroups(settings) {
    return Array.isArray(settings && settings.tools) ? settings.tools.filter(id => GROUP_IDS.includes(id)) : GROUP_IDS.slice();
  }

  function withTools(settings, tools) {
    const next = { version: 1, tools: GROUP_IDS.filter(id => tools.includes(id)) };
    if (settings && Array.isArray(settings.allowed_dirs)) next.allowed_dirs = settings.allowed_dirs.slice();
    if (settings && typeof settings.output_dir === 'string') next.output_dir = settings.output_dir;
    return next;
  }

  function withAllowedDirs(settings, folders) {
    return { ...withTools(settings, enabledGroups(settings)), allowed_dirs: folders.slice(0, 20) };
  }

  function folderLabel(path) {
    const parts = String(path).split(/[\\/]+/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : String(path);
  }

  function skillMessage(state) {
    return {
      'not-installed': 'Not installed',
      installed: 'Installed',
      outdated: 'Installed, an update is available',
      foreign: 'A different skill already uses this name',
      unavailable: 'Not available in this build',
    }[state] || 'Status unavailable';
  }

  function invoke(name, args) {
    const call = global.__TAURI__ && global.__TAURI__.core && global.__TAURI__.core.invoke;
    if (typeof call !== 'function') return Promise.reject(new Error('Agent settings are available in the OfficeKit desktop app.'));
    return call(name, args);
  }

  const state = { mounted: false, helper: { available: false, path: null }, settings: { version: 1 }, defaults: null, client: 'claude-code' };

  function el(id) {
    return document.getElementById(id);
  }

  function say(id, message, isError) {
    const node = el(id);
    if (!node) return;
    officekitOutcome.show(node, { state: 'info', text: message });
    node.classList.toggle('text-error', !!isError);
  }

  function renderConnect() {
    const available = state.helper.available;
    const badge = el('agents-helper-badge');
    badge.className = available ? 'badge badge-success badge-soft' : 'badge badge-warning badge-soft';
    badge.textContent = available ? 'Agent helper found' : 'Agent helper not available in this build';
    el('agents-copy').disabled = !available;
    const code = el('agents-config');
    if (!available) {
      code.textContent = 'The agent helper ships with the macOS app. Run the packaged OfficeKit build to connect an agent.';
      el('agents-config-note').textContent = '';
      return;
    }
    const config = clientConfig(state.client, state.helper.path);
    code.textContent = config.text;
    el('agents-config-note').textContent = config.note;
  }

  function selectClient(client) {
    if (!CLIENTS.includes(client)) return;
    state.client = client;
    document.querySelectorAll('[data-agent-client]').forEach(tab => {
      const selected = tab.dataset.agentClient === client;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle('border-indigo-600', selected);
      tab.classList.toggle('text-indigo-700', selected);
      tab.classList.toggle('font-semibold', selected);
      tab.classList.toggle('border-transparent', !selected);
      tab.classList.toggle('text-slate-500', !selected);
      tab.classList.toggle('font-medium', !selected);
    });
    renderConnect();
  }

  function renderGroups() {
    const enabled = enabledGroups(state.settings);
    document.querySelectorAll('[data-agent-group]').forEach(input => {
      input.checked = enabled.includes(input.dataset.agentGroup);
    });
  }

  function renderFolders() {
    const folders = Array.isArray(state.settings.allowed_dirs) ? state.settings.allowed_dirs : state.defaults.allowed_dirs;
    const output = state.settings.output_dir || state.defaults.output_dir;
    el('agents-read-folders').textContent = folders.map(folderLabel).join(', ') + (Array.isArray(state.settings.allowed_dirs) ? '' : ' (default)');
    el('agents-read-folders').title = folders.join('\n');
    el('agents-output-folder').textContent = output;
  }

  // One row per agent: its checkbox, where the skill goes, and its state. Only a skill that is missing or
  // out of date can be (re)installed, and only for an agent that is on this Mac.
  function canInstall(target) {
    return target.present && (target.state === 'not-installed' || target.state === 'outdated');
  }

  function targetNote(target) {
    if (target.state === 'unavailable') return skillMessage('unavailable');
    if (!target.present && target.state !== 'installed') return 'Not found on this Mac';
    return skillMessage(target.state);
  }

  function renderSkill(skill) {
    const targets = Array.isArray(skill && skill.targets) ? skill.targets : [];
    state.skillTargets = targets;
    const box = el('agents-skill-targets');
    const checked = new Set([...box.querySelectorAll('input:checked')].map(input => input.dataset.skillTarget));
    const first = !box.querySelector('input');
    box.textContent = '';
    for (const target of targets) {
      const row = document.createElement('label');
      row.className = 'flex items-center gap-3 rounded-xl bg-slate-100 px-3 py-2.5 text-sm';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'checkbox checkbox-sm';
      input.dataset.skillTarget = target.id;
      input.setAttribute('aria-label', target.label);
      input.disabled = !canInstall(target);
      input.checked = !input.disabled && (first || checked.has(target.id));
      input.addEventListener('change', syncSkillButton);
      const copy = document.createElement('span');
      copy.className = 'min-w-0 flex-1';
      const name = document.createElement('strong');
      name.className = 'block font-semibold';
      name.textContent = target.label;
      const path = document.createElement('small');
      path.className = 'block truncate text-xs text-slate-500';
      path.textContent = target.path || '';
      copy.append(name, path);
      const note = document.createElement('span');
      note.className = 'text-xs font-medium text-slate-500';
      note.dataset.skillState = target.id;
      note.textContent = targetNote(target);
      row.append(input, copy, note);
      box.append(row);
    }
    syncSkillButton();
  }

  function selectedSkillTargets() {
    return [...el('agents-skill-targets').querySelectorAll('input:checked')].map(input => input.dataset.skillTarget);
  }

  function syncSkillButton() {
    const button = el('agents-skill-install');
    const selected = selectedSkillTargets();
    button.disabled = selected.length === 0;
    const outdated = (state.skillTargets || []).some(target => selected.includes(target.id) && target.state === 'outdated');
    button.querySelector('span').textContent = outdated ? 'Update skill' : 'Install skill';
  }

  async function save(next, statusId) {
    try {
      state.settings = await invoke('agent_settings_write', { settings: next });
      say(statusId, APPLY_NOTE, false);
    } catch (error) {
      say(statusId, error && error.message ? error.message : String(error), true);
    }
    renderGroups();
    renderFolders();
  }

  async function refresh() {
    try {
      const [helper, loaded, skill] = await Promise.all([
        invoke('agent_helper_status'), invoke('agent_settings_read'), invoke('agent_skill_status'),
      ]);
      state.helper = helper;
      state.settings = loaded.settings;
      state.defaults = loaded.defaults;
      renderConnect();
      renderGroups();
      renderFolders();
      renderSkill(skill);
      say('agents-skill-status', '', false);
    } catch (error) {
      say('agents-skill-status', error && error.message ? error.message : String(error), true);
    }
  }

  async function copyConfig() {
    const config = clientConfig(state.client, state.helper.path);
    try {
      await navigator.clipboard.writeText(config.text);
      say('agents-copy-status', 'Copied.', false);
    } catch (_) {
      say('agents-copy-status', 'Copy failed. Select the text above and copy it.', true);
    }
  }

  async function installSkill() {
    try {
      const names = (state.skillTargets || []).filter(target => selectedSkillTargets().includes(target.id)).map(target => target.label);
      renderSkill(await invoke('agent_skill_install', { targets: selectedSkillTargets() }));
      say('agents-skill-status', `Skill installed for ${names.join(' and ')}. ${names.length > 1 ? 'They load' : 'It loads'} it automatically.`, false);
    } catch (error) {
      say('agents-skill-status', error && error.message ? error.message : String(error), true);
    }
  }

  async function changeFolders() {
    try {
      const folders = await invoke('agent_choose_folders', { purpose: 'read' });
      if (folders.length) await save(withAllowedDirs(state.settings, folders), 'agents-folders-status');
    } catch (error) {
      say('agents-folders-status', error && error.message ? error.message : String(error), true);
    }
  }

  function bind() {
    document.querySelectorAll('[data-agent-client]').forEach(tab => {
      tab.addEventListener('click', () => selectClient(tab.dataset.agentClient));
      tab.addEventListener('keydown', event => {
        const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (!step) return;
        const next = CLIENTS[(CLIENTS.indexOf(state.client) + step + CLIENTS.length) % CLIENTS.length];
        selectClient(next);
        document.querySelector(`[data-agent-client="${next}"]`).focus();
      });
    });
    document.querySelectorAll('[data-agent-group]').forEach(input => {
      input.addEventListener('change', () => {
        const tools = [...document.querySelectorAll('[data-agent-group]')].filter(box => box.checked).map(box => box.dataset.agentGroup);
        save(withTools(state.settings, tools), 'agents-tools-status');
      });
    });
    el('agents-copy').addEventListener('click', copyConfig);
    el('agents-skill-install').addEventListener('click', installSkill);
    el('agents-change-folders').addEventListener('click', changeFolders);
    el('agents-reveal-output').addEventListener('click', () => {
      invoke('agent_reveal_output').catch(error => say('agents-folders-status', error && error.message ? error.message : String(error), true));
    });
  }

  function mount() {
    if (!el('tab-settings')) return;
    if (!state.mounted) {
      state.mounted = true;
      bind();
      selectClient(state.client);
    }
    return refresh();
  }

  global.OfficeKitAgents = { shellQuote, clientConfig, enabledGroups, withTools, withAllowedDirs, folderLabel, skillMessage, mount, CLIENTS, GROUP_IDS };
  global.officekitMountAgents = mount;
})(typeof window !== 'undefined' ? window : globalThis);
