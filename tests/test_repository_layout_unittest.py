from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "officekit" / "engines"


class RepositoryLayoutTests(unittest.TestCase):
    def test_engine_modules_are_grouped_in_the_package(self):
        modules = sorted(ENGINE_DIR.glob("engine_*.py"))
        self.assertGreaterEqual(len(modules), 40)
        self.assertTrue((ENGINE_DIR / "__init__.py").is_file())
        self.assertFalse(list(ROOT.glob("engine_*.py")))

    def test_application_entrypoints_remain_at_repository_root(self):
        self.assertTrue((ROOT / "app.py").is_file())
        self.assertTrue((ROOT / "backend_main.py").is_file())
        self.assertTrue((ROOT / "desktop_main.py").is_file())

    def test_benchmark_lives_with_developer_scripts(self):
        self.assertTrue((ROOT / "scripts" / "benchmark_suite.py").is_file())
        self.assertFalse((ROOT / "benchmark_suite.py").exists())


if __name__ == "__main__":
    unittest.main()
