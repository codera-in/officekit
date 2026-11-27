import io
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import (
    MediaInputTooLargeError,
    MediaJobCapacityError,
    MediaJobStore,
)
from officekit.engines.engine_media_native import native_heif_decoder_available, native_media_available
from officekit.engines.engine_media_staging import MediaStagingStore
from officekit.media_routes import create_media_router


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)

    def shutdown(self, **_kwargs):
        return None


def make_client(tmp_path):
    source_path = tmp_path / "camera.png"
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (40, 80, 120)).save(output, format="PNG")
    source_path.write_bytes(output.getvalue())
    selections = FileSelectionStore(native_token="native")
    selection = selections.register_native([str(source_path)], access="read", credential="native")
    selected = next(selections.iter_files(selection["id"]))
    image_staging = MediaStagingStore(root=str(tmp_path / "image-staging"))
    watermark_staging = MediaStagingStore(
        root=str(tmp_path / "watermark-staging"), max_image_bytes=5 * 1024 * 1024, max_images=10,
    )
    store = MediaJobStore(
        selections,
        executor=ImmediateExecutor(),
        staging_root=str(tmp_path / "staging"),
        image_staging_store=image_staging,
        watermark_staging_store=watermark_staging,
    )
    app = FastAPI()
    app.include_router(create_media_router(
        store, image_staging_store=image_staging, watermark_staging_store=watermark_staging,
    ))
    return TestClient(app), store, selections, selected, source_path


def request_for(selected, operation_id="image-resize", options=None):
    return {"items": [{
        "source": {"kind": "selection", "selectionId": selected.selection_id, "fileId": selected.id},
        "operations": [{"operationId": operation_id, "options": options or {"maxWidth": 40, "maxHeight": 30}}],
    }]}


def test_media_job_typed_smart_crop_returns_downloadable_copy_without_exposing_staged_path(tmp_path, monkeypatch):
    from officekit.engines import engine_media_native as native

    client, jobs, selections, selected, source_path = make_client(tmp_path)
    original = source_path.read_bytes()
    probes = []

    def saliency(path, kind, **_kwargs):
        probes.append(Path(path))
        assert kind == "image" and Path(path).read_bytes() == original
        return {"sourceWidth": 80, "sourceHeight": 60, "detected": True,
                "x": 0.8, "y": 0.4, "width": 0.1, "height": 0.2}

    monkeypatch.setattr(native, "probe_smart_crop_bounds", saliency)
    response = client.post("/api/media-jobs", json=request_for(selected, "image-crop", {"aspectRatio": "1:1", "smartCrop": True}))
    assert response.status_code == 202
    status = client.get(response.headers["location"]).json()
    assert status["state"] == "ready"
    item = status["items"][0]
    assert item["attributes"]["smart_crop"] is True
    artifact = client.get(f"/api/media-artifacts/{item['artifactId']}")
    with Image.open(io.BytesIO(artifact.content)) as prepared:
        assert prepared.size == (60, 60)
    assert len(probes) == 1 and not probes[0].exists()
    assert str(probes[0]) not in str(status)
    assert source_path.read_bytes() == original
    jobs.close()
    selections.close()


def test_media_job_routes_create_poll_cancel_and_stream_artifact(tmp_path):
    client, jobs, selections, selected, source_path = make_client(tmp_path)
    original = source_path.read_bytes()
    response = client.post("/api/media-jobs", json=request_for(selected))
    assert response.status_code == 202
    assert response.headers["location"] == f"/api/media-jobs/{response.json()['id']}"
    status = client.get(response.headers["location"])
    assert status.status_code == 200
    assert status.json()["state"] == "ready"
    artifact_id = status.json()["items"][0]["artifactId"]
    artifact = client.get(f"/api/media-artifacts/{artifact_id}")
    assert artifact.status_code == 200
    assert "camera_prepared.png" in artifact.headers["content-disposition"]
    with Image.open(io.BytesIO(artifact.content)) as output:
        assert output.size == (40, 30)
    assert source_path.read_bytes() == original
    cancel = client.post(f"/api/media-jobs/{response.json()['id']}/cancellations", json={})
    assert cancel.status_code == 409
    jobs.close()
    selections.close()


def test_media_job_optimizes_heic_selection_through_shared_image_path(tmp_path):
    if not native_heif_decoder_available():
        pytest.skip("macOS ImageIO via sips is not available")
    client, jobs, selections, _selected, _source_path = make_client(tmp_path)
    source = tmp_path / "portrait.heic"
    shutil.copyfile("tests/fixtures/similar-images/cc0/heic/still-medium.heic", source)
    original = source.read_bytes()
    grant = selections.register_native([str(source)], access="read", credential="native")
    selected = next(selections.iter_files(grant["id"]))
    response = client.post("/api/media-jobs", json=request_for(selected, "image-optimize", {"quality": 82}))
    assert response.status_code == 202
    status = client.get(response.headers["location"]).json()
    item = status["items"][0]
    artifact = client.get(f"/api/media-artifacts/{item['artifactId']}")
    assert status["state"] == "ready"
    assert artifact.headers["content-type"] == "image/webp"
    assert artifact.content[:4] == b"RIFF" and artifact.content[8:12] == b"WEBP"
    assert item["attributes"]["converted_from"] == "heif"
    assert source.read_bytes() == original
    jobs.close()
    selections.close()


def test_media_job_image_optimize_artifact_decodes_with_exact_pixels_and_preserves_source(tmp_path):
    client, jobs, selections, _selected, _source_path = make_client(tmp_path)
    source_path = tmp_path / "unoptimized.png"
    unoptimized = io.BytesIO()
    Image.new("RGB", (80, 60), (40, 80, 120)).save(unoptimized, format="PNG", compress_level=0)
    source_path.write_bytes(unoptimized.getvalue())
    grant = selections.register_native([str(source_path)], access="read", credential="native")
    selected = next(selections.iter_files(grant["id"]))
    original = source_path.read_bytes()

    response = client.post(
        "/api/media-jobs",
        json=request_for(selected, "image-optimize", {"quality": 70, "preserveMetadata": False}),
    )
    assert response.status_code == 202
    status = client.get(response.headers["location"])
    assert status.status_code == 200
    job = status.json()
    assert job["state"] == "ready"
    assert len(job["items"]) == 1
    item = job["items"][0]
    assert item["state"] == "ready"
    assert item["outputBytes"] > 0

    artifact = client.get(f"/api/media-artifacts/{item['artifactId']}")
    assert artifact.status_code == 200
    assert artifact.headers["content-type"] == "image/png"
    assert len(artifact.content) == item["outputBytes"]
    assert artifact.content != original
    with Image.open(io.BytesIO(artifact.content)) as output:
        assert output.format == "PNG"
        assert output.size == (80, 60)
        assert output.convert("RGB").getpixel((40, 30)) == (40, 80, 120)
    assert source_path.read_bytes() == original
    jobs.close()
    selections.close()


def test_media_job_accepts_mixed_per_item_operations_and_preserves_each_original(tmp_path):
    client, jobs, selections, image_selected, image_path = make_client(tmp_path)
    image_original = image_path.read_bytes()
    pdf_path = tmp_path / "report.pdf"
    Image.new("RGB", (64, 48), (220, 220, 220)).save(pdf_path, format="PDF")
    pdf_original = pdf_path.read_bytes()
    pdf_selection = selections.register_native([str(pdf_path)], access="read", credential="native")
    pdf_selected = next(selections.iter_files(pdf_selection["id"]))

    response = client.post("/api/media-jobs", json={"items": [
        {
            "source": {"kind": "selection", "selectionId": image_selected.selection_id, "fileId": image_selected.id},
            "operations": [{"operationId": "image-optimize", "options": {"quality": 70, "preserveMetadata": False}}],
        },
        {
            "source": {"kind": "selection", "selectionId": pdf_selected.selection_id, "fileId": pdf_selected.id},
            "operations": [{"operationId": "pdf-lossless-compress", "options": {"profile": "balanced"}}],
        },
    ]})
    assert response.status_code == 202
    status = client.get(response.headers["location"]).json()
    assert status["state"] == "ready"
    assert {item["name"] for item in status["items"]} == {"camera.png", "report.pdf"}
    artifacts = {item["name"]: client.get(f"/api/media-artifacts/{item['artifactId']}").content for item in status["items"]}
    assert artifacts["camera.png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["report.pdf"].startswith(b"%PDF-")
    assert image_path.read_bytes() == image_original
    assert pdf_path.read_bytes() == pdf_original
    jobs.close()
    selections.close()


def test_media_job_pdf_crop_resolves_device_name_through_shared_operation_model(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    client, jobs, selections, _selected_image, _image_path = make_client(tmp_path)
    pdf_path = tmp_path / "device-target.pdf"
    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800))
    page.drawString(40, 700, "Searchable PDF content")
    page.save()
    pdf_path.write_bytes(pdf.getvalue())
    original = pdf_path.read_bytes()
    grant = selections.register_native([str(pdf_path)], access="read", credential="native")
    selected = next(selections.iter_files(grant["id"]))

    response = client.post("/api/media-jobs", json=request_for(
        selected, "pdf-crop", {"deviceName": "iPad Air", "pageLayout": "portrait"},
    ))
    assert response.status_code == 202
    status = client.get(response.headers["location"]).json()
    assert status["state"] == "ready"
    artifact = client.get(f"/api/media-artifacts/{status['items'][0]['artifactId']}")
    page = PdfReader(io.BytesIO(artifact.content)).pages[0]
    assert float(page.cropbox.width) / float(page.cropbox.height) == pytest.approx(41 / 59)
    assert page.extract_text().strip() == "Searchable PDF content"
    assert pdf_path.read_bytes() == original
    jobs.close()
    selections.close()


def test_media_artifact_openapi_declares_binary_media_responses(tmp_path):
    client, jobs, selections, _selected, _source_path = make_client(tmp_path)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    content = response.json()["paths"]["/api/media-artifacts/{artifact_id}"]["get"]["responses"]["200"]["content"]
    assert content["image/png"]["schema"] == {"type": "string", "format": "binary"}
    assert content["video/x-m4v"]["schema"] == {"type": "string", "format": "binary"}
    assert content["audio/flac"]["schema"] == {"type": "string", "format": "binary"}
    jobs.close()
    selections.close()


def test_screenshot_image_staging_grant_flows_to_one_media_job(tmp_path):
    client, jobs, selections, _selected, source_path = make_client(tmp_path)
    original = source_path.read_bytes()
    upload = client.post(
        "/api/media-image-stagings",
        files={"file": ("../../edited.png", original, "image/png")},
    )
    assert upload.status_code == 200
    grant = upload.json()
    assert grant["filename"] == "edited.png"
    assert grant["mediaType"] == "image/png"
    assert grant["expiresInSeconds"] == 300
    stored, _expires, claimed = jobs.image_staging_store.records[grant["stagingId"]]
    assert claimed is False
    assert Path(stored.path).read_bytes() == original
    response = client.post("/api/media-jobs", json={"items": [{
        "source": {"kind": "staged-image", "stagingId": grant["stagingId"]},
        "operations": [{"operationId": "image-resize", "options": {"maxWidth": 16, "maxHeight": 12}}],
    }]})
    assert response.status_code == 202
    status = client.get(f"/api/media-jobs/{response.json()['id']}").json()
    item = status["items"][0]
    assert status["state"] == "ready"
    assert item["inputBytes"] == len(original)
    assert item["outputBytes"] > 0
    assert grant["stagingId"] not in jobs.image_staging_store.records
    assert not Path(stored.path).exists()
    assert source_path.read_bytes() == original
    jobs.close()
    selections.close()


def test_screenshot_image_staging_rejects_invalid_data_and_single_use_delete(tmp_path):
    client, jobs, selections, _selected, _source_path = make_client(tmp_path)
    invalid = client.post("/api/media-image-stagings", files={"file": ("bad.png", b"not image", "image/png")})
    assert invalid.status_code == 422
    assert not jobs.image_staging_store.records
    output = io.BytesIO()
    Image.new("RGB", (3, 2), (120, 20, 40)).save(output, format="PNG")
    created = client.post("/api/media-image-stagings", files={"file": ("edited.png", output.getvalue(), "image/png")})
    staging_id = created.json()["stagingId"]
    assert client.delete(f"/api/media-image-stagings/{staging_id}").status_code == 204
    assert client.delete(f"/api/media-image-stagings/{staging_id}").status_code == 404
    jobs.close()
    selections.close()


def test_watermark_image_staging_flows_through_local_media_job_without_exposing_bytes(tmp_path):
    client, jobs, selections, selected, source_path = make_client(tmp_path)
    original = source_path.read_bytes()
    mark = io.BytesIO()
    Image.new("RGBA", (20, 10), (250, 10, 20, 255)).save(mark, format="PNG")
    staged = client.post(
        "/api/media-watermark-stagings",
        files={"file": ("../../brand.png", mark.getvalue(), "image/png")},
    )
    assert staged.status_code == 200
    grant = staged.json()
    assert grant["filename"] == "brand.png"
    assert grant["sizeBytes"] == len(mark.getvalue())
    assert "path" not in grant and "data" not in grant
    job = client.post("/api/media-jobs", json={
        **request_for(selected),
        "watermarkStagingId": grant["stagingId"],
        "items": [{
            **request_for(selected)["items"][0],
            "operations": [{"operationId": "image-watermark-overlay", "options": {
                "placement": "top-left", "marginPercent": 0,
                "sizePercent": 20, "opacityPercent": 100,
            }}],
        }],
    })
    assert job.status_code == 202, job.json()
    status = client.get(f"/api/media-jobs/{job.json()['id']}").json()
    assert status["state"] == "ready"
    artifact_id = status["items"][0]["artifactId"]
    with Image.open(io.BytesIO(client.get(f"/api/media-artifacts/{artifact_id}").content)) as output:
        assert output.getpixel((5, 5))[:3] == (250, 10, 20)
        assert output.getpixel((50, 40))[:3] == (40, 80, 120)
    assert source_path.read_bytes() == original
    assert grant["stagingId"] not in jobs.watermark_staging_store.records
    jobs.close()
    selections.close()


def test_watermark_overlay_requires_upload_and_rejects_oversized_staging(tmp_path):
    client, jobs, selections, selected, _source_path = make_client(tmp_path)
    invalid = client.post("/api/media-jobs", json={
        **request_for(selected),
        "items": [{
            **request_for(selected)["items"][0],
            "operations": [{"operationId": "image-watermark-overlay", "options": {}}],
        }],
    })
    assert invalid.status_code == 422
    oversized = client.post(
        "/api/media-watermark-stagings",
        files={"file": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 413
    jobs.close()
    selections.close()


def test_media_capabilities_disclose_every_operation_and_current_unavailable_adapters(tmp_path):
    client, jobs, selections, _selected, _source_path = make_client(tmp_path)
    response = client.get("/api/media-capabilities")
    assert response.status_code == 200
    payload = response.json()
    operations = {operation["id"]: operation for media in payload["media"] for operation in media["operations"]}
    assert len(operations) == 28
    assert operations["image-optimize"]["available"] is True
    from officekit.engines.engine_file_converter import avif_encoder_available
    from officekit.engines.engine_file_converter import jxl_encoder_available
    assert ("avif" in operations["image-convert"]["formats"]) is avif_encoder_available()
    assert ("avif" in operations["image-optimize"]["formats"]) is avif_encoder_available()
    assert ("avif" in operations["image-fit-size"]["formats"]) is avif_encoder_available()
    assert ("avif" in operations["image-resize"]["formats"]) is avif_encoder_available()
    assert ("avif" in operations["image-strip-metadata"]["formats"]) is avif_encoder_available()
    for operation_id in ("image-crop", "image-watermark", "image-watermark-overlay"):
        assert "avif" not in operations[operation_id]["formats"]
    assert ("jxl" in operations["image-convert"]["formats"]) is jxl_encoder_available()
    assert ("jxl" in operations["image-optimize"]["formats"]) is jxl_encoder_available()
    assert ("jxl" in operations["image-fit-size"]["formats"]) is jxl_encoder_available()
    assert ("jxl" in operations["image-resize"]["formats"]) is jxl_encoder_available()
    assert ("jxl" in operations["image-strip-metadata"]["formats"]) is jxl_encoder_available()
    for operation_id in ("image-crop", "image-watermark", "image-watermark-overlay"):
        assert "jxl" not in operations[operation_id]["formats"]
    assert operations["image-watermark-overlay"]["available"] is True
    assert operations["pdf-lossless-compress"]["available"] is True
    assert operations["pdf-visual-optimize"]["available"] is True
    assert operations["pdf-fit-size"]["available"] is True
    assert operations["pdf-crop"]["available"] is True
    assert operations["pdf-uncrop"]["available"] is True
    from officekit.engines.engine_media_native import native_audio_format_available, native_av1_encoder_available, native_media_operation_available
    assert operations["video-optimize"]["available"] is native_media_operation_available("video-optimize")
    assert operations["video-fit-size"]["available"] is native_media_operation_available("video-fit-size")
    for operation_id in ("video-optimize", "video-fit-size"):
        assert ("av1" in operations[operation_id]["formats"]) is native_av1_encoder_available()
    assert operations["video-hevc-convert"]["available"] is native_media_operation_available("video-hevc-convert")
    if operations["video-hevc-convert"]["available"]:
        assert operations["video-hevc-convert"]["formats"] == ["mov"]
    assert operations["video-speed"]["available"] is native_media_operation_available("video-speed")
    assert operations["video-mute"]["available"] is native_media_operation_available("video-mute")
    assert operations["video-strip-metadata"]["available"] is native_media_operation_available("video-strip-metadata")
    assert operations["video-crop"]["available"] is native_media_operation_available("video-crop")
    assert operations["video-to-gif"]["available"] is native_media_operation_available("video-to-gif")
    if operations["video-speed"]["available"]:
        assert operations["video-speed"]["formats"] == ["mov"]
    if operations["video-crop"]["available"]:
        assert operations["video-crop"]["formats"] == ["mov"]
    if operations["video-to-gif"]["available"]:
        assert operations["video-to-gif"]["formats"] == ["gif"]
    assert operations["audio-convert"]["available"] is native_media_available("audio")
    assert operations["audio-normalize"]["available"] is native_media_operation_available("audio-normalize")
    if operations["audio-normalize"]["available"]:
        assert operations["audio-normalize"]["formats"] == ["m4a"]
    assert operations["audio-artwork"]["available"] is native_media_operation_available("audio-artwork")
    if operations["audio-artwork"]["available"]:
        assert operations["audio-artwork"]["formats"] == ["m4a"]
    if operations["audio-convert"]["available"]:
        assert ("flac" in operations["audio-convert"]["formats"]) is native_audio_format_available("flac")
    jobs.close()
    selections.close()


def test_media_job_routes_reject_invalid_dtos_and_map_missing_or_unsafe_authority(tmp_path):
    client, jobs, selections, selected, _source_path = make_client(tmp_path)
    invalid = request_for(selected)
    invalid["tenant_id"] = "client-controlled"
    assert client.post("/api/media-jobs", json=invalid).status_code == 422
    stale = request_for(selected)
    stale["items"][0]["source"]["selectionId"] = "123e4567-e89b-42d3-a456-426614174099"
    assert client.post("/api/media-jobs", json=stale).status_code == 404
    imported = request_for(selected)
    imported["items"][0]["source"] = {"kind": "import", "importId": "123e4567-e89b-42d3-a456-426614174099"}
    unavailable = client.post("/api/media-jobs", json=imported)
    assert unavailable.status_code == 503
    assert "not available" in unavailable.json()["detail"]
    assert client.get("/api/media-jobs/not-a-uuid").status_code == 404
    assert client.get(f"/api/media-artifacts/{selected.id}").status_code == 404
    assert client.post("/api/media-jobs/not-a-uuid/cancellations", json={}).status_code == 404
    jobs.close()
    selections.close()


def test_media_job_routes_map_limits_and_queue_conflicts(tmp_path, monkeypatch):
    client, jobs, selections, selected, _source_path = make_client(tmp_path)
    monkeypatch.setattr(jobs, "submit", lambda _request: (_ for _ in ()).throw(MediaJobCapacityError("secret queue")))
    response = client.post("/api/media-jobs", json=request_for(selected))
    assert response.status_code == 503
    assert "secret" not in response.text
    monkeypatch.setattr(jobs, "submit", lambda _request: (_ for _ in ()).throw(MediaInputTooLargeError("secret input")))
    response = client.post("/api/media-jobs", json=request_for(selected))
    assert response.status_code == 413
    assert "secret" not in response.text
    monkeypatch.setattr(jobs, "submit", lambda _request: (_ for _ in ()).throw(PermissionError("private path")))
    assert client.post("/api/media-jobs", json=request_for(selected)).status_code == 403
    monkeypatch.setattr(jobs, "submit", lambda _request: (_ for _ in ()).throw(ValueError("private validation detail")))
    response = client.post("/api/media-jobs", json=request_for(selected))
    assert response.status_code == 422
    assert "private validation" not in response.text
    jobs.close()
    selections.close()
