import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'assets/officekit-workspace.js'), 'utf8');

const GB = 1024 ** 3;

function load(storage = { setItem() { throw new Error('history must never be saved'); } }) {
  const context = vm.createContext({ window: {}, localStorage: storage, console, Math, Date, Number, String, Array, Object, JSON, Map, Set, Promise });
  const api = vm.runInContext(`${source}
;({ officekitBuildDrawers, officekitRecordStatSample, officekitResetStatHistory, officekitHistorySeries, officekitFormatUptime, OFFICEKIT_STAT_SAMPLES, OFFICEKIT_STAT_INTERVAL_MS, officekitStatHistory: () => officekitStatHistory })`, context);
  // Values built inside the VM context come from another realm; copy them out so deep equality compares plain data.
  const plain = value => JSON.parse(JSON.stringify(value));
  return {
    ...api,
    officekitBuildDrawers: (...args) => plain(api.officekitBuildDrawers(...args)),
    officekitHistorySeries: name => plain(api.officekitHistorySeries(name)),
    officekitStatHistory: () => plain(api.officekitStatHistory()),
  };
}

function snapshot(overrides = {}) {
  return {
    cpu_percent: 37.2,
    memory_percent: 86.9,
    storage_percent: 33.1,
    volume_label: 'Macintosh HD',
    upload_bytes_per_second: 40 * 1024,
    download_bytes_per_second: 512 * 1024,
    captured_at: '2026-10-22T16:50:27.000Z',
    memory: { total_bytes: 32 * GB, used_bytes: 26.89 * GB, app_bytes: 9.56 * GB, wired_bytes: 3.67 * GB, compressed_bytes: 13.66 * GB, free_bytes: 5.11 * GB },
    memory_pressure: 'warning',
    swap: { used_bytes: 5.34 * GB, total_bytes: 16 * GB, percent: 33.4 },
    cpu_breakdown: { user_percent: 18.4, system_percent: 12.1, idle_percent: 69.5 },
    load_average: [25.5, 25.98, 29.38],
    uptime_seconds: 11 * 86400 + 9 * 3600,
    disk: { used_bytes: 326.3 * GB, total_bytes: 994.7 * GB, read_bytes_per_second: 96.9 * 1024 * 1024, write_bytes_per_second: 2.6 * 1024 * 1024 },
    ...overrides,
  };
}

const processes = [
  { pid: 812, name: 'Google Chrome Helper', cpu_percent: 18, memory_bytes: 636 * 1024 * 1024, memory_mb: 636, is_killable: true },
  { pid: 1, name: 'launchd', cpu_percent: 1, memory_bytes: 10 * 1024 * 1024, memory_mb: 10, is_killable: false },
  { pid: 9, name: 'OfficeKit', cpu_percent: 2, memory_bytes: 1400 * 1024 * 1024, memory_mb: 1400, is_killable: false },
];

const byId = drawers => Object.fromEntries(drawers.map(drawer => [drawer.id, drawer]));

test('the memory drawer shows rings, pressure and swap, the usage history and the memory breakdown', () => {
  const api = load();
  api.officekitResetStatHistory();
  api.officekitRecordStatSample(snapshot());
  const drawers = byId(api.officekitBuildDrawers(snapshot(), processes).drawers);
  const ram = drawers.ram;
  assert.equal(ram.big, '');
  assert.match(ram.sub, /^26\.9 of 32\.0 GB used · Updated .+/, 'the memory drawer shows when it last updated, like CPU');
  assert.deepEqual(ram.rings.map(ring => [ring.title ?? 'usage', ring.label]), [['Pressure', 'Warning'], ['usage', '87%'], ['Swap', '5.3G']]);
  assert.deepEqual([ram.rings[0].tone, ram.rings[2].tone], ['orange', 'orange']);
  assert.equal(ram.rings[2].percent, 33.4);
  const noPressure = byId(api.officekitBuildDrawers(snapshot({ memory_pressure: null, swap: null }), processes).drawers).ram;
  assert.deepEqual(noPressure.rings.map(ring => ring.label), ['87%']);
  assert.equal(ram.historyTitle, 'Usage history');
  assert.deepEqual(ram.history, [86.9]);
  assert.deepEqual(ram.details.slice(0, 2), [{ label: 'Used', value: '26.9 GB' }, ram.details[1]]);
  assert.equal(ram.details[1].bar.length, 4);
  assert.equal(Math.round(ram.details[1].bar.reduce((sum, segment) => sum + segment.percent, 0)), 100);
  assert.deepEqual(ram.details.slice(2).map(line => [line.label, line.value]), [
    ['App', '9.6 GB'], ['Wired', '3.7 GB'], ['Compressed', '13.7 GB'], ['Free', '5.1 GB'],
  ]);
  assert.equal(ram.rowsTitle, 'Top processes');
  assert.equal(ram.rows.find(row => row.name === 'Google Chrome Helper').killable, true);
  assert.equal(ram.rows.find(row => row.name === 'OfficeKit').killable, false);
  assert.equal(ram.storage, undefined);
});

test('menu-bar resource drawers show application names, grouped helper detail and honest GPU availability', () => {
  const api = load();
  const applications = {
    cpu: [{ name: 'Browser', pid: 812, process_count: 3, process_names: ['Browser', 'Browser Helper', 'Browser GPU'], cpu_percent: 44, memory_bytes: 900 * 1024 ** 2, memory_mb: 900, is_killable: true }],
    memory: [{ name: 'Browser', pid: 812, process_count: 3, process_names: ['Browser', 'Browser Helper', 'Browser GPU'], cpu_percent: 44, memory_bytes: 900 * 1024 ** 2, memory_mb: 900, is_killable: true }],
    gpu: [],
  };
  const drawers = byId(api.officekitBuildDrawers(snapshot({ gpu: { utilization_percent: 23, renderer_percent: 18, tiler_percent: 5 } }), applications, { groupApplications: true }).drawers);

  assert.equal(drawers.cpu.rowsTitle, 'Top applications');
  assert.equal(drawers.cpu.rows[0].name, 'Browser');
  assert.equal(drawers.cpu.rows[0].detail, '3 processes · Browser, Browser Helper, Browser GPU');
  assert.equal(drawers.ram.rows[0].name, 'Browser');
  assert.equal(drawers.gpu.details.find(item => item.label === 'Per-app activity').value, 'Unavailable');
  assert.equal(drawers.gpu.rows, undefined);

  applications.gpu = [{ ...applications.cpu[0], gpu_percent: 37 }];
  const attributedGpu = byId(api.officekitBuildDrawers(snapshot({ gpu: { utilization_percent: 23, renderer_percent: 18, tiler_percent: 5 } }), applications, { groupApplications: true }).drawers).gpu;
  assert.equal(attributedGpu.rowsTitle, 'Top applications by GPU');
  assert.equal(attributedGpu.rows[0].name, 'Browser');
  assert.equal(attributedGpu.rows[0].value, '37%');
});

const sensors = [
  { name: 'PMU tdie1', current_c: 56 }, { name: 'PMU tdie2', current_c: 60 }, { name: 'gas gauge battery', current_c: 31 }, { name: 'NAND CH0 temp', current_c: 41 },
];
const coreSnapshot = (overrides = {}) => snapshot({
  cpu_cores_percent: [80, 76, 30, 12, 20, 9, 6, 4, 3, 2],
  cpu_topology: { model: 'Apple M3 Pro', performance_cores: 8, efficiency_cores: 2 },
  sensors,
  ...overrides,
});

test('the CPU drawer adds temperature and load rings, per-core bars, efficiency and performance averages and the chip', () => {
  const api = load();
  const cpu = byId(api.officekitBuildDrawers(coreSnapshot(), processes).drawers).cpu;
  assert.equal(cpu.big, '');
  assert.deepEqual(cpu.rings.map(ring => [ring.title ?? 'usage', ring.label]), [['Temp', '58°'], ['usage', '37%'], ['Load', '25.50']]);
  assert.equal(cpu.rings[2].percent, 100, 'the load ring is capped at full');
  assert.equal(cpu.cores.length, 10);
  assert.deepEqual(cpu.cores.slice(0, 3).map(core => core.tone), ['teal', 'teal', 'violet']);
  const lines = Object.fromEntries(cpu.details.filter(item => item.label).map(item => [item.label, item.value]));
  assert.equal(lines['Efficiency cores'], '78%');
  assert.equal(lines['Performance cores'], '11%');
  assert.equal(lines.Model, 'Apple M3 Pro');
  assert.equal(lines.Cores, '8 performance · 2 efficiency');
  assert.equal(cpu.rows.length, 3, 'up to eight processes are listed');
  assert.ok(cpu.details.length <= 40 && cpu.cores.length <= 64 && cpu.rings.length <= 3);
});

test('the CPU drawer leaves out what the Mac does not expose: no temperature ring, no tones when core counts do not add up', () => {
  const api = load();
  const cpu = byId(api.officekitBuildDrawers(coreSnapshot({ sensors: [], cpu_topology: { model: 'Intel Core i7', performance_cores: null, efficiency_cores: null } }), processes).drawers).cpu;
  assert.deepEqual(cpu.rings.map(ring => ring.title ?? 'usage'), ['usage', 'Load']);
  assert.ok(cpu.cores.every(core => core.tone === undefined));
  assert.ok(!cpu.details.some(item => /Efficiency|Performance|Cores/.test(item.label ?? '')));
  assert.ok(cpu.details.some(item => item.label === 'Model'));
  const wrongCount = byId(api.officekitBuildDrawers(coreSnapshot({ cpu_cores_percent: [1, 2, 3] }), processes).drawers).cpu;
  assert.ok(wrongCount.cores.every(core => core.tone === undefined));
});

test('the CPU drawer shows the split, uptime, average load and history; temperature and cores appear only when the Mac reports them', () => {
  const api = load();
  const cpu = byId(api.officekitBuildDrawers(snapshot(), processes).drawers).cpu;
  assert.deepEqual(cpu.details.slice(0, 3).map(line => [line.label, line.value]), [['System', '12%'], ['User', '18%'], ['Idle', '70%']]);
  assert.equal(cpu.details[3].label, 'Uptime');
  assert.equal(cpu.details[3].value, '11 days, 9 hours');
  assert.deepEqual(cpu.details.slice(4).map(item => item.heading ?? [item.label, item.value].join(' ')), [
    'Average load', '1 minute 25.50', '5 minutes 25.98', '15 minutes 29.38',
  ]);
  assert.deepEqual(cpu.rings.map(ring => ring.label), ['37%']);
  assert.deepEqual(cpu.cores, []);
  assert.ok(!JSON.stringify(cpu).match(/temperature|frequency|efficiency|performance/i));
});

test('the disk drawer shows throughput, used-of-total bar and the storage analyser action', () => {
  const api = load();
  const disk = byId(api.officekitBuildDrawers(snapshot(), processes).drawers).ssd;
  assert.equal(disk.big, '');
  assert.equal(disk.sub, 'Macintosh HD · 326.3 GB of 994.7 GB used');
  assert.deepEqual(disk.rings.map(ring => ring.label), ['33%']);
  assert.deepEqual(disk.details.slice(1).map(line => [line.label, line.value]), [
    ['Used', '326.3 GB'], ['Free', '668.4 GB'], ['Total', '994.7 GB'], ['Write', '2.6 MB/s'], ['Read', '96.9 MB/s'],
  ]);
  assert.equal(disk.historyTitle, 'Activity history');
  assert.equal(disk.storage, true);
});

test('the network drawer shows down and up rings and a traffic history; interface, address and totals appear only when read', () => {
  const api = load();
  const bare = byId(api.officekitBuildDrawers(snapshot(), processes).drawers).net;
  assert.deepEqual(bare.rings.map(ring => [ring.title, ring.label]), [['Down', '512K'], ['Up', '40K']]);
  assert.equal(bare.rows, undefined);
  assert.deepEqual(bare.details, []);
  const detailed = byId(api.officekitBuildDrawers(snapshot({ network: { interface: 'en0', local_address: '192.168.1.20', sent_total_bytes: 1024 ** 3 * 2, received_total_bytes: 1024 ** 2 * 5 } }), processes).drawers).net;
  assert.deepEqual(detailed.details.map(item => item.heading ?? `${item.label} ${item.value}`), ['Interface en0', 'Local address 192.168.1.20', 'Since start-up', 'Received 5.0 MB', 'Sent 2.0 GB']);
  assert.ok(!JSON.stringify(detailed).includes('public'), 'the public address is never read');
});

test('GPU, sensors and Bluetooth drawers show rings, power, fans and device batteries, and stay out when nothing is read', () => {
  const api = load();
  const hardware = { thermal_state: 'fair', cpu_frequency_mhz: { all: 1943, efficiency: 1736, performance: 1995 }, power_w: { cpu: null, gpu: 0.2, system: 29 }, fans: [{ name: 'Left fan', rpm: 1330 }] };
  const drawers = byId(api.officekitBuildDrawers(snapshot({
    gpu: { utilization_percent: 4, renderer_percent: 3, tiler_percent: 2, model: 'Apple M1 Max', core_count: 24 },
    sensors: [{ name: 'PMU tdie1', current_c: 50 }, { name: 'GPU MTR Temp Sensor1', current_c: 42 }],
    hardware, bluetooth: [{ name: 'Trackpad', percent: 92 }, { name: 'Mouse', percent: 15 }],
  }), processes).drawers);
  assert.deepEqual(drawers.gpu.rings.map(ring => ring.title ?? 'usage'), ['Temp', 'usage', 'Render']);
  assert.equal(drawers.gpu.big, '');
  const gpuLines = Object.fromEntries(drawers.gpu.details.filter(item => item.label).map(item => [item.label, item.value]));
  assert.deepEqual([gpuLines.Model, gpuLines.Cores, gpuLines.Power], ['Apple M1 Max', '24', '0.2 W']);
  const sensorLines = drawers.sensors.details.map(item => item.heading ?? `${item.label} ${item.value}`);
  assert.deepEqual(sensorLines, ['Temperatures', 'CPU 50°C', 'GPU 42°C', 'Fans', 'Left fan 1330 RPM', 'Power', 'System 29.0 W', 'GPU 0.2 W']);
  assert.equal(drawers.sensors.bar, '50°');
  assert.deepEqual(drawers.bluetooth.details.map(item => [item.label, item.value, item.tone]), [['Trackpad', '92%', 'teal'], ['Mouse', '15%', 'red']]);
  assert.equal(drawers.bluetooth.bar, 'BT 15%');
  const cpu = drawers.cpu.details.map(item => item.heading ?? `${item.label} ${item.value}`);
  assert.ok(cpu.includes('Frequency') && cpu.includes('All cores 1.94 GHz') && cpu.includes('Performance cores 2.00 GHz'));
  assert.ok(cpu.includes('Thermal state Fair'));
  const none = byId(api.officekitBuildDrawers(snapshot(), processes).drawers);
  assert.ok(!none.sensors && !none.bluetooth && !none.gpu);
});

test('the battery drawer needs a charge reading and shows adapter, power, voltage, temperature and cycles when read', () => {
  const api = load();
  const noBattery = byId(api.officekitBuildDrawers(snapshot({ battery: { percent: null, state: 'unknown', power_source: 'ac' } }), processes).drawers);
  assert.ok(!noBattery.battery, 'a desktop Mac without a battery has no battery panel');
  const battery = byId(api.officekitBuildDrawers(snapshot({ battery: {
    percent: 76, state: 'discharging', power_source: 'battery', health_percent: 92, cycle_count: 324, condition: 'Normal',
    time_remaining_seconds: 8100, adapter_watts: 96, power_w: -9.5, voltage_v: 12.1, current_a: -0.79, temperature_c: 30.5,
  } }), processes).drawers).battery;
  assert.deepEqual(battery.rings.map(ring => [ring.title, ring.label]), [['Level', '76%'], ['Health', '92%']]);
  const lines = Object.fromEntries(battery.details.map(item => [item.label, item.value]));
  assert.deepEqual([lines['Time remaining'], lines.Adapter, lines['Power now'], lines.Voltage, lines.Current, lines.Temperature, lines['Cycle count']], ['2 hours, 15 min', '96 W', '9.5 W', '12.10 V', '0.79 A', '30.5°C', '324']);
});

test('the disk drawer adds since-start-up totals and the volumes list', () => {
  const api = load();
  const base = snapshot();
  const disk = byId(api.officekitBuildDrawers(snapshot({ disk: { ...base.disk, read_total_bytes: 2 * 1024 ** 4, write_total_bytes: 1024 ** 3, volumes: [
    { name: 'Macintosh HD', used_bytes: 1024 ** 3, total_bytes: 2 * 1024 ** 3 }, { name: 'Backup', used_bytes: 1024 ** 2, total_bytes: 1024 ** 3 }] } }), processes).drawers).ssd;
  const text = disk.details.map(item => item.heading ?? `${item.label} ${item.value}`);
  assert.ok(text.includes('Since start-up') && text.includes('Read 2.0 TB') && text.includes('Written 1.0 GB'));
  assert.ok(text.includes('Volumes') && text.includes('Backup 1.0 MB of 1.0 GB'));
});

test('history keeps one point per ten seconds however often the stats are polled, and 180 points cover thirty minutes', () => {
  const api = load();
  api.officekitResetStatHistory();
  [1_000, 3_000, 5_000, 11_000, 13_000, 21_000].forEach((at, index) => api.officekitRecordStatSample(snapshot({ cpu_percent: index }), at));
  assert.deepEqual(api.officekitStatHistory().cpu, [0, 3, 5]);
  assert.equal(api.OFFICEKIT_STAT_INTERVAL_MS, 10000);
  assert.equal(api.OFFICEKIT_STAT_SAMPLES * api.OFFICEKIT_STAT_INTERVAL_MS, 30 * 60 * 1000);
});

test('every drawer stays within three buttons: the Activity Monitor link, its bottom button and the optional storage action', () => {
  const api = load();
  for (const drawer of api.officekitBuildDrawers(snapshot(), processes).drawers) {
    const buttons = 2 + (drawer.storage === true ? 1 : 0);
    assert.ok(buttons <= 3, `${drawer.id} shows ${buttons} buttons`);
  }
});

test('history is bounded in memory, never saved and cleared when sampling stops', () => {
  let saved = 0;
  const api = load({ setItem() { saved += 1; }, getItem() { return null; } });
  for (let index = 0; index < api.OFFICEKIT_STAT_SAMPLES + 25; index += 1) {
    api.officekitRecordStatSample(snapshot({ cpu_percent: index % 100 }));
  }
  assert.equal(api.officekitStatHistory().cpu.length, api.OFFICEKIT_STAT_SAMPLES);
  assert.equal(api.OFFICEKIT_STAT_SAMPLES, 180);
  assert.equal(api.officekitStatHistory().cpu.at(-1), (api.OFFICEKIT_STAT_SAMPLES + 24) % 100);
  api.officekitResetStatHistory();
  assert.equal(api.officekitStatHistory().cpu.length, 0);
  assert.equal(saved, 0);
});

test('missing detail fields leave their sections out instead of inventing numbers', () => {
  const api = load();
  const drawers = byId(api.officekitBuildDrawers({ captured_at: '2026-10-22T16:50:27.000Z', cpu_percent: null, memory_percent: null, storage_percent: null, upload_bytes_per_second: null, download_bytes_per_second: null }, []).drawers);
  assert.equal(drawers.cpu.details.length, 0);
  assert.equal(drawers.ram.details.length, 0);
  assert.equal(drawers.ram.rings.length, 1);
  assert.equal(drawers.ram.sub, '—');
  assert.equal(drawers.ssd.details.length, 0);
  assert.equal(drawers.ssd.rings.length, 0);
  assert.equal(drawers.ssd.summary, undefined);
});

test('uptime and rate history read cleanly', () => {
  const api = load();
  assert.equal(api.officekitFormatUptime(59), '0 min');
  assert.equal(api.officekitFormatUptime(3600 + 120), '1 hour, 2 min');
  assert.equal(api.officekitFormatUptime(86400), '1 day, 0 hours');
  api.officekitResetStatHistory();
  api.officekitRecordStatSample({ download_bytes_per_second: 100, upload_bytes_per_second: 300 });
  api.officekitRecordStatSample({ download_bytes_per_second: 50, upload_bytes_per_second: 50 });
  assert.deepEqual(api.officekitStatHistory().network, [400, 100]);
  assert.deepEqual(api.officekitHistorySeries('network'), [100, 25]);
  api.officekitRecordStatSample({ download_bytes_per_second: 'x', upload_bytes_per_second: 1 });
  assert.deepEqual(api.officekitStatHistory().network, [400, 100]);
});
