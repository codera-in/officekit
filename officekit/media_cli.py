"""Local command line entry point for the Media Toolkit operation contract."""

import argparse
import ast
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

from pydantic import ValidationError

from .engines.engine_conversion_errors import ConversionInputError
from .engines.engine_media_models import MAX_MEDIA_OUTPUT_BYTES, MediaOperation
from .engines.engine_media_devices import (
    resolve_device_aspect,
    resolve_paper_aspect,
    supported_devices,
    supported_paper_sizes,
)
from .engines.engine_media_naming import output_name_capture_indices, render_output_name, validate_output_name_template
from .engines.engine_media_crop import (
    parse_crop_aspect_ratio as _parse_crop_aspect_ratio,
    crop_rectangle as _crop_rectangle,
    smart_crop_rectangle as _smart_crop_rectangle,
)
from .engines.engine_media_native import (
    MAX_NATIVE_MEDIA_BYTES,
    NativeMediaUnavailableError,
    _safe_extension,
    convert_native_media_to_file,
    probe_audio_duration,
    probe_smart_crop_bounds,
    probe_video_dimensions,
)
from .engines.engine_media_models import OPERATION_OPTIONS, validate_operation_sequence
from .engines.engine_media_optimizer import MediaOperationUnavailableError, MediaOptimizerEngine
from .engines.engine_media_operation_defaults import (
    MAX_OPERATION_DEFAULTS_BYTES,
    MediaOperationDefaultsStore,
    MediaOperationDefaultsStoreError,
)
from .engines.engine_media_preset_zones import (
    MediaPresetZoneCreate,
    MediaPresetZoneRebind,
    MediaPresetZoneRename,
    MediaPresetZoneStore,
    MediaPresetZoneStoreError,
)
from .engines.engine_media_pipelines import (
    MediaPipelineCreate,
    MediaPipelineRename,
    MediaPipelineStore,
    MediaPipelineStoreError,
)
from .engines.engine_media_pipeline_triggers import (
    MediaPipelineTriggerBinding,
    MediaPipelineTriggerStore,
    MediaPipelineTriggerStoreError,
)


MAX_RECIPE_BYTES = 16 * 1024
MAX_FILES = 30
MAX_DIRECTORY_ENTRIES = 10_000
MAX_WATERMARK_BYTES = 5 * 1024 * 1024


def _run_settings(args, stdout):
    store = MediaOperationDefaultsStore()
    if args.settings == "schema":
        value = {operation_id: model.model_json_schema(by_alias=True) for operation_id, model in OPERATION_OPTIONS.items()}
    elif args.settings == "list":
        value = store.list()
    elif args.settings == "get":
        if not args.operation_id:
            raise ValueError("--settings get requires --operation-id")
        if args.operation_id not in OPERATION_OPTIONS:
            raise ValueError("Unsupported media operation")
        value = store.list().get(args.operation_id)
    elif args.settings == "set":
        if not args.operation_id or args.options_json is None:
            raise ValueError("--settings set requires --operation-id and --options-json")
        if len(args.options_json.encode("utf-8")) > MAX_OPERATION_DEFAULTS_BYTES:
            raise ValueError("--options-json exceeds the 16 KiB settings limit")
        try:
            options = json.loads(args.options_json)
        except (json.JSONDecodeError, TypeError, RecursionError):
            raise ValueError("--options-json must contain a JSON object") from None
        if not isinstance(options, dict):
            raise ValueError("--options-json must contain a JSON object")
        value = store.put(args.operation_id, options)
    else:
        store.clear(args.operation_id)
        value = {"state": "cleared", "operationId": args.operation_id} if args.operation_id else {"state": "cleared"}
    stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    return 0


def _run_settings_command(argv, stdout, stderr):
    parser = argparse.ArgumentParser(prog="officekit-media settings", description="Inspect or update shared typed operation defaults.")
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", help="Show accepted operation options")
    schema.add_argument("query", nargs="*", help="Filter by operation ID")
    schema.add_argument("--json", action="store_true", help="Emit JSON (the default format)")
    get = commands.add_parser("get", help="Read saved options for an operation")
    get.add_argument("operation_id")
    get.add_argument("--json", action="store_true", help="Emit JSON")
    set_command = commands.add_parser("set", help="Save validated options for an operation")
    set_command.add_argument("operation_id")
    set_command.add_argument("options_json", help="JSON object matching the operation schema")
    set_command.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)
    try:
        store = MediaOperationDefaultsStore()
        if args.command == "schema":
            terms = [term.casefold() for term in args.query]
            value = {}
            for operation_id, model in OPERATION_OPTIONS.items():
                schema_value = model.model_json_schema(by_alias=True)
                searchable = f"{operation_id} {json.dumps(schema_value, sort_keys=True)}".casefold()
                if all(
                    operation_id.casefold().startswith(f"{term}-") if term in {"image", "video", "audio", "pdf"}
                    else term in searchable
                    for term in terms
                ):
                    value[operation_id] = schema_value
        elif args.command == "get":
            if args.operation_id not in OPERATION_OPTIONS:
                raise ValueError("Unsupported media operation")
            value = store.list().get(args.operation_id)
        else:
            if len(args.options_json.encode("utf-8")) > MAX_OPERATION_DEFAULTS_BYTES:
                raise ValueError("Options JSON exceeds the 16 KiB settings limit")
            try:
                options = json.loads(args.options_json)
            except (json.JSONDecodeError, TypeError, RecursionError):
                raise ValueError("Options must be a JSON object") from None
            if not isinstance(options, dict):
                raise ValueError("Options must be a JSON object")
            value = store.put(args.operation_id, options)
        stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
        return 0
    except (OSError, ValueError, ValidationError, MediaOperationDefaultsStoreError) as error:
        stderr.write(f"officekit-media: {str(error) or 'settings operation failed'}\n")
        return 2


def _find_pipeline(store, reference):
    entries = store.list()
    return next((entry for entry in entries if entry["id"] == reference or entry["name"].casefold() == reference.casefold()), None)


def _find_preset_zone(store, reference):
    entries = store.list_bindings()
    return next((entry for entry in entries if entry["id"] == reference or entry["name"].casefold() == reference.casefold()), None)


def _split_pipeline_dsl_steps(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > MAX_RECIPE_BYTES:
        raise ValueError("Inline pipeline must be a non-empty DSL string within the 16 KiB limit")
    steps = []
    start = depth = 0
    quote = None
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
            if depth > 1:
                raise ValueError("Nested inline pipeline steps are not supported")
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Inline pipeline parentheses are unbalanced")
        elif char == "-" and index + 1 < len(source) and source[index + 1] == ">" and depth == 0:
            steps.append(source[start:index].strip())
            start = index + 2
            index += 1
        index += 1
    if quote or depth:
        raise ValueError("Inline pipeline quotes or parentheses are unbalanced")
    steps.append(source[start:].strip())
    if not 1 <= len(steps) <= 8 or any(not step for step in steps):
        raise ValueError("Inline pipelines require 1 to 8 non-empty steps")
    return steps


def _parse_pipeline_dsl_arguments(source):
    if not source.strip():
        return {}
    parts = []
    start = 0
    quote = None
    escaped = False
    for index, char in enumerate(source):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == ",":
            parts.append(source[start:index].strip())
            start = index + 1
    if quote:
        raise ValueError("Inline pipeline argument quotes are unbalanced")
    parts.append(source[start:].strip())
    values = {}
    for part in parts:
        key, separator, raw = part.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key) or not raw or key in values:
            raise ValueError("Inline pipeline arguments must use unique key: value pairs")
        if raw in {"true", "false"}:
            value = raw == "true"
        elif raw[:1] in {"'", '"'}:
            try:
                value = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                raise ValueError("Inline pipeline string arguments must be quoted strings") from None
            if not isinstance(value, str):
                raise ValueError("Inline pipeline string arguments must be quoted strings")
        else:
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError, RecursionError):
                if not re.fullmatch(
                    r"(?:[A-Za-z][A-Za-z0-9_-]*|[0-9]+(?:\.[0-9]+)?(?:B|KB|MB|GB|KiB|MiB|GiB)|[0-9]+(?:\.[0-9]{1,4})?:[0-9]+(?:\.[0-9]{1,4})?|[0-9]{1,5}[xX][0-9]{1,5})",
                    raw, flags=re.IGNORECASE,
                ):
                    raise ValueError("Inline pipeline values must be simple strings, numbers, or booleans") from None
                value = raw
        values[key] = value
    return values


def _parse_pipeline_dsl(source, media, source_path=None, fork_cuts=None):
    operations = []
    watermark_image = None
    pipeline_filter = None
    identity_downscale = False
    current_dimensions = None
    last_fork_operation_count = 0
    for index, step in enumerate(_split_pipeline_dsl_steps(source)):
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)(?:\((.*)\))?", step, flags=re.DOTALL)
        if not match:
            raise ValueError("Inline pipeline step syntax is invalid")
        name, arguments_source = match.groups()
        arguments = _parse_pipeline_dsl_arguments(arguments_source or "")
        if name == "fork":
            if arguments or fork_cuts is None:
                raise ValueError("fork() is available only in inline pipeline run and takes no arguments")
            if len(operations) <= last_fork_operation_count or len(fork_cuts) >= 3:
                raise ValueError("fork() requires a new transformation and pipelines allow at most 3 forks")
            fork_cuts.append(len(operations))
            last_fork_operation_count = len(operations)
            continue
        if name in {"if", "ifNot"}:
            if index != 0 or pipeline_filter is not None or not arguments or len(arguments) > 6:
                raise ValueError("Inline filters must be the first step and contain 1 to 6 supported conditions")
            conditions = []
            allowed_types = {
                "image", "video", "pdf", "audio", "jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff",
                "heic", "heif", "avif", "jxl", "gif", "mov", "mp4", "m4v", "mkv", "webm",
                "m4a", "wav", "aiff", "aif", "mp3", "flac", "caf",
            }
            for condition, condition_value in arguments.items():
                if condition in {"nameContains", "nameIs"}:
                    if not isinstance(condition_value, str) or not condition_value.strip() or len(condition_value) > 256:
                        raise ValueError("Inline filter conditions must be bounded non-empty strings")
                    conditions.append({"kind": condition, "value": condition_value})
                elif condition == "regex":
                    if not isinstance(condition_value, str) or not condition_value.strip():
                        raise ValueError("Inline regex filter requires a bounded pattern")
                    _validate_pipeline_filename_regex(condition_value)
                    conditions.append({"kind": condition, "value": condition_value})
                elif condition == "types":
                    if not isinstance(condition_value, str) or not condition_value.strip() or len(condition_value) > 160:
                        raise ValueError("Inline types filter requires a bounded list")
                    types = condition_value.casefold().split()
                    if not types or len(types) > 12 or any(value not in allowed_types for value in types):
                        raise ValueError("Inline types filters require supported media names or file extensions")
                    conditions.append({"kind": condition, "value": types})
                elif condition in {"fileSizeGreaterThan", "fileSizeLowerThan", "minFileSize"}:
                    try:
                        threshold = _parse_pipeline_target_size(condition_value)
                    except (ValueError, TypeError) as error:
                        raise ValueError("Inline file-size filters require a positive byte count or size unit") from error
                    conditions.append({"kind": condition, "value": threshold})
                elif condition in {
                    "widthGreaterThan", "widthLowerThan", "heightGreaterThan", "heightLowerThan",
                }:
                    if isinstance(condition_value, bool) or not isinstance(condition_value, int) or not 1 <= condition_value <= 10_000:
                        raise ValueError("Inline image-dimension filters require an integer from 1 to 10000")
                    conditions.append({"kind": condition, "value": condition_value})
                elif condition == "minResolution":
                    if not isinstance(condition_value, str):
                        raise ValueError("Inline minResolution requires a WIDTHxHEIGHT string")
                    resolution = re.fullmatch(r"([1-9][0-9]{0,4})[xX]([1-9][0-9]{0,4})", condition_value)
                    if resolution is None or any(int(value) > 10_000 for value in resolution.groups()):
                        raise ValueError("Inline minResolution must be between 1x1 and 10000x10000")
                    conditions.append({"kind": condition, "value": [int(value) for value in resolution.groups()]})
                elif condition in {"dpiGreaterThan", "dpiLowerThan"}:
                    if media not in {"image", "pdf"} or isinstance(condition_value, bool) or not isinstance(condition_value, int) or not 1 <= condition_value <= 10_000:
                        raise ValueError("Inline image/PDF-DPI filters require an integer from 1 to 10000")
                    conditions.append({"kind": condition, "value": condition_value})
                else:
                    raise ValueError("Inline filters support safe name, regex, type, file-size, image-dimension, and image-DPI conditions")
            pipeline_filter = {"conditions": conditions, "negate": name == "ifNot"}
            continue
        if name == "optimise" and not arguments:
            operation_id, options = {
                "image": ("image-optimize", {"quality": 82, "preserveMetadata": False}),
                "video": ("video-optimize", {"targetFormat": "m4v", "quality": "balanced"}),
                "pdf": ("pdf-lossless-compress", {"profile": "balanced"}),
                "audio": ("audio-optimize", {"targetFormat": "m4a", "bitrateKbps": 192}),
            }[media]
        elif name == "optimise" and media in {"image", "video", "audio"} and set(arguments) == {"compression"}:
            compression = arguments["compression"]
            if media in {"image", "video", "audio"} and compression == "adaptive":
                operation_id = {"image": "image-optimize", "video": "video-optimize", "audio": "audio-optimize"}[media]
                options = {"compression": "adaptive"}
                if media == "video":
                    options["targetFormat"] = "mp4"
                if media == "audio":
                    options["targetFormat"] = "m4a"
            elif isinstance(compression, int) and not isinstance(compression, bool) and 5 <= compression <= 100 and media == "audio":
                operation_id, options = "audio-optimize", {"targetFormat": "m4a", "compression": compression}
            elif isinstance(compression, int) and not isinstance(compression, bool) and 5 <= compression <= 100 and media == "image":
                operation_id, options = "image-optimize", {"compression": compression}
            elif isinstance(compression, int) and not isinstance(compression, bool) and 5 <= compression <= 100 and media == "video":
                operation_id, options = "video-optimize", {"targetFormat": "mp4", "compression": compression}
            else:
                raise ValueError("compression must be adaptive or an integer from 5 to 100")
        elif name == "optimise" and media == "image" and set(arguments) == {"adaptive"} and arguments["adaptive"] is True:
            operation_id, options = "image-optimize", {"adaptive": True}
        elif name == "convert" and set(arguments) <= {"to", "lossless"} and "to" in arguments and isinstance(arguments["to"], str):
            target = arguments["to"].casefold()
            lossless = arguments.get("lossless", False)
            if not isinstance(lossless, bool):
                raise ValueError("Inline convert lossless must be true or false")
            if media == "image" and target in {"png", "jpeg", "webp", "bmp", "tiff", "ico", "avif", "jxl"}:
                if lossless and target not in {"webp", "jxl"}:
                    raise ValueError("Lossless image conversion supports WebP and JPEG XL only")
                options = {"targetFormat": target, "quality": 90}
                if lossless:
                    options["lossless"] = True
                operation_id = "image-convert"
            elif media == "video" and target in {"av1", "m4v", "mov", "mp4", "webm", "x265"}:
                operation_id, options = "video-optimize", {"targetFormat": target, "quality": "balanced"}
            elif media == "video" and target == "hevc":
                operation_id, options = "video-hevc-convert", {}
            elif media == "video" and target == "gif":
                operation_id, options = "video-to-gif", {}
            elif media == "audio" and target in {"m4a", "wav", "aiff", "flac", "mp3"}:
                operation_id, options = "audio-convert", {"targetFormat": target, "bitrateKbps": 192}
            else:
                raise ValueError("Inline convert target is unavailable for this media type")
        elif name == "stripExif" and not arguments and media in {"image", "video"}:
            operation_id, options = f"{media}-strip-metadata", {}
        elif name == "removeAudio" and not arguments and media == "video":
            operation_id, options = "video-mute", {}
        elif name == "capFps" and set(arguments) == {"fps"} and media == "video":
            fps = arguments["fps"]
            if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
                raise ValueError("Inline capFps fps must be an integer between 1 and 120")
            if source_path is None:
                # The native resize path never enlarges, and the video probe rejects dimensions above this bound.
                source_width, source_height = 10_000, 10_000
            else:
                try:
                    source_width, source_height = probe_video_dimensions(source_path)
                except NativeMediaUnavailableError as error:
                    raise MediaOperationUnavailableError("Video frame-rate limiting is not available in this build.") from error
            operation_id, options = "video-resize", {
                "maxWidth": source_width, "maxHeight": source_height, "fps": fps,
            }
        elif name == "changeSpeed" and set(arguments) == {"factor"} and media in {"video", "audio"}:
            factor = arguments["factor"]
            if isinstance(factor, bool) or not isinstance(factor, (float, int)) or not math.isfinite(factor):
                raise ValueError("Inline changeSpeed factor must be a number")
            operation_id, options = f"{media}-speed", {"factorPercent": round(factor * 100)}
        elif name == "normalize" and set(arguments) in ({"lufs"}, set()) and media == "audio":
            target_lufs = arguments.get("lufs", -14)
            if isinstance(target_lufs, bool) or not isinstance(target_lufs, (float, int)):
                raise ValueError("Inline normalize lufs must be a number")
            operation_id, options = "audio-normalize", {"targetLufs": target_lufs}
        elif name == "lowerBitrate" and set(arguments) == {"kbps"} and media == "audio":
            bitrate = arguments["kbps"]
            if isinstance(bitrate, bool) or not isinstance(bitrate, int) or not 32 <= bitrate <= 640:
                raise ValueError("Inline lowerBitrate kbps must be an integer from 32 to 640")
            operation_id, options = "audio-optimize", {
                "targetFormat": "m4a", "bitrateKbps": bitrate, "noUpscale": True,
            }
        elif name == "optimise" and media == "pdf" and set(arguments) <= {"encoder", "dpi"} and arguments:
            encoder = arguments.get("encoder", "medium")
            if encoder not in {"medium", "aggressive", "lossless"}:
                raise ValueError("PDF optimise encoder must be medium, aggressive, or lossless")
            if "dpi" in arguments:
                dpi = arguments["dpi"]
                if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 300:
                    raise ValueError("PDF optimise dpi must be an integer from 72 to 300")
                operation_id, options = "pdf-visual-optimize", {
                    "quality": 45 if encoder == "aggressive" else 75, "dpi": dpi,
                }
            elif encoder == "lossless":
                operation_id, options = "pdf-lossless-compress", {"profile": "balanced"}
            else:
                operation_id, options = "pdf-visual-optimize", {
                    "quality": 45 if encoder == "aggressive" else 75, "dpi": 150,
                }
        elif name == "targetSize" and set(arguments) == {"size"}:
            target_bytes = _parse_pipeline_target_size(arguments["size"])
            operation_id, options = {
                "image": ("image-fit-size", {"targetBytes": target_bytes, "targetFormat": "webp"}),
                "video": ("video-fit-size", {"targetBytes": target_bytes, "targetFormat": "m4v", "quality": "balanced"}),
                "pdf": ("pdf-fit-size", {"targetBytes": target_bytes, "quality": 75, "dpi": 150}),
                "audio": ("audio-fit-size", {"targetBytes": target_bytes, "targetFormat": "m4a", "bitrateKbps": 192}),
            }[media]
        elif name == "extractPagesAsImages" and media == "pdf" and set(arguments) <= {"format", "quality", "dpi"}:
            target_format = arguments.get("format", "jpeg")
            if not isinstance(target_format, str) or target_format.casefold() not in {"jpeg", "jpg", "png"}:
                raise ValueError("Inline extractPagesAsImages format must be jpeg or png")
            quality_value = arguments.get("quality", "medium")
            quality_presets = {"low": 60, "medium": 80, "high": 92}
            if isinstance(quality_value, str):
                quality = quality_presets.get(quality_value.casefold())
                if quality is None:
                    raise ValueError("Inline extractPagesAsImages quality must be low, medium, or high")
            elif isinstance(quality_value, int) and not isinstance(quality_value, bool) and 1 <= quality_value <= 100:
                quality = quality_value
            else:
                raise ValueError("Inline extractPagesAsImages quality must be low, medium, high, or 1–100")
            dpi = arguments.get("dpi", 150)
            if isinstance(dpi, bool) or not isinstance(dpi, int) or not 36 <= dpi <= 300:
                raise ValueError("Inline extractPagesAsImages dpi must be an integer from 36 to 300")
            operation_id, options = "pdf-pages-to-images", {
                "targetFormat": "jpeg" if target_format.casefold() in {"jpeg", "jpg"} else "png",
                "quality": quality,
                "dpi": dpi,
            }
        elif name == "crop" and set(arguments) <= {"aspectRatio", "width", "height", "longEdge", "smartCrop"} and arguments:
            aspect_ratio = arguments.get("aspectRatio")
            smart_crop = arguments.get("smartCrop", False)
            if type(smart_crop) is not bool:
                raise ValueError("Inline smartCrop must be true or false")
            if aspect_ratio is not None:
                _parse_crop_aspect_ratio(aspect_ratio)
            target_width, target_height, long_edge = arguments.get("width"), arguments.get("height"), arguments.get("longEdge")
            if any(value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000)
                   for value in (target_width, target_height, long_edge)):
                raise ValueError("Inline crop dimensions must be integers from 1 to 10000")
            if long_edge is not None and (target_width is not None or target_height is not None):
                raise ValueError("Inline crop accepts longEdge or width/height, not both")
            if smart_crop and aspect_ratio is None and not (target_width is not None and target_height is not None):
                raise ValueError("smartCrop requires aspectRatio or both width and height")
            if media == "pdf":
                if smart_crop or aspect_ratio is None or any(value is not None for value in (target_width, target_height, long_edge)):
                    raise ValueError("PDF crop supports aspectRatio only")
                operation_id, options = "pdf-crop", {"aspectRatio": aspect_ratio, "pageLayout": "auto", "extend": False}
            else:
                if media not in {"image", "video"}:
                    raise ValueError("Inline crop is available only for image, video, and PDF")
                if source_path is None:
                    raise ValueError("Image/video crop requires a source file and is available through pipeline run")
                if smart_crop and operations:
                    raise ValueError("smartCrop must be the first transformation in an inline pipeline")
                if target_width is None and target_height is None and long_edge is None and aspect_ratio is None:
                    raise ValueError("Inline crop requires aspectRatio, width, height, or longEdge")
                saliency = None
                if smart_crop:
                    try:
                        saliency = probe_smart_crop_bounds(source_path, media)
                    except NativeMediaUnavailableError as error:
                        raise MediaOperationUnavailableError("Smart crop is available only in the macOS Media Toolkit.") from error
                    current_dimensions = (saliency["sourceWidth"], saliency["sourceHeight"])
                elif current_dimensions is None:
                    current_dimensions = _pipeline_media_dimensions(media, source_path)
                source_width, source_height = current_dimensions
                crop_id = f"{media}-crop"
                resize_id = f"{media}-resize"
                step_operations = []
                if aspect_ratio is not None:
                    crop_options = (
                        _smart_crop_rectangle(source_width, source_height, aspect_ratio, saliency)
                        if smart_crop else _crop_rectangle(source_width, source_height, aspect_ratio)
                    )
                    if target_width is None and target_height is None:
                        operation_id, options = crop_id, crop_options
                        current_dimensions = (crop_options["width"], crop_options["height"])
                    else:
                        step_operations.append(MediaOperation.model_validate({"operationId": crop_id, "options": crop_options}))
                        max_width = target_width or crop_options["width"]
                        max_height = target_height or crop_options["height"]
                elif target_width is not None and target_height is not None:
                    aspect = f"{target_width}:{target_height}"
                    crop_options = (
                        _smart_crop_rectangle(source_width, source_height, aspect, saliency)
                        if smart_crop else _crop_rectangle(source_width, source_height, aspect)
                    )
                    step_operations.append(MediaOperation.model_validate({"operationId": crop_id, "options": crop_options}))
                    current_dimensions = (crop_options["width"], crop_options["height"])
                    max_width, max_height = target_width, target_height
                else:
                    edge = long_edge or target_width or target_height
                    max_width = min(source_width, edge) if long_edge is not None or target_width is not None else source_width
                    max_height = min(source_height, edge) if long_edge is not None or target_height is not None else source_height
                if step_operations or aspect_ratio is None or long_edge is not None or target_width is not None or target_height is not None:
                    step_operations.append(MediaOperation.model_validate({"operationId": resize_id, "options": {"maxWidth": max_width, "maxHeight": max_height}}))
                    current_dimensions = _resized_dimensions(current_dimensions[0], current_dimensions[1], max_width, max_height)
                if step_operations:
                    operations.extend(step_operations)
                    continue
        elif name == "downscale" and set(arguments) == {"factor"} and media in {"image", "video", "audio"}:
            factor = arguments["factor"]
            if isinstance(factor, bool) or not isinstance(factor, (float, int)) or not math.isfinite(factor) or not 0 < factor <= 1:
                raise ValueError("Inline downscale factor must be greater than 0 and no more than 1")
            if source_path is None:
                raise ValueError("Factor-based downscale requires a source file and is available through pipeline run")
            if media == "image":
                if current_dimensions is None:
                    current_dimensions = _pipeline_media_dimensions(media, source_path)
                source_width, source_height = current_dimensions
                step_operations = _preset_operations(
                    "downscale-image", Path(source_path).name, factor=factor,
                    image_dimensions=(source_width, source_height),
                )
                identity_downscale = factor == 1
                if step_operations:
                    current_dimensions = _resized_dimensions(
                        source_width, source_height,
                        step_operations[0].options["max_width"], step_operations[0].options["max_height"],
                    )
            elif media == "video":
                if factor == 1:
                    step_operations = []
                    identity_downscale = True
                else:
                    if current_dimensions is None:
                        current_dimensions = _pipeline_media_dimensions(media, source_path)
                    video_dimensions = current_dimensions
                    step_operations = _preset_operations(
                        "downscale-video", Path(source_path).name, factor=factor,
                        video_dimensions=video_dimensions,
                    )
                    if step_operations:
                        current_dimensions = _resized_dimensions(
                            video_dimensions[0], video_dimensions[1],
                            step_operations[0].options["max_width"], step_operations[0].options["max_height"],
                        )
            else:
                if factor == 1:
                    step_operations = []
                    identity_downscale = True
                else:
                    source_data = _read_input(source_path)
                    with tempfile.TemporaryDirectory(prefix="officekit-inline-audio-downscale-") as workspace:
                        staged_source = Path(workspace) / f"source.{_safe_extension(Path(source_path).name)}"
                        staged_source.write_bytes(source_data)
                        try:
                            duration = probe_audio_duration(staged_source)
                        except NativeMediaUnavailableError as error:
                            raise MediaOperationUnavailableError("Audio downscaling is not available in this build.") from error
                    average_bitrate_kbps = len(source_data) * 8 / duration / 1000
                    step_operations = _preset_operations(
                        "downscale-audio", Path(source_path).name, factor=factor,
                        audio_bitrate_kbps=average_bitrate_kbps,
                    )
            operations.extend(step_operations)
            continue
        elif name == "watermark" and media in {"image", "video"} and set(arguments) <= {"image", "position", "opacity", "scale"} and isinstance(arguments.get("image"), str):
            watermark_image = arguments["image"]
            if not watermark_image.strip() or len(watermark_image) > 1024:
                raise ValueError("Inline watermark image must be a bounded non-empty path")
            position = arguments.get("position", "bottomRight")
            positions = {
                "bottomRight": "bottom-right", "bottomLeft": "bottom-left",
                "topRight": "top-right", "topLeft": "top-left", "center": "center",
            }
            opacity = arguments.get("opacity", 1.0)
            scale = arguments.get("scale", 0.15)
            if position not in positions:
                raise ValueError("Inline watermark position is unsupported")
            if (isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not math.isfinite(opacity)
                or not 0.1 <= opacity <= 1):
                raise ValueError("Inline watermark opacity must be between 0.1 and 1 for the typed overlay operation")
            if (isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale)
                or not 0.05 <= scale <= 0.6):
                raise ValueError("Inline watermark scale must be between 0.05 and 0.6")
            operation_id = f"{media}-watermark-overlay"
            options = {
                "placement": positions[position],
                "opacityPercent": round(opacity * 100),
                "sizePercent": round(scale * 100),
            }
        else:
            raise ValueError(f"Inline step '{name}' is unsupported for {media} pipelines")
        operations.append(MediaOperation.model_validate({"operationId": operation_id, "options": options}))
    watermark_operations = [
        operation for operation in operations
        if operation.operation_id in {"image-watermark-overlay", "video-watermark-overlay"}
    ]
    if watermark_image is not None and (len(watermark_operations) != 1 or not watermark_operations[0].operation_id.startswith(f"{media}-")):
        raise ValueError("Inline watermark requires exactly one matching media watermark step")
    if not operations and not identity_downscale:
        raise ValueError("Inline pipeline requires at least one supported transformation step")
    validate_operation_sequence(operations)
    return operations, watermark_image, pipeline_filter


def _parse_pipeline_target_size(value):
    units = {
        "b": 1, "byte": 1, "bytes": 1,
        "kb": 1000, "mb": 1000**2, "gb": 1000**3,
        "kib": 1024, "mib": 1024**2, "gib": 1024**3,
    }
    if isinstance(value, bool):
        raise ValueError("Inline targetSize size must be a positive byte value")
    if isinstance(value, (int, float)):
        amount, unit = Decimal(str(value)), "b"
    elif isinstance(value, str):
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]{1,3})?)\s*([A-Za-z]+)?", value.strip(), flags=re.ASCII)
        if not match:
            raise ValueError("Inline targetSize supports bytes, KB/MB/GB, and KiB/MiB/GiB")
        try:
            amount = Decimal(match.group(1))
        except InvalidOperation:
            raise ValueError("Inline targetSize size is invalid") from None
        unit = (match.group(2) or "b").casefold()
    else:
        raise ValueError("Inline targetSize size must be a byte count or size string")
    if unit not in units or not amount.is_finite() or amount <= 0:
        raise ValueError("Inline targetSize size must be positive and use a supported byte unit")
    target = int(amount * units[unit])
    if not 1 <= target <= MAX_MEDIA_OUTPUT_BYTES:
        raise ValueError("Inline targetSize must not exceed the supported output-size limit")
    return target


def _pipeline_filter_matches(pipeline_filter, filename, media, *, capture_groups=None):
    if pipeline_filter is None:
        return True
    name = Path(filename).name
    extension = Path(filename).suffix.lower().lstrip(".")
    extension = {"jpg": "jpeg", "tif": "tiff", "aif": "aiff"}.get(extension, extension)
    conditions = pipeline_filter.get("conditions", [pipeline_filter])
    matches = True
    image_dimensions = None
    image_dpi = None
    image_dpi_loaded = False
    pending_captures = ()
    for condition in conditions:
        kind, value = condition["kind"], condition["value"]
        if kind == "nameContains":
            matched = value.casefold() in name.casefold()
        elif kind == "nameIs":
            matched = value == name
        elif kind == "regex":
            flags = 0 if any(char.isupper() for char in value) else re.IGNORECASE
            regex_match = re.search(value, name, flags=flags)
            matched = regex_match is not None
            pending_captures = regex_match.groups() if regex_match is not None else ()
        elif kind == "types":
            normalized_types = {{"jpg": "jpeg", "tif": "tiff", "aif": "aiff"}.get(item, item) for item in value}
            matched = media in normalized_types or extension in normalized_types
        elif kind in {"fileSizeGreaterThan", "fileSizeLowerThan", "minFileSize"}:
            try:
                source_stat = os.stat(filename, follow_symlinks=False)
            except OSError:
                matched = False
            else:
                if not stat.S_ISREG(source_stat.st_mode):
                    matched = False
                elif kind == "fileSizeGreaterThan":
                    matched = source_stat.st_size > value
                elif kind == "fileSizeLowerThan":
                    matched = source_stat.st_size < value
                else:
                    matched = source_stat.st_size >= value
        elif kind in {"widthGreaterThan", "widthLowerThan", "heightGreaterThan", "heightLowerThan", "minResolution"}:
            if media != "image":
                matched = False
            else:
                try:
                    if image_dimensions is None:
                        image_dimensions = _pipeline_media_dimensions("image", filename)
                    width, height = image_dimensions
                except (OSError, ValueError, MediaOperationUnavailableError):
                    matched = False
                else:
                    if kind == "widthGreaterThan":
                        matched = width > value
                    elif kind == "widthLowerThan":
                        matched = width < value
                    elif kind == "heightGreaterThan":
                        matched = height > value
                    elif kind == "heightLowerThan":
                        matched = height < value
                    else:
                        matched = width >= value[0] and height >= value[1]
        elif kind in {"dpiGreaterThan", "dpiLowerThan"}:
            if media not in {"image", "pdf"}:
                matched = False
            else:
                if not image_dpi_loaded:
                    image_dpi_loaded = True
                    try:
                        if media == "pdf":
                            from .engines.engine_media_pdf import MediaPdfEngine
                            image_dpi = MediaPdfEngine.image_dpi_range(_read_input(filename))
                        else:
                            image_dpi = MediaOptimizerEngine._image_dpi(_read_input(filename))
                    except (OSError, ValueError, ConversionInputError, MediaOperationUnavailableError):
                        image_dpi = None
                if image_dpi is None:
                    matched = False
                elif kind == "dpiGreaterThan":
                    matched = all(axis > value for axis in image_dpi)
                else:
                    matched = all(axis < value for axis in image_dpi)
        else:
            matched = False
        matches = matches and matched
        if not matched:
            break
    if matches and not pipeline_filter["negate"] and capture_groups is not None:
        capture_groups.extend(pending_captures)
    return not matches if pipeline_filter["negate"] else matches


def _validate_pipeline_filename_regex(pattern):
    if len(pattern) > 128 or "(?" in pattern or re.search(r"\\[1-9]", pattern):
        raise ValueError("Inline filename regex uses an unsupported or oversized construct")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError("Inline filename regex is invalid") from error
    escaped = False
    in_class = False
    quantifiers = 0
    unbounded = 0
    group_stack = []
    closed_group = None
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
            closed_group = None
            continue
        if char == "\\":
            escaped = True
            closed_group = None
            continue
        if char == "[" and not in_class:
            in_class = True
            closed_group = None
            continue
        if char == "]" and in_class:
            in_class = False
            closed_group = None
            continue
        if in_class:
            continue
        if char == "(":
            group_stack.append({"quantified": False, "alternative": False})
            closed_group = None
            continue
        if char == "|" and group_stack:
            for group in group_stack:
                group["alternative"] = True
            closed_group = None
            continue
        if char == ")" and group_stack:
            closed_group = group_stack.pop()
            continue
        if char in "*+?":
            quantifiers += 1
            if char in "*+":
                unbounded += 1
            if closed_group and (closed_group["quantified"] or closed_group["alternative"]):
                raise ValueError("Inline filename regex cannot repeat a group with alternatives or quantifiers")
            for group in group_stack:
                group["quantified"] = True
            closed_group = None
            continue
        if char == "{" and index + 1 < len(pattern) and pattern[index + 1].isdigit():
            closing = pattern.find("}", index + 1)
            bounds = pattern[index + 1:closing] if closing >= 0 else ""
            repetition = re.fullmatch(r"([0-9]+)(?:,([0-9]*))?", bounds)
            if repetition is None:
                raise ValueError("Inline filename regex has invalid repetition bounds")
            upper = repetition.group(2)
            if "," in bounds and upper == "":
                unbounded += 1
            elif int(upper if upper is not None else repetition.group(1)) > 255:
                raise ValueError("Inline filename regex repetition bounds exceed 255")
            quantifiers += 1
            if closed_group and (closed_group["quantified"] or closed_group["alternative"]):
                raise ValueError("Inline filename regex cannot repeat a group with alternatives or quantifiers")
            for group in group_stack:
                group["quantified"] = True
            closed_group = None
        closed_group = None
    if quantifiers > 16 or unbounded > 1:
        raise ValueError("Inline filename regex exceeds the safe repetition limit")


def _run_inline_pipeline(source, files, media, output_dir, collision_policy, name_template, watermark_image, stdout, stderr):
    name_template = validate_output_name_template(name_template, allow_captures=True)
    capture_names = bool(output_name_capture_indices(name_template))
    results = []
    skipped = []
    for sequence, filename in enumerate(files, 1):
        fork_cuts = []
        operations, inline_watermark, pipeline_filter = _parse_pipeline_dsl(
            source, media, source_path=filename, fork_cuts=fork_cuts,
        )
        if watermark_image is not None and inline_watermark is not None:
            raise ValueError("Specify a watermark image in the inline step or with --watermark-image, not both")
        selected_watermark = watermark_image or inline_watermark
        captures = []
        if not _pipeline_filter_matches(pipeline_filter, filename, media, capture_groups=captures):
            skipped.append({"input": Path(filename).name, "state": "skipped"})
            continue
        if capture_names:
            # Validate capture context before encoding or publishing a fork.
            render_output_name(name_template, Path(filename).name, Path(filename).suffix.lstrip("."),
                               media, sequence, captures=tuple(captures))
        if fork_cuts or capture_names:
            result_code, fork_results = _run_inline_pipeline_with_forks(
                filename, operations, fork_cuts, media, output_dir, collision_policy,
                name_template, selected_watermark, stderr, sequence, tuple(captures),
            )
            if result_code != 0:
                return result_code
            results.extend(fork_results)
            continue
        workspace = None
        if operations:
            recipe_payload = json.dumps(
                [operation.model_dump(by_alias=True, mode="json") for operation in operations],
                ensure_ascii=False, separators=(",", ":"),
            )
            if len(recipe_payload.encode("utf-8")) > MAX_RECIPE_BYTES:
                raise ValueError("Inline pipeline exceeds the local recipe limit")
            workspace = tempfile.TemporaryDirectory(prefix="officekit-inline-pipeline-")
            recipe_path = Path(workspace.name) / "recipe.json"
            recipe_path.write_text(recipe_payload, encoding="utf-8")
            invocation = ["--recipe", str(recipe_path)]
        else:
            preset = {"image": "downscale-image", "video": "downscale-video", "audio": "downscale-audio"}.get(media)
            if preset is None:
                raise ValueError("Inline pipeline contains no supported transformation")
            invocation = ["--preset", preset, "--factor", "1"]
        invocation.extend(("--output-dir", output_dir, "--collision-policy", collision_policy))
        if name_template is not None:
            invocation.extend(("--name-template", name_template))
        invocation.extend(("--name-sequence", str(sequence)))
        if selected_watermark is not None:
            invocation.extend(("--watermark-image", selected_watermark))
        invocation.append(filename)
        inline_stdout = io.StringIO()
        try:
            result_code = run(invocation, inline_stdout, stderr)
        finally:
            if workspace is not None:
                workspace.cleanup()
        if result_code != 0:
            return result_code
        result = json.loads(inline_stdout.getvalue())
        if result.get("state") != "complete":
            raise ValueError("Inline pipeline did not complete safely")
        results.extend(result.get("results", []))
    response = {"state": "complete", "results": results}
    if skipped:
        response["skipped"] = skipped
    stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    return 0


def _run_inline_pipeline_with_forks(filename, operations, fork_cuts, media, output_dir,
                                    collision_policy, name_template, watermark_image, stderr, sequence=1, captures=()):
    """Run bounded inline segments, publishing fork snapshots and the final line as copies."""
    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    output_root = output_root.resolve()
    source_name = Path(filename).name
    fallback_template = "{name}-optimized.{ext}"
    segments = []
    start = 0
    for cut in fork_cuts:
        segments.append((operations[start:cut], True))
        start = cut
    segments.append((operations[start:], False))

    results = []
    current_path = None
    current_result = None
    input_bytes = None
    media_prefix = media
    with tempfile.TemporaryDirectory(prefix=".officekit-inline-pipeline-", dir=output_root) as workspace:
        workspace_path = Path(workspace)
        for segment_index, (segment_operations, publish_fork) in enumerate(segments):
            if segment_operations or current_path is None:
                recipe_path = workspace_path / f"recipe-{segment_index}.json"
                recipe_path.write_text(json.dumps(
                    [operation.model_dump(by_alias=True, mode="json") for operation in segment_operations],
                    ensure_ascii=False, separators=(",", ":"),
                ), encoding="utf-8")
                stage_dir = workspace_path / f"stage-{segment_index}"
                invocation = ["--recipe", str(recipe_path), "--output-dir", str(stage_dir),
                              "--collision-policy", "error"]
                if not segment_operations:
                    preset = {"image": "downscale-image", "video": "downscale-video", "audio": "downscale-audio"}.get(media)
                    if preset is None:
                        raise ValueError("Inline pipeline contains no supported transformation")
                    invocation = ["--preset", preset, "--factor", "1", "--output-dir", str(stage_dir)]
                if watermark_image is not None and any(
                    operation.operation_id in {"image-watermark-overlay", "video-watermark-overlay"}
                    for operation in segment_operations
                ):
                    invocation.extend(("--watermark-image", watermark_image))
                invocation.append(str(current_path) if current_path is not None else filename)
                segment_stdout = io.StringIO()
                result_code = run(invocation, segment_stdout, stderr)
                if result_code != 0:
                    return result_code, []
                segment_result = json.loads(segment_stdout.getvalue())
                if segment_result.get("state") != "complete" or len(segment_result.get("results", [])) != 1:
                    raise ValueError("Inline pipeline segment did not complete safely")
                current_result = segment_result["results"][0]
                output_name = current_result.get("output")
                if not isinstance(output_name, str) or Path(output_name).name != output_name:
                    raise ValueError("Inline pipeline segment returned an unsafe output name")
                current_path = stage_dir / output_name
                if not current_path.is_file() or current_path.is_symlink():
                    raise ValueError("Inline pipeline segment output is unavailable")
                if input_bytes is None:
                    input_bytes = current_result.get("inputBytes")

            if publish_fork:
                if current_path is None or current_result is None:
                    raise ValueError("fork() requires a completed transformation before it")
                extension = current_path.suffix.lstrip(".")
                branch_name = render_output_name(
                    f"{{name}}-fork-{len(results) + 1}.{{ext}}", source_name, extension, media_prefix,
                )
                destination = _publish_file_new(
                    output_root, branch_name, current_path, collision_policy == "suffix",
                )
                results.append({
                    "input": source_name, "output": destination.name,
                    "bytes": destination.stat().st_size,
                    "inputBytes": input_bytes,
                    "attributes": current_result.get("attributes", {}),
                })

        if current_path is None or current_result is None:
            raise ValueError("fork() pipeline must contain a supported transformation")
        extension = current_path.suffix.lstrip(".")
        final_name = render_output_name(
            name_template or fallback_template, source_name, extension, media_prefix, sequence, captures=captures,
        )
        destination = _publish_file_new(
            output_root, final_name, current_path, collision_policy == "suffix",
        )
        results.append({
            "input": source_name, "output": destination.name,
            "bytes": destination.stat().st_size,
            "inputBytes": input_bytes,
            "attributes": current_result.get("attributes", {}),
        })
    return 0, results


def _media_kind_for_files(files):
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl", ".gif"}
    video_extensions = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
    audio_extensions = {".m4a", ".wav", ".aiff", ".aif", ".mp3", ".flac", ".caf"}
    kinds = set()
    for filename in files:
        extension = Path(filename).suffix.lower()
        if extension in image_extensions:
            kinds.add("image")
        elif extension in video_extensions:
            kinds.add("video")
        elif extension == ".pdf":
            kinds.add("pdf")
        elif extension in audio_extensions:
            kinds.add("audio")
        else:
            raise ValueError("Inline pipelines require supported image, video, PDF, or audio files")
    if len(kinds) != 1:
        raise ValueError("Inline pipelines accept one media type per run")
    return kinds.pop()


def _run_pipeline_command(argv, stdout, stderr, pipeline_store=None, preset_zone_store=None):
    parser = argparse.ArgumentParser(prog="officekit-media pipeline", description="Manage local typed Media Toolkit pipelines.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List saved typed pipelines")
    show_parser = subparsers.add_parser("show", help="Show a saved pipeline's typed operations")
    show_parser.add_argument("pipeline")
    add_parser = subparsers.add_parser("add", help="Save a paused pipeline from a typed recipe or safe inline steps")
    add_parser.add_argument("name")
    add_parser.add_argument("steps", nargs="?", help="Supported inline steps, such as convert(to: webp)")
    add_parser.add_argument("--media", "--file-type", choices=("image", "video", "pdf", "audio"))
    add_parser.add_argument("--recipe", help="JSON file containing 1 to 8 typed operations")
    add_parser.add_argument("--name-template", help="Safe filename pattern using {name}/{ext}/{media} or Clop %%f/%%e/date/time tokens")
    rename_parser = subparsers.add_parser("rename", help="Rename a saved pipeline without changing its ID")
    rename_parser.add_argument("pipeline")
    rename_parser.add_argument("name")
    run_parser = subparsers.add_parser("run", help="Run a saved typed pipeline or safe inline steps on local files")
    run_parser.add_argument("pipeline", help="Saved pipeline name/ID or supported inline steps such as convert(to: webp)")
    run_parser.add_argument("files", nargs="+")
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--collision-policy", choices=("error", "suffix"), default="error")
    run_parser.add_argument("--name-template", help="Safe output name pattern; inline if(regex: ...) runs also support $1 through $99 captures; end with {ext}")
    run_parser.add_argument("--watermark-image", help="Local image used by an image watermark overlay step")
    attach_parser = subparsers.add_parser("attach", help="Pin a pipeline to an explicit clipboard or drop-zone trigger")
    attach_parser.add_argument("pipeline")
    attach_parser.add_argument("--source", choices=("clipboard", "drop-zone", "dropZone"), required=True)
    detach_parser = subparsers.add_parser("detach", help="Clear a clipboard or drop-zone pipeline pin")
    detach_parser.add_argument("--source", choices=("clipboard", "drop-zone", "dropZone"), required=True)
    prompt_parser = subparsers.add_parser("prompt", help="Print the typed pipeline operation reference")
    prompt_parser.add_argument("--compact", action="store_true", help="Emit operation IDs and option schemas without extra guidance")
    preset_parser = subparsers.add_parser("preset", help="Manage named preset-zone bindings")
    preset_commands = preset_parser.add_subparsers(dest="preset_command", required=True)
    preset_commands.add_parser("list", help="List saved preset-zone bindings")
    preset_add_parser = preset_commands.add_parser("add", help="Bind a named preset zone to a saved pipeline")
    preset_add_parser.add_argument("name")
    preset_add_parser.add_argument("pipeline", help="Saved pipeline name or ID")
    preset_rename_parser = preset_commands.add_parser("rename", help="Rename a preset zone without changing its ID")
    preset_rename_parser.add_argument("zone")
    preset_rename_parser.add_argument("name")
    preset_rebind_parser = preset_commands.add_parser("rebind", help="Bind a preset zone to another saved pipeline")
    preset_rebind_parser.add_argument("zone")
    preset_rebind_parser.add_argument("pipeline", help="Saved pipeline name or ID")
    preset_remove_parser = preset_commands.add_parser("remove", aliases=["delete"], help="Remove a preset-zone binding")
    preset_remove_parser.add_argument("zone")
    args = parser.parse_args(argv)
    store = pipeline_store or MediaPipelineStore()
    try:
        if args.command == "list":
            value = store.list()
        elif args.command == "show":
            value = _find_pipeline(store, args.pipeline)
            if value is None:
                raise ValueError("Saved pipeline is unavailable")
        elif args.command == "add":
            if bool(args.recipe) == bool(args.steps):
                raise ValueError("Provide exactly one of --recipe or inline pipeline steps")
            if args.recipe:
                if not args.media:
                    raise ValueError("--media is required with --recipe")
                operations = _read_recipe(args.recipe)
                media = args.media
            else:
                if not args.media:
                    raise ValueError("--file-type is required for inline steps so their media type is explicit")
                media = args.media
                operations, watermark_image, pipeline_filter = _parse_pipeline_dsl(args.steps, media)
                if watermark_image is not None or pipeline_filter is not None:
                    raise ValueError("Saved pipelines cannot retain a local watermark file or inline filter; use pipeline run")
            definition = MediaPipelineCreate.model_validate({
                "name": args.name,
                "media": media,
                "operations": [operation.model_dump(by_alias=True, mode="json") for operation in operations],
                "outputNameTemplate": args.name_template,
            })
            value = store.create(definition)
        elif args.command == "rename":
            target = _find_pipeline(store, args.pipeline)
            if target is None:
                raise ValueError("Saved pipeline is unavailable")
            value = store.rename(target["id"], MediaPipelineRename.model_validate({"name": args.name}))
        elif args.command == "run":
            if len(args.files) > MAX_FILES:
                raise ValueError("Choose no more than 30 files")
            target = _find_pipeline(store, args.pipeline)
            if target is None:
                media = _media_kind_for_files(args.files)
                return _run_inline_pipeline(
                    args.pipeline, args.files, media, args.output_dir, args.collision_policy,
                    args.name_template, args.watermark_image, stdout, stderr,
                )
            recipe_payload = json.dumps(target["operations"], ensure_ascii=False, separators=(",", ":"))
            if len(recipe_payload.encode("utf-8")) > MAX_RECIPE_BYTES:
                raise ValueError("Saved pipeline exceeds the local recipe limit")
            with tempfile.TemporaryDirectory(prefix="officekit-media-pipeline-") as workspace:
                recipe_path = Path(workspace) / "recipe.json"
                recipe_path.write_text(recipe_payload, encoding="utf-8")
                invocation = ["--recipe", str(recipe_path), "--output-dir", args.output_dir,
                              "--collision-policy", args.collision_policy]
                name_template = args.name_template if args.name_template is not None else target.get("outputNameTemplate")
                if name_template is not None:
                    invocation.extend(("--name-template", name_template))
                if args.watermark_image is not None:
                    invocation.extend(("--watermark-image", args.watermark_image))
                invocation.extend(args.files)
                return run(invocation, stdout, stderr)
        elif args.command == "attach":
            target = _find_pipeline(store, args.pipeline)
            if target is None:
                raise ValueError("Saved pipeline is unavailable")
            trigger = "drop-zone" if args.source == "dropZone" else args.source
            trigger_store = MediaPipelineTriggerStore(store)
            value = trigger_store.set(trigger, MediaPipelineTriggerBinding.model_validate({"pipelineId": target["id"]}))
        elif args.command == "detach":
            trigger = "drop-zone" if args.source == "dropZone" else args.source
            value = {"trigger": trigger, "cleared": MediaPipelineTriggerStore(store).clear(trigger)}
        elif args.command == "preset":
            zones = preset_zone_store or MediaPresetZoneStore(store)
            if args.preset_command == "list":
                value = zones.list_bindings()
            elif args.preset_command == "add":
                pipeline = _find_pipeline(store, args.pipeline)
                if pipeline is None:
                    raise ValueError("Saved pipeline is unavailable")
                value = zones.create(MediaPresetZoneCreate.model_validate({
                    "name": args.name, "pipelineId": pipeline["id"],
                }))
            else:
                zone = _find_preset_zone(zones, args.zone)
                if zone is None:
                    raise ValueError("Preset zone is unavailable")
                if args.preset_command == "rename":
                    value = zones.rename(zone["id"], MediaPresetZoneRename.model_validate({"name": args.name}))
                elif args.preset_command == "rebind":
                    pipeline = _find_pipeline(store, args.pipeline)
                    if pipeline is None:
                        raise ValueError("Saved pipeline is unavailable")
                    value = zones.rebind(zone["id"], MediaPresetZoneRebind.model_validate({
                        "pipelineId": pipeline["id"],
                    }))
                elif zones.delete(zone["id"]):
                    value = {"id": zone["id"], "state": "deleted"}
                else:
                    raise ValueError("Preset zone is unavailable")
        else:
            operations = {operation_id: model.model_json_schema(by_alias=True) for operation_id, model in OPERATION_OPTIONS.items()}
            value = {
                "safety": "Typed, local transforms only. Recipes cannot execute scripts, shell commands, URLs, or file actions.",
                "operations": operations,
            }
            if args.compact:
                value = {"operationIds": list(operations), "safety": value["safety"]}
        stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
        return 0
    except (OSError, ValueError, ValidationError, OverflowError, MediaPipelineStoreError,
            MediaPipelineTriggerStoreError, MediaPresetZoneStoreError) as error:
        stderr.write(f"officekit-media: {str(error) or 'pipeline command failed'}\n")
        return 2


def _run_verb_command(verb, argv, stdout, stderr):
    """Expose Clop-inspired verbs over OfficeKit's existing typed operation contract."""
    parser = argparse.ArgumentParser(
        prog=f"officekit-media {verb}",
        description="Run an allowlisted typed operation and publish a separate local copy.",
    )
    parser.add_argument("--operation-id", help="Typed Media Toolkit operation ID (required for convert and crop)")
    parser.add_argument("--options-json", help="Validated JSON options for --operation-id")
    parser.add_argument("--factor", type=float, help="Downscale factor from greater than 0 through 1")
    parser.add_argument("--compression", help="Image/video factor 5 (highest quality) through 100 (smallest output); images also accept adaptive")
    parser.add_argument("--adaptive-optimisation", "--adaptive-optimization", action="store_true", help="Choose an image format based on image detail; may change the output extension")
    parser.add_argument("--aspect-ratio", help="For crop, crop images or videos to a centered width:height ratio")
    parser.add_argument("--smart-crop", action="store_true", help="Use on-device Vision saliency to choose the crop region")
    parser.add_argument("--remove-audio", action="store_true", help="For video optimisation, remove the audio track in the prepared copy")
    parser.add_argument("--output-dir", required=True, help="Directory for new prepared copies")
    parser.add_argument("--collision-policy", choices=("error", "suffix"), default="error")
    parser.add_argument("--name-template", help="Safe filename pattern using {name}/{ext}/{media} or Clop %%f/%%e/date/time tokens")
    parser.add_argument("files", nargs="+", help="One to 30 local media files")
    args = parser.parse_args(argv)
    if len(args.files) > MAX_FILES:
        parser.error("choose no more than 30 files")
    if args.options_json is not None and len(args.options_json.encode("utf-8")) > MAX_RECIPE_BYTES:
        stderr.write("officekit-media: --options-json exceeds the 16 KiB recipe limit\n")
        return 2
    if args.remove_audio and verb not in {"optimise", "optimize"}:
        stderr.write("officekit-media: --remove-audio is available only with optimise\n")
        return 2
    if args.compression is not None and (verb not in {"optimise", "optimize"} or args.operation_id is not None):
        stderr.write("officekit-media: --compression is available only with optimise without --operation-id\n")
        return 2
    if args.adaptive_optimisation and (verb not in {"optimise", "optimize"} or args.operation_id is not None):
        stderr.write("officekit-media: --adaptive-optimisation is available only with optimise without --operation-id\n")
        return 2

    if args.aspect_ratio is not None and (verb != "crop" or args.operation_id is not None):
        stderr.write("officekit-media: --aspect-ratio requires crop without --operation-id\n")
        return 2
    if args.smart_crop and (verb != "crop" or args.operation_id is not None or args.aspect_ratio is None):
        stderr.write("officekit-media: --smart-crop requires crop with --aspect-ratio and no --operation-id\n")
        return 2

    if verb in {"optimise", "optimize"} and args.operation_id is None:
        if args.options_json is not None or args.factor is not None:
            stderr.write("officekit-media: --options-json and --factor require --operation-id for optimise\n")
            return 2
        if args.adaptive_optimisation:
            image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl"}
            extensions = {Path(filename).suffix.lower() for filename in args.files}
            if args.remove_audio or not extensions or not extensions <= image_extensions:
                stderr.write("officekit-media: --adaptive-optimisation requires image files only\n")
                return 2
            recipe = [{"operationId": "image-optimize", "options": {"adaptive": True}}]
            return _run_verb_recipe(args, recipe, stdout, stderr)
        if args.compression is not None:
            image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl"}
            video_extensions = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
            audio_extensions = {".m4a", ".wav", ".aiff", ".aif", ".mp3", ".flac", ".caf"}
            extensions = {Path(filename).suffix.lower() for filename in args.files}
            adaptive = args.compression.casefold() == "adaptive"
            if adaptive:
                if args.remove_audio or not extensions:
                    stderr.write("officekit-media: adaptive compression requires one homogeneous media batch\n")
                    return 2
                if extensions <= image_extensions:
                    recipe = [{"operationId": "image-optimize", "options": {"compression": "adaptive"}}]
                elif extensions <= video_extensions:
                    recipe = [{"operationId": "video-optimize", "options": {"targetFormat": "mp4", "compression": "adaptive"}}]
                elif extensions <= audio_extensions:
                    recipe = [{"operationId": "audio-optimize", "options": {"targetFormat": "m4a", "compression": "adaptive"}}]
                else:
                    stderr.write("officekit-media: adaptive compression requires image, video, or audio files only\n")
                    return 2
                return _run_verb_recipe(args, recipe, stdout, stderr)
            try:
                compression = int(args.compression)
            except ValueError:
                compression = 0
            if not 5 <= compression <= 100:
                stderr.write("officekit-media: --compression must be adaptive or an integer from 5 to 100\n")
                return 2
            if extensions and extensions <= video_extensions:
                recipe = [{"operationId": "video-optimize", "options": {"targetFormat": "mp4", "compression": compression}}]
            elif extensions and extensions <= image_extensions:
                recipe = [{"operationId": "image-optimize", "options": {"compression": compression}}]
            elif extensions and extensions <= audio_extensions:
                recipe = [{"operationId": "audio-optimize", "options": {"targetFormat": "m4a", "compression": compression}}]
            else:
                stderr.write("officekit-media: --compression accepts a homogeneous image, video, or audio batch\n")
                return 2
            if args.remove_audio:
                if not extensions <= video_extensions:
                    stderr.write("officekit-media: --remove-audio requires video files only\n")
                    return 2
                recipe.append({"operationId": "video-mute", "options": {}})
            return _run_verb_recipe(args, recipe, stdout, stderr)
        if args.remove_audio:
            video_extensions = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
            if any(Path(filename).suffix.lower() not in video_extensions for filename in args.files):
                stderr.write("officekit-media: --remove-audio requires video files only\n")
                return 2
            return _run_verb_recipe(args, [
                {"operationId": "video-optimize", "options": {"targetFormat": "m4v", "quality": "balanced"}},
                {"operationId": "video-mute", "options": {}},
            ], stdout, stderr)
        invocation = ["--preset", "optimize-media"]
    elif verb == "downscale" and args.operation_id is None:
        if args.options_json is not None or args.factor is None:
            stderr.write("officekit-media: downscale requires --factor\n")
            return 2
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl", ".gif"}
        video_extensions = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
        audio_extensions = {".m4a", ".wav", ".aiff", ".aif", ".mp3", ".flac", ".caf"}
        extensions = {Path(filename).suffix.lower() for filename in args.files}
        if extensions and extensions <= image_extensions:
            preset = "downscale-image"
        elif extensions and extensions <= video_extensions:
            preset = "downscale-video"
        elif extensions and extensions <= audio_extensions:
            preset = "downscale-audio"
        else:
            stderr.write("officekit-media: factor downscale accepts one supported media kind per batch\n")
            return 2
        invocation = ["--preset", preset, "--factor", str(args.factor)]
    elif verb == "crop" and args.operation_id is None:
        if args.options_json is not None or args.factor is not None or args.aspect_ratio is None:
            stderr.write("officekit-media: crop without --operation-id requires --aspect-ratio\n")
            return 2
        try:
            _parse_crop_aspect_ratio(args.aspect_ratio)
        except ValueError as error:
            stderr.write(f"officekit-media: {error}\n")
            return 2
        invocation = ["--preset", "crop-aspect", "--aspect-ratio", args.aspect_ratio]
        if args.smart_crop:
            invocation.append("--smart-crop")
    elif verb == "strip-exif" and args.operation_id is None:
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".jxl"}
        video_extensions = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
        if args.options_json is not None or args.factor is not None:
            stderr.write("officekit-media: strip-exif does not accept operation options or a factor\n")
            return 2
        extensions = {Path(filename).suffix.lower() for filename in args.files}
        if extensions and extensions <= image_extensions:
            operation_id = "image-strip-metadata"
        elif extensions and extensions <= video_extensions:
            operation_id = "video-strip-metadata"
        else:
            stderr.write("officekit-media: strip-exif accepts either supported images or supported videos in one batch\n")
            return 2
        recipe = [{"operationId": operation_id, "options": {}}]
        return _run_verb_recipe(args, recipe, stdout, stderr)
    else:
        if args.compression is not None:
            stderr.write("officekit-media: --compression is available only with optimise without --operation-id\n")
            return 2
        allowed = {
            "optimise": {"image-optimize", "video-optimize", "pdf-lossless-compress", "pdf-visual-optimize", "audio-optimize"},
            "optimize": {"image-optimize", "video-optimize", "pdf-lossless-compress", "pdf-visual-optimize", "audio-optimize"},
            "convert": {"image-convert", "video-hevc-convert", "video-optimize", "video-to-gif", "audio-convert"},
            "crop": {"image-crop", "video-crop", "pdf-crop"},
            "downscale": {"image-resize", "video-resize", "audio-optimize"},
            "strip-exif": {"image-strip-metadata", "video-strip-metadata"},
        }[verb]
        if args.operation_id not in allowed:
            stderr.write(f"officekit-media: {verb} requires a supported --operation-id from: {', '.join(sorted(allowed))}\n")
            return 2
        if args.factor is not None:
            stderr.write("officekit-media: --factor is available only with downscale without --operation-id\n")
            return 2
        if args.remove_audio and args.operation_id != "video-optimize":
            stderr.write("officekit-media: --remove-audio requires video-optimize\n")
            return 2
        try:
            options = json.loads(args.options_json) if args.options_json is not None else {}
        except (json.JSONDecodeError, RecursionError):
            stderr.write("officekit-media: --options-json must contain a JSON object\n")
            return 2
        if not isinstance(options, dict):
            stderr.write("officekit-media: --options-json must contain a JSON object\n")
            return 2
        if args.remove_audio:
            return _run_verb_recipe(args, [
                {"operationId": args.operation_id, "options": options},
                {"operationId": "video-mute", "options": {}},
            ], stdout, stderr)
        return _run_verb_recipe(args, [{"operationId": args.operation_id, "options": options}], stdout, stderr)

    invocation.extend(("--output-dir", args.output_dir, "--collision-policy", args.collision_policy))
    if args.name_template is not None:
        invocation.extend(("--name-template", args.name_template))
    invocation.extend(args.files)
    return run(invocation, stdout, stderr)


def _run_verb_recipe(args, recipe, stdout, stderr):
    with tempfile.TemporaryDirectory(prefix="officekit-media-verb-") as workspace:
        recipe_path = Path(workspace) / "recipe.json"
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        invocation = ["--recipe", str(recipe_path), "--output-dir", args.output_dir,
                      "--collision-policy", args.collision_policy]
        if args.name_template is not None:
            invocation.extend(("--name-template", args.name_template))
        invocation.extend(args.files)
        return run(invocation, stdout, stderr)


def _read_recipe(path):
    with open(path, "rb") as recipe_file:
        raw = recipe_file.read(MAX_RECIPE_BYTES + 1)
    if len(raw) > MAX_RECIPE_BYTES:
        raise ValueError("Recipe exceeds the 16 KiB limit")
    value = json.loads(raw)
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("Recipe must be a JSON array of 1 to 8 operations")
    return [MediaOperation.model_validate(item) for item in value]


def _read_input(path, maximum_bytes=MediaOptimizerEngine.MAX_INPUT_BYTES, label="Input", include_stat=False):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > maximum_bytes:
            raise ValueError(f"{label} must be a regular file between 1 byte and {maximum_bytes // (1024 * 1024)} MiB")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            data = source.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
        if len(data) != info.st_size or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ):
            raise ValueError("Input changed while it was being read")
        return (data, info) if include_stat else data
    finally:
        os.close(descriptor)


def _pipeline_media_dimensions(media, source_path):
    source_data = _read_input(source_path)
    if media == "image":
        _format, width, height, frame_count = MediaOptimizerEngine._image_info(source_data)
        if frame_count != 1:
            raise ValueError("Inline geometry steps accept single-frame images only")
        return width, height
    if media == "video":
        with tempfile.TemporaryDirectory(prefix="officekit-inline-dimensions-") as workspace:
            staged_source = Path(workspace) / f"source.{_safe_extension(Path(source_path).name)}"
            staged_source.write_bytes(source_data)
            try:
                return probe_video_dimensions(staged_source)
            except NativeMediaUnavailableError as error:
                raise MediaOperationUnavailableError("Video geometry is not available in this build.") from error
    raise ValueError("Inline geometry steps are available only for image and video files")


def _resized_dimensions(width, height, max_width, max_height):
    scale = min(1.0, max_width / width, max_height / height)
    return min(max_width, max(1, round(width * scale))), min(max_height, max(1, round(height * scale)))


def _candidate_name(name, attempt):
    if attempt == 0:
        return name
    stem, extension = os.path.splitext(name)
    return f"{stem} ({attempt + 1}){extension}"


def _publish_new(directory, name, data, suffix_collisions=False):
    directory.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".officekit-media-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Hard-link publication is atomic and never replaces an existing file.
        for attempt in range(100 if suffix_collisions else 1):
            destination = directory / _candidate_name(name, attempt)
            try:
                os.link(temp_name, destination, follow_symlinks=False)
                break
            except FileExistsError:
                if not suffix_collisions or attempt == 99:
                    raise
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return destination


def _screenshot_output_directory(root, modified_time):
    directory = root.resolve()
    for component in datetime.fromtimestamp(modified_time).strftime("%y/%m").split("/"):
        directory = directory / component
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError("Screenshot sort destination contains an unsafe path component")
    return directory


def _collect_pdf_inputs(files, recursive, excluded_output):
    collected = []
    seen_files = set()
    seen_directories = set()
    scanned = 0
    output_root = Path(excluded_output).resolve()

    def is_output_directory(path):
        resolved = path.resolve()
        return resolved == output_root or output_root in resolved.parents

    def add_file(path, info):
        if path.suffix.casefold() != ".pdf":
            return
        identity = (info.st_dev, info.st_ino)
        if identity in seen_files:
            return
        seen_files.add(identity)
        collected.append(str(path))
        if len(collected) > MAX_FILES:
            raise ValueError(f"Recursive PDF input is limited to {MAX_FILES} files")

    for file_name in files:
        root = Path(file_name).expanduser()
        info = root.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Symbolic links are not accepted as recursive PDF inputs")
        if stat.S_ISREG(info.st_mode):
            add_file(root, info)
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("PDF inputs must be regular files or folders")
        if not recursive:
            raise ValueError("Folder inputs require --recursive")
        pending = [root]
        while pending:
            folder = pending.pop()
            if is_output_directory(folder):
                continue
            folder_info = folder.lstat()
            if stat.S_ISLNK(folder_info.st_mode) or not stat.S_ISDIR(folder_info.st_mode):
                continue
            directory_identity = (folder_info.st_dev, folder_info.st_ino)
            if directory_identity in seen_directories:
                continue
            seen_directories.add(directory_identity)
            with os.scandir(folder) as entries:
                ordered_entries = sorted(entries, key=lambda entry: (entry.name.casefold(), entry.name))
            children = []
            for entry in ordered_entries:
                scanned += 1
                if scanned > MAX_DIRECTORY_ENTRIES:
                    raise ValueError(f"Recursive PDF scan is limited to {MAX_DIRECTORY_ENTRIES} directory entries")
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    children.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    add_file(Path(entry.path), entry.stat(follow_symlinks=False))
            pending.extend(reversed(children))
    if not collected:
        raise ValueError("No PDF files were found in the selected inputs")
    return collected


def _copy_input_to_file(path, destination):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > MediaOptimizerEngine.MAX_INPUT_BYTES:
            raise ValueError("Input must be a regular file between 1 byte and 64 MiB")
        copied = 0
        with os.fdopen(descriptor, "rb", closefd=False) as source, open(destination, "xb") as output:
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > MediaOptimizerEngine.MAX_INPUT_BYTES:
                    raise ValueError("Input exceeds the 64 MiB limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(descriptor)
        if copied != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("Input changed while it was being read")
        return copied
    finally:
        os.close(descriptor)


def _publish_file_new(directory, name, source, suffix_collisions=False):
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(100 if suffix_collisions else 1):
        destination = directory / _candidate_name(name, attempt)
        try:
            os.link(source, destination, follow_symlinks=False)
            return destination
        except FileExistsError:
            if not suffix_collisions or attempt == 99:
                raise


def _native_recipe_kind(operations):
    kinds = {operation.operation_id.split("-", 1)[0] for operation in operations}
    if not kinds.intersection({"audio", "video"}):
        return None
    if len(kinds) != 1 or not kinds <= {"audio", "video"}:
        raise ValueError("Native audio/video operations in a recipe must use one media kind")
    return next(iter(kinds))


def _preset_operations(preset, filename, *, factor=None, image_dimensions=None, video_dimensions=None, audio_bitrate_kbps=None):
    if preset == "downscale-image":
        extension = Path(filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl", ".gif"}:
            raise ValueError("The downscale-image preset accepts supported image files only")
        if type(factor) not in {int, float} or not math.isfinite(factor) or not 0 < factor <= 1:
            raise ValueError("The downscale factor must be greater than 0 and no more than 1")
        if not isinstance(image_dimensions, tuple) or len(image_dimensions) != 2:
            raise ValueError("Image dimensions are required to calculate a downscale")
        width, height = image_dimensions
        if type(width) is not int or type(height) is not int or width < 1 or height < 1:
            raise ValueError("Image dimensions are invalid")
        if factor == 1:
            return []
        return [MediaOperation.model_validate({"operationId": "image-resize", "options": {
            "maxWidth": max(1, math.floor(width * factor)),
            "maxHeight": max(1, math.floor(height * factor)),
        }})]
    if preset == "downscale-video":
        extension = Path(filename).suffix.lower()
        if extension not in {".mov", ".mp4", ".m4v", ".mkv", ".webm"}:
            raise ValueError("The downscale-video preset accepts supported video files only")
        if type(factor) not in {int, float} or not math.isfinite(factor) or not 0 < factor <= 1:
            raise ValueError("The downscale factor must be greater than 0 and no more than 1")
        if not isinstance(video_dimensions, tuple) or len(video_dimensions) != 2:
            raise ValueError("Video dimensions are required to calculate a downscale")
        width, height = video_dimensions
        if type(width) is not int or type(height) is not int or width < 1 or height < 1:
            raise ValueError("Video dimensions are invalid")
        if factor == 1:
            return []
        return [MediaOperation.model_validate({"operationId": "video-resize", "options": {
            "maxWidth": max(1, math.floor(width * factor)),
            "maxHeight": max(1, math.floor(height * factor)),
        }})]
    if preset == "downscale-audio":
        if Path(filename).suffix.lower() not in {".m4a", ".wav", ".aiff", ".aif", ".mp3", ".flac", ".caf"}:
            raise ValueError("The downscale-audio preset accepts supported audio files only")
        if type(factor) not in {int, float} or not math.isfinite(factor) or not 0 < factor <= 1:
            raise ValueError("The downscale factor must be greater than 0 and no more than 1")
        if factor == 1:
            return []
        if type(audio_bitrate_kbps) not in {int, float} or not math.isfinite(audio_bitrate_kbps) or audio_bitrate_kbps <= 0:
            raise ValueError("Audio bitrate is required to calculate a downscale")
        bitrate = min(640, max(32, round(audio_bitrate_kbps * factor)))
        return [MediaOperation.model_validate({"operationId": "audio-optimize", "options": {
            "targetFormat": "m4a", "bitrateKbps": bitrate,
        }})]
    extension = Path(filename).suffix.lower()
    if preset == "optimize-image":
        return [MediaOperation.model_validate({"operationId": "image-optimize", "options": {}})]
    if preset == "uncrop-pdf":
        if extension != ".pdf":
            raise ValueError("The uncrop-pdf preset accepts PDF files only")
        return [MediaOperation.model_validate({"operationId": "pdf-uncrop", "options": {}})]
    if preset == "sort-screenshots":
        screenshot_name = Path(filename).stem.casefold()
        is_screenshot = screenshot_name.startswith(("screenshot", "screen shot", "cleanshot"))
        if not is_screenshot or extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("The sort-screenshots preset accepts screenshot or CleanShot JPEG, PNG, or WebP files only")
        return [MediaOperation.model_validate({"operationId": "image-optimize", "options": {}})]
    if preset == "to-webp":
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}:
            raise ValueError("The to-webp preset supports common image formats only")
        return [MediaOperation.model_validate({"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 90}})]
    if preset == "audio-to-mp3":
        if extension not in {".wav", ".aif", ".aiff", ".m4a", ".flac", ".mp3"}:
            raise ValueError("The audio-to-mp3 preset accepts supported audio files only")
        return [MediaOperation.model_validate({"operationId": "audio-convert", "options": {"targetFormat": "mp3", "bitrateKbps": 192}})]
    if preset == "video-to-gif":
        if extension not in {".mov", ".mp4", ".m4v"}:
            raise ValueError("The video-to-gif preset accepts supported video files only")
        return [MediaOperation.model_validate({"operationId": "video-to-gif", "options": {}})]
    if preset == "video-2x-silent":
        if extension not in {".mov", ".mp4", ".m4v"}:
            raise ValueError("The video-2x-silent preset accepts supported video files only")
        return [
            MediaOperation.model_validate({"operationId": "video-speed", "options": {"factorPercent": 200}}),
            MediaOperation.model_validate({"operationId": "video-mute", "options": {}}),
        ]
    if preset != "optimize-media":
        raise ValueError("Unknown built-in preparation preset")
    if extension in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        recipe = {"operationId": "image-optimize", "options": {}}
    elif extension in {".bmp", ".tif", ".tiff"}:
        recipe = {"operationId": "image-convert", "options": {"targetFormat": "webp", "quality": 90}}
    elif extension in {".mov", ".mp4", ".m4v"}:
        recipe = {"operationId": "video-optimize", "options": {"targetFormat": "m4v", "quality": "balanced"}}
    elif extension == ".pdf":
        recipe = {"operationId": "pdf-lossless-compress", "options": {"profile": "balanced"}}
    elif extension in {".wav", ".aif", ".aiff", ".m4a", ".flac", ".mp3"}:
        target_format = "mp3" if extension == ".wav" else "m4a"
        recipe = {"operationId": "audio-convert", "options": {"targetFormat": target_format, "bitrateKbps": 192}}
    else:
        raise ValueError("The optimize-media preset supports common image, video, PDF, and audio formats only")
    return [MediaOperation.model_validate(recipe)]


def run(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "pipeline":
        return _run_pipeline_command(argv[1:], stdout, stderr)
    if argv and argv[0] == "settings":
        return _run_settings_command(argv[1:], stdout, stderr)
    if argv and argv[0] in {"optimise", "optimize", "convert", "crop", "downscale", "strip-exif"}:
        return _run_verb_command(argv[0], argv[1:], stdout, stderr)
    parser = argparse.ArgumentParser(
        prog="officekit-media",
        description="Run typed local media operations. Commands: optimise, convert, crop, downscale, strip-exif, pipeline.",
        epilog="Verb commands publish new copies into --output-dir; convert and crop use --operation-id with --options-json.",
    )
    recipe_args = parser.add_mutually_exclusive_group(required=True)
    recipe_args.add_argument("--recipe", help="JSON array of typed Media Toolkit operations")
    recipe_args.add_argument("--preset", choices=("optimize-image", "optimize-media", "to-webp", "downscale-image", "downscale-video", "downscale-audio", "crop-aspect", "sort-screenshots", "audio-to-mp3", "video-to-gif", "video-2x-silent", "crop-pdf", "uncrop-pdf"), help="Use a built-in typed preparation preset")
    recipe_args.add_argument("--settings", choices=("schema", "list", "get", "set", "clear"), help="Inspect or update shared typed operation defaults")
    parser.add_argument("--operation-id", help="Operation ID for --settings get, set, or clear")
    parser.add_argument("--options-json", help="Validated JSON options for --settings set")
    parser.add_argument("--factor", type=float, help="Scale image/video dimensions or audio bitrate by a factor from greater than 0 through 1")
    parser.add_argument("--output-dir", help="New output directory; existing files are never replaced")
    parser.add_argument("--collision-policy", choices=("error", "suffix"), default="error", help="On collision, either fail (default) or select the next unused numbered name")
    parser.add_argument("--watermark-image", help="Local PNG, JPEG, or WebP logo for image or video watermark overlay (up to 5 MiB)")
    parser.add_argument("--name-template", help="Safe filename pattern using {name}/{ext}/{media} or Clop %%f/%%e/date/time tokens")
    parser.add_argument("--name-sequence", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--smart-crop", action="store_true", help="For crop-aspect, use on-device Vision saliency")
    crop_target = parser.add_mutually_exclusive_group()
    crop_target.add_argument("--aspect-ratio", help="For crop-aspect, crop images/videos to a centered ratio; for crop-pdf, crop PDF pages")
    crop_target.add_argument("--for-device", help="For --preset crop-pdf, crop PDF pages to fill a supported device screen")
    crop_target.add_argument("--paper-size", help="For --preset crop-pdf, crop PDF pages to a supported paper size (for example A4 or Letter)")
    listings = parser.add_mutually_exclusive_group()
    listings.add_argument("--list-devices", action="store_true", help="List device names supported by --for-device")
    listings.add_argument("--list-paper-sizes", action="store_true", help="List paper sizes supported by --paper-size")
    parser.add_argument("--extend", action="store_true", help="Extend PDF page bounds instead of clipping source content")
    parser.add_argument("--page-layout", choices=("auto", "portrait", "landscape"), default="auto", help="Target layout for PDF crop (default: follow each page)")
    parser.add_argument("-r", "--recursive", action="store_true", help="For PDF crop, scan selected folders recursively; symlinks are skipped")
    parser.add_argument("files", nargs="*", help="One to 30 local media files")
    args = parser.parse_args(argv)
    if not args.settings and (args.operation_id or args.options_json is not None):
        parser.error("--operation-id and --options-json require --settings")
    if args.settings:
        try:
            if args.factor is not None or args.output_dir or args.watermark_image or args.name_template or args.smart_crop or args.files or args.aspect_ratio or args.for_device or args.paper_size or args.extend or args.recursive or args.list_devices or args.list_paper_sizes or args.page_layout != "auto":
                raise ValueError("Settings commands do not accept media files or preparation options")
            if args.settings not in {"get", "set", "clear"} and (args.operation_id or args.options_json is not None):
                raise ValueError("--operation-id and --options-json are available only with settings get, set, or clear")
            if args.settings in {"get", "clear"} and args.options_json is not None:
                raise ValueError("--options-json is available only with --settings set")
            return _run_settings(args, stdout)
        except (OSError, ValueError, ValidationError, MediaOperationDefaultsStoreError) as error:
            stderr.write(f"officekit-media: {str(error) or 'settings operation failed'}\n")
            return 2
    if args.list_devices or args.list_paper_sizes:
        if args.preset != "crop-pdf":
            parser.error("device and paper-size listings require --preset crop-pdf")
        if args.files or args.output_dir or args.extend or args.recursive or args.aspect_ratio or args.smart_crop or args.for_device or args.paper_size or args.page_layout != "auto":
            parser.error("listing options do not accept crop settings, files, or --output-dir")
        listing = {"devices": supported_devices()} if args.list_devices else {"paperSizes": supported_paper_sizes()}
        stdout.write(json.dumps(listing, separators=(",", ":")) + "\n")
        return 0
    if not args.files:
        parser.error("choose one to 30 local media files")
    if not args.output_dir:
        parser.error("--output-dir is required")
    if len(args.files) > MAX_FILES:
        parser.error("choose no more than 30 files")
    try:
        if not 1 <= args.name_sequence <= 10_000:
            raise ValueError("--name-sequence must be between 1 and 10000")
        crop_arguments = args.aspect_ratio or args.smart_crop or args.for_device or args.paper_size or args.extend or args.page_layout != "auto"
        if args.factor is not None and args.preset not in {"downscale-image", "downscale-video", "downscale-audio"}:
            raise ValueError("--factor is available only with a downscale preset")
        if args.preset in {"downscale-image", "downscale-video", "downscale-audio"} and args.factor is None:
            raise ValueError(f"--preset {args.preset} requires --factor")
        if args.factor is not None and (not math.isfinite(args.factor) or not 0 < args.factor <= 1):
            raise ValueError("The downscale factor must be greater than 0 and no more than 1")
        if crop_arguments and args.preset not in {"crop-pdf", "crop-aspect"}:
            raise ValueError("Crop settings are available only with --preset crop-pdf or crop-aspect")
        if args.recursive and args.preset != "crop-pdf":
            raise ValueError("--recursive is available only with --preset crop-pdf")
        if args.smart_crop and args.preset != "crop-aspect":
            raise ValueError("--smart-crop is available only with --preset crop-aspect")
        if args.preset == "crop-aspect":
            if not args.aspect_ratio or args.for_device or args.paper_size or args.extend or args.page_layout != "auto":
                raise ValueError("--preset crop-aspect requires --aspect-ratio and accepts optional --smart-crop")
            _parse_crop_aspect_ratio(args.aspect_ratio)
            recipe_operations = None
        elif args.preset == "crop-pdf":
            if not (args.aspect_ratio or args.for_device or args.paper_size):
                raise ValueError("--preset crop-pdf requires --aspect-ratio, --for-device, or --paper-size")
            aspect_ratio = (
                resolve_device_aspect(args.for_device) if args.for_device else
                resolve_paper_aspect(args.paper_size) if args.paper_size else args.aspect_ratio
            )
            recipe_operations = [MediaOperation.model_validate({"operationId": "pdf-crop", "options": {
                "aspectRatio": aspect_ratio, "pageLayout": args.page_layout, "extend": args.extend,
            }})]
        else:
            recipe_operations = None if args.preset else _read_recipe(args.recipe)
        name_template = validate_output_name_template(args.name_template)
        uses_watermark_overlay = bool(recipe_operations) and any(
            operation.operation_id in {"image-watermark-overlay", "video-watermark-overlay"}
            for operation in recipe_operations
        )
        if uses_watermark_overlay != (args.watermark_image is not None):
            raise ValueError("Provide --watermark-image exactly when the recipe uses a watermark overlay operation")
        if uses_watermark_overlay and any(
            operation.operation_id.split("-", 1)[0] != recipe_operations[0].operation_id.split("-", 1)[0]
            for operation in recipe_operations
        ):
            raise ValueError("Watermark overlays can be combined only with operations for the same media type")
        watermark_image = _read_input(args.watermark_image, MAX_WATERMARK_BYTES, "Watermark image") if uses_watermark_overlay else None
        if watermark_image is not None:
            mark_format, _width, _height, frames = MediaOptimizerEngine._image_info(watermark_image)
            if mark_format not in {"PNG", "JPEG", "WEBP"} or frames != 1:
                raise ValueError("Watermark image must be a single PNG, JPEG, or WebP image")
        output_dir = Path(args.output_dir).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("Output path must be a directory")
        output_root = output_dir.resolve()
        input_files = _collect_pdf_inputs(args.files, args.recursive, output_root) if args.preset == "crop-pdf" else args.files
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for sequence, file_name in enumerate(input_files, args.name_sequence):
            source_path = Path(file_name).expanduser()
            source_data = None
            if args.preset == "downscale-image":
                source_data = _read_input(source_path)
                _image_format, source_width, source_height, _frames = MediaOptimizerEngine._image_info(source_data)
                operations = _preset_operations(
                    args.preset, source_path.name, factor=args.factor,
                    image_dimensions=(source_width, source_height),
                )
            elif args.preset == "downscale-video":
                source_data = _read_input(source_path)
                if args.factor == 1:
                    operations = []
                else:
                    with tempfile.TemporaryDirectory(prefix="officekit-video-downscale-") as workspace:
                        staged_source = Path(workspace) / f"source.{_safe_extension(source_path.name)}"
                        staged_source.write_bytes(source_data)
                        try:
                            video_dimensions = probe_video_dimensions(staged_source)
                        except NativeMediaUnavailableError as error:
                            raise MediaOperationUnavailableError(
                                "Video downscaling is not available in this build."
                            ) from error
                    operations = _preset_operations(
                        args.preset, source_path.name, factor=args.factor,
                        video_dimensions=video_dimensions,
                    )
            elif args.preset == "downscale-audio":
                if args.factor == 1:
                    operations = _preset_operations(args.preset, source_path.name, factor=args.factor)
                else:
                    source_data = _read_input(source_path)
                    try:
                        with tempfile.TemporaryDirectory(prefix="officekit-audio-downscale-") as workspace:
                            staged_source = Path(workspace) / f"source.{_safe_extension(source_path.name)}"
                            staged_source.write_bytes(source_data)
                            duration = probe_audio_duration(staged_source)
                    except NativeMediaUnavailableError as error:
                        raise MediaOperationUnavailableError("Audio downscaling is not available in this build.") from error
                    average_bitrate_kbps = len(source_data) * 8 / duration / 1000
                    operations = _preset_operations(
                        args.preset, source_path.name, factor=args.factor,
                        audio_bitrate_kbps=average_bitrate_kbps,
                    )
            elif args.preset == "crop-aspect":
                extension = source_path.suffix.lower()
                source_data = _read_input(source_path)
                if extension in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jxl"}:
                    _image_format, source_width, source_height, frame_count = MediaOptimizerEngine._image_info(source_data)
                    if frame_count != 1:
                        raise ValueError("Aspect-ratio crop accepts single-frame images only")
                    operation_id = "image-crop"
                    smart_kind = "image"
                elif extension in {".mov", ".mp4", ".m4v", ".mkv", ".webm"}:
                    try:
                        with tempfile.TemporaryDirectory(prefix="officekit-video-crop-") as workspace:
                            staged_source = Path(workspace) / f"source.{_safe_extension(source_path.name)}"
                            staged_source.write_bytes(source_data)
                            source_width, source_height = probe_video_dimensions(staged_source)
                    except NativeMediaUnavailableError as error:
                        raise MediaOperationUnavailableError("Video crop is not available in this build.") from error
                    operation_id = "video-crop"
                    smart_kind = "video"
                else:
                    raise ValueError("Aspect-ratio crop accepts supported still images or videos only")
                if args.smart_crop:
                    try:
                        saliency = probe_smart_crop_bounds(source_path, smart_kind)
                    except NativeMediaUnavailableError as error:
                        raise MediaOperationUnavailableError("Smart crop is available only in the macOS Media Toolkit.") from error
                    source_width, source_height = saliency["sourceWidth"], saliency["sourceHeight"]
                    crop_options = _smart_crop_rectangle(source_width, source_height, args.aspect_ratio, saliency)
                else:
                    crop_options = _crop_rectangle(source_width, source_height, args.aspect_ratio)
                operations = [MediaOperation.model_validate({
                    "operationId": operation_id,
                    "options": crop_options,
                })]
            else:
                operations = recipe_operations or _preset_operations(args.preset, source_path.name)
            if args.preset == "sort-screenshots":
                source, source_info = _read_input(source_path, include_stat=True)
                output = MediaOptimizerEngine.execute(source, source_path.name, operations)
                destination_dir = _screenshot_output_directory(output_root, source_info.st_mtime)
                output_name = render_output_name(name_template or "{name}.{ext}", source_path.name, output.extension, "image", sequence)
                destination = _publish_new(
                    destination_dir, output_name,
                    output.data, args.collision_policy == "suffix",
                )
                results.append({
                    "input": source_path.name, "output": destination.relative_to(output_root).as_posix(),
                    "bytes": len(output.data), "inputBytes": len(source), "attributes": output.attributes,
                })
                continue
            native_kind = _native_recipe_kind(operations)
            if native_kind and args.preset != "downscale-video":
                workspace = tempfile.mkdtemp(prefix=".officekit-media-", dir=output_dir)
                try:
                    staged_source = Path(workspace) / f"source.{_safe_extension(source_path.name)}"
                    if source_data is None:
                        input_size = _copy_input_to_file(source_path, staged_source)
                    else:
                        staged_source.write_bytes(source_data)
                        input_size = len(source_data)
                    output_path = str(staged_source)
                    native_output = None
                    watermark_image_path = None
                    if any(operation.operation_id == "video-watermark-overlay" for operation in operations):
                        if watermark_image is None:
                            raise ValueError("A video watermark overlay requires --watermark-image")
                        watermark_image_path = os.path.join(workspace, "watermark.png")
                        with open(watermark_image_path, "xb") as watermark_file:
                            watermark_file.write(watermark_image)
                    for operation in operations:
                        previous_path = output_path
                        try:
                                native_arguments = {}
                                if operation.operation_id == "video-watermark-overlay":
                                    native_arguments["watermark_image_path"] = watermark_image_path
                                native_output = convert_native_media_to_file(
                                output_path, source_path.name, operation.operation_id,
                                    operation.options, workspace, **native_arguments,
                            )
                        except NativeMediaUnavailableError as error:
                            raise MediaOperationUnavailableError(
                                "This media operation is not available in this build."
                            ) from error
                        output_path = native_output[0]
                        if previous_path != output_path:
                            os.unlink(previous_path)
                    if native_output is None:
                        raise ValueError("Recipe contains no media operations")
                    output_path, extension, _media_type, attributes, output_size = native_output
                    if output_size > MAX_NATIVE_MEDIA_BYTES:
                        raise ValueError("Media output exceeds the supported limit")
                    media = operations[0].operation_id.split("-", 1)[0]
                    output_name = render_output_name(name_template or "{name}-optimized.{ext}", source_path.name, extension, media, sequence)
                    destination = _publish_file_new(output_dir, output_name, Path(output_path), args.collision_policy == "suffix")
                    results.append({"input": source_path.name, "output": destination.name, "bytes": output_size, "inputBytes": input_size, "attributes": attributes})
                finally:
                    shutil.rmtree(workspace, ignore_errors=True)
            else:
                source = source_data if source_data is not None else _read_input(source_path)
                if operations:
                    output = MediaOptimizerEngine.execute(source, source_path.name, operations, watermark_image=watermark_image)
                    output_data, output_extension, attributes = output.data, output.extension, output.attributes
                    media = operations[0].operation_id.split("-", 1)[0]
                else:
                    output_data = source
                    output_extension = source_path.suffix.lstrip(".").lower()
                    attributes = {"no_op": True}
                    media = "video" if args.preset == "downscale-video" else "audio" if args.preset == "downscale-audio" else "image"
                fallback_template = "{name}-uncropped.{ext}" if args.preset == "uncrop-pdf" else "{name}-optimized.{ext}"
                output_name = render_output_name(name_template or fallback_template, source_path.name, output_extension, media, sequence)
                destination = _publish_new(output_dir, output_name, output_data, args.collision_policy == "suffix")
                results.append({"input": source_path.name, "output": destination.name, "bytes": len(output_data), "inputBytes": len(source), "attributes": attributes})
        stdout.write(json.dumps({"state": "complete", "results": results}, separators=(",", ":")) + "\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ValidationError, ConversionInputError, MediaOperationUnavailableError) as error:
        stderr.write(f"officekit-media: {str(error) or 'operation failed'}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
