"""Print the live merged tool catalogue as JSON for Node tests and doc scripts.

Usage: ``python3 -m officekit.tool_catalog --json``
"""

import json
import sys

from officekit.engines.engine_comms import TOOL_REGISTRY
from officekit.tool_catalog import SLICES


def catalogue_payload():
    return {
        "tools": TOOL_REGISTRY,
        "slices": {module.__name__.rsplit(".", 1)[-1]: [tool["id"] for tool in module.TOOLS] for module in SLICES},
    }


def main(argv):
    if argv != ["--json"]:
        sys.stderr.write("usage: python3 -m officekit.tool_catalog --json\n")
        return 2
    sys.stdout.write(json.dumps(catalogue_payload(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
