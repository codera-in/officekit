"""HTTP coverage for the local screenshot editor resource."""

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app import app
from officekit.engines.engine_screenshot_editor import ScreenshotEditError


client = TestClient(app)


def make_png() -> bytes:
    image = Image.new("RGB", (8, 8), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def post_edit(operations: str):
    return client.post(
        "/api/screenshot/edit",
        files={"file": ("clipboard.png", make_png(), "image/png")},
        data={"operations": operations},
    )


def test_screenshot_edit_api_accepts_annotations_and_rejects_invalid_text():
    rectangle = {"type": "rectangle", "x": 0, "y": 0, "width": 8, "height": 8, "color": "#FF0000"}
    text = {**rectangle, "type": "text", "text": "Hi"}
    response = post_edit(json.dumps([rectangle, text]))
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.getpixel((7, 7)) == (255, 0, 0)
    for value in ("", "x" * 201, None, "bad\ntext"):
        assert post_edit(json.dumps([{**text, "text": value}])).status_code == 422


def test_screenshot_edit_returns_cropped_png_with_opaque_mask():
    response = post_edit(json.dumps([
        {"type": "crop", "x": 1, "y": 1, "width": 6, "height": 6},
        {"type": "mask", "x": 4, "y": 4, "width": 2, "height": 2},
    ]))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "screenshot-edited.png" in response.headers["content-disposition"]
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.size == (6, 6)
        assert result.getpixel((4, 4)) == (0, 0, 0)


def test_screenshot_edit_returns_metadata_free_jpeg_when_requested():
    response = client.post(
        "/api/screenshot/edit",
        files={"file": ("clipboard.png", make_png(), "image/png")},
        data={
            "operations": json.dumps([{"type": "mask", "x": 1, "y": 1, "width": 2, "height": 2}]),
            "format": "jpeg",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert "screenshot-edited.jpg" in response.headers["content-disposition"]
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.format == "JPEG"
        assert result.mode == "RGB"
        assert not result.getexif()
        assert not (set(result.info) - {"jfif", "jfif_version", "jfif_unit", "jfif_density"})


def test_screenshot_edit_rejects_unsupported_format():
    response = client.post(
        "/api/screenshot/edit",
        files={"file": ("clipboard.png", make_png(), "image/png")},
        data={"operations": json.dumps([{"type": "mask", "x": 1, "y": 1, "width": 2, "height": 2}]), "format": "gif"},
    )
    assert response.status_code == 422


def test_screenshot_edit_rejects_malformed_operations_and_translucent_redaction():
    for operations in (
        "not-json",
        "[" * 5000 + "]" * 5000,
        json.dumps([{"type": "crop", "x": 0, "y": 0, "width": 100, "height": 1}]),
        json.dumps([{"type": "mask", "x": 0, "y": 0, "width": 1, "height": 1, "color": "#00000080"}]),
        json.dumps([{"type": "erase", "x": 0, "y": 0, "width": 1, "height": 1}]),
    ):
        response = post_edit(operations)
        assert response.status_code == 422
        assert response.json()["detail"] == ScreenshotEditError.public_message


def test_screenshot_edit_returns_413_when_png_encoding_exceeds_output_limit(monkeypatch):
    from officekit.engines.engine_screenshot_editor import ScreenshotEditorEngine

    monkeypatch.setattr(ScreenshotEditorEngine, "MAX_OUTPUT_BYTES", 32)
    response = post_edit(json.dumps([
        {"type": "mask", "x": 0, "y": 0, "width": 1, "height": 1},
    ]))

    assert response.status_code == 413
    assert response.json()["detail"] == "Edited PNG exceeds the 64 MiB output limit."
    assert response.content
