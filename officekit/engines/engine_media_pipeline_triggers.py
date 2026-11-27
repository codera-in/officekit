"""Private bindings that pin saved pipelines to explicit media triggers."""

import json
import os
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager

from pydantic import Field, StrictStr, field_validator

from .engine_media_models import StrictModel
from .engine_media_pipelines import MediaPipelineStore, MediaPipelineStoreError, _cross_process_lock, media_pipeline_path

MAX_TRIGGER_BINDINGS_BYTES = 16 * 1024
TRIGGER_TARGETS = frozenset({"clipboard", "drop-zone"})


def media_pipeline_triggers_path():
    return os.path.join(os.path.dirname(media_pipeline_path()), "media-pipeline-triggers.json")


class MediaPipelineTriggerBinding(StrictModel):
    pipeline_id: uuid.UUID = Field(alias="pipelineId")

    @field_validator("pipeline_id", mode="before")
    @classmethod
    def parse_pipeline_id(cls, value):
        return uuid.UUID(value) if isinstance(value, str) else value


class MediaPipelineTriggerStoreError(RuntimeError):
    pass


class MediaPipelineTriggerStore:
    """Store one optional pipeline binding per trigger, shared by the app and MCP."""

    def __init__(self, pipelines: MediaPipelineStore, path=None):
        self.pipelines = pipelines
        self.path = path or media_pipeline_triggers_path()
        self.lock = threading.RLock()

    def list(self):
        with self._locked():
            return self._read()

    def set(self, target, definition: MediaPipelineTriggerBinding):
        if target not in TRIGGER_TARGETS:
            raise ValueError("Unsupported media pipeline trigger")
        pipeline_id = str(definition.pipeline_id)
        with self.pipelines.coordination_lock(), self._locked():
            pipeline = next((item for item in self.pipelines.list() if item["id"] == pipeline_id), None)
            if pipeline is None:
                raise FileNotFoundError("Saved pipeline is unavailable")
            if target == "clipboard" and pipeline["media"] != "image":
                raise ValueError("Clipboard pipelines must contain image operations")
            bindings = self._read()
            bindings[target] = pipeline_id
            self._write(bindings)
            return {"trigger": target, "pipelineId": pipeline_id}

    def clear(self, target):
        if target not in TRIGGER_TARGETS:
            raise ValueError("Unsupported media pipeline trigger")
        with self.pipelines.coordination_lock(), self._locked():
            bindings = self._read()
            existed = target in bindings
            bindings.pop(target, None)
            if existed:
                self._write(bindings)
            return existed

    def uses_pipeline(self, pipeline_id):
        with self._locked():
            return pipeline_id in self._read().values()

    @contextmanager
    def _locked(self):
        with self.lock:
            with _cross_process_lock(os.path.abspath(self.path) + ".lock"):
                yield

    def _read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise MediaPipelineTriggerStoreError("Saved pipeline triggers could not be opened safely") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_TRIGGER_BINDINGS_BYTES:
                raise MediaPipelineTriggerStoreError("Saved pipeline triggers are invalid or too large")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = json.loads(stream.read(MAX_TRIGGER_BINDINGS_BYTES + 1))
            if not isinstance(payload, dict) or len(payload) > len(TRIGGER_TARGETS):
                raise ValueError("Invalid trigger bindings")
            if not set(payload) <= TRIGGER_TARGETS:
                raise ValueError("Unknown trigger target")
            result = {}
            for target, value in payload.items():
                pipeline_id = str(uuid.UUID(value))
                if pipeline_id != value:
                    raise ValueError("Invalid pipeline identifier")
                result[target] = pipeline_id
            return result
        except MediaPipelineTriggerStoreError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
            raise MediaPipelineTriggerStoreError("Saved pipeline triggers are invalid; the file was left unchanged") from error
        except OSError as error:
            raise MediaPipelineTriggerStoreError("Saved pipeline triggers could not be read safely; the file was left unchanged") from error
        finally:
            os.close(descriptor)

    def _write(self, bindings):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        payload = json.dumps(bindings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_TRIGGER_BINDINGS_BYTES:
            raise OverflowError("Saved pipeline triggers exceed the local configuration limit")
        descriptor, temporary = tempfile.mkstemp(prefix=".media-pipeline-triggers-", dir=directory)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise MediaPipelineTriggerStoreError("Saved pipeline triggers could not be written safely") from error
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
