"""Safe, portable output names for reusable local media pipelines."""

from __future__ import annotations

import os
import re
import secrets
import string
from datetime import datetime

from pydantic import StrictStr


_CLOP_TOKENS = frozenset("ymndwHMSprife")
_TOKEN_RE = re.compile(r"%([A-Za-z%])")
_CAPTURE_RE = re.compile(r"\$([0-9]+)")


def output_name_capture_indices(value: str | None) -> list[int]:
    tokens = _CAPTURE_RE.findall(value or "")
    if any(token.startswith("0") or len(token) > 2 for token in tokens):
        raise ValueError("Output capture tokens must use $1 through $99")
    return [int(token) for token in tokens]


def _percent_tokens(value: str) -> list[str]:
    tokens = [match.group(1) for match in _TOKEN_RE.finditer(value)]
    if any(token != "%" and token not in _CLOP_TOKENS for token in tokens):
        raise ValueError("Output name template contains an unsupported Clop token")
    return [token for token in tokens if token != "%"]


def validate_output_name_template(value: StrictStr | None, *, allow_captures=False) -> StrictStr | None:
    if value is None:
        return None
    if not 1 <= len(value) <= 120 or any(ord(char) < 32 for char in value):
        raise ValueError("Output name template must be 1 to 120 visible characters")
    if any(char in value for char in '/\\<>:"|?*') or value.endswith((".", " ")):
        raise ValueError("Output name template must be a safe filename")
    try:
        fields = [field for _literal, field, format_spec, conversion in string.Formatter().parse(value)
                  if field is not None and not format_spec and conversion is None]
        parsed_fields = [field for _literal, field, _format_spec, _conversion in string.Formatter().parse(value)
                         if field is not None]
    except ValueError as error:
        raise ValueError("Output name template contains invalid braces") from error
    if fields != parsed_fields or set(fields) - {"name", "ext", "media"}:
        raise ValueError("Output name template supports only {name}, {ext}, and {media}")
    capture_indices = output_name_capture_indices(value)
    if capture_indices and not allow_captures:
        raise ValueError("Output capture tokens require an inline filename regex filter")
    percent_tokens = _percent_tokens(value)
    source_tokens = fields.count("name") + percent_tokens.count("f")
    if source_tokens > 1 or (source_tokens == 0 and not capture_indices):
        raise ValueError("Output name template must include exactly one {name} or %f source-name token")
    if fields.count("ext") != 1 or not value.endswith("{ext}"):
        raise ValueError("Output name template must include {ext} as its final token")
    return value


def render_output_name(template: str | None, source_name: str, extension: str, media: str, sequence: int = 1,
                       *, captures: tuple[str | None, ...] = ()) -> str:
    source_basename = os.path.basename(source_name)
    stem = os.path.splitext(source_basename)[0] or "media"
    safe_stem = "".join("_" if char in '<>:\"|?*\\/' or ord(char) < 32 else char for char in stem)
    source_extension = os.path.splitext(source_basename)[1].lstrip(".")
    safe_extension = "".join(char for char in extension.lower().lstrip(".") if char.isalnum())
    if not safe_extension:
        raise ValueError("Prepared output has an invalid file format")
    pattern = template or "{name}_prepared.{ext}"
    indices = output_name_capture_indices(pattern)
    if (len(captures) > 99 or any(index > len(captures) for index in indices)
            or any(value is not None and (not isinstance(value, str) or len(value) > 255) for value in captures)):
        raise ValueError("Output capture tokens require matching bounded regex groups")
    now = datetime.now().astimezone()
    percent_values = {
        "y": now.strftime("%Y"), "m": now.strftime("%m"), "n": now.strftime("%B"),
        "d": now.strftime("%d"), "w": now.strftime("%A"), "H": now.strftime("%H"),
        "M": now.strftime("%M"), "S": now.strftime("%S"), "p": now.strftime("%p"),
        "r": secrets.token_hex(3), "i": str(max(1, sequence)), "f": safe_stem,
        "e": source_extension,
    }
    # Insert values only during formatting so braces and percent signs in source
    # filenames remain literal filename characters rather than template syntax.
    rendered_percent = _TOKEN_RE.sub(lambda match: "%" if match.group(1) == "%" else "{clop_" + match.group(1) + "}", pattern)
    rendered_percent = _CAPTURE_RE.sub(lambda match: "{capture_" + match.group(1) + "}", rendered_percent)
    rendered = rendered_percent.format(name=safe_stem, ext=safe_extension, media=media,
                                       **{f"clop_{key}": value for key, value in percent_values.items()},
                                       **{f"capture_{index}": value or "" for index, value in enumerate(captures, 1)})
    if (not rendered or len(rendered.encode("utf-8")) > 255 or rendered in {".", ".."}
            or os.path.basename(rendered) != rendered or any(char in rendered for char in "/\\<>:\"|?*")
            or rendered.endswith((".", " ")) or any(ord(char) < 32 for char in rendered)):
        raise ValueError("Output name template produced an unsafe filename")
    return rendered
