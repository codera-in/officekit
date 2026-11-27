"""Deterministic evidence ranking and connected sensitive-span resolution."""

from __future__ import annotations

import hashlib
from typing import Any


_VALIDATION_RANK = {"none": 0, "context": 1, "format": 2, "checksum": 3}
_SOURCE_RANK = {"heuristic": 1, "neural": 1, "baseline": 2, "structural": 2, "regional": 3}
_TYPE_ALIASES = {"payment_card": "card", "credit_card": "card", "phone_number": "phone", "full_name": "person"}
_TYPE_SPECIFICITY = {
    "address": 1, "date": 2, "dob": 3, "person": 3, "organization": 3, "username": 4,
    "card": 4, "email": 4, "iban": 4, "passport": 4, "phone": 4,
    "ssn": 4, "tax_id": 4, "ip_address": 5,
}


def resolve_spans(text: str, spans: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    """Merge duplicate or overlapping findings while preserving complete coverage."""
    if not isinstance(text, str) or not isinstance(group_key, str):
        raise ValueError("Resolver text and group identity must be strings.")
    validated = [_validate_span(text, span, group_key) for span in spans]
    validated.sort(key=lambda item: (item["_start"], item["_end"], item["type"], item["_source"], -item["_score"]))
    components: list[list[dict[str, Any]]] = []
    component_end = -1
    for item in validated:
        if not components or item["_start"] >= component_end:
            components.append([item])
            component_end = item["_end"]
        else:
            components[-1].append(item)
            component_end = max(component_end, item["_end"])

    results = []
    for component in components:
        primary = min(component, key=lambda item: _priority_key(item, text, component))
        start = min(item["_start"] for item in component)
        end = max(item["_end"] for item in component)
        coverage = _merge_coverage(component)
        evidence = sorted({_evidence_key(item): _evidence(item) for item in component}.values(), key=lambda item: (
            item["start"], item["end"], item["source"], item["type"], item["validation"], item["score"],
        ))
        value = text[start:end]
        identifier = hashlib.sha256(f"{group_key}\0{primary['type']}\0{start}\0{end}\0{value}".encode("utf-8")).hexdigest()[:24]
        result = dict(primary)
        result.update({"id": identifier, "value": value, "_start": start, "_end": end, "_group": group_key,
                      "_coverage": coverage, "_evidence": evidence})
        results.append(result)
    return results


def _validate_span(text: str, span: Any, group_key: str) -> dict[str, Any]:
    if not isinstance(span, dict):
        raise ValueError("A detected span must be an object.")
    start, end = span.get("_start", span.get("start")), span.get("_end", span.get("end"))
    kind = span.get("type")
    value = span.get("value", text[start:end] if isinstance(start, int) and isinstance(end, int) else None)
    source = span.get("_source", span.get("source", "neural"))
    validation = span.get("_validation", span.get("validation", "none"))
    score = span.get("_score", span.get("score", 1.0))
    if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int):
        raise ValueError("A detected span must have integer offsets.")
    if not 0 <= start < end <= len(text) or value != text[start:end]:
        raise ValueError("A detected span does not match the original text.")
    if not isinstance(kind, str) or not kind or source not in _SOURCE_RANK or validation not in _VALIDATION_RANK:
        raise ValueError("A detected span has an unsupported type or evidence source.")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise ValueError("A detected span score must be between zero and one.")
    result = dict(span)
    result.update({"type": _TYPE_ALIASES.get(kind, kind), "value": value, "_start": start, "_end": end,
                   "_group": group_key, "_source": source, "_validation": validation, "_score": float(score)})
    result.setdefault("label", result["type"])
    result.setdefault("confidence", "high" if validation in {"format", "checksum"} else "possible")
    return result


def _priority_key(span: dict[str, Any], text: str, component: list[dict[str, Any]]) -> tuple[Any, ...]:
    # A Luhn-valid substring inside an explicitly international phone is not
    # enough evidence to relabel the complete phone as a payment card.
    phone_contains_card = span["type"] == "phone" and text[span["_start"]:span["_start"] + 1] == "+" and any(
        item["type"] == "card" and span["_start"] <= item["_start"] and item["_end"] <= span["_end"]
        and (item["_start"], item["_end"]) != (span["_start"], span["_end"])
        for item in component
    )
    ip_covers_address = span["type"] == "ip_address" and any(
        item["type"] == "address" and span["_start"] <= item["_start"] and item["_end"] <= span["_end"]
        for item in component
    )
    return (
        -int(phone_contains_card),
        -int(ip_covers_address),
        -_VALIDATION_RANK[span["_validation"]], -_SOURCE_RANK[span["_source"]],
        -_TYPE_SPECIFICITY.get(span["type"], 0), -span["_score"],
        -(span["_end"] - span["_start"]), span["type"], span["_start"], span["_end"],
    )


def _merge_coverage(component: list[dict[str, Any]]) -> list[tuple[int, int]]:
    intervals = sorted((item["_start"], item["_end"]) for item in component)
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _evidence(span: dict[str, Any]) -> dict[str, Any]:
    return {"source": span["_source"], "type": span["type"], "validation": span["_validation"],
            "score": span["_score"], "start": span["_start"], "end": span["_end"]}


def _evidence_key(span: dict[str, Any]) -> tuple[Any, ...]:
    return (span["_source"], span["type"], span["_validation"], span["_score"], span["_start"], span["_end"])
