"""Dependency-free validation for PDF engine inputs."""

import unicodedata


MAX_PDF_PASSWORD_CHARACTERS = 127
MAX_PDF_PASSWORD_BYTES = 127


def is_valid_pdf_password(value: object, *, require_non_empty: bool) -> bool:
    if not isinstance(value, str):
        return False
    if require_non_empty and not value:
        return False
    if len(value) > MAX_PDF_PASSWORD_CHARACTERS:
        return False
    try:
        raw_bytes = len(value.encode("utf-8"))
        normalized_bytes = len(unicodedata.normalize("NFKC", value).encode("utf-8"))
        return raw_bytes <= MAX_PDF_PASSWORD_BYTES and normalized_bytes <= MAX_PDF_PASSWORD_BYTES
    except UnicodeEncodeError:
        return False
