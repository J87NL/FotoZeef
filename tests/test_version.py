from __future__ import annotations

import re
import tomllib
from pathlib import Path

from fotozeef.appinfo import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_every_copy_of_the_version_agrees() -> None:
    """A release tag is checked against pyproject.toml; the other copies must follow it."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8-sig")
    match = re.search(r'^#define AppVersion "([^"]+)"', installer, re.MULTILINE)

    manifest = (ROOT / "packaging" / "windows" / "fotozeef.manifest").read_text(encoding="utf-8")
    identity = re.search(r'name="nl\.j87\.FotoZeef" version="([^"]+)\.0"', manifest)
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = next(item["version"] for item in lock["package"] if item["name"] == "fotozeef")

    assert match is not None
    assert identity is not None
    version = project["project"]["version"]
    assert version == APP_VERSION == match.group(1) == identity.group(1) == locked


def test_a_newer_database_is_reported_not_crashed_on(tmp_path: Path, monkeypatch) -> None:
    """Installing an older FotoZeef over a newer one's data must explain itself."""
    import sqlite3

    from fotozeef import app as app_module
    from fotozeef.core.db import SCHEMA_VERSION, NewerDatabaseError

    path = tmp_path / "newer.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()
    shown: list[bool] = []
    monkeypatch.setattr(app_module, "database_path", lambda: path)
    monkeypatch.setattr(app_module, "build_application", lambda _argv: None)
    monkeypatch.setattr(app_module, "show_newer_database_message", lambda: shown.append(True))

    assert app_module.main(["fotozeef"]) == 1
    assert shown == [True]

    try:
        app_module.Database(path)
    except NewerDatabaseError as error:
        assert error.found == SCHEMA_VERSION + 1
    else:
        raise AssertionError("a newer schema must be refused")


def test_the_installer_cleans_up_and_refuses_to_downgrade() -> None:
    script = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8-sig")

    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in script
    assert "function InitializeSetup(): Boolean;" in script
    assert "CompareVersions(Installed, '{#AppVersion}') > 0" in script
    app_id = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", script, re.MULTILINE)
    assert app_id is not None
    assert f"{{{app_id.group(1)}}}_is1" in script, "the uninstall key must match the AppId"
