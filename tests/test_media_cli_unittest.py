import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

import officekit.media_cli as media_cli
from officekit.engines import engine_media_native as native
from officekit.media_cli import _collect_pdf_inputs, _preset_operations, run


def png(path):
    image = Image.new("RGB", (32, 24), (30, 80, 140))
    image.save(path, format="PNG")


def test_clop_style_named_presets_map_to_allowlisted_typed_operations():
    audio = _preset_operations("audio-to-mp3", "voice.wav")
    gif = _preset_operations("video-to-gif", "clip.mov")
    fast_silent = _preset_operations("video-2x-silent", "clip.mp4")

    assert [(item.operation_id, item.options) for item in audio] == [
        ("audio-convert", {"target_format": "mp3", "bitrate_kbps": 192}),
    ]
    assert [(item.operation_id, item.options) for item in gif] == [
        ("video-to-gif", {}),
    ]
    assert [(item.operation_id, item.options) for item in fast_silent] == [
        ("video-speed", {"factor_percent": 200}),
        ("video-mute", {}),
    ]
    downscale = _preset_operations("downscale-image", "photo.png", factor=0.5, image_dimensions=(100, 80))
    assert [(item.operation_id, item.options) for item in downscale] == [
        ("image-resize", {"max_width": 50, "max_height": 40}),
    ]
    video_downscale = _preset_operations("downscale-video", "clip.mov", factor=0.5, video_dimensions=(1920, 1080))
    assert [(item.operation_id, item.options) for item in video_downscale] == [
        ("video-resize", {"max_width": 960, "max_height": 540}),
    ]
    assert _preset_operations("downscale-video", "clip.mov", factor=1, video_dimensions=(1920, 1080)) == []
    audio_downscale = _preset_operations("downscale-audio", "voice.wav", factor=0.5, audio_bitrate_kbps=256)
    assert [(item.operation_id, item.options) for item in audio_downscale] == [
        ("audio-optimize", {"target_format": "m4a", "bitrate_kbps": 128}),
    ]
    assert _preset_operations("downscale-audio", "voice.wav", factor=1) == []
    for preset, filename in (("audio-to-mp3", "notes.txt"), ("video-to-gif", "photo.png"), ("video-2x-silent", "notes.txt"), ("downscale-image", "notes.txt"), ("downscale-video", "photo.png")):
        try:
            _preset_operations(preset, filename)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{preset} accepted unsupported input {filename}")


def test_cli_pipeline_preset_commands_manage_shared_disabled_zone_bindings(tmp_path):
    pipeline_store = media_cli.MediaPipelineStore(str(tmp_path / "pipelines.json"))
    zone_store = media_cli.MediaPresetZoneStore(pipeline_store, str(tmp_path / "preset-zones.json"))
    first = pipeline_store.create(media_cli.MediaPipelineCreate.model_validate({
        "name": "Web images", "media": "image", "operations": [
            {"operationId": "image-optimize", "options": {"quality": 82, "preserveMetadata": False}},
        ],
    }))
    second = pipeline_store.create(media_cli.MediaPipelineCreate.model_validate({
        "name": "Small images", "media": "image", "operations": [
            {"operationId": "image-resize", "options": {"maxWidth": 800, "maxHeight": 600}},
        ],
    }))

    def invoke(arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = media_cli._run_pipeline_command(
            ["preset", *arguments], stdout, stderr,
            pipeline_store=pipeline_store, preset_zone_store=zone_store,
        )
        return result, stdout.getvalue(), stderr.getvalue()

    result, created_json, error = invoke(["add", "Images", first["name"]])
    assert result == 0, error
    created = json.loads(created_json)
    assert created["enabled"] is False
    zone_id = created["id"]

    result, renamed_json, error = invoke(["rename", zone_id, "Photos"])
    assert result == 0, error
    assert json.loads(renamed_json)["name"] == "Photos"

    result, rebound_json, error = invoke(["rebind", "Photos", second["id"]])
    assert result == 0, error
    assert json.loads(rebound_json)["pipelineId"] == second["id"]

    result, listing_json, error = invoke(["list"])
    assert result == 0, error
    listing = json.loads(listing_json)
    assert listing == [{"id": zone_id, "name": "Photos", "pipelineId": second["id"]}]

    result, removed_json, error = invoke(["remove", zone_id])
    assert result == 0, error
    assert json.loads(removed_json) == {"id": zone_id, "state": "deleted"}
    assert zone_store.list_bindings() == []


@pytest.mark.parametrize(("width", "height", "ratio", "expected"), [
    (800, 600, "16:9", {"x": 0, "y": 75, "width": 800, "height": 450}),
    (1920, 1080, "1:1", {"x": 420, "y": 0, "width": 1080, "height": 1080}),
    (1920, 1080, "1.91:1", {"x": 0, "y": 37, "width": 1920, "height": 1005}),
])
def test_clop_crop_aspect_rectangle_is_centered_and_within_source(width, height, ratio, expected):
    assert media_cli._crop_rectangle(width, height, ratio) == expected


@pytest.mark.parametrize("ratio", ["", "16", "0:1", "1:0", "1:101", "nan:1", "1:1:1"])
def test_clop_crop_aspect_rejects_invalid_or_extreme_ratios(ratio):
    with pytest.raises(ValueError):
        media_cli._crop_rectangle(800, 600, ratio)


def test_cli_runs_shared_typed_pipeline_and_never_overwrites(tmp_path):
    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    png(source)
    recipe.write_text(json.dumps([{"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 75}}]))
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    assert result["results"][0]["output"] == "photo-optimized.webp"
    assert (output / "photo-optimized.webp").read_bytes().startswith(b"RIFF")
    assert source.exists()
    assert stderr.getvalue() == ""

    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], io.StringIO(), stderr) == 2
    assert source.exists()
    assert (output / "photo-optimized.webp").exists()


def test_cli_pipeline_output_name_template_is_safe_and_collision_checked(tmp_path):
    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    png(source)
    recipe.write_text(json.dumps([{"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 75}}]))
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "--recipe", str(recipe), "--output-dir", str(output),
        "--name-template", "{name}-web.{ext}", str(source),
    ], stdout, stderr) == 0
    assert json.loads(stdout.getvalue())["results"][0]["output"] == "photo-web.webp"
    assert source.exists()
    assert run([
        "--recipe", str(recipe), "--output-dir", str(output),
        "--name-template", "../{name}.{ext}", str(source),
    ], io.StringIO(), stderr) == 2
    assert (output / "photo-web.webp").exists()


def test_cli_name_template_sequence_token_increments_across_batch(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    png(first)
    png(second)
    output_dir = tmp_path / "sequenced"
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert run([
        "--preset", "optimize-image", "--output-dir", str(output_dir),
        "--name-template", "%f-%i.{ext}", str(first), str(second),
    ], stdout, stderr) == 0, stderr.getvalue()
    outputs = [item["output"] for item in json.loads(stdout.getvalue())["results"]]
    assert outputs == ["first-1.png", "second-2.png"]


def test_cli_saved_pipeline_lifecycle_runs_typed_operations_safely(tmp_path, monkeypatch):
    from officekit.engines.engine_media_pipelines import MediaPipelineStore
    from officekit.engines.engine_media_pipeline_triggers import MediaPipelineTriggerStore

    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "prepared"
    store = MediaPipelineStore(tmp_path / "pipelines.json")
    monkeypatch.setattr(media_cli, "MediaPipelineStore", lambda: store)
    monkeypatch.setattr(media_cli, "MediaPipelineTriggerStore", lambda pipelines: MediaPipelineTriggerStore(pipelines, tmp_path / "triggers.json"))
    png(source)
    original = source.read_bytes()
    recipe.write_text(json.dumps([{"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 75}}]))
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run(["pipeline", "add", "Web Export", "--media", "image", "--recipe", str(recipe)], stdout, stderr) == 0
    definition = json.loads(stdout.getvalue())
    assert definition["name"] == "Web Export"
    pipeline_id = definition["id"]
    listed = io.StringIO()
    assert run(["pipeline", "list"], listed, stderr) == 0
    assert json.loads(listed.getvalue())[0]["id"] == pipeline_id
    shown = io.StringIO()
    assert run(["pipeline", "show", "Web Export"], shown, stderr) == 0
    assert json.loads(shown.getvalue())["operations"][0]["operationId"] == "image-convert"
    prompt = io.StringIO()
    assert run(["pipeline", "prompt", "--compact"], prompt, stderr) == 0
    assert "image-convert" in json.loads(prompt.getvalue())["operationIds"]
    assert run(["pipeline", "attach", "Web Export", "--source", "drop-zone"], io.StringIO(), stderr) == 0
    run_output = io.StringIO()
    assert run(["pipeline", "run", pipeline_id, str(source), "--output-dir", str(output)], run_output, stderr) == 0
    result = json.loads(run_output.getvalue())["results"][0]
    assert result["output"] == "photo-optimized.webp"
    assert source.read_bytes() == original
    assert (output / result["output"]).is_file()

    rename_output = io.StringIO()
    assert run(["pipeline", "rename", pipeline_id, "Web Export 2"], rename_output, stderr) == 0
    assert json.loads(rename_output.getvalue())["name"] == "Web Export 2"
    detach_output = io.StringIO()
    assert run(["pipeline", "detach", "--source", "drop-zone"], detach_output, stderr) == 0
    assert json.loads(detach_output.getvalue())["cleared"] is True
    assert stderr.getvalue() == ""


def test_clop_style_cli_verbs_reuse_typed_copy_only_operations(tmp_path):
    source = tmp_path / "photo.png"
    png(source)
    original = source.read_bytes()
    errors = io.StringIO()

    converted = io.StringIO()
    assert run([
        "convert", "--operation-id", "image-convert",
        "--options-json", '{"targetFormat":"webp","quality":75}',
        "--output-dir", str(tmp_path / "converted"), str(source),
    ], converted, errors) == 0
    converted_name = json.loads(converted.getvalue())["results"][0]["output"]
    assert converted_name.endswith(".webp")

    optimized = io.StringIO()
    assert run(["optimise", "--output-dir", str(tmp_path / "optimized"), str(source)], optimized, errors) == 0
    assert json.loads(optimized.getvalue())["results"][0]["output"] == "photo-optimized.png"

    cropped = io.StringIO()
    assert run([
        "crop", "--operation-id", "image-crop", "--options-json",
        '{"x":0,"y":0,"width":16,"height":12}',
        "--output-dir", str(tmp_path / "cropped"), str(source),
    ], cropped, errors) == 0
    assert json.loads(cropped.getvalue())["results"][0]["attributes"]["width"] == 16

    scaled = io.StringIO()
    assert run([
        "downscale", "--factor", "0.5", "--output-dir", str(tmp_path / "scaled"), str(source),
    ], scaled, errors) == 0
    assert json.loads(scaled.getvalue())["results"][0]["attributes"] == {"width": 16, "height": 12}

    stripped = io.StringIO()
    assert run(["strip-exif", "--output-dir", str(tmp_path / "stripped"), str(source)], stripped, errors) == 0
    assert json.loads(stripped.getvalue())["results"][0]["attributes"]["metadata_removed"] is True
    assert run(["strip-exif", "--output-dir", str(tmp_path / "bad-strip"), str(tmp_path / "document.pdf")], io.StringIO(), errors) == 2
    assert "either supported images or supported videos" in errors.getvalue()
    assert source.read_bytes() == original


def test_clop_style_remove_audio_flag_maps_to_video_optimize_then_mute(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video fixture path")
    captured = {}

    def capture(args, recipe, stdout, stderr):
        captured["recipe"] = recipe
        return 0

    monkeypatch.setattr(media_cli, "_run_verb_recipe", capture)
    assert run(["optimise", "--remove-audio", "--output-dir", str(tmp_path / "out"), str(video)], io.StringIO(), io.StringIO()) == 0
    assert [step["operationId"] for step in captured["recipe"]] == ["video-optimize", "video-mute"]
    assert run(["optimise", "--compression", "55", "--remove-audio", "--output-dir", str(tmp_path / "compressed"), str(video)], io.StringIO(), io.StringIO()) == 0
    assert captured["recipe"] == [
        {"operationId": "video-optimize", "options": {"targetFormat": "mp4", "compression": 55}},
        {"operationId": "video-mute", "options": {}},
    ]
    errors = io.StringIO()
    assert run(["optimise", "--compression", "101", "--output-dir", str(tmp_path / "invalid"), str(video)], io.StringIO(), errors) == 2
    assert "from 5 to 100" in errors.getvalue()
    image = tmp_path / "image.png"
    png(image)
    assert run(["optimise", "--compression", "adaptive", "--output-dir", str(tmp_path / "adaptive"), str(image)], io.StringIO(), io.StringIO()) == 0
    assert captured["recipe"] == [{"operationId": "image-optimize", "options": {"compression": "adaptive"}}]
    assert run(["optimise", "--adaptive-optimisation", "--output-dir", str(tmp_path / "adaptive-format"), str(image)], io.StringIO(), io.StringIO()) == 0
    assert captured["recipe"] == [{"operationId": "image-optimize", "options": {"adaptive": True}}]
    assert run(["optimise", "--compression", "55", "--output-dir", str(tmp_path / "image-compressed"), str(image)], io.StringIO(), io.StringIO()) == 0
    assert captured["recipe"] == [{"operationId": "image-optimize", "options": {"compression": 55}}]
    errors = io.StringIO()
    assert run(["optimise", "--remove-audio", "--output-dir", str(tmp_path / "bad"), str(tmp_path / "photo.png")], io.StringIO(), errors) == 2
    assert "video files only" in errors.getvalue()


def test_strip_exif_supports_homogeneous_video_batches(tmp_path, monkeypatch):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"video fixture path")
    captured = {}

    def capture(args, recipe, stdout, stderr):
        captured["recipe"] = recipe
        return 0

    monkeypatch.setattr(media_cli, "_run_verb_recipe", capture)
    assert media_cli._run_verb_command(
        "strip-exif", ["--output-dir", str(tmp_path / "stripped"), str(video)],
        io.StringIO(), io.StringIO(),
    ) == 0
    assert captured["recipe"] == [{"operationId": "video-strip-metadata", "options": {}}]


def test_strip_exif_rejects_mixed_image_and_video_batches(tmp_path):
    image = tmp_path / "photo.png"
    video = tmp_path / "clip.mov"
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    errors = io.StringIO()
    assert media_cli._run_verb_command(
        "strip-exif", ["--output-dir", str(tmp_path / "stripped"), str(image), str(video)],
        io.StringIO(), errors,
    ) == 2
    assert "either supported images or supported videos" in errors.getvalue()


def test_clop_style_video_downscale_uses_video_resize_and_preserves_source(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"bounded video fixture")
    original = source.read_bytes()
    captured = {}
    monkeypatch.setattr(media_cli, "probe_video_dimensions", lambda _path: (160, 120))

    def execute(data, filename, operations, **_kwargs):
        captured["operations"] = operations
        assert data == original
        assert filename == source.name
        return SimpleNamespace(data=b"resized video copy", extension="mov", attributes={"max_width": 80, "max_height": 60})

    monkeypatch.setattr(media_cli.MediaOptimizerEngine, "execute", execute)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["downscale", "--factor", "0.5", "--output-dir", str(tmp_path / "out"), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert result["output"] == "clip-optimized.mov"
    assert captured["operations"][0].operation_id == "video-resize"
    assert captured["operations"][0].options == {"max_width": 80, "max_height": 60}
    assert (tmp_path / "out" / result["output"]).read_bytes() == b"resized video copy"
    assert source.read_bytes() == original


def test_clop_style_video_downscale_factor_one_copies_identical_bytes_without_probe(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    original = b"identity video bytes"
    source.write_bytes(original)
    monkeypatch.setattr(media_cli, "probe_video_dimensions", lambda _path: pytest.fail("factor one should not probe video metadata"))
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["downscale", "--factor", "1", "--output-dir", str(tmp_path / "out"), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert result["attributes"] == {"no_op": True}
    assert (tmp_path / "out" / result["output"]).read_bytes() == original
    assert source.read_bytes() == original


def test_clop_style_audio_downscale_uses_measured_average_bitrate_and_preserves_source(tmp_path, monkeypatch):
    source = tmp_path / "voice.wav"
    original = b"x" * 256_000
    source.write_bytes(original)
    captured = {}
    monkeypatch.setattr(media_cli, "probe_audio_duration", lambda path: 8.0 if Path(path).name == "source.wav" else pytest.fail("unexpected probe source"))

    def fake_convert(path, filename, operation_id, options, workspace):
        captured.update(operation_id=operation_id, options=options, filename=filename)
        output = Path(workspace) / "prepared.m4a"
        output.write_bytes(b"optimized audio copy")
        return str(output), "m4a", "audio/mp4", {}, output.stat().st_size

    monkeypatch.setattr(media_cli, "convert_native_media_to_file", fake_convert)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["downscale", "--factor", "0.5", "--output-dir", str(tmp_path / "out"), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert captured["operation_id"] == "audio-optimize"
    assert captured["options"] == {"target_format": "m4a", "bitrate_kbps": 128}
    assert captured["filename"] == source.name
    assert (tmp_path / "out" / result["output"]).read_bytes() == b"optimized audio copy"
    assert source.read_bytes() == original


def test_clop_style_audio_downscale_factor_one_copies_identical_bytes_without_probe(tmp_path, monkeypatch):
    source = tmp_path / "voice.wav"
    original = b"identity audio bytes"
    source.write_bytes(original)
    monkeypatch.setattr(media_cli, "probe_audio_duration", lambda _path: pytest.fail("factor one should not probe audio metadata"))
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["downscale", "--factor", "1", "--output-dir", str(tmp_path / "out"), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert result["attributes"] == {"no_op": True}
    assert (tmp_path / "out" / result["output"]).read_bytes() == original
    assert source.read_bytes() == original


def test_clop_crop_aspect_preset_crops_to_centered_ratio_and_preserves_source(tmp_path):
    source = tmp_path / "photo.png"
    png(source)
    original = source.read_bytes()
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "crop", "--aspect-ratio", "16:9", "--output-dir", str(tmp_path / "out"), str(source),
    ], stdout, stderr) == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())["results"][0]
    with Image.open(tmp_path / "out" / result["output"]) as image:
        assert image.size == (32, 18)
    assert source.read_bytes() == original


def test_clop_crop_aspect_preset_crops_video_through_typed_operation(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"x" * 5000)
    original = source.read_bytes()
    captured = {}
    monkeypatch.setattr(media_cli, "probe_video_dimensions", lambda path: (800, 600) if Path(path).name == "source.mov" else pytest.fail("expected private staged source"))

    def fake_convert(path, filename, operation_id, options, workspace):
        captured.update(operation_id=operation_id, options=options, filename=filename)
        output = Path(workspace) / "cropped.mov"
        output.write_bytes(b"cropped video copy")
        return str(output), "mov", "video/quicktime", {}, output.stat().st_size

    monkeypatch.setattr(media_cli, "convert_native_media_to_file", fake_convert)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "crop", "--aspect-ratio", "16:9", "--output-dir", str(tmp_path / "out"), str(source),
    ], stdout, stderr) == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())["results"][0]
    assert captured == {
        "operation_id": "video-crop", "options": {"x": 0, "y": 75, "width": 800, "height": 450},
        "filename": "clip.mov",
    }
    assert (tmp_path / "out" / result["output"]).read_bytes() == b"cropped video copy"
    assert source.read_bytes() == original


def test_cli_image_overlay_requires_and_reads_separate_bounded_logo_path(tmp_path):
    source = tmp_path / "photo.png"
    watermark = tmp_path / "logo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    Image.new("RGB", (100, 80), (20, 80, 180)).save(source, format="PNG")
    Image.new("RGBA", (20, 10), (250, 10, 20, 255)).save(watermark, format="PNG")
    original = source.read_bytes()
    recipe.write_text(json.dumps([{"operationId": "image-watermark-overlay", "options": {
        "placement": "top-left", "marginPercent": 0,
        "sizePercent": 20, "opacityPercent": 100,
    }}]))
    errors, stdout = io.StringIO(), io.StringIO()
    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], stdout, errors) == 2
    assert "exactly when" in errors.getvalue()
    assert run([
        "--recipe", str(recipe), "--output-dir", str(output),
        "--watermark-image", str(watermark), str(source),
    ], stdout, errors) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    with Image.open(output / result["output"]) as prepared:
        assert prepared.getpixel((5, 5))[:3] == (250, 10, 20)
        assert prepared.getpixel((50, 40))[:3] == (20, 80, 180)
    assert source.read_bytes() == original


def test_cli_rejects_invalid_recipe_and_oversize_input(tmp_path):
    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    png(source)
    recipe.write_text('[{"operationId":"image-run-script","options":{}}]')
    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], io.StringIO(), io.StringIO()) == 2
    assert not output.exists()

    recipe.write_text('[{"operationId":"image-optimize","options":{}}]')
    with source.open("wb") as source_file:
        source_file.truncate(64 * 1024 * 1024 + 1)
    errors = io.StringIO()
    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], io.StringIO(), errors) == 2
    assert "64 MiB" in errors.getvalue()


def test_cli_refuses_existing_output_without_modifying_it(tmp_path):
    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    png(source)
    recipe.write_text('[{"operationId":"image-optimize","options":{}}]')
    output.mkdir()
    target = output / "photo-optimized.png"
    target.write_bytes(b"keep")
    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], io.StringIO(), io.StringIO()) == 2
    assert target.read_bytes() == b"keep"


def test_cli_suffix_collision_policy_publishes_unique_sibling_without_overwrite(tmp_path):
    source = tmp_path / "photo.png"
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    png(source)
    recipe.write_text('[{"operationId":"image-optimize","options":{}}]')
    output.mkdir()
    first = output / "photo-optimized.png"
    first.write_bytes(b"keep")

    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "--recipe", str(recipe), "--output-dir", str(output),
        "--collision-policy", "suffix", str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    assert result["results"][0]["output"] == "photo-optimized (2).png"
    assert first.read_bytes() == b"keep"
    assert (output / "photo-optimized (2).png").is_file()
    assert stderr.getvalue() == ""


def test_cli_crop_pdf_preset_accepts_custom_aspect_ratio_and_preserves_source(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    source = tmp_path / "book.pdf"
    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800))
    page.drawString(40, 700, "Searchable text")
    page.save()
    source.write_bytes(pdf.getvalue())
    original = source.read_bytes()
    output = tmp_path / "out"
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "crop-pdf", "--aspect-ratio", "16:9",
        "--output-dir", str(output), str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    cropped = PdfReader(output / result["results"][0]["output"]).pages[0]
    assert float(cropped.cropbox.width) == 450
    assert float(cropped.cropbox.height) == 800
    assert cropped.extract_text().strip() == "Searchable text"
    assert source.read_bytes() == original


def test_cli_uncrop_pdf_preset_writes_restored_copy_and_preserves_source(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800), invariant=1)
    page.drawString(36, 752, "Uncrop CLI fixture")
    page.showPage()
    page.save()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf.getvalue())))
    writer.pages[0].cropbox.lower_left = (100, 120)
    writer.pages[0].cropbox.upper_right = (400, 600)
    cropped = io.BytesIO()
    writer.write(cropped)
    source = tmp_path / "cropped.pdf"
    source.write_bytes(cropped.getvalue())
    original = source.read_bytes()
    output = tmp_path / "uncropped"
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run(["--preset", "uncrop-pdf", "--output-dir", str(output), str(source)], stdout, stderr) == 0, stderr.getvalue()

    result = json.loads(stdout.getvalue())
    assert result["results"][0]["output"] == "cropped-uncropped.pdf"
    restored = PdfReader(output / result["results"][0]["output"]).pages[0]
    assert tuple(float(value) for value in restored.cropbox) == tuple(float(value) for value in restored.mediabox)
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""


def test_cli_crop_pdf_accepts_a_named_device_ratio(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    source = tmp_path / "book.pdf"
    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800))
    page.drawString(40, 700, "Searchable text")
    page.save()
    source.write_bytes(pdf.getvalue())
    original = source.read_bytes()
    output = tmp_path / "out"
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "crop-pdf", "--for-device", "iPad Air",
        "--output-dir", str(output), str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    cropped = PdfReader(output / result["results"][0]["output"]).pages[0]
    assert float(cropped.cropbox.width) / float(cropped.cropbox.height) == pytest.approx(41 / 59)
    assert cropped.extract_text().strip() == "Searchable text"
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""


def test_cli_crop_pdf_device_catalog_is_readable_and_unknown_names_fail_closed(tmp_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["--preset", "crop-pdf", "--list-devices"], stdout, stderr) == 0
    devices = json.loads(stdout.getvalue())["devices"]
    assert len(devices) == 101
    assert "iPad Air" in devices
    assert devices == sorted(devices, key=str.casefold)
    assert stderr.getvalue() == ""

    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF placeholder")
    errors = io.StringIO()
    assert run([
        "--preset", "crop-pdf", "--for-device", "made-up device",
        "--output-dir", str(tmp_path / "out"), str(source),
    ], io.StringIO(), errors) == 2
    assert "use --list-devices" in errors.getvalue()
    assert not (tmp_path / "out").exists()


def test_cli_crop_pdf_lists_paper_sizes_and_extends_to_named_paper_without_clipping(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    listing, stderr = io.StringIO(), io.StringIO()
    assert run(["--preset", "crop-pdf", "--list-paper-sizes"], listing, stderr) == 0
    paper_sizes = json.loads(listing.getvalue())["paperSizes"]
    assert len(paper_sizes) == 104
    assert "Letter" in paper_sizes and "A4" in paper_sizes
    assert stderr.getvalue() == ""

    invalid_errors = io.StringIO()
    assert run([
        "--preset", "crop-pdf", "--paper-size", "made-up size",
        "--output-dir", str(tmp_path / "invalid-out"), str(tmp_path / "missing.pdf"),
    ], io.StringIO(), invalid_errors) == 2
    assert "use --list-paper-sizes" in invalid_errors.getvalue()
    assert not (tmp_path / "invalid-out").exists()

    source = tmp_path / "book.pdf"
    pdf = io.BytesIO()
    page = canvas.Canvas(pdf, pagesize=(600, 800))
    page.drawString(40, 700, "Searchable text")
    page.save()
    source.write_bytes(pdf.getvalue())
    original = source.read_bytes()
    output = tmp_path / "out"
    stdout, errors = io.StringIO(), io.StringIO()
    assert run([
        "--preset", "crop-pdf", "--paper-size", "Letter", "--extend",
        "--page-layout", "portrait", "--output-dir", str(output), str(source),
    ], stdout, errors) == 0
    result = json.loads(stdout.getvalue())
    cropped = PdfReader(output / result["results"][0]["output"]).pages[0]
    assert float(cropped.cropbox.width) / float(cropped.cropbox.height) == pytest.approx(216 / 279)
    assert float(cropped.cropbox.width) > 600
    assert cropped.extract_text().strip() == "Searchable text"
    assert source.read_bytes() == original
    assert errors.getvalue() == ""


def test_cli_crop_pdf_recursively_scans_bounded_folders_and_excludes_output(tmp_path):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    source_root = tmp_path / "incoming"
    nested_root = source_root / "nested"
    nested_root.mkdir(parents=True)

    def make_pdf(path, text):
        content = io.BytesIO()
        page = canvas.Canvas(content, pagesize=(600, 800))
        page.drawString(40, 700, text)
        page.save()
        path.write_bytes(content.getvalue())

    first = source_root / "a.pdf"
    second = nested_root / "b.pdf"
    make_pdf(first, "First searchable page")
    make_pdf(second, "Second searchable page")
    originals = {path: path.read_bytes() for path in (first, second)}
    output = source_root / "prepared"
    output.mkdir()
    ignored_output = output / "previous.pdf"
    make_pdf(ignored_output, "Do not recursively reprocess")
    previous_bytes = ignored_output.read_bytes()

    no_recursive = io.StringIO()
    assert run([
        "--preset", "crop-pdf", "--paper-size", "A4",
        "--output-dir", str(tmp_path / "no-recursive"), str(source_root),
    ], io.StringIO(), no_recursive) == 2
    assert "require --recursive" in no_recursive.getvalue()
    assert not (tmp_path / "no-recursive").exists()

    try:
        (source_root / "linked-folder").symlink_to(nested_root, target_is_directory=True)
        (source_root / "linked-file.pdf").symlink_to(second)
    except OSError:
        pass
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "--preset", "crop-pdf", "--paper-size", "A4", "-r",
        "--output-dir", str(output), str(source_root),
    ], stdout, stderr) == 0
    results = json.loads(stdout.getvalue())["results"]
    assert [item["input"] for item in results] == ["a.pdf", "b.pdf"]
    for item in results:
        output_pdf = PdfReader(output / item["output"])
        assert output_pdf.pages[0].extract_text().strip().endswith("searchable page")
    assert {path: path.read_bytes() for path in originals} == originals
    assert ignored_output.read_bytes() == previous_bytes
    assert stderr.getvalue() == ""


def test_recursive_pdf_collection_enforces_file_limit_before_processing(tmp_path):
    root = tmp_path / "many"
    root.mkdir()
    for index in range(31):
        (root / f"{index:02}.pdf").write_bytes(b"pdf")
    with pytest.raises(ValueError, match="limited to 30 files"):
        _collect_pdf_inputs([str(root)], True, tmp_path / "out")


def test_recursive_pdf_collection_enforces_directory_entry_scan_bound(tmp_path, monkeypatch):
    root = tmp_path / "wide"
    root.mkdir()
    for index in range(4):
        (root / f"{index}.txt").write_text("ignored")
    monkeypatch.setattr(media_cli, "MAX_DIRECTORY_ENTRIES", 3)
    with pytest.raises(ValueError, match="limited to 3 directory entries"):
        _collect_pdf_inputs([str(root)], True, tmp_path / "out")


def test_cli_image_preset_runs_typed_optimizer_and_rejects_non_images(tmp_path):
    source = tmp_path / "photo.png"
    output = tmp_path / "out"
    png(source)
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "optimize-image", "--output-dir", str(output),
        "--collision-policy", "suffix", str(source),
    ], stdout, stderr) == 0
    assert json.loads(stdout.getvalue())["results"][0]["output"] == "photo-optimized.png"
    assert source.exists()
    assert stderr.getvalue() == ""

    invalid = tmp_path / "document.txt"
    invalid.write_text("not an image")
    assert run([
        "--preset", "optimize-image", "--output-dir", str(output), str(invalid),
    ], io.StringIO(), stderr) == 2


def test_cli_downscale_image_uses_shared_resize_operation_and_preserves_source(tmp_path):
    source = tmp_path / "photo.png"
    output = tmp_path / "out"
    png(source)
    original = source.read_bytes()
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "downscale-image", "--factor", "0.5",
        "--output-dir", str(output), str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    with Image.open(output / result["output"]) as prepared:
        assert prepared.size == (16, 12)
    assert result["attributes"]["width"] == 16
    assert result["attributes"]["height"] == 12
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""


def test_cli_downscale_image_factor_one_copies_source_without_reencoding(tmp_path):
    source = tmp_path / "photo.png"
    output = tmp_path / "out"
    png(source)
    original = source.read_bytes()
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "downscale-image", "--factor", "1",
        "--output-dir", str(output), str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert (output / result["output"]).read_bytes() == original
    assert result["attributes"] == {"no_op": True}
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("factor", ["0", "-0.5", "1.01", "nan", "inf"])
def test_cli_downscale_image_rejects_invalid_factors(tmp_path, factor):
    source = tmp_path / "photo.png"
    png(source)
    errors = io.StringIO()

    assert run([
        "--preset", "downscale-image", "--factor", factor,
        "--output-dir", str(tmp_path / "out"), str(source),
    ], io.StringIO(), errors) == 2
    assert "downscale factor" in errors.getvalue()
    assert source.exists()


def test_cli_to_webp_preset_converts_supported_image_and_preserves_source(tmp_path):
    source = tmp_path / "photo.png"
    output = tmp_path / "out"
    png(source)
    original = source.read_bytes()
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "to-webp", "--output-dir", str(output), str(source),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    assert result["results"][0]["output"] == "photo-optimized.webp"
    assert (output / result["results"][0]["output"]).read_bytes().startswith(b"RIFF")
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""

    unsupported = tmp_path / "report.pdf"
    unsupported.write_bytes(b"%PDF-1.7")
    errors = io.StringIO()
    assert run([
        "--preset", "to-webp", "--output-dir", str(output), str(unsupported),
    ], io.StringIO(), errors) == 2
    assert "common image formats" in errors.getvalue()


def test_cli_to_webp_accepts_heic_and_publishes_a_separate_copy(tmp_path):
    if not native.native_heif_decoder_available():
        pytest.skip("macOS ImageIO via sips is not available")
    source = Path("tests/fixtures/similar-images/cc0/heic/still-medium.heic")
    output = tmp_path / "out"
    original = source.read_bytes()
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["--preset", "to-webp", "--output-dir", str(output), str(source)], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    artifact = output / result["results"][0]["output"]
    assert result["state"] == "complete"
    assert artifact.suffix == ".webp"
    assert artifact.read_bytes()[:4] == b"RIFF"
    assert source.read_bytes() == original
    assert stderr.getvalue() == ""


def test_cli_sort_screenshots_preset_copies_named_screenshots_into_capture_month(tmp_path):
    from datetime import datetime

    source = tmp_path / "Screenshot 2025-06-15 at 10.00.00.png"
    clean_shot = tmp_path / "CleanShot X 2025-06-15.png"
    output = tmp_path / "sorted"
    png(source)
    png(clean_shot)
    originals = {path: path.read_bytes() for path in (source, clean_shot)}
    capture_time = datetime(2025, 6, 15, 10, 0).timestamp()
    os.utime(source, (capture_time, capture_time))
    os.utime(clean_shot, (capture_time, capture_time))
    stdout, stderr = io.StringIO(), io.StringIO()

    assert run([
        "--preset", "sort-screenshots", "--output-dir", str(output), str(source), str(clean_shot),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    assert [item["output"] for item in result["results"]] == [
        "25/06/Screenshot 2025-06-15 at 10.00.00.png", "25/06/CleanShot X 2025-06-15.png",
    ]
    assert all((output / item["output"]).is_file() for item in result["results"])
    assert {path: path.read_bytes() for path in originals} == originals
    assert stderr.getvalue() == ""

    conflict = io.StringIO()
    assert run([
        "--preset", "sort-screenshots", "--output-dir", str(output), str(source),
    ], io.StringIO(), conflict) == 2
    assert "File exists" in conflict.getvalue()
    assert source.read_bytes() == originals[source]

    suffixed = json.loads(_run_cli_to_string([
        "--preset", "sort-screenshots", "--collision-policy", "suffix",
        "--output-dir", str(output), str(source),
    ]))
    assert suffixed["results"][0]["output"] == "25/06/Screenshot 2025-06-15 at 10.00.00 (2).png"
    assert source.read_bytes() == originals[source]


def _run_cli_to_string(arguments):
    stdout = io.StringIO()
    assert run(arguments, stdout, io.StringIO()) == 0
    return stdout.getvalue()


def test_cli_native_media_keeps_input_and_output_file_backed(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"native media input")
    recipe = tmp_path / "recipe.json"
    output = tmp_path / "out"
    recipe.write_text('[{"operationId":"video-optimize","options":{"targetFormat":"m4v","quality":"balanced"}}]')
    observed = {}

    def convert(source_path, filename, operation_id, options, workspace):
        with open(source_path, "rb") as staged:
            observed["input"] = staged.read()
        observed["name"] = filename
        observed["operation"] = operation_id
        observed["quality"] = options["quality"]
        target = os.path.join(workspace, "converted.m4v")
        with open(target, "wb") as prepared:
            prepared.write(b"file-backed result")
        return target, "m4v", "video/x-m4v", {"quality": options["quality"]}, len(b"file-backed result")

    monkeypatch.setattr("officekit.media_cli.convert_native_media_to_file", convert)
    monkeypatch.setattr(
        "officekit.media_cli.MediaOptimizerEngine.execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("native media was buffered")),
    )
    stdout = io.StringIO()
    assert run(["--recipe", str(recipe), "--output-dir", str(output), str(source)], stdout, io.StringIO()) == 0
    result = json.loads(stdout.getvalue())["results"][0]
    assert result["inputBytes"] == len(b"native media input")
    assert result["bytes"] == len(b"file-backed result")
    assert observed == {
        "input": b"native media input", "name": "clip.mov",
        "operation": "video-optimize", "quality": "balanced",
    }
    assert (output / "clip-optimized.m4v").read_bytes() == b"file-backed result"
    assert source.read_bytes() == b"native media input"


def test_cli_optimize_media_preset_dispatches_allowlisted_operations_per_file(tmp_path, monkeypatch):
    from officekit.engines.engine_media_models import MediaOperation

    image = tmp_path / "photo.png"
    bitmap = tmp_path / "scan.tiff"
    video = tmp_path / "clip.mov"
    pdf = tmp_path / "report.pdf"
    audio = tmp_path / "voice.wav"
    png(image)
    png(bitmap)
    video.write_bytes(b"video source")
    pdf.write_bytes(b"pdf source")
    audio.write_bytes(b"audio source")
    originals = {source.name: source.read_bytes() for source in (image, bitmap, video, pdf, audio)}
    output = tmp_path / "prepared"
    native_calls = []
    image_pdf_calls = []

    def native_convert(source_path, filename, operation_id, options, workspace):
        extension = "m4v" if operation_id == "video-optimize" else options["target_format"]
        target = os.path.join(workspace, f"prepared.{extension}")
        with open(target, "wb") as prepared:
            prepared.write(f"prepared {operation_id}".encode())
        native_calls.append((filename, operation_id, options.copy()))
        content_type = "video/x-m4v" if extension == "m4v" else {"mp3": "audio/mpeg", "m4a": "audio/mp4"}[extension]
        return target, extension, content_type, {}, os.path.getsize(target)

    def optimize_execute(source_bytes, filename, operations, **_kwargs):
        operation = operations[0]
        image_pdf_calls.append((filename, operation.operation_id, operation.options.copy()))
        extension = "pdf" if operation.operation_id == "pdf-lossless-compress" else "webp" if operation.operation_id == "image-convert" else "png"
        return SimpleNamespace(data=f"prepared {operation.operation_id}".encode(), extension=extension, attributes={})

    monkeypatch.setattr("officekit.media_cli.convert_native_media_to_file", native_convert)
    monkeypatch.setattr("officekit.media_cli.MediaOptimizerEngine.execute", optimize_execute)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run([
        "--preset", "optimize-media", "--output-dir", str(output),
        str(image), str(bitmap), str(video), str(pdf), str(audio),
    ], stdout, stderr) == 0
    result = json.loads(stdout.getvalue())
    assert result["state"] == "complete"
    assert {item["input"]: item["output"] for item in result["results"]} == {
        "photo.png": "photo-optimized.png", "clip.mov": "clip-optimized.m4v",
        "scan.tiff": "scan-optimized.webp", "report.pdf": "report-optimized.pdf", "voice.wav": "voice-optimized.mp3",
    }
    assert native_calls == [
        ("clip.mov", "video-optimize", {"target_format": "m4v", "quality": "balanced"}),
        ("voice.wav", "audio-convert", {"target_format": "mp3", "bitrate_kbps": 192}),
    ]
    assert image_pdf_calls == [
        ("photo.png", "image-optimize", {}),
        ("scan.tiff", "image-convert", {"target_format": "webp", "quality": 90}),
        ("report.pdf", "pdf-lossless-compress", {"profile": "balanced"}),
    ]
    assert {source.name: source.read_bytes() for source in (image, bitmap, video, pdf, audio)} == originals
    assert stderr.getvalue() == ""


def test_cli_optimize_media_preset_rejects_unknown_file_types(tmp_path):
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not media")
    errors = io.StringIO()
    assert run([
        "--preset", "optimize-media", "--output-dir", str(tmp_path / "out"), str(unsupported),
    ], io.StringIO(), errors) == 2
    assert "common image, video, PDF, and audio formats" in errors.getvalue()


def test_cli_settings_schema_list_get_set_and_clear_share_the_private_defaults_store(tmp_path, monkeypatch):
    defaults_path = tmp_path / "OfficeKit" / "media-operation-defaults.json"
    monkeypatch.setattr(
        "officekit.engines.engine_media_operation_defaults.media_operation_defaults_path",
        lambda: str(defaults_path),
    )

    schema_stdout = io.StringIO()
    assert run(["--settings", "schema"], schema_stdout, io.StringIO()) == 0
    schema = json.loads(schema_stdout.getvalue())
    assert "image-optimize" in schema and "pdf-uncrop" in schema
    assert "quality" in schema["image-optimize"]["properties"]

    set_stdout = io.StringIO()
    assert run([
        "--settings", "set", "--operation-id", "image-optimize",
        "--options-json", '{"quality":73,"preserveMetadata":false}',
    ], set_stdout, io.StringIO()) == 0
    assert json.loads(set_stdout.getvalue()) == {"quality": 73, "preserveMetadata": False}

    get_stdout = io.StringIO()
    assert run(["--settings", "get", "--operation-id", "image-optimize"], get_stdout, io.StringIO()) == 0
    assert json.loads(get_stdout.getvalue()) == {"quality": 73, "preserveMetadata": False}
    assert defaults_path.stat().st_mode & 0o777 == 0o600

    clear_stdout = io.StringIO()
    assert run(["--settings", "clear", "--operation-id", "image-optimize"], clear_stdout, io.StringIO()) == 0
    assert json.loads(clear_stdout.getvalue()) == {"state": "cleared", "operationId": "image-optimize"}
    assert json.loads((defaults_path).read_text()) == {}


def test_clop_style_settings_commands_filter_schema_and_share_typed_defaults(tmp_path, monkeypatch):
    defaults_path = tmp_path / "OfficeKit" / "media-operation-defaults.json"
    monkeypatch.setattr(
        "officekit.engines.engine_media_operation_defaults.media_operation_defaults_path",
        lambda: str(defaults_path),
    )

    schema = io.StringIO()
    assert run(["settings", "schema", "image", "--json"], schema, io.StringIO()) == 0
    schema_ids = set(json.loads(schema.getvalue()))
    assert len(schema_ids) > 4 and all(operation_id.startswith("image-") for operation_id in schema_ids)

    quality_schema = io.StringIO()
    assert run(["settings", "schema", "quality", "--json"], quality_schema, io.StringIO()) == 0
    assert "image-optimize" in json.loads(quality_schema.getvalue())

    set_result = io.StringIO()
    assert run(["settings", "set", "image-optimize", '{"quality":71,"preserveMetadata":false}', "--json"], set_result, io.StringIO()) == 0
    assert json.loads(set_result.getvalue()) == {"quality": 71, "preserveMetadata": False}

    get_result = io.StringIO()
    assert run(["settings", "get", "image-optimize", "--json"], get_result, io.StringIO()) == 0
    assert json.loads(get_result.getvalue()) == {"quality": 71, "preserveMetadata": False}
    assert defaults_path.stat().st_mode & 0o777 == 0o600


def test_clop_style_settings_reject_unsupported_keys_and_invalid_values():
    for arguments, expected in (
        (["settings", "get", "run-script"], "Unsupported media operation"),
        (["settings", "set", "image-optimize", "[]"], "Options must be a JSON object"),
        (["settings", "set", "image-optimize", '{"quality":900}'], "less than or equal to 100"),
    ):
        stderr = io.StringIO()
        assert run(arguments, io.StringIO(), stderr) == 2
        assert expected in stderr.getvalue()


def test_pipeline_inline_steps_map_to_typed_allowlisted_operations():
    image, watermark, pipeline_filter = media_cli._parse_pipeline_dsl("convert(to: webp) -> stripExif", "image")
    assert watermark is None
    assert pipeline_filter is None
    assert [(operation.operation_id, operation.options) for operation in image] == [
        ("image-convert", {"target_format": "webp", "quality": 90}),
        ("image-strip-metadata", {}),
    ]
    video, watermark, pipeline_filter = media_cli._parse_pipeline_dsl('changeSpeed(factor: 2.0) -> removeAudio -> convert(to: av1)', "video")
    assert watermark is None
    assert pipeline_filter is None
    assert [(operation.operation_id, operation.options) for operation in video] == [
        ("video-speed", {"factor_percent": 200}),
        ("video-mute", {}),
        ("video-optimize", {"target_format": "av1", "quality": "balanced"}),
    ]
    for target, container in (("mp4", "mp4"), ("webm", "webm"), ("x265", "x265")):
        converted, _watermark, _filter = media_cli._parse_pipeline_dsl(f"convert(to: {target})", "video")
        assert converted[0].operation_id == "video-optimize"
        assert converted[0].options == {"target_format": container, "quality": "balanced"}
    lossless_image, _watermark, _filter = media_cli._parse_pipeline_dsl(
        "convert(to: webp, lossless: true)", "image",
    )
    assert lossless_image[0].operation_id == "image-convert"
    assert lossless_image[0].options == {"target_format": "webp", "quality": 90, "lossless": True}
    with pytest.raises(ValueError, match="Lossless image conversion"):
        media_cli._parse_pipeline_dsl("convert(to: jpeg, lossless: true)", "image")
    compressed, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(compression: 55)", "video")
    assert compressed[0].operation_id == "video-optimize"
    assert compressed[0].options == {"target_format": "mp4", "compression": 55}
    for invalid in ("optimise(compression: 4)", "optimise(compression: 101)", "optimise(compression: 55.5)"):
        with pytest.raises(ValueError, match="compression"):
            media_cli._parse_pipeline_dsl(invalid, "video")
    image_adaptive, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(compression: adaptive)", "image")
    assert image_adaptive[0].operation_id == "image-optimize"
    assert image_adaptive[0].options == {"compression": "adaptive"}
    image_format_adaptive, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(adaptive: true)", "image")
    assert image_format_adaptive[0].options == {"adaptive": True}
    image_factor, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(compression: 55)", "image")
    assert image_factor[0].operation_id == "image-optimize"
    assert image_factor[0].options == {"compression": 55}
    audio, watermark, pipeline_filter = media_cli._parse_pipeline_dsl("normalize(lufs: -16)", "audio")
    assert watermark is None
    assert pipeline_filter is None
    lower_bitrate, _watermark, _filter = media_cli._parse_pipeline_dsl("lowerBitrate(kbps: 128)", "audio")
    assert lower_bitrate[0].operation_id == "audio-optimize"
    assert lower_bitrate[0].options == {"target_format": "m4a", "bitrate_kbps": 128, "no_upscale": True}
    visual_pdf, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(dpi: 120)", "pdf")
    assert visual_pdf[0].operation_id == "pdf-visual-optimize"
    assert visual_pdf[0].options == {"quality": 75, "dpi": 120}
    aggressive_pdf, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(encoder: aggressive)", "pdf")
    assert aggressive_pdf[0].options == {"quality": 45, "dpi": 150}
    lossless_pdf, _watermark, _filter = media_cli._parse_pipeline_dsl("optimise(encoder: lossless)", "pdf")
    assert lossless_pdf[0].operation_id == "pdf-lossless-compress"
    assert lossless_pdf[0].options == {"profile": "balanced"}
    assert audio[0].operation_id == "audio-normalize" and audio[0].options == {"target_lufs": -16}
    audio_speed, _watermark, _filter = media_cli._parse_pipeline_dsl("changeSpeed(factor: 1.5)", "audio")
    assert audio_speed[0].operation_id == "audio-speed"
    assert audio_speed[0].options == {"factor_percent": 150}

    fit_operations = {
        media: media_cli._parse_pipeline_dsl('targetSize(size: 10MB)', media)[0][0]
        for media in ("image", "video", "pdf", "audio")
    }
    assert {operation.operation_id for operation in fit_operations.values()} == {
        "image-fit-size", "video-fit-size", "pdf-fit-size", "audio-fit-size",
    }
    assert all(operation.options["target_bytes"] == 10_000_000 for operation in fit_operations.values())
    assert media_cli._parse_pipeline_dsl('targetSize(size: "10MiB")', "image")[0][0].options["target_bytes"] == 10_485_760

    pdf, _logo, pdf_filter = media_cli._parse_pipeline_dsl(
        'extractPagesAsImages(format: png, quality: high, dpi: 120)', "pdf",
    )
    assert pdf_filter is None
    assert [(item.operation_id, item.options) for item in pdf] == [
        ("pdf-pages-to-images", {"target_format": "png", "quality": 92, "dpi": 120}),
    ]
    with pytest.raises(ValueError, match="format"):
        media_cli._parse_pipeline_dsl('extractPagesAsImages(format: tiff)', "pdf")
    with pytest.raises(ValueError, match="quality"):
        media_cli._parse_pipeline_dsl('extractPagesAsImages(quality: 0)', "pdf")
    with pytest.raises(ValueError, match="final"):
        media_cli._parse_pipeline_dsl('extractPagesAsImages -> optimise', "pdf")


def test_pipeline_cap_fps_uses_source_dimensions_and_typed_video_resize(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"video")
    monkeypatch.setattr(media_cli, "probe_video_dimensions", lambda _path: (1920, 1080))

    operations, watermark, pipeline_filter = media_cli._parse_pipeline_dsl(
        "capFps(fps: 24) -> optimise", "video", source_path=str(source),
    )
    assert watermark is None and pipeline_filter is None
    assert [(operation.operation_id, operation.options) for operation in operations] == [
        ("video-resize", {"max_width": 1920, "max_height": 1080, "fps": 24}),
        ("video-optimize", {"target_format": "m4v", "quality": "balanced"}),
    ]
    with pytest.raises(ValueError, match="between 1 and 120"):
        media_cli._parse_pipeline_dsl("capFps(fps: 121)", "video", source_path=str(source))
    saved_operations, _watermark, _pipeline_filter = media_cli._parse_pipeline_dsl("capFps(fps: 24)", "video")
    assert saved_operations[0].options == {"max_width": 10_000, "max_height": 10_000, "fps": 24}


def test_pipeline_inline_watermark_maps_safe_geometry_and_alpha_to_typed_operation():
    operations, logo, pipeline_filter = media_cli._parse_pipeline_dsl(
        'watermark(image: "logo.png", position: topLeft, opacity: 0.5, scale: 0.2)', "image",
    )
    assert logo == "logo.png"
    assert pipeline_filter is None
    assert operations[0].operation_id == "image-watermark-overlay"
    assert operations[0].options == {
        "placement": "top-left", "opacity_percent": 50, "size_percent": 20,
    }


def test_pipeline_video_watermark_maps_to_typed_operation_and_local_logo():
    operations, logo, pipeline_filter = media_cli._parse_pipeline_dsl(
        'watermark(image: "logo.png", position: topLeft, opacity: 0.5, scale: 0.2)', "video",
    )
    assert logo == "logo.png" and pipeline_filter is None
    assert operations[0].operation_id == "video-watermark-overlay"
    assert operations[0].options == {
        "placement": "top-left", "opacity_percent": 50, "size_percent": 20,
    }


def test_pipeline_inline_first_step_filters_are_bounded_and_match_filename_or_type():
    operations, _watermark, name_filter = media_cli._parse_pipeline_dsl(
        'if(nameContains: "invoice") -> convert(to: webp)', "image",
    )
    assert operations[0].operation_id == "image-convert"
    assert media_cli._pipeline_filter_matches(name_filter, "/files/Invoice Final.png", "image")
    assert not media_cli._pipeline_filter_matches(name_filter, "/files/photo.png", "image")
    operations, _watermark, type_filter = media_cli._parse_pipeline_dsl(
        'ifNot(types: "jpeg") -> stripExif', "image",
    )
    assert operations[0].operation_id == "image-strip-metadata"
    assert not media_cli._pipeline_filter_matches(type_filter, "/files/photo.jpg", "image")
    assert media_cli._pipeline_filter_matches(type_filter, "/files/photo.png", "image")
    with pytest.raises(ValueError, match="repetition limit"):
        media_cli._parse_pipeline_dsl('if(regex: ".*private.*foo.*") -> convert(to: webp)', "image")
    with pytest.raises(ValueError, match="must be the first step"):
        media_cli._parse_pipeline_dsl('stripExif -> if(nameIs: "photo.png") -> optimise', "image")


def test_pipeline_filters_support_safe_regex_and_combined_file_size_and_image_dimensions(tmp_path):
    source = tmp_path / "Screen Shot.png"
    Image.new("RGB", (32, 24), (30, 80, 140)).save(source, format="PNG", dpi=(300, 300))
    operations, _watermark, pipeline_filter = media_cli._parse_pipeline_dsl(
        'if(regex: "^(screen ?shot|cleanshot)", minFileSize: 1B, widthGreaterThan: 10, minResolution: 32x24, dpiGreaterThan: 72) -> convert(to: webp)',
        "image",
    )
    assert operations[0].operation_id == "image-convert"
    assert media_cli._pipeline_filter_matches(pipeline_filter, str(source), "image")
    assert not media_cli._pipeline_filter_matches(pipeline_filter, str(source), "video")
    _operations, _watermark, low_dpi_filter = media_cli._parse_pipeline_dsl(
        "if(dpiLowerThan: 600) -> convert(to: webp)", "image",
    )
    assert media_cli._pipeline_filter_matches(low_dpi_filter, str(source), "image")
    plain = tmp_path / "plain.png"
    png(plain)
    assert not media_cli._pipeline_filter_matches(low_dpi_filter, str(plain), "image")
    with pytest.raises(ValueError, match="DPI"):
        media_cli._parse_pipeline_dsl("if(dpiGreaterThan: 72) -> optimise", "video")
    with pytest.raises(ValueError, match="cannot repeat a group"):
        media_cli._parse_pipeline_dsl('if(regex: "(a+)+$") -> optimise', "image")
    with pytest.raises(ValueError, match="cannot repeat a group"):
        media_cli._parse_pipeline_dsl('if(regex: "(a|aa){1,100}$") -> optimise', "image")
    with pytest.raises(ValueError, match="cannot repeat a group"):
        media_cli._parse_pipeline_dsl('if(regex: "((a|aa)){1,100}$") -> optimise', "image")
    with pytest.raises(ValueError, match="safe repetition limit"):
        media_cli._parse_pipeline_dsl('if(regex: ".*a.*b.*") -> optimise', "image")


def test_pipeline_pdf_dpi_filters_read_effective_image_resolution_and_preserve_source(tmp_path):
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    source = tmp_path / "scan.pdf"
    output = io.BytesIO()
    pdf = Canvas(output, pagesize=(420, 600), invariant=1)
    pdf.drawImage(ImageReader(Image.new("RGB", (300, 150))), 0, 0, width=72, height=36)
    pdf.save()
    source.write_bytes(output.getvalue())
    original = source.read_bytes()
    for condition, expected in [("dpiGreaterThan: 150", True), ("dpiLowerThan: 600", True),
                                ("dpiGreaterThan: 300", False), ("dpiLowerThan: 300", False)]:
        _, _, predicate = media_cli._parse_pipeline_dsl(f"if({condition}) -> optimise", "pdf")
        assert media_cli._pipeline_filter_matches(predicate, str(source), "pdf") is expected
    source.write_bytes(b"invalid PDF")
    assert not media_cli._pipeline_filter_matches(predicate, str(source), "pdf")
    source.write_bytes(original)
    assert source.read_bytes() == original


def test_pipeline_inline_filter_skips_unmatched_files_and_reports_them(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    included = tmp_path / "invoice.png"
    excluded = tmp_path / "photo.png"
    png(included)
    png(excluded)
    originals = {item: item.read_bytes() for item in (included, excluded)}
    output_dir = tmp_path / "filtered"
    stdout = io.StringIO()
    step = 'if(nameContains: "invoice") -> convert(to: webp)'
    assert run(["pipeline", "run", step, str(included), str(excluded), "--output-dir", str(output_dir)], stdout, io.StringIO()) == 0
    result = json.loads(stdout.getvalue())
    assert result["state"] == "complete"
    assert [item["input"] for item in result["results"]] == [included.name]
    assert result["skipped"] == [{"input": excluded.name, "state": "skipped"}]
    assert (output_dir / result["results"][0]["output"]).is_file()
    assert all(item.read_bytes() == originals[item] for item in originals)


def test_pipeline_add_accepts_clop_style_typed_steps_and_runs_saved_pipeline(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    source = tmp_path / "source.png"
    png(source)
    source_hash = source.read_bytes()
    added = io.StringIO()
    assert run(["pipeline", "add", "Inline web image", "convert(to: webp)", "--file-type", "image"], added, io.StringIO()) == 0
    pipeline = json.loads(added.getvalue())
    assert pipeline["state"] == "paused"
    assert pipeline["operations"] == [{"operationId": "image-convert", "options": {"target_format": "webp", "quality": 90}}]

    output_dir = tmp_path / "saved-output"
    output = io.StringIO()
    assert run(["pipeline", "run", "Inline web image", str(source), "--output-dir", str(output_dir)], output, io.StringIO()) == 0
    result = json.loads(output.getvalue())
    assert result["state"] == "complete" and result["results"][0]["output"].endswith(".webp")
    assert source.read_bytes() == source_hash


def test_pipeline_add_rejects_inline_filters_and_transient_logo_paths(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    for steps in ('if(nameContains: "photo") -> convert(to: webp)', 'watermark(image: "logo.png")'):
        stderr = io.StringIO()
        assert run(["pipeline", "add", "Saved candidate", steps, "--media", "image"], io.StringIO(), stderr) == 2
        assert "Saved pipelines cannot retain" in stderr.getvalue()


def test_pipeline_inline_run_converts_to_separate_copy_without_saving_pipeline(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    source = tmp_path / "inline.png"
    png(source)
    source_bytes = source.read_bytes()
    output_dir = tmp_path / "outputs"
    stdout = io.StringIO()
    assert run(["pipeline", "run", "convert(to: webp)", str(source), "--output-dir", str(output_dir)], stdout, io.StringIO()) == 0
    result = json.loads(stdout.getvalue())
    assert result["state"] == "complete"
    assert result["results"][0]["output"].endswith(".webp")
    assert source.read_bytes() == source_bytes
    assert not pipelines_path.exists()


@pytest.mark.parametrize("transform", ["convert(to: webp)", "convert(to: webp) -> fork() -> stripExif", "downscale(factor: 1)"])
def test_inline_pipeline_uses_filename_regex_captures_in_safe_output_names(tmp_path, transform):
    source = tmp_path / "IMG_0042.png"
    png(source)
    original = source.read_bytes()
    directory = tmp_path / "prepared"
    steps = 'if(regex: "^IMG_([0-9]{4})") -> ' + transform
    arguments = ["pipeline", "run", steps, str(source), "--output-dir", str(directory),
                 "--name-template", "photo-$1-%i.{ext}"]
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(arguments, stdout, stderr) == 0, stderr.getvalue()
    extension = "png" if "downscale" in transform else "webp"
    result = json.loads(stdout.getvalue())["results"]
    assert result[-1]["output"] == f"photo-0042-1.{extension}"
    assert (directory / result[-1]["output"]).is_file()
    assert source.read_bytes() == original
    assert run(arguments, io.StringIO(), io.StringIO()) == 2
    assert run([*arguments, "--collision-policy", "suffix"], io.StringIO(), io.StringIO()) == 0
    assert (directory / f"photo-0042-1 (2).{extension}").is_file()
    assert not list(directory.glob(".officekit-inline-pipeline-*"))


@pytest.mark.parametrize("steps,template", [
    ('if(regex: "^IMG_([0-9]{4})") -> convert(to: webp)', "$2.{ext}"),
    ('ifNot(regex: "^other_([0-9]+)") -> convert(to: webp)', "$1.{ext}"),
    ('convert(to: webp)', "$1.{ext}"),
    ('if(regex: "^(.*)$") -> convert(to: webp)', "../$1.{ext}"),
    ('if(regex: "^IMG_([0-9]{4})") -> convert(to: webp)', "$0.{ext}"),
])
def test_inline_capture_templates_reject_missing_or_unsafe_context_before_publication(tmp_path, steps, template):
    source = tmp_path / "IMG_0042.png"
    png(source)
    directory = tmp_path / "prepared"
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["pipeline", "run", steps, str(source), "--output-dir", str(directory),
                "--name-template", template], stdout, stderr) == 2
    assert not directory.exists() or not list(directory.iterdir())
    assert source.is_file()


def test_inline_capture_filters_do_not_reuse_captures_from_skipped_files(tmp_path):
    first, second, skipped = [tmp_path / name for name in ("IMG_0042.png", "IMG_0071.png", "private.png")]
    for source in (first, second, skipped):
        png(source)
    directory = tmp_path / "prepared"
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(["pipeline", "run", 'if(regex: "^IMG_([0-9]{4})", minFileSize: 1B) -> convert(to: webp)',
                str(first), str(second), str(skipped), "--output-dir", str(directory),
                "--name-template", "$1.{ext}"], stdout, stderr) == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())
    assert [item["output"] for item in result["results"]] == ["0042.webp", "0071.webp"]
    assert result["skipped"] == [{"input": "private.png", "state": "skipped"}]
    assert {item.name for item in directory.iterdir()} == {"0042.webp", "0071.webp"}


def test_pipeline_inline_fork_publishes_intermediate_copy_and_continues_main_line(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    source = tmp_path / "photo.png"
    png(source)
    source_bytes = source.read_bytes()
    output_dir = tmp_path / "forked"
    stdout, stderr = io.StringIO(), io.StringIO()
    steps = "convert(to: webp) -> fork() -> optimise(compression: 70)"

    assert run(["pipeline", "run", steps, str(source), "--output-dir", str(output_dir)], stdout, stderr) == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())
    assert result["state"] == "complete"
    assert [item["output"] for item in result["results"]] == [
        "photo-fork-1.webp", "photo-optimized.webp",
    ]
    assert all((output_dir / item["output"]).is_file() for item in result["results"])
    assert (output_dir / "photo-fork-1.webp").read_bytes().startswith(b"RIFF")
    assert (output_dir / "photo-optimized.webp").read_bytes().startswith(b"RIFF")
    assert source.read_bytes() == source_bytes
    assert not pipelines_path.exists()

    collision_stdout = io.StringIO()
    assert run([
        "pipeline", "run", steps, str(source), "--output-dir", str(output_dir),
        "--collision-policy", "suffix",
    ], collision_stdout, stderr) == 0, stderr.getvalue()
    collision_result = json.loads(collision_stdout.getvalue())
    assert len(collision_result["results"]) == 2
    assert len({item["output"] for item in collision_result["results"]}) == 2
    assert source.read_bytes() == source_bytes


def test_pipeline_add_rejects_fork_side_effects():
    stderr = io.StringIO()
    assert run([
        "pipeline", "add", "Fork candidate", "convert(to: webp) -> fork() -> stripExif",
        "--file-type", "image",
    ], io.StringIO(), stderr) == 2
    assert "fork() is available only in inline pipeline run" in stderr.getvalue()


def test_pipeline_inline_image_watermark_uses_bounded_logo_and_preserves_source(tmp_path, monkeypatch):
    pipelines_path = tmp_path / "pipelines.json"
    monkeypatch.setattr("officekit.engines.engine_media_pipelines.media_pipeline_path", lambda: str(pipelines_path))
    source = tmp_path / "source.png"
    logo = tmp_path / "logo.png"
    png(source)
    png(logo)
    original = source.read_bytes()
    output_dir = tmp_path / "watermarked"
    stdout = io.StringIO()
    stderr = io.StringIO()
    step = f'watermark(image: "{logo}", position: topLeft, opacity: 0.5, scale: 0.2)'
    assert run(["pipeline", "run", step, str(source), "--output-dir", str(output_dir)], stdout, stderr) == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())
    output = output_dir / result["results"][0]["output"]
    assert result["state"] == "complete" and output.is_file()
    assert source.read_bytes() == original


def test_pipeline_inline_crop_ratio_and_downscale_resolve_source_dimensions(tmp_path):
    source = tmp_path / "dimensions.png"
    png(source)
    crop_operations, _logo, crop_filter = media_cli._parse_pipeline_dsl(
        "crop(aspectRatio: 1:1) -> convert(to: webp)", "image", source_path=str(source),
    )
    assert crop_filter is None
    assert crop_operations[0].operation_id == "image-crop"
    assert crop_operations[0].options == {"x": 4, "y": 0, "width": 24, "height": 24}
    resize_operations, _logo, resize_filter = media_cli._parse_pipeline_dsl(
        "downscale(factor: 0.5) -> convert(to: webp)", "image", source_path=str(source),
    )
    assert resize_filter is None
    assert resize_operations[0].operation_id == "image-resize"
    assert resize_operations[0].options == {"max_width": 16, "max_height": 12}

    original = source.read_bytes()
    output_dir = tmp_path / "dynamic-output"
    stdout = io.StringIO()
    assert run([
        "pipeline", "run", "crop(aspectRatio: 1:1) -> convert(to: webp)",
        str(source), "--output-dir", str(output_dir),
    ], stdout, io.StringIO()) == 0
    result = json.loads(stdout.getvalue())
    assert result["state"] == "complete" and result["results"][0]["output"].endswith(".webp")
    with Image.open(output_dir / result["results"][0]["output"]) as output:
        assert output.size == (24, 24)
    assert source.read_bytes() == original

    resize_directory = tmp_path / "long-edge-output"
    resize_stdout = io.StringIO()
    assert run(["pipeline", "run", "crop(longEdge: 16)", str(source), "--output-dir", str(resize_directory)], resize_stdout, io.StringIO()) == 0
    resize_result = json.loads(resize_stdout.getvalue())
    with Image.open(resize_directory / resize_result["results"][0]["output"]) as resized:
        assert resized.size == (16, 12)
    assert source.read_bytes() == original


def test_pipeline_crop_pixel_dimensions_and_long_edge_compose_existing_resize_tools(tmp_path):
    source = tmp_path / "dimensions.png"
    png(source)
    long_edge, _logo, _filter = media_cli._parse_pipeline_dsl("crop(longEdge: 16)", "image", source_path=str(source))
    assert [(item.operation_id, item.options) for item in long_edge] == [
        ("image-resize", {"max_width": 16, "max_height": 16}),
    ]
    width, _logo, _filter = media_cli._parse_pipeline_dsl("crop(width: 16)", "image", source_path=str(source))
    assert width[0].options == {"max_width": 16, "max_height": 24}
    height, _logo, _filter = media_cli._parse_pipeline_dsl("crop(height: 8)", "image", source_path=str(source))
    assert height[0].options == {"max_width": 32, "max_height": 8}
    exact, _logo, _filter = media_cli._parse_pipeline_dsl("crop(width: 16, height: 8)", "image", source_path=str(source))
    assert [item.operation_id for item in exact] == ["image-crop", "image-resize"]
    assert exact[0].options == {"x": 0, "y": 4, "width": 32, "height": 16}
    assert exact[1].options == {"max_width": 16, "max_height": 8}
    chained, _logo, _filter = media_cli._parse_pipeline_dsl(
        "crop(aspectRatio: 1:1) -> downscale(factor: 0.5)", "image", source_path=str(source),
    )
    assert chained[0].options == {"x": 4, "y": 0, "width": 24, "height": 24}
    assert chained[1].options == {"max_width": 12, "max_height": 12}


def test_pipeline_inline_run_rejects_shell_steps_and_mixed_media(tmp_path):
    for step, files, message in (
        ('runScript(code: "touch /tmp/no")', ["image.png"], "unsupported for image"),
        ("convert(to: webp)", ["image.png", "clip.mov"], "one media type per run"),
    ):
        stderr = io.StringIO()
        arguments = ["pipeline", "run", step, *files, "--output-dir", str(tmp_path / "outputs")]
        assert run(arguments, io.StringIO(), stderr) == 2
        assert message in stderr.getvalue()


def test_cli_settings_reject_invalid_operations_json_and_preparation_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "officekit.engines.engine_media_operation_defaults.media_operation_defaults_path",
        lambda: str(tmp_path / "defaults.json"),
    )
    for arguments, expected in (
        (["--settings", "set", "--operation-id", "run-script", "--options-json", "{}"], "Unsupported media operation"),
        (["--settings", "set", "--operation-id", "image-optimize", "--options-json", "[]"], "JSON object"),
        (["--settings", "get"], "requires --operation-id"),
        (["--settings", "list", "--output-dir", str(tmp_path)], "do not accept media files"),
        (["--settings", "clear", "--options-json", "{}"], "available only with --settings set"),
        (["--settings", "set", "--operation-id", "image-optimize", "--options-json", " " * (16 * 1024 + 1)], "exceeds the 16 KiB settings limit"),
        (["--settings", "set", "--operation-id", "image-optimize", "--options-json", "[" * 1200 + "0" + "]" * 1200], "JSON object"),
    ):
        stderr = io.StringIO()
        assert run(arguments, io.StringIO(), stderr) == 2
        assert expected in stderr.getvalue()


def test_smart_crop_geometry_contains_salient_bounds_and_keeps_requested_ratio():
    crop = media_cli._smart_crop_rectangle(
        400, 200, "1:1", {"x": 0.75, "y": 0.4, "width": 0.1, "height": 0.2, "detected": True},
    )
    assert crop == {"x": 200, "y": 0, "width": 200, "height": 200}


def test_smart_crop_without_saliency_uses_center_crop_and_rejects_invalid_bounds():
    center = media_cli._crop_rectangle(400, 200, "1:1")
    fallback = media_cli._smart_crop_rectangle(
        400, 200, "1:1", {"x": 0.5, "y": 0.5, "width": 0.0, "height": 0.0, "detected": False},
    )
    assert fallback == center
    with pytest.raises(ValueError, match="saliency"):
        media_cli._smart_crop_rectangle(
            400, 200, "1:1", {"x": 0.9, "y": 0.5, "width": 0.2, "height": 0.1, "detected": True},
        )


def test_pipeline_inline_smart_crop_uses_salient_region_and_preserves_source(tmp_path, monkeypatch):
    source = tmp_path / "subject.png"
    image = Image.new("RGB", (400, 200), (20, 40, 220))
    for x in range(300, 340):
        for y in range(80, 120):
            image.putpixel((x, y), (230, 30, 20))
    image.save(source, format="PNG")
    original = source.read_bytes()
    monkeypatch.setattr(media_cli, "probe_smart_crop_bounds", lambda _path, _media: {
        "sourceWidth": 400, "sourceHeight": 200, "x": 0.75, "y": 0.4,
        "width": 0.1, "height": 0.2, "detected": True,
    })
    output_dir = tmp_path / "smart-output"
    stdout = io.StringIO()
    stderr = io.StringIO()
    step = "crop(aspectRatio: 1:1, smartCrop: true)"
    assert run(["pipeline", "run", step, str(source), "--output-dir", str(output_dir)], stdout, stderr) == 0, stderr.getvalue()
    output_name = json.loads(stdout.getvalue())["results"][0]["output"]
    with Image.open(output_dir / output_name) as output:
        assert output.size == (200, 200)
        assert output.getpixel((120, 100))[0] > 200
    assert source.read_bytes() == original
