"""Strict local-only adapter for the POC's contextual PII model."""

from __future__ import annotations

import base64
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class PiiContextModelUnavailable(RuntimeError):
    """The configured local contextual detector cannot be loaded."""


class _GlinerCppClient:
    STARTUP_TIMEOUT_SECONDS = 30.0
    INFERENCE_TIMEOUT_SECONDS = 60.0
    MAX_PROTOCOL_LINE_BYTES = 65_536
    MAX_PROTOCOL_LINES = 2_002

    def __init__(self, executable: Path, model_path: Path, threads: int):
        model_file = model_path / "onnx/model_quint8.onnx"
        tokenizer_file = model_path / "tokenizer.json"
        if not model_file.is_file() or not tokenizer_file.is_file():
            raise PiiContextModelUnavailable("The local PII model files are incomplete.")
        try:
            self._process = subprocess.Popen(
                [str(executable), str(model_file), str(tokenizer_file), str(threads)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            self._lock = threading.Lock()
            self._stdout_lines: queue.Queue[bytes | None] = queue.Queue(maxsize=self.MAX_PROTOCOL_LINES)
            self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
            self._reader.start()
            ready = self._readline(self.STARTUP_TIMEOUT_SECONDS, "start")
            if ready != b"READY\n":
                self._stop_process()
                raise PiiContextModelUnavailable("The local native PII runtime did not start.")
        except PiiContextModelUnavailable:
            self._stop_process()
            raise
        except Exception as error:
            if hasattr(self, "_process"):
                self._stop_process()
            raise PiiContextModelUnavailable("The local native PII runtime could not start.") from error

    def _pump_stdout(self):
        try:
            if self._process.stdout is not None:
                for line in self._process.stdout:
                    self._stdout_lines.put(line)
        finally:
            self._stdout_lines.put(None)

    def _readline(self, timeout: float, phase: str) -> bytes:
        try:
            line = self._stdout_lines.get(timeout=timeout)
        except queue.Empty as error:
            self._stop_process()
            raise PiiContextModelUnavailable(f"The local native PII runtime timed out during {phase}.") from error
        if line is None:
            raise PiiContextModelUnavailable("The local native PII runtime stopped unexpectedly.")
        if len(line) > self.MAX_PROTOCOL_LINE_BYTES:
            self._stop_process()
            raise PiiContextModelUnavailable("The local native PII runtime returned an oversized result.")
        return line

    def _stop_process(self):
        process = getattr(self, "_process", None)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        except Exception:
            pass

        # Closing a buffered pipe can wait for a concurrent writer's lock. The
        # child is stopped first, and pipe closure is isolated so cleanup stays
        # bounded even if a broken runtime leaves a writer stuck.
        def close_pipes():
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass

        threading.Thread(target=close_pipes, daemon=True).start()

    def predict_entities(self, text: str, _labels: list[str], threshold: float) -> list[dict[str, Any]]:
        if self._process.poll() is not None or self._process.stdin is None or self._process.stdout is None:
            raise PiiContextModelUnavailable("The local native PII runtime is unavailable.")
        request = f"{threshold:.6f}\t".encode("ascii") + base64.b64encode(text.encode("utf-8")) + b"\n"
        rows = []
        try:
            with self._lock:
                write_complete = threading.Event()
                write_errors = []

                def send_request():
                    try:
                        self._process.stdin.write(request)
                        self._process.stdin.flush()
                    except Exception as error:
                        write_errors.append(error)
                    finally:
                        write_complete.set()

                writer = threading.Thread(target=send_request, daemon=True)
                deadline = time.monotonic() + self.INFERENCE_TIMEOUT_SECONDS
                writer.start()
                failed = False
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._stop_process()
                        raise PiiContextModelUnavailable("The local native PII runtime timed out during inference.")
                    line = self._readline(remaining, "inference")
                    if line == b".\n":
                        break
                    if line.startswith(b"ERROR\t"):
                        failed = True
                        continue
                    label, raw_start, raw_end, raw_score = line.decode("utf-8").rstrip("\n").split("\t")
                    byte_start, byte_end, score = int(raw_start), int(raw_end), float(raw_score)
                    encoded = text.encode("utf-8")
                    start = len(encoded[:byte_start].decode("utf-8"))
                    end = len(encoded[:byte_end].decode("utf-8"))
                    rows.append({"label": label, "start": start, "end": end, "score": score,
                                 "text": text[start:end]})
                    if len(rows) > PiiContextDetector.MAX_SPANS:
                        self._stop_process()
                        raise PiiContextModelUnavailable("The local native PII runtime returned too many results.")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not write_complete.wait(remaining):
                    self._stop_process()
                    raise PiiContextModelUnavailable("The local native PII runtime timed out during inference.")
                if write_errors:
                    raise PiiContextModelUnavailable("The local native PII runtime is unavailable.")
                if failed:
                    raise PiiContextModelUnavailable("The local native PII runtime failed to detect entities.")
        except PiiContextModelUnavailable:
            self._stop_process()
            raise
        except Exception as error:
            self._stop_process()
            raise PiiContextModelUnavailable("The local native PII runtime returned invalid results.") from error
        return rows


class PiiContextDetector:
    MAX_SPANS = 2_000
    ONNX_WINDOW_CHARS = 1_200
    ONNX_WINDOW_OVERLAP = 240
    LABELS = (
        "person", "full name", "email", "phone number", "address", "street address",
        "government id", "national id number", "tax id", "passport number", "bank account",
        "account number", "iban", "date of birth", "username", "ip address",
    )
    TYPE_MAP = {
        "person": "person", "full name": "person", "first name": "person", "last name": "person",
        "email": "email", "email address": "email",
        "phone": "phone", "phone number": "phone", "telephone": "phone",
        "address": "address", "street address": "address",
        "government id": "tax_id", "national id number": "tax_id", "tax id": "tax_id", "passport number": "passport",
        "bank account": "iban", "account number": "iban", "iban": "iban",
        "date of birth": "dob", "username": "username", "ip address": "ip_address",
    }
    GLINER_LABELS = (
        "name", "dob", "email address", "phone number", "ip address", "location address",
        "account number", "bank account", "credit card", "ssn", "passport number", "username",
    )
    GLINER_TYPE_MAP = {
        "name": "person", "dob": "dob", "email address": "email", "phone number": "phone",
        "ip address": "ip_address", "location address": "address", "account number": "iban",
        "bank account": "iban", "credit card": "card", "ssn": "ssn", "passport number": "passport",
        "username": "username",
    }

    def __init__(self, model: Any = None, threshold: float = 0.5, backend: str = "gliner2"):
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("The contextual detector threshold must be between zero and one.")
        if backend not in {"gliner2", "gliner-onnx", "gliner-cpp"}:
            raise ValueError("The contextual detector backend is unsupported.")
        self._model = model
        self.threshold = float(threshold)
        self._backend = backend

    @classmethod
    def from_local_path(
        cls, model_path: str | Path, threshold: float = 0.5, threads: int = 1,
    ) -> "PiiContextDetector":
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 4:
            raise ValueError("The contextual detector thread count must be between one and four.")
        path = Path(model_path).expanduser()
        if not path.is_dir():
            raise PiiContextModelUnavailable("The local PII model directory is unavailable.")
        if (path / "gliner_config.json").is_file():
            runtime = os.environ.get("OFFICEKIT_PII_CONTEXT_RUNTIME", "python").strip().lower()
            if runtime == "cpp":
                return cls._from_local_gliner_cpp(path, threshold, threads)
            if runtime != "python":
                raise PiiContextModelUnavailable("The configured local PII runtime is unsupported.")
            return cls._from_local_gliner_onnx(path, threshold, threads)
        try:
            from gliner2 import GLiNER2

            model = GLiNER2.from_pretrained(str(path.resolve()), local_files_only=True)
        except Exception as error:
            raise PiiContextModelUnavailable("The local PII model could not be loaded.") from error
        return cls(model=model, threshold=threshold)

    @classmethod
    def _from_local_gliner_onnx(cls, path: Path, threshold: float, threads: int) -> "PiiContextDetector":
        model_file = path / "onnx/model_quint8.onnx"
        if not model_file.is_file() or not (path / "tokenizer.json").is_file():
            raise PiiContextModelUnavailable("The local PII model files are incomplete.")
        try:
            import onnxruntime as ort
            from gliner import GLiNER

            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = threads
            model = GLiNER.from_pretrained(
                str(path.resolve()), local_files_only=True, load_onnx_model=True,
                onnx_model_file="onnx/model_quint8.onnx", session_options=options,
            )
        except Exception as error:
            raise PiiContextModelUnavailable("The local PII model could not be loaded.") from error
        return cls(model=model, threshold=threshold, backend="gliner-onnx")

    @classmethod
    def _from_local_gliner_cpp(cls, path: Path, threshold: float, threads: int) -> "PiiContextDetector":
        binary = Path(os.environ.get("OFFICEKIT_PII_CONTEXT_CPP_BINARY", "")).expanduser()
        if not binary.is_file():
            raise PiiContextModelUnavailable("The local native PII runtime binary is unavailable.")
        model = _GlinerCppClient(binary.resolve(), path.resolve(), threads)
        return cls(model=model, threshold=threshold, backend="gliner-cpp")

    def detect(self, text: str) -> list[dict[str, Any]]:
        if not isinstance(text, str):
            raise ValueError("Context detector input must be text.")
        if self._model is None:
            raise PiiContextModelUnavailable("The local PII model is unavailable.")
        if self._backend != "gliner-onnx" or len(text) <= self.ONNX_WINDOW_CHARS:
            return self._detect_single(text)
        spans = []
        for start, end in self._onnx_windows(text):
            for finding in self._detect_single(text[start:end]):
                finding["_start"] += start
                finding["_end"] += start
                spans.append(finding)
                if len(spans) > self.MAX_SPANS:
                    raise ValueError("The contextual detector returned too many spans.")
        return spans

    @classmethod
    def _onnx_windows(cls, text: str):
        start = 0
        while start < len(text):
            end = min(len(text), start + cls.ONNX_WINDOW_CHARS)
            if end < len(text):
                boundary = text.rfind(" ", start + cls.ONNX_WINDOW_CHARS // 2, end)
                if boundary > start:
                    end = boundary
            yield start, end
            if end == len(text):
                break
            next_start = max(start + 1, end - cls.ONNX_WINDOW_OVERLAP)
            boundary = text.find(" ", next_start, end)
            start = boundary + 1 if boundary >= 0 else next_start

    def _detect_single(self, text: str) -> list[dict[str, Any]]:
        try:
            if self._backend in {"gliner-onnx", "gliner-cpp"}:
                predictions = self._model.predict_entities(text, list(self.GLINER_LABELS), threshold=self.threshold)
                rows = [(item.get("label"), [item]) for item in predictions]
            else:
                result = self._model.extract_entities(
                    text,
                    list(self.LABELS),
                    threshold=self.threshold,
                    include_confidence=True,
                    include_spans=True,
                )
                rows = self._entity_rows(result)
        except Exception as error:
            raise PiiContextModelUnavailable("The local PII model failed during detection.") from error
        spans = []
        for raw_type, candidates in rows:
            normalized_type = " ".join(str(raw_type).lower().replace("_", " ").split())
            kind = (self.GLINER_TYPE_MAP if self._backend in {"gliner-onnx", "gliner-cpp"} else self.TYPE_MAP).get(normalized_type)
            if kind is None:
                continue
            if isinstance(candidates, dict):
                candidates = [candidates]
            if not isinstance(candidates, list):
                raise ValueError("The contextual detector returned malformed entity results.")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise ValueError("The contextual detector returned a malformed span.")
                start, end = candidate.get("start"), candidate.get("end")
                score = candidate.get("confidence", candidate.get("score"))
                candidate_text = candidate.get("text")
                if (
                    isinstance(start, bool) or not isinstance(start, int)
                    or isinstance(end, bool) or not isinstance(end, int)
                    or isinstance(score, bool) or not isinstance(score, (int, float))
                ):
                    raise ValueError("The contextual detector span is missing offsets or a score.")
                if not 0 <= start < end <= len(text) or not 0 <= score <= 1:
                    raise ValueError("The contextual detector span is outside safe bounds.")
                if score < self.threshold:
                    continue
                value = text[start:end]
                if candidate_text is not None and candidate_text != value:
                    raise ValueError("The contextual detector span does not match its text offsets.")
                spans.append({
                    "type": kind, "label": self._label(kind), "confidence": "possible", "value": value,
                    "_start": start, "_end": end, "_source": "neural", "_validation": "none",
                    "_score": float(score),
                })
                if len(spans) > self.MAX_SPANS:
                    raise ValueError("The contextual detector returned too many spans.")
        return spans

    @staticmethod
    def _entity_rows(result: Any) -> list[tuple[str, Any]]:
        if isinstance(result, dict):
            entities = result.get("entities")
        else:
            entities = result
        if isinstance(entities, list) and len(entities) == 1 and isinstance(entities[0], dict):
            entities = entities[0]
        if not isinstance(entities, dict):
            raise ValueError("The contextual detector returned an invalid entities object.")
        return list(entities.items())

    @staticmethod
    def _label(kind: str) -> str:
        return {
            "person": "Person name", "email": "Email address", "phone": "Phone number",
            "address": "Street address", "tax_id": "Tax identifier", "passport": "Passport number",
            "iban": "Bank account", "dob": "Date of birth", "username": "Username", "ip_address": "IP address",
        }[kind]
