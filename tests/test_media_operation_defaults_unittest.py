import json
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_operation_defaults import (
    MediaOperationDefaultsStore,
    MediaOperationDefaultsStoreError,
)
from officekit.media_routes import create_media_router


def test_operation_defaults_are_typed_private_and_shared_between_store_instances(tmp_path):
    path = tmp_path / "OfficeKit" / "media-operation-defaults.json"
    store = MediaOperationDefaultsStore(str(path))

    saved = store.put("image-optimize", {"quality": 75, "preserveMetadata": False})

    assert saved == {"quality": 75, "preserveMetadata": False}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert MediaOperationDefaultsStore(str(path)).list() == {"image-optimize": saved}


def test_operation_defaults_reject_unknown_operations_and_invalid_options(tmp_path):
    path = tmp_path / "defaults.json"
    store = MediaOperationDefaultsStore(str(path))

    with pytest.raises(ValueError):
        store.put("run-script", {})
    with pytest.raises(ValueError):
        store.put("image-optimize", {"quality": True})
    assert not path.exists()


def test_operation_defaults_preserve_corrupt_file_and_reject_oversize(tmp_path):
    path = tmp_path / "defaults.json"
    path.write_text('{"image-optimize":{"quality":900}}')
    original = path.read_bytes()
    store = MediaOperationDefaultsStore(str(path))

    with pytest.raises(MediaOperationDefaultsStoreError):
        store.put("image-optimize", {"quality": 70})
    assert path.read_bytes() == original

    path.write_bytes(b" " * (16 * 1024 + 1))
    with pytest.raises(MediaOperationDefaultsStoreError):
        store.list()


def test_operation_defaults_refuse_symlinked_store(tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({}))
    path = tmp_path / "defaults.json"
    path.symlink_to(target)
    store = MediaOperationDefaultsStore(str(path))

    with pytest.raises(MediaOperationDefaultsStoreError):
        store.list()
    assert json.loads(target.read_text()) == {}


def test_operation_defaults_clear_only_settings(tmp_path):
    path = tmp_path / "defaults.json"
    store = MediaOperationDefaultsStore(str(path))
    store.put("image-optimize", {"quality": 70})

    store.clear()

    assert store.list() == {}
    assert path.exists()


def test_operation_defaults_clear_can_remove_one_operation(tmp_path):
    store = MediaOperationDefaultsStore(str(tmp_path / "defaults.json"))
    store.put("image-optimize", {"quality": 70})
    store.put("pdf-crop", {"aspectRatio": "16:9"})

    store.clear("image-optimize")

    assert store.list() == {"pdf-crop": {"aspectRatio": "9:16"}}


def test_operation_default_routes_share_typed_store_and_reject_invalid_updates(tmp_path):
    store = MediaOperationDefaultsStore(str(tmp_path / "defaults.json"))
    app = FastAPI()
    app.include_router(create_media_router(
        MediaJobStore(FileSelectionStore()), operation_defaults_store=store,
    ))
    client = TestClient(app)

    assert client.get("/api/media-operation-defaults").json() == {}
    saved = client.put("/api/media-operation-defaults/image-optimize", json={
        "options": {"quality": 71, "preserveMetadata": False},
    })
    assert saved.status_code == 200
    assert saved.json() == {"operationId": "image-optimize", "options": {"quality": 71, "preserveMetadata": False}}
    assert client.get("/api/media-operation-defaults").json() == {
        "image-optimize": {"quality": 71, "preserveMetadata": False},
    }
    assert client.put("/api/media-operation-defaults/run-script", json={"options": {}}).status_code == 422
    assert client.put("/api/media-operation-defaults/image-optimize", json={
        "options": {"quality": 71}, "path": "/tmp/private",
    }).status_code == 422
    cleared = client.delete("/api/media-operation-defaults")
    assert cleared.status_code == 204
    assert client.get("/api/media-operation-defaults").json() == {}
