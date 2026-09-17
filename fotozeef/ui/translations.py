from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from fotozeef.appinfo import I18N_DIR

LANGUAGE_ENV = "FOTOZEEF_LANG"
SOURCE_LANGUAGE = "en"

_held: list[QTranslator] = []


def preferred_language() -> str:
    override = os.environ.get(LANGUAGE_ENV, "").strip()
    if override:
        return override.split("_")[0].lower()
    return QLocale.system().name().split("_")[0].lower()


def install(app: QCoreApplication, language: str | None = None) -> str:
    """Loads the catalogue for the chosen language; English is the source text."""
    chosen = (language or preferred_language()).lower()
    if chosen == SOURCE_LANGUAGE:
        return SOURCE_LANGUAGE

    catalogue = I18N_DIR / f"fotozeef_{chosen}.qm"
    if not catalogue.is_file():
        return SOURCE_LANGUAGE

    translator = QTranslator()
    if not translator.load(str(catalogue)):
        return SOURCE_LANGUAGE
    app.installTranslator(translator)
    _held.append(translator)

    qt_translator = QTranslator()
    qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load(f"qtbase_{chosen}", qt_path):
        app.installTranslator(qt_translator)
        _held.append(qt_translator)
    return chosen
