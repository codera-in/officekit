import io

from fastapi.testclient import TestClient
from PIL import Image

import app as officekit_app
from officekit.engines.engine_file_converter import FileConverterEngine


client = TestClient(officekit_app.app)


def test_image_conversion_api_composites_transparency_when_targeting_bmp():
    image = Image.new("RGBA", (24, 24), (255, 0, 0, 128))
    source = io.BytesIO()
    image.save(source, format="PNG")
    original = source.getvalue()

    response = client.post(
        "/api/convert/image",
        files={"file": ("transparent.png", original, "image/png")},
        data={"target_format": "bmp"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/bmp"
    with Image.open(io.BytesIO(response.content)) as converted:
        assert converted.format == "BMP"
        assert converted.mode == "RGB"
        assert converted.size == (24, 24)
        assert all(
            abs(actual - expected) <= 2
            for actual, expected in zip(converted.getpixel((12, 12)), (255, 127, 127))
        )
    assert source.getvalue() == original


def test_image_conversion_endpoint_rejects_output_that_exceeds_response_limit(monkeypatch):
    image = Image.new("RGB", (8, 8), color=(230, 20, 10))
    source = io.BytesIO()
    image.save(source, format="PNG")
    monkeypatch.setattr(FileConverterEngine, "MAX_CONVERT_OUTPUT_BYTES", 8)

    response = client.post(
        "/api/convert/image",
        files={"file": ("source.png", source.getvalue(), "image/png")},
        data={"target_format": "png"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "The converted image exceeds the supported 64 MiB limit."}


def test_image_conversion_endpoint_preserves_animated_webp_timing_and_loop():
    frames = [
        Image.new("RGB", (3, 2), color=(230, 20, 10)),
        Image.new("RGB", (3, 2), color=(10, 20, 230)),
    ]
    source = io.BytesIO()
    frames[0].save(
        source,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=[100, 250],
        loop=2,
    )

    response = client.post(
        "/api/convert/image",
        files={"file": ("motion.webp", source.getvalue(), "image/webp")},
        data={"target_format": "webp"},
    )

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as converted:
        assert converted.n_frames == 2
        durations = []
        for frame_index in range(converted.n_frames):
            converted.seek(frame_index)
            converted.load()
            durations.append(converted.info.get("duration"))
        assert converted.info.get("loop") == 2
    assert durations == [100, 250]
