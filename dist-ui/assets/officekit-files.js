/* Desktop filesystem tools reference native-authorized originals, never cloned inputs. */
let officekitDirectFilesState = { action: 'file_hash', selections: [], job: null, report: null, preview: null, busy: false, archiveFormat: null, archiveCapabilities: {}, archiveOffset: 0 };
// Read-only scans: they reuse the selection → job → results flow and never remove or change originals.
const officekitInspectTools = {
  file_info: { kind: 'file-info', title: 'File info', run: 'Show file info', subfolders: false, description: 'See size, dates and basic attributes of selected originals. Nothing is changed.' },
  file_compare: { kind: 'compare-files', title: 'Compare two files', run: 'Compare two files', description: 'Check whether two files are identical, and see where they differ. Nothing is merged or changed.' },
  file_age_finder: { kind: 'file-age', title: 'File age finder', run: 'Find files', subfolders: true, description: 'List files whose modified or created date falls inside the range. Both dates are included.' },
  empty_file_finder: { kind: 'empty-files', title: 'Empty file finder', run: 'Find empty files', subfolders: false, description: 'List zero-byte files for review. Nothing is removed.' },
  empty_folder_finder: { kind: 'empty-folders', title: 'Empty-folder finder', run: 'Find empty folders', description: 'Check folders from the deepest level up. Review only; nothing is removed.' },
  symlink_inspector: { kind: 'symlinks', title: 'Symlink inspector', run: 'Inspect links', subfolders: true, description: 'Find links in a folder and see where each one points, without following them.' },
};
// Read-only results: Run hides after a result until the selection or an option changes (approved v3 re-mock, Button Limit).
const officekitReadOnlyActions = new Set([...Object.keys(officekitInspectTools), 'file_type', 'file_hash', 'duplicates', 'folder_compare', 'similar_images']);
const officekitDirectKinds = { rename: 'rename-preview', duplicates: 'duplicates', storage: 'storage', folder_compare: 'compare-folders', similar_images: 'similar-images', file_hash: 'hash', file_type: 'file-type', split_join: 'split', archive: 'archive-extract', ...Object.fromEntries(Object.entries(officekitInspectTools).map(([action, tool]) => [action, tool.kind])) };
function officekitDirectNode(tag, text, className) { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; if (tag === 'button') node.classList.add('btn', className?.includes('primary') ? 'btn-primary' : 'btn-outline'); if (tag === 'select') node.classList.add('select'); if (tag === 'input') node.classList.add('input'); return node; }
// A button element drawn as an in-text link, exempt from the three-button count (AGENTS.md Button Limit).
function officekitAsTextLink(node) { node.className = 'ok-text-link'; return node; }
function officekitTextLink(text, id, onclick) { const link = officekitAsTextLink(document.createElement('button')); link.id = id; link.type = 'button'; link.textContent = text; link.onclick = onclick; return link; }
async function officekitDirectFetch(path, options) {
  const response = await fetch(officekitApiUrl(path), options);
  if (!response.ok) { let detail; try { detail = (await response.json()).detail; } catch {} throw Error(typeof detail === 'string' ? detail : 'The file operation failed. Review the selection and try again.'); }
  return response;
}
function officekitBindDirectFiles() {
  const container = document.getElementById('tab-workspace');
  container.replaceChildren();
  const heading = officekitDirectNode('h1', 'Storage analyser & cleaner'); heading.id = 'direct-file-title';
  const description = officekitDirectNode('p', 'Find what takes up space, then review what to remove.'); description.id = 'direct-file-description';
  const selections = officekitDirectNode('section', '', 'ok-file-panel'); selections.id = 'direct-selections';
  // Choosers and Reset are in-text links beside the selection line; only Run, and Cancel during a run, are buttons (approved button rules).
  const files = officekitTextLink('Choose files…', 'direct-choose-files', () => officekitChooseDirectSelection('files', 0));
  const folders = officekitTextLink('Choose folder…', 'direct-choose-folder', () => officekitChooseDirectSelection('folder', 0));
  const second = officekitTextLink('Choose folder B…', 'direct-folder-b', () => officekitChooseDirectSelection(officekitDirectFilesState.action === 'file_compare' ? 'files' : 'folder', 1));
  second.hidden = true;
  const reset = officekitTextLink('Reset selection', 'direct-reset-selection', officekitResetDirectSelection);
  const summary = officekitDirectNode('span', 'No files selected.'); summary.id = 'direct-selection-summary';
  const hint = officekitDirectNode('small', 'Choose them from this Mac. Nothing is uploaded.', 'ok-selection-hint'); hint.id = 'direct-selection-hint';
  const links = officekitDirectNode('span', '', 'ok-selection-links'); links.append(files, folders, second, reset);
  const selectionLine = officekitDirectNode('div', '', 'ok-selection-line'); selectionLine.id = 'direct-selection-line'; selectionLine.dataset.empty = 'true'; selectionLine.append(summary, hint, links);
  const options = officekitDirectNode('div'); options.id = 'direct-file-options';
  const run = officekitDirectNode('button', 'Run'); run.className = 'btn btn-primary'; run.id = 'direct-file-run'; run.type = 'button'; run.disabled = true; run.onclick = () => officekitRunDirectFiles();
  const cancel = officekitDirectNode('button', 'Cancel'); cancel.id = 'direct-file-cancel'; cancel.type = 'button'; cancel.hidden = true; cancel.onclick = async () => { try { await officekitDirectFetch(`/api/file-jobs/${officekitDirectFilesState.job}/cancellations`, {method:'POST', headers:{'Content-Type':'application/json'},body:'{}'}); officekitDirectStatus('Cancellation requested.'); } catch(error) { officekitDirectStatus(error.message); } };
  const status = officekitDirectNode('p'); status.id = 'direct-file-status'; status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
  const results = officekitDirectNode('section', '', 'ok-file-panel'); results.id = 'direct-file-results'; results.hidden = true;
  const actions = officekitDirectNode('div', '', 'flex flex-wrap items-center justify-end gap-2 mt-4'); actions.id = 'direct-file-actions'; actions.append(run, cancel);
  selections.append(selectionLine, options, actions, status); container.append(heading, description, selections, results);
  document.getElementById('zip-select-button').onclick = () => { switchTab('workspace'); officekitOpenDirectFileTool('archive'); officekitChooseDirectSelection('files',0); };
  document.getElementById('zip-extract-button').onclick = () => { switchTab('workspace'); officekitOpenDirectFileTool('archive'); };
  document.getElementById('zip-download-button').hidden = true;
  document.getElementById('zip-clear-button').hidden = true;
  const zipStatus = document.getElementById('zip-workspace-status'); if (zipStatus) officekitOutcome.show(zipStatus, { state: 'success', text: 'Choose the original archive and an extraction folder. No input copy is created.' });
  window.officekitDirectFilesReady = true;
}
function officekitDirectStatus(text) {
  const el = document.getElementById('direct-file-status');
  if (!el) return;
  el.textContent = text;
  if (text && /permission|access/i.test(text) && typeof window.__TAURI__?.core?.invoke === 'function') {
    const permBtn = document.createElement('button');
    permBtn.type = 'button';
    permBtn.className = 'btn btn-xs btn-outline ml-2 rounded-lg font-semibold';
    permBtn.textContent = 'Open System Settings →';
    permBtn.onclick = async () => {
      try { await tauriInvoke()('storage_permissions_open'); } catch (_) {}
    };
    el.append(' ', permBtn);
  }
}
function officekitOpenDirectFileTool(action) {
  const trash = action === 'trash_restore';
  if (!trash && !Object.hasOwn(officekitDirectKinds, action)) return false;
  if (officekitDirectFilesState.busy) { officekitDirectStatus('Wait for this operation or cancel it before switching file tools.'); return false; }
  if (trash) { officekitTrashRestoreOpen(); return true; }
  officekitTrashRestoreShow(false);
  officekitDirectFilesState.action = action; officekitDirectFilesState.preview = null; officekitDirectFilesState.report = null;
  officekitDirectFilesState.archiveFormat = null;
  officekitDirectFilesState.archiveCapabilities = {};
  document.getElementById('direct-file-run').dataset.actionIcon = {rename:'pen-to-square',duplicates:'magnifying-glass',storage:'chart-pie',folder_compare:'columns',similar_images:'images',file_hash:'fingerprint',file_type:'file-circle-question',split_join:'scissors',archive:'file-zipper',file_info:'circle-info',file_compare:'code-compare',file_age_finder:'calendar-days',empty_file_finder:'file',empty_folder_finder:'folder-open',symlink_inspector:'link'}[action];
  const inspect = officekitInspectTools[action];
  const title = action === 'archive' ? 'Archive tools' : inspect ? inspect.title : WORKSPACE_TOOL_COPY[action].title;
  document.getElementById('direct-file-title').textContent = title;
  const chooseFiles = document.getElementById('direct-choose-files'), chooseFolder = document.getElementById('direct-choose-folder'), chooseSecond = document.getElementById('direct-folder-b');
  const pairFiles = action === 'file_compare';
  // Chooser wording follows the selection (officekitDirectUpdateSelection). The symlink inspector is folder-only, so it has no files chooser.
  // Similar images works on whole photo folders, so only the folder chooser applies.
  chooseFiles.hidden = action === 'symlink_inspector' || action === 'similar_images';
  officekitDirectFilesState.imageSummary = null;
  chooseFolder.hidden = pairFiles;
  chooseSecond.hidden = action !== 'folder_compare' && !pairFiles;
  document.getElementById('direct-file-description').textContent = inspect ? inspect.description : action === 'rename' ? 'Preview name changes, then rename the selected originals in their existing folder.' : action === 'duplicates' ? 'Find identical files, choose the copies you don’t need, then move them to Trash.' : action === 'archive' ? 'Browse supported archives, extract selected entries, or create a ZIP on this computer.' : action === 'file_hash' ? 'Get a fingerprint of a file to check it was not changed or corrupted. Nothing leaves this Mac.' : 'Choose original files or folders. OfficeKit reads them directly.';
  const options = document.getElementById('direct-file-options'); options.replaceChildren();
  options.addEventListener('change', officekitInvalidateDirectResult);
  options.addEventListener('input', officekitInvalidateDirectResult);
  document.getElementById('direct-selections').classList.toggle('ok-duplicate-inputs', action === 'duplicates');
  const field = (id, label, choices = null, defaultValue = '') => { const wrap = officekitDirectNode('label', label); const input = document.createElement(choices ? 'select' : 'input'); input.className = choices ? 'select ' : 'input '; input.id = id; if (choices) for (const [value,name] of choices) { const opt = officekitDirectNode('option',name); opt.value=value; input.append(opt); } else { input.value=defaultValue; input.maxLength=100; } wrap.append(input); options.append(wrap); return input; };
  if (action === 'file_hash') {
    // The select keeps the value the run reads; a two-way toggle is what people see.
    const algorithm = field('direct-hash-algorithm','Algorithm',[['sha256','SHA-256'],['sha512','SHA-512']]);
    algorithm.hidden = true;
    const toggle = officekitDirectNode('div', '', 'ok-hash-algorithm'); toggle.setAttribute('role', 'group'); toggle.setAttribute('aria-label', 'Algorithm');
    for (const [value, name] of [['sha256', 'SHA-256'], ['sha512', 'SHA-512']]) {
      const choice = officekitDirectNode('button', name); choice.type = 'button'; choice.dataset.algorithm = value;
      choice.setAttribute('aria-pressed', String(algorithm.value === value));
      choice.onclick = () => {
        algorithm.value = value;
        for (const other of toggle.children) other.setAttribute('aria-pressed', String(other === choice));
        algorithm.dispatchEvent(new Event('change', { bubbles: true }));
      };
      toggle.append(choice);
    }
    algorithm.parentElement.append(toggle);
    options.append(officekitDirectNode('p', 'SHA-256 is the common choice for checking downloads.', 'ok-hash-hint'));
  }
  if (action === 'duplicates') {
    const scope = field('direct-duplicate-mode', 'Find', [['files', 'Identical files'], ['folders', 'Identical folders']]);
    scope.setAttribute('aria-label', 'Find');
    const hint = officekitDirectNode('p', 'Includes all subfolders. Scans stay inside the selected folder; links are skipped.');
    options.append(hint);
    scope.onchange = () => {
      officekitDirectFilesState.report = null;
      document.getElementById('direct-file-results').hidden = true;
      officekitDirectStatus('Match type changed. Find duplicates again to update the results.');
      officekitDirectUpdateSelection();
    };
  }
  if (action === 'similar_images') {
    const input=field('direct-similarity','Sensitivity',null,'8'); input.type='number'; input.min='0'; input.max='16';
    options.append(officekitDirectNode('p', 'Photos taken close together, and files with matching names, are compared first so large folders stay fast.', 'ok-hash-hint'));
    const ready = officekitDirectNode('p', '', 'ok-image-ready'); ready.id = 'direct-image-ready'; ready.setAttribute('role', 'status'); options.append(ready);
  }
  if (action === 'rename') {
    // Only the fields the chosen rule uses are shown: sequence and affix use prefix/suffix, replace uses find/replace.
    const pattern = field('direct-rename-pattern','How to rename',[['sequence','Add a number'],['affix','Add prefix or suffix'],['replace','Find and replace'],['casing','Change case']]);
    const prefix = field('direct-rename-prefix','Prefix');
    const suffix = field('direct-rename-suffix','Suffix');
    const find = field('direct-rename-find','Find');
    const replace = field('direct-rename-replace','Replace with');
    const showRuleFields = () => {
      const affix = pattern.value === 'sequence' || pattern.value === 'affix';
      prefix.parentElement.hidden = !affix; suffix.parentElement.hidden = !affix;
      find.parentElement.hidden = pattern.value !== 'replace'; replace.parentElement.hidden = pattern.value !== 'replace';
    };
    pattern.addEventListener('change', showRuleFields);
    showRuleFields();
  }
  if (action === 'split_join') { field('direct-parts-mode','Operation',[['split','Split file'],['join','Join OfficeKit parts']]); const size=field('direct-part-size','Part size (MiB)',null,'50'); size.type='number'; size.min='1'; size.max='1024'; }
  if (inspect && inspect.subfolders !== undefined) { const label = officekitDirectNode('label', 'Include subfolders'); const box = document.createElement('input'); box.type = 'checkbox'; box.id = 'direct-include-subfolders'; box.className = 'checkbox checkbox-sm'; box.checked = inspect.subfolders; label.prepend(box); options.append(label); }
  if (action === 'file_age_finder') { field('direct-age-field', 'Date', [['modified', 'Modified'], ['created', 'Created']]); field('direct-age-from', 'From').type = 'date'; field('direct-age-to', 'To').type = 'date'; options.append(officekitDirectNode('p', 'Dates use this Mac’s time zone: from 00:00 on the first day to 23:59:59 on the last day. Leave one empty for an open range.')); window.OfficeKitDatePicker?.initialize(options); }
  if (action === 'archive') {
    const mode=field('direct-archive-mode','Operation',[['archive-extract','Browse / extract archive'],['archive-create','Create archive']]);
    field('direct-archive-format','Format',[['zip','ZIP']]);
    mode.onchange=()=>{document.getElementById('direct-file-run').textContent=mode.value==='archive-create'?'Create ZIP':'Extract selected or all';officekitDirectUpdateSelection();const capability=officekitDirectFilesState.archiveCapabilities[officekitDirectFilesState.archiveFormat];if(mode.value==='archive-extract'&&capability&&capability.extract!=='supported')officekitDirectStatus('Browsing is available for this format. Extraction is not currently supported.');};
    officekitLoadArchiveCapabilities(options);
  }
  if (action === 'rename') options.addEventListener('input', () => {
    if (!officekitDirectFilesState.preview) return;
    officekitDirectFilesState.preview = null;
    officekitDirectFilesState.report = null;
    document.getElementById('direct-file-results').replaceChildren();
    document.getElementById('direct-file-results').hidden = true;
    document.getElementById('direct-file-run').textContent = 'Preview rename';
    officekitDirectStatus('Rename options changed. Preview the new names before applying.');
  });
  document.getElementById('direct-file-run').textContent = action === 'rename' ? 'Preview rename' : action === 'duplicates' ? 'Find duplicates' : action === 'file_hash' ? 'Calculate checksum' : action === 'archive' ? 'Extract selected or all' : inspect ? inspect.run : title;
  document.getElementById('direct-file-results').hidden = true;
  officekitDirectStatus(''); officekitDirectUpdateSelection();
  if (typeof officekitStorageOpen === 'function') officekitStorageOpen(action);
  return true;
}

async function officekitAcceptDirectSelection(selection) {
  if (!selection || typeof selection.id !== 'string' || !window.officekitDirectFilesReady) return false;
  const selected = { ...selection, mode: 'files' };
  officekitDirectFilesState.selections = [selected];
  officekitDirectFilesState.preview = null;
  officekitDirectFilesState.report = null;
  officekitDirectFilesState.archiveOffset = 0;
  document.getElementById('direct-file-results').hidden = true;
  officekitDirectUpdateSelection();
  if (officekitDirectFilesState.action === 'archive' && document.getElementById('direct-archive-mode')?.value === 'archive-extract') await officekitLoadArchiveEntries(selection.id, 0);
  return true;
}

function officekitAcceptDirectPair(selections) {
  if (!Array.isArray(selections) || selections.length !== 2 || selections.some((selection) => !selection || typeof selection.id !== 'string') || !window.officekitDirectFilesReady) return false;
  officekitDirectFilesState.selections = selections.map((selection) => ({ ...selection, mode: 'files' }));
  officekitDirectFilesState.preview = null;
  officekitDirectFilesState.report = null;
  document.getElementById('direct-file-results').hidden = true;
  officekitDirectUpdateSelection();
  return true;
}
// Changing an option after a read-only result clears it, so Run comes back for the new options.
function officekitInvalidateDirectResult() {
  const state = officekitDirectFilesState;
  if (state.busy || !state.report || !officekitReadOnlyActions.has(state.action)) return;
  state.report = null;
  document.getElementById('direct-file-results').hidden = true;
  officekitDirectStatus('Options changed. Run again to update the result.');
  officekitDirectUpdateSelection();
}
function officekitDirectUpdateSelection() {
  const selected = officekitDirectFilesState.selections;
  // Approved v2 wording: "Choose …" until something is chosen, then "Change …" (UX-7).
  const pairChoice = officekitDirectFilesState.action === 'file_compare';
  document.getElementById('direct-choose-files').textContent = pairChoice ? (selected[0] ? 'Change file A…' : 'Choose file A…') : (selected[0] ? 'Change files…' : 'Choose files…');
  document.getElementById('direct-choose-folder').textContent = selected[0] ? 'Change folder…' : 'Choose folder…';
  // The approved phone frames drop the folder chooser below 900px on every Files tool (UX-15, UX-18), because every tool also offers "Choose files…".
  // The symlink inspector is folder-only, so it keeps the folder chooser in its approved 390px compact frame (F11 mock v4).
  document.getElementById('direct-choose-folder').classList.toggle('ok-phone-hide', !['symlink_inspector', 'similar_images'].includes(officekitDirectFilesState.action));
  document.getElementById('direct-folder-b').textContent = pairChoice ? (selected[1] ? 'Change file B…' : 'Choose file B…') : (selected[1] ? 'Change folder B…' : 'Choose folder B…');
  // The symlink inspector shows the folder name alone (approved mock v4, UX-5); other tools keep their labelled lines.
  document.getElementById('direct-selection-summary').textContent = officekitDirectFilesState.action === 'symlink_inspector' ? (selected.filter(Boolean).map(s => s.displayNames.join(', ')).join(' · ') || 'Choose a folder to begin.') : selected.filter(Boolean).map((s,i)=>`${officekitDirectFilesState.action === 'file_compare' ? (i === 0 ? 'File A' : 'File B') : officekitDirectFilesState.action === 'folder_compare' ? (i === 0 ? 'Folder A' : 'Folder B') : 'Selected'}: ${s.displayNames.join(', ')}`).join(' · ') || 'No files selected.';
  const similar = officekitDirectFilesState.action === 'similar_images';
  if (similar) officekitRenderImageSelection(selected[0]);
  // Nothing chosen: a dashed drop-style area with a hint and the choosers. Reset only matters once something is chosen.
  document.getElementById('direct-selection-line').dataset.empty = String(!selected[0]);
  document.getElementById('direct-selection-hint').hidden = Boolean(selected[0]);
  document.getElementById('direct-reset-selection').hidden = !selected[0];
  // After a read-only result the Run button is replaced by Copy report and Download; during a run Cancel joins the busy Run.
  const resultOnly = Boolean(officekitDirectFilesState.report) && officekitReadOnlyActions.has(officekitDirectFilesState.action);
  document.getElementById('direct-file-run').hidden = resultOnly && !officekitDirectFilesState.busy;
  document.getElementById('direct-file-cancel').hidden = !officekitDirectFilesState.busy;
  document.getElementById('direct-file-run').disabled = officekitDirectFilesState.busy || !selected[0] || (['folder_compare', 'file_compare'].includes(officekitDirectFilesState.action) && !selected[1]);
  const archiveCapability=officekitDirectFilesState.archiveCapabilities[officekitDirectFilesState.archiveFormat];
  if(officekitDirectFilesState.action==='archive'&&document.getElementById('direct-archive-mode')?.value==='archive-extract'&&archiveCapability&&archiveCapability.extract!=='supported')document.getElementById('direct-file-run').disabled=true;
  const scope = document.getElementById('direct-duplicate-mode');
  if (scope) scope.disabled = officekitDirectFilesState.busy;
  if (similar && selected[0]) {
    const summary = officekitDirectFilesState.imageSummary;
    if (!summary || summary.images === 0 || summary.images > summary.limit) document.getElementById('direct-file-run').disabled = true;
  } else if (!similar) document.getElementById('direct-image-list')?.setAttribute('hidden', '');
}
// Lists what was chosen and checks the image limit right away, instead of failing after Run.
function officekitRenderImageSelection(selection) {
  const summaryNode = document.getElementById('direct-selection-summary');
  const ready = document.getElementById('direct-image-ready');
  let list = document.getElementById('direct-image-list');
  if (!list) { list = officekitDirectNode('ul', '', 'ok-image-list'); list.id = 'direct-image-list'; document.getElementById('direct-selection-line').after(list); }
  list.replaceChildren();
  const summary = officekitDirectFilesState.imageSummary;
  list.hidden = !selection || !summary;
  if (!selection) { summaryNode.textContent = 'No folder selected.'; if (ready) ready.textContent = ''; return; }
  if (!summary) { summaryNode.textContent = 'Counting images…'; if (ready) ready.textContent = ''; return; }
  const number = value => value.toLocaleString('en-US');
  const folders = summary.folders.length;
  summaryNode.textContent = `${number(summary.images)} ${summary.images === 1 ? 'image' : 'images'} in ${folders} ${folders === 1 ? 'folder' : 'folders'}${summary.skipped ? ` · ${number(summary.skipped)} ${summary.skipped === 1 ? 'file' : 'files'} skipped (not images)` : ''}`;
  for (const folder of summary.folders) {
    const row = officekitDirectNode('li', '');
    row.append(officekitDirectNode('span', folder.name), officekitDirectNode('span', `${number(folder.images)} ${folder.images === 1 ? 'image' : 'images'}`, 'ok-muted'));
    list.append(row);
  }
  if (!ready) return;
  ready.dataset.state = summary.images === 0 ? 'empty' : summary.images > summary.limit ? 'over' : 'ready';
  ready.textContent = summary.images === 0 ? 'No supported images in this selection.'
    : summary.images > summary.limit ? `${number(summary.images - summary.limit)} over the ${number(summary.limit)} image limit. Choose a smaller folder.`
    : `Ready: ${number(summary.images)} of ${number(summary.limit)} images.`;
}
async function officekitLoadImageSummary(selectionId) {
  try {
    const summary = await (await officekitDirectFetch(`/api/file-selections/${selectionId}/image-summary`)).json();
    if (officekitDirectFilesState.selections[0]?.id !== selectionId) return;
    officekitDirectFilesState.imageSummary = summary;
  } catch (error) { officekitDirectStatus(error.message); }
  officekitDirectUpdateSelection();
}
async function officekitChooseDirectSelection(mode, index) {
  if (officekitDirectFilesState.busy) return;
  if (typeof window.__TAURI__?.core?.invoke !== 'function') { officekitDirectStatus('Direct file access requires the OfficeKit desktop app. No files have been copied.'); return; }
  try {
    const selection = await tauriInvoke()('file_selection_open', {mode,access:['rename','duplicates'].includes(officekitDirectFilesState.action)?'read-write':'read'});
    if (!selection) return;
    const previous = officekitDirectFilesState.selections[index];
    if (previous) await officekitDirectFetch(`/api/file-selections/${previous.id}`, {method:'DELETE'});
    officekitDirectFilesState.selections[index]={...selection, mode}; officekitDirectFilesState.imageSummary=null; officekitDirectFilesState.preview=null; officekitDirectFilesState.report=null; document.getElementById('direct-file-results').hidden=true; officekitDirectUpdateSelection();
    if (officekitDirectFilesState.action === 'similar_images') await officekitLoadImageSummary(selection.id);
    if (officekitDirectFilesState.action === 'archive' && index === 0 && mode === 'files') { officekitDirectFilesState.archiveOffset=0; await officekitLoadArchiveEntries(selection.id,0); }
    document.getElementById('direct-file-run').textContent=officekitDirectFilesState.action==='rename'?'Preview rename':officekitDirectFilesState.action==='duplicates'?'Find duplicates':officekitDirectFilesState.action==='file_hash'?'Calculate checksum':officekitDirectFilesState.action==='archive'?(document.getElementById('direct-archive-mode').value==='archive-create'?'Create ZIP':'Extract selected or all'):(officekitInspectTools[officekitDirectFilesState.action]?.run ?? document.getElementById('direct-file-title').textContent);
  } catch(error) { officekitDirectStatus(error.message || 'Selection could not be opened.'); }
}
async function officekitResetDirectSelection() {
  if (officekitDirectFilesState.busy) { officekitDirectStatus('Cancel or finish the current operation before resetting.'); return; }
  try { for (const selected of officekitDirectFilesState.selections.filter(Boolean)) await officekitDirectFetch(`/api/file-selections/${selected.id}`,{method:'DELETE'}); officekitDirectFilesState.selections=[]; officekitDirectFilesState.imageSummary=null; officekitDirectFilesState.preview=null; officekitDirectFilesState.report=null; document.getElementById('direct-file-results').hidden=true; officekitDirectUpdateSelection(); officekitDirectStatus('Selection reset. Original files and saved outputs remain in place.'); }
  catch(error) { officekitDirectStatus(error.message); }
}
async function officekitRunDirectFiles(trashOptions = null) {
  const state=officekitDirectFilesState;
  if (state.busy || !state.selections[0]) return;
  const value=id=>document.getElementById(id)?.value;
  let kind=officekitDirectKinds[state.action], options={};
  if(state.action==='file_hash') options.algorithm=value('direct-hash-algorithm');
  if(state.action==='duplicates') options={includeSubfolders:true, matchKind:value('direct-duplicate-mode')};
  if(state.action==='similar_images') options.threshold=Number(value('direct-similarity'));
  if(state.action==='rename') { if(state.preview){kind='rename-apply';options.previewId=state.preview;} else options={pattern_type:value('direct-rename-pattern'),prefix:value('direct-rename-prefix'),suffix:value('direct-rename-suffix'),find_text:value('direct-rename-find'),replace_text:value('direct-rename-replace')}; }
  if(state.action==='split_join'){kind=value('direct-parts-mode');if(kind==='split')options.chunkSize=Number(value('direct-part-size'))*1024*1024;}
  if(state.action==='archive'){kind=value('direct-archive-mode');if(kind==='archive-create')options={format:value('direct-archive-format')};else {const entryIds=[...document.querySelectorAll('.archive-entry-choice:checked')].map(input=>input.value);options=entryIds.length?{all:false,entryIds}:{all:true,entryIds:[]};}}
  if(officekitInspectTools[state.action]) { try { options = officekitInspectOptions(state.action); } catch (error) { officekitDirectStatus(error.message); return; } }
  if(trashOptions && state.action === 'duplicates') { kind = 'duplicate-trash'; options = trashOptions; }
  let grant=null;
  if(['split','join','archive-create','archive-extract'].includes(kind)){try{grant=await tauriInvoke()('file_output_choose',{kind:kind==='archive-extract'?'directory':'file',suggestedName:kind==='archive-extract'?'extracted-files':kind==='join'?'joined-file.bin':'output.zip',jobKind:kind,overwrite:false});if(!grant)return;}catch(error){officekitDirectStatus(error.message);return;}}
  state.busy=true;state.job=null; officekitDirectUpdateSelection(); document.getElementById('direct-file-cancel').hidden=['rename-apply','duplicate-trash'].includes(kind); document.getElementById('direct-file-results').hidden=true;
  try {
    const request={kind,selectionIds:(['compare-folders', 'compare-files'].includes(kind)?state.selections.slice(0,2):state.selections.slice(0,1)).map(s=>s.id),options}; if(grant)request.outputGrantId=grant.id;
    const created=await(await officekitDirectFetch('/api/file-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)})).json();state.job=created.id;
    const title=kind==='duplicates'?'Find duplicates':kind==='duplicate-trash'?'Move duplicates to Trash':state.action.replaceAll('_',' ');
    const activity=window.OfficeKitActivity?.start({id:`file-${created.id}`,title,tool:'File utilities',tab:'workspace',phase:'Queued',progress:0,total:null,unit:kind==='duplicates'?'files':'items',cancel:()=>officekitDirectFetch(`/api/file-jobs/${state.job}/cancellations`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),returnTo:()=>switchTab('workspace')});
    while (true) {
      const progress = await (await officekitDirectFetch(`/api/file-jobs/${state.job}`)).json();
      officekitDirectStatus(`${progress.state} · ${progress.progress} files processed`);
      const insights=progress.insights||{};
      const metrics=[];
      if(Number.isFinite(insights.duplicateGroups))metrics.push({label:'Duplicate groups',value:insights.duplicateGroups.toLocaleString()});
      if(Number.isFinite(insights.extraCopies))metrics.push({label:'Extra copies',value:insights.extraCopies.toLocaleString()});
      if(Number.isFinite(insights.potentialRecoveryBytes))metrics.push({label:insights.inspectionOnly?'Potential size':'Potential recovery',value:`${(insights.potentialRecoveryBytes/1024/1024).toFixed(1)} MB`,detail:insights.inspectionOnly?'folder matches are inspection only':'empty Trash to reclaim disk space'});
      if(Number.isFinite(insights.matchedFolderBytes))metrics.push({label:'Matched folder data',value:`${(insights.matchedFolderBytes/1024/1024).toFixed(1)} MB`,detail:'inspection only; no data is removed'});
      if(Number.isFinite(insights.copiesMovedToTrash))metrics.push({label:'Copies moved to Trash',value:insights.copiesMovedToTrash.toLocaleString()});
      if(Number.isFinite(insights.movedBytes))metrics.push({label:'Size moved to Trash',value:`${(insights.movedBytes/1024/1024).toFixed(1)} MB`,detail:'not reclaimed until Trash is emptied'});
      activity?.update({state:progress.state==='queued'?'queued':'running',phase:progress.phase||progress.state,progress:progress.progress,total:progress.total??null,percent:Number.isFinite(progress.total)&&progress.total>0?progress.progress/progress.total*100:null,insights:metrics});
      if (['ready', 'failed', 'cancelled'].includes(progress.state)) {
        if (progress.state === 'cancelled') { officekitDirectStatus('Operation cancelled.');activity?.finish({state:'cancelled',phase:'Cancelled',summary:'The operation was cancelled.'});break; }
        if (progress.state === 'failed' && !progress.resultRef) throw Error(progress.error || 'File operation failed.');
        const report = await (await officekitDirectFetch(`/api/file-jobs/${state.job}/results${kind === 'duplicates' ? '?format=json' : ''}`)).json();
        state.report = report;
        officekitRenderDirectReport(report, state.job);
        if (kind === 'rename-preview') { state.preview = report.previewId; document.getElementById('direct-file-run').textContent = 'Apply rename'; }
        else if (kind === 'rename-apply') { state.preview = null; document.getElementById('direct-file-run').textContent = 'Preview rename'; }
        if (progress.state === 'failed') officekitDirectStatus(progress.error || 'Partial operation—review the recovery report.');
        else if (kind === 'duplicate-trash') {
          state.selections = [];
          officekitDirectStatus(`${report.moved_count || 0} ${report.moved_count === 1 ? 'copy' : 'copies'} moved to Trash. ${report.complete === false ? 'Some files could not be moved. Review the result.' : 'Kept files remain in place.'} Choose files or a folder again for a fresh search.`);
        }
        else officekitDirectStatus(report.complete === false ? 'Completed with some unavailable items. Review the result.' : state.action === 'duplicates' || state.action === 'file_hash' ? '' : 'Result ready.');
        activity?.finish({state:progress.state==='failed'?'failed':'complete',phase:progress.state==='failed'?'Needs attention':'Complete',percent:100,summary:kind==='duplicate-trash'?`${report.moved_count||0} copies moved to Trash. Empty Trash to reclaim disk space.`:report.complete===false?'Completed with some unavailable items. Review the result.':'Result ready in File utilities.'});
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }catch(error){state.preview=null;officekitDirectStatus(error.message);if(state.job)window.OfficeKitActivity?.update(`file-${state.job}`,{state:'failed',phase:'Could not complete',summary:error.message});}finally{state.busy=false;document.getElementById('direct-file-cancel').hidden=true;officekitDirectUpdateSelection();}
}
async function officekitLoadArchiveCapabilities(container) {
  try {
    const response=await officekitDirectFetch('/api/archive-formats');
    const data=await response.json();
    officekitDirectFilesState.archiveCapabilities=Object.fromEntries(data.formats.map(format=>[format.id,format]));
    officekitDirectUpdateSelection();
    const details=document.createElement('details');details.className='mt-3 rounded-box border border-base-300 p-3';
    const summary=document.createElement('summary');summary.className='cursor-pointer font-semibold';summary.textContent=`Format support (${data.formats.length})`;details.append(summary);
    const wrap=officekitDirectNode('div','','mt-2 overflow-x-auto');
    // Reference table stays behind the disclosure: hidden until the summary opens it, so it never shows as an open list.
    wrap.hidden=true;details.addEventListener('toggle',()=>{wrap.hidden=!details.open;});
    const table=document.createElement('table');table.className='table table-xs';
    const head=document.createElement('thead'),row=document.createElement('tr');
    for(const label of ['Format','Browse','Extract','Create']){const cell=document.createElement('th');cell.textContent=label;row.append(cell);}head.append(row);table.append(head);
    const body=document.createElement('tbody');
    for(const format of data.formats){const row=document.createElement('tr');for(const label of [format.label,format.read,format.extract,format.create]){const cell=document.createElement('td');cell.textContent=label;row.append(cell);}body.append(row);}
    table.append(body);wrap.append(table);details.append(wrap);container.append(details);
  } catch (_) { /* The archive picker still works when capability discovery is unavailable. */ }
}
async function officekitLoadArchiveEntries(selectionId, offset=0) {
  officekitDirectFilesState.archiveOffset=offset;
  const container=document.getElementById('direct-file-results');
  container.replaceChildren();container.hidden=false;
  const heading=officekitDirectNode('h2','Archive contents','text-xl font-bold');container.append(heading);
  try {
    const response=await officekitDirectFetch(`/api/file-selections/${selectionId}/archive-entries?offset=${offset}&limit=100`);
    const listing=await response.json();
    officekitDirectFilesState.archiveFormat=listing.format;
    const capability=officekitDirectFilesState.archiveCapabilities[listing.format];
    if(capability?.read==='unsupported'){
      const notice=officekitDirectNode('div',`${listing.format.toUpperCase()} files aren’t supported yet. This archive manager can’t open or extract this format. Choose a supported archive such as ZIP, 7z, or TAR.`,'alert alert-warning mt-3');notice.setAttribute('role','alert');container.append(notice);
      officekitDirectUpdateSelection();
      return;
    }
    container.append(officekitDirectNode('p',`${Math.min(offset+1,listing.total).toLocaleString()}–${Math.min(offset+listing.entries.length,listing.total).toLocaleString()} of ${listing.total.toLocaleString()} entries · ${listing.format.toUpperCase()}`,'text-sm text-base-content/70'));
    if(capability&&capability.extract!=='supported'){const notice=officekitDirectNode('div',`Browsing ${listing.format.toUpperCase()} is available, but extraction is not currently supported for this format.`,'alert alert-warning mt-3');notice.setAttribute('role','status');container.append(notice);}
    const wrap=officekitDirectNode('div','','overflow-x-auto');
    const table=document.createElement('table');table.className='table table-sm';
    const head=document.createElement('thead'),headRow=document.createElement('tr');
    for(const label of ['Select','Name','Type','Size']){const cell=document.createElement('th');cell.textContent=label;headRow.append(cell);}head.append(headRow);table.append(head);
    const body=document.createElement('tbody');
    for(const entry of listing.entries){const row=document.createElement('tr');const selectCell=document.createElement('td');const check=document.createElement('input');check.type='checkbox';check.className='checkbox checkbox-sm archive-entry-choice';check.value=entry.id;check.disabled=!entry.extractable;check.setAttribute('aria-label',`Select ${entry.name}`);selectCell.append(check);row.append(selectCell);for(const value of [entry.name,entry.kind,entry.kind==='directory'?'—':`${entry.size_bytes.toLocaleString()} bytes`]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}body.append(row);}
    table.append(body);wrap.append(table);container.append(wrap);officekitDirectUpdateSelection();
    if(offset>0||listing.hasMore){const nav=officekitDirectNode('div','','mt-3 flex gap-2');if(offset>0){const previous=officekitAsTextLink(officekitDirectNode('button','Previous 100'));previous.type='button';previous.onclick=()=>officekitLoadArchiveEntries(selectionId,Math.max(0,offset-100));nav.append(previous);}if(listing.hasMore){const next=officekitAsTextLink(officekitDirectNode('button','Next 100'));next.type='button';next.onclick=()=>officekitLoadArchiveEntries(selectionId,offset+100);nav.append(next);}container.append(nav);}
  } catch(error) {
    const selection=officekitDirectFilesState.selections.find(item=>item?.id===selectionId);
    const name=selection?.displayNames?.[0]||'';
    const hint=Object.values(officekitDirectFilesState.archiveCapabilities).find(format=>format.extensions?.some(extension=>name.toLowerCase().endsWith(extension)));
    if(hint?.read==='unsupported'){
      officekitDirectFilesState.archiveFormat=hint.id;
      container.hidden=false;
      container.replaceChildren(officekitDirectNode('h2','Archive contents','text-xl font-bold'));
      const notice=officekitDirectNode('div',`${hint.id.toUpperCase()} files aren’t supported yet. This archive manager can’t open or extract this format. Choose a supported archive such as ZIP, 7z, or TAR.`,'alert alert-warning mt-3');notice.setAttribute('role','alert');container.append(notice);
      officekitDirectUpdateSelection();
      return;
    }
    container.hidden=true;
    officekitDirectStatus(error.message || 'The selected file could not be browsed as an archive.');
  }
}
function officekitRenderDirectReport(report,jobId){
  if(officekitInspectTools[officekitDirectFilesState.action]) return officekitRenderInspectReport(report,jobId);
  if(officekitDirectFilesState.action==='file_hash'&&Array.isArray(report.files)&&report.algorithm) return officekitRenderHashReport(report,jobId);
  const container=document.getElementById('direct-file-results');container.replaceChildren();container.hidden=false;
  container.append(officekitDirectNode('h2','Result','text-xl font-bold'));
  const summary = officekitDirectNode('p', report.complete === false ? 'Some items need attention. Review each row below.' : 'Operation complete.');
  summary.className = 'ok-file-summary'; container.append(summary);
  const rows = Object.entries(report).find(([key,value]) => Array.isArray(value) && key !== 'warnings')?.[1] || [];
  if (officekitDirectFilesState.action === 'file_type' && Array.isArray(report.files)) {
    officekitRenderFileTypeRecords(container, report.files);
  } else if (officekitDirectFilesState.action === 'duplicates' && Array.isArray(report.groups)) {
    officekitRenderDuplicateChoices(container, report, jobId);
  } else if (rows.length) {
    const tableWrap = officekitDirectNode('div', '', 'ok-file-report-scroll');
    const table = document.createElement('table'); table.className = 'table ok-file-report-table';
    const displayRows = officekitDirectFilesState.action === 'duplicates'
      ? rows.flatMap(group => (Array.isArray(group.files) ? group.files : []).map(file => ({ hash: group.hash, size_bytes: group.size_bytes, file })))
      : rows;
    const keys = [...new Set(displayRows.flatMap(row => Object.keys(row)))].slice(0,6);
    const head = document.createElement('tr'); for (const key of keys) { const th=document.createElement('th'); th.textContent=key.replaceAll('_',' '); head.append(th); }
    const thead=document.createElement('thead'); thead.append(head); table.append(thead);
    const body=document.createElement('tbody'); for (const row of displayRows.slice(0,200)) { const tr=document.createElement('tr'); for (const key of keys) { const td=document.createElement('td'); const value=row[key]; td.textContent=value == null ? '—' : typeof value==='object' ? JSON.stringify(value) : String(value); tr.append(td); } body.append(tr); } table.append(body); tableWrap.append(table); container.append(tableWrap);
  } else {
    const details=document.createElement('details'); const summary=officekitDirectNode('summary','Technical details'); const pre=officekitDirectNode('pre',JSON.stringify(report,null,2),'ok-file-report'); details.append(summary,pre); container.append(details);
  }
  if(report.hasMore)container.append(officekitDirectNode('p','Preview shows 200 rows. Copy and Download use the complete result.'));
  const complete=async()=>{const response=await officekitDirectFetch(`/api/file-jobs/${jobId}/results?format=json`);return response.blob();};
  officekitMountResultActions(container,{toolId:officekitDirectFilesState.action,copyLabel:'Copy report',copy:async()=>{const blob=await complete();if(blob.size>8*1024*1024)throw Error('Too large to copy—download the complete report.');return officekitCopyResultText(await blob.text());},download:async()=>officekitDownloadResultBlob(await complete(),'file-result.json')});
  const trash = container.querySelector('#duplicate-trash');
  if (trash) {
    // The duplicate dock is Copy report, Download and Move selected to Trash; Trash is the one primary (approved v3 re-mock).
    const dock = container.querySelector('.officekit-result-actions');
    dock.append(trash);
    const download = dock.querySelector('.officekit-result-download');
    if (download) download.className = 'btn btn-outline';
  }
}

function officekitRenderFileTypeRecords(container, files) {
  const list = officekitDirectNode('div', '', 'ok-file-type-records');
  files.slice(0, 200).forEach(file => {
    const card = officekitDirectNode('article', '', 'ok-file-type-record');
    const heading = officekitDirectNode('h3', file.name || 'Unnamed file', 'ok-file-type-name');
    const facts = officekitDirectNode('dl', '', 'ok-file-type-facts');
    const match = file.extension_matches === null ? 'Not compared' : file.extension_matches ? 'Yes' : 'No';
    const values = [
      ['Size', window.OfficeKitFormatters.fileSize(file.size_bytes)],
      ['Extension', file.extension || 'None'],
      ['Detected type', file.detected_type || 'Unknown'],
      ['MIME type', file.mime_type || 'Unknown'],
      ['Matches extension?', match],
    ];
    values.forEach(([label, value]) => {
      const item = officekitDirectNode('div', '', 'ok-file-type-fact');
      item.append(officekitDirectNode('dt', label), officekitDirectNode('dd', value, label === 'Matches extension?' && value === 'No' ? 'ok-file-type-mismatch' : ''));
      facts.append(item);
    });
    card.append(heading, facts); list.append(card);
  });
  container.append(list);
  container.append(officekitDirectNode('p', 'File contents are identified by signature. This does not scan for malware.', 'ok-file-type-note'));
}
// The Trash ledger disclosure (approved mock v5, 2026-10-23). Storage review draws it boxed with its title; the duplicate
// finder and the Restore screen draw the short line alone. “What is kept” opens in place.
const officekitTrashCopy = {
  disclosureTitle: 'You can put these back for 30 days',
  disclosureShort: 'OfficeKit keeps a private list of what it moves to Trash, so you can put items back for 30 days. The list stays on this Mac.',
  disclosureOpen: 'Open Restore from Trash to put items back or forget them.',
  disclosureKept: 'To let you put items back, OfficeKit keeps a private list of what it moves to Trash: each item’s name, original folder, size and when it was moved. The list stays on this Mac, is readable only by your account, and is never logged, exported or sent anywhere. Entries are removed after 30 days, or sooner when you choose Forget.',
};
function officekitTrashDisclosure(boxed) {
  const kept = officekitDirectNode('p', officekitTrashCopy.disclosureKept, 'ok-trash-kept');
  kept.hidden = true;
  const toggle = officekitTextLink('What is kept', '', () => { kept.hidden = !kept.hidden; toggle.setAttribute('aria-expanded', String(!kept.hidden)); });
  toggle.setAttribute('aria-expanded', 'false');
  const line = officekitDirectNode('p');
  line.append(officekitDirectNode('span', boxed ? `${officekitTrashCopy.disclosureShort} ${officekitTrashCopy.disclosureOpen}` : officekitTrashCopy.disclosureShort), toggle);
  const block = officekitDirectNode('div', '', boxed ? 'ok-trash-disclosure boxed' : 'ok-trash-disclosure');
  if (boxed) block.append(officekitDirectNode('b', officekitTrashCopy.disclosureTitle));
  block.append(line, kept);
  return block;
}
// S06 Restore from Trash (approved mock v5). The webview only reads the list (GET). Every change goes through native
// commands that hold the grants, so this screen never calls the mutating routes. Original folders are shown here and never logged.
const officekitTrashPageSize = 200;
const officekitTrashMaxRecords = 10000;
const officekitTrashStates = {
  restorable: ['Restorable', 'badge-success'],
  'name-taken': ['Name taken', 'badge-warning'],
  changed: ['Folder changed', 'badge-warning'],
  missing: ['Not in Trash', 'badge-error'],
};
const officekitTrashReasons = { 'name-taken': 'Name taken. Nothing was replaced.', changed: 'Folder changed. Nothing was replaced.', missing: 'Not in Trash.' };
const officekitTrashState = { records: [], selected: new Set(), busy: false, loading: false, loadError: null, message: '', result: null, screen: null, view: null };
function officekitTrashCount(count) { return `${count.toLocaleString()} ${count === 1 ? 'item' : 'items'}`; }
// moved_at arrives as epoch seconds (API-CONTRACT.md), not as an ISO string.
function officekitTrashWhen(seconds) { return Number.isFinite(seconds) ? new Date(seconds * 1000).toLocaleString() : 'Unavailable'; }
// The dock status line: plain text is a status; an error is an alert, so assistive tech announces it.
function officekitTrashStatusLine(node, text, alert) { node.textContent = text; node.setAttribute('role', alert ? 'alert' : 'status'); }
// Fixed copy only: the server detail is never shown. Native errors carry a status when the command refuses a grant.
function officekitTrashMessage(error, fallback) {
  if (error?.status === 403) return 'Choose the items again.';
  if (error?.status === 404) return 'That item is no longer in the list.';
  return fallback;
}
async function officekitTrashFetch(path) {
  const response = await fetch(officekitApiUrl(path));
  if (!response.ok) { const error = Error('The Trash list request failed.'); error.status = response.status; throw error; }
  return response;
}
function officekitTrashRoot() {
  if (!officekitTrashState.screen) {
    const screen = officekitDirectNode('section', '', 'ok-trash-restore');
    screen.id = 'trash-restore'; screen.hidden = true;
    document.getElementById('tab-workspace').append(screen);
    officekitTrashState.screen = screen;
  }
  return officekitTrashState.screen;
}
// Shows the Restore screen in place of the direct-file workspace, or hands the workspace back to the other tools.
function officekitTrashRestoreShow(on) {
  if (!on && !officekitTrashState.screen) return;
  officekitTrashRoot().hidden = !on;
  for (const id of ['direct-file-title', 'direct-file-description', 'direct-selections']) { const node = document.getElementById(id); if (node) node.hidden = on; }
  const storage = document.getElementById('storage-system'); if (on && storage) storage.hidden = true;
}
async function officekitTrashRestoreOpen() {
  officekitTrashRestoreShow(true);
  officekitTrashState.result = null;
  officekitTrashState.message = '';
  await officekitTrashLoad();
}
// Reads every page of GET /api/trash-records until hasMore is false, capped at the server's 10,000 entries.
async function officekitTrashLoad() {
  const state = officekitTrashState;
  state.loading = true; state.loadError = null; officekitTrashRender();
  const records = [];
  try {
    while (records.length < officekitTrashMaxRecords) {
      const body = await (await officekitTrashFetch(`/api/trash-records?offset=${records.length}&limit=${officekitTrashPageSize}`)).json();
      const batch = Array.isArray(body?.records) ? body.records : [];
      records.push(...batch);
      if (!body?.hasMore || !batch.length) break;
    }
    state.records = records;
    state.selected = new Set(records.filter(record => record.state === 'restorable').map(record => record.id));
  } catch (error) {
    state.records = []; state.selected = new Set();
    state.loadError = officekitTrashMessage(error, 'The Trash list could not be loaded. Try again.');
  } finally { state.loading = false; officekitTrashRender(); }
}
function officekitTrashItem(record) { return { id: record.id, name: record.name, folder: record.original_folder_display }; }
// Runs one native flow at a time.
async function officekitTrashRun(task, fallback) {
  const state = officekitTrashState;
  if (state.busy) return;
  state.busy = true; state.message = ''; officekitTrashSync();
  try { await task(); }
  catch (error) { state.message = officekitTrashMessage(error, fallback); }
  finally { state.busy = false; officekitTrashRender(); }
}
// Confirm (native dialog), then apply with the returned grant. A null grant means the user cancelled: nothing is applied.
async function officekitTrashApply(records, destination) {
  const invoke = tauriInvoke();
  // The destination is the planned target inside the folder the user chose; its parent is the folder shown to the user.
  const chosen = destination ? destination.path.slice(0, destination.path.lastIndexOf('/')) : null;
  const items = records.map(officekitTrashItem).map(item => (chosen ? { ...item, folder: chosen } : item));
  const grant = await invoke('trash_restore_confirm', { items, destinationGrantId: destination?.id ?? null });
  if (!grant) return;
  const outcome = await invoke('trash_restore_apply', { restoreGrantId: grant, recordIds: items.map(item => item.id) });
  if (!Array.isArray(outcome?.items)) throw Error('OfficeKit returned an unexpected restore result.');
  const byId = new Map(outcome.items.map(row => [row.id, row]));
  const rows = items.map(item => {
    const restored = byId.get(item.id)?.state === 'restored';
    const path = restored ? (byId.get(item.id)?.restored_to ?? null) : null;
    const folder = path ? path.slice(0, path.lastIndexOf('/')) : (chosen ?? item.folder);
    return { id: item.id, name: item.name, folder, path, restored, reason: restored ? '' : (officekitTrashReasons[byId.get(item.id)?.reason] ?? 'Not restored. Nothing was replaced.') };
  });
  officekitTrashState.result = { rows, restoredBytes: Number(outcome.restored_bytes) || 0 };
}
async function officekitTrashRestoreSelected() {
  const state = officekitTrashState;
  const items = state.records.filter(record => state.selected.has(record.id) && record.state === 'restorable');
  if (!items.length) return;
  await officekitTrashRun(() => officekitTrashApply(items, null), 'The items could not be restored. Try again.');
}
// Restore to… for one item that is name-taken or in a changed folder: the native folder chooser supplies the destination grant.
async function officekitTrashRestoreTo(record) {
  await officekitTrashRun(async () => {
    const output = await tauriInvoke()('file_output_choose', { kind: 'directory', suggestedName: record.name, jobKind: 'trash-restore', overwrite: false });
    if (!output) return;
    await officekitTrashApply([record], output);
  }, 'The items could not be restored. Try again.');
}
async function officekitTrashForget(record) {
  await officekitTrashRun(async () => {
    const removed = await tauriInvoke()('trash_record_forget', { recordId: record.id, name: record.name });
    if (removed !== true) return;
    officekitTrashState.selected.delete(record.id);
    await officekitTrashLoad();
  }, 'The item could not be removed from this list. Try again.');
}
async function officekitTrashReveal(path) {
  await officekitTrashRun(() => tauriInvoke()('trash_restore_reveal', { path }), 'The item could not be shown in Finder. Try again.');
}
function officekitTrashDone() {
  officekitTrashState.result = null;
  officekitTrashState.message = '';
  return officekitTrashLoad();
}
// Updates the summary, the dock status and the Restore selected button in place, so focus stays on a checkbox.
function officekitTrashSync() {
  const state = officekitTrashState, view = state.view;
  if (!view) return;
  const chosen = state.records.filter(record => state.selected.has(record.id));
  view.summary.textContent = `${officekitTrashCount(state.records.length)} moved by OfficeKit in the last 30 days · ${chosen.length} selected`;
  // An error from the last action replaces the selection line in the dock, so the list above does not move.
  const text = state.busy ? 'Restoring…' : (state.message || `${chosen.length} selected · ${officekitInspectBytes(chosen.reduce((sum, record) => sum + record.size_bytes, 0))}`);
  officekitTrashStatusLine(view.status, text, !state.busy && Boolean(state.message));
  view.action.disabled = state.busy || chosen.length === 0;
}
function officekitTrashRow(record) {
  const state = officekitTrashState;
  const [label, tone] = officekitTrashStates[record.state] ?? officekitTrashStates.missing;
  const tr = document.createElement('tr');
  const selectCell = officekitDirectNode('td', '', 'sel');
  if (record.state !== 'missing') {
    const box = document.createElement('input');
    box.type = 'checkbox'; box.className = 'checkbox checkbox-sm';
    box.checked = state.selected.has(record.id); box.disabled = record.state !== 'restorable';
    box.setAttribute('aria-label', `Select ${record.name}`);
    if (box.disabled) box.title = 'Use Restore to… for this item';
    box.onchange = () => { if (state.busy) { box.checked = state.selected.has(record.id); return; } if (box.checked) state.selected.add(record.id); else state.selected.delete(record.id); officekitTrashSync(); };
    selectCell.append(box);
  }
  const item = officekitDirectNode('td', '', 'item');
  item.append(officekitDirectNode('span', record.name), officekitDirectNode('small', `${record.original_folder_display} · ${officekitTrashWhen(record.moved_at)} · ${officekitInspectBytes(record.size_bytes)}`, 'ok-phone-show'));
  const stateCell = officekitDirectNode('td', '', 'state');
  stateCell.append(officekitDirectNode('span', label, `badge badge-sm badge-outline ${tone}`));
  const acts = officekitDirectNode('td', '', 'acts');
  if (record.state === 'name-taken' || record.state === 'changed') acts.append(officekitTextLink('Restore to…', '', () => officekitTrashRestoreTo(record)));
  acts.append(officekitTextLink('Forget', '', () => officekitTrashForget(record)));
  tr.append(selectCell, item, officekitDirectNode('td', record.original_folder_display, 'mono ok-phone-hide'), officekitDirectNode('td', officekitTrashWhen(record.moved_at), 'ok-phone-hide'), officekitDirectNode('td', officekitInspectBytes(record.size_bytes), 'ok-phone-hide'), stateCell, acts);
  return tr;
}
function officekitTrashListView(panel, status, action) {
  const state = officekitTrashState;
  if (!state.records.length) {
    panel.append(officekitDirectNode('p', 'Nothing to restore.', 'ok-file-summary'), officekitDirectNode('p', 'Items OfficeKit moves to Trash from Duplicate finder or Storage cleanup appear here for 30 days.', 'text-sm text-base-content/70'), officekitTrashDisclosure(false));
    officekitTrashStatusLine(status, state.message || 'No items', Boolean(state.message)); action.disabled = true;
    return;
  }
  const summary = officekitDirectNode('p', '', 'ok-file-summary');
  const wrap = officekitDirectNode('div', '', 'ok-file-report-scroll');
  const table = document.createElement('table'); table.className = 'table ok-file-report-table ok-trash-table';
  const head = document.createElement('tr');
  for (const [label, className] of [['', 'sel'], ['Item', ''], ['Original folder', 'ok-phone-hide'], ['Moved', 'ok-phone-hide'], ['Size', 'ok-phone-hide'], ['State', ''], ['', 'acts']]) head.append(officekitDirectNode('th', label, className));
  const thead = officekitDirectNode('thead'); thead.append(head);
  const body = officekitDirectNode('tbody');
  for (const record of state.records) body.append(officekitTrashRow(record));
  table.append(thead, body); wrap.append(table);
  panel.append(summary, wrap, officekitTrashDisclosure(false));
  state.view = { summary, status, action };
  officekitTrashSync();
}
function officekitTrashResultView(panel, status, action) {
  const state = officekitTrashState, result = state.result;
  const restored = result.rows.filter(row => row.restored);
  panel.append(officekitDirectNode('h2', 'Result', 'text-xl font-bold'));
  panel.append(officekitDirectNode('p', `${restored.length.toLocaleString()} restored to their original folders · ${officekitInspectBytes(result.restoredBytes)}`, 'ok-file-summary'));
  const wrap = officekitDirectNode('div', '', 'ok-file-report-scroll');
  const table = document.createElement('table'); table.className = 'table ok-file-report-table ok-trash-table';
  const head = document.createElement('tr');
  table.classList.add('ok-trash-result');
  for (const [label, className] of [['Item', ''], ['Restored to', 'ph ok-phone-hide'], ['Result', 'acts']]) head.append(officekitDirectNode('th', label, className));
  const thead = officekitDirectNode('thead'); thead.append(head);
  const body = officekitDirectNode('tbody');
  for (const row of result.rows) {
    const item = officekitDirectNode('td', '', 'item');
    item.append(officekitDirectNode('span', row.name), officekitDirectNode('small', row.folder, 'ok-phone-show'));
    const outcome = officekitDirectNode('td', '', 'acts');
    if (row.restored) {
      outcome.append(officekitDirectNode('span', 'Restored', 'badge badge-sm badge-success badge-outline'));
      if (row.path) outcome.append(officekitTextLink('Show in Finder', '', () => officekitTrashReveal(row.path)));
    } else outcome.append(officekitDirectNode('span', 'Skipped', 'badge badge-sm badge-warning badge-outline'), officekitDirectNode('small', row.reason, 'ok-trash-reason'));
    const tr = document.createElement('tr');
    tr.append(item, officekitDirectNode('td', row.folder, 'mono ok-phone-hide'), outcome);
    body.append(tr);
  }
  table.append(thead, body); wrap.append(table);
  panel.append(wrap);
  // Shown only when a row was skipped: skipped items stay in the list, so Restore to… is there after Done.
  if (result.rows.length > restored.length) panel.append(officekitDirectNode('p', 'Skipped items stay in the list, where you can use Restore to…', 'text-sm text-base-content/70'));
  officekitTrashStatusLine(status, `Done · ${restored.length.toLocaleString()} restored`, false);
  action.textContent = 'Done'; action.disabled = state.busy; action.onclick = officekitTrashDone;
}
function officekitTrashRender() {
  const state = officekitTrashState, screen = officekitTrashRoot();
  state.view = null;
  const heading = officekitDirectNode('h1', 'Restore from Trash'); heading.id = 'trash-restore-title';
  const description = officekitDirectNode('p', 'Put back files and folders that OfficeKit moved to Trash.', 'desc');
  const panel = officekitDirectNode('section', '', 'ok-file-panel');
  const status = officekitDirectNode('span', '', 'status');
  const action = officekitDirectNode('button', 'Restore selected', 'btn-primary'); action.id = 'trash-restore-selected'; action.type = 'button'; action.onclick = officekitTrashRestoreSelected;
  const dock = officekitDirectNode('div', '', 'ok-trash-dock');
  dock.append(status, action);
  if (state.result) officekitTrashResultView(panel, status, action);
  else if (state.loading) { panel.append(officekitDirectNode('p', 'Loading…', 'ok-file-summary')); status.textContent = 'Loading…'; action.disabled = true; }
  else if (state.loadError) { officekitTrashStatusLine(status, state.loadError, true); action.disabled = true; }
  else officekitTrashListView(panel, status, action);
  screen.replaceChildren(heading, description, panel, dock);
}

// Builds the request options for a read-only scan. Date bounds are whole local days: From 00:00:00, To 23:59:59.
function officekitInspectOptions(action) {
  const inspect = officekitInspectTools[action];
  const subfolders = document.getElementById('direct-include-subfolders')?.checked === true;
  if (action !== 'file_age_finder') return inspect.subfolders === undefined ? {} : { includeSubfolders: subfolders };
  const bound = (id, endOfDay) => {
    const value = document.getElementById(id).value;
    if (!value) return null;
    const [year, month, day] = value.split('-').map(Number);
    return Math.floor(new Date(year, month - 1, day, ...(endOfDay ? [23, 59, 59] : [0, 0, 0])).getTime() / 1000);
  };
  const notBefore = bound('direct-age-from', false), notAfter = bound('direct-age-to', true);
  if (notBefore === null && notAfter === null) throw Error('Enter a From date, a To date, or both.');
  if (notBefore !== null && notAfter !== null && notBefore > notAfter) throw Error('The From date must be on or before the To date.');
  return { dateField: document.getElementById('direct-age-field').value, notBefore, notAfter, includeSubfolders: subfolders };
}
const officekitInspectStateLabels = { empty: 'Empty', 'hidden-files-only': 'Only hidden files' };
const officekitInspectReasonLabels = { link: 'Symbolic link, not followed', special: 'Special file', denied: 'Permission denied' };
function officekitInspectBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes.toLocaleString()} bytes`;
  let value = bytes / 1024, unit = 0;
  while (value >= 1024 && unit < 3) { value /= 1024; unit += 1; }
  return `${value.toFixed(1)} ${['KB', 'MB', 'GB', 'TB'][unit]}`;
}
function officekitInspectWhen(iso) { const time = Date.parse(iso); return Number.isFinite(time) ? new Date(time).toLocaleString() : 'Unavailable'; }
function officekitInspectReveal(jobId, itemId) {
  // A list-row action: standard button size (40px, 44px at 900px and below), not counted toward the screen limit.
  const reveal = officekitDirectNode('button', 'Show', 'row-act');
  reveal.type = 'button'; reveal.dataset.actionIcon = 'folder-open';
  reveal.disabled = typeof window.__TAURI__?.core?.invoke !== 'function';
  reveal.onclick = async () => {
    reveal.disabled = true;
    try { await tauriInvoke()('file_job_reveal', { jobId, itemId }); officekitDirectStatus('Revealed in Finder.'); }
    catch (error) { officekitDirectStatus(error.message || 'This scanned item could not be revealed. Run a fresh scan.'); }
    finally { reveal.disabled = false; }
  };
  return reveal;
}
function officekitInspectRows(headers, rows, emptyText, notes) {
  if (rows.length > 200) notes.push('Preview shows 200 rows. Copy and Download use the complete result.');
  if (!rows.length) return officekitDirectNode('p', emptyText);
  const wrap = officekitDirectNode('div', '', 'ok-file-report-scroll overflow-x-auto');
  const table = document.createElement('table'); table.className = 'table table-sm ok-file-report-table';
  const head = document.createElement('tr');
  for (const label of headers) head.append(officekitDirectNode('th', label));
  const thead = document.createElement('thead'); thead.append(head);
  const body = document.createElement('tbody');
  for (const cells of rows.slice(0, 200)) {
    const tr = document.createElement('tr');
    for (const cell of cells) { const td = document.createElement('td'); if (cell !== null && typeof cell === 'object') td.append(cell); else td.textContent = cell ?? '—'; tr.append(td); }
    body.append(tr);
  }
  table.append(thead, body); wrap.append(table);
  return wrap;
}
function officekitInspectLinkNotes(report) {
  const notes = [];
  if (report.skipped_links) notes.push(`${report.skipped_links.toLocaleString()} symbolic ${report.skipped_links === 1 ? 'link was' : 'links were'} not followed.`);
  if (report.denied_folders) notes.push(`${report.denied_folders.toLocaleString()} ${report.denied_folders === 1 ? 'folder' : 'folders'} could not be opened (permission denied).`);
  return notes;
}
// F11 symlink inspector (approved frame, 2026-10-23). Links are shown as written; nothing is followed or opened.
const officekitLinkStateTags = {
  inside: ['Resolves inside folder', 'badge-success badge-outline'],
  broken: ['Broken', 'badge-error badge-outline'],
  circular: ['Circular', 'badge-error badge-outline'],
  'too-many-hops': ['Too many hops', 'badge-error badge-outline'],
  'out-of-scope': ['Outside selected folder · not checked', 'badge-warning badge-outline'],
  denied: ['Not checked · permission denied', 'badge-warning badge-outline'],
  unsupported: ['Not supported on this system', 'badge-ghost'],
};
const officekitLinkNote = 'Links are never followed outside the selection. Targets outside it are shown as written, never opened or checked.';
function officekitLinkStateTag(link) {
  const [label, tone] = officekitLinkStateTags[link.state];
  const text = link.state === 'circular' ? `${label} (${link.hops} ${link.hops === 1 ? 'hop' : 'hops'})` : label;
  return officekitDirectNode('span', text, `badge badge-sm ${tone}`);
}
function officekitSymlinkSummary(report) {
  if (!report.total_links) return `No links found${report.complete ? '' : ' so far'} in ${report.scanned_items.toLocaleString()} items.`;
  const count = `${report.total_links.toLocaleString()} ${report.total_links === 1 ? 'link' : 'links'}`;
  if (!report.complete) return `${count} found so far`;
  return `${count} · ${report.resolves_inside.toLocaleString()} resolves inside the folder, ${report.broken_or_circular.toLocaleString()} broken or circular, ${report.outside_selection.toLocaleString()} point outside`;
}
function officekitSymlinkBanner(report) {
  const unread = [];
  if (report.denied_folders) unread.push(`${report.denied_folders.toLocaleString()} ${report.denied_folders === 1 ? 'folder' : 'folders'}`);
  if (report.not_checked) unread.push(`${report.not_checked.toLocaleString()} link ${report.not_checked === 1 ? 'target' : 'targets'}`);
  const parts = [];
  if (unread.length) parts.push(`${unread.join(' and ')} could not be read (permission denied)`);
  if (report.entry_limit_reached) parts.push(`the scan stopped at ${report.entry_limit.toLocaleString()} entries`);
  return parts.length ? `Partial result: ${parts.join(' and ')}.` : null;
}
function officekitSymlinkTable(report) {
  const wrap = officekitDirectNode('div', '', 'ok-file-report-scroll overflow-x-auto');
  const table = document.createElement('table'); table.className = 'table table-sm ok-file-report-table';
  const head = document.createElement('tr');
  ['Link', 'Points to (as written)', 'Type', 'State'].forEach((label, index) => head.append(officekitDirectNode('th', label, index === 2 ? 'ok-phone-hide' : '')));
  const thead = document.createElement('thead'); thead.append(head);
  const body = document.createElement('tbody');
  for (const link of report.links.slice(0, 200)) {
    const name = officekitDirectNode('td');
    name.append(officekitDirectNode('span', link.name), officekitDirectNode('span', link.relative_path, 'block text-xs opacity-70 ok-phone-hide'));
    const kind = link.type === 'absolute' ? 'Absolute' : link.type === 'relative' ? 'Relative' : '—';
    const state = officekitDirectNode('td'); state.append(officekitLinkStateTag(link));
    const tr = document.createElement('tr');
    tr.append(name, officekitDirectNode('td', link.points_to ?? '—', 'font-mono break-all'), officekitDirectNode('td', kind, 'ok-phone-hide'), state);
    body.append(tr);
  }
  table.append(thead, body); wrap.append(table);
  return wrap;
}
function officekitRenderSymlinkReport(report, jobId) {
  const container = document.getElementById('direct-file-results');
  container.replaceChildren(); container.hidden = false;
  container.append(officekitDirectNode('h2', 'Result', 'text-xl font-bold'));
  container.append(officekitDirectNode('p', officekitSymlinkSummary(report), 'ok-file-summary'));
  const banner = officekitSymlinkBanner(report);
  if (banner) { const alert = officekitDirectNode('div', banner, 'alert alert-warning mt-3'); alert.setAttribute('role', 'status'); container.append(alert); }
  if (report.total_links) {
    container.append(officekitSymlinkTable(report));
    if (report.hasMore) container.append(officekitDirectNode('p', 'Preview shows 200 rows. Copy and Download use the complete result.'));
    if (report.complete) container.append(officekitDirectNode('p', officekitLinkNote));
  }
  officekitMountInspectActions(container, jobId);
}
function officekitMountInspectActions(container, jobId) {
  const reportBlob = async () => (await officekitDirectFetch(`/api/file-jobs/${jobId}/results?format=json`)).blob();
  officekitMountResultActions(container, {toolId:officekitDirectFilesState.action,copyLabel:'Copy report',copy:async()=>{const blob=await reportBlob();if(blob.size>8*1024*1024)throw Error('Too large to copy—download the complete report.');return officekitCopyResultText(await blob.text());},download:async()=>officekitDownloadResultBlob(await reportBlob(),'file-result.json')});
}
// Checksum result (approved mock 2026-10-25): one titled card, File / Size / Checksum, and a copy icon beside each digest.
function officekitRenderHashReport(report, jobId) {
  const container = document.getElementById('direct-file-results');
  container.replaceChildren(); container.hidden = false;
  const algorithm = report.algorithm === 'sha512' ? 'SHA-512' : 'SHA-256';
  const count = report.files.length;
  container.append(officekitDirectNode('h2', `${algorithm} · ${count.toLocaleString()} ${count === 1 ? 'file' : 'files'} · ${officekitInspectBytes(report.total_bytes)}`, 'text-xl font-bold'));
  const rows = report.files.map(file => {
    const digest = officekitDirectNode('code', file.digest, 'ok-hash-digest');
    const copy = officekitDirectNode('button', '', 'row-act ok-hash-copy');
    copy.type = 'button'; copy.dataset.actionIcon = 'copy';
    copy.setAttribute('aria-label', `Copy ${file.name} checksum to clipboard`); copy.title = 'Copy checksum';
    copy.onclick = async () => {
      try { await officekitCopyResultText(file.digest); officekitDirectStatus('Checksum copied to clipboard.'); }
      catch (_) { officekitDirectStatus('Could not access the clipboard.'); }
    };
    const cell = officekitDirectNode('div', '', 'ok-hash-cell'); cell.append(digest, copy);
    return [file.name, officekitInspectBytes(file.size_bytes), cell];
  });
  container.append(officekitInspectRows(['File', 'Size', 'Checksum'], rows, 'No files found.', []));
  const complete = async () => (await officekitDirectFetch(`/api/file-jobs/${jobId}/results?format=json`)).blob();
  officekitMountResultActions(container, {toolId:officekitDirectFilesState.action,copyLabel:'Copy report',copy:async()=>{const blob=await complete();if(blob.size>8*1024*1024)throw Error('Too large to copy—download the complete report.');return officekitCopyResultText(await blob.text());},download:async()=>officekitDownloadResultBlob(await complete(),'file-result.json')});
}
function officekitRenderInspectReport(report, jobId) {
  const action = officekitDirectFilesState.action;
  if (action === 'symlink_inspector') return officekitRenderSymlinkReport(report, jobId);
  const container = document.getElementById('direct-file-results');
  container.replaceChildren(); container.hidden = false;
  container.append(officekitDirectNode('h2', 'Result', 'text-xl font-bold'));
  const notes = [], blocks = [];
  let summary = 'Result ready.';
  if (action === 'file_info') {
    summary = `${report.total_files.toLocaleString()} ${report.total_files === 1 ? 'file' : 'files'} · ${officekitInspectBytes(report.total_bytes)}`;
    const rows = report.files.map(file => [file.name, officekitInspectBytes(file.size_bytes), officekitInspectWhen(file.modified_at), officekitInspectWhen(file.created_at), file.mode, [file.hidden ? 'Hidden' : '', file.hard_links > 1 ? `${file.hard_links} hard links` : ''].filter(Boolean).join(' · ') || '—']);
    for (const skipped of report.skipped) rows.push([skipped.name, '—', '—', '—', '—', officekitInspectReasonLabels[skipped.reason] ?? skipped.reason]);
    notes.push(...officekitInspectLinkNotes(report), ...report.platform_limits);
    if (report.skipped_truncated) notes.push(`${report.skipped_truncated.toLocaleString()} more skipped ${report.skipped_truncated === 1 ? 'item is' : 'items are'} not listed. The counts above are complete.`);
    blocks.push(officekitDirectNode('p', 'Dates use this Mac’s time zone.', 'text-sm text-base-content/70'));
    blocks.push(officekitInspectRows(['Name', 'Size', 'Modified', 'Created', 'Permissions', 'Notes'], rows, 'No files found.', notes));
  } else if (action === 'file_compare') {
    summary = report.same_file ? 'Same file selected twice.' : report.equal ? 'Files are identical.' : `Files differ · first difference at byte ${report.first_difference_offset.toLocaleString()}`;
    if (report.mode === 'text') blocks.push(officekitDirectNode('p', 'Text view, 2 files, both under 2 MiB.', 'text-sm text-base-content/70'));
    if (report.mode === 'text-too-large') notes.push('Text view is limited to 2 MiB per file. The byte comparison above is complete.');
    if (report.truncated) notes.push('Some differences are not shown. Copy or Download include the complete comparison.');
    blocks.push(officekitInspectRows(['', 'File A', 'File B'], [
      ['Size', officekitInspectBytes(report.size_a), officekitInspectBytes(report.size_b)],
      ['SHA-256', ...(report.sha256_a === report.sha256_b ? ['Match', 'Match'] : ['Differ', 'Differ'])],
      ['Text encoding', report.encoding_a, report.encoding_b],
      ['Line endings', report.line_endings_a, report.line_endings_b],
    ], '', notes));
    if (report.mode === 'binary' && report.bytes_a !== null) {
      const spaced = hex => (hex ? hex.match(/../g).join(' ') : '—');
      notes.push('Binary files are compared byte by byte. The bytes below start at the first difference.');
      blocks.push(officekitInspectRows(['', 'File A', 'File B'], [['Bytes', spaced(report.bytes_a), spaced(report.bytes_b)]], '', notes));
    }
    if (report.mode === 'text' && report.hunks.length) {
      const diff = officekitDirectNode('div', '', 'mt-4 overflow-x-auto font-mono text-xs');
      diff.setAttribute('role', 'region'); diff.setAttribute('aria-label', 'Differences');
      for (const hunk of report.hunks) {
        for (const line of hunk.lines) {
          const row = officekitDirectNode('div', `${line.op} ${line.text}`);
          row.style.whiteSpace = 'pre';
          if (line.op === '+') row.classList.add('ok-diff-line-add');
          if (line.op === '-') row.classList.add('ok-diff-line-remove');
          diff.append(row);
        }
      }
      blocks.push(diff);
    }
  } else if (action === 'file_age_finder') {
    summary = `${report.matched.toLocaleString()} of ${report.scanned.toLocaleString()} files match · ${officekitInspectBytes(report.matched_bytes)}`;
    if (report.unavailable_dates) notes.push(`${report.unavailable_dates.toLocaleString()} ${report.unavailable_dates === 1 ? 'file has' : 'files have'} no ${report.date_field} date, so ${report.unavailable_dates === 1 ? 'it is' : 'they are'} not matched.`);
    notes.push(...officekitInspectLinkNotes(report));
    blocks.push(officekitInspectRows(['Name', 'Size', 'Modified', 'Created', ''], report.files.map(file => [file.name, officekitInspectBytes(file.size_bytes), officekitInspectWhen(file.modified_at), officekitInspectWhen(file.created_at), officekitInspectReveal(jobId, file.id)]), 'No files match this range.', notes));
  } else if (action === 'empty_file_finder') {
    const emptyCount = report.files.length.toLocaleString();
    summary = `${emptyCount} empty file${report.files.length === 1 ? '' : 's'} among ${report.scanned.toLocaleString()} scanned`;
    notes.push('Whitespace-only files are not empty, so they are not listed.', ...officekitInspectLinkNotes(report));
    blocks.push(officekitInspectRows(['Name', 'Modified', ''], report.files.map(file => [file.name, officekitInspectWhen(file.modified_at), officekitInspectReveal(jobId, file.id)]), 'No empty files found.', notes));
  } else {
    const empty = report.folders.filter(folder => folder.state === 'empty').length;
    const hidden = report.folders.filter(folder => folder.state === 'hidden-files-only').length;
    summary = `${empty.toLocaleString()} empty ${empty === 1 ? 'folder' : 'folders'} · ${hidden.toLocaleString()} ${hidden === 1 ? 'folder' : 'folders'} with only hidden files`;
    const unchecked = [[report.skipped_other_volume, 'other drive'], [report.skipped_bundles, 'app bundles'], [report.denied_folders, 'permission denied'], [report.skipped_links, 'symbolic links'], [report.excluded_protected, 'protected folders']]
      .filter(([count]) => count).map(([count, label]) => `${label} (${count.toLocaleString()})`);
    if (unchecked.length) notes.push(`Not checked: ${unchecked.join(' · ')}.`);
    blocks.push(officekitInspectRows(['Folder', 'State', ''], report.folders.map(folder => [folder.name, officekitInspectStateLabels[folder.state] ?? folder.state, officekitInspectReveal(jobId, folder.id)]), 'No empty folders found.', notes));
  }
  container.append(officekitDirectNode('p', summary, 'ok-file-summary'));
  for (const note of notes) { const alert = officekitDirectNode('div', note, 'alert alert-warning mt-3'); alert.setAttribute('role', 'status'); container.append(alert); }
  container.append(...blocks);
  officekitMountInspectActions(container, jobId);
}

function officekitRenderDuplicateChoices(container, report, jobId) {
  const groups = report.groups;
  const folders = report.match_kind === 'folders';
  const heading = container.querySelector('h2'); heading.textContent = `${groups.length} ${folders ? 'identical folder' : 'duplicate'} ${groups.length === 1 ? 'group' : 'groups'}`;
  container.querySelector('.ok-file-summary')?.remove();
  const headingRow = officekitDirectNode('div', '', 'ok-duplicate-heading');
  const badge = officekitDirectNode('span', report.complete === false ? 'Partial scan' : 'Complete', 'badge badge-outline');
  const details = officekitDirectNode('details'); details.id = 'duplicate-report-details';
  const disclosure = officekitDirectNode('summary', 'Scan details', 'ok-text-link');
  const detailBody = officekitDirectNode('div', '', 'ok-duplicate-detail-body');
  detailBody.append(officekitDirectNode('p', folders ? 'Folder matches are for inspection. Relative names, empty directories and file contents must match; the top-level folder name may differ.' : 'Files marked Keep stay in place. Select all duplicates covers every page; sorting and paging preserve your selection.'));
  detailBody.append(officekitDirectNode('p', 'Includes subfolders. Hover a name or location for its full path. Show in Finder reveals the exact item.'));
  if (Number.isInteger(report.files_scanned)) detailBody.append(officekitDirectNode('p', `${report.files_scanned.toLocaleString()} files scanned.`));
  if (report.skipped_entries || report.skipped_links) detailBody.append(officekitDirectNode('p', `${Number(report.skipped_entries || report.skipped_links).toLocaleString()} linked or special entries skipped. Their containing folders are excluded from exact folder matches.`));
  details.append(disclosure, detailBody); headingRow.append(heading, badge, details); container.append(headingRow);
  const groupedEntries = groups.map((group, index) => (group.entries || []).map((file, position) => ({...file, group: index + 1, size: group.size_bytes, keep: position === 0})));
  const entries = groupedEntries.flat();
  if (!entries.length) { container.append(officekitDirectNode('p', folders ? 'No identical folders found.' : 'No identical files found.')); return; }
  const wrapper = officekitDirectNode('div', '', 'overflow-x-auto ok-file-report-scroll ok-duplicate-list');
  wrapper.tabIndex = 0; wrapper.setAttribute('role', 'region'); wrapper.setAttribute('aria-label', folders ? 'Identical folders' : 'Duplicate files');
  const table = document.createElement('table'); table.className = 'table table-pin-rows ok-file-report-table ok-duplicate-table';
  const head = document.createElement('thead'), row = document.createElement('tr');
  let sortKey = 'name', descending = false;
  const headers = [];
  for (const [key, title] of [['name', 'Name'], ['date', 'Date modified'], ['size', 'Size']]) {
    const th = officekitDirectNode('th'), button = officekitAsTextLink(officekitDirectNode('button', title));
    button.setAttribute('aria-label', `Sort by ${title}`);
    button.dataset.sort = key; th.append(button); row.append(th); headers.push({th, button, key, title});
    if (key === 'date') th.classList.add('ok-phone-hide');
    button.onclick = () => { descending = sortKey === key ? !descending : false; sortKey = key; page = 0; renderPage(); };
  }
  row.append(officekitDirectNode('th', ''));
  head.append(row); const body = document.createElement('tbody'); table.append(head, body); wrapper.append(table);
  const selected = new Set(), checkboxes = new Map(); let page = 0;
  if (entries.filter(file => !file.keep).length > 10000) container.append(officekitDirectNode('p', 'Select all duplicates chooses up to 10,000 copies per batch. Rescan after moving a batch.'));
  const controls = officekitDirectNode('div', '', 'flex flex-wrap items-center justify-between gap-3 mt-4');
  const selectionButtons = officekitDirectNode('div', '', 'flex flex-wrap gap-2');
  const select = officekitAsTextLink(officekitDirectNode('button', 'Select all duplicates')), clear = officekitAsTextLink(officekitDirectNode('button', 'Clear selection'));
  const status = officekitDirectNode('p', 'No copies selected'); status.id = 'duplicate-selection-status'; status.setAttribute('role', 'status');
  selectionButtons.append(select, clear); controls.append(selectionButtons, status); if (!folders) container.append(controls);
  const trash = officekitDirectNode('button', 'Move selected to Trash'); trash.className = 'btn btn-primary'; trash.id = 'duplicate-trash'; trash.disabled = true;
  const writable = report.trash_supported === true && officekitDirectFilesState.selections[0]?.access === 'read-write';
  const update = () => { for (const [id, input] of checkboxes) input.checked = selected.has(id); trash.disabled = !writable || !selected.size || officekitDirectFilesState.busy; officekitOutcome.show(status, { state: 'info', text: selected.size ? `${selected.size.toLocaleString()} ${selected.size === 1 ? 'copy' : 'copies'} selected` : 'No copies selected' }); };
  select.onclick = () => { if (officekitDirectFilesState.busy) return; selected.clear(); for (const file of entries) if (!file.keep && selected.size < 10000) selected.add(file.id); update(); };
  clear.onclick = () => { if (officekitDirectFilesState.busy) return; selected.clear(); update(); };
  const makeSelect = (id, label, choices) => {
    const wrap = officekitDirectNode('label', label), input = document.createElement('select');
    input.id = id; input.className = 'select'; input.setAttribute('aria-label', label);
    for (const [value, title] of choices) { const option = officekitDirectNode('option', title); option.value = value; input.append(option); }
    wrap.append(input); return {wrap, input};
  };
  container.append(wrapper);
  const pagination = officekitDirectNode('nav', '', 'ok-duplicate-controls'); pagination.setAttribute('aria-label', 'Duplicate result pages');
  const pageSize = makeSelect('duplicate-page-size', 'Groups per page', ['10', '25', '50', '100'].map(size => [size, size]));
  const pageStatus = officekitDirectNode('span'); pageStatus.id = 'duplicate-page-status'; pageStatus.setAttribute('role', 'status');
  const pageButtons = officekitDirectNode('div', '', 'join');
  const previous = officekitAsTextLink(officekitDirectNode('button', 'Previous')), next = officekitAsTextLink(officekitDirectNode('button', 'Next'));
  pageButtons.append(previous, next); pagination.append(pageSize.wrap, pageStatus, pageButtons); container.append(pagination);
  // Sort and paginate whole groups; display order never changes the scan's keeper.
  const grouped = groups.map((group, index) => ({index, files: groupedEntries[index],
    name: group.entries?.[0]?.display_name || group.entries?.[0]?.name.split('/').at(-1) || '', size: Number(group.size_bytes),
    date: (group.entries || []).reduce((latest, file) => Math.max(latest, Date.parse(file.modified_at) || 0), 0)}));
  const renderPage = () => {
    const ordered = [...grouped].sort((a, b) => {
      const result = sortKey === 'name' ? a.name.localeCompare(b.name, undefined, {numeric: true, sensitivity: 'base'}) : a[sortKey] - b[sortKey];
      return result * (descending ? -1 : 1) || a.index - b.index;
    });
    const size = Number(pageSize.input.value), pages = Math.ceil(ordered.length / size);
    page = Math.min(page, pages - 1);
    officekitOutcome.show(pageStatus, { state: 'info', text: `Page ${page + 1} of ${pages} · Groups ${page * size + 1}–${Math.min((page + 1) * size, ordered.length)} of ${ordered.length}` });
    previous.disabled = page === 0; next.disabled = page === pages - 1;
    for (const header of headers) {
      const active = header.key === sortKey;
      header.th.setAttribute('aria-sort', active ? descending ? 'descending' : 'ascending' : 'none');
      header.button.textContent = `${header.title} ${active ? descending ? '↓' : '↑' : '↕'}`;
    }
    body.replaceChildren(); checkboxes.clear();
    for (const file of ordered.slice(page * size, (page + 1) * size).flatMap(group => group.files)) {
      const tr = document.createElement('tr'), name = document.createElement('td'), input = document.createElement('input');
      input.type = 'checkbox'; input.className = 'checkbox checkbox-primary'; input.disabled = file.keep; input.checked = selected.has(file.id); input.setAttribute('aria-label', `${file.keep ? 'Keep' : 'Select'} ${file.name}`);
      input.onchange = () => { if (officekitDirectFilesState.busy) { input.checked = selected.has(file.id); return; } if (input.checked && selected.size < 10000) selected.add(file.id); else selected.delete(file.id); update(); };
      if (!file.keep) checkboxes.set(file.id, input);
      const title = officekitDirectNode('strong', file.display_name || file.name.split('/').at(-1)); title.title = file.full_path || file.name;
      if (!folders) name.append(input, ' ');
      name.append(title);
      if (file.keep && !folders) name.append(officekitDirectNode('span', 'Keep', 'badge badge-ghost ml-2'));
      const selection = officekitDirectFilesState.selections[0];
      const location = selection?.mode === 'folder' ? `${selection.displayNames[0]}/${file.name === '.' ? '' : file.name}` : file.name;
      const path = officekitDirectNode('div', `Group ${file.group} · ${location}`, 'ok-duplicate-path');
      path.title = file.full_path || file.name; path.tabIndex = 0; path.setAttribute('aria-label', file.full_path || file.name); name.append(path);
      const date = Date.parse(file.modified_at);
      const open = officekitDirectNode('td'), reveal = officekitDirectNode('button', 'Show in Finder', 'row-act');
      reveal.dataset.actionIcon = 'folder-open'; reveal.title = file.full_path || file.name;
      reveal.disabled = typeof window.__TAURI__?.core?.invoke !== 'function';
      reveal.onclick = async () => {
        reveal.disabled = true;
        try { await tauriInvoke()('file_job_reveal', {jobId, itemId:file.id}); officekitDirectStatus('Revealed in Finder.'); }
        catch (error) { officekitDirectStatus(error.message || String(error) || 'This scanned item could not be revealed. Run a fresh scan.'); }
        finally { reveal.disabled = false; }
      };
      open.append(reveal);
      tr.append(name, officekitDirectNode('td', Number.isFinite(date) ? new Date(date).toLocaleString() : 'Unavailable', 'ok-phone-hide'), officekitDirectNode('td',`${folders ? `${file.file_count} files · ` : ''}${Number(file.size).toLocaleString()} bytes`), open); body.append(tr);
    }
    wrapper.scrollTop = 0; update();
  };
  previous.onclick = () => { page--; renderPage(); };
  next.onclick = () => { page++; renderPage(); };
  pageSize.input.onchange = () => { page = 0; renderPage(); };
  renderPage();
  if (folders) return;
  if (!writable) container.append(officekitDirectNode('p', report.trash_supported === true ? 'Choose the folder again to allow moving copies to Trash.' : 'Moving copies to Trash is available on macOS.'));
  container.append(officekitTrashDisclosure(false), trash);
  trash.onclick = () => {
    if (officekitDirectFilesState.busy || officekitDirectFilesState.job !== jobId || !selected.size) return;
    const dialog = document.createElement('dialog'); dialog.className = 'modal';
    const box = officekitDirectNode('div', '', 'modal-box'), title = officekitDirectNode('h2', 'Move selected copies to Trash?', 'text-xl font-bold'); title.id = 'duplicate-trash-confirm-heading'; dialog.setAttribute('aria-labelledby', title.id);
    const text = officekitDirectNode('p', `${selected.size.toLocaleString()} selected ${selected.size === 1 ? 'copy will' : 'copies will'} be moved to Trash. Kept files remain in place. You can restore copies from Trash.`, 'py-4');
    const actions = officekitDirectNode('div', '', 'modal-action'), cancel = officekitDirectNode('button', 'Cancel'), confirm = officekitDirectNode('button', 'Move to Trash'); confirm.className = 'btn btn-error btn-outline';
    cancel.onclick = () => dialog.close(); confirm.onclick = () => { const fileIds = [...selected]; dialog.close(); officekitRunDirectFiles({sourceJobId: jobId, fileIds}); };
    actions.append(cancel, confirm); box.append(title, text, actions); dialog.append(box); dialog.addEventListener('close', () => { dialog.remove(); trash.focus(); }, {once:true}); document.body.append(dialog); dialog.showModal(); cancel.focus();
  };
}
