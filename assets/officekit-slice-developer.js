// Developer slice (D04, D10–D11, D15–D17). Keep this register() call first. List destinations one
// `id: { tab: '…', … },` line each: tests/ui-search-routing.test.mjs parses them against the live catalogue.
window.OfficeKitExtensions.register({
  slice: 'developer',
  destinations: {
    json_compare: { tab: 'developer', sliceView: 'compare-json' },
    text_diff: { tab: 'developer', sliceView: 'compare-text' },
    uuid_generator: { tab: 'developer', sliceView: 'uuid' },
    qr_generator: { tab: 'developer', sliceView: 'qr' },
    text_metrics: { tab: 'converter', converterMode: 'developer_tools', developerOperation: 'text_metrics', focusId: 'developer-tools-input' },
    text_case: { tab: 'converter', converterMode: 'developer_tools', developerOperation: 'text_case', focusId: 'developer-tools-input' },
    timestamp_converter: { tab: 'converter', converterMode: 'developer_tools', developerOperation: 'timestamp_convert', focusId: 'developer-tools-input' },
  },
  tabs: ['developer'],
  openView: view => window.OfficeKitDeveloperSlice?.openView(view),
});

// Developer slice logic. Every dynamic value reaches the DOM through textContent or
// setAttribute (P-011); the server never sends markup and the UI never builds HTML strings.
(function developerSlice(win) {
  'use strict';

  const LIMITS = Object.freeze({ text: 1048576, uuidBatch: 1000, uuidName: 1024, zones: 8, qrPayload: 2953, qrSizeMin: 128, qrSizeMax: 2048, compactWidth: 600 });
  const QR_CAPACITY = Object.freeze({ L: 2953, M: 2331, Q: 1663, H: 1273 });
  const PATHS = Object.freeze({
    jsonDiff: '/api/developer/json-diffs',
    textDiff: '/api/developer/text-diffs',
    textCase: '/api/developer/text-case-conversions',
    textAnalysis: '/api/developer/text-analyses',
    timestamp: '/api/developer/timestamp-conversions',
    timeZones: '/api/developer/time-zones',
    uuids: '/api/developer/uuids',
    qr: '/api/developer/qr-codes',
  });
  const MESSAGES = Object.freeze({
    json: 'JSON comparison input is invalid or exceeds supported limits.',
    jsonOriginal: 'Original: JSON comparison input is invalid or exceeds supported limits.',
    jsonChanged: 'Changed: JSON comparison input is invalid or exceeds supported limits.',
    text: 'Text comparison input is invalid, too different, or exceeds supported limits.',
    textInput: 'Text input is invalid or exceeds supported limits.',
    timestamp: 'Timestamp input is invalid, ambiguous or out of range.',
    uuid: 'UUID request is invalid or exceeds the batch limit.',
    qr: 'QR payload is empty, invalid or too long for this error-correction level.',
    empty: 'Enter text to process.',
    gap: 'That local time does not exist in the chosen zone. Nothing is shifted automatically.',
    zones: 'Choose up to eight target zones.',
    tooLarge: 'Input is too large for this operation.',
    network: 'OfficeKit could not reach its local service. Restart OfficeKit and try again.',
    invalidResponse: 'OfficeKit returned an invalid response.',
    copied: 'Copied to the clipboard.',
    copyDenied: 'Copy was denied. Select the text to copy it manually.',
    compared: 'Comparison complete. Nothing is saved.',
  });
  const TIMESTAMP_INPUTS = Object.freeze(['unix_seconds', 'unix_milliseconds', 'unix_microseconds', 'iso_8601', 'local_datetime']);
  const CASE_STYLES = Object.freeze(['lower', 'upper', 'title', 'sentence', 'camel', 'pascal', 'snake', 'kebab', 'constant']);
  const CASE_LOCALES = Object.freeze(['root', 'tr', 'az']);
  const UUID_NAMESPACES = Object.freeze(['dns', 'url', 'oid', 'x500']);
  const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;
  const SLICE_OPERATIONS = new Set(['text_metrics', 'text_case', 'timestamp_convert']);

  // ---- pure helpers -------------------------------------------------------

  const codePointLength = text => Array.from(text).length;
  const utf8Length = text => new TextEncoder().encode(text).length;

  function oneOf(value, allowed, message) {
    if (!allowed.includes(value)) throw new Error(message);
    return value;
  }

  function requireText(value, limit, message) {
    // The contract limit is UTF-8 bytes (ARCH-2, PM-6): the same unit the server enforces.
    if (typeof value !== 'string' || utf8Length(value) > limit) throw new Error(message);
    return value;
  }

  // The side is named when its text is not JSON, so the user knows which input to fix (UX-13).
  function requireJson(value, message, fieldId) {
    requireText(value, LIMITS.text, message);
    try { JSON.parse(value); } catch {
      const error = new Error(message);
      error.inputError = true;
      error.validationField = fieldId;
      error.validationMessage = 'This JSON is incomplete or invalid. Check its property names, commas and brackets, then compare again.';
      throw error;
    }
    return value;
  }

  function jsonDiffRequest({ original, changed, arrayOrder = 'ordered', numeric = 'value' } = {}) {
    return {
      path: PATHS.jsonDiff,
      body: {
        original: requireJson(original, MESSAGES.jsonOriginal, 'developer-compare-original'),
        changed: requireJson(changed, MESSAGES.jsonChanged, 'developer-compare-changed'),
        array_order: oneOf(arrayOrder, ['ordered', 'unordered'], MESSAGES.json),
        numeric: oneOf(numeric, ['value', 'lexical'], MESSAGES.json),
      },
    };
  }

  function textDiffRequest({ original, changed, whitespace = 'exact', lineEndings = 'normalize', unicodeNfc = false } = {}) {
    return {
      path: PATHS.textDiff,
      body: {
        original: requireText(original, LIMITS.text, MESSAGES.text),
        changed: requireText(changed, LIMITS.text, MESSAGES.text),
        whitespace: oneOf(whitespace, ['exact', 'ignore_trailing', 'ignore_all'], MESSAGES.text),
        line_endings: oneOf(lineEndings, ['normalize', 'exact'], MESSAGES.text),
        unicode_nfc: Boolean(unicodeNfc),
      },
    };
  }

  function textCaseRequest({ text, style, locale = 'root' } = {}) {
    return {
      path: PATHS.textCase,
      body: {
        text: requireText(text, LIMITS.text, MESSAGES.textInput),
        style: oneOf(style, CASE_STYLES, MESSAGES.textInput),
        locale: oneOf(locale, CASE_LOCALES, MESSAGES.textInput),
      },
    };
  }

  function textAnalysisRequest(text) {
    if (text === '') throw new Error(MESSAGES.empty);
    return { path: PATHS.textAnalysis, body: { text: requireText(text, LIMITS.text, MESSAGES.textInput) } };
  }

  function timestampRequest({ value, inputType, sourceZone = '', fold = 'reject', targetZones = [] } = {}) {
    const trimmed = typeof value === 'string' ? value.trim() : '';
    if (trimmed === '' || codePointLength(trimmed) > 64) throw new Error(MESSAGES.timestamp);
    const zones = [...new Set((Array.isArray(targetZones) ? targetZones : []).map(zone => String(zone).trim()).filter(Boolean))];
    if (zones.length < 1 || zones.length > LIMITS.zones) throw new Error(MESSAGES.timestamp);
    const body = { value: trimmed, input_type: oneOf(inputType, TIMESTAMP_INPUTS, MESSAGES.timestamp), target_zones: zones };
    if (inputType === 'local_datetime') {
      const zone = String(sourceZone).trim();
      if (zone === '') throw new Error(MESSAGES.timestamp);
      body.source_zone = zone;
      body.fold = oneOf(fold, ['reject', 'earlier', 'later'], MESSAGES.timestamp);
    }
    return { path: PATHS.timestamp, body };
  }

  function uuidRequest({ version, count = 1, namespace, name, letters = 'lower', style = 'canonical' } = {}) {
    const caseValue = oneOf(letters, ['lower', 'upper'], MESSAGES.uuid);
    const styleValue = oneOf(style, ['canonical', 'braces', 'urn', 'compact'], MESSAGES.uuid);
    if (!Number.isInteger(count) || count < 1 || count > LIMITS.uuidBatch) throw new Error(MESSAGES.uuid);
    if (version === 5) {
      if (count !== 1) throw new Error(MESSAGES.uuid);
      const ns = typeof namespace === 'string' ? namespace.trim().toLowerCase() : '';
      if (!UUID_NAMESPACES.includes(ns) && !UUID_PATTERN.test(ns)) throw new Error(MESSAGES.uuid);
      if (typeof name !== 'string' || name === '' || utf8Length(name) > LIMITS.uuidName) throw new Error(MESSAGES.uuid);
      return { path: PATHS.uuids, body: { version: 5, count: 1, namespace: ns, name, case: caseValue, style: styleValue } };
    }
    oneOf(version, [4, 7], MESSAGES.uuid);
    return { path: PATHS.uuids, body: { version, count, case: caseValue, style: styleValue } };
  }

  function qrRequest({ payload, errorCorrection = 'M', sizePx = 512, format = 'png' } = {}) {
    if (typeof payload !== 'string' || payload === '' || codePointLength(payload) > LIMITS.qrPayload) throw new Error(MESSAGES.qr);
    const ecc = oneOf(errorCorrection, ['L', 'M', 'Q', 'H'], MESSAGES.qr);
    if (utf8Length(payload) > QR_CAPACITY[ecc]) throw new Error(MESSAGES.qr);
    if (!Number.isInteger(sizePx) || sizePx < LIMITS.qrSizeMin || sizePx > LIMITS.qrSizeMax) throw new Error(MESSAGES.qr);
    return {
      path: PATHS.qr,
      body: { payload, error_correction: ecc, size_px: sizePx, format: oneOf(format, ['png', 'svg'], MESSAGES.qr) },
    };
  }

  function qrCapacity(payload, errorCorrection) {
    const limit = QR_CAPACITY[errorCorrection] || QR_CAPACITY.M;
    return { used: utf8Length(payload), limit };
  }

  function expectObject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(MESSAGES.invalidResponse);
    return value;
  }

  function parseJsonDiffResponse(data) {
    const body = expectObject(data);
    if (typeof body.equal !== 'boolean' || !Array.isArray(body.changes) || typeof body.truncated !== 'boolean') throw new Error(MESSAGES.invalidResponse);
    expectObject(body.counts);
    return body;
  }

  function parseTextDiffResponse(data) {
    const body = expectObject(data);
    if (typeof body.equal !== 'boolean' || !Array.isArray(body.rows) || typeof body.patch !== 'string') throw new Error(MESSAGES.invalidResponse);
    expectObject(body.stats);
    return body;
  }

  function parseQrResponse(data) {
    const body = expectObject(data);
    if (typeof body.data !== 'string' || (body.format === 'png' && !BASE64_PATTERN.test(body.data))) throw new Error(MESSAGES.invalidResponse);
    if (body.format !== 'png' && body.format !== 'svg') throw new Error(MESSAGES.invalidResponse);
    return body;
  }

  function parseUuidResponse(data) {
    const body = expectObject(data);
    if (!Array.isArray(body.uuids) || !body.uuids.every(item => typeof item === 'string')) throw new Error(MESSAGES.invalidResponse);
    return body;
  }

  function uuidExport(uuids, kind) {
    if (kind === 'csv') return ['uuid', ...uuids].join('\n') + '\n';
    return uuids.join('\n') + '\n';
  }

  function analysisLines(data) {
    const body = expectObject(data);
    return [
      `Graphemes: ${body.graphemes}`,
      `Code points: ${body.code_points}`,
      `UTF-8 bytes: ${body.utf8_bytes}`,
      `UTF-16 units: ${body.utf16_units}`,
      `Words: ${body.words}`,
      `Lines: ${body.lines}`,
      `Blank lines: ${body.blank_lines}`,
      `Whitespace characters: ${body.whitespace}`,
      `Longest line (graphemes): ${body.longest_line_graphemes}`,
    ].join('\n');
  }

  function timestampLines(data) {
    const body = expectObject(data);
    const lines = [
      `Instant (UTC): ${body.instant_utc}`,
      `Unix seconds: ${body.unix_seconds}`,
      `Unix milliseconds: ${body.unix_milliseconds}`,
      `Unix microseconds: ${body.unix_microseconds}`,
    ];
    for (const zone of body.conversions) {
      lines.push(`${zone.zone}: ${zone.local_iso} ${zone.abbreviation} (${zone.offset})${zone.is_dst ? ' daylight saving' : ''}, ${zone.weekday}`);
    }
    for (const warning of body.warnings || []) lines.push(`Warning: ${warning}`);
    return lines.join('\n');
  }

  // ---- DOM helpers (textContent and setAttribute only) -------------------

  const doc = () => win.document;
  const byId = id => doc().getElementById(id);

  function el(tag, props = {}, ...children) {
    const node = doc().createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'text') node.textContent = String(value);
      else if (key === 'className') node.className = String(value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat()) {
      if (child === undefined || child === null || child === false) continue;
      node.append(typeof child === 'object' ? child : doc().createTextNode(String(child)));
    }
    return node;
  }

  function setStatus(node, message, isError = false) {
    if (!node) return;
    node.className = isError ? 'ok-action-dock__status ok-dev-error' : 'ok-action-dock__status';
    node.textContent = message;
  }

  function toast(message, state) {
    if (typeof win.showAppFeedbackToast === 'function') win.showAppFeedbackToast(message, state);
  }

  function spanNodes(text, spans, markClass) {
    if (!Array.isArray(spans) || spans.length === 0) return [text];
    const chars = Array.from(text);
    const out = [];
    let cursor = 0;
    for (const span of spans) {
      const start = Math.max(cursor, Math.min(span.start, chars.length));
      const end = Math.max(start, Math.min(span.end, chars.length));
      if (start > cursor) out.push(chars.slice(cursor, start).join(''));
      if (end > start) out.push(el('mark', { className: markClass, text: chars.slice(start, end).join('') }));
      cursor = end;
    }
    if (cursor < chars.length) out.push(chars.slice(cursor).join(''));
    return out;
  }

  // One table row per change: Path, Change (badge) and Original → Changed.
  function jsonChangeNodes(data) {
    const kind = { added: ['ok-dev-badge-add', 'added'], removed: ['ok-dev-badge-rem', 'removed'], changed: ['ok-dev-badge-chg', 'changed'], type_changed: ['ok-dev-badge-type', 'type changed'] };
    const missing = value => value === null || value === undefined;
    return data.changes.map(change => {
      const [badgeClass, badgeText] = kind[change.kind] || ['ok-dev-badge-chg', 'changed'];
      const before = missing(change.before) ? '' : change.before;
      const after = missing(change.after) ? '(missing)' : change.after;
      return el('tr', {},
        el('td', { className: 'font-mono break-all', text: change.path === '' ? '(root)' : change.path }),
        el('td', {}, el('span', { className: `ok-dev-badge ${badgeClass}`, text: badgeText })),
        el('td', { className: 'font-mono break-all', text: `${before} → ${after}`.trim() }));
    });
  }

  function textRowNodes(rows, layout) {
    if (layout === 'unified') {
      const lines = [];
      for (const row of rows) {
        if (row.op === 'equal') lines.push(el('div', { className: 'whitespace-pre-wrap font-mono text-xs', text: ` ${row.left ?? ''}` }));
        if (row.op === 'delete' || row.op === 'change') lines.push(el('div', { className: 'whitespace-pre-wrap font-mono text-xs ok-dev-error', text: `-${row.left ?? ''}` }));
        if (row.op === 'insert' || row.op === 'change') lines.push(el('div', { className: 'whitespace-pre-wrap font-mono text-xs ok-dev-success', text: `+${row.right ?? ''}` }));
      }
      return lines;
    }
    return rows.map(row => el('div', { role: 'row', className: 'grid grid-cols-[3rem_1fr_3rem_1fr] gap-2 border-b ok-dev-line py-1 text-xs' },
      el('span', { className: 'text-right ok-dev-muted', text: row.left_no ?? '' }),
      el('div', { className: 'whitespace-pre-wrap break-all font-mono' + (row.op === 'delete' || row.op === 'change' ? ' ok-dev-del' : '') },
        spanNodes(row.left ?? '', row.left_spans, 'ok-dev-mark-del ')),
      el('span', { className: 'text-right ok-dev-muted', text: row.right_no ?? '' }),
      el('div', { className: 'whitespace-pre-wrap break-all font-mono' + (row.op === 'insert' || row.op === 'change' ? ' ok-dev-ins' : '') },
        spanNodes(row.right ?? '', row.right_spans, 'ok-dev-mark-ins '))));
  }

  // ---- transport ----------------------------------------------------------

  async function postJson(path, body, errorMessage, fetchImpl = win.fetch) {
    let response;
    try {
      response = await fetchImpl(win.officekitApiUrl(path), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store',
      });
    } catch {
      throw new Error(MESSAGES.network);
    }
    if (response.status === 413) throw new Error(MESSAGES.tooLarge);
    if (!response.ok) throw new Error(errorMessage);
    try {
      return await response.json();
    } catch {
      throw new Error(MESSAGES.invalidResponse);
    }
  }

  async function getJson(path, fetchImpl = win.fetch) {
    const response = await fetchImpl(win.officekitApiUrl(path), { cache: 'no-store' });
    if (!response.ok) throw new Error(MESSAGES.invalidResponse);
    return response.json();
  }

  async function copyText(text, statusNode) {
    try {
      if (!win.navigator?.clipboard?.writeText) throw new Error('Clipboard access is unavailable.');
      await win.navigator.clipboard.writeText(text);
      setStatus(statusNode, MESSAGES.copied);
      toast(MESSAGES.copied, 'success');
    } catch {
      setStatus(statusNode, MESSAGES.copyDenied, true);
      toast(MESSAGES.copyDenied, 'error');
    }
  }

  function saveBlob(content, type, filename) {
    const url = win.URL.createObjectURL(new win.Blob([content], { type }));
    const link = doc().createElement('a');
    link.href = url;
    link.download = filename;
    // Browsers need the anchor in the document before click() starts the download (CR-9).
    doc().body.append(link);
    link.click();
    link.remove();
    win.setTimeout(() => win.URL.revokeObjectURL(url), 30_000);
  }

  // ---- developer select integration (text metrics, change case, timestamp) --

  const fieldState = { zonesLoaded: false };

  function ensureFields() {
    const host = byId('developer-slice-fields');
    if (!host || host.dataset.ready === 'true') return host;
    host.dataset.ready = 'true';
    host.append(
      el('div', { id: 'developer-slice-case-fields', className: 'grid gap-4 md:grid-cols-2', hidden: true },
        el('div', {}, el('label', { for: 'developer-slice-case-style', className: 'block text-sm font-semibold ok-dev-text', text: 'Case style' }),
          selectNode('developer-slice-case-style', [['lower', 'lower case'], ['upper', 'UPPER CASE'], ['title', 'Title Case'], ['sentence', 'Sentence case'], ['camel', 'camelCase'], ['pascal', 'PascalCase'], ['snake', 'snake_case'], ['kebab', 'kebab-case'], ['constant', 'CONSTANT_CASE']])),
        el('div', {}, el('label', { for: 'developer-slice-case-locale', className: 'block text-sm font-semibold ok-dev-text', text: 'Language rules' }),
          selectNode('developer-slice-case-locale', [['root', 'Standard Unicode'], ['tr', 'Turkish (i → İ)'], ['az', 'Azerbaijani (i → İ)']]))),
      el('div', { id: 'developer-slice-time-fields', className: 'grid gap-4 md:grid-cols-3', hidden: true },
        el('div', {}, el('label', { for: 'developer-slice-ts-type', className: 'block text-sm font-semibold ok-dev-text', text: 'Input is' }),
          selectNode('developer-slice-ts-type', [['unix_seconds', 'Unix seconds'], ['unix_milliseconds', 'Unix milliseconds'], ['unix_microseconds', 'Unix microseconds'], ['iso_8601', 'ISO 8601 with offset'], ['local_datetime', 'Local date and time in a zone']])),
        el('div', {},
          el('div', { className: 'flex items-baseline justify-between gap-2' },
            el('label', { for: 'developer-slice-ts-value', className: 'block text-sm font-semibold ok-dev-text', text: 'Value' }),
            el('button', { id: 'developer-slice-ts-now', type: 'button', className: 'ok-text-link', text: 'Use now' })),
          el('input', { id: 'developer-slice-ts-value', type: 'text', className: 'mt-1 block w-full rounded-lg border ok-dev-control-line ok-dev-surface px-3 py-2 font-mono text-sm', placeholder: 'Unix value, ISO 8601 text, or local date and time', autocomplete: 'off', spellcheck: 'false' }),
          el('p', { id: 'developer-slice-ts-gap-guidance', className: 'mt-1 text-sm ok-calc-error', role: 'alert', 'data-officekit-no-bug-report': 'true', hidden: true })),
        el('div', {}, el('label', { for: 'developer-slice-ts-source', className: 'block text-sm font-semibold ok-dev-text', text: 'Source zone (local date and time only)' }),
          el('input', { id: 'developer-slice-ts-source', type: 'text', list: 'developer-slice-zones', className: 'mt-1 block w-full rounded-lg border ok-dev-control-line ok-dev-surface px-3 py-2 font-mono text-sm', placeholder: 'America/New_York', disabled: true, autocomplete: 'off' })),
        el('div', { className: 'md:col-span-3' },
          el('div', { className: 'flex items-baseline justify-between gap-2' },
            el('span', { className: 'block text-sm font-semibold ok-dev-text', text: 'Show in' }),
            el('button', { id: 'developer-slice-ts-add', type: 'button', className: 'ok-text-link', text: '+ Add zone' })),
          el('div', { id: 'developer-slice-ts-zones', className: 'mt-2 flex flex-wrap gap-2' }),
          el('input', { id: 'developer-slice-ts-zone-input', type: 'text', list: 'developer-slice-zones', hidden: true, placeholder: 'Zone name, for example Asia/Tokyo', autocomplete: 'off', className: 'mt-2 block w-full rounded-lg border ok-dev-control-line ok-dev-surface px-3 py-2 font-mono text-sm' }),
          el('p', { className: 'hint ok-dev-muted text-xs', text: 'Unix seconds 1700000000 · milliseconds 1700000000000 · microseconds 1700000000000000' }))),
      el('datalist', { id: 'developer-slice-zones' }),
    );
    byId('developer-slice-ts-type').addEventListener('change', syncTimeFields);
    byId('developer-slice-ts-value').addEventListener('input', clearTimestampGapGuidance);
    byId('developer-slice-ts-now').addEventListener('click', fillNow);
    byId('developer-slice-ts-add').addEventListener('click', showZoneInput);
    byId('developer-slice-ts-zone-input').addEventListener('change', commitZoneInput);
    return host;
  }

  function selectNode(id, options) {
    return el('select', { id, className: 'mt-1 w-full rounded-lg border ok-dev-control-line ok-dev-surface px-3 py-2 text-sm' },
      options.map(([value, label]) => el('option', { value, text: label })));
  }

  function syncTimeFields() {
    clearTimestampGapGuidance();
    const isLocal = byId('developer-slice-ts-type').value === 'local_datetime';
    byId('developer-slice-ts-source').disabled = !isLocal;
    if (isLocal && !byId('developer-slice-ts-source').value) byId('developer-slice-ts-source').value = localZone();
    if (!fieldState.zonesLoaded) loadZones();
  }

  // ---- timestamp zones, fold and result ------------------------------------

  const tsState = { zones: [], fold: 'reject', value: '', ambiguousFor: null };

  function localZone() {
    const zone = typeof win.officekitLocalTimeZone === 'function' ? win.officekitLocalTimeZone() : Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone || 'UTC';
  }

  function renderZoneChips() {
    byId('developer-slice-ts-zones').replaceChildren(...tsState.zones.map(zone => {
      const remove = el('button', { type: 'button', className: 'ok-row-action', 'aria-label': `Remove ${zone}`, text: '×' });
      remove.addEventListener('click', () => removeZone(zone));
      return el('span', { className: 'ok-chip' }, zone === localZone() && zone !== 'UTC' ? `${zone} (this Mac)` : zone, remove);
    }));
  }

  // The default list is UTC and this Mac's zone; Add zone appends one more (up to eight).
  function resetZones() {
    tsState.zones = localZone() === 'UTC' ? ['UTC'] : ['UTC', localZone()];
    renderZoneChips();
  }

  function removeZone(zone) {
    tsState.zones = tsState.zones.filter(item => item !== zone);
    renderZoneChips();
  }

  function showZoneInput() {
    const input = byId('developer-slice-ts-zone-input');
    input.hidden = false;
    input.value = '';
    input.focus?.();
  }

  function commitZoneInput() {
    const input = byId('developer-slice-ts-zone-input');
    const zone = input.value.trim();
    input.hidden = true;
    input.value = '';
    if (!zone || tsState.zones.includes(zone)) return;
    if (tsState.zones.length >= LIMITS.zones) {
      setStatus(byId('developer-tools-status'), MESSAGES.zones, true);
      return;
    }
    tsState.zones = [...tsState.zones, zone];
    renderZoneChips();
  }

  const alertNode = (kind, ...children) => el('div', { role: 'alert', className: `ok-dev-alert ok-dev-alert-${kind}` }, ...children);

  function timestampTable(data) {
    return el('table', { className: 'ok-dev-table', 'aria-label': 'Converted times' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Zone' }), el('th', { text: 'Date and time' }), el('th', { text: 'Offset' }), el('th', { text: 'Note' }))),
      el('tbody', {}, data.conversions.map(zone => el('tr', {},
        el('td', { text: zone.zone }),
        el('td', { className: 'font-mono break-all', text: zone.local_iso }),
        el('td', { className: 'font-mono', text: zone.abbreviation === 'UTC' ? zone.offset : `${zone.abbreviation} ${zone.offset}` }),
        el('td', { text: zone.abbreviation === 'UTC' ? zone.weekday : `${zone.weekday} · ${zone.is_dst ? 'daylight' : 'standard'} time` })))));
  }

  function foldGroup(earlierOffset, laterOffset) {
    const group = el('div', { role: 'group', 'aria-label': 'Which occurrence', className: 'mt-2 inline-flex rounded-lg border ok-dev-control-line p-0.5' });
    for (const [fold, label, offset] of [['earlier', 'Earlier', earlierOffset], ['later', 'Later', laterOffset]]) {
      const button = el('button', { type: 'button', className: 'ok-segment rounded-md px-3 py-1.5 text-sm font-semibold', 'aria-pressed': String(tsState.fold === fold), text: offset ? `${label} (${offset})` : label });
      button.addEventListener('click', () => chooseFold(fold));
      group.append(button);
    }
    return group;
  }

  function offsetOf(data) {
    const zone = byId('developer-slice-ts-source').value;
    return data.conversions.find(item => item.zone === zone)?.offset;
  }

  function renderTimestamp(data, value, ambiguous) {
    const inputType = byId('developer-slice-ts-type').value;
    const nodes = [];
    if (ambiguous) {
      const zone = byId('developer-slice-ts-source').value;
      nodes.push(alertNode('warn', `${value.split('T').pop()} happens twice in ${zone}. Choose which one you mean.`));
      nodes.push(foldGroup(ambiguous.earlier, ambiguous.later));
    }
    for (const warning of data.warnings || []) {
      if (warning === 'magnitude_suggests_milliseconds' && inputType === 'unix_seconds') {
        nodes.push(alertNode('warn', `${value} read as Unix seconds is ${data.instant_utc}. This looks like milliseconds. `,
          readAsAction('Read as milliseconds', 'unix_milliseconds')));
      } else if (warning === 'magnitude_suggests_seconds' && inputType === 'unix_milliseconds') {
        nodes.push(alertNode('warn', `${value} read as Unix milliseconds is ${data.instant_utc}. This looks like seconds. `,
          readAsAction('Read as seconds', 'unix_seconds')));
      }
    }
    nodes.push(timestampTable(data));
    showSliceResult(el('div', {}, nodes));
  }

  function readAsAction(label, type) {
    const action = el('button', { type: 'button', className: 'ok-text-link', text: label });
    action.addEventListener('click', () => {
      byId('developer-slice-ts-type').value = type;
      syncTimeFields();
      convertFromUi();
    });
    return action;
  }

  function renderGap(value, zone) {
    const field = byId('developer-slice-ts-value');
    const guidance = byId('developer-slice-ts-gap-guidance');
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', guidance.id);
    guidance.hidden = false;
    guidance.textContent = `This local time does not exist in ${zone} because clocks move forward. Choose a later time.`;
  }

  function clearTimestampGapGuidance() {
    const field = byId('developer-slice-ts-value');
    const guidance = byId('developer-slice-ts-gap-guidance');
    if (!field || !guidance || guidance.hidden) return;
    field.removeAttribute('aria-invalid');
    field.removeAttribute('aria-describedby');
    guidance.hidden = true;
    guidance.textContent = '';
  }

  async function requestTimestamp(value, fold) {
    const request = timestampRequest({
      value,
      inputType: byId('developer-slice-ts-type').value,
      sourceZone: byId('developer-slice-ts-source').value,
      fold,
      targetZones: tsState.zones,
    });
    return expectObject(await postJson(request.path, request.body, MESSAGES.timestamp));
  }

  async function tryTimestamp(value, fold) {
    try { return await requestTimestamp(value, fold); } catch { return null; }
  }

  // A local time that reject refuses is either ambiguous (both folds convert) or a DST gap (neither does).
  async function convertTimestamp(value) {
    tsState.value = value;
    const fold = tsState.ambiguousFor === value ? tsState.fold : 'reject';
    // Validation errors surface before any probe, so they never read as a DST gap.
    timestampRequest({ value, inputType: byId('developer-slice-ts-type').value, sourceZone: byId('developer-slice-ts-source').value, fold, targetZones: tsState.zones });
    try {
      const data = await requestTimestamp(value, fold);
      renderTimestamp(data, value, fold === 'reject' ? null : tsState.offsets);
      return timestampLines(data);
    } catch (error) {
      if (fold !== 'reject' || byId('developer-slice-ts-type').value !== 'local_datetime' || error.message !== MESSAGES.timestamp) throw error;
      const earlier = await tryTimestamp(value, 'earlier');
      const later = await tryTimestamp(value, 'later');
      if (earlier && later) {
        tsState.ambiguousFor = value;
        tsState.fold = 'earlier';
        tsState.offsets = { earlier: offsetOf(earlier), later: offsetOf(later) };
        renderTimestamp(earlier, value, tsState.offsets);
        return timestampLines(earlier);
      }
      tsState.ambiguousFor = null;
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value.trim())) {
        renderGap(value.trim(), byId('developer-slice-ts-source').value);
        const error = new Error(MESSAGES.gap);
        error.inputError = true;
        error.validationField = 'developer-slice-ts-value';
        error.validationGuidance = 'developer-slice-ts-gap-guidance';
        throw error;
      }
      throw error;
    }
  }

  async function chooseFold(fold) {
    tsState.fold = fold;
    await convertFromUi();
  }

  async function convertFromUi() {
    const status = byId('developer-tools-status');
    try {
      await convertTimestamp(byId('developer-slice-ts-value').value);
      setStatus(status, 'Converted locally.');
    } catch (error) {
      setStatus(status, error.message, true);
    }
  }

  async function loadZones() {
    fieldState.zonesLoaded = true;
    try {
      const data = await getJson(PATHS.timeZones);
      const list = byId('developer-slice-zones');
      if (!list || !Array.isArray(data.zones)) return;
      list.replaceChildren(...data.zones.map(zone => el('option', { value: zone })));
    } catch {
      fieldState.zonesLoaded = false;
    }
  }

  function fillNow() {
    clearTimestampGapGuidance();
    const type = byId('developer-slice-ts-type').value;
    const now = Date.now();
    const values = {
      unix_seconds: String(Math.floor(now / 1000)),
      unix_milliseconds: String(now),
      unix_microseconds: String(now * 1000),
      iso_8601: new Date(now).toISOString(),
      local_datetime: new Date(now - new Date(now).getTimezoneOffset() * 60000).toISOString().slice(0, 16),
    };
    byId('developer-slice-ts-value').value = values[type] || '';
  }

  // The slice result (stat grid, timestamp table) sits under the input. Text metrics replaces the text result.
  function clearSliceResult() {
    const result = byId('developer-slice-result');
    if (!result) return;
    const outputLabel = byId('developer-tools-output-label');
    if (result.parentNode && outputLabel?.parentNode === result.parentNode) result.parentNode.insertBefore(result, outputLabel);
    result.replaceChildren();
    result.hidden = true;
  }

  // Clear empties the slice result and resets the timestamp value, the fold choice and the zone chips.
  // Run uses clearSliceResult only, so a failed run never leaves a stale table or grid behind (UX-18).
  function clearSlice() {
    clearSliceResult();
    clearTimestampGapGuidance();
    tsState.value = '';
    tsState.ambiguousFor = null;
    tsState.fold = 'reject';
    const value = byId('developer-slice-ts-value');
    if (value) value.value = '';
    if (byId('developer-slice-ts-zones')) resetZones();
  }

  // The approved Convert timestamp frame shows Run locally and Copy result only, so its result is not offered as a download (UX-20).
  function offersDownload(operation) {
    return operation !== 'timestamp_convert';
  }

  function showSliceResult(node) {
    const result = byId('developer-slice-result');
    result.replaceChildren(node);
    result.hidden = false;
  }

  function showMetricsResult(node) {
    showSliceResult(node);
    const result = byId('developer-slice-result');
    const inputLabel = byId('developer-tools-input-label');
    if (result.parentNode && inputLabel?.parentNode?.parentNode === result.parentNode) result.parentNode.insertBefore(result, inputLabel.parentNode);
    result.scrollIntoView?.({ block: 'start' });
  }

  const METRIC_TILES = Object.freeze([
    ['graphemes', 'Characters you see (graphemes)'],
    ['code_points', 'Unicode code points'],
    ['utf8_bytes', 'UTF-8 bytes'],
    ['words', 'Words'],
    ['lines', 'Lines'],
    ['blank_lines', 'Blank lines'],
  ]);
  const METRIC_RULES = 'Graphemes follow Unicode extended grapheme clusters, so 👩‍👩‍👧 counts as 1. Words are whitespace-separated runs that contain a letter or number; text without spaces, such as Chinese or Japanese, counts as one word per run. Lines split on LF, CRLF, CR, U+2028 and U+2029, and a final line break does not add a line.';

  function metricsNodes(data) {
    const body = expectObject(data);
    return el('div', {},
      el('div', { className: 'grid grid-cols-2 gap-2 sm:grid-cols-3', 'aria-label': 'Text metrics' },
        METRIC_TILES.map(([key, label]) => el('div', { className: 'ok-dev-stat' }, el('b', { text: String(body[key]) }), el('span', { text: label })))),
      el('details', { className: 'ok-dev-details' }, el('summary', { text: 'How these are counted' }), el('p', { className: 'ok-dev-muted text-xs', text: METRIC_RULES })));
  }

  function syncOperation(operation) {
    const host = ensureFields();
    if (!host) return;
    const isSlice = SLICE_OPERATIONS.has(operation);
    host.hidden = !isSlice;
    clearSliceResult();
    // Text metrics and Convert timestamp show their own result, so the text result and the Input are not drawn.
    const ownResult = operation === 'text_metrics' || operation === 'timestamp_convert';
    byId('developer-tools-output').hidden = ownResult;
    byId('developer-tools-output-label').hidden = ownResult;
    byId('developer-tools-input').hidden = operation === 'timestamp_convert';
    byId('developer-tools-input-label').hidden = operation === 'timestamp_convert';
    if (operation === 'text_case') byId('developer-tools-hint').textContent = 'Some characters change length, for example ß becomes SS.';
    byId('developer-slice-case-fields').hidden = operation !== 'text_case';
    byId('developer-slice-time-fields').hidden = operation !== 'timestamp_convert';
    if (operation === 'timestamp_convert') {
      syncTimeFields();
      if (tsState.zones.length === 0) resetZones();
    }
  }

  // The value the slice reads from its own field instead of the shared Input (Convert timestamp).
  function inputFor(operation) {
    return operation === 'timestamp_convert' ? byId('developer-slice-ts-value').value : undefined;
  }

  async function runSliceOperation(operation, input) {
    ensureFields();
    if (operation === 'text_metrics') {
      const request = textAnalysisRequest(input);
      const data = await postJson(request.path, request.body, MESSAGES.textInput);
      showMetricsResult(metricsNodes(data));
      return analysisLines(data);
    }
    if (operation === 'text_case') {
      const request = textCaseRequest({ text: input, style: byId('developer-slice-case-style').value, locale: byId('developer-slice-case-locale').value });
      const data = await postJson(request.path, request.body, MESSAGES.textInput);
      return expectObject(data).result;
    }
    if (operation === 'timestamp_convert') return convertTimestamp(input);
    throw new Error('Choose a supported developer-tool operation.');
  }

  // ---- compare panel ------------------------------------------------------

  const compareState = { mode: 'json', layout: 'side', json: null, text: null, textStale: false };

  function labelled(id, label, ...controls) {
    return el('div', {}, el('label', { for: id, className: 'block text-sm font-semibold ok-dev-text', text: label }), ...controls);
  }

  function areaNode(id, label) {
    return labelled(id, label,
      el('textarea', { id, rows: 10, spellcheck: 'false', maxlength: LIMITS.text, className: 'mt-1 w-full rounded-xl border ok-dev-control-line ok-dev-surface p-3 font-mono text-sm' }),
      el('p', { id: `${id}-guidance`, role: 'alert', 'data-officekit-no-bug-report': 'true', hidden: true, className: 'mt-1 text-sm ok-calc-error' }));
  }

  function modeButton(mode, label) {
    return el('button', { type: 'button', 'data-compare-mode': mode, 'aria-pressed': mode === compareState.mode ? 'true' : 'false', className: 'ok-segment rounded-md px-3 py-1.5 text-sm font-semibold', text: label });
  }

  function buildCompare(root) {
    const section = el('section', { id: 'developer-compare-panel', 'aria-label': 'Compare', className: 'ok-dev-panel p-6 space-y-4' },
      el('h2', { className: 'ok-dev-title font-bold ok-dev-text', text: 'Compare' }),
      el('p', { className: 'text-sm ok-dev-muted', text: 'Compare JSON by structure, or text line by line. Input stays on this computer and is not saved.' }),
      el('div', { className: 'flex flex-wrap items-center justify-between gap-2' },
        el('div', { role: 'group', 'aria-label': 'Comparison type', className: 'inline-flex rounded-lg border ok-dev-control-line p-0.5', id: 'developer-compare-mode' }, modeButton('json', 'JSON'), modeButton('text', 'Text')),
        el('div', { className: 'flex items-center gap-4' },
          el('button', { type: 'button', id: 'developer-compare-swap', className: 'ok-text-link', text: 'Swap' }),
          el('button', { type: 'button', id: 'developer-compare-clear', className: 'ok-text-link', text: 'Clear' }))),
      el('div', { className: 'grid gap-4 md:grid-cols-2' }, areaNode('developer-compare-original', 'Original'), areaNode('developer-compare-changed', 'Changed')),
      el('details', { id: 'developer-compare-json-details', open: true, className: 'ok-dev-details' }, el('summary', { text: 'Options' }),
        el('div', { id: 'developer-compare-json-options', className: 'grid gap-4 md:grid-cols-2' },
          labelled('developer-compare-array', 'Array order', selectNode('developer-compare-array', [['ordered', 'Order matters (align items)'], ['unordered', 'Ignore order (compare as sets)']])),
          labelled('developer-compare-numbers', 'Numbers', selectNode('developer-compare-numbers', [['value', 'Compare values (1 equals 1.0)'], ['lexical', 'Compare as written (1 differs from 1.0)']]))),
        el('p', { className: 'ok-dev-muted text-xs', text: 'Object key order is always ignored. Duplicate keys, NaN and Infinity are rejected.' })),
      el('details', { id: 'developer-compare-text-details', hidden: true, className: 'ok-dev-details' }, el('summary', { text: 'Options: whitespace, line endings, Unicode' }),
        el('div', { id: 'developer-compare-text-options', className: 'grid gap-4 md:grid-cols-3' },
          labelled('developer-compare-whitespace', 'Whitespace', selectNode('developer-compare-whitespace', [['exact', 'Compare exactly'], ['ignore_trailing', 'Ignore trailing spaces'], ['ignore_all', 'Ignore all whitespace']])),
          labelled('developer-compare-eol', 'Line endings', selectNode('developer-compare-eol', [['normalize', 'Treat CRLF, CR, LF alike'], ['exact', 'Compare exactly']])),
          labelled('developer-compare-nfc', 'Unicode', selectNode('developer-compare-nfc', [['as_typed', 'Compare as typed'], ['nfc', 'Normalize (NFC) first']])))),
      el('div', { role: 'group', 'aria-label': 'Result layout', id: 'developer-compare-layout', hidden: true, className: 'inline-flex rounded-lg border ok-dev-control-line p-0.5' },
        el('button', { type: 'button', 'data-compare-layout': 'side', 'aria-pressed': 'true', className: 'ok-segment rounded-md px-3 py-1.5 text-sm font-semibold', text: 'Side by side' }),
        el('button', { type: 'button', 'data-compare-layout': 'unified', 'aria-pressed': 'false', className: 'ok-segment rounded-md px-3 py-1.5 text-sm font-semibold', text: 'Unified' })),
      el('footer', { className: 'ok-action-dock', 'aria-label': 'Compare actions' },
        el('p', { id: 'developer-compare-status', role: 'status', 'aria-live': 'polite', className: 'ok-action-dock__status' }),
        el('div', { className: 'ok-action-dock__controls flex flex-wrap items-center gap-2' },
          el('button', { type: 'button', id: 'developer-compare-run', className: 'rounded-xl  px-4 py-2.5 text-sm font-semibold  btn btn-primary', text: 'Compare' }),
          el('button', { type: 'button', id: 'developer-compare-copy', disabled: true, hidden: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Copy result' }),
          el('select', { id: 'developer-compare-format', 'aria-label': 'Download format', hidden: true, className: 'rounded-lg border ok-dev-control-line px-2 py-2 text-sm' },
            el('option', { value: 'patch', text: '.patch' }), el('option', { value: 'markdown', text: 'Markdown' })),
          el('button', { type: 'button', id: 'developer-compare-download', disabled: true, hidden: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Download' }))),
      el('div', { id: 'developer-compare-results', 'aria-live': 'polite', className: 'space-y-2' }));
    root.append(section);
    if (typeof win.ResizeObserver === 'function') {
      new win.ResizeObserver(entries => { for (const entry of entries) applyCompactWidth(entry.contentRect.width); }).observe(section);
    }
    section.querySelectorAll('[data-compare-mode]').forEach(node => node.addEventListener('click', () => setCompareMode(node.dataset.compareMode)));
    for (const fieldId of ['developer-compare-original', 'developer-compare-changed']) {
      byId(fieldId).addEventListener('input', () => {
        clearCompareFieldError(fieldId);
        const status = byId('developer-compare-status');
        status.removeAttribute('data-officekit-no-bug-report');
        if (compareState.mode === 'text') markTextDiffStale();
        else setStatus(status, '');
      });
    }
    for (const fieldId of ['developer-compare-whitespace', 'developer-compare-eol', 'developer-compare-nfc']) {
      byId(fieldId).addEventListener('change', markTextDiffStale);
    }
    section.querySelectorAll('[data-compare-layout]').forEach(node => node.addEventListener('click', () => setCompareLayout(node.dataset.compareLayout)));
    byId('developer-compare-run').addEventListener('click', runCompare);
    byId('developer-compare-clear').addEventListener('click', clearCompare);
    byId('developer-compare-swap').addEventListener('click', swapCompare);
    byId('developer-compare-copy').addEventListener('click', copyCompare);
    byId('developer-compare-download').addEventListener('click', downloadCompare);
  }

  function setCompareMode(mode) {
    compareState.mode = mode === 'text' ? 'text' : 'json';
    clearCompareValidation();
    const status = byId('developer-compare-status');
    status.removeAttribute('data-officekit-no-bug-report');
    setStatus(status, '');
    doc().querySelectorAll('[data-compare-mode]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.compareMode === compareState.mode)));
    byId('developer-compare-json-details').hidden = compareState.mode !== 'json';
    byId('developer-compare-text-details').hidden = compareState.mode !== 'text';
    byId('developer-compare-copy').textContent = compareState.mode === 'text' ? 'Copy patch' : 'Copy differences';
    byId('developer-compare-download').textContent = compareState.mode === 'text' ? 'Download' : 'Download JSON';
    byId('developer-compare-layout').hidden = compareState.mode !== 'text' || (compareState.width ?? Infinity) <= LIMITS.compactWidth;
    byId('developer-compare-format').hidden = compareState.mode !== 'text';
    clearCompareResults();
  }

  // Below the compact width the text diff is unified only, and Side by side is not offered (UX-9).
  function layoutFor(width, requested) {
    if (width <= LIMITS.compactWidth) return 'unified';
    return requested === 'unified' ? 'unified' : 'side';
  }

  function applyCompactWidth(width) {
    compareState.width = width;
    byId('developer-compare-layout').hidden = compareState.mode !== 'text' || width <= LIMITS.compactWidth;
    if (compareState.text) renderTextResult(compareState.text);
  }

  function setCompareLayout(layout) {
    compareState.layout = layout === 'unified' ? 'unified' : 'side';
    doc().querySelectorAll('[data-compare-layout]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.compareLayout === compareState.layout)));
    if (compareState.text) renderTextResult(compareState.text);
  }

  function clearCompareResults() {
    compareState.json = null;
    compareState.text = null;
    compareState.textStale = false;
    byId('developer-compare-results').replaceChildren();
    byId('developer-compare-copy').disabled = true;
    byId('developer-compare-download').disabled = true;
    byId('developer-compare-copy').hidden = true;
    byId('developer-compare-download').hidden = true;
  }

  function clearCompareFieldError(fieldId) {
    const field = byId(fieldId);
    const guidance = byId(`${fieldId}-guidance`);
    field.removeAttribute('aria-invalid');
    field.removeAttribute('aria-describedby');
    if (guidance) { guidance.hidden = true; guidance.textContent = ''; }
  }

  function clearCompareValidation() {
    clearCompareFieldError('developer-compare-original');
    clearCompareFieldError('developer-compare-changed');
  }

  function showCompareFieldError(fieldId, message) {
    const field = byId(fieldId);
    const guidance = byId(`${fieldId}-guidance`);
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', guidance.id);
    guidance.hidden = false;
    guidance.textContent = message;
  }

  function markTextDiffStale() {
    if (compareState.mode !== 'text' || !compareState.text || compareState.textStale) return;
    compareState.textStale = true;
    byId('developer-compare-copy').disabled = true;
    byId('developer-compare-download').disabled = true;
    setStatus(byId('developer-compare-status'), 'Inputs changed. Compare again to update the result.');
    renderTextResult(compareState.text);
  }

  function clearCompare() {
    byId('developer-compare-original').value = '';
    byId('developer-compare-changed').value = '';
    clearCompareResults();
    setStatus(byId('developer-compare-status'), '');
  }

  function swapCompare() {
    const original = byId('developer-compare-original');
    const changed = byId('developer-compare-changed');
    [original.value, changed.value] = [changed.value, original.value];
    clearCompareResults();
  }

  function renderJsonResult(data) {
    const results = byId('developer-compare-results');
    results.replaceChildren();
    if (data.equal) {
      results.append(el('p', { className: 'text-sm font-semibold ok-dev-success', text: 'No differences. The two JSON documents are equal (key order ignored).' }));
      return;
    }
    const count = data.changes.length;
    results.append(el('p', { className: 'text-sm font-semibold ok-dev-text', text: `${count} ${count === 1 ? 'difference' : 'differences'} · keys reordered (ignored)` }));
    if (data.truncated) results.append(el('p', { className: 'text-sm font-semibold ok-dev-warning', text: 'Only the first 10,000 differences are shown.' }));
    results.append(el('table', { className: 'ok-dev-table', 'aria-label': 'JSON differences' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Path' }), el('th', { text: 'Change' }), el('th', { text: 'Original → Changed' }))),
      el('tbody', {}, jsonChangeNodes(data))));
  }

  function renderTextResult(data) {
    const results = byId('developer-compare-results');
    results.replaceChildren();
    if (compareState.textStale) {
      results.append(el('div', { role: 'status', className: 'ok-dev-alert ok-dev-alert-warn', text: 'Inputs changed — compare again to update. The result below uses the previous text. Copy and Download are paused until you compare again.' }));
      results.append(el('h3', { className: 'text-sm font-semibold ok-dev-text', text: 'Previous comparison' }));
    }
    if (data.equal) {
      results.append(el('p', { className: 'text-sm font-semibold ok-dev-success', text: 'No differences. The texts are equal under the chosen options.' }));
      return;
    }
    results.append(el('p', { className: 'text-sm font-semibold ok-dev-text', text: `${data.stats.deleted} deleted · ${data.stats.changed} changed · ${data.stats.inserted} inserted` }));
    results.append(el('div', { className: 'max-h-96 overflow-auto rounded-xl border ok-dev-line p-3' }, textRowNodes(data.rows, layoutFor(compareState.width ?? Infinity, compareState.layout))));
    results.append(el('p', { className: 'ok-dev-muted text-xs', text: 'Content is always shown as text. Markup in either input is never run.' }));
  }

  function renderCompareError(message) {
    const results = byId('developer-compare-results');
    results.replaceChildren(el('p', { role: 'alert', className: 'text-sm ok-dev-error', text: message }));
  }

  async function runCompare() {
    const status = byId('developer-compare-status');
    const run = byId('developer-compare-run');
    run.disabled = true;
    clearCompareResults();
    clearCompareValidation();
    status.removeAttribute('data-officekit-no-bug-report');
    try {
      const original = byId('developer-compare-original').value;
      const changed = byId('developer-compare-changed').value;
      if (compareState.mode === 'json') {
        const request = jsonDiffRequest({ original, changed, arrayOrder: byId('developer-compare-array').value, numeric: byId('developer-compare-numbers').value });
        const data = parseJsonDiffResponse(await postJson(request.path, request.body, MESSAGES.json));
        compareState.json = data;
        renderJsonResult(data);
        setStatus(status, data.equal ? 'Compared locally. No differences.' : `Compared locally. ${data.changes.length} ${data.changes.length === 1 ? 'difference' : 'differences'}.`);
        byId('developer-compare-copy').disabled = false;
        byId('developer-compare-download').disabled = false;
        byId('developer-compare-copy').hidden = false;
        byId('developer-compare-download').hidden = false;
        return;
      } else {
        const request = textDiffRequest({
          original,
          changed,
          whitespace: byId('developer-compare-whitespace').value,
          lineEndings: byId('developer-compare-eol').value,
          unicodeNfc: byId('developer-compare-nfc').value === 'nfc',
        });
        const data = parseTextDiffResponse(await postJson(request.path, request.body, MESSAGES.text));
        compareState.text = data;
        compareState.textStale = false;
        renderTextResult(data);
      }
      byId('developer-compare-copy').disabled = false;
      byId('developer-compare-download').disabled = false;
      byId('developer-compare-copy').hidden = false;
      byId('developer-compare-download').hidden = false;
      setStatus(status, MESSAGES.compared);
    } catch (error) {
      if (error?.inputError && error.validationField) {
        showCompareFieldError(error.validationField, error.validationMessage);
        status.setAttribute('data-officekit-no-bug-report', 'true');
        setStatus(status, 'Correct the highlighted JSON before comparing.', true);
      } else {
        renderCompareError(error.message);
        setStatus(status, error.message, true);
      }
    } finally {
      run.disabled = false;
    }
  }

  function compareOutput() {
    if (compareState.mode === 'text') return compareState.text ? compareState.text.patch : '';
    if (!compareState.json || compareState.json.changes.length === 0) return '';
    return compareState.json.changes.map(change => `${change.path || '(root)'} ${change.kind} ${change.before ?? ''} -> ${change.after ?? ''}`).join('\n') + '\n';
  }

  function copyCompare() {
    if (compareState.mode === 'text' && compareState.textStale) return;
    const output = compareOutput();
    if (output) copyText(output, byId('developer-compare-status'));
  }

  // Markdown wraps the patch in a fence longer than any backtick run inside it.
  function markdownFence(patch) {
    const longest = Math.max(0, ...(patch.match(/`+/g) || []).map(run => run.length));
    const fence = '`'.repeat(Math.max(3, longest + 1));
    return `${fence}diff\n${patch}${fence}\n`;
  }

  function downloadCompare() {
    if (compareState.mode === 'json') {
      if (!compareState.json || compareState.json.changes.length === 0) return;
      saveBlob(`${JSON.stringify({ counts: compareState.json.counts, changes: compareState.json.changes }, null, 2)}\n`, 'application/json;charset=utf-8', 'officekit-json-differences.json');
      return;
    }
    if (compareState.mode === 'text' && compareState.textStale) return;
    const output = compareOutput();
    if (!output) return;
    if (compareState.mode === 'text') {
      if (byId('developer-compare-format').value === 'markdown') saveBlob(markdownFence(output), 'text/markdown;charset=utf-8', 'officekit-text.md');
      else saveBlob(output, 'text/x-diff;charset=utf-8', 'officekit-text.patch');
    } else saveBlob(output, 'text/plain;charset=utf-8', 'officekit-json-changes.txt');
  }

  // ---- UUID panel ---------------------------------------------------------

  const uuidState = { uuids: [], countBeforeV5: null };

  function buildUuid(root) {
    const section = el('section', { id: 'developer-uuid-panel', 'aria-label': 'UUID generator', className: 'ok-dev-panel p-6 space-y-4' },
      el('h2', { className: 'ok-dev-title font-bold ok-dev-text', text: 'UUID generator' }),
      el('p', { className: 'text-sm ok-dev-muted', text: 'Generate up to 1,000 UUIDs on this computer. Version 4 and 7 are random identifiers, not secrets.' }),
      el('div', { className: 'grid gap-4 md:grid-cols-2' },
        labelled('developer-uuid-version', 'Version', selectNode('developer-uuid-version', [['4', 'v4 · random'], ['7', 'v7 · time-ordered'], ['5', 'v5 · from a name']])),
        labelled('developer-uuid-count', 'How many', el('input', { id: 'developer-uuid-count', type: 'number', min: '1', max: String(LIMITS.uuidBatch), value: '25', className: 'mt-1 w-full rounded-lg border ok-dev-control-line px-3 py-2 text-sm' }))),
      // The v5 fields keep their slot when hidden, so Generate and the dock do not move when Version changes (UX-12).
      el('div', { id: 'developer-uuid-v5', className: 'grid gap-4 md:grid-cols-2' },
        labelled('developer-uuid-namespace', 'Namespace', selectNode('developer-uuid-namespace', [['dns', 'DNS'], ['url', 'URL'], ['oid', 'OID'], ['x500', 'X.500'], ['custom', 'Custom UUID…']])),
        labelled('developer-uuid-name', 'Name', el('input', { id: 'developer-uuid-name', type: 'text', maxlength: '1024', className: 'mt-1 w-full rounded-lg border ok-dev-control-line px-3 py-2 text-sm' }))),
      el('div', { id: 'developer-uuid-custom-wrap', className: 'ok-dev-invisible' }, labelled('developer-uuid-custom', 'Custom namespace UUID', el('input', { id: 'developer-uuid-custom', type: 'text', className: 'mt-1 w-full rounded-lg border ok-dev-control-line px-3 py-2 font-mono text-sm' }))),
      el('div', { className: 'flex items-start justify-between gap-2' },
        el('p', { id: 'developer-uuid-hint', className: 'hint ok-dev-muted text-xs', text: '1 to 1,000 at a time. v7 sorts by creation time and includes it, so do not use v7 where the creation time should stay private.' }),
        el('button', { type: 'button', id: 'developer-uuid-clear', className: 'ok-text-link', text: 'Clear' })),
      el('details', { id: 'developer-uuid-details', className: 'ok-dev-details' }, el('summary', { text: 'Letters and format' }),
        el('div', { className: 'grid gap-4 md:grid-cols-2' },
          labelled('developer-uuid-letters', 'Letters', selectNode('developer-uuid-letters', [['lower', 'lowercase'], ['upper', 'UPPERCASE']])),
          labelled('developer-uuid-style', 'Format', selectNode('developer-uuid-style', [['canonical', 'Standard'], ['braces', '{braces}'], ['urn', 'urn:uuid:'], ['compact', 'No hyphens']])))),
      el('footer', { className: 'ok-action-dock', 'aria-label': 'UUID actions' },
        el('p', { id: 'developer-uuid-status', role: 'status', 'aria-live': 'polite', className: 'ok-action-dock__status' }),
        el('div', { className: 'ok-action-dock__controls flex flex-wrap gap-2' },
          el('button', { type: 'button', id: 'developer-uuid-generate', className: 'rounded-xl  px-4 py-2.5 text-sm font-semibold  btn btn-primary', text: 'Generate' }),
          el('button', { type: 'button', id: 'developer-uuid-copy', disabled: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Copy all' }),
          el('select', { id: 'developer-uuid-format', 'aria-label': 'Download format', className: 'rounded-lg border ok-dev-control-line px-2 py-2 text-sm' },
            el('option', { value: 'txt', text: '.txt' }), el('option', { value: 'csv', text: '.csv' })),
          el('button', { type: 'button', id: 'developer-uuid-download', disabled: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Download' }))),
      el('ol', { id: 'developer-uuid-list', className: 'max-h-96 overflow-auto rounded-xl border ok-dev-line ok-dev-surface-muted p-3 font-mono text-sm space-y-1' }));
    root.append(section);
    byId('developer-uuid-version').addEventListener('change', syncUuidFields);
    byId('developer-uuid-namespace').addEventListener('change', syncUuidFields);
    byId('developer-uuid-generate').addEventListener('click', runUuid);
    byId('developer-uuid-copy').addEventListener('click', () => copyText(uuidState.uuids.join('\n'), byId('developer-uuid-status')));
    byId('developer-uuid-download').addEventListener('click', downloadUuids);
    byId('developer-uuid-clear').addEventListener('click', clearUuids);
    byId('developer-uuid-version').value = '7';
    syncUuidFields();
  }

  function clearUuids() {
    setUuidList([]);
    setStatus(byId('developer-uuid-status'), '');
  }

  function downloadUuids() {
    if (uuidState.uuids.length === 0) return;
    if (byId('developer-uuid-format').value === 'csv') saveBlob(uuidExport(uuidState.uuids, 'csv'), 'text/csv;charset=utf-8', 'officekit-uuids.csv');
    else saveBlob(uuidExport(uuidState.uuids, 'txt'), 'text/plain;charset=utf-8', 'officekit-uuids.txt');
  }

  function syncUuidFields() {
    const isV5 = byId('developer-uuid-version').value === '5';
    byId('developer-uuid-v5').classList.toggle('ok-dev-invisible', !isV5);
    // The Custom UUID slot keeps its space (visibility, not hidden), so choosing it does not move Generate or the dock (UX-12).
    byId('developer-uuid-custom-wrap').classList.toggle('ok-dev-invisible', !(isV5 && byId('developer-uuid-namespace').value === 'custom'));
    byId('developer-uuid-hint').textContent = isV5
      ? 'The same namespace and name always give the same UUID, so “How many” is fixed at 1.'
      : '1 to 1,000 at a time. v7 sorts by creation time and includes it, so do not use v7 where the creation time should stay private.';
    // v5 is one name per UUID, so How many is fixed at 1 and disabled (UX-11).
    // Leaving v5 restores the count the user had before it (UX-19); a re-sync while still on v5 keeps that remembered count.
    const count = byId('developer-uuid-count');
    if (isV5) {
      if (!count.disabled) uuidState.countBeforeV5 = count.value;
      count.value = '1';
    } else if (uuidState.countBeforeV5 !== null) {
      count.value = uuidState.countBeforeV5;
      uuidState.countBeforeV5 = null;
    }
    count.disabled = isV5;
  }

  function setUuidList(uuids) {
    uuidState.uuids = uuids;
    const list = byId('developer-uuid-list');
    list.replaceChildren(...uuids.map(uuid => el('li', { text: uuid })));
    const hasItems = uuids.length > 0;
    byId('developer-uuid-copy').disabled = !hasItems;
    byId('developer-uuid-download').disabled = !hasItems;
  }

  async function runUuid() {
    const status = byId('developer-uuid-status');
    const version = Number(byId('developer-uuid-version').value);
    setUuidList([]);
    try {
      const count = Number(byId('developer-uuid-count').value);
      const namespaceChoice = byId('developer-uuid-namespace').value;
      const request = uuidRequest({
        version,
        count: Number.isInteger(count) ? count : NaN,
        namespace: namespaceChoice === 'custom' ? byId('developer-uuid-custom').value : namespaceChoice,
        name: byId('developer-uuid-name').value,
        letters: byId('developer-uuid-letters').value,
        style: byId('developer-uuid-style').value,
      });
      const data = parseUuidResponse(await postJson(request.path, request.body, MESSAGES.uuid));
      setUuidList(data.uuids);
      setStatus(status, `Generated ${data.uuids.length} ${data.uuids.length === 1 ? 'UUID' : 'UUIDs'} on this computer.`);
    } catch (error) {
      setStatus(status, error.message, true);
    }
  }

  // ---- QR panel -----------------------------------------------------------

  const qrState = { url: null, format: null, data: null };

  function buildQr(root) {
    const section = el('section', { id: 'developer-qr-panel', 'aria-label': 'QR code generator', className: 'ok-dev-panel p-6 space-y-4' },
      el('h2', { className: 'ok-dev-title font-bold ok-dev-text', text: 'QR code generator' }),
      el('div', { className: 'flex items-start justify-between gap-2' },
        el('p', { className: 'text-sm ok-dev-muted', text: 'Create a QR code from text or a link on this device. Links are not opened or checked.' }),
        el('button', { type: 'button', id: 'developer-qr-clear', className: 'ok-text-link', text: 'Clear' })),
      labelled('developer-qr-payload', 'Text or link', el('textarea', { id: 'developer-qr-payload', rows: 4, maxlength: '2953', spellcheck: 'false', className: 'mt-1 w-full rounded-xl border ok-dev-control-line ok-dev-surface p-3 font-mono text-sm' })),
      el('div', { className: 'grid gap-4 md:grid-cols-3' },
        labelled('developer-qr-ecc', 'Error correction', selectNode('developer-qr-ecc', [['L', 'Low (7%)'], ['M', 'Medium (15%)'], ['Q', 'Quartile (25%)'], ['H', 'High (30%)']])),
        labelled('developer-qr-size', 'Size', selectNode('developer-qr-size', [['256', '256 px'], ['512', '512 px'], ['1024', '1024 px'], ['2048', '2048 px']])),
        labelled('developer-qr-format', 'Download as', selectNode('developer-qr-format', [['png', 'PNG image'], ['svg', 'SVG vector']]))),
      el('div', { id: 'developer-qr-capacity', className: 'text-sm ok-dev-muted' },
        el('progress', { id: 'developer-qr-meter', max: String(QR_CAPACITY.M), value: '0', className: 'w-full' }),
        el('p', { id: 'developer-qr-capacity-text', className: 'mt-1 text-xs', text: '0 of 2,331 bytes at Medium error correction.' })),
      el('footer', { className: 'ok-action-dock', 'aria-label': 'QR actions' },
        el('p', { id: 'developer-qr-status', role: 'status', 'aria-live': 'polite', className: 'ok-action-dock__status' }),
        el('div', { className: 'ok-action-dock__controls flex flex-wrap gap-2' },
          el('button', { type: 'button', id: 'developer-qr-generate', className: 'rounded-xl  px-4 py-2.5 text-sm font-semibold  btn btn-primary', text: 'Create QR code' }),
          el('button', { type: 'button', id: 'developer-qr-copy', disabled: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Copy image' }),
          el('button', { type: 'button', id: 'developer-qr-download', disabled: true, className: 'rounded-xl border ok-dev-control-line px-4 py-2.5 text-sm font-semibold ok-dev-text btn btn-ghost', text: 'Download' }))),
      el('div', { id: 'developer-qr-preview', className: 'flex min-h-40 items-center justify-center rounded-xl border border-dashed ok-dev-control-line ok-dev-surface p-4' },
        el('p', { className: 'text-sm ok-dev-muted', text: 'Generate a code to preview it here.' })));
    root.append(section);
    byId('developer-qr-payload').addEventListener('input', updateQrCapacity);
    byId('developer-qr-ecc').addEventListener('change', updateQrCapacity);
    byId('developer-qr-generate').addEventListener('click', runQr);
    byId('developer-qr-download').addEventListener('click', downloadQr);
    byId('developer-qr-copy').addEventListener('click', copyQrImage);
    byId('developer-qr-clear').addEventListener('click', clearQr);
  }

  function updateQrCapacity() {
    const ecc = byId('developer-qr-ecc').value;
    const { used, limit } = qrCapacity(byId('developer-qr-payload').value, ecc);
    const meter = byId('developer-qr-meter');
    meter.max = limit;
    meter.value = Math.min(used, limit);
    byId('developer-qr-capacity-text').textContent = `${used.toLocaleString('en-US')} of ${limit.toLocaleString('en-US')} bytes at ${{ L: 'Low', M: 'Medium', Q: 'Quartile', H: 'High' }[ecc]} error correction.`;
  }

  function clearQr() {
    byId('developer-qr-copy').disabled = true;
    if (qrState.url) win.URL.revokeObjectURL(qrState.url);
    qrState.url = null;
    qrState.format = null;
    byId('developer-qr-preview').replaceChildren(el('p', { className: 'text-sm ok-dev-muted', text: 'Generate a code to preview it here.' }));
    byId('developer-qr-download').disabled = true;
    setStatus(byId('developer-qr-status'), '');
  }

  function qrPreviewNode(data) {
    const alt = 'QR code for the text you entered';
    if (data.format === 'png') return el('img', { src: `data:image/png;base64,${data.data}`, alt, width: String(data.size_px), height: String(data.size_px), className: 'max-w-full h-auto' });
    if (qrState.url) win.URL.revokeObjectURL(qrState.url);
    qrState.url = win.URL.createObjectURL(new win.Blob([data.data], { type: 'image/svg+xml' }));
    return el('img', { src: qrState.url, alt, className: 'max-w-full h-auto' });
  }

  async function runQr() {
    const status = byId('developer-qr-status');
    byId('developer-qr-download').disabled = true;
    byId('developer-qr-copy').disabled = true;
    try {
      const request = qrRequest({
        payload: byId('developer-qr-payload').value,
        errorCorrection: byId('developer-qr-ecc').value,
        sizePx: Number(byId('developer-qr-size').value),
        format: byId('developer-qr-format').value,
      });
      const data = parseQrResponse(await postJson(request.path, request.body, MESSAGES.qr));
      qrState.format = data.format;
      qrState.data = data.data;
      byId('developer-qr-preview').replaceChildren(qrPreviewNode(data));
      byId('developer-qr-download').disabled = false;
      // Copy image puts the PNG on the clipboard; an SVG cannot be copied as an image, so its slot stays disabled.
      byId('developer-qr-copy').disabled = data.format !== 'png';
      setStatus(status, `Generated locally as ${data.format.toUpperCase()}. Nothing was uploaded.`);
    } catch (error) {
      setStatus(status, error.message, true);
    }
  }

  async function copyQrImage() {
    const status = byId('developer-qr-status');
    if (qrState.format !== 'png') return;
    try {
      if (!win.navigator?.clipboard?.write || typeof win.ClipboardItem !== 'function') throw new Error('Clipboard access is unavailable.');
      const bytes = Uint8Array.from(win.atob(qrState.data), char => char.charCodeAt(0));
      await win.navigator.clipboard.write([new win.ClipboardItem({ 'image/png': new win.Blob([bytes], { type: 'image/png' }) })]);
      setStatus(status, 'Copied the QR image. Nothing was saved.');
      toast('Copied the QR image.', 'success');
    } catch {
      setStatus(status, MESSAGES.copyDenied, true);
      toast(MESSAGES.copyDenied, 'error');
    }
  }

  function downloadQr() {
    if (!qrState.format) return;
    if (qrState.format === 'png') {
      const bytes = Uint8Array.from(win.atob(qrState.data), char => char.charCodeAt(0));
      saveBlob(bytes, 'image/png', 'officekit-qr.png');
    } else {
      saveBlob(qrState.data, 'image/svg+xml', 'officekit-qr.svg');
    }
  }

  // ---- views and public surface -----------------------------------------

  const builders = { compare: buildCompare, uuid: buildUuid, qr: buildQr };
  const built = new Set();
  const viewSection = { 'compare-json': 'compare', 'compare-text': 'compare', uuid: 'uuid', qr: 'qr' };

  function openView(view) {
    const key = viewSection[view];
    if (!key) return;
    const root = byId('tab-developer');
    if (!root) return;
    if (!built.has(key)) {
      builders[key](root);
      built.add(key);
    }
    for (const name of Object.keys(builders)) {
      const section = byId(`developer-${name}-panel`);
      if (section) section.hidden = name !== key;
    }
    if (key === 'compare') setCompareMode(view === 'compare-text' ? 'text' : 'json');
  }

  win.OfficeKitDeveloperSlice = Object.freeze({
    openView,
    syncOperation,
    clear: clearSlice,
    clearResult: clearSliceResult,
    offersDownload,
    handles: operation => SLICE_OPERATIONS.has(operation),
    inputFor,
    run: (operation, input) => runSliceOperation(operation, input),
    // Pure helpers, exported for the Node unit tests.
    jsonDiffRequest,
    parseJsonDiffResponse,
    textDiffRequest,
    parseTextDiffResponse,
    textCaseRequest,
    textAnalysisRequest,
    timestampRequest,
    uuidRequest,
    parseUuidResponse,
    qrRequest,
    parseQrResponse,
    qrCapacity,
    uuidExport,
    analysisLines,
    timestampLines,
    jsonChangeNodes,
    textRowNodes,
    spanNodes,
    layoutFor,
    el,
    LIMITS,
    QR_CAPACITY,
    MESSAGES,
  });
})(window);
