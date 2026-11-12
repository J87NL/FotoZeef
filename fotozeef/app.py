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
from fotozeef.core.db import Database, NewerDatabaseError
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
    # Offscreen unless asked otherwise: CI also boots the bundle on a real X server.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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

        from fotozeef.ui.sleep_guard import DBusBackend, default_backend

        backend = default_backend()
        if isinstance(backend, DBusBackend):
            try:
                # libQt6DBus links libdbus directly, so the import proves both are there.
                import PySide6.QtDBus  # noqa: F401
            except ImportError as error:
                print(f"selftest failed: QtDBus missing: {error}", file=sys.stderr)
                return 1
        checks.append(f"sleepguard={type(backend).__name__ if backend else 'none'}")

        library = Library(Database(root / "selftest.sqlite"))
        window = MainWindow(library, ThumbnailCache(root / "cache"))
        window.show()
        app.processEvents()
        window.close()
        library.close()
        checks.append("window=ok")

    print(f"{APP_NAME} {APP_VERSION} selftest: " + " ".join(checks))
    return 0


def show_newer_database_message() -> None:
    """An older FotoZeef over a newer one's data: say what to do instead of crashing."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.critical(
        None,
        APP_NAME,
        QCoreApplication.translate(
            "FotoZeef",
            "Your projects were saved by a newer version of FotoZeef than this one ({0}).\n\n"
            "Install the latest version from the releases page to open them. Nothing has been"
            " changed.",
        ).format(APP_VERSION),
    )


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

    try:
        database = Database(database_path())
    except NewerDatabaseError:
        show_newer_database_message()
        return 1
    library = Library(database)
    window = MainWindow(library, ThumbnailCache(cache_dir()))
    window.show()
    window.open_last_project()
    try:
        return app.exec()
    finally:
        library.close()


if __name__ == "__main__":
    raise SystemExit(main())
