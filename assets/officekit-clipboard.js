/**
 * OfficeKit - Unified Clipboard Manager & Snippets Studio
 * Combines features from PasteBar, Maccy, Clipy, CopyQ, and Espanso:
 * - Local-first clipboard history with auto-categorization and pin management
 * - Instant 1–9 numeric keyboard shortcuts in Quick Paste palette
 * - CopyQ-style one-click string transformations
 * - Clipy-style snippet folders and library management with JSON export/import
 * - Espanso-style dynamic templates with {{variables}} and interactive prompt filling
 */

(function (global) {
  'use strict';

  const state = {
    viewMode: 'clips', // 'clips' | 'snippets' | 'dictation'
    dictations: [],
    selectedDictation: null,
    activeBoard: 'all', // 'all' | 'pinned' | 'code' | 'link' | 'image'
    activeFolderId: 'all',
    searchQuery: '',
    clips: [],
    snippets: [],
    folders: [{ id: 'default', name: 'General', icon: 'fa-folder' }],
    selectedClip: null,
    selectedSnippet: null,
    quickPaletteItems: [],
    quickPaletteIndex: 0,
    lastCopiedText: '',
  };

  function apiFetch(endpoint, options = {}) {
    const url = typeof officekitApiUrl === 'function' ? officekitApiUrl(endpoint) : endpoint;
    const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    return fetch(url, Object.assign({}, options, { headers }));
  }

  function showToast(message, type = 'info') {
    if (typeof showAppFeedbackToast === 'function') {
      showAppFeedbackToast(message, type);
    } else {
      console.log(`[OfficeKit Clipboard] ${type}: ${message}`);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatRelativeTime(timestamp) {
    if (!timestamp) return '';
    const now = Date.now() / 1000;
    const diff = Math.max(0, Math.floor(now - timestamp));
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  // =========================================================================
  // Native Bridge: Copy & Paste
  // =========================================================================

  async function copyToClipboard(text, notify = true) {
    if (typeof text !== 'string') return;
    try {
      if (typeof window.__TAURI__?.core?.invoke === 'function') {
        try {
          await window.__TAURI__.core.invoke('result_copy_text', { text });
        } catch (err) {
          await navigator.clipboard.writeText(text);
        }
      } else {
        await navigator.clipboard.writeText(text);
      }
      state.lastCopiedText = text;
      if (notify) showToast('Copied to clipboard!', 'success');
    } catch (e) {
      showToast('Could not copy to clipboard: ' + e.message, 'error');
    }
  }

  async function pasteActiveText(text) {
    if (!text) return;
    await copyToClipboard(text, false);
    if (typeof window.__TAURI__?.core?.invoke === 'function') {
      try {
        await window.__TAURI__.core.invoke('dictation_paste_text', { text });
        showToast('Pasted into active app!', 'success');
        return;
      } catch (err) {
        // Fallback if accessibility permission not granted
      }
    }
    showToast('Copied! Press Cmd+V (or Ctrl+V) to paste.', 'success');
  }

  // =========================================================================
  // API Integration: Clips & History
  // =========================================================================

  async function loadClips() {
    try {
      const params = new URLSearchParams();
      if (state.searchQuery.trim()) params.set('search', state.searchQuery.trim());
      if (state.activeBoard === 'pinned') {
        params.set('pinned_only', 'true');
      } else if (state.activeBoard !== 'all') {
        params.set('category', state.activeBoard);
      }
      params.set('limit', '100');

      const res = await apiFetch(`/api/clipboard/history?${params.toString()}`);
      if (!res.ok) return;
      const data = await res.json();
      state.clips = data.clips || [];

      // Update badge count
      const badge = document.getElementById('clipboard-count-badge');
      if (badge) badge.textContent = String(data.total || state.clips.length);

      // Refresh selection
      if (state.clips.length > 0) {
        if (!state.selectedClip || !state.clips.some(c => c.id === state.selectedClip.id)) {
          state.selectedClip = state.clips[0];
        } else {
          state.selectedClip = state.clips.find(c => c.id === state.selectedClip.id) || state.clips[0];
        }
      } else {
        state.selectedClip = null;
      }

      renderClipsList();
      renderInspector();
    } catch (e) {
      console.error('Error loading clips:', e);
    }
  }

  // Dictation transcripts live in this window's own history (never the clipboard database), so the tab only
  // reads them: the text is shown, copied or pasted, and nothing is written or sent anywhere.
  function loadDictations() {
    const query = state.searchQuery.trim().toLowerCase();
    const entries = typeof global.officekitDictationEntries === 'function' ? global.officekitDictationEntries() : [];
    state.dictations = entries.filter(entry => !query || entry.text.toLowerCase().includes(query));
    if (!state.dictations.some(entry => entry.id === state.selectedDictation?.id)) {
      state.selectedDictation = state.dictations[0] || null;
    }
    renderDictationList();
    renderInspector();
  }

  function renderDictationList() {
    const container = document.getElementById('clipboard-dictation-container');
    if (!container) return;
    container.replaceChildren();
    if (state.dictations.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'p-8 text-center text-slate-400';
      const note = document.createElement('p');
      note.className = 'text-xs';
      note.textContent = 'No dictation transcripts yet. Dictate with your shortcut and they appear here.';
      empty.append(note);
      container.append(empty);
      return;
    }
    state.dictations.forEach(entry => {
      const selected = state.selectedDictation?.id === entry.id;
      const item = document.createElement('div');
      item.className = `group p-3 rounded-xl border transition cursor-pointer select-none mb-2 ${
        selected ? 'border-sky-500 bg-sky-500/5 shadow-sm' : 'border-slate-200 dark:border-white/10 hover:border-slate-300 dark:hover:border-white/20 bg-white dark:bg-white/5'}`;
      item.onclick = () => { state.selectedDictation = entry; renderDictationList(); renderInspector(); };
      const text = document.createElement('p');
      text.className = 'text-xs text-slate-700 dark:text-slate-200 line-clamp-2 break-words';
      text.textContent = entry.text;
      const meta = document.createElement('div');
      meta.className = 'mt-2 text-[10px] text-slate-400';
      const when = new Date(entry.createdAt);
      const label = { 'push-to-talk': 'push-to-talk', meeting: 'meeting', 'audio-file': 'audio file' }[entry.source] || '';
      meta.textContent = `${Number.isNaN(when.getTime()) ? '' : when.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}${label ? ` · ${label}` : ''}`;
      item.append(text, meta);
      container.append(item);
    });
  }

  async function syncCurrentClipboard() {
    // The desktop app captures copies natively; reading the clipboard from the page would only
    // raise macOS's "Paste" prompt and mislabel the source app.
    if (window.__TAURI__) return;
    try {
      let currentText = '';
      if (navigator.clipboard && navigator.clipboard.readText) {
        try {
          currentText = await navigator.clipboard.readText();
        } catch (_) {}
      }
      if (!currentText || currentText === state.lastCopiedText) return;

      const res = await apiFetch('/api/clipboard/clips', {
        method: 'POST',
        body: JSON.stringify({ text_content: currentText, source_app: 'OfficeKit' }),
      });
      if (res.ok) {
        state.lastCopiedText = currentText;
        await loadClips();
      }
    } catch (_) {}
  }

  async function toggleClipPin(clipId, e) {
    if (e) e.stopPropagation();
    try {
      const res = await apiFetch(`/api/clipboard/clips/${clipId}/pin`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      if (res.ok) {
        await loadClips();
      }
    } catch (e) {
      showToast('Failed to toggle pin', 'error');
    }
  }

  async function deleteClip(clipId, e) {
    if (e) e.stopPropagation();
    try {
      const res = await apiFetch(`/api/clipboard/clips/${clipId}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('Clip deleted', 'info');
        if (state.selectedClip?.id === clipId) {
          state.selectedClip = null;
          renderInspector();
        }
        await loadClips();
      }
    } catch (e) {
      showToast('Failed to delete clip', 'error');
    }
  }

  async function clearHistory(keepPinned = true) {
    if (!confirm(keepPinned ? 'Clear unpinned clipboard history?' : 'Clear ALL clipboard history including pinned items?')) {
      return;
    }
    try {
      const res = await apiFetch('/api/clipboard/clear', {
        method: 'POST',
        body: JSON.stringify({ keep_pinned: keepPinned }),
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Cleared ${data.deleted_count} items`, 'info');
        await loadClips();
      }
    } catch (e) {
      showToast('Failed to clear history', 'error');
    }
  }

  // =========================================================================
  // API Integration: Snippets & Folders
  // =========================================================================

  async function loadFolders() {
    try {
      const res = await apiFetch('/api/clipboard/folders');
      if (res.ok) {
        const data = await res.json();
        state.folders = data.folders || [];
        renderFolders();
      }
    } catch (e) {
      console.error('Error loading folders:', e);
    }
  }

  async function loadSnippets() {
    try {
      const params = new URLSearchParams();
      if (state.activeFolderId && state.activeFolderId !== 'all') {
        params.set('folder_id', state.activeFolderId);
      }
      if (state.searchQuery.trim()) {
        params.set('search', state.searchQuery.trim());
      }
      const res = await apiFetch(`/api/clipboard/snippets?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        state.snippets = data.snippets || [];
        if (state.snippets.length > 0) {
          if (!state.selectedSnippet || !state.snippets.some(s => s.id === state.selectedSnippet.id)) {
            state.selectedSnippet = state.snippets[0];
          }
        } else {
          state.selectedSnippet = null;
        }
        renderSnippetsList();
        renderInspector();
      }
    } catch (e) {
      console.error('Error loading snippets:', e);
    }
  }

  async function saveSnippetFromForm(e) {
    if (e) e.preventDefault();
    const titleInput = document.getElementById('snippet-form-title');
    const contentInput = document.getElementById('snippet-form-content');
    const folderInput = document.getElementById('snippet-form-folder');
    const triggerInput = document.getElementById('snippet-form-trigger');
    const shortcutInput = document.getElementById('snippet-form-shortcut');
    const idInput = document.getElementById('snippet-form-id');

    if (!titleInput || !contentInput) return;
    const title = titleInput.value.trim();
    const content = contentInput.value;
    if (!title || !content) {
      showToast('Title and content are required', 'warning');
      return;
    }

    const payload = {
      title,
      content,
      folder_id: folderInput ? folderInput.value : 'default',
      trigger_key: triggerInput && triggerInput.value.trim() ? triggerInput.value.trim() : null,
      shortcut_number: shortcutInput && shortcutInput.value ? parseInt(shortcutInput.value, 10) : null,
      snippet_id: idInput && idInput.value ? idInput.value : null,
    };

    try {
      const res = await apiFetch('/api/clipboard/snippets', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Snippet saved successfully!', 'success');
        closeSnippetModal();
        await loadSnippets();
      }
    } catch (err) {
      showToast('Failed to save snippet: ' + err.message, 'error');
    }
  }

  async function deleteSnippet(snippetId, e, skipConfirm = false) {
    if (e) e.stopPropagation();
    if (!skipConfirm && !confirm('Are you sure you want to remove this snippet?')) return;
    try {
      const res = await apiFetch(`/api/clipboard/snippets/${snippetId}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('Snippet removed', 'info');
        if (state.selectedSnippet?.id === snippetId) {
          state.selectedSnippet = null;
          renderInspector();
        }
        closeSnippetModal();
        await loadSnippets();
      }
    } catch (e) {
      showToast('Failed to remove snippet', 'error');
    }
  }

  async function createFolderPrompt() {
    const name = prompt('Enter new Snippets folder name:');
    if (!name || !name.trim()) return;
    try {
      const res = await apiFetch('/api/clipboard/folders', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), icon: 'fa-folder' }),
      });
      if (res.ok) {
        showToast('Folder created', 'success');
        await loadFolders();
      }
    } catch (e) {
      showToast('Failed to create folder', 'error');
    }
  }

  // =========================================================================
  // Transformations (CopyQ-Inspired)
  // =========================================================================

  async function applyTransform(transformName) {
    if (!state.selectedClip && !state.selectedSnippet) return;
    const text = state.viewMode === 'clips'
      ? state.selectedClip?.text_content
      : state.selectedSnippet?.content;
    if (!text) return;

    try {
      const res = await apiFetch('/api/clipboard/transform', {
        method: 'POST',
        body: JSON.stringify({ text, transform: transformName }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Transform failed');
      }
      const data = await res.json();
      const newText = data.result;

      // Copy transformed text
      await copyToClipboard(newText, false);
      showToast(`Applied ${transformName} & copied to clipboard!`, 'success');

      // Update preview if text changed
      const previewTextarea = document.getElementById('clipboard-preview-textarea');
      if (previewTextarea) previewTextarea.value = newText;
    } catch (e) {
      showToast('Transformation error: ' + e.message, 'error');
    }
  }

  // =========================================================================
  // Dynamic Templates & Espanso Expansion Form
  // =========================================================================

  function openDynamicTemplateModal(snippet) {
    if (!snippet || !snippet.content) return;
    const modal = document.getElementById('officekit-template-modal');
    if (!modal) return;

    const titleEl = document.getElementById('template-modal-title');
    const fieldsContainer = document.getElementById('template-modal-fields');
    const previewEl = document.getElementById('template-modal-preview');

    if (titleEl) titleEl.textContent = `Expand Snippet: ${snippet.title}`;

    // Extract variables
    const matches = snippet.content.match(/\{\{([a-zA-Z0-9_:-]+)\}\}/g) || [];
    const uniqueVars = Array.from(new Set(matches.map(m => m.slice(2, -2))));

    fieldsContainer.innerHTML = '';
    const formValues = {};

    uniqueVars.forEach(v => {
      const vLower = v.toLowerCase();
      const isBuiltin = vLower.startsWith('date') || vLower.startsWith('time') || vLower === 'clipboard' || vLower === 'uuid';
      if (!isBuiltin) {
        const fieldRow = document.createElement('div');
        fieldRow.className = 'flex flex-col gap-1 mb-2';
        fieldRow.innerHTML = `
          <label class="text-xs font-semibold text-slate-700 dark:text-slate-300 capitalize">${escapeHtml(v.replace(/_/g, ' '))}:</label>
          <input type="text" data-template-var="${escapeHtml(v)}" class="input input-sm input-bordered w-full" placeholder="Enter ${escapeHtml(v)}..." />
        `;
        fieldsContainer.appendChild(fieldRow);
      }
    });

    const updatePreview = async () => {
      const inputs = fieldsContainer.querySelectorAll('[data-template-var]');
      inputs.forEach(input => {
        formValues[input.dataset.templateVar] = input.value;
      });
      try {
        const res = await apiFetch('/api/clipboard/snippets/render', {
          method: 'POST',
          body: JSON.stringify({
            template: snippet.content,
            values: formValues,
            current_clipboard: state.lastCopiedText || '',
          }),
        });
        if (res.ok) {
          const data = await res.json();
          if (previewEl) previewEl.textContent = data.rendered;
        }
      } catch (_) {}
    };

    fieldsContainer.querySelectorAll('input').forEach(input => {
      input.addEventListener('input', updatePreview);
    });

    updatePreview();

    const insertBtn = document.getElementById('template-modal-insert');
    if (insertBtn) {
      insertBtn.onclick = async () => {
        const rendered = previewEl ? previewEl.textContent : '';
        modal.close();
        closeQuickPalette();
        await pasteActiveText(rendered);
      };
    }

    modal.showModal();
    const firstInput = fieldsContainer.querySelector('input');
    if (firstInput) firstInput.focus();
  }

  // =========================================================================
  // Import & Export Snippets (Clipy-Inspired)
  // =========================================================================

  async function exportSnippets() {
    try {
      const res = await apiFetch('/api/clipboard/snippets/export');
      if (!res.ok) throw new Error('Export failed');
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `officekit-snippets-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast('Snippets exported successfully!', 'success');
    } catch (e) {
      showToast('Export failed: ' + e.message, 'error');
    }
  }

  function triggerImportSnippets() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const json = JSON.parse(text);
        const res = await apiFetch('/api/clipboard/snippets/import', {
          method: 'POST',
          body: JSON.stringify({ data: json, merge: true }),
        });
        if (!res.ok) throw new Error('Invalid snippets file format');
        const outcome = await res.json();
        showToast(`Imported ${outcome.imported_snippets} snippets & ${outcome.imported_folders} folders!`, 'success');
        await loadFolders();
        await loadSnippets();
      } catch (e) {
        showToast('Import error: ' + e.message, 'error');
      }
    };
    input.click();
  }

  // =========================================================================
  // Quick-Paste Palette Overlay (Maccy-Inspired 1–9 Hotkey Modal)
  // =========================================================================

  function openQuickPalette() {
    const modal = document.getElementById('officekit-quickpaste-modal');
    if (!modal) return;
    modal.showModal();
    state.quickPaletteIndex = 0;
    const searchInput = document.getElementById('quickpaste-search');
    if (searchInput) {
      searchInput.value = '';
      searchInput.focus();
    }
    renderQuickPaletteItems();
  }

  function closeQuickPalette() {
    const modal = document.getElementById('officekit-quickpaste-modal');
    if (modal && modal.open) modal.close();
  }

  function renderQuickPaletteItems() {
    const container = document.getElementById('quickpaste-items-list');
    if (!container) return;

    const query = (document.getElementById('quickpaste-search')?.value || '').toLowerCase().trim();
    let items = [];

    if (state.viewMode === 'snippets') {
      items = state.snippets.filter(s =>
        !query || s.title.toLowerCase().includes(query) || s.content.toLowerCase().includes(query)
      ).map(s => ({
        id: s.id,
        type: 'snippet',
        title: s.title,
        text: s.content,
        icon: 'fa-quote-left',
        badge: s.shortcut_number ? String(s.shortcut_number) : null,
        raw: s,
      }));
    } else {
      items = state.clips.filter(c =>
        !query || c.text_content.toLowerCase().includes(query)
      ).map((c, i) => ({
        id: c.id,
        type: 'clip',
        title: c.text_content.slice(0, 100).replace(/\n/g, ' '),
        text: c.text_content,
        icon: c.content_type === 'code' ? 'fa-code' : (c.content_type === 'link' ? 'fa-link' : (c.content_type === 'image' ? 'fa-image' : 'fa-align-left')),
        badge: i < 9 ? String(i + 1) : null,
        pinned: c.pinned,
        raw: c,
      }));
    }

    state.quickPaletteItems = items;
    container.innerHTML = '';

    if (items.length === 0) {
      container.innerHTML = `
        <div class="py-8 text-center text-sm text-slate-400">
          <i class="fa-solid fa-inbox text-2xl mb-2 opacity-50"></i>
          <p>No items found matching your search</p>
        </div>
      `;
      return;
    }

    items.slice(0, 25).forEach((item, index) => {
      const isSelected = index === state.quickPaletteIndex;
      const el = document.createElement('div');
      el.className = `flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition select-none ${
        isSelected
          ? 'bg-sky-500 text-white font-medium'
          : 'hover:bg-slate-100 dark:hover:bg-white/5 text-slate-800 dark:text-slate-200'
      }`;
      el.onclick = () => selectQuickPaletteItem(index);

      el.innerHTML = `
        <div class="w-6 h-6 rounded flex items-center justify-center shrink-0 ${
          isSelected ? 'bg-white/20 text-white' : 'bg-slate-200 dark:bg-white/10 text-slate-600 dark:text-slate-400'
        }">
          <i class="fa-solid ${item.icon} text-xs"></i>
        </div>
        <div class="flex-1 min-w-0">
          <div class="text-xs truncate">${escapeHtml(item.title)}</div>
        </div>
        ${item.pinned ? `<i class="fa-solid fa-thumbtack text-[10px] ${isSelected ? 'text-amber-200' : 'text-amber-500'}"></i>` : ''}
        ${
          item.badge
            ? `<kbd class="px-1.5 py-0.5 text-[10px] font-mono rounded border ${
                isSelected
                  ? 'border-white/30 bg-white/20 text-white'
                  : 'border-slate-300 dark:border-white/20 bg-slate-100 dark:bg-white/10 text-slate-600 dark:text-slate-300'
              }">${item.badge}</kbd>`
            : ''
        }
        <button type="button" title="Delete" class="p-1 rounded opacity-50 hover:opacity-100 transition text-xs ${isSelected ? 'text-white/80 hover:text-white hover:bg-white/20' : 'text-slate-400 hover:text-rose-500 hover:bg-slate-200 dark:hover:bg-white/10'}" data-qp-delete="${index}">
          <i class="fa-solid fa-trash-can text-[11px]"></i>
        </button>
      `;

      const delBtn = el.querySelector(`[data-qp-delete="${index}"]`);
      if (delBtn) {
        delBtn.onclick = (e) => {
          e.stopPropagation();
          deleteQuickPaletteItem(index);
        };
      }

      container.appendChild(el);
    });
  }

  async function deleteQuickPaletteItem(index) {
    const item = state.quickPaletteItems[index];
    if (!item) return;
    if (item.type === 'clip') {
      await deleteClip(item.id);
    } else if (item.type === 'snippet') {
      await deleteSnippet(item.id, null, true);
    }
    await loadQuickPaletteItems();
    if (state.quickPaletteIndex >= state.quickPaletteItems.length) {
      state.quickPaletteIndex = Math.max(0, state.quickPaletteItems.length - 1);
    }
    renderQuickPaletteItems();
  }

  async function selectQuickPaletteItem(index) {
    const item = state.quickPaletteItems[index];
    if (!item) return;

    if (item.type === 'snippet') {
      const hasVariables = /\{\{([a-zA-Z0-9_:-]+)\}\}/.test(item.text);
      if (hasVariables) {
        closeQuickPalette();
        openDynamicTemplateModal(item.raw);
        return;
      }
    }

    closeQuickPalette();
    await pasteActiveText(item.text);
  }

  // =========================================================================
  // Rendering Studio UI (3-Column Layout)
  // =========================================================================

  function renderFolders() {
    const container = document.getElementById('clipboard-folders-list');
    if (!container) return;
    container.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.className = `w-full text-left px-3 py-1.5 rounded-lg text-xs flex items-center gap-2 transition ${
      state.activeFolderId === 'all'
        ? 'bg-sky-500/10 text-sky-600 dark:text-sky-400 font-semibold'
        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/5'
    }`;
    allBtn.innerHTML = '<i class="fa-solid fa-layer-group text-xs"></i> <span>All Folders</span>';
    allBtn.onclick = () => {
      state.activeFolderId = 'all';
      renderFolders();
      loadSnippets();
    };
    container.appendChild(allBtn);

    state.folders.forEach(f => {
      const btn = document.createElement('button');
      btn.className = `w-full text-left px-3 py-1.5 rounded-lg text-xs flex items-center gap-2 transition ${
        state.activeFolderId === f.id
          ? 'bg-sky-500/10 text-sky-600 dark:text-sky-400 font-semibold'
          : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/5'
      }`;
      btn.innerHTML = `<i class="fa-solid ${escapeHtml(f.icon || 'fa-folder')} text-xs"></i> <span class="truncate">${escapeHtml(f.name)}</span>`;
      btn.onclick = () => {
        state.activeFolderId = f.id;
        renderFolders();
        loadSnippets();
      };
      container.appendChild(btn);
    });
  }

  function renderClipsList() {
    const container = document.getElementById('clipboard-clips-container');
    if (!container) return;
    container.innerHTML = '';

    if (state.clips.length === 0) {
      container.innerHTML = `
        <div class="p-8 text-center text-slate-400">
          <i class="fa-solid fa-clipboard text-3xl mb-2 opacity-40"></i>
          <p class="text-xs">No clipboard items found</p>
        </div>
      `;
      return;
    }

    state.clips.forEach((clip, index) => {
      const isSelected = state.selectedClip?.id === clip.id;
      const el = document.createElement('div');
      el.className = `group p-3 rounded-xl border transition cursor-pointer select-none mb-2 ${
        isSelected
          ? 'border-sky-500 bg-sky-500/5 shadow-sm'
          : 'border-slate-200 dark:border-white/10 hover:border-slate-300 dark:hover:border-white/20 bg-white dark:bg-white/5'
      }`;
      el.onclick = () => {
        state.selectedClip = clip;
        renderClipsList();
        renderInspector();
      };

      const icon = clip.content_type === 'code' ? 'fa-code text-amber-500' :
                   clip.content_type === 'link' ? 'fa-link text-indigo-500' :
                   clip.content_type === 'image' ? 'fa-image text-purple-500' : 'fa-align-left text-sky-500';

      el.innerHTML = `
        <div class="flex items-center justify-between gap-2 mb-1">
          <div class="flex items-center gap-1.5 min-w-0">
            <i class="fa-solid ${icon} text-xs"></i>
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">${clip.content_type}</span>
            ${index < 9 ? `<span class="px-1 text-[9px] font-mono font-bold rounded bg-slate-100 dark:bg-white/10 text-slate-500">⌘${index + 1}</span>` : ''}
          </div>
          <div class="flex items-center gap-1">
            <button type="button" title="${clip.pinned ? 'Unpin' : 'Pin'}" class="btn btn-ghost btn-xs p-1 text-slate-400 hover:text-amber-500 ${clip.pinned ? 'text-amber-500' : ''}" data-pin-id="${clip.id}">
              <i class="fa-solid fa-thumbtack text-xs"></i>
            </button>
            <button type="button" title="Delete" class="btn btn-ghost btn-xs p-1 text-slate-400 hover:text-rose-500 opacity-60 hover:opacity-100 transition" data-delete-id="${clip.id}">
              <i class="fa-solid fa-trash text-xs"></i>
            </button>
          </div>
        </div>
        <p class="text-xs text-slate-700 dark:text-slate-200 line-clamp-2 font-mono break-all">${escapeHtml(clip.text_content)}</p>
        <div class="mt-2 flex items-center justify-between text-[10px] text-slate-400">
          <span>${formatRelativeTime(clip.created_at)}</span>
          <span>${clip.char_count} chars · ${clip.word_count} words</span>
        </div>
      `;

      el.querySelector(`[data-pin-id="${clip.id}"]`).onclick = (e) => toggleClipPin(clip.id, e);
      el.querySelector(`[data-delete-id="${clip.id}"]`).onclick = (e) => deleteClip(clip.id, e);

      container.appendChild(el);
    });
  }

  function renderSnippetsList() {
    const container = document.getElementById('clipboard-snippets-container');
    if (!container) return;
    container.innerHTML = '';

    if (state.snippets.length === 0) {
      container.innerHTML = `
        <div class="p-8 text-center text-slate-400">
          <i class="fa-solid fa-quote-left text-3xl mb-2 opacity-40"></i>
          <p class="text-xs">No snippets in this folder</p>
          <button type="button" class="btn btn-xs btn-primary mt-3" onclick="officekitOpenSnippetModal()">+ New Snippet</button>
        </div>
      `;
      return;
    }

    state.snippets.forEach(snip => {
      const isSelected = state.selectedSnippet?.id === snip.id;
      const el = document.createElement('div');
      el.className = `group p-3 rounded-xl border transition cursor-pointer select-none mb-2 ${
        isSelected
          ? 'border-cyan-500 bg-cyan-500/5 shadow-sm'
          : 'border-slate-200 dark:border-white/10 hover:border-slate-300 dark:hover:border-white/20 bg-white dark:bg-white/5'
      }`;
      el.onclick = () => {
        state.selectedSnippet = snip;
        renderSnippetsList();
        renderInspector();
      };

      const hasVariables = /\{\{([a-zA-Z0-9_:-]+)\}\}/.test(snip.content);

      el.innerHTML = `
        <div class="flex items-center justify-between gap-2 mb-1">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">${escapeHtml(snip.title)}</span>
            ${hasVariables ? '<span class="px-1 text-[9px] font-bold rounded bg-cyan-500/10 text-cyan-600">Template</span>' : ''}
          </div>
          <div class="flex items-center gap-1">
            ${snip.trigger_key ? `<kbd class="px-1 text-[10px] font-mono rounded bg-slate-100 dark:bg-white/10 text-slate-500">${escapeHtml(snip.trigger_key)}</kbd>` : ''}
            <button type="button" title="Edit" class="btn btn-ghost btn-xs p-1 text-slate-400 hover:text-sky-500" data-edit-id="${snip.id}">
              <i class="fa-solid fa-pen text-xs"></i>
            </button>
            <button type="button" title="Remove snippet" class="btn btn-ghost btn-xs p-1 text-slate-400 hover:text-rose-500 opacity-60 hover:opacity-100 transition" data-delete-id="${snip.id}">
              <i class="fa-solid fa-trash text-xs"></i>
            </button>
          </div>
        </div>
        <p class="text-xs text-slate-600 dark:text-slate-300 line-clamp-2 font-mono break-all">${escapeHtml(snip.content)}</p>
        <div class="mt-2 flex items-center justify-between text-[10px] text-slate-400">
          <span>${escapeHtml(snip.folder_name || 'General')}</span>
          <span>${snip.content.length} chars</span>
        </div>
      `;

      el.querySelector(`[data-edit-id="${snip.id}"]`).onclick = (e) => {
        e.stopPropagation();
        openSnippetModal(snip);
      };
      el.querySelector(`[data-delete-id="${snip.id}"]`).onclick = (e) => deleteSnippet(snip.id, e);

      container.appendChild(el);
    });
  }

  function renderInspector() {
    const emptyEl = document.getElementById('clipboard-inspector-empty');
    const contentEl = document.getElementById('clipboard-inspector-content');
    if (!emptyEl || !contentEl) return;

    const dictation = state.viewMode === 'dictation';
    const currentItem = dictation ? state.selectedDictation : state.viewMode === 'clips' ? state.selectedClip : state.selectedSnippet;
    if (!currentItem) {
      emptyEl.classList.remove('hidden');
      contentEl.classList.add('hidden');
      return;
    }

    emptyEl.classList.add('hidden');
    contentEl.classList.remove('hidden');
    // Transcripts are read-only here: no transformations, snippet creation or delete (history is managed on the Dictation page).
    ['clipboard-inspector-transforms', 'clipboard-action-delete', 'clipboard-action-save-as-snippet'].forEach(id => document.getElementById(id)?.classList.toggle('hidden', dictation));

    const textarea = document.getElementById('clipboard-preview-textarea');
    const statsEl = document.getElementById('clipboard-inspector-stats');
    const titleEl = document.getElementById('clipboard-inspector-title');

    const text = dictation ? currentItem.text : state.viewMode === 'clips' ? currentItem.text_content : currentItem.content;
    if (textarea) { textarea.value = text; textarea.readOnly = dictation; }
    if (titleEl) {
      titleEl.textContent = dictation ? 'DICTATION'
        : state.viewMode === 'clips'
        ? (currentItem.content_type.toUpperCase() + ' CLIP')
        : currentItem.title;
    }
    if (statsEl) {
      statsEl.textContent = `${text.length} chars · ${text.split(/\s+/).filter(Boolean).length} words · ${text.split('\n').length} lines`;
    }

    // Dynamic template form section in inspector
    const templateSection = document.getElementById('clipboard-inspector-template-box');
    if (templateSection) {
      const hasVariables = !dictation && /\{\{([a-zA-Z0-9_:-]+)\}\}/.test(text);
      templateSection.classList.toggle('hidden', !hasVariables);
    }

    const deleteBtn = document.getElementById('clipboard-action-delete');
    const deleteLabel = document.getElementById('clipboard-action-delete-label');
    if (deleteBtn) {
      if (deleteLabel) {
        deleteLabel.textContent = state.viewMode === 'clips' ? 'Delete' : 'Remove';
      }
      deleteBtn.title = state.viewMode === 'clips' ? 'Delete clip from history' : 'Remove snippet';
    }
  }

  // =========================================================================
  // Snippet Modal Form Handling
  // =========================================================================

  function openSnippetModal(snippet = null) {
    const modal = document.getElementById('officekit-snippet-form-modal');
    if (!modal) return;

    const modalTitle = document.getElementById('snippet-modal-heading');
    const titleInput = document.getElementById('snippet-form-title');
    const contentInput = document.getElementById('snippet-form-content');
    const folderSelect = document.getElementById('snippet-form-folder');
    const triggerInput = document.getElementById('snippet-form-trigger');
    const shortcutInput = document.getElementById('snippet-form-shortcut');
    const idInput = document.getElementById('snippet-form-id');
    const deleteBtn = document.getElementById('snippet-modal-delete');

    if (deleteBtn) {
      if (snippet && snippet.id) {
        deleteBtn.classList.remove('hidden');
        deleteBtn.onclick = () => deleteSnippet(snippet.id);
      } else {
        deleteBtn.classList.add('hidden');
        deleteBtn.onclick = null;
      }
    }

    // Populate folder dropdown
    if (folderSelect) {
      folderSelect.innerHTML = '';
      state.folders.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.textContent = f.name;
        folderSelect.appendChild(opt);
      });
    }

    if (snippet) {
      if (modalTitle) modalTitle.textContent = 'Edit Snippet';
      if (titleInput) titleInput.value = snippet.title || '';
      if (contentInput) contentInput.value = snippet.content || '';
      if (folderSelect) folderSelect.value = snippet.folder_id || 'default';
      if (triggerInput) triggerInput.value = snippet.trigger_key || '';
      if (shortcutInput) shortcutInput.value = snippet.shortcut_number || '';
      if (idInput) idInput.value = snippet.id || '';
    } else {
      if (modalTitle) modalTitle.textContent = 'New Reusable Snippet';
      if (titleInput) titleInput.value = '';
      if (contentInput) contentInput.value = state.selectedClip ? state.selectedClip.text_content : '';
      if (folderSelect) folderSelect.value = state.activeFolderId !== 'all' ? state.activeFolderId : 'default';
      if (triggerInput) triggerInput.value = '';
      if (shortcutInput) shortcutInput.value = '';
      if (idInput) idInput.value = '';
    }

    modal.showModal();
    if (titleInput) titleInput.focus();
  }

  function closeSnippetModal() {
    const modal = document.getElementById('officekit-snippet-form-modal');
    if (modal && modal.open) modal.close();
  }

  // =========================================================================
  // Keyboard Navigation & Shortcuts
  // =========================================================================

  function bindKeyboardHandlers() {
    // Global hotkey: Alt+V (Option+V) or Cmd+Shift+V to toggle Quick Palette
    window.addEventListener('keydown', (e) => {
      if ((e.altKey && e.code === 'KeyV') || (e.metaKey && e.shiftKey && e.code === 'KeyV')) {
        e.preventDefault();
        const modal = document.getElementById('officekit-quickpaste-modal');
        if (modal?.open) {
          closeQuickPalette();
        } else {
          openQuickPalette();
        }
        return;
      }

      const clipboardTab = document.getElementById('tab-clipboard');
      if (clipboardTab && !clipboardTab.classList.contains('hidden')) {
        if (!['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
          if (e.key === 'Backspace' || e.key === 'Delete') {
            if (state.viewMode === 'clips' && state.selectedClip) {
              e.preventDefault();
              deleteClip(state.selectedClip.id);
            } else if (state.viewMode === 'snippets' && state.selectedSnippet) {
              e.preventDefault();
              deleteSnippet(state.selectedSnippet.id);
            }
          }
        }
      }
    });

    // Quick Palette modal keyboard navigation
    const modal = document.getElementById('officekit-quickpaste-modal');
    if (modal) {
      modal.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          closeQuickPalette();
          return;
        }

        const searchInput = document.getElementById('quickpaste-search');

        // Delete highlighted item via Backspace or Delete
        if ((e.key === 'Backspace' || e.key === 'Delete') && (e.metaKey || e.altKey || document.activeElement !== searchInput || searchInput?.value === '')) {
          e.preventDefault();
          if (state.quickPaletteItems.length > 0) {
            deleteQuickPaletteItem(state.quickPaletteIndex);
          }
          return;
        }

        // Numeric keys 1–9 for instant selection
        if (/^[1-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
          if (document.activeElement !== searchInput || searchInput.value === '') {
            const numIndex = parseInt(e.key, 10) - 1;
            if (numIndex < state.quickPaletteItems.length) {
              e.preventDefault();
              selectQuickPaletteItem(numIndex);
              return;
            }
          }
        }

        // Arrow navigation
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          state.quickPaletteIndex = Math.min(state.quickPaletteItems.length - 1, state.quickPaletteIndex + 1);
          renderQuickPaletteItems();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          state.quickPaletteIndex = Math.max(0, state.quickPaletteIndex - 1);
          renderQuickPaletteItems();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (state.quickPaletteItems.length > 0) {
            selectQuickPaletteItem(state.quickPaletteIndex);
          }
        }
      });
    }

    // Auto sync clipboard when window gains focus
    window.addEventListener('focus', () => {
      syncCurrentClipboard();
    });
  }

  // =========================================================================
  // Mounting & Initialization
  // =========================================================================

  function mountClipboard() {
    bindKeyboardHandlers();
    loadFolders();
    loadClips();
    loadSnippets();
    syncCurrentClipboard();

    // Set up search bar
    const searchInput = document.getElementById('clipboard-search-input');
    if (searchInput) {
      searchInput.oninput = (e) => {
        state.searchQuery = e.target.value;
        if (state.viewMode === 'clips') loadClips();
        else if (state.viewMode === 'dictation') loadDictations();
        else loadSnippets();
      };
    }

    // Set up Quick Palette search input
    const qpSearch = document.getElementById('quickpaste-search');
    if (qpSearch) {
      qpSearch.oninput = () => {
        state.quickPaletteIndex = 0;
        renderQuickPaletteItems();
      };
    }

    // Setup action button listeners for CSP compliance
    document.getElementById('clipboard-action-quickpaste')?.addEventListener('click', openQuickPalette);
    document.getElementById('clipboard-action-new-snippet')?.addEventListener('click', () => openSnippetModal());
    document.getElementById('clipboard-action-import')?.addEventListener('click', triggerImportSnippets);
    document.getElementById('clipboard-action-export')?.addEventListener('click', exportSnippets);
    document.getElementById('clipboard-action-clear-unpinned')?.addEventListener('click', () => clearHistory(true));
    document.getElementById('clipboard-action-clear-all')?.addEventListener('click', () => clearHistory(false));
    document.getElementById('clipboard-action-new-folder')?.addEventListener('click', createFolderPrompt);
    document.getElementById('clipboard-action-copy')?.addEventListener('click', () => {
      const text = document.getElementById('clipboard-preview-textarea')?.value;
      if (text) copyToClipboard(text);
    });
    document.getElementById('clipboard-action-paste')?.addEventListener('click', () => {
      const text = document.getElementById('clipboard-preview-textarea')?.value;
      if (text) pasteActiveText(text);
    });
    document.getElementById('clipboard-action-delete')?.addEventListener('click', () => {
      if (state.viewMode === 'clips' && state.selectedClip) {
        deleteClip(state.selectedClip.id);
      } else if (state.viewMode === 'snippets' && state.selectedSnippet) {
        deleteSnippet(state.selectedSnippet.id);
      }
    });
    document.getElementById('clipboard-action-expand-template')?.addEventListener('click', () => {
      const item = state.viewMode === 'clips' ? state.selectedClip : state.selectedSnippet;
      if (item) openDynamicTemplateModal(item);
    });
    document.getElementById('clipboard-action-save-as-snippet')?.addEventListener('click', () => openSnippetModal());
    document.getElementById('clipboard-mode-clips-btn')?.addEventListener('click', () => global.officekitClipboard.switchMode('clips'));
    document.getElementById('clipboard-mode-snippets-btn')?.addEventListener('click', () => global.officekitClipboard.switchMode('snippets'));
    document.getElementById('clipboard-mode-dictation-btn')?.addEventListener('click', () => global.officekitClipboard.switchMode('dictation'));
    document.getElementById('snippet-modal-delete')?.addEventListener('click', () => {
      const id = document.getElementById('snippet-form-id')?.value;
      if (id) deleteSnippet(id);
    });

    document.querySelectorAll('[data-clipboard-board]').forEach(btn => {
      btn.addEventListener('click', () => {
        global.officekitClipboard.switchBoard(btn.dataset.clipboardBoard);
      });
    });

    document.querySelectorAll('[data-clipboard-transform]').forEach(btn => {
      btn.addEventListener('click', () => {
        applyTransform(btn.dataset.clipboardTransform);
      });
    });

    document.getElementById('snippet-form')?.addEventListener('submit', saveSnippetFromForm);
    document.getElementById('snippet-modal-cancel')?.addEventListener('click', closeSnippetModal);
    document.getElementById('template-modal-cancel')?.addEventListener('click', () => {
      document.getElementById('officekit-template-modal')?.close();
    });
  }

  // Expose global interface for DOM event handlers
  global.officekitClipboard = {
    mount: mountClipboard,
    loadClips,
    loadSnippets,
    deleteClip,
    deleteSnippet,
    clearHistory,
    applyTransform,
    copyCurrent: () => {
      const text = document.getElementById('clipboard-preview-textarea')?.value;
      if (text) copyToClipboard(text);
    },
    pasteCurrent: () => {
      const text = document.getElementById('clipboard-preview-textarea')?.value;
      if (text) pasteActiveText(text);
    },
    openSnippetModal,
    closeSnippetModal,
    saveSnippetFromForm,
    createFolderPrompt,
    exportSnippets,
    importSnippets: triggerImportSnippets,
    openQuickPalette,
    closeQuickPalette,
    switchMode: (mode) => {
      state.viewMode = mode;
      const modes = { clips: 'clipboard-clips-container', snippets: 'clipboard-snippets-container', dictation: 'clipboard-dictation-container' };
      Object.entries(modes).forEach(([name, containerId]) => {
        document.getElementById(containerId)?.classList.toggle('hidden', name !== mode);
        const button = document.getElementById(`clipboard-mode-${name}-btn`);
        button?.classList.toggle('btn-primary', name === mode);
        button?.classList.toggle('btn-ghost', name !== mode);
        if (name === 'dictation') button?.setAttribute('aria-pressed', String(name === mode));
      });
      const search = document.getElementById('clipboard-search-input');
      if (search) search.placeholder = mode === 'dictation' ? 'Search dictation…' : 'Search clips (text, apps)...';
      if (mode === 'clips') loadClips();
      else if (mode === 'dictation') loadDictations();
      else loadSnippets();
    },
    switchBoard: (board) => {
      state.activeBoard = board;
      document.querySelectorAll('[data-clipboard-board]').forEach(btn => {
        if (btn.dataset.clipboardBoard === board) {
          btn.classList.add('bg-sky-500/10', 'text-sky-600', 'font-semibold');
        } else {
          btn.classList.remove('bg-sky-500/10', 'text-sky-600', 'font-semibold');
        }
      });
      loadClips();
    },
    openTemplateExpander: () => {
      const item = state.viewMode === 'clips' ? state.selectedClip : state.selectedSnippet;
      if (item) openDynamicTemplateModal(item);
    },
  };

  global.officekitMountClipboard = mountClipboard;
  global.officekitOpenQuickPalette = openQuickPalette;
  global.officekitOpenSnippetModal = openSnippetModal;

})(typeof window !== 'undefined' ? window : this);
