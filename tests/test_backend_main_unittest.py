import pytest

import backend_main


def test_backend_entry_dispatches_packaged_media_cli_without_starting_api(capsys):
    with pytest.raises(SystemExit) as stopped:
        backend_main.main(["--media-cli", "--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "Run typed local media operations." in output
    assert "pipeline" in output


def test_backend_entry_dispatches_agent_cli_without_starting_api(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OFFICEKIT_AGENT_SETTINGS", str(tmp_path / "none.json"))
    exit_code = backend_main.main(["--agent-cli", "call", "calc", "math-eval", "--params", '{"expression":"6*7"}'])
    assert exit_code == 0
    assert '"result":42' in capsys.readouterr().out


def test_backend_entry_dispatches_agent_mcp_over_stdio(monkeypatch):
    served = []
    monkeypatch.setattr("officekit.mcp.server.serve", lambda environment: served.append(environment))
    assert backend_main.main(["--agent-mcp"]) == 0
    assert len(served) == 1
