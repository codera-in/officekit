"""Offline English person and organization candidates for review-first PII scans."""

from __future__ import annotations

import re
from typing import Any


class PiiEnglishEntityDetector:
    MAX_TEXT_BYTES = 8 * 1024 * 1024
    _HEADER_NAME = re.compile(r"[A-Z][A-Z.'’\-]*(?:[ \t]+[A-Z][A-Z.'’\-]*){1,3}")
    _PERSON_NAME = r"[A-Z][A-Za-z.'’\-]*(?:[ \t]+[A-Z][A-Za-z.'’\-]*){1,3}"
    _PERSON_FIELD = re.compile(
        rf"^\s*(?:full\s+name|name|author|prepared\s+by|submitted\s+by|signed\s+by|"
        rf"created\s+by|approved\s+by|reviewed\s+by|contact|customer|patient|employee|"
        rf"applicant|candidate|recipient|sender)\s*[:\-]\s*(?P<value>{_PERSON_NAME})(?=\s*(?:[,;|(<]|$))",
        re.I,
    )
    _ORGANIZATION_FIELD = re.compile(
        r"^\s*(?:company|employer|organization|organisation|school|college|university|"
        r"institution|client|vendor|supplier)\s*[:\-]\s*(?P<value>[^,;|]+?)\s*$", re.I,
    )
    _INSTITUTION = re.compile(r"\b(?:school|college|university|institute|academy)\b", re.I)
    _CORPORATE_SUFFIX = re.compile(
        r"\b(?:pvt\.?\s*Ltd\.?|private\s+limited|limited|ltd\.?|incorporated|inc\.?|"
        r"corporation|corp\.?|llc|llp|gmbh|s\.a\.?|s\.p\.a\.)\s*$", re.I,
    )
    _DOMAIN = re.compile(r"(?<![@\w])(?:https?://)?(?:www\.)?([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})(?![\w])", re.I)
    _ROLE_OR_DESCRIPTION = re.compile(
        r"\b(?:builder|engineer|developer|architect|manager|director|founder|president|vp|"
        r"banking|solution|services|platform|technology|operations|development|on-chain|blockchain|remote|hybrid)\b", re.I,
    )

    def __init__(self, model: Any = None):
        # The selected PII Edge model does not reliably recognize English names,
        # organizations, or institutions in all document layouts. Keep these
        # high-precision document cues local and dependency-free.
        self._model = model

    def detect(self, text: str) -> list[dict[str, Any]]:
        if not isinstance(text, str):
            raise ValueError("English entity detector input must be text.")
        if len(text.encode("utf-8", errors="replace")) > self.MAX_TEXT_BYTES:
            raise ValueError("The English entity detector input contains too much text.")

        matches = []
        seen = set()
        offset = 0
        first_content_line = True
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            leading = len(line) - len(line.lstrip())
            if not stripped:
                offset += len(line)
                continue

            is_header = first_content_line and bool(self._HEADER_NAME.fullmatch(stripped))
            first_content_line = False
            person_field = self._PERSON_FIELD.search(stripped)
            organization_field = self._ORGANIZATION_FIELD.search(stripped)
            has_institution = bool(self._INSTITUTION.search(stripped))
            has_company_suffix = bool(self._CORPORATE_SUFFIX.search(stripped))
            domain = self._DOMAIN.search(stripped) if "@" not in stripped else None

            if is_header:
                self._append(matches, seen, stripped, "person", offset + leading)
            if person_field:
                value = person_field.group("value")
                self._append(matches, seen, value, "person", offset + leading + person_field.start("value"))

            if organization_field:
                value = organization_field.group("value").strip()
                value_start = organization_field.start("value") + len(organization_field.group("value")) - len(organization_field.group("value").lstrip())
                self._append(matches, seen, value, "organization", offset + leading + value_start)
            elif has_institution:
                self._append(matches, seen, stripped, "organization", offset + leading)
            elif has_company_suffix:
                self._append(matches, seen, stripped, "organization", offset + leading)
            elif domain:
                prefix = stripped[:domain.start(1)].strip().rstrip("(").strip()
                if prefix.lower() in {"http://", "https://", "http://www.", "https://www.", "www."}:
                    prefix = ""
                value = prefix or domain.group(1)
                self._append(matches, seen, value, "organization", offset + leading + stripped.find(value))

            doc = self._model(stripped) if self._model is not None else None
            if "," in stripped and not (has_institution or has_company_suffix):
                offset += len(line)
                continue

            for entity in getattr(doc, "ents", ()):
                start, end = getattr(entity, "start_char", None), getattr(entity, "end_char", None)
                label = getattr(entity, "label_", "")
                value = getattr(entity, "text", "")
                if (
                    isinstance(start, bool) or not isinstance(start, int)
                    or isinstance(end, bool) or not isinstance(end, int)
                    or not 0 <= start < end <= len(stripped)
                    or value != stripped[start:end]
                ):
                    continue
                if has_institution:
                    kind, value, start, end = "organization", stripped, 0, len(stripped)
                elif label in {"ORG", "FAC"}:
                    if not has_company_suffix and self._ROLE_OR_DESCRIPTION.search(stripped):
                        continue
                    kind = "organization"
                elif label == "PERSON":
                    if self._ROLE_OR_DESCRIPTION.search(value):
                        continue
                    if domain:
                        kind = "organization"
                        value = stripped[:domain.start(1)].strip().rstrip("(").strip() or domain.group(1)
                        start = stripped.find(value)
                        end = start + len(value)
                    else:
                        kind = "person"
                else:
                    continue
                self._append(matches, seen, value, kind, offset + leading + start, end=end + offset + leading)
            offset += len(line)

        matches.sort(key=lambda item: (item["_start"], item["_end"], item["type"]))
        return matches

    @staticmethod
    def _append(matches, seen, value, kind, start, end=None):
        if not value:
            return
        end = start + len(value) if end is None else end
        key = (start, end, kind)
        if key in seen:
            return
        seen.add(key)
        matches.append({
            "type": kind,
            "label": "Person name" if kind == "person" else "Organization or institution",
            "confidence": "possible",
            "value": value,
            "_start": start,
            "_end": end,
            "_source": "heuristic",
            "_validation": "context",
            "_score": 0.6,
        })
