import io
from contextlib import contextmanager
import os
import time
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_converter import ImageOutputLimitError
from officekit.engines.engine_media_jobs import (
    MediaJobCapacityError,
    MediaJobConflictError,
    MediaJobNotFoundError,
    MediaInputTooLargeError,
    MediaImportUnavailableError,
    MediaItem,
    MediaJobStore,
)
from officekit.engines.engine_media_models import MediaJobCreate, MAX_MEDIA_JOB_ITEMS
from officekit.engines import engine_media_native as native
from officekit.engines.engine_media_native import NativeMediaCancelledError
from officekit.engines.engine_media_optimizer import MediaOperationUnavailableError, MediaOutput
from officekit.engines.engine_screenshot_editor import ScreenshotOutputLimitError


class RecordingExecutor:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append((function, args))

    def run_all(self):
        while self.calls:
            function, args = self.calls.pop(0)
            function(*args)

    def shutdown(self, **_kwargs):
        self.calls.clear()


def make_png(path, size=(32, 24), color=(10, 20, 30)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    Path(path).write_bytes(output.getvalue())


def create_selection(tmp_path, names=("photo.png",), store=None):
    store = store or FileSelectionStore(native_token="native")
    paths = []
    for index, name in enumerate(names):
        path = tmp_path / name
        if path.suffix.lower() == ".png":
            make_png(path, color=(10 + index, 20, 30))
        else:
            path.write_bytes(b"selected source")
        paths.append(str(path))
    selection = store.register_native(paths, access="read", credential="native")
    files = list(store.iter_files(selection["id"]))
    return store, selection, files


def request_for(items):
    return MediaJobCreate.model_validate({"items": items})


def selected_job_item(selected, operation_id="image-strip-metadata", options=None):
    return {
        "source": {"kind": "selection", "selection_id": selected.selection_id, "file_id": selected.id},
        "operations": [{"operation_id": operation_id, "options": options or {}}],
    }


def test_media_job_reads_native_original_processes_and_retains_private_artifact(tmp_path):
    selections, selection, files = create_selection(tmp_path)
    original = Path(files[0].path).read_bytes()
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([selected_job_item(files[0], "image-resize", {"max_width": 16, "max_height": 12})]))
    assert created["state"] == "queued"
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "ready"
    assert result["items"][0]["state"] == "ready"
    assert result["items"][0]["inputBytes"] == len(original)
    assert result["items"][0]["outputBytes"] > 0
    assert "path" not in result["items"][0]
    artifact = jobs.artifact(result["items"][0]["artifactId"])
    with artifact["file"] as stream:
        assert stream.read() != original
    assert Path(files[0].path).read_bytes() == original
    assert selection["id"] == str(files[0].selection_id)
    jobs.close()


def test_media_job_applies_validated_pipeline_output_name_template(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    item = selected_job_item(files[0], "image-resize", {"max_width": 16, "max_height": 12})
    item["outputNameTemplate"] = "{name}-web.{ext}"
    created = jobs.submit(request_for([item]))
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["items"][0]["outputName"] == "photo-web.png"
    assert Path(files[0].path).is_file()
    jobs.close()


@pytest.mark.parametrize("sequence", [True, 0, -1, 10_001, "2", 1.5])
def test_media_job_rejects_invalid_internal_output_sequence(tmp_path, sequence):
    selections, _selection, files = create_selection(tmp_path)
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    with pytest.raises(ValueError, match="Output sequence"):
        jobs.submit(request_for([selected_job_item(files[0])]), output_sequence_start=sequence)
    assert not jobs.jobs
    jobs.close()


def test_media_job_sequences_output_names_within_batch(tmp_path):
    selections, _selection, files = create_selection(tmp_path, ("first.png", "second.png"))
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    items = [dict(selected_job_item(source), outputNameTemplate="%f-%i.{ext}") for source in files]
    created = jobs.submit(request_for(items))
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "ready"
    assert [item["outputName"] for item in result["items"]] == ["first-1.png", "second-2.png"]
    jobs.close()


def test_native_media_job_stages_and_retains_file_backed_output(tmp_path, monkeypatch):
    selections, _selection, files = create_selection(tmp_path, ("clip.mov",))
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor, staging_root=str(tmp_path / "media-jobs"))
    observed = {}

    def convert(source_path, filename, operation_id, options, workspace, cancel_event=None):
        assert Path(source_path).is_file()
        assert Path(source_path).parent == Path(workspace)
        observed["input"] = Path(source_path).read_bytes()
        output_path = Path(workspace) / "prepared.m4v"
        output_path.write_bytes(b"prepared video")
        return str(output_path), "m4v", "video/x-m4v", {"quality": options["quality"]}, output_path.stat().st_size

    monkeypatch.setattr("officekit.engines.engine_media_jobs.convert_native_media_to_file", convert)
    monkeypatch.setattr(
        "officekit.engines.engine_media_jobs.MediaOptimizerEngine.execute",
        lambda *_args, **_kwargs: pytest.fail("native media must stay file-backed"),
    )
    created = jobs.submit(request_for([selected_job_item(
        files[0], "video-optimize", {"target_format": "m4v", "quality": "balanced"},
    )]))
    executor.run_all()
    status = jobs.status(created["id"])
    item = status["items"][0]
    assert status["state"] == "ready"
    assert item["inputBytes"] == len(b"selected source")
    assert item["outputBytes"] == len(b"prepared video")
    assert observed["input"] == b"selected source"
    artifact = jobs.artifact(item["artifactId"])
    with artifact["file"] as stream:
        assert stream.read() == b"prepared video"
    assert Path(files[0].path).read_bytes() == b"selected source"
    jobs.close()


def test_media_job_reports_partial_per_file_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    selections, _selection, files = create_selection(tmp_path, ("photo.png", "clip.mp4"))
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([
        selected_job_item(files[0]),
        selected_job_item(files[1], "video-mute"),
    ]))
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "partial"
    assert [item["state"] for item in result["items"]] == ["ready", "failed"]
    assert result["items"][1]["errorCode"] == "engine_unavailable"
    jobs.close()


def test_cancellation_before_worker_starts_preserves_source_and_publishes_no_artifact(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    request = request_for([selected_job_item(files[0])])
    created = jobs.submit(request.model_dump(by_alias=True))
    cancelled = jobs.cancel(created["id"])
    assert cancelled["cancellationRequested"] is True
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "cancelled"
    assert result["items"][0]["state"] == "cancelled"
    assert result["items"][0].get("artifactId") is None
    jobs.close()


def test_running_native_converter_cancellation_is_reported_as_cancelled(tmp_path, monkeypatch):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    def cancel_during_conversion(job, _item):
        job.cancel.set()
        raise NativeMediaCancelledError()
    monkeypatch.setattr(jobs, "_process_item", cancel_during_conversion)
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "cancelled"
    assert result["items"][0]["state"] == "cancelled"
    assert result["items"][0]["errorCode"] is None
    jobs.close()


def test_invalid_or_stale_source_is_rejected_before_queueing(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    stale = selected_job_item(files[0])
    stale["source"]["file_id"] = "123e4567-e89b-42d3-a456-426614174099"
    with pytest.raises((FileNotFoundError, ValueError)):
        jobs.submit(request_for([stale]))
    import_item = {
        "source": {"kind": "import", "import_id": "123e4567-e89b-42d3-a456-426614174099"},
        "operations": [{"operation_id": "image-strip-metadata", "options": {}}],
    }
    with pytest.raises(MediaImportUnavailableError):
        jobs.submit(request_for([import_item]))
    jobs.close()


def test_input_and_job_queue_limits_are_enforced(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    large = tmp_path / "large.png"
    with large.open("wb") as stream:
        stream.truncate(MediaJobStore.MAX_MEDIA_INPUT_BYTES + 1)
    larger_selection = selections.register_native([str(large)], credential="native")
    large_item = next(selections.iter_files(larger_selection["id"]))
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    with pytest.raises(MediaInputTooLargeError):
        jobs.submit(request_for([selected_job_item(large_item)]))

    request = request_for([selected_job_item(files[0])])
    for _index in range(MediaJobStore.MAX_MEDIA_QUEUED):
        jobs.submit(request)
    with pytest.raises(MediaJobCapacityError):
        jobs.submit(request)
    for job in list(jobs.jobs.values())[:MediaJobStore.MAX_MEDIA_ACTIVE]:
        job.state = "running"
    for _index in range(MediaJobStore.MAX_MEDIA_ACTIVE):
        jobs.submit(request)
    with pytest.raises(MediaJobCapacityError):
        jobs.submit(request)
    jobs.close()


def test_changed_source_fails_without_creating_an_artifact(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    Path(files[0].path).write_bytes(b"changed after selection")
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "failed"
    assert result["items"][0]["errorCode"] == "source_changed"
    assert result["items"][0].get("artifactId") is None
    jobs.close()


def test_artifacts_expire_and_terminal_jobs_cannot_be_cancelled(tmp_path):
    current = [0.0]
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor, clock=lambda: current[0])
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    executor.run_all()
    artifact_id = jobs.status(created["id"])["items"][0]["artifactId"]
    with pytest.raises(MediaJobConflictError):
        jobs.cancel(created["id"])
    current[0] += MediaJobStore.JOB_TTL + 1
    with pytest.raises(MediaJobNotFoundError):
        jobs.status(created["id"])
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact(artifact_id)
    jobs.close()


def test_job_request_rejects_duplicate_and_over_limit_items():
    source_id = "123e4567-e89b-42d3-a456-426614174000"
    file_id = "123e4567-e89b-42d3-a456-426614174001"
    item = {
        "source": {"kind": "selection", "selection_id": source_id, "file_id": file_id},
        "operations": [{"operation_id": "image-strip-metadata", "options": {}}],
    }
    with pytest.raises(ValueError):
        MediaJobCreate.model_validate({"items": [item, item]})
    with pytest.raises(ValueError):
        MediaJobCreate.model_validate({"items": [item] * (MAX_MEDIA_JOB_ITEMS + 1)})


def test_submit_rolls_back_pins_when_executor_rejects_work(tmp_path):
    selections, selection, files = create_selection(tmp_path)

    class RejectingExecutor:
        def submit(self, *_args):
            raise RuntimeError("executor stopped")

        def shutdown(self, **_kwargs):
            return None

    jobs = MediaJobStore(selections, executor=RejectingExecutor())
    with pytest.raises(RuntimeError):
        jobs.submit(request_for([selected_job_item(files[0])]))
    assert selections.selections[selection["id"]].pins == 0
    assert jobs.jobs == {}
    jobs.close()


def test_artifact_descriptor_rejects_missing_changed_and_linked_files(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([selected_job_item(files[0], "image-resize", {"max_width": 16, "max_height": 12})]))
    executor.run_all()
    artifact_id = jobs.status(created["id"])["items"][0]["artifactId"]
    path = Path(jobs.artifacts[artifact_id][1])
    path.unlink()
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact(artifact_id)

    created = jobs.submit(request_for([selected_job_item(files[0], "image-resize", {"max_width": 12, "max_height": 9})]))
    executor.run_all()
    artifact_id = jobs.status(created["id"])["items"][0]["artifactId"]
    path = Path(jobs.artifacts[artifact_id][1])
    path.write_bytes(b"changed")
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact(artifact_id)

    created = jobs.submit(request_for([selected_job_item(files[0], "image-resize", {"max_width": 10, "max_height": 8})]))
    executor.run_all()
    artifact_id = jobs.status(created["id"])["items"][0]["artifactId"]
    path = Path(jobs.artifacts[artifact_id][1])
    path.unlink()
    path.symlink_to(files[0].path)
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact(artifact_id)
    jobs.close()


def test_artifact_lookup_fails_closed_for_expired_job_even_if_still_running(tmp_path):
    current = [10.0]
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor, clock=lambda: current[0])
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    executor.run_all()
    artifact_id = jobs.status(created["id"])["items"][0]["artifactId"]
    job = jobs.jobs[created["id"]]
    job.state = "running"
    job.expires = current[0] - 1
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact(artifact_id)
    jobs.close()


@pytest.mark.parametrize(("exception", "expected"), [
    (MediaInputTooLargeError("limit"), "input_limit"),
    (ImageOutputLimitError("limit"), "output_limit"),
    (ScreenshotOutputLimitError(), "output_limit"),
    (ConversionInputError(), "invalid_media"),
    (PermissionError("private path"), "permission_denied"),
    (FileNotFoundError("private path"), "source_unavailable"),
    (ValueError("private path"), "source_changed"),
    (OSError("private path"), "read_failed"),
    (RuntimeError("private parser detail"), "operation_failed"),
])
def test_worker_maps_failures_to_stable_safe_per_file_codes(tmp_path, exception, expected):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([selected_job_item(files[0])]))

    def fail_item(_job, _item):
        raise exception

    jobs._process_item = fail_item
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "failed"
    assert result["items"][0]["errorCode"] == expected
    assert "path" not in result["items"][0]
    jobs.close()


def test_worker_handles_cancellation_between_files_and_before_publication(tmp_path, monkeypatch):
    selections, _selection, files = create_selection(tmp_path, ("one.png", "two.png", "three.png"))
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    created = jobs.submit(request_for([selected_job_item(files[0]), selected_job_item(files[1]), selected_job_item(files[2])]))
    job = jobs.jobs[created["id"]]

    def cancel_after_processing(_job, _item):
        job.cancel.set()
        return MediaOutput(b"prepared", "png", "image/png")

    monkeypatch.setattr(jobs, "_process_item", cancel_after_processing)
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "cancelled"
    assert [item["state"] for item in result["items"]] == ["cancelled", "cancelled", "cancelled"]
    assert not any(item["artifactId"] for item in result["items"])
    jobs.close()


def test_process_item_rejects_private_imports_oversize_and_output_overflow(tmp_path, monkeypatch):
    selections, _selection, files = create_selection(tmp_path)
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    valid_request = request_for([selected_job_item(files[0])])
    job_item = jobs._resolve_item(valid_request.items[0])
    job = jobs.submit(valid_request)
    media_job = jobs.jobs[job["id"]]
    with pytest.raises(MediaImportUnavailableError):
        jobs._process_item(media_job, MediaItem("x", None, "media", []))
    monkeypatch.setattr(jobs, "MAX_MEDIA_INPUT_BYTES", 1)
    with pytest.raises(MediaInputTooLargeError):
        jobs._process_item(media_job, job_item)
    monkeypatch.setattr(jobs, "MAX_MEDIA_INPUT_BYTES", len(Path(files[0].path).read_bytes()))
    monkeypatch.setattr(jobs, "MAX_MEDIA_OUTPUT_BYTES", 1)
    monkeypatch.setattr("officekit.engines.engine_media_jobs.MediaOptimizerEngine.execute", lambda *_args, **_kwargs: MediaOutput(b"12", "png", "image/png"))
    with pytest.raises(ImageOutputLimitError):
        jobs._process_item(media_job, job_item)
    jobs.close()


def test_worker_reports_stream_growth_cancellation_during_read_and_rechecks_after_read(tmp_path, monkeypatch):
    selections, _selection, files = create_selection(tmp_path)
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    selected = files[0]
    request = request_for([selected_job_item(selected)])
    job_item = jobs._resolve_item(request.items[0])
    job_data = jobs.submit(request)
    job = jobs.jobs[job_data["id"]]
    source_size = selected.signature[2]

    class FakeStream:
        def __init__(self, reads, cancel=None):
            self.reads = iter(reads)
            self.cancel = cancel

        def read(self, _size):
            if self.cancel:
                self.cancel.set()
            return next(self.reads, b"")

    @contextmanager
    def fake_open(_selected, stream):
        yield stream

    monkeypatch.setattr(jobs, "MAX_MEDIA_INPUT_BYTES", source_size)
    monkeypatch.setattr(selections, "open_file", lambda _selected: fake_open(_selected, FakeStream([b"x" * (source_size + 1)])))
    with pytest.raises(MediaInputTooLargeError):
        jobs._process_item(job, job_item)

    job.cancel.clear()
    monkeypatch.setattr(selections, "open_file", lambda _selected: fake_open(_selected, FakeStream([b"x", b"y"], job.cancel)))
    assert jobs._process_item(job, job_item) is None

    job.cancel.clear()
    monkeypatch.setattr(selections, "open_file", lambda _selected: fake_open(_selected, FakeStream([b""], job.cancel)))
    assert jobs._process_item(job, job_item) is None
    jobs.close()


def test_expired_failure_without_a_stage_directory_is_removed(tmp_path):
    current = [0.0]
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor, clock=lambda: current[0])
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    jobs._process_item = lambda *_args: (_ for _ in ()).throw(ValueError("no output"))
    executor.run_all()
    current[0] += jobs.JOB_TTL + 1
    with pytest.raises(MediaJobNotFoundError):
        jobs.status(created["id"])
    assert created["id"] not in jobs.jobs
    jobs.close()


def test_retained_output_budget_rejects_publication(tmp_path):
    selections, _selection, files = create_selection(tmp_path)
    executor = RecordingExecutor()
    jobs = MediaJobStore(selections, executor=executor)
    jobs.MAX_RETAINED_OUTPUT_BYTES = 0
    created = jobs.submit(request_for([selected_job_item(files[0])]))
    executor.run_all()
    result = jobs.status(created["id"])
    assert result["state"] == "failed"
    assert result["items"][0]["errorCode"] == "output_limit"
    assert jobs.retained_bytes == 0
    jobs.close()


def test_invalid_job_ids_and_missing_artifacts_are_not_found(tmp_path):
    selections, _selection, _files = create_selection(tmp_path)
    jobs = MediaJobStore(selections, executor=RecordingExecutor())
    with pytest.raises(MediaJobNotFoundError):
        jobs.status("bad-id")
    with pytest.raises(MediaJobNotFoundError):
        jobs.artifact("123e4567-e89b-42d3-a456-426614174000")
    jobs.close()
