"""Named PDF compression profiles and honest output-size reporting."""

from __future__ import annotations


_PROFILES = {
    "fast": {"compress_streams": True, "recompress_flate": True, "compression_level": 3, "object_streams": "generate"},
    "balanced": {"compress_streams": True, "recompress_flate": True, "compression_level": 6, "object_streams": "generate"},
    "maximum": {"compress_streams": True, "recompress_flate": True, "compression_level": 9, "object_streams": "generate"},
}

_ALIASES = {
    "screen": "fast",
    "ebook": "balanced",
    "printer": "maximum",
}


def compression_options(preset: object) -> dict[str, object]:
    """Return a copy of the selected lossless qpdf profile.

    The legacy screen/ebook/printer names remain accepted for compatibility,
    but they do not imply DPI changes or lossy image recompression.
    """
    if not isinstance(preset, str):
        raise ValueError("Unknown PDF compression preset")
    normalized = preset.strip().casefold()
    normalized = _ALIASES.get(normalized, normalized)
    profile = _PROFILES.get(normalized)
    if profile is None:
        raise ValueError("Unknown PDF compression preset")
    return dict(profile)


def compression_ratio(compressed_size: int, original_size: int) -> float:
    """Return compressed/original size, including values above 1.0."""
    if (
        isinstance(compressed_size, bool)
        or isinstance(original_size, bool)
        or not isinstance(compressed_size, int)
        or not isinstance(original_size, int)
        or compressed_size <= 0
        or original_size <= 0
    ):
        raise ValueError("PDF sizes must be positive integers")
    return compressed_size / original_size
