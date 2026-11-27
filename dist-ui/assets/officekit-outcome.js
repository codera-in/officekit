// One outcome slot for every action. Success, working and failure look the same on every tool.
// The slot is the action dock's status element; the icon comes from CSS so textContent is only the words.
(function (global) {
  'use strict';
  // info is a neutral hint with no icon; anything unknown falls back to it.
  const STATES = {
    success: { role: 'status' },
    working: { role: 'status' },
    error: { role: 'alert' },
    info: { role: 'status' },
  };

  // Bottom action bar groups. A message raised from inside one of these is shown as a toast (success) or a popup (error);
  // the slot itself keeps the text for screen readers and tests but is not drawn in the bar.
  const DOCK = '.ok-action-dock,.officekit-result-actions,.officekit-result-action-status,.ok-pdf-dock,.ok-storage-footer,.ok-invoice-actions,.ok-invoice-folder-actions,.ok-trash-dock,#direct-file-actions,#direct-file-status,#officekit-tool-actions';
  const TOAST_MS = 4000;
  let toastTimer = null;
  const inDock = slot => !!slot.closest?.(DOCK);

  function toast(text, doc = document) {
    let node = doc.getElementById('ok-toast');
    if (!node) {
      node = doc.createElement('div');
      node.id = 'ok-toast'; node.className = 'ok-toast'; node.setAttribute('role', 'status'); node.setAttribute('aria-live', 'polite');
      doc.body.append(node);
    }
    node.textContent = text;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, TOAST_MS);
  }

  function popup(text, recovery = '', doc = document) {
    let dialog = doc.getElementById('ok-error-dialog');
    if (!dialog) {
      dialog = doc.createElement('dialog');
      dialog.id = 'ok-error-dialog'; dialog.className = 'modal ok-error-dialog'; dialog.setAttribute('aria-labelledby', 'ok-error-title');
      dialog.innerHTML = '<div class="modal-box"><h2 id="ok-error-title">That did not work</h2><p id="ok-error-text"></p><p id="ok-error-recovery" class="ok-error-dialog__recovery"></p>' +
        '<div class="ok-error-dialog__row"><button type="button" class="btn" id="ok-error-report" hidden>Report issue</button><button type="button" class="btn btn-primary" id="ok-error-close">Close</button></div></div>';
      doc.body.append(dialog);
      dialog.querySelector('#ok-error-close').addEventListener('click', () => dialog.close());
      dialog.querySelector('#ok-error-report').addEventListener('click', () => {
        const message = dialog.querySelector('#ok-error-text').textContent;
        dialog.close();
        if (typeof globalThis.officekitOpenBugReport === 'function') globalThis.officekitOpenBugReport({ errorMessage: message, source: 'popup' });
      });
    }
    dialog.querySelector('#ok-error-text').textContent = text;
    const note = dialog.querySelector('#ok-error-recovery');
    note.textContent = recovery; note.hidden = !recovery;
    dialog.querySelector('#ok-error-report').hidden = typeof globalThis.officekitOpenBugReport !== 'function';
    if (!dialog.open) dialog.showModal?.();
    dialog.querySelector('#ok-error-close').focus?.();
  }

  // A locked app answers with license_required. That is a state, not a fault: it never becomes a toast, a popup or text.
  function isLicenseRequired(value) {
    if (typeof value === 'string') return value.includes('license_required');
    return !!value && typeof value === 'object'
      && [value.message, value.code, value.error?.code, value.error?.message].some(part => typeof part === 'string' && part.includes('license_required'));
  }

  function show(slot, { state = 'info', text = '', recovery = '' } = {}) {
    if (!slot) return;
    if (isLicenseRequired(text)) { clear(slot); return; }
    const style = STATES[state] || STATES.info;
    // Only this helper's own class changes, so a slot keeps the layout class its screen gave it.
    slot.classList.add('ok-outcome');
    slot.dataset.state = STATES[state] ? state : 'info';
    slot.setAttribute('role', style.role);
    slot.textContent = text;
    if (recovery) {
      const note = slot.ownerDocument.createElement('small');
      note.className = 'ok-outcome__recovery';
      note.textContent = recovery;
      slot.append(note);
    }
    if (text && inDock(slot) && slot.ownerDocument?.body) {
      if (state === 'success') toast(text, slot.ownerDocument);
      else if (state === 'error') popup(text, recovery, slot.ownerDocument);
    }
  }

  function clear(slot) {
    if (!slot) return;
    slot.classList.remove('ok-outcome');
    delete slot.dataset.state;
    slot.textContent = '';
  }

  // Page code calls officekitOutcome as a bare name, so it must sit on the global object itself.
  const api = { show, clear, toast, popup, isLicenseRequired, dock: DOCK };
  global.officekitOutcome = api;
  globalThis.officekitOutcome = api;
})(typeof window !== 'undefined' ? window : globalThis);
