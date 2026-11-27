import json
import os
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from officekit.engines import engine_media_native as native
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_converter import ImageOutputLimitError


class FakeProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_probe_video_dimensions_uses_private_environment_and_validates_bounds(monkeypatch, tmp_path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"bounded video bytes")
    captured = {}
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b'{"width":1920,"height":1080}', stderr=b"")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert native.probe_video_dimensions(source) == (1920, 1080)
    assert captured["args"] == ["/private/officekit-media-transform", "video-info", str(source)]
    assert captured["kwargs"]["timeout"] == 10
    assert captured["kwargs"]["env"]["PATH"] == "/usr/bin:/bin"
    assert captured["kwargs"]["capture_output"] is True


@pytest.mark.parametrize("cancel_at", [1, 2, 3])
def test_smart_crop_probe_honors_cancellation_before_copy_during_copy_and_after_analysis(monkeypatch, tmp_path, cancel_at):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    calls = []

    class Cancel:
        checks = 0

        def is_set(self):
            self.checks += 1
            return self.checks >= cancel_at

    def analyze(args, *_args, **kwargs):
        calls.append(args)
        return b"{}"

    monkeypatch.setattr(native, "_run_smart_crop_probe", analyze)
    with pytest.raises(native.NativeMediaCancelledError):
        native.probe_smart_crop_bounds(source, "image", cancel_event=Cancel())
    assert len(calls) == (1 if cancel_at == 3 else 0)
    assert not calls or not Path(calls[0][2]).exists()
    assert source.read_bytes() == b"source"


def test_smart_crop_probe_streams_private_video_copy_in_bounded_chunks(monkeypatch, tmp_path):
    source = tmp_path / "source.mov"
    original = b"x" * (2 * 1024 * 1024 + 7)
    source.write_bytes(original)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    real_fdopen = native.os.fdopen
    reads = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def read(self, size):
            assert 0 < size <= 1024 * 1024
            reads.append(size)
            return self.stream.read(size)

    def fdopen(descriptor, mode, **kwargs):
        stream = real_fdopen(descriptor, mode, **kwargs)
        return Reader(stream) if mode == "rb" else stream

    def analyze(args, *_args, **_kwargs):
        assert Path(args[2]).read_bytes() == original
        return b'{"width":200,"height":100,"x":0.5,"y":0.5,"boxWidth":0,"boxHeight":0,"detected":false}'

    monkeypatch.setattr(native.os, "fdopen", fdopen)
    monkeypatch.setattr(native, "_run_smart_crop_probe", analyze)
    assert native.probe_smart_crop_bounds(source, "video")["sourceWidth"] == 200
    assert reads == [1024 * 1024] * 4
    assert source.read_bytes() == original


@pytest.mark.parametrize("oversize", [False, True])
def test_smart_crop_analysis_uses_bounded_private_stdout_and_reports_bad_output(monkeypatch, tmp_path, oversize):
    captured = {}

    def popen(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        kwargs["stdout"].write(b"x" * (4097 if oversize else 2))
        kwargs["stdout"].flush()
        return FakeProcess()

    monkeypatch.setattr(native.subprocess, "Popen", popen)
    if oversize:
        with pytest.raises(ConversionInputError):
            native._run_smart_crop_probe(["/private/helper", "smart-crop-bounds"], str(tmp_path), None)
    else:
        assert native._run_smart_crop_probe(["/private/helper", "smart-crop-bounds"], str(tmp_path), None) == b"xx"
    assert captured["args"] == ["/private/helper", "smart-crop-bounds"]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["env"] == {"HOME": str(tmp_path), "TMPDIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    assert captured["kwargs"]["stdin"] == native.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == native.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"].closed


def test_smart_crop_analysis_cancels_a_live_helper_process(monkeypatch, tmp_path):
    process = FakeProcess(returncode=None)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_args, **_kwargs: process)
    cancel = SimpleNamespace(is_set=lambda: True)
    with pytest.raises(native.NativeMediaCancelledError):
        native._run_smart_crop_probe(["/private/helper"], str(tmp_path), cancel)
    assert process.terminated is True


def test_bounded_runner_honors_shorter_analysis_deadline(tmp_path):
    output = tmp_path / "probe.json"
    output.write_bytes(b"{}")
    process = FakeProcess(returncode=None)
    ticks = iter((0, 21))
    with pytest.raises(ConversionInputError):
        native._run_bounded(["/private/helper"], str(output), str(tmp_path), timeout_seconds=20,
                            popen=lambda *_args, **_kwargs: process, clock=lambda: next(ticks), sleeper=lambda _seconds: None)
    assert process.killed is True


def test_probe_smart_crop_bounds_uses_local_helper_and_validates_json(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"bounded image bytes")
    captured = {}
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")

    def fake_run(args, workspace, cancel_event):
        captured["args"] = args
        captured["workspace"] = workspace
        captured["cancel"] = cancel_event
        return b'{"width":400,"height":200,"x":0.7,"y":0.3,"boxWidth":0.2,"boxHeight":0.4,"detected":true}'

    monkeypatch.setattr(native, "_run_smart_crop_probe", fake_run)
    assert native.probe_smart_crop_bounds(source, "image") == {
        "sourceWidth": 400, "sourceHeight": 200, "x": 0.7, "y": 0.3,
        "width": 0.2, "height": 0.4, "detected": True,
    }
    assert captured["args"][0:2] == ["/private/officekit-media-transform", "smart-crop-bounds"]
    assert Path(captured["args"][2]).name == "source.png"
    assert captured["args"][2] != str(source)
    assert captured["cancel"] is None
    assert not Path(captured["workspace"]).exists()


@pytest.mark.parametrize("payload", [
    b'{"width":true,"height":200,"x":0,"y":0,"boxWidth":0.1,"boxHeight":0.1,"detected":true}',
    b'{"width":400,"height":200,"x":0.9,"y":0,"boxWidth":0.2,"boxHeight":0.1,"detected":true}',
    b'{"width":400,"height":200,"x":NaN,"y":0,"boxWidth":0.1,"boxHeight":0.1,"detected":true}',
    b'{"width":400,"height":200,"x":0.5,"y":0.5,"boxWidth":0,"boxHeight":0,"detected":true}',
])
def test_probe_smart_crop_bounds_rejects_invalid_helper_output(monkeypatch, tmp_path, payload):
    source = tmp_path / "source.png"
    source.write_bytes(b"bounded image bytes")
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")
    monkeypatch.setattr(native, "_run_smart_crop_probe", lambda *_args, **_kwargs: payload)
    with pytest.raises(ConversionInputError):
        native.probe_smart_crop_bounds(source, "image")


def test_probe_smart_crop_bounds_rejects_symlinks_without_launching_helper(monkeypatch, tmp_path):
    target = tmp_path / "target.png"
    target.write_bytes(b"image bytes")
    source = tmp_path / "linked.png"
    source.symlink_to(target)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")
    monkeypatch.setattr(native, "_run_smart_crop_probe", lambda *_args, **_kwargs: pytest.fail("helper must not run for a symlink"))
    with pytest.raises(ConversionInputError):
        native.probe_smart_crop_bounds(source, "image")


@pytest.mark.parametrize("payload", [
    b"[]", b'{"width":0,"height":100}', b'{"width":10001,"height":100}',
    b'{"width":true,"height":100}',
])
def test_probe_video_dimensions_rejects_invalid_or_oversized_results(monkeypatch, tmp_path, payload):
    source = tmp_path / "source.mov"
    source.write_bytes(b"bounded video bytes")
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=payload))
    with pytest.raises(ConversionInputError):
        native.probe_video_dimensions(source)


def test_probe_audio_duration_uses_private_environment_and_bounds(monkeypatch, tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"bounded audio bytes")
    captured = {}
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b'{"duration":60.5}', stderr=b"")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert native.probe_audio_duration(source) == 60.5
    assert captured["args"] == ["/private/officekit-media-transform", "audio-info", str(source)]
    assert captured["kwargs"]["timeout"] == 10
    assert captured["kwargs"]["env"]["PATH"] == "/usr/bin:/bin"


@pytest.mark.parametrize("payload", [b"[]", b'{"duration":0}', b'{"duration":121}', b'{"duration":true}'])
def test_probe_audio_duration_rejects_invalid_results(monkeypatch, tmp_path, payload):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"bounded audio bytes")
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/officekit-media-transform")
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=payload))
    with pytest.raises(ConversionInputError):
        native.probe_audio_duration(source)


def test_native_media_runtime_is_available_only_for_executable_mac_tools(monkeypatch, tmp_path):
    tool = tmp_path / "avconvert"
    tool.write_bytes(b"runtime")
    tool.chmod(0o755)
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"video": str(tool), "audio": "/missing"})
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    assert native.native_media_available("video") is True
    assert native.native_media_available("audio") is False
    assert native.native_media_available("unknown") is False
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    assert native.native_media_available("video") is False


def test_native_media_extension_and_fixed_argument_maps(monkeypatch):
    assert native._safe_extension("clip.MOV") == "mov"
    assert native._safe_extension("no extension") == "media"
    assert native._safe_extension("file.bad!ext") == "media"
    assert native._video_candidate("in", "out", "m4v", "smaller")[4] == "PresetAppleM4V480pSD"
    assert native._video_candidate("in", "out", "mov", "higher")[4] == "PresetHighestQuality"
    assert native._video_candidate("in", "out.mov", "hevc", "higher")[4] == "PresetHEVCHighestQuality"
    with pytest.raises(native.NativeMediaUnavailableError):
        native._video_candidate("in", "out", "webm", "balanced")
    assert native._audio_candidate("in", "out", "m4a", 128)[1:8] == ["-f", "m4af", "-d", "aac@44100", "-b", "128000", "in"]
    assert native._audio_candidate("in", "out", "wav", 128)[1:5] == ["-f", "WAVE", "-d", "LEI16"]
    assert native._audio_candidate("in", "out", "aiff", 128)[1:5] == ["-f", "AIFF", "-d", "BEI16"]
    assert native._audio_candidate("in", "out", "flac", 128)[1:5] == ["-f", "flac", "-d", "flac"]
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_format_available", lambda target: target == "mp3")
    mp3_args = native._audio_candidate("in", "out", "mp3", 128)
    assert mp3_args[:7] == ["/opt/homebrew/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe"]
    assert mp3_args[-5:] == ["-b:a", "128k", "-f", "mp3", "out"]
    with pytest.raises(native.NativeMediaUnavailableError):
        native._audio_candidate("in", "out", "ogg", 128)


def test_native_hevc_probe_requires_the_system_encoder_preset(monkeypatch):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    native.native_hevc_encoder_available.cache_clear()
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: native.subprocess.CompletedProcess(
        ["avconvert"], 205, stdout=b"PresetHEVCHighestQuality", stderr=b"usage",
    ))
    assert native.native_hevc_encoder_available() is True
    native.native_hevc_encoder_available.cache_clear()
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: native.subprocess.CompletedProcess(
        ["avconvert"], 205, stdout=b"PresetHighestQuality", stderr=b"usage",
    ))
    assert native.native_hevc_encoder_available() is False
    native.native_hevc_encoder_available.cache_clear()


def test_native_audio_flac_probe_requires_a_successful_private_encode(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    native.native_audio_format_available.cache_clear()
    def encode(args, **_kwargs):
        Path(args[-1]).write_bytes(b"fLaC" + b"x" * 100)
        return native.subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
    monkeypatch.setattr(native.subprocess, "run", encode)
    assert native.native_audio_format_available("flac") is True
    native.native_audio_format_available.cache_clear()
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: native.subprocess.CompletedProcess([], 1))
    assert native.native_audio_format_available("flac") is False
    native.native_audio_format_available.cache_clear()


def test_native_audio_mp3_probe_requires_the_optional_ffmpeg_encoder(monkeypatch):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    native._probe_ffmpeg_mp3_encoder.cache_clear()
    def encode(args, **_kwargs):
        Path(args[-1]).write_bytes(b"ID3" + b"x" * 100)
        return native.subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
    monkeypatch.setattr(native.subprocess, "run", encode)
    native.native_audio_format_available.cache_clear()
    assert native.native_audio_format_available("mp3") is True
    native.native_audio_format_available.cache_clear()
    native._probe_ffmpeg_mp3_encoder.cache_clear()
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: native.subprocess.CompletedProcess([], 1))
    assert native.native_audio_format_available("mp3") is False
    native.native_audio_format_available.cache_clear()
    native._probe_ffmpeg_mp3_encoder.cache_clear()


def test_native_audio_loudnorm_probe_requires_json_metrics_and_m4a(monkeypatch):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    native.native_audio_loudnorm_available.cache_clear()
    def encode(args, **_kwargs):
        with wave.open(args[args.index("-i") + 1], "rb") as source:
            assert source.getnchannels() == 2 and source.getframerate() == 8000
            assert source.getnframes() >= 3200
            assert any(source.readframes(source.getnframes()))
        Path(args[-1]).write_bytes(b"\0\0\0\x18ftypM4A \0\0\0\0")
        metrics = b'{"input_i":"-21.0","output_i":"-14.0","output_tp":"-2.1","normalization_type":"linear"}'
        return native.subprocess.CompletedProcess(args, 0, stdout=b"", stderr=metrics)
    monkeypatch.setattr(native.subprocess, "run", encode)
    assert native.native_audio_loudnorm_available() is True
    native.native_audio_loudnorm_available.cache_clear()
    monkeypatch.setattr(native.subprocess, "run", lambda *_args, **_kwargs: native.subprocess.CompletedProcess([], 1))
    assert native.native_audio_loudnorm_available() is False
    native.native_audio_loudnorm_available.cache_clear()


def test_ffmpeg_loudnorm_uses_file_only_protocols_and_reports_true_peak(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source = tmp_path / "surround.wav"
    source.write_bytes(b"source audio")
    output = tmp_path / "normalized.m4a"
    stderr = (
        b'{"input_i":"-21.2","input_tp":"-1.0","output_i":"-14.1","output_tp":"-2.0",'
        b'"normalization_type":"dynamic"}'
    )
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        if args[-1] == "-":
            assert args[args.index("-i") + 1] == str(output)
            kwargs["stderr"].write(b'{"input_i":"-14.3","input_tp":"-2.2","output_i":"-14.0","output_tp":"-2.0","normalization_type":"dynamic"}')
        else:
            kwargs["stderr"].write(stderr)
            Path(args[-1]).write_bytes(b"\0\0\0\x18ftypM4A normalized")
            assert args[args.index("-i") + 1] == str(source)
            assert args[args.index("-ar") + 1] == "48000"
            assert "-ac" not in args
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert args[args.index("-format_whitelist") + 1] == "aac,aiff,caf,flac,mov,mp3,wav"
        return FakeProcess()

    native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen)
    attributes = native._normalization_attributes(str(output), {"target_lufs": -14})
    assert attributes == {
        "target_lufs": -14.0, "input_lufs": -21.2, "output_lufs": -14.3,
        "true_peak_dbfs": -2.2, "normalization_mode": "dynamic", "peak_limited": True,
        "target_met": True, "true_peak_ceiling_dbfs": -2.0,
    }
    assert source.read_bytes() == b"source audio"
    assert len(calls) == 2
    assert not Path(f"{output}.metrics.json").exists()


@pytest.mark.parametrize("peaks,loudness,expected_filters,limited", [
    ([0.3, -2.25], [-19.5, -20.0], [(-14, -2), (-14, -4.55)], True),
    ([-10, -10], [-13.1, -14.0], [(-14, -2), (-14.9, -2)], False),
    ([-10, -10, -10], [-12, -12, -12], [(-14, -2), (-16, -2), (-18, -2)], False),
])
def test_loudness_retries_from_original_and_reports_final_decoded_metrics(monkeypatch, tmp_path, peaks, loudness, expected_filters, limited):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"original audio")
    calls = []

    def popen(args, **kwargs):
        attempt = len(calls) // 2
        measuring = args[-1] == "-"
        calls.append(args)
        assert args[args.index("-i") + 1] == str(output if measuring else source)
        if not measuring:
            assert args[args.index("-af") + 1] == f"loudnorm=I={expected_filters[attempt][0]:.2f}:LRA=11:TP={expected_filters[attempt][1]:.2f}:print_format=json"
            output.write_bytes(b"encoded original")
        metrics = {"input_i": str(loudness[attempt] if measuring else -21),
                   "input_tp": str(peaks[attempt] if measuring else -1), "output_i": "-14",
                   "output_tp": str(-10 if not limited else expected_filters[attempt][1]), "normalization_type": "dynamic"}
        kwargs["stderr"].write(json.dumps(metrics).encode())
        return FakeProcess()

    native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen)
    attrs = native._normalization_attributes(str(output), {"target_lufs": -14})
    assert len(calls) == 2 * len(expected_filters)
    assert attrs["output_lufs"] == loudness[-1] and attrs["true_peak_dbfs"] == peaks[-1]
    assert attrs["peak_limited"] is limited
    assert attrs["target_met"] is (abs(loudness[-1] + 14) <= 0.5)
    assert source.read_bytes() == b"original audio"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["output.m4a", "source.wav"]


def test_loudness_exhaustion_preserves_source_and_removes_unverified_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"original")
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        if args[-1] != "-":
            assert args[args.index("-i") + 1] == str(source)
            output.write_bytes(b"encoded")
        kwargs["stderr"].write(b'{"input_i":"-14","input_tp":"0.3","output_i":"-14","output_tp":"-2","normalization_type":"dynamic"}')
        return FakeProcess()

    with pytest.raises(ConversionInputError):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen)
    assert len(calls) == 6
    assert list(tmp_path.iterdir()) == [source] and source.read_bytes() == b"original"


def test_loudness_passes_share_one_deadline(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"original")
    ticks = iter((0, 0, 121))
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        output.write_bytes(b"encoded")
        kwargs["stderr"].write(b'{"input_i":"-21","input_tp":"-5","output_i":"-14","output_tp":"-8","normalization_type":"dynamic"}')
        return FakeProcess()

    with pytest.raises(ConversionInputError):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen, clock=lambda: next(ticks))
    assert len(calls) == 1 and list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("completed", [False, True])
def test_loudness_cancellation_during_decoded_measurement_discards_candidate(monkeypatch, tmp_path, completed):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"original")
    cancel = SimpleNamespace(cancelled=False)
    cancel.is_set = lambda: cancel.cancelled
    measurement = FakeProcess(0 if completed else None)

    def popen(args, **kwargs):
        kwargs["stderr"].write(b'{"input_i":"-14","input_tp":"-4","output_i":"-14","output_tp":"-4","normalization_type":"dynamic"}')
        if args[-1] == "-":
            cancel.cancelled = True
            return measurement
        output.write_bytes(b"encoded")
        return FakeProcess()

    with pytest.raises(native.NativeMediaCancelledError):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, cancel_event=cancel, popen=popen)
    assert completed or measurement.terminated
    assert list(tmp_path.iterdir()) == [source]


def test_loudness_never_replaces_an_existing_output(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"source")
    output.write_bytes(b"user output")
    with pytest.raises(ConversionInputError):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14,
                                  popen=lambda *_args, **_kwargs: pytest.fail("must not launch"))
    assert output.read_bytes() == b"user output" and source.read_bytes() == b"source"


@pytest.mark.parametrize("failure,expected", [
    ("exit", ConversionInputError), ("invalid-metrics", ConversionInputError),
    ("missing-decoded-peak", ConversionInputError), ("empty-output", ConversionInputError),
    ("large-output", ImageOutputLimitError), ("large-log", ImageOutputLimitError),
    ("workspace-limit", ImageOutputLimitError),
])
def test_loudness_failures_clean_private_outputs_and_logs(monkeypatch, tmp_path, failure, expected):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    if failure == "large-output":
        monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    if failure == "workspace-limit":
        monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", 1)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"source")
    processes = []

    def popen(args, **kwargs):
        measuring = args[-1] == "-"
        metrics = {"input_i": "-14", "input_tp": "-4", "output_i": "-14", "output_tp": "-4", "normalization_type": "dynamic"}
        if measuring and failure == "missing-decoded-peak":
            metrics.pop("input_tp")
        log = json.dumps(metrics).encode()
        if failure == "invalid-metrics":
            log = b"not JSON"
        if failure == "large-log":
            log = b"x" * 65_537
        kwargs["stderr"].write(log)
        kwargs["stderr"].flush()
        if not measuring and failure != "empty-output":
            output.write_bytes(b"encoded")
        process = FakeProcess(1 if failure == "exit" else None if failure in {"large-output", "large-log", "workspace-limit"} else 0)
        processes.append(process)
        return process

    with pytest.raises(expected):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen)
    assert list(tmp_path.iterdir()) == [source]
    assert source.read_bytes() == b"source"
    if failure in {"large-output", "large-log", "workspace-limit"}:
        assert processes[0].terminated


def test_loudness_preserves_an_existing_metrics_file(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: True)
    source, output = tmp_path / "source.wav", tmp_path / "output.m4a"
    source.write_bytes(b"source")
    metrics = Path(f"{output}.metrics.json")
    metrics.write_bytes(b"user-owned")

    def popen(args, **kwargs):
        if args[-1] != "-":
            output.write_bytes(b"encoded")
        kwargs["stderr"].write(b'{"input_i":"-14","input_tp":"-4","output_i":"-14","output_tp":"-4","normalization_type":"dynamic"}')
        return FakeProcess()

    with pytest.raises(ConversionInputError):
        native._run_ffmpeg_loudnorm(str(source), str(output), str(tmp_path), -14, popen=popen)
    assert metrics.read_bytes() == b"user-owned" and not output.exists()


@pytest.mark.parametrize("peak_key", ["true_peak_dbfs", "sample_peak_dbfs"])
def test_normalization_target_status_includes_the_encoded_peak_ceiling(tmp_path, peak_key):
    output = tmp_path / "output.m4a"
    metrics = {"input_lufs": -21, "output_lufs": -14, "peak_limited": True, peak_key: -1.5}
    metrics.update({"normalization_mode": "dynamic"} if peak_key == "true_peak_dbfs" else {"applied_gain_db": 7})
    Path(f"{output}.metrics.json").write_text(json.dumps(metrics))
    assert native._normalization_attributes(str(output), {"target_lufs": -14})["target_met"] is False


@pytest.mark.parametrize("payload", [
    b'{}', b'{broken}',
    b'{"input_i":true,"output_i":-14,"output_tp":-4,"normalization_type":"dynamic"}',
    b'{"input_i":null,"output_i":-14,"output_tp":-4,"normalization_type":"dynamic"}',
    b'{"input_i":"-inf","output_i":-14,"output_tp":-4,"normalization_type":"dynamic"}',
    b'{"input_i":-21,"output_i":-14,"output_tp":-4,"normalization_type":"unknown"}',
])
def test_loudness_parser_rejects_invalid_or_nonfinite_metrics(payload):
    assert native._parse_ffmpeg_loudnorm(payload) is None


@pytest.mark.parametrize("tool,available", [(None, True), ("/local/ffmpeg", False)])
def test_loudness_unavailable_does_not_create_outputs(monkeypatch, tmp_path, tool, available):
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: tool)
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: available)
    with pytest.raises(native.NativeMediaUnavailableError):
        native._run_ffmpeg_loudnorm("source", str(tmp_path / "result.m4a"), str(tmp_path), -14)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["missing", "oversize", "schema", "boolean", "nonfinite", "mode", "valid-native"])
def test_normalization_metrics_boundary_and_cleanup(tmp_path, failure):
    output = tmp_path / "output.m4a"
    sidecar = Path(f"{output}.metrics.json")
    metrics = {"input_lufs": -21, "output_lufs": -14, "peak_limited": False,
               "sample_peak_dbfs": -4, "applied_gain_db": 7}
    if failure == "schema":
        metrics["extra"] = True
    if failure == "boolean":
        metrics["output_lufs"] = True
    if failure == "nonfinite":
        metrics["output_lufs"] = float("nan")
    if failure == "mode":
        metrics.pop("sample_peak_dbfs")
        metrics.pop("applied_gain_db")
        metrics.update(true_peak_dbfs=-4, normalization_mode="unknown")
    if failure != "missing":
        sidecar.write_text("x" * 4097 if failure == "oversize" else json.dumps(metrics))
    if failure == "valid-native":
        result = native._normalization_attributes(str(output), {"target_lufs": -14})
        assert result == {**metrics, "target_lufs": -14.0, "target_met": True, "peak_ceiling_dbfs": -2.0}
    else:
        with pytest.raises(ConversionInputError):
            native._normalization_attributes(str(output), {"target_lufs": -14})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["pre-cancel", "cancel-kill", "limit-kill", "deadline", "final-workspace", "final-output", "success-after-poll"])
def test_loudness_pass_resource_lifecycle(monkeypatch, tmp_path, failure):
    output = tmp_path / "output.m4a"
    output.write_bytes(b"encoded")
    process = FakeProcess(None)
    waits = []
    polls = []

    def poll():
        polls.append(True)
        return 0 if failure in {"final-workspace", "final-output"} or len(polls) > 1 else None

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is not None:
            raise native.subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0

    process.poll, process.wait = poll, wait
    if failure in {"limit-kill", "final-workspace"}:
        monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", 1)
    if failure == "final-output":
        monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 1)
    cancel = SimpleNamespace(is_set=lambda: failure == "pre-cancel" or (failure == "cancel-kill" and bool(polls)))
    ticks = iter((0, 2))
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        kwargs["stderr"].write(b'{"input_i":"-14","input_tp":"-4","output_i":"-14","output_tp":"-4","normalization_type":"dynamic"}')
        return process

    expected = (native.NativeMediaCancelledError if failure in {"pre-cancel", "cancel-kill"}
                else ConversionInputError if failure == "deadline" else ImageOutputLimitError)
    arguments = (["ffmpeg"], str(output), str(tmp_path), cancel, 1, popen,
                 (lambda: next(ticks)) if failure == "deadline" else (lambda: 0), lambda _seconds: None)
    if failure == "success-after-poll":
        assert native._run_audio_loudness_pass(*arguments)["input_i"] == -14
        assert len(polls) == 2 and waits == [None]
    else:
        with pytest.raises(expected):
            native._run_audio_loudness_pass(*arguments)
        assert len(calls) == (0 if failure == "pre-cancel" else 1)
        if failure in {"cancel-kill", "limit-kill", "deadline"}:
            assert process.killed
    assert list(tmp_path.iterdir()) == [output]


def test_video_transform_helper_uses_fixed_operations_and_bounded_speed(monkeypatch, tmp_path):
    helper = tmp_path / "officekit-media-transform"
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: str(helper))
    assert native._video_transform_candidate("in", "out", "video-mute", {}) == [str(helper), "video-mute", "in", "out", "0"]
    assert native._video_transform_candidate("in", "out", "video-strip-metadata", {}) == [
        str(helper), "video-strip-metadata", "in", "out",
    ]
    assert native._video_transform_candidate("in", "out", "video-speed", {"factor_percent": 150})[-1] == "150"
    assert native._video_transform_candidate("in", "out", "video-to-gif", {
        "fps": 12, "max_width": 320, "max_duration_seconds": 8,
    }) == [str(helper), "video-to-gif", "in", "out", "12", "320", "8"]
    assert native._video_transform_candidate("in", "out", "video-crop", {
        "x": 2, "y": 3, "width": 640, "height": 360,
    }) == [str(helper), "video-crop", "in", "out", "2", "3", "640", "360"]
    assert native._video_transform_candidate("in", "out", "video-resize", {
        "max_width": 1280, "max_height": 720,
    }) == [str(helper), "video-resize", "in", "out", "1280", "720"]
    assert native._video_transform_candidate("in", "out", "video-resize", {
        "max_width": 1280, "max_height": 720, "fps": 24,
    }) == [str(helper), "video-resize", "in", "out", "1280", "720", "24"]
    assert native._video_transform_candidate("in", "out", "video-watermark-overlay", {
        "placement": "top-left", "margin_percent": 4, "size_percent": 20, "opacity_percent": 80,
    }, "/private/work/watermark.png") == [
        str(helper), "video-watermark-overlay", "in", "out", "/private/work/watermark.png",
        "top-left", "4", "20", "80",
    ]
    assert native._video_transform_candidate("in", "out", "video-watermark-overlay", {
        "placement": "top-left", "size_percent": 20, "opacity_percent": 80,
    }, "/private/work/watermark.png")[-4:] == ["top-left", "4", "20", "80"]
    with pytest.raises(native.NativeMediaUnavailableError):
        native._video_transform_candidate("in", "out", "video-rotate", {})
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    with pytest.raises(native.NativeMediaUnavailableError):
        native._video_transform_candidate("in", "out", "video-mute", {})


def test_video_watermark_file_adapter_uses_only_private_staged_logo_and_preserves_source(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.mov"
    logo = workspace / "watermark.png"
    source.write_bytes(b"original-video")
    logo.write_bytes(b"validated-logo")
    source_hash, logo_hash = source.read_bytes(), logo.read_bytes()
    calls = []

    def runner(args, output_path, _workspace, _cancel):
        calls.append(args)
        Path(output_path).write_bytes(b"watermarked-video")

    result = native.convert_native_media_to_file(
        str(source), source.name, "video-watermark-overlay",
        {"placement": "top-left", "margin_percent": 4, "size_percent": 20, "opacity_percent": 80},
        str(workspace), runner=runner, watermark_image_path=str(logo),
    )
    output, extension, media_type, attributes, size = result
    assert calls == [[
        "/private/helper", "video-watermark-overlay", str(source), output, str(logo),
        "top-left", "4", "20", "80",
    ]]
    assert extension == "mov" and media_type == "video/quicktime"
    assert attributes == {"watermarked": True, "placement": "top-left", "margin_percent": 4, "size_percent": 20, "opacity_percent": 80}
    assert size == len(b"watermarked-video")
    assert source.read_bytes() == source_hash and logo.read_bytes() == logo_hash

    outside_logo = tmp_path / "outside.png"
    outside_logo.write_bytes(b"not a staged logo")
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(
            str(source), source.name, "video-watermark-overlay", {}, str(workspace),
            runner=runner, watermark_image_path=str(outside_logo),
        )


def test_audio_artwork_helper_uses_bounded_local_transform(monkeypatch, tmp_path):
    helper = tmp_path / "officekit-media-transform"
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: str(helper))
    assert native._audio_transform_candidate("in", "out", "audio-artwork", {"max_edge": 512}) == [
        str(helper), "audio-artwork", "in", "out", "512",
    ]
    assert native._audio_transform_candidate("in", "out", "audio-speed", {"factor_percent": 150}) == [
        str(helper), "audio-speed", "in", "out", "150",
    ]
    assert native._audio_transform_candidate("in", "out", "audio-normalize", {"target_lufs": -14}) == [
        str(helper), "audio-normalize", "in", "out", "-14", "out.metrics.json",
    ]
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    with pytest.raises(native.NativeMediaUnavailableError):
        native._audio_transform_candidate("in", "out", "audio-artwork", {"max_edge": 512})


def test_bounded_runner_returns_only_after_a_small_successful_output(tmp_path):
    output = tmp_path / "output.bin"
    output.write_bytes(b"good")
    process = FakeProcess()
    native._run_bounded(["/usr/bin/tool"], str(output), str(tmp_path), popen=lambda *_a, **_k: process, sleeper=lambda _delay: None)


def test_bounded_runner_rejects_nonzero_exit_missing_empty_and_oversized_outputs(tmp_path, monkeypatch):
    output = tmp_path / "output.bin"
    output.write_bytes(b"x")
    with pytest.raises(ConversionInputError):
        native._run_bounded([], str(output), str(tmp_path), popen=lambda *_a, **_k: FakeProcess(1), sleeper=lambda _delay: None)
    with pytest.raises(ConversionInputError):
        native._run_bounded([], str(tmp_path / "missing"), str(tmp_path), popen=lambda *_a, **_k: FakeProcess(), sleeper=lambda _delay: None)
    output.write_bytes(b"")
    with pytest.raises(ConversionInputError):
        native._run_bounded([], str(output), str(tmp_path), popen=lambda *_a, **_k: FakeProcess(), sleeper=lambda _delay: None)
    output.write_bytes(b"12345")
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    with pytest.raises(ImageOutputLimitError):
        native._run_bounded([], str(output), str(tmp_path), popen=lambda *_a, **_k: FakeProcess(), sleeper=lambda _delay: None)

    class RunningProcess(FakeProcess):
        def poll(self): return None
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    process = RunningProcess()
    def write_large_output(*_args, **_kwargs):
        output.write_bytes(b"12345")
        return process
    with pytest.raises(ImageOutputLimitError):
        native._run_bounded([], str(output), str(tmp_path), popen=write_large_output, sleeper=lambda _delay: None)
    assert process.killed is True


def test_bounded_runner_enforces_cumulative_workspace_limit(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"123")
    output = tmp_path / "output.m4v"
    output.write_bytes(b"45")
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", 4)

    class RunningProcess(FakeProcess):
        def poll(self):
            return None

    process = RunningProcess()
    with pytest.raises(ImageOutputLimitError, match="workspace"):
        native._run_bounded(
            [], str(output), str(tmp_path), popen=lambda *_args, **_kwargs: process,
            sleeper=lambda _delay: None,
        )
    assert process.killed is True


def test_workspace_size_skips_files_that_disappear_during_scan(tmp_path, monkeypatch):
    file_path = tmp_path / "vanishing.bin"
    file_path.write_bytes(b"x")
    original_stat = native.os.stat

    def stat_with_race(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(file_path):
            raise FileNotFoundError(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(native.os, "stat", stat_with_race)
    assert native._workspace_size(tmp_path) == 0


def test_bounded_runner_checks_workspace_size_after_process_exits(tmp_path, monkeypatch):
    output = tmp_path / "output.bin"
    output.write_bytes(b"ok")
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", 1)
    monkeypatch.setattr(native, "_workspace_size", lambda _workspace: 2)
    with pytest.raises(ImageOutputLimitError, match="workspace"):
        native._run_bounded([], str(output), str(tmp_path), popen=lambda *_a, **_k: FakeProcess(), sleeper=lambda _delay: None)


def test_bounded_runner_kills_timed_out_and_cancelled_processes(tmp_path):
    class RunningProcess(FakeProcess):
        def poll(self): return None
    process = RunningProcess()
    clock_values = iter([0, 121])
    with pytest.raises(ConversionInputError):
        native._run_bounded([], str(tmp_path / "missing"), str(tmp_path), popen=lambda *_a, **_k: process, clock=lambda: next(clock_values), sleeper=lambda _delay: None)
    assert process.killed is True

    class Cancel:
        def is_set(self): return True
    process = RunningProcess()
    with pytest.raises(native.NativeMediaCancelledError):
        native._run_bounded([], str(tmp_path / "missing"), str(tmp_path), cancel_event=Cancel(), popen=lambda *_a, **_k: process, sleeper=lambda _delay: None)
    assert process.terminated is True

    class SlowProcess(FakeProcess):
        def __init__(self):
            super().__init__()
            self.wait_calls = 0
        def poll(self): return None
        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1: raise native.subprocess.TimeoutExpired("tool", timeout)
            return self.returncode
    process = SlowProcess()
    with pytest.raises(native.NativeMediaCancelledError):
        native._run_bounded([], str(tmp_path / "missing"), str(tmp_path), cancel_event=Cancel(), popen=lambda *_a, **_k: process, sleeper=lambda _delay: None)
    assert process.killed is True


def test_video_and_audio_adapters_write_outputs_to_private_workspaces(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_hevc_encoder_available", lambda: True)
    commands = []
    def runner(args, output_path, workspace, _cancel):
        commands.append(args)
        Path(output_path).write_bytes(b"prepared")
    video = native.convert_native_media(b"video", "clip.mov", "video-optimize", {"target_format": "m4v", "quality": "balanced"}, runner=runner)
    assert video == (b"prepared", "m4v", "video/x-m4v", {"quality": "balanced"})
    assert commands[-1][0] == "/usr/bin/avconvert"
    assert "--source" in commands[-1]
    assert Path(commands[-1][2]).parent.name.startswith("officekit-media-adapter-")

    hevc = native.convert_native_media(b"video", "clip.mov", "video-hevc-convert", {}, runner=runner)
    assert hevc == (b"prepared", "mov", "video/quicktime", {"codec": "hevc"})
    assert commands[-1][4] == "PresetHEVCHighestQuality"
    assert commands[-1][-1].endswith(".mov")

    fit = native.convert_native_media(b"video", "clip.mov", "video-fit-size", {"target_format": "mov", "quality": "higher", "target_bytes": 9}, runner=runner)
    assert fit[3]["target_met"] is True
    assert len(commands[-1]) > 0
    fit_missed = native.convert_native_media(b"video", "clip.mov", "video-fit-size", {"target_format": "m4v", "quality": "balanced", "target_bytes": 1}, runner=runner)
    assert fit_missed[3]["target_met"] is False

    audio = native.convert_native_media(b"audio", "track.wav", "audio-convert", {"target_format": "m4a", "bitrate_kbps": 128}, runner=runner)
    assert audio == (b"prepared", "m4a", "audio/mp4", {"bitrate_kbps": 128})
    assert commands[-1][0] == "/usr/bin/afconvert"
    audio_flac = native.convert_native_media(b"audio", "track.wav", "audio-convert", {"target_format": "flac", "bitrate_kbps": 128}, runner=runner)
    assert audio_flac == (b"prepared", "flac", "audio/flac", {"codec": "flac", "lossless": True})
    assert commands[-1][1:5] == ["-f", "flac", "-d", "flac"]
    audio_fit = native.convert_native_media(b"audio", "track.wav", "audio-fit-size", {"target_format": "wav", "bitrate_kbps": 96, "target_bytes": 5}, runner=runner)
    assert audio_fit[3]["target_met"] is False
    audio_fit_met = native.convert_native_media(b"audio", "track.wav", "audio-fit-size", {"target_format": "m4a", "bitrate_kbps": 128, "target_bytes": 10}, runner=runner)
    assert audio_fit_met[3]["target_met"] is True
    audio_flac_fit = native.convert_native_media(b"audio", "track.wav", "audio-fit-size", {"target_format": "flac", "bitrate_kbps": 128, "target_bytes": 10}, runner=runner)
    assert audio_flac_fit[3] == {"target_bytes": 10, "target_met": True, "codec": "flac", "lossless": True}


@pytest.mark.parametrize(("target_format", "encoder", "container", "mime", "codec"), [
    ("mp4", "libx264", "mp4", "video/mp4", "h264"),
    ("webm", "libvpx-vp9", "webm", "video/webm", "vp9"),
    ("x265", "libx265", "mp4", "video/mp4", "hevc"),
])
def test_optional_ffmpeg_video_formats_use_allowlisted_local_encoders(monkeypatch, tmp_path, target_format, encoder, container, mime, codec):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: False)
    monkeypatch.setattr(native, "native_video_format_available", lambda requested: requested == target_format)
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    source = tmp_path / "source.mov"
    source.write_bytes(b"original-video")
    commands = []

    def runner(args, output_path, workspace, _cancel):
        commands.append(args)
        Path(output_path).write_bytes(b"converted-video")

    result = native.convert_native_media_to_file(
        str(source), source.name, "video-optimize",
        {"target_format": target_format, "quality": "balanced"}, str(tmp_path), runner=runner,
    )
    output_path, extension, media_type, attributes, size = result
    command = commands[0]
    assert command[0] == "/opt/homebrew/bin/ffmpeg"
    assert command[command.index("-c:v") + 1] == encoder
    assert command[command.index("-f", command.index("-c:a")) + 1] == container
    assert "-protocol_whitelist" in command and command[command.index("-protocol_whitelist") + 1] == "file"
    assert extension == container and media_type == mime
    assert attributes == {"quality": "balanced", "codec": codec}
    assert Path(output_path).read_bytes() == b"converted-video" and size == len(b"converted-video")
    assert source.read_bytes() == b"original-video"


def test_webm_output_signature_requires_an_ebml_container():
    assert native._native_output_signature_valid("webm", b"\x1aE\xdf\xa3" + b"\x00" * 12)
    assert not native._native_output_signature_valid("webm", b"not a webm file")


@pytest.mark.parametrize(("factor", "expected_crf"), [(5, "18"), (55, "30"), (100, "40")])
def test_h264_video_compression_factor_maps_to_bounded_crf(monkeypatch, tmp_path, factor, expected_crf):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: False)
    monkeypatch.setattr(native, "native_video_format_available", lambda target: target == "mp4")
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    source = tmp_path / "clip.mov"
    source.write_bytes(b"source")
    commands = []

    def runner(args, output_path, workspace, _cancel):
        commands.append(args)
        Path(output_path).write_bytes(b"encoded")

    result = native.convert_native_media_to_file(
        str(source), source.name, "video-optimize",
        {"target_format": "mp4", "compression": factor}, str(tmp_path), runner=runner,
    )
    args = commands[0]
    assert args[args.index("-crf") + 1] == expected_crf
    assert result[3] == {"quality": "balanced", "compression": factor, "codec": "h264"}
    assert source.read_bytes() == b"source"


def test_native_file_adapter_returns_the_output_path_without_loading_output_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_hevc_encoder_available", lambda: True)
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    commands = []

    def runner(args, output_path, workspace, _cancel):
        commands.append(args)
        Path(output_path).write_bytes(b"prepared-media")

    result = native.convert_native_media_to_file(
        str(source), "clip.mov", "video-optimize",
        {"target_format": "m4v", "quality": "balanced"}, str(tmp_path), runner=runner,
    )
    output_path, extension, media_type, attributes, size = result
    assert Path(output_path).read_bytes() == b"prepared-media"
    assert extension == "m4v"
    assert media_type == "video/x-m4v"
    assert attributes == {"quality": "balanced"}
    assert size == len(b"prepared-media")
    assert commands[0][2] == str(source)

    flac_source = tmp_path / "track.wav"
    flac_source.write_bytes(b"audio source")
    flac_path, extension, media_type, attributes, size = native.convert_native_media_to_file(
        str(flac_source), "track.wav", "audio-convert", {"target_format": "flac", "bitrate_kbps": 192},
        str(tmp_path), runner=runner,
    )
    assert Path(flac_path).read_bytes() == b"prepared-media"
    assert extension == "flac" and media_type == "audio/flac"
    assert attributes == {"codec": "flac", "lossless": True} and size == len(b"prepared-media")
    assert commands[-1][1:5] == ["-f", "flac", "-d", "flac"]
    assert flac_source.read_bytes() == b"audio source"

    mp3_source = tmp_path / "source-mp3.wav"
    mp3_source.write_bytes(b"audio source for mp3")
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "native_audio_format_available", lambda target: target == "mp3")
    mp3_path, extension, media_type, attributes, size = native.convert_native_media_to_file(
        str(mp3_source), "track.wav", "audio-convert", {"target_format": "mp3", "bitrate_kbps": 128},
        str(tmp_path), runner=runner,
    )
    assert Path(mp3_path).read_bytes() == b"prepared-media"
    assert extension == "mp3" and media_type == "audio/mpeg"
    assert attributes == {"codec": "mp3", "bitrate_kbps": 128, "lossy": True} and size == len(b"prepared-media")
    assert commands[-1][0] == "/opt/homebrew/bin/ffmpeg"
    assert commands[-1][-5:] == ["-b:a", "128k", "-f", "mp3", commands[-1][-1]]
    assert mp3_source.read_bytes() == b"audio source for mp3"

    hevc_path, extension, media_type, attributes, size = native.convert_native_media_to_file(
        str(source), "clip.mov", "video-hevc-convert", {}, str(tmp_path), runner=runner,
    )
    assert Path(hevc_path).read_bytes() == b"prepared-media"
    assert extension == "mov" and media_type == "video/quicktime"
    assert attributes == {"codec": "hevc"} and size == len(b"prepared-media")
    assert commands[-1][4] == "PresetHEVCHighestQuality"
    assert Path(commands[-1][-1]).suffix == ".mov"
    assert source.read_bytes() == b"source"


def test_native_file_adapter_fit_size_retries_rates_and_reports_miss(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    rates = []

    def runner(args, output_path, _workspace, _cancel):
        rate = int(args[6]) // 1000
        rates.append(rate)
        Path(output_path).write_bytes(b"x" * rate)

    result = native.convert_native_media_to_file(
        str(source), "audio.wav", "audio-fit-size",
        {"target_format": "m4a", "bitrate_kbps": 128, "target_bytes": 50},
        str(tmp_path), runner=runner,
    )
    output_path, extension, media_type, attributes, size = result
    assert rates == [128, 192, 96, 64, 48]
    assert extension == "m4a"
    assert media_type == "audio/mp4"
    assert attributes == {"target_bytes": 50, "target_met": True, "bitrate_kbps": 48}
    assert size == 48
    assert Path(output_path).stat().st_size == size
    assert len(list(tmp_path.glob("candidate-*.m4a"))) == 1


@pytest.mark.parametrize(("extension", "header"), [
    ("m4a", b"\x00\x00\x00\x18ftypM4A "),
    ("mp4", b"\x00\x00\x00\x18ftypisom"),
    ("m4v", b"\x00\x00\x00\x18ftypM4V "),
    ("mov", b"\x00\x00\x00\x18ftypqt  "),
    ("flac", b"fLaC"),
    ("mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00"),
    ("wav", b"RIFF\x00\x00\x00\x00WAVE"),
    ("aiff", b"FORM\x00\x00\x00\x00AIFF"),
    ("aiff", b"FORM\x00\x00\x00\x00AIFC"),
    ("gif", b"GIF89a"),
])
def test_native_output_container_signatures(extension, header):
    assert native._native_output_signature_valid(extension, header)
    with pytest.raises(ConversionInputError):
        native._verify_native_output_from_bytes(b"not a media container", extension)


def test_native_av1_output_uses_local_ffmpeg_and_publishes_mp4(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: False)
    monkeypatch.setattr(native, "native_av1_encoder_available", lambda: True)
    monkeypatch.setattr(native, "_ffmpeg_path", lambda: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"video": "unavailable", "audio": "/usr/bin/afconvert"})
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    commands = []

    def runner(args, output_path, _workspace, _cancel):
        commands.append(args)
        Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypisomav01prepared")

    result = native.convert_native_media_to_file(
        str(source), "source.mov", "video-optimize", {"target_format": "av1", "quality": "balanced"},
        str(tmp_path), runner=runner,
    )
    output, extension, media_type, attributes, size = result
    assert Path(output).read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
    assert extension == "mp4" and media_type == "video/mp4"
    assert attributes == {"quality": "balanced", "codec": "av1"} and size > 0
    assert commands[0][commands[0].index("-protocol_whitelist") + 1] == "file"
    assert "http" not in commands[0] and commands[0][-3] == "mp4"
    assert source.read_bytes() == b"source"


def test_native_file_adapter_rejects_invalid_container_from_default_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")

    def invalid_runner(_args, output_path, _workspace, _cancel):
        Path(output_path).write_bytes(b"not an M4V container")

    monkeypatch.setattr(native, "_run_bounded", invalid_runner)
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(
            str(source), "clip.mov", "video-optimize", {"target_format": "m4v"}, str(tmp_path),
        )


def test_native_file_adapter_rejects_untrusted_paths_unavailable_operations_and_oversized_output(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(
            str(source), "clip.mov", "video-optimize", {"target_format": "m4v"}, str(tmp_path / "other"),
        )
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media_to_file(
            str(source), "clip.mov", "video-mute", {}, str(tmp_path),
        )

    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"video": "relative-tool", "audio": "/usr/bin/afconvert"})
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media_to_file(str(source), "clip.mov", "video-optimize", {}, str(tmp_path))
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"video": "/usr/bin/avconvert", "audio": "/usr/bin/afconvert"})

    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    source.write_bytes(b"large")
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(str(source), "clip.mov", "video-optimize", {}, str(tmp_path))
    source.write_bytes(b"src")
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", 1)
    with pytest.raises(ImageOutputLimitError, match="workspace"):
        native.convert_native_media_to_file(str(source), "clip.mov", "video-optimize", {}, str(tmp_path))
    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_WORKSPACE_BYTES", native.MAX_NATIVE_MEDIA_BYTES * 3)

    monkeypatch.setattr(native, "MAX_NATIVE_MEDIA_BYTES", 4)
    source.write_bytes(b"src")
    def oversized_runner(_args, output_path, _workspace, _cancel):
        Path(output_path).write_bytes(b"12345")
    with pytest.raises(ImageOutputLimitError):
        native.convert_native_media_to_file(
            str(source), "clip.mov", "video-optimize", {"target_format": "m4v"},
            str(tmp_path), runner=oversized_runner,
        )


def test_video_file_fit_retries_and_removes_superseded_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    qualities = []

    def runner(args, output_path, _workspace, _cancel):
        quality = {"PresetAppleM4V1080pHD": "higher", "PresetAppleM4V720pHD": "balanced", "PresetAppleM4V480pSD": "smaller"}[args[4]]
        qualities.append(quality)
        Path(output_path).write_bytes(b"x" * {"higher": 8, "balanced": 5, "smaller": 2}[quality])

    result = native.convert_native_media_to_file(
        str(source), "clip.mov", "video-fit-size",
        {"target_format": "m4v", "quality": "higher", "target_bytes": 3},
        str(tmp_path), runner=runner,
    )
    output_path, _extension, _mime, attrs, size = result
    assert qualities == ["higher", "balanced", "smaller"]
    assert attrs == {"target_bytes": 3, "target_met": True, "quality": "smaller"}
    assert size == 2
    assert Path(output_path).stat().st_size == 2
    assert len(list(tmp_path.glob("candidate-*.m4v"))) == 1


@pytest.mark.parametrize(("operation", "options", "expected_attributes"), [
    ("video-mute", {}, {"audio_removed": True}),
    ("video-strip-metadata", {}, {"metadata_removed": True}),
    ("video-speed", {"factor_percent": 150}, {"factor_percent": 150}),
    ("video-to-gif", {"fps": 12, "max_width": 320, "max_duration_seconds": 8}, {
        "fps": 12, "max_width": 320, "max_duration_seconds": 8,
    }),
    ("video-crop", {"x": 2, "y": 3, "width": 640, "height": 360}, {
        "x": 2, "y": 3, "width": 640, "height": 360,
    }),
    ("video-resize", {"max_width": 1280, "max_height": 720}, {
        "max_width": 1280, "max_height": 720,
    }),
    ("video-resize", {"max_width": 1920, "max_height": 1080, "fps": 24}, {
        "max_width": 1920, "max_height": 1080, "max_fps": 24,
    }),
])
def test_video_transform_file_adapter_keeps_output_file_backed(monkeypatch, tmp_path, operation, options, expected_attributes):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    source = tmp_path / "source.mov"
    source.write_bytes(b"original")
    calls = []

    def runner(args, output_path, _workspace, _cancel):
        calls.append(args)
        Path(output_path).write_bytes(b"prepared")

    output, extension, mime, attributes, size = native.convert_native_media_to_file(
        str(source), "clip.mov", operation, options, str(tmp_path), runner=runner,
    )
    assert calls[0][0:2] == ["/private/helper", operation]
    if operation == "video-to-gif":
        assert extension == "gif" and mime == "image/gif"
    else:
        assert extension == "mov" and mime == "video/quicktime"
    assert attributes == expected_attributes and size == 8
    assert Path(output).read_bytes() == b"prepared"
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize("smart", [False, True])
def test_typed_video_aspect_crop_resolves_at_runtime_for_file_and_byte_adapters(monkeypatch, tmp_path, smart):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    monkeypatch.setattr(native, "probe_video_dimensions", lambda _path: (200, 100))
    probes = []

    def saliency(path, kind, **_kwargs):
        probes.append((path, kind))
        return {"sourceWidth": 200, "sourceHeight": 100, "detected": True,
                "x": 0.8, "y": 0.4, "width": 0.1, "height": 0.2}

    monkeypatch.setattr(native, "probe_smart_crop_bounds", saliency)
    calls = []

    def runner(args, output, _workspace, _cancel):
        calls.append(args)
        assert args[-4:] == ["100" if smart else "50", "0", "100", "100"]
        Path(output).write_bytes(b"prepared")

    source = tmp_path / "source.mov"
    source.write_bytes(b"original")
    options = {"aspect_ratio": "1:1", "smart_crop": smart}
    file_output = native.convert_native_media_to_file(str(source), "source.mov", "video-crop", options, str(tmp_path), runner=runner)
    byte_output = native.convert_native_media(b"original", "source.mov", "video-crop", options, runner=runner)
    assert file_output[3] == byte_output[3]
    assert file_output[3]["width"] == 100 and file_output[3]["height"] == 100
    assert len(calls) == 2 and len(probes) == (2 if smart else 0)
    assert source.read_bytes() == b"original"


def test_audio_normalize_file_adapter_returns_verified_meter_results(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "track.wav"
    source.write_bytes(b"audio fixture")

    def runner(args, output_path, _workspace, _cancel_event):
        assert args == ["/private/helper", "audio-normalize", str(source), output_path, "-14", f"{output_path}.metrics.json"]
        Path(output_path).write_bytes(b"normalized")
        Path(f"{output_path}.metrics.json").write_text(json.dumps({
            "input_lufs": -22.0, "output_lufs": -14.1, "applied_gain_db": 7.9,
            "sample_peak_dbfs": -2.2, "peak_limited": False,
        }))

    result = native.convert_native_media_to_file(
        str(source), "track.wav", "audio-normalize", {"target_lufs": -14}, str(workspace), runner=runner,
    )
    output, extension, mime, attributes, size = result
    assert Path(output).read_bytes() == b"normalized"
    assert extension == "m4a" and mime == "audio/mp4" and size == len(b"normalized")
    assert attributes["input_lufs"] == -22.0 and attributes["output_lufs"] == -14.1
    assert attributes["target_met"] is True
    assert not Path(f"{output}.metrics.json").exists()


def test_audio_artwork_file_adapter_keeps_output_file_backed(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    source = tmp_path / "source.m4a"
    source.write_bytes(b"original")
    calls = []

    def runner(args, output_path, _workspace, _cancel):
        calls.append(args)
        Path(output_path).write_bytes(b"prepared")

    output, extension, mime, attributes, size = native.convert_native_media_to_file(
        str(source), "track.m4a", "audio-artwork", {"max_edge": 512}, str(tmp_path), runner=runner,
    )
    assert calls == [["/private/helper", "audio-artwork", str(source), output, "512"]]
    assert extension == "m4a" and mime == "audio/mp4"
    assert attributes == {"max_edge": 512, "artwork_resized": True} and size == 8
    assert Path(output).read_bytes() == b"prepared"
    assert source.read_bytes() == b"original"


def test_audio_speed_file_adapter_writes_a_separate_bounded_m4a_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: "/private/helper")
    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    source_hash = source.read_bytes()
    calls = []

    def runner(args, output_path, _workspace, _cancel):
        calls.append(args)
        Path(output_path).write_bytes(b"sped-audio")

    output, extension, mime, attributes, size = native.convert_native_media_to_file(
        str(source), source.name, "audio-speed", {"factor_percent": 150}, str(tmp_path), runner=runner,
    )
    assert calls == [["/private/helper", "audio-speed", str(source), output, "150"]]
    assert extension == "m4a" and mime == "audio/mp4"
    assert attributes == {"factor_percent": 150} and size == len(b"sped-audio")
    assert Path(output).read_bytes() == b"sped-audio"
    assert source.read_bytes() == source_hash


def test_native_conversion_rejects_missing_runtime_and_unimplemented_operations(monkeypatch):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: False)
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: False)
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media(b"video", "clip.mov", "video-optimize", {"target_format": "m4v"})
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media(b"video", "clip.mov", "video-mute", {})
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media(b"audio", "clip.wav", "audio-normalize", {})
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"audio": "relative-tool"})
    with pytest.raises(native.NativeMediaUnavailableError):
        native.convert_native_media(b"audio", "clip.wav", "audio-optimize", {"target_format": "m4a"})


def test_native_adapter_media_operation_maps_to_an_output(monkeypatch):
    from officekit.engines.engine_media_models import MediaOperation
    from officekit.engines.engine_media_optimizer import MediaOptimizerEngine

    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr("officekit.engines.engine_media_optimizer.convert_native_media", lambda *_args, **_kwargs: (b"out", "m4a", "audio/mp4", {"bitrate_kbps": 128}))
    output = MediaOptimizerEngine.execute(b"source", "audio.wav", [MediaOperation.model_validate({"operationId": "audio-convert", "options": {"targetFormat": "m4a"}})])
    assert output.data == b"out"
    assert output.extension == "m4a"
    assert output.attributes == {"bitrate_kbps": 128}

    monkeypatch.setattr("officekit.engines.engine_media_optimizer.convert_native_media", lambda *_args, **_kwargs: (_ for _ in ()).throw(native.NativeMediaCancelledError()))
    with pytest.raises(native.NativeMediaCancelledError):
        MediaOptimizerEngine.execute(b"source", "audio.wav", [MediaOperation.model_validate({"operationId": "audio-convert", "options": {"targetFormat": "m4a"}})])


@pytest.mark.parametrize(("compression", "expected_bitrate"), [(5, 320), (55, 192), (100, 64), ("adaptive", 160)])
def test_audio_compression_factor_maps_to_bounded_bitrate(monkeypatch, tmp_path, compression, expected_bitrate):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"audio": "/usr/bin/afconvert"})
    calls = []

    def runner(args, output, *_args):
        calls.append(args)
        Path(output).write_bytes(b"audio")

    output, extension, _mime, attributes = native.convert_native_media(
        b"audio", "track.wav", "audio-optimize", {"target_format": "m4a", "compression": compression}, runner=runner,
    )
    assert extension == "m4a"
    assert attributes["bitrate_kbps"] == expected_bitrate
    assert attributes["compression"] == compression
    assert str(expected_bitrate * 1000) in calls[0]


def test_lower_bitrate_never_selects_rate_above_conservative_source_estimate(monkeypatch, tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"a" * 100_000)
    monkeypatch.setattr(native, "probe_audio_duration", lambda _path: 10.0)
    assert native._lower_bitrate_target(str(source), 128) == 64
    assert native._lower_bitrate_target(str(source), 48) == 48
    source.write_bytes(b"a" * 10_000)
    assert native._lower_bitrate_target(str(source), 128) is None


def test_lower_bitrate_pipeline_reencodes_below_source_or_passes_through(monkeypatch):
    monkeypatch.setattr(native, "native_media_available", lambda _kind: True)
    monkeypatch.setattr(native, "NATIVE_MEDIA_TOOLS", {"audio": "/usr/bin/afconvert"})
    monkeypatch.setattr(native, "probe_audio_duration", lambda _path: 10.0)
    commands = []

    def runner(args, output, *_args):
        commands.append(args)
        Path(output).write_bytes(b"prepared")

    audio = b"a" * 100_000
    result = native.convert_native_media(
        audio, "track.m4a", "audio-optimize", {"target_format": "m4a", "bitrate_kbps": 128, "no_upscale": True}, runner=runner,
    )
    assert result == (b"prepared", "m4a", "audio/mp4", {"bitrate_kbps": 64, "no_upscale": True})
    assert "64000" in commands[0]

    commands.clear()
    smaller_source = b"b" * 10_000
    result = native.convert_native_media(
        smaller_source, "track.m4a", "audio-optimize", {"target_format": "m4a", "bitrate_kbps": 128, "no_upscale": True}, runner=runner,
    )
    assert result == (smaller_source, "m4a", "audio/mp4", {"no_op": True, "no_upscale": True})
    assert commands == []
