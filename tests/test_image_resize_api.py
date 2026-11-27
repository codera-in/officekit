import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

import app as officekit_app
from officekit.engines.engine_file_converter import FileConverterEngine


client = TestClient(officekit_app.app)


def _image_bytes(image, image_format="PNG", **save_options):
    output = io.BytesIO()
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


def test_batch_resize_returns_safe_zip_and_resizes_each_file():
    first = _image_bytes(Image.new("RGB", (80, 40), (255, 0, 0)))
    second = _image_bytes(Image.new("RGB", (20, 60), (0, 0, 255)))
    response = client.post(
        "/api/images/resize",
        data={"max_width": "40", "max_height": "30"},
        files=[
            ("files", ("../same.png", first, "image/png")),
            ("files", ("same.png", second, "image/png")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert response.headers["content-disposition"].startswith('attachment; filename="resized_images.zip"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["same_resized.png", "same_resized (2).png"]
        with Image.open(io.BytesIO(archive.read("same_resized.png"))) as resized:
            assert resized.size == (40, 20)
        with Image.open(io.BytesIO(archive.read("same_resized (2).png"))) as resized:
            assert resized.size == (10, 30)


def test_batch_resize_rejects_too_many_files_before_processing():
    response = client.post(
        "/api/images/resize",
        data={"max_width": "40", "max_height": "30"},
        files=[("files", (f"{index}.png", b"not decoded", "image/png")) for index in range(51)],
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "A batch can contain at most 50 images."


def test_batch_resize_enforces_one_aggregate_input_budget(monkeypatch):
    monkeypatch.setattr(officekit_app, "MAX_IMAGE_BATCH_INPUT_BYTES", 8)
    response = client.post(
        "/api/images/resize",
        data={"max_width": "4", "max_height": "4"},
        files=[("files", ("one.png", b"12345", "image/png")), ("files", ("two.png", b"67890", "image/png"))],
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "The image batch exceeds the supported 64 MiB input limit."


def test_batch_resize_enforces_cumulative_decoded_pixel_work(monkeypatch):
    monkeypatch.setattr(FileConverterEngine, "MAX_RESIZE_BATCH_TOTAL_PIXELS", 511, raising=False)
    image = _image_bytes(Image.new("RGB", (16, 16), (90, 120, 150)))

    response = client.post(
        "/api/images/resize",
        data={"max_width": "8", "max_height": "8"},
        files=[("files", ("one.png", image, "image/png")), ("files", ("two.png", image, "image/png"))],
    )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "The image batch requires too much processing; select fewer or smaller images."


def test_batch_resize_accepts_exact_cumulative_decoded_pixel_work_limit(monkeypatch):
    monkeypatch.setattr(FileConverterEngine, "MAX_RESIZE_BATCH_TOTAL_PIXELS", 512, raising=False)
    image = _image_bytes(Image.new("RGB", (16, 16), (90, 120, 150)))

    response = client.post(
        "/api/images/resize",
        data={"max_width": "8", "max_height": "8"},
        files=[("files", ("one.png", image, "image/png")), ("files", ("two.png", image, "image/png"))],
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["one_resized.png", "two_resized.png"]
        assert all(Image.open(io.BytesIO(archive.read(name))).size == (8, 8) for name in archive.namelist())


def test_batch_resize_bounds_the_final_zip_output(monkeypatch):
    monkeypatch.setattr(FileConverterEngine, "MAX_RESIZE_OUTPUT_BYTES", 64)
    source = _image_bytes(Image.new("RGB", (40, 40), (22, 33, 44)))
    response = client.post(
        "/api/images/resize",
        data={"max_width": "20", "max_height": "20"},
        files=[("files", ("large.png", source, "image/png"))],
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "The resized image batch exceeds the supported 64 MiB output limit."


def test_batch_resize_rejects_malformed_image_without_partial_zip():
    valid = _image_bytes(Image.new("RGB", (8, 8)))
    response = client.post(
        "/api/images/resize",
        data={"max_width": "4", "max_height": "4"},
        files=[
            ("files", ("valid.png", valid, "image/png")),
            ("files", ("broken.png", b"not an image", "image/png")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The file or requested format cannot be converted. Check the input and try again."


def test_resize_image_returns_bounded_attachment_with_dimensions_and_safe_name():
    source = Image.new("RGB", (800, 600), (45, 120, 210))
    response = client.post(
        "/api/image/resize",
        data={"max_width": "400", "max_height": "300"},
        files={"file": ("../../private/customer.png", _image_bytes(source), "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="customer_resized.png"'
    )
    assert response.headers["x-officekit-image-width"] == "400"
    assert response.headers["x-officekit-image-height"] == "300"
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.size == (400, 300)
        assert resized.getpixel((200, 150)) == (45, 120, 210)


def test_resize_image_preserves_aspect_ratio_without_upscaling():
    source = Image.new("RGB", (100, 50), (10, 20, 30))
    response = client.post(
        "/api/image/resize",
        data={"max_width": "400", "max_height": "300"},
        files={"file": ("small.png", _image_bytes(source), "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["x-officekit-image-width"] == "100"
    assert response.headers["x-officekit-image-height"] == "50"


def test_resize_image_applies_jpeg_orientation_and_preserves_dimensions():
    source = Image.new("RGB", (20, 10), (120, 30, 40))
    exif = Image.Exif()
    exif[274] = 6
    payload = _image_bytes(source, "JPEG", exif=exif)
    response = client.post(
        "/api/image/resize",
        data={"max_width": "15", "max_height": "15"},
        files={"file": ("rotated.jpg", payload, "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.headers["x-officekit-image-width"] == "8"
    assert response.headers["x-officekit-image-height"] == "15"
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.size == (8, 15)
        assert resized.getexif().get(274) is None


def test_resize_image_preserves_animated_gif_frames_and_durations():
    frames = [
        Image.new("RGB", (40, 20), (255, 0, 0)),
        Image.new("RGB", (40, 20), (0, 0, 255)),
    ]
    payload = _image_bytes(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=[120, 340], loop=0)
    response = client.post(
        "/api/image/resize",
        data={"max_width": "20", "max_height": "20"},
        files={"file": ("motion.gif", payload, "image/gif")},
    )

    assert response.status_code == 200
    assert response.headers["x-officekit-image-width"] == "20"
    assert response.headers["x-officekit-image-height"] == "10"
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.n_frames == 2
        assert resized.info.get("loop") == 0
        colors = []
        durations = []
        for frame_index in range(resized.n_frames):
            resized.seek(frame_index)
            colors.append(resized.convert("RGB").getpixel((10, 5)))
            durations.append(resized.info.get("duration"))
    assert colors == [(255, 0, 0), (0, 0, 255)]
    assert durations == [120, 340]


def test_resize_image_preserves_multipage_tiff_pages():
    frames = [
        Image.new("RGB", (40, 20), (230, 20, 30)),
        Image.new("RGB", (30, 30), (20, 40, 220)),
    ]
    payload = _image_bytes(frames[0], "TIFF", save_all=True, append_images=frames[1:])
    response = client.post(
        "/api/image/resize",
        data={"max_width": "20", "max_height": "20"},
        files={"file": ("pages.tiff", payload, "image/tiff")},
    )

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.n_frames == 2
        dimensions = []
        colors = []
        for frame_index in range(resized.n_frames):
            resized.seek(frame_index)
            dimensions.append(resized.size)
            colors.append(resized.convert("RGB").getpixel((1, 1)))
    assert dimensions == [(20, 10), (20, 20)]
    assert colors == [(230, 20, 30), (20, 40, 220)]


def test_resize_image_preserves_animated_webp_frames_timing_and_loop():
    frames = [Image.new("RGB", (40, 20), "red"), Image.new("RGB", (40, 20), "blue")]
    payload = _image_bytes(
        frames[0], "WEBP", save_all=True, append_images=frames[1:], duration=[110, 320], loop=2,
    )
    with Image.open(io.BytesIO(payload)) as source:
        source_durations = []
        for frame_index in range(source.n_frames):
            source.seek(frame_index)
            source.load()
            source_durations.append(source.info.get("duration"))
    assert source_durations == [110, 320]
    response = client.post(
        "/api/image/resize",
        data={"max_width": "20", "max_height": "20"},
        files={"file": ("motion.webp", payload, "image/webp")},
    )

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.n_frames == 2
        durations = []
        colors = []
        for frame_index in range(resized.n_frames):
            resized.seek(frame_index)
            resized.load()
            durations.append(resized.info.get("duration"))
            colors.append(resized.convert("RGB").getpixel((10, 5)))
        assert resized.info.get("loop") == 2
    assert durations == [110, 320]
    assert colors[0][0] > 220 and colors[0][2] < 40
    assert colors[1][2] > 220 and colors[1][0] < 40


def test_resize_image_preserves_supported_color_profile_and_density():
    output = io.BytesIO()
    Image.new("RGB", (20, 10), (20, 80, 160)).save(
        output,
        format="PNG",
        icc_profile=b"test-icc-profile",
        dpi=(144, 144),
    )
    response = client.post(
        "/api/image/resize",
        data={"max_width": "10", "max_height": "10"},
        files={"file": ("profile.png", output.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as resized:
        assert resized.info["icc_profile"] == b"test-icc-profile"
        assert all(abs(value - 144.0) < 0.02 for value in resized.info["dpi"])


def test_resize_image_rejects_invalid_dimensions_and_unsupported_extensions():
    payload = _image_bytes(Image.new("RGB", (2, 2), "white"))
    invalid_dimensions = client.post(
        "/api/image/resize",
        data={"max_width": "0", "max_height": "2"},
        files={"file": ("image.png", payload, "image/png")},
    )
    unsupported = client.post(
        "/api/image/resize",
        data={"max_width": "2", "max_height": "2"},
        files={"file": ("image.txt", payload, "text/plain")},
    )

    assert invalid_dimensions.status_code == 422
    assert unsupported.status_code == 415
    assert unsupported.json() == {"detail": "Choose a supported image file."}


def test_resize_image_maps_corrupt_images_and_resource_excess_to_safe_errors(monkeypatch):
    corrupt = client.post(
        "/api/image/resize",
        data={"max_width": "10", "max_height": "10"},
        files={"file": ("private.png", b"not an image", "image/png")},
    )
    monkeypatch.setattr(officekit_app.FileConverterEngine, "MAX_RESIZE_FRAME_PIXELS", 3)
    oversized = client.post(
        "/api/image/resize",
        data={"max_width": "10", "max_height": "10"},
        files={"file": ("small.png", _image_bytes(Image.new("RGB", (2, 2), "white")), "image/png")},
    )

    assert corrupt.status_code == 422
    assert "private" not in corrupt.text
    assert oversized.status_code == 422


def test_resize_image_rejects_aggregate_frame_work_and_frame_count_over_limits(monkeypatch):
    frames = [Image.new("RGB", (2, 2), "red"), Image.new("RGB", (2, 2), "blue")]
    animated = _image_bytes(frames[0], "GIF", save_all=True, append_images=frames[1:])
    monkeypatch.setattr(officekit_app.FileConverterEngine, "MAX_RESIZE_TOTAL_PIXELS", 7)
    aggregate = client.post(
        "/api/image/resize",
        data={"max_width": "2", "max_height": "2"},
        files={"file": ("motion.gif", animated, "image/gif")},
    )
    monkeypatch.setattr(officekit_app.FileConverterEngine, "MAX_RESIZE_TOTAL_PIXELS", 100)
    monkeypatch.setattr(officekit_app.FileConverterEngine, "MAX_RESIZE_FRAMES", 1)
    frame_count = client.post(
        "/api/image/resize",
        data={"max_width": "2", "max_height": "2"},
        files={"file": ("motion.gif", animated, "image/gif")},
    )

    assert aggregate.status_code == 422
    assert frame_count.status_code == 422


def test_resize_image_rejects_oversized_output(monkeypatch):
    monkeypatch.setattr(officekit_app.FileConverterEngine, "MAX_RESIZE_OUTPUT_BYTES", 8)
    response = client.post(
        "/api/image/resize",
        data={"max_width": "20", "max_height": "20"},
        files={"file": ("image.png", _image_bytes(Image.new("RGB", (40, 40), "white")), "image/png")},
    )

    assert response.status_code == 413
