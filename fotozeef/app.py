from __future__ import annotations

import signal
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fotozeef.appinfo import APP_NAME, APP_VERSION, cache_dir, database_path
from fotozeef.core.db import Database
from fotozeef.core.library import Library
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow
from fotozeef.ui.theme import apply_dark_theme


def build_application(argv: list[str]) -> QApplication:
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("ComfyCoders")
    apply_dark_theme(app)
    return app


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv)
    app = build_application(arguments)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    library = Library(Database(database_path()))
    window = MainWindow(library, ThumbnailCache(cache_dir()))
    window.show()
    window.open_last_project()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
