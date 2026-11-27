"""Session-scoped watched folders for explicitly enabled local media pipelines."""

from __future__ import annotations

import os
import stat
import threading
import time
import uuid
from dataclasses import dataclass, field

from .engine_file_selections import SelectedFile, exclusive_rename, identity, open_parent
from .engine_media_jobs import MediaJobCapacityError
from .engine_media_models import MediaJobCreate

_MEDIA_EXTENSIONS = {
    "image": {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "ico", "heic", "heif", "avif", "jxl"},
    "video": {"m4v", "mov", "mp4", "gif"},
    "pdf": {"pdf"},
    "audio": {"m4a", "wav", "aiff", "aif", "mp3", "flac", "caf"},
}


@dataclass
class _Watch:
    id: str
    selection_id: str
    pipeline_id: str
    folder_name: str
    folder_root: str
    paused: bool = False
    candidates: dict = field(default_factory=dict)
    submitted: set = field(default_factory=set)
    jobs: dict = field(default_factory=dict)
    last_outcome: dict | None = None
    recent_outcomes: list = field(default_factory=list)
    processed_count: int = 0
    output_sequence: int = 1


class MediaFolderAutomationStore:
    """Poll only native-authorized folders and submit settled files to the normal job queue."""

    MAX_WATCHES = 20
    MAX_TRACKED_FILES = 10_000
    POLL_SECONDS = 1.0
    VIDEO_STABLE_POLLS = 5

    def __init__(self, selections, pipelines, jobs, sleeper=time.sleep, start_worker=True):
        self.selections = selections
        self.pipelines = pipelines
        self.jobs = jobs
        self.sleeper = sleeper
        self.start_worker = start_worker
        self.lock = threading.RLock()
        self.watches = {}
        self.published_outputs = set()
        self._stop = threading.Event()
        self._thread = None

    def add(self, selection_id, pipeline_id):
        selection_id = str(uuid.UUID(selection_id))
        pipeline_id = str(uuid.UUID(pipeline_id))
        selection = self.selections.get(selection_id, write=True)
        roots = [root for root, _root_id, is_directory in selection.roots if is_directory]
        if len(roots) != 1 or len(selection.roots) != 1:
            raise ValueError("Choose exactly one folder for automation")
        pipeline = next((item for item in self.pipelines.list() if item["id"] == pipeline_id), None)
        if pipeline is None:
            raise FileNotFoundError("Saved pipeline is unavailable")
        baseline = self._snapshot(selection_id, pipeline["media"])
        with self.lock:
            if len(self.watches) >= self.MAX_WATCHES:
                raise OverflowError("The watched-folder limit has been reached")
            if any(item.selection_id == selection_id for item in self.watches.values()):
                raise ValueError("This folder is already watched")
            self.selections.pin(selection_id)
            watch = _Watch(
                str(uuid.uuid4()), selection_id, pipeline_id,
                os.path.basename(roots[0]) or "Selected folder", os.path.realpath(roots[0]),
            )
            watch.submitted.update((item.path, item.signature) for item in baseline.values())
            self.watches[watch.id] = watch
            self._ensure_worker()
            return self._payload(watch, pipeline["name"])

    def list(self):
        with self.lock:
            values = []
            for watch in self.watches.values():
                try:
                    pipeline = next((item for item in self.pipelines.list() if item["id"] == watch.pipeline_id), None)
                except Exception:
                    pipeline = None
                values.append(self._payload(watch, pipeline["name"] if pipeline else "Unavailable pipeline"))
            return values

    def set_paused(self, watch_id, paused):
        if type(paused) is not bool:
            raise ValueError("Paused state must be a boolean")
        with self.lock:
            watch = self._get(watch_id)
            watch.paused = paused
            return self._payload(watch, self._pipeline_name(watch.pipeline_id))

    def remove(self, watch_id):
        with self.lock:
            watch = self._get(watch_id)
            if watch.jobs:
                raise RuntimeError("Wait for active folder jobs to finish before removing this folder")
            self.watches.pop(watch.id)
            self.selections.unpin(watch.selection_id)
            self._prune_published_outputs()
            return True

    def uses_pipeline(self, pipeline_id):
        with self.lock:
            return any(item.pipeline_id == pipeline_id for item in self.watches.values())

    def close(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        with self.lock:
            for watch in self.watches.values():
                self.selections.unpin(watch.selection_id)
            self.watches.clear()
            self.published_outputs.clear()

    def _ensure_worker(self):
        if not self.start_worker:
            return
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="officekit-media-folder-watcher", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            with self.lock:
                watches = tuple(self.watches.values())
            for watch in watches:
                try:
                    self._poll(watch)
                except Exception:
                    self._outcome(watch, {"state": "error", "message": "Folder access or preparation failed. Review the folder grant and pipeline."})
            self.sleeper(self.POLL_SECONDS)

    def _poll(self, watch):
        with self.lock:
            if watch.id not in self.watches:
                return
        pipeline = next((item for item in self.pipelines.list() if item["id"] == watch.pipeline_id), None)
        if pipeline is None:
            with self.lock:
                watch.paused = True
            self._outcome(watch, {"state": "error", "message": "The saved pipeline was removed."})
            return
        try:
            current = self._snapshot(watch.selection_id, pipeline["media"])
        except OverflowError:
            with self.lock:
                watch.paused = True
            self._outcome(watch, {"state": "paused", "message": "The folder exceeds the 10,000-file session scan limit. Choose a smaller folder."})
            return
        self._finish_jobs(watch, current)
        with self.lock:
            if watch.paused or watch.id not in self.watches:
                return
        for file_id in tuple(watch.candidates):
            if file_id not in current:
                watch.candidates.pop(file_id, None)
        for file_id, selected in current.items():
            marker = (selected.path, selected.signature)
            if marker in watch.submitted:
                watch.candidates.pop(file_id, None)
                continue
            previous = watch.candidates.get(file_id)
            count = previous[1] + 1 if previous and previous[0] == marker else 1
            if previous is None and len(watch.candidates) >= self.MAX_TRACKED_FILES:
                with self.lock:
                    watch.paused = True
                self._outcome(watch, {"state": "paused", "message": "The folder reached its session tracking limit. Review outcomes, then remove and regrant the folder."})
                return
            watch.candidates[file_id] = (marker, count)
            required_stable_polls = self.VIDEO_STABLE_POLLS if pipeline["media"] == "video" else 2
            if count >= required_stable_polls and marker not in watch.submitted:
                if len(watch.submitted) >= self.MAX_TRACKED_FILES:
                    with self.lock:
                        watch.paused = True
                    self._outcome(watch, {"state": "paused", "message": "The folder reached its session tracking limit. Review outcomes, then remove and regrant the folder."})
                    return
                # Serialize submission with pause/remove so no job can slip in
                # after the user has paused or removed this watch.
                with self.lock:
                    if watch.id not in self.watches or watch.paused:
                        return
                    self._submit(watch, selected, pipeline)
                watch.candidates.pop(file_id, None)

    def _matches(self, selected, media):
        if (selected.path, selected.signature) in self.published_outputs:
            return False
        basename = os.path.basename(selected.path).casefold()
        extension = os.path.splitext(basename)[1].lstrip(".")
        if extension in {"heic", "heif"}:
            from .engine_media_native import native_heif_decoder_available
            return media == "image" and native_heif_decoder_available()
        return extension in _MEDIA_EXTENSIONS.get(media, set())

    def _snapshot(self, selection_id, media):
        current = {}
        scanned = 0
        for selected in self.selections.iter_files(selection_id):
            scanned += 1
            if scanned > self.MAX_TRACKED_FILES:
                raise OverflowError("Folder scan exceeded its entry limit")
            if self._matches(selected, media):
                current[selected.id] = selected
        return current

    def _submit(self, watch, selected, pipeline):
        marker = (selected.path, selected.signature)
        try:
            request = MediaJobCreate.model_validate({"items": [{
                "source": {"kind": "selection", "selectionId": watch.selection_id, "fileId": selected.id},
                "operations": pipeline["operations"],
                "outputNameTemplate": pipeline.get("outputNameTemplate"),
            }]})
            accepted = self.jobs.submit(request, output_sequence_start=watch.output_sequence)
            with self.lock:
                watch.output_sequence += 1
                watch.submitted.add(marker)
                watch.jobs[accepted["id"]] = (selected, marker)
        except MediaJobCapacityError:
            self._outcome(watch, {"state": "queued", "filename": os.path.basename(selected.path), "message": "The media queue is full. This stable file will be retried."})
        except Exception:
            with self.lock:
                watch.submitted.add(marker)
            self._outcome(watch, {"state": "error", "filename": os.path.basename(selected.path), "message": "This file could not be prepared. The source was left unchanged."})

    def _finish_jobs(self, watch, current):
        for job_id, (selected, marker) in tuple(watch.jobs.items()):
            try:
                status = self.jobs.status(job_id)
            except Exception:
                continue
            if status["state"] in {"queued", "running"}:
                continue
            item = next(iter(status["items"]), {})
            outcome = {"state": "error", "filename": os.path.basename(selected.path), "message": "This file could not be prepared. The source was left unchanged."}
            if item.get("state") == "ready" and item.get("artifactId"):
                current_item = current.get(selected.id)
                if current_item is not None and current_item.signature == selected.signature:
                    try:
                        output_path = self._publish(watch.selection_id, current_item, item["artifactId"], item["outputName"])
                        output_info = os.stat(output_path, follow_symlinks=False)
                        if not stat.S_ISREG(output_info.st_mode):
                            raise OSError("The prepared output is not a regular file")
                        output_marker = (output_path, identity(output_info))
                        with self.lock:
                            watch.submitted.add(output_marker)
                            self.published_outputs.add(output_marker)
                        outcome = {"state": "ready", "filename": os.path.basename(selected.path), "outputName": os.path.basename(output_path), "message": "Prepared copy saved. Original unchanged."}
                        watch.processed_count += 1
                    except Exception:
                        outcome["message"] = "Prepared copy could not be saved safely. The original was left unchanged."
                else:
                    outcome["message"] = "The source changed before the prepared copy could be saved. No output was published."
            self._outcome(watch, outcome)
            with self.lock:
                watch.jobs.pop(job_id, None)

    def _publish(self, selection_id, selected: SelectedFile, artifact_id, output_name):
        selection = self.selections.get(selection_id, write=True)
        root, root_identity, is_directory = selection.roots[0]
        current_root = os.stat(root, follow_symlinks=False)
        if not is_directory or (current_root.st_dev, current_root.st_ino) != root_identity:
            raise OSError("The granted folder changed")
        current = os.stat(selected.path, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or identity(current) != selected.signature:
            raise OSError("The source file changed")
        parent = os.path.dirname(selected.path)
        if os.path.commonpath((os.path.realpath(selected.root), os.path.realpath(parent))) != os.path.realpath(selected.root):
            raise OSError("The output folder is outside the grant")
        safe_name = os.path.basename(output_name or "")
        if not safe_name or safe_name in {".", ".."} or safe_name != output_name or "/" in safe_name or "\\" in safe_name:
            raise OSError("Invalid output name")
        artifact = self.jobs.artifact(artifact_id)
        try:
            stem, extension = os.path.splitext(safe_name)
            for index in range(1, 1000):
                candidate = safe_name if index == 1 else f"{stem} ({index}).{extension.lstrip('.')}"
                temporary = f".officekit-{uuid.uuid4().hex}.partial"
                with open_parent(os.path.join(parent, candidate)) as parent_fd:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd) if parent_fd is not None else os.open(os.path.join(parent, temporary), flags, 0o600)
                    try:
                        with os.fdopen(descriptor, "wb", closefd=True) as output:
                            copied = 0
                            while chunk := artifact["file"].read(1024 * 1024):
                                copied += len(chunk)
                                if copied > self.jobs.MAX_MEDIA_OUTPUT_BYTES:
                                    raise OSError("Prepared output exceeds the media limit")
                                output.write(chunk)
                            if copied != artifact.get("sizeBytes"):
                                raise OSError("Prepared output changed while being copied")
                            output.flush()
                            os.fsync(output.fileno())
                        latest = os.stat(selected.path, follow_symlinks=False)
                        if not stat.S_ISREG(latest.st_mode) or identity(latest) != selected.signature:
                            raise OSError("The source file changed")
                        exclusive_rename(os.path.join(parent, temporary) if parent_fd is None else temporary,
                                          os.path.join(parent, candidate) if parent_fd is None else candidate, parent_fd)
                        return os.path.join(parent, candidate)
                    except FileExistsError:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd) if parent_fd is not None else os.unlink(os.path.join(parent, temporary))
                        except OSError:
                            pass
                        artifact["file"].seek(0)
                        continue
                    except Exception:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd) if parent_fd is not None else os.unlink(os.path.join(parent, temporary))
                        except OSError:
                            pass
                        raise
            raise FileExistsError("No unused output name is available")
        finally:
            artifact["file"].close()

    def _prune_published_outputs(self):
        active_roots = tuple(watch.folder_root for watch in self.watches.values())
        if not active_roots:
            self.published_outputs.clear()
            return
        self.published_outputs = {
            marker for marker in self.published_outputs
            if any(self._path_is_within(root, marker[0]) for root in active_roots)
        }

    @staticmethod
    def _path_is_within(root, path):
        try:
            return os.path.normcase(os.path.commonpath((root, path))) == os.path.normcase(root)
        except ValueError:
            return False

    def _outcome(self, watch, outcome):
        with self.lock:
            entry = {**outcome, "at": int(time.time())}
            if watch.last_outcome and all(watch.last_outcome.get(key) == entry.get(key) for key in ("state", "filename", "message", "outputName")):
                watch.last_outcome = entry
                if watch.recent_outcomes:
                    watch.recent_outcomes[-1] = entry
                return
            watch.last_outcome = entry
            watch.recent_outcomes.append(entry)
            del watch.recent_outcomes[:-10]

    def _pipeline_name(self, pipeline_id):
        try:
            return next((item["name"] for item in self.pipelines.list() if item["id"] == pipeline_id), "Unavailable pipeline")
        except Exception:
            return "Unavailable pipeline"

    @staticmethod
    def _payload(watch, pipeline_name):
        return {"id": watch.id, "folderName": watch.folder_name, "pipelineId": watch.pipeline_id,
                "pipelineName": pipeline_name, "state": "paused" if watch.paused else "watching",
                "processedCount": watch.processed_count, "lastOutcome": watch.last_outcome,
                "recentOutcomes": list(watch.recent_outcomes)}

    def _get(self, watch_id):
        try:
            canonical = str(uuid.UUID(watch_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("Watched folder is unavailable") from error
        watch = self.watches.get(canonical)
        if watch is None:
            raise FileNotFoundError("Watched folder is unavailable")
        return watch
