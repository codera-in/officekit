"""Offline conformance checks against measurements of the decoded prepared file."""

import hashlib
from array import array
import json
import math
from pathlib import Path
import platform
import struct
import subprocess
import wave

import pytest

from officekit.engines import engine_media_native as native
from officekit.engines.engine_conversion_errors import ConversionInputError


def write_fixture(path, channels, transient=False, silence=False):
    rate = 48_000
    samples = bytearray()
    for frame in range(rate * 4):
        time = frame / rate
        amplitude = 0 if silence else (0.95 if transient and time % 0.25 < 0.002 else 0.02 if transient else 0.01)
        frequency = 10_000 if transient else 440
        value = round(amplitude * math.sin(2 * math.pi * frequency * time) * 32767)
        samples.extend(struct.pack("<h", value) * channels)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples)


@pytest.fixture
def ffmpeg():
    tool = native._ffmpeg_path()
    if platform.system() != "Darwin" or not tool or not native.native_audio_loudnorm_available():
        pytest.skip("Local macOS FFmpeg loudnorm is unavailable")
    return tool


def measure_decoded(tool, path):
    result = subprocess.run([
        tool, "-nostdin", "-hide_banner", "-nostats", "-protocol_whitelist", "file,pipe",
        "-i", str(path), "-map", "0:a:0", "-af", "loudnorm=I=-14:LRA=11:TP=-2:print_format=json",
        "-f", "null", "-",
    ], capture_output=True, check=True, timeout=30)
    text = result.stderr.decode("utf-8")
    start = text.rfind("{")
    return json.loads(text[start:text.index("}", start) + 1])


@pytest.mark.parametrize("channels,transient", [(1, False), (2, False), (2, True), (6, False)])
def test_normalization_reports_decoded_output_and_meets_true_peak_ceiling(ffmpeg, tmp_path, channels, transient):
    source = tmp_path / "fixture.wav"
    write_fixture(source, channels, transient=transient)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output, extension, mime, attributes, _size = native.convert_native_media_to_file(
        str(source), "fixture.wav", "audio-normalize", {"target_lufs": -14}, str(tmp_path),
    )
    decoded = measure_decoded(ffmpeg, output)
    loudness, peak = float(decoded["input_i"]), float(decoded["input_tp"])
    assert attributes["output_lufs"] == pytest.approx(loudness, abs=0.02)
    assert attributes["true_peak_dbfs"] == pytest.approx(peak, abs=0.02)
    assert peak <= -2.0
    assert attributes["target_met"] is (abs(loudness + 14) <= 0.5)
    assert extension == "m4a" and mime == "audio/mp4"
    ffprobe = Path(ffmpeg).with_name("ffprobe")
    if ffprobe.is_file():
        stream = json.loads(subprocess.run([
            str(ffprobe), "-v", "error", "-select_streams", "a:0", "-show_entries",
            "stream=channels,sample_rate,duration", "-of", "json", output,
        ], capture_output=True, check=True, timeout=10).stdout)["streams"][0]
        assert stream["channels"] == channels
        assert stream["sample_rate"] == "48000"
        assert float(stream["duration"]) == pytest.approx(4, abs=0.1)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_normalization_rejects_silent_audio_without_publishing_a_result(ffmpeg, tmp_path):
    source = tmp_path / "silent.wav"
    write_fixture(source, 1, silence=True)
    original = source.read_bytes()
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(str(source), "silent.wav", "audio-normalize", {"target_lufs": -14}, str(tmp_path))
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


def test_native_fallback_meets_sample_peak_ceiling_after_aac_encoding(ffmpeg, tmp_path):
    helper = native.native_media_transform_tool()
    if not helper:
        pytest.skip("The local AVFoundation helper is unavailable")
    source = tmp_path / "transient.wav"
    write_fixture(source, 2, transient=True)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output, metrics = tmp_path / "native.m4a", tmp_path / "native.metrics.json"
    subprocess.run([helper, "audio-normalize", str(source), str(output), "-14", str(metrics)],
                   capture_output=True, check=True, timeout=120)
    measured = json.loads(metrics.read_text())
    pcm = subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(output),
        "-map", "0:a:0", "-ar", "48000", "-c:a", "pcm_f32le", "-f", "f32le", "-",
    ], capture_output=True, check=True, timeout=30).stdout
    values = array("f")
    values.frombytes(pcm)
    decoded_peak = 20 * math.log10(max(abs(value) for value in values))
    assert measured["sample_peak_dbfs"] <= -2
    assert decoded_peak <= -2
    assert measured["sample_peak_dbfs"] == pytest.approx(decoded_peak, abs=0.02)
    assert measured["peak_limited"] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_audio_normalizer_rejects_a_playlist_disguised_as_one_selected_audio_file(ffmpeg, tmp_path):
    original = tmp_path / "unselected.wav"
    write_fixture(original, 1)
    segment = tmp_path / "unselected.aac"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(original), "-c:a", "aac", "-f", "adts", str(segment)],
                   capture_output=True, check=True, timeout=20)
    workspace = tmp_path / "job"
    workspace.mkdir()
    selected = workspace / "source.wav"
    selected.write_text(f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:4.0,\n{segment.as_uri()}\n#EXT-X-ENDLIST\n")
    with pytest.raises(ConversionInputError):
        native.convert_native_media_to_file(str(selected), "source.wav", "audio-normalize", {"target_lufs": -14}, str(workspace))
    assert list(workspace.iterdir()) == [selected]
