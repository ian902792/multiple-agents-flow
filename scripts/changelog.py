"""Print one version's section of CHANGELOG.md, for release notes: python3 scripts/changelog.py v0.2.0"""
from pathlib import Path
import re
import sys

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def versions(text):
    """(version, body) for each '## [X.Y.Z] - date' section, newest first."""
    parts = re.split(r"^## \[(\d+\.\d+\.\d+)\][^\n]*\n", text, flags=re.M)
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def section(version):
    version = version.removeprefix("v")
    body = dict(versions(CHANGELOG.read_text())).get(version)
    if body is None:
        raise SystemExit(f"CHANGELOG.md has no section for {version}.")
    return body


if __name__ == "__main__":
    print(section(sys.argv[1]))
