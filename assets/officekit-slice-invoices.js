// Invoice workbench. Keep registry destinations explicit for catalogue/routing checks.
window.OfficeKitExtensions.register({
  slice: 'invoices',
  destinations: {
    invoice_manager: { tab: 'invoices', sliceView: 'documents' },
  },
  tabs: ['invoices'],
  openView(view) { return window.OfficeKitInvoices.open(view); },
});

(function invoiceWorkbenchModule() {
  'use strict';
  const ROOT = '/api/invoice-libraries';
    const copy = value => JSON.parse(JSON.stringify(value));
  const PRESETS = Object.freeze([
    ['USD', 'US dollar', '$', 2], ['EUR', 'Euro', '€', 2], ['GBP', 'British pound', '£', 2],
    ['JPY', 'Japanese yen', '¥', 0], ['INR', 'Indian rupee', '₹', 2], ['CAD', 'Canadian dollar', 'CA$', 2],
    ['AUD', 'Australian dollar', 'A$', 2], ['CHF', 'Swiss franc', 'CHF', 2], ['AED', 'UAE dirham', 'AED', 2],
    ['SGD', 'Singapore dollar', 'S$', 2], ['CNY', 'Chinese yuan', 'CN¥', 2], ['KWD', 'Kuwaiti dinar', 'KWD', 3],
  ]);

  // Formatting only: all financial arithmetic stays in the authoritative backend.
  function formatMoney(raw, currency) {
    const negative = String(raw).startsWith('-');
    const [whole, fractional = ''] = String(raw).replace(/^-/, '').split('.');
    let integer = whole;
    if (currency.grouping === 'western') integer = whole.replace(/\B(?=(\d{3})+(?!\d))/g, currency.grouping_separator);
    if (currency.grouping === 'indian' && whole.length > 3) integer = `${whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, currency.grouping_separator)}${currency.grouping_separator}${whole.slice(-3)}`;
    const fraction = fractional.padEnd(currency.precision, '0').slice(0, currency.precision);
    const sign = negative ? '−' : '';
    const amount = `${sign}${integer}${currency.precision ? currency.decimal_separator + fraction : ''}`;
    return { before: `${currency.symbol}${amount}`, after: `${amount} ${currency.symbol}`, code: `${currency.code} ${amount}` }[currency.placement];
  }

  function currencyPreset(code, uuid) {
    const preset = PRESETS.find(item => item[0] === code);
    if (!preset) throw new Error('Choose a supported preset or enter a custom currency.');
    return { id: uuid(), code: preset[0], name: preset[1], symbol: preset[2], precision: preset[3], placement: 'before', grouping: code === 'INR' ? 'indian' : 'western', decimal_separator: '.', grouping_separator: ',' };
  }

  function newBusiness(uuid) {
    const currency = currencyPreset('USD', uuid);
    const template = { id: uuid(), name: 'Classic', layout: 'Classic', paper: 'A4', logo_id: null, logo_size: 'medium', logo_placement: 'left', accent: '#16749a', labels: {}, columns: ['description', 'quantity', 'rate', 'amount'], footer: '' };
    const noTax = { id: uuid(), name: 'No tax', inclusive: false, rows: [] };
    return { profile_name: '', name: '', address: '', contact: '', registrations: [], currencies: [currency], default_currency_id: currency.id, tax_profiles: [noTax], default_tax_profile_id: noTax.id, templates: [template], default_template_id: template.id, payment_methods: [], numbering: { invoice_prefix: 'INV-', quote_prefix: 'QUO-', estimate_prefix: 'EST-', next_counter: 1, padding: 3, reset: 'never' } };
  }

  function create(deps) {
    const { document: doc, fetch: fetchImpl, invoke, uuid, storage, now, download, objectUrl, revokeUrl, openEmail, apiUrl } = deps;
    const state = { library: null, businesses: [], businessId: '', clients: [], items: [], documents: [], schedules: [], bindings: [], view: 'documents', editor: null, settings: null, wizard: null, logoPreviewUrl: '', logoPreviewId: '', catalogue: null, schedule: null, report: null, history: [], historyBusinessId: '', backupSelection: null, restoreSelection: null, search: '', status: '', error: '', message: '', busy: false, previewUrl: '', previewStale: false, fieldErrors: {}, recovery: null };
    const fields = new Map();
    const screen = doc.createElement('section');
    screen.id = 'tab-invoices'; screen.className = 'hidden ok-invoices'; screen.setAttribute('aria-labelledby', 'invoice-heading');
    doc.getElementById('app-main').append(screen);
    const prefix = () => `${ROOT}/${encodeURIComponent(state.library.id)}`;
    const business = () => state.businesses.find(item => item.id === state.businessId);

    function element(tag, text, className = '', parent = screen) {
      const node = doc.createElement(tag); node.textContent = text; node.className = className; parent.append(node); return node;
    }
    function action(label, handler, parent, primary = false, inline = false) {
      const node = element('button', label, inline ? 'ok-text-link' : `btn${primary ? ' btn-primary' : ''}`, parent);
      node.type = 'button'; node.disabled = state.busy;
      node.addEventListener('click', () => run(handler, node.textContent.trim())); return node;
    }
    function inlineAction(label, handler, parent) {
      const node = doc.createElement('a'); node.href = '#'; node.className = 'ok-text-link'; node.textContent = label;
      node.addEventListener('click', event => { event.preventDefault(); return run(() => handler(node), node.textContent.trim()); }); parent.append(node); return node;
    }
    function field(parent, label, record, key, options = {}) {
      const wrapper = element('label', label, 'ok-invoice-field', parent);
      const input = element(options.choices ? 'select' : options.multiline ? 'textarea' : 'input', '', options.choices ? 'select' : options.multiline ? 'textarea' : 'input', wrapper);
      const id = `invoice-${fields.size}`; input.id = id; wrapper.htmlFor = id;
      if (options.choices) {
        for (const choice of options.choices) {
          const option = element('option', choice[1], '', input); option.value = choice[0];
        }
      } else if (!options.multiline) input.type = options.type || 'text';
      input.value = String(record[key] ?? '');
      if (options.maxLength) input.maxLength = options.maxLength;
      if (options.required) { input.required = true; input.setAttribute('aria-required', 'true'); }
      if (state.fieldErrors[key]) { input.setAttribute('aria-invalid', 'true'); const error = element('span', state.fieldErrors[key], 'ok-invoice-field-error', wrapper); error.setAttribute('role', 'alert'); }
      input.addEventListener('change', () => {
        record[key] = options.number ? Number(input.value) : input.value;
        if (state.fieldErrors[key]) { delete state.fieldErrors[key]; wrapper.querySelector('.ok-invoice-field-error')?.remove(); input.removeAttribute('aria-invalid'); }
        if (state.view === 'editor' && (record === state.editor || record === state.editor?.discount || state.editor?.lines.includes(record))) markPreviewStale();
        if (state.schedule?.error && (record === state.schedule.draft || state.schedule.draft?.lines.includes(record))) { state.schedule.error = ''; state.schedule.errorTarget = ''; wrapper.querySelector('.ok-invoice-field-error')?.remove(); input.removeAttribute('aria-invalid'); }
        persistDraft();
      });
      fields.set(id, { input, record, key, label }); return input;
    }
    function grid(parent) { return element('div', '', 'ok-invoice-grid', parent); }
    function details(parent, title) { const node = element('details', '', '', parent); element('summary', title, '', node); return node; }
    function heading(title, subtitle) { const head = element('header', '', 'ok-invoice-heading'); const titleNode = element('h1', title, '', head); titleNode.id = 'invoice-heading'; element('p', subtitle, 'ok-invoice-muted', head); return head; }
    function footer(message) { const node = element('footer', '', 'ok-invoice-actions'); if (message) node.dataset.officekitActionContext = message; return element('div', '', 'ok-invoice-action-buttons', node); }
    function rows(parent, headers, records, cells) {
      const wrapper = element('div', '', 'ok-invoice-table-scroll', parent); const table = element('table', '', 'table', wrapper);
      const tr = element('tr', '', '', element('thead', '', '', table)); headers.forEach(label => element('th', label, '', tr));
      const body = element('tbody', '', '', table);
      records.forEach(record => { const row = element('tr', '', '', body); cells(record).forEach(value => { const cell = element('td', '', '', row); if (typeof value === 'object') cell.append(value); else cell.textContent = value; }); });
      if (!records.length) element('p', 'No matching records.', 'ok-invoice-muted', parent);
    }
    async function request(path, method = 'GET', body = null, binary = false) {
      const options = { method, headers: { 'Content-Type': 'application/json' } };
      if (body !== null) options.body = JSON.stringify(body);
      const response = await fetchImpl(apiUrl(path), options);
      if (!response.ok) {
        let payload;
        try { payload = await response.json(); } catch { payload = {}; }
        const error = new Error(payload.error?.message || payload.detail || `Invoice request failed (${response.status}).`);
        error.status = response.status; error.details = payload.error?.details || []; throw error;
      }
      if (binary) return response.blob();
      const result = await response.json();
      if (!result || typeof result !== 'object') throw new Error('OfficeKit returned an invalid invoice response.');
      return result;
    }
    async function page(resource, query = '') {
      let cursor = ''; const items = []; const seen = new Set();
      do {
        const result = await request(`${prefix()}/${resource}${query}${cursor ? `${query ? '&' : '?'}cursor=${encodeURIComponent(cursor)}` : ''}`);
        if (!Array.isArray(result.items) || (result.next_cursor && seen.has(result.next_cursor))) throw new Error('OfficeKit returned an invalid invoice list.');
        items.push(...result.items); cursor = result.next_cursor; seen.add(cursor);
      } while (cursor);
      return items;
    }
    function revision() { return state.library.revision; }
    function adopted(result) {
      const next = result.library_revision;
      if (!Number.isInteger(next)) throw new Error('OfficeKit returned an invalid library revision.');
      state.library.revision = next;
      return result;
    }
    async function mutate(resource, body, method = 'POST') { return adopted(await request(`${prefix()}/${resource}`, method, { ...body, expected_revision: revision() })); }
    function persistDraft() {
      if (state.editor && state.library) {
        const recovery = { libraryId: state.library.id, businessId: state.editor.business_id, editor: state.editor };
        try { storage.setItem('officekit.invoice-draft.v1', JSON.stringify(recovery)); } catch { state.message = 'Draft recovery storage is unavailable. Keep this window open until you save.'; }
      }
    }
    function restoreDraft() {
      try {
        const saved = JSON.parse(storage.getItem('officekit.invoice-draft.v1') || 'null');
        if (saved && saved.libraryId === state.library.id) state.recovery = saved;
      } catch { state.message = 'A previous draft recovery copy could not be read.'; }
    }
    async function refresh() {
      state.library = await request(prefix());
      state.businesses = await page('businesses');
      if (!state.businesses.some(item => item.id === state.businessId)) state.businessId = state.businesses[0]?.id || '';
      if (state.businessId) {
        const query = `?business_id=${encodeURIComponent(state.businessId)}`;
        [state.clients, state.items, state.documents, state.schedules] = await Promise.all(['clients', 'items', 'documents', 'schedules'].map(resource => page(resource, query)));
      } else { state.clients = []; state.items = []; state.documents = []; state.schedules = []; }
    }
    async function chooseFolder() {
      const selection = await invoke('file_selection_open', { mode: 'folder', access: 'read-write' });
      if (selection === null) return;
      state.library = await request(ROOT, 'POST', { selection_id: selection.id });
      state.editor = null; state.settings = null; await refresh(); restoreDraft();
    }
    async function reconnect(id) { state.library = await invoke('invoice_library_reconnect', { bindingId: id }); await refresh(); restoreDraft(); }
    async function open(view = 'documents') {
      screen.className = 'ok-invoices';
      state.view = view;
      await run(async () => {
        if (state.library) {
          await refresh();
          if (state.schedules.some(schedule => !schedule.paused && schedule.catch_up === 'each')) {
            const batch = await mutate('recurring-draft-batches', { approved_schedule_ids: [] });
            if (batch.created_document_ids.length) { await refresh(); state.message = `${batch.created_document_ids.length} recurring drafts are ready for review.`; }
          }
        }
        else { const result = await request(ROOT); if (!Array.isArray(result.items)) throw new Error('OfficeKit returned an invalid folder list.'); state.bindings = result.items; }
      });
    }
    function focusAction(label) {
      if (!label) return;
      const target = [...screen.querySelectorAll('button,a')].find(node => node.textContent.trim() === label);
      if (target) target.focus();
    }
    async function run(work, focusLabel = '') {
      if (state.busy) return;
      state.busy = true; state.error = ''; render();
      if (focusLabel) focusAction(focusLabel);
      try { await work(); }
      catch (error) {
        state.error = error.message; persistDraft();
        if (error.status === 409) state.error += ' Your draft is preserved. Reconnect or reload the folder before reviewing changes.';
        if (error.status === 422 && error.details.length) state.error += ` ${error.details[0].message || 'Review the invoice details and try again.'}`;
      } finally {
        state.busy = false; render();
        const invalidField = state.focusFieldAfterRun;
        state.focusFieldAfterRun = '';
        if (invalidField) [...fields.values()].find(item => item.key === invalidField)?.input.focus();
        const nextFocus = state.focusAfterWizard || focusLabel;
        state.focusAfterWizard = '';
        if (!state.error && !invalidField) focusAction(nextFocus);
      }
    }
    async function navigate(view) { persistDraft(); state.message = ''; state.error = ''; if (view === 'reports') state.report = null; state.view = view; state.catalogue = null; state.clientReturn = false; state.schedule = null; render(); if (view === 'reports') await loadReport(); if (view === 'history') state.history = await page('history'); render(); }
    function profileLabel(profile) { const currency = profile.currencies.find(item => item.id === profile.default_currency_id); return `${profile.profile_name || profile.name} · ${currency.code}`; }
    function currencyOf(record) { return record.currency; }
    function totalOf(record) { return record.totals.total; }
    function recordLink(label, work) { const link = doc.createElement('button'); link.type = 'button'; link.className = 'ok-row-action'; link.textContent = label; link.addEventListener('click', () => run(work)); return link; }

    function render() {
      fields.clear(); screen.replaceChildren();
      if (!state.library) {
        heading('Invoices', 'Create invoices and branded PDFs in a folder you control.');
        action('Choose folder', chooseFolder, screen, true);
        state.bindings.forEach(binding => screen.append(recordLink(`Open ${binding.label}`, () => reconnect(binding.id))));
      } else {
        heading('Invoices', `${state.library.label} · ${state.library.status}`);
        const top = grid(screen);
        const select = field(top, 'Business profile', state, 'businessId', { choices: state.businesses.map(item => [item.id, profileLabel(item)]) });
        select.addEventListener('change', () => { if (state.view === 'reports') state.report = null; return run(async () => { persistDraft(); await refresh(); state.editor = null; state.settings = null; if (state.view === 'reports') { reportQuery.currency_id = business().default_currency_id; await loadReport(); } }); });
        const nav = element('nav', '', 'tabs tabs-border', screen); nav.setAttribute('aria-label', 'Invoice sections');
        [['documents', 'Documents'], ['catalogue', 'Clients & items'], ['recurring', 'Recurring'], ['reports', 'Reports'], ['settings', 'Settings'], ['folder', 'Data folder']].forEach(([key, label]) => {
          const tab = element('button', label, `tab${state.view === key ? ' tab-active' : ''}`, nav); tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(state.view === key)); tab.addEventListener('click', () => run(() => navigate(key)));
        });
        if (!state.businesses.length && state.view !== 'folder') {
          state.view = 'settings'; state.settings = state.settings || newBusiness(uuid);
          if (!state.wizard && !state.profileWizardDismissed) state.wizard = { step: 1, mode: 'new', returnView: 'documents', record: state.settings, currencyCode: 'USD', layout: 'Classic' };
        }
        const views = { documents: renderDocuments, catalogue: renderCatalogue, recurring: renderRecurring, reports: renderReports, settings: renderSettings, folder: renderFolder, editor: renderEditor, restore: renderRestore, history: renderHistory };
        views[state.view]();
        if (state.wizard) renderProfileWizard();
      }
      if (state.error && !state.wizard) { const error = element('p', state.error, 'ok-invoice-error'); error.setAttribute('role', 'alert'); error.tabIndex = -1; error.focus(); }
      if (state.message) { const message = element('p', state.message, 'ok-invoice-muted'); message.setAttribute('role', 'status'); }
    }

    function renderDocuments() {
      const toolbar = grid(screen); const search = field(toolbar, 'Search documents', state, 'search'); search.addEventListener('change', render);
      const status = field(toolbar, 'Status', state, 'status', { choices: [['', 'All statuses'], ...['Draft', 'Issued', 'Partially paid', 'Paid', 'Overdue', 'Void', 'Accepted', 'Declined', 'Expired'].map(item => [item, item])] }); status.addEventListener('change', render);
      action('New document', newDocument, screen, true);
      const matches = state.documents.filter(record => `${record.number} ${record.client.name}`.toLowerCase().includes(state.search.toLowerCase()) && (!state.status || record.status === state.status));
      rows(screen, ['Document', 'Client', 'Due', 'Total', 'Balance', 'Status'], matches, record => [recordLink(record.number, () => editDocument(record)), record.client.name, record.draft.due_date || record.draft.valid_until || '—', formatMoney(totalOf(record), currencyOf(record)), formatMoney(record.balance, currencyOf(record)), record.status]);
      if (state.recovery) screen.append(recordLink('Review recovered draft', async () => { state.businessId = state.recovery.businessId; state.editor = state.recovery.editor; state.view = 'editor'; }));
    }
    function newDocument() {
      const profile = business(); const today = now();
      state.editor = { business_id: profile.id, kind: 'invoice', client_id: state.clients[0]?.id || '', currency_id: profile.default_currency_id, tax_profile_id: profile.default_tax_profile_id, template_id: profile.default_template_id, issue_date: today, due_date: today, valid_until: today, lines: [{ description: '', quantity: '1', rate: '0', unit: '', tax_exempt: false }], discount: { kind: 'none', value: '0' }, notes: '', terms: '', payment_method_ids: profile.payment_methods.filter(item => item.enabled).map(item => item.id) };
      state.fieldErrors = {}; clearInvoicePreview(); state.view = 'editor'; persistDraft();
    }
    function draftPayload() {
      const record = copy(state.editor);
      const allowed = ['business_id', 'kind', 'client_id', 'currency_id', 'tax_profile_id', 'template_id', 'issue_date', 'due_date', 'valid_until', 'lines', 'discount', 'notes', 'terms', 'payment_method_ids'];
      const payload = Object.fromEntries(allowed.map(key => [key, record[key]]));
      payload.lines.forEach(line => { line.tax_exempt = line.tax_exempt === true || line.tax_exempt === 'true'; line.date = line.date || null; });
      return payload;
    }
    function adoptDocument(record) { return { ...record.draft, ...record }; }
    async function editDocument(record) { clearInvoicePreview(); state.fieldErrors = {}; state.editor = adoptDocument(await request(`${prefix()}/documents/${record.id}`)); state.view = 'editor'; }
    function validateDocumentClient() {
      if (!state.editor.client_id) {
        state.fieldErrors.client_id = 'Choose a client before saving or issuing this document.';
        state.focusFieldAfterRun = 'client_id';
        state.error = '';
        return false;
      }
      return true;
    }
    async function saveDocument() {
      if (!validateDocumentClient()) return false;
      const resource = state.editor.id ? `documents/${state.editor.id}` : 'documents';
      const method = state.editor.id ? 'PUT' : 'POST';
      state.editor = adoptDocument(await mutate(resource, draftPayload(), method));
      storage.removeItem('officekit.invoice-draft.v1'); state.recovery = null; await refresh(); state.message = 'Draft saved.';
      return true;
    }
    async function transition(actionName) {
      if (!state.editor.id) { if (!(await saveDocument())) return; }
      else if (actionName === 'issue' && !validateDocumentClient()) return;
      state.editor = adoptDocument(await mutate(`documents/${state.editor.id}/transitions`, { action: actionName })); await refresh();
    }
    async function showPreview() {
      const blob = await request(`${prefix()}/document-previews`, 'POST', { draft: draftPayload(), expected_revision: revision() }, true);
      if (state.previewUrl) revokeUrl(state.previewUrl);
      state.previewUrl = objectUrl(blob); state.previewStale = false;
    }
    function markPreviewStale() {
      state.previewStale = true;
      if (!state.previewUrl) return;
      const preview = screen.querySelector('.ok-invoice-preview');
      if (!preview) return;
      const iframe = preview.querySelector('iframe');
      if (!preview.querySelector('.ok-invoice-preview-stale')) { const stale = element('p', 'Preview out of date · refresh to review current invoice.', 'ok-invoice-preview-stale', preview); stale.setAttribute('role', 'status'); if (iframe) preview.insertBefore(stale, iframe); }
      if (iframe) iframe.title = 'Out-of-date invoice PDF preview';
    }
    function clearInvoicePreview() { if (state.previewUrl) revokeUrl(state.previewUrl); state.previewUrl = ''; state.previewStale = false; }
    async function exportPdf() {
      if (state.editor.archive_status === 'pending') state.editor = adoptDocument(await mutate(`documents/${state.editor.id}/archives`, {}));
      const blob = state.editor.id && state.editor.state !== 'draft' ? await request(`${prefix()}/documents/${state.editor.id}/pdf`, 'GET', null, true) : await request(`${prefix()}/document-previews`, 'POST', { draft: draftPayload(), expected_revision: revision() }, true);
      await download(blob, 'invoice.pdf');
    }
    function selectItem(line, itemId) {
      const item = state.items.find(record => record.id === itemId);
      Object.assign(line, { item_id: item.id, description: item.description, quantity: item.quantity, rate: item.rate, unit: item.unit, tax_exempt: item.tax_exempt }); markPreviewStale(); persistDraft(); render();
    }
    const NEW_CLIENT = '__new_client__';
    async function openNewClient() {
      state.clientReturn = true; state.view = 'catalogue';
      state.catalogue = { type: 'clients', record: { business_id: state.businessId, name: '', address: '', email: '', contact: '', customer_reference: '', terms_days: 14, tax_profile_id: null, archived: false } };
    }
    function renderEditor() {
      const record = state.editor; const issued = record.state && record.state !== 'draft';
      const body = element('div', '', 'ok-invoice-editor'); const form = element('div', '', '', body); const preview = element('aside', '', 'ok-invoice-preview', body);
      element('h2', record.number || 'New document', '', form);
      if (!issued) {
        const basics = grid(form);
        field(basics, 'Document type', record, 'kind', { choices: [['invoice', 'Invoice'], ['quote', 'Quote'], ['estimate', 'Estimate']] });
        const client = field(basics, 'Client', record, 'client_id', { choices: [['', 'Choose a client'], ...state.clients.map(item => [item.id, item.name]), [NEW_CLIENT, '+ New client']] });
        client.addEventListener('change', () => { if (client.value === NEW_CLIENT) { record.client_id = ''; persistDraft(); void run(() => openNewClient()); } });
        field(basics, 'Currency', record, 'currency_id', { choices: business().currencies.map(item => [item.id, `${item.code} — ${item.name}`]) });
        field(basics, 'Tax profile', record, 'tax_profile_id', { choices: business().tax_profiles.map(item => [item.id, item.name]) });
        field(basics, 'Issue date', record, 'issue_date', { type: 'date' }); field(basics, 'Due date', record, 'due_date', { type: 'date' }); field(basics, 'Quote valid until', record, 'valid_until', { type: 'date' });
        record.lines.forEach((line, index) => {
          const block = element('fieldset', '', 'ok-invoice-line', form); element('legend', `Line ${index + 1}`, '', block);
          const picker = { item_id: '' }; const select = field(block, 'Saved item', picker, 'item_id', { choices: [['', 'Ad-hoc item'], ...state.items.map(item => [item.id, item.private_name])] });
          select.addEventListener('change', () => { if (picker.item_id) selectItem(line, picker.item_id); });
          field(block, 'Description & invoice-specific details', line, 'description', { multiline: true, maxLength: 4000 });
          const money = grid(block); field(money, 'Quantity', line, 'quantity'); field(money, 'Unit', line, 'unit'); field(money, 'Rate', line, 'rate');
          const extra = details(block, 'Line date, section & tax'); field(extra, 'Line date', line, 'date', { type: 'date' }); field(extra, 'Section', line, 'section'); field(extra, 'Tax exemption', line, 'tax_exempt', { choices: [['false', 'Use selected taxes'], ['true', 'Exempt this line']] });
          inlineAction('Remove line', () => { record.lines.splice(index, 1); markPreviewStale(); persistDraft(); render(); }, block);
        });
        inlineAction('Add line', () => { record.lines.push({ description: '', quantity: '1', rate: '0', unit: '', tax_exempt: false }); markPreviewStale(); persistDraft(); render(); }, form);
        const more = details(form, 'Discount, notes & payment terms'); const discounts = grid(more);
        field(discounts, 'Discount type', record.discount, 'kind', { choices: [['none', 'None'], ['percent', 'Percentage'], ['fixed', 'Fixed amount']] }); field(discounts, 'Discount value', record.discount, 'value');
        field(more, 'Notes', record, 'notes', { multiline: true, maxLength: 8000 }); field(more, 'Payment terms', record, 'terms', { multiline: true, maxLength: 8000 });
        field(more, 'Template', record, 'template_id', { choices: business().templates.map(item => [item.id, item.name]) });
      } else {
        element('p', `${record.client.name} · ${record.status}`, '', form);
        rows(form, ['Description', 'Quantity', 'Rate'], record.lines, line => [line.description, line.quantity, line.rate]);
        element('p', `Total ${formatMoney(totalOf(record), currencyOf(record))} · Balance ${formatMoney(record.balance, currencyOf(record))}`, '', form);
        if (record.kind === 'invoice') paymentForm(form);
        else quoteForm(form);
      }
      element('h2', 'PDF preview', '', preview);
      if (state.previewUrl && state.previewStale) { const stale = element('p', 'Preview out of date · refresh to review current invoice.', 'ok-invoice-preview-stale', preview); stale.setAttribute('role', 'status'); }
      if (state.previewUrl) { const iframe = element('iframe', '', '', preview); iframe.title = state.previewStale ? 'Out-of-date invoice PDF preview' : 'Invoice PDF preview'; iframe.src = state.previewUrl; }
      else element('p', 'Preview the generated PDF with your business branding.', 'ok-invoice-muted', preview);
      inlineAction(state.previewUrl ? 'Refresh preview' : 'Preview PDF', showPreview, preview);
      const buttons = footer(issued ? 'Issued details are preserved.' : 'Invoice-specific item edits do not alter your catalogue.');
      if (issued) { action('Download PDF', exportPdf, buttons); action('Draft email', draftEmail, buttons); action(record.kind === 'invoice' ? 'Record payment' : 'Apply quote action', issuedAction, buttons, true); }
      else { action('Save draft', saveDocument, buttons); action('Download PDF', exportPdf, buttons); action('Issue document', () => transition('issue'), buttons, true); }
    }

    const payment = { amount: '', date: '', method: 'Bank transfer', reference: '', correction_id: '', reason: '' };
    const quote = { action: 'accept', amount: '' };
    function paymentForm(parent) {
      const box = details(parent, 'Record or correct a payment'); const controls = grid(box);
      field(controls, 'Amount', payment, 'amount'); field(controls, 'Payment date', payment, 'date', { type: 'date' }); field(controls, 'Method', payment, 'method'); field(controls, 'Reference', payment, 'reference');
      field(box, 'Payment ID to correct (optional)', payment, 'correction_id'); field(box, 'Correction reason', payment, 'reason');
    }
    function quoteForm(parent) { field(parent, 'Quote action', quote, 'action', { choices: [['accept', 'Mark accepted'], ['decline', 'Mark declined'], ['full', 'Convert to invoice'], ['deposit', 'Create deposit invoice'], ['balance', 'Create balance invoice']] }); field(parent, 'Deposit / balance amount', quote, 'amount'); }
    async function issuedAction() {
      if (state.editor.kind === 'invoice') {
        const record = { amount: payment.amount, date: payment.date || now(), method: payment.method, reference: payment.reference, idempotency_key: uuid() };
        const result = payment.correction_id ? await mutate(`documents/${state.editor.id}/payment-corrections`, { payment_id: payment.correction_id, reason: payment.reason, replacement: { ...record, expected_revision: revision() } }) : await mutate(`documents/${state.editor.id}/payments`, record);
        state.editor = adoptDocument(result.document); await refresh();
      } else if (quote.action === 'accept' || quote.action === 'decline') await transition(quote.action);
      else { const result = await mutate('document-conversions', { source_quote_id: state.editor.id, kind: quote.action, amount: quote.amount || null, idempotency_key: uuid() }); state.editor = adoptDocument(result.documents[0]); await refresh(); }
    }
    async function draftEmail() { await exportPdf(); const record = state.editor; openEmail(`mailto:${encodeURIComponent(record.client.email || '')}?subject=${encodeURIComponent(`${record.number} from ${record.business.name}`)}&body=${encodeURIComponent('Please find the invoice PDF attached. Review and attach the downloaded PDF before sending.')}`); }

    function renderCatalogue() {
      if (state.catalogue) {
        const editor = state.catalogue; const type = editor.type; const record = editor.record;
        element('h2', type === 'clients' ? 'Client' : 'Catalogue item'); const controls = grid(screen);
        if (type === 'clients') { field(controls, 'Client name', record, 'name'); field(controls, 'Email', record, 'email', { type: 'email' }); field(controls, 'Contact', record, 'contact'); field(controls, 'Customer reference', record, 'customer_reference'); field(screen, 'Address', record, 'address', { multiline: true }); }
        else { field(controls, 'Private item name', record, 'private_name'); field(controls, 'Unit', record, 'unit'); field(controls, 'Default quantity', record, 'quantity'); field(controls, 'Default rate', record, 'rate'); field(controls, 'Default tax behavior', record, 'tax_exempt', { choices: [['false', 'Use invoice taxes'], ['true', 'Tax exempt']] }); field(screen, 'Printed description', record, 'description', { multiline: true }); }
        action('Save record', async () => { const body = copy(record); delete body.id; delete body.created_at; delete body.updated_at; delete body.library_revision; if (type === 'items') body.tax_exempt = body.tax_exempt === true || body.tax_exempt === 'true'; const saved = await mutate(`${type}${record.id ? `/${record.id}` : ''}`, body, record.id ? 'PUT' : 'POST'); const returning = state.clientReturn && type === 'clients'; state.clientReturn = false; state.catalogue = null; await refresh(); if (returning) { state.view = 'editor'; if (state.editor && saved?.id) state.editor.client_id = saved.id; persistDraft(); } }, screen, true);
        return;
      }
      state.catalogueType = state.catalogueType || 'items';
      const choice = state; const select = field(screen, 'Catalogue', choice, 'catalogueType', { choices: [['items', 'Items'], ['clients', 'Clients']] });
      const list = element('div', '', '', screen);
      const display = () => { list.replaceChildren(); const records = choice.catalogueType === 'items' ? state.items : state.clients; rows(list, ['Name', 'Details'], records, item => [recordLink(choice.catalogueType === 'items' ? item.private_name : item.name, async () => { state.catalogue = { type: choice.catalogueType, record: copy(item) }; }), choice.catalogueType === 'items' ? item.description : item.address]); };
      select.addEventListener('change', display); display();
      action('New record', () => { state.catalogue = { type: choice.catalogueType, record: choice.catalogueType === 'items' ?{ business_id: state.businessId, private_name: '', description: '', unit: '', quantity: '1', rate: '0', tax_exempt: false, archived: false } : { business_id: state.businessId, name: '', address: '', email: '', contact: '', customer_reference: '', terms_days: 14, tax_profile_id: null, archived: false } }; render(); }, screen, true);
    }

    function renderRecurring() {
      if (state.schedule) {
        const record = state.schedule;
        if (record.step === 'details') {
          element('h2', 'New recurring invoice'); element('p', 'Invoice details · Step 1 of 2', 'ok-invoice-muted');
          const client = field(screen, 'Client', record.draft, 'client_id', { choices: [['', 'Choose a client'], ...state.clients.map(item => [item.id, item.name])] });
          field(screen, 'Currency', record.draft, 'currency_id', { choices: business().currencies.map(item => [item.id, `${item.code} — ${item.name}`]) });
          if (record.errorTarget === 'client') { client.setAttribute('aria-invalid', 'true'); const error = element('span', record.error, 'ok-invoice-field-error', client.parent); error.setAttribute('role', 'alert'); }
          record.draft.lines.forEach((line, index) => { const block = element('fieldset', '', 'ok-invoice-line', screen); element('legend', `Item ${index + 1}`, '', block); const description = field(block, 'Description', line, 'description', { multiline: true, maxLength: 4000 }); if (record.errorTarget === `line-${index}`) { description.setAttribute('aria-invalid', 'true'); const error = element('span', record.error, 'ok-invoice-field-error', description.parent); error.setAttribute('role', 'alert'); } const values = grid(block); field(values, 'Quantity', line, 'quantity'); field(values, 'Unit', line, 'unit'); field(values, 'Rate', line, 'rate'); });
          const actions = footer('Each occurrence is saved as a draft for your review.');
          action('Cancel', () => { state.schedule = null; render(); }, actions);
          action('Continue to schedule', () => { if (!record.draft.client_id) { record.error = 'Choose a client to continue.'; record.errorTarget = 'client'; render(); [...fields.values()].find(item => item.key === 'client_id')?.input.focus(); return; } const emptyLine = record.draft.lines.findIndex(line => !line.description.trim()); if (emptyLine >= 0) { record.error = 'Add a description for this invoice item.'; record.errorTarget = `line-${emptyLine}`; render(); [...fields.values()].find(item => item.label === 'Description')?.input.focus(); return; } record.error = ''; record.errorTarget = ''; record.step = 'schedule'; render(); }, actions, true); return;
        }
        const clientName = state.clients.find(item => item.id === record.draft.client_id)?.name || 'Client';
        const scheduleCurrency = business().currencies.find(item => item.id === record.draft.currency_id);
        const controls = grid(screen); element('h2', 'Schedule recurring invoice'); element('p', clientName, 'ok-invoice-muted');
        element('h3', 'Invoice details to repeat', '', screen);
        rows(screen, ['Description', 'Quantity', 'Rate'], record.draft.lines, line => [line.description || 'Untitled item', line.quantity, scheduleCurrency ? `${formatMoney(line.rate, scheduleCurrency)} · ${scheduleCurrency.code}` : line.rate]);
        field(controls, 'Frequency', record, 'frequency', { choices: ['weekly', 'monthly', 'quarterly', 'yearly'].map(item => [item, item]) }); field(controls, 'First date', record, 'anchor_date', { type: 'date' }); field(controls, 'End date', record, 'end_date', { type: 'date' }); field(controls, 'Occurrence limit', record, 'end_count', { type: 'number', number: true }); field(controls, 'Missed occurrences', record, 'catch_up', { choices: [['each', 'Create missed drafts'], ['ask', 'Ask first']] });
        const actions = footer('Each occurrence is saved as a draft for your review.');
        action('Back', () => { if (record.isEditing) { state.schedule = null; render(); } else { record.step = 'details'; render(); } }, actions);
        action('Save schedule', async () => { const body = copy(record); delete body.step; delete body.error; delete body.isEditing; delete body.id; delete body.library_revision; delete body.created_at; delete body.updated_at; body.end_date = body.end_date || null; body.end_count = body.end_count || null; await mutate(`schedules${record.id ? `/${record.id}` : ''}`, body, record.id ? 'PUT' : 'POST'); state.schedule = null; await refresh(); }, actions, true); return;
      }
      element('p', 'Recurring invoices become drafts for your review when you open this tool. Nothing is sent automatically.', 'ok-invoice-muted');
      rows(screen, ['Schedule', 'Frequency', 'Next', 'State'], state.schedules, record => [recordLink(record.id, async () => { state.schedule = { ...copy(record), isEditing: true }; }), record.frequency, record.anchor_date, record.paused ? 'Paused' : 'Active']);
      action('New schedule', () => { const profile = business(); const today = now(); state.schedule = { business_id: state.businessId, draft: { business_id: state.businessId, kind: 'invoice', client_id: '', currency_id: profile.default_currency_id, tax_profile_id: profile.default_tax_profile_id, template_id: profile.default_template_id, issue_date: today, due_date: today, valid_until: today, lines: [{ description: '', quantity: '1', rate: '0', unit: '', tax_exempt: false }], discount: { kind: 'none', value: '0' }, notes: '', terms: '', payment_method_ids: profile.payment_methods.filter(item => item.enabled).map(item => item.id) }, frequency: 'monthly', anchor_date: today, end_date: '', end_count: '', paused: false, catch_up: 'each', step: 'details' }; render(); }, screen, true);
      action('Review missed drafts', async () => { const result = await mutate('recurring-draft-batches', { approved_schedule_ids: state.schedules.map(record => record.id) }); state.message = `${result.created_document_ids.length} recurring drafts created.`; await refresh(); }, screen, false, true);
    }
    const reportQuery = { start: '', end: '', currency_id: '' };
    function renderReports() {
      reportQuery.start = reportQuery.start || `${now().slice(0, 7)}-01`; reportQuery.end = reportQuery.end || now(); reportQuery.currency_id = reportQuery.currency_id || business().default_currency_id;
      const controls = grid(screen); const start = field(controls, 'From', reportQuery, 'start', { type: 'date' }); const end = field(controls, 'To', reportQuery, 'end', { type: 'date' }); const currencyInput = field(controls, 'Currency', reportQuery, 'currency_id', { choices: business().currencies.map(item => [item.id, item.code]) });
      [start, end, currencyInput].forEach(input => input.addEventListener('change', () => { state.report = null; return run(loadReport); }));
      const reportCurrency = business().currencies.find(item => item.id === reportQuery.currency_id);
      element('p', `Report · ${business().profile_name || business().name} · ${reportCurrency ? reportCurrency.code : ''} · ${reportQuery.start} to ${reportQuery.end}`, 'ok-invoice-muted').setAttribute('role', 'status');
      if (state.report) { const currency = business().currencies.find(item => item.id === reportQuery.currency_id); rows(screen, ['Invoiced', 'Received', 'Outstanding', 'Overdue'], [state.report], record => ['invoiced', 'received', 'outstanding', 'overdue'].map(key => formatMoney(record[key], currency))); rows(screen, ['Client', 'Invoiced', 'Received', 'Outstanding'], state.report.clients, record => [record.name, ...['invoiced', 'received', 'outstanding'].map(key => formatMoney(record[key], currency))]); }
      else if (!state.error) element('p', state.busy ? 'Updating report…' : 'No report loaded. Change a filter to load results.', 'ok-invoice-muted', screen);
      action('Download CSV', async () => download(await request(`${prefix()}/reports.csv${reportSearch()}`, 'GET', null, true), 'invoice-report.csv'), screen);
    }
    function reportSearch() { return `?business_id=${encodeURIComponent(state.businessId)}&start=${reportQuery.start}&end=${reportQuery.end}&currency_id=${encodeURIComponent(reportQuery.currency_id)}`; }
    async function loadReport() { state.report = null; state.report = await request(`${prefix()}/reports${reportSearch()}`); }

    function renderSettings() {
      state.settings = state.settings || copy(business()); const record = state.settings;
      element('h2', 'Business profile');
      const profileActions = element('div', '', 'ok-invoice-profile-actions');
      inlineAction('New profile', opener => startProfileWizard('new', opener), profileActions);
      if (business()) inlineAction('Edit profile', opener => startProfileWizard('edit', opener), profileActions);
      const controls = grid(screen);
      field(controls, 'Profile name', record, 'profile_name'); field(controls, 'Business name printed on invoices', record, 'name'); field(controls, 'Contact details', record, 'contact'); field(screen, 'Business address', record, 'address', { multiline: true });
      const currencyBox = details(screen, 'Currencies & formatting');
      record.currencies.forEach(currency => { const row = grid(currencyBox); field(row, 'Currency code', currency, 'code'); field(row, 'Currency name', currency, 'name'); field(row, 'Symbol', currency, 'symbol'); field(row, 'Decimal places', currency, 'precision', { type: 'number', number: true }); field(row, 'Symbol placement', currency, 'placement', { choices: [['before', 'Before amount'], ['after', 'After amount'], ['code', 'Show code']] }); field(row, 'Grouping', currency, 'grouping', { choices: [['western', '1,234,567'], ['indian', '12,34,567'], ['none', 'No grouping']] }); field(row, 'Decimal separator', currency, 'decimal_separator', { choices: [['.', '.'], [',', ',']] }); field(row, 'Grouping separator', currency, 'grouping_separator', { choices: [[',', ','], ['.', '.'], [' ', 'Space'], ['', 'None']] }); });
      field(currencyBox, 'Default currency', record, 'default_currency_id', { choices: record.currencies.map(item => [item.id, item.code]) });
      const preset = { code: 'USD' }; field(currencyBox, 'Add currency preset', preset, 'code', { choices: PRESETS.map(item => [item[0], `${item[0]} — ${item[1]}`]) }); action('Add currency', () => { record.currencies.push(currencyPreset(preset.code, uuid)); render(); }, currencyBox, false, true);
      const taxBox = details(screen, 'Tax profiles & registrations');
      record.tax_profiles.forEach(profile => { const container = element('div', '', 'ok-invoice-line', taxBox); field(container, 'Tax profile name', profile, 'name'); field(container, 'Price treatment', profile, 'inclusive', { choices: [['false', 'Tax exclusive'], ['true', 'Tax inclusive']] }); profile.rows.forEach(tax => { const row = grid(container); field(row, 'Tax label', tax, 'label'); field(row, 'Rate (%)', tax, 'rate'); field(row, 'Registration label', tax, 'registration_label'); field(row, 'Registration number', tax, 'registration_number'); field(row, 'Calculation', tax, 'mode', { choices: [['additive', 'Add to net'], ['compound', 'Compound after preceding taxes']] }); }); action('Add tax row', () => { profile.rows.push({ label: '', rate: '0', registration_label: '', registration_number: '', mode: 'additive' }); render(); }, container, false, true); });
      field(taxBox, 'Default tax profile', record, 'default_tax_profile_id', { choices: [['', 'No tax'], ...record.tax_profiles.map(item => [item.id, item.name])] }); action('Add tax profile', () => { record.tax_profiles.push({ id: uuid(), name: '', inclusive: false, rows: [] }); render(); }, taxBox, false, true);
      const branding = details(screen, 'Logo, branding & templates'); record.templates.forEach(template => { const row = grid(branding); field(row, 'Template name', template, 'name'); field(row, 'Layout', template, 'layout', { choices: ['Classic', 'Compact', 'Bold'].map(item => [item, item]) }); field(row, 'Paper size', template, 'paper', { choices: [['A4', 'A4'], ['Letter', 'US Letter']] }); field(row, 'Accent color', template, 'accent', { type: 'color' }); field(row, 'Logo size', template, 'logo_size', { choices: ['small', 'medium', 'large'].map(item => [item, item]) }); field(row, 'Logo placement', template, 'logo_placement', { choices: [['left', 'Left'], ['center', 'Center'], ['right', 'Right']] }); field(branding, 'Footer', template, 'footer', { multiline: true }); });
      const payments = details(screen, 'Bank & payment details'); record.payment_methods.forEach(method => { const row = grid(payments); field(row, 'Payment method label', method, 'label'); field(row, 'Payment method', method, 'type', { choices: [['bank', 'Bank transfer'], ['link', 'Payment link'], ['local', 'Local payment / QR'], ['cash-cheque', 'Cash / cheque'], ['custom', 'Custom']] }); method.fields.forEach(item => { field(row, 'Field label', item, 'label'); field(row, item.label || 'Field value', item, 'value'); }); field(row, 'Payment link', method, 'link', { type: 'url' }); field(row, 'QR payload', method, 'qr_payload'); field(payments, 'Instructions', method, 'instructions', { multiline: true }); });
      action('Add payment method', () => { record.payment_methods.push({ id: uuid(), type: 'bank', label: 'Bank transfer', enabled: true, fields: ['Account holder', 'Bank name', 'Account number', 'IBAN', 'SWIFT / BIC', 'Routing / sort / branch code'].map(label => ({ label, value: '', visible: true })), link: '', qr_payload: '', instructions: '' }); render(); }, payments, false, true);
      const numbering = details(screen, 'Invoice numbering'); const numbers = grid(numbering); field(numbers, 'Invoice prefix', record.numbering, 'invoice_prefix'); field(numbers, 'Quote prefix', record.numbering, 'quote_prefix'); field(numbers, 'Estimate prefix', record.numbering, 'estimate_prefix'); field(numbers, 'Next counter', record.numbering, 'next_counter', { type: 'number', number: true }); field(numbers, 'Counter padding', record.numbering, 'padding', { type: 'number', number: true }); field(numbers, 'Counter reset', record.numbering, 'reset', { choices: [['never', 'Never'], ['yearly', 'Yearly']] });
      if (!state.wizard) {
        const buttons = footer('');
        action('Save', saveSettings, buttons, true);
      }
    }

    function startProfileWizard(mode, opener) {
      const record = mode === 'new'
        ? (!state.businesses.length && state.settings ? copy(state.settings) : newBusiness(uuid))
        : copy(state.settings);
      const currency = record.currencies.find(item => item.id === record.default_currency_id);
      const template = record.templates.find(item => item.id === record.default_template_id);
      state.settings = record;
      state.wizard = { step: 1, mode, returnView: mode === 'new' ? 'documents' : state.view, returnFocus: opener.textContent.trim(), record, currencyCode: currency.code, layout: template.layout };
      state.profileWizardDismissed = false;
      state.error = '';
      render();
    }
    function closeProfileWizard() {
      const wizard = state.wizard; const record = wizard?.record;
      state.wizard = null; state.settings = state.businesses.length ? null : record; state.error = '';
      if (!state.businesses.length) state.profileWizardDismissed = true;
      state.focusAfterWizard = wizard?.returnFocus || 'New profile';
      clearLogoPreview(); render();
    }
    function clearLogoPreview() {
      if (state.logoPreviewUrl) revokeUrl(state.logoPreviewUrl);
      state.logoPreviewUrl = ''; state.logoPreviewId = '';
    }
    async function loadLogoPreview(id) {
      if (state.logoPreviewUrl && state.logoPreviewId === id) return;
      if (state.logoPreviewUrl) revokeUrl(state.logoPreviewUrl);
      state.logoPreviewUrl = ''; state.logoPreviewId = id;
      const blob = await request(`${prefix()}/assets/${encodeURIComponent(id)}`, 'GET', null, true);
      if (!state.wizard || state.logoPreviewId !== id || !state.wizard.record.templates.some(item => item.logo_id === id)) return;
      state.logoPreviewUrl = objectUrl(blob);
    }
    function renderProfileWizard() {
      const wizard = state.wizard; const record = wizard.record;
      const dialog = element('dialog', '', 'modal ok-invoice-profile-dialog');
      dialog.setAttribute('aria-modal', 'true'); dialog.setAttribute('aria-labelledby', 'invoice-profile-wizard-title');
      dialog.addEventListener('cancel', event => event.preventDefault());
      const content = element('div', '', 'modal-box', dialog);
      const title = wizard.mode === 'new' ? 'Create your business profile' : 'Edit business profile';
      const titleNode = element('h2', wizard.step === 1 ? title : 'Invoice defaults', '', content); titleNode.id = 'invoice-profile-wizard-title';
      element('p', wizard.step === 1 ? 'Set up the details that appear on your invoices. You can edit them later.' : 'These defaults make the profile ready to use. You can change them any time.', 'ok-invoice-muted', content);
      const steps = element('ol', '', 'ok-invoice-profile-steps', content);
      [['Business', 1], ['Invoice defaults', 2]].forEach(([label, number], index) => {
        const item = element('li', '', number === wizard.step ? 'active' : '', steps);
        if (number === wizard.step) item.setAttribute('aria-current', 'step');
        const marker = element('span', String(number), 'ok-invoice-profile-step-number', item); marker.setAttribute('aria-hidden', 'true');
        element('span', label, '', item);
        if (index === 0) element('span', '', 'ok-invoice-profile-step-line', steps);
      });
      if (wizard.step === 1) {
        const name = field(content, 'Business name', record, 'name', { required: true, maxLength: 160 });
        if (state.error) name.setAttribute('aria-invalid', 'true');
        element('span', 'Required · printed on invoices', 'ok-invoice-profile-hint', name.parent);
        const profileName = field(content, 'Profile name', record, 'profile_name', { maxLength: 160 });
        element('span', 'Optional', 'ok-invoice-profile-hint', profileName.parent);
        const address = field(content, 'Business address', record, 'address', { multiline: true, maxLength: 4000 });
        element('span', 'Optional', 'ok-invoice-profile-hint', address.parent);
        const contact = field(content, 'Contact details', record, 'contact', { maxLength: 512 });
        element('span', 'Optional', 'ok-invoice-profile-hint', contact.parent);
        name.setAttribute('autofocus', '');
      } else {
        const currencyOptions = [...PRESETS.map(([code, name]) => [code, `${code} · ${name}`])];
        record.currencies.filter(item => !PRESETS.some(([code]) => code === item.code)).forEach(item => currencyOptions.push([item.code, `${item.code} · custom` ]));
        const currency = field(content, 'Currency', wizard, 'currencyCode', { choices: currencyOptions });
        currency.value = wizard.currencyCode;
        currency.addEventListener('change', () => {
          let definition = record.currencies.find(item => item.code === wizard.currencyCode);
          if (!definition) { definition = currencyPreset(wizard.currencyCode, uuid); record.currencies.push(definition); }
          record.default_currency_id = definition.id;
        });
        field(content, 'Tax profile', record, 'default_tax_profile_id', { choices: record.tax_profiles.map(item => [item.id, item.name || 'No tax']) });
        const layout = field(content, 'Invoice design', wizard, 'layout', { choices: ['Classic', 'Compact', 'Bold'].map(item => [item, item]) });
        layout.value = wizard.layout;
        layout.addEventListener('change', () => {
          let template = record.templates.find(item => item.id === record.default_template_id);
          if (!template) template = record.templates[0];
          template.layout = wizard.layout; template.name = wizard.layout;
          record.default_template_id = template.id;
        });
        const logoBox = element('div', '', 'ok-invoice-profile-logo', content);
        element('div', 'Invoice logo', 'ok-invoice-profile-label', logoBox);
        element('span', 'Optional', 'ok-invoice-profile-hint', logoBox);
        action('Upload logo', async () => {
          const selection = await invoke('file_selection_open', { mode: 'files', access: 'read' });
          if (selection === null) return;
          const asset = await mutate('assets', { selection_id: selection.id });
          const template = record.templates.find(item => item.id === record.default_template_id);
          template.logo_id = asset.id;
          await loadLogoPreview(asset.id);
        }, logoBox);
        const preview = element('div', '', 'ok-invoice-logo-preview', logoBox);
        const logoId = record.templates.find(item => item.id === record.default_template_id)?.logo_id;
        if (logoId && state.logoPreviewUrl && state.logoPreviewId === logoId) {
          const image = element('img', '', '', preview); image.src = state.logoPreviewUrl; image.alt = 'Invoice logo preview';
        } else {
          element('span', logoId ? 'Loading logo preview…' : 'Logo preview will appear here after you choose an image.', 'ok-invoice-profile-hint', preview);
          if (logoId && state.logoPreviewId !== logoId) loadLogoPreview(logoId).then(() => { if (state.wizard) render(); }).catch(error => { state.error = error.message; render(); });
        }
      }
      if (state.error) { const error = element('p', state.error, 'ok-invoice-error', content); error.setAttribute('role', 'alert'); error.tabIndex = -1; error.focus(); }
      const actions = element('div', '', 'ok-invoice-profile-actions-row', content);
      action(wizard.step === 1 ? 'Cancel' : 'Back', () => {
        if (wizard.step === 2) { state.wizard.step = 1; state.error = ''; render(); }
        else closeProfileWizard();
      }, actions);
      action(wizard.step === 1 ? 'Continue' : 'Finish profile', () => {
        if (wizard.step === 1) {
          if (!record.name.trim()) { state.error = 'Business name is required.'; render(); return; }
          state.error = ''; wizard.step = 2; render();
        }
        else return saveSettings();
      }, actions, true);
      dialog.showModal();
    }
    async function saveSettings() {
      const wizard = state.wizard;
      const source = wizard ? wizard.record : state.settings;
      if (wizard && !source.name.trim()) throw new Error('Business name is required.');
      const record = copy(source);
      if (wizard && !record.profile_name.trim()) record.profile_name = record.name.trim();
      record.default_tax_profile_id = record.default_tax_profile_id || null;
      record.tax_profiles.forEach(profile => { profile.inclusive = profile.inclusive === true || profile.inclusive === 'true'; });
      const id = record.id; delete record.id; delete record.created_at; delete record.updated_at; delete record.library_revision;
      const saved = await mutate(`businesses${id ? `/${id}` : ''}`, record, id ? 'PUT' : 'POST'); state.businessId = saved.id;
      if (wizard) {
        state.wizard = null; state.view = wizard.returnView; state.profileWizardDismissed = false;
        state.focusAfterWizard = wizard.returnFocus || 'New document'; clearLogoPreview();
      }
      state.settings = null; await refresh(); state.message = 'Business profile saved.';
    }
    function renderFolder() {
      element('h2', 'Invoice workspace'); element('p', `${state.library.label} · ${state.library.status}`);
      element('p', 'Business profiles, invoices, payments and history stay together in this folder. You control cloud-provider sync. Edit on one computer at a time.', 'ok-invoice-muted');
      element('pre', 'Workspace/\n  config/  Business settings, catalogue & history\n  data/YYYY/MM/  Issued invoice files', 'ok-invoice-folder-tree');
      const controls = element('div', '', 'ok-invoice-folder-actions', screen);
      const primary = element('div', '', 'ok-invoice-folder-primary', controls);
      action(state.library.status === 'ready' ? 'Choose folder' : 'Reconnect folder', state.library.status === 'ready' ? chooseFolder : () => reconnect(state.library.id), primary);
      action('Create backup', async () => download(await request(`${prefix()}/backups`, 'POST', {}, true), 'officekit-invoices-backup.zip'), primary);
      action('Restore backup', () => { state.view = 'restore'; render(); }, primary, true);
      const secondary = element('details', '', 'ok-invoice-folder-secondary', screen);
      element('summary', 'More workspace actions', '', secondary);
      const moreActions = element('select', '', 'select select-bordered', secondary);
      moreActions.setAttribute('aria-label', 'More workspace actions');
      [['', 'Choose an action'], ['history', 'Workspace history'], ['reload', 'Reload changed library']].forEach(([value, label]) => { const option = element('option', label, '', moreActions); option.value = value; });
      moreActions.addEventListener('change', async () => {
        if (moreActions.value === 'history') await run(() => navigate('history'));
        if (moreActions.value === 'reload') await run(async () => { persistDraft(); state.library = await request(`${prefix()}/reloads`, 'POST', {}); await refresh(); state.message = 'Folder reloaded. Your unsaved draft remains available for review.'; });
      });
    }

    function renderRestore() {
      element('h2', 'Restore invoice workspace');
      element('p', 'Restore the complete backup into a new workspace. Existing workspaces are never overwritten.', 'ok-invoice-muted');
      element('p', state.backupSelection ? state.backupSelection.displayNames.join(', ') : 'Choose an OfficeKit invoice backup.');
      action('Choose backup file', async () => { const selected = await invoke('file_selection_open', { mode: 'files', access: 'read' }); if (selected !== null) state.backupSelection = selected; }, screen);
      element('p', state.restoreSelection ? state.restoreSelection.displayNames.join(', ') : 'Choose the parent folder for the new workspace.');
      action('Choose parent folder', async () => { const selected = await invoke('file_selection_open', { mode: 'folder', access: 'read-write' }); if (selected !== null) state.restoreSelection = selected; }, screen);
      const buttons = footer('Includes profiles, clients, items, invoices, payments, logos, files and history.');
      const restore = action('Restore & open workspace', async () => { state.library = await request('/api/invoice-restorations', 'POST', { selection_id: state.restoreSelection.id, backup_selection_id: state.backupSelection.id }); state.editor = null; state.settings = null; state.backupSelection = null; state.restoreSelection = null; state.view = 'folder'; await refresh(); }, buttons, true);
      restore.disabled = state.busy || !state.backupSelection || !state.restoreSelection;
      const cancel = doc.createElement('a'); cancel.href = '#'; cancel.className = 'ok-text-link'; cancel.textContent = 'Cancel'; cancel.addEventListener('click', event => { event.preventDefault(); void navigate('folder'); }); buttons.append(cancel);
    }

    function renderHistory() {
      element('h2', 'Workspace history'); action('Workspace settings', () => navigate('folder'), screen, false, true);
      const filter = field(screen, 'History business profile', state, 'historyBusinessId', { choices: [['', 'All profiles'], ...state.businesses.map(item => [item.id, profileLabel(item)])] }); filter.addEventListener('change', render);
      const filtered = state.history.filter(entry => !state.historyBusinessId || entry.business_id === state.historyBusinessId);
      rows(screen, ['When', 'Change', 'Profile / document'], filtered, entry => [entry.changed_at, entry.summary || 'Workspace updated', entry.document_number || state.businesses.find(item => item.id === entry.business_id)?.profile_name || '—']);
    }

    return Object.freeze({ state, fields, screen, open, render, run, request, refresh, chooseFolder, reconnect, navigate, newDocument, editDocument, saveDocument, transition, showPreview, exportPdf, selectItem, issuedAction, draftEmail, saveSettings, loadReport, persistDraft, restoreDraft, draftPayload, reportQuery, payment, quote });
  }

  let instance;
  function open(view) {
    if (!instance) {
      const native = window.__TAURI__?.core?.invoke;
      instance = create({ document, fetch: (...args) => window.fetch(...args), invoke: async (command, args) => { if (typeof native !== 'function') throw new Error('Folder access requires the OfficeKit desktop app.'); return native(command, args); }, uuid: () => crypto.randomUUID(), storage: window.localStorage, now: () => new Date().toLocaleDateString('en-CA'), download: (blob, name) => window.officekitDownloadResultBlob(blob, name), objectUrl: blob => URL.createObjectURL(blob), revokeUrl: url => URL.revokeObjectURL(url), openEmail: url => { window.location.href = url; }, apiUrl: path => officekitApiUrl(path) });
    }
    return instance.open(view);
  }
  window.OfficeKitInvoices = Object.freeze({ create, open, formatMoney, currencyPreset, newBusiness, presets: PRESETS });
}());
