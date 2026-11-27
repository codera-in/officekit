import json
import os

import pytest

from officekit.mcp.server import OfficeKitMcpServer, enabled_groups
from officekit.mcp.settings import effective_environment, load_settings, settings_path, validate_settings


def write_settings(tmp_path, document):
    path = tmp_path / "agent-settings.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return {"OFFICEKIT_AGENT_SETTINGS": str(path)}


def test_saved_settings_become_the_effective_environment(tmp_path):
    env = write_settings(tmp_path, {
        "version": 1, "tools": ["pdf", "calc"],
        "allowed_dirs": [str(tmp_path / "a"), str(tmp_path / "b")], "output_dir": str(tmp_path / "out"),
    })
    effective = effective_environment(env)
    assert effective["OFFICEKIT_MCP_TOOLS"] == "pdf,calc"
    assert effective["OFFICEKIT_MCP_ALLOWED_DIRS"] == os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
    assert effective["OFFICEKIT_MCP_OUTPUT_DIR"] == str(tmp_path / "out")
    assert enabled_groups(effective) == ["pdf", "calc"]


def test_environment_overrides_saved_settings(tmp_path):
    env = write_settings(tmp_path, {"version": 1, "tools": ["pdf"]})
    assert effective_environment({**env, "OFFICEKIT_MCP_TOOLS": "calc"})["OFFICEKIT_MCP_TOOLS"] == "calc"


def test_every_group_off_offers_no_tools_but_help(tmp_path):
    effective = effective_environment(write_settings(tmp_path, {"version": 1, "tools": []}))
    assert enabled_groups(effective) == []
    server = OfficeKitMcpServer(effective)
    assert server.groups == []


@pytest.mark.parametrize("document", [
    {"version": 2},
    {"version": 1, "tools": ["pdf", "pdf"]},
    {"version": 1, "tools": ["clipboard"]},
    {"version": 1, "allowed_dirs": []},
    {"version": 1, "allowed_dirs": ["relative/path"]},
    {"version": 1, "allowed_dirs": ["/"]},
    {"version": 1, "output_dir": ""},
    {"version": 1, "surprise": True},
    ["not", "an", "object"],
])
def test_invalid_settings_are_rejected(document):
    with pytest.raises(ValueError):
        validate_settings(document)


def test_invalid_or_missing_file_falls_back_to_defaults(tmp_path):
    assert load_settings({"OFFICEKIT_AGENT_SETTINGS": str(tmp_path / "missing.json")}) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert effective_environment({"OFFICEKIT_AGENT_SETTINGS": str(bad)}).get("OFFICEKIT_MCP_TOOLS") is None
    assert write_settings(tmp_path, {"version": 1, "allowed_dirs": ["/"]}) and load_settings(
        {"OFFICEKIT_AGENT_SETTINGS": str(tmp_path / "agent-settings.json")}) == {}


def test_default_settings_path_is_in_the_user_home():
    assert settings_path({}).name == "agent-settings.json" and settings_path({}).parent.name == ".officekit"
