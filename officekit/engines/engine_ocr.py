"""Dependency-injected image OCR boundary with safe, actionable failures."""

import io
import re
from collections.abc import Callable
from typing import Any


class ImageTextRecognitionUnavailable(RuntimeError):
    status_code = 503
    public_message = "Image text recognition is unavailable on this computer."

    def __init__(self):
        super().__init__(self.public_message)


class ImageTextRecognitionError(ValueError):
    status_code = 422
    public_message = "Could not read this image. Try a clearer image or a text PDF."

    def __init__(self):
        super().__init__(self.public_message)


def parse_ocr_text_rows(raw_text: str) -> list[list[str]]:
    """Convert OCR lines into the same whitespace-delimited rows as before."""
    if not isinstance(raw_text, str):
        raise ImageTextRecognitionError()
    rows = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t")]
            if any(parts):
                rows.append(parts)
                continue
        parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        if len(parts) >= 2:
            rows.append(parts)
        elif len(line.split()) >= 3:
            rows.append(line.split())
    return rows


def extract_image_text_rows(
    image_bytes: bytes,
    image_opener: Callable[[Any], Any],
    recognize: Callable[[Any], str] | None,
) -> list[list[str]]:
    """Open and OCR an image, distinguishing unavailable OCR from bad image data."""
    if recognize is None:
        raise ImageTextRecognitionUnavailable()
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ImageTextRecognitionError()
    try:
        image = image_opener(io.BytesIO(image_bytes))
    except Exception as error:
        raise ImageTextRecognitionError() from error
    try:
        raw_text = recognize(image)
    except ImageTextRecognitionUnavailable:
        raise
    except Exception as error:
        raise ImageTextRecognitionError() from error
    return parse_ocr_text_rows(raw_text)
