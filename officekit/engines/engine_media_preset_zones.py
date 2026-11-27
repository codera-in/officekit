"""Private named drop-zone bindings for saved Media Toolkit pipelines."""

import json
import os
import stat
import tempfile
import threading
import uuid

from pydantic import Field, StrictBool, StrictStr, field_validator

from .engine_media_models import StrictModel
from .engine_media_pipelines import MediaPipelineStore, MediaPipelineStoreError, media_pipeline_path

MAX_PRESET_ZONES = 30
MAX_PRESET_ZONE_FILE_BYTES = 64 * 1024
MAX_PRESET_ZONE_NAME = 48


def media_preset_zone_path():
    return os.path.join(os.path.dirname(media_pipeline_path()), "media-preset-zones.json")


class MediaPresetZoneCreate(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=MAX_PRESET_ZONE_NAME)
    pipeline_id: uuid.UUID = Field(alias="pipelineId")

    @field_validator("pipeline_id", mode="before")
    @classmethod
    def parse_pipeline_id(cls, value):
        return uuid.UUID(value) if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Preset-zone name must contain visible characters")
        return value


class MediaPresetZoneUpdate(StrictModel):
    enabled: StrictBool


class MediaPresetZoneRename(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=MAX_PRESET_ZONE_NAME)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Preset-zone name must contain visible characters")
        return value


class MediaPresetZoneRebind(StrictModel):
    pipeline_id: uuid.UUID = Field(alias="pipelineId")

    @field_validator("pipeline_id", mode="before")
    @classmethod
    def parse_pipeline_id(cls, value):
        return uuid.UUID(value) if isinstance(value, str) else value


class MediaPresetZoneResponse(StrictModel):
    id: StrictStr
    name: StrictStr
    pipeline_id: StrictStr = Field(alias="pipelineId")
    enabled: StrictBool

    @field_validator("id", "pipeline_id")
    @classmethod
    def validate_identifiers(cls, value):
        return str(uuid.UUID(value))


class MediaPresetZoneStoreError(RuntimeError):
    pass


class MediaPresetZoneStore:
    """Persist zone-to-pipeline bindings; enablement lasts only for this app session."""

    def __init__(self, pipelines: MediaPipelineStore, path=None):
        self.path = path or media_preset_zone_path()
        self.pipelines = pipelines
        self.lock = threading.RLock()
        self.enabled_ids: set[str] = set()

    def list(self):
        with self.lock:
            return [self._response(entry) for entry in self._read()]

    def list_bindings(self):
        """Return durable bindings without implying this process owns session enablement."""
        with self.lock:
            return [dict(entry) for entry in self._read()]

    def create(self, definition: MediaPresetZoneCreate):
        with self.pipelines.coordination_lock(), self.lock:
            entries = self._read()
            if len(entries) >= MAX_PRESET_ZONES:
                raise OverflowError("The preset-zone list is full")
            if any(entry["name"].casefold() == definition.name.casefold() for entry in entries):
                raise ValueError("A preset zone with this name already exists")
            pipeline_id = str(definition.pipeline_id)
            if not any(pipeline["id"] == pipeline_id for pipeline in self.pipelines.list()):
                raise FileNotFoundError("Saved pipeline is unavailable")
            entry = {"id": str(uuid.uuid4()), "name": definition.name, "pipelineId": pipeline_id}
            self._write([*entries, entry])
            return self._response(entry)

    def set_enabled(self, zone_id, enabled):
        with self.lock:
            entries = self._read()
            entry = next((item for item in entries if item["id"] == zone_id), None)
            if entry is None:
                raise FileNotFoundError("Preset zone is unavailable")
            if enabled:
                if not any(pipeline["id"] == entry["pipelineId"] for pipeline in self.pipelines.list()):
                    raise FileNotFoundError("Saved pipeline is unavailable")
                self.enabled_ids.add(zone_id)
            else:
                self.enabled_ids.discard(zone_id)
            return self._response(entry)

    def rename(self, zone_id, definition: MediaPresetZoneRename):
        try:
            canonical_id = str(uuid.UUID(zone_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("Preset zone is unavailable") from error
        if canonical_id != zone_id:
            raise FileNotFoundError("Preset zone is unavailable")
        with self.pipelines.coordination_lock(), self.lock:
            entries = self._read()
            target = next((item for item in entries if item["id"] == canonical_id), None)
            if target is None:
                raise FileNotFoundError("Preset zone is unavailable")
            folded = definition.name.casefold()
            if any(item["id"] != canonical_id and item["name"].casefold() == folded for item in entries):
                raise ValueError("A preset zone with this name already exists")
            updated = [{**item, "name": definition.name} if item["id"] == canonical_id else item for item in entries]
            self._write(updated)
            return self._response(next(item for item in updated if item["id"] == canonical_id))

    def rebind(self, zone_id, definition: MediaPresetZoneRebind):
        try:
            canonical_id = str(uuid.UUID(zone_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("Preset zone is unavailable") from error
        if canonical_id != zone_id:
            raise FileNotFoundError("Preset zone is unavailable")
        pipeline_id = str(definition.pipeline_id)
        with self.pipelines.coordination_lock(), self.lock:
            entries = self._read()
            target = next((item for item in entries if item["id"] == canonical_id), None)
            if target is None:
                raise FileNotFoundError("Preset zone is unavailable")
            if not any(pipeline["id"] == pipeline_id for pipeline in self.pipelines.list()):
                raise FileNotFoundError("Saved pipeline is unavailable")
            updated = [
                {**item, "pipelineId": pipeline_id} if item["id"] == canonical_id else item
                for item in entries
            ]
            self._write(updated)
            return self._response(next(item for item in updated if item["id"] == canonical_id))

    def delete(self, zone_id):
        with self.pipelines.coordination_lock(), self.lock:
            entries = self._read()
            remaining = [entry for entry in entries if entry["id"] != zone_id]
            if len(remaining) == len(entries):
                return False
            self._write(remaining)
            self.enabled_ids.discard(zone_id)
            return True

    def uses_pipeline(self, pipeline_id):
        with self.lock:
            return any(entry["pipelineId"] == pipeline_id for entry in self._read())

    def _response(self, entry):
        return MediaPresetZoneResponse.model_validate({
            "id": entry["id"],
            "name": entry["name"],
            "pipelineId": entry["pipelineId"],
            "enabled": entry["id"] in self.enabled_ids,
        }).model_dump(by_alias=True)

    def _read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return []
        except OSError as error:
            raise MediaPresetZoneStoreError("The saved preset-zone file cannot be opened safely") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PRESET_ZONE_FILE_BYTES:
                raise MediaPresetZoneStoreError("The saved preset-zone file is invalid or too large")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_PRESET_ZONE_FILE_BYTES + 1)
            payload = json.loads(raw)
            if not isinstance(payload, list) or len(payload) > MAX_PRESET_ZONES:
                raise ValueError("Invalid preset-zone collection")
            validated = []
            names = set()
            for entry in payload:
                if not isinstance(entry, dict) or set(entry) != {"id", "name", "pipelineId"}:
                    raise ValueError("Invalid preset-zone entry")
                parsed = MediaPresetZoneCreate.model_validate({"name": entry["name"], "pipelineId": entry["pipelineId"]})
                zone_id = str(uuid.UUID(entry["id"]))
                if parsed.name.casefold() in names:
                    raise ValueError("Duplicate preset-zone name")
                names.add(parsed.name.casefold())
                validated.append({"id": zone_id, **parsed.model_dump(by_alias=True, mode="json")})
            return validated
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            raise MediaPresetZoneStoreError("Saved preset zones are invalid; the file was left unchanged") from error
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
        if len(payload) > MAX_PRESET_ZONE_FILE_BYTES:
            raise OverflowError("Saved preset zones exceed the local configuration limit")
        descriptor, temporary = tempfile.mkstemp(prefix=".media-preset-zones-", dir=directory)
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
