"""Shared bounded image/video crop geometry for typed jobs and the local CLI."""

from decimal import Decimal
from fractions import Fraction
import math
import re


def parse_crop_aspect_ratio(value):
    if not isinstance(value, str) or len(value) > 15:
        raise ValueError("Aspect ratio must use width:height, such as 16:9 or 1.91:1")
    parts = value.split(":")
    if len(parts) != 2 or not all(re.fullmatch(r"[0-9]+(?:\.[0-9]{1,4})?", part, flags=re.ASCII) for part in parts):
        raise ValueError("Aspect ratio must use width:height, such as 16:9 or 1.91:1")
    width, height = (Fraction(Decimal(part)) for part in parts)
    ratio = width / height if height else Fraction(0, 1)
    if width <= 0 or height <= 0 or not Fraction(1, 10) <= ratio <= Fraction(10, 1):
        raise ValueError("Aspect ratio must be between 1:10 and 10:1")
    if max(ratio.numerator, ratio.denominator) > 10_000:
        raise ValueError("Reduced aspect ratio dimensions must not exceed 10,000")
    return ratio


def crop_rectangle(width, height, aspect_ratio):
    if type(width) is not int or type(height) is not int or not 1 <= width <= 40_000 or not 1 <= height <= 40_000:
        raise ValueError("Source dimensions are outside the supported crop range")
    ratio = parse_crop_aspect_ratio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
    if not isinstance(ratio, Fraction) or ratio <= 0:
        raise ValueError("Aspect ratio is invalid")
    if ratio >= Fraction(width, height):
        crop_width = width
        crop_height = max(1, (width * ratio.denominator + ratio.numerator // 2) // ratio.numerator)
    else:
        crop_height = height
        crop_width = max(1, (height * ratio.numerator + ratio.denominator // 2) // ratio.denominator)
    return {"x": (width - crop_width) // 2, "y": (height - crop_height) // 2,
            "width": crop_width, "height": crop_height}


def smart_crop_rectangle(width, height, aspect_ratio, saliency):
    centered = crop_rectangle(width, height, aspect_ratio)
    if not isinstance(saliency, dict) or type(saliency.get("detected")) is not bool:
        raise ValueError("Smart crop saliency bounds are invalid")
    if not saliency["detected"]:
        return centered
    values = tuple(saliency.get(key) for key in ("x", "y", "width", "height"))
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in values):
        raise ValueError("Smart crop saliency bounds are invalid")
    x, y, box_width, box_height = values
    if (box_width <= 0 or box_height <= 0 or min(values) < 0 or max(values) > 1
            or x + box_width > 1.000001 or y + box_height > 1.000001):
        raise ValueError("Smart crop saliency bounds are invalid")
    crop_width, crop_height = centered["width"], centered["height"]
    center_x = (x + box_width / 2) * width
    center_y = (1 - y - box_height / 2) * height
    return {"x": min(max(round(center_x - crop_width / 2), 0), width - crop_width),
            "y": min(max(round(center_y - crop_height / 2), 0), height - crop_height),
            "width": crop_width, "height": crop_height}
