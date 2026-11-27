import io
import json
from pathlib import Path

import pytest

from officekit.mcp.cli import run
from tests.mcp_server_unittest import write_pdf


def environment(tmp_path):
    allowed = tmp_path / "in"
    allowed.mkdir()
    return allowed, {"OFFICEKIT_MCP_ALLOWED_DIRS": str(allowed), "OFFICEKIT_MCP_OUTPUT_DIR": str(tmp_path / "out")}


def invoke(argv, env):
    out, err = io.StringIO(), io.StringIO()
    return run(argv, env, out, err), out.getvalue(), err.getvalue()


def test_calc_and_help_commands(tmp_path):
    _, env = environment(tmp_path)
    code, out, _ = invoke(["call", "calc", "loan-emi", "--params", json.dumps({"principal": 100000, "annual_interest_rate": 8, "tenure_years": 5})], env)
    assert code == 0 and "emi" in out.lower()
    code, out, _ = invoke(["help", "pdf", "text"], env)
    assert code == 0 and "page_ranges" in out


def test_pdf_commands_use_the_same_folder_guards(tmp_path):
    allowed, env = environment(tmp_path)
    first, second = allowed / "a.pdf", allowed / "b.pdf"
    write_pdf(first, ["alpha page"])
    write_pdf(second, ["beta page"])
    code, out, _ = invoke(["call", "pdf", "text", "--file", str(first)], env)
    assert code == 0 and "alpha page" in out
    code, out, _ = invoke(["call", "pdf", "merge", "--file", str(first), "--file", str(second)], env)
    assert code == 0 and Path(json.loads(out)["saved"]).read_bytes().startswith(b"%PDF")

    outside = tmp_path / "secret.pdf"
    write_pdf(outside, ["x"])
    code, out, err = invoke(["call", "pdf", "text", "--file", str(outside)], env)
    assert code == 1 and out == "" and "outside the allowed folders" in err


def test_bad_params_and_groups_fail_cleanly(tmp_path):
    _, env = environment(tmp_path)
    code, _, err = invoke(["call", "calc", "loan-emi", "--params", "{nope"], env)
    assert code == 2 and "JSON" in err
    code, _, err = invoke(["call", "calc", "nope"], env)
    assert code == 1 and "Unknown action" in err
    with pytest.raises(SystemExit):
        invoke(["call", "clipboard", "items"], env)
