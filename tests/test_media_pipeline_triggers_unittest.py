import json
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_pipelines import MediaPipelineCreate, MediaPipelineStore
from officekit.engines.engine_media_pipeline_triggers import (
    MediaPipelineTriggerBinding,
    MediaPipelineTriggerStore,
    MediaPipelineTriggerStoreError,
)
from officekit.media_routes import create_media_router


def _pipeline(store, name, media="image"):
    operation_id = {"image": "image-optimize", "video": "video-optimize"}[media]
    options = {"quality": 75, "preserveMetadata": False} if media == "image" else {"targetFormat": "m4v", "quality": "balanced"}
    return store.create(MediaPipelineCreate.model_validate({
        "name": name, "media": media,
        "operations": [{"operationId": operation_id, "options": options}],
    }))


def test_trigger_bindings_are_private_typed_and_shared(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    pipeline = _pipeline(pipelines, "Clipboard images")
    path = tmp_path / "settings" / "media-pipeline-triggers.json"
    store = MediaPipelineTriggerStore(pipelines, str(path))
    binding = MediaPipelineTriggerBinding.model_validate({"pipelineId": pipeline["id"]})

    assert store.set("clipboard", binding) == {"trigger": "clipboard", "pipelineId": pipeline["id"]}
    store.set("drop-zone", binding)
    assert MediaPipelineTriggerStore(pipelines, str(path)).list() == {
        "clipboard": pipeline["id"], "drop-zone": pipeline["id"],
    }
    assert store.uses_pipeline(pipeline["id"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert str(tmp_path) not in path.read_text()
    assert store.clear("clipboard") is True
    assert store.clear("clipboard") is False
    assert store.list() == {"drop-zone": pipeline["id"]}


def test_clipboard_trigger_accepts_only_image_pipeline_and_existing_ids(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    video_pipeline = _pipeline(pipelines, "Video", "video")
    store = MediaPipelineTriggerStore(pipelines, str(tmp_path / "triggers.json"))
    with pytest.raises(ValueError, match="image operations"):
        store.set("clipboard", MediaPipelineTriggerBinding.model_validate({"pipelineId": video_pipeline["id"]}))
    with pytest.raises(ValueError, match="Unsupported"):
        store.set("unknown", MediaPipelineTriggerBinding.model_validate({"pipelineId": video_pipeline["id"]}))
    with pytest.raises(FileNotFoundError):
        store.set("drop-zone", MediaPipelineTriggerBinding.model_validate({"pipelineId": "d869f223-8368-4266-9160-7e9c8153b973"}))
    assert not store.list()


def test_trigger_store_rejects_symlinks_and_preserves_corrupt_files(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    target = tmp_path / "target.json"
    target.write_text("{}")
    path = tmp_path / "triggers.json"
    path.symlink_to(target)
    with pytest.raises(MediaPipelineTriggerStoreError):
        MediaPipelineTriggerStore(pipelines, str(path)).list()
    assert target.read_text() == "{}"

    path.unlink()
    path.write_text(json.dumps({"unknown": "d869f223-8368-4266-9160-7e9c8153b973"}))
    before = path.read_bytes()
    with pytest.raises(MediaPipelineTriggerStoreError):
        MediaPipelineTriggerStore(pipelines, str(path)).clear("clipboard")
    assert path.read_bytes() == before


def test_pipeline_trigger_api_lifecycle_and_delete_guard(tmp_path):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    triggers = MediaPipelineTriggerStore(pipelines, str(tmp_path / "settings" / "triggers.json"))
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines, pipeline_trigger_store=triggers))
    client = TestClient(app)
    pipeline = client.post("/api/media-pipelines", json={
        "name": "Clipboard images", "media": "image",
        "operations": [{"operationId": "image-optimize", "options": {"quality": 75}}],
    }).json()

    assert client.get("/api/media-pipeline-triggers").json() == {}
    saved = client.put("/api/media-pipeline-triggers/clipboard", json={"pipelineId": pipeline["id"]})
    assert saved.status_code == 200
    assert saved.json() == {"trigger": "clipboard", "pipelineId": pipeline["id"]}
    assert client.get("/api/media-pipeline-triggers").json() == {"clipboard": pipeline["id"]}
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 409
    assert client.delete("/api/media-pipeline-triggers/clipboard").status_code == 204
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 204
    assert client.put("/api/media-pipeline-triggers/invalid", json={"pipelineId": pipeline["id"]}).status_code == 422
