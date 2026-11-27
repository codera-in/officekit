"""Development launcher for the agent tools: `python mcp_main.py` serves MCP over stdio,
`python mcp_main.py call ...` / `help ...` run the CLI. Packaged builds use the sidecar's
`--agent-mcp` and `--agent-cli` flags (see backend_main.py)."""

import os
import sys

from officekit.mcp.cli import run
from officekit.mcp.server import serve


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(run(sys.argv[1:], os.environ))
    serve(os.environ)
