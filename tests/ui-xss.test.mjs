import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(repoRoot, 'index.html'), 'utf8');
const bundledHtml = fs.readFileSync(path.join(repoRoot, 'dist-ui/index.html'), 'utf8');

class FakeElement {
  #innerHTML = '';
  get innerHTML() { return this.#innerHTML; }
  set innerHTML(value) {
    this.#innerHTML = value;
    if (value === '') this.children = [];
  }
  textContent = '';
  className = '';
  children = [];
  attributes = {};
  classList = { add() {}, remove() {} };
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  closest() { return null; }
  appendChild(child) { this.children.push(child); }
}

function renderer(name, _nextFunction, context) {
  const escape = html.match(/function officekitEscapeHtml\(value\) \{[\s\S]*?\n        \}/)?.[0];
  const statementCellMarkup = html.match(/function statementCellMarkup\(value, label\) \{[\s\S]*?\n        \}/)?.[0];
  const source = html.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n        \\}(?=\\n\\n        (?:async )?function [A-Za-z_$][\\w$]*\\()`))?.[0];
  assert.ok(escape, 'shared HTML escaping helper exists');
  assert.ok(source, `${name} renderer exists`);
  vm.runInNewContext(`${escape}\n${statementCellMarkup || ''}\n${source}`, context);
  return context[name];
}

test('statement renderer displays hostile imported values as text', () => {
  const elements = new Map();
  const created = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement());
      return elements.get(id);
    },
    createElement() {
      const element = new FakeElement();
      created.push(element);
      return element;
    },
  };
  const context = { document, Number };
  const render = renderer('renderStatementResults', 'exportStatement', context);
  render({
    reconciliation: { valid: false, status: 'discrepancy', checked_rows: 1, unverified_rows: 0, discrepancies_count: '<img src=x onerror=alert(1)>' },
    transactions: [{
      id: '1</td><script>alert(1)</script>',
      date: '2026-01-01',
      description: '<img src=x onerror=alert(1)> café',
      debit: null,
      credit: null,
      balance: null,
      status: 'ok',
    }],
  });

  assert.equal(created.length, 1);
  assert.doesNotMatch(created[0].innerHTML, /<script|<img/i);
  assert.match(created[0].innerHTML, /&lt;img src=x onerror=alert\(1\)&gt; café/);
  assert.doesNotMatch(elements.get('reconciliation-banner').innerHTML, /<img/i);
  assert.equal(elements.get('reconciliation-banner').attributes['aria-live'], 'polite');
});

test('statement renderer explains all four reconciliation states and row statuses', () => {
  const elements = new Map();
  const created = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement());
      return elements.get(id);
    },
    createElement() {
      const element = new FakeElement();
      created.push(element);
      return element;
    },
  };
  const context = { document, Number };
  const render = renderer('renderStatementResults', 'exportStatement', context);
  const scenarios = [
    { status: 'verified', valid: true, checked_rows: 2, unverified_rows: 0, discrepancies_count: 0, title: 'All balance movements matched' },
    { status: 'partial', valid: null, checked_rows: 1, unverified_rows: 1, discrepancies_count: 0, title: 'Some balance rows could not be checked' },
    { status: 'discrepancy', valid: false, checked_rows: 2, unverified_rows: 1, discrepancies_count: 1, title: 'A balance mismatch needs review' },
    { status: 'unverified', valid: null, checked_rows: 0, unverified_rows: 2, discrepancies_count: 0, title: 'Balance math could not be verified' },
  ];
  for (const reconciliation of scenarios) {
    render({
      reconciliation,
      transactions: [
        { id: 1, status: 'baseline', balance: 100 },
        { id: 2, status: 'unverified', balance: 90, debit: null, credit: null },
        { id: 3, status: 'reconciliation_warning', balance: 80, debit: 10 },
        { id: 4, status: 'ok', balance: 70, debit: 10 },
      ],
    });
    const banner = elements.get('reconciliation-banner');
    const rows = elements.get('transactions-tbody').children;
    assert.match(banner.innerHTML, new RegExp(reconciliation.title));
    assert.match(banner.innerHTML, new RegExp(`${reconciliation.checked_rows}\\s*</strong> movements checked`));
    assert.match(banner.innerHTML, new RegExp(`${reconciliation.unverified_rows}\\s*</strong> rows unchecked`));
    assert.match(banner.innerHTML, new RegExp(`${reconciliation.discrepancies_count}\\s*</strong> mismatches`));
    assert.equal(rows.length, 4);
    assert.match(rows[0].innerHTML, /Starting balance/);
    assert.match(rows[1].innerHTML, /Amount not detected/);
    assert.match(rows[2].innerHTML, /Mismatch/);
    assert.match(rows[3].innerHTML, /Balance matched/);
  }
  assert.match(html, /A balance check confirms arithmetic only/);
  assert.match(html, /does not verify the statement's authenticity or that extracted values are correct/);
  assert.match(html, /exportStatement\('csv'\)/);
  assert.match(html, /exportStatement\('excel'\)/);
});

test('statement renderer bounds long date and narration previews without losing raw text', () => {
  const elements = new Map();
  const created = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement());
      return elements.get(id);
    },
    createElement() {
      const element = new FakeElement();
      created.push(element);
      return element;
    },
  };
  const context = { document, Number };
  const render = renderer('renderStatementResults', 'exportStatement', context);
  const longDate = '21/09/26 25/09/26 25/09/26 25/09/26';
  const longDescription = 'FOREIGNINNRPACBINW-TXN000000RO-ORBITX NETWORKGROUPPTELTD-SKYDO NEFTDR-UTIB0004034-JENNIFER ANDERSSON-NETBANK,MUM-HDFC00000000001-BB00N000001 12000000000003 50100000000001-TPT-HDFCAAAA0000001-MARY JANESMITH50100000000002-TPT-HDFCBBBB0000002-JOHNPAULDAWSO';
  render({
    reconciliation: { status: 'unverified', valid: null },
    transactions: [{ id: 1, date: longDate, description: longDescription, debit: null, credit: null, balance: null, status: 'unverified' }],
  });

  const row = created[0].innerHTML;
  assert.match(row, /statement-cell-details/);
  assert.match(row, /Show full date/);
  assert.match(row, /Show full description/);
  assert.match(row, /aria-label="Full extracted date"/);
  assert.match(row, /aria-label="Full extracted description"/);
  assert.ok(row.includes(longDate));
  assert.ok(row.includes(longDescription));
  assert.match(html, /max-h-\[500px\]/);
  assert.match(html, /overflow-x-auto/);
});

test('statement amounts do not imply a currency the parser never identified', () => {
  const elements = new Map();
  const created = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement());
      return elements.get(id);
    },
    createElement() {
      const element = new FakeElement();
      created.push(element);
      return element;
    },
  };
  const context = { document, Number };
  const render = renderer('renderStatementResults', 'exportStatement', context);
  render({
    reconciliation: { status: 'unverified', valid: null },
    transactions: [{ id: 1, date: '05/10/2026', description: 'UPI transfer', debit: 250.5, credit: null, balance: 12500, status: 'unverified' }],
  });

  const row = created[0].innerHTML;
  assert.doesNotMatch(row, /\$/);
  assert.match(row, />250\.50</);
  assert.match(row, />12500\.00</);
  assert.match(html, /source currency is not inferred/i);
});

test('tool search treats API catalogue values as text and avoids inline handlers', () => {
  const container = new FakeElement();
  container.querySelectorAll = () => [];
  const document = { getElementById: () => container };
  const destinations = html.match(/const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{[\s\S]*?\n        \}\);/)?.[0];
  assert.ok(destinations, 'stable search destination map exists');
  const context = { document, selectSearchTool() {} };
  vm.runInNewContext(`${destinations}\nfunction officekitToolDestination(id) { return OFFICEKIT_TOOL_DESTINATIONS[id]; }`, context);
  const render = renderer('renderSearchResults', 'selectSearchTool', context);
  render([{ id: "tools' onmouseover='alert(1)", icon: 'fa-file', name: '<svg onload=alert(1)>', category: 'PDF', desc: 'Résumé' }]);

  assert.doesNotMatch(container.innerHTML, /<svg/i);
  assert.doesNotMatch(container.innerHTML, /onclick=/i);
  assert.match(container.innerHTML, /&lt;svg onload=alert\(1\)&gt;/i);
  assert.match(container.innerHTML, /data-tool-id="tools&#39; onmouseover=&#39;alert\(1\)"/);
  assert.match(container.innerHTML, /Unavailable/);
});

test('calculator result renderers escape or reject untrusted API values', async () => {
  const attack = '<img src=x onerror=alert(1)>';
  for (const [functionName, values] of [
    ['runEmiCalc', { monthly_emi: attack, total_interest: attack, total_payment: attack }],
    ['runCompoundCalc', { future_value: attack, total_invested: attack, total_interest_earned: attack }],
    ['runVatCalc', { net_amount: attack, tax_rate_percent: attack, tax_amount: attack, gross_amount: attack, is_inclusive: false, assumptions: { rate_source: attack, jurisdiction: 'not_specified', currency_precision: '0.01', rounding: 'half_up' } }],
    ['runFreelanceCalc', { recommended_hourly_rate: attack, recommended_day_rate: attack }],
  ]) {
    const result = new FakeElement();
    const document = {
      getElementById(id) {
        return id.endsWith('-result') ? result : {
          value: '1', checked: false, setCustomValidity() {}, checkValidity: () => true, reportValidity() {},
          removeAttribute() {}, setAttribute() {}, classList: { add() {}, remove() {} }, closest: () => null,
        };
      },
    };
    const source = html.match(new RegExp(`async function ${functionName}\\(\\) \\{[\\s\\S]*?\\n        \\}`))?.[0];
    const escape = html.match(/function officekitEscapeHtml\(value\) \{[\s\S]*?\n        \}/)?.[0];
    const exactKeys = html.match(/function officekitExactKeys\(value, keys\) \{[\s\S]*?\n        \}/)?.[0];
    const vatValidation = html.match(/function officekitValidateVatResult\(data, inputs\) \{[\s\S]*?\n        \}/)?.[0];
    const loanValidation = html.match(/function officekitValidateLoanEmiResult\(data, inputs\) \{[\s\S]*?\n        \}/)?.[0];
    const freelanceValidation = html.match(/function officekitValidateFreelanceRateResult\(data, inputs\) \{[\s\S]*?\n        \}/)?.[0];
    const clearFieldError = html.match(/function officekitClearFinancialFieldError\(form, input, feedback\) \{[\s\S]*?\n        \}/)?.[0];
    const currency = html.split('/* CURRENCY DISPLAY START */')[1].split('/* CURRENCY DISPLAY END */')[0];
    assert.ok(clearFieldError, 'financial field error clearing helper exists');
    assert.ok(source, `${functionName} exists`);
    assert.ok(escape, 'shared HTML escaping helper exists');
    if (functionName === 'runVatCalc') {
      assert.ok(exactKeys, 'VAT exact-key validator exists');
      assert.ok(vatValidation, 'VAT response validator exists');
    }
    if (functionName === 'runEmiCalc') assert.ok(loanValidation, 'loan response validator exists');
    if (functionName === 'runFreelanceCalc') assert.ok(freelanceValidation, 'freelance response validator exists');
    const context = {
      document,
      fetch: async () => ({ json: async () => values }),
      officekitApiUrl: value => value,
      officekitReadCalculatorResponse: async response => response.json(),
      officekitRenderCalculationActions() {},
      officekitShowCalculatorError(container, error) { container.textContent = error.message; },
      parseFloat,
      JSON,
    };
    vm.runInNewContext(`${escape}\n${exactKeys || ''}\n${vatValidation || ''}\n${loanValidation || ''}\n${freelanceValidation || ''}\n${clearFieldError}\n${currency}\n${source}`, context);
    await context[functionName]();
    assert.doesNotMatch(result.innerHTML, /<img/i, `${functionName} must render API values as text`);
    if (functionName === 'runVatCalc') {
      assert.equal(result.innerHTML, '');
      assert.match(result.textContent, /invalid tax calculation result/i);
    } else if (functionName === 'runEmiCalc' || functionName === 'runCompoundCalc') {
      assert.equal(result.innerHTML, '');
      assert.match(result.textContent, functionName === 'runEmiCalc' ? /invalid loan schedule/i : /incomplete compound-growth result/i);
    } else if (functionName === 'runFreelanceCalc') {
      assert.equal(result.innerHTML, '');
      assert.match(result.textContent, /inconsistent freelance-rate calculation/i);
    } else {
      assert.match(result.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/i);
    }
  }
});

test('shared HTML escaping covers markup delimiters and preserves Unicode text', () => {
  const escape = html.match(/function officekitEscapeHtml\(value\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(escape, 'shared HTML escaping helper exists');
  const input = '<&>"\' café';
  assert.equal(vm.runInNewContext(`${escape}; officekitEscapeHtml(${JSON.stringify(input)})`, {}), '&lt;&amp;&gt;&quot;&#39; café');
});

test('tested UI source and packaged UI stay byte-identical', () => {
  assert.equal(html, bundledHtml);
});
