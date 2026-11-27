(() => {
  const POLL_MS = 500;
  const SPEAKING_MS = 2500;
  const AUTO_CLEAR_KEY = 'officekit.speechCoach.liveWorkspace.autoClearMinutes';
  const invoke = (command, args = {}) => window.__TAURI__.core.invoke(command, args);
  const el = id => document.getElementById(id);
  const stateText = { listening: 'Listening · speak naturally', checking: 'Checking the last sentence…', unavailable: 'Listening · pace and pitch only' };
  let lastGrowth = 0;
  let lastTranscript = null;
  let currentSnapshot = null;
  let copyTimer = 0;
  let autoClearTimer = 0;
  let autoClearDeadline = 0;
  let snapshotEpoch = 0;
  const fixRows = new Map();

  const node = (tag, className, text) => {
    const created = document.createElement(tag);
    if (className) created.className = className;
    if (text !== undefined) created.textContent = text;
    return created;
  };

  const appleNotes = {
    off: 'Apple Intelligence is turned off, so word-choice suggestions are off. Basic grammar checks are on.',
    preparing: 'Apple Intelligence is still getting ready. Basic grammar checks are on.',
    unsupported: "This Mac can't run Apple Intelligence (it needs an Apple Silicon Mac on macOS 26 or later), so word-choice suggestions are off. Basic grammar checks are on."
  };

  const renderTranscript = snapshot => {
    const box = el('ws-box');
    // Follow the newest words unless the person scrolled up to read.
    const following = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
    box.replaceChildren();
    if (following) queueMicrotask(() => { box.scrollTop = box.scrollHeight; });
    if (!snapshot.parts.length) {
      box.append(node('span', 'empty', 'Your words appear here as you speak. Improvements appear below.'));
      return;
    }
    // Improvements owns the proposed rewrite and dismissal action. Keep this pad a
    // readable, faithful record of what was spoken rather than repeating that advice.
    for (const part of snapshot.parts) box.append(document.createTextNode(part.text));
  };

  const renderFixes = snapshot => {
    const list = el('ws-list');
    if (!snapshot.fixes.length) {
      for (const row of fixRows.values()) row.remove();
      fixRows.clear();
      let row = list.firstElementChild;
      if (!row || !row.classList.contains('empty-row')) {
        row?.remove();
        row = node('li', 'row empty-row');
        list.append(row);
      }
      row.replaceChildren(node('span', 'empty', snapshot.checksAvailable ? 'Nothing to fix yet.' : 'Not checked.'));
      return;
    }
    list.querySelector('.empty-row')?.remove();
    const wanted = new Set(snapshot.fixes.map(fix => fix.id));
    for (const [id, row] of fixRows) {
      if (!wanted.has(id)) { row.remove(); fixRows.delete(id); }
    }
    snapshot.fixes.forEach((fix, index) => {
      let row = fixRows.get(fix.id);
      const signature = JSON.stringify([fix.quote, fix.suggestion, fix.hint, fix.category, fix.rule]);
      if (!row || row.dataset.signature !== signature) {
        row?.remove();
        row = node('li', 'row');
        const text = node('span', 'fix');
        text.append(node('s', '', fix.quote), document.createTextNode(' → '), node('em', '', fix.suggestion));
        const why = node('span', 'why');
        why.append(node('span', 'pill', fix.category), document.createTextNode(fix.hint));
        const dismiss = node('a', 'dismiss', 'Not a mistake');
        dismiss.href = '#';
        dismiss.setAttribute('aria-label', `Not a mistake: ${fix.quote}`);
        dismiss.addEventListener('click', event => { event.preventDefault(); void dismissFix(fix.id); });
        row.append(text, why, dismiss);
        // The rule behind the fix, so the speaker learns why and not only what to say instead.
        if (fix.rule) {
          const rule = node('p', 'rule');
          rule.append(node('b', '', 'Rule: '), document.createTextNode(fix.rule.rule));
          const example = node('span', 'ex');
          example.append(node('i', '', fix.rule.wrong), document.createTextNode(' → '), node('u', '', fix.rule.right));
          rule.append(example);
          row.append(rule);
        }
        row.dataset.fixId = String(fix.id);
        row.dataset.signature = signature;
        fixRows.set(fix.id, row);
      }
      const atIndex = list.children[index];
      if (atIndex !== row) list.insertBefore(row, atIndex || null);
    });
  };

  const render = snapshot => {
    const now = Date.now();
    const transcript = snapshot.parts.map(part => part.text).join('');
    if (transcript !== lastTranscript) lastGrowth = now;
    lastTranscript = transcript;
    currentSnapshot = snapshot;
    el('ws-state').textContent = stateText[snapshot.state] || stateText.listening;
    const note = appleNotes[snapshot.appleStatus];
    el('ws-warning').hidden = !note || !snapshot.checksAvailable;
    el('ws-warning-text').textContent = note || '';
    el('ws-apple-link').hidden = snapshot.appleStatus !== 'off';
    el('ws-clear').hidden = snapshot.wordCount === 0;
    el('ws-note').textContent = el('ws-auto-clear').value === '0'
      ? 'Stays on this Mac · cleared when you press Clear or close'
      : 'Stays on this Mac · cleared by Clear, selected timer or close';
    const pace = el('ws-pace');
    pace.hidden = snapshot.paceWpm == null;
    pace.textContent = snapshot.paceWpm == null ? '' : `Pace ${snapshot.paceWpm} WPM`;
    el('ws-bars').classList.toggle('speaking', now - lastGrowth < SPEAKING_MS && snapshot.wordCount > 0);
    renderTranscript(snapshot);
    renderFixes(snapshot);
    // Never claim "0 mistakes" when nothing was checked.
    el('ws-count').textContent = snapshot.checksAvailable ? String(snapshot.fixes.length) : '—';
    const copy = el('ws-copy');
    // The copied text is the corrected text; the label stays short.
    copy.textContent = 'Copy';
    copy.title = snapshot.checksAvailable ? 'Copy the corrected text' : 'Copy the text';
    copy.disabled = snapshot.wordCount === 0;
    if (!copyTimer) {
      const count = snapshot.fixes.length;
      el('ws-summary').textContent = snapshot.checksAvailable && count ? `${count} ${count === 1 ? 'fix' : 'fixes'}` : '';
    }
    syncAutoClear(snapshot);
  };

  const savedAutoClearMinutes = () => {
    try {
      const value = window.localStorage.getItem(AUTO_CLEAR_KEY);
      return ['0', '5', '10'].includes(value) ? value : '0';
    } catch { return '0'; }
  };
  el('ws-auto-clear').value = savedAutoClearMinutes();

  const cancelAutoClear = () => {
    if (autoClearTimer) clearTimeout(autoClearTimer);
    autoClearTimer = 0;
    autoClearDeadline = 0;
  };

  const clearWorkspace = async () => {
    const epoch = ++snapshotEpoch;
    try {
      const snapshot = await invoke('coach_workspace_clear');
      if (epoch === snapshotEpoch) render(snapshot);
    } catch { if (epoch === snapshotEpoch) await refresh(); }
  };

  function syncAutoClear(snapshot) {
    const duration = Number(el('ws-auto-clear').value) * 60_000;
    if (!duration || !snapshot.wordCount) { cancelAutoClear(); return; }
    const deadline = lastGrowth + duration;
    if (deadline === autoClearDeadline) return;
    cancelAutoClear();
    autoClearDeadline = deadline;
    autoClearTimer = setTimeout(async () => {
      autoClearTimer = 0;
      autoClearDeadline = 0;
      await clearWorkspace();
    }, Math.max(0, deadline - Date.now()));
  }

  const refresh = async () => {
    const epoch = snapshotEpoch;
    try {
      const snapshot = await invoke('coach_workspace_snapshot');
      if (epoch === snapshotEpoch) render(snapshot);
    } catch { /* the panel is closing */ }
  };

  const dismissFix = async fixId => {
    const epoch = ++snapshotEpoch;
    try {
      const snapshot = await invoke('coach_workspace_dismiss', { fixId });
      if (epoch === snapshotEpoch) render(snapshot);
    } catch { if (epoch === snapshotEpoch) await refresh(); }
  };

  const say = message => {
    el('ws-summary').textContent = message;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copyTimer = 0; void refresh(); }, 2000);
  };

  el('ws-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(await invoke('coach_workspace_corrected_text'));
      say('Copied');
    } catch { say('Copy failed'); }
  });

  el('ws-clear').addEventListener('click', () => { void clearWorkspace(); });

  el('ws-auto-clear').addEventListener('change', event => {
    try { window.localStorage.setItem(AUTO_CLEAR_KEY, event.currentTarget.value); } catch { /* The choice still applies until the workspace closes. */ }
    autoClearDeadline = 0;
    if (currentSnapshot) syncAutoClear(currentSnapshot);
  });

  el('ws-apple-link').addEventListener('click', async event => {
    event.preventDefault();
    try { await invoke('coach_workspace_open_apple_intelligence'); } catch { say('System Settings did not open'); }
  });

  el('ws-done').addEventListener('click', async () => {
    try { await invoke('coach_workspace_done'); } catch { /* already closed */ }
  });

  void refresh();
  setInterval(refresh, POLL_MS);
})();
