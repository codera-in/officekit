import vm from 'node:vm';

// Drop-in for node:vm in UI sandbox tests. Page code calls officekitOutcome as a bare name, and these
// tests check messages and states rather than the helper itself (tests/outcome-helper.test.mjs covers
// that), so every sandbox context gets a plain stub that writes the text and state onto the element.
const outcomeStub = {
  show(slot, options) {
    if (!slot) return;
    slot.textContent = options.text;
    if (slot.dataset) slot.dataset.state = options.state;
  },
  clear(slot) {
    if (slot) slot.textContent = '';
  },
};

function withOutcome(context = {}) {
  if (!('officekitOutcome' in context)) context.officekitOutcome = outcomeStub;
  return context;
}

export default {
  runInNewContext: (code, context, options) => vm.runInNewContext(code, withOutcome(context), options),
  runInContext: (code, context, options) => vm.runInContext(code, context, options),
  createContext: context => vm.createContext(withOutcome(context)),
};
