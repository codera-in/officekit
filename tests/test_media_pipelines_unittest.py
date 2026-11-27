import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_naming import render_output_name
from officekit.engines.engine_media_pipelines import MediaPipelineCreate, MediaPipelineRename, MediaPipelineStore, MediaPipelineStoreError
from officekit.media_routes import create_media_router


def image_pipeline(name="Web images"):
    return {
        "name": name,
        "media": "image",
        "operations": [
            {"operationId": "image-resize", "options": {"maxWidth": 1600, "maxHeight": 1200}},
            {"operationId": "image-strip-metadata", "options": {}},
        ],
    }


def test_pipeline_definitions_are_allowlisted_bounded_and_media_specific():
    parsed = MediaPipelineCreate.model_validate(image_pipeline())
    assert parsed.name == "Web images"
    with pytest.raises(ValueError):
        MediaPipelineCreate.model_validate({**image_pipeline(), "operations": [{"operationId": "run-script", "options": {}}]})
    with pytest.raises(ValueError, match="selected media type"):
        MediaPipelineCreate.model_validate({**image_pipeline(), "operations": [{"operationId": "pdf-crop", "options": {"pageSize": "a4"}}]})
    with pytest.raises(ValueError, match="final"):
        MediaPipelineCreate.model_validate({
            "name": "PDF export", "media": "pdf",
            "operations": [
                {"operationId": "pdf-pages-to-images", "options": {}},
                {"operationId": "pdf-uncrop", "options": {}},
            ],
        })
    with pytest.raises(ValueError):
        MediaPipelineCreate.model_validate({**image_pipeline(), "name": "  "})
    with pytest.raises(ValueError):
        MediaPipelineCreate.model_validate({**image_pipeline(), "extra": "path/to/file"})
    named = MediaPipelineCreate.model_validate({**image_pipeline(), "outputNameTemplate": "{name}-web.{ext}"})
    assert named.output_name_template == "{name}-web.{ext}"
    clop_named = MediaPipelineCreate.model_validate({**image_pipeline(), "outputNameTemplate": "%f-%y%m%d-%i.{ext}"})
    assert clop_named.output_name_template == "%f-%y%m%d-%i.{ext}"
    for template in ("../{name}.{ext}", "{name}.{ext}/{media}", "{name}.{ext}.backup", "{stem}.{ext}", "{name}.{ext}.{ext}", "{name}-%P.{ext}", "%i.{ext}", "%f-%f.{ext}", "{name}\n.{ext}", "{name}" * 20 + ".{ext}"):
        with pytest.raises(ValueError):
            MediaPipelineCreate.model_validate({**image_pipeline(), "outputNameTemplate": template})


def test_output_name_template_does_not_reinterpret_source_braces_or_percent_tokens():
    assert render_output_name("%f-%e-%i.{ext}", "photo{private}%y.png", "webp", "image", 2) == "photo{private}%y-png-2.webp"
    assert render_output_name("{name}-%i.{ext}", "photo{private}%y.png", "webp", "image", 2) == "photo{private}%y-2.webp"


def test_regex_capture_name_tokens_require_explicit_inline_context_and_keep_captures_literal():
    from officekit.engines.engine_media_naming import validate_output_name_template

    template = "$1-%i.{ext}"
    assert validate_output_name_template(template, allow_captures=True) == template
    assert render_output_name(template, "source.png", "webp", "image", 2,
                              captures=("{name}%y$2",)) == "{name}%y$2-2.webp"
    with pytest.raises(ValueError, match="capture"):
        MediaPipelineCreate.model_validate({**image_pipeline(), "outputNameTemplate": "%f-$1.{ext}"})
    with pytest.raises(ValueError, match="capture"):
        render_output_name(template, "source.png", "webp", "image")


@pytest.mark.parametrize("token", ["$0", "$01", "$100"])
def test_output_capture_tokens_reject_ambiguous_or_unbounded_indices(token):
    from officekit.engines.engine_media_naming import validate_output_name_template

    with pytest.raises(ValueError, match="capture"):
        validate_output_name_template(token + ".{ext}", allow_captures=True)


@pytest.mark.parametrize("captures", [("x" * 256,), tuple("x" for _ in range(100)), (123,), ("bad\nname",), ("../escape",)])
def test_output_capture_values_cannot_escape_filename_or_resource_bounds(captures):
    with pytest.raises(ValueError):
        render_output_name("$1.{ext}", "source.png", "webp", "image", captures=captures)


def test_optional_unmatched_capture_is_empty_without_reinterpreting_adjacent_capture():
    assert render_output_name("$1$2.{ext}", "source.png", "webp", "image", captures=(None, "$1")) == "$1.webp"


@pytest.mark.parametrize("template", ["{name.{ext}", "{name}.{ext}", "%f.{ext}"])
def test_output_name_rejects_invalid_template_or_unpublishable_result(template):
    if template == "{name.{ext}":
        with pytest.raises(ValueError):
            MediaPipelineCreate.model_validate({**image_pipeline(), "outputNameTemplate": template})
    else:
        with pytest.raises(ValueError, match="unsafe filename"):
            render_output_name(template, "long" * 70 + ".png", "webp", "image")
        with pytest.raises(ValueError, match="invalid file format"):
            render_output_name(template, "photo.png", "---", "image")


def test_output_name_template_renders_bounded_clop_filename_tokens():
    rendered = render_output_name("%f-%e-%i-%r-%y%m%d.{ext}", "/private/photos/trip.png", "webp", "image", sequence=7)
    assert rendered.startswith("trip-png-7-")
    assert len(rendered.split("-")[3]) == 6
    assert rendered.endswith(".webp")
    assert "/" not in rendered


def test_saved_pipeline_persists_runtime_smart_crop_without_file_geometry(tmp_path):
    path = tmp_path / "pipelines.json"
    definition = MediaPipelineCreate.model_validate({
        "name": "Subject crop", "media": "image", "operations": [
            {"operationId": "image-crop", "options": {"aspectRatio": "1.5:1", "smartCrop": True}},
        ],
    })
    saved = MediaPipelineStore(str(path)).create(definition)
    restored = MediaPipelineStore(str(path)).list()[0]
    assert saved == restored and restored["state"] == "paused"
    assert restored["operations"] == [{"operationId": "image-crop", "options": {"aspect_ratio": "3:2", "smart_crop": True}}]
    assert str(tmp_path) not in path.read_text()


def test_pipeline_store_persists_private_paused_recipes_without_media_or_paths(tmp_path):
    path = tmp_path / "OfficeKit" / "media-pipelines.json"
    store = MediaPipelineStore(str(path))
    created = store.create(MediaPipelineCreate.model_validate(image_pipeline()))
    assert created["state"] == "paused"
    assert len(created["operations"]) == 2
    assert created["outputNameTemplate"] is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    serialized = path.read_text()
    assert "original" not in serialized
    assert "/" not in json.dumps(created["operations"])
    reopened = MediaPipelineStore(str(path))
    assert reopened.list() == [created]
    assert reopened.delete(created["id"])
    assert reopened.list() == []


def test_pipeline_store_persists_safe_output_name_template_and_migrates_older_entries(tmp_path):
    path = tmp_path / "pipelines.json"
    path.write_text(json.dumps([{
        "id": "c04154e8-c8d9-4354-9134-c1566f334b12", "name": "Legacy", "media": "image",
        "operations": [{"operationId": "image-optimize", "options": {"quality": 82, "preserveMetadata": False}}],
        "state": "paused",
    }]))
    store = MediaPipelineStore(str(path))
    legacy = store.list()[0]
    assert legacy["outputNameTemplate"] is None
    created = store.create(MediaPipelineCreate.model_validate({
        **image_pipeline("Web output"), "outputNameTemplate": "{name}-web.{ext}",
    }))
    assert created["outputNameTemplate"] == "{name}-web.{ext}"
    assert MediaPipelineStore(str(path)).list() == [legacy, created]


def test_pipeline_store_works_when_fchmod_is_unavailable(tmp_path, monkeypatch):
    import officekit.engines.engine_media_pipelines as pipeline_module

    monkeypatch.delattr(pipeline_module.os, "fchmod")
    store = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    created = store.create(MediaPipelineCreate.model_validate(image_pipeline()))
    assert store.list() == [created]


def test_pipeline_store_rejects_duplicate_names_and_preserves_corrupt_file(tmp_path):
    path = tmp_path / "pipelines.json"
    store = MediaPipelineStore(str(path))
    store.create(MediaPipelineCreate.model_validate(image_pipeline("Studio")))
    with pytest.raises(ValueError, match="already exists"):
        store.create(MediaPipelineCreate.model_validate(image_pipeline("studio")))
    path.write_text('[{"unsafe":true}]')
    original = path.read_bytes()
    with pytest.raises(MediaPipelineStoreError):
        store.create(MediaPipelineCreate.model_validate(image_pipeline("New")))
    assert path.read_bytes() == original


def test_pipeline_store_renames_without_changing_recipe_or_bindings(tmp_path):
    store = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    first = store.create(MediaPipelineCreate.model_validate(image_pipeline("Studio")))
    second = store.create(MediaPipelineCreate.model_validate(image_pipeline("Archive")))

    renamed = store.rename(first["id"], MediaPipelineRename.model_validate({"name": "  Studio final  "}))
    assert renamed == {**first, "name": "Studio final"}
    assert store.list() == [renamed, second]
    with pytest.raises(ValueError, match="already exists"):
        store.rename(first["id"], MediaPipelineRename.model_validate({"name": "archive"}))
    assert store.list() == [renamed, second]
    with pytest.raises(FileNotFoundError):
        store.rename("not-a-uuid", MediaPipelineRename.model_validate({"name": "Missing"}))
    with pytest.raises(ValueError):
        MediaPipelineRename.model_validate({"name": "  "})


def test_pipeline_store_updates_steps_without_changing_id_or_paused_state(tmp_path):
    store = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    recipe = store.create(MediaPipelineCreate.model_validate(image_pipeline("Studio")))
    updated_definition = MediaPipelineCreate.model_validate({
        "name": "Studio resized",
        "media": "image",
        "operations": [{"operationId": "image-resize", "options": {"maxWidth": 800, "maxHeight": 600}}],
    })
    updated = store.update(recipe["id"], updated_definition)
    assert updated["id"] == recipe["id"]
    assert updated["state"] == "paused"
    assert updated["name"] == "Studio resized"
    assert updated["operations"] == updated_definition.model_dump(by_alias=True, mode="json")["operations"]
    assert store.list() == [updated]
    with pytest.raises(FileNotFoundError):
        store.update("not-a-uuid", updated_definition)


def test_pipeline_store_locks_reads_across_independent_instances(tmp_path, monkeypatch):
    path = str(tmp_path / "pipelines.json")
    first_store, second_store = MediaPipelineStore(path), MediaPipelineStore(path)
    first_inside_write = Event()
    release_first_write = Event()
    second_attempting = Event()
    second_read_started = Event()
    original_first_write = first_store._write
    original_second_read = second_store._read

    def paused_first_write(entries):
        first_inside_write.set()
        assert release_first_write.wait(timeout=5)
        original_first_write(entries)

    def tracked_second_read():
        second_read_started.set()
        return original_second_read()

    monkeypatch.setattr(first_store, "_write", paused_first_write)
    monkeypatch.setattr(second_store, "_read", tracked_second_read)
    first_definition = MediaPipelineCreate.model_validate(image_pipeline("First"))
    second_definition = MediaPipelineCreate.model_validate(image_pipeline("Second"))

    def create_second():
        second_attempting.set()
        return second_store.create(second_definition)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_store.create, first_definition)
        assert first_inside_write.wait(timeout=5)
        second = executor.submit(create_second)
        assert second_attempting.wait(timeout=5)
        assert not second_read_started.wait(timeout=0.1)
        release_first_write.set()
        created = [first.result(timeout=5), second.result(timeout=5)]
    assert {entry["name"] for entry in MediaPipelineStore(path).list()} == {"First", "Second"}
    assert len({entry["id"] for entry in created}) == 2


def test_pipeline_rename_size_overflow_preserves_store_and_maps_api_error(tmp_path, monkeypatch):
    import officekit.engines.engine_media_pipelines as pipeline_module

    path = tmp_path / "pipelines.json"
    store = MediaPipelineStore(str(path))
    recipe = store.create(MediaPipelineCreate.model_validate(image_pipeline("Before")))
    original = path.read_bytes()
    monkeypatch.setattr(pipeline_module, "MAX_PIPELINE_FILE_BYTES", len(original) + 1)
    with pytest.raises(OverflowError):
        store.rename(recipe["id"], MediaPipelineRename.model_validate({"name": "A much longer renamed pipeline"}))
    assert path.read_bytes() == original

    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=store))
    response = TestClient(app).patch(f"/api/media-pipelines/{recipe['id']}", json={"name": "A much longer renamed pipeline"})
    assert response.status_code == 413
    assert path.read_bytes() == original
    jobs.close()
    selections.close()


def test_pipeline_api_lists_creates_renames_and_deletes_recipes(tmp_path):
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, staging_root=str(tmp_path / "job-staging"))
    pipelines = MediaPipelineStore(str(tmp_path / "settings" / "pipelines.json"))
    app = FastAPI()
    app.include_router(create_media_router(jobs, pipeline_store=pipelines))
    client = TestClient(app)
    create = client.post("/api/media-pipelines", json=image_pipeline())
    assert create.status_code == 201
    recipe = create.json()
    assert recipe["state"] == "paused"
    assert client.get("/api/media-pipelines").json() == [recipe]
    other = client.post("/api/media-pipelines", json=image_pipeline("Archive")).json()
    renamed = client.patch(f"/api/media-pipelines/{recipe['id']}", json={"name": "Production"})
    assert renamed.status_code == 200
    assert renamed.json() == {**recipe, "name": "Production"}
    assert client.patch(f"/api/media-pipelines/{recipe['id']}", json={"name": "archive"}).status_code == 409
    assert client.patch(f"/api/media-pipelines/{recipe['id']}", json={"name": "   "}).status_code == 422
    assert client.patch(f"/api/media-pipelines/{'0' * 8}-0000-0000-0000-000000000000", json={"name": "Missing"}).status_code == 404
    changed = client.put(f"/api/media-pipelines/{recipe['id']}", json={
        "name": "Production",
        "media": "image",
        "operations": [{"operationId": "image-resize", "options": {"maxWidth": 800, "maxHeight": 600}}],
    })
    assert changed.status_code == 200
    assert changed.json()["id"] == recipe["id"]
    assert changed.json()["state"] == "paused"
    assert changed.json()["operations"][0]["operationId"] == "image-resize"
    assert client.put(f"/api/media-pipelines/{recipe['id']}", json={
        "name": "Production video", "media": "video",
        "operations": [{"operationId": "video-mute", "options": {}}],
    }).status_code == 409
    assert client.put(f"/api/media-pipelines/{'0' * 8}-0000-0000-0000-000000000000", json=image_pipeline()).status_code == 404
    assert client.put(f"/api/media-pipelines/{recipe['id']}", json={
        "name": "Production", "media": "image",
        "operations": [{"operationId": "run-script", "options": {}}],
    }).status_code == 422
    assert client.put(f"/api/media-pipelines/{recipe['id']}", json={
        "name": "archive", "media": "image", "operations": image_pipeline()["operations"],
    }).status_code == 409
    assert client.get("/api/media-pipelines").json() == [changed.json(), other]
    assert client.delete(f"/api/media-pipelines/{recipe['id']}").status_code == 204
    assert client.delete(f"/api/media-pipelines/{recipe['id']}").status_code == 404
    assert client.post("/api/media-pipelines", json={**image_pipeline(), "operations": [{"operationId": "execute", "options": {}}]}).status_code == 422
    jobs.close()
    selections.close()


def test_pipeline_delete_rejects_invalid_id_without_touching_store(tmp_path):
    pipelines = MediaPipelineStore(str(tmp_path / "pipelines.json"))
    assert pipelines.delete("not-a-uuid") is False
