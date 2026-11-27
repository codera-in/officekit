import asyncio
import io
import json
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from officekit.mcp.paths import PathPolicy, PathPolicyError
from officekit.mcp.server import OfficeKitMcpServer, enabled_groups, tool_definitions
from officekit.mcp.registry import GROUPS


def make_server(tmp_path, **env):
    allowed = tmp_path / "in"
    allowed.mkdir(exist_ok=True)
    environment = {
        "OFFICEKIT_MCP_ALLOWED_DIRS": str(allowed),
        "OFFICEKIT_MCP_OUTPUT_DIR": str(tmp_path / "out"),
        **env,
    }
    return OfficeKitMcpServer(environment), allowed


def call(server, name, **arguments):
    return asyncio.run(server.call_tool(name, arguments))


def text_of(result):
    return result["content"][0]["text"]


def write_pdf(path: Path, pages):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for label in pages:
        pdf.drawString(72, 720, label)
        pdf.showPage()
    pdf.save()
    path.write_bytes(buffer.getvalue())


def test_initialize_and_list_tools_without_importing_the_app(tmp_path):
    server, _ = make_server(tmp_path)
    reply = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}))
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    listed = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == ["officekit_help", *(f"officekit_{group}" for group in GROUPS)]
    assert asyncio.run(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None
    unknown = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}))
    assert unknown["error"]["code"] == -32601


def test_tool_groups_can_be_limited_and_unknown_groups_fail():
    assert enabled_groups({"OFFICEKIT_MCP_TOOLS": "pdf, calc"}) == ["pdf", "calc"]
    assert enabled_groups({}) == list(GROUPS)
    with pytest.raises(ValueError):
        enabled_groups({"OFFICEKIT_MCP_TOOLS": "pdf,rm"})


def test_tool_definitions_stay_within_the_token_budget():
    serialized = json.dumps(tool_definitions(list(GROUPS)), separators=(",", ":"))
    # ~4 characters per token; the budget protects agents' context windows.
    assert len(serialized) / 4 < 1500


def test_calculator_runs_in_process_with_api_validation(tmp_path):
    server, _ = make_server(tmp_path)
    ok = call(server, "officekit_calc", action="loan-emi", params={"principal": 100000, "annual_interest_rate": 8, "tenure_years": 5})
    assert "isError" not in ok and "emi" in text_of(ok).lower()
    bad = call(server, "officekit_calc", action="loan-emi", params={"principal": -1, "annual_interest_rate": 8, "tenure_years": 5})
    assert bad["isError"] and "422" in text_of(bad)


def test_help_describes_json_and_form_actions(tmp_path):
    server, _ = make_server(tmp_path)
    described = json.loads(text_of(call(server, "officekit_help", group="calc", action="units-convert")))
    assert described["category"]["enum"][0] == "length"
    assert "page_ranges" in text_of(call(server, "officekit_help", group="pdf", action="text"))
    assert call(server, "officekit_help", group="pdf", action="nope")["isError"]


def test_pdf_text_and_merge_write_outputs_without_overwriting(tmp_path):
    server, allowed = make_server(tmp_path)
    first, second = allowed / "a.pdf", allowed / "b.pdf"
    write_pdf(first, ["alpha page"])
    write_pdf(second, ["beta page"])

    extracted = call(server, "officekit_pdf", action="text", file=str(first))
    assert "alpha page" in text_of(extracted)

    merged = call(server, "officekit_pdf", action="merge", files=[str(first), str(second)])
    saved = Path(json.loads(text_of(merged))["saved"])
    assert saved.parent == (tmp_path / "out").resolve() and saved.read_bytes().startswith(b"%PDF")
    again = Path(json.loads(text_of(call(server, "officekit_pdf", action="merge", files=[str(first), str(second)])))["saved"])
    assert again != saved and saved.exists() and again.exists()


def test_paths_outside_allowed_folders_and_hidden_files_are_rejected(tmp_path):
    server, allowed = make_server(tmp_path)
    outside = tmp_path / "secret.pdf"
    write_pdf(outside, ["x"])
    rejected = call(server, "officekit_pdf", action="text", file=str(outside))
    assert rejected["isError"] and "outside the allowed folders" in text_of(rejected)

    hidden = allowed / ".private.pdf"
    write_pdf(hidden, ["x"])
    assert call(server, "officekit_pdf", action="text", file=str(hidden))["isError"]

    link = allowed / "link.pdf"
    link.symlink_to(outside)
    assert call(server, "officekit_pdf", action="text", file=str(link))["isError"]


def test_invalid_arguments_return_tool_errors(tmp_path):
    server, allowed = make_server(tmp_path)
    assert call(server, "officekit_pdf", action="nope")["isError"]
    assert call(server, "officekit_pdf", action="merge", files=[])["isError"]
    assert call(server, "officekit_calc", action="loan-emi", params="x")["isError"]
    assert call(server, "officekit_missing")["isError"]
    limited = OfficeKitMcpServer({"OFFICEKIT_MCP_TOOLS": "calc"})
    assert asyncio.run(limited.call_tool("officekit_pdf", {"action": "text"}))["isError"]


def test_every_registered_action_targets_a_route_the_app_serves():
    import app as api

    served = {(method, route.path) for route in api.app.routes if hasattr(route, "methods") for method in route.methods}
    for group in GROUPS.values():
        for name, action in group["actions"].items():
            assert (action.method, action.path) in served, name


def test_clipboard_history_and_other_sensitive_data_are_never_exposed(tmp_path):
    from officekit.mcp.registry import Action, assert_no_sensitive_actions

    assert_no_sensitive_actions()  # the shipped registry is clean
    for path in ("/api/clipboard/items", "/api/clipboard/snippets", "/api/dictate/cleanup", "/api/history"):
        bad = {"x": {"description": "", "actions": {"leak": Action("GET", path, "none")}}}
        with pytest.raises(ValueError):
            assert_no_sensitive_actions(bad)
    server, _ = make_server(tmp_path)
    assert call(server, "officekit_clipboard")["isError"]
    assert not any("clipboard" in tool["name"] for tool in tool_definitions(server.groups))


def test_pii_scan_never_returns_raw_personal_data_but_redact_still_works(tmp_path):
    server, allowed = make_server(tmp_path)
    sample = allowed / "note.txt"
    sample.write_text("Mail jane.doe@example.com card 4111 1111 1111 1111.")
    scan = call(server, "officekit_privacy", action="pii-scan", file=str(sample))
    body = text_of(scan)
    assert "jane.doe@example.com" not in body and "4111 1111 1111 1111" not in body
    matches = json.loads(body)["matches"]
    assert {m["type"] for m in matches} >= {"email", "card"} and all("•" in m["value"] for m in matches)

    ids = json.dumps([m["id"] for m in matches])
    redacted = call(server, "officekit_privacy", action="pii-redact", file=str(sample), params={"selected_ids": ids, "mode": "redact"})
    assert "isError" not in redacted
    assert "jane.doe@example.com" not in text_of(redacted) and "4111" not in text_of(redacted)


def test_secret_generators_are_not_offered_to_agents():
    assert set(GROUPS["dev"]["actions"]) == {"devtools", "hashes"}
    assert not any("/crypto/password" in a.path or "/crypto/passphrase" in a.path
                   for group in GROUPS.values() for a in group["actions"].values())


def test_path_policy_defaults_are_user_folders_and_output_dir(tmp_path):
    policy = PathPolicy({}, cwd=tmp_path, home=tmp_path / "home")
    assert (tmp_path / "home" / "OfficeKit Output").resolve() in policy.roots
    assert (tmp_path / "home" / "Downloads").resolve() in policy.roots
    with pytest.raises(PathPolicyError):
        policy.read_file("")
