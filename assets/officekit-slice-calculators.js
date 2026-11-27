// Calculators slice (C06–C07, C15–C25).
// Keep this register() call first. List destinations one `id: { tab: '…', … },` line
// each: tests/ui-search-routing.test.mjs parses them against the live catalogue.
window.OfficeKitExtensions.register({
  slice: 'calculators',
  destinations: {
    weighted_average: { tab: 'calculators', calculator: 'average' },
    fractions_ratios: { tab: 'calculators', calculator: 'fractions' },
    roi: { tab: 'calculators', calculator: 'roi' },
    cagr: { tab: 'calculators', calculator: 'cagr' },
    date_difference: { tab: 'calculators', calculator: 'date-difference' },
    age_calculator: { tab: 'calculators', calculator: 'age' },
    business_days: { tab: 'calculators', calculator: 'business-days' },
    work_hours: { tab: 'calculators', calculator: 'work-hours' },
    time_zone_converter: { tab: 'calculators', calculator: 'time-zones' },
    quadratic_solver: { tab: 'calculators', calculator: 'quadratic' },
    gcd_lcm: { tab: 'calculators', calculator: 'gcd-lcm' },
    descriptive_statistics: { tab: 'calculators', calculator: 'statistics' },
    geometry: { tab: 'calculators', calculator: 'geometry' },
  },
  tabs: [],
});

// Client logic for the new calculator forms. Request bodies mirror officekit/routes/calculators.py.
// Result text is written with textContent and DOM nodes only, never as HTML strings (P-011).
(function officekitCalculatorsSlice() {
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const CLOCK_PATTERN = /^\d{2}:\d{2}$/;
  const NUMBER_PATTERN = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
  const INVALID_RESULT = 'OfficeKit returned an invalid calculator result.';
  const WEEKEND_CHOICES = { 'sat-sun': [5, 6], 'fri-sat': [4, 5], sun: [6], none: [] };
  const GEOMETRY_SHAPES = {
    circle: { fields: ['radius'], labels: ['Radius'] },
    rectangle: { fields: ['width', 'height'], labels: ['Width', 'Height'] },
    triangle: { fields: ['a', 'b', 'c'], labels: ['Side a', 'Side b', 'Side c'] },
    sphere: { fields: ['radius'], labels: ['Radius'] },
    cylinder: { fields: ['radius', 'height'], labels: ['Radius', 'Height'] },
    cone: { fields: ['radius', 'height'], labels: ['Radius', 'Height'] },
    cuboid: { fields: ['length', 'width', 'height'], labels: ['Length', 'Width', 'Height'] },
  };
  const el = id => document.getElementById(id);
  // Marks one input invalid, links its message with aria-describedby and moves focus to it (DESIGN_SYSTEM "Invalid field").
  function showFieldError(inputId, messageId, message) {
    const input = el(inputId);
    const messageEl = el(messageId);
    messageEl.textContent = message;
    messageEl.classList.remove('hidden');
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', messageId);
    input.focus();
  }
  function clearFieldError(inputId, messageId) {
    const input = el(inputId);
    el(messageId).textContent = '';
    el(messageId).classList.add('hidden');
    input.removeAttribute('aria-invalid');
    input.removeAttribute('aria-describedby');
  }
  const fail = message => new Error(message);
  const text = value => String(value ?? '').trim();

  function readNumber(raw, label) {
    const value = text(raw);
    if (!NUMBER_PATTERN.test(value) || !Number.isFinite(Number(value))) throw fail(`${label} must be a number.`);
    return Number(value);
  }

  function readDate(raw, label) {
    const value = text(raw);
    if (!DATE_PATTERN.test(value)) throw fail(`${label} needs a calendar date.`);
    return value;
  }

  // Lines or commas separate items. A blank item is kept as null only when allowBlank is set.
  function readList(raw, label, { allowBlank = false, integer = false } = {}) {
    const trimmed = text(raw);
    if (!trimmed) throw fail(`Enter at least one value for ${label}.`);
    return trimmed.split(/\r?\n|,/).map((item, index) => {
      const token = item.trim();
      if (token === '') {
        if (allowBlank) return null;
        throw fail(`${label} item ${index + 1} is blank.`);
      }
      const value = readNumber(token, `${label} item ${index + 1}`);
      if (integer && !Number.isInteger(value)) throw fail(`${label} must be whole numbers.`);
      return value;
    });
  }

  function nonBlankLines(raw) {
    return text(raw).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  }

  function workHoursInputIssue(error) {
    const message = String(error?.message || 'Check the shift format.')
      .replace(/^row (\d+): /, 'Shift $1: ')
      .replace(/: ([a-z])/, (_match, letter) => `: ${letter.toUpperCase()}`);
    return {
      field: 'calc-work-hours-rows',
      message,
      statusMessage: 'Fix the marked shift row. Your entries are kept.',
    };
  }


  function readDateLines(raw, label, fieldId = null) {
    const lines = nonBlankLines(raw);
    return lines.map((line, index) => {
      const [year, month, day] = DATE_PATTERN.test(line) ? line.split('-').map(Number) : [];
      const parsed = Number.isInteger(year) && Number.isInteger(month) && Number.isInteger(day)
        ? new Date(Date.UTC(year, month - 1, day))
        : null;
      const isSupportedDate = parsed && line >= '1600-01-01' && line <= '2400-12-31' &&
        parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
      if (!isSupportedDate) {
        const error = fail(`${label} line ${index + 1} must be a real date in YYYY-MM-DD format between 1600-01-01 and 2400-12-31.`);
        if (fieldId) error.fieldValidation = {
          field: fieldId,
          message: 'Enter real dates as YYYY-MM-DD between 1600-01-01 and 2400-12-31.',
          statusMessage: 'Result appears here after you correct the holiday dates. Your other inputs are kept.',
        };
        throw error;
      }
      return line;
    });
  }

  function readWorkRows(raw) {
    const lines = nonBlankLines(raw);
    if (!lines.length) throw fail('Add at least one shift, for example 2026-03-02 09:00 17:30 30.');
    return lines.map((line, index) => {
      const parts = line.split(/\s+/);
      const date = DATE_PATTERN.test(parts[0]) ? parts.shift() : null;
      if (parts.length < 2 || parts.length > 3) throw fail(`Shift ${index + 1} needs a start time, an end time and optional break minutes.`);
      const [start, end, breakText = '0'] = parts;
      if (!CLOCK_PATTERN.test(start) || !CLOCK_PATTERN.test(end)) throw fail(`Shift ${index + 1} times use the form HH:MM.`);
      if (!/^\d+$/.test(breakText)) throw fail(`Shift ${index + 1} break must be whole minutes.`);
      return { date, start, end, break_minutes: Number(breakText) };
    });
  }

  function formatValue(value) {
    if (value === null || value === undefined) return 'Not available';
    return String(value);
  }

  function formatPercent(value) { return `${formatValue(value)}%`; }

  function formatRoot(root) {
    if (root.imaginary === 0) return formatValue(root.real);
    const sign = root.imaginary < 0 ? '-' : '+';
    return `${formatValue(root.real)} ${sign} ${formatValue(Math.abs(root.imaginary))}i`;
  }

  function formatMixed(mixed) {
    if (mixed.numerator === '0') return mixed.whole;
    if (mixed.whole === '0') return `${mixed.numerator}/${mixed.denominator}`;
    return `${mixed.whole} ${mixed.numerator}/${mixed.denominator}`;
  }

  const KIND_TEXT = {
    two_real: 'Two real roots', repeated_real: 'One repeated real root', complex_pair: 'Complex conjugate pair',
    linear: 'Linear (a = 0)', all_numbers: 'Every number is a solution', no_solution: 'No solution',
  };

  function setValue(id, value) {
    const node = el(id);
    if (node && value !== undefined && value !== null) node.value = String(value);
  }

  function setList(id, value) {
    if (!Array.isArray(value)) return;
    setValue(id, value.map(item => item ?? '').join('\n'));
  }

  function setChecked(id, checked) {
    const node = el(id);
    if (node) node.checked = checked === true;
  }

  // The checked radio in a named group, or the fallback when none is checked.
  function checkedRadio(name, fallback) {
    const checked = document.querySelector(`input[type="radio"][name="${name}"]:checked`);
    return checked ? checked.value : fallback;
  }

  function setRadio(name, value) {
    for (const input of document.querySelectorAll(`input[type="radio"][name="${name}"]`)) input.checked = input.value === value;
  }

  const SPECS = {
    roi: {
      key: 'roi', toolId: 'roi', path: '/api/calculator/roi', title: 'Return on investment',
      validationField: 'calc-roi-invested',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      read() {
        const fees = text(el('calc-roi-fees').value);
        return {
          invested: readNumber(el('calc-roi-invested').value, 'Amount invested'),
          returned: readNumber(el('calc-roi-returned').value, 'Amount returned'),
          fees: fees === '' ? 0 : readNumber(fees, 'Fees'),
        };
      },
      validate(body) {
        if (body.invested <= 0) return { field: 'calc-roi-invested', message: 'Initial investment must be greater than $0.', explanation: 'ROI compares gain with the initial investment. Enter a positive starting amount to continue.' };
      },
      restore(inputs) { setValue('calc-roi-invested', inputs.invested); setValue('calc-roi-returned', inputs.returned); setValue('calc-roi-fees', inputs.fees); },
      shape: { net_gain: 'number', roi_percent: 'number', total_cost: 'number' },
      rows: d => [['Net gain', formatValue(d.net_gain)], ['Return on investment', formatPercent(d.roi_percent)], ['Total cost including fees', formatValue(d.total_cost)]],
    },
    cagr: {
      key: 'cagr', toolId: 'cagr', path: '/api/calculator/cagr', title: 'Compound annual growth rate',
      validationField: 'calc-cagr-years',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      read() {
        return {
          start_value: readNumber(el('calc-cagr-start').value, 'Start value'),
          end_value: readNumber(el('calc-cagr-end').value, 'End value'),
          years: readNumber(el('calc-cagr-years').value, 'Years'),
        };
      },
      validate(body) {
        if (body.years <= 0) return { field: 'calc-cagr-years', message: 'Enter a number of years greater than zero.', explanation: 'CAGR needs a positive time period. Update Number of years to continue.' };
      },
      restore(inputs) { setValue('calc-cagr-start', inputs.start_value); setValue('calc-cagr-end', inputs.end_value); setValue('calc-cagr-years', inputs.years); },
      shape: { cagr_percent: 'number', growth_multiple: 'number' },
      rows: d => [['Annual growth rate', formatPercent(d.cagr_percent)], ['Growth multiple', formatValue(d.growth_multiple)]],
    },
    average: {
      key: 'average', toolId: 'weighted_average', path: '/api/calculator/averages', title: 'Average and weighted average',
      resultHeading: 'Latest result',
      validationField: 'calc-average-weights',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      read() {
        const values = readList(el('calc-average-values').value, 'Values', { allowBlank: true });
        const weightText = text(el('calc-average-weights').value);
        const weights = weightText ? readList(weightText, 'Weights', { allowBlank: true }) : null;
        if (weights && weights.length !== values.length) {
          const error = fail('Weights must have one entry for each value.');
          error.fieldValidation = {
            field: 'calc-average-weights',
            message: 'Add one weight for each value, or clear Weights to use a simple average.',
            statusMessage: 'Your values are kept. Correct the weight count to continue.',
          };
          throw error;
        }
        return { values, weights, missing: el('calc-average-missing').value === 'skip' ? 'skip' : 'reject' };
      },
      restore(inputs) {
        setList('calc-average-values', inputs.values);
        setList('calc-average-weights', inputs.weights);
        setValue('calc-average-missing', inputs.missing);
      },
      shape: { mean: 'number', count_used: 'number', count_skipped: 'number', weight_total: 'number', weighted: 'boolean' },
      rows(d) {
        const rows = [['Mean', formatValue(d.mean)], ['Values used', formatValue(d.count_used)], ['Blank values skipped', formatValue(d.count_skipped)]];
        if (d.weighted) rows.push(['Total weight', formatValue(d.weight_total)]);
        return rows;
      },
    },
    fractions: {
      key: 'fractions', toolId: 'fractions_ratios', path: '/api/calculator/fractions', title: 'Fractions and ratios',
      read() {
        const operation = el('calc-fractions-operation').value;
        const part = prefix => ({
          numerator: readIntegerField(el(`calc-fractions-${prefix}-num`).value, 'Numerator'),
          denominator: readIntegerField(el(`calc-fractions-${prefix}-den`).value, 'Denominator'),
        });
        const body = { operation, left: part('left') };
        if (operation !== 'simplify') body.right = part('right');
        return body;
      },
      restore(inputs) {
        setValue('calc-fractions-operation', inputs.operation);
        setValue('calc-fractions-left-num', inputs.left?.numerator);
        setValue('calc-fractions-left-den', inputs.left?.denominator);
        if (inputs.right) { setValue('calc-fractions-right-num', inputs.right.numerator); setValue('calc-fractions-right-den', inputs.right.denominator); }
        syncFractionsOperand();
      },
      shape: { numerator: 'string', denominator: 'string', mixed: 'object', decimal: 'string', is_integer: 'boolean' },
      rows: d => [['Simplified fraction', `${d.numerator}/${d.denominator}`], ['Mixed number', formatMixed(d.mixed)], ['Decimal', d.decimal], ['Whole number', d.is_integer ? 'Yes' : 'No']],
    },
    'gcd-lcm': {
      key: 'gcd-lcm', toolId: 'gcd_lcm', path: '/api/calculator/gcd-lcm', title: 'GCD and LCM',
      read() { return { integers: readList(el('calc-gcd-lcm-integers').value, 'Whole numbers', { integer: true }) }; },
      restore(inputs) { setList('calc-gcd-lcm-integers', inputs.integers); },
      shape: { gcd: 'string', lcm: 'string', count: 'number' },
      rows: d => [['Greatest common divisor', d.gcd], ['Least common multiple', d.lcm], ['Numbers', formatValue(d.count)]],
    },
    statistics: {
      key: 'statistics', toolId: 'descriptive_statistics', path: '/api/calculator/statistics', title: 'Descriptive statistics',
      read() { return { values: readList(el('calc-statistics-values').value, 'Values'), kind: checkedRadio('calc-statistics-kind', 'sample') === 'population' ? 'population' : 'sample' }; },
      restore(inputs) { setList('calc-statistics-values', inputs.values); setRadio('calc-statistics-kind', inputs.kind === 'population' ? 'population' : 'sample'); },
      shape: { count: 'number', sum: 'number', mean: 'number', median: 'number', modes: 'array', modes_truncated: 'boolean', no_mode: 'boolean', minimum: 'number', maximum: 'number', range: 'number' },
      rows(d) {
        const modes = d.no_mode ? 'No mode' : `${d.modes.join(', ')}${d.modes_truncated ? ' (first 20 shown)' : ''}`;
        const rows = [['Count', formatValue(d.count)], ['Sum', formatValue(d.sum)], ['Mean', formatValue(d.mean)], ['Median', formatValue(d.median)], ['Mode', modes], ['Minimum', formatValue(d.minimum)], ['Maximum', formatValue(d.maximum)], ['Range', formatValue(d.range)]];
        rows.push(['Variance', d.variance === null ? `Not available (${d.variance_unavailable_reason || 'see note'})` : formatValue(d.variance)]);
        rows.push(['Standard deviation', d.std_dev === null ? 'Not available' : formatValue(d.std_dev)]);
        return rows;
      },
    },
    'date-difference': {
      key: 'date-difference', toolId: 'date_difference', path: '/api/calculator/date-differences', title: 'Date difference',
      resultLabel: 'Difference',
      read() {
        return {
          start_date: readDate(el('calc-date-difference-start').value, 'Start date'),
          end_date: readDate(el('calc-date-difference-end').value, 'End date'),
          inclusive: el('calc-date-difference-inclusive').checked,
        };
      },
      restore(inputs) {
        setValue('calc-date-difference-start', inputs.start_date);
        setValue('calc-date-difference-end', inputs.end_date);
        setChecked('calc-date-difference-inclusive', inputs.inclusive === true);
      },
      shape: { days: 'number', direction: 'string', years: 'number', months: 'number', rem_days: 'number', weeks: 'number', week_days: 'number' },
      rows: d => [['Days between', formatValue(d.days)], ['Direction', d.direction], ['Years, months and days', `${d.years} years, ${d.months} months, ${d.rem_days} days`], ['Weeks and days', `${d.weeks} weeks, ${d.week_days} days`]],
    },
    age: {
      key: 'age', toolId: 'age_calculator', path: '/api/calculator/ages', title: 'Age',
      validationField: 'calc-age-as-of',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      validationResultRole: 'status',
      read() { return { birth_date: readDate(el('calc-age-birth').value, 'Date of birth'), as_of_date: readDate(el('calc-age-as-of').value, 'Age on date') }; },
      validate(body) {
        if (body.birth_date > body.as_of_date) return {
          field: 'calc-age-as-of',
          message: 'Choose a date on or after the date of birth.',
          statusMessage: 'Result appears here after you correct the date. Your dates are kept.',
        };
      },
      restore(inputs) { setValue('calc-age-birth', inputs.birth_date); setValue('calc-age-as-of', inputs.as_of_date); },
      shape: { years: 'number', months: 'number', days: 'number', total_days: 'number', next_birthday: 'string', days_to_next_birthday: 'number' },
      rows: d => [['Age', `${d.years} years, ${d.months} months, ${d.days} days`], ['Total days lived', formatValue(d.total_days)], ['Next birthday', d.next_birthday], ['Days until next birthday', formatValue(d.days_to_next_birthday)]],
    },
    'business-days': {
      key: 'business-days', toolId: 'business_days', path: '/api/calculator/business-days', title: 'Business days',
      resultHeading: 'Latest result',
      resultLabel: 'Working days',
      validationField: 'calc-business-days-holidays',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      validationResultRole: 'status',
      read() {
        const weekend = WEEKEND_CHOICES[el('calc-business-days-weekend').value] || WEEKEND_CHOICES['sat-sun'];
        return {
          start_date: readDate(el('calc-business-days-start').value, 'Start date'),
          end_date: readDate(el('calc-business-days-end').value, 'End date'),
          inclusive: el('calc-business-days-inclusive').checked,
          weekend,
          holidays: readDateLines(el('calc-business-days-holidays').value, 'Holiday', 'calc-business-days-holidays'),
        };
      },
      restore(inputs) {
        setValue('calc-business-days-start', inputs.start_date);
        setValue('calc-business-days-end', inputs.end_date);
        setChecked('calc-business-days-inclusive', inputs.inclusive !== false);
        const choice = Object.entries(WEEKEND_CHOICES).find(([, days]) => JSON.stringify(days) === JSON.stringify(inputs.weekend));
        if (choice) setValue('calc-business-days-weekend', choice[0]);
        setList('calc-business-days-holidays', inputs.holidays);
      },
      shape: { business_days: 'number', calendar_days: 'number', weekend_days: 'number', holidays_excluded: 'number', holidays_on_weekend: 'number', holidays_outside_range: 'number', duplicate_holidays: 'number' },
      rows: d => [['Business days', formatValue(d.business_days)], ['Calendar days', formatValue(d.calendar_days)], ['Weekend days', formatValue(d.weekend_days)], ['Holidays excluded', formatValue(d.holidays_excluded)], ['Holidays on a weekend', formatValue(d.holidays_on_weekend)], ['Holidays outside the range', formatValue(d.holidays_outside_range)], ['Duplicate holidays ignored', formatValue(d.duplicate_holidays)]],
    },
    'work-hours': {
      key: 'work-hours', toolId: 'work_hours', path: '/api/calculator/work-hours', title: 'Work hours',
      validationField: 'calc-work-hours-rows',
      preventBugReportOnValidation: true,
      hideActionsOnValidation: true,
      validationResultRole: 'status',
      validationFromError(error) {
        if (/row \d+: break must be shorter than the shift/i.test(String(error?.message || ''))) return workHoursInputIssue(error);
        return null;
      },
      read() {
        const zone = text(el('calc-work-hours-zone').value);
        let rows;
        try {
          rows = readWorkRows(el('calc-work-hours-rows').value);
        } catch (error) {
          if (error && typeof error === 'object') error.fieldValidation = workHoursInputIssue(error);
          throw error;
        }
        return { rows, time_zone: zone || null };
      },
      restore(inputs) {
        setValue('calc-work-hours-zone', inputs.time_zone || '');
        if (Array.isArray(inputs.rows)) {
          setValue('calc-work-hours-rows', inputs.rows.map(row => [row.date, row.start, row.end, row.break_minutes].filter(part => part !== null && part !== undefined).join(' ')).join('\n'));
        }
      },
      shape: { rows: 'array', total_minutes: 'number', total_hours: 'number', weeks: 'array' },
      rows(d) {
        const rows = [['Total hours', formatValue(d.total_hours)], ['Total minutes', formatValue(d.total_minutes)]];
        for (const week of d.weeks) rows.push([`Week ${week.iso_week}`, `${week.total_minutes} minutes`]);
        return rows;
      },
    },
    'time-zones': {
      key: 'time-zones', toolId: 'time_zone_converter', path: '/api/calculator/time-zone-conversions', title: 'Time zones',
      againLabel: 'Convert again',
      staleResult(inputs) {
        return `This conversion is for ${inputs.date} at ${inputs.time} in ${inputs.from_zone}. Current inputs have not been converted.`;
      },
      // A repeated local time needs the earlier or later choice; the choice appears only for that error.
      onError(error) {
        // The engine codes are API tokens; visible text is mapped here, and a nonexistent time is a field error on the time input.
        const code = String(error?.message || '').match(/^([A-Z][A-Z_]+):/)?.[1];
        if (code === 'AMBIGUOUS_TIME') {
          el('calc-form-time-zones').setAttribute('data-officekit-no-bug-report', '');
          el('calc-time-zones-choice-note').textContent = `${el('calc-time-zones-time').value} happens twice on ${el('calc-time-zones-date').value} in this zone because clocks go back. Choose which one you mean.`;
          el('calc-time-zones-choice').classList.remove('hidden');
          return true;
        }
        if (code === 'NONEXISTENT_TIME') {
          el('calc-form-time-zones').setAttribute('data-officekit-no-bug-report', '');
          showFieldError('calc-time-zones-time', 'calc-time-zones-time-error', `${el('calc-time-zones-time').value} does not exist on this date in this zone because clocks go forward. Choose another time.`);
          return true;
        }
        return false;
      },
      afterResult() { el('calc-time-zones-choice').classList.add('hidden'); },
      read() {
        clearFieldError('calc-time-zones-time', 'calc-time-zones-time-error');
        const fold = checkedRadio('calc-time-zones-fold', '');
        const toZones = text(el('calc-time-zones-to').value).split(/\r?\n|,/).map(zone => zone.trim()).filter(Boolean);
        if (!toZones.length) throw fail('Add at least one zone to convert to.');
        const body = {
          date: readDate(el('calc-time-zones-date').value, 'Date'),
          time: text(el('calc-time-zones-time').value),
          from_zone: text(el('calc-time-zones-from').value),
          to_zones: toZones,
        };
        if (!CLOCK_PATTERN.test(body.time)) throw fail('Time needs the form HH:MM.');
        if (!body.from_zone) throw fail('Choose the time zone the time is in.');
        if (fold === 'earlier' || fold === 'later') body.fold = fold;
        return body;
      },
      restore(inputs) {
        setValue('calc-time-zones-date', inputs.date);
        setValue('calc-time-zones-time', inputs.time);
        setValue('calc-time-zones-from', inputs.from_zone);
        setList('calc-time-zones-to', inputs.to_zones);
        setRadio('calc-time-zones-fold', inputs.fold || '');
      },
      shape: { utc: 'string', source: 'object', targets: 'array' },
      rows(d) {
        const source = d.source;
        const rows = [['Source time', `${source.local} ${source.abbreviation} (UTC${source.offset})`], ['UTC', d.utc]];
        for (const target of d.targets) rows.push([target.zone, `${target.local} ${target.abbreviation} (UTC${target.offset})${target.day_shift ? ` · ${target.day_shift > 0 ? '+' : ''}${target.day_shift} day` : ''}`]);
        return rows;
      },
    },
    quadratic: {
      key: 'quadratic', toolId: 'quadratic_solver', path: '/api/calculator/quadratics', title: 'Quadratic equation',
      read() { return { a: readNumber(el('calc-quadratic-a').value, 'a'), b: readNumber(el('calc-quadratic-b').value, 'b'), c: readNumber(el('calc-quadratic-c').value, 'c') }; },
      restore(inputs) { setValue('calc-quadratic-a', inputs.a); setValue('calc-quadratic-b', inputs.b); setValue('calc-quadratic-c', inputs.c); },
      shape: { kind: 'string', discriminant: 'number_or_null', roots: 'array', max_residual: 'number' },
      rows: d => [
        ['Type', KIND_TEXT[d.kind] || d.kind],
        ...(d.discriminant === null ? [] : [['Discriminant', formatValue(d.discriminant)]]),
        ['Roots', d.roots.length ? d.roots.map(formatRoot).join(' and ') : 'None'],
        ['Largest residual check', formatValue(d.max_residual)],
      ],
    },
    geometry: {
      key: 'geometry', toolId: 'geometry', path: '/api/calculator/geometry', title: 'Geometry',
      read() {
        const shape = el('calc-geometry-shape').value;
        const spec = GEOMETRY_SHAPES[shape];
        if (!spec) throw fail('Choose a shape.');
        const body = { shape, unit: el('calc-geometry-unit').value };
        spec.fields.forEach((field, index) => {
          body[field] = readNumber(el(`calc-geometry-dim-${index + 1}`).value, spec.labels[index]);
        });
        return body;
      },
      restore(inputs) {
        const spec = GEOMETRY_SHAPES[inputs.shape];
        if (!spec) return;
        setValue('calc-geometry-shape', inputs.shape);
        relabelGeometry();
        setValue('calc-geometry-unit', inputs.unit);
        spec.fields.forEach((field, index) => setValue(`calc-geometry-dim-${index + 1}`, inputs[field]));
      },
      shape: { shape: 'string', unit: 'string', measures: 'array' },
      rows: d => d.measures.map(measure => [measure.name, `${formatValue(measure.value)} ${d.unit}${measure.unit_power > 1 ? `^${measure.unit_power}` : ''} (${measure.formula})`]),
    },
  };

  const SPEC_BY_TOOL = Object.fromEntries(Object.values(SPECS).map(spec => [spec.toolId, spec]));

  function readIntegerField(raw, label) {
    const value = readNumber(raw, label);
    if (!Number.isInteger(value)) throw fail(`${label} must be a whole number.`);
    return value;
  }

  function syncFractionsOperand() {
    const operation = el('calc-fractions-operation')?.value;
    el('calc-fractions-right')?.classList.toggle('hidden', operation === 'simplify');
  }

  function relabelGeometry() {
    const spec = GEOMETRY_SHAPES[el('calc-geometry-shape')?.value];
    if (!spec) return;
    for (let index = 0; index < 3; index += 1) {
      const wrap = el(`calc-geometry-dim-wrap-${index + 1}`);
      const label = el(`calc-geometry-dim-${index + 1}-label`);
      const visible = index < spec.labels.length;
      wrap?.classList.toggle('hidden', !visible);
      if (label && visible) label.textContent = spec.labels[index];
    }
  }

  const SHAPE_CHECKS = {
    number: value => typeof value === 'number' && Number.isFinite(value),
    number_or_null: value => value === null || (typeof value === 'number' && Number.isFinite(value)),
    string: value => typeof value === 'string',
    boolean: value => typeof value === 'boolean',
    array: value => Array.isArray(value),
    object: value => !!value && typeof value === 'object' && !Array.isArray(value),
  };

  function assertResponse(spec, data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw fail(INVALID_RESULT);
    for (const [key, type] of Object.entries(spec.shape)) {
      if (!(key in data) || !SHAPE_CHECKS[type]?.(data[key])) throw fail(INVALID_RESULT);
    }
    return data;
  }

  function describeRows(rows) {
    const list = document.createElement('dl');
    list.className = 'grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2';
    for (const [label, value] of rows) {
      const term = document.createElement('dt');
      term.className = 'text-slate-600';
      term.textContent = label;
      const detail = document.createElement('dd');
      detail.className = 'font-semibold text-slate-900 break-words';
      detail.textContent = value;
      list.append(term, detail);
    }
    return list;
  }

  function markFresh(container) {
    const form = container?.closest('[data-calc-form]');
    form?.querySelector('[data-calc-stale]')?.remove();
  }

  function showValidationIssue(spec, issue, container) {
    const form = container.closest('[data-calc-form]');
    if (spec.preventBugReportOnValidation) form?.setAttribute('data-officekit-no-bug-report', '');
    const input = el(issue.field);
    const details = input.closest?.('details');
    if (details) details.open = true;
    let fieldMessage = el(`${issue.field}-validation`);
    if (!fieldMessage) {
      fieldMessage = document.createElement('p');
      fieldMessage.id = `${issue.field}-validation`;
      fieldMessage.className = 'ok-calc-error mt-1 text-sm';
      fieldMessage.setAttribute('role', 'alert');
      input.insertAdjacentElement('afterend', fieldMessage);
    }
    fieldMessage.textContent = issue.message;
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', fieldMessage.id);
    input.focus();
    window.officekitDisableCalculationActions?.(container);
    if (spec.hideActionsOnValidation) container.querySelector('.officekit-result-actions')?.remove();
    container.classList.remove('hidden');
    container.setAttribute('role', spec.validationResultRole || 'alert');
    const feedback = document.createElement('p');
    feedback.className = 'text-slate-600';
    feedback.textContent = issue.statusMessage || issue.explanation;
    container.replaceChildren(feedback);
  }

  function clearValidationIssue(spec, container) {
    const form = container.closest('[data-calc-form]');
    if (spec.preventBugReportOnValidation) form?.removeAttribute('data-officekit-no-bug-report');
    const inputs = spec.validationField
      ? [el(spec.validationField)].filter(Boolean)
      : [...(form?.querySelectorAll('[aria-invalid="true"]') || [])];
    for (const input of inputs) {
      const fieldId = spec.validationField || input.id;
      const fieldMessage = el(`${fieldId}-validation`);
      if (!String(fieldMessage?.className || '').split(/\s+/).includes('ok-calc-error')) continue;
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
      fieldMessage.remove();
    }
  }

  // Results are live: the form recalculates shortly after the last key, so there is no Calculate button.
  // It runs only once every required field has a value, so half-typed numbers never show an error.
  const LIVE_DELAY_MS = 300;
  const liveTimers = new WeakMap();
  const FIELD_SELECTOR = 'input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea, select';

  function requiredFieldEmpty(form) {
    return [...form.querySelectorAll(FIELD_SELECTOR)].some(field => {
      if (field.disabled || field.closest('.hidden, [hidden]')) return false;
      if (field.id === 'calc-business-days-holidays') return false;
      if (/optional/i.test(field.closest('label')?.textContent ?? '')) return false;
      return field.value.trim() === '';
    });
  }

  function showFillHint(form) {
    const container = form.querySelector('[role="status"][id$="-result"], [id$="-result"]');
    if (!container) return;
    const hint = document.createElement('p');
    hint.className = 'text-slate-600';
    hint.setAttribute('data-calc-hint', '');
    hint.textContent = 'Fill in every field to see the result.';
    container.classList.remove('hidden');
    container.setAttribute('role', 'status');
    container.replaceChildren(hint);
  }

  // The inputs behind the result on screen: a live run with the same inputs would only repeat it.
  const shownInputs = new WeakMap();
  const lastBodies = new WeakMap();
  const inputSignature = form => JSON.stringify([...form.querySelectorAll(`${FIELD_SELECTOR}, input[type="checkbox"], input[type="radio"]`)].map(field =>
    field.type === 'checkbox' || field.type === 'radio' ? field.checked : field.value));

  function runLive(form) {
    if (!form.isConnected || form.classList.contains('hidden')) return;
    if (requiredFieldEmpty(form)) { shownInputs.delete(form); showFillHint(form); return; }
    if (shownInputs.get(form) === inputSignature(form)) return;
    form.querySelector('[data-calc-run]')?.click();
  }

  function noteRun(event) {
    const form = event.target instanceof Element && event.target.closest('[data-calc-run]')?.closest('[data-calc-form]');
    if (form) shownInputs.set(form, inputSignature(form));
  }

  function onInputChange(event) {
    const form = event.target instanceof Element ? event.target.closest('[data-calc-form]') : null;
    if (!form) return;
    const result = form.querySelector('[id$="-result"]');
    const actions = result?.querySelector('.officekit-result-actions');
    const spec = SPECS[form.id.replace(/^calc-form-/, '')];
    if (!actions || actions.dataset.inputSignature !== inputSignature(form)) {
      window.officekitDisableCalculationActions?.(result);
      if (actions && spec?.staleResult && lastBodies.has(form)) {
        let notice = form.querySelector('[data-calc-stale]');
        if (!notice) {
          notice = document.createElement('div');
          notice.className = 'ok-calc-stale-card';
          notice.setAttribute('data-calc-stale', '');
          notice.setAttribute('role', 'status');
          const heading = document.createElement('strong');
          heading.textContent = 'Previous result · inputs changed';
          const detail = document.createElement('p');
          detail.textContent = spec.staleResult(lastBodies.get(form));
          notice.append(heading, detail);
          const introduction = form.querySelector(':scope > p');
          form.insertBefore(notice, introduction?.nextSibling || result);
        }
      }
    } else if (actions?.dataset.stale === 'true' && spec?.staleResult) {
      actions.dataset.stale = 'false';
      actions.querySelectorAll('button').forEach(button => {
        button.disabled = false;
        button.style?.removeProperty('background-color');
        button.style?.removeProperty('border-color');
        button.style?.removeProperty('color');
      });
      const status = actions.querySelector('[data-calculation-action-status]');
      if (status) status.textContent = '';
      form.querySelector('[data-calc-stale]')?.remove();
    }
    clearTimeout(liveTimers.get(form));
    liveTimers.set(form, setTimeout(() => runLive(form), LIVE_DELAY_MS));
  }

  async function runNewCalculator(key) {
    const spec = SPECS[key];
    const container = el(`calc-${key}-result`);
    if (!spec || !container) return false;
    const form = container.closest('[data-calc-form]');
    form?.removeAttribute('data-officekit-no-bug-report');
    const startedWith = form ? inputSignature(form) : null;
    let body;
    try {
      body = spec.read();
      const issue = spec.validate?.(body);
      if (issue) {
        showValidationIssue(spec, issue, container);
        return false;
      }
      clearValidationIssue(spec, container);
    } catch (error) {
      if (error && typeof error === 'object' && !(error instanceof TypeError)) error.inputError = true;
      if (error?.fieldValidation && spec.preventBugReportOnValidation) {
        showValidationIssue(spec, error.fieldValidation, container);
        return false;
      }
      window.officekitShowCalculatorError?.(container, error, { hideActions: true });
      return false;
    }
    try {
      const response = await fetch(window.officekitApiUrl(spec.path), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const data = assertResponse(spec, await window.officekitReadCalculatorResponse(response));
      if (form && inputSignature(form) !== startedWith) return false;
      markFresh(container);
      container.classList.remove('hidden');
      container.setAttribute('role', 'status');
      const resultNodes = [];
      if (spec.resultHeading) {
        const heading = document.createElement('h3');
        heading.className = 'mb-2 text-sm font-semibold text-slate-700';
        heading.textContent = spec.resultHeading;
        resultNodes.push(heading);
      }
      resultNodes.push(describeRows(spec.rows(data)));
      container.replaceChildren(...resultNodes);
      window.officekitRenderCalculationActions(container, {
        toolId: spec.toolId, title: spec.title, inputs: body, result: data,
        resultLabel: spec.resultLabel, againLabel: spec.againLabel,
      });
      if (form) lastBodies.set(form, body);
      spec.afterResult?.();
      if (key === 'business-days') container.scrollIntoView({ block: 'start' });
      if (key === 'work-hours') container.scrollIntoView({ block: 'start' });
    } catch (error) {
      if (form && inputSignature(form) !== startedWith) return false;
      const validationIssue = spec.validationFromError?.(error);
      if (validationIssue) {
        showValidationIssue(spec, validationIssue, container);
        return true;
      }
      if (!spec.onError?.(error)) window.officekitShowCalculatorError?.(container, error, { hideActions: error?.inputError === true });
    }
    return true;
  }

  function fieldUnit(snapshot, name, section) {
    const toolId = snapshot?.toolId;
    if (!SPEC_BY_TOOL[toolId]) return undefined;
    if (section === 'inputs') {
      if (toolId === 'cagr' && name === 'years') return 'years';
      if (toolId === 'geometry' && ['radius', 'width', 'height', 'length', 'a', 'b', 'c'].includes(name)) return snapshot.inputs?.unit ?? null;
      return null;
    }
    if (toolId === 'roi' && name === 'roi_percent') return '%';
    if (toolId === 'cagr' && name === 'cagr_percent') return '%';
    if (toolId === 'age_calculator' && ['years', 'months', 'days'].includes(name)) return name;
    if (toolId === 'date_difference' && ['years', 'months'].includes(name)) return name;
    if (toolId === 'date_difference' && name === 'rem_days') return 'days';
    if (toolId === 'date_difference' && name === 'weeks') return 'weeks';
    if (toolId === 'work_hours' && name === 'total_hours') return 'hours';
    if (toolId === 'work_hours' && name === 'total_minutes') return 'minutes';
    return null;
  }

  function restorePlan(snapshot) {
    const spec = SPEC_BY_TOOL[snapshot?.toolId];
    if (!spec || !snapshot.inputs || typeof snapshot.inputs !== 'object') return null;
    return {
      key: spec.key,
      apply(inputs) {
        const container = el(`calc-${spec.key}-result`);
        container?.classList.add('hidden');
        container?.replaceChildren();
        spec.restore(inputs);
      },
    };
  }

  function populateZones(zones) {
    for (const id of ['calc-time-zones-list', 'calc-work-hours-zones']) {
      const list = el(id);
      if (!list) continue;
      list.replaceChildren(...zones.map(zone => {
        const option = document.createElement('option');
        option.value = zone;
        return option;
      }));
    }
  }

  let zonesRequested = false;
  let wired = false;

  function loadTimeZones() {
    if (zonesRequested) return;
    zonesRequested = true;
    fetch(window.officekitApiUrl('/api/calculator/time-zones'), { cache: 'no-store' })
      .then(response => window.officekitReadCalculatorResponse(response))
      .then(data => { if (Array.isArray(data?.zones)) populateZones(data.zones); })
      .catch(() => { zonesRequested = false; });
  }

  // Approved 2026-10-24 (work-area mock): each calculator's Calculate sits in one bottom row inside the card, status on the left.
  function buildActionRows() {
    document.querySelectorAll('[data-calc-form]').forEach(form => {
      const run = form.querySelector('[data-calc-run]');
      if (!run || run.closest('.calc-actionbar')) return;
      const status = document.createElement('p');
      status.className = 'calc-actionbar__status';
      status.textContent = 'Result appears here after you convert.';
      const row = document.createElement('div');
      row.className = 'calc-actionbar';
      run.classList.remove('w-full');
      row.append(status, run);
      form.append(row);
    });
  }

  function wire() {
    if (wired) return;
    wired = true;
    document.addEventListener('click', noteRun, true);
    buildActionRows();
    document.addEventListener('input', onInputChange);
    document.addEventListener('change', onInputChange);
    el('calc-fractions-operation')?.addEventListener('change', syncFractionsOperand);
    el('calc-geometry-shape')?.addEventListener('change', relabelGeometry);
    relabelGeometry();
    syncFractionsOperand();
  }

  function onShown(calc) {
    wire();
    const form = el(`calc-form-${calc}`);
    form?.querySelector('[data-calc-run]')?.classList.add('hidden');
    if (form) setTimeout(() => runLive(form), 0);
    if (calc === 'time-zones' || calc === 'work-hours') loadTimeZones();
    if (calc === 'age') {
      const asOf = el('calc-age-as-of');
      if (asOf && !asOf.value) {
        const today = new Date();
        const pad = number => String(number).padStart(2, '0');
        asOf.value = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
      }
    }
  }

  window.OfficeKitCalculatorShown = onShown;
  window.OfficeKitCalculatorFieldUnit = fieldUnit;
  window.officekitCalcMarkFresh = markFresh;
  window.OfficeKitCalcSlice = {
    restorePlan,
    specs: SPECS,
    showValidationIssue,
    clearValidationIssue,
    parse: { readNumber, readList, readDateLines, readWorkRows, readDate },
    assertResponse,
    formatRoot,
    formatMixed,
    weekendChoices: WEEKEND_CHOICES,
    geometryShapes: GEOMETRY_SHAPES,
  };
  window.runNewCalculator = runNewCalculator;
})();
