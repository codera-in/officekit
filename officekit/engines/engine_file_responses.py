"""Safe helpers for downloadable file responses."""

import re
import unicodedata
from urllib.parse import quote


MAX_ATTACHMENT_NAME_LENGTH = 180
_CONTROL_CATEGORIES = {"Cc", "Cf", "Cs"}


def content_disposition_attachment(filename: str) -> str:
    """Build an ASCII-safe RFC 6266 header with a UTF-8 extended filename."""
    if not isinstance(filename, str):
        filename = ""

    separator = max(filename.rfind("/"), filename.rfind("\\"))
    basename = filename[separator + 1:] if separator >= 0 else filename
    suffix_start = basename.rfind(".")
    has_short_suffix = suffix_start >= 0 and len(basename) - suffix_start <= 16
    raw_stem = basename[:suffix_start] if has_short_suffix else basename
    raw_suffix = basename[suffix_start:] if has_short_suffix else ""

    stem = unicodedata.normalize("NFC", raw_stem[:MAX_ATTACHMENT_NAME_LENGTH])
    suffix = unicodedata.normalize("NFC", raw_suffix)
    stem = "".join(
        character for character in stem
        if unicodedata.category(character) not in _CONTROL_CATEGORIES
    ).strip(" .")
    suffix = "".join(
        character for character in suffix
        if unicodedata.category(character) not in _CONTROL_CATEGORIES
    )
    stem = stem.strip(" .") or "download"
    stem = stem[:MAX_ATTACHMENT_NAME_LENGTH - len(suffix)]
    safe_name = f"{stem}{suffix}"

    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    fallback_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip(" .") or "download"
    ascii_suffix = unicodedata.normalize("NFKD", suffix).encode("ascii", "ignore").decode("ascii")
    fallback_suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_suffix)
    fallback_stem = fallback_stem[:MAX_ATTACHMENT_NAME_LENGTH - len(fallback_suffix)]
    fallback = f"{fallback_stem}{fallback_suffix}"
    encoded_name = quote(safe_name, safe="!#$&+-.^_`|~")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded_name}"
