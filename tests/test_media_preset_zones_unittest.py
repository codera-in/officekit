import stat
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_pipelines import MediaPipelineCreate, MediaPipelineStore
from officekit.engines.engine_media_preset_zones import (
    MediaPresetZoneCreate,
    MediaPresetZoneRebind,
    MediaPresetZoneRename,
    MediaPresetZoneStore,
    MediaPresetZoneStoreError,
)
from officekit.media_routes import create_media_router


def create_pipeline(pipelines):
    return pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Web images",
        "media": "image",
        "operations": [{"operationId": "image-convert", "options": {"targetFormat": "webp"}}],
    }))


def test_preset_zone_store_is_private_bounded_and_starts_disabled(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    path = tmp_path / "settings" / "media-preset-zones.json"
    zones = MediaPresetZoneStore(pipelines, str(path))
    zone = zones.create(MediaPresetZoneCreate.model_validate({"name": "Web-ready", "pipelineId": pipeline["id"]}))

    assert zone["enabled"] is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert zones.uses_pipeline(pipeline["id"])
    assert pipeline["id"] in path.read_text()
    assert str(tmp_path) not in path.read_text()
    assert zones.set_enabled(zone["id"], True)["enabled"] is True
    assert MediaPresetZoneStore(pipelines, str(path)).list()[0]["enabled"] is False
    assert zones.set_enabled(zone["id"], False)["enabled"] is False
    renamed = zones.rename(zone["id"], MediaPresetZoneRename.model_validate({"name": "Web optimized"}))
    assert renamed["id"] == zone["id"]
    assert renamed["pipelineId"] == pipeline["id"]
    assert renamed["enabled"] is False
    replacement = pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Web archive",
        "media": "image",
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
    }))
    rebound = zones.rebind(zone["id"], MediaPresetZoneRebind.model_validate({"pipelineId": replacement["id"]}))
    assert rebound["id"] == zone["id"]
    assert rebound["name"] == renamed["name"]
    assert rebound["pipelineId"] == replacement["id"]
    assert rebound["enabled"] is False
    with pytest.raises(FileNotFoundError):
        zones.rebind(zone["id"], MediaPresetZoneRebind.model_validate({"pipelineId": "d869f223-8368-4266-9160-7e9c8153b973"}))
    assert zones.delete(zone["id"])
    assert not zones.uses_pipeline(pipeline["id"])


def test_preset_zone_store_works_when_fchmod_is_unavailable(tmp_path, monkeypatch):
    import os

    monkeypatch.delattr(os, "fchmod")
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    zones = MediaPresetZoneStore(pipelines, str(tmp_path / "zones.json"))
    zone = zones.create(MediaPresetZoneCreate.model_validate({"name": "Web-ready", "pipelineId": pipeline["id"]}))
    assert zone["pipelineId"] == pipeline["id"]


def test_preset_zone_store_rejects_duplicate_and_missing_pipeline(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    zones = MediaPresetZoneStore(pipelines, str(tmp_path / "zones.json"))
    definition = MediaPresetZoneCreate.model_validate({"name": "Studio", "pipelineId": pipeline["id"]})
    zones.create(definition)
    with pytest.raises(ValueError, match="already exists"):
        zones.create(MediaPresetZoneCreate.model_validate({"name": "studio", "pipelineId": pipeline["id"]}))
    with pytest.raises(FileNotFoundError):
        zones.create(MediaPresetZoneCreate.model_validate({"name": "Missing", "pipelineId": "d869f223-8368-4266-9160-7e9c8153b973"}))
    with pytest.raises(ValueError):
        MediaPresetZoneCreate.model_validate({"name": "\n", "pipelineId": pipeline["id"]})


def test_preset_zone_store_rejects_corruption_without_replacing_file(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    path = tmp_path / "zones.json"
    path.write_text('[{"unsafe":true}]')
    before = path.read_bytes()
    zones = MediaPresetZoneStore(pipelines, str(path))
    with pytest.raises(MediaPresetZoneStoreError):
        zones.create(MediaPresetZoneCreate.model_validate({"name": "Zone", "pipelineId": pipeline["id"]}))
    assert path.read_bytes() == before


def test_preset_zone_updates_from_independent_store_instances_are_serialized(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    path = str(tmp_path / "zones.json")
    definitions = [
        MediaPresetZoneCreate.model_validate({"name": f"Zone {index}", "pipelineId": pipeline["id"]})
        for index in range(2)
    ]
    stores = [MediaPresetZoneStore(pipelines, path), MediaPresetZoneStore(pipelines, path)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda pair: pair[0].create(pair[1]), zip(stores, definitions)))
    assert len({item["id"] for item in results}) == 2
    assert {item["name"] for item in MediaPresetZoneStore(pipelines, path).list_bindings()} == {"Zone 0", "Zone 1"}


def test_preset_zone_api_lifecycle_and_pipeline_delete_guard(tmp_path):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    zones = MediaPresetZoneStore(pipelines, str(tmp_path / "settings" / "zones.json"))
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines, preset_zone_store=zones))
    client = TestClient(app)

    assert client.get("/api/media-preset-zones").json() == []
    pipeline = client.post("/api/media-pipelines", json={
        "name": "Web images",
        "media": "image",
        "operations": [{"operationId": "image-convert", "options": {"targetFormat": "webp"}}],
    }).json()
    created = client.post("/api/media-preset-zones", json={"name": "Web-ready", "pipelineId": pipeline["id"]})
    assert created.status_code == 201
    zone = created.json()
    assert zone == {"id": zone["id"], "name": "Web-ready", "pipelineId": pipeline["id"], "enabled": False}
    assert client.patch(f"/api/media-preset-zones/{zone['id']}", json={"enabled": True}).json()["enabled"] is True
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 409
    assert client.post("/api/media-preset-zones", json={"name": "Web-ready", "pipelineId": pipeline["id"]}).status_code == 409
    assert client.post("/api/media-preset-zones", json={"name": "Missing", "pipelineId": "d869f223-8368-4266-9160-7e9c8153b973"}).status_code == 404
    assert client.post("/api/media-preset-zones", json={"name": "Unsafe", "pipelineId": pipeline["id"], "path": "/tmp/private"}).status_code == 422
    assert client.patch(f"/api/media-preset-zones/{zone['id']}", json={"enabled": "true"}).status_code == 422
    assert client.delete(f"/api/media-preset-zones/{zone['id']}").status_code == 204
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 204
    assert client.delete(f"/api/media-preset-zones/{zone['id']}").status_code == 404

    jobs.close()
    selections.close()


def test_preset_zone_api_returns_safe_failure_for_corrupt_settings(tmp_path):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    zones_path = tmp_path / "zones.json"
    zones_path.write_text('[{"unsafe":true}]')
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines, preset_zone_store=MediaPresetZoneStore(pipelines, str(zones_path))))
    response = TestClient(app).get("/api/media-preset-zones")
    assert response.status_code == 503
    assert "left unchanged" in response.json()["detail"]
    delete_response = TestClient(app).delete(f"/api/media-pipelines/{pipeline['id']}")
    assert delete_response.status_code == 503
    assert any(item["id"] == pipeline["id"] for item in pipelines.list())
    jobs.close()
    selections.close()


def test_preset_zone_api_renames_without_changing_pipeline_or_enabled_state(tmp_path):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    pipeline = create_pipeline(pipelines)
    replacement = pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Archive images",
        "media": "image",
        "operations": [{"operationId": "image-strip-metadata", "options": {}}],
    }))
    zones = MediaPresetZoneStore(pipelines, str(tmp_path / "zones.json"))
    zone = zones.create(MediaPresetZoneCreate.model_validate({"name": "Before", "pipelineId": pipeline["id"]}))
    zones.set_enabled(zone["id"], True)
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines, preset_zone_store=zones))
    client = TestClient(app)
    response = client.put(f"/api/media-preset-zones/{zone['id']}/name", json={"name": "After"})
    assert response.status_code == 200
    assert response.json() == {"id": zone["id"], "name": "After", "pipelineId": pipeline["id"], "enabled": True}
    duplicate = client.put(f"/api/media-preset-zones/{zone['id']}/name", json={"name": "After"})
    assert duplicate.status_code == 200
    assert client.put(f"/api/media-preset-zones/{zone['id']}/name", json={"name": "\n"}).status_code == 422
    rebound = client.put(f"/api/media-preset-zones/{zone['id']}/pipeline", json={"pipelineId": replacement["id"]})
    assert rebound.status_code == 200
    assert rebound.json() == {"id": zone["id"], "name": "After", "pipelineId": replacement["id"], "enabled": True}
    assert client.put(f"/api/media-preset-zones/{zone['id']}/pipeline", json={"pipelineId": "d869f223-8368-4266-9160-7e9c8153b973"}).status_code == 404
    jobs.close()
    selections.close()
