from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QSettings, QTranslator

from fotozeef.appinfo import I18N_DIR

LANGUAGE_ENV = "FOTOZEEF_LANG"
SETTINGS_KEY = "ui/language"
SOURCE_LANGUAGE = "en"

ENDONYMS = {
    "en": "English",
    "nl": "Nederlands",
}

_installed: list[QTranslator] = []


def available_languages() -> list[tuple[str, str]]:
    """Source language first, then every compiled catalogue that is shipped."""
    codes = [SOURCE_LANGUAGE]
    codes += sorted(
        path.stem.removeprefix("fotozeef_")
        for path in I18N_DIR.glob("fotozeef_*.qm")
        if path.stem.removeprefix("fotozeef_") != SOURCE_LANGUAGE
    )
    return [(code, ENDONYMS.get(code, code)) for code in codes]


def saved_language() -> str | None:
    value = QSettings().value(SETTINGS_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def save_language(language: str) -> None:
    QSettings().setValue(SETTINGS_KEY, language)


def resolve_language() -> str:
    override = os.environ.get(LANGUAGE_ENV, "").strip()
    if override:
        return override.split("_")[0].lower()
    stored = saved_language()
    if stored:
        return stored
    return QLocale.system().name().split("_")[0].lower()


def current_language() -> str:
    return _current


def install(app: QCoreApplication, language: str | None = None) -> str:
    """Swaps the active catalogue; widgets retranslate themselves afterwards."""
    global _current
    chosen = (language or resolve_language()).lower()

    for translator in _installed:
        app.removeTranslator(translator)
    _installed.clear()

    if chosen != SOURCE_LANGUAGE:
        catalogue = I18N_DIR / f"fotozeef_{chosen}.qm"
        translator = QTranslator()
        if catalogue.is_file() and translator.load(str(catalogue)):
            app.installTranslator(translator)
            _installed.append(translator)
        else:
            chosen = SOURCE_LANGUAGE

    qt_translator = QTranslator()
    qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if chosen != SOURCE_LANGUAGE and qt_translator.load(f"qtbase_{chosen}", qt_path):
        app.installTranslator(qt_translator)
        _installed.append(qt_translator)

    _current = chosen
    return chosen


_current = SOURCE_LANGUAGE
