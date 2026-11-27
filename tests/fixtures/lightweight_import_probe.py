import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import officekit.engines.engine_file_converter as engine_file_converter  # noqa: F401
if 'pandas' in sys.modules:
    raise SystemExit('pandas loaded during converter import')

import officekit.engines.engine_parser as engine_parser  # noqa: F401

if 'pandas' in sys.modules:
    raise SystemExit('pandas loaded during statement engine import')
