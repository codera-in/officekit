import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from datetime import datetime

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from PIL import Image
import pytest

from officekit.engines.engine_media_pipelines import MediaPipelineCreate, MediaPipelineStore
import officekit.media_mcp as media_mcp
from officekit.media_mcp import MediaPrepareInput, _prepare_files, rename_pipeline, server


def test_mcp_discovers_operations_and_prepares_local_copy_without_overwrite(tmp_path, monkeypatch):
    from officekit.engines.engine_media_operation_defaults import MediaOperationDefaultsStore

    defaults_store = MediaOperationDefaultsStore(str(tmp_path / "settings" / "media-operation-defaults.json"))
    monkeypatch.setattr("officekit.media_mcp._operation_defaults_store", lambda: defaults_store)
    pipeline_store = MediaPipelineStore(str(tmp_path / "settings" / "media-pipelines.json"))
    monkeypatch.setattr("officekit.media_mcp._pipeline_store", lambda: pipeline_store)
    source = tmp_path / "photo.png"
    output = tmp_path / "prepared"
    Image.new("RGB", (32, 24), (30, 80, 140)).save(source, format="PNG")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    async def exercise():
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == {
                "officekit_media_list_operations",
                "officekit_media_prepare_files",
                "officekit_media_run_preset",
                "officekit_media_list_pipelines",
                "officekit_media_create_pipeline",
                "officekit_media_rename_pipeline",
                "officekit_media_update_pipeline",
                "officekit_media_run_pipeline",
                "officekit_media_delete_pipeline",
                "officekit_media_list_preset_zones",
                "officekit_media_create_preset_zone",
                "officekit_media_rename_preset_zone",
                "officekit_media_rebind_preset_zone",
                "officekit_media_delete_preset_zone",
                "officekit_media_list_operation_defaults",
                "officekit_media_set_operation_default",
                "officekit_media_clear_operation_defaults",
                "officekit_media_list_pipeline_triggers",
                "officekit_media_set_pipeline_trigger",
                "officekit_media_clear_pipeline_trigger",
            }
            preset_tool = next(tool for tool in tools.tools if tool.name == "officekit_media_run_preset")
            assert set(preset_tool.input_schema["properties"]["preset"]["enum"]) == {
                "optimize-image", "optimize-media", "to-webp", "sort-screenshots",
                "downscale-image", "downscale-video", "downscale-audio", "crop-aspect", "audio-to-mp3", "video-to-gif", "video-2x-silent", "uncrop-pdf",
            }

            saved_default = await client.call_tool("officekit_media_set_operation_default", {
                "operation_id": "image-optimize", "options": {"quality": 71, "preserveMetadata": False},
            })
            assert not saved_default.is_error
            assert json.loads(saved_default.content[0].text)["options"] == {"quality": 71, "preserveMetadata": False}
            listed_defaults = await client.call_tool("officekit_media_list_operation_defaults", {})
            assert json.loads(listed_defaults.content[0].text) == {"image-optimize": {"quality": 71, "preserveMetadata": False}}
            cleared_defaults = await client.call_tool("officekit_media_clear_operation_defaults", {})
            assert json.loads(cleared_defaults.content[0].text) == {"state": "cleared"}

            pipeline = await client.call_tool("officekit_media_create_pipeline", {"definition": {
                "name": "Clipboard WebP", "media": "image",
                "operations": [{"operationId": "image-convert", "options": {"targetFormat": "webp"}}],
            }})
            assert not pipeline.is_error
            pipeline_id = json.loads(pipeline.content[0].text)["id"]
            pinned = await client.call_tool("officekit_media_set_pipeline_trigger", {
                "trigger": "clipboard", "pipeline_id": pipeline_id,
            })
            assert not pinned.is_error
            assert json.loads(pinned.content[0].text) == {"trigger": "clipboard", "pipelineId": pipeline_id}
            bindings = await client.call_tool("officekit_media_list_pipeline_triggers", {})
            assert json.loads(bindings.content[0].text) == {"clipboard": pipeline_id}
            blocked_delete = await client.call_tool("officekit_media_delete_pipeline", {"pipeline_id": pipeline_id})
            assert blocked_delete.is_error
            unpinned = await client.call_tool("officekit_media_clear_pipeline_trigger", {"trigger": "clipboard"})
            assert json.loads(unpinned.content[0].text) == {"trigger": "clipboard", "state": "cleared"}
            deleted_pipeline = await client.call_tool("officekit_media_delete_pipeline", {"pipeline_id": pipeline_id})
            assert not deleted_pipeline.is_error

            catalog = await client.call_tool("officekit_media_list_operations", {})
            assert not catalog.is_error
            assert "image-convert" in str(catalog.content)

            arguments = {
                "files": [str(source)],
                "operations": [{"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 75}}],
                "output_directory": str(output),
            }
            result = await client.call_tool("officekit_media_prepare_files", arguments)
            assert not result.is_error, result.content[0].text
            assert (output / "photo-optimized.webp").read_bytes().startswith(b"RIFF")
            assert source.exists()
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

            downscale_source = tmp_path / "downscale.png"
            Image.new("RGB", (32, 24), (30, 80, 140)).save(downscale_source)
            downscale_original = hashlib.sha256(downscale_source.read_bytes()).hexdigest()
            downscale_output = tmp_path / "downscaled"
            downscaled = await client.call_tool("officekit_media_run_preset", {
                "files": [str(downscale_source)],
                "preset": "downscale-image",
                "factor": 0.5,
                "output_directory": str(downscale_output),
            })
            assert not downscaled.is_error, downscaled.content[0].text
            with Image.open(downscale_output / "downscale-optimized.png") as image:
                assert image.size == (16, 12)
            assert hashlib.sha256(downscale_source.read_bytes()).hexdigest() == downscale_original

            video_args = {}
            def capture_video_preset(arguments, *, stdout, stderr):
                video_args["arguments"] = arguments
                stdout.write(json.dumps({"state": "complete", "results": [{"input": "clip.mov", "output": "clip-optimized.mov"}]}))
                return 0
            with monkeypatch.context() as video_preset_patch:
                video_preset_patch.setattr(media_mcp, "run_media_cli", capture_video_preset)
                video_downscale = await client.call_tool("officekit_media_run_preset", {
                    "files": [str(tmp_path / "clip.mov")],
                    "preset": "downscale-video",
                    "factor": 0.5,
                    "output_directory": str(tmp_path / "video-downscale"),
                })
            assert not video_downscale.is_error, video_downscale.content[0].text
            assert video_args["arguments"][:2] == ["--preset", "downscale-video"]
            assert video_args["arguments"][video_args["arguments"].index("--factor") + 1] == "0.5"

            audio_args = {}
            def capture_audio_preset(arguments, *, stdout, stderr):
                audio_args["arguments"] = arguments
                stdout.write(json.dumps({"state": "complete", "results": [{"input": "voice.wav", "output": "voice-optimized.m4a"}]}))
                return 0
            with monkeypatch.context() as audio_preset_patch:
                audio_preset_patch.setattr(media_mcp, "run_media_cli", capture_audio_preset)
                audio_downscale = await client.call_tool("officekit_media_run_preset", {
                    "files": [str(tmp_path / "voice.wav")],
                    "preset": "downscale-audio",
                    "factor": 0.5,
                    "output_directory": str(tmp_path / "audio-downscale"),
                })
            assert not audio_downscale.is_error, audio_downscale.content[0].text
            assert audio_args["arguments"][:2] == ["--preset", "downscale-audio"]
            assert audio_args["arguments"][audio_args["arguments"].index("--factor") + 1] == "0.5"

            crop_args = {}
            def capture_crop_preset(arguments, *, stdout, stderr):
                crop_args["arguments"] = arguments
                stdout.write(json.dumps({"state": "complete", "results": [{"input": "photo.png", "output": "photo-optimized.png"}]}))
                return 0
            with monkeypatch.context() as crop_preset_patch:
                crop_preset_patch.setattr(media_mcp, "run_media_cli", capture_crop_preset)
                cropped = await client.call_tool("officekit_media_run_preset", {
                    "files": [str(downscale_source)],
                    "preset": "crop-aspect",
                    "aspect_ratio": "16:9",
                    "output_directory": str(tmp_path / "crop-aspect"),
                })
            assert not cropped.is_error, cropped.content[0].text
            assert crop_args["arguments"][:2] == ["--preset", "crop-aspect"]
            assert crop_args["arguments"][crop_args["arguments"].index("--aspect-ratio") + 1] == "16:9"

            missing_factor = await client.call_tool("officekit_media_run_preset", {
                "files": [str(downscale_source)],
                "preset": "downscale-image",
                "output_directory": str(tmp_path / "missing-factor"),
            })
            assert missing_factor.is_error

            preset_output = tmp_path / "preset-output"
            preset = await client.call_tool("officekit_media_run_preset", {
                "files": [str(source)],
                "preset": "to-webp",
                "output_directory": str(preset_output),
            })
            assert not preset.is_error, preset.content[0].text
            assert (preset_output / "photo-optimized.webp").read_bytes().startswith(b"RIFF")
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

            pdf_source = Path(__file__).parent / "fixtures" / "pdf-page-management-source.pdf"
            pdf_source_hash = hashlib.sha256(pdf_source.read_bytes()).hexdigest()
            pdf_output = tmp_path / "uncropped-pdfs"
            uncropped = await client.call_tool("officekit_media_run_preset", {
                "files": [str(pdf_source)],
                "preset": "uncrop-pdf",
                "output_directory": str(pdf_output),
            })
            assert not uncropped.is_error, uncropped.content[0].text
            assert (pdf_output / "pdf-page-management-source-uncropped.pdf").read_bytes().startswith(b"%PDF-")
            assert hashlib.sha256(pdf_source.read_bytes()).hexdigest() == pdf_source_hash

            screenshot = tmp_path / "Screenshot 2025-06-15.png"
            Image.new("RGB", (24, 18), (80, 120, 160)).save(screenshot)
            capture_time = datetime(2025, 6, 15, 12, 0).timestamp()
            os.utime(screenshot, (capture_time, capture_time))
            screenshot_hash = hashlib.sha256(screenshot.read_bytes()).hexdigest()
            sorted_output = tmp_path / "sorted-screenshots"
            sorted_result = await client.call_tool("officekit_media_run_preset", {
                "files": [str(screenshot)],
                "preset": "sort-screenshots",
                "output_directory": str(sorted_output),
            })
            assert not sorted_result.is_error, sorted_result.content[0].text
            assert (sorted_output / "25" / "06" / "Screenshot 2025-06-15.png").is_file()
            assert hashlib.sha256(screenshot.read_bytes()).hexdigest() == screenshot_hash

            invalid_preset = await client.call_tool("officekit_media_run_preset", {
                "files": [str(source)],
                "preset": "run-arbitrary-script",
                "output_directory": str(tmp_path / "invalid-preset"),
            })
            assert invalid_preset.is_error

            collision = await client.call_tool("officekit_media_prepare_files", arguments)
            assert collision.is_error
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

            invalid = {**arguments, "operations": [{"operationId": "image-run-script", "options": {}}]}
            rejected = await client.call_tool("officekit_media_prepare_files", invalid)
            assert rejected.is_error

    asyncio.run(exercise())


def test_mcp_creates_and_lists_strict_paused_local_pipelines(tmp_path, monkeypatch):
    store = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    monkeypatch.setattr("officekit.media_mcp._pipeline_store", lambda: store)
    definition = {
        "name": "Web ready",
        "media": "image",
        "operations": [{"operationId": "image-resize", "options": {"maxWidth": 1600, "maxHeight": 1200}}],
        "outputNameTemplate": "{name}-web.{ext}",
    }
    store.create(MediaPipelineCreate.model_validate({
        **definition,
        "name": "Archive",
    }))
    source = tmp_path / "photo.png"
    Image.new("RGB", (20, 16), (40, 80, 120)).save(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output_directory = tmp_path / "pipeline-output"

    async def exercise():
        async with Client(server) as client:
            created = await client.call_tool("officekit_media_create_pipeline", {"definition": definition})
            assert not created.is_error, created.content[0].text
            assert "paused" in created.content[0].text
            assert "image-resize" in created.content[0].text

            listed = await client.call_tool("officekit_media_list_pipelines", {})
            assert not listed.is_error
            assert any("Web ready" in item.text for item in listed.content)
            recipe = next(item for item in store.list() if item["name"] == "Web ready")
            original_operations = recipe["operations"]

            prepared = await client.call_tool("officekit_media_run_pipeline", {
                "pipeline_id": recipe["id"],
                "files": [str(source)],
                "output_directory": str(output_directory),
            })
            assert not prepared.is_error, prepared.content[0].text
            assert [item.name for item in output_directory.iterdir()] == ["photo-web.png"]
            assert json.loads(prepared.content[0].text)["results"][0]["output"] == "photo-web.png"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
            collision = await client.call_tool("officekit_media_run_pipeline", {
                "pipeline_id": recipe["id"],
                "files": [str(source)],
                "output_directory": str(output_directory),
            })
            assert collision.is_error
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

            renamed = await client.call_tool("officekit_media_rename_pipeline", {
                "pipeline_id": recipe["id"],
                "name": "Web production",
            })
            assert not renamed.is_error, renamed.content[0].text
            assert "Web production" in renamed.content[0].text
            renamed_recipe = next(item for item in store.list() if item["id"] == recipe["id"])
            assert renamed_recipe["operations"] == original_operations
            assert renamed_recipe["state"] == "paused"

            updated = await client.call_tool("officekit_media_update_pipeline", {
                "pipeline_id": recipe["id"],
                "definition": {
                    "name": "Web production",
                    "media": "image",
                    "operations": [{"operationId": "image-strip-metadata", "options": {}}],
                },
            })
            assert not updated.is_error, updated.content[0].text
            updated_recipe = next(item for item in store.list() if item["id"] == recipe["id"])
            assert updated_recipe["name"] == "Web production"
            assert updated_recipe["state"] == "paused"
            assert updated_recipe["operations"] != original_operations
            duplicate_update = await client.call_tool("officekit_media_update_pipeline", {
                "pipeline_id": recipe["id"],
                "definition": {"name": "Archive", "media": "image", "operations": original_operations},
            })
            assert duplicate_update.is_error
            missing_update = await client.call_tool("officekit_media_update_pipeline", {
                "pipeline_id": "00000000-0000-0000-0000-000000000000",
                "definition": {"name": "Missing", "media": "image", "operations": original_operations},
            })
            assert missing_update.is_error
            media_change = await client.call_tool("officekit_media_update_pipeline", {
                "pipeline_id": recipe["id"],
                "definition": {
                    "name": "Web production", "media": "video",
                    "operations": [{"operationId": "video-mute", "options": {}}],
                },
            })
            assert media_change.is_error

            duplicate_rename = await client.call_tool("officekit_media_rename_pipeline", {
                "pipeline_id": recipe["id"],
                "name": "archive",
            })
            assert duplicate_rename.is_error
            missing_rename = await client.call_tool("officekit_media_rename_pipeline", {
                "pipeline_id": "00000000-0000-0000-0000-000000000000",
                "name": "Missing",
            })
            assert missing_rename.is_error

            duplicate = await client.call_tool("officekit_media_create_pipeline", {
                "definition": {**definition, "name": "Web production"},
            })
            assert duplicate.is_error
            invalid = await client.call_tool("officekit_media_create_pipeline", {
                "definition": {**definition, "operations": [{"operationId": "run-script", "options": {}}]},
            })
            assert invalid.is_error
            assert renamed_recipe["state"] == "paused"

    asyncio.run(exercise())


def test_mcp_typed_smart_crop_uses_the_current_pipeline_image(tmp_path, monkeypatch):
    from officekit.engines import engine_media_native as native

    source = tmp_path / "photo.png"
    Image.new("RGB", (200, 100), (20, 120, 200)).save(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "smart-crop-output"
    probes = []

    def saliency(path, kind, **_kwargs):
        assert kind == "image"
        with Image.open(path) as current:
            probes.append(current.size)
            width, height = current.size
        return {"sourceWidth": width, "sourceHeight": height, "detected": False,
                "x": 0.5, "y": 0.5, "width": 0.0, "height": 0.0}

    monkeypatch.setattr(native, "probe_smart_crop_bounds", saliency)

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("officekit_media_prepare_files", {
                "files": [str(source)], "output_directory": str(output),
                "operations": [
                    {"operationId": "image-resize", "options": {"maxWidth": 80, "maxHeight": 80}},
                    {"operationId": "image-crop", "options": {"aspectRatio": "1:1", "smartCrop": True}},
                ],
            })
            assert not result.is_error
            item = json.loads(result.content[0].text)["results"][0]
            with Image.open(output / item["output"]) as prepared:
                assert prepared.size == (40, 40)
            assert item["attributes"]["smart_crop"] is True
            assert item["attributes"]["saliency_detected"] is False

    asyncio.run(exercise())
    assert probes == [(80, 40)]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_mcp_pdf_crop_resolves_device_name_through_shared_operation_model(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    source = tmp_path / "book.pdf"
    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800))
    page.drawString(40, 700, "Keep this searchable")
    page.save()
    source.write_bytes(pdf.getvalue())
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "device-crop-output"

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("officekit_media_prepare_files", {
                "files": [str(source)],
                "operations": [{"operationId": "pdf-crop", "options": {"deviceName": "iPad Air"}}],
                "output_directory": str(output),
            })
            assert not result.is_error, result.content[0].text
            output_name = json.loads(result.content[0].text)["results"][0]["output"]
            cropped = PdfReader(output / output_name).pages[0]
            assert float(cropped.cropbox.width) / float(cropped.cropbox.height) == pytest.approx(41 / 59)
            assert cropped.extract_text().strip() == "Keep this searchable"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

    asyncio.run(exercise())


def test_mcp_prepare_files_routes_video_metadata_removal_through_typed_cli(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"local video")
    params = MediaPrepareInput.model_validate({
        "files": [str(source)],
        "operations": [{"operationId": "video-strip-metadata", "options": {}}],
        "output_directory": str(tmp_path / "prepared"),
    })
    captured = {}

    def run_cli(arguments, *, stdout, stderr):
        recipe = Path(arguments[arguments.index("--recipe") + 1])
        captured["recipe"] = json.loads(recipe.read_text(encoding="utf-8"))
        captured["arguments"] = arguments
        stdout.write(json.dumps({"state": "complete", "results": [{
            "input": "clip.mov", "output": "clip-optimized.mov",
        }]}))
        return 0

    monkeypatch.setattr(media_mcp, "run_media_cli", run_cli)
    result = media_mcp._prepare_files(params)
    assert captured["recipe"] == [{"operationId": "video-strip-metadata", "options": {}}]
    assert captured["arguments"][-2:] == ["--", str(source)]
    assert result["results"][0]["output"] == "clip-optimized.mov"


def test_mcp_image_overlay_accepts_separate_local_logo_and_preserves_original(tmp_path):
    source = tmp_path / "photo.png"
    watermark = tmp_path / "logo.png"
    output = tmp_path / "prepared"
    Image.new("RGB", (100, 80), (20, 80, 180)).save(source, format="PNG")
    Image.new("RGBA", (20, 10), (250, 10, 20, 255)).save(watermark, format="PNG")
    original = source.read_bytes()

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("officekit_media_prepare_files", {
                "files": [str(source)],
                "operations": [{"operationId": "image-watermark-overlay", "options": {
                    "placement": "top-left", "marginPercent": 0,
                    "sizePercent": 20, "opacityPercent": 100,
                }}],
                "output_directory": str(output),
                "watermark_image": str(watermark),
            })
            assert not result.is_error, result.content[0].text
            with Image.open(output / "photo-optimized.png") as prepared:
                assert prepared.getpixel((5, 5))[:3] == (250, 10, 20)
                assert prepared.getpixel((50, 40))[:3] == (20, 80, 180)
            assert source.read_bytes() == original

    asyncio.run(exercise())


def test_mcp_job_errors_do_not_disclose_local_paths(monkeypatch, tmp_path):
    private_path = "/Users/private/customer/source.png"

    def fail_with_path(arguments, stdout, stderr):
        stderr.write(f"could not open {private_path}")
        return 2

    monkeypatch.setattr("officekit.media_mcp.run_media_cli", fail_with_path)
    params = MediaPrepareInput.model_validate({
        "files": [private_path],
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
        "output_directory": str(tmp_path / "output"),
    })
    try:
        _prepare_files(params)
    except ValueError as error:
        assert private_path not in str(error)
        assert str(error) == "The local media job failed. Check the files and recipe, then retry."
    else:
        raise AssertionError("Expected sanitized job failure")


def test_mcp_rename_size_overflow_returns_bounded_error_and_preserves_store(tmp_path, monkeypatch):
    import officekit.engines.engine_media_pipelines as pipeline_module

    path = tmp_path / "pipelines.json"
    store = MediaPipelineStore(str(path))
    recipe = store.create(MediaPipelineCreate.model_validate({
        "name": "Before",
        "media": "image",
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
    }))
    original = path.read_bytes()
    monkeypatch.setattr("officekit.media_mcp._pipeline_store", lambda: store)
    monkeypatch.setattr(pipeline_module, "MAX_PIPELINE_FILE_BYTES", len(original) + 1)

    with pytest.raises(ValueError, match="local configuration size"):
        asyncio.run(rename_pipeline(recipe["id"], "An expanded pipeline name"))
    assert path.read_bytes() == original


def test_mcp_manages_preset_bindings_and_guards_pipeline_deletion(tmp_path, monkeypatch):
    from officekit.engines.engine_media_preset_zones import MediaPresetZoneStore

    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    zones = MediaPresetZoneStore(pipelines, str(tmp_path / "settings" / "zones.json"))
    monkeypatch.setattr("officekit.media_mcp._pipeline_store", lambda: pipelines)
    monkeypatch.setattr("officekit.media_mcp._preset_zone_store", lambda: zones)
    definition = MediaPipelineCreate.model_validate({
        "name": "Share copy",
        "media": "image",
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
    })
    pipeline = pipelines.create(definition)
    replacement = pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Archive copy",
        "media": "image",
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
    }))

    async def exercise():
        async with Client(server) as client:
            created = await client.call_tool("officekit_media_create_preset_zone", {
                "name": "Clean Images",
                "pipeline_id": pipeline["id"],
            })
            assert not created.is_error, created.content[0].text
            zone = json.loads(created.content[0].text)
            assert zone["enabled"] is False
            assert zone["pipelineId"] == pipeline["id"]

            renamed = await client.call_tool("officekit_media_rename_preset_zone", {
                "zone_id": zone["id"],
                "name": "Clean Images Renamed",
            })
            assert not renamed.is_error
            renamed_zone = json.loads(renamed.content[0].text)
            assert renamed_zone["id"] == zone["id"]
            assert renamed_zone["pipelineId"] == pipeline["id"]
            assert renamed_zone["state"] == "renamed"
            assert "enabled" not in renamed_zone

            rebound = await client.call_tool("officekit_media_rebind_preset_zone", {
                "zone_id": zone["id"],
                "pipeline_id": replacement["id"],
            })
            assert not rebound.is_error, rebound.content[0].text
            rebound_zone = json.loads(rebound.content[0].text)
            assert rebound_zone["id"] == zone["id"]
            assert rebound_zone["name"] == renamed_zone["name"]
            assert rebound_zone["pipelineId"] == replacement["id"]
            assert rebound_zone["state"] == "rebound"
            assert "enabled" not in rebound_zone

            listed = await client.call_tool("officekit_media_list_preset_zones", {})
            assert not listed.is_error
            assert "Clean Images Renamed" in listed.content[0].text
            assert "enabled" not in listed.content[0].text

            blocked = await client.call_tool("officekit_media_delete_pipeline", {
                "pipeline_id": replacement["id"],
            })
            assert blocked.is_error
            assert any(item["id"] == replacement["id"] for item in pipelines.list())

            removed_zone = await client.call_tool("officekit_media_delete_preset_zone", {
                "zone_id": zone["id"],
            })
            assert not removed_zone.is_error
            removed_pipeline = await client.call_tool("officekit_media_delete_pipeline", {
                "pipeline_id": replacement["id"],
            })
            assert not removed_pipeline.is_error
            assert not (await client.call_tool("officekit_media_delete_pipeline", {"pipeline_id": pipeline["id"]})).is_error
            assert pipelines.list() == []

            missing = await client.call_tool("officekit_media_delete_pipeline", {
                "pipeline_id": pipeline["id"],
            })
            assert missing.is_error

    asyncio.run(exercise())


def test_bundled_media_launcher_exposes_stdio_mcp_tools(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "src-tauri" / "binaries" / "officekit-media"
    if not launcher.is_file():
        return

    async def exercise():
        async with Client(StdioServerParameters(
            command=str(launcher),
            args=["--mcp-server"],
            env={**os.environ, "HOME": str(tmp_path)},
        )) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "officekit_media_list_operations",
                "officekit_media_prepare_files",
                "officekit_media_run_preset",
                "officekit_media_list_pipelines",
                "officekit_media_create_pipeline",
                "officekit_media_rename_pipeline",
                "officekit_media_update_pipeline",
                "officekit_media_run_pipeline",
                "officekit_media_delete_pipeline",
                "officekit_media_list_preset_zones",
                "officekit_media_create_preset_zone",
                "officekit_media_rename_preset_zone",
                "officekit_media_rebind_preset_zone",
                "officekit_media_delete_preset_zone",
                "officekit_media_list_operation_defaults",
                "officekit_media_set_operation_default",
                "officekit_media_clear_operation_defaults",
                "officekit_media_list_pipeline_triggers",
                "officekit_media_set_pipeline_trigger",
                "officekit_media_clear_pipeline_trigger",
            }
            created = await client.call_tool("officekit_media_create_pipeline", {"definition": {
                "name": "Packaged web images",
                "media": "image",
                "operations": [{"operationId": "image-strip-metadata", "options": {}}],
            }})
            assert not created.is_error, created.content[0].text
            saved_default = await client.call_tool("officekit_media_set_operation_default", {
                "operation_id": "image-optimize", "options": {"quality": 70},
            })
            assert not saved_default.is_error, saved_default.content[0].text
            assert "image-optimize" in (await client.call_tool("officekit_media_list_operation_defaults", {})).content[0].text
            cleared_defaults = await client.call_tool("officekit_media_clear_operation_defaults", {})
            assert json.loads(cleared_defaults.content[0].text) == {"state": "cleared"}
            listed = await client.call_tool("officekit_media_list_pipelines", {})
            assert not listed.is_error
            assert "Packaged web images" in listed.content[0].text
            source = tmp_path / "packaged.png"
            output_directory = tmp_path / "packaged-output"
            Image.new("RGB", (20, 16), (40, 80, 120)).save(source)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline_id = json.loads(created.content[0].text)["id"]
            prepared = await client.call_tool("officekit_media_run_pipeline", {
                "pipeline_id": pipeline_id,
                "files": [str(source)],
                "output_directory": str(output_directory),
            })
            assert not prepared.is_error, prepared.content[0].text
            assert list(output_directory.iterdir())
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            collision = await client.call_tool("officekit_media_run_pipeline", {
                "pipeline_id": pipeline_id,
                "files": [str(source)],
                "output_directory": str(output_directory),
            })
            assert collision.is_error
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            renamed = await client.call_tool("officekit_media_rename_pipeline", {
                "pipeline_id": pipeline_id,
                "name": "Packaged production images",
            })
            assert not renamed.is_error, renamed.content[0].text
            updated = await client.call_tool("officekit_media_update_pipeline", {
                "pipeline_id": pipeline_id,
                "definition": {
                    "name": "Packaged production images",
                    "media": "image",
                    "operations": [{"operationId": "image-resize", "options": {"maxWidth": 800, "maxHeight": 600}}],
                },
            })
            assert not updated.is_error, updated.content[0].text
            assert json.loads(updated.content[0].text)["id"] == pipeline_id
            assert json.loads(updated.content[0].text)["state"] == "paused"
            listed_after_rename = await client.call_tool("officekit_media_list_pipelines", {})
            assert "Packaged production images" in listed_after_rename.content[0].text
            zone_created = await client.call_tool("officekit_media_create_preset_zone", {
                "name": "Packaged zone",
                "pipeline_id": pipeline_id,
            })
            assert not zone_created.is_error, zone_created.content[0].text
            zone = json.loads(zone_created.content[0].text)
            assert zone["enabled"] is False
            zone_renamed = await client.call_tool("officekit_media_rename_preset_zone", {
                "zone_id": zone["id"],
                "name": "Packaged zone renamed",
            })
            assert not zone_renamed.is_error, zone_renamed.content[0].text
            zone = json.loads(zone_renamed.content[0].text)
            assert zone["id"] == json.loads(zone_created.content[0].text)["id"]
            assert zone["pipelineId"] == pipeline_id
            assert zone["state"] == "renamed"
            assert "enabled" not in zone
            rebound = await client.call_tool("officekit_media_rebind_preset_zone", {
                "zone_id": zone["id"],
                "pipeline_id": pipeline_id,
            })
            assert not rebound.is_error, rebound.content[0].text
            rebound_zone = json.loads(rebound.content[0].text)
            assert rebound_zone["pipelineId"] == pipeline_id
            assert rebound_zone["state"] == "rebound"
            assert "enabled" not in rebound_zone
            zone_listing = await client.call_tool("officekit_media_list_preset_zones", {})
            assert not zone_listing.is_error
            assert "Packaged zone renamed" in zone_listing.content[0].text
            guarded_delete = await client.call_tool("officekit_media_delete_pipeline", {
                "pipeline_id": pipeline_id,
            })
            assert guarded_delete.is_error
            removed_zone = await client.call_tool("officekit_media_delete_preset_zone", {
                "zone_id": zone["id"],
            })
            assert not removed_zone.is_error, removed_zone.content[0].text
            removed_pipeline = await client.call_tool("officekit_media_delete_pipeline", {
                "pipeline_id": pipeline_id,
            })
            assert not removed_pipeline.is_error, removed_pipeline.content[0].text

    asyncio.run(exercise())
