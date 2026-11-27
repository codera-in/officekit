// Image slice (I06–I07, I10–I12, I14–I20).
// Keep this register() call first. List destinations one `id: { tab: '…', … },` line
// each: tests/ui-search-routing.test.mjs parses them against the live catalogue.
window.OfficeKitExtensions.register({
  slice: 'image',
  destinations: {
    image_rotate_flip: { tab: 'image-tools', sliceView: 'rotate-flip' },
    image_exif_view: { tab: 'image-tools', sliceView: 'exif' },
    image_dpi: { tab: 'image-tools', sliceView: 'dpi' },
    image_grayscale: { tab: 'image-tools', sliceView: 'grayscale' },
    image_adjust: { tab: 'image-tools', sliceView: 'adjust' },
    image_border: { tab: 'image-tools', sliceView: 'border' },
    image_palette: { tab: 'image-tools', sliceView: 'palette' },
    image_data_uri: { tab: 'image-tools', sliceView: 'data-uri' },
    image_icon_pack: { tab: 'image-tools', sliceView: 'icon-pack' },
    image_collage: { tab: 'image-tools', sliceView: 'collage' },
    image_contact_sheet: { tab: 'image-tools', sliceView: 'contact-sheet' },
    image_compare: { tab: 'image-tools', sliceView: 'compare' },
  },
  tabs: ['image-tools'],
  openView: view => window.OfficeKitImageTools?.openView(view),
});

(function imageToolsSlice() {
  'use strict';

  // ---------------------------------------------------------------------------
  // Pure logic (no DOM). Loaded by tests/image-tools-*.test.mjs through a vm context.
  // ---------------------------------------------------------------------------

  const LIMITS = Object.freeze({
    previewMaxEdge: 1024,
    collageSide: 10000,
    collageArea: 40000000,
    collageFiles: 50,
    contactSheetFiles: 200,
    dataUriChars: 11184900,
  });
  const DATA_URI_PATTERN = /^data:image\/(png|jpeg|webp|gif|bmp|tiff|svg\+xml);base64,/;
  const HEX_PATTERN = /^#[0-9a-fA-F]{6}$/;
  const SUPPORTED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif'];
  const ACCEPT = SUPPORTED_EXTENSIONS.join(',');
  const METADATA_GROUPS = ['date', 'camera', 'exposure', 'image', 'location'];
  const METADATA_STATUSES = ['present', 'missing', 'unsupported', 'malformed'];
  const RESPONSE_ERROR = 'The server returned an unexpected response. Try again.';
  const STATUS_MESSAGES = Object.freeze({
    400: 'The request was not accepted. Check the values and try again.',
    413: 'The image is too large for this tool.',
    415: 'Choose a supported image file.',
    422: 'The image could not be processed. It may be damaged or the settings are not supported.',
  });

  class ImageToolError extends Error {
    constructor(message, status = 0) {
      super(message);
      this.name = 'ImageToolError';
      this.status = status;
    }
  }

  // Every interpolated value is escaped unless it is wrapped with raw(). P-011.
  class Raw {
    constructor(value) { this.value = String(value); }
    toString() { return this.value; }
  }
  function raw(value) { return new Raw(value); }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  }
  function renderPart(value) {
    if (value instanceof Raw) return value.value;
    if (Array.isArray(value)) return value.map(renderPart).join('');
    return escapeHtml(value);
  }
  function html(strings, ...values) {
    return new Raw(strings.reduce((out, text, index) => out + text + (index < values.length ? renderPart(values[index]) : ''), ''));
  }

  const VIEWS = Object.freeze([
    { slug: 'rotate-flip', title: 'Rotate & flip', group: 'Adjust', tool: 'image_rotate_flip' },
    { slug: 'grayscale', title: 'Grayscale', group: 'Adjust', tool: 'image_grayscale' },
    { slug: 'adjust', title: 'Color adjustments', group: 'Adjust', tool: 'image_adjust' },
    { slug: 'border', title: 'Borders & corners', group: 'Adjust', tool: 'image_border' },
    { slug: 'dpi', title: 'DPI / PPI', group: 'Adjust', tool: 'image_dpi' },
    { slug: 'exif', title: 'EXIF viewer', group: 'Inspect', tool: 'image_exif_view' },
    { slug: 'palette', title: 'Dominant colors', group: 'Inspect', tool: 'image_palette' },
    { slug: 'compare', title: 'Compare images', group: 'Inspect', tool: 'image_compare' },
    { slug: 'collage', title: 'Collage', group: 'Combine', tool: 'image_collage' },
    { slug: 'contact-sheet', title: 'Contact sheet', group: 'Combine', tool: 'image_contact_sheet' },
    { slug: 'data-uri', title: 'Image ↔ data URI', group: 'Export', tool: 'image_data_uri' },
    { slug: 'icon-pack', title: 'Icon pack', group: 'Export', tool: 'image_icon_pack' },
  ]);
  const GROUPS = Object.freeze(['Adjust', 'Inspect', 'Combine', 'Export']);

  function viewForSlug(slug) {
    return VIEWS.find(view => view.slug === slug) || null;
  }

  // Accepts a number or a non-empty numeric string. Blank or non-numeric input is rejected.
  function integerInRange(value, min, max, label) {
    const number = typeof value === 'string' && value.trim() !== '' ? Number(value) : value;
    if (typeof number !== 'number' || !Number.isInteger(number) || number < min || number > max) {
      throw new ImageToolError(`${label} must be a whole number from ${min} to ${max}.`);
    }
    return number;
  }

  function normalizeHex(value) {
    if (typeof value !== 'string' || !HEX_PATTERN.test(value)) throw new ImageToolError('Choose a colour as #RRGGBB.');
    return value.toUpperCase();
  }

  // Operations for /api/image-renditions. Objects carry only the keys the server's
  // discriminated union accepts, because extra keys are rejected.
  function renditionOperations(slug, params = {}) {
    if (slug === 'rotate-flip') {
      const operations = [];
      const degrees = integerInRange(params.turn || '0', 0, 270, 'Turn');
      if (degrees !== 0) {
        if (![90, 180, 270].includes(degrees)) throw new ImageToolError('Turn must be 90, 180 or 270 degrees.');
        operations.push({ type: 'rotate', degrees_cw: degrees });
      }
      if (params.flip_h) operations.push({ type: 'flip', axis: 'horizontal' });
      if (params.flip_v) operations.push({ type: 'flip', axis: 'vertical' });
      return operations;
    }
    if (slug === 'grayscale') return [{ type: 'grayscale' }];
    if (slug === 'adjust') {
      const brightness = integerInRange(params.brightness ?? '0', -100, 100, 'Brightness');
      const contrast = integerInRange(params.contrast ?? '0', -100, 100, 'Contrast');
      const saturation = integerInRange(params.saturation ?? '0', -100, 100, 'Saturation');
      if (brightness === 0 && contrast === 0 && saturation === 0) return [];
      return [{ type: 'adjust', brightness, contrast, saturation }];
    }
    if (slug === 'border') {
      return [{
        type: 'border',
        width: integerInRange(params.width, 0, 2000, 'Border width'),
        corner_radius: integerInRange(params.corner_radius ?? '0', 0, 5000, 'Corner radius'),
        fill: normalizeHex(params.fill || '#FFFFFF'),
        fill_opacity: integerInRange(params.fill_opacity ?? '100', 0, 100, 'Fill opacity'),
      }];
    }
    if (slug === 'dpi') {
      return [{
        type: 'density',
        x: integerInRange(params.x, 1, 2400, 'Horizontal density'),
        y: integerInRange(params.y, 1, 2400, 'Vertical density'),
        unit: params.unit === 'cm' ? 'cm' : 'inch',
      }];
    }
    throw new ImageToolError('This view does not export a rendition.');
  }

  function buildRenditionForm({ file, operations, format = 'same', quality, previewMaxEdge }) {
    if (!Array.isArray(operations) || operations.length < 1 || operations.length > 8) {
      throw new ImageToolError('Choose at least one change.');
    }
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('operations', JSON.stringify({ operations }));
    form.append('format', format);
    if (quality !== undefined && quality !== '' && (format === 'jpeg' || format === 'webp' || format === 'same')) {
      form.append('quality', String(integerInRange(quality, 1, 100, 'Quality')));
    }
    if (previewMaxEdge !== undefined) {
      form.append('preview_max_edge', String(integerInRange(previewMaxEdge, 64, 2048, 'Preview size')));
    }
    return form;
  }

  function buildMetadataForm(file, includeLocation) {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('include_location', includeLocation ? 'true' : 'false');
    return form;
  }

  // Canvas size is computed before any upload, so an oversize layout never reaches the server.
  function collageCanvas(params, count) {
    const columns = integerInRange(params.columns, 1, 10, 'Columns');
    const cellWidth = integerInRange(params.cell_width, 16, 4000, 'Cell width');
    const cellHeight = integerInRange(params.cell_height, 16, 4000, 'Cell height');
    const gap = integerInRange(params.gap ?? '0', 0, 200, 'Gap');
    const padding = integerInRange(params.padding ?? '0', 0, 400, 'Padding');
    const fit = params.fit === 'cover' ? 'cover' : 'contain';
    const background = params.background === 'transparent' ? 'transparent' : normalizeHex(params.background || '#FFFFFF');
    const format = ['png', 'jpeg', 'webp'].includes(params.format) ? params.format : 'png';
    const rows = Math.max(1, Math.ceil(count / columns));
    const width = 2 * padding + columns * cellWidth + (columns - 1) * gap;
    const height = 2 * padding + rows * cellHeight + (rows - 1) * gap;
    const overflow = width > LIMITS.collageSide || height > LIMITS.collageSide || width * height > LIMITS.collageArea;
    return {
      width,
      height,
      rows,
      overflow,
      reason: overflow ? `The canvas would be ${width} × ${height} px. Keep each side at ${LIMITS.collageSide} px or less and the total under 40 million pixels.` : '',
      layout: { columns, cell_width: cellWidth, cell_height: cellHeight, fit, gap, padding, background, format },
    };
  }

  function buildCollageForm(files, params) {
    if (!Array.isArray(files) || files.length < 2 || files.length > LIMITS.collageFiles) {
      throw new ImageToolError(`Choose 2 to ${LIMITS.collageFiles} images.`);
    }
    const canvas = collageCanvas(params, files.length);
    if (canvas.overflow) throw new ImageToolError(canvas.reason);
    const form = new FormData();
    files.forEach(file => form.append('files', file, file.name));
    form.append('layout', JSON.stringify(canvas.layout));
    return form;
  }

  function contactSheetPages(count, columns, rows) {
    return Math.max(1, Math.ceil(count / (columns * rows)));
  }

  function buildContactSheetForm(files, params, preview = false) {
    if (!Array.isArray(files) || files.length < 1 || files.length > LIMITS.contactSheetFiles) {
      throw new ImageToolError(`Choose 1 to ${LIMITS.contactSheetFiles} images.`);
    }
    const sheet = {
      page: params.page === 'letter' ? 'letter' : 'a4',
      orientation: params.orientation === 'landscape' ? 'landscape' : 'portrait',
      columns: integerInRange(params.columns, 1, 10, 'Columns'),
      rows: integerInRange(params.rows, 1, 20, 'Rows'),
      show_names: Boolean(params.show_names),
      format: params.format === 'png-zip' ? 'png-zip' : 'pdf',
      ...(preview ? { preview_first_page: true } : {}),
    };
    const form = new FormData();
    files.forEach(file => form.append('files', file, file.name));
    form.append('sheet', JSON.stringify(sheet));
    return form;
  }

  function buildComparisonForm(fileA, fileB, { alignment = 'none', threshold = 0 } = {}) {
    const form = new FormData();
    form.append('image_a', fileA, fileA.name);
    form.append('image_b', fileB, fileB.name);
    form.append('alignment', alignment === 'scale-b-to-a' ? 'scale-b-to-a' : 'none');
    form.append('threshold', String(integerInRange(threshold, 0, 255, 'Threshold')));
    return form;
  }

  function buildPaletteForm(file, count, alphaThreshold) {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('count', String(integerInRange(count, 1, 12, 'Colours')));
    form.append('alpha_threshold', String(integerInRange(alphaThreshold, 1, 255, 'Alpha threshold')));
    return form;
  }

  function buildIconPackForm(file, flags, fit) {
    const platforms = ['web', 'windows', 'macos'].filter(name => flags[name]);
    if (platforms.length < 1 || platforms.length > 3) throw new ImageToolError('Choose at least one platform.');
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('platforms', platforms.join(','));
    form.append('fit', fit === 'crop' ? 'crop' : 'pad');
    return form;
  }

  function validateDataUriText(text) {
    if (typeof text !== 'string' || text.length === 0) return { ok: false, reason: 'Paste a data URI that starts with data:image/.' };
    if (text.length > LIMITS.dataUriChars) return { ok: false, reason: 'This data URI is too large for this tool.' };
    if (!DATA_URI_PATTERN.test(text)) return { ok: false, reason: 'Only base64 image data URIs (PNG, JPEG, WebP, GIF, BMP, TIFF or SVG) are supported.' };
    return { ok: true, reason: '' };
  }

  function expectObject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ImageToolError(RESPONSE_ERROR);
    return value;
  }

  function parseMetadataReport(value) {
    const report = expectObject(value);
    if (typeof report.format !== 'string' || !Number.isInteger(report.width) || !Number.isInteger(report.height)
      || !Array.isArray(report.groups) || report.groups.length > 256) throw new ImageToolError(RESPONSE_ERROR);
    const groups = report.groups.map(entry => {
      const item = expectObject(entry);
      if (!METADATA_GROUPS.includes(item.group) || !METADATA_STATUSES.includes(item.status)
        || typeof item.label !== 'string' || typeof item.value !== 'string') throw new ImageToolError(RESPONSE_ERROR);
      return { group: item.group, tag: String(item.tag ?? ''), label: item.label, value: item.value, status: item.status };
    });
    const location = expectObject(report.location);
    return {
      format: report.format,
      width: report.width,
      height: report.height,
      frames: Number.isInteger(report.frames) ? report.frames : 1,
      groups,
      location: {
        present: Boolean(location.present),
        withheld: Boolean(location.withheld),
        latitude: typeof location.latitude === 'number' ? location.latitude : null,
        longitude: typeof location.longitude === 'number' ? location.longitude : null,
        altitude_m: typeof location.altitude_m === 'number' ? location.altitude_m : null,
      },
      has_icc: Boolean(report.has_icc),
      has_xmp: Boolean(report.has_xmp),
      has_iptc: Boolean(report.has_iptc),
    };
  }

  function parsePalette(value) {
    const palette = expectObject(value);
    if (!Array.isArray(palette.colors) || !Number.isInteger(palette.sampled_pixels)) throw new ImageToolError(RESPONSE_ERROR);
    const colors = palette.colors.map(entry => {
      const swatch = expectObject(entry);
      if (typeof swatch.hex !== 'string' || !HEX_PATTERN.test(swatch.hex) || !Array.isArray(swatch.rgb) || swatch.rgb.length !== 3
        || typeof swatch.share !== 'number') throw new ImageToolError(RESPONSE_ERROR);
      return { hex: swatch.hex.toUpperCase(), rgb: swatch.rgb.slice(), share: swatch.share, pixels: Number(swatch.pixels) || 0 };
    });
    return { colors, sampled_pixels: palette.sampled_pixels, excluded_transparent_pixels: Number(palette.excluded_transparent_pixels) || 0 };
  }

  function parseComparison(value) {
    const result = expectObject(value);
    if (typeof result.comparable !== 'boolean' || !result.a || !result.b || typeof result.threshold !== 'number') {
      throw new ImageToolError(RESPONSE_ERROR);
    }
    if (result.difference_png !== undefined && result.difference_png !== null && typeof result.difference_png !== 'string') {
      throw new ImageToolError(RESPONSE_ERROR);
    }
    return { ...result, a: { w: result.a.w, h: result.a.h }, b: { w: result.b.w, h: result.b.h } };
  }

  // Wording never claims identity: zero changes is reported as "no pixel differed by more than N".
  // Used for the size-mismatch alert and for a zero-change result. Changed results show the stat tiles instead.
  // Only a zero-change result gets this sentence. A changed result is described by the stat tiles, so it returns no sentence.
  function comparisonSummary(result) {
    if (!result.comparable) return 'No pixel difference was computed.';
    if (result.changed_pixels !== 0) return '';
    return `No pixel differed by more than ${result.threshold} at ${result.a.w} × ${result.a.h}.`;
  }

  // Thousands are grouped with no-break spaces, as the approved mock writes them ("12 288").
  function formatCount(value) {
    return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  // The three stat tiles of the approved Compare panel: percent changed, changed count of the total, max channel delta.
  function comparisonStatsMarkup(result) {
    const total = result.a.w * result.a.h;
    const percent = ((result.changed_ratio || 0) * 100).toFixed(2);
    return html`<div class="image-tools__stats">
      <div class="image-tools__stat"><b>${percent}%</b>pixels changed &gt; ${result.threshold}</div>
      <div class="image-tools__stat"><b>${formatCount(result.changed_pixels)}</b>of ${formatCount(total)}</div>
      <div class="image-tools__stat"><b>${result.max_channel_delta ?? '—'}</b>max channel delta</div></div>`;
  }

  function parseDataUri(value) {
    const encoded = expectObject(value);
    if (typeof encoded.mime !== 'string' || typeof encoded.data_uri !== 'string' || !Number.isInteger(encoded.byte_length)) {
      throw new ImageToolError(RESPONSE_ERROR);
    }
    return { mime: encoded.mime, byte_length: encoded.byte_length, data_uri_length: Number(encoded.data_uri_length) || encoded.data_uri.length, data_uri: encoded.data_uri };
  }

  // The density is per inch or per cm, so pixels / density is already a length in that unit.
  function printSize(pixels, density, unit) {
    if (!density || density <= 0) return '';
    const size = pixels / density;
    return unit === 'cm' ? `${size.toFixed(1)} cm` : `${size.toFixed(2)} in`;
  }

  // Decodes a server-produced image data URI locally, so the packaged WebView never fetches a data: URL.
  function dataUriToBlob(uri) {
    const match = typeof uri === 'string' ? uri.match(/^data:(image\/[a-z+]+);base64,([A-Za-z0-9+/]*={0,2})$/) : null;
    if (!match) throw new ImageToolError('The result is not an image data URI.');
    const binary = atob(match[2]);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: match[1] });
  }

  function errorMessageFromResponse(status, bodyText) {
    let detail = '';
    try {
      const parsed = JSON.parse(bodyText);
      if (parsed && typeof parsed.detail === 'string') detail = parsed.detail;
    } catch {
      detail = '';
    }
    return detail || STATUS_MESSAGES[status] || 'The request could not be completed. Try again.';
  }

  function metadataText(report, { includeLocation }) {
    const lines = report.groups
      .filter(entry => entry.group !== 'location')
      .map(entry => `${entry.label}: ${entry.status === 'present' ? entry.value : entry.status}`);
    if (includeLocation && report.location.latitude !== null && report.location.longitude !== null) {
      lines.push(`Location: ${report.location.latitude}, ${report.location.longitude}`);
    }
    return lines.join('\n');
  }

  function paletteCsv(palette) {
    const rows = ['hex,r,g,b,share'];
    palette.colors.forEach(color => rows.push(`${color.hex},${color.rgb.join(',')},${(color.share * 100).toFixed(1)}%`));
    return rows.join('\n');
  }

  const logic = Object.freeze({
    LIMITS, VIEWS, GROUPS, SUPPORTED_EXTENSIONS, ImageToolError, Raw, raw, escapeHtml, html,
    viewForSlug, integerInRange, normalizeHex, renditionOperations, buildRenditionForm, buildMetadataForm,
    collageCanvas, buildCollageForm, contactSheetPages, buildContactSheetForm, buildComparisonForm,
    buildPaletteForm, buildIconPackForm, validateDataUriText, parseMetadataReport, parsePalette,
    parseComparison, comparisonSummary, parseDataUri, printSize, errorMessageFromResponse, metadataText,
    paletteCsv,
  });

  // ---------------------------------------------------------------------------
  // DOM layer. Everything here runs lazily, from openView or an event handler.
  // ---------------------------------------------------------------------------

  const SECTION_ID = 'tab-image-tools';
  const state = {
    section: null, slug: null, files: {}, urls: {}, objectUrls: new Set(), previewUrl: null, preview: null,
    comparison: null, compareMode: 'side', overlayOpacity: 50, threshold: 8, alignment: 'none',
    orderedPreviewUrl: null, palette: null, metadata: null, includeLocation: false, dataUri: null, statusRevision: 0,
  };

  function apiUrl(path) {
    return typeof officekitApiUrl === 'function' ? officekitApiUrl(path) : path;
  }

  async function postForm(path, body, signal) {
    const response = await fetch(apiUrl(path), { method: 'POST', body, signal });
    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new ImageToolError(errorMessageFromResponse(response.status, text), response.status);
    }
    return response;
  }

  function ensureSection() {
    if (state.section && state.section.isConnected) return state.section;
    let section = document.getElementById(SECTION_ID);
    if (!section) {
      section = document.createElement('section');
      section.id = SECTION_ID;
      section.className = 'hidden space-y-6 image-tools';
      section.setAttribute('aria-label', 'Image tools');
      const anchor = document.getElementById('tab-ergonomics');
      if (anchor) anchor.insertAdjacentElement('afterend', section);
      else document.body.append(section);
    }
    state.section = section;
    return section;
  }

  // One object URL per slot, cached until the file changes or the view is left.
  function urlFor(slot) {
    if (!state.files[slot]) return '';
    if (!state.urls[slot]) {
      const url = URL.createObjectURL(state.files[slot]);
      state.urls[slot] = url;
      state.objectUrls.add(url);
    }
    return state.urls[slot];
  }

  function revokeUrls() {
    state.objectUrls.forEach(url => URL.revokeObjectURL(url));
    state.objectUrls.clear();
    state.urls = {};
    state.previewUrl = null;
    state.orderedPreviewUrl = null;
  }

  function renderShell(section) {
    if (section.dataset.ready === 'true') return;
    section.dataset.ready = 'true';
    const rail = GROUPS.map(group => html`<h3 class="image-tools__group">${group}</h3>${VIEWS.filter(view => view.group === group).map(view => html`<a href="#image-tools/${view.slug}" data-slug="${view.slug}">${view.title}</a>`)}`);
    const menu = VIEWS.map(view => html`<option value="${view.slug}">${view.title}</option>`);
    section.innerHTML = html`
      <div class="image-tools__layout">
        <nav class="image-tools__rail" aria-label="Image tools">${rail}
          <p class="image-tools__foot">Convert, resize or compress: <button type="button" class="link" data-open-tool="media_toolkit">Media Toolkit</button></p>
        </nav>
        <div class="image-tools__menu">
          <label for="image-tools-menu">Tool</label>
          <select id="image-tools-menu">${menu}</select>
        </div>
        <div class="image-tools__main" id="image-tools-main"></div>
      </div>`;
    section.addEventListener('click', event => {
      const tool = event.target.closest('[data-open-tool]');
      if (tool) {
        event.preventDefault();
        if (typeof window.selectSearchTool === 'function') window.selectSearchTool(tool.dataset.openTool);
        return;
      }
      const tab = event.target.closest('[data-open-tab]');
      if (tab) {
        event.preventDefault();
        if (typeof window.switchTab === 'function') window.switchTab(tab.dataset.openTab);
        return;
      }
      const link = event.target.closest('.image-tools__rail a[data-slug]');
      if (link) {
        event.preventDefault();
        navigate(link.dataset.slug);
      }
    });
    section.querySelector('#image-tools-menu').addEventListener('change', event => navigate(event.target.value));
  }

  function navigate(slug) {
    if (!viewForSlug(slug)) return;
    if (window.location.hash !== `#image-tools/${slug}`) history.pushState(null, '', `#image-tools/${slug}`);
    renderView(slug);
  }

  function markRail(slug) {
    state.section.querySelectorAll('.image-tools__rail a[data-slug]').forEach(link => {
      if (link.dataset.slug === slug) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    state.section.querySelector('#image-tools-menu').value = slug;
  }

  // The dock is the one persistent action area of a view. Form controls (not buttons) may sit beside it.
  function dock(status, buttons, control = '', statusRole = 'status', statusClass = '') {
    if (buttons.length > 3) throw new Error('An action dock holds at most three buttons.');
    return html`<footer class="ok-action-dock"><p class="ok-action-dock__status${statusClass ? ` ${statusClass}` : ''}" role="${statusRole}">${status}</p>
      <div class="ok-action-dock__controls">${control}${buttons.map(button => html`<button type="button" class="btn${button.primary ? ' btn-primary' : ''}" data-action="${button.action}"${button.disabled ? ' disabled' : ''}>${button.label}</button>`)}</div></footer>`;
  }

  function setStatus(text, { error = false } = {}) {
    state.statusRevision += 1;
    const status = state.section?.querySelector('.ok-action-dock__status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('ok-image-error', error);
  }

  function collectParams(root) {
    const params = {};
    root.querySelectorAll('[data-param]').forEach(input => {
      params[input.dataset.param] = input.type === 'checkbox' ? input.checked : input.value;
    });
    return params;
  }

  function baseNameOf(file) {
    return (file?.name || 'image').replace(/\.[^.]+$/, '') || 'image';
  }

  async function downloadResponse(response, baseName, suffix = '') {
    const blob = await response.blob();
    const type = (response.headers.get('Content-Type') || blob.type || '').split(';')[0].trim();
    const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/bmp': 'bmp', 'image/tiff': 'tif', 'image/gif': 'gif', 'application/pdf': 'pdf', 'application/zip': 'zip', 'text/plain': 'txt' }[type] || 'bin';
    return window.officekitDownloadResultBlob(blob, `${baseName}${suffix}.${extension}`);
  }

  function pickFile(slot, file) {
    if (!file) return;
    const extension = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(extension)) {
      if (state.preview) state.preview.abort();
      state.preview = null;
      const message = `Choose a supported image file.${state.files[slot] ? ' The current image is unchanged.' : ''}`;
      const inlineError = state.section?.querySelector('[data-role="pick-error"]');
      if (inlineError) inlineError.textContent = message;
      else setStatus(message, { error: true });
      return;
    }
    state.files[slot] = file;
    if (state.preview) state.preview.abort();
    revokeUrls();
    renderView(state.slug);
  }

  function fileSlot(slot, multiple = false, label = 'Choose image') {
    return html`<label class="btn btn-primary">${label}<input type="file"${multiple ? ' multiple' : ''} hidden accept="${ACCEPT}" data-slot="${slot}"></label>`;
  }

  function emptyState(slot, text) {
    return html`<div class="image-tools__empty"><p>${text}</p>${fileSlot(slot)}<p class="muted" data-role="pick-error"></p></div>`;
  }

  // The loaded file's name with an in-text "Change image" link (not a button). The input is re-used by the link.
  function fileBar(slot = 'file', label = '') {
    const file = state.files[slot];
    if (!file) return '';
    return html`<div class="image-tools__filebar"><span>${label}${file.name}</span> · <button type="button" class="link" data-action="change-file" data-slot="${slot}">${label ? `Change ${label.trim()}` : 'Change image'}</button>
      <input type="file" hidden accept="${ACCEPT}" data-slot="${slot}"></div>`;
  }

  function downloadNote() {
    return html`<p class="muted image-tools__note">Metadata such as camera and location is kept. <button type="button" class="link" data-open-tool="image_exif_strip">Use Remove metadata to strip it.</button></p>`;
  }

  // Output format lives in the action dock, as the approved mock shows it ("Same format").
  function formatSelect() {
    return html`<label class="image-tools__field">Format
      <select data-param="format">${['same', 'png', 'jpeg', 'webp'].map(option => html`<option value="${option}">${option === 'same' ? 'Same as source' : option.toUpperCase()}</option>`)}</select></label>`;
  }

  function qualityField() {
    return html`<label class="image-tools__field">Quality (JPEG and WebP)
      <input type="number" min="1" max="100" value="90" data-param="quality" aria-describedby="image-quality-hint">
      <span class="image-tools__field-hint" id="image-quality-hint">Choose a whole number from 1 to 100. Used for JPEG and WebP copies.</span>
      <span class="image-tools__field-error" data-role="quality-error" hidden></span></label>`;
  }

  function qualityApplies(file, format) {
    if (format === 'jpeg' || format === 'webp') return true;
    if (format === 'png') return false;
    const source = `${file?.type || ''} ${file?.name || ''}`.toLowerCase();
    return /image\/(?:jpeg|webp)/.test(source) || /\.(?:jpe?g|webp)(?:\s|$)/.test(source);
  }

  function updateQualityValidation(root) {
    const input = root.querySelector('[data-param="quality"]');
    if (!input) return true;
    const wasInvalid = input.getAttribute('aria-invalid') === 'true';
    const format = root.querySelector('[data-param="format"]')?.value || 'same';
    let message = '';
    const applies = qualityApplies(state.files.file, format);
    if (applies) {
      try { integerInRange(input.value, 1, 100, 'Quality'); }
      catch { message = 'Use a whole number from 1 to 100.'; }
    }
    const error = root.querySelector('[data-role="quality-error"]');
    const hint = root.querySelector('#image-quality-hint');
    const save = root.querySelector('[data-action="save"]');
    input.disabled = !applies;
    input.setAttribute('aria-invalid', String(Boolean(message)));
    input.setAttribute('aria-describedby', message ? 'image-quality-hint image-quality-error' : 'image-quality-hint');
    if (error) {
      error.id = 'image-quality-error';
      error.textContent = message;
      error.hidden = !message;
    }
    if (hint) hint.textContent = !applies
      ? 'Only used for JPEG or WebP copies.'
      : 'Choose a whole number from 1 to 100. Used for JPEG and WebP copies.';
    if (save) save.disabled = Boolean(message);
    if (message) setStatus(message, { error: true });
    else if (wasInvalid) setStatus(applies ? 'Quality is valid. You can save the copy.' : '');
    return !message;
  }

  function previewPair(caption) {
    return html`<div class="image-tools__split">
      <figure><img alt="Original image" src="${urlFor('file')}"><figcaption>Original</figcaption></figure>
      <figure><div class="image-tools__preview-frame"><p class="image-tools__preview-state" data-role="preview-state" role="status">Preparing preview…</p><img alt="Image preview" data-role="preview" src="" hidden></div><figcaption data-role="preview-caption">${caption}</figcaption></figure></div>`;
  }

  function schedulePreview(root, buildOperations) {
    if (state.preview) state.preview.abort();
    const file = state.files.file;
    if (!file) return;
    const statusRevision = state.statusRevision;
    const controller = new AbortController();
    state.preview = controller;
    clearTimeout(schedulePreview.timer);
    schedulePreview.timer = setTimeout(async () => {
      const img = root.querySelector('[data-role="preview"]');
      const caption = root.querySelector('[data-role="preview-caption"]');
      const previewState = root.querySelector('[data-role="preview-state"]');
      try {
        const operations = buildOperations(collectParams(root));
        if (operations.length === 0) {
          if (caption) caption.textContent = 'Preview · identity (no change)';
          if (img) { img.src = urlFor('file'); img.hidden = false; }
          if (previewState) previewState.hidden = true;
          setStatus('No change yet.');
          return;
        }
        const form = buildRenditionForm({ file, operations, format: 'png', previewMaxEdge: LIMITS.previewMaxEdge });
        const response = await postForm('/api/image-renditions', form, controller.signal);
        const blob = await response.blob();
        if (controller.signal.aborted || state.preview !== controller) return;
        const nextPreviewUrl = URL.createObjectURL(blob);
        try {
          if (typeof createImageBitmap === 'function') {
            const decodedPreview = await createImageBitmap(blob);
            decodedPreview.close();
          } else {
            const decodedPreview = new Image();
            decodedPreview.src = nextPreviewUrl;
            await decodedPreview.decode();
          }
        }
        catch (error) { URL.revokeObjectURL(nextPreviewUrl); throw error; }
        if (controller.signal.aborted || state.preview !== controller) {
          URL.revokeObjectURL(nextPreviewUrl);
          return;
        }
        if (state.previewUrl) {
          URL.revokeObjectURL(state.previewUrl);
          state.objectUrls.delete(state.previewUrl);
        }
        state.previewUrl = nextPreviewUrl;
        state.objectUrls.add(state.previewUrl);
        if (img) img.src = state.previewUrl;
        if (img) img.hidden = false;
        if (previewState) previewState.hidden = true;
        if (caption) caption.textContent = 'Preview · 1024 px · same engine as export';
        if (state.statusRevision === statusRevision) setStatus('Preview updated.');
      } catch (error) {
        if (error.name === 'AbortError' || controller.signal.aborted || state.preview !== controller) return;
        if (previewState && (!img || img.hidden)) {
          previewState.textContent = 'Preview unavailable. Your original is unchanged.';
          previewState.classList.add('is-error');
        }
        if (state.statusRevision === statusRevision) setStatus(error.message || 'The preview could not be made.');
      }
    }, 250);
  }

  async function exportRendition(root, buildOperations, suffix) {
    const file = state.files.file;
    if (!file) { setStatus('Choose an image first.'); return; }
    if (!updateQualityValidation(root)) return;
    try {
      const params = collectParams(root);
      const operations = buildOperations(params);
      if (operations.length === 0) { setStatus('Change a value before saving.'); return; }
      const format = params.format || 'same';
      const quality = qualityApplies(file, format) ? params.quality || undefined : undefined;
      const form = buildRenditionForm({ file, operations, format, quality });
      setStatus('Saving…');
      const response = await postForm('/api/image-renditions', form);
      const outcome = await downloadResponse(response, baseNameOf(file), suffix);
      setStatus(outcome.state === 'cancelled' ? 'Save cancelled.' : 'Saved. Your original is unchanged.');
    } catch (error) {
      setStatus(error.message || 'The image could not be saved.');
    }
  }

  // Shared bind for the single-image rendition views.
  async function copyImage(root, buildOperations) {
    const file = state.files.file;
    if (!file) return;
    try {
      const operations = buildOperations(collectParams(root));
      if (operations.length === 0) { setStatus('Change a value before copying.'); return; }
      setStatus('Copying…');
      const response = await postForm('/api/image-renditions', buildRenditionForm({ file, operations, format: 'png' }));
      const blob = await response.blob();
      await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })]);
      setStatus('Image copied. Your original is unchanged.');
    } catch (error) {
      setStatus(error instanceof ImageToolError ? error.message : 'The image could not be copied in this window.');
    }
  }

  // Shared bind for the single-image rendition views.
  function renditionView({ content, buildOperations, suffix, previewable, saveLabel = 'Save copy', copyButton = false, afterBind, reset = false }) {
    return {
      markup() {
        if (!state.files.file) return emptyState('file', content.empty);
        const buttons = [{ action: 'save', label: saveLabel, primary: true }];
        if (copyButton) buttons.push({ action: 'copy-image', label: 'Copy image' });
        return html`${fileBar()}${previewable ? previewPair(content.caption) : ''}${content.controls}${downloadNote()}
          ${dock(content.status, buttons, previewable ? formatSelect() : '')}`;
      },
      bind(root) {
        updateQualityValidation(root);
        root.querySelectorAll('[data-param]').forEach(input => {
          input.addEventListener('input', () => {
            const output = root.querySelector(`[data-output="${input.dataset.param}"]`);
            if (output) output.textContent = input.value > 0 ? `+${input.value}` : input.value;
            if (input.dataset.param === 'quality') updateQualityValidation(root);
            else if (previewable) schedulePreview(root, buildOperations);
          });
          input.addEventListener('change', () => {
            if (input.dataset.param === 'quality' || input.dataset.param === 'format') updateQualityValidation(root);
            else if (previewable) schedulePreview(root, buildOperations);
          });
        });
        root.addEventListener('click', event => {
          const chip = event.target.closest('[data-turn]');
          if (chip) {
            const turn = root.querySelector('input[data-param="turn"]');
            turn.value = chip.dataset.turn;
            root.querySelectorAll('[data-turn]').forEach(item => item.setAttribute('aria-selected', String(item === chip)));
            turn.dispatchEvent(new Event('change'));
            return;
          }
          const button = event.target.closest('[data-action]');
          if (!button || button.disabled) return;
          if (button.dataset.action === 'save') exportRendition(root, buildOperations, suffix);
          if (button.dataset.action === 'copy-image') copyImage(root, buildOperations);
          if (button.dataset.action === 'reset' && reset) {
            root.querySelectorAll('input[type=range][data-param]').forEach(input => { input.value = 0; input.dispatchEvent(new Event('input')); });
            if (previewable) schedulePreview(root, buildOperations);
          }
        });
        if (state.files.file && previewable) schedulePreview(root, buildOperations);
        if (afterBind) afterBind(root);
      },
    };
  }

  // kind: 'collage' or 'contact-sheet'. The dock is the view's persistent action area (P-172): it sticks to the bottom.
  function orderedMarkup({ kind, controls }) {
    const files = state.files.files || [];
    const isSheet = kind === 'contact-sheet';
    const items = files.map((file, index) => html`<li data-index="${index}">
      <span class="image-tools__n">${index + 1}</span><span>${file.name}</span>
      <span class="image-tools__moves"><button type="button" data-move="-1" aria-label="Move up">↑</button>
      <button type="button" data-move="1" aria-label="Move down">↓</button><button type="button" data-remove aria-label="Remove">×</button></span></li>`);
    const buttons = [
      { action: 'preview', label: isSheet ? 'Preview page 1' : 'Preview' },
      { action: 'save', label: isSheet ? 'Save PDF' : 'Save collage', primary: true },
    ];
    return html`<div class="image-tools__ordered">
      <div class="image-tools__row"><strong>${files.length} image${files.length === 1 ? '' : 's'}</strong>
        <label class="image-tools__add">Add images<input type="file" multiple hidden accept="${ACCEPT}" data-slot="files"></label></div>
      <ol class="image-tools__order" data-role="order">${items}</ol>
      ${controls}
      <p class="muted" data-role="canvas-size"></p>
      <img class="image-tools__ordered-preview" alt="Preview" data-role="ordered-img" hidden>
      ${dock(files.length ? 'Originals are unchanged.' : 'Add images to begin.', buttons)}
    </div>`;
  }

  function bindOrdered(root, kind) {
    const isSheet = kind === 'contact-sheet';
    const refresh = () => {
      const params = collectParams(root);
      const files = state.files.files || [];
      const size = root.querySelector('[data-role="canvas-size"]');
      const save = root.querySelector('[data-action="save"]');
      const preview = root.querySelector('[data-action="preview"]');
      const setEnabled = enabled => {
        if (save) save.disabled = !enabled;
        if (preview) preview.disabled = !enabled;
      };
      try {
        if (isSheet) {
          const pages = contactSheetPages(files.length || 1, Number(params.columns) || 1, Number(params.rows) || 1);
          size.textContent = `${pages} page${pages === 1 ? '' : 's'} · ${(Number(params.columns) || 0) * (Number(params.rows) || 0)} per page`;
          if (save) save.textContent = params.format === 'png-zip' ? 'Save ZIP' : 'Save PDF';
          setEnabled(files.length >= 1);
        } else {
          const canvas = collageCanvas(params, Math.max(files.length, 2));
          size.textContent = canvas.overflow ? canvas.reason : `Canvas ${canvas.width} × ${canvas.height} px`;
          setEnabled(!canvas.overflow && files.length >= 2);
        }
      } catch (error) {
        size.textContent = error.message;
        setEnabled(false);
      }
    };
    root.addEventListener('input', refresh);
    root.addEventListener('change', event => {
      if (event.target.dataset.slot !== 'files') { refresh(); return; }
      const limit = isSheet ? LIMITS.contactSheetFiles : LIMITS.collageFiles;
      state.files.files = [...(state.files.files || []), ...event.target.files].slice(0, limit);
      revokeUrls();
      renderView(state.slug);
    });
    root.addEventListener('click', event => {
      const files = state.files.files || [];
      const move = event.target.closest('[data-move]');
      const remove = event.target.closest('[data-remove]');
      if (move) {
        const index = Number(move.closest('li').dataset.index);
        const target = index + Number(move.dataset.move);
        if (target < 0 || target >= files.length) return;
        [files[index], files[target]] = [files[target], files[index]];
        renderView(state.slug);
        return;
      }
      if (remove) {
        files.splice(Number(remove.closest('li').dataset.index), 1);
        renderView(state.slug);
        return;
      }
      const save = event.target.closest('[data-action="save"]');
      if (save && !save.disabled) saveOrdered(root, kind);
      const preview = event.target.closest('[data-action="preview"]');
      if (preview && !preview.disabled) previewOrdered(root, kind);
    });
    refresh();
  }

  // The preview is the same engine as the export: a collage at the preview edge, or page 1 of a contact sheet.
  async function previewOrdered(root, kind) {
    const files = state.files.files || [];
    const img = root.querySelector('[data-role="ordered-img"]');
    try {
      setStatus('Building preview…');
      const params = collectParams(root);
      let response;
      if (kind === 'contact-sheet') {
        response = await postForm('/api/contact-sheets', buildContactSheetForm(files, params, true));
      } else {
        const form = buildCollageForm(files, params);
        form.append('preview_max_edge', String(LIMITS.previewMaxEdge));
        response = await postForm('/api/image-collages', form);
      }
      const blob = await response.blob();
      if (state.orderedPreviewUrl) {
        URL.revokeObjectURL(state.orderedPreviewUrl);
        state.objectUrls.delete(state.orderedPreviewUrl);
      }
      state.orderedPreviewUrl = URL.createObjectURL(blob);
      state.objectUrls.add(state.orderedPreviewUrl);
      img.src = state.orderedPreviewUrl;
      img.hidden = false;
      setStatus('Preview updated.');
    } catch (error) {
      setStatus(error.message || 'The preview could not be made.');
    }
  }

  async function saveOrdered(root, kind) {
    const files = state.files.files || [];
    const params = collectParams(root);
    try {
      setStatus('Building…');
      if (kind === 'contact-sheet') {
        const response = await postForm('/api/contact-sheets', buildContactSheetForm(files, params));
        await downloadResponse(response, 'contact-sheet');
      } else {
        const response = await postForm('/api/image-collages', buildCollageForm(files, params));
        await downloadResponse(response, 'collage');
      }
      setStatus('Saved. Your originals are unchanged.');
    } catch (error) {
      setStatus(error.message || 'The file could not be built.');
    }
  }

  function renderMetadata(report, includeLocation) {
    const rows = report.groups.map(entry => {
      const text = entry.status === 'present' ? entry.value
        : entry.status === 'missing' ? 'Missing'
          : entry.status === 'unsupported' ? 'Unsupported' : 'Could not be read';
      return html`<tr><th>${entry.label}</th><td>${text}</td></tr>`;
    });
    let location = html`<span class="muted">Missing</span>`;
    if (report.location.present && report.location.withheld && !includeLocation) {
      location = html`<span class="image-tools__hidden">Present, hidden</span> · <button type="button" class="link" data-action="show-location">Show location</button>`;
    } else if (report.location.present && includeLocation) {
      const altitude = report.location.altitude_m !== null ? ` · altitude ${report.location.altitude_m} m` : '';
      location = html`${report.location.latitude}, ${report.location.longitude}${altitude} · <button type="button" class="link" data-action="hide-location">Hide</button>`;
    }
    return html`<div class="image-tools__table"><table><tbody><tr><th>Location</th><td>${location}</td></tr>${rows}</tbody></table></div>
      <p class="muted">${report.format} · ${report.width} × ${report.height} px · ${report.frames} frame${report.frames === 1 ? '' : 's'}</p>
      ${dock(includeLocation ? 'Location will be included in Copy.' : 'Copy excludes location while it is hidden.', [{ action: 'copy', label: 'Copy details', primary: true }])}
      <p class="muted">Remove location and other metadata with <button type="button" class="link" data-open-tool="image_exif_strip">Remove metadata</button>.</p>`;
  }

  async function loadMetadata(root, includeLocation) {
    const target = root.querySelector('[data-role="exif"]');
    state.metadata = null;
    state.includeLocation = includeLocation;
    target.innerHTML = dock('Reading image metadata…', []);
    try {
      const response = await postForm('/api/image-metadata-reports', buildMetadataForm(state.files.file, includeLocation));
      const report = parseMetadataReport(await response.json());
      state.metadata = report;
      state.includeLocation = includeLocation;
      target.innerHTML = renderMetadata(report, includeLocation);
    } catch (error) {
      target.innerHTML = dock(error.message, [], '', 'alert', 'ok-image-error');
      if ([400, 413, 415, 422].includes(Number(error?.status))) {
        target.querySelector('[role="alert"]')?.setAttribute('data-officekit-no-bug-report', '');
      }
    }
  }

  function renderPalette(palette) {
    return html`<div class="image-tools__swatches">${palette.colors.map(color => html`<div class="image-tools__swatch">
      <i style="background:${color.hex}"></i><span>${color.hex}<br>${(color.share * 100).toFixed(1)}%</span>
      <button type="button" class="link" data-open-tab="color">Convert</button></div>`)}</div>
      <p class="muted">Sampled ${palette.sampled_pixels} pixels · ${palette.excluded_transparent_pixels} transparent pixels excluded.</p>
      ${dock('Copy the palette as CSV.', [{ action: 'copy-csv', label: 'Copy CSV', primary: true }])}`;
  }

  async function loadPalette(root) {
    const target = root.querySelector('[data-role="palette"]');
    const params = collectParams(root);
    state.palette = null;
    target.innerHTML = dock('Sampling colours…', []);
    try {
      const response = await postForm('/api/image-palettes', buildPaletteForm(state.files.file, params.count, params.alpha_threshold));
      state.palette = parsePalette(await response.json());
      target.innerHTML = renderPalette(state.palette);
    } catch (error) {
      target.innerHTML = dock(error.message, [], '', 'alert', 'ok-image-error');
      // A 422 from palette sampling is input feedback (for example, an all-transparent
      // image), so keep the alert accessible without offering bug reporting.
      if (error.status === 422) target.querySelector('[role="alert"]')?.setAttribute('data-officekit-no-bug-report', '');
    }
  }

  // Pure markup for one comparison result, so every compare state can be mounted and counted in tests.
  function comparisonVisualMarkup(result, { mode = 'side', overlayOpacity = 50 } = {}) {
    if (!result.comparable) {
      return html`<div class="image-tools__alert warn"><strong>The images are different sizes.</strong>
        A is ${result.a.w} × ${result.a.h} and B is ${result.b.w} × ${result.b.h}. ${comparisonSummary(result)}
        <button type="button" class="link" data-action="scale">Scale B to A</button></div>`;
    }
    const side = mode === 'side'
      ? html`<div class="image-tools__split"><figure><img alt="Image A" src="${urlFor('a')}"><figcaption>A</figcaption></figure><figure><img alt="Image B" src="${urlFor('b')}"><figcaption>B</figcaption></figure></div>`
      : '';
    const overlay = mode === 'overlay'
      ? html`<div class="image-tools__overlay"><img alt="Image A" src="${urlFor('a')}"><img alt="Image B" class="image-tools__overlay-top" src="${urlFor('b')}" style="opacity:${overlayOpacity / 100}"></div>
        <div class="image-tools__field"><span>B opacity <output data-role="overlay-output">${overlayOpacity}%</output></span>
        <input type="range" min="0" max="100" value="${overlayOpacity}" data-param="overlay-opacity"></div>`
      : '';
    const diff = mode === 'diff'
      ? html`${result.difference_png ? html`<img alt="Difference map" src="${result.difference_png}">` : ''}`
      : '';
    return html`${side}${overlay}${diff}`;
  }

  // Stats and note, then the dock. The view places the threshold slider between the visual and this summary.
  // changed_bbox is PIL's [left, upper, right, lower], with right and lower exclusive; the copy shows inclusive pixels.
  // Returns the region sentence with its trailing space, or '' when the result has no changed box.
  function changedRegionSentence(result) {
    const box = result.changed_bbox;
    if (!Array.isArray(box) || box.length !== 4) return '';
    const [left, upper, right, lower] = box;
    return `Changes are in the region x ${left}–${right - 1}, y ${upper}–${lower - 1}. `;
  }

  function comparisonSummaryMarkup(result) {
    // The approved mismatch state shows no result, and its dock waits with Save disabled.
    if (!result.comparable) {
      return dock('Waiting for a choice.', [{ action: 'save-diff', label: 'Save difference image', primary: true, disabled: true }]);
    }
    // A changed result joins the region sentence and the note in one muted paragraph, as the approved mock does.
    const figures = result.changed_pixels === 0
      ? html`<p class="muted">${comparisonSummary(result)}</p>`
      : html`${comparisonStatsMarkup(result)}`;
    const region = result.changed_pixels === 0 ? '' : changedRegionSentence(result);
    return html`${figures}
      <p class="muted">${region}Results describe pixels at this resolution only, not visual or perceptual sameness.</p>
      ${dock('Not saved to History.', [{ action: 'save-diff', label: 'Save difference image', primary: true }])}`;
  }

  // The whole result as one string, for the tests that count the buttons of each compare mode.
  function comparisonMarkup(result, options = {}) {
    return html`${comparisonVisualMarkup(result, options)}${comparisonSummaryMarkup(result)}`;
  }

  // The threshold applies only to a comparable Difference result.
  function thresholdShown() {
    return state.compareMode === 'diff' && state.comparison?.comparable !== false;
  }

  function renderComparison(root, result) {
    const visual = root.querySelector('[data-role="compare-visual"]');
    const summary = root.querySelector('[data-role="compare-result"]');
    const control = root.querySelector('[data-role="threshold-control"]');
    if (control) control.hidden = !thresholdShown();
    if (!visual || !summary) return;
    visual.innerHTML = comparisonVisualMarkup(result, { mode: state.compareMode, overlayOpacity: state.overlayOpacity });
    summary.innerHTML = comparisonSummaryMarkup(result);
    const differenceMap = visual.querySelector('img[alt="Difference map"]');
    if (differenceMap) {
      const revealMap = () => differenceMap.scrollIntoView({ block: 'nearest' });
      if (differenceMap.complete && differenceMap.naturalWidth) revealMap();
      else differenceMap.addEventListener('load', revealMap, { once: true });
    }
  }

  async function runComparison(root, alignment) {
    const visual = root.querySelector('[data-role="compare-visual"]');
    const summary = root.querySelector('[data-role="compare-result"]');
    state.alignment = alignment;
    try {
      const response = await postForm('/api/image-comparisons', buildComparisonForm(state.files.a, state.files.b, { alignment, threshold: state.threshold }));
      state.comparison = parseComparison(await response.json());
      renderComparison(root, state.comparison);
    } catch (error) {
      state.comparison = null;
      if (visual) visual.textContent = '';
      if (summary) summary.innerHTML = dock(error.message || 'Images could not be compared. Check the files and try again.', [
        { action: 'save-diff', label: 'Save difference image', primary: true, disabled: true },
      ], '', 'alert', 'ok-image-error');
    }
  }

  async function saveDifference() {
    const result = state.comparison;
    if (!result?.difference_png) { setStatus('There is no difference image yet.'); return; }
    try {
      const blob = dataUriToBlob(result.difference_png);
      const outcome = await window.officekitDownloadResultBlob(blob, `${baseNameOf(state.files.a)}-vs-${baseNameOf(state.files.b)}-difference.png`);
      setStatus(outcome.state === 'cancelled' ? 'Save cancelled.' : 'Difference image saved.');
    } catch (error) {
      setStatus(error.message || 'The difference image could not be saved.');
    }
  }

  async function encodeUri(root) {
    const target = root.querySelector('[data-role="uri-result"]');
    state.dataUri = null;
    target.innerHTML = dock('Encoding image as text…', []);
    try {
      const form = new FormData();
      form.append('file', state.files.file, state.files.file.name);
      const response = await postForm('/api/data-uris', form);
      state.dataUri = parseDataUri(await response.json());
      target.innerHTML = html`<span><strong>${state.dataUri.mime}</strong> · ${state.dataUri.byte_length} bytes → ${state.dataUri.data_uri_length} characters of text.</span>
        ${dock('Copy the URI or save it as text.', [{ action: 'copy-uri', label: 'Copy URI', primary: true }, { action: 'save-txt', label: 'Save .txt' }])}`;
    } catch (error) {
      target.innerHTML = dock(error.message, [], '', 'alert', 'ok-image-error');
    }
  }

  async function decodeUri(root) {
    const text = root.querySelector('[data-param="data_uri"]')?.value || '';
    const check = validateDataUriText(text);
    if (!check.ok) { setStatus(check.reason, { error: true }); return; }
    try {
      const body = new Blob([JSON.stringify({ data_uri: text })], { type: 'application/json' });
      setStatus('Saving image…');
      const response = await postForm('/api/data-uri-images', body);
      const blob = await response.blob();
      const subtype = (text.match(/^data:image\/([a-z+]+);/) || [])[1] || 'bin';
      const outcome = await window.officekitDownloadResultBlob(blob, `decoded-image.${subtype === 'svg+xml' ? 'svg' : subtype}`);
      setStatus(outcome.state === 'cancelled' ? 'Save cancelled.' : 'Image saved.');
    } catch (error) {
      const input = root.querySelector('[data-param="data_uri"]');
      const note = root.querySelector('[data-role="uri-check"]');
      input?.setAttribute('aria-invalid', 'true');
      if (note) note.textContent = error.message;
      setStatus(error.message, { error: true });
    }
  }

  function bindDataUri(root) {
    const body = root.querySelector('[data-role="data-uri-body"]');
    const renderBody = () => {
      const direction = collectParams(root).direction;
      if (direction === 'decode') {
        body.innerHTML = html`<label class="image-tools__field">Data URI<textarea rows="6" data-param="data_uri" aria-describedby="image-data-uri-check"></textarea></label>
          <p class="muted" id="image-data-uri-check" data-role="uri-check"></p>${dock('Paste a base64 image data URI to save it.', [{ action: 'save-decode', label: 'Save image', primary: true, disabled: true }])}`;
        const input = body.querySelector('[data-param="data_uri"]');
        const note = body.querySelector('[data-role="uri-check"]');
        const save = body.querySelector('[data-action="save-decode"]');
        const check = validateDataUriText(input.value);
        note.textContent = check.reason;
        save.disabled = !check.ok;
        return;
      }
      body.innerHTML = state.files.file
        ? html`${fileBar()}<div class="muted" data-role="uri-result">Encoding…</div>`
        : emptyState('file', 'Encode an image as base64 text. SVG is never previewed.');
      if (state.files.file) encodeUri(root);
    };
    root.querySelector('[data-param="direction"]').addEventListener('change', renderBody);
    root.addEventListener('input', event => {
      if (event.target.dataset.param !== 'data_uri') return;
      const check = validateDataUriText(event.target.value);
      const note = root.querySelector('[data-role="uri-check"]');
      const save = root.querySelector('[data-action="save-decode"]');
      if (note) note.textContent = check.ok ? 'Looks like an image data URI.' : check.reason;
      if (save) save.disabled = !check.ok;
      if (check.ok) event.target.removeAttribute('aria-invalid');
      else event.target.setAttribute('aria-invalid', 'true');
      setStatus(check.ok ? 'Ready to save the image.' : 'Paste a base64 image data URI.');
    });
    root.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button) return;
      if (button.dataset.action === 'save-decode') decodeUri(root);
      if (button.dataset.action === 'copy-uri' && state.dataUri) {
        window.officekitCopyResultText(state.dataUri.data_uri).then(() => setStatus('Data URI copied.'), error => setStatus(error.message));
      }
      if (button.dataset.action === 'save-txt' && state.dataUri) {
        window.officekitDownloadResultBlob(new Blob([state.dataUri.data_uri], { type: 'text/plain;charset=utf-8' }), `${baseNameOf(state.files.file)}-data-uri.txt`)
          .then(outcome => setStatus(outcome.state === 'cancelled' ? 'Save cancelled.' : 'Text saved.'), error => setStatus(error.message));
      }
    });
    renderBody();
  }

  async function saveIconPack(root) {
    const file = state.files.file;
    const params = collectParams(root);
    try {
      const response = await postForm('/api/icon-packs', buildIconPackForm(file, params, params.fit));
      const upscaled = response.headers.get('X-OfficeKit-Upscaled-Sizes');
      const note = root.querySelector('[data-role="upscale"]');
      if (note) note.textContent = upscaled ? `Enlarged sizes (edges may look soft): ${upscaled}` : '';
      const outcome = await downloadResponse(response, `${baseNameOf(file)}-icons`);
      setStatus(outcome.state === 'cancelled' ? 'Save cancelled.' : 'ZIP saved.');
    } catch (error) {
      setStatus(error.message);
    }
  }

  const RENDERERS = {
    'rotate-flip': renditionView({
      previewable: true,
      suffix: '-rotated',
      buildOperations: params => renditionOperations('rotate-flip', params),
      content: {
        empty: 'Rotate, flip or turn a photo. Orientation is applied first.',
        caption: 'Preview · same engine as export',
        status: '',
        controls: html`<div class="image-tools__controls"><div class="image-tools__turns" role="tablist" aria-label="Turn clockwise">
          ${[['0', 'None'], ['90', '90° CW'], ['180', '180°'], ['270', '270° CW']].map(([value, label]) => html`<button type="button" role="tab" data-turn="${value}" aria-selected="${value === '0'}">${label}</button>`)}</div>
          <input type="hidden" value="0" data-param="turn">
          <label class="image-tools__check"><input type="checkbox" data-param="flip_h"> Flip horizontal</label>
          <label class="image-tools__check"><input type="checkbox" data-param="flip_v"> Flip vertical</label>${qualityField()}</div>`,
      },
    }),
    grayscale: renditionView({
      previewable: true,
      suffix: '-grayscale',
      buildOperations: () => renditionOperations('grayscale'),
      content: {
        empty: 'Convert a photo to black and white. Transparency is kept.',
        caption: 'Preview · same engine as export',
        status: '',
        controls: html`<div class="image-tools__controls">${qualityField()}</div>`,
      },
    }),
    adjust: renditionView({
      previewable: true,
      reset: true,
      copyButton: true,
      suffix: '-adjusted',
      buildOperations: params => renditionOperations('adjust', params),
      content: {
        empty: 'Adjust brightness, contrast and saturation with a live preview.',
        caption: 'Preview · identity (no change)',
        status: '',
        controls: html`<div class="image-tools__controls">${['brightness', 'contrast', 'saturation'].map(name => html`<label class="image-tools__field">${name[0].toUpperCase() + name.slice(1)} <output data-output="${name}">0</output>
          <input type="range" min="-100" max="100" value="0" data-param="${name}"></label>`)}
          <p class="muted"><button type="button" class="link" data-action="reset">Reset to original</button> · Values from −100 to 100. 0 means no change.</p>${qualityField()}</div>`,
      },
    }),
    border: renditionView({
      previewable: true,
      suffix: '-border',
      buildOperations: params => renditionOperations('border', params),
      content: {
        empty: 'Add a border and rounded corners to one image.',
        caption: 'Preview · same engine as export',
        status: '',
        controls: html`<div class="image-tools__controls"><label class="image-tools__field">Width (px)<input type="number" min="0" max="2000" value="24" data-param="width"></label>
          <label class="image-tools__field">Corner radius (px)<input type="number" min="0" max="5000" value="0" data-param="corner_radius"></label>
          <label class="image-tools__field">Fill colour<input type="color" value="#ffffff" data-param="fill"></label>
          <label class="image-tools__field">Fill opacity (%)<input type="number" min="0" max="100" value="100" data-param="fill_opacity"></label>${qualityField()}</div>`,
      },
    }),
    dpi: renditionView({
      previewable: false,
      suffix: '-dpi',
      buildOperations: params => renditionOperations('dpi', params),
      content: {
        empty: 'Set the print density of an image without resampling it.',
        caption: '',
        status: '',
        controls: html`<p class="muted" data-role="print-size">Reading image size…</p>
          <div class="image-tools__controls"><label class="image-tools__field">Horizontal density<input type="number" min="1" max="2400" value="300" data-param="x"></label>
          <label class="image-tools__field">Vertical density<input type="number" min="1" max="2400" value="300" data-param="y"></label>
          <label class="image-tools__field">Unit<select data-param="unit"><option value="inch">per inch</option><option value="cm">per cm</option></select></label></div>`,
      },
      afterBind(root) {
        const file = state.files.file;
        if (!file) return;
        const fields = ['x', 'y'].map(key => root.querySelector(`[data-param="${key}"]`));
        const printSizeLabel = root.querySelector('[data-role="print-size"]');
        const save = root.querySelector('[data-action="save"]');
        const validate = () => {
          let firstInvalid = '';
          fields.forEach((field, index) => {
            if (!field) return;
            const valid = /^\d+$/.test(field.value) && Number(field.value) >= 1 && Number(field.value) <= 2400;
            const key = index === 0 ? 'horizontal' : 'vertical';
            const errorId = `image-dpi-${key}-error`;
            let error = root.querySelector(`#${errorId}`);
            if (!valid && !error) {
              error = document.createElement('span');
              error.id = errorId;
              error.className = 'image-tools__field-error';
              error.textContent = 'Use a whole number from 1 to 2,400.';
              field.insertAdjacentElement('afterend', error);
            } else if (valid && error) error.remove();
            field.setAttribute('aria-invalid', String(!valid));
            if (valid) field.removeAttribute('aria-describedby');
            else {
              field.setAttribute('aria-describedby', errorId);
              if (!firstInvalid) firstInvalid = key;
            }
          });
          const valid = !firstInvalid;
          if (save) save.disabled = !valid;
          if (!valid) {
            if (printSizeLabel) printSizeLabel.textContent = 'Print size preview is unavailable until the density values are corrected.';
            setStatus(`Correct the ${firstInvalid} density to continue.`, { error: true });
          } else if (state.section?.querySelector('.ok-action-dock__status')?.textContent.startsWith('Correct the ')) {
            setStatus('');
          }
          return valid;
        };
        root.addEventListener('input', validate);
        root.addEventListener('change', validate);
        validate();
        postForm('/api/image-metadata-reports', buildMetadataForm(file, false))
          .then(response => response.json())
          .then(parseMetadataReport)
          .then(report => {
            const update = () => {
              if (!validate()) return;
              const params = collectParams(root);
              const label = root.querySelector('[data-role="print-size"]');
              const unit = params.unit === 'cm' ? 'per cm' : 'per inch';
              const x = Number(params.x) || 0;
              const y = Number(params.y) || 0;
              if (label) label.textContent = `Print size at ${x || '…'} ${unit} × ${y || '…'} ${unit}: ${printSize(report.width, x, params.unit)} × ${printSize(report.height, y, params.unit)}`;
            };
            root.addEventListener('input', update);
            root.addEventListener('change', update);
            update();
          })
          .catch(error => { if (validate()) setStatus(error.message); });
      },
    }),
    exif: {
      markup() {
        if (!state.files.file) return emptyState('file', 'Read date, camera and exposure details. Location stays hidden unless you show it.');
        return html`${fileBar()}<div data-role="exif" class="image-tools__exif">Reading metadata…</div>`;
      },
      bind(root) {
        root.addEventListener('click', event => {
          const button = event.target.closest('[data-action]');
          if (!button) return;
          if (button.dataset.action === 'show-location') loadMetadata(root, true);
          if (button.dataset.action === 'hide-location') loadMetadata(root, false);
          if (button.dataset.action === 'copy' && state.metadata) {
            window.officekitCopyResultText(metadataText(state.metadata, { includeLocation: state.includeLocation }))
              .then(() => setStatus('Details copied.'), error => setStatus(error.message));
          }
        });
        if (state.files.file) loadMetadata(root, false);
      },
    },
    palette: {
      markup() {
        if (!state.files.file) return emptyState('file', 'List the dominant colours. Transparent pixels are excluded.');
        return html`${fileBar()}<div data-role="palette" class="image-tools__palette">Sampling colours…</div>
          <div class="image-tools__controls"><label class="image-tools__field">Colours (1–12)<input type="number" min="1" max="12" value="6" data-param="count"></label>
          <label class="image-tools__field">Alpha threshold (1–255)<input type="number" min="1" max="255" value="128" data-param="alpha_threshold"></label></div>`;
      },
      bind(root) {
        root.querySelectorAll('[data-param]').forEach(input => input.addEventListener('change', () => loadPalette(root)));
        root.addEventListener('click', event => {
          const button = event.target.closest('[data-action="copy-csv"]');
          if (!button || !state.palette) return;
          window.officekitCopyResultText(paletteCsv(state.palette)).then(() => setStatus('CSV copied.'), error => setStatus(error.message));
        });
        if (state.files.file) loadPalette(root);
      },
    },
    compare: {
      markup() {
        // A missing image gets a picker; a chosen one gets an in-text "Change" link.
        const slot = (key, name) => (state.files[key]
          ? html`<div class="image-tools__filebar"><span>${name} · ${state.files[key].name}</span> · <button type="button" class="link" data-action="change-file" data-slot="${key}">Change ${name}</button>
              <input type="file" hidden accept="${ACCEPT}" data-slot="${key}"></div>`
          : html`<div class="image-tools__field"><span>Image ${name}</span>${fileSlot(key, false, `Choose image ${name}`)}</div>`);
        const pickers = html`<div class="image-tools__compare-inputs">${slot('a', 'A')}${slot('b', 'B')}</div>`;
        if (!state.files.a || !state.files.b) return html`${pickers}<p class="muted">Choose two images to compare them on this device.</p>`;
        return html`${pickers}
          <div class="image-tools__seg" role="tablist" aria-label="Compare view">
            <button type="button" role="tab" data-mode="side" aria-selected="${state.compareMode === 'side'}">Side by side</button>
            <button type="button" role="tab" data-mode="overlay" aria-selected="${state.compareMode === 'overlay'}">Overlay</button>
            <button type="button" role="tab" data-mode="diff" aria-selected="${state.compareMode === 'diff'}">Difference</button></div>
          <div data-role="compare-visual" class="image-tools__compare-visual"></div>
          <div class="image-tools__field" data-role="threshold-control"><span>Threshold (per channel, 0–255) <output data-role="threshold-output">${state.threshold}</output></span>
            <input type="range" min="0" max="255" value="${state.threshold}" data-param="threshold"></div>
          <div data-role="compare-result" class="image-tools__compare-result">Comparing…</div>`;
      },
      bind(root) {
        // The slider sits beside the result, not in it: renderComparison replaces the result and would drop focus.
        const thresholdControl = root.querySelector('[data-role="threshold-control"]');
        if (thresholdControl) thresholdControl.hidden = !thresholdShown();
        root.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
          state.compareMode = button.dataset.mode;
          root.querySelectorAll('[data-mode]').forEach(item => item.setAttribute('aria-selected', String(item === button)));
          if (thresholdControl) thresholdControl.hidden = !thresholdShown();
          if (state.comparison) renderComparison(root, state.comparison);
        }));
        const thresholdReadout = () => {
          const output = root.querySelector('[data-role="threshold-output"]');
          if (output) output.textContent = String(state.threshold);
        };
        root.addEventListener('input', event => {
          if (event.target.dataset.param === 'threshold') {
            state.threshold = Number(event.target.value);
            thresholdReadout();
            return;
          }
          if (event.target.dataset.param !== 'overlay-opacity') return;
          state.overlayOpacity = Number(event.target.value);
          const top = root.querySelector('.image-tools__overlay-top');
          if (top) top.style.opacity = String(state.overlayOpacity / 100);
          const output = root.querySelector('[data-role="overlay-output"]');
          if (output) output.textContent = `${state.overlayOpacity}%`;
        });
        root.addEventListener('change', event => {
          if (event.target.dataset.param !== 'threshold') return;
          state.threshold = Number(event.target.value);
          thresholdReadout();
          if (state.files.a && state.files.b) runComparison(root, state.alignment);
        });
        root.addEventListener('click', event => {
          const button = event.target.closest('[data-action]');
          if (!button) return;
          if (button.dataset.action === 'scale') runComparison(root, 'scale-b-to-a');
          if (button.dataset.action === 'save-diff') saveDifference();
        });
        if (state.files.a && state.files.b) runComparison(root, state.alignment);
      },
    },
    collage: {
      markup() {
        return orderedMarkup({
          kind: 'collage',
          controls: html`<div class="image-tools__controls">
            <label class="image-tools__field">Columns<input type="number" min="1" max="10" value="2" data-param="columns"></label>
            <label class="image-tools__field">Cell width (px)<input type="number" min="16" max="4000" value="1200" data-param="cell_width"></label>
            <label class="image-tools__field">Cell height (px)<input type="number" min="16" max="4000" value="800" data-param="cell_height"></label>
            <label class="image-tools__field">Gap (px)<input type="number" min="0" max="200" value="20" data-param="gap"></label>
            <label class="image-tools__field">Padding (px)<input type="number" min="0" max="400" value="40" data-param="padding"></label>
            <label class="image-tools__field">Fit<select data-param="fit"><option value="contain">Contain</option><option value="cover">Cover</option></select></label>
            <label class="image-tools__field">Background<input type="color" value="#ffffff" data-param="background"></label>
            <label class="image-tools__field">Format<select data-param="format"><option value="png">PNG</option><option value="jpeg">JPEG</option><option value="webp">WebP</option></select></label></div>`,
        });
      },
      bind(root) { bindOrdered(root, 'collage'); },
    },
    'contact-sheet': {
      markup() {
        return orderedMarkup({
          kind: 'contact-sheet',
          controls: html`<div class="image-tools__controls">
            <label class="image-tools__field">Page<select data-param="page"><option value="a4">A4</option><option value="letter">Letter</option></select></label>
            <label class="image-tools__field">Orientation<select data-param="orientation"><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label>
            <label class="image-tools__field">Columns<input type="number" min="1" max="10" value="4" data-param="columns"></label>
            <label class="image-tools__field">Rows<input type="number" min="1" max="20" value="6" data-param="rows"></label>
            <label class="image-tools__check"><input type="checkbox" checked data-param="show_names"> Show filenames</label>
            <label class="image-tools__field">Output<select data-param="format"><option value="pdf">PDF</option><option value="png-zip">PNG pages in ZIP</option></select></label></div>`,
        });
      },
      bind(root) { bindOrdered(root, 'contact-sheet'); },
    },
    'data-uri': {
      markup() {
        return html`<div class="image-tools__controls"><label class="image-tools__field">Direction<select data-param="direction"><option value="encode">Image → URI</option><option value="decode">URI → Image</option></select></label></div>
          <div data-role="data-uri-body"></div>`;
      },
      bind: bindDataUri,
    },
    'icon-pack': {
      markup() {
        if (!state.files.file) return emptyState('file', 'Build favicons, Windows .ico and macOS .iconset sizes in one ZIP.');
        return html`${fileBar()}<div class="image-tools__controls">
          <fieldset><legend>Platforms</legend>
            <label class="image-tools__check"><input type="checkbox" checked data-param="web"> Web (favicon 16–48, PNG 16–512, apple-touch 180)</label>
            <label class="image-tools__check"><input type="checkbox" data-param="windows"> Windows (app.ico 16–256)</label>
            <label class="image-tools__check"><input type="checkbox" data-param="macos"> macOS (.iconset folder 16–1024)</label></fieldset>
          <label class="image-tools__field">Fit<select data-param="fit"><option value="pad">Pad transparent</option><option value="crop">Crop centre</option></select></label>
          <p class="muted">.icns is not built. Run iconutil on a Mac to convert the .iconset folder.</p>
          <p class="muted" data-role="upscale"></p></div>
          ${dock('Choose platforms and save the ZIP.', [{ action: 'save-zip', label: 'Save ZIP', primary: true }])}`;
      },
      bind(root) {
        root.addEventListener('click', event => {
          const button = event.target.closest('[data-action="save-zip"]');
          if (button && !button.disabled) saveIconPack(root);
        });
      },
    },
  };

  function renderView(slug) {
    const view = viewForSlug(slug);
    const section = ensureSection();
    if (!view) return;
    if (state.slug !== slug) {
      if (state.preview) state.preview.abort();
      revokeUrls();
    }
    state.slug = slug;
    renderShell(section);
    markRail(slug);
    const main = section.querySelector('#image-tools-main');
    const renderer = RENDERERS[slug];
    main.innerHTML = html`<section class="image-tools__view" aria-labelledby="image-tools-view-title">
      <p class="eyebrow">Image tools · ${view.group}</p>
      <h2 id="image-tools-view-title">${view.title}</h2>
      <div class="image-tools__body" data-view="${slug}">${renderer.markup()}</div>
    </section>`;
    const body = main.querySelector('.image-tools__body');
    // The in-text "Change image" / "Change A" links open the hidden input of their slot.
    body.addEventListener('click', event => {
      const change = event.target.closest('[data-action="change-file"]');
      if (!change) return;
      body.querySelector(`input[type="file"][data-slot="${change.dataset.slot || 'file'}"]`)?.click();
    });
    // One delegated listener survives inputs that a renderer re-creates later (Data URI encode).
    body.addEventListener('change', event => {
      const input = event.target;
      if (input.type === 'file' && (input.dataset.slot === 'file' || input.dataset.slot === 'a' || input.dataset.slot === 'b')) {
        pickFile(input.dataset.slot, input.files[0]);
      }
    });
    renderer.bind(body);
  }

  function openView(view) {
    if (!VIEWS.some(item => item.slug === view)) return;
    const section = ensureSection();
    section.classList.remove('hidden');
    renderView(view);
  }

  window.addEventListener('hashchange', () => {
    const match = window.location.hash.match(/^#image-tools\/([a-z-]+)$/);
    if (!match || !state.section || state.section.classList.contains('hidden')) return;
    if (viewForSlug(match[1])) renderView(match[1]);
  });

  // Renders one view's markup with the given files (and optional state overrides) without touching the page.
  // Used by tests to count the buttons each view shows (AGENTS.md Button Limit).
  function viewMarkup(slug, files = {}, overrides = {}) {
    const saved = { files: state.files, ...Object.fromEntries(Object.keys(overrides).map(key => [key, state[key]])) };
    state.files = files;
    Object.assign(state, overrides);
    try {
      return RENDERERS[slug].markup();
    } finally {
      state.files = saved.files;
      Object.keys(overrides).forEach(key => { state[key] = saved[key]; });
    }
  }

  // Attaches one view's event handlers to a root without rendering it. Used by tests to drive bind() on a stub root.
  function bindView(slug, root, files = state.files) {
    const saved = state.files;
    state.files = files;
    try {
      RENDERERS[slug].bind(root);
    } finally {
      state.files = saved;
    }
  }

  window.OfficeKitImageTools = Object.freeze({ ...logic, dock, comparisonMarkup, dataUriToBlob, viewMarkup, openView, bindView });
})();
