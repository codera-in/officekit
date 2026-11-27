"""Bounded background media jobs over native-authorized files."""

from dataclasses import dataclass, field
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .engine_conversion_errors import ConversionInputError
from .engine_file_converter import ImageOutputLimitError
from .engine_file_selections import FileSelectionStore, SelectedFile, identity
from .engine_media_models import ImportedSource, MediaJobCreate, SelectedSource, StagedImageSource
from .engine_media_naming import render_output_name
from .engine_media_import import (
    MediaImportCancelledError,
    MediaImportGrant,
    MediaImportRejectedError,
    MediaImportStore,
    MediaImportTooLargeError,
    MediaImportUnsafeTargetError,
    MediaImportUnavailableError,
)
from .engine_media_optimizer import MediaOperationUnavailableError, MediaOptimizerEngine
from .engine_media_native import NativeMediaCancelledError, NativeMediaUnavailableError, _safe_extension, convert_native_media_to_file
from .engine_media_pdf import MediaPdfCancelledError
from .engine_media_staging import (
    MediaStagingStore,
    StagedImageGrant,
    StagedImageTooLargeError,
    StagedImageUnavailableError,
)
from .engine_screenshot_editor import ScreenshotOutputLimitError


class MediaJobCapacityError(RuntimeError):
    """The bounded media job queue is full."""


class MediaJobConflictError(RuntimeError):
    """The requested media job state transition is not valid."""


class MediaJobNotFoundError(FileNotFoundError):
    """The job or its retained artifact is unavailable."""


class MediaInputTooLargeError(ValueError):
    """The selected source exceeds the current bounded image/PDF adapter size."""


@dataclass(frozen=True)
class MediaFileOutput:
    path: str
    workspace: str
    extension: str
    media_type: str
    size: int
    attributes: dict


@dataclass
class MediaItem:
    source_id: str
    selected: SelectedFile | None
    name: str
    operations: list
    output_name_template: str | None = None
    import_grant: MediaImportGrant | None = None
    staged_image: StagedImageGrant | None = None
    input_size: int | None = None
    sequence: int = 1
    state: str = "queued"
    artifact_id: str | None = None
    output_name: str | None = None
    output_type: str | None = None
    output_size: int | None = None
    attributes: dict = field(default_factory=dict)
    error_code: str | None = None


@dataclass
class MediaJob:
    id: str
    selection_ids: tuple[str, ...]
    items: list[MediaItem]
    state: str = "queued"
    progress: int = 0
    phase: str = "Queued"
    cancel: threading.Event = field(default_factory=threading.Event)
    expires: float = 0
    artifact_paths: dict = field(default_factory=dict)
    result_bytes: int = 0
    watermark_image: bytes | None = None


class MediaJobStore:
    MAX_MEDIA_INPUT_BYTES = 64 * 1024 * 1024
    MAX_MEDIA_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_RETAINED_OUTPUT_BYTES = 512 * 1024 * 1024
    MAX_MEDIA_ACTIVE = 4
    MAX_MEDIA_QUEUED = 20
    MAX_WORKERS = 4
    READ_CHUNK_BYTES = 1024 * 1024
    JOB_TTL = 1800

    def __init__(
        self,
        selections: FileSelectionStore,
        clock=time.monotonic,
        executor=None,
        staging_root=None,
        import_store: MediaImportStore | None = None,
        image_staging_store: MediaStagingStore | None = None,
        watermark_staging_store: MediaStagingStore | None = None,
    ):
        self.selections = selections
        self.import_store = import_store
        self.image_staging_store = image_staging_store
        self.watermark_staging_store = watermark_staging_store
        self.clock = clock
        self.jobs = {}
        self.artifacts = {}
        self.retained_bytes = 0
        self.lock = threading.RLock()
        self.root = staging_root or tempfile.mkdtemp(prefix="officekit-media-")
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        self.executor = executor or ThreadPoolExecutor(max_workers=self.MAX_WORKERS, thread_name_prefix="officekit-media")

    def submit(self, request, *, output_sequence_start=1):
        if isinstance(output_sequence_start, bool) or not isinstance(output_sequence_start, int) or not 1 <= output_sequence_start <= 10_000:
            raise ValueError("Output sequence must be an integer from 1 to 10000")
        if not isinstance(request, MediaJobCreate):
            request = MediaJobCreate.model_validate(request)
        with self.lock:
            self._prune()
            live = [job for job in self.jobs.values() if job.state in {"queued", "running"}]
            if len(live) >= self.MAX_MEDIA_ACTIVE + self.MAX_MEDIA_QUEUED:
                raise MediaJobCapacityError("Media queue is full")
            if sum(job.state == "queued" for job in live) >= self.MAX_MEDIA_QUEUED:
                raise MediaJobCapacityError("Media queue is full")
            items = []
            watermark_image = None
            try:
                for sequence, request_item in enumerate(request.items, output_sequence_start):
                    item = self._resolve_item(request_item)
                    item.sequence = sequence
                    items.append(item)
                if request.watermark_staging_id is not None:
                    if self.watermark_staging_store is None:
                        raise MediaOperationUnavailableError("Image watermarking is not available in this build.")
                    grant = self.watermark_staging_store.claim(str(request.watermark_staging_id))
                    try:
                        watermark_image = self.watermark_staging_store.read(grant)
                    finally:
                        self.watermark_staging_store.release(grant)
            except Exception:
                if self.image_staging_store is not None:
                    for item in items:
                        if item.staged_image is not None:
                            self.image_staging_store.release(item.staged_image)
                raise
            selection_ids = tuple(sorted({item.selected.selection_id for item in items if item.selected is not None}))
            for selection_id in selection_ids:
                self.selections.pin(selection_id)
            job_id = str(uuid.uuid4())
            job = MediaJob(job_id, selection_ids, items, watermark_image=watermark_image)
            self.jobs[job_id] = job
            try:
                self.executor.submit(self._run, job)
            except Exception:
                self.jobs.pop(job_id, None)
                for selection_id in selection_ids:
                    self.selections.unpin(selection_id)
                if self.image_staging_store is not None:
                    for item in items:
                        if item.staged_image is not None:
                            self.image_staging_store.release(item.staged_image)
                raise
            return {"id": job_id, "state": "queued"}

    def _resolve_item(self, item):
        source = item.source
        if isinstance(source, ImportedSource):
            if self.import_store is None:
                raise MediaImportUnavailableError("Public URL imports are not available in this build.")
            grant = self.import_store.claim(str(source.import_id))
            return MediaItem(str(uuid.uuid4()), None, grant.filename, item.operations, item.output_name_template, import_grant=grant)
        if isinstance(source, StagedImageSource):
            if self.image_staging_store is None:
                raise MediaImportUnavailableError("Screenshot handoff is not available in this build.")
            grant = self.image_staging_store.claim(str(source.staging_id))
            return MediaItem(str(uuid.uuid4()), None, grant.filename, item.operations, item.output_name_template, staged_image=grant)
        if not isinstance(source, SelectedSource):
            raise MediaImportUnavailableError("URL imports are unavailable until the safe local import adapter is ready.")
        selection_id = str(source.selection_id)
        self.selections.get(selection_id)
        selected = next((entry for entry in self.selections.iter_files(selection_id) if entry.id == str(source.file_id)), None)
        if selected is None:
            raise FileNotFoundError("Selected media file is unavailable")
        if selected.signature[2] > self.MAX_MEDIA_INPUT_BYTES:
            raise MediaInputTooLargeError("This media adapter currently supports files up to 64 MiB.")
        safe_name = selected.name.replace("\\", "/").rsplit("/", 1)[-1]
        return MediaItem(str(source.file_id), selected, safe_name, item.operations, item.output_name_template)

    def status(self, job_id):
        with self.lock:
            self._prune()
            job = self._get(job_id)
            return self._payload(job)

    @staticmethod
    def _payload(job):
        return {
            "id": job.id,
            "state": job.state,
            "progress": job.progress,
            "total": len(job.items),
            "phase": job.phase,
            "items": [{
                "fileId": item.source_id,
                "name": item.name,
                "state": item.state,
                "artifactId": item.artifact_id,
                "outputName": item.output_name,
                "outputType": item.output_type,
                "outputBytes": item.output_size,
                "inputBytes": item.input_size,
                "attributes": dict(item.attributes),
                "errorCode": item.error_code,
            } for item in job.items],
        }

    def cancel(self, job_id):
        with self.lock:
            job = self._get(job_id)
            if job.state not in {"queued", "running"}:
                raise MediaJobConflictError("This media job can no longer be cancelled")
            job.cancel.set()
            return {"id": job.id, "state": job.state, "cancellationRequested": True}

    def artifact(self, artifact_id):
        with self.lock:
            self._prune()
            reference = self.artifacts.get(artifact_id)
            if reference is None:
                raise MediaJobNotFoundError("Media artifact is unavailable")
            job_id, path, item, expected = reference
            job = self.jobs.get(job_id)
            if job is None or job.expires <= self.clock():
                raise MediaJobNotFoundError("Media artifact is unavailable")
            descriptor = None
            try:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
                value = os.fstat(descriptor)
            except OSError as error:
                raise MediaJobNotFoundError("Media artifact is unavailable") from error
            if not stat.S_ISREG(value.st_mode) or identity(value) != expected:
                os.close(descriptor)
                raise MediaJobNotFoundError("Media artifact is unavailable")
            return {
                "file": os.fdopen(descriptor, "rb"),
                "displayName": item.output_name,
                "mediaType": item.output_type,
                "sizeBytes": item.output_size,
            }

    def _get(self, job_id):
        try:
            canonical = str(uuid.UUID(job_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise MediaJobNotFoundError("Media job is unavailable") from error
        job = self.jobs.get(canonical)
        if job is None or (job.state not in {"queued", "running"} and job.expires <= self.clock()):
            raise MediaJobNotFoundError("Media job is unavailable")
        return job

    def _prune(self):
        for job_id, job in tuple(self.jobs.items()):
            if job.state not in {"queued", "running"} and job.expires <= self.clock():
                for artifact_id in tuple(job.artifact_paths):
                    self.artifacts.pop(artifact_id, None)
                self.retained_bytes = max(0, self.retained_bytes - job.result_bytes)
                if os.path.isdir(os.path.join(self.root, job_id)):
                    shutil.rmtree(os.path.join(self.root, job_id), ignore_errors=True)
                del self.jobs[job_id]

    def _run(self, job):
        with self.lock:
            if job.cancel.is_set():
                job.state = "cancelled"
                job.phase = "Cancelled"
                for item in job.items:
                    item.state = "cancelled"
                job.expires = self.clock() + self.JOB_TTL
                self._release_selections(job)
                self._release_staged_images(job)
                job.watermark_image = None
                return
            job.state = "running"
        try:
            for index, item in enumerate(job.items):
                if job.cancel.is_set():
                    item.state = "cancelled"
                    for pending in job.items[index + 1:]:
                        pending.state = "cancelled"
                    break
                with self.lock:
                    job.phase = f"Preparing file {index + 1} of {len(job.items)}"
                item.state = "running"
                output = None
                try:
                    output = self._process_item(job, item)
                    if job.cancel.is_set():
                        item.state = "cancelled"
                    else:
                        self._retain_artifact(job, item, output)
                        item.state = "ready"
                except (NativeMediaCancelledError, MediaPdfCancelledError):
                    item.state, item.error_code = "cancelled", None
                except MediaImportCancelledError:
                    item.state, item.error_code = "cancelled", None
                except MediaImportTooLargeError:
                    item.state, item.error_code = "failed", "input_limit"
                except MediaImportUnsafeTargetError:
                    item.state, item.error_code = "failed", "unsafe_target"
                except MediaImportRejectedError:
                    item.state, item.error_code = "failed", "import_rejected"
                except MediaOperationUnavailableError:
                    item.state, item.error_code = "failed", "engine_unavailable"
                except MediaInputTooLargeError:
                    item.state, item.error_code = "failed", "input_limit"
                except (ImageOutputLimitError, ScreenshotOutputLimitError):
                    item.state, item.error_code = "failed", "output_limit"
                except ConversionInputError:
                    item.state, item.error_code = "failed", "invalid_media"
                except PermissionError:
                    item.state, item.error_code = "failed", "permission_denied"
                except FileNotFoundError:
                    item.state, item.error_code = "failed", "source_unavailable"
                except ValueError:
                    item.state, item.error_code = "failed", "source_changed"
                except OSError:
                    item.state, item.error_code = "failed", "read_failed"
                except Exception:
                    item.state, item.error_code = "failed", "operation_failed"
                finally:
                    if isinstance(output, MediaFileOutput):
                        shutil.rmtree(output.workspace, ignore_errors=True)
                job.progress = index + 1

            completed = [item for item in job.items if item.state == "ready"]
            if job.cancel.is_set():
                job.state, job.phase = "cancelled", "Cancelled"
            elif len(completed) == len(job.items):
                job.state, job.phase = "ready", "Complete"
            elif completed:
                job.state, job.phase = "partial", "Completed with unavailable files"
            else:
                job.state, job.phase = "failed", "Could not prepare media"
        finally:
            job.watermark_image = None
            job.expires = self.clock() + self.JOB_TTL
            self._release_selections(job)
            self._release_staged_images(job)

    def _process_item(self, job, item):
        native_kinds = {
            operation.operation_id.split("-", 1)[0]
            for operation in item.operations
            if operation.operation_id.startswith(("video-", "audio-"))
        }
        if native_kinds:
            if len(native_kinds) != 1 or any(
                operation.operation_id.split("-", 1)[0] not in native_kinds
                for operation in item.operations
            ):
                raise ConversionInputError()
            return self._process_native_file_item(job, item)
        selected = item.selected
        if item.staged_image is not None:
            if self.image_staging_store is None:
                raise MediaImportUnavailableError("Screenshot handoff is not available.")
            grant = item.staged_image
            content = self.image_staging_store.read(grant)
            self.image_staging_store.release(grant)
            item.staged_image = None
        elif selected is None:
            if self.import_store is None or item.import_grant is None:
                raise MediaImportUnavailableError("URL imports are unavailable")
            imported_bytes, imported_name, _content_type = self.import_store.download(item.import_grant, job.cancel)
            item.name = imported_name
            content = imported_bytes
        else:
            if selected.signature[2] > self.MAX_MEDIA_INPUT_BYTES:
                raise MediaInputTooLargeError("Source exceeds the media input limit")
            with self.selections.open_file(selected) as source:
                content = bytearray()
                while True:
                    if job.cancel.is_set():
                        return None
                    chunk = source.read(self.READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > self.MAX_MEDIA_INPUT_BYTES:
                        raise MediaInputTooLargeError("Source exceeds the media input limit")
            content = bytes(content)
        if job.cancel.is_set():
            return None
        if len(content) > self.MAX_MEDIA_INPUT_BYTES:
            raise MediaInputTooLargeError("Source exceeds the media input limit")
        item.input_size = len(content)
        output = MediaOptimizerEngine.execute(
            content, item.name, item.operations, cancel_event=job.cancel,
            watermark_image=job.watermark_image,
        )
        if len(output.data) > self.MAX_MEDIA_OUTPUT_BYTES:
            raise ImageOutputLimitError("Media output exceeds the supported limit")
        return output

    def _process_native_file_item(self, job, item):
        workspace = tempfile.mkdtemp(prefix="media-native-", dir=self.root)
        source_path = os.path.join(workspace, f"source-{uuid.uuid4().hex}.{_safe_extension(item.name)}")
        try:
            if item.selected is not None:
                if item.selected.signature[2] > self.MAX_MEDIA_INPUT_BYTES:
                    raise MediaInputTooLargeError("Source exceeds the media input limit")
                with self.selections.open_file(item.selected) as source, open(source_path, "xb") as target:
                    input_size = self._copy_bounded(source, target, job.cancel)
            elif item.import_grant is not None and self.import_store is not None:
                imported_file_download = getattr(self.import_store, "download_to_file", None)
                if imported_file_download is not None:
                    imported_name, _content_type, input_size = imported_file_download(
                        item.import_grant, source_path, job.cancel,
                    )
                    item.name = imported_name
                else:
                    imported_bytes, imported_name, _content_type = self.import_store.download(item.import_grant, job.cancel)
                    item.name = imported_name
                    input_size = len(imported_bytes)
                    if input_size > self.MAX_MEDIA_INPUT_BYTES:
                        raise MediaInputTooLargeError("Source exceeds the media input limit")
                    with open(source_path, "xb") as target:
                        target.write(imported_bytes)
                if input_size > self.MAX_MEDIA_INPUT_BYTES:
                    raise MediaInputTooLargeError("Source exceeds the media input limit")
            else:
                # Staged-image grants are only valid for image operations.
                raise MediaImportUnavailableError("Native audio/video conversion requires a selected or imported media file.")
            if job.cancel.is_set():
                raise NativeMediaCancelledError()
            item.input_size = input_size
            current_path = source_path
            watermark_path = None
            if any(operation.operation_id == "video-watermark-overlay" for operation in item.operations):
                if job.watermark_image is None:
                    raise ConversionInputError("Choose a watermark image before preparing this copy.")
                watermark_path = os.path.join(workspace, "watermark.png")
                with open(watermark_path, "xb") as watermark_file:
                    watermark_file.write(job.watermark_image)
            result = None
            for operation in item.operations:
                previous_path = current_path
                result = convert_native_media_to_file(
                    current_path,
                    item.name,
                    operation.operation_id,
                    operation.options,
                    workspace,
                    cancel_event=job.cancel,
                    **({"watermark_image_path": watermark_path} if operation.operation_id == "video-watermark-overlay" else {}),
                )
                current_path, extension, media_type, attributes, size = result
                if previous_path != current_path:
                    os.unlink(previous_path)
            if result is None:
                raise MediaOperationUnavailableError("No native media operation was selected.")
            return MediaFileOutput(current_path, workspace, extension, media_type, size, attributes)
        except NativeMediaUnavailableError as error:
            shutil.rmtree(workspace, ignore_errors=True)
            raise MediaOperationUnavailableError("This media operation is not available in this build.") from error
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    def _copy_bounded(self, source, target, cancel_event):
        total = 0
        while True:
            if cancel_event.is_set():
                raise NativeMediaCancelledError()
            chunk = source.read(self.READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > self.MAX_MEDIA_INPUT_BYTES:
                raise MediaInputTooLargeError("Source exceeds the media input limit")
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
        return total

    def _retain_artifact(self, job, item, output):
        artifact_id = str(uuid.uuid4())
        media = item.operations[0].operation_id.split("-", 1)[0]
        output_name = render_output_name(item.output_name_template, item.name, output.extension, media, item.sequence)
        job_directory = os.path.join(self.root, job.id)
        os.makedirs(job_directory, mode=0o700, exist_ok=True)
        path = os.path.join(job_directory, artifact_id)
        with self.lock:
            output_size = output.size if isinstance(output, MediaFileOutput) else len(output.data)
            if self.retained_bytes + output_size > self.MAX_RETAINED_OUTPUT_BYTES:
                raise ImageOutputLimitError("Retained media output limit reached")
            created = False
            try:
                with open(path, "xb") as stream:
                    created = True
                    if isinstance(output, MediaFileOutput):
                        with open(output.path, "rb") as source:
                            copied = 0
                            while chunk := source.read(self.READ_CHUNK_BYTES):
                                copied += len(chunk)
                                if copied > self.MAX_MEDIA_OUTPUT_BYTES:
                                    raise ImageOutputLimitError("Media output exceeds the supported limit")
                                stream.write(chunk)
                        if copied != output.size:
                            raise OSError("Media output changed while it was retained")
                    else:
                        stream.write(output.data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    artifact_identity = identity(os.fstat(stream.fileno()))
            except Exception:
                if created:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                raise
            item.artifact_id = artifact_id
            item.output_name = output_name
            item.output_type = output.media_type
            item.output_size = output_size
            item.attributes = dict(output.attributes)
            job.artifact_paths[artifact_id] = path
            job.result_bytes += output_size
            self.retained_bytes += output_size
            self.artifacts[artifact_id] = (job.id, path, item, artifact_identity)

    def _release_selections(self, job):
        for selection_id in job.selection_ids:
            self.selections.unpin(selection_id)

    def _release_staged_images(self, job):
        if self.image_staging_store is None:
            return
        for item in job.items:
            if item.staged_image is not None:
                self.image_staging_store.release(item.staged_image)
                item.staged_image = None
        job.selection_ids = ()

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                if job.state in {"queued", "running"}:
                    job.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for job in self.jobs.values():
                self._release_selections(job)
            shutil.rmtree(self.root, ignore_errors=True)
            self.jobs.clear()
            self.artifacts.clear()
            self.retained_bytes = 0
        if self.image_staging_store is not None:
            self.image_staging_store.close()
        if self.watermark_staging_store is not None:
            self.watermark_staging_store.close()
