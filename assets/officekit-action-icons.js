/* Decorative Font Awesome icons on existing daisyUI actions. Labels own names. */
(function (global) {
  'use strict';
  const rules = [
    [/^(?:move .*trash|move to trash|delete|remove selected|remove result|remove transcript|remove model)\b/i, 'trash-can'],
    [/^(?:strip|remove) (?:exif|gps|metadata|personal)/i, 'eraser'],
    [/^(?:choose|change|select|open) (?:a |the )?folder/i, 'folder-open'],
    [/^(?:choose|select|replace|open) (?:a |the )?(?:pdf|pdfs)\b/i, 'file-pdf'],
    [/^(?:choose|select|replace|open|paste) (?:an? |the )?(?:image|photo|screenshot)/i, 'image'],
    [/^(?:choose|select|replace) (?:a |the |another )?(?:file|files|archive|certificate|font)/i, 'file-arrow-up'],
    [/^select (?:copies|all|duplicates)\b/i, 'check-double'],
    [/^(?:find|search|scan|look up|analyse|analyze|detect|inspect)\b/i, 'magnifying-glass'],
    [/^(?:copy|copied)\b/i, 'copy'],
    [/^(?:download|export|create download|preparing download)\b/i, 'download'],
    [/^(?:save|saved)\b/i, 'floppy-disk'],
    [/^(?:calculate|evaluate)\b/i, 'calculator'],
    [/^(?:convert|decode|encode|swap)\b/i, 'repeat'],
    [/^resize\b/i, 'up-right-and-down-left-from-center'],
    [/^(?:merge|join)\b/i, 'object-group'],
    [/^(?:split|extract pages)\b/i, 'scissors'],
    [/^reorder\b/i, 'arrows-up-down'],
    [/^(?:compress|optimise|optimize)\b/i, 'compress'],
    [/^(?:extract|recognise|recognize)\b/i, 'file-lines'],
    [/^(?:protect|encrypt|lock)\b/i, 'lock'],
    [/^(?:unlock|decrypt|remove password)\b/i, 'unlock'],
    [/^(?:sign|signature appearance)\b/i, 'signature'],
    [/^(?:verify|check signatures)\b/i, 'shield-halved'],
    [/^read certificates\b/i, 'certificate'],
    [/^(?:generate|create) (?:password|passphrase)\b/i, 'key'],
    [/^(?:generate|create)\b/i, 'wand-magic-sparkles'],
    [/^capture\b/i, 'camera'],
    [/^paste\b/i, 'paste'],
    [/^crop\b/i, 'crop-simple'],
    [/^(?:start|record|dictate|resume recording)\b/i, 'microphone'],
    [/^stop\b/i, 'stop'],
    [/^allow microphone\b/i, 'microphone'],
    [/^(?:(?:enable|disable).*shortcut|set up shortcut)\b/i, 'keyboard'],
    [/^grant access\b/i, 'shield-halved'],
    [/^(?:reuse|re-read|recheck)\b/i, 'rotate-right'],
    [/^(?:refresh|reload|retry|check for updates|check this|load summary)\b/i, 'rotate-right'],
    [/^(?:preview|review|view)\b/i, 'eye'],
    [/^(?:edit|rename)\b/i, 'pen-to-square'],
    [/^fit\b/i, 'expand'],
    [/^(?:previous|back)\b/i, 'arrow-left'],
    [/^(?:place|load)\b/i, 'plus'],
    [/^(?:load more|show more|add)\b/i, 'plus'],
    [/^undo\b/i, 'rotate-left'],
    [/^(?:redo|rotate)\b/i, 'rotate-right'],
    [/^(?:apply|confirm)\b/i, 'check'],
    [/^compare\b/i, 'columns'],
    [/^(?:open|browse)\b/i, 'folder-open'],
    [/^(?:view|reveal|show)\b/i, 'eye'],
    [/^(?:activate|manage license)\b/i, 'key'],
    [/^(?:run|process|continue|next)\b/i, 'arrow-right'],
  ];
  const textOnly = /^(?:cancel|clear(?:\s|$)|reset(?:\s|$)|close(?:\s|$))/i;
  const previousIcons = new WeakMap();

  function iconForLabel(label) {
    const text = String(label || '').replace(/\s+/g, ' ').trim();
    if (textOnly.test(text)) return null;
    return rules.find(([pattern]) => pattern.test(text))?.[1] || null;
  }

  function decorate(button) {
    if (!button?.matches?.('button') || button.closest('#app-sidebar') || button.matches('[role="tab"], [data-open-tool], [data-screenshot-tool], [data-pdf-tool]')) return;
    const label = button.textContent.replace(/\s+/g, ' ').trim();
    const owned = button.querySelector('[data-officekit-action-icon]');
    if (textOnly.test(label)) {
      owned?.remove();
      previousIcons.delete(button);
      button.classList.remove('ok-icon-label-button');
      if (!button.matches('.btn-primary,.btn-error')) {
        for (const name of [...button.classList]) {
          if (/^(?:btn-outline|border(?:-|$)|bg-|shadow(?:-|$)|hover:(?:border-|bg-|shadow))/.test(name)) button.classList.remove(name);
        }
        button.classList.add('btn', 'btn-ghost');
      }
      return;
    }
    const existing = button.querySelector('i.fa-solid,i.fa-regular,i.fa-brands,i.fas,i.far,i.fab');
    if (existing && !owned) {
      existing.classList.add('ok-button-icon');
      existing.setAttribute('aria-hidden', 'true');
      if (label) button.classList.add('ok-icon-label-button');
      return;
    }
    // Canvas glyphs, navigation arrows and icon-only utilities already carry
    // their own affordance. Keep their layout and accessible labels intact.
    if (button.querySelector('svg,img') || /[←→↖↗↘↙↑↓✎▧⌫🖐]/u.test(label)) return;
    const name = button.dataset.actionIcon || iconForLabel(label) || previousIcons.get(button)
      || (button.matches('.btn-primary') && /[A-Za-z]{2}/.test(label) ? 'arrow-right' : null);
    if (!name) return;
    previousIcons.set(button, name);
    const icon = owned || document.createElement('i');
    icon.className = `fa-solid fa-${name} ok-button-icon`;
    icon.dataset.officekitActionIcon = name;
    icon.setAttribute('aria-hidden', 'true');
    button.classList.add('btn', 'ok-icon-label-button');
    if (!owned) button.prepend(icon);
  }

  function refresh(root = document) {
    if (root.matches?.('button')) decorate(root);
    root.querySelectorAll?.('button').forEach(decorate);
  }

  global.OfficeKitActionIcons = { iconForLabel, decorate, refresh };
  if (typeof document === 'undefined') return;
  function start() {
    refresh(document);
    const pending = new Set(); let scheduled = false;
    const collect = node => {
      const element = node.nodeType === 1 ? node : node.parentElement;
      if (!element) return;
      const button = element.closest?.('button');
      if (button) pending.add(button);
      element.querySelectorAll?.('button').forEach(item => pending.add(item));
    };
    new MutationObserver(records => {
      for (const record of records) {
        collect(record.target);
        for (const node of record.addedNodes) collect(node);
      }
      if (scheduled || !pending.size) return;
      scheduled = true;
      queueMicrotask(() => {
        scheduled = false;
        const buttons = [...pending]; pending.clear();
        for (const button of buttons) if (button.isConnected) decorate(button);
      });
    }).observe(document.body, { childList: true, characterData: true, subtree: true });
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start, {once:true});
})(typeof window === 'undefined' ? globalThis : window);
