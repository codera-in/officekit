import base64
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_preview import (
    MAX_PREVIEW_EDGE,
    MediaPreviewEngine,
    MediaPreviewUnavailableError,
)
from officekit.media_routes import create_media_router


def image_bytes(size, mode="RGB", fmt="PNG", color=(40, 80, 120), **save):
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, format=fmt, **save)
    return output.getvalue()


def decoded(result):
    return Image.open(io.BytesIO(base64.b64decode(result["dataBase64"])))


def test_preview_shrinks_a_large_picture_and_reports_its_original_size():
    result = MediaPreviewEngine.render(image_bytes((4000, 3000), fmt="JPEG"), "photo.jpg", 192)
    assert (result["width"], result["height"]) == (4000, 3000)
    assert result["contentType"] == "image/jpeg"
    picture = decoded(result)
    assert max(picture.size) == 192
    assert picture.size[0] / picture.size[1] == pytest.approx(4 / 3, abs=0.02)


def test_preview_does_not_enlarge_a_small_picture():
    result = MediaPreviewEngine.render(image_bytes((50, 40)), "tiny.png", 192)
    assert decoded(result).size == (50, 40)


def test_preview_keeps_transparency_as_png():
    result = MediaPreviewEngine.render(image_bytes((300, 200), "RGBA", color=(255, 0, 0, 80)), "logo.png", 128)
    assert result["contentType"] == "image/png"
    assert decoded(result).mode == "RGBA"


def test_preview_reports_the_displayed_size_of_a_rotated_phone_photo():
    exif = Image.Exif()
    exif[0x0112] = 6
    result = MediaPreviewEngine.render(image_bytes((400, 300), fmt="JPEG", exif=exif), "IMG_1.JPG", 128)
    assert (result["width"], result["height"]) == (300, 400)
    assert decoded(result).size[1] > decoded(result).size[0]


def test_preview_uses_the_first_frame_of_an_animation():
    frames = [Image.new("RGB", (60, 40), color) for color in ((255, 0, 0), (0, 255, 0))]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
    assert MediaPreviewEngine.render(output.getvalue(), "spin.gif", 64)["width"] == 60


@pytest.mark.parametrize("edge", [0, 31, MAX_PREVIEW_EDGE + 1, "192", None, True])
def test_preview_rejects_an_out_of_range_size(edge):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render(image_bytes((20, 20)), "a.png", edge)


@pytest.mark.parametrize("data", [b"", b"not an image", None, "text"])
def test_preview_rejects_empty_or_invalid_bytes(data):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render(data, "broken.png", 128)


def test_preview_rejects_a_pixel_bomb_before_decoding_it():
    huge = io.BytesIO()
    Image.new("1", (20_000, 10_000)).save(huge, format="PNG")
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render(huge.getvalue(), "bomb.png", 128)


@pytest.mark.parametrize("name", ["voice.wav", "report.pdf", "clip.mp4", "scan.jxl", "no_extension", "", None])
def test_image_preview_is_unavailable_for_other_types(name):
    with pytest.raises(MediaPreviewUnavailableError):
        MediaPreviewEngine.render(image_bytes((20, 20)), name, 128)


def test_preview_says_so_when_heic_decoding_is_missing(monkeypatch):
    from officekit.engines import engine_media_native as native

    def missing(_data):
        raise native.NativeMediaUnavailableError()

    monkeypatch.setattr(native, "decode_heif_to_png_bytes", missing)
    with pytest.raises(MediaPreviewUnavailableError):
        MediaPreviewEngine.render(b"\x00" * 32, "IMG_7469.HEIC", 128)


def test_heic_goes_through_the_native_decoder(monkeypatch):
    from officekit.engines import engine_media_native as native

    monkeypatch.setattr(native, "decode_heif_to_png_bytes", lambda _data: image_bytes((640, 480)))
    result = MediaPreviewEngine.render(b"\x00" * 32, "IMG_7469.HEIC", 128)
    assert (result["width"], result["height"]) == (640, 480)


def make_client(tmp_path, files):
    selections = FileSelectionStore(native_token="native")
    paths = []
    for name, data in files.items():
        path = tmp_path / name
        path.write_bytes(data)
        paths.append(str(path))
    selection = selections.register_native(paths, access="read", credential="native")
    # With several roots the manifest names are prefixed "1/", "2/"; key the ids by the plain file name.
    ids = {entry.name.rsplit("/", 1)[-1]: entry.id for entry in selections.iter_files(selection["id"])}
    store = MediaJobStore(selections, staging_root=str(tmp_path / "staging"))
    app = FastAPI()
    app.include_router(create_media_router(store))
    return TestClient(app), selection["id"], ids


def test_preview_route_returns_a_thumbnail_without_touching_the_original(tmp_path):
    original = image_bytes((800, 600), fmt="JPEG")
    client, selection_id, ids = make_client(tmp_path, {"a.jpg": original})
    response = client.get(f"/api/media-previews/{selection_id}/{ids['a.jpg']}?size=128")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"kind", "width", "height", "contentType", "dataBase64"}
    assert body["kind"] == "image"
    assert (body["width"], body["height"]) == (800, 600)
    assert (tmp_path / "a.jpg").read_bytes() == original


def test_preview_route_reports_typed_errors(tmp_path):
    client, selection_id, ids = make_client(tmp_path, {"scan.jxl": b"RIFF....", "bad.png": b"nope"})
    assert client.get(f"/api/media-previews/{selection_id}/{ids['scan.jxl']}").status_code == 415
    assert client.get(f"/api/media-previews/{selection_id}/{ids['bad.png']}").status_code == 422
    assert client.get(f"/api/media-previews/{selection_id}/not-a-file").status_code == 404
    assert client.get(f"/api/media-previews/missing/{ids['bad.png']}").status_code == 404
    assert client.get(f"/api/media-previews/{selection_id}/{ids['bad.png']}?size=9999").status_code == 422
