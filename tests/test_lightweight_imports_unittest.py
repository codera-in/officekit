import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


class LightweightImportTests(unittest.TestCase):
    def test_converter_and_statement_engines_do_not_load_pandas_at_app_startup(self):
        if importlib.util.find_spec('PIL') is None:
            self.skipTest('Pillow is required to import these app engines')
        probe = Path(__file__).parent / 'fixtures' / 'lightweight_import_probe.py'
        result = subprocess.run(
            [sys.executable, str(probe)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
