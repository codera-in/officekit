"""Measure local contextual PII model load, warm prediction, CPU and peak RSS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import resource
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from officekit.engines.pii_context_detector import PiiContextDetector


BASE_TEXT = "Please ask our colleague Nora Scott for help with the annual report."


def make_text(word_count: int) -> str:
    words = BASE_TEXT.split()
    if word_count < len(words):
        raise ValueError("word count must be at least the synthetic example length")
    return " ".join(words + ["routine"] * (word_count - len(words)))


def current_rss_mb() -> float:
    completed = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], check=True,
                               capture_output=True, text=True)
    processes = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3:
            pid, parent, rss_kb = map(int, fields)
            processes[pid] = (parent, rss_kb)
    selected = {os.getpid()}
    changed = True
    while changed:
        children = {pid for pid, (parent, _rss) in processes.items() if parent in selected}
        changed = not children.issubset(selected)
        selected.update(children)
    return sum(processes[pid][1] for pid in selected if pid in processes) / 1024


def current_process_tree_cpu_seconds() -> float:
    completed = subprocess.run(["ps", "-axo", "pid=,ppid=,time="], check=True,
                               capture_output=True, text=True)
    processes = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3:
            pid, parent = int(fields[0]), int(fields[1])
            parts = fields[2].split(":")
            seconds = float(parts[-1])
            minutes = int(parts[-2])
            hours = int(parts[-3]) if len(parts) == 3 else 0
            processes[pid] = (parent, hours * 3600 + minutes * 60 + seconds)
    selected = {os.getpid()}
    changed = True
    while changed:
        children = {pid for pid, (parent, _cpu) in processes.items() if parent in selected}
        changed = not children.issubset(selected)
        selected.update(children)
    return sum(processes[pid][1] for pid in selected if pid in processes)


def run_worker(model_path: Path, threads: int, repeats: int, word_count: int) -> dict:
    text = make_text(word_count)
    baseline_rss_mb = current_rss_mb()
    cpu_start = time.process_time()
    tree_cpu_start = current_process_tree_cpu_seconds()
    baseline_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cpu_start = time.process_time()
    load_start = time.perf_counter()
    detector = PiiContextDetector.from_local_path(model_path, threshold=0.7, threads=threads)
    load_seconds = time.perf_counter() - load_start
    first_start = time.perf_counter()
    detector.detect(text)
    first_prediction_seconds = time.perf_counter() - first_start
    timings = []
    loaded_rss_mb = current_rss_mb()
    rss_samples = [baseline_rss_mb, loaded_rss_mb]
    for _ in range(repeats):
        started = time.perf_counter()
        detector.detect(text)
        timings.append(time.perf_counter() - started)
        if len(timings) % 10 == 0 or len(timings) == repeats:
            rss_samples.append(current_rss_mb())
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    baseline_peak_mb = baseline_peak / (1024 * 1024) if sys.platform == "darwin" else baseline_peak / 1024
    loaded_rss_mb = current_rss_mb()
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "threads": threads,
        "word_count": word_count,
        "load_seconds": load_seconds,
        "first_prediction_seconds": first_prediction_seconds,
        "warm_repeats": repeats,
        "warm_mean_seconds": statistics.mean(timings),
        "warm_p50_seconds": statistics.median(timings),
        "warm_p95_seconds": p95,
        "process_cpu_seconds": time.process_time() - cpu_start,
        "process_tree_cpu_seconds": current_process_tree_cpu_seconds() - tree_cpu_start,
        "baseline_rss_mb": baseline_rss_mb,
        "loaded_rss_mb": loaded_rss_mb,
        "rss_increase_mb": loaded_rss_mb - baseline_rss_mb,
        "peak_rss_mb": peak_mb,
        "sampled_peak_process_tree_rss_mb": max(rss_samples),
        "sampled_incremental_peak_process_tree_rss_mb": max(rss_samples) - baseline_rss_mb,
        "incremental_peak_rss_mb": peak_mb - baseline_peak_mb,
        "rss_samples_mb_every_10_scans": rss_samples,
        "rss_drift_mb_over_repeats": rss_samples[-1] - rss_samples[1] if len(rss_samples) > 1 else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--cold-starts", type=int, default=0)
    parser.add_argument("--word-count", type=int, default=12)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 1000 or not 0 <= args.cold_starts <= 20 or args.word_count < len(BASE_TEXT.split()):
        parser.error("repeats must be 1..1000, cold-starts 0..20 and word-count at least 12")
    model_path = args.model_path.expanduser().resolve()
    if args.worker:
        print(json.dumps(run_worker(model_path, args.threads, args.repeats, args.word_count)))
        return 0
    warm = run_worker(model_path, args.threads, args.repeats, args.word_count)
    cold = []
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker", "--model-path", str(model_path),
        "--threads", str(args.threads), "--repeats", "1", "--word-count", str(args.word_count),
    ]
    for _ in range(args.cold_starts):
        completed = subprocess.run(command, check=True, capture_output=True, text=True,
                                   env={**os.environ, "OFFICEKIT_PII_CONTEXT_MODEL": str(model_path)})
        cold.append(json.loads(completed.stdout))
    model_file = model_path / "onnx/model_quint8.onnx"
    tokenizer_file = model_path / "tokenizer.json"
    binary = Path(os.environ.get("OFFICEKIT_PII_CONTEXT_CPP_BINARY", ""))
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "runtime": os.environ.get("OFFICEKIT_PII_CONTEXT_RUNTIME", "python"),
    }
    try:
        import onnxruntime
        environment["onnxruntime_python_version"] = onnxruntime.__version__
    except ImportError:
        environment["onnxruntime_python_version"] = None
    model = {
        "onnx_bytes": model_file.stat().st_size,
        "onnx_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "tokenizer_bytes": tokenizer_file.stat().st_size,
        "tokenizer_sha256": hashlib.sha256(tokenizer_file.read_bytes()).hexdigest(),
        "cpp_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None,
    }
    rendered = json.dumps({"backend": "knowledgator-gliner-onnx-int8", "environment": environment,
                           "model": model, "warm_process": warm, "cold_processes": cold}, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
