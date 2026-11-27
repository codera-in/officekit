"""Hybrid detector adapter and span-resolution safety checks."""

import pytest

from officekit.engines.pii_context_detector import PiiContextDetector
from officekit.engines.pii_span_resolver import resolve_spans


def span(text, kind, start, end, source="neural", validation="none", score=0.7):
    return {"type": kind, "label": kind, "confidence": "possible", "value": text[start:end], "_start": start,
            "_end": end, "_group": "group", "_source": source, "_validation": validation, "_score": score}


def test_resolver_collapses_duplicates_and_keeps_checksum_evidence():
    text = "Card 4111111111111111"
    structural = span(text, "card", 5, 21, "baseline", "checksum", 1.0)
    neural = span(text, "payment_card", 5, 21)
    resolved = resolve_spans(text, [neural, structural], "group")
    assert len(resolved) == 1
    assert resolved[0]["type"] == "card"
    assert resolved[0]["_validation"] == "checksum"
    assert {item["source"] for item in resolved[0]["_evidence"]} == {"baseline", "neural"}
    assert resolved[0]["id"] == resolve_spans(text, [structural, neural], "group")[0]["id"]


def test_resolver_prefers_specific_ip_type_over_broad_address_label():
    text = "192.0.2.18"
    resolved = resolve_spans(text, [
        span(text, "address", 0, len(text), "baseline", "format", 1.0),
        span(text, "ip_address", 0, len(text), "structural", "format", 0.75),
    ], "group")

    assert len(resolved) == 1
    assert resolved[0]["type"] == "ip_address"
    assert {item["type"] for item in resolved[0]["_evidence"]} == {"address", "ip_address"}


def test_model_ip_candidate_overrides_unvalidated_broad_address_cue():
    text = "192.0.2.18"
    resolved = resolve_spans(text, [
        span(text, "address", 0, len(text), "baseline", "context", 1.0),
        span(text, "ip_address", 0, len(text), "neural", "none", 0.7),
    ], "group")

    assert len(resolved) == 1
    assert resolved[0]["type"] == "ip_address"


def test_resolver_keeps_country_code_phone_classification_over_nested_luhn_match():
    text = "+86 130 0000 0101"
    resolved = resolve_spans(text, [
        span(text, "phone", 0, len(text), "baseline", "format", 1.0),
        span(text, "card", 1, len(text), "baseline", "checksum", 1.0),
    ], "group")

    assert len(resolved) == 1
    assert resolved[0]["type"] == "phone"
    assert {item["type"] for item in resolved[0]["_evidence"]} == {"phone", "card"}


def test_resolver_uses_stronger_nested_classification_and_preserves_coverage():
    text = "Maria 4111111111111111"
    resolved = resolve_spans(text, [span(text, "person", 0, 22), span(text, "card", 6, 22, "baseline", "checksum", 1.0)], "group")
    assert len(resolved) == 1
    assert resolved[0]["type"] == "card"
    assert resolved[0]["_coverage"] == [(0, 22)]


def test_resolver_unions_partial_overlaps_but_keeps_adjacent_spans_separate():
    text = "abcdefghij"
    overlapped = resolve_spans(text, [span(text, "person", 0, 6), span(text, "address", 4, 10)], "group")
    assert len(overlapped) == 1
    assert overlapped[0]["_coverage"] == [(0, 10)]
    adjacent = resolve_spans(text, [span(text, "person", 0, 5), span(text, "address", 5, 10)], "group")
    assert len(adjacent) == 2


def test_resolver_rejects_invalid_offsets_and_value_mismatches():
    text = "safe text"
    with pytest.raises(ValueError):
        resolve_spans(text, [span(text, "person", 0, 99)], "group")
    wrong = span(text, "person", 0, 4)
    wrong["value"] = "false"
    with pytest.raises(ValueError):
        resolve_spans(text, [wrong], "group")


@pytest.mark.parametrize("changes", [
    {"_source": "remote"}, {"_validation": "guessed"}, {"_score": 1.1}, {"_score": True},
    {"type": ""}, {"_start": True},
])
def test_resolver_rejects_invalid_evidence(changes):
    text = "safe text"
    finding = span(text, "person", 0, 4)
    finding.update(changes)
    with pytest.raises(ValueError):
        resolve_spans(text, [finding], "group")


def test_resolver_ids_change_with_group_but_not_input_order():
    text = "abcde"
    first = span(text, "person", 0, 3)
    second = span(text, "address", 2, 5)
    result = resolve_spans(text, [first, second], "one")
    reverse = resolve_spans(text, [second, first], "one")
    other_group = resolve_spans(text, [first, second], "two")
    assert [item["id"] for item in result] == [item["id"] for item in reverse]
    assert result[0]["id"] != other_group[0]["id"]


def test_context_adapter_validates_character_offsets_scores_and_label_mapping():
    class FakeModel:
        def extract_entities(self, text, labels, **options):
            assert labels
            assert options["include_spans"] is True
            return {"entities": [{"person": [{"text": "Ana", "start": 0, "end": 3, "confidence": 0.91}],
                                  "phone_number": [{"text": "123", "start": 4, "end": 7, "confidence": 0.62}]}]}

    detector = PiiContextDetector(model=FakeModel())
    found = detector.detect("Ana 123")
    assert [(item["type"], item["_start"], item["_end"]) for item in found] == [("person", 0, 3), ("phone", 4, 7)]
    assert all(item["_source"] == "neural" for item in found)


def test_context_adapter_rejects_out_of_bounds_span_and_bad_score():
    class FakeModel:
        def __init__(self, score, end):
            self.score, self.end = score, end

        def extract_entities(self, text, labels, **options):
            return {"entities": [{"person": [{"text": "Ana", "start": 0, "end": self.end, "confidence": self.score}]}]}

    for score, end in ((1.1, 3), (0.5, 8)):
        with pytest.raises(ValueError):
            PiiContextDetector(model=FakeModel(score, end)).detect("Ana")


def test_context_adapter_applies_threshold_and_ignores_unknown_labels():
    class FakeModel:
        def extract_entities(self, text, labels, **options):
            return {"entities": [{"person": [
                {"text": "Ana", "start": 0, "end": 3, "confidence": 0.4},
                {"text": "Bob", "start": 4, "end": 7, "confidence": 0.8},
            ], "medical condition": [{"text": "flu", "start": 8, "end": 11, "confidence": 0.99}]}]}

    found = PiiContextDetector(model=FakeModel(), threshold=0.5).detect("Ana Bob flu")
    assert [(item["value"], item["_score"]) for item in found] == [("Bob", 0.8)]


def test_context_adapter_rejects_model_failures_and_malformed_results():
    class FailedModel:
        def extract_entities(self, *args, **kwargs):
            raise OSError("secret model details")

    with pytest.raises(RuntimeError, match="failed during detection") as error:
        PiiContextDetector(model=FailedModel()).detect("text")
    assert "secret model details" not in str(error.value)

    class MalformedModel:
        def extract_entities(self, *args, **kwargs):
            return {"entities": [{"person": "not-a-span-list"}]}

    with pytest.raises(ValueError, match="malformed entity results"):
        PiiContextDetector(model=MalformedModel()).detect("text")


@pytest.mark.parametrize("threshold", [-0.1, 1.1, True, "0.5"])
def test_context_adapter_rejects_invalid_thresholds(threshold):
    with pytest.raises(ValueError, match="threshold"):
        PiiContextDetector(threshold=threshold)


def test_context_adapter_is_unavailable_without_a_loaded_local_model(tmp_path):
    from officekit.engines.pii_context_detector import PiiContextModelUnavailable

    with pytest.raises(PiiContextModelUnavailable, match="directory is unavailable"):
        PiiContextDetector.from_local_path(tmp_path / "missing")
    with pytest.raises(PiiContextModelUnavailable, match="model is unavailable"):
        PiiContextDetector().detect("text")


@pytest.mark.parametrize("threads", [0, 5, True, 1.5])
def test_context_adapter_rejects_unsafe_thread_counts(tmp_path, threads):
    with pytest.raises(ValueError, match="thread count"):
        PiiContextDetector.from_local_path(tmp_path, threads=threads)


def test_onnx_adapter_chunks_long_text_with_global_offsets_and_overlap():
    class FakeOnnxModel:
        def predict_entities(self, text, _labels, threshold):
            assert threshold == 0.5
            start = text.find("Nora Scott")
            if start < 0:
                return []
            return [{"label": "name", "text": "Nora Scott", "start": start,
                     "end": start + len("Nora Scott"), "score": 0.9}]

    text = ("routine " * 140) + "Nora Scott" + (" routine" * 300)
    detector = PiiContextDetector(model=FakeOnnxModel(), backend="gliner-onnx")
    findings = detector.detect(text)
    expected = text.index("Nora Scott")

    assert len(findings) >= 1
    assert all(item["_start"] == expected and item["_end"] == expected + 10 for item in findings)
    windows = list(detector._onnx_windows(text))
    assert all(end - start <= detector.ONNX_WINDOW_CHARS for start, end in windows)
    assert all(current[0] < previous[1] for previous, current in zip(windows, windows[1:]))


def test_context_adapter_routes_to_local_cpp_runtime_and_normalizes_labels(monkeypatch, tmp_path):
    import officekit.engines.pii_context_detector as module

    model_path = tmp_path / "model"
    (model_path / "onnx").mkdir(parents=True)
    (model_path / "onnx/model_quint8.onnx").touch()
    (model_path / "tokenizer.json").touch()
    (model_path / "gliner_config.json").touch()
    binary = tmp_path / "pii-daemon"
    binary.touch()

    class FakeCppClient:
        def __init__(self, *_args):
            pass

        def predict_entities(self, text, _labels, threshold):
            start = text.index("Nora Scott")
            return [{"label": "name", "text": "Nora Scott", "start": start,
                     "end": start + 10, "score": 0.91}]

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_RUNTIME", "cpp")
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_CPP_BINARY", str(binary))
    monkeypatch.setattr(module, "_GlinerCppClient", FakeCppClient)
    detector = PiiContextDetector.from_local_path(model_path, threshold=0.5, threads=4)

    finding = detector.detect("Please ask Nora Scott for help.")[0]
    assert detector._backend == "gliner-cpp"
    assert finding["type"] == "person"
    assert finding["value"] == "Nora Scott"


def test_cpp_client_converts_utf8_byte_offsets_to_python_character_offsets():
    import queue
    import threading
    from officekit.engines.pii_context_detector import _GlinerCppClient

    class FakeStdin:
        def write(self, _value):
            pass

        def flush(self):
            pass

    class FakeStdout:
        def __init__(self):
            self._lines = iter([b"name\t2\t6\t0.9\n", b".\n"])

        def readline(self):
            return next(self._lines)

    class FakeProcess:
        stdin = FakeStdin()
        stdout = FakeStdout()

        @staticmethod
        def poll():
            return None

    client = object.__new__(_GlinerCppClient)
    client._process = FakeProcess()
    client._lock = threading.Lock()
    client._stdout_lines = queue.Queue()
    client._stdout_lines.put(b"name\t2\t6\t0.9\n")
    client._stdout_lines.put(b".\n")
    finding = client.predict_entities("éNora", ["name"], 0.5)[0]

    assert (finding["start"], finding["end"], finding["text"]) == (1, 5, "Nora")


@pytest.mark.parametrize("ready", [False, True])
def test_cpp_client_terminates_a_stuck_runtime_within_timeout(monkeypatch, tmp_path, ready):
    import threading
    import officekit.engines.pii_context_detector as module

    class SilentStream:
        def __init__(self):
            self.stopped = threading.Event()

        def __iter__(self):
            if ready:
                yield b"READY\n"
            self.stopped.wait()

    class FakeStdin:
        def write(self, _value):
            pass

        def flush(self):
            pass

    class FakeProcess:
        def __init__(self):
            self.stdout = SilentStream()
            self.stdin = FakeStdin()
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True
            self.stdout.stopped.set()

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminate()

    process = FakeProcess()
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx/model_quint8.onnx").touch()
    (tmp_path / "tokenizer.json").touch()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(module._GlinerCppClient, "STARTUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(module._GlinerCppClient, "INFERENCE_TIMEOUT_SECONDS", 0.01)

    if not ready:
        with pytest.raises(module.PiiContextModelUnavailable, match="timed out"):
            module._GlinerCppClient(tmp_path, tmp_path, 1)
    else:
        client = module._GlinerCppClient(tmp_path, tmp_path, 1)
        with pytest.raises(module.PiiContextModelUnavailable, match="timed out"):
            client.predict_entities("Nora Scott", ["name"], 0.5)

    assert process.terminated


def test_cpp_client_terminates_before_closing_a_blocked_pipe():
    import queue
    import threading
    import time
    from officekit.engines.pii_context_detector import _GlinerCppClient

    events = []
    terminated = threading.Event()

    class BlockingPipe:
        def close(self):
            events.append("close")
            assert terminated.wait(0.5)

    class FakeProcess:
        stdin = BlockingPipe()
        stdout = None

        def poll(self):
            return 0 if terminated.is_set() else None

        def terminate(self):
            events.append("terminate")
            terminated.set()

        def wait(self, timeout=None):
            return 0

    client = object.__new__(_GlinerCppClient)
    client._process = FakeProcess()
    started = time.monotonic()
    client._stop_process()

    assert time.monotonic() - started < 0.2
    assert terminated.is_set()
    assert events[0] == "terminate"
    # Pipe cleanup is asynchronous but must start only after termination.
    for _ in range(100):
        if "close" in events:
            break
        time.sleep(0.001)
    assert "close" in events


def test_context_adapter_maps_username_and_ip_address_candidates_to_reviewable_types():
    class FakeModel:
        def predict_entities(self, text, _labels, **_options):
            return [
                {"label": "username", "start": 10, "end": 22, "score": 0.9, "text": "@sample_user"},
                {"label": "ip address", "start": 27, "end": 37, "score": 0.9, "text": "192.0.2.18"},
            ]

    detector = PiiContextDetector(model=FakeModel(), backend="gliner-cpp")
    findings = detector.detect("Username: @sample_user IP: 192.0.2.18")

    assert [(item["type"], item["value"]) for item in findings] == [
        ("username", "@sample_user"), ("ip_address", "192.0.2.18"),
    ]
