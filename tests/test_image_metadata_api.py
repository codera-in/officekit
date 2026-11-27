import io

from fastapi.testclient import TestClient
from PIL import Image

import app as officekit_app


client = TestClient(officekit_app.app)


def _palette_png():
    palette = [0, 0, 0] * 256
    palette[3 * 7:3 * 7 + 3] = [245, 24, 81]
    palette[3 * 203:3 * 203 + 3] = [16, 173, 232]
    image = Image.new("P", (2, 1))
    image.putpalette(palette)
    image.putdata([7, 203])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), list(image.convert("RGB").get_flattened_data())


def test_image_metadata_endpoint_preserves_palette_pixels_and_attachment_name():
    source, expected = _palette_png()
    response = client.post(
        "/api/image/metadata",
        files={"file": ("palette.png", source, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="palette_metadata_removed.png"'
    )
    with Image.open(io.BytesIO(response.content)) as image:
        assert list(image.convert("RGB").get_flattened_data()) == expected
        assert not image.info.get("exif")


def test_image_metadata_endpoint_preserves_animated_gif_frames_and_timing():
    frames = [
        Image.new("RGB", (3, 2), color=(255, 0, 0)),
        Image.new("RGB", (3, 2), color=(0, 0, 255)),
    ]
    source = io.BytesIO()
    frames[0].save(
        source, format="GIF", save_all=True, append_images=frames[1:],
        duration=[120, 340], loop=0, disposal=2,
    )

    response = client.post(
        "/api/image/metadata",
        files={"file": ("motion.gif", source.getvalue(), "image/gif")},
    )

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.n_frames == 2
        colors = []
        durations = []
        for frame in range(result.n_frames):
            result.seek(frame)
            colors.append(result.convert("RGB").getpixel((1, 1)))
            durations.append(result.info.get("duration"))
    assert colors == [(255, 0, 0), (0, 0, 255)]
    assert durations == [120, 340]


def test_image_metadata_endpoint_returns_safe_error_for_corrupt_image():
    response = client.post(
        "/api/image/metadata",
        files={"file": ("private-photo.png", b"not an image", "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The file or requested format cannot be converted. Check the input and try again."
    }
    assert "private-photo" not in response.text


def test_image_metadata_endpoint_rejects_non_image_extension():
    response = client.post(
        "/api/image/metadata",
        files={"file": ("payload.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Choose a supported image file."}


def test_image_metadata_endpoint_rejects_output_that_exceeds_response_limit(monkeypatch):
    source, _expected = _palette_png()
    monkeypatch.setattr(officekit_app, "MAX_IMAGE_RESPONSE_BYTES", 8)
    response = client.post(
        "/api/image/metadata",
        files={"file": ("palette.png", source, "image/png")},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "The image output exceeds the supported 64 MiB limit."}
