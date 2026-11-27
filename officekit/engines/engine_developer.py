"""Developer slice engines (D04, D10, D11, D15, D16, D17).

Pure functions with no storage. Every user-input failure raises
``DeveloperInputError``; routes replace its text with a fixed per-route
message, so parser details are never echoed (P-013).
"""

import base64
import functools
import io
import itertools
import json
import re
import secrets
import time
import unicodedata
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import qrcode
import qrcode.constants
import qrcode.exceptions
import regex
import tzlocal
from PIL import Image

from officekit.engines import _myers
from officekit.engines.engine_devtools import DevToolsEngine

MAX_TEXT_BYTES = 1_048_576
MAX_JSON_CHANGES = 10_000
# UTF-8 bytes of change paths and previews listed in one JSON compare response (CR-3).
MAX_JSON_OUTPUT_BYTES = 1_048_576
MAX_PREVIEW_CHARS = 256
MAX_DIFF_LINES = 50_000
MAX_INLINE_SPAN_CODE_POINTS = 1_000
# Work units for all inline-span diffs of one text compare, shared across rows (CR-2).
MAX_INLINE_SPAN_WORK = 4_000_000
# Search work for all arrays of one JSON compare request, shared (CR-1, round 2).
MAX_JSON_SEARCH_WORK = 4_000_000
MAX_CONTEXT_LINES = 20
TEXT_DIFF_WHITESPACE = ("exact", "ignore_trailing", "ignore_all")
TEXT_DIFF_LINE_ENDINGS = ("normalize", "exact")

_LINE_PATTERN = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
_BACKTICK_RUN = re.compile(r"`+")

_MISSING = object()


class DeveloperInputError(ValueError):
    """Developer tool input is invalid, ambiguous or outside supported limits."""

    public_message = "Developer tool input is invalid or exceeds supported limits."


def _parse_json_input(text):
    try:
        return DevToolsEngine._parse_json(text)
    except ValueError as error:
        raise DeveloperInputError(DeveloperInputError.public_message) from error


def _json_kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _number_key(value, numeric):
    if numeric == "lexical":
        return "n" + str(value)
    # Value equality: the exact coefficient and exponent with trailing zeros removed.
    # Built from the digit tuple so no context rounding or exponent expansion occurs.
    sign, digits, exponent = Decimal(value).as_tuple()
    if not any(digits):
        return "n0"
    digits = list(digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return "n" + str(sign) + "".join(str(digit) for digit in digits) + "e" + str(exponent)


def _canonical(value, numeric):
    kind = _json_kind(value)
    if kind == "null":
        return "null"
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "number":
        return _number_key(value, numeric)
    if kind == "string":
        return "s" + json.dumps(value)
    if kind == "array":
        return "[" + ",".join(_canonical(item, numeric) for item in value) + "]"
    return "{" + ",".join(
        json.dumps(key) + ":" + _canonical(value[key], numeric) for key in sorted(value)
    ) + "}"


def _pointer(tokens):
    return "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in tokens)


def _preview(value):
    return _dump_preview(value)[:MAX_PREVIEW_CHARS]


def _dump_preview(value):
    return DevToolsEngine._dump_json(value, indent=0).replace("\n", "")


def _diff_or_reject(keys_a, keys_b, max_edits, budget=None):
    try:
        return _myers.diff_ops(keys_a, keys_b, max_edits=max_edits, budget=budget)
    except _myers.EditDistanceExceeded as error:
        raise DeveloperInputError(DeveloperInputError.public_message) from error


def _escaped_bytes(token):
    """UTF-8 length of an RFC 6901 reference token after ``~`` and ``/`` escaping."""
    return len(token.encode("utf-8")) + token.count("~") + token.count("/")


def _child(tokens, path_bytes, token, a=_MISSING, b=_MISSING):
    """Child work item: its tokens, its pointer length in bytes, and both values."""
    return (tokens + (token,), path_bytes + 1 + _escaped_bytes(token), a, b)


class _JsonDiffCollector:
    def __init__(self, array_order, numeric, budget):
        self.array_order = array_order
        self.numeric = numeric
        # One search budget for the whole document, shared by every array (CR-1, round 2).
        self.budget = budget
        self.changes = []
        self.counts = {"added": 0, "removed": 0, "changed": 0, "type_changed": 0}
        self.output_bytes = 0

    def record(self, kind, tokens, path_bytes, before=_MISSING, after=_MISSING):
        self.counts[kind] += 1
        if len(self.changes) >= MAX_JSON_CHANGES:
            return
        change = {"kind": kind}
        size = path_bytes
        if before is not _MISSING:
            change["before"] = _preview(before)
            size += len(change["before"].encode("utf-8"))
        if after is not _MISSING:
            change["after"] = _preview(after)
            size += len(change["after"].encode("utf-8"))
        # The byte budget is checked before the path string is built, so a long key
        # repeated in every ancestor path is never materialized past the cap (CR-3).
        if self.output_bytes + size > MAX_JSON_OUTPUT_BYTES:
            return
        self.output_bytes += size
        self.changes.append({"path": _pointer(tokens), **change})

    def run(self, left, right):
        pending = [((), 0, left, right)]
        while pending:
            tokens, path_bytes, a, b = pending.pop()
            children = self.compare(tokens, path_bytes, a, b)
            pending.extend(reversed(children))

    def compare(self, tokens, path_bytes, a, b):
        if a is _MISSING:
            self.record("added", tokens, path_bytes, after=b)
            return []
        if b is _MISSING:
            self.record("removed", tokens, path_bytes, before=a)
            return []
        kind_a, kind_b = _json_kind(a), _json_kind(b)
        if kind_a != kind_b:
            self.record("type_changed", tokens, path_bytes, before=a, after=b)
            return []
        if kind_a == "object":
            keys = sorted(set(a) | set(b))
            return [
                _child(tokens, path_bytes, key, a.get(key, _MISSING), b.get(key, _MISSING))
                for key in keys
            ]
        if kind_a == "array":
            return self.align_arrays(tokens, path_bytes, a, b)
        if _canonical(a, self.numeric) != _canonical(b, self.numeric):
            self.record("changed", tokens, path_bytes, before=a, after=b)
        return []

    def align_arrays(self, tokens, path_bytes, a, b):
        if self.array_order == "unordered":
            return self.match_unordered(tokens, path_bytes, a, b)
        keys_a = [_canonical(item, self.numeric) for item in a]
        keys_b = [_canonical(item, self.numeric) for item in b]
        ops = _diff_or_reject(keys_a, keys_b, _myers.MAX_EDIT_DISTANCE, self.budget)
        children = []
        removed, inserted = [], []
        for kind, i, j in ops + [(_myers.EQUAL, None, None)]:
            if kind == _myers.EQUAL:
                for index_a, index_b in itertools.zip_longest(removed, inserted):
                    if index_b is None:
                        children.append(_child(tokens, path_bytes, str(index_a), a[index_a]))
                    elif index_a is None:
                        children.append(_child(tokens, path_bytes, str(index_b), _MISSING, b[index_b]))
                    else:
                        children.append(_child(tokens, path_bytes, str(index_a), a[index_a], b[index_b]))
                removed, inserted = [], []
            elif kind == _myers.DELETE:
                removed.append(i)
            else:
                inserted.append(j)
        return children

    def match_unordered(self, tokens, path_bytes, a, b):
        positions = {}
        for j, item in enumerate(b):
            positions.setdefault(_canonical(item, self.numeric), deque()).append(j)
        matched_b = set()
        for i, item in enumerate(a):
            queue = positions.get(_canonical(item, self.numeric))
            if queue:
                matched_b.add(queue.popleft())
            else:
                child_tokens, child_bytes, _, _ = _child(tokens, path_bytes, str(i))
                self.record("removed", child_tokens, child_bytes, before=item)
        for j, item in enumerate(b):
            if j not in matched_b:
                child_tokens, child_bytes, _, _ = _child(tokens, path_bytes, str(j))
                self.record("added", child_tokens, child_bytes, after=item)
        return []


def compare_json(original, changed, *, array_order="ordered", numeric="value"):
    """Structural JSON diff with RFC 6901 paths (D04).

    Object key order is ignored. ``array_order`` is ``ordered`` (aligned with
    Myers) or ``unordered`` (multiset). ``numeric`` is ``value`` (exact decimal
    value) or ``lexical`` (source token). Changes are listed up to
    ``MAX_JSON_CHANGES``; the counts always cover every change.
    """
    left = _parse_json_input(original)
    right = _parse_json_input(changed)
    collector = _JsonDiffCollector(array_order, numeric, _myers.WorkBudget(MAX_JSON_SEARCH_WORK))
    collector.run(left, right)
    total = sum(collector.counts.values())
    return {
        "equal": total == 0,
        "changes": collector.changes,
        "truncated": total > len(collector.changes),
        "counts": dict(collector.counts),
    }


def _checked_text(text, label):
    try:
        DevToolsEngine._text_bytes(text, label)
    except ValueError as error:
        raise DeveloperInputError(DeveloperInputError.public_message) from error
    return text


def _split_lines(text):
    """Return (content, ending) pairs. Endings are CRLF, CR, LF or empty for a last line."""
    lines = []
    for segment in _LINE_PATTERN.findall(text):
        ending = ""
        for candidate in ("\r\n", "\r", "\n"):
            if segment.endswith(candidate):
                ending = candidate
                break
        lines.append((segment[: len(segment) - len(ending)], ending))
    return lines


def _line_ending_style(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    present = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    if not present:
        return "none"
    return present[0] if len(present) == 1 else "mixed"


def _line_key(content, ending, whitespace, unicode_nfc, line_endings):
    key = content
    if whitespace == "ignore_trailing":
        key = key.rstrip()
    elif whitespace == "ignore_all":
        key = "".join(character for character in key if not character.isspace())
    if unicode_nfc:
        key = unicodedata.normalize("NFC", key)
    if line_endings == "exact":
        key += ending
    return key


def _merged_ranges(indexes):
    ranges = []
    for index in indexes:
        if ranges and ranges[-1]["end"] == index:
            ranges[-1]["end"] = index + 1
        else:
            ranges.append({"start": index, "end": index + 1})
    return ranges


def _inline_spans(left, right, budget):
    if len(left) > MAX_INLINE_SPAN_CODE_POINTS or len(right) > MAX_INLINE_SPAN_CODE_POINTS:
        return None
    try:
        ops = _myers.diff_ops(list(left), list(right), budget=budget)
    except _myers.EditDistanceExceeded:
        return None
    left_spans = _merged_ranges([i for kind, i, _ in ops if kind == _myers.DELETE])
    right_spans = _merged_ranges([j for kind, _, j in ops if kind == _myers.INSERT])
    return left_spans, right_spans


def _emit_gap(rows, lines_a, lines_b, removed, inserted, budget):
    for i, j in itertools.zip_longest(removed, inserted):
        if j is None:
            rows.append({"op": "delete", "left_no": i + 1, "left": lines_a[i][0]})
        elif i is None:
            rows.append({"op": "insert", "right_no": j + 1, "right": lines_b[j][0]})
        else:
            left, right = lines_a[i][0], lines_b[j][0]
            row = {"op": "change", "left_no": i + 1, "right_no": j + 1, "left": left, "right": right}
            spans = _inline_spans(left, right, budget)
            if spans is not None:
                row["left_spans"], row["right_spans"] = spans
            rows.append(row)


def _build_rows(lines_a, lines_b, ops, budget):
    rows = []
    removed, inserted = [], []
    for kind, i, j in ops + [(None, None, None)]:
        if kind == _myers.DELETE:
            removed.append(i)
        elif kind == _myers.INSERT:
            inserted.append(j)
        else:
            _emit_gap(rows, lines_a, lines_b, removed, inserted, budget)
            removed, inserted = [], []
            if kind == _myers.EQUAL:
                rows.append({
                    "op": "equal",
                    "left_no": i + 1,
                    "right_no": j + 1,
                    "left": lines_a[i][0],
                    "right": lines_b[j][0],
                })
    return rows


def _no_newline_marker(lines, index):
    last = len(lines) - 1
    return index == last and lines[index][1] == ""


def _patch_hunks(rows, lines_a, lines_b, context):
    changed = [index for index, row in enumerate(rows) if row["op"] != "equal"]
    if not changed:
        return []
    spans = []
    start = end = changed[0]
    for index in changed[1:]:
        if index - end - 1 <= 2 * context:
            end = index
        else:
            spans.append((start, end))
            start = end = index
    spans.append((start, end))

    old_before, new_before = [0], [0]
    for row in rows:
        old_before.append(old_before[-1] + (row["op"] != "insert"))
        new_before.append(new_before[-1] + (row["op"] != "delete"))

    hunks = []
    for first, last in spans:
        low = max(0, first - context)
        high = min(len(rows) - 1, last + context)
        old_count = old_before[high + 1] - old_before[low]
        new_count = new_before[high + 1] - new_before[low]
        old_start = old_before[low] + 1 if old_count else old_before[low]
        new_start = new_before[low] + 1 if new_count else new_before[low]
        lines = [f"@@ -{old_start},{old_count} +{new_start},{new_count} @@\n"]
        index = low
        while index <= high:
            row = rows[index]
            if row["op"] == "equal":
                lines.append(" " + row["left"] + "\n")
                if _no_newline_marker(lines_a, row["left_no"] - 1):
                    lines.append("\\ No newline at end of file\n")
                index += 1
                continue
            minus, plus = [], []
            while index <= high and rows[index]["op"] != "equal":
                current = rows[index]
                if current["op"] in ("delete", "change"):
                    minus.append(current["left_no"] - 1)
                if current["op"] in ("insert", "change"):
                    plus.append(current["right_no"] - 1)
                index += 1
            for position in minus:
                lines.append("-" + lines_a[position][0] + "\n")
                if _no_newline_marker(lines_a, position):
                    lines.append("\\ No newline at end of file\n")
            for position in plus:
                lines.append("+" + lines_b[position][0] + "\n")
                if _no_newline_marker(lines_b, position):
                    lines.append("\\ No newline at end of file\n")
        hunks.append("".join(lines))
    return hunks


def _markdown_patch(patch):
    if not patch:
        return ""
    longest = max((len(run) for run in _BACKTICK_RUN.findall(patch)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}diff\n{patch}{fence}\n"


def compare_text(
    original,
    changed,
    *,
    whitespace="exact",
    line_endings="normalize",
    unicode_nfc=False,
    context=3,
    max_edits=None,
):
    """Line diff with inline spans, a unified patch and a Markdown export (D17).

    Line endings are normalized to LF before comparison unless
    ``line_endings="exact"``. ``whitespace`` and ``unicode_nfc`` change only the
    equality key; rows always show the original text. The patch uses fixed
    ``original`` / ``changed`` labels and no paths.
    """
    if whitespace not in TEXT_DIFF_WHITESPACE or line_endings not in TEXT_DIFF_LINE_ENDINGS:
        raise DeveloperInputError(DeveloperInputError.public_message)
    if type(context) is not int or not 0 <= context <= MAX_CONTEXT_LINES or type(unicode_nfc) is not bool:
        raise DeveloperInputError(DeveloperInputError.public_message)
    text_a = _checked_text(original, "Original")
    text_b = _checked_text(changed, "Changed")
    lines_a = _split_lines(text_a)
    lines_b = _split_lines(text_b)
    if len(lines_a) > MAX_DIFF_LINES or len(lines_b) > MAX_DIFF_LINES:
        raise DeveloperInputError(DeveloperInputError.public_message)
    keys_a = [_line_key(c, e, whitespace, unicode_nfc, line_endings) for c, e in lines_a]
    keys_b = [_line_key(c, e, whitespace, unicode_nfc, line_endings) for c, e in lines_b]
    bound = _myers.MAX_EDIT_DISTANCE if max_edits is None else max_edits
    span_budget = _myers.WorkBudget(MAX_INLINE_SPAN_WORK)
    rows = _build_rows(lines_a, lines_b, _diff_or_reject(keys_a, keys_b, bound), span_budget)
    hunks = _patch_hunks(rows, lines_a, lines_b, context)
    patch = ""
    if hunks:
        patch = "--- original\n+++ changed\n" + "".join(hunks)
    return {
        "equal": all(row["op"] == "equal" for row in rows),
        "rows": rows,
        "spans_omitted": any(row["op"] == "change" and "left_spans" not in row for row in rows),
        "hunks": len(hunks),
        "stats": {
            "inserted": sum(1 for row in rows if row["op"] == "insert"),
            "deleted": sum(1 for row in rows if row["op"] == "delete"),
            "changed": sum(1 for row in rows if row["op"] == "change"),
        },
        "line_endings": {
            "original": _line_ending_style(text_a),
            "changed": _line_ending_style(text_b),
        },
        "patch": patch,
        "markdown": _markdown_patch(patch),
    }


CASE_STYLES = ("lower", "upper", "title", "sentence", "camel", "pascal", "snake", "kebab", "constant")
CASE_LOCALES = ("root", "tr", "az")
_TURKIC_LOCALES = ("tr", "az")
_WORD_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
_IDENTIFIER_PATTERN = re.compile(r"[^\W_]+")
_LINE_BREAK_PATTERN = re.compile(r"\r\n|\r|\n")
_GRAPHEME_PATTERN = regex.compile(r"\X")
_LETTER_PATTERN = re.compile(r"[^\W\d_]")


def count_graphemes(text):
    """Extended grapheme clusters (UAX #29) via the pinned regex package."""
    return len(_GRAPHEME_PATTERN.findall(text))


def text_metrics(text):
    """Defined counts for D16: graphemes, code points, bytes, words, lines and whitespace."""
    _checked_text(text, "Text")
    if text == "":
        segments = []
    else:
        segments = _LINE_BREAK_PATTERN.split(text)
        if segments[-1] == "":
            segments.pop()
    return {
        "graphemes": count_graphemes(text),
        "code_points": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "utf16_units": len(text.encode("utf-16-le")) // 2,
        "words": sum(1 for token in text.split() if any(character.isalnum() for character in token)),
        "lines": len(segments),
        "blank_lines": sum(1 for segment in segments if not segment.strip()),
        "whitespace": sum(1 for character in text if character.isspace()),
        "longest_line_graphemes": max((count_graphemes(segment) for segment in segments), default=0),
    }


def _case_lower(text, locale):
    if locale in _TURKIC_LOCALES:
        text = text.replace("I", "ı").replace("İ", "i")
    return text.lower()


def _case_upper(text, locale):
    if locale in _TURKIC_LOCALES:
        text = text.replace("i", "İ")
    return text.upper()


def _case_title_head(head, locale):
    if locale in _TURKIC_LOCALES and head == "i":
        return "İ"
    return head.title()


def _case_title_word(word, locale):
    return _case_title_head(word[:1], locale) + _case_lower(word[1:], locale)


def _identifier_words(text):
    return _IDENTIFIER_PATTERN.findall(text.replace("'", "").replace("’", ""))


def _sentence_case(text, locale):
    lowered = _case_lower(text, locale)
    match = _LETTER_PATTERN.search(lowered)
    if match is None:
        return lowered
    start = match.start()
    return lowered[:start] + _case_title_head(lowered[start], locale) + lowered[start + 1:]


def _convert_case(text, style, locale):
    if style == "lower":
        return _case_lower(text, locale)
    if style == "upper":
        return _case_upper(text, locale)
    if style == "title":
        return _WORD_PATTERN.sub(lambda match: _case_title_word(match.group(0), locale), text)
    if style == "sentence":
        return _sentence_case(text, locale)
    words = _identifier_words(text)
    if style == "camel":
        if not words:
            return ""
        return _case_lower(words[0], locale) + "".join(_case_title_word(word, locale) for word in words[1:])
    if style == "pascal":
        return "".join(_case_title_word(word, locale) for word in words)
    if style == "snake":
        return "_".join(_case_lower(word, locale) for word in words)
    if style == "kebab":
        return "-".join(_case_lower(word, locale) for word in words)
    return "_".join(_case_upper(word, locale) for word in words)


def convert_case(text, style, locale="root"):
    """Convert text to one of nine case styles, optionally with Turkish or Azeri rules (D16)."""
    if style not in CASE_STYLES or locale not in CASE_LOCALES:
        raise DeveloperInputError(DeveloperInputError.public_message)
    _checked_text(text, "Text")
    result = _convert_case(text, style, locale)
    if len(result.encode("utf-8")) > MAX_TEXT_BYTES:
        raise DeveloperInputError(DeveloperInputError.public_message)
    return {"result": result, "style": style, "locale": locale}


TIMESTAMP_INPUT_TYPES = ("unix_seconds", "unix_milliseconds", "unix_microseconds", "iso_8601", "local_datetime")
FOLD_POLICIES = ("reject", "earlier", "later")
MAX_TARGET_ZONES = 8
MAX_ZONE_KEY_CHARS = 64
MAX_TIMESTAMP_CHARS = 64
MAX_TIME_ZONE_LIST = 1_000
MAGNITUDE_LIMIT = 10**11
_MICROS_PER_SECOND = 1_000_000
_MIN_INSTANT_US = -62_135_596_800 * _MICROS_PER_SECOND
_MAX_INSTANT_US = 253_402_300_799 * _MICROS_PER_SECOND + 999_999
_UNIX_UNITS = {
    # input type: (microseconds per unit, maximum fraction digits)
    "unix_seconds": (_MICROS_PER_SECOND, 6),
    "unix_milliseconds": (1_000, 3),
    "unix_microseconds": (1, 0),
}
_UNIX_PATTERN = re.compile(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?")
_ISO_PATTERN = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}:[0-9]{2})"
)
_LOCAL_PATTERN = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,6}))?)?"
)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EPOCH_NAIVE = datetime(1970, 1, 1)
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _timestamp_error():
    return DeveloperInputError(DeveloperInputError.public_message)


@functools.lru_cache(maxsize=1)
def _zone_keys():
    return frozenset(available_timezones())


def _checked_zone(key):
    if not isinstance(key, str) or not 1 <= len(key) <= MAX_ZONE_KEY_CHARS or key not in _zone_keys():
        raise _timestamp_error()
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise _timestamp_error() from error


def _naive_micros(moment):
    return (moment - _EPOCH_NAIVE) // timedelta(microseconds=1)


def _check_range(micro):
    if not _MIN_INSTANT_US <= micro <= _MAX_INSTANT_US:
        raise _timestamp_error()


def _unix_micros(value, input_type):
    match = _UNIX_PATTERN.fullmatch(value)
    if match is None:
        raise _timestamp_error()
    sign, whole, fraction = match.group(1), match.group(2), match.group(3) or ""
    unit_micros, digits = _UNIX_UNITS[input_type]
    if len(fraction) > digits:
        raise _timestamp_error()
    fraction_micros = int(fraction.ljust(digits, "0")) if digits else 0
    micro = int(whole) * unit_micros + fraction_micros
    warnings = []
    if input_type == "unix_seconds" and abs(micro) >= MAGNITUDE_LIMIT * _MICROS_PER_SECOND:
        warnings.append("magnitude_suggests_milliseconds")
    if input_type == "unix_milliseconds" and 0 < abs(micro) < MAGNITUDE_LIMIT * 1_000:
        warnings.append("magnitude_suggests_seconds")
    return (-micro if sign else micro), warnings


def _iso_micros(value):
    match = _ISO_PATTERN.fullmatch(value)
    if match is None:
        raise _timestamp_error()
    parts = [int(part) for part in match.groups()[:6]]
    fraction = match.group(7) or ""
    offset_text = match.group(8)
    try:
        moment = datetime(*parts, int(fraction.ljust(6, "0")))
    except ValueError as error:
        raise _timestamp_error() from error
    offset_minutes = 0
    if offset_text != "Z":
        hours, minutes = int(offset_text[1:3]), int(offset_text[4:6])
        if hours > 23 or minutes > 59:
            raise _timestamp_error()
        offset_minutes = (hours * 60 + minutes) * (1 if offset_text[0] == "+" else -1)
    return _naive_micros(moment) - offset_minutes * 60 * _MICROS_PER_SECOND


def _local_micros(value, zone_key, fold):
    match = _LOCAL_PATTERN.fullmatch(value)
    if match is None:
        raise _timestamp_error()
    parts = [int(part) for part in match.groups()[:6]]
    fraction = match.group(7) or ""
    try:
        naive = datetime(*parts, int(fraction.ljust(6, "0")))
    except ValueError as error:
        raise _timestamp_error() from error
    zone = _checked_zone(zone_key)
    candidates = set()
    for fold_index in (0, 1):
        try:
            offset = naive.replace(tzinfo=zone, fold=fold_index).utcoffset()
            utc_naive = naive - offset
            round_trip = utc_naive.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
        except (OverflowError, ValueError):
            continue
        if round_trip == naive:
            candidates.add(_naive_micros(utc_naive))
    if not candidates:
        # The local time falls in a DST gap, or outside the supported range.
        raise _timestamp_error()
    if len(candidates) == 1:
        return next(iter(candidates))
    if fold == "reject":
        raise _timestamp_error()
    return min(candidates) if fold == "earlier" else max(candidates)


def _unit_text(micro, unit_micros, digits):
    sign = "-" if micro < 0 else ""
    whole, remainder = divmod(abs(micro), unit_micros)
    if digits == 0 or remainder == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{str(remainder).zfill(digits).rstrip('0')}"


def _format_offset(delta):
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, rest = divmod(abs(total), 3600)
    minutes, seconds = divmod(rest, 60)
    text = f"{sign}{hours:02d}:{minutes:02d}"
    return text + f":{seconds:02d}" if seconds else text


def _zone_conversion(micro, zone_key):
    zone = _checked_zone(zone_key)
    try:
        instant = _EPOCH_UTC + timedelta(microseconds=micro)
        local = instant.astimezone(zone)
    except (OverflowError, ValueError) as error:
        raise _timestamp_error() from error
    return {
        "zone": zone_key,
        "local_iso": local.isoformat(),
        "offset": _format_offset(local.utcoffset()),
        "abbreviation": local.tzname() or "",
        "is_dst": bool(local.dst()),
        "weekday": _WEEKDAYS[local.weekday()],
    }


def convert_timestamp(value, input_type, source_zone, fold, target_zones):
    """Convert one instant between Unix, ISO 8601 and local date-time forms (D10).

    Values are parsed as exact integers in microseconds, never as floats.
    ``source_zone`` is used only for ``local_datetime``. ``fold`` resolves an
    ambiguous local time only when it is set explicitly; a DST gap is always rejected.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TIMESTAMP_CHARS:
        raise _timestamp_error()
    if input_type not in TIMESTAMP_INPUT_TYPES or fold not in FOLD_POLICIES:
        raise _timestamp_error()
    if (
        not isinstance(target_zones, list)
        or not 1 <= len(target_zones) <= MAX_TARGET_ZONES
        or len(set(target_zones)) != len(target_zones)
    ):
        raise _timestamp_error()
    warnings = []
    if input_type in _UNIX_UNITS:
        micro, warnings = _unix_micros(value, input_type)
    elif input_type == "iso_8601":
        micro = _iso_micros(value)
    else:
        micro = _local_micros(value, source_zone, fold)
    _check_range(micro)
    unit_text = {
        "unix_seconds": _unit_text(micro, _MICROS_PER_SECOND, 6),
        "unix_milliseconds": _unit_text(micro, 1_000, 3),
        "unix_microseconds": _unit_text(micro, 1, 0),
    }
    instant = (_EPOCH_UTC + timedelta(microseconds=micro)).isoformat().replace("+00:00", "Z")
    return {
        "instant_utc": instant,
        "unix_seconds": unit_text["unix_seconds"],
        "unix_milliseconds": unit_text["unix_milliseconds"],
        "unix_microseconds": unit_text["unix_microseconds"],
        "conversions": [_zone_conversion(micro, key) for key in target_zones],
        "warnings": warnings,
    }


def _local_zone_name():
    try:
        name = tzlocal.get_localzone_name()
    except (LookupError, OSError, ValueError):
        return None
    return name if name in _zone_keys() else None


def list_time_zones():
    """Sorted IANA zone keys (at most MAX_TIME_ZONE_LIST) and the device zone when known."""
    return {"zones": sorted(_zone_keys())[:MAX_TIME_ZONE_LIST], "local_zone": _local_zone_name()}


UUID_VERSIONS = (4, 5, 7)
UUID_CASES = ("lower", "upper")
UUID_STYLES = ("canonical", "braces", "urn", "compact")
MAX_UUID_BATCH = 1_000
MAX_UUID_NAME_BYTES = 1_024
UUID_NAMESPACES = {
    "dns": uuid.NAMESPACE_DNS,
    "url": uuid.NAMESPACE_URL,
    "oid": uuid.NAMESPACE_OID,
    "x500": uuid.NAMESPACE_X500,
}
_CANONICAL_UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_V7_COUNTER_MAX = 0xFFF
_V7_COUNTER_SEED_BITS = 11  # the top bit stays clear so the 12-bit counter has headroom (RFC 9562 6.2)
_V7_RANDOM_BITS = 62
_UUID_MS_MASK = (1 << 48) - 1


def _uuid7_ints(count, now_ms, random_bits):
    """Monotonic UUIDv7 values for one batch (RFC 9562 section 6.2, method 1).

    ``now_ms`` returns the Unix time in milliseconds and ``random_bits(n)`` returns
    an ``n``-bit random integer. The clock never moves the batch backwards, and a
    counter overflow borrows the next millisecond.
    """
    values = []
    last_ms = -1
    counter = 0
    for _ in range(count):
        ms = max(now_ms(), last_ms)
        if ms != last_ms:
            last_ms = ms
            counter = random_bits(_V7_COUNTER_SEED_BITS)
        else:
            counter += 1
            if counter > _V7_COUNTER_MAX:
                last_ms += 1
                counter = random_bits(_V7_COUNTER_SEED_BITS)
        rand_b = random_bits(_V7_RANDOM_BITS)
        values.append(
            ((last_ms & _UUID_MS_MASK) << 80)
            | (0x7 << 76)
            | (counter << 64)
            | (0b10 << 62)
            | rand_b
        )
    return values


def _now_ms():
    return time.time_ns() // 1_000_000


def _format_uuid(value, case, style):
    hex_text = value.hex.upper() if case == "upper" else value.hex
    canonical = f"{hex_text[:8]}-{hex_text[8:12]}-{hex_text[12:16]}-{hex_text[16:20]}-{hex_text[20:]}"
    if style == "braces":
        return "{" + canonical + "}"
    if style == "urn":
        return "urn:uuid:" + canonical
    if style == "compact":
        return hex_text
    return canonical


def _uuid5_namespace(namespace):
    if namespace in UUID_NAMESPACES:
        return UUID_NAMESPACES[namespace]
    if isinstance(namespace, str) and _CANONICAL_UUID_TEXT.fullmatch(namespace):
        return uuid.UUID(namespace)
    raise DeveloperInputError(DeveloperInputError.public_message)


def generate_uuids(version, count, *, namespace=None, name=None, case="lower", style="canonical",
                   now_ms=None, random_bits=None):
    """Generate v4, v5 or v7 UUIDs (D11). Nothing is stored or remembered.

    v4 uses ``uuid.uuid4`` (OS CSPRNG). v7 is built here because the pinned
    Python 3.13 lacks ``uuid.uuid7``. v5 uses ``uuid.uuid5`` and takes exactly
    one name. ``now_ms`` and ``random_bits`` are test hooks for v7.
    """
    if type(version) is not int or version not in UUID_VERSIONS:
        raise DeveloperInputError(DeveloperInputError.public_message)
    if type(count) is not int or not 1 <= count <= MAX_UUID_BATCH:
        raise DeveloperInputError(DeveloperInputError.public_message)
    if case not in UUID_CASES or style not in UUID_STYLES:
        raise DeveloperInputError(DeveloperInputError.public_message)
    if version == 5:
        if count != 1 or not isinstance(name, str):
            raise DeveloperInputError(DeveloperInputError.public_message)
        name_bytes = name.encode("utf-8")
        if not 1 <= len(name_bytes) <= MAX_UUID_NAME_BYTES:
            raise DeveloperInputError(DeveloperInputError.public_message)
        values = [uuid.uuid5(_uuid5_namespace(namespace), name)]
    else:
        if namespace is not None or name is not None:
            raise DeveloperInputError(DeveloperInputError.public_message)
        if version == 4:
            values = [uuid.uuid4() for _ in range(count)]
        else:
            values = [
                uuid.UUID(int=value)
                for value in _uuid7_ints(count, now_ms or _now_ms, random_bits or secrets.randbits)
            ]
    return {
        "uuids": [_format_uuid(value, case, style) for value in values],
        "version": version,
        "count": count,
    }


QR_ERROR_LEVELS = ("L", "M", "Q", "H")
QR_FORMATS = ("png", "svg")
QR_SIZE_MIN = 128
QR_SIZE_MAX = 2_048
QR_BORDER = 4
# Byte-mode capacity of version 40 per error-correction level (the largest QR code).
QR_BYTE_CAPACITY = {"L": 2953, "M": 2331, "Q": 1663, "H": 1273}
_QR_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}


def _qr_code(payload, error_correction):
    if error_correction not in QR_ERROR_LEVELS or not isinstance(payload, str):
        raise DeveloperInputError(DeveloperInputError.public_message)
    if not 1 <= len(payload.encode("utf-8")) <= QR_BYTE_CAPACITY[error_correction]:
        raise DeveloperInputError(DeveloperInputError.public_message)
    code = qrcode.QRCode(error_correction=_QR_LEVELS[error_correction], box_size=1, border=QR_BORDER)
    code.add_data(payload)
    try:
        code.make(fit=True)
    except qrcode.exceptions.DataOverflowError as error:
        raise DeveloperInputError(DeveloperInputError.public_message) from error
    return code


def qr_matrix(payload, error_correction):
    """Module matrix including the quiet zone (True is dark). Test hook and PNG/SVG source."""
    return _qr_code(payload, error_correction).get_matrix()


def _svg_document(matrix, side):
    count = len(matrix)
    modules = "".join(
        f"M{x} {y}h1v1h-1z" for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {count} {count}" width="{side}" height="{side}">'
        f'<rect width="{count}" height="{count}" fill="#fff"/>'
        f'<path fill="#000" d="{modules}"/>'
        "</svg>"
    )


def _png_document(matrix, side):
    count = len(matrix)
    image = Image.new("1", (count, count), 1)
    pixels = image.load()
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                pixels[x, y] = 0
    buffer = io.BytesIO()
    image.resize((side, side), Image.Resampling.NEAREST).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def generate_qr(payload, error_correction, size_px, fmt):
    """Local QR code as a base64 PNG or an SVG document (D15).

    Colours are fixed black on white. Each module is a whole number of pixels, so
    the returned ``size_px`` is the exact side length: the multiple of the module
    count nearest to the request, clamped into [QR_SIZE_MIN, QR_SIZE_MAX].
    """
    if type(size_px) is not int or not QR_SIZE_MIN <= size_px <= QR_SIZE_MAX or fmt not in QR_FORMATS:
        raise DeveloperInputError(DeveloperInputError.public_message)
    code = _qr_code(payload, error_correction)
    matrix = code.get_matrix()
    count = len(matrix)
    # Whole-module scale nearest to the request, clamped so the side stays inside
    # [QR_SIZE_MIN, QR_SIZE_MAX]. The smallest scale for the minimum keeps a small code
    # at or above 128 px; the largest keeps a 2,048 px request at or below 2,048 px (CR-6, ARCH-4).
    scale = min(max(round(size_px / count), -(-QR_SIZE_MIN // count)), QR_SIZE_MAX // count)
    side = count * scale
    if fmt == "svg":
        data = _svg_document(matrix, side)
    else:
        data = base64.b64encode(_png_document(matrix, side)).decode("ascii")
    return {
        "format": fmt,
        "data": data,
        "qr_version": code.version,
        "modules": code.modules_count,
        "payload_bytes": len(payload.encode("utf-8")),
        "size_px": side,
    }
