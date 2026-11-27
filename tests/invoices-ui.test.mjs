import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../assets/officekit-slice-invoices.js', import.meta.url), 'utf8');

class Element {
  constructor(tag, doc) { this.tagName = tag.toUpperCase(); this.doc = doc; this.children = []; this.listeners = {}; this.attributes = {}; this.dataset = {}; this.value = ''; this.className = ''; this.disabled = false; this.open = false; this._text = ''; }
  set id(value) { this._id = value; this.doc.ids.set(value, this); }
  get id() { return this._id; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); for (const child of children) child.parent = this; }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  async fire(type) { for (const listener of this.listeners[type] || []) await listener({ target: this, preventDefault() {} }); }
  focus() { this.doc.activeElement = this; }
  querySelectorAll(selector) { const tags = selector.split(',').map(tag => tag.trim().toUpperCase()); return descendants(this).filter(node => tags.includes(node.tagName)); }
  querySelector(selector) { return descendants(this).find(node => selector.startsWith('.') ? node.className.split(/\s+/).includes(selector.slice(1)) : node.tagName === selector.toUpperCase()) || null; }
  insertBefore(child, reference) { if (child.parent) child.parent.children = child.parent.children.filter(item => item !== child); const index = this.children.indexOf(reference); if (index < 0) this.append(child); else { this.children.splice(index, 0, child); child.parent = this; } }
  showModal() { this.open = true; }
}

function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
function harness() {
  const doc = { ids: new Map(), createElement(tag) { return new Element(tag, this); }, getElementById(id) { return this.ids.get(id); } };
  const main = doc.createElement('main'); main.id = 'app-main';
  const saved = new Map(); const storage = { setItem: (key, value) => saved.set(key, value), getItem: key => saved.get(key) || null, removeItem: key => saved.delete(key) };
  let sequence = 0; const uuid = () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}`;
  const requests = []; const downloads = []; const revoked = []; const emails = []; let nativeSelection = { id: 'selected', displayNames: ['Selected fixture'] }; let errorResponse = null; let nextAssetId = 'logo'; let assetGetOverride = null;
  const library = { id: 'library', library_id: 'library', label: 'Invoices', status: 'ready', revision: 0 };
  const context = { document: doc, crypto: { randomUUID: uuid }, Date, URL: { createObjectURL: () => 'blob:preview', revokeObjectURL: value => revoked.push(value) }, officekitApiUrl: value => value };
  let registration;
  const window = { document: doc, localStorage: storage, OfficeKitExtensions: { register: value => { registration = value; } }, location: {}, officekitDownloadResultBlob: async (blob, name) => downloads.push({ blob, name }) };
  context.window = window;
  vm.runInNewContext(source, context, { filename: new URL('../assets/officekit-slice-invoices.js', import.meta.url).pathname });
  const module = window.OfficeKitInvoices;
  const profile = module.newBusiness(uuid); profile.id = 'business'; profile.name = 'Northstar'; profile.profile_name = 'Global';
  const client = { id: 'client', business_id: profile.id, name: 'Acme', email: 'billing@example.test', address: 'Client address', contact: '', customer_reference: '', terms_days: 14, tax_profile_id: null, archived: false };
  const item = { id: 'item', business_id: profile.id, private_name: 'Design', description: 'Saved design', unit: 'day', quantity: '2', rate: '25.00', tax_exempt: false, archived: false };
  const draft = { business_id: profile.id, kind: 'invoice', client_id: client.id, currency_id: profile.default_currency_id, tax_profile_id: null, template_id: profile.default_template_id, issue_date: '2026-10-26', due_date: '2026-11-09', valid_until: '2026-11-09', lines: [{ description: 'Design work', quantity: '2', rate: '25', unit: 'day', tax_exempt: false }], discount: { kind: 'none', value: '0' }, notes: '', terms: '', payment_method_ids: [] };
  const record = { id: 'document', business_id: profile.id, kind: 'invoice', state: 'draft', status: 'draft', number: 'DRAFT', draft, business: profile, client, currency: profile.currencies[0], tax_profile: { rows: [] }, template: profile.templates[0], payment_methods: [], totals: { total: '50.00' }, paid: '0.00', balance: '50.00', library_revision: 0 };
  const data = { businesses: [profile], clients: [client], items: [item], documents: [record], schedules: [], history: [{ revision: 1, changed_at: '2026-10-26T12:00:00Z', summary: 'Invoice issued', business_id: 'business', document_number: 'INV-001' }, { revision: 2, changed_at: '2026-10-26T12:01:00Z' }] };
  let responder;
  const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body, blob: async () => ({ type: 'application/pdf', size: 100 }) });
  const fetch = async (path, options) => {
    requests.push({ path, ...options, body: options.body ? JSON.parse(options.body) : null });
    if (responder) return responder(path, options);
    if (errorResponse) return errorResponse;
    const url = new URL(path, 'http://local'); const pieces = url.pathname.split('/').filter(Boolean); const resource = pieces[3]; const id = pieces[4]; const body = options.body ? JSON.parse(options.body) : null;
    if (pieces.length === 2) return response(options.method === 'POST' ? library : { items: [library], next_cursor: null });
    if (pieces.length === 3 || resource === 'reloads') return response({ ...library });
    if (resource === 'document-previews' || resource === 'reports.csv' || resource === 'backups' || pieces[5] === 'pdf') return response({});
    if (pieces[5] === 'archives') { record.archive_status = 'ready'; return response({ ...record }); }
    if (resource === 'assets' && options.method === 'GET') return assetGetOverride ? assetGetOverride() : response({ type: 'image/png', size: 8 });
    if (resource === 'assets') { library.revision += 1; return response({ id: nextAssetId, library_revision: library.revision }); }
    if (resource === 'reports') return response({ invoiced: '50.00', received: '0.00', outstanding: '50.00', overdue: '0.00', clients: [{ name: 'Acme', invoiced: '50.00', received: '0.00', outstanding: '50.00' }] });
    if (resource === 'recurring-draft-batches') { library.revision += 1; return response({ created_document_ids: ['generated'], remaining_count: 0, approval_required: [], library_revision: library.revision }); }
    if (resource === 'document-conversions') { library.revision += 1; return response({ documents: [{ ...record, state: 'draft' }], library_revision: library.revision }); }
    if (pieces[5] === 'transitions') { library.revision += 1; record.state = body.action === 'issue' ? 'issued' : body.action; record.status = record.state; record.library_revision = library.revision; return response({ ...record }); }
    if (pieces[5] === 'payments' || pieces[5] === 'payment-corrections') { library.revision += 1; return response({ document: { ...record, state: 'issued', status: 'paid' }, payments: [], library_revision: library.revision }); }
    if (options.method === 'GET') return response(id ? data[resource].find(row => row.id === id) : { items: data[resource], next_cursor: null });
    library.revision += 1;
    const { expected_revision, ...clean } = body;
    let result = { ...clean, id: id || `${resource}-new`, library_revision: library.revision };
    if (resource === 'documents') { Object.assign(record, { draft: clean, library_revision: library.revision }); result = { ...record }; }
    else { data[resource] = data[resource].filter(row => row.id !== result.id); data[resource].push(result); }
    return response(result, options.method === 'POST' ? 201 : 200);
  };
  const invoke = async (command, args) => { requests.push({ command, args }); return command === 'file_selection_open' ? nativeSelection : { ...library }; };
  window.fetch = fetch; window.__TAURI__ = { core: { invoke } };
  const workbench = module.create({ document: doc, fetch, invoke, uuid, storage, now: () => '2026-10-26', download: async (blob, name) => downloads.push({ blob, name }), objectUrl: () => 'blob:preview', revokeUrl: value => revoked.push(value), openEmail: value => emails.push(value), apiUrl: value => value });
  const click = async label => { const node = descendants(workbench.screen).find(node => ['BUTTON', 'A'].includes(node.tagName) && node.textContent === label); assert.ok(node, `action ${label}`); await node.fire('click', { preventDefault() {} }); };
  const change = async (label, value, index = 0) => { const field = [...workbench.fields.values()].filter(field => field.label === label)[index]; assert.ok(field, `field ${label}`); field.input.value = value; await field.input.fire('change'); };
  const attach = async () => { await workbench.chooseFolder(); workbench.render(); };
  return { module, workbench, window, registration, doc, data, profile, client, item, record, library, requests, downloads, revoked, emails, saved, storage, click, change, attach, response, setResponder: value => { responder = value; }, setError: value => { errorResponse = value; }, setAssetId: value => { nextAssetId = value; }, setAssetGetOverride: value => { assetGetOverride = value; }, setSelection: value => { nativeSelection = value; }, cancelPicker: () => { nativeSelection = null; } };
}

test('custom currency formatting keeps explicit precision, grouping and placement', () => {
  const context = { window: { OfficeKitExtensions: { register() {} } } };
  vm.runInNewContext(source, context, { filename: new URL('../assets/officekit-slice-invoices.js', import.meta.url).pathname });
  const format = context.window.OfficeKitInvoices.formatMoney;
  assert.equal(format('123456.70', { code: 'INR', symbol: '₹', precision: 2, grouping: 'indian', placement: 'before', decimal_separator: '.', grouping_separator: ',' }), '₹1,23,456.70');
  assert.equal(format('1234', { code: 'JPY', symbol: '¥', precision: 0, grouping: 'western', placement: 'after', decimal_separator: '.', grouping_separator: ',' }), '1,234 ¥');
  assert.equal(format('-12.3', { code: 'CUSTOM', symbol: '', precision: 3, grouping: 'none', placement: 'code', decimal_separator: ',', grouping_separator: '' }), 'CUSTOM −12,300');
});

test('registers one invoice destination, opens safe bindings and cancels folder selection without mutation', async () => {
  const h = harness();
  assert.equal(h.registration.slice, 'invoices');
  assert.equal(h.registration.destinations.invoice_manager.tab, 'invoices');
  await h.workbench.open();
  assert.match(h.workbench.screen.textContent, /Choose folder/);
  assert.match(h.workbench.screen.textContent, /Open Invoices/);
  await h.click('Open Invoices');
  assert.equal(h.requests.find(request => request.command === 'invoice_library_reconnect').args.bindingId, 'library');
  const h2 = harness(); h2.cancelPicker(); await h2.workbench.chooseFolder();
  assert.equal(h2.workbench.state.library, null);
  assert.equal(h2.requests.filter(request => request.method === 'POST').length, 0);
});

test('profile catalogue line copies remain editable without changing saved items or other profiles', async () => {
  const h = harness(); await h.attach();
  const other = h.module.newBusiness(() => 'other-currency'); other.id = 'other'; other.name = 'Another'; other.profile_name = '';
  h.data.businesses.push(other); await h.workbench.refresh(); h.workbench.render();
  await h.click('New document');
  await h.change('Saved item', 'item');
  assert.equal(h.workbench.state.editor.lines[0].description, 'Saved design');
  await h.change('Description & invoice-specific details', 'Additional delivery details');
  assert.equal(h.item.description, 'Saved design');
  assert.equal(h.workbench.state.editor.lines[0].description, 'Additional delivery details');
  await h.click('Add line'); assert.equal(h.workbench.state.editor.lines.length, 2);
  await h.click('Remove line'); assert.equal(h.workbench.state.editor.lines.length, 1);
  await h.change('Saved item', '');
  await h.change('Quantity', '3'); await h.change('Discount type', 'percent'); await h.change('Discount value', '10');
  await h.change('Notes', 'Thanks'); await h.change('Payment terms', 'Net 14');
  assert.equal(JSON.parse(h.saved.get('officekit.invoice-draft.v1')).businessId, 'business');
  await h.click('Save draft');
  const request = h.requests.find(request => request.method === 'POST' && request.path.endsWith('/documents'));
  assert.equal(request.body.lines[0].quantity, '3');
  assert.equal(request.body.expected_revision, 0);
  assert.equal(h.saved.has('officekit.invoice-draft.v1'), false);
  await h.click('Save draft');
  assert.ok(h.requests.some(request => request.method === 'PUT' && request.path.endsWith('/documents/document')));
  await h.workbench.navigate('documents'); await h.change('Business profile', 'other');
  assert.equal(h.workbench.state.businessId, 'other'); assert.equal(h.workbench.state.editor, null);
});

test('saved draft and issued document preview/download use authoritative PDF routes; email only drafts', async () => {
  const h = harness(); await h.attach(); await h.workbench.editDocument(h.record); h.workbench.render();
  await h.click('Preview PDF'); await h.click('Refresh preview');
  assert.deepEqual(h.revoked, ['blob:preview']);
  assert.ok(descendants(h.workbench.screen).some(node => node.tagName === 'IFRAME' && node.title === 'Invoice PDF preview'));
  await h.change('Description & invoice-specific details', 'Updated design');
  assert.match(h.workbench.screen.textContent, /Preview out of date/);
  assert.equal(descendants(h.workbench.screen).find(node => node.tagName === 'IFRAME').title, 'Out-of-date invoice PDF preview');
  await h.change('Description & invoice-specific details', 'Updated design again');
  const staleMessages = descendants(h.workbench.screen).filter(node => node.className === 'ok-invoice-preview-stale');
  assert.equal(staleMessages.length, 1, staleMessages.map(node => node.textContent).join(' | '));
  await h.click('Refresh preview');
  assert.doesNotMatch(h.workbench.screen.textContent, /Preview out of date/);
  assert.equal(descendants(h.workbench.screen).find(node => node.tagName === 'IFRAME').title, 'Invoice PDF preview');
  await h.click('Download PDF');
  assert.equal(h.downloads[0].name, 'invoice.pdf');
  await h.click('Issue document');
  assert.equal(h.workbench.state.editor.state, 'issued');
  await h.click('Download PDF');
  assert.ok(h.requests.some(request => request.path?.endsWith('/documents/document/pdf') && request.method === 'GET'));
  await h.click('Draft email');
  assert.match(h.emails[0], /^mailto:billing%40example.test\?subject=/);
  assert.match(decodeURIComponent(h.emails[0]), /attach the downloaded PDF before sending/);
  await h.change('Amount', '50'); await h.change('Payment date', '2026-10-26'); await h.change('Method', 'Wire'); await h.change('Reference', 'REF-1');
  await h.click('Record payment');
  assert.equal(h.requests.find(request => request.path?.endsWith('/payments')).body.amount, '50');
  await h.change('Payment ID to correct (optional)', 'payment'); await h.change('Correction reason', 'Incorrect reference');
  await h.click('Record payment');
  assert.equal(h.requests.find(request => request.path?.endsWith('/payment-corrections')).body.replacement.expected_revision, h.library.revision - 1);
  h.workbench.newDocument();
  assert.equal(h.workbench.state.previewUrl, '');
  assert.ok(h.revoked.length >= 2);
});

test('preview freshness survives an offscreen editor and clears safely when switching drafts', async () => {
  const h = harness(); await h.attach(); h.workbench.newDocument(); h.workbench.render();
  h.workbench.state.previewUrl = 'blob:preview';
  await h.change('Description & invoice-specific details', 'Changed while preview frame is absent');
  assert.match(h.workbench.screen.textContent, /Preview out of date/);
  const description = [...h.workbench.fields.values()].find(field => field.label === 'Description & invoice-specific details');
  h.workbench.screen.replaceChildren(); description.input.value = 'Changed while editor is detached'; await description.input.fire('change');
  assert.equal(h.workbench.state.previewStale, true);
  h.workbench.newDocument();
  assert.equal(h.workbench.state.previewUrl, '');
  assert.ok(h.revoked.includes('blob:preview'));
});

test('new draft issue first saves; quotes support acceptance, decline and idempotent deposit conversion', async () => {
  const h = harness(); await h.attach(); h.workbench.newDocument(); h.workbench.render();
  await h.change('Description & invoice-specific details', 'Quote work');
  await h.click('Issue document');
  assert.ok(h.requests.some(request => request.path?.endsWith('/documents') && request.method === 'POST'));
  h.record.kind = 'quote'; h.record.draft.kind = 'quote'; h.record.state = 'issued';
  await h.workbench.editDocument(h.record); h.workbench.render();
  await h.click('Apply quote action'); assert.equal(h.record.state, 'accept');
  await h.change('Quote action', 'decline'); await h.click('Apply quote action'); assert.equal(h.record.state, 'decline');
  await h.change('Quote action', 'deposit'); await h.change('Deposit / balance amount', '10'); await h.click('Apply quote action');
  const request = h.requests.find(request => request.path?.endsWith('/document-conversions'));
  assert.equal(request.body.source_quote_id, 'document'); assert.equal(request.body.kind, 'deposit'); assert.equal(request.body.amount, '10');
});

test('documents filter by search/status, preserve recovery and render empty results', async () => {
  const h = harness(); await h.attach();
  await h.change('Search documents', 'missing'); assert.match(h.workbench.screen.textContent, /No matching records/);
  await h.change('Search documents', 'Acme'); await h.change('Status', 'paid'); assert.match(h.workbench.screen.textContent, /No matching records/);
  await h.change('Status', ''); await h.click('DRAFT'); assert.equal(h.workbench.state.view, 'editor');
  h.workbench.persistDraft(); h.workbench.restoreDraft(); h.workbench.navigate('documents');
  await h.click('Review recovered draft'); assert.equal(h.workbench.state.editor.client_id, 'client');
});

test('catalogue creates and updates clients and items without inventory stock fields', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('catalogue');
  await h.click('New record'); await h.change('Private item name', 'Advisory'); await h.change('Printed description', 'Consulting details'); await h.change('Default rate', '120'); await h.click('Save record');
  assert.ok(h.data.items.some(item => item.private_name === 'Advisory'));
  await h.click('Design'); await h.change('Printed description', 'Updated item'); await h.click('Save record');
  assert.equal(h.data.items.find(item => item.id === 'item').description, 'Updated item');
  await h.change('Catalogue', 'clients'); await h.click('New record'); await h.change('Client name', 'New client'); await h.change('Email', 'new@example.test'); await h.change('Address', 'New address'); await h.click('Save record');
  await h.change('Catalogue', 'clients'); await h.click('Acme'); await h.change('Contact', 'Finance'); await h.click('Save record');
  assert.equal(h.data.clients.find(client => client.id === 'client').contact, 'Finance');
  assert.equal(h.requests.filter(request => request.body && JSON.stringify(request.body).includes('stock')).length, 0);
});

test('settings save independent profiles through the wizard and preserve advanced configuration', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('settings');
  await h.change('Profile name', 'India'); await h.change('Business address', 'Business address'); await h.change('Add currency preset', 'INR'); await h.click('Add currency');
  assert.equal(h.workbench.state.settings.currencies[1].code, 'INR');
  await h.change('Currency code', 'TOKEN', 1); await h.change('Decimal places', '8', 1); await h.change('Symbol placement', 'code', 1);
  await h.click('Add tax profile'); await h.change('Tax profile name', 'VAT'); await h.change('Price treatment', 'true'); await h.click('Add tax row'); await h.change('Tax label', 'VAT'); await h.change('Rate (%)', '20'); await h.change('Calculation', 'compound');
  await h.click('Add payment method'); await h.change('Bank name', 'Bank'); await h.change('Payment link', 'https://pay.example.test'); await h.change('QR payload', 'payment-reference'); await h.change('Instructions', 'Pay within 14 days');
  await h.change('Layout', 'Bold'); await h.change('Footer', 'Thank you'); await h.change('Next counter', '27');
  await h.click('Edit profile'); await h.click('Continue'); await h.change('Currency', 'INR');
  h.workbench.state.wizard.record.default_template_id = 'missing-template'; await h.change('Invoice design', 'Compact');
  await h.click('Upload logo'); assert.equal(h.workbench.state.wizard.record.templates[0].logo_id, 'logo'); assert.equal(h.workbench.state.logoPreviewUrl, 'blob:preview');
  await h.click('Upload logo'); assert.equal(h.workbench.state.logoPreviewUrl, 'blob:preview');
  await h.click('Finish profile'); await h.click('Save');
  const saved = h.data.businesses.find(profile => profile.id === 'business');
  assert.equal(saved.profile_name, 'India'); assert.equal(saved.tax_profiles[0].inclusive, true); assert.equal(saved.currencies[1].precision, 8);
  h.workbench.navigate('settings'); await h.click('New profile'); await h.change('Profile name', 'International'); await h.change('Business name', 'Northstar'); await h.click('Continue');
  await h.change('Currency', 'INR'); await h.change('Invoice design', 'Bold'); await h.click('Finish profile');
  assert.equal(h.data.businesses.length, 2);
  assert.equal(h.workbench.state.businessId, 'businesses-new');
  const international = h.data.businesses.find(profile => profile.id === 'businesses-new');
  assert.equal(international.currencies.find(currency => currency.id === international.default_currency_id).code, 'INR');
  h.workbench.state.businessId = 'business'; h.workbench.navigate('settings'); await h.click('Edit profile'); await h.click('Continue');
  await new Promise(resolve => setTimeout(resolve, 0)); assert.equal(h.workbench.state.logoPreviewUrl, 'blob:preview');
  h.cancelPicker(); await h.click('Upload logo');
  h.setAssetId('logo-2'); h.setSelection({ id: 'selected', displayNames: ['Replacement logo'] }); await h.click('Upload logo');
  assert.equal(h.workbench.state.wizard.record.templates[0].logo_id, 'logo-2');
  await h.click('Back'); await h.click('Cancel');
  assert.equal(h.requests.filter(request => request.path?.endsWith('/assets') && request.method === 'POST').length, 3);
});

test('first library opens profile settings with no imposed tax profile', async () => {
  const h = harness(); h.data.businesses = []; await h.attach();
  assert.equal(h.workbench.state.view, 'settings'); assert.equal(h.workbench.state.wizard.step, 1); assert.equal(h.workbench.state.settings.tax_profiles.length, 1);
  assert.equal(h.workbench.state.settings.tax_profiles[0].rows.length, 0);
  const profile = h.workbench.state.wizard.record;
  assert.equal(profile.currencies.find(currency => currency.id === profile.default_currency_id).code, 'USD');
  assert.equal(profile.tax_profiles.find(tax => tax.id === profile.default_tax_profile_id).name, 'No tax');
  assert.equal(profile.templates.find(template => template.id === profile.default_template_id).layout, 'Classic');
  const wizardDialog = descendants(h.workbench.screen).find(node => node.tagName === 'DIALOG');
  assert.match(wizardDialog.className, /\bmodal\b/);
  await h.change('Business name', 'Northstar Studio'); await h.click('Continue'); await h.click('Finish profile');
  assert.equal(h.workbench.state.view, 'documents'); assert.equal(h.workbench.state.businessId, 'businesses-new');
});

test('first-run wizard requires a business name and can be resumed after cancel', async () => {
  const h = harness(); h.data.businesses = []; await h.attach();
  await h.click('Continue');
  assert.equal(h.workbench.state.wizard.step, 1); assert.equal(h.workbench.state.error, 'Business name is required.');
  await assert.rejects(h.workbench.saveSettings(), /Business name is required/);
  await h.change('Business name', 'Retained business');
  await h.click('Cancel');
  assert.equal(h.workbench.state.wizard, null);
  assert.equal(h.requests.filter(request => request.path?.endsWith('/businesses') && request.method === 'POST').length, 0);
  await h.click('New profile'); assert.equal(h.workbench.state.wizard.step, 1); assert.equal(h.workbench.state.wizard.record.name, 'Retained business');
});

test('closing a profile wizard while an existing logo loads ignores the stale preview', async () => {
  const h = harness(); await h.attach(); h.profile.templates[0].logo_id = 'pending-logo';
  h.workbench.navigate('settings'); await h.click('Edit profile');
  let startLoad; const started = new Promise(resolve => { startLoad = resolve; });
  let releaseLoad; const gate = new Promise(resolve => { releaseLoad = resolve; });
  h.setAssetGetOverride(async () => { startLoad(); await gate; return h.response({ type: 'image/png', size: 8 }); });
  await h.click('Continue'); await started;
  await h.click('Back'); await h.click('Cancel'); releaseLoad();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(h.workbench.state.wizard, null); assert.equal(h.workbench.state.logoPreviewUrl, '');
});

test('recurring schedule creation/edit and startup catch-up create drafts for review', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('recurring');
  await h.click('New schedule'); await h.click('Continue to schedule');
  assert.match(h.workbench.screen.textContent, /Choose a client to continue/);
  await h.change('Client', 'client'); await h.click('Continue to schedule');
  assert.match(h.workbench.screen.textContent, /Add a description for this invoice item/);
  await h.change('Description', 'Monthly service'); await h.click('Continue to schedule');
  assert.match(h.workbench.screen.textContent, /Invoice details to repeat.*DescriptionQuantityRate.*Monthly service.*1.*\$0\.00 · USD/);
  assert.equal(descendants(h.workbench.screen).filter(node => node.tagName === 'BUTTON' && node.className.split(/\s+/).includes('btn')).length, 2);
  await h.click('Back');
  assert.match(h.workbench.screen.textContent, /Invoice details · Step 1 of 2/);
  await h.click('Continue to schedule'); await h.change('Frequency', 'quarterly'); await h.change('End date', '2027-10-26'); await h.change('Occurrence limit', '3'); await h.click('Save schedule');
  assert.equal(h.data.schedules[0].frequency, 'quarterly');
  assert.equal(h.data.schedules[0].draft.client_id, 'client');
  assert.equal(h.data.schedules[0].draft.lines[0].description, 'Monthly service');
  await h.click(h.data.schedules[0].id); await h.change('Missed occurrences', 'ask'); await h.click('Back');
  await h.click(h.data.schedules[0].id); await h.change('Missed occurrences', 'ask'); await h.click('Save schedule');
  await h.click('Review missed drafts'); assert.match(h.workbench.state.message, /1 recurring drafts created/);
  h.data.schedules[0].catch_up = 'each'; await h.workbench.open();
  assert.match(h.workbench.state.message, /1 recurring drafts are ready/);
  h.data.schedules[0].paused = true; h.workbench.navigate('recurring'); assert.match(h.workbench.screen.textContent, /Paused/);
  h.workbench.state.editor = null; await h.click('New schedule'); await h.change('Client', 'client'); await h.change('Description', 'Monthly service'); await h.click('Continue to schedule'); await h.change('End date', ''); await h.change('Occurrence limit', '0'); await h.click('Save schedule');
  assert.equal(h.requests.filter(request => request.path?.endsWith('/schedules') && request.method === 'POST').at(-1).body.end_count, null);
  const incomplete = { ...h.data.schedules[0], id: 'incomplete-schedule', draft: { ...h.data.schedules[0].draft, client_id: 'missing-client', currency_id: 'missing-currency', lines: [{ ...h.data.schedules[0].draft.lines[0], description: '' }, { description: 'Second service', quantity: '1', rate: '5' }] } };
  h.data.schedules.push(incomplete); await h.workbench.refresh(); h.workbench.navigate('recurring'); await h.click('incomplete-schedule');
  assert.match(h.workbench.screen.textContent, /Invoice details to repeat.*Untitled item10.*Second service15/);
});

test('reports keep explicit currency boundaries and download the same filtered period', async () => {
  const h = harness(); await h.attach(); await h.workbench.navigate('reports');
  assert.match(h.workbench.screen.textContent, /\$50.00/);
  h.setError(h.response({ error: { message: 'Report unavailable', details: [] } }, 503));
  await h.change('From', '2026-10-01');
  assert.equal(h.workbench.state.report, null);
  assert.doesNotMatch(h.workbench.screen.textContent, /\$50\.00/);
  assert.match(h.workbench.screen.textContent, /Report unavailable/);
  h.setError(null);
  await h.change('From', '2026-10-01'); await h.change('To', '2026-10-26'); await h.click('Download CSV');
  assert.equal(h.downloads[0].name, 'invoice-report.csv');
  const other = h.module.newBusiness(() => 'other-currency'); other.id = 'other'; other.name = 'Southstar'; other.profile_name = '';
  h.data.businesses.push(other); await h.workbench.refresh(); h.workbench.render();
  await h.change('Business profile', 'other');
  assert.match(h.workbench.screen.textContent, /Report · Southstar/);
  assert.ok(h.requests.some(request => request.path?.includes(`business_id=other&start=2026-10-01&end=2026-10-26&currency_id=${other.default_currency_id}`)));
  h.setError(h.response({ error: { message: 'Unknown report currency', details: [] } }, 503));
  await h.change('Currency', 'unsupported');
  assert.match(h.workbench.screen.textContent, /Report · Southstar ·  ·/);
  h.setError(null);
  assert.ok(h.requests.some(request => request.path?.includes('business_id=business&start=2026-10-01&end=2026-10-26&currency_id=')));
});

test('folder reconnect/reload are explicit and never run a cloud sync job', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('folder'); h.workbench.state.library.status = 'unavailable'; h.workbench.render(); await h.click('Reconnect folder');
  const more = descendants(h.workbench.screen).find(node => node.attributes['aria-label'] === 'More workspace actions');
  more.value = 'reload'; await more.fire('change');
  assert.ok(h.requests.some(request => request.path?.endsWith('/reloads') && request.method === 'POST'));
  assert.equal(h.requests.some(request => /sync/.test(request.path || '')), false);
  await h.click('Choose folder');
});

test('folder controls keep three buttons, expose secondary actions in a picker, and clear stale feedback', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('folder');
  const controls = descendants(h.workbench.screen).find(node => node.className === 'ok-invoice-folder-actions');
  assert.ok(controls);
  assert.deepEqual(controls.children.map(node => node.className), ['ok-invoice-folder-primary']);
  assert.deepEqual(controls.children[0].children.map(node => node.textContent), ['Choose folder', 'Create backup', 'Restore backup']);
  const secondary = descendants(h.workbench.screen).find(node => node.className === 'ok-invoice-folder-secondary');
  assert.equal(secondary.tagName, 'DETAILS');
  assert.equal(secondary.children[0].textContent, 'More workspace actions');
  assert.deepEqual(secondary.children[1].children.map(node => node.textContent), ['Choose an action', 'Workspace history', 'Reload changed library']);
  assert.equal(controls.children[0].children.filter(node => node.tagName === 'BUTTON').length, 3);
  assert.equal(descendants(h.workbench.screen).filter(node => node.className.split(/\s+/).includes('btn')).length, 3);
  h.workbench.state.message = 'Draft saved.'; h.workbench.navigate('documents');
  assert.equal(h.workbench.state.message, '');
  assert.doesNotMatch(h.workbench.screen.textContent, /Draft saved\./);
  const failedHistory = harness(); await failedHistory.attach(); failedHistory.workbench.navigate('folder');
  failedHistory.setError(failedHistory.response({ error: { message: 'History unavailable', details: [] } }, 503));
  const historyPicker = descendants(failedHistory.workbench.screen).find(node => node.attributes['aria-label'] === 'More workspace actions');
  historyPicker.value = 'history'; await historyPicker.fire('change');
  assert.match(failedHistory.workbench.state.error, /History unavailable/);
});

test('strict API failures, conflicts and validation preserve drafts and provide focused errors', async () => {
  const h = harness(); await h.attach(); h.workbench.newDocument(); h.workbench.render();
  h.setError(h.response({ error: { message: 'Changed externally', details: [] } }, 409)); await h.click('Save draft');
  assert.match(h.workbench.state.error, /Changed externally.*draft is preserved/);
  assert.equal(h.doc.activeElement.attributes.role, 'alert');
  h.setError(h.response({ error: { message: 'Invalid currency', details: [{ message: 'Check symbol' }] } }, 422)); await h.click('Save draft'); assert.match(h.workbench.state.error, /Check symbol/);
  h.setError(h.response({ error: { message: 'Invalid field', details: [{}] } }, 422)); await h.click('Save draft'); assert.match(h.workbench.state.error, /Review the invoice details and try again/);
  h.setError(h.response({ detail: 'Sign in again' }, 401)); await h.click('Save draft'); assert.equal(h.workbench.state.error, 'Sign in again');
  h.setError({ ok: false, status: 503, json: async () => { throw new Error('HTML error'); } }); await h.click('Save draft'); assert.match(h.workbench.state.error, /503/);
  h.setError(h.response(null)); await assert.rejects(h.workbench.request('/invalid'), /invalid invoice response/);
  h.setError(h.response({ items: 'not-list' })); await h.workbench.open(); assert.match(h.workbench.state.error, /invalid invoice list/);
  const h2 = harness(); h2.setError(h2.response({ items: false })); await h2.workbench.open(); assert.match(h2.workbench.state.error, /invalid folder list/);
});

test('missing client is shown inline and focused before save or issue', async () => {
  const h = harness(); await h.attach(); h.workbench.state.clients = []; h.workbench.newDocument(); h.workbench.render();
  await h.click('Save draft');
  assert.match(h.workbench.screen.textContent, /Choose a client before saving or issuing this document/);
  await h.click('Issue document');
  const client = [...h.workbench.fields.values()].find(field => field.key === 'client_id').input;
  assert.equal(h.doc.activeElement, client);
  assert.equal(client.attributes['aria-invalid'], 'true');
  assert.match(h.workbench.screen.textContent, /Choose a client before saving or issuing this document/);
  assert.equal(h.requests.some(request => request.path?.endsWith('/documents/transitions')), false);
  await h.change('Client', 'client');
  assert.equal([...h.workbench.fields.values()].find(field => field.key === 'client_id').input.attributes['aria-invalid'], undefined);
  h.record.draft.client_id = '';
  h.workbench.state.clients = [];
  await h.workbench.editDocument(h.record); h.workbench.render(); await h.click('Issue document');
  assert.equal(h.workbench.state.editor.state, 'draft');
  assert.match(h.workbench.screen.textContent, /Choose a client before saving or issuing this document/);
});

test('recovery storage failures, mismatched libraries and malformed recovery stay local', async () => {
  const h = harness(); await h.attach(); h.workbench.newDocument();
  h.storage.setItem = () => { throw new Error('quota'); }; h.workbench.persistDraft(); assert.match(h.workbench.state.message, /recovery storage is unavailable/);
  h.saved.set('officekit.invoice-draft.v1', '{'); h.workbench.restoreDraft(); assert.match(h.workbench.state.message, /could not be read/);
  h.workbench.state.recovery = null; h.saved.set('officekit.invoice-draft.v1', JSON.stringify({ libraryId: 'another' })); h.workbench.restoreDraft(); assert.equal(h.workbench.state.recovery, null);
  h.workbench.state.busy = true; let called = false; await h.workbench.run(() => { called = true; }); assert.equal(called, false);
});

test('full workspace backup, restore and history use opaque selections and three counted buttons', async () => {
  const h = harness(); await h.attach(); h.workbench.navigate('folder');
  const count = () => descendants(h.workbench.screen).filter(node => node.tagName === 'BUTTON' && node.className.split(/\s+/).includes('btn')).length;
  assert.equal(count(), 3); await h.click('Create backup'); assert.equal(h.downloads[0].name, 'officekit-invoices-backup.zip');
  assert.deepEqual(h.requests.find(request => request.path?.endsWith('/backups')).body, {});
  const more = descendants(h.workbench.screen).find(node => node.attributes['aria-label'] === 'More workspace actions');
  more.value = 'history'; await more.fire('change'); assert.match(h.workbench.screen.textContent, /Invoice issued/);
  await h.change('History business profile', 'business'); assert.doesNotMatch(h.workbench.screen.textContent, /Workspace updated/);
  await h.click('Workspace settings'); await h.click('Restore backup'); assert.equal(count(), 3);
  let restore = descendants(h.workbench.screen).find(node => node.textContent === 'Restore & open workspace'); assert.equal(restore.disabled, true);
  await h.click('Choose backup file'); await h.click('Choose parent folder');
  restore = descendants(h.workbench.screen).find(node => node.tagName === 'BUTTON' && node.textContent === 'Restore & open workspace'); assert.equal(restore.disabled, false);
  await h.click('Restore & open workspace');
  assert.deepEqual(h.requests.find(request => request.path === '/api/invoice-restorations').body, { selection_id: 'selected', backup_selection_id: 'selected' });
  await h.click('Restore backup'); h.cancelPicker(); await h.click('Choose backup file'); await h.click('Choose parent folder'); await h.click('Cancel');
  assert.equal(h.workbench.state.view, 'folder');
});

test('invoice-specific tax exemptions are typed booleans and pending archives retry within Download PDF', async () => {
  const h = harness(); await h.attach(); h.workbench.newDocument(); h.workbench.render();
  await h.change('Tax exemption', 'true'); await h.change('Line date', '2026-10-25'); await h.change('Section', 'Consultancy');
  assert.equal(h.workbench.draftPayload().lines[0].tax_exempt, true);
  h.record.state = 'issued'; h.record.archive_status = 'pending'; await h.workbench.editDocument(h.record); h.workbench.render();
  await h.click('Download PDF'); assert.ok(h.requests.some(request => request.path?.endsWith('/archives'))); assert.equal(h.workbench.state.editor.archive_status, 'ready');
  h.workbench.navigate('catalogue'); await h.click('Design'); await h.change('Default tax behavior', 'true'); await h.click('Save record');
  assert.equal(h.data.items.find(item => item.id === 'item').tax_exempt, true);
});

test('pagination follows opaque cursors and rejects cycles without hiding malformed results', async () => {
  const h = harness(); await h.attach();
  const calls = [];
  h.setResponder((path) => {
    calls.push(path);
    if (path === '/api/invoice-libraries/library') return h.response(h.library);
    if (path.endsWith('/businesses')) return h.response({ items: [h.profile], next_cursor: 'page two' });
    if (path.endsWith('/businesses?cursor=page%20two')) return h.response({ items: [], next_cursor: null });
    return h.response({ items: [], next_cursor: null });
  });
  await h.workbench.refresh(); assert.ok(calls.some(path => path.endsWith('cursor=page%20two')));
  h.setResponder(path => path.endsWith('/library') ? h.response(h.library) : h.response({ items: [h.profile], next_cursor: 'again' }));
  await assert.rejects(h.workbench.refresh(), /invalid invoice list/);
});

test('production mount wrappers preserve native access boundaries and use shared download helpers', async () => {
  const h = harness(); await h.registration.openView('documents');
  const mounted = () => h.doc.getElementById('app-main').children.at(-1);
  const click = async label => { const button = descendants(mounted()).find(node => ['BUTTON', 'A'].includes(node.tagName) && node.textContent === label); assert.ok(button, label); await button.fire('click', { preventDefault() {} }); };
  await click('Choose folder');
  await h.module.open('documents');
  await click('New document');
  await click('Preview PDF'); await click('Refresh preview'); await click('Download PDF');
  await click('Issue document'); await click('Draft email');
  assert.equal(h.downloads.length, 2); assert.match(h.window.location.href, /^mailto:/);
  await click('Settings'); await click('New profile');
  const missing = harness(); delete missing.window.__TAURI__; await missing.module.open('documents');
  const node = missing.doc.getElementById('app-main').children.at(-1);
  await descendants(node).find(item => item.tagName === 'BUTTON' && item.textContent === 'Choose folder').fire('click');
  assert.match(node.textContent, /requires the OfficeKit desktop app/);
});

test('remaining boundary paths cover custom currency rejection, optional dates and empty catalogues', async () => {
  const h = harness();
  assert.throws(() => h.module.currencyPreset('UNLISTED', () => 'id'), /custom currency/);
  await h.attach();
  h.record.draft.due_date = null; h.record.draft.valid_until = '2026-11-30'; h.workbench.render(); assert.match(h.workbench.screen.textContent, /2026-11-30/);
  h.record.draft.valid_until = null; h.workbench.render(); assert.match(h.workbench.screen.textContent, /—/);
  h.workbench.state.clients = []; h.workbench.newDocument(); assert.equal(h.workbench.state.editor.client_id, '');
  h.record.state = 'issued'; h.record.client.email = ''; await h.workbench.editDocument(h.record); h.workbench.render();
  h.workbench.payment.date = ''; h.workbench.payment.amount = '1'; await h.click('Record payment');
  assert.equal(h.requests.find(request => request.path?.endsWith('/payments')).body.date, '2026-10-26');
  await h.click('Draft email'); assert.match(h.emails[0], /^mailto:\?subject=/);
  h.record.kind = 'quote'; h.record.draft.kind = 'quote'; await h.workbench.editDocument(h.record); h.workbench.render(); h.workbench.quote.action = 'full'; await h.click('Apply quote action');
  assert.equal(h.requests.find(request => request.path?.endsWith('/document-conversions')).body.amount, null);
  h.workbench.navigate('settings'); h.workbench.state.settings.default_tax_profile_id = ''; await h.click('Add payment method');
  h.workbench.state.settings.payment_methods[0].fields[0].label = ''; h.workbench.render(); assert.ok([...h.workbench.fields.values()].some(field => field.label === 'Field value'));
  await h.click('Save');
  h.data.history.push({ changed_at: 'today', business_id: 'business' }); await h.workbench.navigate('history'); assert.match(h.workbench.screen.textContent, /Global/);
});

test('collection cursors append to existing business queries and mutations reject missing revision', async () => {
  const h = harness(); await h.attach();
  h.setResponder(path => {
    if (path === '/api/invoice-libraries/library') return h.response(h.library);
    if (path.endsWith('/businesses')) return h.response({ items: [h.profile], next_cursor: null });
    if (path.endsWith('/clients?business_id=business')) return h.response({ items: [h.client], next_cursor: 'next' });
    return h.response({ items: [], next_cursor: null });
  });
  await h.workbench.refresh(); assert.ok(h.requests.some(request => request.path?.includes('clients?business_id=business&cursor=next')));
  h.setResponder(() => h.response({ id: 'missing-revision' })); h.workbench.state.editor = { ...h.record.draft }; await assert.rejects(h.workbench.saveDocument(), /invalid library revision/);
});

test('client dropdown offers New client, saves it and returns to the draft with that client selected', async () => {
  const h = harness(); await h.attach();
  await h.click('New document');
  const options = [...h.workbench.fields.values()].find(field => field.label === 'Client').input.children.map(option => option.textContent);
  assert.ok(options.includes('+ New client'));
  await h.change('Client', '__new_client__');
  assert.equal(h.workbench.state.view, 'catalogue');
  assert.equal(h.workbench.state.catalogue.type, 'clients');
  await h.change('Client name', 'Globex');
  await h.click('Save record');
  assert.equal(h.workbench.state.view, 'editor');
  const created = h.data.clients.find(row => row.name === 'Globex');
  assert.ok(created);
  assert.equal(h.workbench.state.editor.client_id, created.id);
  assert.equal(JSON.parse(h.saved.get('officekit.invoice-draft.v1')).editor.client_id, created.id);
});

test('saving a client from the Clients tab refreshes the visible client list', async () => {
  const h = harness(); await h.attach();
  await h.click('Clients & items');
  await h.change('Catalogue', 'clients');
  await h.click('New record');
  await h.change('Client name', 'Initech');
  await h.click('Save record');
  const names = [...h.workbench.screen.querySelectorAll('button')].map(node => node.textContent);
  assert.ok(names.includes('Initech'), `client list shows ${names.join(', ')}`);
});
