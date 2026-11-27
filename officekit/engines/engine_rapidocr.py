"""Bounded offline OCR using bundled RapidOCR ONNX models."""

import importlib.util
import math
import re
import threading
from pathlib import Path

import numpy as np

from officekit.engines.engine_ocr import ImageTextRecognitionError, ImageTextRecognitionUnavailable


MAX_IMAGE_PIXELS = 40_000_000
MAX_OCR_OBSERVATIONS = 10_000
MAX_OCR_TEXT_BYTES = 1_048_576
MIN_TEXT_CONFIDENCE = 0.35
MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "PP-OCRv6_rec_small.onnx",
)
_engine = None
_engine_lock = threading.RLock()


def _models_directory() -> Path | None:
    if importlib.util.find_spec("rapidocr") is None:
        return None
    import rapidocr

    models = Path(rapidocr.__file__).resolve().parent / "models"
    return models if all((models / filename).is_file() for filename in MODEL_FILES) else None


def is_available() -> bool:
    """Return true only when the package includes every local model and runtime."""
    return _models_directory() is not None and importlib.util.find_spec("onnxruntime") is not None


def _engine_params(models: Path) -> dict[str, str]:
    """Pin every model to the bundled path so OCR cannot fetch models at runtime."""
    return {
        "Global.model_root_dir": str(models),
        "Global.log_level": "error",
        "Det.model_path": str(models / MODEL_FILES[0]),
        "Cls.model_path": str(models / MODEL_FILES[1]),
        "Rec.model_path": str(models / MODEL_FILES[2]),
    }


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        models = _models_directory()
        if models is None or importlib.util.find_spec("onnxruntime") is None:
            raise ImageTextRecognitionUnavailable()
        try:
            from rapidocr import RapidOCR

            _engine = RapidOCR(params=_engine_params(models))
        except Exception as error:
            raise ImageTextRecognitionUnavailable() from error
        return _engine


def _validate_image(image):
    try:
        width, height = image.size
    except Exception as error:
        raise ImageTextRecognitionError() from error
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise ImageTextRecognitionError()
    try:
        return np.asarray(image.convert("RGB"))
    except Exception as error:
        raise ImageTextRecognitionError() from error


def _observations(result, width: int, height: int) -> list[dict]:
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        if boxes is None and texts is None and scores is None:
            return []
        raise ImageTextRecognitionError()
    if not (len(boxes) == len(texts) == len(scores)) or len(texts) > MAX_OCR_OBSERVATIONS:
        raise ImageTextRecognitionError()
    observations = []
    for box, text, confidence in zip(boxes, texts, scores):
        if not isinstance(text, str) or not text.strip():
            continue
        if isinstance(confidence, bool):
            raise ImageTextRecognitionError()
        try:
            confidence = float(confidence)
        except (TypeError, ValueError, OverflowError) as error:
            raise ImageTextRecognitionError() from error
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ImageTextRecognitionError()
        if confidence < MIN_TEXT_CONFIDENCE:
            continue
        try:
            coordinates = np.asarray(box, dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise ImageTextRecognitionError() from error
        if coordinates.shape != (4, 2) or not np.isfinite(coordinates).all():
            raise ImageTextRecognitionError()
        x_min, y_min = coordinates.min(axis=0)
        x_max, y_max = coordinates.max(axis=0)
        if x_min < 0 or y_min < 0 or x_max > width or y_max > height or x_max <= x_min or y_max <= y_min:
            raise ImageTextRecognitionError()
        normalized = " ".join(text.split())
        if len(normalized) > 4096:
            raise ImageTextRecognitionError()
        matches = list(re.finditer(r"\S+", normalized))
        box_width = float(x_max - x_min)
        for match in matches:
            if len(observations) >= MAX_OCR_OBSERVATIONS:
                raise ImageTextRecognitionError()
            start_ratio = match.start() / max(len(normalized), 1)
            end_ratio = match.end() / max(len(normalized), 1)
            observations.append({
                "text": match.group(),
                "x": float(x_min) + box_width * start_ratio,
                "center_y": float((y_min + y_max) / 2),
                "width": box_width * (end_ratio - start_ratio),
                "height": float(y_max - y_min),
            })
    return observations


def _rows(observations: list[dict]) -> list[list[str]]:
    ordered = sorted(observations, key=lambda item: (item["center_y"], item["x"]))
    lines: list[dict] = []
    for observation in ordered:
        if lines:
            current = lines[-1]
            threshold = max(5.0, 0.38 * max(current["height"], observation["height"]))
            if abs(current["center_y"] - observation["center_y"]) <= threshold:
                current["items"].append(observation)
                current["center_y"] = sum(item["center_y"] for item in current["items"]) / len(current["items"])
                current["height"] = max(current["height"], observation["height"])
                continue
        lines.append({
            "center_y": observation["center_y"],
            "height": observation["height"],
            "items": [observation],
        })
    header_fields = {
        "date", "transaction date", "value date", "description", "particulars",
        "narration", "details", "debit", "withdrawal", "credit", "deposit", "balance",
        "amount",
    }
    header_line_index = None
    header_centers = []
    for line_index, line in enumerate(lines):
        header_items = [
            item for item in line["items"]
            if item["text"].casefold().strip(":") in header_fields
        ]
        if len(header_items) >= 2:
            header_line_index = line_index
            header_centers = [
                item["x"] + item["width"] / 2
                for item in sorted(header_items, key=lambda item: item["x"])
            ]
            break

    output = []
    for line_index, line in enumerate(lines):
        items = sorted(line["items"], key=lambda item: item["x"])
        if header_centers and line_index != header_line_index:
            cells = [""] * len(header_centers)
            for item in items:
                center_x = item["x"] + item["width"] / 2
                column = min(range(len(header_centers)), key=lambda index: abs(header_centers[index] - center_x))
                cells[column] = f"{cells[column]} {item['text']}".strip()
            output.append(cells)
        else:
            output.append([item["text"] for item in items])
    return output


def recognize_image(image, timeout_seconds=None) -> str:
    """Recognize a PIL image without network access and preserve table cells as tabs."""
    observations = recognize_observations(image, timeout_seconds=timeout_seconds)
    rows = _rows(observations)
    text = "\n".join("\t".join(row) for row in rows)
    if len(text.encode("utf-8")) > MAX_OCR_TEXT_BYTES:
        raise ImageTextRecognitionError()
    return text


def recognize_observations(image, timeout_seconds=None) -> list[dict]:
    """Recognize words and retain validated pixel boxes for irreversible masking."""
    pixels = _validate_image(image)
    height, width = pixels.shape[:2]
    with _engine_lock:
        try:
            result = _get_engine()(pixels)
            observations = _observations(result, width, height)
        except (ImageTextRecognitionError, ImageTextRecognitionUnavailable):
            raise
        except Exception as error:
            raise ImageTextRecognitionError() from error
    return observations
