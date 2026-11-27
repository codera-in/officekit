/* Shared result actions consume explicit complete data, never rendered previews. */
(() => {
  'use strict';
  const COPY_LIMIT = 8 * 1024 * 1024;
  const SAVE_LIMIT = 64 * 1024 * 1024;
  const capabilities = new Map();
  const invoke = () => window.__TAURI__?.core?.invoke;
  const humanLabel = key => String(key).replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, character => character.toUpperCase());
  const valueText = value => value === null || value === undefined ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const cellText = value => valueText(value).replace(/[\t\r\n]+/g, ' ');
  function tableText(rows, unitFor = () => null) {
    const keys = [...new Set(rows.flatMap(row => Object.keys(row)))];
    return [keys.map(key => `${humanLabel(key)}${unitFor(key) ? ` (${unitFor(key)})` : ''}`).join('\t'), ...rows.map(row => keys.map(key => cellText(row[key])).join('\t'))].join('\n');
  }
  function snapshotText(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') throw Error('Select a complete result first.');
    const lines = [snapshot.title || 'OfficeKit result'];
    const unitFor = (key, section) => snapshot.units?.[section]?.[key] ?? (typeof window.officekitResultFieldUnit === 'function' ? window.officekitResultFieldUnit(snapshot, key, section) : null);
    for (const [label, data] of [['Inputs', snapshot.inputs], ['Results', snapshot.result]]) {
      if (!data || typeof data !== 'object') continue;
      lines.push('', label);
      for (const [key, value] of Object.entries(data)) {
        if (Array.isArray(value) && value.every(row => row && typeof row === 'object' && !Array.isArray(row))) {
          lines.push(humanLabel(key), tableText(value, name => unitFor(name, 'table')));
        } else {
          const unit = unitFor(key, label === 'Inputs' ? 'inputs' : 'results');
          lines.push(`${humanLabel(key)}: ${valueText(value)}${unit ? ` ${unit}` : ''}`);
        }
      }
    }
    if (Array.isArray(snapshot.assumptions) && snapshot.assumptions.length) lines.push('', 'Assumptions', ...snapshot.assumptions.map(valueText));
    else if (typeof snapshot.assumptions === 'string' && snapshot.assumptions) lines.push('', 'Assumptions', snapshot.assumptions);
    return lines.join('\n');
  }
  async function copyText(text) {
    if (typeof text !== 'string' || !text.length) throw Error('There is no result to copy.');
    if (new TextEncoder().encode(text).byteLength > COPY_LIMIT) throw Error('Too large to copy—download the complete result.');
    try {
      if (typeof invoke() === 'function') await invoke()('result_copy_text', { text });
      else {
        if (typeof navigator.clipboard?.writeText !== 'function') throw Error('Unavailable');
        await navigator.clipboard.writeText(text);
      }
      return { state: 'copied' };
    } catch { throw Error('Clipboard access failed. Download the result instead.'); }
  }
  async function downloadBlob(blob, fileName) {
    if (!(blob instanceof Blob) || blob.size > SAVE_LIMIT) throw Error('Result exceeds the 64 MiB save limit.');
    if (typeof fileName !== 'string' || !fileName.length || fileName.length > 200 || /[\/\\\x00-\x1f]/.test(fileName) || /^\.+$/.test(fileName)) throw Error('Choose a valid filename.');
    if (typeof invoke() === 'function') {
      try {
        const bytes = new Uint8Array(await blob.arrayBuffer());
        const chunks = [];
        for (let index = 0; index < bytes.length; index += 32768) chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768)));
        const outcome = await invoke()('result_save', { suggestedName: fileName, base64Data: btoa(chunks.join('')) });
        if (outcome === null) return { state: 'cancelled', name: fileName };
        if (outcome?.state !== 'saved') throw Error('Invalid outcome');
        return { state: 'saved', name: outcome.name || fileName };
      } catch { throw Error('The result could not be saved. Try another destination.'); }
    }
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch { throw Error('The download could not be started. Try again.'); }
    finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
    return { state: 'download-started', name: fileName };
  }
  function tableFormats(rows) {
    if (!Array.isArray(rows) || !rows.every(row => row && typeof row === 'object' && !Array.isArray(row))) throw Error('A complete table is required.');
    rows = rows.map(row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, value && typeof value === 'object' ? JSON.parse(JSON.stringify(value)) : value])));
    const keys = [...new Set(rows.flatMap(row => Object.keys(row)))];
    const csvCell = value => {
      let text = valueText(value);
      if (typeof value === 'string' && /^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
      return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    return [
      { id: 'txt', label: 'Text (tab-separated)', extension: 'txt', mime: 'text/plain;charset=utf-8', serialize: () => tableText(rows) },
      { id: 'csv', label: 'CSV spreadsheet', extension: 'csv', mime: 'text/csv;charset=utf-8', serialize: () => [keys.map(csvCell).join(','), ...rows.map(row => keys.map(key => csvCell(row[key])).join(','))].join('\r\n') },
      { id: 'json', label: 'JSON data', extension: 'json', mime: 'application/json', serialize: () => JSON.stringify(rows, null, 2) },
    ];
  }
  function csvToTsv(csv) {
    if (typeof csv !== 'string' || !csv.length) throw Error('CSV result is empty or invalid.');
    const rows = [];
    let row = [], field = '', quoted = false, closed = false;
    const pushField = () => { row.push(field); field = ''; closed = false; };
    const pushRow = () => { pushField(); rows.push(row); row = []; };
    for (let index = 0; index < csv.length; index++) {
      const character = csv[index];
      if (quoted) {
        if (character === '"') {
          if (csv[index + 1] === '"') { field += '"'; index++; }
          else { quoted = false; closed = true; }
        } else field += character;
      } else if (character === ',') pushField();
      else if (character === '\n' || character === '\r') {
        if (character === '\r' && csv[index + 1] === '\n') index++;
        pushRow();
      } else if (character === '"') {
        if (field || closed) throw Error('CSV result contains malformed quoting.');
        quoted = true;
      } else {
        if (closed) throw Error('CSV result contains malformed quoting.');
        field += character;
      }
    }
    if (quoted) throw Error('CSV result contains incomplete quoting.');
    if (field || row.length || closed || !/[\r\n]$/.test(csv)) pushRow();
    if (!rows.length || rows.some(cells => cells.length !== rows[0].length)) throw Error('CSV result contains inconsistent rows.');
    return rows.map(cells => cells.map(value => {
      let cell = value.replace(/[\t\r\n]+/g, ' ');
      if (/^\s*[=+@]/.test(cell) || /^\s*-/.test(cell) && !/^\s*-\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*$/.test(cell)) cell = `'${cell}`;
      return cell;
    }).join('\t')).join('\n');
  }
  function chooseFormat(formats, title) {
    if (formats.length === 1) return Promise.resolve(formats[0]);
    return new Promise(resolve => {
      const previous = document.activeElement;
      const dialog = document.createElement('dialog');
      dialog.className = 'modal officekit-download-dialog';
      const box = document.createElement('div');
      box.className = 'modal-box';
      const heading = document.createElement('h2');
      heading.className = 'text-lg font-bold';
      heading.textContent = `Download ${title || 'result'}`;
      const label = document.createElement('label');
      label.textContent = 'File format';
      const select = document.createElement('select');
      select.className = 'select ';
      for (const format of formats) {
        const option = document.createElement('option');
        option.value = format.id;
        option.textContent = format.label;
        select.append(option);
      }
      label.className = 'form-control mt-4 w-full';
      label.append(select);
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'btn btn-outline';
      cancel.textContent = 'Cancel';
      const submit = document.createElement('button');
      submit.type = 'button';
      submit.className = 'btn btn-primary';
      submit.textContent = 'Continue';
      const actions = document.createElement('div');
      actions.className = 'modal-action';
      actions.append(cancel, submit);
      let finished = false;
      const finish = value => {
        if (finished) return;
        finished = true;
        dialog.close();
        dialog.remove();
        previous?.focus?.();
        resolve(value);
      };
      cancel.onclick = () => finish(null);
      submit.onclick = () => finish(formats.find(format => format.id === select.value));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
      box.append(heading, label, actions);
      dialog.append(box);
      document.body.append(dialog);
      dialog.showModal();
      select.focus();
    });
  }
  function registerCapability(toolId, capability) {
    if (typeof toolId !== 'string' || !toolId || toolId.length > 100 || !capability || typeof capability !== 'object') throw Error('A valid result capability is required.');
    capabilities.set(toolId, { ...capability, toolId });
    return capabilities.get(toolId);
  }
  function mountActions(container, capability) {
    if (!container || !capability) throw Error('A result container and capability are required.');
    capability = { ...capability, snapshot: capability.snapshot ? JSON.parse(JSON.stringify(capability.snapshot)) : undefined };
    container.querySelector('.officekit-result-actions')?.remove();
    const row = document.createElement('div');
    row.className = 'officekit-result-actions';
    const copy = document.createElement('button');
    copy.className = 'btn btn-outline';
    copy.type = 'button';
    copy.textContent = capability.copyLabel || 'Copy';
    const download = document.createElement('button');
    download.className = 'btn btn-primary officekit-result-download';
    download.type = 'button';
    download.textContent = 'Download';
    const status = document.createElement('span');
    status.className = 'officekit-result-action-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const getText = () => typeof capability.text === 'function' ? capability.text() : capability.text ?? (capability.snapshot ? snapshotText(capability.snapshot) : null);
    const initial = getText();
    copy.disabled = !capability.copy && (typeof initial !== 'string' || !initial.length || new TextEncoder().encode(initial).byteLength > COPY_LIMIT);
    if (typeof initial === 'string' && new TextEncoder().encode(initial).byteLength > COPY_LIMIT) officekitOutcome.show(status, { state: 'error', text: 'Too large to copy—download the complete result.' });
    download.disabled = !capability.download && !capability.formats?.length && !capability.snapshot;
    let disposed = false;
    const run = async (button, pending, action) => {
      button.disabled = true;
      officekitOutcome.show(status, { state: 'working', text: pending });
      try {
        const outcome = await action();
        if (disposed) return;
        const text = outcome?.state === 'cancelled' ? '' : outcome?.state === 'saved' ? `Saved ${outcome.name || 'result'}.` : outcome?.state === 'download-started' ? `Download started: ${outcome.name}.` : outcome?.state === 'dialog-opened' ? '' : button === copy ? 'Copied to clipboard.' : 'Download requested.';
        if (text) officekitOutcome.show(status, { state: 'success', text }); else officekitOutcome.clear(status);
      } catch (error) { if (!disposed) officekitOutcome.show(status, { state: 'error', text: error?.message || 'The action failed. Try again.' }); }
      finally { if (!disposed) button.disabled = false; }
    };
    copy.onclick = () => run(copy, 'Copying…', () => capability.copy ? capability.copy() : copyText(getText()));
    download.onclick = () => run(download, 'Preparing download…', async () => {
      if (capability.download) return capability.download();
      if (capability.snapshot && !capability.formats?.length) {
        if (typeof window.officekitOpenResultExport !== 'function') throw Error('Download is unavailable. Try again.');
        window.officekitOpenResultExport(capability.snapshot);
        return { state: 'dialog-opened' };
      }
      const format = await chooseFormat(capability.formats, capability.title);
      if (!format) return { state: 'cancelled' };
      const content = await format.serialize();
      const blob = content instanceof Blob ? content : new Blob([content], { type: format.mime });
      const baseName = (capability.fileName || capability.toolId || 'officekit-result').replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 150);
      return downloadBlob(blob, `${baseName}.${format.extension}`);
    });
    row.append(copy, download, status);
    // An inline row sits at the top of its panel as small header actions and stays out of the bottom bar.
    if (capability.inline) {
      row.classList.add('officekit-result-actions--inline');
      copy.className = 'btn btn-outline btn-sm';
      download.className = 'btn btn-outline btn-sm officekit-result-download';
      container.prepend(row);
    } else container.append(row);
    return { element: row, dispose() { disposed = true; row.remove(); } };
  }
  Object.assign(window, {
    officekitCopyResultText: copyText, officekitDownloadResultBlob: downloadBlob,
    officekitResultSnapshotText: snapshotText, officekitResultTableFormats: tableFormats,
    officekitCsvToTsv: csvToTsv, officekitUnregisterResultCapability: toolId => capabilities.delete(toolId),
    officekitRegisterResultCapability: registerCapability, officekitGetResultCapability: toolId => capabilities.get(toolId),
    officekitMountResultActions: mountActions,
  });
})();
