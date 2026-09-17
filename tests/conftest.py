from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from fotozeef.core.db import Database
from fotozeef.core.library import Library

os.environ["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM") or "offscreen"


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """Keeps QSettings inside the test run: the language choice is persisted."""
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    settings_dir = tmp_path_factory.mktemp("settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(settings_dir))
    QCoreApplication.setOrganizationName("ComfyCoders")
    QCoreApplication.setApplicationName("FotoZeefTests")

    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "state" / "test.sqlite")


@pytest.fixture
def library(db: Database) -> Library:
    return Library(db)


def make_jpeg(
    path: Path,
    captured_at: datetime | None = None,
    size: tuple[int, int] = (64, 48),
    color: tuple[int, int, int] = (200, 120, 60),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    if captured_at is None:
        image.save(path, format="JPEG")
        return path
    exif = image.getexif()
    exif[36867] = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    exif[271] = "Canon"
    exif[272] = "Canon EOS R6"
    image.save(path, format="JPEG", exif=exif)
    return path


@pytest.fixture
def jpeg_factory():
    return make_jpeg
