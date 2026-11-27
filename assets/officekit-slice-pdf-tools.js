// PDF slice (P06, P08, P10, P12–P13, P15–P17).
// Keep this register() call first. List destinations one `id: { tab: '…', … },` line
// each: tests/ui-search-routing.test.mjs parses them against the live catalogue.
window.OfficeKitExtensions.register({
  slice: 'pdf_tools',
  destinations: {
    pdf_rotate_pages: { tab: 'pdf', pdfTool: 'rotate' },
    pdf_from_images: { tab: 'pdf', pdfTool: 'images-to-pdf' },
    pdf_metadata_view: { tab: 'pdf', pdfTool: 'metadata-view' },
    pdf_watermark: { tab: 'pdf', pdfTool: 'watermark' },
    pdf_page_numbers: { tab: 'pdf', pdfTool: 'page-numbers' },
    pdf_resize_pages: { tab: 'pdf', pdfTool: 'resize-pages' },
    pdf_grayscale: { tab: 'pdf', pdfTool: 'grayscale' },
    pdf_flatten: { tab: 'pdf', pdfTool: 'flatten' },
  },
  tabs: [],
});

// Request building, validation, response checks and the DOM builders for the eight new
// PDF operations. Everything here is lazy: nothing touches the DOM until a builder is called.
// The workbench passes a shell object (files, tool, callbacks); this module owns the rest.
(function () {
  'use strict';

  const MiB = 1024 * 1024;
  const MAX_UPLOAD_BYTES = 64 * MiB;
  const MAX_IMAGE_FILES = 200;
  const MAX_IMAGE_MEGAPIXELS = 40;
  const MAX_OUTPUT_BYTES = 64 * MiB;
  const MAX_PREVIEW_BYTES = 4 * MiB;
  const MAX_WATERMARK_IMAGE_BYTES = 8 * MiB;
  const PREVIEW_DELAY_MS = 400;
  const STANDARD_FIELD_COUNT = 9;
  const GENERIC_FAILURE = 'The PDF task could not be completed. Check the file and settings, then try again.';
  const IMAGE_EXTENSION = /\.(png|jpe?g|webp|tiff?|gif|bmp)$/i;
  const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/tiff', 'image/gif', 'image/bmp'];
  const POSITIONS = ['top-left', 'top-center', 'top-right', 'bottom-left', 'bottom-center', 'bottom-right'];
  const WATERMARK_POSITIONS = [['center', 'Center'], ['tile', 'Tile'], ['top-left', 'Top left'], ['top-center', 'Top center'],
    ['top-right', 'Top right'], ['bottom-left', 'Bottom left'], ['bottom-center', 'Bottom center'], ['bottom-right', 'Bottom right']];
  const ANCHORS = ['top-left', 'top-center', 'top-right', 'center-left', 'center', 'center-right',
    'bottom-left', 'bottom-center', 'bottom-right'];
  const OPERATIONS = Object.freeze({
    rotate: { toolId: 'pdf_rotate_pages', endpoint: '/api/pdf/page-rotations', result: 'pdf', suffix: 'rotated', files: 1 },
    'images-to-pdf': { toolId: 'pdf_from_images', endpoint: '/api/pdf/image-pdfs', result: 'pdf', suffix: 'images', files: MAX_IMAGE_FILES, images: true },
    'metadata-view': { toolId: 'pdf_metadata_view', endpoint: '/api/pdf/inspections', result: 'json', suffix: '', files: 1 },
    watermark: { toolId: 'pdf_watermark', endpoint: '/api/pdf/watermarks', preview: '/api/pdf/watermarks/previews', result: 'pdf', suffix: 'watermarked', files: 1 },
    'page-numbers': { toolId: 'pdf_page_numbers', endpoint: '/api/pdf/page-numbers', preview: '/api/pdf/page-numbers/previews', result: 'pdf', suffix: 'numbered', files: 1 },
    'resize-pages': { toolId: 'pdf_resize_pages', endpoint: '/api/pdf/page-sizes', result: 'pdf', suffix: 'resized', files: 1 },
    grayscale: { toolId: 'pdf_grayscale', endpoint: '/api/pdf/grayscale-conversions', result: 'pdf', suffix: 'grayscale', files: 1 },
    flatten: { toolId: 'pdf_flatten', endpoint: '/api/pdf/flattenings', result: 'pdf', suffix: 'flattened', files: 1 },
  });
  const states = Object.create(null);

  class PdfSliceError extends Error {
    constructor(message, code = '', status = 0) {
      super(message);
      this.name = 'PdfSliceError';
      this.code = code;
      this.status = status;
    }
  }

  function isOperation(key) {
    return Object.hasOwn(OPERATIONS, key);
  }

  function operation(key) {
    if (!isOperation(key)) throw new PdfSliceError('This is an unsupported PDF task.');
    return OPERATIONS[key];
  }

  function defaults(key) {
    switch (key) {
      case 'rotate': return { angle: 90, pageRanges: '' };
      case 'images-to-pdf': return { pageSize: 'a4', orientation: 'auto', fit: 'contain', marginMm: 10 };
      case 'metadata-view': return {};
      case 'watermark': return { kind: 'text', text: 'CONFIDENTIAL', position: 'center', opacity: 30, fontSize: 48, angle: 35, color: '#B91C1C', pageRanges: '', imageFile: null };
      case 'page-numbers': return { format: 'number', template: 'Page {n} of {total}', start: 1, position: 'bottom-center', pageRanges: '', marginMm: 10, fontSize: 10, countSkipped: false };
      case 'resize-pages': return { preset: 'a4', width: '', height: '', unit: 'mm', orientation: 'keep', mode: 'scale', anchor: 'center', pageRanges: '' };
      case 'grayscale': return { method: 'vector', dpi: 150 };
      case 'flatten': return { scope: 'all', acknowledge: false, signed: false, signatureFields: 0, factsKey: '', fields: 0, annotations: 0 };
      default: throw new PdfSliceError('This is an unsupported PDF task.');
    }
  }

  // Mutable per-operation state. The inline workbench reads and writes it through state(key).
  function state(key) {
    operation(key);
    if (!states[key]) states[key] = defaults(key);
    return states[key];
  }

  function reset(key) {
    operation(key);
    states[key] = defaults(key);
  }

  function stemOf(name) {
    const stem = String(name || '').replace(/\.pdf$/i, '').replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 100);
    return stem || 'document';
  }

  function isPdfName(name) {
    return /\.pdf$/i.test(String(name || ''));
  }

  function isImageFile(file) {
    return IMAGE_TYPES.includes(String(file?.type || '').toLowerCase()) || IMAGE_EXTENSION.test(String(file?.name || ''));
  }

  // Page ranges are strict and ascending, matching the server: "1-3, 5" is valid, "5, 1-3" is not.
  function validPageRanges(text) {
    if (typeof text !== 'string' || text.length > 4096) return false;
    if (!text.trim()) return true;
    let previousEnd = 0;
    for (const part of text.split(',')) {
      const match = /^\s*([0-9]{1,6})\s*(?:-\s*([0-9]{1,6})\s*)?$/.exec(part);
      if (!match) return false;
      const start = Number(match[1]);
      const end = match[2] === undefined ? start : Number(match[2]);
      if (start < 1 || end < start || start <= previousEnd) return false;
      previousEnd = end;
    }
    return true;
  }

  // The first page a range names, used to pick the numbered sheet in the page-number preview.
  function firstSelectedPage(pageRanges) {
    const match = /^\s*([0-9]{1,6})/.exec(String(pageRanges || ''));
    return match ? Math.max(1, Number(match[1])) : 1;
  }

  function validWatermarkText(text) {
    if (typeof text !== 'string' || text.normalize('NFC') !== text) return false;
    const length = [...text].length;
    return length >= 1 && length <= 200 && !/[\u0000-\u001f\u007f-\u009f]/u.test(text);
  }

  // Template tokens are {n} and {total} only; any other brace content is rejected, never rewritten.
  function validTemplate(template) {
    if (typeof template !== 'string' || !template || template.length > 64) return false;
    if (/[\u0000-\u001f\u007f-\u009f]/u.test(template)) return false;
    const tokens = template.match(/\{[^{}]*\}/g) || [];
    if (template.replace(/\{[^{}]*\}/g, '').match(/[{}]/)) return false;
    return tokens.every(token => token === '{n}' || token === '{total}');
  }

  function romanRange(format) {
    return format === 'roman-lower' || format === 'roman-upper' ? [1, 3999] : [0, 9999];
  }

  function sizeInPoints(value, unit) {
    const factor = unit === 'pt' ? 1 : unit === 'in' ? 72 : 72 / 25.4;
    return Number(value) * factor;
  }

  // Returns a user-facing message for the first invalid input, or null when the request may be sent.
  function validate(key, files, options = state(key)) {
    const op = operation(key);
    const list = Array.from(files || []);
    if (op.images) {
      if (list.length < 1 || list.length > MAX_IMAGE_FILES) return `Choose 1–${MAX_IMAGE_FILES} images (64 MiB total, 40 MP each).`;
      if (list.some(file => !isImageFile(file))) return 'Choose PNG, JPEG, WebP, TIFF, GIF or BMP images.';
    } else if (list.length !== 1 || !isPdfName(list[0]?.name)) {
      return 'Choose one PDF file for this task.';
    }
    const total = list.reduce((sum, file) => sum + (Number(file?.size) || 0), 0);
    if (total > MAX_UPLOAD_BYTES) return 'Selected files exceed the 64 MiB processing limit.';
    switch (key) {
      case 'rotate':
        if (![90, 180, 270].includes(options.angle)) return 'Choose a turn of 90°, 180° or 270°.';
        return validPageRanges(options.pageRanges) ? null : 'Enter pages such as 1-3, 5. Ranges must be ascending and not overlap.';
      case 'images-to-pdf':
        if (!['a4', 'letter', 'legal', 'image'].includes(options.pageSize)) return 'Choose a supported page size.';
        if (!['auto', 'portrait', 'landscape'].includes(options.orientation)) return 'Choose a supported orientation.';
        if (!['contain', 'cover', 'actual'].includes(options.fit)) return 'Choose a supported fit.';
        return Number.isInteger(options.marginMm) && options.marginMm >= 0 && options.marginMm <= 50 ? null : 'Margin must be a whole number from 0 to 50 mm.';
      case 'watermark': {
        if (options.kind === 'image') {
          if (!options.imageFile) return 'Choose a PNG or JPEG image to use as the watermark.';
          if (options.imageFile.size > MAX_WATERMARK_IMAGE_BYTES) return 'The watermark image must be 8 MiB or smaller.';
        } else if (!validWatermarkText(options.text)) {
          return 'Enter 1–200 characters for the watermark text. Control characters are not allowed.';
        }
        if (!Number.isInteger(options.fontSize) || options.fontSize < 8 || options.fontSize > 144) return 'Font size must be from 8 to 144 pt.';
        if (!/^#[0-9A-Fa-f]{6}$/.test(options.color)) return 'Color must be a #RRGGBB value.';
        if (!Number.isInteger(options.opacity) || options.opacity < 5 || options.opacity > 100) return 'Opacity must be from 5 to 100%.';
        if (!Number.isInteger(options.angle) || options.angle < -90 || options.angle > 90) return 'Angle must be from −90 to 90 degrees.';
        if (!WATERMARK_POSITIONS.some(([value]) => value === options.position)) return 'Choose a supported position.';
        return validPageRanges(options.pageRanges) ? null : 'Enter pages such as 1-3, 5. Ranges must be ascending and not overlap.';
      }
      case 'page-numbers': {
        if (!['number', 'page', 'page-of-total', 'roman-lower', 'roman-upper', 'custom'].includes(options.format)) return 'Choose a supported number format.';
        if (options.format === 'custom' && !validTemplate(options.template)) return 'Use a template with {n} and {total} only, up to 64 characters.';
        const [low, high] = romanRange(options.format);
        if (!Number.isInteger(options.start) || options.start < low || options.start > high) {
          return low === 1 ? 'Roman numbers start at 1 and stop at 3,999.' : 'Start must be a whole number from 0 to 9,999.';
        }
        if (!POSITIONS.includes(options.position)) return 'Choose a supported position.';
        if (!Number.isInteger(options.marginMm) || options.marginMm < 0 || options.marginMm > 50) return 'Margin must be from 0 to 50 mm.';
        if (!Number.isInteger(options.fontSize) || options.fontSize < 6 || options.fontSize > 36) return 'Font size must be from 6 to 36 pt.';
        return validPageRanges(options.pageRanges) ? null : 'Enter pages such as 1-3, 5. Ranges must be ascending and not overlap.';
      }
      case 'resize-pages': {
        if (!['scale', 'canvas'].includes(options.mode)) return 'Choose a resize mode.';
        if (!['keep', 'portrait', 'landscape'].includes(options.orientation)) return 'Choose a supported orientation.';
        if (options.preset === 'custom') {
          if (!['mm', 'in', 'pt'].includes(options.unit)) return 'Choose mm, in or pt.';
          const pattern = /^\d{1,6}(\.\d{1,2})?$/;
          if (!pattern.test(options.width) || !pattern.test(options.height)) return 'Enter width and height with at most two decimal places.';
          for (const value of [options.width, options.height]) {
            const points = sizeInPoints(value, options.unit);
            if (points < 72 || points > 14400) return 'Custom sizes must be between 72 and 14,400 pt.';
          }
        }
        if (options.mode === 'canvas' && !ANCHORS.includes(options.anchor)) return 'Choose a supported anchor.';
        return validPageRanges(options.pageRanges) ? null : 'Enter pages such as 1-3, 5. Ranges must be ascending and not overlap.';
      }
      case 'grayscale':
        if (!['vector', 'raster'].includes(options.method)) return 'Choose a supported method.';
        if (options.method === 'raster' && ![150, 300].includes(options.dpi)) return 'Choose 150 or 300 DPI for rasterizing.';
        return null;
      case 'flatten':
        if (!['all', 'forms', 'annotations'].includes(options.scope)) return 'Choose what to flatten.';
        if (options.signed && !options.acknowledge) return 'Confirm the signature warning to flatten this PDF.';
        return null;
      default:
        return null;
    }
  }

  function payloadFor(key, options) {
    switch (key) {
      case 'rotate': return { angle: options.angle, page_ranges: options.pageRanges };
      case 'images-to-pdf': return { page_size: options.pageSize, orientation: options.orientation, fit: options.fit, margin_mm: options.marginMm };
      case 'watermark': {
        const payload = {
          kind: options.kind, font_size: options.fontSize, color: options.color, opacity: options.opacity,
          angle: options.angle, position: options.position, page_ranges: options.pageRanges,
        };
        if (options.kind === 'text') payload.text = options.text;
        return payload;
      }
      case 'page-numbers': {
        const payload = {
          format: options.format, start: options.start, position: options.position, margin_mm: options.marginMm,
          font_size: options.fontSize, page_ranges: options.pageRanges, count_skipped: options.countSkipped,
        };
        if (options.format === 'custom') payload.template = options.template;
        return payload;
      }
      case 'resize-pages': {
        const payload = { preset: options.preset, orientation: options.orientation, mode: options.mode, page_ranges: options.pageRanges };
        if (options.preset === 'custom') Object.assign(payload, { width: options.width, height: options.height, unit: options.unit });
        if (options.mode === 'canvas') payload.anchor = options.anchor;
        return payload;
      }
      case 'grayscale': {
        const payload = { method: options.method };
        if (options.method === 'raster') payload.dpi = options.dpi;
        return payload;
      }
      case 'flatten': return { scope: options.scope, acknowledge_signature_loss: options.acknowledge };
      default: return null;
    }
  }

  // Builds the multipart request for a run. Throws PdfSliceError with user copy when invalid.
  function buildRequest(key, files, options = state(key)) {
    const op = operation(key);
    const message = validate(key, files, options);
    if (message) throw new PdfSliceError(message);
    const form = new FormData();
    const list = Array.from(files);
    if (op.images) list.forEach(file => form.append('files', file, file.name));
    else form.append('file', list[0], list[0].name);
    const payload = payloadFor(key, options);
    if (payload) form.append('options', JSON.stringify(payload));
    if (key === 'watermark' && options.kind === 'image') form.append('image', options.imageFile, options.imageFile.name);
    const name = op.images ? 'images.pdf' : op.result === 'json' ? '' : `${stemOf(list[0].name)}-${op.suffix}.pdf`;
    return { endpoint: op.endpoint, form, name, result: op.result, key };
  }

  // Preview requests reuse the same options and add the page to render (P-164: same engine path).
  // previewPage 0 asks the engine for the first landscape page (watermark sheets).
  function buildPreviewRequest(key, files, options = state(key), previewPage = 1) {
    const op = operation(key);
    if (!op.preview) throw new PdfSliceError('This task has no preview.');
    const message = validate(key, files, options);
    if (message) throw new PdfSliceError(message);
    const list = Array.from(files);
    const form = new FormData();
    form.append('file', list[0], list[0].name);
    const payload = { ...payloadFor(key, options), preview_page: previewPage };
    form.append('options', JSON.stringify(payload));
    if (key === 'watermark' && options.kind === 'image') form.append('image', options.imageFile, options.imageFile.name);
    return { endpoint: op.preview, form, key };
  }

  function integerHeader(value) {
    return /^[0-9]{1,6}$/.test(String(value || '')) ? Number(value) : null;
  }

  function validOverlapList(value) {
    return typeof value === 'string' && value.length <= 256 && /^[0-9,\- ]*$/.test(value) ? value : '';
  }

  // Reads the typed refusal body without echoing parser text. Returns { code, message }.
  async function readRefusal(response) {
    const fallback = { code: '', message: GENERIC_FAILURE };
    try {
      const payload = await response.json();
      const detail = payload?.detail;
      if (typeof detail === 'string' && detail) return { code: '', message: detail };
      if (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message) {
        return { code: typeof detail.code === 'string' ? detail.code : '', message: detail.message };
      }
    } catch (_) { /* Non-JSON failure keeps the generic copy. */ }
    return fallback;
  }

  function sniffPdf(bytes) {
    return new TextDecoder().decode(bytes).includes('%PDF-');
  }

  // Sends a request and validates the response. Returns { kind, blob | report, headers }.
  async function send(request, fetchImpl = fetch, apiUrl = path => path) {
    const response = await fetchImpl(apiUrl(request.endpoint), { method: 'POST', body: request.form });
    if (!response.ok) {
      const refusal = await readRefusal(response);
      throw new PdfSliceError(refusal.message, refusal.code, response.status);
    }
    const contentType = String(response.headers?.get?.('content-type') || '').split(';', 1)[0].trim().toLowerCase();
    if (request.result === 'json') {
      if (contentType !== 'application/json') throw new PdfSliceError('OfficeKit did not return a valid report for this PDF.');
      return { kind: 'json', report: parseInspection(await response.json()), headers: {} };
    }
    if (contentType !== 'application/pdf') throw new PdfSliceError('OfficeKit did not return a valid file for this PDF task.');
    const declared = response.headers?.get?.('content-length');
    if (declared != null && (!/^(0|[1-9][0-9]*)$/.test(declared) || Number(declared) > MAX_OUTPUT_BYTES)) {
      throw new PdfSliceError('OfficeKit returned an invalid or oversized PDF output.');
    }
    const blob = await response.blob();
    if (!(blob instanceof Blob) || blob.size === 0 || blob.size > MAX_OUTPUT_BYTES) {
      throw new PdfSliceError('OfficeKit returned an empty or oversized PDF output.');
    }
    const signature = new Uint8Array(await blob.slice(0, 1024).arrayBuffer());
    if (!sniffPdf(signature)) throw new PdfSliceError('OfficeKit did not return a valid file for this PDF task.');
    const headers = {
      pageCount: integerHeader(response.headers?.get?.('x-officekit-page-count')),
      affectedPages: integerHeader(response.headers?.get?.('x-officekit-affected-pages')),
      flattenedFields: integerHeader(response.headers?.get?.('x-officekit-flattened-fields')),
      flattenedAnnotations: integerHeader(response.headers?.get?.('x-officekit-flattened-annotations')),
      overlapPages: validOverlapList(response.headers?.get?.('x-officekit-overlap-pages') || ''),
      grayscaleMethod: response.headers?.get?.('x-officekit-grayscale-method') || '',
      scale: Number(response.headers?.get?.('x-officekit-scale')),
    };
    return { kind: 'pdf', blob, name: request.name, headers };
  }

  function parseInspection(payload) {
    const valid = payload && typeof payload === 'object' && !Array.isArray(payload)
      && typeof payload.pdf_version === 'string' && Number.isSafeInteger(payload.page_count)
      && Array.isArray(payload.docinfo) && Array.isArray(payload.page_sizes)
      && payload.xmp && typeof payload.xmp === 'object' && Array.isArray(payload.xmp.entries)
      && payload.forms && typeof payload.forms === 'object' && Number.isSafeInteger(payload.forms.fields)
      && typeof payload.forms.signed === 'boolean' && Number.isSafeInteger(payload.annotations)
      && typeof payload.encrypted === 'boolean';
    if (!valid) throw new PdfSliceError('OfficeKit did not return a valid report for this PDF.');
    return payload;
  }

  // Status line for a metadata read: standard fields read against the nine the report lists.
  function reportStatus(report) {
    const standard = report.docinfo.filter(entry => entry.standard);
    const read = standard.filter(entry => entry.present && entry.value !== null && entry.value !== '').length;
    return `${read} of ${STANDARD_FIELD_COUNT} standard fields read · ${STANDARD_FIELD_COUNT - read} not set`;
  }

  // Plain-text copy of a report, for the dock's Copy report button. Values are copied as text only.
  function reportText(report) {
    const lines = [
      'Document information',
      `PDF version: ${report.pdf_version}`,
      `Pages: ${report.page_count}`,
      `Encrypted: ${report.encrypted ? 'Yes' : 'No'}`,
    ];
    for (const entry of report.docinfo) {
      const present = entry.present && entry.value !== null && entry.value !== '';
      lines.push(`${entry.label}: ${present ? `${entry.value}${entry.truncated ? ' … (shortened)' : ''}` : 'Not set'}`);
    }
    lines.push('XMP metadata');
    if (report.xmp.present && report.xmp.entries.length) {
      for (const entry of report.xmp.entries) {
        lines.push(`${entry.name}: ${entry.value}${entry.truncated ? ' … (shortened)' : ''}`);
      }
    } else {
      lines.push(report.xmp.present ? 'No readable XMP entries.' : 'No XMP metadata packet.');
    }
    lines.push('Pages and structure');
    const pageSizes = report.page_sizes.map(group =>
      `${group.count} × ${Math.round(group.width_pt * 25.4 / 72)} × ${Math.round(group.height_pt * 25.4 / 72)} mm${group.rotate ? ` (rotate ${group.rotate})` : ''}`,
    );
    lines.push(`Page sizes: ${pageSizes.length ? pageSizes.join(' · ') + (report.other_count ? ` · ${report.other_count} more` : '') : 'Not available'}`);
    lines.push(`Form fields: ${report.forms.fields}${report.forms.signed ? ' (signed)' : ''}`);
    lines.push(`Signature fields: ${report.forms.signature_fields}`);
    lines.push(`Annotations: ${report.annotations}`);
    lines.push(`XFA forms: ${report.forms.xfa ? 'Yes' : 'No'}`);
    if (report.truncated) lines.push('Some values were shortened to 2,000 characters.');
    lines.push('Nothing is changed or saved.');
    return lines.join('\n');
  }

  async function copyReport(report, clipboard = globalThis.navigator?.clipboard) {
    if (!clipboard || typeof clipboard.writeText !== 'function') {
      throw new PdfSliceError('Copy is not available in this browser. Select the report text instead.');
    }
    await clipboard.writeText(reportText(report));
  }

  // Number of pages a page-numbers run labels: the selected pages of the total (blank = all), clipped to 1..total.
  // Start and count-unnumbered change the printed numbers, not how many pages are labelled, so they are not inputs.
  // The clip and de-duplicate steps match the engine's parser (CR-11). The server refuses those selections, so the
  // branches only matter for the shared table, which keeps the slice and the engine counting the same way.
  function numberedPageCount(pageRanges, total) {
    const text = String(pageRanges || '').trim();
    if (!text) return total;
    const pages = new Set();
    for (const part of text.split(',')) {
      const [from, to = from] = part.trim().split('-').map(Number);
      for (let page = Math.max(1, from); page <= Math.min(total, to); page += 1) pages.add(page);
    }
    return pages.size;
  }

  // The dock status after a PDF result (UX-20, PM-9, owner answer 2026-10-22 "Match the mock (Recommended)").
  // Images to PDF, grayscale and flatten show a bare "Done": the file row already names the output and count.
  // Page numbers shows "Done · N of M pages numbered", N from the selection and M from the route's page count.
  // Rotate, watermark and resize keep their approved forms.
  function doneLine(key, result, options = {}) {
    const headers = result.headers || {};
    const pages = headers.pageCount;
    switch (key) {
      case 'rotate': return headers.affectedPages == null ? 'Done · pages turned' : `Done · ${headers.affectedPages} page${headers.affectedPages === 1 ? '' : 's'} turned`;
      case 'resize-pages': return 'Done · resized copy';
      case 'watermark': return pages == null ? `Done · ${result.name}` : `Done · ${result.name} · ${pages} page${pages === 1 ? '' : 's'}`;
      case 'page-numbers': {
        if (pages == null) return 'Done';
        const numbered = numberedPageCount(options.pageRanges, pages);
        return `Done · ${numbered} of ${pages} ${pages === 1 ? 'page' : 'pages'} numbered`;
      }
      default: return 'Done';
    }
  }

  // The file-limit line the shell shows for a slice task (ARCH-5). Only the images task has one, and its cap
  // comes from MAX_IMAGE_FILES, so index.html keeps no copy of the number.
  function limitFor(key) {
    if (!isOperation(key) || operation(key).images !== true) return null;
    return `Choose 1–${MAX_IMAGE_FILES} images (PNG, JPEG, WebP, TIFF, GIF, BMP) · ${MAX_UPLOAD_BYTES / MiB} MiB total · up to ${MAX_IMAGE_MEGAPIXELS} MP each.`;
  }

  // Selection rules for the slice operations (ARCH-5). Returns { files } for the next selection, or { error }
  // with the user copy. Images append up to the operation's cap; every other task replaces the selection.
  function acceptFiles(key, current, incoming) {
    const op = operation(key);
    const list = Array.from(incoming || []);
    if (!list.length) return { files: Array.from(current || []) };
    const wrongType = op.images
      ? list.some(file => !isImageFile(file) || !file.size)
      : list.some(file => !isPdfName(file?.name) || !file.size);
    if (wrongType) return { error: op.images ? 'Select non-empty PNG, JPEG, WebP, TIFF, GIF or BMP images only.' : 'Select non-empty PDF files only.' };
    if (!op.images && list.length > 1) return { error: 'This task accepts one PDF. Choose a single file.' };
    const combined = op.images ? [...Array.from(current || []), ...list] : list;
    if (combined.length > op.files) return { error: `Images to PDF accepts no more than ${op.files} images.` };
    const totalBytes = combined.reduce((total, file) => total + file.size, 0);
    if (!Number.isSafeInteger(totalBytes) || totalBytes > MAX_UPLOAD_BYTES) return { error: 'Selected PDF files exceed the 64 MiB processing limit.' };
    return { files: combined };
  }

  // Alt+↑ / Alt+↓ on an image row moves it one place (ARCH-5). Returns the new order, or null when nothing moves.
  function keyboardMove(event, files, index) {
    if (!event || !event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return null;
    event.preventDefault();
    const target = index + (event.key === 'ArrowUp' ? -1 : 1);
    const list = Array.from(files || []);
    if (target < 0 || target >= list.length) return null;
    [list[index], list[target]] = [list[target], list[index]];
    return list;
  }

  // Only the images operation reorders rows; the workbench uses this to attach the handler.
  function reordersRows(key) {
    return isOperation(key) && operation(key).images === true;
  }

  // The generic "Output preview" panel is hidden for slice tasks: the engine preview sits in the options (UX-8).
  function workbenchPreviewVisible(key) {
    return !isOperation(key);
  }

  // Runs one operation end to end: build, send, validate. Throws PdfSliceError on any failure.
  async function run(key, files, fetchImpl, apiUrl) {
    const request = buildRequest(key, files);
    return send(request, fetchImpl, apiUrl);
  }

  // Dock actions for a phase. Idle shows the one primary Run; after a result the primary becomes
  // Download (PDF) or Copy report (metadata). No other action is shown, so the screen stays within
  // the Button Limit together with the option controls.
  function dockFor(key, phase = 'idle') {
    const op = operation(key);
    if (phase !== 'result') return ['run'];
    return op.result === 'json' ? ['copy'] : ['download'];
  }

  // ----------------------------------------------------------------- DOM builders (lazy)

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function labelled(text, control) {
    const label = el('label', 'grid gap-1 text-xs font-semibold text-slate-600', text);
    label.append(control);
    return label;
  }

  function select(choices, value, onChange, disabled = false) {
    const node = el('select', 'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800');
    for (const [choice, text] of choices) {
      const option = el('option', '', text);
      option.value = String(choice);
      node.append(option);
    }
    node.value = String(value);
    node.disabled = disabled;
    node.addEventListener('change', () => onChange(node.value));
    return node;
  }

  function numberInput(value, min, max, onInput) {
    const node = el('input', 'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800');
    node.type = 'number';
    node.min = String(min);
    node.max = String(max);
    node.value = String(value);
    node.addEventListener('input', () => onInput(node.value));
    return node;
  }

  function textInput(value, maxLength, onInput) {
    const node = el('input', 'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800');
    node.type = 'text';
    node.maxLength = maxLength;
    node.value = value;
    node.addEventListener('input', () => onInput(node.value));
    return node;
  }

  function note(text) {
    return el('p', 'text-xs leading-5 text-slate-500', text);
  }

  // Secondary disclosure for options that are rarely changed. Closed by default.
  function details(summaryText, children) {
    const node = el('details', 'rounded-lg border border-slate-200 bg-white p-3');
    node.append(el('summary', 'cursor-pointer text-sm font-semibold text-slate-700', summaryText), ...children);
    return node;
  }

  // In-text link button: not counted in the Button Limit (AGENTS.md).
  function linkButton(text, onClick) {
    const button = el('button', 'pdf-slice-link text-sm font-semibold text-indigo-700 underline', text);
    button.type = 'button';
    button.addEventListener('click', onClick);
    return button;
  }

  function segmented(label, choices, value, onPick) {
    const group = el('div', 'inline-flex overflow-hidden rounded-lg border border-slate-300');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', label);
    for (const [choice, text] of choices) {
      const button = el('button', 'px-3 py-2 text-sm', text);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(String(value) === String(choice)));
      button.addEventListener('click', () => onPick(choice));
      group.append(button);
    }
    const wrap = el('div', 'grid gap-1');
    wrap.append(el('span', 'text-xs font-semibold text-slate-600', label), group);
    return wrap;
  }

  // Preview sheets for watermark (page 1 and the first landscape page) and page numbers
  // (pages 1, 2 and the first selected page). Each sheet is a separate engine render.
  function previewSheetsFor(key, options) {
    if (key === 'watermark') return [[1, 'Page 1'], [0, 'First landscape page']];
    const first = firstSelectedPage(options.pageRanges);
    const sheets = [[1, 'Page 1'], [2, 'Page 2']];
    if (first > 2) sheets.push([first, `Page ${first}, numbered`]);
    return sheets;
  }

  function previewCaption(key) {
    return key === 'watermark' ? 'Preview · page 1 and first landscape page' : 'Preview · pages 1, 2 and the first selected page';
  }

  // Renders the options for one operation into `container`. `ctx` supplies the current files and
  // hooks: notify() after any change, schedulePreview() and refreshFacts() for the preview and flatten facts.
  function renderOptions(key, container, ctx) {
    operation(key);
    const options = state(key);
    const change = () => ctx.notify();
    const changeAndPreview = () => { change(); if (ctx.schedulePreview) ctx.schedulePreview(key); };
    const pages = (label = 'Pages (blank = all)') => labelled(label, textInput(options.pageRanges, 4096, value => {
      options.pageRanges = value; changeAndPreview();
    }));
    container.replaceChildren();
    switch (key) {
      case 'rotate':
        container.append(
          labelled('Turn', select([[90, '90° right'], [180, '180°'], [270, '90° left']], options.angle, value => { options.angle = Number(value); change(); })),
          pages(),
        );
        break;
      case 'images-to-pdf':
        container.append(
          labelled('Page size', select([['a4', 'A4'], ['letter', 'Letter'], ['legal', 'Legal'], ['image', 'Same as image']], options.pageSize, value => { options.pageSize = value; change(); })),
          labelled('Orientation', select([['auto', 'Match each image'], ['portrait', 'Portrait'], ['landscape', 'Landscape']], options.orientation, value => { options.orientation = value; change(); })),
          labelled('Fit', select([['contain', 'Fit inside margins'], ['cover', 'Fill page (crop)'], ['actual', 'Actual size (image DPI)']], options.fit, value => { options.fit = value; change(); })),
          labelled('Margin (0–50 mm)', numberInput(options.marginMm, 0, 50, value => { options.marginMm = Number(value); change(); })),
        );
        break;
      case 'metadata-view':
        break;
      case 'watermark': {
        container.append(segmented('Stamp', [['text', 'Text'], ['image', 'Image']], options.kind, value => { options.kind = value; renderOptions(key, container, ctx); changeAndPreview(); }));
        if (options.kind === 'text') {
          container.append(labelled('Text (up to 200 characters)', textInput(options.text, 200, value => { options.text = value; changeAndPreview(); })));
        } else {
          const picker = el('input', 'sr-only');
          picker.type = 'file';
          picker.accept = 'image/png,image/jpeg,.png,.jpg,.jpeg';
          picker.setAttribute('aria-label', 'Watermark image');
          picker.addEventListener('change', () => {
            options.imageFile = picker.files?.[0] || null;
            renderOptions(key, container, ctx);
            changeAndPreview();
          });
          const caption = options.imageFile
            ? `${options.imageFile.name} · ${Math.max(1, Math.round(options.imageFile.size / 1024))} KB chosen.`
            : 'PNG or JPEG, up to 8 MiB. No image chosen.';
          const row = el('div', 'flex flex-wrap items-center gap-3');
          row.append(linkButton('Choose image…', () => picker.click()), note(caption));
          container.append(row, picker);
        }
        container.append(
          labelled('Position', select(WATERMARK_POSITIONS, options.position, value => { options.position = value; changeAndPreview(); })),
          labelled('Opacity (5–100%)', numberInput(options.opacity, 5, 100, value => { options.opacity = Number(value); changeAndPreview(); })),
          details('Details', [
            labelled('Font size (8–144 pt)', numberInput(options.fontSize, 8, 144, value => { options.fontSize = Number(value); changeAndPreview(); })),
            labelled('Angle (−90 to 90°)', numberInput(options.angle, -90, 90, value => { options.angle = Number(value); changeAndPreview(); })),
            labelled('Color (#RRGGBB)', textInput(options.color, 7, value => { options.color = value; changeAndPreview(); })),
            pages(),
          ]),
          note('The watermark is page content, not a security control; it can be edited out.'),
        );
        break;
      }
      case 'page-numbers': {
        container.append(
          labelled('Format', select([['number', '1, 2, 3'], ['page', 'Page 1'], ['page-of-total', 'Page 1 of N'], ['roman-lower', 'i, ii, iii'], ['roman-upper', 'I, II, III'], ['custom', 'Custom…']], options.format, value => { options.format = value; renderOptions(key, container, ctx); changeAndPreview(); })),
        );
        if (options.format === 'custom') container.append(labelled('Template ({n} and {total} only)', textInput(options.template, 64, value => { options.template = value; changeAndPreview(); })));
        container.append(
          labelled('Start at', numberInput(options.start, 0, 9999, value => { options.start = Number(value); changeAndPreview(); })),
          labelled('Position', select([['bottom-center', 'Bottom center'], ['bottom-right', 'Bottom right'], ['bottom-left', 'Bottom left'], ['top-center', 'Top center'], ['top-right', 'Top right'], ['top-left', 'Top left']], options.position, value => { options.position = value; changeAndPreview(); })),
          pages('Number these pages (blank = all)'),
        );
        const count = el('label', 'flex items-center gap-2 text-sm text-slate-700');
        const box = el('input');
        box.type = 'checkbox';
        box.checked = options.countSkipped;
        box.addEventListener('change', () => { options.countSkipped = box.checked; changeAndPreview(); });
        count.append(box, document.createTextNode('Count unnumbered pages'));
        container.append(details('Details', [
          labelled('Margin (0–50 mm)', numberInput(options.marginMm, 0, 50, value => { options.marginMm = Number(value); changeAndPreview(); })),
          labelled('Font size (6–36 pt)', numberInput(options.fontSize, 6, 36, value => { options.fontSize = Number(value); changeAndPreview(); })),
          count,
          note('Example: with pages 1–2 left out and the box unchecked, page 3 shows “1”.'),
        ]));
        break;
      }
      case 'resize-pages':
        container.append(
          labelled('New size', select([['a4', 'A4 (210 × 297 mm)'], ['a5', 'A5'], ['letter', 'Letter'], ['legal', 'Legal'], ['tabloid', 'Tabloid'], ['custom', 'Custom']], options.preset, value => { options.preset = value; renderOptions(key, container, ctx); change(); })),
          labelled('Orientation', select([['keep', 'Keep each page’s'], ['portrait', 'Portrait'], ['landscape', 'Landscape']], options.orientation, value => { options.orientation = value; change(); })),
          segmented('Content', [['scale', 'Scale to fit'], ['canvas', 'Change canvas only']], options.mode, value => { options.mode = value; renderOptions(key, container, ctx); change(); }),
        );
        if (options.preset === 'custom') {
          container.append(
            labelled('Width', textInput(options.width, 9, value => { options.width = value; change(); })),
            labelled('Height', textInput(options.height, 9, value => { options.height = value; change(); })),
            labelled('Unit', select([['mm', 'mm'], ['in', 'in'], ['pt', 'pt']], options.unit, value => { options.unit = value; change(); })),
          );
        }
        if (options.mode === 'canvas') container.append(labelled('Anchor', select(ANCHORS.map(value => [value, value.replace(/-/g, ' ')]), options.anchor, value => { options.anchor = value; change(); })));
        container.append(
          pages(),
          note('Scale to fit shrinks or enlarges content proportionally and centers it. Change canvas keeps content at 100%; trimmed content stays in the file.'),
        );
        break;
      case 'grayscale':
        container.append(
          labelled('Method', select([['vector', 'Keep text and vectors (recommended)'], ['raster', 'Rasterize pages']], options.method, value => { options.method = value; renderOptions(key, container, ctx); change(); })),
          labelled('Rasterize resolution', select([[150, '150 DPI'], [300, '300 DPI']], options.dpi, value => { options.dpi = Number(value); change(); }, options.method !== 'raster')),
          note('Keep text and vectors converts colors and images in place, and text stays selectable. If the file uses color features it cannot convert safely, it stops and offers Rasterize. Rasterize turns each page into a gray image: text is no longer selectable and the file may grow.'),
        );
        break;
      case 'flatten': {
        container.append(labelled('Flatten', select([['all', 'Forms and annotations'], ['forms', 'Forms only'], ['annotations', 'Annotations only']], options.scope, value => { options.scope = value; change(); })));
        container.append(el('div', 'rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900', 'This can’t be undone in the new copy. Fields stop being editable and comments can’t be moved or deleted. Your original stays unchanged.'));
        if (options.signed) {
          const count = Math.max(1, Number(options.signatureFields) || 1);
          const headline = count === 1 ? 'This PDF has a signed signature field' : `This PDF has ${count} signed signature fields`;
          const warning = el('div', 'rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900');
          warning.setAttribute('role', 'alert');
          warning.append(el('strong', '', headline), document.createTextNode(count === 1 ? ' Flattening invalidates the signature; its appearance stays but it no longer verifies.' : ' Flattening invalidates these signatures; their appearance stays but they no longer verify.'));
          const ack = el('label', 'mt-2 flex min-h-10 items-center gap-2 text-sm text-slate-800');
          const box = el('input');
          box.type = 'checkbox';
          box.checked = options.acknowledge;
          box.addEventListener('change', () => { options.acknowledge = box.checked; change(); });
          ack.append(box, document.createTextNode('I understand the signature will no longer be valid'));
          warning.append(ack);
          container.append(warning);
        }
        if (ctx.refreshFacts) ctx.refreshFacts(key);
        break;
      }
      default:
        break;
    }
    if (key === 'watermark' || key === 'page-numbers') {
      const sheets = el('div', 'pdf-slice-sheets flex flex-wrap items-end gap-3');
      sheets.id = 'pdf-slice-preview';
      container.append(el('p', 'text-xs font-semibold text-slate-600', previewCaption(key)), sheets);
    }
  }

  // Facts line for the file row (flatten only): empty until a file's facts are known.
  function factsLine(key) {
    if (key !== 'flatten') return '';
    const options = state('flatten');
    if (!options.factsKey) return '';
    return `${options.fields} field${options.fields === 1 ? '' : 's'} · ${options.annotations} annotation${options.annotations === 1 ? '' : 's'}`;
  }

  function renderJsonReport(report, host, ctx) {
    const table = (rows, headers) => {
      const wrap = el('div', 'overflow-x-auto');
      const node = el('table', 'w-full text-sm');
      if (headers) {
        const head = el('tr');
        for (const label of headers) head.append(el('th', 'text-left text-xs uppercase text-slate-500 p-1', label));
        node.append(head);
      }
      for (const [left, right, absent] of rows) {
        const row = el('tr');
        row.append(el('td', 'p-1 align-top text-slate-600', left));
        row.append(el('td', absent ? 'p-1 align-top italic text-slate-500' : 'p-1 align-top break-all text-slate-800', right));
        node.append(row);
      }
      wrap.append(node);
      return wrap;
    };
    host.replaceChildren();
    host.append(el('h3', 'text-sm font-bold text-slate-800', 'Document information'));
    const docRows = report.docinfo.map(entry => {
      const present = entry.present && entry.value !== null && entry.value !== '';
      const value = present ? `${entry.value}${entry.truncated ? ' … (shortened)' : ''}` : 'Not set';
      return [entry.label, value, !present];
    });
    host.append(table(docRows, ['Field', 'Value']));
    host.append(el('h3', 'mt-4 text-sm font-bold text-slate-800', 'XMP metadata'));
    if (report.xmp.present && report.xmp.entries.length) {
      host.append(table(report.xmp.entries.map(entry => [entry.name, `${entry.value}${entry.truncated ? ' … (shortened)' : ''}`, false])));
    } else {
      host.append(note('No XMP metadata packet.'));
    }
    host.append(el('h3', 'mt-4 text-sm font-bold text-slate-800', 'Pages and structure'));
    const sizes = report.page_sizes.map(group => `${group.count} × ${Math.round(group.width_pt * 25.4 / 72)} × ${Math.round(group.height_pt * 25.4 / 72)} mm${group.rotate ? ` (rotate ${group.rotate})` : ''}`);
    host.append(table([
      ['Pages', String(report.page_count), false],
      ['PDF version', report.pdf_version, false],
      ['Page sizes', sizes.length ? sizes.join(' · ') + (report.other_count ? ` · ${report.other_count} more` : '') : 'Not available', !sizes.length],
      ['Form fields', `${report.forms.fields}${report.forms.signed ? ' (signed)' : ''}`, false],
      ['Annotations', String(report.annotations), false],
      ['XFA forms', report.forms.xfa ? 'Yes' : 'No', false],
      ['Encrypted', report.encrypted ? 'Yes' : 'No', false],
    ]));
    host.append(note(report.truncated ? 'Some values were shortened to 2,000 characters. Nothing is changed or saved.' : 'Nothing is changed or saved.'));
    if (ctx && typeof ctx.onRemoveMetadata === 'function') {
      host.append(linkButton('Remove metadata…', () => ctx.onRemoveMetadata()));
    }
  }

  const previewState = { timer: null, controller: null, urls: [] };

  function clearPreviewUrls() {
    for (const url of previewState.urls) URL.revokeObjectURL(url);
    previewState.urls = [];
  }

  function sheetFigure(blob, caption) {
    const url = URL.createObjectURL(blob);
    previewState.urls.push(url);
    const figure = el('figure', 'pdf-slice-sheet m-0 grid gap-1');
    const image = el('img', 'max-h-72 rounded-lg border border-slate-200 bg-white');
    image.alt = `Engine preview: ${caption}`;
    image.src = url;
    figure.append(image, el('figcaption', 'text-xs text-slate-600', caption));
    return figure;
  }

  // Debounced preview for watermark and page numbers. Stale responses are aborted, never shown.
  // A sheet the engine refuses (for example no landscape page) is skipped; the others still show.
  function schedulePreview(key, files, ctx, fetchImpl = fetch, apiUrl = path => path) {
    if (!OPERATIONS[key] || !OPERATIONS[key].preview) return;
    window.clearTimeout(previewState.timer);
    previewState.controller?.abort();
    previewState.timer = window.setTimeout(async () => {
      const host = document.getElementById('pdf-slice-preview');
      if (!host) return;
      const message = validate(key, files);
      if (message) { clearPreviewUrls(); host.replaceChildren(); return; }
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      previewState.controller = controller;
      try {
        const options = state(key);
        const pageRanges = options.pageRanges;
        let rangeRefusalShown = false;
        const sheets = previewSheetsFor(key, options);
        const results = await Promise.all(sheets.map(async ([page, caption]) => {
          const request = buildPreviewRequest(key, files, options, page);
          const response = await fetchImpl(apiUrl(request.endpoint), { method: 'POST', body: request.form, signal: controller?.signal });
          if (!response.ok) {
            const refusal = await readRefusal(response);
            if (refusal.code === 'page_selection_out_of_range' && state(key).pageRanges === pageRanges && showPageRangeError(refusal.message)) {
              rangeRefusalShown = true;
              const runButton = document.getElementById('pdf-workbench-run');
              if (runButton) runButton.disabled = true;
              const status = document.getElementById('pdf-workbench-status');
              if (status) {
                status.textContent = 'Correct the page selection to continue.';
                status.setAttribute('role', 'alert');
                status.setAttribute('data-officekit-no-bug-report', '');
              }
            }
            return null;
          }
          const contentType = String(response.headers?.get?.('content-type') || '').split(';', 1)[0].trim().toLowerCase();
          const declared = Number(response.headers?.get?.('content-length') || 0);
          const blob = await response.blob();
          if (contentType !== 'image/png' || blob.size === 0 || blob.size > MAX_PREVIEW_BYTES || (declared && declared > MAX_PREVIEW_BYTES)) return null;
          return { blob, caption, overlap: validOverlapList(response.headers?.get?.('x-officekit-overlap-pages') || '') };
        }));
        const shown = results.filter(Boolean);
        clearPreviewUrls();
        host.replaceChildren();
        if (!shown.length && !rangeRefusalShown) {
          host.append(el('p', 'text-sm text-rose-700', 'The preview could not be created. Check the file and settings.'));
        } else {
          host.append(...shown.map(result => sheetFigure(result.blob, result.caption)));
        }
        const overlap = shown.map(result => result.overlap).find(Boolean);
        if (overlap) host.append(el('p', 'text-xs text-amber-800', `Content may sit under the number on pages ${overlap}. Move the number or create anyway.`));
      } catch (error) {
        if (error?.name === 'AbortError') return;
        host.replaceChildren(el('p', 'text-sm text-rose-700', 'The preview could not be created. Check the file and settings.'));
      } finally {
        if (ctx && typeof ctx.previewDone === 'function') ctx.previewDone(key);
      }
    }, PREVIEW_DELAY_MS);
  }

  // Shows a typed refusal next to the options. Codes are the only thing read from the body.
  function showError(key, error, ctx) {
    const host = document.getElementById('pdf-slice-message');
    if (!host) return;
    host.replaceChildren();
    const box = el('div', 'rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900');
    box.setAttribute('role', 'alert');
    if (key === 'metadata-view' && Number(error?.status) === 422) box.setAttribute('data-officekit-no-bug-report', '');
    box.textContent = error?.message || GENERIC_FAILURE;
    host.append(box);
    if (error?.code === 'grayscale_needs_raster' && ctx && typeof ctx.onRasterize === 'function') {
      const button = el('button', 'mt-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800', 'Rasterize instead');
      button.type = 'button';
      button.addEventListener('click', () => ctx.onRasterize());
      box.append(button);
    }
    if (error?.code === 'signature_ack_required' && ctx && typeof ctx.onAcknowledgeNeeded === 'function') ctx.onAcknowledgeNeeded();
  }

  function clearMessage() {
    const host = document.getElementById('pdf-slice-message');
    if (host) host.replaceChildren();
  }

  // Forgets the file facts for flatten (for example after the file list is emptied). Scope is kept.
  function clearFlattenFacts() {
    Object.assign(state('flatten'), { factsKey: '', fields: 0, annotations: 0, signed: false, signatureFields: 0, acknowledge: false });
  }

  // Facts for flatten (field counts and whether a signed field exists). Resolves true only when
  // the facts changed, so the caller re-renders once; stale results are dropped.
  async function loadFlattenFacts(files, fetchImpl = fetch, apiUrl = path => path) {
    const options = state('flatten');
    const file = Array.from(files || [])[0];
    if (!file || !isPdfName(file.name)) return false;
    const factsKey = `${file.name}:${file.size}`;
    if (options.factsKey === factsKey) return false;
    const form = new FormData();
    form.append('file', file, file.name);
    const response = await fetchImpl(apiUrl('/api/pdf/inspections'), { method: 'POST', body: form });
    if (!response.ok) return false;
    const report = parseInspection(await response.json());
    if (states.flatten !== options) return false;
    options.factsKey = factsKey;
    options.fields = report.forms.fields;
    options.annotations = report.annotations;
    options.signed = report.forms.signed;
    options.signatureFields = Number(report.forms.signature_fields) || 0;
    options.acknowledge = false;
    return true;
  }

  // ----------------------------------------------------------------- workbench glue
  // The shell is built by index.html for each call and carries the current tool, files and hooks:
  //   tool, files, url(path), fetch, changed(), rerender(), refresh(), openTool(tool), status(msg, isError),
  //   busy(on), clearOutput(), setOutput(blob, name), phase('idle'|'result'), report(report).

  function contextFor(shell) {
    return {
      notify: () => shell.changed(),
      schedulePreview: key => schedulePreview(key, shell.files, contextFor(shell), shell.fetch, shell.url),
      refreshFacts: () => {
        if (!shell.files.length) { clearFlattenFacts(); return; }
        loadFlattenFacts(shell.files, shell.fetch, shell.url).then(changed => {
          if (changed) shell.rerender();
        }).catch(() => { /* Facts are advisory; the server still checks signed fields. */ });
      },
      onRasterize: () => { state('grayscale').method = 'raster'; shell.rerender(); },
      onAcknowledgeNeeded: () => {
        // The server found a signed field the client did not know about: show the confirmation now.
        Object.assign(state('flatten'), { signed: true, acknowledge: false });
        shell.rerender();
      },
      onRemoveMetadata: () => shell.openTool('metadata'),
      previewDone: () => {},
    };
  }

  // Renders the options for the shell's tool and starts the preview where the tool has one.
  function renderWorkbench(shell, container) {
    clearMessage();
    if (!shell.files.length) document.getElementById('pdf-slice-report')?.replaceChildren();
    renderOptions(shell.tool, container, contextFor(shell));
    if (OPERATIONS[shell.tool].preview) schedulePreview(shell.tool, shell.files, contextFor(shell), shell.fetch, shell.url);
  }

  // Shows the inline validation reason under the options, and returns true when Run must stay disabled.
  // The note never replaces a server message, and stays empty until files are chosen.
  function syncSelection(shell) {
    const message = validate(shell.tool, shell.files);
    const host = document.getElementById('pdf-slice-validation');
    if (host) host.textContent = message && shell.files.length ? message : '';
    return Boolean(message);
  }

  // Runs the operation for the shell. Success moves the dock to its result phase; failure keeps the reason.
  async function runWorkbench(shell) {
    const tool = shell.tool;
    shell.busy(true);
    shell.clearOutput();
    clearMessage();
    shell.status('Processing the selected PDF locally…');
    try {
      const result = await run(tool, shell.files, shell.fetch, shell.url);
      if (result.kind === 'json') {
        renderJsonReport(result.report, document.getElementById('pdf-slice-report'), contextFor(shell));
        shell.report(result.report);
        shell.phase('result');
        shell.status(reportStatus(result.report));
      } else {
        shell.setOutput(result.blob, result.name);
        shell.phase('result');
        shell.status(doneLine(tool, result, { pageRanges: state(tool).pageRanges }));
      }
    } catch (error) {
      showError(tool, error, contextFor(shell));
      const recoverableMetadataInput = tool === 'metadata-view' && Number(error?.status) === 422;
      shell.status(error.message || GENERIC_FAILURE, true, !recoverableMetadataInput);
    } finally {
      shell.busy(false);
      shell.refresh();
    }
  }

  window.OfficeKitPdfSlice = Object.freeze({
    imageAccept: 'image/png,image/jpeg,image/webp,image/tiff,image/gif,image/bmp,.png,.jpg,.jpeg,.webp,.tif,.tiff,.gif,.bmp',
    isOperation,
    operations: () => Object.keys(OPERATIONS),
    toolId: key => operation(key).toolId,
    state,
    reset,
    validate,
    buildRequest,
    buildPreviewRequest,
    send,
    run,
    doneLine,
    numberedPageCount,
    parseInspection,
    readRefusal,
    validPageRanges,
    validTemplate,
    dockFor,
    acceptFiles,
    keyboardMove,
    reordersRows,
    workbenchPreviewVisible,
    limitFor,
    factsLine,
    reportStatus,
    reportText,
    copyReport,
    renderOptions,
    renderJsonReport,
    renderWorkbench,
    syncSelection,
    runWorkbench,
    schedulePreview,
    showError,
    clearMessage,
    loadFlattenFacts,
    clearFlattenFacts,
    stemOf,
    isImageFile,
    PdfSliceError,
  });
})();
