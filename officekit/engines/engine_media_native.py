"""Bounded wrappers around native media tools and optional host encoders."""

import json
import math
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import wave
from functools import lru_cache
from pathlib import Path

from .engine_conversion_errors import ConversionInputError
from .engine_file_converter import ImageOutputLimitError
from .engine_media_crop import crop_rectangle, smart_crop_rectangle


MAX_NATIVE_MEDIA_SECONDS = 120
MAX_NATIVE_MEDIA_BYTES = 64 * 1024 * 1024
MAX_AUDIO_NORMALIZE_ATTEMPTS = 3
AUDIO_TRUE_PEAK_CEILING_DBFS = -2.0
AUDIO_PEAK_CORRECTION_MARGIN_DB = 0.25
AUDIO_PEAK_MEASUREMENT_MARGIN_DB = 0.01
AUDIO_LOUDNESS_TOLERANCE_LU = 0.5
AUDIO_OUTPUT_SAMPLE_RATE = 48_000
# Reject playlist/script demuxers even when their source uses a local file URL.
AUDIO_INPUT_DEMUXERS = "aac,aiff,caf,flac,mov,mp3,wav"
FFMPEG_MIN_TRUE_PEAK_DBFS = -9.0
FFMPEG_MIN_LOUDNESS_LUFS = -70.0
FFMPEG_MAX_LOUDNESS_LUFS = -5.0
MAX_NATIVE_MEDIA_WORKSPACE_BYTES = 192 * 1024 * 1024
NATIVE_MEDIA_TOOLS = {"video": "/usr/bin/avconvert", "audio": "/usr/bin/afconvert"}
NATIVE_MEDIA_TRANSFORM_NAME = "officekit-media-transform"


class NativeMediaUnavailableError(RuntimeError):
    """A requested media operation has no supported system adapter."""


class NativeMediaCancelledError(RuntimeError):
    """A native media subprocess was cancelled before publishing output."""


def native_heif_decoder_available():
    return platform.system() == "Darwin" and os.path.isfile("/usr/bin/sips") and os.access("/usr/bin/sips", os.X_OK)


def native_media_available(kind):
    path = NATIVE_MEDIA_TOOLS.get(kind)
    return platform.system() == "Darwin" and path is not None and os.path.isfile(path) and os.access(path, os.X_OK)


def native_media_transform_tool():
    root = Path(__file__).resolve().parents[2]
    candidates = (
        Path(sys.executable).resolve().parent / NATIVE_MEDIA_TRANSFORM_NAME,
        root / ".build" / "backend-sidecar" / "dist" / "officekit-backend" / NATIVE_MEDIA_TRANSFORM_NAME,
        root / "src-tauri" / "resources" / "officekit-backend" / NATIVE_MEDIA_TRANSFORM_NAME,
    )
    return next((str(path) for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def probe_smart_crop_bounds(source_path, media, cancel_event=None):
    """Return a validated on-device Vision saliency rectangle for one image or video."""
    if media not in {"image", "video"}:
        raise ValueError("Smart crop supports images and videos only")
    if cancel_event is not None and cancel_event.is_set():
        raise NativeMediaCancelledError()
    helper = native_media_transform_tool()
    if not helper:
        raise NativeMediaUnavailableError()
    source_path = os.path.abspath(source_path)
    descriptor = None
    try:
        descriptor = os.open(source_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        source_info = os.fstat(descriptor)
        if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= MAX_NATIVE_MEDIA_BYTES:
            raise ConversionInputError()
        extension = Path(source_path).suffix
        if not extension or len(extension) > 12 or not extension[1:].isalnum():
            raise ConversionInputError()
        with tempfile.TemporaryDirectory(prefix="officekit-smart-crop-") as workspace:
            staged_path = os.path.join(workspace, f"source{extension.lower()}")
            staged_descriptor = os.open(staged_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            copied = 0
            with os.fdopen(staged_descriptor, "wb") as staged, os.fdopen(os.dup(descriptor), "rb") as source:
                while chunk := source.read(1024 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        raise NativeMediaCancelledError()
                    copied += len(chunk)
                    if copied > MAX_NATIVE_MEDIA_BYTES:
                        raise ConversionInputError()
                    staged.write(chunk)
            source_after = os.fstat(descriptor)
            if (copied != source_info.st_size
                    or (source_info.st_dev, source_info.st_ino, source_info.st_size, source_info.st_mtime_ns, source_info.st_ctime_ns)
                    != (source_after.st_dev, source_after.st_ino, source_after.st_size, source_after.st_mtime_ns, source_after.st_ctime_ns)):
                raise ConversionInputError("Input changed while saliency was being read.")
            payload = _run_smart_crop_probe([helper, "smart-crop-bounds", staged_path, media], workspace, cancel_event)
            if cancel_event is not None and cancel_event.is_set():
                raise NativeMediaCancelledError()
        bounds = json.loads(payload)
        expected = {"width", "height", "x", "y", "boxWidth", "boxHeight", "detected"}
        if not isinstance(bounds, dict) or set(bounds) != expected:
            raise ConversionInputError("Saliency bounds could not be read safely.")
        width, height, detected = bounds["width"], bounds["height"], bounds["detected"]
        if (type(width) is not int or type(height) is not int or type(detected) is not bool
                or not 0 < width <= 40_000 or not 0 < height <= 40_000 or width * height > 100_000_000):
            raise ConversionInputError("Saliency bounds could not be read safely.")
        x, y, box_width, box_height = (bounds[key] for key in ("x", "y", "boxWidth", "boxHeight"))
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in (x, y, box_width, box_height)):
            raise ConversionInputError("Saliency bounds could not be read safely.")
        if (not 0 <= x <= 1 or not 0 <= y <= 1 or not 0 <= box_width <= 1 or not 0 <= box_height <= 1
                or x + box_width > 1.000001 or y + box_height > 1.000001):
            raise ConversionInputError("Saliency bounds could not be read safely.")
        if detected and (box_width <= 0 or box_height <= 0):
            raise ConversionInputError("Saliency bounds could not be read safely.")
        return {
            "sourceWidth": width, "sourceHeight": height, "x": float(x), "y": float(y),
            "width": float(box_width), "height": float(box_height), "detected": detected,
        }
    except NativeMediaUnavailableError:
        raise
    except ConversionInputError:
        if cancel_event is not None and cancel_event.is_set():
            raise NativeMediaCancelledError() from None
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ConversionInputError("Saliency bounds could not be read safely.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _run_smart_crop_probe(args, workspace, cancel_event):
    output_path = os.path.join(workspace, "saliency.json")
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            def popen(command, **kwargs):
                return subprocess.Popen(command, **{**kwargs, "stdout": output})

            try:
                _run_bounded(args, output_path, workspace, cancel_event, popen=popen,
                             timeout_seconds=20, max_output_bytes=4096)
            except ImageOutputLimitError as error:
                raise ConversionInputError("Saliency bounds could not be read safely.") from error
        with open(output_path, "rb") as output:
            return output.read(4097)
    finally:
        os.unlink(output_path)


def _resolve_video_crop_options(source_path, options, cancel_event=None):
    if "aspect_ratio" not in options:
        return options
    if cancel_event is not None and cancel_event.is_set():
        raise NativeMediaCancelledError()
    if options.get("smart_crop"):
        saliency = probe_smart_crop_bounds(source_path, "video", cancel_event=cancel_event)
        geometry = smart_crop_rectangle(saliency["sourceWidth"], saliency["sourceHeight"], options["aspect_ratio"], saliency)
        return {**geometry, "smart_crop": True, "saliency_detected": saliency["detected"]}
    return crop_rectangle(*probe_video_dimensions(source_path), options["aspect_ratio"])


def _crop_result_attributes(options):
    result = {key: options[key] for key in ("x", "y", "width", "height")}
    if options.get("smart_crop"):
        result.update(smart_crop=True, saliency_detected=options["saliency_detected"])
    return result


def probe_video_dimensions(source_path):
    """Read bounded, orientation-correct video dimensions with the bundled AVFoundation helper."""
    helper = native_media_transform_tool()
    if not helper:
        raise NativeMediaUnavailableError()
    source_path = os.path.abspath(source_path)
    try:
        source_info = os.stat(source_path, follow_symlinks=False)
        if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= MAX_NATIVE_MEDIA_BYTES:
            raise ConversionInputError()
        with tempfile.TemporaryDirectory(prefix="officekit-video-info-") as workspace:
            result = subprocess.run(
                [helper, "video-info", source_path], capture_output=True, check=False, timeout=10,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ConversionInputError("Video dimensions could not be read safely.")
        dimensions = json.loads(result.stdout)
        if not isinstance(dimensions, dict) or set(dimensions) != {"width", "height"}:
            raise ConversionInputError("Video dimensions could not be read safely.")
        width, height = dimensions["width"], dimensions["height"]
        if type(width) is not int or type(height) is not int or not (0 < width <= 10_000 and 0 < height <= 10_000):
            raise ConversionInputError("Video dimensions could not be read safely.")
        if width * height > 100_000_000:
            raise ConversionInputError("Video dimensions exceed the supported pixel limit.")
        return width, height
    except NativeMediaUnavailableError:
        raise
    except ConversionInputError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ConversionInputError("Video dimensions could not be read safely.") from error


def probe_audio_duration(source_path):
    """Read bounded audio duration with the bundled AVFoundation helper."""
    helper = native_media_transform_tool()
    if not helper:
        raise NativeMediaUnavailableError()
    source_path = os.path.abspath(source_path)
    try:
        source_info = os.stat(source_path, follow_symlinks=False)
        if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= MAX_NATIVE_MEDIA_BYTES:
            raise ConversionInputError()
        with tempfile.TemporaryDirectory(prefix="officekit-audio-info-") as workspace:
            result = subprocess.run(
                [helper, "audio-info", source_path], capture_output=True, check=False, timeout=10,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ConversionInputError("Audio duration could not be read safely.")
        details = json.loads(result.stdout)
        if not isinstance(details, dict) or set(details) != {"duration"}:
            raise ConversionInputError("Audio duration could not be read safely.")
        duration = details["duration"]
        if type(duration) not in {int, float} or not math.isfinite(duration) or not 0 < duration <= MAX_NATIVE_MEDIA_SECONDS:
            raise ConversionInputError("Audio duration is outside the supported range.")
        return float(duration)
    except NativeMediaUnavailableError:
        raise
    except ConversionInputError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ConversionInputError("Audio duration could not be read safely.") from error


def decode_heif_to_png_bytes(input_bytes):
    """Decode a bounded HEIC/HEIF image with macOS ImageIO via the system sips tool."""
    if not native_heif_decoder_available():
        raise NativeMediaUnavailableError("HEIC/HEIF decoding is not available in this build.")
    if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > MAX_NATIVE_MEDIA_BYTES:
        raise ConversionInputError()
    tool = "/usr/bin/sips"
    if not os.path.isfile(tool) or not os.access(tool, os.X_OK):
        raise NativeMediaUnavailableError("HEIC/HEIF decoding is not available in this build.")
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-heif-") as workspace:
            source = os.path.join(workspace, "source.heic")
            output = os.path.join(workspace, "decoded.png")
            with open(source, "xb") as stream:
                stream.write(input_bytes)
            env = {"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
            dimensions = subprocess.run(
                [tool, "-g", "pixelWidth", "-g", "pixelHeight", source],
                capture_output=True, check=False, timeout=8, env=env,
            )
            if dimensions.returncode != 0 or len(dimensions.stdout) > 4096:
                raise ConversionInputError()
            values = {}
            for line in dimensions.stdout.decode("utf-8", "replace").splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() in {"pixelWidth", "pixelHeight"}:
                    try:
                        values[key.strip()] = int(value.strip())
                    except ValueError:
                        raise ConversionInputError() from None
            width, height = values.get("pixelWidth", 0), values.get("pixelHeight", 0)
            if not (0 < width <= 10_000 and 0 < height <= 10_000 and width * height <= 40_000_000):
                raise ConversionInputError()
            converted = subprocess.run(
                [tool, "-s", "format", "png", source, "--out", output],
                capture_output=True, check=False, timeout=30, env=env,
            )
            metadata = os.stat(output, follow_symlinks=False)
            if (converted.returncode != 0 or not stat.S_ISREG(metadata.st_mode)
                    or not 8 <= metadata.st_size <= MAX_NATIVE_MEDIA_BYTES):
                raise ConversionInputError()
            with open(output, "rb") as stream:
                data = stream.read(MAX_NATIVE_MEDIA_BYTES + 1)
            if len(data) != metadata.st_size or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ConversionInputError()
            return data
    except (subprocess.TimeoutExpired, OSError):
        raise ConversionInputError() from None


MEDIA_PREVIEW_TIMEOUT_SECONDS = 25
MEDIA_PREVIEW_MAX_OUTPUT_BYTES = 12 * 1024 * 1024
MEDIA_PREVIEW_MAX_SECONDS = 86_400
MEDIA_PREVIEW_WAVEFORM_BUCKETS = 64


def render_media_preview(source, extension, kind, max_edge, position_percent=10):
    """Draw a video frame, or read an audio file's cover art and waveform, with the bundled AVFoundation helper.

    ``source`` is an open binary file; it is copied (bounded) into a private workspace and never modified.
    Returns ``{"duration", "width", "height", "peaks", "image"}`` where ``image`` is JPEG bytes or None.
    """
    if kind not in {"video", "audio"}:
        raise ValueError("Preview supports video and audio only")
    helper = native_media_transform_tool()
    if platform.system() != "Darwin" or not helper:
        raise NativeMediaUnavailableError()
    if not extension or len(extension) > 12 or not extension[1:].isalnum():
        raise ConversionInputError()
    if type(max_edge) is not int or not 32 <= max_edge <= 2048 or type(position_percent) is not int or not 0 <= position_percent <= 100:
        raise ConversionInputError()
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-av-preview-") as workspace:
            staged_path = os.path.join(workspace, f"source{extension.lower()}")
            image_path = os.path.join(workspace, "preview.jpg")
            copied = 0
            descriptor = os.open(staged_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as staged:
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > MAX_NATIVE_MEDIA_BYTES:
                        raise ConversionInputError()
                    staged.write(chunk)
            if copied == 0:
                raise ConversionInputError()
            last_argument = str(position_percent) if kind == "video" else str(MEDIA_PREVIEW_WAVEFORM_BUCKETS)
            result = subprocess.run(
                [helper, f"preview-{kind}", staged_path, image_path, str(max_edge), last_argument],
                capture_output=True, check=False, timeout=MEDIA_PREVIEW_TIMEOUT_SECONDS,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
            if result.returncode != 0 or len(result.stdout) > 8192:
                raise ConversionInputError("This file could not be previewed.")
            details = json.loads(result.stdout)
            expected = {"width", "height", "duration", "peaks", "hasArtwork"}
            if not isinstance(details, dict) or set(details) != expected:
                raise ConversionInputError("This file could not be previewed.")
            width, height, duration, peaks = details["width"], details["height"], details["duration"], details["peaks"]
            if (type(width) is not int or type(height) is not int or not 0 <= width <= 40_000 or not 0 <= height <= 40_000
                    or type(duration) not in {int, float} or not math.isfinite(duration) or not 0 < duration <= MEDIA_PREVIEW_MAX_SECONDS
                    or not isinstance(peaks, list) or len(peaks) > 256
                    or any(type(value) is not int or not 0 <= value <= 100 for value in peaks)):
                raise ConversionInputError("This file could not be previewed.")
            image = None
            if details["hasArtwork"] is True:
                metadata = os.stat(image_path, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MEDIA_PREVIEW_MAX_OUTPUT_BYTES:
                    raise ConversionInputError("This file could not be previewed.")
                with open(image_path, "rb") as stream:
                    image = stream.read(MEDIA_PREVIEW_MAX_OUTPUT_BYTES + 1)
                if len(image) != metadata.st_size or not image.startswith(b"\xff\xd8"):
                    raise ConversionInputError("This file could not be previewed.")
            elif kind == "video":
                raise ConversionInputError("This file could not be previewed.")
            return {"duration": float(duration), "width": width, "height": height, "peaks": peaks, "image": image}
    except (subprocess.TimeoutExpired, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ConversionInputError("This file could not be previewed.") from error


def native_media_transform_available():
    return platform.system() == "Darwin" and native_media_transform_tool() is not None


def native_media_operation_available(operation_id):
    if operation_id == "video-hevc-convert":
        return native_hevc_encoder_available()
    if operation_id in {"video-optimize", "video-fit-size"}:
        return native_media_available("video") or native_av1_encoder_available()
    if operation_id in {"video-speed", "video-mute", "video-strip-metadata", "video-to-gif", "video-crop", "video-resize", "video-watermark-overlay"}:
        return native_media_available("video") and native_media_transform_available()
    if operation_id in {"audio-optimize", "audio-convert", "audio-fit-size"}:
        return native_media_available("audio")
    if operation_id == "audio-speed":
        return native_media_available("audio") and native_media_transform_available()
    if operation_id == "audio-artwork":
        return native_media_available("audio") and native_media_transform_available()
    if operation_id == "audio-normalize":
        return native_media_available("audio") and (native_media_transform_available() or native_audio_loudnorm_available())
    return False


def _ffmpeg_path():
    path = shutil.which("ffmpeg", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    if not path:
        return None
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
        return None
    if not any(os.path.commonpath((resolved, root)) == root for root in ("/opt/homebrew", "/usr/local", "/usr")):
        return None
    return resolved


@lru_cache(maxsize=1)
def native_av1_encoder_available():
    """Probe one bounded AV1-in-MP4 encode using a locally installed FFmpeg."""
    tool = _ffmpeg_path()
    if not tool:
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-av1-probe-") as workspace:
            output = os.path.join(workspace, "probe.mp4")
            result = subprocess.run(
                [tool, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=64x64:r=1:d=0.2", "-frames:v", "1", "-an", "-threads", "1",
                 "-c:v", "libsvtav1", "-preset", "13", "-crf", "63", "-svtav1-params", "lp=1",
                 "-y", output],
                capture_output=True,
                check=False,
                timeout=8,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
            )
            return result.returncode == 0 and os.path.isfile(output) and 0 < os.path.getsize(output) <= 1_048_576 and _native_output_signature_valid("mp4", Path(output).read_bytes()[:16])
    except (OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=4)
def native_video_format_available(target_format):
    """Probe optional FFmpeg video encoders without accessing user media."""
    encoder_options = {
        "mp4": ("libx264", "aac", "mp4"),
        "webm": ("libvpx-vp9", "libopus", "webm"),
        "x265": ("libx265", "aac", "mp4"),
    }
    encoders = encoder_options.get(target_format)
    tool = _ffmpeg_path()
    if not tool or not encoders:
        return False
    video_encoder, audio_encoder, container = encoders
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-video-probe-") as workspace:
            output = os.path.join(workspace, f"probe.{container}")
            video_args = {
                "mp4": ["-preset", "ultrafast", "-crf", "51"],
                "webm": ["-deadline", "realtime", "-cpu-used", "8", "-crf", "63", "-b:v", "0"],
                "x265": ["-preset", "ultrafast", "-crf", "51", "-x265-params", "pools=1:frame-threads=1:log-level=error", "-tag:v", "hvc1"],
            }[target_format]
            result = subprocess.run(
                [tool, "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=0.2",
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=0.2",
                 "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-frames:v", "1", "-threads", "1",
                 "-c:v", video_encoder, *video_args, "-pix_fmt", "yuv420p",
                 "-c:a", audio_encoder, "-b:a", "32k", "-f", container, output],
                capture_output=True,
                check=False,
                timeout=10,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"},
            )
            if result.returncode != 0 or not os.path.isfile(output):
                return False
            size = os.path.getsize(output)
            if not 0 < size <= 1_048_576:
                return False
            with open(output, "rb") as stream:
                header = stream.read(16)
            return _native_output_signature_valid(container, header)
    except (OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=4)
def native_audio_format_available(target_format):
    """Verify optional audio output encoders with a tiny private WAV fixture."""
    if target_format in {"m4a", "wav", "aiff"}:
        return native_media_available("audio")
    if target_format == "mp3":
        return _probe_ffmpeg_mp3_encoder()
    if target_format != "flac" or not native_media_available("audio"):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-audio-probe-") as workspace:
            source = os.path.join(workspace, "probe.wav")
            output = os.path.join(workspace, "probe.flac")
            with wave.open(source, "wb") as sample:
                sample.setnchannels(1)
                sample.setsampwidth(2)
                sample.setframerate(8000)
                sample.writeframes(b"\0\0" * 800)
            result = subprocess.run(
                _audio_candidate(source, output, target_format, 128),
                capture_output=True,
                check=False,
                timeout=5,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin"},
            )
            return result.returncode == 0 and os.path.isfile(output) and 0 < os.path.getsize(output) <= 1_048_576
    except (OSError, subprocess.TimeoutExpired, wave.Error):
        return False


@lru_cache(maxsize=1)
def native_audio_loudnorm_available():
    """Probe optional FFmpeg EBU R128 and true-peak M4A output support."""
    tool = _ffmpeg_path()
    if not tool:
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-loudnorm-probe-") as workspace:
            source = os.path.join(workspace, "probe.wav")
            output = os.path.join(workspace, "probe.m4a")
            with wave.open(source, "wb") as sample:
                sample.setnchannels(2)
                sample.setsampwidth(2)
                sample.setframerate(8000)
                sample.writeframes(b"".join(
                    struct.pack("<hh", value, value)
                    for index in range(8000)
                    for value in (int(8000 * math.sin(2 * math.pi * 440 * index / 8000)),)
                ))
            filter_spec = "loudnorm=I=-14:LRA=11:TP=-2:print_format=json"
            result = subprocess.run(
                [tool, "-nostdin", "-hide_banner", "-loglevel", "info", "-nostats", "-protocol_whitelist", "file,pipe",
                 "-i", source, "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-af", filter_spec, "-c:a", "aac", "-b:a", "96k", "-f", "ipod", output],
                capture_output=True, check=False, timeout=8,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
            )
            metrics = _parse_ffmpeg_loudnorm(result.stderr)
            return result.returncode == 0 and metrics is not None and os.path.isfile(output) and 0 < os.path.getsize(output) <= 1_048_576 and _native_output_signature_valid("m4a", Path(output).read_bytes()[:16])
    except (OSError, subprocess.TimeoutExpired, wave.Error):
        return False


@lru_cache(maxsize=1)
def _probe_ffmpeg_mp3_encoder():
    """Check an installed FFmpeg's MP3 encoder using a tiny private WAV."""
    tool = _ffmpeg_path()
    if not tool:
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="officekit-mp3-probe-") as workspace:
            source = os.path.join(workspace, "probe.wav")
            output = os.path.join(workspace, "probe.mp3")
            with wave.open(source, "wb") as sample:
                sample.setnchannels(1)
                sample.setsampwidth(2)
                sample.setframerate(8000)
                sample.writeframes(b"\0\0" * 800)
            result = subprocess.run(
                [tool, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
                 "-i", source, "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-c:a", "libmp3lame", "-b:a", "96k", "-f", "mp3", output],
                capture_output=True, check=False, timeout=8,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
            )
            return result.returncode == 0 and os.path.isfile(output) and 0 < os.path.getsize(output) <= 1_048_576 and _native_output_signature_valid("mp3", Path(output).read_bytes()[:16])
    except (OSError, subprocess.TimeoutExpired, wave.Error):
        return False


@lru_cache(maxsize=1)
def native_hevc_encoder_available():
    """Check that the OS converter advertises its HEVC export preset."""
    if not native_media_available("video"):
        return False
    try:
        result = subprocess.run(
            [NATIVE_MEDIA_TOOLS["video"], "--help"],
            capture_output=True,
            check=False,
            timeout=5,
            env={"HOME": tempfile.gettempdir(), "TMPDIR": tempfile.gettempdir(), "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    help_text = (result.stdout + result.stderr)[:262_144]
    return b"PresetHEVCHighestQuality" in help_text


def _workspace_size(workspace):
    total = 0
    for current, directories, files in os.walk(workspace, followlinks=False):
        directories[:] = [name for name in directories if not os.path.islink(os.path.join(current, name))]
        for name in files:
            path = os.path.join(current, name)
            try:
                info = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def _run_bounded(args, output_path, workspace, cancel_event=None, popen=subprocess.Popen, clock=time.monotonic, sleeper=time.sleep,
                 *, timeout_seconds=None, max_output_bytes=None):
    timeout_seconds = MAX_NATIVE_MEDIA_SECONDS if timeout_seconds is None else timeout_seconds
    max_output_bytes = MAX_NATIVE_MEDIA_BYTES if max_output_bytes is None else max_output_bytes
    process = popen(
        args,
        cwd=workspace,
        env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    deadline = clock() + timeout_seconds
    while process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise NativeMediaCancelledError()
        if clock() >= deadline:
            process.kill()
            process.wait()
            raise ConversionInputError()
        try:
            output_size = os.path.getsize(output_path)
        except OSError:
            output_size = 0
        if output_size > max_output_bytes:
            process.kill()
            process.wait()
            raise ImageOutputLimitError()
        if _workspace_size(workspace) > MAX_NATIVE_MEDIA_WORKSPACE_BYTES:
            process.kill()
            process.wait()
            raise ImageOutputLimitError("Native media workspace limit reached")
        sleeper(0.05)
    if process.returncode != 0:
        raise ConversionInputError()
    try:
        output_size = os.path.getsize(output_path)
    except OSError as error:
        raise ConversionInputError() from error
    if output_size < 1:
        raise ConversionInputError()
    if output_size > max_output_bytes:
        raise ImageOutputLimitError()
    if _workspace_size(workspace) > MAX_NATIVE_MEDIA_WORKSPACE_BYTES:
        raise ImageOutputLimitError("Native media workspace limit reached")


def _safe_extension(filename):
    extension = os.path.splitext(filename)[1].lower().lstrip(".")
    return extension if extension.isascii() and extension.isalnum() and len(extension) <= 8 else "media"


def _video_candidate(source_path, output_path, target_format, quality, compression=None):
    if compression == "adaptive":
        compression = 55
    if target_format in {"av1", "mp4", "webm", "x265"}:
        tool = _ffmpeg_path()
        source_format = os.path.splitext(source_path)[1].lower()
        encoder_available = native_av1_encoder_available() if target_format == "av1" else native_video_format_available(target_format)
        if not tool or not encoder_available or source_format not in {".mov", ".mp4", ".m4v", ".mkv", ".webm"}:
            raise NativeMediaUnavailableError()
        demuxer = "matroska" if source_format in {".mkv", ".webm"} else "mov"
        crf_by_format = {
            "av1": {"smaller": "45", "balanced": "36", "higher": "28"},
            "mp4": {"smaller": "32", "balanced": "24", "higher": "18"},
            "webm": {"smaller": "45", "balanced": "34", "higher": "24"},
            "x265": {"smaller": "35", "balanced": "28", "higher": "21"},
        }
        if target_format == "mp4" and compression is not None:
            # Factor 5 means highest quality and 100 means smallest file.
            crf_by_format["mp4"][quality] = str(round(18 + (compression - 5) * 22 / 95))
        video_encoder = {"av1": "libsvtav1", "mp4": "libx264", "webm": "libvpx-vp9", "x265": "libx265"}[target_format]
        audio_encoder = "libopus" if target_format == "webm" else "aac"
        container = "webm" if target_format == "webm" else "mp4"
        args = [tool, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file",
                "-f", demuxer, "-i", source_path, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
                "-map_chapters", "-1", "-threads", "1", "-c:v", video_encoder]
        if target_format == "av1":
            args.extend(["-preset", "12", "-crf", crf_by_format[target_format][quality], "-svtav1-params", "lp=1"])
        elif target_format == "mp4":
            args.extend(["-preset", "medium", "-crf", crf_by_format[target_format][quality]])
        elif target_format == "webm":
            args.extend(["-deadline", "good", "-cpu-used", "6", "-crf", crf_by_format[target_format][quality], "-b:v", "0", "-row-mt", "1"])
        else:
            args.extend(["-preset", "fast", "-crf", crf_by_format[target_format][quality], "-x265-params", "pools=1:frame-threads=1:log-level=error", "-tag:v", "hvc1"])
        args.extend(["-pix_fmt", "yuv420p", "-c:a", audio_encoder, "-b:a", "128k"])
        if container == "mp4":
            args.extend(["-movflags", "+faststart"])
        args.extend(["-f", container, "-y", output_path])
        return args
    if target_format == "hevc":
        preset = "PresetHEVCHighestQuality"
    elif target_format == "m4v":
        preset = {"smaller": "PresetAppleM4V480pSD", "balanced": "PresetAppleM4V720pHD", "higher": "PresetAppleM4V1080pHD"}[quality]
    elif target_format == "mov":
        preset = {"smaller": "PresetLowQuality", "balanced": "PresetMediumQuality", "higher": "PresetHighestQuality"}[quality]
    else:
        raise NativeMediaUnavailableError()
    return [NATIVE_MEDIA_TOOLS["video"], "--source", source_path, "--preset", preset, "--output", output_path]


def _video_file_format(target_format):
    return {"av1": "mp4", "x265": "mp4"}.get(target_format, target_format)


def _video_mime_type(target_format):
    if target_format == "webm":
        return "video/webm"
    if target_format in {"av1", "mp4", "x265"}:
        return "video/mp4"
    return "video/x-m4v" if target_format == "m4v" else "video/quicktime"


def _video_codec_attributes(target_format):
    codecs = {"av1": "av1", "mp4": "h264", "webm": "vp9", "x265": "hevc"}
    codec = codecs.get(target_format)
    return {"codec": codec} if codec else {}


def _video_transform_candidate(source_path, output_path, operation_id, options, watermark_image_path=None):
    helper = native_media_transform_tool()
    if not helper:
        raise NativeMediaUnavailableError()
    if operation_id == "video-mute":
        value = 0
    elif operation_id == "video-strip-metadata":
        return [helper, operation_id, source_path, output_path]
    elif operation_id == "video-speed":
        return [helper, operation_id, source_path, output_path, str(options["factor_percent"])]
    elif operation_id == "video-to-gif":
        return [helper, operation_id, source_path, output_path,
                str(options["fps"]), str(options["max_width"]), str(options["max_duration_seconds"])]
    elif operation_id == "video-crop":
        return [helper, operation_id, source_path, output_path, str(options["x"]), str(options["y"]),
                str(options["width"]), str(options["height"])]
    elif operation_id == "video-resize":
        args = [helper, operation_id, source_path, output_path, str(options["max_width"]), str(options["max_height"])]
        if options.get("fps") is not None:
            args.append(str(options["fps"]))
        return args
    elif operation_id == "video-watermark-overlay":
        if not isinstance(watermark_image_path, str) or not os.path.isabs(watermark_image_path):
            raise NativeMediaUnavailableError()
        return [helper, operation_id, source_path, output_path, watermark_image_path,
                str(options.get("placement", "bottom-right")),
                str(options.get("margin_percent", 4)),
                str(options.get("size_percent", 18)),
                str(options.get("opacity_percent", 72))]
    else:
        raise NativeMediaUnavailableError()
    return [helper, operation_id, source_path, output_path, str(value)]


def _audio_candidate(source_path, output_path, target_format, bitrate_kbps):
    if target_format == "m4a":
        return [NATIVE_MEDIA_TOOLS["audio"], "-f", "m4af", "-d", "aac@44100", "-b", str(bitrate_kbps * 1000), source_path, output_path]
    if target_format == "wav":
        return [NATIVE_MEDIA_TOOLS["audio"], "-f", "WAVE", "-d", "LEI16", source_path, output_path]
    if target_format == "aiff":
        return [NATIVE_MEDIA_TOOLS["audio"], "-f", "AIFF", "-d", "BEI16", source_path, output_path]
    if target_format == "flac":
        return [NATIVE_MEDIA_TOOLS["audio"], "-f", "flac", "-d", "flac", source_path, output_path]
    if target_format == "mp3":
        tool = _ffmpeg_path()
        if not tool or not native_audio_format_available("mp3"):
            raise NativeMediaUnavailableError()
        return [tool, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", AUDIO_INPUT_DEMUXERS, "-i", source_path, "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-map_chapters", "-1",
                "-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k", "-f", "mp3", output_path]
    raise NativeMediaUnavailableError()


def _lower_bitrate_target(source_path, requested_kbps):
    """Choose a supported rate below a conservative measured source-rate estimate."""
    duration = probe_audio_duration(source_path)
    source_info = os.stat(source_path, follow_symlinks=False)
    if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= MAX_NATIVE_MEDIA_BYTES:
        raise ConversionInputError()
    # Reserve space for container headers and VBR overhead so the estimate does not
    # turn a lower-bitrate request into an accidental up-conversion.
    estimated_kbps = max(0, (source_info.st_size - min(source_info.st_size, 4096)) * 8 / duration / 1000 * 0.9)
    rates = (320, 256, 224, 192, 160, 128, 96, 80, 64, 48, 32)
    return next((rate for rate in rates if rate <= requested_kbps and rate <= estimated_kbps), None)


def _audio_source_format(filename):
    extension = os.path.splitext(filename)[1].lower().lstrip(".")
    normalized = "aiff" if extension == "aif" else extension
    if normalized not in {"m4a", "wav", "aiff", "flac", "mp3"}:
        raise NativeMediaUnavailableError("No safe no-upscale output format is available for this audio file.")
    return normalized


def _audio_attributes(target_format, bitrate_kbps):
    if target_format == "m4a":
        return {"bitrate_kbps": bitrate_kbps}
    if target_format == "flac":
        return {"codec": "flac", "lossless": True}
    if target_format == "mp3":
        return {"codec": "mp3", "bitrate_kbps": bitrate_kbps, "lossy": True}
    return {"codec": "pcm_s16le" if target_format == "wav" else "pcm_s16be"}


def _audio_transform_candidate(source_path, output_path, operation_id, options):
    helper = native_media_transform_tool()
    if not helper or operation_id not in {"audio-artwork", "audio-normalize", "audio-speed"}:
        raise NativeMediaUnavailableError()
    if operation_id == "audio-speed":
        return [helper, operation_id, source_path, output_path, str(options["factor_percent"])]
    if operation_id == "audio-normalize":
        return [helper, operation_id, source_path, output_path, str(options["target_lufs"]), f"{output_path}.metrics.json"]
    return [helper, operation_id, source_path, output_path, str(options["max_edge"])]


def _parse_ffmpeg_loudnorm(stderr):
    if not isinstance(stderr, bytes) or len(stderr) > 65_536:
        return None
    text = stderr.decode("utf-8", errors="replace")
    start = text.rfind("{")
    end = text.find("}", start)
    if start < 0 or end < 0:
        return None
    try:
        metrics = json.loads(text[start:end + 1])
        required = {"input_i", "output_i", "output_tp", "normalization_type"}
        if not isinstance(metrics, dict) or not required <= set(metrics):
            return None
        for key in (required - {"normalization_type"}) | ({"input_tp"} & set(metrics)):
            if isinstance(metrics[key], bool):
                return None
            value = float(metrics[key])
            if not math.isfinite(value):
                return None
            metrics[key] = value
        if metrics["normalization_type"] not in {"linear", "dynamic"}:
            return None
        return metrics
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _run_audio_loudness_pass(args, output_path, workspace, cancel_event, deadline, popen, clock, sleeper):
    if cancel_event is not None and cancel_event.is_set():
        raise NativeMediaCancelledError()
    if clock() >= deadline:
        raise ConversionInputError("Native media conversion exceeded its time limit.")
    descriptor, log_path = tempfile.mkstemp(prefix="loudness-", suffix=".log", dir=workspace)
    try:
        with os.fdopen(descriptor, "wb") as log:
            process = popen(
                args, cwd=workspace,
                env={"HOME": workspace, "TMPDIR": workspace, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, close_fds=True,
            )
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise NativeMediaCancelledError()
                if (os.fstat(log.fileno()).st_size > 65_536 or _workspace_size(workspace) > MAX_NATIVE_MEDIA_WORKSPACE_BYTES
                        or (output_path is not None and os.path.getsize(output_path) > MAX_NATIVE_MEDIA_BYTES)):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise ImageOutputLimitError("Native media workspace limit reached")
                if clock() >= deadline:
                    process.kill()
                    process.wait()
                    raise ConversionInputError("Native media conversion exceeded its time limit.")
                sleeper(0.05)
            if process.wait() != 0:
                raise ConversionInputError("The audio could not be normalized.")
        with open(log_path, "rb") as log:
            stderr = log.read(65_537)
        if _workspace_size(workspace) > MAX_NATIVE_MEDIA_WORKSPACE_BYTES:
            raise ImageOutputLimitError("Native media workspace limit reached")
        if output_path is not None:
            output_size = os.path.getsize(output_path)
            if output_size < 1:
                raise ConversionInputError("The audio could not be normalized.")
            if output_size > MAX_NATIVE_MEDIA_BYTES:
                raise ImageOutputLimitError()
        metrics = _parse_ffmpeg_loudnorm(stderr)
        if metrics is None:
            raise ConversionInputError("The loudness output could not be verified.")
        return metrics
    finally:
        Path(log_path).unlink(missing_ok=True)


def _run_ffmpeg_loudnorm(source_path, output_path, workspace, target_lufs, cancel_event=None,
                         popen=subprocess.Popen, clock=time.monotonic, sleeper=time.sleep):
    tool = _ffmpeg_path()
    if not tool or not native_audio_loudnorm_available():
        raise NativeMediaUnavailableError()
    metrics_path = f"{output_path}.metrics.json"
    completed = False
    metrics_created = False
    output_created = False
    deadline = clock() + MAX_NATIVE_MEDIA_SECONDS
    requested = float(target_lufs)
    filter_target, filter_peak = requested, AUDIO_TRUE_PEAK_CEILING_DBFS
    peak_limited = False
    base = [tool, "-nostdin", "-hide_banner", "-loglevel", "info", "-nostats", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", AUDIO_INPUT_DEMUXERS]
    try:
        # Reserve our private output exclusively; retries may replace only this
        # owned candidate and always encode from the original staged input.
        descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        output_created = True
        for attempt in range(MAX_AUDIO_NORMALIZE_ATTEMPTS):
            filter_spec = f"loudnorm=I={filter_target:.2f}:LRA=11:TP={filter_peak:.2f}:print_format=json"
            encode = [*base, "-i", source_path, "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-map_chapters", "-1",
                      "-af", filter_spec, "-ar", str(AUDIO_OUTPUT_SAMPLE_RATE), "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", "-f", "ipod", "-y", output_path]
            encoded = _run_audio_loudness_pass(encode, output_path, workspace, cancel_event, deadline, popen, clock, sleeper)
            measure = [*base, "-i", output_path, "-map", "0:a:0", "-vn", "-af",
                       f"loudnorm=I={requested:.2f}:LRA=11:TP=-2:print_format=json", "-f", "null", "-"]
            decoded = _run_audio_loudness_pass(measure, None, workspace, cancel_event, deadline, popen, clock, sleeper)
            if cancel_event is not None and cancel_event.is_set():
                raise NativeMediaCancelledError()
            if "input_tp" not in decoded:
                raise ConversionInputError("The encoded audio peak could not be verified.")
            peak_limited = peak_limited or encoded["output_tp"] >= filter_peak - 0.05
            # FFmpeg prints hundredths of a dB; keep the rounding uncertainty
            # below the advertised ceiling as well.
            if decoded["input_tp"] > AUDIO_TRUE_PEAK_CEILING_DBFS - AUDIO_PEAK_MEASUREMENT_MARGIN_DB:
                peak_limited = True
                correction = decoded["input_tp"] - AUDIO_TRUE_PEAK_CEILING_DBFS + AUDIO_PEAK_CORRECTION_MARGIN_DB
                filter_peak = max(FFMPEG_MIN_TRUE_PEAK_DBFS, filter_peak - correction)
                continue
            loudness_error = requested - decoded["input_i"]
            corrected_target = min(FFMPEG_MAX_LOUDNESS_LUFS, max(FFMPEG_MIN_LOUDNESS_LUFS, filter_target + loudness_error))
            if (abs(loudness_error) > AUDIO_LOUDNESS_TOLERANCE_LU and not peak_limited
                    and attempt + 1 < MAX_AUDIO_NORMALIZE_ATTEMPTS and round(corrected_target, 2) != round(filter_target, 2)):
                filter_target = corrected_target
                continue
            summary = {
                "input_lufs": encoded["input_i"], "output_lufs": decoded["input_i"],
                "true_peak_dbfs": decoded["input_tp"], "normalization_mode": encoded["normalization_type"],
                "peak_limited": peak_limited,
            }
            descriptor = os.open(metrics_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            metrics_created = True
            with os.fdopen(descriptor, "w", encoding="utf-8") as metrics_file:
                json.dump(summary, metrics_file, allow_nan=False, separators=(",", ":"))
            completed = True
            return
        raise ConversionInputError("The encoded audio could not meet the true-peak ceiling.")
    except OSError as error:
        raise ConversionInputError("The audio could not be normalized.") from error
    finally:
        if not completed:
            for path, created in ((output_path, output_created), (metrics_path, metrics_created)):
                if created:
                    Path(path).unlink(missing_ok=True)


def _convert(data, filename, kind, operation_id, options, staging_root=None, cancel_event=None, runner=None, watermark_image=None):
    target_format = options.get("target_format")
    wants_ffmpeg_video = kind == "video" and operation_id in {"video-optimize", "video-fit-size"} and target_format in {"av1", "mp4", "webm", "x265"}
    ffmpeg_video_available = (
        native_av1_encoder_available() if target_format == "av1" else native_video_format_available(target_format)
    ) if wants_ffmpeg_video else False
    if not native_media_available(kind) and not (wants_ffmpeg_video and ffmpeg_video_available):
        raise NativeMediaUnavailableError()
    tool_path = NATIVE_MEDIA_TOOLS[kind]
    if not os.path.isabs(tool_path) and not (wants_ffmpeg_video and ffmpeg_video_available):
        raise NativeMediaUnavailableError()
    runner = runner or _run_bounded
    with tempfile.TemporaryDirectory(prefix="officekit-media-adapter-", dir=staging_root) as workspace:
        extension = _safe_extension(filename)
        source_path = os.path.join(workspace, f"source.{extension}")
        with open(source_path, "xb") as source:
            source.write(data)
            source.flush()
            os.fsync(source.fileno())
        if kind == "video":
            if operation_id == "video-crop":
                options = _resolve_video_crop_options(source_path, options, cancel_event)
            if operation_id in {"video-mute", "video-strip-metadata", "video-speed", "video-to-gif", "video-crop", "video-resize", "video-watermark-overlay"}:
                target_format = "gif" if operation_id == "video-to-gif" else "mov"
                output_path = os.path.join(workspace, f"prepared.{target_format}")
                watermark_image_path = None
                if operation_id == "video-watermark-overlay":
                    if not isinstance(watermark_image, bytes) or not 0 < len(watermark_image) <= 5 * 1024 * 1024:
                        raise ConversionInputError("Choose a watermark image before preparing this copy.")
                    watermark_image_path = os.path.join(workspace, "watermark.png")
                    with open(watermark_image_path, "xb") as watermark_file:
                        watermark_file.write(watermark_image)
                runner(_video_transform_candidate(
                    source_path, output_path, operation_id, options, watermark_image_path,
                ), output_path, workspace, cancel_event)
                output_data = Path(output_path).read_bytes()
                if operation_id == "video-mute":
                    attributes = {"audio_removed": True}
                elif operation_id == "video-strip-metadata":
                    attributes = {"metadata_removed": True}
                elif operation_id == "video-speed":
                    attributes = {"factor_percent": options["factor_percent"]}
                elif operation_id == "video-crop":
                    attributes = _crop_result_attributes(options)
                elif operation_id == "video-resize":
                    attributes = {key: options[key] for key in ("max_width", "max_height")}
                    if options.get("fps") is not None:
                        attributes["max_fps"] = options["fps"]
                elif operation_id == "video-watermark-overlay":
                    attributes = {"watermarked": True, **options}
                else:
                    attributes = {"fps": options["fps"], "max_width": options["max_width"], "max_duration_seconds": options["max_duration_seconds"]}
                return output_data, target_format, "image/gif" if target_format == "gif" else "video/quicktime", attributes
            if operation_id == "video-hevc-convert":
                if not native_hevc_encoder_available():
                    raise NativeMediaUnavailableError()
                output_path = os.path.join(workspace, "prepared.mov")
                runner(_video_candidate(source_path, output_path, "hevc", "higher"), output_path, workspace, cancel_event)
                return Path(output_path).read_bytes(), "mov", "video/quicktime", {"codec": "hevc"}
            target_format = options.get("target_format", "m4v")
            output_format = _video_file_format(target_format)
            output_path = os.path.join(workspace, f"prepared.{output_format}")
            if operation_id == "video-optimize":
                quality = options.get("quality", "balanced")
                compression = options.get("compression")
                args = _video_candidate(source_path, output_path, target_format, quality, compression)
                runner(args, output_path, workspace, cancel_event)
                output_data = Path(output_path).read_bytes()
                attributes = {"quality": quality}
                if compression is not None:
                    attributes["compression"] = compression
                attributes.update(_video_codec_attributes(target_format))
                media_type = _video_mime_type(target_format)
                return output_data, output_format, media_type, attributes
            if operation_id == "video-fit-size":
                quality = options.get("quality", "balanced")
                compression = options.get("compression")
                attempts = []
                candidates = (((quality, compression), (quality, max(compression, 75)), (quality, 100))
                              if compression is not None else ((quality, None), ("balanced", None), ("smaller", None)))
                for candidate_quality, candidate_compression in candidates:
                    candidate = (candidate_quality, candidate_compression)
                    if candidate in attempts:
                        continue
                    attempts.append(candidate)
                    candidate_path = os.path.join(workspace, f"prepared-{len(attempts)}.{output_format}")
                    args = _video_candidate(source_path, candidate_path, target_format, candidate_quality, candidate_compression)
                    runner(args, candidate_path, workspace, cancel_event)
                    output_data = Path(candidate_path).read_bytes()
                    if len(output_data) <= options["target_bytes"]:
                        attributes = {"target_bytes": options["target_bytes"], "target_met": True, "quality": candidate_quality}
                        if candidate_compression is not None:
                            attributes["compression"] = candidate_compression
                        attributes.update(_video_codec_attributes(target_format))
                        media_type = _video_mime_type(target_format)
                        return output_data, output_format, media_type, attributes
                attributes = {"target_bytes": options["target_bytes"], "target_met": False, "quality": attempts[-1][0]}
                if attempts[-1][1] is not None:
                    attributes["compression"] = attempts[-1][1]
                attributes.update(_video_codec_attributes(target_format))
                media_type = _video_mime_type(target_format)
                return output_data, output_format, media_type, attributes
            raise NativeMediaUnavailableError()

        if operation_id == "audio-artwork":
            output_path = os.path.join(workspace, "prepared.m4a")
            runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            output_data = Path(output_path).read_bytes()
            return output_data, "m4a", _audio_mime("m4a"), {"max_edge": options["max_edge"], "artwork_resized": True}

        if operation_id == "audio-speed":
            output_path = os.path.join(workspace, "prepared.m4a")
            runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            output_data = Path(output_path).read_bytes()
            return output_data, "m4a", _audio_mime("m4a"), {"factor_percent": options["factor_percent"]}

        if operation_id == "audio-normalize":
            output_path = os.path.join(workspace, "prepared.m4a")
            if native_audio_loudnorm_available():
                _run_ffmpeg_loudnorm(source_path, output_path, workspace, options["target_lufs"], cancel_event)
            else:
                runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            output_data = Path(output_path).read_bytes()
            return output_data, "m4a", _audio_mime("m4a"), _normalization_attributes(output_path, options)

        target_format = options.get("target_format", "m4a")
        output_path = os.path.join(workspace, f"prepared.{target_format}")
        if operation_id == "audio-fit-size":
            selected_rate = options.get("bitrate_kbps", 192)
            rates = list(dict.fromkeys([selected_rate, 192, 128, 96, 64, 48, 32])) if target_format in {"m4a", "mp3"} else [selected_rate]
            for rate in rates:
                candidate_path = os.path.join(workspace, f"prepared-{rate}.{target_format}")
                runner(_audio_candidate(source_path, candidate_path, target_format, rate), candidate_path, workspace, cancel_event)
                output_data = Path(candidate_path).read_bytes()
                if len(output_data) <= options["target_bytes"]:
                    return output_data, target_format, _audio_mime(target_format), {
                        "target_bytes": options["target_bytes"], "target_met": True,
                        **_audio_attributes(target_format, rate),
                    }
            return output_data, target_format, _audio_mime(target_format), {
                "target_bytes": options["target_bytes"], "target_met": False,
                **_audio_attributes(target_format, rates[-1]),
            }
        if operation_id in {"audio-optimize", "audio-convert"}:
            bitrate = options.get("bitrate_kbps", 192)
            compression = options.get("compression")
            if operation_id == "audio-optimize" and compression is not None and "bitrate_kbps" not in options:
                bitrate = 160 if compression == "adaptive" else round(320 - (compression - 5) * 256 / 95)
                bitrate = max(32, min(320, int(round(bitrate / 16) * 16)))
            if operation_id == "audio-optimize" and options.get("no_upscale"):
                lower_rate = _lower_bitrate_target(source_path, bitrate)
                if lower_rate is None:
                    source_format = _audio_source_format(filename)
                    return data, source_format, _audio_mime(source_format), {"no_op": True, "no_upscale": True}
                bitrate = lower_rate
            runner(_audio_candidate(source_path, output_path, target_format, bitrate), output_path, workspace, cancel_event)
            output_data = Path(output_path).read_bytes()
            attributes = _audio_attributes(target_format, bitrate)
            if compression is not None:
                attributes["compression"] = compression
            if options.get("no_upscale"):
                attributes["no_upscale"] = True
            return output_data, target_format, _audio_mime(target_format), attributes
        raise NativeMediaUnavailableError()


def _audio_mime(target_format):
    return {"m4a": "audio/mp4", "wav": "audio/wav", "aiff": "audio/aiff", "flac": "audio/flac", "mp3": "audio/mpeg"}[target_format]


def _native_output_signature_valid(extension, header):
    if extension == "webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    if extension in {"m4a", "m4v", "mov", "mp4"}:
        return len(header) >= 8 and header[4:8] == b"ftyp"
    if extension == "flac":
        return header.startswith(b"fLaC")
    if extension == "mp3":
        return header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    if extension == "wav":
        return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if extension == "aiff":
        return len(header) >= 12 and header.startswith(b"FORM") and header[8:12] in {b"AIFF", b"AIFC"}
    if extension == "gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    return False


def _verify_native_output(path, extension):
    try:
        with open(path, "rb") as output:
            header = output.read(16)
    except OSError as error:
        raise ConversionInputError("The native media output could not be verified.") from error
    if not _native_output_signature_valid(extension, header):
        raise ConversionInputError("The native media output did not match its expected container.")


def _normalization_attributes(output_path, options):
    metrics_path = f"{output_path}.metrics.json"
    try:
        with open(metrics_path, "rb") as metrics_file:
            raw = metrics_file.read(4097)
        if len(raw) > 4096:
            raise ValueError("Loudness metrics exceeded their response limit")
        metrics = json.loads(raw)
        common = {"input_lufs", "output_lufs", "peak_limited"}
        legacy = common | {"applied_gain_db", "sample_peak_dbfs"}
        true_peak = common | {"true_peak_dbfs", "normalization_mode"}
        if not isinstance(metrics, dict) or frozenset(metrics) not in {frozenset(legacy), frozenset(true_peak)} or type(metrics["peak_limited"]) is not bool:
            raise ValueError("Loudness metrics were invalid")
        numeric = set(metrics) - {"peak_limited", "normalization_mode"}
        if any(type(metrics[key]) not in {int, float} or not math.isfinite(metrics[key]) for key in numeric):
            raise ValueError("Loudness metrics were invalid")
        if "normalization_mode" in metrics and metrics["normalization_mode"] not in {"linear", "dynamic"}:
            raise ValueError("Loudness metrics were invalid")
        result = {
            "target_lufs": float(options["target_lufs"]),
            **metrics,
            "target_met": (abs(metrics["output_lufs"] - float(options["target_lufs"])) <= AUDIO_LOUDNESS_TOLERANCE_LU
                           and metrics.get("true_peak_dbfs", metrics.get("sample_peak_dbfs")) <= AUDIO_TRUE_PEAK_CEILING_DBFS),
        }
        if "true_peak_dbfs" in metrics:
            result["true_peak_ceiling_dbfs"] = -2.0
        else:
            result["peak_ceiling_dbfs"] = -2.0
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ConversionInputError("The audio loudness result could not be verified.") from error
    finally:
        try:
            os.unlink(metrics_path)
        except FileNotFoundError:
            pass


def convert_native_media_to_file(source_path, filename, operation_id, options, workspace, cancel_event=None, runner=None, watermark_image_path=None):
    """Convert a private staged file and keep the result file-backed for its caller."""
    kind = operation_id.split("-", 1)[0]
    target_format = options.get("target_format")
    wants_ffmpeg_video = kind == "video" and operation_id in {"video-optimize", "video-fit-size"} and target_format in {"av1", "mp4", "webm", "x265"}
    ffmpeg_video_available = (
        native_av1_encoder_available() if target_format == "av1" else native_video_format_available(target_format)
    ) if wants_ffmpeg_video else False
    if kind not in {"video", "audio"} or (not native_media_available(kind) and not (wants_ffmpeg_video and ffmpeg_video_available)):
        raise NativeMediaUnavailableError()
    tool_path = NATIVE_MEDIA_TOOLS[kind]
    if not os.path.isabs(tool_path) and not (wants_ffmpeg_video and ffmpeg_video_available):
        raise NativeMediaUnavailableError()
    if not os.path.isdir(workspace):
        raise ConversionInputError()
    verify_output = runner is None
    runner = runner or _run_bounded
    source_path = os.path.realpath(source_path)
    workspace = os.path.realpath(workspace)
    if os.path.commonpath((source_path, workspace)) != workspace:
        raise ConversionInputError()
    source_info = os.stat(source_path, follow_symlinks=False)
    if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= MAX_NATIVE_MEDIA_BYTES:
        raise ConversionInputError()
    if operation_id == "video-watermark-overlay":
        if not isinstance(watermark_image_path, str):
            raise ConversionInputError("Choose a watermark image before preparing this copy.")
        watermark_image_path = os.path.realpath(watermark_image_path)
        if os.path.commonpath((watermark_image_path, workspace)) != workspace:
            raise ConversionInputError()
        watermark_info = os.stat(watermark_image_path, follow_symlinks=False)
        if not stat.S_ISREG(watermark_info.st_mode) or not 0 < watermark_info.st_size <= 5 * 1024 * 1024:
            raise ConversionInputError()
    if _workspace_size(workspace) > MAX_NATIVE_MEDIA_WORKSPACE_BYTES:
        raise ImageOutputLimitError("Native media workspace limit reached")

    if kind == "video":
        if operation_id == "video-crop":
            options = _resolve_video_crop_options(source_path, options, cancel_event)
        if operation_id in {"video-mute", "video-strip-metadata", "video-speed", "video-to-gif", "video-crop", "video-resize", "video-watermark-overlay"}:
            target_format = "gif" if operation_id == "video-to-gif" else "mov"
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.{target_format}")
            runner(_video_transform_candidate(
                source_path, output_path, operation_id, options, watermark_image_path,
            ), output_path, workspace, cancel_event)
            if operation_id == "video-mute":
                attributes = {"audio_removed": True}
            elif operation_id == "video-strip-metadata":
                attributes = {"metadata_removed": True}
            elif operation_id == "video-speed":
                attributes = {"factor_percent": options["factor_percent"]}
            elif operation_id == "video-crop":
                attributes = _crop_result_attributes(options)
            elif operation_id == "video-resize":
                attributes = {key: options[key] for key in ("max_width", "max_height")}
                if options.get("fps") is not None:
                    attributes["max_fps"] = options["fps"]
            elif operation_id == "video-watermark-overlay":
                attributes = {"watermarked": True, **options}
            else:
                attributes = {"fps": options["fps"], "max_width": options["max_width"], "max_duration_seconds": options["max_duration_seconds"]}
            media_type = "image/gif" if target_format == "gif" else "video/quicktime"
        elif operation_id == "video-optimize":
            target_format = options.get("target_format", "m4v")
            output_format = _video_file_format(target_format)
            quality = options.get("quality", "balanced")
            compression = options.get("compression")
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.{output_format}")
            runner(_video_candidate(source_path, output_path, target_format, quality, compression), output_path, workspace, cancel_event)
            attributes = {"quality": quality}
            if compression is not None:
                attributes["compression"] = compression
            attributes.update(_video_codec_attributes(target_format))
            media_type = _video_mime_type(target_format)
            target_format = output_format
        elif operation_id == "video-hevc-convert":
            if not native_hevc_encoder_available():
                raise NativeMediaUnavailableError()
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.mov")
            runner(_video_candidate(source_path, output_path, "hevc", "higher"), output_path, workspace, cancel_event)
            target_format = "mov"
            media_type = "video/quicktime"
            attributes = {"codec": "hevc"}
        elif operation_id == "video-fit-size":
            target_format = options.get("target_format", "m4v")
            output_format = _video_file_format(target_format)
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.{output_format}")
            quality = options.get("quality", "balanced")
            compression = options.get("compression")
            attempts = []
            previous_candidate = None
            candidates = (((quality, compression), (quality, max(compression, 75)), (quality, 100))
                          if compression is not None else ((quality, None), ("balanced", None), ("smaller", None)))
            for candidate_quality, candidate_compression in candidates:
                candidate = (candidate_quality, candidate_compression)
                if candidate in attempts:
                    continue
                attempts.append(candidate)
                candidate_path = os.path.join(workspace, f"candidate-{len(attempts)}-{uuid_token()}.{output_format}")
                if previous_candidate is not None:
                    os.unlink(previous_candidate)
                runner(_video_candidate(source_path, candidate_path, target_format, candidate_quality, candidate_compression), candidate_path, workspace, cancel_event)
                output_path = candidate_path
                previous_candidate = candidate_path
                if os.path.getsize(candidate_path) <= options["target_bytes"]:
                    attributes = {"target_bytes": options["target_bytes"], "target_met": True, "quality": candidate_quality}
                    if candidate_compression is not None:
                        attributes["compression"] = candidate_compression
                    attributes.update(_video_codec_attributes(target_format))
                    break
            else:
                attributes = {"target_bytes": options["target_bytes"], "target_met": False, "quality": attempts[-1][0]}
                if attempts[-1][1] is not None:
                    attributes["compression"] = attempts[-1][1]
                attributes.update(_video_codec_attributes(target_format))
            media_type = _video_mime_type(target_format)
            target_format = output_format
        else:
            raise NativeMediaUnavailableError()
    else:
        target_format = options.get("target_format", "m4a")
        if operation_id == "audio-speed":
            target_format = "m4a"
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.m4a")
            runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            attributes = {"factor_percent": options["factor_percent"]}
        elif operation_id == "audio-artwork":
            target_format = "m4a"
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.m4a")
            runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            attributes = {"max_edge": options["max_edge"], "artwork_resized": True}
        elif operation_id == "audio-normalize":
            target_format = "m4a"
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.m4a")
            if native_audio_loudnorm_available():
                _run_ffmpeg_loudnorm(source_path, output_path, workspace, options["target_lufs"], cancel_event)
            else:
                runner(_audio_transform_candidate(source_path, output_path, operation_id, options), output_path, workspace, cancel_event)
            attributes = _normalization_attributes(output_path, options)
        elif operation_id == "audio-fit-size":
            selected_rate = options.get("bitrate_kbps", 192)
            rates = list(dict.fromkeys([selected_rate, 192, 128, 96, 64, 48, 32])) if target_format in {"m4a", "mp3"} else [selected_rate]
            previous_candidate = None
            for rate in rates:
                candidate_path = os.path.join(workspace, f"candidate-{rate}-{uuid_token()}.{target_format}")
                if previous_candidate is not None:
                    os.unlink(previous_candidate)
                runner(_audio_candidate(source_path, candidate_path, target_format, rate), candidate_path, workspace, cancel_event)
                output_path = candidate_path
                previous_candidate = candidate_path
                if os.path.getsize(candidate_path) <= options["target_bytes"]:
                    attributes = {
                        "target_bytes": options["target_bytes"], "target_met": True,
                        **_audio_attributes(target_format, rate),
                    }
                    break
            else:
                attributes = {
                    "target_bytes": options["target_bytes"], "target_met": False,
                    **_audio_attributes(target_format, rates[-1]),
                }
        elif operation_id in {"audio-optimize", "audio-convert"}:
            bitrate = options.get("bitrate_kbps", 192)
            compression = options.get("compression")
            if operation_id == "audio-optimize" and compression is not None and "bitrate_kbps" not in options:
                bitrate = 160 if compression == "adaptive" else round(320 - (compression - 5) * 256 / 95)
                bitrate = max(32, min(320, int(round(bitrate / 16) * 16)))
            if operation_id == "audio-optimize" and options.get("no_upscale"):
                lower_rate = _lower_bitrate_target(source_path, bitrate)
                if lower_rate is None:
                    target_format = _audio_source_format(filename)
                    return source_path, target_format, _audio_mime(target_format), {"no_op": True, "no_upscale": True}, source_info.st_size
                bitrate = lower_rate
            output_path = os.path.join(workspace, f"prepared-{uuid_token()}.{target_format}")
            runner(_audio_candidate(source_path, output_path, target_format, bitrate), output_path, workspace, cancel_event)
            attributes = _audio_attributes(target_format, bitrate)
            if compression is not None:
                attributes["compression"] = compression
            if options.get("no_upscale"):
                attributes["no_upscale"] = True
        else:
            raise NativeMediaUnavailableError()
        media_type = _audio_mime(target_format)

    if cancel_event is not None and cancel_event.is_set():
        raise NativeMediaCancelledError()
    if verify_output:
        _verify_native_output(output_path, target_format)
    try:
        output_size = os.path.getsize(output_path)
    except OSError as error:
        raise ConversionInputError() from error
    if not 0 < output_size <= MAX_NATIVE_MEDIA_BYTES:
        raise ImageOutputLimitError() if output_size > MAX_NATIVE_MEDIA_BYTES else ConversionInputError()
    return output_path, target_format, media_type, attributes, output_size


def uuid_token():
    return os.urandom(16).hex()


def convert_native_media(data, filename, operation_id, options, cancel_event=None, runner=None, watermark_image=None):
    kind = operation_id.split("-", 1)[0]
    result = _convert(
        data, filename, kind, operation_id, options,
        cancel_event=cancel_event, runner=runner, watermark_image=watermark_image,
    )
    if runner is None:
        _verify_native_output_from_bytes(result[0], result[1])
    return result


def _verify_native_output_from_bytes(data, extension):
    if not _native_output_signature_valid(extension, data[:16]):
        raise ConversionInputError("The native media output did not match its expected container.")
