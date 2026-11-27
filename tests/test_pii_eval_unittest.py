"""Checks that the labelled PII evaluation corpus and scorer enforce exact spans."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pii_eval", ROOT / "scripts/pii_eval.py")
pii_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pii_eval)


def test_manifest_has_verified_offsets_and_split_families():
    records = pii_eval.load_records("all")
    assert len(records) == 40
    assert {record["language"] for record in records} == {"en", "es", "fr", "de", "pt", "ar", "hi", "zh", "ja"}
    assert {record["split"] for record in records} == {"dev", "heldout"}
    assert {record["text_kind"] for record in records} == {"clean", "ocr_like"}
    for split in ("dev", "heldout"):
        assert {record["text_kind"] for record in records if record["split"] == split} == {"clean", "ocr_like"}


def test_scorer_requires_exact_entity_type_and_character_boundaries():
    record = {
        "id": "fixture", "language": "en", "split": "heldout", "text_kind": "clean",
        "text": "Name: Alex Sample", "entities": [{"type": "person", "start": 6, "end": 17, "value": "Alex Sample"}],
    }
    exact = pii_eval.score_records([record], {"fixture": [{"type": "person", "start": 6, "end": 17}]})
    assert exact["micro"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 1, "tp": 1, "fp": 0, "fn": 0}
    partial = pii_eval.score_records([record], {"fixture": [{"type": "person", "start": 6, "end": 16}]})
    assert partial["micro"]["tp"] == 0
    assert partial["micro"]["fp"] == 1
    assert partial["micro"]["fn"] == 1
    assert partial["sensitive_character_coverage"] == 10 / 11
    wrong_type = pii_eval.score_records([record], {"fixture": [{"type": "address", "start": 6, "end": 17}]})
    assert wrong_type["micro"]["f1"] == 0.0
    assert wrong_type["documents_with_miss"] == 1


def test_resolution_outcomes_count_overlap_shapes_and_wrong_primary_type():
    record = {
        "id": "overlap", "language": "en", "split": "dev", "text_kind": "clean",
        "text": "Alex Sample", "entities": [{"type": "person", "start": 0, "end": 11, "value": "Alex Sample"}],
    }
    raw = {"overlap": [
        {"type": "person", "start": 0, "end": 11},
        {"type": "person", "start": 0, "end": 11},
        {"type": "address", "start": 0, "end": 5},
        {"type": "phone", "start": 4, "end": 11},
    ]}
    resolved = {"overlap": [{"type": "address", "start": 0, "end": 11}]}

    outcomes = pii_eval.resolution_outcomes([record], raw, resolved)

    assert outcomes["totals"] == {
        "exact_duplicate_pairs": 1,
        "nested_overlap_pairs": 4,
        "partial_overlap_pairs": 1,
        "merged_components": 3,
        "incorrect_primary_type_overrides": 1,
    }
