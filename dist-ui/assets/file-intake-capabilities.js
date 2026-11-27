/* Shared file intake: the catalogue is the compatibility boundary for native and upload tools. */
(function () {
  'use strict';

  // The desktop webview is not served from the API's origin, so every request goes through officekitApiUrl (the
  // authenticated fetch wrapper only recognises the full local address). A bare "/api/…" path fails there with "Load failed".
  const fetch = (path, init) => window.fetch(typeof officekitApiUrl === 'function' ? officekitApiUrl(path) : path, init);

  const GROUP_ICONS = { PDF: 'fa-file-pdf', Images: 'fa-image', Data: 'fa-table', 'File utilities': 'fa-toolbox', Archives: 'fa-file-zipper', Privacy: 'fa-user-shield', Statements: 'fa-file-invoice' };
  const pdf = ['pdf'];
  const images = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif', 'ico', 'svg'];
  const tables = ['csv', 'tsv', 'tab', 'txt', 'xlsx', 'xls', 'json', 'yaml', 'yml'];
  // File utilities (checksum, file type, ZIP, rename, compare…) work on any file, including one with no or an unknown extension.
  const ANY_FILE = '*';
  const allFiles = [ANY_FILE];
  const rows = [];
  const dynamicMediaRows = [];
  const add = (ids, extensions, group, adapter, min = 1, max = 1) => ids.forEach(([id, label, description]) => rows.push({ id, label, description, extensions, group, adapter, min, max,
    maxFileBytes: adapter === 'upload' ? 64 * 1024 * 1024 : null, maxTotalBytes: adapter === 'upload' ? 64 * 1024 * 1024 : null }));
  add([
    ['pdf_editor', 'Edit, annotate & sign PDF', 'Edit supported text and images, annotate, or sign.'],
    ['pdf_protect', 'Protect PDF', 'Add password protection to a PDF.'],
    ['pdf_unlock', 'Unlock PDF', 'Create an unlocked copy of a password protected PDF.'],
    ['pdf_split', 'Split PDF', 'Export selected pages or split into separate PDFs.'],
    ['pdf_compress', 'Compress PDF', 'Reduce PDF size and compare the result.'],
    ['pdf_metadata_strip', 'Remove PDF metadata', 'Create a copy without document metadata.'],
    ['pdf_to_images', 'Convert PDF to images', 'Export PDF pages as image files.'],
    ['pdf_table_extractor', 'Extract tables', 'Find tables and export them to a spreadsheet.'],
    ['pdf_text_extract', 'Extract text', 'Read selectable text from the PDF.'],
    ['pdf_delete_pages', 'Delete PDF pages', 'Create a copy with selected pages removed.'],
    ['pdf_reorder_pages', 'Reorder PDF pages', 'Create a copy with pages in a new order.'],
    ['pdf_rotate_pages', 'Rotate pages', 'Rotate selected pages and save a separate PDF.'],
    ['pdf_metadata_view', 'View PDF details', 'Inspect metadata and page information.'],
    ['pdf_watermark', 'Add watermark', 'Add a text or image watermark.'],
    ['pdf_page_numbers', 'Add page numbers', 'Number pages with a chosen format.'],
    ['pdf_resize_pages', 'Resize pages', 'Change page dimensions while preserving content.'],
    ['pdf_grayscale', 'Convert to grayscale', 'Create a grayscale PDF copy.'],
    ['pdf_flatten', 'Flatten PDF', 'Flatten supported annotations and form elements.'],
  ], pdf, 'PDF', 'upload');
  add([['bank_statement', 'Extract statement data', 'Extract transactions to a spreadsheet with balance checks.']], ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'csv', 'tsv'], 'Statements', 'upload');
  add([['pdf_merge', 'Merge PDFs', 'Combine the selected PDFs in the chosen order.']], pdf, 'PDF', 'upload', 2, 30);
  add([['image_converter', 'Convert SVG image', 'Convert SVG to a supported image format or PDF.']], ['svg'], 'Images', 'upload');
  add([['screenshot_editor', 'Annotate image', 'Crop, blur, highlight, or mask an image.']], ['png', 'jpg', 'jpeg', 'webp', 'tif', 'tiff'], 'Images', 'upload');
  add([
    ['data_converter', 'Convert spreadsheet or data', 'Convert CSV, TSV, Excel, JSON, or YAML.'],
  ], tables, 'Data', 'upload');
  add([
    ['zip_create', 'Create ZIP archive', 'Package the selected files into a ZIP archive.'],
    ['file_info', 'File info', 'Review file sizes, dates, and basic attributes.'],
    ['file_type', 'Identify file type', 'Inspect the actual type of each selected file.'],
    ['file_hash', 'Calculate file hash', 'Calculate SHA-256 or SHA-512 fingerprints.'],
    ['batch_rename', 'Batch rename', 'Preview a consistent naming change for selected files.'],
    ['file_split_join', 'Split or join files', 'Split a large file or join compatible OfficeKit parts.'],
  ], allFiles, 'File utilities', 'native', 1, 30);
  add([['file_compare', 'Compare two files', 'Check whether two selected files are identical and see where they differ.']], allFiles, 'File utilities', 'compare', 2, 2);
  add([
    ['zip_extract', 'Extract ZIP archive', 'Review the archive contents and extract selected files.'],
    ['archive_inspector', 'Inspect ZIP archive', 'Browse archive contents and inspect supported files.'],
  ], ['zip'], 'Archives', 'native', 1, 1);
  add([
    ['pii_redaction', 'Find & mask personal information', 'Review detected sensitive values before creating a masked copy.'],
  ], ['txt', 'md', 'csv', 'pdf', 'png', 'jpg', 'jpeg', 'webp', 'tif', 'tiff', 'bmp', 'gif', 'docx', 'xlsx', 'pptx'], 'Privacy', 'upload');

  // A name with no dot (or only a leading one, like .gitignore) has no extension; it is not its own extension.
  const fileExt = (name) => { const text = String(name || ''), dot = text.lastIndexOf('.'); return dot > 0 ? text.slice(dot + 1).toLowerCase() : ''; };
  const state = { batches: [], current: null, selectedTool: null, files: [], activeFiles: [], handoff: false };
  const setIntakeError = (message) => {
    const alert = byId('file-intake-error');
    alert.textContent = message;
    alert.classList.remove('hidden');
  };
  const clearIntakeError = () => {
    const alert = byId('file-intake-error');
    alert.textContent = '';
    alert.classList.add('hidden');
  };
  let mediaCatalogLoaded = false;
  const seen = new Set();
  const byId = (id) => document.getElementById(id);
  const escapeText = (value) => String(value ?? '');

  function compatible(fileList) {
    const extensions = fileList.map((file) => fileExt(file.name));
    return [...rows, ...dynamicMediaRows].filter((tool) => extensions.length && extensions.every((extension) => tool.extensions.includes(ANY_FILE) || tool.extensions.includes(extension)))
      .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
  }

  async function loadMediaCatalog() {
    if (mediaCatalogLoaded) return;
    mediaCatalogLoaded = true;
    try {
      const response = await fetch('/api/media-capabilities');
      if (!response.ok) return;
      const data = await response.json();
      for (const group of data.media || []) for (const operation of group.operations || []) {
        if (operation.available !== true || !Array.isArray(operation.formats) || !operation.formats.length) continue;
        dynamicMediaRows.push({ id: 'media_toolkit', label: operation.label, description: `Open ${group.label.toLowerCase()} settings for this operation.`, extensions: operation.formats, group: group.label, adapter: 'media', operation: operation.id, min: 1, max: 30,
          maxFileBytes: data.maxInputBytes, maxTotalBytes: data.maxInputBytes });
      }
    } catch {}
  }

  function showCurrent() {
    const batch = state.current;
    if (!batch) return;
    if (state.returnable && state.returnable.batch !== batch) dropReturnable();
    state.files = batch.files;
    state.activeFiles = [...batch.files];
    state.selectedTool = null;
    byId('file-intake-files').replaceChildren(...batch.files.map((file) => {
      const row = document.createElement('label');
      row.className = 'flex cursor-pointer items-center gap-3 py-2 text-sm';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.className = 'checkbox checkbox-sm'; checkbox.checked = true;
      checkbox.onchange = () => {
        state.activeFiles = batch.files.filter((item) => byId(`file-intake-file-${item.id}`)?.checked);
        state.selectedTool = null; renderOptions();
      };
      checkbox.id = `file-intake-file-${file.id}`;
      const extension = fileExt(file.name).toUpperCase() || 'FILE';
      const detail = document.createElement('span'); detail.textContent = file.name;
      const meta = document.createElement('span'); meta.className = 'ok-intake-file-meta'; meta.textContent = `${extension} · ${Number(file.size_bytes).toLocaleString()} bytes`;
      row.append(checkbox, detail, meta);
      return row;
    }));
    const origin = batch.selection.intakeSource === 'open_with' ? 'Opened from Finder' : 'Dropped into OfficeKit';
    byId('file-intake-summary').textContent = `${origin} · ${batch.files.length} file${batch.files.length === 1 ? '' : 's'} selected. Choose a compatible tool; the tool will open for its normal review step.`;
    renderOptions();
    byId('file-intake-status').textContent = '';
    clearIntakeError();
    switchTab('file-intake');
    requestAnimationFrame(() => byId('file-intake-search').focus());
  }

  function renderOptions() {
    const tools = compatible(state.activeFiles);
    const query = byId('file-intake-search').value.trim().toLowerCase();
    const visible = tools.filter((tool) => `${tool.label} ${tool.description} ${tool.group}`.toLowerCase().includes(query));
    if (state.selectedTool && !visible.some((tool) => tool.id === state.selectedTool.id)) {
      state.selectedTool = null;
    }
    const root = byId('file-intake-options');
    root.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement('p');
      empty.className = 'text-sm text-base-content/70';
      empty.textContent = query ? 'No supported tools match this search.' : 'No tools in the current release support this file selection.';
      root.append(empty);
      return;
    }
    let groupName = '';
    let group;
    visible.forEach((tool) => {
      if (groupName !== tool.group) {
        groupName = tool.group;
        const fieldset = document.createElement('fieldset');
        const legend = document.createElement('legend');
        legend.className = 'mb-2 font-semibold';
        legend.textContent = groupName;
        group = document.createElement('div');
        group.className = 'ok-intake-tiles';
        fieldset.append(legend, group);
        root.append(fieldset);
      }
      const label = document.createElement('label');
      label.className = 'ok-intake-tile';
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'file-intake-tool'; radio.value = tool.id; radio.className = 'radio radio-primary radio-sm ok-intake-dot';
      radio.checked = state.selectedTool?.id === tool.id;
      const countOkay = state.activeFiles.length >= tool.min && state.activeFiles.length <= tool.max;
      const totalBytes = state.activeFiles.reduce((total, file) => total + Number(file.size_bytes || 0), 0);
      const sizeOkay = !tool.maxFileBytes || state.activeFiles.every((file) => Number(file.size_bytes) <= tool.maxFileBytes);
      const totalOkay = !tool.maxTotalBytes || totalBytes <= tool.maxTotalBytes;
      radio.disabled = !countOkay || !sizeOkay || !totalOkay;
      // Choosing a tool opens it (approved mock 2026-10-25). A real click or Enter/Space opens; arrow keys only move the choice.
      const choose = () => { if (radio.disabled || state.handoff) return; state.selectedTool = tool; radio.checked = true; void continueToTool(); };
      label.addEventListener('click', (event) => { if (event.detail > 0) choose(); });
      radio.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
      const icon = document.createElement('span'); icon.className = 'ok-intake-icon'; icon.setAttribute('aria-hidden', 'true');
      const glyph = document.createElement('i'); glyph.className = `fa-solid ${GROUP_ICONS[tool.group] || 'fa-wrench'}`; icon.append(glyph);
      const title = document.createElement('span'); title.className = 'ok-intake-name'; title.textContent = tool.label;
      const description = document.createElement('span'); description.className = 'ok-intake-desc'; description.textContent = tool.description;
      const countHint = document.createElement('span'); countHint.className = 'ok-intake-hint';
      const unmet = !countOkay || !sizeOkay || !totalOkay;
      countHint.hidden = !unmet;
      countHint.textContent = !countOkay ? (state.activeFiles.length < tool.min ? `Needs ${tool.min} compatible files` : `Choose at most ${tool.max} file${tool.max === 1 ? '' : 's'}`)
        : !sizeOkay ? `A file exceeds this tool’s ${Math.floor(tool.maxFileBytes / (1024 * 1024))} MiB limit`
          : !totalOkay ? `Selected files exceed this tool’s ${Math.floor(tool.maxTotalBytes / (1024 * 1024))} MiB total limit`
            : `${tool.min === tool.max ? `${tool.min} file${tool.min === 1 ? '' : 's'}` : `1–${tool.max} files`}`;
      if (!countOkay || !sizeOkay || !totalOkay) label.classList.add('opacity-60');
      label.append(radio, icon, title, description, countHint); group.append(label);
    });
  }

  async function contentFiles(selection, files) {
    const result = [];
    for (const file of files) {
      if (file.size_bytes > 64 * 1024 * 1024) throw new Error(`${file.name} exceeds the 64 MiB tool input limit.`);
      const response = await fetch(`/api/file-selections/${encodeURIComponent(selection.id)}/files/${encodeURIComponent(file.id)}/content`);
      if (!response.ok) throw new Error(`${file.name} could not be read. Choose the file again.`);
      const blob = await response.blob();
      result.push(new File([blob], file.name, { type: blob.type || 'application/octet-stream', lastModified: Date.now() }));
    }
    return result;
  }

  async function continueToTool() {
    const tool = state.selectedTool;
    const batch = state.current;
    if (!tool || !batch || state.handoff) return;
    let derivedSelection = null;
    const derivedSelections = [];
    try {
      state.handoff = true; state.handoffTab = null;
      const opened = selectSearchTool(tool.id);
      if (!opened) throw new Error('This tool is not available in the current release.');
      if (tool.id === 'image_converter' && state.activeFiles.every((file) => fileExt(file.name) === 'svg')) setConverterMode('convert');
      const activeIds = state.activeFiles.map((file) => file.id);
      const completeIds = batch.files.map((file) => file.id);
      let toolSelection = batch.selection;
      if (tool.adapter === 'compare') {
        for (const fileId of activeIds) {
          const response = await fetch(`/api/file-selections/${encodeURIComponent(batch.selection.id)}/subsets`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fileIds: [fileId] }),
          });
          if (!response.ok) throw new Error('The selected comparison files could not be prepared. Review the files and try again.');
          derivedSelections.push(await response.json());
        }
        if (!officekitAcceptDirectPair(derivedSelections)) throw new Error('The two files could not be passed to comparison.');
      } else if ((tool.adapter === 'native' || tool.adapter === 'media') && (activeIds.length !== completeIds.length || activeIds.some((id, index) => id !== completeIds[index]))) {
        const response = await fetch(`/api/file-selections/${encodeURIComponent(batch.selection.id)}/subsets`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fileIds: activeIds }),
        });
        if (!response.ok) throw new Error('The selected subset could not be prepared. Review the files and try again.');
        derivedSelection = await response.json();
        toolSelection = derivedSelection;
      }
      if (tool.adapter === 'native') {
        if (!await officekitAcceptDirectSelection({ ...toolSelection, files: state.activeFiles.map((file) => file.name) })) throw new Error('The selected file could not be passed to this tool.');
      } else if (tool.adapter === 'media') {
        const operation = tool.operation;
        if (!operation || !window.officekitMediaToolkit) throw new Error('The media tool is not ready to receive this selection.');
        await window.officekitMediaToolkit.setOperation(operation);
        await window.officekitMediaToolkit.acceptSelection(toolSelection);
      } else {
        const files = await contentFiles(batch.selection, state.activeFiles);
        if (tool.id === 'pdf_editor') {
          const root = byId('pdf-editor-workspace');
          if (files.length !== 1 || !root?.pdfEditor) throw new Error('The PDF editor could not accept this file.');
          await root.pdfEditor.openFile(files[0]);
        } else if (tool.id === 'pii_redaction') {
          if (files.length !== 1 || typeof officekitPiiSelectFile !== 'function') throw new Error('Choose one file for the privacy review.');
          officekitPiiSelectFile(files[0]);
        } else {
          const inputId = tool.id === 'bank_statement' ? 'statement-file-input' : tool.id === 'screenshot_editor' ? 'screenshot-file-input' : tool.extensions.includes('pdf') ? 'pdf-workbench-file-input' : 'generic-file-input';
          const input = byId(inputId);
          if (!input) throw new Error('This tool is not ready to receive the selected file.');
          const transfer = new DataTransfer();
          files.forEach((file) => transfer.items.add(file));
          input.files = transfer.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
      state.current = null;
      state.handoff = false;
      // The opened batch stays available so Esc, Backspace or ⌘Z can return to the tool choice; its selection is released
      // when the user moves on (dropReturnable).
      dropReturnable();
      state.returnable = { batch, activeFiles: [...state.activeFiles], tab: state.handoffTab, release: Boolean(batch.selection?.id && (tool.adapter === 'upload' || derivedSelection || derivedSelections.length)) };
      showBackLink(state.handoffTab);
      if (derivedSelection?.id && tool.adapter === 'upload') void fetch(`/api/file-selections/${encodeURIComponent(derivedSelection.id)}`, { method: 'DELETE' });
      nextBatch();
      void drainNativeQueue();
    } catch (error) {
      state.handoff = false;
      if (derivedSelection?.id) void fetch(`/api/file-selections/${encodeURIComponent(derivedSelection.id)}`, { method: 'DELETE' });
      for (const selection of derivedSelections) void fetch(`/api/file-selections/${encodeURIComponent(selection.id)}`, { method: 'DELETE' });
      setIntakeError(error instanceof Error ? error.message : 'The selected file could not be opened.');
    }
  }

  async function openSelection(selection) {
    if (!selection || typeof selection.id !== 'string') return;
    if (seen.has(selection.id)) return;
    seen.add(selection.id);
    await loadMediaCatalog();
    if (state.batches.length + Number(Boolean(state.current)) >= 8) {
      seen.delete(selection.id);
      setIntakeError('OfficeKit already has eight file batches waiting. Finish one before opening more.');
      return;
    }
    try {
      const response = await fetch(`/api/file-selections/${encodeURIComponent(selection.id)}?limit=30`);
      if (!response.ok) throw new Error('OfficeKit could not read the selected file list.');
      const manifest = await response.json();
      if (manifest.hasMore || manifest.files?.length > 30 || !manifest.files?.length) throw new Error('Choose at most 30 regular files in one batch.');
      state.batches.push({ selection, files: manifest.files });
      if (typeof window.__TAURI__?.core?.invoke === 'function') void window.__TAURI__.core.invoke('file_intake_ack', { selectionId: selection.id });
      // A file already on screen is never swapped silently or left waiting unseen: ask first (approved mock 2026-10-25).
      if (state.current) askReplace();
      else nextBatch();
    } catch (error) {
      seen.delete(selection.id);
      setIntakeError(error instanceof Error ? error.message : 'The selected file list is unavailable.');
      // Show the message: a failure on the page the user is looking at must never look like nothing happened.
      switchTab('file-intake');
    }
  }

  // Back to the tool choice (approved mock 2026-10-25): the opened batch is kept until the user moves on.
  function removeBackLink() { byId('file-intake-back')?.remove(); }

  function showBackLink(tab) {
    removeBackLink();
    const section = tab ? byId(`tab-${tab}`) : null;
    if (!section) return;
    const link = document.createElement('a');
    link.id = 'file-intake-back'; link.href = '#'; link.className = 'ok-intake-back';
    const hint = document.createElement('kbd'); hint.textContent = 'Esc';
    link.append('‹ Back to tool choice ', hint);
    link.addEventListener('click', (event) => { event.preventDefault(); goBack(); });
    section.prepend(link);
  }

  function dropReturnable() {
    const held = state.returnable;
    state.returnable = null;
    removeBackLink();
    if (held?.release && held.batch.selection?.id) void fetch(`/api/file-selections/${encodeURIComponent(held.batch.selection.id)}`, { method: 'DELETE' });
  }

  function goBack() {
    const held = state.returnable;
    if (!held || state.current) return false;
    state.returnable = null;
    removeBackLink();
    state.current = held.batch;
    showCurrent();
    // Keep the subset that was chosen for several files.
    const keep = new Set(held.activeFiles.map((file) => file.id));
    held.batch.files.forEach((file) => { const box = byId(`file-intake-file-${file.id}`); if (box) box.checked = keep.has(file.id); });
    state.activeFiles = held.batch.files.filter((file) => keep.has(file.id));
    renderOptions();
    return true;
  }

  function isTyping(target) {
    return target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="textbox"], [role="combobox"]'));
  }

  function batchLabel(batch) {
    const names = batch.files.map((file) => file.name);
    return names.length > 1 ? `${names[0]} and ${names.length - 1} more` : names[0];
  }

  function askReplace() {
    const dialog = byId('file-intake-replace-dialog');
    const incoming = state.batches[state.batches.length - 1];
    if (!dialog || !incoming || !state.current) return;
    const waiting = state.batches.length - 1;
    byId('file-intake-replace-new').textContent = `You also opened ${batchLabel(incoming)}.${waiting ? ` ${waiting} more ${waiting === 1 ? 'file is' : 'files are'} waiting.` : ''}`;
    byId('file-intake-replace-old').textContent = `Replace ${batchLabel(state.current)} with it, or finish this one first.`;
    if (!dialog.open) dialog.showModal();
  }

  function replaceCurrent() {
    const incoming = state.batches.pop();
    const old = state.current;
    if (!incoming || !old) return;
    state.current = incoming;
    if (old.selection?.id) void fetch(`/api/file-selections/${encodeURIComponent(old.selection.id)}`, { method: 'DELETE' });
    showCurrent();
  }

  function nextBatch() {
    if (state.current) {
      showCurrent();
    } else if (!state.current && state.batches.length) {
      state.current = state.batches.shift();
      showCurrent();
    }
  }

  function leave(destination) {
    if (destination === 'file-intake') return;
    if (state.handoff) { state.handoffTab = destination; return; }
    if (state.returnable && destination !== state.returnable.tab) dropReturnable();
    const replaceDialog = byId('file-intake-replace-dialog');
    if (replaceDialog?.open) replaceDialog.close('keep');
    const selections = [state.current?.selection, ...state.batches.map((batch) => batch.selection)].filter((selection) => selection?.id);
    state.current = null; state.batches = []; state.selectedTool = null; state.files = []; state.activeFiles = [];
    for (const selection of selections) void fetch(`/api/file-selections/${encodeURIComponent(selection.id)}`, { method: 'DELETE' });
  }

  byId('file-intake-search').addEventListener('input', renderOptions);
  document.addEventListener('keydown', (event) => {
    if (!state.returnable || state.current || event.defaultPrevented || event.isComposing) return;
    const undo = (event.metaKey || event.ctrlKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'z';
    if (event.key !== 'Escape' && event.key !== 'Backspace' && !undo) return;
    if (isTyping(event.target) || document.querySelector('dialog[open]')) return;
    event.preventDefault();
    goBack();
  });
  // Keep current (and Esc) leave the new file waiting; Replace swaps to it and discards the old selection.
  byId('file-intake-replace-dialog').addEventListener('close', (event) => { if (event.target.returnValue === 'replace') replaceCurrent(); event.target.returnValue = ''; });
  window.OfficeKitFileIntake = Object.freeze({ open: openSelection, refresh: nextBatch, leave });
  const drainNativeQueue = async () => {
    try {
      const pending = await window.__TAURI__?.core?.invoke?.('file_intake_pending');
      if (Array.isArray(pending)) for (const selection of pending) void openSelection(selection);
    } catch {}
  };
  window.__TAURI__?.event?.listen('officekit-file-intake', () => void drainNativeQueue());
  window.__TAURI__?.event?.listen('officekit-file-intake-error', (event) => { setIntakeError(event.payload?.message || 'OfficeKit could not open these files.'); switchTab('file-intake'); });
  window.addEventListener('dragover', (event) => { if (event.dataTransfer?.types?.includes('Files')) event.preventDefault(); });
  void drainNativeQueue();
})();
