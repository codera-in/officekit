"""Bounded adapter for the bundled, offline macOS Vision text recognizer."""

import json
import math
import os
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from officekit.engines.engine_ocr import ImageTextRecognitionError, ImageTextRecognitionUnavailable


MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_OCR_TEXT_BYTES = 1024 * 1024
MAX_OCR_OBSERVATIONS = 10_000
MAX_OCR_LINE_LENGTH = 4096
OCR_TIMEOUT_SECONDS = 60
HELPER_BASENAME = "officekit-vision-ocr"
EXIT_UNAVAILABLE = 69


class VisionOcrUnavailable(ImageTextRecognitionUnavailable):
    """The native helper is absent, timed out, or could not be started."""


class VisionOcrError(ImageTextRecognitionError):
    """The native helper rejected the image or returned invalid output."""


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def find_vision_helper(
    platform: str = sys.platform,
    executable_path: str = sys.executable,
    module_file: str = __file__,
) -> Path | None:
    """Find the signed-in-bundle helper or the deterministic local build output."""
    if platform != "darwin":
        return None
    candidates = [
        Path(executable_path).parent / HELPER_BASENAME,
        Path(module_file).resolve().parents[2] / ".build" / "backend-sidecar" / "dist" /
        "officekit-backend" / HELPER_BASENAME,
    ]
    for candidate in candidates:
        if _is_executable_file(candidate):
            return candidate
    return None


def image_to_png_bytes(
    image,
    max_image_pixels: int = MAX_IMAGE_PIXELS,
    max_image_bytes: int = MAX_IMAGE_BYTES,
) -> bytes:
    """Serialize a decoded image under explicit pixel and encoded-byte budgets."""
    if (
        isinstance(max_image_pixels, bool)
        or not isinstance(max_image_pixels, int)
        or max_image_pixels <= 0
        or isinstance(max_image_bytes, bool)
        or not isinstance(max_image_bytes, int)
        or max_image_bytes <= 0
    ):
        raise VisionOcrError()
    try:
        width, height = image.size
    except Exception as error:
        raise VisionOcrError() from error
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or width * height > max_image_pixels
    ):
        raise VisionOcrError()
    output = BytesIO()
    try:
        image.save(output, format="PNG", optimize=False)
        encoded = output.getvalue()
    except Exception as error:
        raise VisionOcrError() from error
    if len(encoded) > max_image_bytes:
        raise VisionOcrError()
    return encoded


def _decode_observations(value) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_OCR_OBSERVATIONS:
        raise VisionOcrError()
    observations = []
    required = {"text", "x", "y", "width", "height", "confidence"}
    for row in value:
        if not isinstance(row, dict) or set(row) != required:
            raise VisionOcrError()
        text = row["text"]
        numbers = [row[key] for key in ("x", "y", "width", "height", "confidence")]
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_OCR_LINE_LENGTH:
            raise VisionOcrError()
        if any(isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) for number in numbers):
            raise VisionOcrError()
        x, y, width, height, confidence = numbers
        if (
            not 0 <= x <= 1
            or not 0 <= y <= 1
            or not 0 < width <= 1
            or not 0 < height <= 1
            or x + width > 1.001
            or y + height > 1.001
            or not 0 <= confidence <= 1
        ):
            raise VisionOcrError()
        observations.append({
            "text": text.strip(),
            "x": float(x),
            "y": float(y),
            "width": float(width),
            "height": float(height),
            "confidence": float(confidence),
        })
    return observations


def _is_date_token(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})",
            text.strip(),
        )
    )


def _is_amount_token(text: str) -> bool:
    normalized = text.strip().replace("−", "-")
    return bool(
        re.fullmatch(
            r"\(?-?(?:[$€£₹])?\d[\d,]*(?:\.\d{1,2})?\)?(?:CR|DR)?",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def parse_vision_output(raw_output: bytes, max_observations: int = MAX_OCR_OBSERVATIONS) -> str:
    """Validate helper JSON and group text boxes into ordered lines and columns."""
    if (
        not isinstance(raw_output, bytes)
        or len(raw_output) > MAX_OCR_TEXT_BYTES
        or isinstance(max_observations, bool)
        or not isinstance(max_observations, int)
        or max_observations < 0
    ):
        raise VisionOcrError()
    try:
        decoded = json.loads(raw_output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisionOcrError() from error
    if not isinstance(decoded, list) or len(decoded) > max_observations:
        raise VisionOcrError()
    observations = _decode_observations(decoded)
    ordered = sorted(observations, key=lambda item: (-(item["y"] + item["height"] / 2), item["x"]))
    lines: list[dict] = []
    for observation in ordered:
        center_y = observation["y"] + observation["height"] / 2
        if lines:
            current = lines[-1]
            threshold = max(0.004, (observation["height"] + current["height"]) * 0.325)
            if abs(current["center_y"] - center_y) <= threshold:
                current["items"].append(observation)
                current["center_y"] = sum(item["y"] + item["height"] / 2 for item in current["items"]) / len(current["items"])
                current["height"] = max(current["height"], observation["height"])
                continue
        lines.append({"center_y": center_y, "height": observation["height"], "items": [observation]})

    output_lines = []
    header_fields = {"date", "description", "particulars", "withdrawal", "deposit", "balance", "amount", "debit", "credit"}
    header_indexes = []
    header_centers = []
    for line_index, line in enumerate(lines):
        header_items = [
            item for item in line["items"]
            if item["text"].casefold().strip(":") in header_fields
        ]
        if len(header_items) >= 2:
            header_indexes = [line_index]
            header_centers = [item["x"] + item["width"] / 2 for item in sorted(header_items, key=lambda item: item["x"])]
            break

    for line_index, line in enumerate(lines):
        items = sorted(line["items"], key=lambda item: item["x"])
        texts = [item["text"] for item in items]
        is_header = any(text.casefold().strip(":") in header_fields for text in texts)
        if header_centers and line_index == header_indexes[0]:
            output_lines.append("\t".join(texts))
            continue
        if header_centers:
            cells = [""] * len(header_centers)
            for item in items:
                center_x = item["x"] + item["width"] / 2
                column = min(range(len(header_centers)), key=lambda index: abs(header_centers[index] - center_x))
                cells[column] = f"{cells[column]} {item['text']}".strip()
            if any(cells):
                output_lines.append("\t".join(cells))
            continue
        has_date = any(_is_date_token(text) for text in texts)
        combined = texts[0]
        previous = items[0]
        for item in items[1:]:
            gap = item["x"] - previous["x"] - previous["width"]
            previous_character_width = previous["width"] / max(len(previous["text"]), 1)
            current_character_width = item["width"] / max(len(item["text"]), 1)
            column_gap = max(0.012, (previous_character_width + current_character_width) * 0.625)
            current_text = item["text"].casefold().strip(":")
            previous_text = previous["text"]
            semantic_boundary = (
                is_header and current_text in header_fields
            ) or (
                has_date and (
                    _is_date_token(previous_text)
                    or _is_amount_token(item["text"])
                )
            )
            separator = "   " if semantic_boundary or gap >= column_gap else " "
            combined += separator + item["text"]
            previous = item
        output_lines.append(combined.strip())
    return "\n".join(output_lines)


def recognize_image(
    image,
    helper_path: str | Path | None = None,
    runner=None,
    helper_lookup=find_vision_helper,
    timeout_seconds: float = OCR_TIMEOUT_SECONDS,
) -> str:
    """Send only encoded image bytes to the helper; never use paths or a shell."""
    helper = Path(helper_path) if helper_path is not None else helper_lookup()
    if helper is None:
        raise VisionOcrUnavailable()
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= OCR_TIMEOUT_SECONDS
    ):
        raise VisionOcrError()
    image_bytes = image_to_png_bytes(image)
    run = subprocess.run if runner is None else runner
    try:
        result = run(
            [str(helper)],
            input=image_bytes,
            capture_output=True,
            check=False,
            close_fds=True,
            shell=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VisionOcrUnavailable() from error
    if getattr(result, "returncode", None) == EXIT_UNAVAILABLE:
        raise VisionOcrUnavailable()
    if getattr(result, "returncode", None) != 0:
        raise VisionOcrError()
    stdout = getattr(result, "stdout", None)
    return parse_vision_output(stdout)


def is_available() -> bool:
    """Whether this build has a runnable macOS Vision helper."""
    return find_vision_helper() is not None
