/* One reserved workspace action area. Original controls keep their DOM/form owners. */
(function (global) {
  'use strict';
  const groups = '.ok-action-dock,.officekit-result-actions,.officekit-result-action-status,.ok-pdf-dock,.ok-storage-footer,.ok-invoice-actions,.ok-invoice-folder-actions,.ok-trash-dock,#direct-file-actions';
  const browsing = new Set(['tab-home','tab-tools','tab-recents','tab-favorites','tab-history','tab-activity','tab-settings','tab-pricing']);
  const taskLabel = /^(?:draft email|email draft|calculate|convert|generate|create|run|find|scan|analy[sz]e|detect|inspect|compare|extract|merge|split|join|compress|remove (?:exif|metadata)|encode|decode|protect|unlock|decrypt|encrypt|capture|apply|start|stop|record|download|export|copy|paste|save result|refresh|load summary|look up|prepare model|generate notes|choose (?:file|files|folder|folders|a file|an image|image|pdf|pdfs|audio file)|select (?:file|files|image|pdf|pdfs))\b/i;
  const messageSelector = '.ok-outcome,.ok-action-dock__status,.officekit-result-action-status,#direct-file-status';
  const BAR_HEIGHT = 64, MESSAGE_HEIGHT = 36, SLOT_GAP = 8, EDGE = 16;
  let main, dock, summary, scheduled = false, count = 0, messages = new Set();
  let sources = new Set(), ancestors = new Set();
  const backdropStyles = new Map();
  const logicalVisible = element => element.isConnected && !element.closest('[hidden],.hidden') &&
    !element.closest('details:not([open])') && getComputedStyle(element).display !== 'none' &&
    getComputedStyle(element).visibility !== 'hidden' && element.getClientRects().length > 0;
  const appliesToActiveTool = element => {
    const scope = element.closest('[data-officekit-action-for]')?.dataset.officekitActionFor;
    return !scope || scope.split(/\s+/).includes(global.officekitActiveToolId);
  };

  function removeBackdropContainingBlock(parent) {
    const computed = getComputedStyle(parent);
    if (computed.backdropFilter === 'none' && computed.webkitBackdropFilter === 'none') return;
    backdropStyles.set(parent, ['backdrop-filter','-webkit-backdrop-filter'].map(property => ({
      property,
      value: parent.style.getPropertyValue(property),
      priority: parent.style.getPropertyPriority(property),
    })));
    parent.style.setProperty('backdrop-filter', 'none', 'important');
    parent.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
  }
  function restoreBackdrop(parent) {
    const saved = backdropStyles.get(parent);
    if (!saved) return;
    for (const {property,value,priority} of saved) {
      if (value) parent.style.setProperty(property,value,priority);
      else parent.style.removeProperty(property);
    }
    backdropStyles.delete(parent);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; refresh(); });
  }
  function refresh() {
    if (!main || !dock) return;
    const active = [...main.querySelectorAll('section[id^="tab-"]')].find(section => logicalVisible(section));
    const wanted = new Set();
    const statementResults = active?.id === 'tab-statement' ? active.querySelector('#statement-results') : null;
    const statementLoading = active?.id === 'tab-statement' ? active.querySelector('#statement-loading') : null;
    const statementHasResult = !!statementResults && !statementResults.classList.contains('hidden');
    const statementIsLoading = !!statementLoading && !statementLoading.classList.contains('hidden');
    let statementChooseAction = document.getElementById('statement-choose-action');
    if (active?.id === 'tab-statement' && !statementHasResult && !statementIsLoading && !statementChooseAction) {
      const choose = document.createElement('button');
      choose.id = 'statement-choose-action'; choose.type = 'button'; choose.className = 'btn btn-primary';
      choose.textContent = active.querySelector('#statement-file-error:not(.hidden)') ? 'Choose another statement' : 'Choose statement file';
      choose.onclick = () => document.getElementById('statement-dropzone').click();
      active.append(choose);
      statementChooseAction = choose;
    }
    if (statementChooseAction && (active?.id !== 'tab-statement' || statementHasResult || statementIsLoading)) statementChooseAction.remove();
    const result = active?.querySelector('#direct-file-results:not([hidden])');
    const direct = active?.querySelector('#direct-file-actions');
    const directFileResult = active?.id === 'tab-workspace' && !!result;
    // A completed file report replaces its scan actions. Rename preview still
    // needs Apply rename; choosing fresh inputs hides the report and restores Run.
    const archiveListing = !!result && typeof officekitDirectFilesState !== 'undefined' &&
      officekitDirectFilesState.action === 'archive' &&
      document.getElementById('direct-archive-mode')?.value === 'archive-extract' &&
      !officekitDirectFilesState.report;
    const hideDirect = !!result && !archiveListing && (typeof officekitDirectFilesState === 'undefined' || officekitDirectFilesState.action !== 'rename');
    if (direct && direct.classList.contains('ok-tool-actions-suppressed') !== hideDirect) direct.classList.toggle('ok-tool-actions-suppressed', hideDirect);
    const storageResult = active?.querySelector('#storage-candidates:not([hidden]),#storage-footer:not([hidden])');
    const storageRun = active?.querySelector('#storage-run');
    if (storageRun && storageRun.classList.contains('ok-tool-actions-suppressed') !== !!storageResult) {
      storageRun.classList.toggle('ok-tool-actions-suppressed', !!storageResult);
    }
    if (active && !browsing.has(active.id)) {
      const roots = [...active.querySelectorAll(groups)].filter(logicalVisible).filter(appliesToActiveTool).filter(root => !root.matches('.officekit-result-actions--inline'));
      for (const root of roots) if (!roots.some(other => other !== root && other.contains(root))) wanted.add(root);
      for (const button of active.querySelectorAll('button,label.btn')) {
        if (!logicalVisible(button) || !appliesToActiveTool(button) || [...wanted].some(root => root.contains(button))) continue;
        const label = button.textContent.replace(/\s+/g,' ').trim();
        const intakeAction = /^(?:choose|select)\b/i.test(label);
        if (directFileResult && intakeAction) continue;
        const filePickerLabel = button.matches('label.btn') && !!button.querySelector('input[type="file"]');
        if (button.closest('table,.officekit-result-actions--inline,.ok-pdf-toolbar,.ok-pdf-context,.ok-pdf-inspector,.ok-pdf-thumbnails,#screenshot-toolbar,#screenshot-contextual-settings,[role="tablist"]') ||
        button.matches('[role="tab"],[aria-pressed],.link,.calc-tab,[data-open-tool],[data-screenshot-tool],[data-pdf-tool],[data-inline-action]') ||
        (button.matches('.ok-text-link') && !intakeAction)) continue;
        if (button.id === 'statement-choose-action' || button.hasAttribute('data-officekit-action') || filePickerLabel || taskLabel.test(label)) wanted.add(button);
      }
    }
    for (const old of sources) if (!wanted.has(old)) {
      old.removeAttribute('data-officekit-docked');
      old.classList.remove('ok-tool-action-source','ok-tool-action-group');
      for (const property of ['left','top','max-width']) old.style.removeProperty(property);
    }
    const nextAncestors = new Set();
    for (const source of wanted) for (let parent = source.parentElement; parent && main.contains(parent); parent = parent.parentElement) nextAncestors.add(parent);
    for (const parent of ancestors) if (!nextAncestors.has(parent)) {
      parent.classList.remove('ok-tool-action-ancestor');
      restoreBackdrop(parent);
    }
    for (const parent of nextAncestors) if (!ancestors.has(parent)) {
      parent.classList.add('ok-tool-action-ancestor');
      removeBackdropContainingBlock(parent);
    }
    ancestors = nextAncestors;
    sources = wanted;
    // Browsing screens and tool screens with nothing to act on show no bar (DESIGN_SYSTEM.md: "Browsing screens show no empty bar").
    dock.hidden = !sources.size;
    if (!sources.size) {
      dock.removeAttribute('aria-owns');
      for (const old of messages) {
        old.removeAttribute('data-officekit-message');
        for (const property of ['left','top','max-width']) old.style.removeProperty(property);
      }
      messages = new Set();
      return;
    }

    // One fixed-height bar: the message slot on the left, buttons anchored to the right edge in a fixed order.
    const width = Math.max(1, dock.getBoundingClientRect().width - EDGE * 2);
    const actionSources = [...sources].filter(source => !source.matches(messageSelector));
    const messageCandidates = [...sources].flatMap(source => source.matches(messageSelector) ? [source] : [...source.querySelectorAll(messageSelector)]);
    const message = messageCandidates.find(element => element.textContent.trim() && logicalVisible(element)) || null;
    const nextMessages = new Set(message ? [message] : []);
    for (const old of messages) if (!nextMessages.has(old)) {
      old.removeAttribute('data-officekit-message');
      for (const property of ['left','top','max-width']) old.style.removeProperty(property);
    }
    for (const current of nextMessages) current.dataset.officekitMessage = 'true';
    messages = nextMessages;
    const items = []; let total = 0;
    for (const source of actionSources) {
      if (!source.id) source.id = `officekit-action-source-${++count}`;
      if (!source.hasAttribute('data-officekit-docked')) {
        source.dataset.officekitDocked = 'true';
        source.classList.add('ok-tool-action-source');
        if (source.tagName !== 'BUTTON' && !source.matches('label.btn')) source.classList.add('ok-tool-action-group');
      }
      source.style.removeProperty('left');
      source.style.removeProperty('top');
      if (source.style.maxWidth !== `${width}px`) source.style.maxWidth = `${width}px`;
      const bounds = source.getBoundingClientRect(), itemWidth = Math.min(width, Math.ceil(bounds.width));
      total += (items.length ? SLOT_GAP : 0) + itemWidth;
      items.push({source,width:itemWidth,height:Math.ceil(bounds.height)});
    }
    if (dock.style.height !== `${BAR_HEIGHT}px`) dock.style.height = `${BAR_HEIGHT}px`;
    const bounds = dock.getBoundingClientRect();
    let x = Math.max(bounds.left + EDGE, bounds.left + EDGE + width - total);
    const buttonsLeft = items.length ? x : bounds.left + EDGE + width;
    for (const item of items) {
      const top = `${Math.round(bounds.top + (BAR_HEIGHT - item.height) / 2)}px`, left = `${Math.round(x)}px`;
      if (item.source.style.top !== top) item.source.style.top = top;
      if (item.source.style.left !== left) item.source.style.left = left;
      x += item.width + SLOT_GAP;
    }
    if (message) {
      message.style.left = `${Math.round(bounds.left + EDGE)}px`;
      message.style.top = `${Math.round(bounds.top + (BAR_HEIGHT - MESSAGE_HEIGHT) / 2)}px`;
      message.style.maxWidth = `${Math.max(0, Math.round(buttonsLeft - SLOT_GAP * 2 - (bounds.left + EDGE)))}px`;
    }
    // The tool name is no longer shown in the bar; officekitActiveToolTitle stays for bug reports and tests.
    summary.textContent = '';
    summary.removeAttribute('title');
    const owns = [...sources].map(source=>source.id).filter(Boolean).join(' ');
    if (dock.getAttribute('aria-owns') !== owns) dock.setAttribute('aria-owns', owns);
  }
  function start() {
    main = document.getElementById('app-main'); dock = document.getElementById('officekit-tool-actions'); summary = document.getElementById('officekit-tool-action-summary');
    if (!main || !dock) return;
    new MutationObserver(schedule).observe(main,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden','class','disabled']});
    new ResizeObserver(schedule).observe(document.getElementById('officekit-workspace-column'));
    global.addEventListener('resize',schedule);
    document.fonts?.ready.then(schedule);
    main.addEventListener('toggle',schedule,true);
    global.OfficeKitToolActions = {refresh,schedule};
    refresh();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})(window);
