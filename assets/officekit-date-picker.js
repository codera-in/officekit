(function (global) {
  'use strict';

  const formatter = (locale, options) => new Intl.DateTimeFormat(locale, options);
  const mountedInputs = new Map();

  function dateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function parseDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return date.getFullYear() === Number(match[1]) && date.getMonth() === Number(match[2]) - 1 && date.getDate() === Number(match[3]) ? date : null;
  }

  function monthCells(year, month, weekStart = 0) {
    const first = new Date(year, month, 1);
    const offset = (first.getDay() - weekStart + 7) % 7;
    const start = new Date(year, month, 1 - offset);
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
      return { date, value: dateKey(date), inMonth: date.getMonth() === month };
    });
  }

  function getWeekStart(locale) {
    try { return new Intl.Locale(locale).weekInfo.firstDay % 7; }
    catch { return 0; }
  }

  function accessibleLabel(input) {
    const label = input.labels?.[0]?.textContent?.trim() || input.getAttribute('aria-label') || 'date';
    return `Choose ${label.toLowerCase()}`;
  }

  function initialize(root = document) {
    for (const [input, dispose] of mountedInputs) {
      if (!input.isConnected) { dispose(); mountedInputs.delete(input); }
    }
    const inputs = [...root.querySelectorAll('input[type="date"]')].filter(input => !input.closest('.ok-date-control'));
    for (const input of inputs) mountedInputs.set(input, mount(input));
    return inputs.length;
  }

  function mount(input) {
    const doc = input.ownerDocument;
    const locale = input.dataset.locale || global.navigator?.language || doc.documentElement.lang || 'en';
    const weekStart = getWeekStart(locale);
    const wrapper = doc.createElement('span');
    wrapper.className = 'ok-date-control';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.append(input);

    const popover = doc.createElement('div');
    popover.className = 'ok-date-picker';
    popover.hidden = true;
    popover.id = `${input.id}-date-picker-popover`;
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', accessibleLabel(input));
    input.setAttribute('aria-haspopup', 'dialog');
    input.setAttribute('aria-controls', popover.id);
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-keyshortcuts', 'Alt+ArrowDown');
    popover.innerHTML = '<div class="ok-date-picker__header"><button type="button" class="ok-date-picker__nav" data-month-step="-1" aria-label="Previous month">‹</button><span class="ok-date-picker__month"></span><button type="button" class="ok-date-picker__nav" data-month-step="1" aria-label="Next month">›</button></div><div class="ok-date-picker__week" role="row"></div><div class="ok-date-picker__days" role="grid"></div><div class="ok-date-picker__footer"><span>Choose a date · results return after selection<br>Arrow keys move · Enter selects · Esc closes</span><a href="#" class="ok-date-picker__today">Today</a></div>';
    doc.body.append(popover);

    const monthHeading = popover.querySelector('.ok-date-picker__month');
    const weekdays = popover.querySelector('.ok-date-picker__week');
    const days = popover.querySelector('.ok-date-picker__days');
    const today = new Date();
    let displayed = parseDate(input.value) || today;
    let focusedDate = parseDate(input.value) || today;

    const formatMonth = formatter(locale, { month: 'long', year: 'numeric' });
    const formatWeekday = formatter(locale, { weekday: 'short' });
    const formatDay = formatter(locale, { day: 'numeric' });
    const weekdayStart = new Date(2024, 0, 7 + weekStart);
    for (let index = 0; index < 7; index += 1) {
      const weekday = doc.createElement('span');
      weekday.className = 'ok-date-picker__weekday';
      weekday.setAttribute('role', 'columnheader');
      weekday.textContent = formatWeekday.format(new Date(weekdayStart.getFullYear(), weekdayStart.getMonth(), weekdayStart.getDate() + index));
      weekdays.append(weekday);
    }

    function withinBounds(value) {
      return (!input.min || value >= input.min) && (!input.max || value <= input.max);
    }

    function render(focus = false) {
      monthHeading.textContent = formatMonth.format(displayed);
      days.setAttribute('aria-label', formatMonth.format(displayed));
      days.replaceChildren();
      for (const cell of monthCells(displayed.getFullYear(), displayed.getMonth(), weekStart)) {
        const day = doc.createElement('div');
        day.className = `ok-date-picker__day${cell.inMonth ? '' : ' ok-date-picker__day--outside'}`;
        day.setAttribute('role', 'gridcell');
        day.setAttribute('aria-label', formatter(locale, { dateStyle: 'full' }).format(cell.date));
        day.setAttribute('aria-selected', String(cell.value === input.value));
        if (cell.value === dateKey(today)) day.setAttribute('aria-current', 'date');
        day.tabIndex = cell.value === dateKey(focusedDate) ? 0 : -1;
        day.textContent = formatDay.format(cell.date);
        day.addEventListener('click', () => {
          if (!withinBounds(cell.value)) return;
          input.value = cell.value;
          input.dispatchEvent(new global.Event('input', { bubbles: true }));
          input.dispatchEvent(new global.Event('change', { bubbles: true }));
          close(true);
        });
        day.addEventListener('keydown', event => onGridKeydown(event, cell.date));
        days.append(day);
      }
      if (focus) days.querySelector('[tabindex="0"]')?.focus();
    }

    function moveMonth(amount) {
      displayed = new Date(displayed.getFullYear(), displayed.getMonth() + amount, 1);
      focusedDate = new Date(displayed.getFullYear(), displayed.getMonth(), Math.min(focusedDate.getDate(), new Date(displayed.getFullYear(), displayed.getMonth() + 1, 0).getDate()));
      render(true);
    }

    function onGridKeydown(event, date) {
      let offset = 0;
      if (event.key === 'ArrowRight') offset = 1;
      else if (event.key === 'ArrowLeft') offset = -1;
      else if (event.key === 'ArrowDown') offset = 7;
      else if (event.key === 'ArrowUp') offset = -7;
      else if (event.key === 'Home') focusedDate = new Date(date.getFullYear(), date.getMonth(), date.getDate() - ((date.getDay() - weekStart + 7) % 7));
      else if (event.key === 'End') focusedDate = new Date(date.getFullYear(), date.getMonth(), date.getDate() + (6 - ((date.getDay() - weekStart + 7) % 7)));
      else if (event.key === 'PageUp') { event.preventDefault(); moveMonth(event.shiftKey ? -12 : -1); return; }
      else if (event.key === 'PageDown') { event.preventDefault(); moveMonth(event.shiftKey ? 12 : 1); return; }
      else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); days.querySelector('[tabindex="0"]')?.click(); return; }
      else if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
      else return;
      event.preventDefault();
      if (offset) focusedDate = new Date(date.getFullYear(), date.getMonth(), date.getDate() + offset);
      displayed = new Date(focusedDate.getFullYear(), focusedDate.getMonth(), 1);
      render(true);
    }

    function open() {
      displayed = parseDate(input.value) || today;
      focusedDate = parseDate(input.value) || today;
      popover.hidden = false;
      wrapper.classList.add('ok-date-control--open');
      doc.body.classList.add('officekit-date-picker-open');
      input.setAttribute('aria-expanded', 'true');
      render(true);
      positionPopover();
    }

    function close(returnFocus = false) {
      popover.hidden = true;
      wrapper.classList.remove('ok-date-control--open');
      popover.classList.remove('ok-date-picker--floating');
      popover.style.removeProperty('--ok-date-picker-top');
      popover.style.removeProperty('--ok-date-picker-left');
      input.setAttribute('aria-expanded', 'false');
      if (!doc.querySelector('.ok-date-picker:not([hidden])')) doc.body.classList.remove('officekit-date-picker-open');
      if (returnFocus) input.focus();
    }

    function positionPopover() {
      if (popover.hidden) return;
      popover.classList.add('ok-date-picker--floating');
      const anchor = wrapper.getBoundingClientRect();
      const picker = popover.getBoundingClientRect();
      const dock = [...doc.querySelectorAll('#officekit-tool-actions, .ok-action-dock')]
        .find(candidate => !candidate.hidden && getComputedStyle(candidate).display !== 'none' && candidate.getBoundingClientRect().height > 0);
      const lowerEdge = dock ? Math.min(global.innerHeight - 24, dock.getBoundingClientRect().top) : global.innerHeight - 24;
      const safeTop = Math.min(160, Math.max(12, global.innerHeight - picker.height - 12));
      let top = anchor.bottom + 8;
      let left = anchor.left;
      if (top + picker.height > lowerEdge - 6) {
        top = Math.max(safeTop, lowerEdge - picker.height - 6);
        if (anchor.right + 16 + picker.width <= global.innerWidth - 8) left = anchor.right + 16;
        else if (anchor.left - 16 - picker.width >= 8) left = anchor.left - 16 - picker.width;
      }
      left = Math.max(8, Math.min(left, global.innerWidth - picker.width - 8));
      popover.style.setProperty('--ok-date-picker-top', `${top}px`);
      popover.style.setProperty('--ok-date-picker-left', `${left}px`);
    }

    input.addEventListener('click', event => {
      const bounds = input.getBoundingClientRect();
      if (event.clientX >= bounds.right - 42) {
        event.preventDefault();
        popover.hidden ? open() : close();
      }
    });
    input.addEventListener('keydown', event => {
      if (event.altKey && event.key === 'ArrowDown') { event.preventDefault(); open(); }
    });
    popover.querySelectorAll('[data-month-step]').forEach(button => button.addEventListener('click', () => moveMonth(Number(button.dataset.monthStep))));
    popover.querySelector('.ok-date-picker__today').addEventListener('click', event => {
      event.preventDefault();
      const value = dateKey(today);
      if (!withinBounds(value)) return;
      input.value = value;
      input.dispatchEvent(new global.Event('input', { bubbles: true }));
      input.dispatchEvent(new global.Event('change', { bubbles: true }));
      close(true);
    });
    const onInputChange = () => { if (!popover.hidden) render(); };
    const onPointerDown = event => { if (!wrapper.contains(event.target) && !popover.contains(event.target)) close(); };
    const onDocumentKeyDown = event => { if (event.key === 'Escape' && !popover.hidden) close(true); };
    const onScroll = () => positionPopover();
    input.addEventListener('change', onInputChange);
    doc.addEventListener('pointerdown', onPointerDown);
    doc.addEventListener('keydown', onDocumentKeyDown);
    global.addEventListener('resize', positionPopover);
    doc.addEventListener('scroll', onScroll, true);
    render();
    return () => {
      close(false);
      input.removeEventListener('change', onInputChange);
      doc.removeEventListener('pointerdown', onPointerDown);
      doc.removeEventListener('keydown', onDocumentKeyDown);
      global.removeEventListener('resize', positionPopover);
      doc.removeEventListener('scroll', onScroll, true);
      popover.remove();
    };
  }

  global.OfficeKitDatePicker = { initialize, monthCells, parseDate, dateKey };
  if (global.document) {
    if (global.document.readyState === 'loading') global.document.addEventListener('DOMContentLoaded', () => initialize());
    else initialize();
  }
})(window);
