import pytest

from officekit.engines import engine_media_capabilities as capabilities


@pytest.mark.parametrize("ready", [False, True])
def test_workbench_optional_formats_follow_actual_encoder_probes(monkeypatch, ready):
    monkeypatch.setattr(capabilities, "native_media_operation_available", lambda _operation: True)
    monkeypatch.setattr(capabilities, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(capabilities, "native_audio_format_available", lambda _format: ready)
    monkeypatch.setattr(capabilities, "native_video_format_available", lambda _format: ready, raising=False)
    operations = {operation["id"]: operation for group in capabilities.media_capabilities()["media"] for operation in group["operations"]}
    for operation in ("video-optimize", "video-fit-size"):
        for target in ("mp4", "webm", "x265"):
            assert (target in operations[operation]["formats"]) is ready
    for operation in ("audio-optimize", "audio-convert", "audio-fit-size"):
        for target in ("flac", "mp3"):
            assert (target in operations[operation]["formats"]) is ready
    assert operations["video-watermark-overlay"]["available"] is True
    assert operations["video-watermark-overlay"]["formats"] == ["mov"]
