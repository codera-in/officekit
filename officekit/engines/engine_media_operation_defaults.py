"""Private, typed per-operation defaults shared by the desktop app and MCP server."""

import json
import os
import stat
import tempfile
from contextlib import contextmanager

from .engine_media_models import MediaOperation, OPERATION_OPTIONS
from .engine_media_pipelines import MediaPipelineStoreError, _cross_process_lock, media_pipeline_path

MAX_OPERATION_DEFAULTS_BYTES = 16 * 1024


class MediaOperationDefaultsStoreError(RuntimeError):
    pass


def media_operation_defaults_path():
    return os.path.join(os.path.dirname(media_pipeline_path()), "media-operation-defaults.json")


def _validate_default(operation_id, options):
    operation = MediaOperation.model_validate({"operationId": operation_id, "options": options})
    options_type = OPERATION_OPTIONS[operation.operation_id]
    return options_type.model_validate(operation.options).model_dump(by_alias=True, exclude_unset=True)


class MediaOperationDefaultsStore:
    def __init__(self, path=None):
        self.path = path or media_operation_defaults_path()

    def list(self):
        with self._locked():
            return self._read()

    def put(self, operation_id, options):
        normalized = _validate_default(operation_id, options)
        with self._locked():
            defaults = self._read()
            defaults[operation_id] = normalized
            self._write(defaults)
            return normalized

    def clear(self, operation_id=None):
        with self._locked():
            defaults = self._read()
            if operation_id is None:
                defaults = {}
            else:
                if operation_id not in OPERATION_OPTIONS:
                    raise ValueError("Unsupported media operation")
                defaults.pop(operation_id, None)
            self._write(defaults)

    @contextmanager
    def _locked(self):
        try:
            with _cross_process_lock(os.path.abspath(self.path) + ".lock"):
                yield
        except MediaPipelineStoreError as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults cannot be locked safely") from error

    def _read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults cannot be opened safely") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_OPERATION_DEFAULTS_BYTES:
                raise MediaOperationDefaultsStoreError("Saved operation defaults are invalid or too large")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = json.loads(stream.read(MAX_OPERATION_DEFAULTS_BYTES + 1))
            if not isinstance(payload, dict) or len(payload) > len(OPERATION_OPTIONS):
                raise ValueError("Invalid operation defaults")
            return {operation_id: _validate_default(operation_id, options) for operation_id, options in payload.items()}
        except MediaOperationDefaultsStoreError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults are invalid; the file was left unchanged") from error
        except OSError as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults could not be read safely; the file was left unchanged") from error
        finally:
            os.close(descriptor)

    def _write(self, defaults):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        payload = json.dumps(defaults, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_OPERATION_DEFAULTS_BYTES:
            raise OverflowError("Operation defaults exceed the local configuration limit")
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".media-operation-defaults-", dir=directory)
        except OSError as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults could not be written safely") from error
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb")
            descriptor = None
            with stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise MediaOperationDefaultsStoreError("Saved operation defaults could not be written safely") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
