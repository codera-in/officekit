"""Stdio MCP server exposing OfficeKit's shipped tools to local AI agents.

Requests are served by the FastAPI app in-process (no network port, so no API token
is needed). The app is imported lazily so `initialize` and `tools/list` stay instant.
"""

import asyncio
import json
import os
import re
import sys
from email.message import Message

from officekit.mcp.paths import PathPolicy, PathPolicyError
from officekit.mcp.registry import GROUPS, assert_no_sensitive_actions
from officekit.mcp.settings import effective_environment

SERVER_INFO = {"name": "officekit", "version": "1.0.0"}
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_INLINE_CHARS = 20_000
TOOLS_ENV = "OFFICEKIT_MCP_TOOLS"
PREFIX = "officekit_"

_FILE_PROPERTIES = {
    "file": {"type": "string", "description": "Absolute path of the input file."},
    "files": {"type": "array", "items": {"type": "string"}, "description": "Absolute input paths, in order."},
}


def enabled_groups(environment) -> list[str]:
    configured = environment.get(TOOLS_ENV, "")
    if configured.strip() == "none":
        return []
    names = [name.strip() for name in configured.split(",") if name.strip()]
    unknown = [name for name in names if name not in GROUPS]
    if unknown:
        raise ValueError(f"Unknown OfficeKit tool group: {', '.join(unknown)}")
    return names or list(GROUPS)


def tool_definitions(groups) -> list[dict]:
    tools = [{
        "name": f"{PREFIX}help",
        "description": "Parameters for one action. Call before using an unfamiliar action.",
        "inputSchema": {
            "type": "object",
            "properties": {"group": {"type": "string", "enum": list(groups)}, "action": {"type": "string"}},
            "required": ["group", "action"],
        },
    }]
    for name in groups:
        group = GROUPS[name]
        file_based = any(action.files for action in group["actions"].values())
        properties = {
            "action": {"type": "string", "enum": list(group["actions"])},
            "params": {"type": "object", "description": "Action parameters; see officekit_help."},
        }
        if file_based:
            properties.update(_FILE_PROPERTIES)
        tools.append({
            "name": f"{PREFIX}{name}",
            "description": group["description"],
            "inputSchema": {"type": "object", "properties": properties, "required": ["action"]},
        })
    return tools


def _load_app():
    """Import the FastAPI app for in-process use. There is no socket here, so no API token is needed."""
    os.environ.setdefault("OFFICEKIT_DEV_NOAUTH", "1")
    from app import app

    return app


class OfficeKitMcpServer:
    def __init__(self, environment, policy: PathPolicy | None = None, client=None):
        assert_no_sensitive_actions()
        self.groups = enabled_groups(environment)
        self.policy = policy or PathPolicy(environment)
        self._client = client

    async def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_load_app()), base_url="http://127.0.0.1", timeout=600,
            )
        return self._client

    # JSON-RPC -----------------------------------------------------------
    async def handle(self, message: dict) -> dict | None:
        method, request_id = message.get("method"), message.get("id")
        if request_id is None:
            return None  # notifications (initialized, cancelled) need no reply
        try:
            result = await self._dispatch(method, message.get("params") or {})
        except KeyError:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def _dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            return {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tool_definitions(self.groups)}
        if method == "tools/call":
            return await self.call_tool(params.get("name", ""), params.get("arguments") or {})
        raise KeyError(method)

    # Tools --------------------------------------------------------------
    async def call_tool(self, name: str, arguments: dict) -> dict:
        try:
            if name == f"{PREFIX}help":
                return _text(await self._help(arguments))
            group = name.removeprefix(PREFIX)
            if not name.startswith(PREFIX) or group not in self.groups:
                return _error(f"Unknown tool: {name}")
            return await self._run(group, arguments)
        except (PathPolicyError, ValueError, TypeError) as error:
            return _error(str(error))

    async def _help(self, arguments) -> str:
        action = self._action(arguments.get("group"), arguments.get("action"))
        if action.kind == "form":
            files = {"file": "file", "files": "files"}[action.files]
            return f"Uses {files}. {action.hint}"
        if action.kind == "none":
            return "No parameters."
        spec = _load_app().openapi()
        operation = spec["paths"][action.path][action.method.lower()]
        if action.kind == "query":
            return json.dumps({p["name"]: _summarize(p["schema"]) for p in operation.get("parameters", [])})
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        return json.dumps(_properties(schema, spec))

    def _action(self, group, action_name):
        if group not in self.groups:
            raise ValueError(f"Unknown group: {group}")
        action = GROUPS[group]["actions"].get(action_name)
        if action is None:
            raise ValueError(f"Unknown action '{action_name}'. Choose from: {', '.join(GROUPS[group]['actions'])}")
        return action

    async def _run(self, group: str, arguments: dict) -> dict:
        action = self._action(group, arguments.get("action"))
        params = arguments.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        client = await self._http()
        if action.kind == "form":
            names, payloads = self._read_inputs(action, arguments)
            files = [("file" if action.files == "file" else "files", (n, p, "application/octet-stream"))
                     for n, p in zip(names, payloads)]
            data = {key: _form_value(value) for key, value in params.items()}
            response = await client.request(action.method, action.path, files=files, data=data)
        elif action.kind == "json":
            response = await client.request(action.method, action.path, json=params)
        elif action.kind == "query":
            response = await client.request(action.method, action.path, params=params)
        else:
            response = await client.request(action.method, action.path)
        return self._render(response, action)

    def _read_inputs(self, action, arguments):
        if action.files == "file":
            values = [arguments.get("file")]
        else:
            values = arguments.get("files")
            if not isinstance(values, list) or not values:
                raise ValueError("files must be a non-empty list of paths")
        loaded = [self.policy.read_file(value) for value in values]
        return [name for name, _ in loaded], [content for _, content in loaded]

    # Responses ----------------------------------------------------------
    def _render(self, response, action) -> dict:
        media_type = response.headers.get("content-type", "").split(";")[0].strip()
        if response.status_code >= 400:
            detail = response.json().get("detail") if media_type == "application/json" else response.text
            return _error(f"HTTP {response.status_code}: {detail}")
        if media_type == "application/json":
            body = response.json()
            if action.mask_matches:
                body = _mask_matches(body)
            text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            return self._inline_or_file(text, ".json", "result")
        if media_type.startswith("text/"):
            suffix = ".md" if media_type == "text/markdown" else ".csv" if media_type == "text/csv" else ".txt"
            return self._inline_or_file(response.text, suffix, "result")
        saved = self.policy.write_file(_attachment_name(response), response.content, "result.bin")
        return _text(json.dumps({"saved": str(saved), "bytes": len(response.content)}))

    def _inline_or_file(self, text: str, suffix: str, fallback: str) -> dict:
        if len(text) <= MAX_INLINE_CHARS:
            return _text(text)
        saved = self.policy.write_file(fallback + suffix, text.encode("utf-8"), fallback + suffix)
        return _text(json.dumps({"saved": str(saved), "chars": len(text), "preview": text[:500]}))


def _text(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}]}


def _error(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}], "isError": True}


def _mask_hint(value) -> str:
    text = value if isinstance(value, str) else ""
    visible = min(4, len(text) // 4)
    return "•" * (len(text) - visible) + (text[-visible:] if visible else "")


def _mask_matches(body):
    """Agents see what was found and where, never the raw personal data itself."""
    if isinstance(body, dict) and isinstance(body.get("matches"), list):
        body = {**body, "matches": [
            {key: _mask_hint(item[key]) if key == "value" else item[key] for key in item}
            if isinstance(item, dict) else item
            for item in body["matches"]
        ]}
    return body


def _form_value(value) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _attachment_name(response) -> str:
    message = Message()
    message["content-disposition"] = response.headers.get("content-disposition", "")
    return message.get_filename() or re.sub(r"\W+", "_", response.headers.get("content-type", "result"))


def _summarize(schema: dict) -> dict:
    keys = ("type", "enum", "minimum", "maximum", "minLength", "maxLength", "default", "description")
    options = schema.get("anyOf")
    if options and "type" not in schema:
        schema = next((o for o in options if o.get("type") != "null"), schema)
    return {key: schema[key] for key in keys if key in schema}


def _properties(schema: dict, spec: dict) -> dict:
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    required = set(schema.get("required", []))
    return {
        name: {**_summarize(prop), **({"required": True} if name in required else {})}
        for name, prop in schema.get("properties", {}).items()
    }


def serve(environment, stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    server = OfficeKitMcpServer(effective_environment(environment))
    loop = asyncio.new_event_loop()
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            reply = loop.run_until_complete(server.handle(message)) if isinstance(message, dict) else None
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            stdout.flush()
