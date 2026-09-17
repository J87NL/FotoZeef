from __future__ import annotations

import logging
import os
import signal
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fotozeef.appinfo import (
    APP_NAME,
    APP_VERSION,
    ICON_PATH,
    SETTINGS_ORGANIZATION,
    cache_dir,
    database_path,
)
from fotozeef.core.db import Database
from fotozeef.core.library import Library
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow
from fotozeef.ui.theme import apply_dark_theme
from fotozeef.ui.translations import install as install_translations


def build_application(argv: list[str]) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setDesktopFileName("fotozeef")
    install_translations(app)
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_dark_theme(app)
    return app


def selftest() -> int:
    """Boots the whole stack offscreen; CI runs this against the packaged builds."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = build_application([APP_NAME])

    from PIL import Image

    from fotozeef.core.imaging import register_codecs
    from fotozeef.core.metadata import read_metadata
    from fotozeef.core.thumbnails import FILMSTRIP_SIZE, ThumbnailRequest, render

    register_codecs()
    checks: list[str] = []
    checks.append(f"heif={'HEIF' in Image.OPEN}")
    try:
        import rawpy

        checks.append(f"rawpy={rawpy.libraw_version}")
    except Exception as error:
        print(f"selftest failed: rawpy unusable: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sample = root / "sample.jpg"
        Image.new("RGB", (400, 300), (120, 80, 40)).save(sample)
        stat = sample.stat()
        payload = render(
            ThumbnailRequest(
                photo_id=1,
                path=sample,
                mtime=stat.st_mtime,
                file_size=stat.st_size,
                target=FILMSTRIP_SIZE,
            )
        )
        checks.append(f"thumbnail={len(payload)}B")
        checks.append(f"capture={read_metadata(sample, stat.st_mtime).capture_source}")

        library = Library(Database(root / "selftest.sqlite"))
        window = MainWindow(library, ThumbnailCache(root / "cache"))
        window.show()
        app.processEvents()
        window.close()
        library.close()
        checks.append("window=ok")

    print(f"{APP_NAME} {APP_VERSION} selftest: " + " ".join(checks))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv)
    logging.basicConfig(
        level=os.environ.get("FOTOZEEF_LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    if "--version" in arguments:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--selftest" in arguments:
        return selftest()

    app = build_application(arguments)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    library = Library(Database(database_path()))
    window = MainWindow(library, ThumbnailCache(cache_dir()))
    window.show()
    window.open_last_project()
    try:
        return app.exec()
    finally:
        library.close()


if __name__ == "__main__":
    raise SystemExit(main())
