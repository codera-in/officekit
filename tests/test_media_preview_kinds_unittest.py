import base64
import io
import json
import platform
import stat

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from officekit.engines import engine_media_native as native
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_media_preview import (
    MediaPreviewEngine,
    MediaPreviewLockedError,
    MediaPreviewUnavailableError,
)
from tests.test_media_preview_unittest import make_client


def pdf_bytes(pages=3, size=(300, 400)):
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=size, invariant=1)
    for number in range(pages):
        canvas.drawString(40, size[1] - 60, f"Page {number + 1}")
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def locked_pdf_bytes():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes(1))))
    writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def picture(result):
    return Image.open(io.BytesIO(base64.b64decode(result["dataBase64"])))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.mark.parametrize("name,kind", [
    ("a.JPG", "image"), ("scan.heic", "image"), ("doc.PDF", "pdf"), ("clip.mp4", "video"), ("movie.MOV", "video"),
    ("voice.m4a", "audio"), ("song.flac", "audio"), ("scan.jxl", None), ("noext", None), ("", None), (None, None),
])
def test_preview_kind_by_extension(name, kind):
    assert MediaPreviewEngine.kind(name) == kind


def test_pdf_preview_draws_the_first_page_and_counts_pages():
    result = MediaPreviewEngine.render_pdf(pdf_bytes(3), 128)
    assert (result["kind"], result["pageCount"], result["page"]) == ("pdf", 3, 1)
    assert (result["width"], result["height"]) == (300, 400)
    assert result["contentType"] == "image/jpeg"
    assert max(picture(result).size) == 128


def test_pdf_preview_draws_the_requested_page():
    document = pdf_bytes(3)
    first = MediaPreviewEngine.render_pdf(document, 200, 1)
    third = MediaPreviewEngine.render_pdf(document, 200, 3)
    assert third["page"] == 3
    assert first["dataBase64"] != third["dataBase64"]


@pytest.mark.parametrize("page", [0, 4, -1, "1", None, True, 1.0])
def test_pdf_preview_rejects_pages_that_do_not_exist(page):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render_pdf(pdf_bytes(3), 128, page)


@pytest.mark.parametrize("edge", [0, 31, 2049, "128", None, True])
def test_pdf_preview_rejects_an_out_of_range_size(edge):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render_pdf(pdf_bytes(1), edge)


@pytest.mark.parametrize("data", [b"", None, "text", b"not a pdf"])
def test_pdf_preview_rejects_empty_or_invalid_bytes(data):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render_pdf(data, 128)


def test_pdf_preview_reports_a_password_protected_file_as_locked():
    with pytest.raises(MediaPreviewLockedError):
        MediaPreviewEngine.render_pdf(locked_pdf_bytes(), 128)


def test_pdf_preview_rejects_an_enormous_page():
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render_pdf(pdf_bytes(1, (20_000, 100)), 128)


def test_pdf_preview_is_unavailable_without_pdfium(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "pypdfium2":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(MediaPreviewUnavailableError):
        MediaPreviewEngine.render_pdf(pdf_bytes(1), 128)


def fake_native(monkeypatch, **details):
    seen = {}

    def fake(source, extension, kind, max_edge, position):
        seen.update(extension=extension, kind=kind, max_edge=max_edge, position=position, bytes=source.read())
        return {"duration": 84.4, "width": 1920, "height": 1080, "peaks": [], "image": JPEG, **details}

    monkeypatch.setattr(native, "render_media_preview", fake)
    return seen


def test_video_preview_reports_the_frame_size_and_duration(monkeypatch):
    seen = fake_native(monkeypatch)
    result = MediaPreviewEngine.render_av(io.BytesIO(b"movie"), "holiday.MP4", "video", 256, 40)
    assert result == {
        "kind": "video", "durationSeconds": 84.4, "width": 1920, "height": 1080,
        "contentType": "image/jpeg", "dataBase64": base64.b64encode(JPEG).decode("ascii"),
    }
    assert seen == {"extension": ".MP4", "kind": "video", "max_edge": 256, "position": 40, "bytes": b"movie"}


def test_audio_preview_returns_a_waveform_and_cover_art_only_when_present(monkeypatch):
    fake_native(monkeypatch, peaks=[10, 80, 100], width=0, height=0)
    with_cover = MediaPreviewEngine.render_av(io.BytesIO(b"x"), "talk.m4a", "audio", 128)
    assert with_cover["peaks"] == [10, 80, 100] and "dataBase64" in with_cover
    assert "width" not in with_cover
    fake_native(monkeypatch, peaks=[10, 80, 100], image=None)
    without = MediaPreviewEngine.render_av(io.BytesIO(b"x"), "talk.m4a", "audio", 128)
    assert without == {"kind": "audio", "durationSeconds": 84.4, "peaks": [10, 80, 100]}


@pytest.mark.parametrize("name,kind", [("a.mp3", "video"), ("a.mp4", "audio"), ("a.pdf", "video"), ("a.png", "audio")])
def test_av_preview_refuses_a_mismatched_kind(name, kind):
    with pytest.raises(MediaPreviewUnavailableError):
        MediaPreviewEngine.render_av(io.BytesIO(b"x"), name, kind)


def test_av_preview_is_unavailable_when_the_native_helper_is_missing(monkeypatch):
    def missing(*_args):
        raise native.NativeMediaUnavailableError()

    monkeypatch.setattr(native, "render_media_preview", missing)
    with pytest.raises(MediaPreviewUnavailableError):
        MediaPreviewEngine.render_av(io.BytesIO(b"x"), "clip.mp4", "video")


@pytest.mark.parametrize("edge", [0, 31, 2049, "128", None])
def test_av_preview_rejects_an_out_of_range_size(edge):
    with pytest.raises(ConversionInputError):
        MediaPreviewEngine.render_av(io.BytesIO(b"x"), "clip.mp4", "video", edge)


def install_fake_helper(monkeypatch, tmp_path, body):
    helper = tmp_path / "helper.sh"
    helper.write_text("#!/bin/sh\n" + body)
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: str(helper))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")


GOOD_VIDEO = 'printf "\\377\\330\\377\\340rest" > "$3"\nprintf \'{"width":1920,"height":1080,"duration":12.5,"peaks":[],"hasArtwork":true}\'\n'


def test_native_helper_output_is_read_and_validated(monkeypatch, tmp_path):
    install_fake_helper(monkeypatch, tmp_path, GOOD_VIDEO)
    result = native.render_media_preview(io.BytesIO(b"movie"), ".mp4", "video", 256, 10)
    assert (result["width"], result["height"], result["duration"]) == (1920, 1080, 12.5)
    assert result["image"].startswith(b"\xff\xd8")


def test_native_helper_receives_a_private_copy_and_the_right_arguments(monkeypatch, tmp_path):
    log = tmp_path / "args.txt"
    install_fake_helper(monkeypatch, tmp_path, f'echo "$1 $4 $5 $(wc -c < "$2" | tr -d " ")" > {log}\n' + GOOD_VIDEO)
    native.render_media_preview(io.BytesIO(b"12345"), ".MOV", "video", 300, 55)
    assert log.read_text().split() == ["preview-video", "300", "55", "5"]


def test_native_audio_preview_without_cover_art_returns_peaks_only(monkeypatch, tmp_path):
    install_fake_helper(monkeypatch, tmp_path, 'printf \'{"width":0,"height":0,"duration":3,"peaks":[5,100],"hasArtwork":false}\'\n')
    result = native.render_media_preview(io.BytesIO(b"x"), ".m4a", "audio", 128)
    assert result["peaks"] == [5, 100] and result["image"] is None


@pytest.mark.parametrize("body", [
    "exit 1\n",
    "printf 'not json'\n",
    'printf \'{"width":1,"height":1,"duration":1,"peaks":[]}\'\n',
    'printf \'{"width":1,"height":1,"duration":0,"peaks":[],"hasArtwork":false}\'\n',
    'printf \'{"width":1,"height":1,"duration":999999,"peaks":[],"hasArtwork":false}\'\n',
    'printf \'{"width":"1","height":1,"duration":1,"peaks":[],"hasArtwork":false}\'\n',
    'printf \'{"width":1,"height":1,"duration":1,"peaks":[101],"hasArtwork":false}\'\n',
    'printf \'{"width":1,"height":1,"duration":1,"peaks":[1.5],"hasArtwork":false}\'\n',
    'printf \'{"width":1,"height":1,"duration":1,"peaks":[],"hasArtwork":true}\'\n',
    'printf "not a jpeg" > "$3"\nprintf \'{"width":1,"height":1,"duration":1,"peaks":[],"hasArtwork":true}\'\n',
    'printf \'{"width":1,"height":1,"duration":1,"peaks":[],"hasArtwork":false}\'\n',
])
def test_native_helper_output_that_does_not_validate_is_rejected(monkeypatch, tmp_path, body):
    install_fake_helper(monkeypatch, tmp_path, body)
    with pytest.raises(ConversionInputError):
        native.render_media_preview(io.BytesIO(b"movie"), ".mp4", "video", 256, 10)


@pytest.mark.parametrize("extension,edge,position", [("", 128, 10), (".mp4/..", 128, 10), (".a" * 7, 128, 10), (".mp4", 31, 10), (".mp4", 128, 101), (".mp4", 128, -1), (".mp4", 128, "5")])
def test_native_preview_rejects_unsafe_arguments(monkeypatch, tmp_path, extension, edge, position):
    install_fake_helper(monkeypatch, tmp_path, GOOD_VIDEO)
    with pytest.raises(ConversionInputError):
        native.render_media_preview(io.BytesIO(b"x"), extension, "video", edge, position)


def test_native_preview_rejects_an_empty_or_oversized_source(monkeypatch, tmp_path):
    install_fake_helper(monkeypatch, tmp_path, GOOD_VIDEO)
    with pytest.raises(ConversionInputError):
        native.render_media_preview(io.BytesIO(b""), ".mp4", "video", 128)
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    with pytest.raises(ConversionInputError):
        native.render_media_preview(io.BytesIO(b"12345"), ".mp4", "video", 128)


def test_native_preview_only_supports_video_and_audio(monkeypatch, tmp_path):
    install_fake_helper(monkeypatch, tmp_path, GOOD_VIDEO)
    with pytest.raises(ValueError):
        native.render_media_preview(io.BytesIO(b"x"), ".png", "image", 128)


def test_native_preview_is_unavailable_off_macos_or_without_the_helper(monkeypatch, tmp_path):
    install_fake_helper(monkeypatch, tmp_path, GOOD_VIDEO)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(native.NativeMediaUnavailableError):
        native.render_media_preview(io.BytesIO(b"x"), ".mp4", "video", 128)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    with pytest.raises(native.NativeMediaUnavailableError):
        native.render_media_preview(io.BytesIO(b"x"), ".mp4", "video", 128)


def test_route_previews_a_pdf_page_and_leaves_the_original(tmp_path):
    original = pdf_bytes(3)
    client, selection_id, ids = make_client(tmp_path, {"invoice.pdf": original})
    body = client.get(f"/api/media-previews/{selection_id}/{ids['invoice.pdf']}?size=128&page=2").json()
    assert (body["kind"], body["page"], body["pageCount"]) == ("pdf", 2, 3)
    assert set(body) == {"kind", "width", "height", "contentType", "dataBase64", "pageCount", "page"}
    assert (tmp_path / "invoice.pdf").read_bytes() == original


def test_route_pdf_errors(tmp_path):
    client, selection_id, ids = make_client(tmp_path, {"locked.pdf": locked_pdf_bytes(), "short.pdf": pdf_bytes(1), "bad.pdf": b"no"})
    locked = client.get(f"/api/media-previews/{selection_id}/{ids['locked.pdf']}")
    assert (locked.status_code, locked.json()) == (200, {"kind": "pdf", "locked": True})
    assert client.get(f"/api/media-previews/{selection_id}/{ids['short.pdf']}?page=2").status_code == 422
    assert client.get(f"/api/media-previews/{selection_id}/{ids['bad.pdf']}").status_code == 422
    assert client.get(f"/api/media-previews/{selection_id}/{ids['short.pdf']}?page=0").status_code == 422


def test_route_passes_size_and_position_to_video_and_audio(tmp_path, monkeypatch):
    seen = fake_native(monkeypatch, peaks=[1, 2])
    client, selection_id, ids = make_client(tmp_path, {"clip.mp4": b"movie", "talk.m4a": b"voice"})
    video = client.get(f"/api/media-previews/{selection_id}/{ids['clip.mp4']}?size=300&position=70").json()
    assert (video["kind"], video["width"], video["durationSeconds"]) == ("video", 1920, 84.4)
    assert (seen["max_edge"], seen["position"], seen["bytes"]) == (300, 70, b"movie")
    audio = client.get(f"/api/media-previews/{selection_id}/{ids['talk.m4a']}").json()
    assert audio["kind"] == "audio" and audio["peaks"] == [1, 2]


def test_route_av_is_a_typed_415_when_the_helper_is_missing_and_422_when_it_fails(tmp_path, monkeypatch):
    client, selection_id, ids = make_client(tmp_path, {"clip.mp4": b"movie"})

    def missing(*_args):
        raise native.NativeMediaUnavailableError()

    monkeypatch.setattr(native, "render_media_preview", missing)
    assert client.get(f"/api/media-previews/{selection_id}/{ids['clip.mp4']}").status_code == 415

    def broken(*_args):
        raise ConversionInputError()

    monkeypatch.setattr(native, "render_media_preview", broken)
    assert client.get(f"/api/media-previews/{selection_id}/{ids['clip.mp4']}").status_code == 422


def test_route_rejects_out_of_range_query_values(tmp_path):
    client, selection_id, ids = make_client(tmp_path, {"short.pdf": pdf_bytes(1)})
    base = f"/api/media-previews/{selection_id}/{ids['short.pdf']}"
    for query in ("size=2049", "size=31", "page=0", "position=101", "position=-1"):
        assert client.get(f"{base}?{query}").status_code == 422
    assert client.get(f"{base}?size=2048").status_code == 200


def test_route_large_preview_up_to_2048_for_an_image(tmp_path):
    big = io.BytesIO()
    Image.new("RGB", (3000, 2000), (10, 90, 160)).save(big, format="JPEG")
    client, selection_id, ids = make_client(tmp_path, {"big.jpg": big.getvalue()})
    body = client.get(f"/api/media-previews/{selection_id}/{ids['big.jpg']}?size=2048").json()
    assert (body["width"], body["height"]) == (3000, 2000)
    assert max(picture(body).size) == 2048
    json.dumps(body)
