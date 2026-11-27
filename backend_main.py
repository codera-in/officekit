"""Entrypoint for the bundled OfficeKit local API sidecar."""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()

if sys.argv[1:2] not in (["--media-cli"], ["--media-mcp"], ["--agent-cli"], ["--agent-mcp"]):
    import uvicorn

    from app import app
    from officekit.engines.engine_api_security import load_sidecar_api_token

def sidecar_api_port(environment=None):
    value = (os.environ if environment is None else environment).get("OFFICEKIT_API_PORT", "8000")
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("OFFICEKIT_API_PORT must be a decimal TCP port")
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("OFFICEKIT_API_PORT must be between 1 and 65535")
    return port


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--media-cli"]:
        from officekit.media_cli import run

        return run(arguments[1:])
    if arguments[:1] == ["--media-mcp"]:
        from officekit.media_mcp import main as run_mcp

        run_mcp()
        return 0
    if arguments[:1] == ["--agent-cli"]:
        from officekit.mcp.cli import run as run_agent_cli

        return run_agent_cli(arguments[1:], os.environ)
    if arguments[:1] == ["--agent-mcp"]:
        from officekit.mcp.server import serve

        serve(os.environ)
        return 0
    return None


if __name__ == "__main__":
    exit_code = main()
    if exit_code is None:
        load_sidecar_api_token(os.environ)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=sidecar_api_port(),
            reload=False,
            log_level="warning",
            access_log=False,
        )
    else:
        raise SystemExit(exit_code)
