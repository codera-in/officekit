import io

import pytest
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter

from officekit.engines.engine_pdf_editor import (
    inspect_document, render_page, list_objects, apply_operations, PdfEditorError,
    recognize_regions,
)
from officekit.engines.pdf_editor_models import RevisionCreate


def fixture_pdf():
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(300, 400))
    canvas.drawString(30, 350, 'Original text')
    canvas.save()
    return out.getvalue()


def test_objects_after_first_window_are_editable():
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(300, 400))
    for index in range(205):
        canvas.drawString(30, 350, f'Line {index}')
    canvas.save()
    data = out.getvalue()
    first = list_objects(data, 1, limit=200)
    assert first['has_more']
    obj = list_objects(data, 1, offset=204)['objects'][0]
    edited = apply_operations(data, [{'kind': 'replace_text', 'page': 1, 'object_id': obj['id'],
        'font': 'Helvetica', 'text': 'Last changed', 'rect': [30, 340, 180, 370]}])
    text = PdfReader(io.BytesIO(edited)).pages[0].extract_text()
    assert 'Last changed' in text and 'Line 204' not in text


def test_transparent_image_preserves_pdf_background():
    import base64
    from PIL import Image
    image = Image.new('RGBA', (10, 10), (0, 0, 0, 0))
    image.putpixel((5, 5), (255, 0, 0, 255))
    encoded = io.BytesIO()
    image.save(encoded, format='PNG')
    background = io.BytesIO()
    canvas = Canvas(background, pagesize=(300, 400))
    canvas.setFillColorRGB(0, 1, 0)
    canvas.rect(30, 30, 100, 100, fill=1, stroke=0)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.drawString(35, 90, 'Underlying text')
    canvas.save()
    edited = apply_operations(background.getvalue(), [{'kind': 'add_image', 'page': 1, 'rect': [30, 30, 130, 130],
        'image_base64': base64.b64encode(encoded.getvalue()).decode()}])
    rendered = Image.open(io.BytesIO(render_page(edited, 1))).convert('RGB')
    assert rendered.getpixel((35, 365)) == (0, 255, 0)
    assert 'Underlying text' in PdfReader(io.BytesIO(edited)).pages[0].extract_text()


def test_move_preserves_rotated_reflected_image_matrix():
    import pypdfium2 as pdfium
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    for transform in ((0, 30, -40, 0, 80, 20), (-30, 0, 0, 40, 80, 20), (30, 10, 5, 30, 20, 20)):
        out = io.BytesIO()
        canvas = Canvas(out, pagesize=(300, 400))
        pattern = Image.new('RGB', (10, 10), 'red')
        for x in range(5):
            for y in range(10):
                pattern.putpixel((x, y), (0, 0, 255))
        canvas.drawImage(ImageReader(pattern), 0, 0, 30, 30)
        canvas.save()
        with pdfium.PdfDocument(out.getvalue()) as doc:
            page = doc[0]
            obj = list(page.get_objects(max_depth=0))[0]
            obj.set_matrix(pdfium.PdfMatrix(*transform))
            page.gen_content()
            output = io.BytesIO()
            doc.save(output)
            page.close()
        source = output.getvalue()
        obj = list_objects(source, 1)['objects'][0]
        x, y, r, t = obj['rect']
        moved = apply_operations(source, [{'kind': 'image_change', 'page': 1, 'object_id': obj['id'],
            'rect': [x+10, y+20, r+10, t+20]}])
        before_pixels = Image.open(io.BytesIO(render_page(source, 1))).convert('RGB')
        after_pixels = Image.open(io.BytesIO(render_page(moved, 1))).convert('RGB')
        for px in range(int(x)+1, int(r), 3):
            for py in range(400-int(t)+1, 400-int(y), 3):
                assert before_pixels.getpixel((px, py)) == after_pixels.getpixel((px+10, py-20))
        with pdfium.PdfDocument(moved) as doc:
            page = doc[0]
            matrix = list(page.get_objects(max_depth=0))[0].get_matrix().get()
            assert matrix[:4] == pytest.approx(transform[:4])
            assert matrix[4:] == pytest.approx((transform[4]+10, transform[5]+20))
            page.close()


def test_image_crop_checks_intrinsic_dimensions_before_decode(monkeypatch):
    import pypdfium2 as pdfium
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(300, 400))
    canvas.drawImage(ImageReader(Image.new('RGB', (10, 10), 'red')), 20, 20, 30, 30)
    canvas.save()
    obj = list_objects(out.getvalue(), 1)['objects'][0]
    monkeypatch.setattr(pdfium.PdfImage, 'get_px_size', lambda self: (10000, 10000))
    monkeypatch.setattr(pdfium.PdfImage, 'get_bitmap', lambda self: pytest.fail('Oversized image decoded'))
    with pytest.raises(PdfEditorError, match='pixels'):
        apply_operations(out.getvalue(), [{'kind': 'image_change', 'page': 1, 'object_id': obj['id'],
            'action': 'crop', 'image_crop': [0, 0, 5, 5]}])


def test_mutation_object_count_and_zero_area_transform_guards(monkeypatch):
    import pypdfium2 as pdfium
    source = fixture_pdf()
    obj = list_objects(source, 1)['objects'][0]
    with monkeypatch.context() as patch:
        patch.setattr(pdfium.PdfPage, 'get_objects', lambda *args, **kwargs: iter([None] * 10001))
        with pytest.raises(PdfEditorError, match='object count'):
            apply_operations(source, [{'kind': 'replace_text', 'page': 1, 'object_id': obj['id'], 'font': 'Helvetica', 'text': 'x'}])
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(300, 400))
    canvas.drawImage(ImageReader(Image.new('RGB', (10, 10), 'red')), 20, 20, 30, 30)
    canvas.save()
    obj = list_objects(out.getvalue(), 1)['objects'][0]
    monkeypatch.setattr(pdfium.PdfImage, 'get_bounds', lambda *args: (0, 0, 0, 0))
    with pytest.raises(PdfEditorError, match='no editable area'):
        apply_operations(out.getvalue(), [{'kind': 'image_change', 'page': 1, 'object_id': obj['id'], 'rect': [10, 10, 30, 30]}])


def test_inspect_preview_and_replace_real_text():
    source = fixture_pdf()
    assert inspect_document(source)['page_count'] == 1
    assert render_page(source, 1).startswith(b'\x89PNG')
    objects = list_objects(source, 1)['objects']
    text = next(obj for obj in objects if obj['kind'] == 'text')
    output = apply_operations(source, [{'kind': 'replace_text', 'page': 1,
        'object_id': text['id'], 'text': 'Changed text', 'font': 'Helvetica',
        'font_size': 12, 'rect': [30, 340, 250, 380]}])
    extracted = PdfReader(io.BytesIO(output)).pages[0].extract_text()
    assert 'Changed text' in extracted
    assert 'Original text' not in extracted
    assert 'Original text' in PdfReader(io.BytesIO(source)).pages[0].extract_text()


def test_bounds_invalid_pdf_and_strict_dto():
    with pytest.raises(PdfEditorError):
        inspect_document(b'not pdf')
    with pytest.raises(PdfEditorError):
        render_page(fixture_pdf(), 2)
    with pytest.raises(ValueError):
        RevisionCreate(base_revision=0, operations=[{'kind': 'add_text', 'page': 1,
            'rect': [0, 0, float('nan'), 20], 'text': 'a'}])
    with pytest.raises(PdfEditorError):
        apply_operations(fixture_pdf(), [{'kind': 'add_text', 'page': 1,
            'rect': [0, 0, 400, 20], 'text': 'outside'}])


def test_add_text_and_native_annotation():
    output = apply_operations(fixture_pdf(), [
        {'kind': 'add_text', 'page': 1, 'rect': [20, 20, 160, 50], 'text': 'Added'},
        {'kind': 'annotation', 'page': 1, 'rect': [20, 70, 160, 100],
         'annotation_type': 'highlight'},
    ])
    page = PdfReader(io.BytesIO(output)).pages[0]
    assert 'Added' in page.extract_text()
    assert page['/Annots'][0].get_object()['/Subtype'] == '/Highlight'


def test_ocr_reconstruction_removes_pixels_and_adds_editable_text():
    source = fixture_pdf()
    output = apply_operations(source, [{'kind': 'apply_ocr', 'page': 1,
        'rect': [20, 330, 200, 380], 'text': 'Corrected', 'ocr_mode': 'reconstruction'}])
    page = PdfReader(io.BytesIO(output)).pages[0]
    assert 'Corrected' in page.extract_text()
    assert 'Original text' not in page.extract_text()
    assert len(page.images) == 1


def test_image_move_is_instance_specific_and_delete():
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    image = ImageReader(Image.new('RGB', (10, 10), 'red'))
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(300, 400))
    canvas.drawImage(image, 10, 10, 30, 30)
    canvas.drawImage(image, 100, 100, 30, 30)
    canvas.save()
    source = out.getvalue()
    objects = list_objects(source, 1)['objects']
    first = objects[0]
    result = apply_operations(source, [{'kind': 'image_change', 'page': 1,
        'object_id': first['id'], 'rect': [50, 50, 80, 80]}])
    moved = list_objects(result, 1)['objects']
    assert moved[0]['rect'] == [50, 50, 80, 80]
    assert moved[1]['rect'] == objects[1]['rect']
    result = apply_operations(source, [{'kind': 'image_change', 'page': 1,
        'object_id': first['id'], 'action': 'delete'}])
    assert len(list_objects(result, 1)['objects']) == 1


def test_ocr_review_coordinates_and_failure(monkeypatch):
    import officekit.engines.engine_pdf_editor as engine
    regions = recognize_regions(fixture_pdf(), [1], recognize=lambda image, language: [
        {'left': 20, 'top': 20, 'width': 40, 'height': 20, 'text': 'Read'}])
    assert regions == [{'id': '1:0', 'page': 1, 'rect': [20, 360, 60, 380], 'text': 'Read'}]
    with monkeypatch.context() as patch:
        patch.setattr(engine, '_default_recognizer', lambda *args: (_ for _ in ()).throw(PdfEditorError('unavailable', 503)))
        with pytest.raises(PdfEditorError, match='unavailable'):
            recognize_regions(fixture_pdf(), [1])
    with pytest.raises(PdfEditorError):
        apply_operations(fixture_pdf(), [{'kind': 'replace_text', 'page': 1,
            'object_id': 'stale', 'text': 'No'}])


@pytest.mark.parametrize('annotation_type', ['text', 'rectangle', 'circle', 'freehand', 'line', 'arrow', 'callout'])
def test_annotation_appearances_render(annotation_type):
    source = fixture_pdf()
    result = apply_operations(source, [{'kind': 'annotation', 'page': 1,
        'rect': [20, 20, 200, 100], 'text': 'Note', 'annotation_type': annotation_type,
        'points': [[30, 30], [100, 70], [150, 40]], 'outer_width': 2}])
    annotation = PdfReader(io.BytesIO(result)).pages[0]['/Annots'][0].get_object()
    assert '/AP' in annotation
    assert render_page(result, 1) != render_page(source, 1)
    item = next(item for item in list_objects(result, 1)['objects'] if item['kind'] == 'annotation')
    assert item['annotation_type'] == annotation_type
    assert item['outer_width'] == 2
    if annotation_type in ('freehand', 'line', 'arrow'):
        assert item['points'][0] == [30, 30]


@pytest.mark.parametrize('operation', [
    {'kind': 'add_text', 'page': 1},
    {'kind': 'add_text', 'page': 1, 'rect': [0, 0, 50, 50], 'text': '漢字'},
    {'kind': 'add_text', 'page': 1, 'rect': [0, 0, 2, 2], 'text': 'too long'},
    {'kind': 'add_image', 'page': 1, 'rect': [0, 0, 50, 50], 'image_base64': 'bad'},
    {'kind': 'annotation', 'page': 1, 'rect': [0, 0, 50, 50], 'annotation_type': 'signature'},
    {'kind': 'annotation', 'page': 1, 'rect': [0, 0, 50, 50], 'annotation_type': 'line'},
    {'kind': 'annotation', 'page': 1, 'rect': [0, 0, 50, 50], 'points': [[51, 1]]},
])
def test_unsupported_operations_fail_without_output(operation):
    with pytest.raises(PdfEditorError):
        apply_operations(fixture_pdf(), [operation])


def test_image_add_replace_and_searchable_ocr():
    import base64
    from PIL import Image
    encoded = io.BytesIO()
    Image.new('RGB', (20, 20), 'blue').save(encoded, format='PNG')
    image = base64.b64encode(encoded.getvalue()).decode('ascii')
    result = apply_operations(fixture_pdf(), [{'kind': 'add_image', 'page': 1,
        'rect': [20, 20, 80, 80], 'image_base64': image}])
    obj = next(obj for obj in list_objects(result, 1)['objects'] if obj['kind'] == 'image')
    replaced = apply_operations(result, [{'kind': 'image_change', 'page': 1,
        'object_id': obj['id'], 'action': 'replace', 'image_base64': image}])
    assert len(PdfReader(io.BytesIO(replaced)).pages[0].images) == 1
    result = apply_operations(fixture_pdf(), [{'kind': 'apply_ocr', 'page': 1,
        'rect': [20, 20, 200, 80], 'text': 'Searchable'}])
    assert 'Searchable' in PdfReader(io.BytesIO(result)).pages[0].extract_text()


def test_pagination_render_and_ocr_limits():
    source = fixture_pdf()
    for scale in (float('nan'), 0, True, 5):
        with pytest.raises(PdfEditorError):
            render_page(source, 1, scale)
    for offset, limit in ((-1, 1), (0, 201), (True, 1)):
        with pytest.raises(PdfEditorError):
            list_objects(source, 1, offset=offset, limit=limit)
    assert list_objects(source, 1, offset=100)['objects'] == []
    with pytest.raises(PdfEditorError):
        inspect_document(b'')
    with pytest.raises(PdfEditorError):
        recognize_regions(source, [])
    with pytest.raises(PdfEditorError):
        recognize_regions(source, [1], recognize=lambda image, language: [
            {'left': -1, 'top': 0, 'width': 10, 'height': 10, 'text': 'Bad'}])


def test_ocr_and_model_boundaries():
    from officekit.engines.pdf_editor_models import Operation, OcrCreate
    assert OcrCreate(base_revision=0, pages=[1]).pages == [1]
    for pages in ([0], [1, 1], [2001]):
        with pytest.raises(ValueError):
            OcrCreate(base_revision=0, pages=pages)
    with pytest.raises(ValueError):
        Operation(kind='annotation', page=1, points=[[float('inf'), 1]])
    with pytest.raises(ValueError):
        Operation(kind='add_text', page=1, text='a\0hidden')
    with pytest.raises(ValueError):
        RevisionCreate(base_revision=0, operations=[Operation(kind='add_text', page=1, text='a'*60000)]*2)
    assert recognize_regions(fixture_pdf(), [1], recognize=lambda image, language: [
        {'left': 0, 'top': 0, 'width': 1, 'height': 1, 'text': ' '}]) == []
    with pytest.raises(PdfEditorError):
        recognize_regions(fixture_pdf(), [1], recognize=lambda image, language: [
            {'left': 0, 'top': 0, 'width': 1, 'height': 1, 'text': 'a'}]*10001)


def test_wrong_object_type_and_revision_collision():
    source = fixture_pdf()
    obj = list_objects(source, 1)['objects'][0]
    with pytest.raises(PdfEditorError, match='does not support'):
        apply_operations(source, [{'kind': 'image_change', 'page': 1, 'object_id': obj['id']}])
    with pytest.raises(PdfEditorError, match='no longer'):
        apply_operations(source, [{'kind': 'replace_text', 'page': 1,
            'font': 'Helvetica', 'object_id': 'stale'}])
    with pytest.raises(PdfEditorError, match='separate revisions'):
        apply_operations(source, [{'kind': 'replace_text', 'page': 1, 'font': 'Helvetica', 'object_id': obj['id']},
            {'kind': 'apply_ocr', 'page': 1, 'rect': [0, 0, 100, 100], 'ocr_mode': 'reconstruction'}])


def test_rotated_crop_ocr_fail_closed_and_metadata():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(fixture_pdf())))
    writer.pages[0].rotate(90)
    out = io.BytesIO()
    writer.write(out)
    source = out.getvalue()
    assert inspect_document(source)['pages'][0]['rotation'] == 90
    with pytest.raises(PdfEditorError, match='unrotated'):
        recognize_regions(source, [1], recognize=lambda image, language: [])
    with pytest.raises(PdfEditorError, match='unrotated'):
        apply_operations(source, [{'kind': 'apply_ocr', 'page': 1,
            'rect': [0, 0, 100, 100], 'ocr_mode': 'reconstruction'}])


def test_annotations_remain_individually_editable():
    source = apply_operations(fixture_pdf(), [{'kind': 'annotation', 'page': 1,
        'rect': [20, 20, 200, 80], 'text': 'Old note'}])
    annotation = next(obj for obj in list_objects(source, 1)['objects'] if obj['kind'] == 'annotation')
    updated = apply_operations(source, [{'kind': 'annotation', 'page': 1,
        'object_id': annotation['id'], 'action': 'replace', 'rect': [30, 30, 200, 90], 'text': 'New note'}])
    items = [obj for obj in list_objects(updated, 1)['objects'] if obj['kind'] == 'annotation']
    assert len(items) == 1 and items[0]['text'] == 'New note'
    deleted = apply_operations(source, [{'kind': 'annotation', 'page': 1,
        'object_id': annotation['id'], 'action': 'delete'}])
    assert not any(obj['kind'] == 'annotation' for obj in list_objects(deleted, 1)['objects'])
    with pytest.raises(PdfEditorError, match='no longer'):
        apply_operations(source, [{'kind': 'annotation', 'page': 1,
            'object_id': 'stale', 'action': 'delete'}])


def test_native_failures_and_worker_error_pickle(monkeypatch):
    import pickle
    import officekit.engines.engine_pdf_editor as engine
    error = pickle.loads(pickle.dumps(PdfEditorError('Unavailable', 503)))
    assert error.status_code == 503 and str(error) == 'Unavailable'
    operation = {'kind': 'add_text', 'page': 1, 'rect': [0, 0, 200, 100], 'text': 'Text'}
    with monkeypatch.context() as patch:
        patch.setattr(engine.raw, 'FPDFPageObj_NewTextObj', lambda *args: None)
        with pytest.raises(PdfEditorError, match='font is unavailable'):
            apply_operations(fixture_pdf(), [operation])
    with monkeypatch.context() as patch:
        patch.setattr(engine.raw, 'FPDFText_SetText', lambda *args: False)
        with pytest.raises(PdfEditorError, match='could not be encoded'):
            apply_operations(fixture_pdf(), [operation])
    with monkeypatch.context() as patch:
        patch.setattr(engine.raw, 'FPDFTextObj_GetText', lambda *args: 200004)
        assert list_objects(fixture_pdf(), 1)['objects'][0]['editable'] is False
    empty = PdfWriter()
    for _ in range(2001):
        empty.add_blank_page(width=10, height=10)
    data = io.BytesIO()
    empty.write(data)
    with pytest.raises(PdfEditorError, match='page count'):
        inspect_document(data.getvalue())


def test_pixel_and_output_budgets(monkeypatch):
    import base64
    import officekit.engines.engine_pdf_editor as engine
    from PIL import Image
    source = fixture_pdf()
    with monkeypatch.context() as patch:
        patch.setattr(engine, 'MAX_RENDER_PIXELS', 10)
        with pytest.raises(PdfEditorError, match='Preview exceeds'):
            render_page(source, 1)
        with pytest.raises(PdfEditorError, match='reconstruction exceeds'):
            apply_operations(source, [{'kind': 'apply_ocr', 'page': 1,
                'rect': [0, 0, 100, 100], 'ocr_mode': 'reconstruction'}])
        png = io.BytesIO()
        Image.new('RGB', (20, 20)).save(png, format='PNG')
        with pytest.raises(PdfEditorError, match='Image must'):
            apply_operations(source, [{'kind': 'add_image', 'page': 1, 'rect': [0, 0, 100, 100],
                'image_base64': base64.b64encode(png.getvalue()).decode()}])
    with pytest.raises(PdfEditorError, match='Image must'):
        apply_operations(source, [{'kind': 'add_image', 'page': 1, 'rect': [0, 0, 100, 100]}])
    with monkeypatch.context() as patch:
        patch.setattr(engine, 'MAX_PDF_BYTES', len(source)+20)
        with pytest.raises(PdfEditorError, match='Edited PDF exceeds'):
            apply_operations(source, [{'kind': 'add_text', 'page': 1, 'rect': [0, 0, 200, 100], 'text': 'Extra'}])


def test_missing_annotation_rect_ignored():
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(fixture_pdf())))
    writer.pages[0][NameObject('/Annots')] = ArrayObject([DictionaryObject({NameObject('/Subtype'): NameObject('/Text')})])
    data = io.BytesIO()
    writer.write(data)
    assert len(list_objects(data.getvalue(), 1)['objects']) == 1


def test_large_encoded_preview_object_and_ocr_budgets(monkeypatch):
    import officekit.engines.engine_pdf_editor as engine
    from PIL import Image
    with monkeypatch.context() as patch:
        patch.setattr(Image.Image, 'save', lambda self, output, **kwargs: output.write(b'x'*(16*1024*1024+1)))
        with pytest.raises(PdfEditorError, match='16 MiB'):
            render_page(fixture_pdf(), 1)
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(300, 400))
    for _ in range(10001):
        canvas.drawString(10, 10, 'a')
    canvas.save()
    with pytest.raises(PdfEditorError, match='object count'):
        list_objects(output.getvalue(), 1)
    encoded = io.BytesIO()
    Image.new('RGB', (2001, 2001)).save(encoded, format='PNG')
    with monkeypatch.context() as patch:
        patch.setattr(engine, 'render_page', lambda *args, **kwargs: encoded.getvalue())
        with pytest.raises(PdfEditorError, match='OCR pixel budget'):
            recognize_regions(fixture_pdf(), [1]*10, recognize=lambda image, language: [])


def test_default_local_ocr_and_limits(monkeypatch):
    from types import SimpleNamespace
    import sys
    import officekit.engines.engine_pdf_editor as engine
    with monkeypatch.context() as patch:
        patch.setattr(engine.engine_rapidocr, 'is_available', lambda: True)
        patch.setattr(engine.engine_rapidocr, 'recognize_observations', lambda image, timeout_seconds: [
            {'x': 10, 'center_y': 30, 'width': 20, 'height': 10, 'text': 'Word'}])
        assert recognize_regions(fixture_pdf(), [1])[0]['text'] == 'Word'
        patch.setattr(engine.engine_rapidocr, 'recognize_observations', lambda *args, **kwargs: (_ for _ in ()).throw(engine.ImageTextRecognitionUnavailable()))
        with pytest.raises(PdfEditorError, match='models are unavailable'):
            recognize_regions(fixture_pdf(), [1])
    provider = SimpleNamespace(get_languages=lambda config: ['eng'], Output=SimpleNamespace(DICT='dict'),
        image_to_data=lambda image, **kwargs: {'left': [10], 'top': [10], 'width': [20], 'height': [10], 'text': ['Read']})
    with monkeypatch.context() as patch:
        patch.setattr(engine.engine_rapidocr, 'is_available', lambda: False)
        patch.setitem(sys.modules, 'pytesseract', provider)
        assert recognize_regions(fixture_pdf(), [1])[0]['text'] == 'Read'
        with pytest.raises(PdfEditorError, match='language is not installed'):
            recognize_regions(fixture_pdf(), [1], language='fra')
        provider.image_to_data = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('timeout'))
        with pytest.raises(PdfEditorError, match='timed out'):
            recognize_regions(fixture_pdf(), [1])
    with pytest.raises(PdfEditorError, match='100,000'):
        recognize_regions(fixture_pdf(), [1], recognize=lambda *args: [
            {'left': 0, 'top': 0, 'width': 20, 'height': 10, 'text': 'a'*60000}]*2)
    with monkeypatch.context() as patch:
        times = iter([0, 121])
        patch.setattr(engine.time, 'monotonic', lambda: next(times))
        with pytest.raises(PdfEditorError, match='120-second'):
            recognize_regions(fixture_pdf(), [1], recognize=lambda *args: [])
    with monkeypatch.context() as patch:
        times = iter([0, 1, 121])
        patch.setattr(engine.time, 'monotonic', lambda: next(times))
        with pytest.raises(PdfEditorError, match='120-second'):
            recognize_regions(fixture_pdf(), [1], recognize=lambda *args: [])


def test_image_crop_rotate_shared_instance():
    import base64
    from PIL import Image
    encoded = io.BytesIO()
    Image.new('RGB', (20, 10), 'blue').save(encoded, format='PNG')
    source = apply_operations(fixture_pdf(), [{'kind': 'add_image', 'page': 1,
        'rect': [20, 20, 100, 60], 'image_base64': base64.b64encode(encoded.getvalue()).decode()}])
    obj = next(item for item in list_objects(source, 1)['objects'] if item['kind'] == 'image')
    output = apply_operations(source, [{'kind': 'image_change', 'page': 1,
        'object_id': obj['id'], 'action': 'crop', 'image_crop': [0, 0, 10, 10]}])
    assert PdfReader(io.BytesIO(output)).pages[0].images[0].image.size == (10, 10)
    with pytest.raises(PdfEditorError, match='crop must'):
        apply_operations(source, [{'kind': 'image_change', 'page': 1,
            'object_id': obj['id'], 'action': 'crop', 'image_crop': [-1, 0, 10, 10]}])
    for rotation in (90, 180, 270):
        output = apply_operations(source, [{'kind': 'image_change', 'page': 1,
            'object_id': obj['id'], 'action': 'rotate', 'rotation_delta': rotation}])
        assert next(item for item in list_objects(output, 1)['objects'] if item['kind'] == 'image')['rect'] == [20, 20, 100, 60]
    rotated_id = next(item for item in list_objects(output, 1)['objects'] if item['kind'] == 'image')['id']
    restored = apply_operations(output, [{'kind': 'image_change', 'page': 1,
        'object_id': rotated_id, 'action': 'rotate', 'rotation_delta': 90}])
    assert render_page(restored, 1) == render_page(source, 1)
    with engine_document_for_test(source) as document:
        page = document[0]
        image = next(item for item in page.get_objects(max_depth=0) if item.type == 3)
        import pypdfium2
        image.set_matrix(pypdfium2.PdfMatrix(30, 30, -30, 30, 70, 30))
        page.gen_content()
        saved = io.BytesIO()
        document.save(saved)
        page.close()
    tilted = saved.getvalue()
    tilted_id = next(item for item in list_objects(tilted, 1)['objects'] if item['kind'] == 'image')['id']
    with pytest.raises(PdfEditorError, match='quarter turns'):
        apply_operations(tilted, [{'kind': 'image_change', 'page': 1, 'object_id': tilted_id, 'action': 'rotate'}])


def test_actual_bundled_local_ocr():
    from officekit.engines import engine_rapidocr
    if not engine_rapidocr.is_available():
        pytest.skip('Bundled RapidOCR models are absent in this environment.')
    regions = recognize_regions(fixture_pdf(), [1])
    assert regions
    assert any('Original' in region['text'] for region in regions)


def engine_document_for_test(source):
    import pypdfium2
    return pypdfium2.PdfDocument(source)
