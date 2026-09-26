import contextlib
import importlib.util
import io
from pathlib import Path
import re
import unittest

import maf
from maf import cli

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("changelog", ROOT / "scripts" / "changelog.py")
changelog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changelog)


class Version(unittest.TestCase):
    def test_changelog_leads_with_the_package_version(self):
        entries = changelog.versions((ROOT / "CHANGELOG.md").read_text())
        self.assertRegex(maf.__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(entries[0][0], maf.__version__)
        numbers = [tuple(map(int, version.split("."))) for version, _ in entries]
        self.assertEqual(numbers, sorted(set(numbers), reverse=True))
        self.assertTrue(all(body for _, body in entries))
        self.assertTrue(re.search(rf"^## \[{re.escape(maf.__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                                  (ROOT / "CHANGELOG.md").read_text(), re.M))
        self.assertEqual(changelog.section("v" + maf.__version__), entries[0][1])
        with self.assertRaises(SystemExit):
            changelog.section("v99.0.0")

    def test_cli_prints_version(self):
        output = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(output):
            cli.main(["--version"])
        self.assertIn(f"multiple-agents-flow {maf.__version__}", output.getvalue())


if __name__ == "__main__":
    unittest.main()
