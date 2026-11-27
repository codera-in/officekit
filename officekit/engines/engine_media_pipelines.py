"""Local, bounded storage for reusable typed Media Toolkit pipelines."""

import json
import os
import stat
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager

from pydantic import Field, StrictStr, field_validator, model_validator

from .engine_media_models import MediaOperation, StrictModel, validate_operation_sequence
from .engine_media_naming import validate_output_name_template

MAX_PIPELINES = 50
MAX_PIPELINE_FILE_BYTES = 128 * 1024
MAX_PIPELINE_NAME = 64
_MEDIA_COORDINATION_LOCKS = {}
_MEDIA_COORDINATION_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path):
    with _MEDIA_COORDINATION_LOCKS_GUARD:
        return _MEDIA_COORDINATION_LOCKS.setdefault(path, threading.RLock())


@contextmanager
def _cross_process_lock(lock_path):
    """Serialize related pipeline and preset-zone mutations across threads/processes."""
    lock_path = os.path.abspath(lock_path)
    thread_lock = _thread_lock_for(lock_path)
    with thread_lock:
        os.makedirs(os.path.dirname(lock_path), mode=0o700, exist_ok=True)
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as error:
            raise MediaPipelineStoreError("The saved automation settings cannot be locked safely") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise MediaPipelineStoreError("The saved automation lock is invalid")
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
                except OSError as error:
                    raise MediaPipelineStoreError("The saved automation settings cannot be locked safely") from error
                try:
                    yield
                finally:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                except OSError as error:
                    raise MediaPipelineStoreError("The saved automation settings cannot be locked safely") from error
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

OPERATION_MEDIA = {
    "image-convert": "image", "image-optimize": "image", "image-fit-size": "image",
    "image-resize": "image", "image-crop": "image", "image-strip-metadata": "image",
    "image-watermark": "image", "video-optimize": "video", "video-fit-size": "video",
    "video-crop": "video", "video-resize": "video", "video-speed": "video", "video-mute": "video",
    "video-strip-metadata": "video", "video-to-gif": "video", "video-watermark-overlay": "video", "pdf-lossless-compress": "pdf", "pdf-visual-optimize": "pdf",
    "pdf-fit-size": "pdf", "pdf-crop": "pdf", "pdf-uncrop": "pdf", "pdf-pages-to-images": "pdf", "audio-optimize": "audio",
    "audio-convert": "audio", "audio-fit-size": "audio", "audio-normalize": "audio",
    "audio-artwork": "audio", "audio-speed": "audio",
}


def media_pipeline_path():
    if sys.platform == "darwin":
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    elif os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        root = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(root, "OfficeKit", "media-pipelines.json")


class MediaPipelineCreate(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=MAX_PIPELINE_NAME)
    media: StrictStr
    operations: list[MediaOperation] = Field(min_length=1, max_length=8)
    output_name_template: StrictStr | None = Field(default=None, alias="outputNameTemplate", max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Pipeline name must contain visible characters")
        return value

    @field_validator("output_name_template")
    @classmethod
    def validate_template(cls, value):
        return validate_output_name_template(value)

    @model_validator(mode="after")
    def validate_media(self):
        if self.media not in {"image", "video", "pdf", "audio"}:
            raise ValueError("Unsupported pipeline media type")
        if any(OPERATION_MEDIA.get(operation.operation_id) != self.media for operation in self.operations):
            raise ValueError("Every pipeline step must use the selected media type")
        validate_operation_sequence(self.operations)
        return self


class MediaPipelineRename(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=MAX_PIPELINE_NAME)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Pipeline name must contain visible characters")
        return value


class MediaPipelineStoreError(RuntimeError):
    pass


class MediaPipelineStore:
    def __init__(self, path=None):
        self.path = path or media_pipeline_path()
        self.lock = threading.RLock()

    def list(self):
        with self._locked_store():
            return self._read()

    @contextmanager
    def coordination_lock(self):
        """Lock cross-store automation changes before reading dependent zone settings."""
        with _cross_process_lock(os.path.abspath(self.path) + ".automation.lock"):
            yield

    def create(self, definition: MediaPipelineCreate):
        with self._locked_store():
            entries = self._read()
            folded = definition.name.casefold()
            if any(entry["name"].casefold() == folded for entry in entries):
                raise ValueError("A pipeline with this name already exists")
            if len(entries) >= MAX_PIPELINES:
                raise OverflowError("The pipeline list is full")
            entry = {
                "id": str(uuid.uuid4()),
                "name": definition.name,
                "media": definition.media,
                "operations": [operation.model_dump(by_alias=True, mode="json") for operation in definition.operations],
                "outputNameTemplate": definition.output_name_template,
                "state": "paused",
            }
            self._write([*entries, entry])
            return entry

    def delete(self, pipeline_id):
        with self._locked_store():
            entries = self._read()
            remaining = [entry for entry in entries if entry["id"] != pipeline_id]
            if len(remaining) == len(entries):
                return False
            self._write(remaining)
            return True

    def rename(self, pipeline_id, definition: MediaPipelineRename):
        try:
            canonical_id = str(uuid.UUID(pipeline_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("Saved pipeline is unavailable") from error
        if canonical_id != pipeline_id:
            raise FileNotFoundError("Saved pipeline is unavailable")
        with self._locked_store():
            entries = self._read()
            target = next((entry for entry in entries if entry["id"] == canonical_id), None)
            if target is None:
                raise FileNotFoundError("Saved pipeline is unavailable")
            folded = definition.name.casefold()
            if any(entry["id"] != canonical_id and entry["name"].casefold() == folded for entry in entries):
                raise ValueError("A pipeline with this name already exists")
            updated = [{**entry, "name": definition.name} if entry["id"] == canonical_id else entry for entry in entries]
            self._write(updated)
            return next(entry for entry in updated if entry["id"] == canonical_id)

    def update(self, pipeline_id, definition: MediaPipelineCreate):
        try:
            canonical_id = str(uuid.UUID(pipeline_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("Saved pipeline is unavailable") from error
        if canonical_id != pipeline_id:
            raise FileNotFoundError("Saved pipeline is unavailable")
        with self._locked_store():
            entries = self._read()
            target = next((entry for entry in entries if entry["id"] == canonical_id), None)
            if target is None:
                raise FileNotFoundError("Saved pipeline is unavailable")
            if definition.media != target["media"]:
                raise ValueError("A saved pipeline's media type cannot be changed; create a new pipeline")
            folded = definition.name.casefold()
            if any(entry["id"] != canonical_id and entry["name"].casefold() == folded for entry in entries):
                raise ValueError("A pipeline with this name already exists")
            updated_entry = {
                "id": canonical_id,
                **definition.model_dump(by_alias=True, mode="json"),
                "state": "paused",
            }
            updated = [updated_entry if entry["id"] == canonical_id else entry for entry in entries]
            self._write(updated)
            return updated_entry

    @contextmanager
    def _locked_store(self):
        """Serialize store snapshots and read-modify-write operations across processes."""
        with self.lock:
            lock_path = os.path.abspath(self.path) + ".lock"
            os.makedirs(os.path.dirname(lock_path), mode=0o700, exist_ok=True)
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except OSError as error:
                raise MediaPipelineStoreError("The saved pipeline file cannot be locked safely") from error
            try:
                lock_metadata = os.fstat(descriptor)
                if not stat.S_ISREG(lock_metadata.st_mode):
                    raise MediaPipelineStoreError("The saved pipeline lock is invalid")
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)
                if os.name == "nt":
                    import msvcrt

                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    try:
                        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
                    except OSError as error:
                        raise MediaPipelineStoreError("The saved pipeline file cannot be locked safely") from error
                    try:
                        yield
                    finally:
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX)
                    except OSError as error:
                        raise MediaPipelineStoreError("The saved pipeline file cannot be locked safely") from error
                    try:
                        yield
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return []
        except OSError as error:
            raise MediaPipelineStoreError("The saved pipeline file cannot be opened safely") from error
        try:
            value = os.fstat(descriptor)
            if not stat.S_ISREG(value.st_mode) or value.st_size > MAX_PIPELINE_FILE_BYTES:
                raise MediaPipelineStoreError("The saved pipeline file is invalid or too large")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_PIPELINE_FILE_BYTES + 1)
            payload = json.loads(raw)
            if not isinstance(payload, list) or len(payload) > MAX_PIPELINES:
                raise ValueError("Invalid pipeline collection")
            validated = []
            for entry in payload:
                if not isinstance(entry, dict) or set(entry) not in (
                    {"id", "name", "media", "operations", "state"},
                    {"id", "name", "media", "operations", "outputNameTemplate", "state"},
                ):
                    raise ValueError("Invalid pipeline entry")
                if entry["state"] != "paused":
                    raise ValueError("Saved automation must start paused")
                parsed = MediaPipelineCreate.model_validate({
                    "name": entry["name"], "media": entry["media"], "operations": entry["operations"],
                    "outputNameTemplate": entry.get("outputNameTemplate"),
                })
                uuid.UUID(entry["id"])
                validated.append({"id": entry["id"], **parsed.model_dump(by_alias=True, mode="json"), "state": "paused"})
            return validated
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            raise MediaPipelineStoreError("Saved pipelines are invalid; the file was left unchanged") from error
        finally:
            os.close(descriptor)

    def _write(self, entries):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_PIPELINE_FILE_BYTES:
            raise OverflowError("Saved pipelines exceed the local configuration limit")
        descriptor, temporary = tempfile.mkstemp(prefix=".media-pipelines-", dir=directory)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
