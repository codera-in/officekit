"""Command-line mode for agent skills: same tools, same guards as the MCP server.

    officekit call pdf text --file report.pdf --params '{"page_ranges": "1-2"}'
    officekit call calc loan-emi --params '{"principal": 100000, ...}'
    officekit help pdf merge
"""

import argparse
import asyncio
import json
import sys

from officekit.mcp.registry import GROUPS
from officekit.mcp.server import PREFIX, OfficeKitMcpServer
from officekit.mcp.settings import effective_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="officekit", description="Run OfficeKit tools from the command line.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("call", "help"):
        sub = commands.add_parser(name)
        sub.add_argument("group", choices=list(GROUPS))
        sub.add_argument("action")
        if name == "call":
            sub.add_argument("--file", action="append", default=[], help="Input path; repeat for several files.")
            sub.add_argument("--params", default="{}", help="JSON object of action parameters.")
    return parser


def run(argv, environment, stdout=None, stderr=None) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    server = OfficeKitMcpServer(effective_environment(environment))
    if args.command == "help":
        result = asyncio.run(server.call_tool(f"{PREFIX}help", {"group": args.group, "action": args.action}))
    else:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            stderr.write("--params must be a JSON object\n")
            return 2
        arguments = {"action": args.action, "params": params}
        if len(args.file) == 1:
            arguments["file"] = args.file[0]
        if args.file:
            arguments["files"] = args.file
        result = asyncio.run(server.call_tool(f"{PREFIX}{args.group}", arguments))
    stream = stderr if result.get("isError") else stdout
    stream.write(result["content"][0]["text"] + "\n")
    return 1 if result.get("isError") else 0
