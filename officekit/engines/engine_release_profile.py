"""Startup-owned release scope; this is readiness gating, not DRM."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

from starlette.responses import JSONResponse


def _valid_route_pattern(path: str) -> bool:
    """Allow exact API paths or `*` for exactly one non-empty path segment."""
    if not isinstance(path, str):
        return False
    parts = path.split("/")
    return (
        len(parts) >= 3
        and parts[0] == ""
        and parts[1] == "api"
        and all(part == "*" or bool(re.fullmatch(r"[a-z][a-z0-9-]*", part)) for part in parts[2:])
    )


def _route_matches(pattern: str, path: str) -> bool:
    """Match exact routes and single-segment resource placeholders."""
    if not _valid_route_pattern(pattern) or not isinstance(path, str):
        return False
    expected, actual = pattern.split("/"), path.split("/")
    if len(expected) != len(actual):
        return False
    return all(
        route_part == actual_part if route_part != "*"
        else bool(actual_part) and actual_part not in {".", ".."}
        for route_part, actual_part in zip(expected, actual, strict=True)
    )


@dataclass(frozen=True)
class ReleaseProfile:
    name: str
    tool_ids: tuple[str, ...] = ()
    routes: frozenset[tuple[str, str]] = frozenset()

    def allows(self, method: str, path: str) -> bool:
        return self.name == "development" or any(
            route_method == method and _route_matches(route_path, path)
            for route_method, route_path in self.routes
        )

    def payload(self) -> dict:
        return {"profile": self.name, "tool_ids": list(self.tool_ids)}


def load_release_profile(environment=None, document=None) -> ReleaseProfile:
    name = (os.environ if environment is None else environment).get("OFFICEKIT_RELEASE_PROFILE", "development")
    if name not in ("development", "private-beta"):
        raise ValueError("OFFICEKIT_RELEASE_PROFILE must be development or private-beta")
    if name == "development":
        return ReleaseProfile(name)
    if document is None:
        profile_path = Path(__file__).resolve().parents[2] / "release-profile.json"
        document = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"tool_ids", "routes"}:
        raise ValueError("Invalid OfficeKit release manifest")
    ids, routes = document["tool_ids"], document["routes"]
    if (
        not isinstance(ids, list) or not ids
        or any(not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) for value in ids)
        or len(set(ids)) != len(ids)
        or not isinstance(routes, list) or not routes
        or any(
            not isinstance(route, list) or len(route) != 2
            or route[0] not in ("GET", "POST", "DELETE")
            or not _valid_route_pattern(route[1])
            for route in routes
        )
    ):
        raise ValueError("Invalid OfficeKit release manifest")
    pairs = frozenset(tuple(route) for route in routes)
    if len(pairs) != len(routes):
        raise ValueError("Duplicate OfficeKit release routes")
    return ReleaseProfile(name, tuple(ids), pairs)


class ReleaseScopeMiddleware:
    def __init__(self, app, profile):
        self.app, self.profile = app, profile

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http" and scope["path"].startswith("/api/")
            and not self.profile().allows(scope["method"], scope["path"])
        ):
            response = JSONResponse(status_code=404, content={
                "detail": "This operation is not available in the OfficeKit private beta.",
            })
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
