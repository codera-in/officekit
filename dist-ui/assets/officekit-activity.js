/* Session-local activity monitor for work that can outlive the current tool view. */
(function (global) {
  'use strict';
  const records = new Map();
  const keepMs = 30 * 60 * 1000;
  let sequence = 0;
  let activeTool = 'OfficeKit';
  let lastAction = null;
  let currentTab = 'tools';
  const running = record => record.state === 'running' || record.state === 'queued';
  const byRecent = (left, right) => (running(right) - running(left)) || right.updatedAt - left.updatedAt;

  function clean() {
    const now = Date.now();
    for (const [id, record] of records) if (!running(record) && now - record.updatedAt > keepMs) records.delete(id);
    const finished = [...records.values()].filter(record => !running(record)).sort(byRecent);
    for (const record of finished.slice(20)) records.delete(record.id);
  }
  function notify() {
    clean();
    global.dispatchEvent(new CustomEvent('officekit-activity-change'));
  }
  function start(options = {}) {
    const id = String(options.id || `activity-${++sequence}`);
    const previous = records.get(id);
    const record = {
      id, title: String(options.title || 'OfficeKit task'), tool: String(options.tool || activeTool),
      tab: String(options.tab || currentTab), state: options.state || 'running',
      phase: String(options.phase || 'Working'), progress: Number.isFinite(options.progress) ? options.progress : null,
      total: Number.isFinite(options.total) ? options.total : null,
      unit: String(options.unit || 'items'),
      insights: Array.isArray(options.insights) ? options.insights.map(item => ({label:String(item.label),value:String(item.value),detail:String(item.detail||'')})) : [],
      summary: String(options.summary || ''), startedAt: previous?.startedAt || Date.now(), updatedAt: Date.now(),
      cancel: typeof options.cancel === 'function' ? options.cancel : previous?.cancel || null,
      returnTo: typeof options.returnTo === 'function' ? options.returnTo : previous?.returnTo || null,
      background: options.background ?? previous?.background ?? false,
      percent: Number.isFinite(options.percent) ? Math.max(0,Math.min(100,options.percent)) : null,
    };
    records.set(id, record); notify();
    return {
      id,
      update(patch = {}) { update(id, patch); },
      finish(patch = {}) { finish(id, patch); },
    };
  }
  function update(id, patch = {}) {
    const record = records.get(String(id)); if (!record) return;
    for (const key of ['title','tool','tab','phase','summary','unit']) if (typeof patch[key] === 'string') record[key] = patch[key];
    if (['queued','running','complete','failed','cancelled'].includes(patch.state)) record.state = patch.state;
    if (patch.progress === null || Number.isFinite(patch.progress)) record.progress = patch.progress;
    if (patch.total === null || Number.isFinite(patch.total)) record.total = patch.total;
    if (patch.percent === null || Number.isFinite(patch.percent)) record.percent = patch.percent === null ? null : Math.max(0,Math.min(100,patch.percent));
    if (Array.isArray(patch.insights)) record.insights = patch.insights.map(item => ({label:String(item.label),value:String(item.value),detail:String(item.detail||'')}));
    if (typeof patch.cancel === 'function' || patch.cancel === null) record.cancel = patch.cancel;
    if (typeof patch.returnTo === 'function' || patch.returnTo === null) record.returnTo = patch.returnTo;
    if (typeof patch.background === 'boolean') record.background = patch.background;
    record.updatedAt = Date.now(); notify();
  }
  function finish(id, patch = {}) {
    const record = records.get(String(id)); if (!record) return;
    update(id, { ...patch, state: patch.state || 'complete', phase: patch.phase || (patch.state === 'failed' ? 'Could not complete' : patch.state === 'cancelled' ? 'Cancelled' : 'Complete'), percent: patch.percent ?? 100, cancel: null });
  }
  function entries() { clean(); return [...records.values()].sort(byRecent).map(record => ({ ...record })); }
  function activeCount() { return [...records.values()].filter(running).length; }
  function continueInBackground(id) {
    const record = records.get(String(id)); if (!record || !running(record)) return;
    update(id, { background: true });
    if (typeof global.switchTab === 'function') global.switchTab('home');
  }
  function open(id) {
    const record = records.get(String(id)); if (!record) return;
    if (typeof record.returnTo === 'function') record.returnTo();
    else if (typeof global.switchTab === 'function') global.switchTab(record.tab);
  }
  async function cancel(id) {
    const record = records.get(String(id)); if (!record?.cancel || !running(record)) return;
    try { await record.cancel(); update(id,{phase:'Cancellation requested'}); }
    catch (error) { update(id,{phase:error?.message || 'Cancellation failed'}); }
  }
  const formatNumber = value => Number.isFinite(value) ? Math.trunc(value).toLocaleString() : '—';
  function button(label, action, className = 'btn btn-outline') {
    const element = document.createElement('button'); element.type = 'button'; element.className = className; element.textContent = label; element.addEventListener('click',action); return element;
  }
  function progressElement(record, compact = false) {
    const bar = document.createElement('progress'); bar.className = `progress progress-primary${compact ? ' ok-activity-progress-compact' : ''}`;
    if (record.percent !== null) { bar.max = 100; bar.value = record.percent; bar.setAttribute('aria-valuetext',`${Math.round(record.percent)}%`); }
    else { bar.removeAttribute('value'); bar.setAttribute('aria-label',`${record.phase}; total is not available`); }
    return bar;
  }
  function metricList(record) {
    const list = document.createElement('dl'); list.className = 'ok-activity-metrics';
    for (const metric of record.insights) {
      const item = document.createElement('div'); item.className = 'ok-activity-metric';
      const term = document.createElement('dt'); term.textContent = metric.label;
      const value = document.createElement('dd'); value.textContent = metric.value;
      if (metric.detail) { const detail = document.createElement('small'); detail.textContent = metric.detail; item.append(term,value,detail); }
      else item.append(term,value);
      list.append(item);
    }
    return list;
  }
  function renderCard(record) {
    const card = document.createElement('article'); card.className = 'ok-activity-card';
    const header = document.createElement('div'); header.className = 'ok-activity-card-head';
    const title = document.createElement('h3'); title.textContent = `${record.tool} · ${record.title}`;
    const state = document.createElement('span'); state.className = `ok-activity-state ok-activity-state--${record.state}`; state.textContent = record.phase;
    header.append(title,state); card.append(header);
    const isActive = running(record);
    if (isActive) {
      card.append(progressElement(record));
      if (record.total !== null || record.progress !== null) {
        const count = document.createElement('p'); count.className = 'ok-activity-count';
        count.textContent = record.total !== null
          ? `${formatNumber(record.progress || 0)} of ${formatNumber(record.total)} ${record.unit} · ${formatNumber(Math.max(0,record.total-(record.progress||0)))} remaining`
          : `${formatNumber(record.progress || 0)} ${record.unit} processed · total is not available`;
        card.append(count);
      }
    }
    if (record.insights.length) card.append(metricList(record));
    if (record.summary) { const summary = document.createElement('p'); summary.className = 'ok-activity-summary'; summary.textContent = record.summary; card.append(summary); }
    const actions = document.createElement('div'); actions.className = 'ok-activity-actions';
    if (isActive) actions.append(button(record.background ? 'Return to tool' : 'Open tool',() => open(record.id),'btn btn-primary'));
    else if (record.returnTo) actions.append(button('Open result',() => open(record.id),'btn btn-outline'));
    if (isActive && record.cancel) actions.append(button('Cancel',() => void cancel(record.id),'btn btn-outline'));
    if (isActive && !record.background && record.tab !== 'activity') actions.append(button('Continue in background',() => continueInBackground(record.id),'btn btn-soft'));
    if (actions.childElementCount) card.append(actions);
    return card;
  }
  function render() {
    const count = activeCount();
    for (const badge of document.querySelectorAll('[data-officekit-activity-count]')) {
      badge.textContent = String(count); badge.hidden = count === 0;
      badge.setAttribute('aria-label',`${count} active ${count === 1 ? 'task' : 'tasks'}`);
    }
    const mini = document.getElementById('officekit-activity-mini');
    if (mini) {
      const active = entries().filter(running).slice(0,2);
      mini.replaceChildren(); mini.hidden = active.length === 0;
      for (const record of active) {
        const item = document.createElement('section'); item.className = 'ok-activity-mini-item';
        const header = document.createElement('div'); header.className = 'ok-activity-mini-head';
        const label = document.createElement('strong'); label.textContent = `${record.tool} · ${record.title}`;
        const phase = document.createElement('span'); phase.textContent = record.phase;
        header.append(label,phase); item.append(header,progressElement(record,true));
        const row = document.createElement('div'); row.className = 'ok-activity-mini-row';
        const detail = document.createElement('span'); detail.textContent = record.insights.length
          ? record.insights.map(metric => `${metric.label}: ${metric.value}`).join(' · ')
          : record.total !== null ? `${formatNumber(record.progress||0)} / ${formatNumber(record.total)} ${record.unit}` : record.progress !== null ? `${formatNumber(record.progress||0)} ${record.unit} processed` : record.phase;
        row.append(detail,button('Open Activity',() => { global.switchTab('activity'); },'btn btn-ghost'));
        if (!record.background && record.tab !== 'activity') row.append(button('Continue in background',() => continueInBackground(record.id),'btn btn-soft'));
        item.append(row); mini.append(item);
      }
    }
    const panel = document.getElementById('officekit-activity-content');
    if (!panel) return;
    const all = entries(); panel.replaceChildren();
    const active = all.filter(running), recent = all.filter(record => !running(record));
    if (!active.length && !recent.length) {
      const emptyCard = document.createElement('div');
      emptyCard.className = 'ok-activity-empty-card p-6 rounded-2xl border border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/5 text-center space-y-2';
      const icon = document.createElement('div');
      icon.className = 'w-10 h-10 rounded-xl bg-sky-500/10 text-sky-500 flex items-center justify-center text-lg mx-auto';
      icon.innerHTML = '<i class="fa-solid fa-list-check" aria-hidden="true"></i>';
      const title = document.createElement('h3');
      title.className = 'text-sm font-bold text-slate-800 dark:text-white';
      title.textContent = 'No active operations';
      const desc = document.createElement('p');
      desc.className = 'text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto';
      desc.textContent = 'Background tasks and recent results will appear here as you work.';
      emptyCard.append(icon, title, desc);
      panel.append(emptyCard);
      return;
    }
    if (active.length) {
      const activeHeading = document.createElement('h2'); activeHeading.textContent = `Running · ${active.length}`; panel.append(activeHeading);
      for (const record of active) panel.append(renderCard(record));
    }
    if (recent.length) {
      const recentHeading = document.createElement('h2'); recentHeading.textContent = 'Recent results'; panel.append(recentHeading);
      for (const record of recent) panel.append(renderCard(record));
    }
  }
  function activeToolContext() {
    const section = [...document.querySelectorAll('#app-main > section')].find(item => !item.classList.contains('hidden'));
    const heading = section?.querySelector('h1')?.textContent?.trim();
    const tab = section?.id?.replace(/^tab-/,'') || currentTab;
    return { tool: heading || activeTool, tab };
  }
  function eligibleApiMutation(input, init) {
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!['POST','PUT','PATCH','DELETE'].includes(method)) return null;
    let url; try { url = new URL(input instanceof Request ? input.url : String(input),location.href); } catch { return null; }
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return null;
    if (url.pathname === '/api/file-jobs' || url.pathname.startsWith('/api/file-jobs/')) return null;
    if (url.pathname.startsWith('/api/storage-scans/')) return null;
    if (method === 'DELETE' && /^\/api\/storage-cleanup-plans\/[^/]+\/execution$/.test(url.pathname)) return null;
    if (/^\/api\/pdf-documents\/[^/]+\/(?:exports|ocr-reviews|signatures|verifications)$/.test(url.pathname)) return null;
    if (url.pathname.includes('/cancellations')) return null;
    return { method, url };
  }
  function installFetchTracker() {
    if (typeof global.fetch !== 'function' || global.fetch.__officekitActivity) return;
    const original = global.fetch.bind(global);
    const tracked = async (input,init) => {
      const api = eligibleApiMutation(input,init);
      if (!api) return original(input,init);
      const context = activeToolContext();
      const action = lastAction && Date.now() - lastAction.at < 5000 ? lastAction.label : '';
      const label = action || api.url.pathname.split('/').filter(Boolean).at(-1).replaceAll('-',' ');
      const activity = start({ title:label || 'Working',tool:context.tool,tab:context.tab,phase:'Working' });
      try {
        const response = await original(input,init);
        activity.finish({ state:response.ok ? 'complete' : 'failed', phase:response.ok ? 'Complete' : 'Needs attention', summary:response.ok ? 'The result is ready in this tool.' : `The request failed (${response.status}).` });
        return response;
      } catch (error) {
        activity.finish({state:'failed',phase:'Could not complete',summary:error?.message || 'The request could not reach OfficeKit.'});
        throw error;
      }
    };
    tracked.__officekitActivity = true; global.fetch = tracked;
  }
  function startApp() {
    currentTab = global.officekitCurrentTab || 'tools';
    document.addEventListener('click',event => {
      const button = event.target instanceof Element ? event.target.closest('button,[type="submit"]') : null;
      if (!button || button.closest('#officekit-activity-content,#officekit-activity-mini')) return;
      const context = activeToolContext(); activeTool = context.tool; currentTab = context.tab;
      const label = button.textContent.replace(/\s+/g,' ').trim();
      if (label) lastAction = {label,at:Date.now()};
    },true);
    global.addEventListener('officekit-activity-change',render);
    const originalSwitch = global.switchTab;
    if (typeof originalSwitch === 'function' && !originalSwitch.__officekitActivity) {
      const wrapped = function (tab) { currentTab = tab; return originalSwitch.apply(this,arguments); };
      wrapped.__officekitActivity = true; global.switchTab = wrapped;
    }
    installFetchTracker(); render();
  }
  global.OfficeKitActivity = { start, update, finish, entries, activeCount, continueInBackground, open, cancel, render };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',startApp,{once:true}); else startApp();
})(window);
