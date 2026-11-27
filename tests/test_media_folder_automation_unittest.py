import io
import os
import shutil
import time
from pathlib import Path

import officekit.engines.engine_media_folder_automation as folder_automation
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_folder_automation import MediaFolderAutomationStore
from officekit.engines.engine_media_jobs import MediaJobCapacityError, MediaJobStore
from officekit.engines import engine_media_native as native
from officekit.engines.engine_media_pipelines import MediaPipelineCreate, MediaPipelineStore
from officekit.media_routes import create_media_router


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)

    def shutdown(self, **_kwargs):
        return None


def image(path, color):
    content = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(content, format="PNG")
    path.write_bytes(content.getvalue())


def setup(tmp_path, start_worker=False):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, executor=ImmediateExecutor(), staging_root=str(tmp_path / "jobs"))
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    pipeline = pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Clean images", "media": "image", "operations": [
            {"operationId": "image-resize", "options": {"maxWidth": 16, "maxHeight": 12}}
        ],
    }))
    manager = MediaFolderAutomationStore(selections, pipelines, jobs, start_worker=start_worker)
    return selections, jobs, pipelines, manager, pipeline


def test_folder_watch_processes_only_new_stable_files_and_publishes_unique_sibling_copy(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    image(folder / "existing.png", (10, 20, 30))
    (folder / "new_prepared.png").write_bytes(b"user-owned existing output")
    before_existing = (folder / "existing.png").read_bytes()
    selections, jobs, _pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    assert watch["folderName"] == "incoming"
    assert "selectionId" not in watch
    assert str(folder) not in str(watch)
    (folder / "new.png").unlink(missing_ok=True)
    image(folder / "new.png", (90, 80, 70))
    original = (folder / "new.png").read_bytes()

    manager._poll(manager.watches[watch["id"]])
    assert any(value[0][0] == str(folder / "new.png") for value in manager.watches[watch["id"]].candidates.values())
    assert not (folder / "new_prepared (2).png").exists()
    manager._poll(manager.watches[watch["id"]])
    assert len(manager.watches[watch["id"]].jobs) == 1
    manager._poll(manager.watches[watch["id"]])

    output = folder / "new_prepared (2).png"
    assert output.is_file(), manager.list()[0]["lastOutcome"]
    with Image.open(output) as prepared:
        assert prepared.size == (16, 12)
    assert (folder / "new.png").read_bytes() == original
    assert (folder / "existing.png").read_bytes() == before_existing
    updated = manager.list()[0]
    assert updated["processedCount"] == 1
    assert updated["lastOutcome"]["state"] == "ready"
    assert updated["lastOutcome"]["outputName"] == output.name

    manager.set_paused(watch["id"], True)
    image(folder / "later.png", (30, 20, 10))
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])
    assert not (folder / "later_prepared.png").exists()
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_folder_watch_processes_user_files_whose_name_contains_prepared(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, _pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    source = folder / "client_prepared.png"
    image(source, (90, 80, 70))
    original = source.read_bytes()

    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])

    output = folder / "client_prepared_prepared.png"
    assert output.is_file(), manager.list()[0]["lastOutcome"]
    assert source.read_bytes() == original
    for _ in range(3):
        manager._poll(manager.watches[watch["id"]])
    assert manager.list()[0]["processedCount"] == 1
    assert not (folder / "client_prepared_prepared_prepared.png").exists()
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_video_folder_watch_waits_for_five_unchanged_polls_before_processing_recording(tmp_path):
    folder = tmp_path / "recordings"
    folder.mkdir()
    selections, jobs, pipelines, manager, _image_pipeline = setup(tmp_path)
    pipeline = pipelines.create(MediaPipelineCreate.model_validate({
        "name": "Prepare recordings", "media": "video", "operations": [
            {"operationId": "video-optimize", "options": {}}
        ],
    }))
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    submitted = []
    manager._submit = lambda _watch, selected, _pipeline: submitted.append(selected.path)
    recording = folder / "recording.mov"
    recording.write_bytes(b"recording in progress")

    for _ in range(4):
        manager._poll(manager.watches[watch["id"]])
    assert submitted == []

    recording.write_bytes(b"recording finished")
    for _ in range(4):
        manager._poll(manager.watches[watch["id"]])
    assert submitted == []
    manager._poll(manager.watches[watch["id"]])
    assert submitted == [str(recording)]
    assert recording.read_bytes() == b"recording finished"

    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_folder_watch_optimizes_new_heic_recordings_without_replacing_them(tmp_path):
    if not native.native_heif_decoder_available():
        pytest.skip("macOS ImageIO via sips is not available")
    folder = tmp_path / "incoming"
    folder.mkdir()
    source = folder / "recording.heic"
    selections, jobs, pipelines, manager, pipeline = setup(tmp_path)
    pipeline = pipelines.update(pipeline["id"], MediaPipelineCreate.model_validate({
        "name": pipeline["name"], "media": "image",
        "operations": [{"operationId": "image-optimize", "options": {}}],
    }))
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    shutil.copyfile("tests/fixtures/similar-images/cc0/heic/still-medium.heic", source)
    original = source.read_bytes()
    for _ in range(3):
        manager._poll(manager.watches[watch["id"]])
    output = folder / "recording_prepared.webp"
    assert output.is_file(), manager.list()[0]["lastOutcome"]
    assert output.read_bytes()[:4] == b"RIFF"
    assert source.read_bytes() == original
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_folder_watch_applies_saved_output_name_template_without_overwriting(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, pipelines, manager, pipeline = setup(tmp_path)
    named = pipelines.update(pipeline["id"], MediaPipelineCreate.model_validate({
        "name": pipeline["name"], "media": pipeline["media"], "operations": pipeline["operations"],
        "outputNameTemplate": "{name}-web.{ext}",
    }))
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], named["id"])
    source = folder / "new.png"
    image(source, (90, 80, 70))
    original = source.read_bytes()
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])
    output = folder / "new-web.png"
    assert output.is_file()
    assert (folder / "new.png").read_bytes() == original
    assert manager.list()[0]["lastOutcome"]["outputName"] == output.name
    for _ in range(3):
        manager._poll(manager.watches[watch["id"]])
    assert manager.list()[0]["processedCount"] == 1
    assert not (folder / "new-web-web.png").exists()
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_watch_output_sequence_continues_across_files_and_retries_capacity(tmp_path, monkeypatch):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, pipelines, manager, pipeline = setup(tmp_path)
    named = pipelines.update(pipeline["id"], MediaPipelineCreate.model_validate({
        "name": pipeline["name"], "media": pipeline["media"], "operations": pipeline["operations"],
        "outputNameTemplate": "%f-%i.{ext}",
    }))
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch_id = manager.add(selection["id"], named["id"])["id"]
    watch = manager.watches[watch_id]
    originals = {}
    real_submit = jobs.submit
    calls = []

    def submit(request, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise MediaJobCapacityError("full")
        return real_submit(request, **kwargs)

    monkeypatch.setattr(jobs, "submit", submit)
    for index, name in enumerate(("first", "second"), 1):
        source = folder / f"{name}.png"
        image(source, (index * 20, 80, 70))
        originals[source] = source.read_bytes()
        for _ in range(5):
            manager._poll(watch)
        assert (folder / f"{name}-{index}.png").is_file()
    assert calls == [{"output_sequence_start": 1}, {"output_sequence_start": 1}, {"output_sequence_start": 2}]
    assert manager.list()[0]["processedCount"] == 2
    assert all(source.read_bytes() == original for source, original in originals.items())
    manager.close()
    jobs.close()
    selections.close()


def test_watch_keeps_native_folder_grant_pinned_until_removed(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, _pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    selections.selections[selection["id"]].expires = 0
    assert selections.get(selection["id"], write=True).pins == 1
    manager.remove(watch["id"])
    try:
        selections.get(selection["id"], write=True)
        assert False, "The revoked watcher grant should expire after unpinning"
    except FileNotFoundError:
        pass
    manager.close()
    jobs.close()
    selections.close()


def test_source_changed_during_pipeline_is_never_published(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, _pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    source = folder / "new.png"
    image(source, (80, 40, 20))
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])
    replacement = folder / "replacement.png"
    image(replacement, (5, 10, 15))
    changed_bytes = replacement.read_bytes()
    os.replace(replacement, source)
    manager._poll(manager.watches[watch["id"]])
    assert source.read_bytes() == changed_bytes
    assert not (folder / "new_prepared.png").exists()
    assert "source changed" in manager.list()[0]["lastOutcome"]["message"]
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_source_changed_after_copy_before_publish_is_never_published(tmp_path, monkeypatch):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, _pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    watch = manager.add(selection["id"], pipeline["id"])
    source = folder / "new.png"
    image(source, (80, 40, 20))
    manager._poll(manager.watches[watch["id"]])
    manager._poll(manager.watches[watch["id"]])

    real_stat = os.stat
    source_stat_count = 0

    def change_source_before_recheck(path, *args, **kwargs):
        nonlocal source_stat_count
        if os.fspath(path) == os.fspath(source):
            source_stat_count += 1
            if source_stat_count == 2:
                replacement = folder / "replacement.png"
                image(replacement, (5, 10, 15))
                os.replace(replacement, source)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(folder_automation.os, "stat", change_source_before_recheck)
    manager._poll(manager.watches[watch["id"]])
    assert not (folder / "new_prepared.png").exists()
    assert "could not be saved safely" in manager.list()[0]["lastOutcome"]["message"]
    manager.remove(watch["id"])
    manager.close()
    jobs.close()
    selections.close()


def test_folder_watch_api_requires_native_grant_and_supports_pause_resume_remove(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    selections, jobs, pipelines, manager, pipeline = setup(tmp_path)
    selection = selections.register_native([str(folder)], access="read-write", credential="native")
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines, folder_store=manager))
    client = TestClient(app)
    payload = {"selectionId": selection["id"], "pipelineId": pipeline["id"]}
    assert client.post("/api/media-folder-watches", json=payload).status_code == 403
    created = client.post("/api/media-folder-watches", json=payload, headers={"X-OfficeKit-Native-Grant": "native"})
    assert created.status_code == 201
    watch = created.json()
    assert client.get("/api/media-folder-watches").json() == [watch]
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 409
    paused = client.patch(f"/api/media-folder-watches/{watch['id']}", json={"paused": True})
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    resumed = client.patch(f"/api/media-folder-watches/{watch['id']}", json={"paused": False})
    assert resumed.json()["state"] == "watching"
    assert client.delete(f"/api/media-folder-watches/{watch['id']}").status_code == 204
    assert client.get("/api/media-folder-watches").json() == []
    assert client.delete(f"/api/media-pipelines/{pipeline['id']}").status_code == 204
    manager.close()
    jobs.close()
    selections.close()
