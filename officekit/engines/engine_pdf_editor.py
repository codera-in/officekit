"""Immutable local PDF editing. All PDFium calls are serialized in this boundary.

Geometry is unrotated PDF points in the page's native coordinate system. Crop
and rotation metadata are returned explicitly; callers must not use screen pixels.
"""
import base64
import ctypes
import hashlib
import io
import math
import threading
from itertools import islice
import time
from contextlib import closing

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject, DecodedStreamObject
from reportlab.pdfgen.canvas import Canvas

from .pdf_editor_models import Operation, RevisionCreate
from . import engine_rapidocr
from .engine_ocr import ImageTextRecognitionUnavailable

MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_RENDER_PIXELS = 8_000_000
_LOCK = threading.RLock()


class PdfEditorError(ValueError):
    def __init__(self, message='This PDF could not be processed.', status_code=422):
        super().__init__(message)
        self.public_message = message
        self.status_code = status_code

    def __reduce__(self):
        return type(self), (self.public_message, self.status_code)


def _open(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_PDF_BYTES:
        raise PdfEditorError('PDF input must be between 1 byte and 64 MiB.', 413)
    try:
        document = pdfium.PdfDocument(data)
        if not 1 <= len(document) <= 2000:
            document.close()
            raise PdfEditorError('PDF page count exceeds the supported limit.', 413)
        return document
    except PdfEditorError:
        raise
    except Exception:
        raise PdfEditorError('Unable to open PDF. Encrypted documents must be decrypted first.') from None


def _page(document, number):
    if type(number) is not int or not 1 <= number <= len(document):
        raise PdfEditorError('Page is outside this document.')
    return document[number - 1]


def inspect_document(data):
    with _LOCK, _open(data) as document:
        pages = []
        for number in range(1, len(document) + 1):
            with closing(_page(document, number)) as page:
                crop = list(page.get_cropbox())
                pages.append({'page': number, 'width': crop[2]-crop[0], 'height': crop[3]-crop[1],
                              'render_width': page.get_width(), 'render_height': page.get_height(),
                              'crop_box': crop, 'rotation': page.get_rotation()})
        return {'page_count': len(document), 'pages': pages,
                'warnings': ['General editing creates a new PDF and does not preserve existing signature validity.']}


def render_page(data, page, scale=1):
    if isinstance(scale, bool) or not isinstance(scale, (float, int)) or not math.isfinite(scale) or not .1 <= scale <= 4:
        raise PdfEditorError('Render scale must be between 0.1 and 4.')
    with _LOCK, _open(data) as document, closing(_page(document, page)) as selected:
        if math.ceil(selected.get_width() * scale) * math.ceil(selected.get_height() * scale) > MAX_RENDER_PIXELS:
            raise PdfEditorError('Preview exceeds 8 million pixels.', 413)
        bitmap = selected.render(scale=scale)
        try:
            output = io.BytesIO()
            bitmap.to_pil().save(output, format='PNG')
        finally:
            bitmap.close()
        if output.tell() > 16 * 1024 * 1024:
            raise PdfEditorError('Preview exceeds 16 MiB.', 413)
        return output.getvalue()


def _identity(data, revision, page, index):
    return hashlib.sha256(data).hexdigest()[:20] + f':{revision}:{page}:{index}'


def list_objects(data, page, revision=0, offset=0, limit=100):
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 200:
        raise PdfEditorError('Invalid object pagination.')
    with _LOCK, _open(data) as document, closing(_page(document, page)) as selected:
        objects = []
        with closing(selected.get_textpage()) as textpage:
            for index, obj in enumerate(selected.get_objects(max_depth=0)):
                if index >= 10000:
                    raise PdfEditorError('Page object count exceeds the editing limit.', 413)
                kind = {raw.FPDF_PAGEOBJ_TEXT: 'text', raw.FPDF_PAGEOBJ_IMAGE: 'image'}.get(obj.type, 'unsupported')
                item = {'id': _identity(data, revision, page, index), 'kind': kind,
                        'rect': list(obj.get_bounds()), 'editable': kind in ('text', 'image'),
                        'reason': 'Explicit replacement font required.' if kind == 'text' else None}
                left, bottom, right, top = item['rect']
                item.update(page=page, x=left, y=bottom, width=right-left, height=top-bottom)
                if kind == 'text':
                    size = raw.FPDFTextObj_GetText(obj, textpage, None, 0)
                    if size > 200002:
                        item.update(editable=False, reason='Text object exceeds editing limit.')
                    else:
                        buffer = (ctypes.c_ushort * (size // 2 + 1))()
                        raw.FPDFTextObj_GetText(obj, textpage, buffer, size)
                        item['text'] = bytes(buffer)[:max(0, size - 2)].decode('utf-16-le', errors='replace')
                objects.append(item)
        reader = PdfReader(io.BytesIO(data))
        for index, ref in enumerate(reader.pages[page-1].get('/Annots', [])):
            annotation = ref.get_object()
            if '/Rect' not in annotation:
                continue
            left, bottom, right, top = map(float, annotation['/Rect'])
            subtype = str(annotation.get('/Subtype'))
            points = annotation.get('/L', []) if subtype == '/Line' else (annotation.get('/InkList', [[]])[0] if subtype == '/Ink' else [])
            color = annotation.get('/C', [0, 0, 0])
            item = {'id': _identity(data, revision, page, f'a{index}'), 'kind': 'annotation',
                'page': page, 'rect': [left, bottom, right, top], 'x': left, 'y': bottom,
                'width': right-left, 'height': top-bottom, 'text': str(annotation.get('/Contents', '')),
                'annotation_type': {'/Highlight': 'highlight', '/Square': 'rectangle', '/Circle': 'circle',
                    '/Ink': 'freehand', '/Line': 'line', '/FreeText': 'text'}.get(subtype, 'unsupported'),
                'editable': str(annotation.get('/Subtype')) in ('/Highlight', '/Square', '/Circle', '/Ink', '/Line', '/FreeText'),
                'points': [[float(points[i]), float(points[i+1])] for i in range(0, len(points)-1, 2)],
                'color': '#'+''.join(f'{max(0,min(255,round(float(c)*255))):02x}' for c in color[:3]),
                'outer_color': str(annotation.get('/OfficeKitOuterColor', '#ffffff')),
                'outer_width': float(annotation.get('/OfficeKitOuterWidth', 0)),
                'stroke_width': float(annotation.get('/OfficeKitStrokeWidth', 2)),
                'font_size': float(annotation.get('/OfficeKitFontSize', 12)),
                'font': str(annotation.get('/OfficeKitFont', 'Helvetica')), 'reason': None}
            if subtype == '/Line' and '/OpenArrow' in annotation.get('/LE', []):
                item['annotation_type'] = 'arrow'
            if annotation.get('/IT') == '/FreeTextCallout':
                item['annotation_type'] = 'callout'
            objects.append(item)
        return {'revision': revision, 'page': page, 'objects': objects[offset:offset+limit], 'offset': offset,
                'has_more': offset + limit < len(objects)}


def _rect(selected, rect):
    if rect is None:
        raise PdfEditorError('A placement rectangle is required.')
    left, bottom, right, top = selected.get_cropbox()
    if rect[0] < left or rect[1] < bottom or rect[2] > right or rect[3] > top:
        raise PdfEditorError('Placement is outside the page crop box.')
    return rect


def _text(document, selected, op, rect, invisible=False):
    if any(ord(char) > 255 for char in op.text):
        raise PdfEditorError('This replacement font cannot encode the text. Choose supported Latin text.')
    obj = raw.FPDFPageObj_NewTextObj(document, op.font.encode('ascii'), op.font_size)
    if not obj:
        raise PdfEditorError('Replacement font is unavailable.', 503)
    owned = pdfium.PdfObject(obj)
    encoded = (op.text + '\0').encode('utf-16-le')
    buffer = (ctypes.c_ushort * (len(encoded) // 2)).from_buffer_copy(encoded)
    if not raw.FPDFText_SetText(owned, buffer):
        owned.close()
        raise PdfEditorError('Text could not be encoded with the replacement font.')
    color = tuple(int(op.color[i:i + 2], 16) for i in (1, 3, 5))
    raw.FPDFPageObj_SetFillColor(owned, *color, 255)
    if invisible:
        raw.FPDFTextObj_SetTextRenderMode(owned, 3)
    selected.insert_obj(owned)
    original = owned.get_bounds()
    raw.FPDFPageObj_Transform(owned, 1, 0, 0, 1, rect[0]-original[0], rect[1]-original[1])
    bounds = owned.get_bounds()
    if bounds[2] > rect[2] + .1 or bounds[3] > rect[3] + .1:
        raise PdfEditorError('Replacement text does not fit the selected region.')


def _image(document, selected, op, rect):
    try:
        data = base64.b64decode(op.image_base64 or '', validate=True)
        if not data or len(data) > 16 * 1024 * 1024:
            raise ValueError()
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_RENDER_PIXELS:
            raise ValueError()
        image = image.convert('RGBA')
    except Exception:
        raise PdfEditorError('Image must be a supported image under 16 MiB and 8 million pixels.') from None
    bitmap = pdfium.PdfBitmap.from_pil(image)
    try:
        obj = pdfium.PdfImage.new(document)
        obj.set_bitmap(bitmap)
        obj.set_matrix(pdfium.PdfMatrix(rect[2] - rect[0], 0, 0, rect[3] - rect[1], rect[0], rect[1]))
        selected.insert_obj(obj)
    finally:
        bitmap.close()


def _annotations(data, operations, source_data=None, revision=0):
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    removed = {}
    for op in operations:
        if op.object_id:
            annots = writer.pages[op.page-1].get('/Annots', [])
            original = PdfReader(io.BytesIO(source_data or data)).pages[op.page-1].get('/Annots', [])
            index = next((i for i in range(len(original)) if _identity(source_data or data, revision, op.page, f'a{i}') == op.object_id), None)
            gone = removed.setdefault(op.page, set())
            if index is None or index in gone:
                raise PdfEditorError('Annotation no longer belongs to this revision.', 409)
            del annots[index-sum(i < index for i in gone)]
            gone.add(index)
            if op.action == 'delete':
                continue
        rect = op.rect
        subtype = {'highlight': '/Highlight', 'rectangle': '/Square', 'circle': '/Circle',
                   'text': '/FreeText', 'callout': '/FreeText', 'freehand': '/Ink', 'line': '/Line', 'arrow': '/Line'}.get(op.annotation_type)
        if subtype is None:
            raise PdfEditorError('Signature appearances require an image operation.')
        arr = lambda values: ArrayObject([FloatObject(value) for value in values])
        annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'),
            NameObject('/Subtype'): NameObject(subtype), NameObject('/Rect'): arr(rect),
            NameObject('/C'): arr([int(op.color[i:i + 2], 16) / 255 for i in (1, 3, 5)]),
            NameObject('/Contents'): TextStringObject(op.text), NameObject('/F'): FloatObject(4)})
        annotation.update({NameObject('/OfficeKitOuterColor'): TextStringObject(op.outer_color),
            NameObject('/OfficeKitOuterWidth'): FloatObject(op.outer_width),
            NameObject('/OfficeKitStrokeWidth'): FloatObject(op.stroke_width),
            NameObject('/OfficeKitFontSize'): FloatObject(op.font_size),
            NameObject('/OfficeKitFont'): TextStringObject(op.font)})
        if subtype == '/Highlight':
            annotation[NameObject('/QuadPoints')] = arr([rect[0], rect[3], rect[2], rect[3], rect[0], rect[1], rect[2], rect[1]])
            annotation[NameObject('/CA')] = FloatObject(.3)
        if subtype == '/FreeText':
            annotation[NameObject('/DA')] = TextStringObject(f'/Helv {op.font_size} Tf 0 0 0 rg')
            if op.annotation_type == 'callout':
                annotation[NameObject('/IT')] = NameObject('/FreeTextCallout')
                annotation[NameObject('/CL')] = arr([rect[0], rect[1], rect[0]+10, rect[1]+10])
        if op.annotation_type == 'arrow':
            annotation[NameObject('/LE')] = ArrayObject([NameObject('/None'), NameObject('/OpenArrow')])
        if subtype in ('/Ink', '/Line'):
            if len(op.points) < 2:
                raise PdfEditorError('At least two annotation points are required.')
            flat = [coordinate for point in op.points for coordinate in point]
            annotation[NameObject('/InkList') if subtype == '/Ink' else NameObject('/L')] = ArrayObject([arr(flat)]) if subtype == '/Ink' else arr(flat[:4])
        appearance_bytes = io.BytesIO()
        width, height = rect[2]-rect[0], rect[3]-rect[1]
        canvas = Canvas(appearance_bytes, pagesize=(width, height))
        def paint(color, line_width):
            rgb = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
            canvas.setStrokeColorRGB(*rgb)
            canvas.setFillColorRGB(*rgb)
            canvas.setLineWidth(line_width)
            inset = max(line_width/2, .1)
            if subtype == '/FreeText':
                canvas.setFont(op.font, op.font_size)
                canvas.drawString(inset, inset, op.text)
                if op.annotation_type == 'callout':
                    canvas.rect(inset, inset, max(0, width-2*inset), max(0, height-2*inset))
            elif subtype == '/Highlight':
                canvas.setFillAlpha(.3)
                canvas.rect(0, 0, width, height, fill=1, stroke=0)
            elif subtype == '/Square':
                canvas.rect(inset, inset, max(0, width-2*inset), max(0, height-2*inset), fill=0, stroke=1)
            elif subtype == '/Circle':
                canvas.ellipse(inset, inset, width-inset, height-inset, fill=0, stroke=1)
            else:
                path = canvas.beginPath()
                path.moveTo(op.points[0][0]-rect[0], op.points[0][1]-rect[1])
                for point in op.points[1:] if subtype == '/Ink' else op.points[1:2]:
                    path.lineTo(point[0]-rect[0], point[1]-rect[1])
                canvas.drawPath(path)
                if op.annotation_type == 'arrow':
                    start, end = op.points[:2]
                    angle = math.atan2(end[1]-start[1], end[0]-start[0])
                    for delta in (-.45, .45):
                        canvas.line(end[0]-rect[0], end[1]-rect[1],
                            end[0]-rect[0]-10*math.cos(angle+delta),
                            end[1]-rect[1]-10*math.sin(angle+delta))
        if op.outer_width and subtype != '/Highlight':
            paint(op.outer_color, op.stroke_width+2*op.outer_width)
        paint(op.color, op.stroke_width)
        canvas.save()
        appearance_page = PdfReader(io.BytesIO(appearance_bytes.getvalue())).pages[0]
        appearance = DecodedStreamObject()
        appearance.set_data(appearance_page.get_contents().get_data())
        appearance.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                           NameObject('/BBox'): arr([0, 0, width, height]),
                           NameObject('/Resources'): appearance_page['/Resources'].clone(writer)})
        annotation[NameObject('/AP')] = DictionaryObject({NameObject('/N'): writer._add_object(appearance)})
        writer.add_annotation(op.page - 1, annotation)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _reconstruct(document, selected, operations):
    """Explicit reviewed raster reconstruction; never a secure-redaction claim."""
    left, bottom, right, top = selected.get_cropbox()
    if selected.get_rotation() or left or bottom:
        raise PdfEditorError('OCR reconstruction requires an unrotated page with a zero-origin crop box.', 503)
    if math.ceil(right * 2) * math.ceil(top * 2) > MAX_RENDER_PIXELS:
        raise PdfEditorError('OCR reconstruction exceeds the pixel limit.', 413)
    bitmap = selected.render(scale=2, draw_annots=False)
    try:
        image = bitmap.to_pil().copy().convert('RGB')
    finally:
        bitmap.close()
    painter = ImageDraw.Draw(image)
    for op in operations:
        x0, y0, x1, y1 = _rect(selected, op.rect)
        painter.rectangle((math.floor(x0 * 2), math.floor((top-y1) * 2),
                           math.ceil(x1 * 2), math.ceil((top-y0) * 2)), fill='white')
    # Remove original objects before embedding freshly encoded pixels. Shared
    # image resources are not changed: this derived page owns its new image.
    for obj in list(selected.get_objects(max_depth=0)):
        selected.remove_obj(obj)
        obj.close()
    encoded = io.BytesIO()
    image.save(encoded, format='PNG')
    operation = Operation(kind='add_image', page=operations[0].page,
        image_base64=base64.b64encode(encoded.getvalue()).decode('ascii'))
    _image(document, selected, operation, [left, bottom, right, top])
    selected.gen_content()


def apply_operations(data, operations, revision=0):
    try:
        request = RevisionCreate(base_revision=revision, operations=[
            op if isinstance(op, Operation) else Operation.model_validate(op) for op in operations])
    except ValueError:
        raise PdfEditorError('Invalid PDF editing operations.') from None
    annotations = []
    removed_indices = {}
    with _LOCK, _open(data) as document:
        reconstruct_pages = {op.page for op in request.operations if op.kind == 'apply_ocr' and op.ocr_mode == 'reconstruction'}
        for number in reconstruct_pages:
            if any(op.page == number and op.kind in ('replace_text', 'image_change') for op in request.operations):
                raise PdfEditorError('Object editing and OCR reconstruction must use separate revisions.')
            with closing(_page(document, number)) as selected:
                _reconstruct(document, selected, [op for op in request.operations
                    if op.page == number and op.kind == 'apply_ocr' and op.ocr_mode == 'reconstruction'])
        for op in request.operations:
            with closing(_page(document, op.page)) as selected:
                if op.kind in ('replace_text', 'image_change'):
                    candidates = list(islice(selected.get_objects(max_depth=0), 10001))
                    if len(candidates) > 10000:
                        raise PdfEditorError('Page object count exceeds the editing limit.', 413)
                    suffix = (op.object_id or '').rsplit(':', 1)[-1]
                    original_index = int(suffix) if suffix.isascii() and suffix.isdigit() and len(suffix) <= 5 else None
                    removed = removed_indices.setdefault(op.page, set())
                    if (original_index is None or original_index in removed
                            or original_index >= len(candidates) + len(removed)
                            or _identity(data, revision, op.page, original_index) != op.object_id):
                        raise PdfEditorError('Object no longer belongs to this revision.', 409)
                    index = original_index - sum(i < original_index for i in removed)
                    obj = candidates[index]
                    expected = raw.FPDF_PAGEOBJ_TEXT if op.kind == 'replace_text' else raw.FPDF_PAGEOBJ_IMAGE
                    if obj.type != expected:
                        raise PdfEditorError('This object does not support the requested edit.')
                    rect = _rect(selected, op.rect or list(obj.get_bounds()))
                    if op.kind == 'replace_text':
                        _text(document, selected, op, rect)
                    elif op.action == 'move':
                        left, bottom, right, top = obj.get_bounds()
                        if right <= left or top <= bottom:
                            raise PdfEditorError('Image transform has no editable area.')
                        sx, sy = (rect[2] - rect[0]) / (right - left), (rect[3] - rect[1]) / (top - bottom)
                        a, b, c, d, e, f = obj.get_matrix().get()
                        obj.set_matrix(pdfium.PdfMatrix(a*sx, b*sy, c*sx, d*sy,
                            rect[0]+(e-left)*sx, rect[1]+(f-bottom)*sy))
                        selected.gen_content()
                        continue
                    elif op.action == 'rotate':
                        x, y, right, top = rect
                        width, height = right-x, top-y
                        a, b, c, d, _, _ = obj.get_matrix().get()
                        angle = math.degrees(math.atan2(b, a)) % 360
                        if min(abs(angle-target) for target in (0, 90, 180, 270, 360)) > .01:
                            raise PdfEditorError('Rotation requires an image aligned to quarter turns.', 503)
                        rotation = (round(angle/90)*90+op.rotation_delta) % 360
                        matrices = {0: (width, 0, 0, height, x, y), 90: (0, height, -width, 0, right, y),
                                    180: (-width, 0, 0, -height, right, top),
                                    270: (0, -height, width, 0, x, top)}
                        obj.set_matrix(pdfium.PdfMatrix(*matrices[rotation]))
                        selected.gen_content()
                        continue
                    elif op.action == 'crop':
                        pixel_width, pixel_height = obj.get_px_size()
                        if pixel_width < 1 or pixel_height < 1 or pixel_width * pixel_height > MAX_RENDER_PIXELS:
                            raise PdfEditorError('Source image exceeds 8 million pixels.', 413)
                        bitmap = obj.get_bitmap()
                        try:
                            image = bitmap.to_pil().copy()
                        finally:
                            bitmap.close()
                        crop = op.image_crop
                        if crop is None or not (0 <= crop[0] < crop[2] <= image.width and 0 <= crop[1] < crop[3] <= image.height):
                            image.close()
                            raise PdfEditorError('Image crop must be a positive rectangle inside the source image pixels.')
                        cropped = image.crop(crop)
                        image.close()
                        encoded = io.BytesIO()
                        cropped.save(encoded, format='PNG')
                        cropped.close()
                        replacement = op.model_copy(update={'image_base64': base64.b64encode(encoded.getvalue()).decode()})
                        _image(document, selected, replacement, rect)
                    elif op.action == 'replace':
                        _image(document, selected, op, rect)
                    selected.remove_obj(obj)
                    obj.close()
                    removed.add(original_index)
                else:
                    if op.kind == 'annotation' and op.action == 'delete':
                        annotations.append(op)
                        continue
                    rect = _rect(selected, op.rect)
                    if any(not rect[0] <= point[0] <= rect[2] or not rect[1] <= point[1] <= rect[3] for point in op.points):
                        raise PdfEditorError('Annotation point is outside its rectangle.')
                    if op.kind == 'add_text':
                        _text(document, selected, op, rect)
                    elif op.kind == 'add_image':
                        _image(document, selected, op, rect)
                    elif op.kind == 'annotation':
                        annotations.append(op)
                    elif op.kind == 'apply_ocr':
                        _text(document, selected, op, rect, invisible=op.ocr_mode == 'searchable')
                selected.gen_content()
        out = io.BytesIO()
        document.save(out)
    result = _annotations(out.getvalue(), annotations, data, revision) if annotations else out.getvalue()
    if len(result) > MAX_PDF_BYTES:
        raise PdfEditorError('Edited PDF exceeds 64 MiB.', 413)
    return result


def recognize_regions(data, pages, language='eng', recognize=None):
    """Return reviewed geometry candidates; provider must return image_to_data fields."""
    if len(pages) > 20 or not pages:
        raise PdfEditorError('OCR accepts between 1 and 20 pages.', 413)
    recognize = recognize or _default_recognizer
    regions = []
    pixels = 0
    characters = 0
    started = time.monotonic()
    for page in pages:
        with _LOCK, _open(data) as document, closing(_page(document, page)) as selected:
            if selected.get_rotation() or selected.get_cropbox()[:2] != (0, 0):
                raise PdfEditorError('OCR requires an unrotated page with a zero-origin crop box.', 503)
        image = Image.open(io.BytesIO(render_page(data, page, scale=1)))
        pixels += image.width * image.height
        if pixels > 40_000_000:
            image.close()
            raise PdfEditorError('OCR pixel budget exceeded.', 413)
        try:
            if time.monotonic()-started > 120:
                raise PdfEditorError('OCR exceeded the 120-second limit.', 503)
            words = recognize(image, language)
            for word in words:
                x, y, width, height = (float(word[key]) for key in ('left', 'top', 'width', 'height'))
                text = str(word['text'])
                if not text.strip():
                    continue
                rect = [x, image.height - y - height, x + width, image.height - y]
                if not all(math.isfinite(v) for v in rect) or min(rect) < 0 or rect[2] > image.width or rect[3] > image.height or len(text) > 100000:
                    raise ValueError()
                regions.append({'id': f'{page}:{len(regions)}', 'page': page, 'rect': rect, 'text': text})
                characters += len(text)
                if characters > 100000:
                    raise PdfEditorError('OCR text exceeds 100,000 characters.', 413)
                if len(regions) > 10000:
                    raise ValueError()
            if time.monotonic()-started > 120:
                raise PdfEditorError('OCR exceeded the 120-second limit.', 503)
        except PdfEditorError:
            raise
        except Exception:
            raise PdfEditorError('Local OCR could not recognise bounded text regions.') from None
        finally:
            image.close()
    return regions


def _default_recognizer(image, language):
    """Use installed local models only; this boundary never downloads models."""
    if language == 'eng' and engine_rapidocr.is_available():
        try:
            observations = engine_rapidocr.recognize_observations(image, timeout_seconds=120)
            return [{'left': item['x'], 'top': item['center_y']-item['height']/2,
                     'width': item['width'], 'height': item['height'], 'text': item['text']}
                    for item in observations]
        except ImageTextRecognitionUnavailable:
            raise PdfEditorError('Local OCR models are unavailable.', 503) from None
    try:
        import pytesseract
        installed = set(pytesseract.get_languages(config=''))
        if not set(language.split('+')).issubset(installed):
            raise PdfEditorError('The requested OCR language is not installed.', 503)
        result = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT, timeout=120)
        return [{key: result[key][index] for key in ('left', 'top', 'width', 'height', 'text')}
                for index in range(len(result['text']))]
    except PdfEditorError:
        raise
    except Exception:
        raise PdfEditorError('Local OCR is unavailable or timed out. Install Tesseract and the requested language.', 503) from None
