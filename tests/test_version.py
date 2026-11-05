from __future__ import annotations

import re
import tomllib
from pathlib import Path

from fotozeef.appinfo import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_every_copy_of_the_version_agrees() -> None:
    """A release tag is checked against pyproject.toml; the other copies must follow it."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    match = re.search(r'^#define AppVersion "([^"]+)"', installer, re.MULTILINE)

    assert match is not None
    assert project["project"]["version"] == APP_VERSION == match.group(1)
