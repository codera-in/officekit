"""Agent settings written by the desktop app's Settings screen and read by `officekit-mcp`.

Precedence for each value: environment variable, then the settings file, then the built-in default.
An unreadable or invalid file is ignored so the defaults (the most restrictive choice) apply.
"""

import json
import os
from pathlib import Path

from officekit.mcp.paths import ALLOWED_DIRS_ENV, OUTPUT_DIR_ENV
from officekit.mcp.registry import GROUPS

SETTINGS_PATH_ENV = "OFFICEKIT_AGENT_SETTINGS"
TOOLS_ENV = "OFFICEKIT_MCP_TOOLS"
NO_TOOLS = "none"  # explicit "every group off"; an empty value means the default (all groups)
SETTINGS_VERSION = 1
MAX_ALLOWED_DIRS = 20
MAX_PATH_CHARS = 1024


def settings_path(environment=None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(SETTINGS_PATH_ENV) or Path.home() / ".officekit" / "agent-settings.json").expanduser()


def validate_settings(document) -> dict:
    """Return a normalised settings dict or raise ValueError; used by the app before saving."""
    if not isinstance(document, dict) or document.get("version") != SETTINGS_VERSION:
        raise ValueError("Unsupported agent settings version.")
    unknown = set(document) - {"version", "tools", "allowed_dirs", "output_dir"}
    if unknown:
        raise ValueError(f"Unknown agent setting: {sorted(unknown)[0]}")
    result = {"version": SETTINGS_VERSION}
    if "tools" in document:
        tools = document["tools"]
        if not isinstance(tools, list) or any(name not in GROUPS for name in tools) or len(set(tools)) != len(tools):
            raise ValueError("tools must be a list of known, unique tool groups.")
        result["tools"] = tools
    if "allowed_dirs" in document:
        directories = document["allowed_dirs"]
        if not isinstance(directories, list) or not 1 <= len(directories) <= MAX_ALLOWED_DIRS:
            raise ValueError(f"allowed_dirs must list 1 to {MAX_ALLOWED_DIRS} folders.")
        result["allowed_dirs"] = [_folder(value) for value in directories]
    if "output_dir" in document:
        result["output_dir"] = _folder(document["output_dir"])
    return result


def _folder(value) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS or "\0" in value or os.pathsep in value:
        raise ValueError("Folders must be non-empty paths.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Folders must be absolute paths.")
    if path == Path(path.anchor):
        raise ValueError("A whole drive cannot be shared with agents.")
    return str(path)


def load_settings(environment=None) -> dict:
    try:
        return validate_settings(json.loads(settings_path(environment).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def effective_environment(environment=None) -> dict:
    """Environment overlaid with saved settings, for `OfficeKitMcpServer`."""
    env = dict(os.environ if environment is None else environment)
    saved = load_settings(env)
    if "tools" in saved and not env.get(TOOLS_ENV):
        env[TOOLS_ENV] = ",".join(saved["tools"]) or NO_TOOLS
    if "allowed_dirs" in saved and not env.get(ALLOWED_DIRS_ENV):
        env[ALLOWED_DIRS_ENV] = os.pathsep.join(saved["allowed_dirs"])
    if "output_dir" in saved and not env.get(OUTPUT_DIR_ENV):
        env[OUTPUT_DIR_ENV] = saved["output_dir"]
    return env
