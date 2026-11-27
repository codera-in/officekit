"""
Tests for the global clipboard additions: any-match dedupe, retention by age and count, type
filter, source bundle id, persisted capture settings, snippet keyword rules and the settings API.
"""

import os
import sqlite3
import tempfile
import time

import pytest

from officekit.engines.engine_clipboard import (
    DEFAULT_SKIP_BUNDLE_IDS,
    ClipboardStore,
    TriggerError,
)


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name
    try:
        yield ClipboardStore(db_path=db_path, max_clips=50)
    finally:
        os.remove(db_path)


def test_identical_text_anywhere_in_history_moves_to_the_top_instead_of_duplicating(store):
    first = store.add_clip("alpha")
    store.add_clip("beta")
    store.add_clip("gamma")
    again = store.add_clip("alpha", source_app="Notes", source_bundle_id="com.apple.Notes")
    assert again["id"] == first["id"]
    assert again["source_bundle_id"] == "com.apple.Notes"
    clips = store.list_clips()["clips"]
    assert [clip["text_content"] for clip in clips] == ["alpha", "gamma", "beta"]
    assert store.list_clips()["total"] == 3


def test_identical_pinned_text_is_bumped_and_stays_pinned(store):
    pinned = store.add_clip("keep me")
    store.toggle_pin(pinned["id"], True)
    store.add_clip("other")
    bumped = store.add_clip("keep me")
    assert bumped["id"] == pinned["id"] and bumped["pinned"] == 1


def test_images_are_never_merged_by_text(store):
    one = store.add_clip("", image_data="aW1hZ2Ux", content_type="image")
    two = store.add_clip("", image_data="aW1hZ2Uy", content_type="image")
    assert one["id"] != two["id"]


def test_using_a_clip_moves_it_to_the_top_but_pinned_clips_stay_above(store):
    old = store.add_clip("used again")
    store.add_clip("middle")
    newest = store.add_clip("newest")
    pinned = store.add_clip("pinned one")
    store.toggle_pin(pinned["id"], True)
    assert [c["id"] for c in store.list_clips()["clips"]][:2] == [pinned["id"], newest["id"]]

    time.sleep(0.01)
    used = store.touch_clip(old["id"])
    assert used["id"] == old["id"] and used["last_used_at"] > old["last_used_at"]
    ids = [c["id"] for c in store.list_clips()["clips"]]
    assert ids[0] == pinned["id"], "pinned clips stay in their own group at the top"
    assert ids[1] == old["id"], "the clip just used leads the unpinned history"
    assert ids[2] == newest["id"]


def test_using_an_image_clip_moves_it_to_the_top_and_an_unknown_clip_is_none(store):
    image = store.add_clip("", image_data="iVBORw0KGgo=")
    store.add_clip("later text")
    time.sleep(0.01)
    assert store.touch_clip(image["id"])["id"] == image["id"]
    assert store.list_clips()["clips"][0]["id"] == image["id"]
    assert store.touch_clip("does-not-exist") is None


def test_skip_listed_source_apps_are_never_stored(store):
    assert store.add_clip("hunter2", source_bundle_id="com.1password.1password") is None
    assert store.add_clip("notes text", source_bundle_id="com.apple.Notes") is not None
    store.update_settings({"skip_bundle_ids": ["com.example.Secret"]})
    assert store.add_clip("now allowed", source_bundle_id="com.1password.1password") is not None
    assert store.add_clip("blocked", source_bundle_id="com.example.Secret") is None


def test_apple_passwords_is_skipped_by_default_and_bundle_ids_match_ignoring_case(store):
    assert "com.apple.Passwords" in store.get_settings()["skip_bundle_ids"]
    assert store.add_clip("a password", source_bundle_id="com.apple.Passwords") is None
    assert store.add_clip("a password", source_bundle_id="COM.APPLE.PASSWORDS") is None
    assert store.add_clip("other text", source_bundle_id="com.apple.Notes") is not None


def test_retention_prunes_unpinned_clips_by_age_but_keeps_pinned(store):
    old = store.add_clip("old clip")
    keeper = store.add_clip("old but pinned")
    store.toggle_pin(keeper["id"], True)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE clips SET created_at = ?", (time.time() - 40 * 86400,))
    store.update_settings({"retention_days": 30})
    store.add_clip("fresh clip")
    texts = {clip["text_content"] for clip in store.list_clips()["clips"]}
    assert texts == {"old but pinned", "fresh clip"}
    assert store.get_clip(old["id"]) is None


def test_lowering_retention_prunes_immediately_and_on_start_without_any_new_copy(store):
    old = store.add_clip("old clip")
    store.update_settings({"capture_enabled": False})
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE clips SET created_at = ?", (time.time() - 3 * 86400,))
    store.update_settings({"retention_days": 1})
    assert store.get_clip(old["id"]) is None
    survivor = store.add_clip("kept")
    assert survivor is None or store.get_clip(survivor["id"]) is not None
    store.update_settings({"capture_enabled": True, "retention_days": 30})
    fresh = store.add_clip("restart me")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE clips SET created_at = ?", (time.time() - 40 * 86400,))
    reopened = ClipboardStore(db_path=store.db_path, max_clips=50)
    assert reopened.get_clip(fresh["id"]) is None


def test_retention_prunes_by_count_using_the_stored_setting(store):
    store.update_settings({"retention_clips": 50})
    for index in range(55):
        store.add_clip(f"clip {index}")
    assert store.list_clips(limit=200)["total"] == 50


def test_type_filter_maps_chips_to_content_types(store):
    store.add_clip("plain words")
    store.add_clip("https://example.com/a")
    store.add_clip("", image_data="aW1n", content_type="image")
    store.add_clip('{"a": 1}')
    by_type = lambda *names: {c["content_type"] for c in store.list_clips(types=list(names))["clips"]}
    assert by_type("text") == {"text", "json"}
    assert by_type("link") == {"link"}
    assert by_type("image") == {"image"}
    assert by_type("link", "image") == {"link", "image"}
    assert store.list_clips(types=["nonsense"])["clips"] == []


def test_list_without_image_data_marks_image_clips_and_keeps_text_clips_intact(store):
    store.add_clip("plain words")
    store.add_clip("", image_data="aW1hZ2U=", content_type="image")
    light = {c["content_type"]: c for c in store.list_clips(include_image_data=False)["clips"]}
    assert light["image"]["image_data"] is None and light["image"]["has_image"] == 1
    assert light["text"]["has_image"] == 0 and light["text"]["text_content"] == "plain words"
    full = {c["content_type"]: c for c in store.list_clips()["clips"]}
    assert full["image"]["image_data"] == "aW1hZ2U="


def test_settings_defaults_roundtrip_and_validation(store):
    defaults = store.get_settings()
    assert defaults["capture_enabled"] is True and defaults["expansion_enabled"] is True
    assert defaults["skip_bundle_ids"] == list(DEFAULT_SKIP_BUNDLE_IDS)
    assert defaults["retention_clips"] == 50 and defaults["retention_days"] == 30
    updated = store.update_settings({"capture_enabled": False, "retention_days": 7})
    assert updated["capture_enabled"] is False and updated["retention_days"] == 7
    assert store.get_settings()["retention_days"] == 7
    for bad in (
        {"unknown": 1},
        {"capture_enabled": "yes"},
        {"expansion_enabled": 1},
        {"retention_clips": 10},
        {"retention_clips": True},
        {"retention_days": 0},
        {"retention_days": 400},
        {"skip_bundle_ids": "com.a"},
        {"skip_bundle_ids": ["bad id with spaces"]},
        {"skip_bundle_ids": [f"com.x{n}" for n in range(65)]},
    ):
        with pytest.raises(ValueError):
            store.update_settings(bad)
    assert store.get_settings()["retention_days"] == 7


def test_corrupt_stored_setting_falls_back_to_the_default(store):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('retention_days', 'not json')")
        conn.execute("INSERT INTO settings (key, value) VALUES ('mystery', '1')")
    assert store.get_settings()["retention_days"] == 30


def test_existing_database_without_new_columns_is_migrated():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name
    try:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE clips (
                    id TEXT PRIMARY KEY, content_type TEXT NOT NULL, text_content TEXT NOT NULL,
                    rich_content TEXT, image_data TEXT, category TEXT NOT NULL DEFAULT 'general',
                    pinned INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, last_used_at REAL NOT NULL,
                    char_count INTEGER NOT NULL DEFAULT 0, word_count INTEGER NOT NULL DEFAULT 0,
                    byte_size INTEGER NOT NULL DEFAULT 0, source_app TEXT
                );
                INSERT INTO clips VALUES ('legacy', 'text', 'old', NULL, NULL, 'general', 0, 4102444800, 4102444800, 3, 1, 3, NULL);
                """
            )
        migrated = ClipboardStore(db_path=db_path)
        assert migrated.get_clip("legacy")["source_bundle_id"] is None
        assert migrated.add_clip("new", source_bundle_id="com.apple.Notes")["source_bundle_id"] == "com.apple.Notes"
        ClipboardStore(db_path=db_path)  # re-opening an already migrated database is a no-op
    finally:
        os.remove(db_path)


@pytest.mark.parametrize(
    "trigger, code",
    [("a", "length"), ("x" * 33, "length"), ("has space", "whitespace"), ("tab\there", "whitespace")],
)
def test_snippet_keyword_shape_is_enforced(store, trigger, code):
    with pytest.raises(TriggerError) as raised:
        store.save_snippet("T", "body", trigger_key=trigger)
    assert raised.value.code == code


def test_snippet_keywords_must_be_unique_and_prefix_free(store):
    store.save_snippet("Signature", "Best,\nA", trigger_key=";sig")
    with pytest.raises(TriggerError) as duplicate:
        store.save_snippet("Other", "x", trigger_key=";sig")
    assert duplicate.value.code == "duplicate"
    with pytest.raises(TriggerError) as longer:
        store.save_snippet("Other", "x", trigger_key=";sig2")
    assert longer.value.code == "prefix"
    with pytest.raises(TriggerError) as shorter:
        store.save_snippet("Other", "x", trigger_key=";s")
    assert shorter.value.code == "prefix"
    assert store.save_snippet("Meeting", "link", trigger_key=";meet")["trigger_key"] == ";meet"


def test_editing_a_snippet_keeps_its_own_keyword_and_blank_keyword_clears_it(store):
    first = store.save_snippet("Signature", "v1", trigger_key=";sig")
    edited = store.save_snippet("Signature", "v2", trigger_key=";sig", snippet_id=first["id"])
    assert edited["content"] == "v2" and edited["trigger_key"] == ";sig"
    cleared = store.save_snippet("Signature", "v2", trigger_key="  ", snippet_id=first["id"])
    assert cleared["trigger_key"] is None
    assert store.save_snippet("Reuse", "x", trigger_key=";sig")["trigger_key"] == ";sig"


def test_legacy_keyword_that_breaks_the_rules_stays_editable(store):
    legacy = store.save_snippet("Legacy", "v1")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE snippets SET trigger_key = 'x' WHERE id = ?", (legacy["id"],))
    edited = store.save_snippet("Legacy", "v2", trigger_key="x", snippet_id=legacy["id"])
    assert edited["content"] == "v2" and edited["trigger_key"] == "x"


@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module

    monkeypatch.setattr(app_module, "clipboard_store", store)
    return TestClient(app_module.app)


def test_api_clip_bundle_id_type_filter_and_skip_list(client):
    saved = client.post(
        "/api/clipboard/clips",
        json={"text_content": "https://example.com", "source_app": "Safari", "source_bundle_id": "com.apple.Safari"},
    )
    assert saved.status_code == 200 and saved.json()["clip"]["source_bundle_id"] == "com.apple.Safari"
    ignored = client.post(
        "/api/clipboard/clips", json={"text_content": "secret", "source_bundle_id": "com.1password.1password"}
    )
    assert ignored.json()["status"] == "ignored"
    client.post("/api/clipboard/clips", json={"text_content": "plain words"})
    links = client.get("/api/clipboard/history", params={"types": "link"}).json()["clips"]
    assert [clip["content_type"] for clip in links] == ["link"]
    both = client.get("/api/clipboard/history", params={"types": "link, text"}).json()["clips"]
    assert len(both) == 2
    assert client.get("/api/clipboard/history", params={"types": "x" * 65}).status_code == 422
    too_long = client.post("/api/clipboard/clips", json={"text_content": "x", "source_bundle_id": "c" * 256})
    assert too_long.status_code == 422
    too_big = client.post("/api/clipboard/clips", json={"text_content": "", "image_data": "A" * 6_000_001})
    assert too_big.status_code == 422


def test_api_get_clip_and_light_history(client):
    image = client.post(
        "/api/clipboard/clips", json={"text_content": "", "image_data": "aW1n", "content_type": "image"}
    ).json()["clip"]
    fetched = client.get(f"/api/clipboard/clips/{image['id']}")
    assert fetched.status_code == 200 and fetched.json()["clip"]["image_data"] == "aW1n"
    assert client.get("/api/clipboard/clips/missing").status_code == 404
    light = client.get("/api/clipboard/history", params={"include_images": "false"}).json()["clips"]
    assert light[0]["image_data"] is None and light[0]["has_image"] == 1


def test_api_global_settings_are_strict_and_bounded(client):
    current = client.get("/api/clipboard/global-settings").json()["settings"]
    assert current["capture_enabled"] is True
    updated = client.post(
        "/api/clipboard/global-settings",
        json={"capture_enabled": False, "retention_days": 14, "skip_bundle_ids": ["com.example.Vault"]},
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["retention_days"] == 14
    assert client.get("/api/clipboard/global-settings").json()["settings"]["capture_enabled"] is False
    for bad in ({"surprise": 1}, {"retention_days": 0}, {"retention_clips": 9}, {"skip_bundle_ids": ["bad id"]}):
        assert client.post("/api/clipboard/global-settings", json=bad).status_code == 422
    assert client.post("/api/clipboard/global-settings", json={}).status_code == 200
    assert client.put("/api/clipboard/global-settings", json={}).status_code == 405


def test_api_snippet_keyword_rules_map_to_status_codes(client):
    ok = client.post("/api/clipboard/snippets", json={"title": "Sig", "content": "x", "trigger_key": ";sig"})
    assert ok.status_code == 200
    assert client.post("/api/clipboard/snippets", json={"title": "B", "content": "x", "trigger_key": ";sig"}).status_code == 409
    assert client.post("/api/clipboard/snippets", json={"title": "B", "content": "x", "trigger_key": ";sig2"}).status_code == 409
    assert client.post("/api/clipboard/snippets", json={"title": "B", "content": "x", "trigger_key": "a"}).status_code == 422
    assert client.post("/api/clipboard/snippets", json={"title": "B", "content": "x", "trigger_key": "a b"}).status_code == 422


def test_capture_pause_defaults_off_and_panel_opens_on_text(store):
    defaults = store.get_settings()
    assert defaults["capture_pause"] == "off"
    assert defaults["capture_paused_until"] is None
    assert defaults["capture_paused"] is False
    assert defaults["panel_default_filter"] == "text"


def test_timed_pause_derives_its_end_on_the_server_and_ends_by_itself(store, monkeypatch):
    import officekit.engines.engine_clipboard as engine

    clock = {"now": 1_000.0}
    monkeypatch.setattr(engine.time, "time", lambda: clock["now"])
    paused = store.update_settings({"capture_pause": "15m"})
    assert paused["capture_paused"] is True
    assert paused["capture_paused_until"] == 1_000.0 + 15 * 60
    clock["now"] += 14 * 60
    assert store.get_settings()["capture_paused"] is True
    clock["now"] += 2 * 60
    resumed = store.get_settings()
    assert resumed["capture_paused"] is False
    assert resumed["capture_pause"] == "off" and resumed["capture_paused_until"] is None


def test_until_resume_pauses_indefinitely_and_off_resumes(store):
    assert store.update_settings({"capture_pause": "until_resume"})["capture_paused"] is True
    assert store.update_settings({"capture_pause": "1h"})["capture_paused_until"] > time.time() + 3000
    resumed = store.update_settings({"capture_pause": "off"})
    assert resumed["capture_paused"] is False and resumed["capture_paused_until"] is None


def test_pausing_never_deletes_existing_history(store):
    store.add_clip("kept before the pause", source_app="Notes")
    store.update_settings({"capture_pause": "until_resume"})
    assert [clip["text_content"] for clip in store.list_clips(limit=10)["clips"]] == ["kept before the pause"]


def test_clients_cannot_set_the_pause_end_time_or_unknown_choices(store):
    for bad in (
        {"capture_paused_until": 5.0},
        {"capture_pause": "forever"},
        {"capture_pause": True},
        {"panel_default_filter": "videos"},
        {"panel_default_filter": 1},
    ):
        with pytest.raises(ValueError):
            store.update_settings(bad)
    assert store.get_settings()["capture_pause"] == "off"


def test_panel_filter_accepts_each_choice_and_persists(store):
    for choice in ("all", "text", "images", "links", "pinned"):
        assert store.update_settings({"panel_default_filter": choice})["panel_default_filter"] == choice


def test_api_pause_and_panel_filter_are_strict(client):
    paused = client.post("/api/clipboard/global-settings", json={"capture_pause": "1h"})
    assert paused.status_code == 200
    assert paused.json()["settings"]["capture_paused"] is True
    assert client.post("/api/clipboard/global-settings", json={"capture_pause": "off"}).json()["settings"]["capture_paused"] is False
    assert client.post("/api/clipboard/global-settings", json={"capture_pause": "2h"}).status_code == 422
    assert client.post("/api/clipboard/global-settings", json={"panel_default_filter": "videos"}).status_code == 422
    assert client.post("/api/clipboard/global-settings", json={"capture_paused_until": 1}).status_code == 422
    assert client.post("/api/clipboard/global-settings", json={"panel_default_filter": "links"}).json()["settings"]["panel_default_filter"] == "links"
    client.post("/api/clipboard/global-settings", json={"panel_default_filter": "text"})
