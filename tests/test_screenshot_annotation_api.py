"""HTTP annotation contracts and pixel output, using an untouched local bitmap."""
import io
import json
import pytest
from PIL import Image
from fastapi.testclient import TestClient
import app as api


def source_image(size=(100, 100)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format='PNG')
    return buffer.getvalue()


def edit(client, operations, format='png'):
    return client.post('/api/screenshot/edit', files={'file': ('source.png', source_image(), 'image/png')}, data={'operations': json.dumps(operations), 'format': format})


@pytest.mark.parametrize('kind', ['text', 'highlight', 'rectangle', 'circle', 'arrow', 'freehand'])
@pytest.mark.parametrize('format', ['png', 'jpeg'])
def test_dual_color_annotation_api_outputs_valid_image(kind, format):
    operation = {'type': kind, 'x': 10, 'y': 10, 'width': 70, 'height': 70,
                 'color': '#ff0000', 'outer_color': '#0000ff', 'stroke_width': 3, 'outer_width': 2}
    if kind == 'text':
        operation.update(text='Hello', font_size=24)
    if kind in {'arrow', 'freehand'}:
        operation['points'] = [[15, 15], [60, 60]]
    with TestClient(api.app) as client:
        response = edit(client, [operation], format)
    assert response.status_code == 200
    assert response.headers['content-type'] == ('image/png' if format == 'png' else 'image/jpeg')
    assert 'screenshot-edited.' in response.headers['content-disposition']
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (100, 100)
        pixels = list(image.convert('RGB').get_flattened_data())
        assert any(red > blue + 30 for red, green, blue in pixels)
        assert any(blue > red + 30 for red, green, blue in pixels)


@pytest.mark.parametrize('override', [
    {'outer_color': 'blue'}, {'outer_width': 33}, {'stroke_width': 0},
    {'outer_width': True}, {'unexpected': True}, {'x': -1}, {'width': 0},
    {'points': [[10, 10], [10, 10]]}, {'points': [[10, 10]]},
    {'points': [[10, 10], [10, 10], [20, 20]]},
    {'points': [[10.5, 10], [20, 20]]}, {'points': [[10, 10], [99, 99]]},
])
def test_invalid_annotation_styles_and_arrow_points_rejected(override):
    operation = {'type': 'arrow', 'x': 10, 'y': 10, 'width': 30, 'height': 30, 'points': [[10, 10], [20, 20]]}
    with TestClient(api.app) as client:
        response = edit(client, [{**operation, **override}])
    assert response.status_code == 422


def test_annotation_point_and_encoded_payload_limits():
    operation = {'type': 'freehand', 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'points': [[10, 10]] * 512}
    with TestClient(api.app) as client:
        assert edit(client, [{**operation, 'points': [[10, 10]] * 513}]).status_code == 422
        assert edit(client, [operation] * 3).status_code == 422
        text = {'type': 'text', 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'text': 'a' * 201}
        assert edit(client, [text]).status_code == 422
        assert edit(client, [{'type': 'rectangle', 'x': 0, 'y': 0, 'width': 1, 'height': 1}] * 51).status_code == 422
        oversized = json.dumps([{'type': 'text', 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'text': '字' * 200}] * 50, ensure_ascii=False)
        response = client.post('/api/screenshot/edit', files={'file': ('source.png', source_image(), 'image/png')}, data={'operations': oversized})
        assert response.status_code == 422


def test_blur_uses_fixed_default_without_settings():
    with TestClient(api.app) as client:
        response = edit(client, [{'type': 'blur', 'x': 0, 'y': 0, 'width': 50, 'height': 50}])
    assert response.status_code == 200


@pytest.mark.parametrize('stamp_name', ['check', 'question', 'x', 'alert', 'heart'])
def test_every_directional_stamp_variant_is_accepted_by_the_http_contract(stamp_name):
    operation = {'type': 'stamp', 'stamp': stamp_name, 'x': 5, 'y': 5, 'width': 40, 'height': 30,
                 'points': [[30, 20], [8, 8]]}
    with TestClient(api.app) as client:
        response = edit(client, [operation])
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (100, 100)


@pytest.mark.parametrize('operation', [
    {'type': 'rounded_rectangle', 'x': 5, 'y': 5, 'width': 30, 'height': 20, 'color': '#ff0000'},
    {'type': 'line', 'x': 5, 'y': 5, 'width': 30, 'height': 20, 'points': [[6, 6], [30, 18]], 'color': '#ff0000'},
    {'type': 'pixelate', 'x': 5, 'y': 5, 'width': 30, 'height': 20, 'block_size': 8},
    {'type': 'rotate'},
])
def test_new_screenshot_operations_are_accepted_by_the_http_contract(operation):
    with TestClient(api.app) as client:
        response = edit(client, [operation])
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (100, 100)


@pytest.mark.parametrize('operation', [
    {'type': 'rounded_rectangle', 'x': 0, 'y': 0, 'width': 4, 'height': 4, 'color': 'red', 'extra': 1},
    {'type': 'line', 'x': 0, 'y': 0, 'width': 4, 'height': 4, 'points': [[1, 1], [1, 1]]},
    {'type': 'stamp', 'stamp': 'smile', 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'points': [[5, 5], [1, 1]]},
    {'type': 'stamp', 'stamp': 'heart', 'x': 0, 'y': 0, 'width': 10, 'height': 10, 'points': [[5, 5], [5, 5]]},
    {'type': 'pixelate', 'x': 0, 'y': 0, 'width': 4, 'height': 4, 'block_size': 65},
    {'type': 'rotate', 'direction': 'counter-clockwise'},
])
def test_invalid_new_screenshot_operations_are_rejected_by_the_http_contract(operation):
    with TestClient(api.app) as client:
        response = edit(client, [operation])
    assert response.status_code == 422


def test_rotation_changes_dimensions_before_later_regions_and_pixelation_is_bounded():
    source = Image.new('RGB', (24, 16))
    for y in range(source.height):
        for x in range(source.width):
            source.putpixel((x, y), (x * 8, y * 12, 100))
    encoded = io.BytesIO()
    source.save(encoded, format='PNG')
    with TestClient(api.app) as client:
        response = client.post('/api/screenshot/edit', files={'file': ('source.png', encoded.getvalue(), 'image/png')}, data={
            'operations': json.dumps([
                {'type': 'rotate'},
                {'type': 'pixelate', 'x': 0, 'y': 0, 'width': 8, 'height': 8, 'block_size': 4},
            ]),
        })
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (16, 24)
        assert image.getpixel((0, 0)) == image.getpixel((3, 3))
        assert image.getpixel((15, 0)) == source.getpixel((0, 0))


@pytest.mark.parametrize('payload', ['{', '{}', 'null', '[]', '[{"type":"unsupported"}]'])
def test_malformed_annotation_operations_fail_with_safe_error(payload):
    with TestClient(api.app) as client:
        response = client.post('/api/screenshot/edit', files={'file': ('source.png', source_image(), 'image/png')}, data={'operations': payload})
    assert response.status_code == 422
    assert 'traceback' not in response.text.lower()


@pytest.mark.parametrize('error_type,status', [('ScreenshotEditError', 422), ('ScreenshotOutputLimitError', 413)])
def test_annotation_engine_errors_are_mapped_without_details(monkeypatch, error_type, status):
    from officekit.engines import engine_screenshot_editor as engine
    from unittest.mock import Mock
    stub = Mock(side_effect=getattr(engine, error_type)())
    monkeypatch.setattr(api.ScreenshotEditorEngine, 'edit_image', stub)
    with TestClient(api.app) as client:
        response = edit(client, [{'type': 'rectangle', 'x': 0, 'y': 0, 'width': 20, 'height': 20}])
    assert response.status_code == status
    stub.assert_called_once()
