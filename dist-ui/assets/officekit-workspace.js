/* Shared shell behavior. Tool drafts and jobs remain owned by their existing adapters. */
function officekitSetSidebarCollapsed(collapsed, explicit = false, forceAutomatic = false) {
  const sidebar = document.getElementById('app-sidebar');
  if (!sidebar) return;
  if (!explicit && !forceAutomatic && window.officekitSidebarPreference !== undefined) collapsed = window.officekitSidebarPreference;
  sidebar.classList.toggle('ok-collapsed', collapsed);
  const button = document.getElementById('sidebar-toggle');
  button?.setAttribute('aria-expanded', String(!collapsed));
  button?.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
  const label = button?.querySelector('.ok-nav-label');
  if (label) label.textContent = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  if (explicit) {
    window.officekitSidebarPreference = collapsed;
    try { localStorage.setItem('officekit.sidebar.collapsed', String(collapsed)); } catch { /* Shell remains usable. */ }
  }
}

function officekitInitWorkspaceUX() {
  const sidebar = document.getElementById('app-sidebar');
  sidebar.querySelectorAll('button:not(#sidebar-toggle)').forEach(button => {
    const name = button.textContent.trim();
    if (!button.getAttribute('aria-label')) button.setAttribute('aria-label', name);
    button.title = name;
    for (const node of [...button.childNodes]) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
        const span = document.createElement('span'); span.className = 'ok-nav-label'; span.textContent = node.textContent; node.replaceWith(span);
      }
    }
  });
  try {
    const value = localStorage.getItem('officekit.sidebar.collapsed');
    if (value === 'true' || value === 'false') window.officekitSidebarPreference = value === 'true';
  } catch { /* Defaults are not a storage prerequisite. */ }
  officekitSetSidebarCollapsed(window.matchMedia('(max-width:760px)').matches, false);
  document.getElementById('sidebar-toggle').addEventListener('click', () => officekitSetSidebarCollapsed(!sidebar.classList.contains('ok-collapsed'), true));
  document.addEventListener('keydown', event => {
    if (event.isComposing) return;
    const editing = event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"]');
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b' && !editing) {
      event.preventDefault(); document.getElementById('sidebar-toggle').click();
    } else if (event.altKey && !event.metaKey && !event.ctrlKey && !editing && ['r','f'].includes(event.key.toLowerCase())) {
      event.preventDefault(); switchTab(event.key.toLowerCase() === 'r' ? 'recents' : 'favorites');
    }
  });
  const chrome = document.querySelector('header');
  const banner = document.getElementById('inapp-announcement-banner');
  const updateChrome = () => document.documentElement.style.setProperty('--ok-chrome-height', `${chrome.getBoundingClientRect().height + (banner.classList.contains('hidden') ? 0 : banner.getBoundingClientRect().height)}px`);
  if (typeof ResizeObserver === 'function') { const observer = new ResizeObserver(updateChrome); observer.observe(chrome); observer.observe(banner); }
  updateChrome();
  officekitBindQuickAccess();
  void officekitLoadMenuStats();
  const listen = window.__TAURI__?.event?.listen;
  if (typeof listen === 'function') void listen('menu-stats-changed', event => officekitApplyMenuStats(event.payload));
}

// Which stats show in the menu bar is chosen in Quick controls and saved by the app, not by this page.
let officekitMenuStats = { cpu: false, gpu: false, temperature: false, ram: false, storage: false, network: false, battery: false, bluetooth: false };
const OFFICEKIT_DRAWER_STAT = { cpu: 'cpu', gpu: 'gpu', sensors: 'temperature', ram: 'ram', ssd: 'storage', net: 'network', battery: 'battery', bluetooth: 'bluetooth' };

function officekitMenuStatsAny() {
  return Object.values(officekitMenuStats).some(Boolean);
}

function officekitApplyMenuStats(stats) {
  officekitMenuStats = {
    cpu: !!stats?.cpu, gpu: !!stats?.gpu, temperature: !!stats?.temperature, ram: !!stats?.ram,
    storage: !!stats?.storage, network: !!stats?.network, battery: !!stats?.battery, bluetooth: !!stats?.bluetooth,
  };
  if (!officekitMenuStatsAny() && typeof window.__TAURI__?.core?.invoke === 'function') {
    void tauriInvoke()('tray_stats_update', { text: '' });
    void tauriInvoke()('menu_drawers_remove');
  }
  void officekitRefreshQuickStats();
}

async function officekitLoadMenuStats() {
  if (typeof window.__TAURI__?.core?.invoke !== 'function') return;
  try {
    let stats = await tauriInvoke()('menu_stats_status');
    if (!stats?.configured) {
      // First launch with the four switches: keep the menu bar the way the old single switch left it.
      let wasOn = false;
      try { wasOn = localStorage.getItem('officekit.stats.persistent') === 'true'; } catch { /* storage may be blocked */ }
      stats = await tauriInvoke()('menu_stats_adopt_legacy', { wasOn });
    }
    officekitApplyMenuStats(stats);
  } catch { void officekitRefreshQuickStats(); /* the menu bar simply stays off; history still builds */ }
}

async function officekitBindQuickAccess() {
  const listen = window.__TAURI__?.event?.listen;
  if (typeof listen !== 'function') return;
  await listen('quick-access', async event => {
    const action = event.payload?.action;
    if (action === 'transcribe') {
      try { const state=await tauriInvoke()('quick_access_transcribe');window.officekitTrayRecording=state.recording;await tauriInvoke()('quick_access_recording',{recording:state.recording}); }
      catch(error){showAppFeedbackToast(error.message||'Transcription could not start. Open OfficeKit to check microphone/model setup.','error');}
    } else if (action === 'screenshot') await officekitCaptureScreenshot();
    else if (action === 'system-stats') { switchTab('quick-stats'); officekitRefreshQuickStats(); }
    else if (action === 'drawer-quit') { const pid = event.payload?.pid; if (Number.isInteger(pid)) await officekitRunMenuDrawerQuit(pid); }
    else if (action === 'drawer-quit-cancel') { const pid = event.payload?.pid; if (Number.isInteger(pid)) await officekitCancelMenuDrawerQuit(pid); }
    else if (action === 'drawer-open') { if (event.payload?.tool === 'storage') { switchTab('workspace'); officekitOpenDirectFileTool('storage'); } }
    else if (action === 'network-check') void officekitRunMenuNetworkHealthCheck();
    else if (action === 'open') switchTab('home');
    else if(action==='quit'){
      const active=window.officekitTrayRecording || typeof meetingRecordingActive!=='undefined'&&meetingRecordingActive || typeof officekitDirectFilesState!=='undefined'&&officekitDirectFilesState.busy;
      if(!active||window.confirm('Quit OfficeKit and stop active recording or file operations?'))await tauriInvoke()('officekit_quit');
    }
  });
  await listen('quick-access-recording',event=>{window.officekitTrayRecording=event.payload?.recording===true;});
}

let officekitDrawerNames = new Map();
let officekitMenuQuitFeedback = null;
let officekitMenuQuitBusy = false;

/** A transfer rate in the unit that keeps it short: 512 B/s, 9.8 KB/s, 12.4 MB/s, 1.2 GB/s. `compact` drops the space and "/s". */
function officekitFormatRate(value, compact, fallback = '—') {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return fallback;
  const units = ['B', 'K', 'M', 'G', 'T'];
  let amount = value, index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  const digits = index === 0 || (compact && amount >= 10) ? 0 : 1;
  const text = amount.toFixed(digits);
  return compact ? `${text}${units[index]}` : `${text} ${index === 0 ? 'B' : `${units[index]}B`}/s`;
}

/** A byte count in the unit that keeps it short, to one decimal: 512 B, 9.8 KB, 12.4 MB, 1.2 GB, 3.1 TB. */
function officekitFormatSize(value, fallback = '—') {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return fallback;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let amount = value, index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return `${index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

/** The average temperature of the sensors whose name matches, or null when the Mac exposes none. Sensors are named by the hardware, e.g. "PMU tdie3". */
function officekitSensorTemperature(sensors, pattern) {
  if (!Array.isArray(sensors)) return null;
  const readings = sensors
    .filter(sensor => sensor && typeof sensor.name === 'string' && pattern.test(sensor.name) && typeof sensor.current_c === 'number' && Number.isFinite(sensor.current_c) && sensor.current_c > 0 && sensor.current_c < 150)
    .map(sensor => sensor.current_c);
  return readings.length ? readings.reduce((total, value) => total + value, 0) / readings.length : null;
}

/** History kept in memory for the graphs: one point every ten seconds for thirty minutes. Never saved. */
const OFFICEKIT_STAT_INTERVAL_MS = 10000;
const OFFICEKIT_STAT_SAMPLES = 180;
let officekitStatHistory = { cpu: [], memory: [], gpu: [], battery: [], disk: [], network: [] };
let officekitLastStatSampleAt = -Infinity;

function officekitResetStatHistory() {
  Object.values(officekitStatHistory).forEach(series => { series.length = 0; });
  officekitLastStatSampleAt = -Infinity;
}

/** Records one point per interval; pass the clock reading (`at`) so faster polling does not crowd the graph. */
function officekitRecordStatSample(data, at) {
  if (typeof at === 'number') {
    if (at - officekitLastStatSampleAt < OFFICEKIT_STAT_INTERVAL_MS) return;
    officekitLastStatSampleAt = at;
  }
  const push = (name, value) => {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return;
    const series = officekitStatHistory[name];
    series.push(value);
    if (series.length > OFFICEKIT_STAT_SAMPLES) series.splice(0, series.length - OFFICEKIT_STAT_SAMPLES);
  };
  const sum = (a, b) => typeof a === 'number' && typeof b === 'number' ? a + b : null;
  push('cpu', data.cpu_percent);
  push('memory', data.memory_percent);
  push('disk', sum(data.disk?.read_bytes_per_second, data.disk?.write_bytes_per_second));
  push('network', sum(data.download_bytes_per_second, data.upload_bytes_per_second));
  push('gpu', data.gpu?.utilization_percent);
  push('battery', data.battery?.percent);
}

/** Graph heights (0 to 100) for one history series. Percentages stay as they are; rates scale to the busiest sample. */
function officekitHistorySeries(name) {
  const values = officekitStatHistory[name] || [];
  if (name === 'cpu' || name === 'memory' || name === 'gpu' || name === 'battery') return values.map(value => Math.min(100, value));
  const top = Math.max(1, ...values);
  return values.map(value => Math.min(100, (value / top) * 100));
}

/** A small line-and-fill graph of 0 to 100 heights. Only numbers go into the markup. */
function officekitRenderHistoryGraph(node, values) {
  if (!values.length) { node.innerHTML = ''; return; }
  const width = 360, height = 52;
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1) * width).toFixed(1)},${(height - Math.min(100, Math.max(0, value)) / 100 * height).toFixed(1)}`);
  const line = points.join(' ');
  const fill = `0,${height} ${line} ${width},${height}`;
  node.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img"><polygon points="${fill}"/><polyline points="${line}"/></svg>`;
}

const OFFICEKIT_CARD_TONES = new Set(['blue', 'orange', 'red', 'teal', 'violet', 'grey']);

/**
 * One stat card from a drawer model, so the in-app pages show exactly what the menu-bar panels show.
 * Everything is set as text or a numeric style value; nothing from the model becomes markup.
 */
function officekitRenderStatCard(drawer) {
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const tone = value => (OFFICEKIT_CARD_TONES.has(value) ? value : null);
  const percent = value => Math.min(100, Math.max(0, Number(value) || 0));
  const card = make('article', 'ok-system-card');
  card.dataset.statCard = drawer.id;
  card.append(make('h2', '', drawer.heading));
  if (drawer.big) card.append(make('p', 'ok-system-metric', drawer.big));
  if (drawer.rings?.length) {
    const rings = make('div', 'ok-card-rings');
    drawer.rings.forEach((ring, index) => {
      const node = make('div', `ok-ring${drawer.rings.length === 3 && index === 1 ? ' ok-ring-large' : ''}`);
      node.style.setProperty('--p', String(percent(ring.percent)));
      if (tone(ring.tone)) node.dataset.tone = ring.tone;
      node.append(make('span', '', ring.label));
      if (ring.title) node.append(make('small', '', ring.title));
      rings.append(node);
    });
    card.append(rings);
  }
  if (drawer.sub) card.append(make('p', 'ok-card-sub', drawer.sub));
  const line = item => {
    const row = make('div', 'ok-card-line');
    const label = make('span');
    if (tone(item.tone)) { const dot = make('i', 'ok-card-dot'); dot.dataset.tone = item.tone; label.append(dot); }
    label.append(document.createTextNode(item.label));
    row.append(label, make('b', '', item.value));
    return row;
  };
  (drawer.summary || []).forEach(item => card.append(line(item)));
  if (drawer.history?.length) {
    card.append(make('div', 'ok-card-section', drawer.historyTitle || 'Usage history'));
    const graph = make('div', 'ok-stat-history');
    graph.setAttribute('aria-label', drawer.historyTitle || 'Usage history');
    officekitRenderHistoryGraph(graph, drawer.history);
    card.append(graph);
  }
  if (drawer.cores?.length) {
    card.append(make('div', 'ok-card-section', 'Cores'));
    const cores = make('div', 'ok-card-cores');
    drawer.cores.forEach(core => {
      const slot = make('i');
      if (tone(core.tone)) slot.dataset.tone = core.tone;
      const fill = make('b');
      fill.style.height = `${percent(core.percent)}%`;
      slot.append(fill);
      cores.append(slot);
    });
    card.append(cores);
  }
  if (drawer.details?.length) {
    card.append(make('div', 'ok-card-section', 'Details'));
    drawer.details.forEach(item => {
      if (item.heading) card.append(make('div', 'ok-card-section', item.heading));
      else if (Array.isArray(item.bar)) {
        const bar = make('div', 'ok-card-bar');
        item.bar.forEach(segment => {
          const part = make('i');
          part.style.width = `${percent(segment.percent)}%`;
          if (tone(segment.tone)) part.dataset.tone = segment.tone;
          bar.append(part);
        });
        card.append(bar);
      } else if (item.label) card.append(line(item));
    });
  }
  if (drawer.rows?.length) {
    card.append(make('div', 'ok-card-section', drawer.rowsTitle || 'Top processes'));
    drawer.rows.forEach(row => card.append(line({ label: row.name, value: row.value })));
  }
  return card;
}

/** Cards for the in-app pages: the host's cards are replaced with the drawers whose ids are asked for. */
function officekitRenderStatCards(hostId, drawers, ids) {
  const host = document.getElementById(hostId);
  if (!host) return;
  const wanted = ids ? drawers.filter(drawer => ids.includes(drawer.id)) : drawers;
  host.replaceChildren(...wanted.map(officekitRenderStatCard));
}

function officekitFormatMetricBytes(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? `${(value / OFFICEKIT_GIGABYTE).toFixed(1)} GB` : 'Unavailable';
}

function officekitFormatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days} ${days === 1 ? 'day' : 'days'}, ${hours} ${hours === 1 ? 'hour' : 'hours'}`;
  if (hours > 0) return `${hours} ${hours === 1 ? 'hour' : 'hours'}, ${minutes} min`;
  return `${minutes} min`;
}

const OFFICEKIT_PRESSURE_LABELS = { normal: 'Normal', warning: 'Warning', critical: 'Critical' };
const OFFICEKIT_GIGABYTE = 1024 ** 3;

/** Builds resource cards from a metrics snapshot and the in-memory history. */
function officekitBuildDrawers(data, applications, { groupApplications = false } = {}) {
  const cpuApplications = Array.isArray(applications) ? applications : applications?.cpu || [];
  const memoryApplications = Array.isArray(applications) ? applications : applications?.memory || [];
  const gpuApplications = Array.isArray(applications) ? applications : applications?.gpu || [];
  const whole = value => typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}%` : '—';
  const precise = value => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';
  const row = (application, value) => {
    const names = Array.isArray(application.process_names) ? application.process_names : [];
    const fullDetail = groupApplications && application.process_count > 1
      ? `${application.process_count} processes · ${names.join(', ')}${names.length < application.process_count ? ', …' : ''}`
      : '';
    const detail = Array.from(fullDetail).slice(0, 120).join('');
    return { pid: application.pid, name: application.name || application.process_name || 'Process', detail, value, killable: application.is_killable === true };
  };
  const byCpu = [...cpuApplications].sort((a, b) => b.cpu_percent - a.cpu_percent).slice(0, 8);
  const byMemory = [...memoryApplications].sort((a, b) => b.memory_bytes - a.memory_bytes).slice(0, 8);
  const gpuAttributionAvailable = groupApplications && gpuApplications.some(application => typeof application.gpu_percent === 'number' && Number.isFinite(application.gpu_percent));
  const byGpu = gpuAttributionAvailable
    ? [...gpuApplications].filter(application => typeof application.gpu_percent === 'number' && Number.isFinite(application.gpu_percent)).sort((a, b) => b.gpu_percent - a.gpu_percent).slice(0, 8)
    : [];
  const time = new Date(data.captured_at).toLocaleTimeString();
  const compactRate = value => officekitFormatRate(value, true);
  const fullRate = value => officekitFormatRate(value, false);
  const gigabytes = bytes => `${(bytes / OFFICEKIT_GIGABYTE).toFixed(1)} GB`;
  const share = (bytes, total) => total > 0 ? Math.min(100, (bytes / total) * 100) : 0;
  const series = name => officekitHistorySeries(name);
  const memory = data.memory || null;
  const swap = data.swap || null;
  const cpu = data.cpu_breakdown || null;
  const disk = data.disk || null;
  const pressure = OFFICEKIT_PRESSURE_LABELS[data.memory_pressure] || 'Unavailable';

  const memoryRings = [];
  const pressureLook = { normal: [100, 'teal'], warning: [66, 'orange'], critical: [33, 'red'] }[data.memory_pressure];
  if (pressureLook) memoryRings.push({ label: pressure, percent: pressureLook[0], tone: pressureLook[1], title: 'Pressure' });
  memoryRings.push({ label: whole(data.memory_percent), percent: Math.min(100, data.memory_percent ?? 0), tone: 'blue' });
  if (swap) memoryRings.push({ label: `${(swap.used_bytes / OFFICEKIT_GIGABYTE).toFixed(1)}G`, percent: swap.percent, tone: 'orange', title: 'Swap' });
  const memoryDetails = memory ? [
    { label: 'Used', value: gigabytes(memory.used_bytes) },
    { bar: [
      { percent: share(memory.app_bytes, memory.total_bytes), tone: 'blue' },
      { percent: share(memory.wired_bytes, memory.total_bytes), tone: 'orange' },
      { percent: share(memory.compressed_bytes, memory.total_bytes), tone: 'red' },
      { percent: share(memory.free_bytes, memory.total_bytes), tone: 'grey' },
    ] },
    { label: 'App', value: gigabytes(memory.app_bytes), tone: 'blue' },
    { label: 'Wired', value: gigabytes(memory.wired_bytes), tone: 'orange' },
    { label: 'Compressed', value: gigabytes(memory.compressed_bytes), tone: 'red' },
    { label: 'Free', value: gigabytes(memory.free_bytes), tone: 'grey' },
  ] : [];

  const cpuDetails = cpu ? [
    { label: 'System', value: `${Math.round(cpu.system_percent)}%`, tone: 'red' },
    { label: 'User', value: `${Math.round(cpu.user_percent)}%`, tone: 'blue' },
    { label: 'Idle', value: `${Math.round(cpu.idle_percent)}%`, tone: 'grey' },
  ] : [];
  const coreLoads = Array.isArray(data.cpu_cores_percent) ? data.cpu_cores_percent.filter(value => typeof value === 'number' && Number.isFinite(value)) : [];
  const topology = data.cpu_topology || null;
  const efficiencyCount = topology && Number.isInteger(topology.efficiency_cores) ? topology.efficiency_cores : 0;
  const performanceCount = topology && Number.isInteger(topology.performance_cores) ? topology.performance_cores : 0;
  // Efficiency cores come first in the per-core list, so the two groups can be told apart when the counts add up.
  const splitCores = efficiencyCount > 0 && performanceCount > 0 && efficiencyCount + performanceCount === coreLoads.length;
  const average = values => values.reduce((total, value) => total + value, 0) / values.length;
  if (splitCores) {
    cpuDetails.push({ label: 'Efficiency cores', value: `${Math.round(average(coreLoads.slice(0, efficiencyCount)))}%`, tone: 'teal' });
    cpuDetails.push({ label: 'Performance cores', value: `${Math.round(average(coreLoads.slice(efficiencyCount)))}%`, tone: 'violet' });
  }
  if (typeof data.uptime_seconds === 'number') cpuDetails.push({ label: 'Uptime', value: officekitFormatUptime(data.uptime_seconds) });
  const hardware = data.hardware || null;
  const ghz = mhz => (typeof mhz === 'number' && Number.isFinite(mhz) && mhz > 0 ? `${(mhz / 1000).toFixed(2)} GHz` : null);
  const frequency = hardware?.cpu_frequency_mhz || null;
  const frequencyRows = frequency ? [['All cores', frequency.all], ['Efficiency cores', frequency.efficiency], ['Performance cores', frequency.performance]]
    .filter(([, mhz]) => ghz(mhz)).map(([label, mhz]) => ({ label, value: ghz(mhz) })) : [];
  if (frequencyRows.length) cpuDetails.push({ heading: 'Frequency' }, ...frequencyRows);
  const thermal = { nominal: 'Normal', fair: 'Fair', serious: 'Serious', critical: 'Critical' }[hardware?.thermal_state];
  if (topology || thermal) {
    cpuDetails.push({ heading: 'Chip' });
    if (topology) cpuDetails.push({ label: 'Model', value: topology.model });
    if (topology && splitCores) cpuDetails.push({ label: 'Cores', value: `${performanceCount} performance · ${efficiencyCount} efficiency` });
    if (thermal) cpuDetails.push({ label: 'Thermal state', value: thermal, tone: hardware.thermal_state === 'nominal' ? 'teal' : hardware.thermal_state === 'fair' ? 'orange' : 'red' });
  }
  if (Array.isArray(data.load_average) && data.load_average.length === 3) {
    cpuDetails.push({ heading: 'Average load' });
    ['1 minute', '5 minutes', '15 minutes'].forEach((label, index) => cpuDetails.push({ label, value: data.load_average[index].toFixed(2) }));
  }
  const cpuTemperature = officekitSensorTemperature(data.sensors, /tdie|cpu/i);
  const cpuRings = [];
  if (cpuTemperature !== null) cpuRings.push({ label: `${Math.round(cpuTemperature)}°`, percent: Math.min(100, cpuTemperature), tone: 'orange', title: 'Temp' });
  cpuRings.push({ label: whole(data.cpu_percent), percent: Math.min(100, data.cpu_percent ?? 0), tone: 'blue' });
  if (Array.isArray(data.load_average) && typeof data.load_average[0] === 'number' && coreLoads.length) {
    const load = data.load_average[0];
    cpuRings.push({ label: load.toFixed(2), percent: Math.min(100, load / coreLoads.length * 100), tone: 'teal', title: 'Load' });
  }
  const cpuCores = coreLoads.map((percent, index) => ({ percent, ...(splitCores ? { tone: index < efficiencyCount ? 'teal' : 'violet' } : {}) }));

  const diskSummary = disk ? [
    { label: 'Write', value: fullRate(disk.write_bytes_per_second), tone: 'red' },
    { label: 'Read', value: fullRate(disk.read_bytes_per_second), tone: 'blue' },
  ] : [];
  const diskUsed = disk && disk.total_bytes > 0 && typeof disk.used_bytes === 'number' ? share(disk.used_bytes, disk.total_bytes) : null;
  const diskGb = bytes => `${(bytes / OFFICEKIT_GIGABYTE).toFixed(1)} GB`;
  const diskDetails = diskUsed === null ? [] : [
    { bar: [{ percent: diskUsed, tone: 'blue' }, { percent: 100 - diskUsed, tone: 'grey' }] },
    { label: 'Used', value: diskGb(disk.used_bytes) },
    { label: 'Free', value: diskGb(Math.max(0, disk.total_bytes - disk.used_bytes)) },
    { label: 'Total', value: diskGb(disk.total_bytes) },
    ...diskSummary,
  ];
  const diskRings = typeof data.storage_percent === 'number' ? [{ label: whole(data.storage_percent), percent: Math.min(100, data.storage_percent), tone: 'blue' }] : [];
  if (disk && typeof disk.read_total_bytes === 'number' && typeof disk.write_total_bytes === 'number') {
    diskDetails.push({ heading: 'Since start-up' }, { label: 'Read', value: officekitFormatSize(disk.read_total_bytes) }, { label: 'Written', value: officekitFormatSize(disk.write_total_bytes) });
  }
  if (Array.isArray(disk?.volumes) && disk.volumes.length > 1) {
    diskDetails.push({ heading: 'Volumes' }, ...disk.volumes.map(volume => ({ label: volume.name, value: `${officekitFormatSize(volume.used_bytes)} of ${officekitFormatSize(volume.total_bytes)}` })));
  }

  const power = hardware?.power_w || null;
  const watts = value => (typeof value === 'number' && Number.isFinite(value) && value > 0 ? `${value.toFixed(1)} W` : null);
  const gpu = data.gpu || null;
  const gpuTemperature = officekitSensorTemperature(data.sensors, /gpu/i);
  const gpuRings = [];
  if (gpuTemperature !== null) gpuRings.push({ label: `${Math.round(gpuTemperature)}°`, percent: Math.min(100, gpuTemperature), tone: 'orange', title: 'Temp' });
  if (gpu) {
    gpuRings.push({ label: whole(gpu.utilization_percent), percent: Math.min(100, gpu.utilization_percent ?? 0), tone: 'blue' });
    if (typeof gpu.renderer_percent === 'number') gpuRings.push({ label: whole(gpu.renderer_percent), percent: gpu.renderer_percent, tone: 'teal', title: 'Render' });
  }
  const gpuDetails = [];
  if (gpu?.model) gpuDetails.push({ label: 'Model', value: gpu.model });
  if (gpu?.core_count) gpuDetails.push({ label: 'Cores', value: String(gpu.core_count) });
  if (watts(power?.gpu)) gpuDetails.push({ label: 'Power', value: watts(power.gpu) });
  if (gpu) gpuDetails.push({ heading: 'Utilization' }, { label: 'Device', value: whole(gpu.utilization_percent) }, { label: 'Renderer', value: whole(gpu.renderer_percent) }, { label: 'Tiler', value: whole(gpu.tiler_percent) });

  const sensorRows = [['CPU', /tdie|cpu/i], ['GPU', /gpu/i], ['Storage', /nand|ssd/i], ['Battery', /battery|gauge/i]]
    .map(([label, pattern]) => [label, officekitSensorTemperature(data.sensors, pattern)]).filter(([, value]) => value !== null)
    .map(([label, value]) => ({ label, value: `${Math.round(value)}°C` }));
  const fans = (Array.isArray(hardware?.fans) ? hardware.fans : []).filter(fan => fan && typeof fan.name === 'string' && Number.isFinite(fan.rpm));
  const powerRows = [['System', power?.system], ['CPU', power?.cpu], ['GPU', power?.gpu]].filter(([, value]) => watts(value)).map(([label, value]) => ({ label, value: watts(value) }));
  const sensorDetails = [
    ...(sensorRows.length ? [{ heading: 'Temperatures' }, ...sensorRows] : []),
    ...(fans.length ? [{ heading: 'Fans' }, ...fans.map(fan => ({ label: fan.name, value: `${Math.round(fan.rpm)} RPM` }))] : []),
    ...(powerRows.length ? [{ heading: 'Power' }, ...powerRows] : []),
  ];
  const sensorsBar = cpuTemperature !== null ? `${Math.round(cpuTemperature)}°` : fans.length ? `${Math.round(fans[0].rpm)} RPM` : watts(power?.system) || '—';

  const devices = (Array.isArray(data.bluetooth) ? data.bluetooth : []).filter(device => device && typeof device.name === 'string' && Number.isFinite(device.percent));
  const lowest = devices.length ? Math.min(...devices.map(device => device.percent)) : null;

  const network = data.network || null;
  const networkScale = 12.5 * 1024 * 1024;
  const rateRing = (value, title, tone) => ({ label: compactRate(value), percent: typeof value === 'number' ? Math.min(100, value / networkScale * 100) : 0, tone, title });
  const networkDetails = network ? [
    { label: 'Interface', value: network.interface },
    ...(network.local_address ? [{ label: 'Local address', value: network.local_address }] : []),
    { heading: 'Since start-up' },
    { label: 'Received', value: officekitFormatSize(network.received_total_bytes) },
    { label: 'Sent', value: officekitFormatSize(network.sent_total_bytes) },
  ] : [];

  const battery = data.battery && typeof data.battery.percent === 'number' ? data.battery : null;
  const batteryRings = battery ? [{ label: whole(battery.percent), percent: battery.percent, tone: 'teal', title: 'Level' }] : [];
  if (battery && typeof battery.health_percent === 'number') batteryRings.push({ label: whole(battery.health_percent), percent: battery.health_percent, tone: 'blue', title: 'Health' });
  const batteryDetails = battery ? [
    { label: 'Power source', value: battery.power_source === 'ac' ? 'Power adapter' : battery.power_source === 'battery' ? 'Battery' : 'Unavailable' },
    ...(battery.time_remaining_seconds == null ? [] : [{ label: battery.state === 'charging' ? 'Time to full' : 'Time remaining', value: officekitFormatUptime(battery.time_remaining_seconds) }]),
    ...(battery.adapter_watts == null ? [] : [{ label: 'Adapter', value: `${Math.round(battery.adapter_watts)} W` }]),
    ...(battery.power_w == null ? [] : [{ label: 'Power now', value: `${Math.abs(battery.power_w).toFixed(1)} W` }]),
    ...(battery.voltage_v == null ? [] : [{ label: 'Voltage', value: `${battery.voltage_v.toFixed(2)} V` }]),
    ...(battery.current_a == null ? [] : [{ label: 'Current', value: `${Math.abs(battery.current_a).toFixed(2)} A` }]),
    ...(battery.temperature_c == null ? [] : [{ label: 'Temperature', value: `${battery.temperature_c.toFixed(1)}°C` }]),
    ...(battery.cycle_count == null ? [] : [{ label: 'Cycle count', value: String(battery.cycle_count) }]),
    ...(battery.condition ? [{ label: 'Condition', value: battery.condition }] : []),
  ] : [];

  return {
    drawers: [
      { id: 'cpu', bar: `CPU ${whole(data.cpu_percent)}`, heading: 'CPU', big: '', sub: `Updated ${time}`,
        rings: cpuRings, cores: cpuCores,
        historyTitle: 'Usage history', history: series('cpu'), details: cpuDetails,
        rowsTitle: groupApplications ? 'Top applications' : 'Top processes', rows: byCpu.map(p => row(p, `${p.cpu_percent.toFixed(0)}%`)) },
      ...(gpu ? [{ id: 'gpu', bar: `GPU ${whole(gpu.utilization_percent)}`, heading: 'GPU', big: '', sub: `Updated ${time}`,
        rings: gpuRings, historyTitle: 'Usage history', history: series('gpu'),
        details: [...gpuDetails, ...(!gpuAttributionAvailable ? [{ label: 'Per-app activity', value: 'Unavailable' }] : [])],
        ...(gpuAttributionAvailable ? { rowsTitle: 'Top applications by GPU', rows: byGpu.map(p => row(p, `${p.gpu_percent.toFixed(0)}%`)) } : {}) }] : []),
      ...(sensorDetails.length ? [{ id: 'sensors', bar: sensorsBar, heading: 'Sensors', big: '', sub: `Updated ${time}`, details: sensorDetails }] : []),
      { id: 'ram', bar: `RAM ${whole(data.memory_percent)}`, heading: 'Memory', big: '',
        sub: memory ? `${(memory.used_bytes / OFFICEKIT_GIGABYTE).toFixed(1)} of ${(memory.total_bytes / OFFICEKIT_GIGABYTE).toFixed(1)} GB used · Updated ${time}` : precise(data.memory_percent),
        rings: memoryRings, historyTitle: 'Usage history', history: series('memory'), details: memoryDetails,
        rowsTitle: groupApplications ? 'Top applications' : 'Top processes', rows: byMemory.map(p => row(p, p.memory_mb >= 1024 ? `${(p.memory_mb / 1024).toFixed(1)} GB` : `${p.memory_mb.toFixed(0)} MB`)) },
      { id: 'ssd', bar: `SSD ${precise(data.storage_percent)}`, heading: 'Disk', big: '', sub: `${String(data.volume_label || 'Storage').slice(0, 60)}${diskUsed === null ? '' : ` · ${diskGb(disk.used_bytes)} of ${diskGb(disk.total_bytes)} used`}`,
        rings: diskRings, historyTitle: 'Activity history', history: series('disk'), details: diskDetails, storage: true },
      // No Quit buttons here: network use is not tied to one killable process.
      { id: 'net', bar: `↑${compactRate(data.upload_bytes_per_second)} ↓${compactRate(data.download_bytes_per_second)}`, heading: 'Network', big: '', sub: `Updated ${time}`, settings: 'network',
        rings: [rateRing(data.download_bytes_per_second, 'Down', 'blue'), rateRing(data.upload_bytes_per_second, 'Up', 'orange')],
        details: networkDetails, historyTitle: 'Traffic history', history: series('network'),
        networkHealth: officekitMenuNetworkHealth, networkCheck: true, networkCheckBusy: officekitNetworkCheckBusy,
        networkCheckAuto: !officekitNetworkCheckBusy && Date.now() - officekitNetworkCheckedAt > OFFICEKIT_NETWORK_CHECK_MAX_AGE_MS },
      ...(battery ? [{ id: 'battery', bar: `Battery ${whole(battery.percent)}`, heading: 'Battery', big: '', sub: battery.state === 'unknown' ? 'Power state unavailable' : battery.state,
        rings: batteryRings, details: batteryDetails, historyTitle: 'Charge history', history: series('battery'), battery: true }] : []),
      ...(devices.length ? [{ id: 'bluetooth', bar: `BT ${lowest}%`, heading: 'Bluetooth', big: '', sub: 'Connected devices', settings: 'bluetooth',
        details: devices.slice(0, 8).map(device => ({ label: device.name, value: `${device.percent}%`, tone: device.percent <= 20 ? 'red' : device.percent <= 40 ? 'orange' : 'teal' })) }] : []),
    ],
  };
}

async function officekitUpdateDrawers(data) {
  const applications = { cpu: [], memory: [], gpu: [] };
  const activeSorts = [
    ['cpu', officekitMenuStats.cpu], ['memory', officekitMenuStats.ram], ['gpu', officekitMenuStats.gpu],
  ].filter(([, enabled]) => enabled).map(([sortBy]) => sortBy);
  const results = await Promise.all(activeSorts.map(async sortBy => {
    try {
      const response = await fetch(officekitApiUrl(`/api/system/processes?limit=100&sort_by=${sortBy}`));
      if (!response.ok) return [sortBy, []];
      const processData = await response.json();
      return [sortBy, processData.applications || []];
    } catch { return [sortBy, []]; }
  }));
  results.forEach(([sortBy, rows]) => { applications[sortBy] = rows; });
  officekitDrawerNames = new Map(Object.values(applications).flat().map(application => [application.pid, application.name || application.app_name || 'Application']));
  const built = officekitBuildDrawers(data, applications, { groupApplications: true });
  built.drawers = built.drawers.filter(drawer => {
    return officekitMenuStats[OFFICEKIT_DRAWER_STAT[drawer.id]] === true;
  });
  if (officekitMenuQuitFeedback) {
    const destinations = built.drawers.filter(drawer => drawer.rows?.some(row => row.pid === officekitMenuQuitFeedback.pid));
    if (destinations.length) destinations.forEach(drawer => { drawer.quitFeedback = officekitMenuQuitFeedback; });
    else officekitMenuQuitFeedback = null;
  }
  await tauriInvoke()('menu_drawers_update', { payload: JSON.stringify(built) });
}

async function officekitRefreshMenuDrawersAfterQuit() {
  if (officekitLatestMetrics) await officekitUpdateDrawers(officekitLatestMetrics);
  else await officekitRefreshQuickStats();
}

async function officekitRunMenuDrawerQuit(pid) {
  if (officekitMenuQuitBusy || !Number.isInteger(pid) || pid < 2) return;
  const name = officekitDrawerNames.get(pid) || `process ${pid}`;
  officekitMenuQuitBusy = true;
  officekitMenuQuitFeedback = { pid, state: 'working', message: `Closing ${name}…` };
  try {
    await officekitRefreshMenuDrawersAfterQuit();
    const response = await fetch(officekitApiUrl('/api/system/processes/terminate'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pid, force: false }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Could not quit ${name}.`);
    officekitMenuQuitFeedback = null;
    await officekitRefreshMenuDrawersAfterQuit();
  } catch (error) {
    officekitMenuQuitFeedback = { pid, state: 'error', message: (error.message || `Could not quit ${name}.`).slice(0, 120) };
    await officekitRefreshMenuDrawersAfterQuit();
  } finally {
    officekitMenuQuitBusy = false;
  }
}

async function officekitCancelMenuDrawerQuit(pid) {
  if (officekitMenuQuitFeedback?.pid === pid && !officekitMenuQuitBusy) officekitMenuQuitFeedback = null;
  await officekitRefreshMenuDrawersAfterQuit();
}

let officekitStatsTimer = null;
let officekitStatsRequest = false;
let officekitNetworkCheckBusy = false;
// Opening the Network drawer re-runs the check unless one finished in the last minute.
let officekitNetworkCheckedAt = 0;
const OFFICEKIT_NETWORK_CHECK_MAX_AGE_MS = 60 * 1000;
let officekitLatestMetrics = null;
let officekitMenuNetworkHealth = null;

function officekitNetworkHealthPresentation(result) {
  const connection = result.link_type === 'wifi' ? 'Wi-Fi' : result.link_type === 'wired' ? 'Wired' : 'Network';
  const routerHasVerdict = ['healthy', 'internet_slow', 'router_slow'].includes(result.status);
  const router = result.router_median_ms == null ? 'Not measured' : `${result.status === 'router_slow' ? 'Slow · ' : routerHasVerdict ? 'Fast · ' : ''}${result.router_median_ms} ms${result.router_loss_percent ? ` · ${result.router_loss_percent}% loss` : ''}`;
  const internet = result.internet_median_ms == null ? 'No reply' : `${result.internet_median_ms} ms${result.internet_loss_percent ? ` · ${result.internet_loss_percent}% loss` : ''}`;
  const tones = { healthy: 'teal', internet_slow: 'orange', router_slow: 'orange', offline: 'red', incomplete: 'grey', router_unmeasured: 'grey', no_route: 'grey' };
  return {
    headline: result.headline,
    detail: result.detail.slice(0, 120),
    tone: tones[result.status] || 'grey',
    routerTone: result.router_median_ms == null || !routerHasVerdict ? 'grey' : result.status === 'router_slow' ? 'orange' : 'teal',
    internetTone: ['internet_slow', 'offline'].includes(result.status) ? 'red' : result.internet_median_ms == null ? 'grey' : 'teal',
    connection: `${connection}${result.interface ? ` · ${result.interface}` : ''}`,
    router,
    internet,
    checked: new Date(result.checked_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
  };
}

function officekitNetworkHealthResponseIsValid(result) {
  const allowed = ['healthy', 'router_slow', 'internet_slow', 'offline', 'incomplete', 'router_unmeasured', 'no_route'];
  const bounded = (value, max) => value == null || (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max);
  return result && allowed.includes(result.status) && typeof result.headline === 'string' && result.headline.length <= 80 &&
    typeof result.detail === 'string' && result.detail.length <= 180 && ['wifi', 'wired', 'unknown'].includes(result.link_type) &&
    bounded(result.router_median_ms, 10000) && bounded(result.router_loss_percent, 100) && bounded(result.internet_median_ms, 10000) &&
    bounded(result.internet_loss_percent, 100) && (result.interface == null || (typeof result.interface === 'string' && result.interface.length <= 64)) &&
    typeof result.checked_at === 'string' && Number.isFinite(Date.parse(result.checked_at));
}

async function officekitPublishMenuDrawers() {
  if (!officekitMenuStats.network || !officekitLatestMetrics) return;
  try { await officekitUpdateDrawers(officekitLatestMetrics); } catch { /* Keep the existing menu drawer responsive. */ }
}

async function officekitRunMenuNetworkHealthCheck() {
  if (officekitNetworkCheckBusy) return;
  officekitNetworkCheckBusy = true;
  officekitMenuNetworkHealth = { headline: 'Network check in progress', detail: 'Measuring the gateway and internet response times.', tone: 'grey', routerTone: 'grey', internetTone: 'grey', connection: 'Checking…', router: 'Checking…', internet: 'Checking…', checked: '' };
  await officekitPublishMenuDrawers();
  try {
    const response = await fetch(officekitApiUrl('/api/network/health'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Network check is unavailable.');
    if (!officekitNetworkHealthResponseIsValid(result)) throw new Error('Network check returned an invalid result.');
    officekitMenuNetworkHealth = officekitNetworkHealthPresentation(result);
  } catch (error) {
    officekitMenuNetworkHealth = { headline: 'Network check unavailable', detail: (error.message || 'Try again when your network is available.').slice(0, 120), tone: 'red', routerTone: 'grey', internetTone: 'grey', connection: 'Unavailable', router: 'Unavailable', internet: 'Unavailable', checked: '' };
  } finally {
    officekitNetworkCheckBusy = false;
    officekitNetworkCheckedAt = Date.now();
    await officekitPublishMenuDrawers();
  }
}

async function officekitRefreshQuickStats() {
  if (officekitStatsRequest) return;
  const panel = document.getElementById('tab-quick-stats');
  const enabled = officekitMenuStatsAny();
  if (!panel) { clearTimeout(officekitStatsTimer); return; }
  const systemPanel = document.getElementById('tab-system');
  const onScreen = !panel.classList.contains('hidden') || (!!systemPanel && !systemPanel.classList.contains('hidden'));
  const needsFullStats = onScreen || enabled;
  const showing = needsFullStats;
  officekitStatsRequest = true;
  const status = document.getElementById('quick-stats-status');
  try {
    const response = await fetch(officekitApiUrl('/api/system/metrics'));
    if (!response.ok) throw new Error('System stats are unavailable. Try again.');
    const data = await response.json();
    officekitLatestMetrics = data;
    // Keep the menu-bar graph current without collecting optional sensors unless the stats page is open.
    if (!needsFullStats) { officekitRecordStatSample(data, Date.now()); return; }
    if (typeof window.__TAURI__?.core?.invoke === 'function') {
      try {
        const nativeSensors = await tauriInvoke()('system_sensor_metrics');
        if (Array.isArray(nativeSensors) && nativeSensors.length) data.sensors = nativeSensors;
      } catch { /* native HID temperatures are optional; keep the API readings */ }
      try {
        const hardware = await tauriInvoke()('system_hardware_metrics');
        if (hardware && typeof hardware === 'object') data.hardware = hardware;
      } catch { /* clock speed, power and fans are optional; the panels hide those rows */ }
    }
    officekitRecordStatSample(data, Date.now());
    await officekitShowStatCards(data);
    officekitOutcome.show(status, { state: 'info', text: `Snapshot ${new Date(data.captured_at).toLocaleTimeString()} · updates while visible` });
    if (enabled && typeof window.__TAURI__?.core?.invoke === 'function') {
      // The network rates live in their own drawer item, so the OfficeKit icon carries no text.
      await tauriInvoke()('tray_stats_update', { text: '' });
      await officekitUpdateDrawers(data);
    }
    if (!panel.classList.contains('hidden')) {
      const sortBy = document.getElementById('quick-processes-sort')?.value || 'cpu';
      officekitFetchProcesses(sortBy);
    }
  } catch (error) { officekitOutcome.show(status, { state: 'error', text: error.message || 'System stats are unavailable.' }); }
  finally {
    officekitStatsRequest = false;
    clearTimeout(officekitStatsTimer);
    officekitStatsTimer = setTimeout(officekitRefreshQuickStats, !showing ? OFFICEKIT_STAT_INTERVAL_MS : onScreen ? 2000 : 5000);
  }
}

/** Fills the in-app cards (System Stats page and System page) from one snapshot; does nothing when neither page is open. */
async function officekitShowStatCards(data) {
  const statsPage = document.getElementById('tab-quick-stats');
  const systemPage = document.getElementById('tab-system');
  const statsOpen = !!statsPage && !statsPage.classList.contains('hidden');
  const systemOpen = !!systemPage && !systemPage.classList.contains('hidden');
  if (!statsOpen && !systemOpen) return;
  let processes = [];
  try {
    const response = await fetch(officekitApiUrl('/api/system/processes?limit=100&sort_by=cpu'));
    if (response.ok) processes = (await response.json()).processes || [];
  } catch { /* the cards still show the headline numbers */ }
  const drawers = officekitBuildDrawers(data, processes).drawers;
  if (statsOpen) officekitRenderStatCards('quick-stat-cards', drawers);
  if (systemOpen) officekitRenderStatCards('system-stat-cards', drawers, ['cpu', 'ram']);
}

let officekitProcessData = [];
let officekitProcessLoading = false;

function officekitEscapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[c]);
}

async function officekitFetchProcesses(sortBy = 'cpu') {
  const status = document.getElementById('quick-processes-status');
  const tbody = document.getElementById('quick-processes-tbody');
  if (!tbody || officekitProcessLoading) return;
  officekitProcessLoading = true;
  if (status) officekitOutcome.show(status, { state: 'working', text: 'Updating running processes…' });
  try {
    const url = officekitApiUrl(`/api/system/processes?limit=50&sort_by=${encodeURIComponent(sortBy)}`);
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to read processes');
    }
    const data = await res.json();
    officekitProcessData = data.processes || [];
    officekitRenderProcessList();
    if (status) officekitOutcome.show(status, { state: 'info', text: `${data.total_count} total processes · sorted by ${sortBy.toUpperCase()} · ${new Date(data.captured_at).toLocaleTimeString()}` });
  } catch (error) {
    if (status) officekitOutcome.show(status, { state: 'error', text: error.message || 'Could not load processes.' });
    if (!officekitProcessData.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-rose-500">${officekitEscapeText(error.message || 'Could not load processes.')}</td></tr>`;
    }
  } finally {
    officekitProcessLoading = false;
  }
}

function officekitRenderProcessList() {
  const tbody = document.getElementById('quick-processes-tbody');
  const filterInput = document.getElementById('quick-processes-filter');
  if (!tbody) return;
  const filter = (filterInput?.value || '').toLowerCase().trim();

  const filtered = officekitProcessData.filter(p => {
    if (!filter) return true;
    return p.name.toLowerCase().includes(filter) || String(p.pid).includes(filter);
  });

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-slate-400">No processes match "${officekitEscapeText(filter)}"</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(p => {
    const cpuClass = p.cpu_percent > 50 ? 'text-rose-600 font-bold' : p.cpu_percent > 15 ? 'text-amber-600 font-semibold' : 'text-slate-700 dark:text-slate-300';
    const actionBtn = p.is_killable
      ? `<button type="button" class="btn btn-xs btn-outline border-rose-200 text-rose-600 hover:bg-rose-50 hover:border-rose-300 dark:border-rose-900/50 dark:hover:bg-rose-950/40" data-kill-pid="${p.pid}" data-kill-name="${officekitEscapeText(p.name)}">End Process</button>`
      : `<span class="text-[11px] text-slate-400 font-mono">Protected</span>`;

    return `
      <tr class="hover:bg-slate-50/60 dark:hover:bg-white/5 transition-colors">
        <td class="py-2.5 px-3 font-medium text-slate-900 dark:text-white flex items-center gap-2">
          <i class="fa-solid fa-cube text-slate-400 text-xs"></i>
          <span class="truncate max-w-[180px]" title="${officekitEscapeText(p.name)}">${officekitEscapeText(p.name)}</span>
        </td>
        <td class="py-2.5 px-3 font-mono text-slate-500 text-[11px]">${p.pid}</td>
        <td class="py-2.5 px-3 tabular-nums ${cpuClass}">${p.cpu_percent.toFixed(1)}%</td>
        <td class="py-2.5 px-3 tabular-nums text-slate-700 dark:text-slate-300">${p.memory_mb >= 1024 ? (p.memory_mb / 1024).toFixed(2) + ' GB' : p.memory_mb.toFixed(1) + ' MB'} <span class="text-[10px] text-slate-400">(${p.memory_percent.toFixed(1)}%)</span></td>
        <td class="py-2.5 px-3 text-slate-500 capitalize text-[11px]">${officekitEscapeText(p.status)}</td>
        <td class="py-2.5 px-3 text-right">${actionBtn}</td>
      </tr>
    `;
  }).join('');
}

async function officekitConfirmAndKillProcess(pid, name) {
  const confirmed = window.confirm(`End process "${name}" (PID: ${pid})?\n\nAny unsaved changes in that application may be lost.`);
  if (!confirmed) return;

  const status = document.getElementById('quick-processes-status');
  if (status) officekitOutcome.show(status, { state: 'working', text: `Terminating ${name} (PID ${pid})…` });

  try {
    const res = await fetch(officekitApiUrl('/api/system/processes/terminate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pid, force: false }),
    });
    const result = await res.json();
    if (!res.ok) {
      throw new Error(result.detail || `Failed to terminate ${name}`);
    }
    if (typeof showAppFeedbackToast === 'function') {
      showAppFeedbackToast(`Terminated ${name} (PID ${pid})`, 'success');
    }
    if (status) officekitOutcome.show(status, { state: 'success', text: result.message || `Successfully terminated ${name}.` });
    const sortBy = document.getElementById('quick-processes-sort')?.value || 'cpu';
    await officekitFetchProcesses(sortBy);
  } catch (error) {
    const msg = error.message || `Could not terminate process ${pid}.`;
    if (typeof showAppFeedbackToast === 'function') {
      showAppFeedbackToast(msg, 'error');
    }
    if (status) officekitOutcome.show(status, { state: 'error', text: msg });
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('click', event => {
    const killBtn = event.target.closest('[data-kill-pid]');
    if (killBtn) {
      const pid = parseInt(killBtn.dataset.killPid, 10);
      const name = killBtn.dataset.killName || `PID ${pid}`;
      if (pid) officekitConfirmAndKillProcess(pid, name);
    }
    if (event.target.closest('#quick-processes-refresh-btn')) {
      const sortBy = document.getElementById('quick-processes-sort')?.value || 'cpu';
      officekitFetchProcesses(sortBy);
    }
  });

  document.addEventListener('input', event => {
    if (event.target.id === 'quick-processes-filter') {
      officekitRenderProcessList();
    }
  });

  document.addEventListener('change', event => {
    if (event.target.id === 'quick-processes-sort') {
      officekitFetchProcesses(event.target.value);
    }
  });
}

function officekitPublishComputedResult(container,data,title,toolId,inputs={}){
  if(!container)return;
  const snapshot={toolId,title,inputs:JSON.parse(JSON.stringify(inputs)),result:JSON.parse(JSON.stringify(data))};
  const text=officekitResultSnapshotText(snapshot);
  officekitRegisterResultCapability(toolId,{snapshot,text});
  const actions=officekitMountResultActions(container,{toolId,title,text,formats:[{id:'txt',label:'Text report (.txt)',extension:'txt',mime:'text/plain;charset=utf-8',serialize:()=>text},{id:'json',label:'JSON data (.json)',extension:'json',mime:'application/json',serialize:()=>JSON.stringify(snapshot,null,2)}]});
  container.append(actions.element);
}
function officekitPublishTextResult(container,text,title,toolId,extension='txt',fileName=toolId){
  const capability={toolId,title,text,fileName,copyLabel:'Copy text',formats:[{id:extension,label:`${extension.toUpperCase()} file`,extension,mime:'text/plain;charset=utf-8',serialize:()=>text}]};
  officekitRegisterResultCapability(toolId,capability);const actions=officekitMountResultActions(container,capability);container.append(actions.element);
}
function officekitPublishBinaryResult(container,blob,fileName,title,copyImage=false,toolId=fileName){
  const text=`${title}\nOutput: ${fileName}\nSize: ${blob.size.toLocaleString()} bytes`;
  const actions=officekitMountResultActions(container,{toolId,title,text,copyLabel:copyImage?'Copy image':'Copy summary',copy:copyImage?async()=>{await officekitWriteScreenshotClipboardImage(blob);return{state:'copied'};}:undefined,download:()=>officekitDownloadResultBlob(blob,fileName)});container.append(actions.element);
}

function officekitArrangeScreenshotWorkbench() {
  const section=document.getElementById('tab-screenshot');
  const heading=section.querySelector('div');
  const actions=document.createElement('div');actions.className='ok-screenshot-actions';
  const copy=document.getElementById('screenshot-copy-button');copy.textContent='Copy image';
  const download=document.getElementById('screenshot-export-button');download.textContent='Download…';
  const format=document.getElementById('screenshot-export-format');format.setAttribute('aria-label','Image format');
  actions.append(copy,format,download);heading.append(actions);
  const frame=section.querySelector('.grid');frame.classList.add('ok-screenshot-frame');
  const tools=frame.querySelector('nav');tools.classList.add('ok-screenshot-tools');
  for(const [type,label] of [['select','Select V'],['arrow','Arrow A'],['freehand','Freehand P']]){const b=document.createElement('button');b.type='button';b.className='btn btn-ghost';b.dataset.screenshotTool=type;b.textContent=label;b.setAttribute('aria-pressed','false');tools.prepend(b);}
  const inspector=frame.querySelector('aside');inspector.id='screenshot-contextual-settings';inspector.className='ok-screenshot-context';
  const region=inspector.querySelector('fieldset');const precision=document.createElement('details');precision.className='ok-screenshot-precision';const summary=document.createElement('summary');summary.textContent='Precise region';precision.append(summary,region);
  inspector.replaceChildren();
  const textLabel=document.createElement('label');textLabel.textContent='Text';textLabel.dataset.annotationSettings='text';
  const text=document.createElement('input');text.className='input ';text.id='screenshot-annotation-text';text.maxLength=200;text.value='Note';textLabel.append(text);
  function control(id,label,type,value,min,max){const wrap=document.createElement('label');wrap.textContent=label;wrap.dataset.annotationSettings='text highlight rectangle circle arrow freehand';const input=document.createElement('input');input.className=type==='range'?'range range-primary':type==='checkbox'?'checkbox checkbox-primary':'input ';input.id=id;input.type=type;input.value=value;if(min)input.min=min;if(max)input.max=max;wrap.append(input);inspector.append(wrap);}
  inspector.append(textLabel);
  control('screenshot-mask-color','Main color','color','#d94b2d');control('screenshot-outer-color','Outer color','color','#ffffff');control('screenshot-stroke-width','Stroke width','number','3','1','32');control('screenshot-outer-width','Outer width','number','2','1','32');control('screenshot-font-size','Text size','number','24','8','96');
  inspector.querySelector('#screenshot-font-size').parentElement.dataset.annotationSettings='text';
  const blur=document.createElement('input');blur.id='screenshot-blur-radius';blur.type='hidden';blur.value='24';const blurValue=document.createElement('span');blurValue.id='screenshot-blur-value';blurValue.hidden=true;
  const deleteButton=document.createElement('button');deleteButton.type='button';deleteButton.className='btn btn-error';deleteButton.id='screenshot-delete-button';deleteButton.textContent='Delete selected';
  section.children[1].append(deleteButton);
  const objectList=document.createElement('select');objectList.className='select ';objectList.id='screenshot-object-list';objectList.setAttribute('aria-label','Select added annotation');section.children[1].append(objectList);
  inspector.append(precision,blur,blurValue);
  const status=document.createElement('p');status.id='screenshot-export-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const link=document.createElement('a');link.id='screenshot-download-link';link.className='hidden';link.download='';
  section.querySelector('[aria-label="Screenshot preview"]').append(status,link);
  officekitScreenshot.tool='select';
}

let officekitScreenshotRenderSequence=0;
async function officekitRenderScreenshotExact() {
  const state=officekitScreenshot;const original=state.original;if(!original||!state.bitmap)return;
  const sequence=++officekitScreenshotRenderSequence;const operations=JSON.parse(JSON.stringify(state.operations));
  let bitmap=state.bitmap,generated=false,output=null;
  let previewUrl=null;
  if(operations.length){
    officekitValidateScreenshotOperations(operations,state.bitmap.width,state.bitmap.height);output=await officekitEditScreenshot(original,operations,'png');
    if(typeof createImageBitmap==='function')bitmap=await createImageBitmap(output.blob);
    else{previewUrl=URL.createObjectURL(output.blob);bitmap=new Image();try{await new Promise((resolve,reject)=>{bitmap.onload=resolve;bitmap.onerror=()=>reject(Error('Could not decode the edited preview.'));bitmap.src=previewUrl;});}catch(error){URL.revokeObjectURL(previewUrl);throw error;}}
    generated=true;
  }
  if(sequence!==officekitScreenshotRenderSequence||original!==state.original){if(generated)bitmap.close?.();if(previewUrl)URL.revokeObjectURL(previewUrl);return;}
  const canvas=document.getElementById('screenshot-canvas');const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
  canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
  canvas.style.width='';canvas.style.height='';canvas.style.maxWidth='';canvas.style.maxHeight='';canvas.style.flex='';
  if(state.zoom!==1){const fit=canvas.getBoundingClientRect();canvas.style.width=`${fit.width*state.zoom}px`;canvas.style.height=`${fit.height*state.zoom}px`;canvas.style.maxWidth='none';canvas.style.maxHeight='none';canvas.style.flex='none';}
  state.width=bitmap.width;state.height=bitmap.height;state.lastExport=output;
  if(generated)bitmap.close?.();
  if(previewUrl)URL.revokeObjectURL(previewUrl);
  document.getElementById('screenshot-dimensions').textContent=`${state.width} × ${state.height} · ${operations.length} edit${operations.length===1?'':'s'}`;
  document.getElementById('screenshot-export-button').disabled=false;document.getElementById('screenshot-copy-button').disabled=false;
  document.getElementById('screenshot-undo-button').disabled=state.undo.length===0;document.getElementById('screenshot-redo-button').disabled=state.redo.length===0;
  officekitRefreshScreenshotObjectSelection();
}
