"""Evaluate local PII detector spans against the synthetic labelled corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / "tests/fixtures/pii-eval/manifest.jsonl"
MANIFEST_VERSION = "1.1.0"
SUPPORTED_LANGUAGES = {"en", "es", "fr", "de", "pt"}
TYPE_MAP = {
    "PERSON": "person", "PERSON_NAME": "person", "FULL_NAME": "person", "NAME": "person",
    "EMAIL": "email", "EMAIL_ADDRESS": "email", "PHONE": "phone", "PHONE_NUMBER": "phone",
    "STREET_ADDRESS": "address", "ADDRESS": "address", "POSTAL_CODE": "address",
    "GOVERNMENT_ID": "tax_id", "NATIONAL_ID_NUMBER": "tax_id", "TAX_ID": "tax_id", "PASSPORT_NUMBER": "passport",
    "BANK_ACCOUNT": "iban", "ACCOUNT_NUMBER": "iban", "IBAN": "iban", "DATE_OF_BIRTH": "dob",
    "USERNAME": "username", "IP_ADDRESS": "ip_address", "CREDIT_CARD": "card", "PAYMENT_CARD": "card",
    "SSN": "ssn", "AADHAAR": "tax_id", "PAN": "tax_id", "GSTIN": "tax_id",
}


def load_records(split: str) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line]
    selected = [item for item in records if split == "all" or item["split"] == split]
    seen_families: dict[str, str] = {}
    for item in records:
        prior = seen_families.setdefault(item["family"], item["split"])
        if prior != item["split"]:
            raise ValueError(f"Template family crosses data splits: {item['family']}")
        for entity in item["entities"]:
            start, end, value = entity["start"], entity["end"], entity["value"]
            if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(item["text"])):
                raise ValueError(f"Invalid entity offsets in {item['id']}")
            if item["text"][start:end] != value:
                raise ValueError(f"Entity value and offsets disagree in {item['id']}")
    return selected


class Baseline:
    name = "officekit-regex"

    def detect(self, text: str) -> list[dict[str, Any]]:
        from officekit.engines.engine_pii_redaction import PiiRedactionEngine

        return [
            {"type": match["type"], "start": match["_start"], "end": match["_end"], "score": 1.0,
             "_source": "baseline", "_validation": "checksum" if match["type"] in {"card", "iban"} else "format"}
            for match in PiiRedactionEngine._find_matches(text, "Eval", "eval")
        ]


class MaskFlow:
    name = "maskflow-patterns+india"

    def __init__(self, use_ner: bool):
        from maskflow import detect
        from maskflow_core.detection import detect_patterns_only

        self.detect_function = detect if use_ner else detect_patterns_only
        if use_ner:
            self.name = "maskflow-full-ner"

    def detect(self, text: str) -> list[dict[str, Any]]:
        spans = self.detect_function(text)
        output = []
        for span in spans:
            kind = TYPE_MAP.get(str(span.entity_type.value).upper())
            if kind is None:
                continue
            validation = "checksum" if span.validated else "format" if span.recognizer.startswith("pattern:") else "context"
            output.append({"type": kind, "start": span.start, "end": span.end, "score": span.score,
                           "_source": "regional" if span.entity_type.value in {"AADHAAR", "PAN", "GSTIN"} else "structural",
                           "_validation": validation})
        return output


class Fastino:
    name = "fastino-gliner2-pii-multi"

    def __init__(self, model_path: Path, threshold: float):
        from officekit.engines.pii_context_detector import PiiContextDetector

        self.detector = PiiContextDetector.from_local_path(model_path, threshold)

    def detect(self, text: str) -> list[dict[str, Any]]:
        return [
            {"type": span["type"], "start": span["_start"], "end": span["_end"], "score": span["_score"],
             "_source": "neural", "_validation": "none"}
            for span in self.detector.detect(text)
        ]


class Knowledgator:
    name = "knowledgator-gliner-pii-edge-v1.0-onnx-int8"

    def __init__(self, model_path: Path, threshold: float):
        from officekit.engines.pii_context_detector import PiiContextDetector

        self.detector = PiiContextDetector.from_local_path(model_path, threshold)

    def detect(self, text: str) -> list[dict[str, Any]]:
        return [
            {"type": span["type"], "start": span["_start"], "end": span["_end"],
             "score": span["_score"], "_source": "neural", "_validation": "none"}
            for span in self.detector.detect(text)
        ]


class CombinedCandidate:
    def __init__(self, maskflow: MaskFlow, fastino: Fastino):
        self.maskflow = maskflow
        self.fastino = fastino
        self.name = f"{maskflow.name}+{fastino.name}"

    def detect(self, text: str) -> list[dict[str, Any]]:
        return self.maskflow.detect(text) + self.fastino.detect(text)


class Hybrid:
    def __init__(self, candidate: Any):
        self.candidate = candidate
        self.name = f"officekit+{candidate.name}"

    def detect_raw(self, text: str) -> list[dict[str, Any]]:
        baseline = Baseline().detect(text)
        candidate = self.candidate.detect(text)
        return baseline + candidate

    def detect(self, text: str) -> list[dict[str, Any]]:
        return self.resolve(text, self.detect_raw(text))

    @staticmethod
    def resolve(text: str, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from officekit.engines.pii_span_resolver import resolve_spans

        internal = []
        for item in raw:
            internal.append({"type": item["type"], "label": item["type"], "confidence": "high" if item["_validation"] in {"checksum", "format"} else "possible",
                             "value": text[item["start"]:item["end"]], "_start": item["start"], "_end": item["end"],
                             "_source": item["_source"], "_validation": item["_validation"], "_score": item["score"]})
        return [{"type": item["type"], "start": item["_start"], "end": item["_end"], "score": item["_score"]}
                for item in resolve_spans(text, internal, "eval")]


def score_records(records: list[dict[str, Any]], predictions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    counters: dict[str, Counter] = defaultdict(Counter)
    false_positive_words: dict[str, int] = defaultdict(int)
    document_misses = 0
    total_words = 0
    covered_characters = 0
    gold_characters = 0
    grouped = defaultdict(int)
    group_words = defaultdict(int)
    per_record = []
    for record in records:
        gold = record["entities"]
        predicted = predictions[record["id"]]
        matched: set[int] = set()
        record_tp = record_fp = 0
        for guess in predicted:
            key = (record["language"], guess["type"])
            counters[key]["predicted"] += 1
            exact = next((i for i, item in enumerate(gold) if i not in matched and item["type"] == guess["type"] and item["start"] == guess["start"] and item["end"] == guess["end"]), None)
            if exact is not None:
                matched.add(exact)
                counters[key]["tp"] += 1
                record_tp += 1
            else:
                counters[key]["fp"] += 1
                record_fp += 1
        for index, item in enumerate(gold):
            key = (record["language"], item["type"])
            counters[key]["support"] += 1
            if index not in matched:
                counters[key]["fn"] += 1
        gold_positions = {position for item in gold for position in range(item["start"], item["end"])}
        predicted_positions = {position for guess in predicted for position in range(guess["start"], guess["end"])}
        covered_characters += len(gold_positions & predicted_positions)
        gold_characters += len(gold_positions)
        if len(matched) != len(gold):
            document_misses += 1
        words = max(1, len(record["text"].split()))
        total_words += words
        false_positive_words[record["language"]] += words
        grouped[(record["text_kind"], "tp")] = grouped[(record["text_kind"], "tp")] + record_tp
        grouped[(record["text_kind"], "fp")] = grouped[(record["text_kind"], "fp")] + record_fp
        grouped[(record["text_kind"], "fn")] = grouped[(record["text_kind"], "fn")] + len(gold) - len(matched)
        grouped[(record["text_kind"], "support")] = grouped[(record["text_kind"], "support")] + len(gold)
        group_words[record["text_kind"]] += words
        per_record.append({"id": record["id"], "language": record["language"], "split": record["split"], "text_kind": record["text_kind"], "gold": len(gold), "predicted": len(predicted), "tp": record_tp, "fp": record_fp, "fn": len(gold) - len(matched)})

    metrics = {}
    micro = Counter()
    for (language, entity_type), values in sorted(counters.items()):
        tp, fp, fn = values["tp"], values["fp"], values["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        metrics[f"{language}/{entity_type}"] = {
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "support": values["support"], "tp": tp, "fp": fp, "fn": fn,
        }
        micro.update(values)
    tp, fp, fn = micro["tp"], micro["fp"], micro["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    by_text_kind = {}
    for text_kind in sorted(group_words):
        values = grouped
        kind_tp, kind_fp, kind_fn = (values[(text_kind, key)] for key in ("tp", "fp", "fn"))
        kind_precision = kind_tp / (kind_tp + kind_fp) if kind_tp + kind_fp else 0.0
        kind_recall = kind_tp / (kind_tp + kind_fn) if kind_tp + kind_fn else 0.0
        by_text_kind[text_kind] = {
            "precision": kind_precision, "recall": kind_recall,
            "f1": 2 * kind_precision * kind_recall / (kind_precision + kind_recall) if kind_precision + kind_recall else 0.0,
            "support": values[(text_kind, "support")], "tp": kind_tp, "fp": kind_fp, "fn": kind_fn,
            "false_positives_per_1000_words": kind_fp * 1000 / group_words[text_kind] if group_words[text_kind] else 0.0,
        }
    return {
        "micro": {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                  "support": micro["support"], "tp": tp, "fp": fp, "fn": fn},
        "per_language_entity": metrics,
        "by_text_kind": by_text_kind,
        "sensitive_character_coverage": covered_characters / gold_characters if gold_characters else 0.0,
        "false_positives_per_1000_words_by_language": {
            language: sum(values["fp"] for (lang, _entity), values in counters.items() if lang == language) * 1000 / words
            for language, words in sorted(false_positive_words.items())
        },
        "documents_with_miss": document_misses,
        "document_count": len(records),
        "false_positives_per_1000_words": fp * 1000 / total_words if total_words else 0.0,
        "per_record": per_record,
    }


def resolution_outcomes(records: list[dict[str, Any]], raw: dict[str, list[dict[str, Any]]],
                        resolved: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Summarize resolver conflicts and classification choices against exact labels."""
    totals = Counter()
    per_record = {}
    for record in records:
        candidates = raw[record["id"]]
        outputs = resolved[record["id"]]
        exact_duplicates = nested_overlaps = partial_overlaps = 0
        for index, left in enumerate(candidates):
            for right in candidates[index + 1:]:
                start = max(left["start"], right["start"])
                end = min(left["end"], right["end"])
                if start >= end:
                    continue
                left_span = (left["start"], left["end"])
                right_span = (right["start"], right["end"])
                if left_span == right_span:
                    exact_duplicates += 1
                elif left["start"] <= right["start"] and left["end"] >= right["end"] or right["start"] <= left["start"] and right["end"] >= left["end"]:
                    nested_overlaps += 1
                else:
                    partial_overlaps += 1
        merged_components = max(0, len(candidates) - len(outputs))
        incorrect_overrides = 0
        for output in outputs:
            component = [item for item in candidates
                         if max(item["start"], output["start"]) < min(item["end"], output["end"])]
            gold_types = {gold["type"] for gold in record["entities"] for item in component
                          if gold["start"] == item["start"] and gold["end"] == item["end"] and gold["type"] == item["type"]}
            if gold_types and output["type"] not in gold_types and any(item["type"] in gold_types for item in component):
                incorrect_overrides += 1
        values = {
            "exact_duplicate_pairs": exact_duplicates,
            "nested_overlap_pairs": nested_overlaps,
            "partial_overlap_pairs": partial_overlaps,
            "merged_components": merged_components,
            "incorrect_primary_type_overrides": incorrect_overrides,
        }
        per_record[record["id"]] = values
        totals.update(values)
    return {"totals": dict(totals), "per_record": per_record}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    parser.add_argument("--language", choices=tuple(sorted({"en", "es", "fr", "de", "pt", "ar", "hi", "zh", "ja"})))
    parser.add_argument("--model-path", type=Path, help="Local model directory; no download is performed")
    parser.add_argument("--candidate", choices=("baseline", "maskflow-patterns", "maskflow-ner", "fastino", "knowledgator", "knowledgator-combined", "combined"), default="baseline")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be in [0,1]")
    records = load_records(args.split)
    if args.language:
        records = [record for record in records if record["language"] == args.language]
    if args.candidate.startswith("knowledgator") and args.language != "en":
        parser.error("The Knowledgator Edge candidate is evaluated only with --language en")
    started = time.perf_counter()
    if args.candidate == "baseline":
        detector = Baseline()
    elif args.candidate in {"maskflow-patterns", "maskflow-ner"}:
        detector = Hybrid(MaskFlow(use_ner=args.candidate == "maskflow-ner"))
    elif args.candidate == "fastino":
        if args.model_path is None:
            parser.error("--model-path is required for --candidate fastino")
        detector = Hybrid(Fastino(args.model_path, args.threshold))
    elif args.candidate == "knowledgator":
        if args.model_path is None:
            parser.error("--model-path is required for --candidate knowledgator")
        detector = Hybrid(Knowledgator(args.model_path, args.threshold))
    elif args.candidate == "knowledgator-combined":
        if args.model_path is None:
            parser.error("--model-path is required for --candidate knowledgator-combined")
        detector = Hybrid(CombinedCandidate(MaskFlow(use_ner=False), Knowledgator(args.model_path, args.threshold)))
    else:
        if args.model_path is None:
            parser.error("--model-path is required for --candidate combined")
        detector = Hybrid(CombinedCandidate(MaskFlow(use_ner=True), Fastino(args.model_path, args.threshold)))
    load_seconds = time.perf_counter() - started
    predictions, raw_predictions, durations = {}, {}, []
    for record in records:
        begin = time.perf_counter()
        if isinstance(detector, Hybrid):
            raw = detector.detect_raw(record["text"])
            raw_predictions[record["id"]] = raw
            predictions[record["id"]] = detector.resolve(record["text"], raw)
        else:
            raw_predictions[record["id"]] = detector.detect(record["text"])
            predictions[record["id"]] = raw_predictions[record["id"]]
        durations.append(time.perf_counter() - begin)
    scored = {"raw": score_records(records, raw_predictions), "resolved": score_records(records, predictions),
              "resolution_outcomes": resolution_outcomes(records, raw_predictions, predictions)}
    result = {
        "corpus": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), "version": MANIFEST_VERSION},
        "detector": detector.name,
        "model_path": str(args.model_path) if args.model_path else None,
        "threshold": args.threshold if args.model_path else None,
        "split": args.split,
        "language": args.language,
        "environment": {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "cpu_count": __import__("os").cpu_count()},
        "timing": {"model_load_seconds": load_seconds, "mean_seconds_per_document": statistics.mean(durations) if durations else 0.0,
                   "p95_seconds_per_document": sorted(durations)[max(0, min(len(durations) - 1, int((len(durations) * 0.95 + 0.999999)) - 1))] if durations else 0.0},
        "metrics": scored,
        "predictions": {"raw": raw_predictions, "resolved": predictions},
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("detector", "split", "corpus", "timing")}, ensure_ascii=False))
    print(json.dumps({"raw": scored["raw"]["micro"], "resolved": scored["resolved"]["micro"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
