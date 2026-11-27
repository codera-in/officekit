import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const mock = fs.readFileSync(path.join(root, 'design/mocks/pdf-group-split-review.html'), 'utf8');
const script = mock.match(/<script>([\s\S]*?)<\/script>/)?.[1];

test('grouped PDF mock explains a safe named-output flow against the current one-range screen', () => {
  for (const label of [
    'Current screen',
    'Proposed screen',
    'Pages to extract',
    'Output groups',
    'cover.pdf',
    'appendix.pdf',
    'split-pages.zip',
    'original remains unchanged',
    'overlapping groups',
  ]) {
    assert.ok(mock.includes(label), `mock is missing ${label}`);
  }
  assert.match(mock, /Up to 2,000 pages total/);
  assert.match(mock, /2 of 50 groups/);
});

test('grouped PDF mock is responsive, self-contained and keeps generated control ids unique', () => {
  assert.match(mock, /@media\s*\(max-width:\s*780px\)/);
  assert.match(mock, /@media\s*\(max-width:\s*430px\)/);
  assert.doesNotMatch(mock, /<(?:script|link|img)[^>]+(?:src|href)=["']https?:/i);
  assert.doesNotMatch(mock, /fetch\s*\(|XMLHttpRequest/);
  assert.ok(script, 'mock has an inline script');
  assert.doesNotThrow(() => new vm.Script(script));
  assert.match(script, /nextGroupId\s*\+\+/);
});

test('group controls keep ids unique through removal, enforce two-to-fifty groups, and update the count', () => {
  class FakeElement {
    constructor(tag = 'div') {
      this.tagName = tag;
      this.children = [];
      this.listeners = new Map();
      this.attributes = new Map();
      this.parentElement = null;
      this.disabled = false;
      this.value = '';
    }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    append(...items) {
      for (const item of items) {
        this.children.push(item);
        item.parentElement = this;
      }
    }
    querySelectorAll(selector) {
      if (selector !== '.remove') return [];
      return this.children.flatMap(row => row.children.filter(child => child.className === 'remove'));
    }
    matches(selector) { return selector === '.remove' && this.className === 'remove'; }
    closest(selector) { return selector === '.group' ? this.parentElement : null; }
    remove() {
      const siblings = this.parentElement?.children ?? [];
      const index = siblings.indexOf(this);
      if (index >= 0) siblings.splice(index, 1);
    }
  }

  const list = new FakeElement();
  for (const [id, name, pages] of [[1, 'cover.pdf', '1-3'], [2, 'appendix.pdf', '4-6']]) {
    const row = new FakeElement();
    row.className = 'group';
    const nameField = new FakeElement();
    nameField.append(new FakeElement('label'));
    const nameInput = new FakeElement('input');
    nameInput.id = `group-name-${id}`;
    const rangeField = new FakeElement();
    rangeField.append(new FakeElement('label'));
    const rangeInput = new FakeElement('input');
    rangeInput.id = `group-pages-${id}`;
    const remove = new FakeElement('button');
    remove.className = 'remove';
    nameField.append(nameInput);
    rangeField.append(rangeInput);
    row.append(nameField, rangeField, remove);
    list.append(row);
    assert.ok(name && pages);
  }
  const add = new FakeElement('button');
  const count = new FakeElement('span');
  const controls = new Map([['group-list', list], ['add-group', add], ['group-count', count]]);
  const document = {
    getElementById(id) { return controls.get(id); },
    createElement(tag) { return new FakeElement(tag); },
  };
  vm.runInNewContext(script, { document });
  const clickAdd = () => add.listeners.get('click')();
  const removeLast = () => {
    const button = list.children.at(-1).children.at(-1);
    list.listeners.get('click')({ target: button });
  };

  clickAdd();
  assert.equal(list.children.length, 3);
  assert.equal(list.children[2].children[0].children[1].id, 'group-name-3');
  assert.equal(count.textContent, '3 of 50 groups');
  removeLast();
  clickAdd();
  assert.equal(list.children[2].children[0].children[1].id, 'group-name-4');
  assert.deepEqual(list.children.map(row => row.children[0].children[1]?.id), ['group-name-1', 'group-name-2', 'group-name-4']);

  removeLast();
  assert.equal(list.children.length, 2);
  assert.equal(list.children[0].children[2].disabled, true);
  for (let index = 0; index < 60; index += 1) clickAdd();
  assert.equal(list.children.length, 50);
  assert.equal(add.disabled, true);
  assert.equal(count.textContent, '50 of 50 groups');
});
